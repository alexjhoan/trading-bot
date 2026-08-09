import sys
import traceback
from pathlib import Path

# 1. Configurar la ruta raíz del proyecto PRIMERO que todo
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 2. Ahora sí podemos importar CustomTkinter y los módulos propios
import customtkinter as ctk
import threading
from typing import Dict, List, Any
import MetaTrader5 as mt5

from gui.components import SidebarComponent, SymbolSelectorComponent, ConsoleTabviewComponent, ConfigWindow
from core.bot_worker import SymbolWorker
from core.config_manager import load_config, save_config
from core.connector import initialize_mt5, shutdown_mt5, get_symbol_specs

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

    def _update_account_loop(self) -> None:
        """Obtiene el balance actual de MT5 con reintento de conexión."""
        try:
            acc_info = mt5.account_info()

            # Si se perdió la comunicación IPC, reintentamos reconectar
            if acc_info is None:
                print("[DEBUG ACCOUNT] ⚠️ Conexión perdida o no inicializada. Reintentando initialize_mt5()...")
                if initialize_mt5():
                    acc_info = mt5.account_info()

            if acc_info is not None:
                balance = acc_info.balance
                equity = acc_info.equity

                # Actualizar la interfaz
                self.sidebar.update_account_info(balance, equity)

                # Calcular riesgo dinámico
                sidebar_params = self.sidebar.get_parameters()
                risk_pct = sidebar_params.get("risk_pct", 0.01)
                max_risk_usd = balance * risk_pct
                self.symbol_selector.set_max_risk_usd(max_risk_usd)
            else:
                last_error = mt5.last_error()
                print(f"[DEBUG ACCOUNT] ⚠️ mt5.account_info() devolvió None. Código de error MT5: {last_error}")
                self.sidebar.update_account_info(0.0, 0.0)

        except Exception as e:
            print(f"[DEBUG ACCOUNT] ❌ Excepción al consultar cuenta: {e}")

        # Re-ejecutar cada 30 segundos
        self.after(30000, self._update_account_loop)

    def _build_ui(self) -> None:
        # 1. Sidebar (Columna 0)
        self.sidebar = SidebarComponent(
            self,
            on_test_order_callback=self._execute_test_order,
            on_config_saved_callback=self._on_config_reloaded
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # 2. Panel Central (Columna 1) - Lo asignamos como self.main_frame
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # 3. Selector de Símbolos (dentro de self.main_frame)
        self.symbol_selector = SymbolSelectorComponent(
            self.main_frame,
            symbols=self.symbols,
            available_symbols=self.config_data.get("available_symbols", []),
            on_toggle_callback=self._handle_symbol_toggle,
            on_symbols_changed_callback=self._handle_symbols_list_changed
        )
        self.symbol_selector.pack(fill="x", pady=(0, 10))

        # 4. Consola de Logs (dentro de self.main_frame)
        self.console = ConsoleTabviewComponent(
            master=self.main_frame,
            symbols=self.symbols
        )
        self.console.pack(fill="both", expand=True)

    def _handle_symbol_toggle(self, symbol: str, active: bool) -> None:
        if active:
            if symbol not in self.workers or not self.workers[symbol].is_alive():
                stop_evt = threading.Event()
                self.stop_events[symbol] = stop_evt

                # Obtener parámetros del sidebar (como el riesgo %)
                params = self.sidebar.get_parameters()

                worker = SymbolWorker(
                    symbol=symbol,
                    params=params,
                    log_callback=self.console.log,
                    stop_event=stop_evt
                )
                self.workers[symbol] = worker
                worker.start()
                self.console.log(symbol, f"▶️ Monitoreo iniciado para {symbol}", "INFO")
        else:
            if symbol in self.stop_events:
                self.stop_events[symbol].set()
                self.console.log(symbol, f"⏹️ Monitoreo detenido para {symbol}", "WARNING")

    def _handle_symbols_list_changed(self, new_symbols: List[str]) -> None:
        self.symbols = new_symbols
        self.save_settings()

    def _on_config_reloaded(self) -> None:
        """Callback cuando se guardan credenciales desde el modal de configuración."""
        self.config_data = load_config()
        available = self.config_data.get("available_symbols", [])
        self.symbol_selector.update_available_symbols(available)
        self.console.log("General", "🔄 Configuración reloaded exitosamente.", "SUCCESS")

    def _execute_test_order(self) -> None:
        """Ejecuta una orden de prueba rápida."""
        def run_test():
            try:
                params = self.sidebar.get_parameters()
                test_symbol = self.symbols[0] if self.symbols else "EURUSD_r"

                self.console.log("General", f"🧪 Iniciando orden de prueba en {test_symbol}...", "INFO")
                # Lógica de prueba...
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


if __name__ == "__main__":
    app = QuantBotApp()
    app.mainloop()
