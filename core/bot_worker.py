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
    Analiza el mercado en segundo plano ejecutando la estrategia al cierre de vela.
    """

    def __init__(
        self,
        symbol: str,
        log_callback: Callable[[str, str, str], None],
        stop_event: Optional[threading.Event] = None,
        timeframe: int = mt5.TIMEFRAME_M1,
        test_mode: bool = False,
        risk_pct: float = 0.01,
    ) -> None:
        super().__init__(daemon=True)
        self.symbol = symbol
        self.log_callback = log_callback
        self.stop_event = stop_event or threading.Event()
        self.timeframe = timeframe
        self.test_mode = test_mode
        self.risk_pct = risk_pct

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
                # 1. Obtener datos según la temporalidad del Sidebar
                df = get_historical_data(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    rates_count=100
                )

                if df is None or df.empty:
                    time.sleep(3)
                    continue

                # 2. Evaluar Modo Test o Estrategia Real
                if self.test_mode:
                    signal = "BUY"
                    self._log(f"🧪 [MODO TEST] Señal forzada BUY en {self.symbol}", "INFO")
                else:
                    self._log(f"🧠 [ANALIZANDO] Llamando a generate_signal() para {self.symbol}...", "INFO")
                    signal_data = self.strategy.generate_signal(df)
                    signal = signal_data.get("signal", "HOLD") if isinstance(signal_data, dict) else str(signal_data)

                # 3. Ejecución de la Orden
                self._log(f"🧠 [ANALIZANDO antes de la señal] {signal_data} - {self.symbol}...", "INFO")
                if signal in ["BUY", "SELL"]:
                    positions = mt5.positions_get(symbol=self.symbol)
                    if not positions:
                        # Ejecutar orden
                        resultado = self.executor.send_order(
                            order_type=signal,
                            volume=0.01,
                            sl_pips=20.0
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

            # 🟢 Notificación enviada a la consola de la GUI
            self._log(f"⏳ Próximo análisis de vela en {int(sleep_time)} segundos...", "INFO")

            # Espera interrumpible
            sleep_counter = 0.0
            while sleep_counter < sleep_time and not self.stop_event.is_set():
                time.sleep(1.0)
                sleep_counter += 1.0

    def _log(self, message: str, level: str = "INFO") -> None:
        """Envía el log de vuelta a la GUI en la pestaña correspondiente."""
        self.log_callback(self.symbol, message, level)
