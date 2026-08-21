import threading
import time
import traceback
from typing import Callable, Dict, Any, Optional

import MetaTrader5 as mt5
import pandas as pd

from core.connector import check_account_safety, check_algo_trading_enabled
from core.strategy import PriceActionStrategy
from core.executor import OrderExecutor
from core.risk_manager import RiskManager
from core.data_loader import get_historical_data
from core.config_manager import load_config

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
    - Si ya existe una posición abierta: omite análisis de nuevas entradas y ejecuta
      análisis de gestión activa (modificación de SL/TP, Trailing Stop y Cierre Prematuro).
    - Si no existe posición abierta: analiza el mercado buscando confluencias para nuevas entradas.
    """

    def __init__(
        self,
        symbol: str,
        log_callback: Callable[[str, str, str], None],
        stop_event: Optional[threading.Event] = None,
        timeframe: int = mt5.TIMEFRAME_M1,
        test_mode: bool = False,
        risk_pct: float = 0.01,
        lot: float = 0.01,
    ) -> None:
        super().__init__(daemon=True)
        self.symbol = symbol
        self.log_callback = log_callback
        self.stop_event = stop_event or threading.Event()
        self.timeframe = timeframe
        self.test_mode = test_mode
        self.risk_pct = risk_pct
        self.lot = lot

        self.strategy = PriceActionStrategy(
            symbol=self.symbol,
            logger=lambda msg, lvl="INFO": self._log(msg, lvl)
        )
        self.executor = OrderExecutor(
            symbol=self.symbol,
            log_callback=self.log_callback
        )
        self.risk_manager = RiskManager()

    def run(self) -> None:
        self._log(f"Iniciando monitoreo para {self.symbol}...", "INFO")

        while not self.stop_event.is_set():
            try:
                # 1. Obtener datos según la temporalidad configurada para este símbolo
                df = get_historical_data(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    rates_count=300,
                    log_callback=self.log_callback
                )

                if df is None or df.empty:
                    time.sleep(3)
                    continue

                # 2. Verificar si ya existe al menos una posición abierta en este par
                open_positions = mt5.positions_get(symbol=self.symbol)

                if open_positions and len(open_positions) > 0:
                    # 🟢 RAMA A: POSICIÓN ABIERTA ACTIVA ➔ GESTIÓN DE SL/TP Y CIERRE PREMATURO
                    for pos in open_positions:
                        pos_type_str = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                        pnl_current = pos.profit + pos.swap
                        self._log(
                            f"🛡️ [POSICIÓN ACTIVA DETECTADA] {self.symbol} #{pos.ticket} ({pos_type_str} {pos.volume} lotes | PnL: ${pnl_current:+.2f}). "
                            f"Omitiendo búsqueda de nuevas entradas. Analizando SL/TP y posibles cierres prematuros...",
                            "INFO"
                        )

                        # Análisis de la posición abierta con la estrategia cuantitativa
                        mgmt_result = self.strategy.analyze_open_position(df=df, position=pos)
                        action = mgmt_result.get("action", "MONITOR")
                        reason = mgmt_result.get("reason", "")

                        self._log(f"🔎 [ANÁLISIS GESTIÓN POSICIÓN] #{pos.ticket} ➔ Acción: {action} | Razón: {reason}", "INFO")

                        # Ejecutar acción recomendada (Cierre prematuro, modificación de SL/TP, Break-Even)
                        self.executor.manage_position_with_strategy(position=pos, management_result=mgmt_result)

                else:
                    # 🟢 RAMA B: NO HAY POSICIONES ABIERTAS ➔ BUSCAR NUEVAS ENTRADAS
                    if self.test_mode:
                        signal = "BUY"
                        signal_data = {"signal": "BUY", "reason": "Modo Test Activo"}
                        self._log(f"🧪 [MODO TEST] Señal forzada BUY en {self.symbol}", "INFO")
                    else:
                        self._log(f"🧠 [ANALIZANDO] Sin órdenes abiertas en {self.symbol}. Evaluando confluencias para nueva entrada...", "INFO")
                        signal_data = self.strategy.generate_signal(df)
                        signal = signal_data.get("signal", "HOLD") if isinstance(signal_data, dict) else str(signal_data)

                    self._log(f"🧠 [RESULTADO ANÁLISIS] {signal_data} - {self.symbol}", "INFO")

                    if signal in ["BUY", "SELL"]:
                        # 🟢 VALIDACIÓN DE FILTRO DE CORRELACIÓN DE PARES (PEARSON)
                        all_open_positions = mt5.positions_get()
                        other_positions = [
                            {
                                "symbol": p.symbol,
                                "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                                "ticket": p.ticket
                            }
                            for p in all_open_positions
                            if p.symbol != self.symbol
                        ] if all_open_positions else []

                        if other_positions and self.strategy.use_correlation_filter:
                            market_data: Dict[str, pd.DataFrame] = {self.symbol: df}
                            rates_needed = max(self.strategy.correlation_window + 10, 60)

                            for pos in other_positions:
                                sym_other = pos["symbol"]
                                if sym_other not in market_data:
                                    df_other = get_historical_data(
                                        symbol=sym_other,
                                        timeframe=self.timeframe,
                                        rates_count=rates_needed
                                    )
                                    if df_other is not None and not df_other.empty:
                                        market_data[sym_other] = df_other

                            is_safe_to_trade, corr_reason = self.strategy.validate_correlation_filter(
                                target_symbol=self.symbol,
                                signal_type=signal,
                                active_positions=other_positions,
                                market_data=market_data
                            )

                            if not is_safe_to_trade:
                                self._log(f"🚫 [ORDEN CANCELADA POR CORRELACIÓN] {corr_reason}", "WARNING")
                                signal = "HOLD"

                    if signal in ["BUY", "SELL"]:
                        acc_info = mt5.account_info()
                        balance = acc_info.balance if acc_info else 0.0

                        sl_pips = self.risk_manager.calculate_sl_pips_from_risk(
                            balance=balance,
                            fixed_lot=self.lot,
                            risk_pct=self.risk_pct,
                            symbol=self.symbol
                        )

                        # Take Profit = 2x Stop Loss (Ratio 1:2)
                        rr_ratio = getattr(self.strategy.config, "risk_reward_ratio", 2.0)
                        tp_pips = round(sl_pips * rr_ratio, 1)

                        # Ejecutar orden con lote, SL y TP calculados
                        resultado = self.executor.send_order(
                            order_type=signal,
                            volume=self.lot,
                            sl_pips=sl_pips,
                            tp_pips=tp_pips
                        )
                        if isinstance(resultado, dict) and not resultado.get("status", False):
                            self._log(f"Error al ejecutar orden: {resultado.get('message', 'Desconocido')}", "ERROR")
                        else:
                            self._log(f"Resultado Orden: {resultado}", "SUCCESS")

            except Exception as e:
                self._log(f"Error en worker {self.symbol}: {e}", "ERROR")

            # Calcular segundos restantes para la siguiente vela
            seconds = TIMEFRAME_SECONDS_MAP.get(self.timeframe, 60)
            sleep_time = calculate_sleep_seconds(seconds)

            # Notificación enviada a la consola de la GUI
            self._log(f"⏳ Próximo análisis de vela en {int(sleep_time)} segundos...", "INFO")

            # Espera interrumpible
            sleep_counter = 0.0
            while sleep_counter < sleep_time and not self.stop_event.is_set():
                time.sleep(1.0)
                sleep_counter += 1.0

    def _log(self, message: str, level: str = "INFO") -> None:
        """Envía el log de vuelta a la GUI en la pestaña correspondiente."""
        self.log_callback(self.symbol, message, level)
