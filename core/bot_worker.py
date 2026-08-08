import threading
import time
import traceback
from typing import Callable, Dict, Any, Optional

import MetaTrader5 as mt5
import pandas as pd

from core.connector import check_account_safety, check_algo_trading_enabled
from core.strategy import SimpleTrendStrategy
from core.executor import OrderExecutor
from core.risk_manager import RiskManager
from core.data_loader import get_historical_data

TIMEFRAME_SECONDS_MAP: Dict[int, int] = {
    mt5.TIMEFRAME_M1: 60,
    mt5.TIMEFRAME_M5: 300,
    mt5.TIMEFRAME_M15: 900,
    mt5.TIMEFRAME_M30: 1800,
    mt5.TIMEFRAME_H1: 3600,
    mt5.TIMEFRAME_H4: 14400,
    mt5.TIMEFRAME_D1: 86400,
}


def calculate_sleep_seconds(timeframe_seconds: int) -> float:
    """Calcula el tiempo exacto restante hasta el cierre de la vela actual + 1s extra de margen."""
    current_time: float = time.time()
    elapsed: float = current_time % timeframe_seconds
    return (timeframe_seconds - elapsed) + 1.0


class SymbolWorker(threading.Thread):
    """
    Hilo de ejecución independiente por cada par de divisas.
    Analiza el mercado en segundo plano ejecutando la estrategia al cierre de vela.
    """
    def __init__(
        self,
        symbol: str,
        params: Dict[str, Any],
        log_callback: Callable[[str, str, str], None],
        stop_event: threading.Event
    ) -> None:
        super().__init__(daemon=True)
        self.symbol = symbol
        self.params: Dict[str, Any] = params
        self.log_callback = log_callback
        self.stop_event = stop_event

        # 1. Instanciar primero los gestores y la estrategia
        self.risk_mgr = RiskManager()
        self.strategy = SimpleTrendStrategy()  # 👈 1º Crear la estrategia aquí

        # 2. Ahora sí instanciar OrderExecutor usando self.strategy
        self.executor = OrderExecutor(
            symbol=self.symbol,
            strategy_name=self.strategy.__class__.__name__,  # 👈 ¡Ahora sí existe!
            log_callback=self._log
        )

        self.executor = OrderExecutor(
            symbol=self.symbol,
            strategy_name=self.strategy.__class__.__name__,  # 👈 Pasará "SimpleTrendStrategy" (que sí es un string)
            log_callback=self.log_callback
        )
        self.risk_mgr: RiskManager = RiskManager()
        self.strategy: SimpleTrendStrategy = SimpleTrendStrategy(symbol=self.symbol)

    def run(self) -> None:
        timeframe_val: int = int(self.params.get("timeframe", mt5.TIMEFRAME_M1))
        timeframe_str: str = str(self.params.get("timeframe_str", "M1"))
        tf_seconds: int = TIMEFRAME_SECONDS_MAP.get(timeframe_val, 60)
        test_mode: bool = bool(self.params.get("test_mode", False))
        sl_pips: float = float(self.params.get("sl_pips", 15.0))
        tp_pips: float = float(self.params.get("tp_pips", 30.0))

        mode_str: str = "MODO TEST (BUY Forzado)" if test_mode else "Estrategia Real (MA+RSI)"
        self._log(f"Hilo de monitoreo iniciado para {self.symbol} ({timeframe_str} | {mode_str}).", "INFO")

        first_run: bool = True

        while not self.stop_event.is_set():
            try:
                if not first_run:
                    sleep_needed: float = calculate_sleep_seconds(tf_seconds)
                    self._log(f"⏱️ Esperando cierre de vela {timeframe_str} ({sleep_needed:.1f}s)...", "INFO")

                    sleep_end: float = time.time() + sleep_needed
                    while time.time() < sleep_end and not self.stop_event.is_set():
                        time.sleep(1.0)

                    if self.stop_event.is_set():
                        break

                first_run = False

                # 1. Validaciones de seguridad previas
                if not check_account_safety():
                    self._log("Margen o equidad en niveles críticos. Pausando ejecuciones.", "WARN")
                    time.sleep(10)
                    continue

                if not check_algo_trading_enabled():
                    self._log("AlgoTrading desactivado en la terminal MT5.", "ERROR")
                    time.sleep(10)
                    continue
                # 1.1 Verificar estado del Mercado para el Símbolo
                symbol_info = mt5.symbol_info(self.symbol)
                if symbol_info is None:
                    self._log(f"⚠️ No se pudo obtener información del símbolo {self.symbol}.", "WARN")
                    time.sleep(5)
                    continue

                # trade_mode: 0 = Disabled, 1 = LongOnly, 2 = ShortOnly, 3 = CloseOnly, 4 = Full Access
                if symbol_info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
                    self._log(
                        f"⛔ MERCADO CERRADO / FUERA DE HORARIO: El activo {self.symbol} "
                        f"no permite operaciones en este momento. Operación cancelada.",
                        "WARN"
                    )
                    # Pausamos el hilo o pasamos al siguiente ciclo
                    time.sleep(10)
                    continue

                # 2. Obtener datos de mercado
                df: Optional[pd.DataFrame] = get_historical_data(self.symbol, timeframe_val, 50)
                if df is None or len(df) == 0:
                    self._log(f"⚠️ No se pudieron obtener datos de mercado ({timeframe_str}) para {self.symbol}.", "WARN")
                else:
                    positions = mt5.positions_get(symbol=self.symbol)
                    has_open_position: bool = positions is not None and len(positions) > 0

                    if test_mode:
                        signal: str = "BUY"
                        self._log(f"🧪 [MODO TEST] Señal FORZADA generada: {signal}", "WARN")
                    else:
                        signal = self.strategy.generate_signal(df)
                        self._log(f"📡 Señal obtenida ({self.symbol} - {timeframe_str}): {signal}", "INFO")

                    # 3. Gestionar posiciones abiertas
                    self.executor.manage_open_positions(current_signal=signal)

                    # 4. Evaluación para NUEVA Entrada
                    if has_open_position:
                        self._log(f"⏳ Posición abierta existente en {self.symbol}. Omitiendo nueva entrada.", "INFO")
                    elif signal in ["BUY", "SELL"]:
                        acc_info = mt5.account_info()
                        balance: float = acc_info.balance if acc_info else 0.0
                        lot: float = self.risk_mgr.calculate_position_size(balance, sl_pips)

                        is_valid, msg = self.risk_mgr.validate_new_trade(self.symbol, lot)
                        if not is_valid:
                            self._log(f"🛑 Riesgo rechazó entrada: {msg}", "WARN")
                        else:
                            ticket = self.executor.send_order(
                                signal=signal,
                                volume=lot,
                                sl_pips=sl_pips,
                                tp_pips=tp_pips
                            )
                            if ticket:
                                self._log(f"✅ ¡ORDEN {signal} EJECUTADA EN MT5! | Ticket #{ticket} | Lot: {lot}", "SUCCESS")
                            else:
                                self._log(f"❌ Error al ejecutar orden {signal} en MT5.", "ERROR")

            except Exception as e:
                # Capturar la pila de llamadas completa (Traceback)
                error_trace = traceback.format_exc()
                self._log(
                    f"❌ Exception en loop de {self.symbol} ({type(e).__name__}): {e}\n"
                    f"🔍 Detalle del Traceback:\n{error_trace}",
                    "ERROR"
                )
                time.sleep(5)

        self._log(f"Hilo de monitoreo para {self.symbol} finalizado.", "WARN")

    def _log(self, message: str, level: str = "INFO") -> None:
        """Envía el log de vuelta a la GUI en la pestaña correspondiente."""
        self.log_callback(self.symbol, message, level)

