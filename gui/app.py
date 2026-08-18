import sys
import traceback
from pathlib import Path

# 1. Configurar la ruta raíz del proyecto PRIMERO que todo
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 2. Módulos propios y librerías
import customtkinter as ctk
import threading
from typing import Dict, List, Any
import MetaTrader5 as mt5

from gui.components import TopbarComponent, SymbolSelectorComponent, ConsoleTabviewComponent, ConfigWindow
from core.bot_worker import SymbolWorker
from core.config_manager import load_config, save_config
from core.connector import initialize_mt5, shutdown_mt5, get_symbol_specs

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class QuantBotApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("🤖 Quant Trading Bot - Auto Execution")
        self.geometry("1150x760")
        self.minsize(1000, 680)

        # Configuración de Grid Principal (Row 0: Topbar, Row 1: Main Panel)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Cargar configuración persistente
        self.config_data: Dict[str, Any] = load_config()
        raw_active_symbols: List[str] = self.config_data.get("active_symbols", [])
        available_symbols: List[str] = self.config_data.get("available_symbols", [])

        # Sanitizar coincidencia de mayúsculas/minúsculas según la lista disponible de MT5
        if available_symbols:
            avail_map = {s.lower(): s for s in available_symbols}
            self.symbols = [avail_map.get(s.lower(), s) for s in raw_active_symbols]
        else:
            self.symbols = raw_active_symbols

        self.config_data["active_symbols"] = self.symbols

        self.stop_events: Dict[str, threading.Event] = {}
        self.workers: Dict[str, SymbolWorker] = {}

        self._build_ui()

        # -----------------------------------------------------------------
        # 1. Intentar inicializar MT5 al arrancar la app
        # -----------------------------------------------------------------
        if initialize_mt5():
            print("[DEBUG MT5] ✅ Conexión inicializada correctamente con la terminal MT5.")
            self.console.log("General", "🔌 Conexión con MT5 establecida.", "SUCCESS")
        else:
            print("[DEBUG MT5] ❌ No se pudo conectar a MT5 al iniciar la app.")
            self.console.log("General", "❌ No se pudo conectar a MT5. Revisa tus credenciales.", "ERROR")

        # -----------------------------------------------------------------
        # 2. Iniciar el bucle de actualización de la cuenta
        # -----------------------------------------------------------------
        self._update_account_loop()
        self.console_tabview = self.console

    def _build_ui(self) -> None:
        # 1. Topbar Superior (Fila 0)
        self.topbar = TopbarComponent(
            self,
            on_test_order_callback=self._execute_test_order,
            on_config_saved_callback=self._on_config_reloaded
        )
        self.topbar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

        # 2. Panel Central (Fila 1)
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # 3. Selector de Símbolos y Tabla por Par (dentro de self.main_frame)
        self.symbol_selector = SymbolSelectorComponent(
            self.main_frame,
            symbols=self.symbols,
            available_symbols=self.config_data.get("available_symbols", []),
            symbol_specs=self.config_data.get("symbol_specs", {}),
            on_toggle_callback=self._handle_symbol_toggle,
            on_symbols_changed_callback=self._handle_symbols_list_changed
        )
        self.symbol_selector.pack(fill="x", pady=(0, 8))

        # 4. Consola de Logs (dentro de self.main_frame)
        self.console = ConsoleTabviewComponent(
            master=self.main_frame,
            symbols=self.symbol_selector.symbols
        )
        self.console.pack(fill="both", expand=True)

    def _handle_symbol_toggle(self, symbol: str, is_active: bool) -> None:
        """Maneja el encendido / apagado del monitoreo de un símbolo específico."""
        if is_active:
            # Obtener configuración propia de este par desde symbol_selector
            sym_config = self.symbol_selector.get_symbol_config(symbol)
            topbar_vals = self.topbar.get_topbar_values()

            stop_evt = threading.Event()
            self.stop_events[symbol] = stop_evt

            worker = SymbolWorker(
                symbol=symbol,
                log_callback=self.on_worker_log,
                stop_event=stop_evt,
                timeframe=sym_config["timeframe_val"],
                test_mode=topbar_vals.get("test_mode", False),
                risk_pct=sym_config["risk_pct"],
                lot=sym_config["lot"]
            )

            self.workers[symbol] = worker
            worker.start()

            self.console.log(symbol, f"🚀 Monitoreo activado ({symbol} | Lote: {sym_config['lot']} | Riesgo: {sym_config['risk_pct']*100:.1f}% | TF: {sym_config['timeframe_str']})", "INFO")
        else:
            if symbol in self.stop_events:
                self.stop_events[symbol].set()
                del self.stop_events[symbol]
            if symbol in self.workers:
                del self.workers[symbol]

            self.console.log(symbol, f"🛑 Monitoreo detenido para {symbol}...", "WARN")

    def _handle_symbols_list_changed(self, new_symbols: List[str]) -> None:
        self.symbols = new_symbols
        self.save_settings()

        # Sincronizar las pestañas de la consola inmediatamente
        if hasattr(self, "console"):
            self.console.sync_tabs(self.symbols)

    def _on_config_reloaded(self) -> None:
        """Callback cuando se guardan credenciales desde el modal de configuración."""
        self.config_data = load_config()
        available = self.config_data.get("available_symbols", [])
        specs = self.config_data.get("symbol_specs", {})
        self.symbol_selector.update_available_symbols(available)
        self.symbol_selector.update_symbol_specs(specs)
        self.console.log("General", "🔄 Configuración reloaded exitosamente.", "SUCCESS")

    def _execute_test_order(self) -> None:
        """Ejecuta una orden de prueba rápida."""
        def run_test():
            try:
                test_symbol = self.symbols[0] if self.symbols else "EURUSD_r"
                self.console.log("General", f"🧪 Iniciando orden de prueba en {test_symbol}...", "INFO")
            except Exception as e:
                self.console.log("General", f"❌ Error en orden de prueba: {e}", "ERROR")

        threading.Thread(target=run_test, daemon=True).start()

    def save_settings(self) -> None:
        """Guarda los símbolos activos en config.json."""
        self.config_data["active_symbols"] = self.symbols
        if save_config(self.config_data):
            self.console.log("General", "✅ Configuración guardada.", "SUCCESS")
        else:
            self.console.log("General", "❌ Error al guardar configuración.", "ERROR")

    def destroy(self) -> None:
        for event in self.stop_events.values():
            event.set()
        shutdown_mt5()
        super().destroy()

    def _update_account_loop(self) -> None:
        """Bucle secundario en segundo plano para actualizar balance y equidad."""
        try:
            acc_info = mt5.account_info()
            if acc_info is not None:
                balance = acc_info.balance
                equity = acc_info.equity
                self.topbar.update_account_info(balance, equity)
                self.symbol_selector.set_account_balance(balance)
            else:
                self.topbar.update_account_info(0.0, 0.0)
                self.symbol_selector.set_account_balance(0.0)

        except Exception as e:
            print(f"[DEBUG ACCOUNT] Excepción en loop: {e}")
            traceback.print_exc()

        self.after(5000, self._update_account_loop)

    def on_worker_log(self, symbol: str, message: str, level: str = "INFO") -> None:
        """Callback que reciben los workers para enviar logs a la consola de la UI."""
        if hasattr(self, "console") and self.console:
            self.console.log(symbol, message, level)
        elif hasattr(self, "console_tabview") and self.console_tabview:
            self.console_tabview.log(symbol, message, level)
        else:
            print(f"[{level}] [{symbol}] {message}")


if __name__ == "__main__":
    app = QuantBotApp()
    app.mainloop()
