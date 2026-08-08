import sys
import traceback
from pathlib import Path

# Obtener la ruta raíz del proyecto
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import customtkinter as ctk
import threading
from typing import Dict, List, Any
import MetaTrader5 as mt5

from components import SidebarComponent, SymbolSelectorComponent, ConsoleTabviewComponent, ConfigWindow
from core.bot_worker import SymbolWorker
from core.connector import initialize_mt5, shutdown_mt5
from core.config_manager import load_config, save_config

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class QuantBotApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("🤖 Quant Trading Bot - Auto Execution")
        self.geometry("1100x720")
        self.minsize(980, 650)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Cargar configuración persistente
        self.config_data: Dict[str, Any] = load_config()
        self.symbols: List[str] = self.config_data.get(
            "active_symbols", ["EURUSD_r", "GBPUSD_r", "USDJPY_r", "AUDUSD_r"]
        )

        self.stop_events: Dict[str, threading.Event] = {}
        self.workers: Dict[str, SymbolWorker] = {}

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # Conectar a MT5 una sola vez al iniciar la aplicación
        if initialize_mt5():
            self.console.log("General", "Conexión inicial con MetaTrader 5 establecida.", "SUCCESS")
        else:
            self.console.log("General", "No se pudo conectar a MetaTrader 5 al iniciar.", "ERROR")

        # Iniciar polling periódicos solo para consultar balance (sin volver a inicializar)
        self._start_account_polling()

    def _start_account_polling(self) -> None:
        """Obtiene balance y equidad de la sesión activa de MT5 sin reconectar continuamente."""
        def poll():
            try:
                acc = mt5.account_info()
                if acc:
                    self.sidebar.update_account_info(acc.balance, acc.equity)
            except Exception:
                pass

            # Programar la próxima consulta en 5 segundos (5000 ms)
            self.after(5000, self._start_account_polling)

        threading.Thread(target=poll, daemon=True).start()

    def open_config_window(self) -> None:
        ConfigWindow(parent=self, on_save_callback=self.reload_config_and_symbols)

    def reload_config_and_symbols(self) -> None:
        self.config_data = load_config()
        new_available = self.config_data.get("available_symbols", [])

        if hasattr(self, "symbol_selector"):
            self.symbol_selector.update_available_symbols(new_available)
            if hasattr(self, "console"):
                self.console.log("General", f"Símbolos de MT5 actualizados ({len(new_available)} cargados).", "SUCCESS")

    def _build_ui(self) -> None:
        # 1. Panel Lateral (Sidebar)
        self.sidebar = SidebarComponent(
            master=self,
            on_test_order_callback=self._on_test_order,
            on_config_saved_callback=self.reload_config_and_symbols
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # 2. Área Principal
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # 2.1 Selector de Símbolos Dinámico
        available_symbols: List[str] = self.config_data.get("available_symbols", [])
        self.symbol_selector = SymbolSelectorComponent(
            master=self.main_frame,
            symbols=self.symbols,
            available_symbols=available_symbols,
            on_toggle_callback=self._on_symbol_toggle,
            on_symbols_changed_callback=self._on_symbols_changed
        )
        self.symbol_selector.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        # 2.2 Consola con Pestañas Dinámicas
        self.console = ConsoleTabviewComponent(
            master=self.main_frame,
            symbols=self.symbols
        )
        self.console.grid(row=1, column=0, sticky="nsew")

        self.console.log("General", "Sistema inicializado. Listo para operar.", "INFO")

    def _start_worker_for_symbol(self, symbol: str) -> None:
        """Inicia el hilo trabajador para un símbolo específico."""
        if symbol in self.workers:
            return

        stop_event = threading.Event()
        params = self.sidebar.get_parameters()

        worker = SymbolWorker(
            symbol=symbol,
            params=params,
            log_callback=self.console.log,
            stop_event=stop_event
        )
        self.stop_events[symbol] = stop_event
        self.workers[symbol] = worker
        worker.start()
        self.console.log("General", f"🟢 Bot INICIADO para {symbol}", "SUCCESS")

    def _stop_worker_for_symbol(self, symbol: str) -> None:
        """Detiene el hilo trabajador para un símbolo específico."""
        if symbol in self.stop_events:
            self.stop_events[symbol].set()
            del self.stop_events[symbol]

        if symbol in self.workers:
            del self.workers[symbol]
            self.console.log("General", f"⚪ Bot DETENIDO para {symbol}", "WARN")

    def _on_symbols_changed(self, new_symbols: List[str]) -> None:
        old_symbols = self.symbols
        self.symbols = list(new_symbols)

        self.console.sync_tabs(self.symbols)

        removed_symbols = [s for s in old_symbols if s not in new_symbols]
        for sym in removed_symbols:
            self._stop_worker_for_symbol(sym)

        self.config_data["active_symbols"] = self.symbols
        save_config(self.config_data)

        self.console.log("General", f"Lista de activos actualizada: {self.symbols}", "INFO")

    def _on_symbol_toggle(self, symbol: str, is_active: bool) -> None:
        """Se activa cuando el usuario cambia el switch de un activo."""
        if is_active:
            self._start_worker_for_symbol(symbol)
        else:
            self._stop_worker_for_symbol(symbol)

    def _on_test_order(self) -> None:
        active_symbols = self.symbol_selector.get_active_symbols()
        if not active_symbols:
            self.console.log("General", "Selecciona al menos un par activo para la prueba.", "ERROR")
            return

        test_symbol = active_symbols[0]
        params = self.sidebar.get_parameters()

        self.console.log("General", f"Ejecutando orden de prueba en {test_symbol}...", "INFO")

        def run_test():
            try:
                if not initialize_mt5():
                    self.console.log("General", "No se pudo conectar a MT5 para la prueba.", "ERROR")
                    return

                from core.risk_manager import RiskManager
                from core.executor import OrderExecutor

                risk_mgr = RiskManager()
                executor = OrderExecutor()
                acc_info = mt5.account_info()
                balance: float = acc_info.balance if acc_info else 10000.0

                lot = risk_mgr.calculate_position_size(
                    balance=balance,
                    sl_pips=params["sl_pips"],
                    risk_pct=params["risk_pct"],
                    symbol=test_symbol
                )

                res = executor.execute_market_order(
                    symbol=test_symbol,
                    order_type="BUY",
                    volume=lot,
                    sl_pips=params["sl_pips"],
                    tp_pips=params["tp_pips"]
                )

                if res["status"]:
                    self.console.log("General", f"✅ Orden de prueba EXITOSA en {test_symbol} (Ticket: {res['ticket']})", "SUCCESS")
                    self.console.log(test_symbol, f"✅ Orden BUY colocada. Lote: {lot}, Ticket: {res['ticket']}", "SUCCESS")
                else:
                    self.console.log("General", f"❌ Falló orden de prueba: {res['message']}", "ERROR")

            except Exception as e:
                error_detail = traceback.format_exc()
                self.console.log("General", f"❌ Error crítico en orden de prueba ({type(e).__name__}): {e}\n{error_detail}", "ERROR")
                threading.Thread(target=run_test, daemon=True).start()

    def _on_test_order(self) -> None:
        active_symbols = self.symbol_selector.get_active_symbols()
        if not active_symbols:
            self.console.log("General", "Selecciona al menos un par activo para la prueba.", "ERROR")
            return

        test_symbol = active_symbols[0]
        params = self.sidebar.get_parameters()

        self.console.log("General", f"Ejecutando orden de prueba en {test_symbol}...", "INFO")

        def run_test():
            try:
                if not initialize_mt5():
                    self.console.log("General", "No se pudo conectar a MT5 para la prueba.", "ERROR")
                    return

                from core.risk_manager import RiskManager
                from core.executor import OrderExecutor

                risk_mgr = RiskManager()
                executor = OrderExecutor(symbol=test_symbol, log_callback=self.console.log)

                acc_info = mt5.account_info()
                balance = acc_info.balance if acc_info else 1000.0

                lot = risk_mgr.calculate_position_size(
                    balance=balance,
                    sl_pips=params["sl_pips"]
                )

                # Loguear el cálculo de gestión de riesgo en la GUI
                risk_msg = f"📊 [GESTIÓN RIESGO] Capital: ${balance:.2f} | Risk: {params['risk_pct']*100:.1f}% | SL: {params['sl_pips']} pips -> Lotaje: {lot}"
                self.console.log(test_symbol, risk_msg, "INFO")

                res = executor.execute_market_order(
                    symbol=test_symbol,
                    order_type="BUY",
                    volume=lot,
                    sl_pips=params["sl_pips"],
                    tp_pips=params["tp_pips"]
                )

                if not res["status"]:
                    self.console.log("General", f"❌ Falló orden de prueba en {test_symbol}: {res['message']}", "ERROR")

            except Exception as e:
                error_detail = traceback.format_exc()
                self.console.log("General", f"❌ Error crítico en orden de prueba ({type(e).__name__}): {e}\n{error_detail}", "ERROR")
                threading.Thread(target=run_test, daemon=True).start()

    def destroy(self) -> None:
        for event in self.stop_events.values():
            event.set()
        shutdown_mt5()
        super().destroy()


if __name__ == "__main__":
    app = QuantBotApp()
    app.mainloop()
