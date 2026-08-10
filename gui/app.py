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
            "active_symbols", []
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

        self.console_tabview = ConsoleTabviewComponent(
            master=self.main_frame,
            symbols=self.symbols
        )

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
            symbol_specs=self.config_data.get("symbol_specs", {}),  # 🟢 AGREGAR ESTA LÍNEA
            on_toggle_callback=self._handle_symbol_toggle,
            on_symbols_changed_callback=self._handle_symbols_list_changed
        )
        self.symbol_selector.pack(fill="x", pady=(0, 10))

        # 4. Consola de Logs (dentro de self.main_frame)
        self.console = ConsoleTabviewComponent(
            master=self.main_frame,
            symbols=self.symbol_selector.symbols
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

        # ⚡ Sincronizar las pestañas de la consola inmediatamente
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

    def _on_toggle(self, symbol: str) -> None:
        """Se ejecuta al instante al pulsar el switch."""
        is_active = self.switch_vars[symbol].get()

        # 1. Notificar a la App para que reevalúe bloqueos de UI INMEDIATAMENTE
        if hasattr(self.master, "update_controls_state"):
            self.master.update_controls_state()

        # 2. Ejecutar callback del worker si existe
        if self.on_toggle_callback:
            self.on_toggle_callback(symbol, is_active)

    def set_inputs_enabled(self, force_all_disabled: bool = False) -> None:
        """Aplica el bloqueo/desbloqueo instantáneo con estilos desvanecidos."""
        for symbol, entry in self.entry_lots.items():
            is_switch_on = self.switch_vars.get(symbol, ctk.BooleanVar()).get()
            should_disable = force_all_disabled or is_switch_on

            if should_disable:
                entry.configure(
                    state="disabled",
                    fg_color="#1A1A1A",
                    text_color="#555555"
                )
            else:
                entry.configure(
                    state="normal",
                    fg_color="#333333",
                    text_color="#FFFFFF"
                )
            entry.update_idletasks()

    def _on_symbol_toggle(self, symbol: str, is_active: bool) -> None:
        """Maneja el encendido/apagado de un bot por símbolo y actualiza la UI al instante."""
        if is_active:
            self.console.log(symbol, f"🚀 Activando monitoreo para {symbol}...", "INFO")
            stop_event = threading.Event()
            self.stop_events[symbol] = stop_event

            worker = SymbolWorker(
                symbol=symbol,
                timeframe_str=self.sidebar.get_parameters().get("timeframe", "M15"),
                risk_pct=self.sidebar.get_parameters().get("risk_pct", 0.01),
                stop_event=stop_event,
                log_callback=self._log_from_worker,
                lot_size=self.symbol_selector.get_symbol_lots().get(symbol, 0.01)
            )
            self.workers[symbol] = worker
            worker.start()
        else:
            self.console.log(symbol, f"🛑 Deteniendo monitoreo para {symbol}...", "INFO")
            if symbol in self.stop_events:
                self.stop_events[symbol].set()
                del self.stop_events[symbol]
            if symbol in self.workers:
                del self.workers[symbol]

        # ⚡ IMPORTANTE: Refrescar el estado de los controles AL INSTANTE
        self.update_controls_state()

    def update_controls_state(self) -> None:
        """Sincroniza el estado de los controles con las posiciones abiertas de MT5."""
        has_real_trades = self._has_open_positions()

        # Si hay posiciones abiertas, se deshabilita el sidebar
        self.sidebar.set_inputs_state(enabled=not has_real_trades)

        # Actualizar selector de símbolos
        self.symbol_selector.update_all_inputs_state(force_all_disabled=has_real_trades)

    def _has_open_positions(self) -> bool:
        """Verifica si existen posiciones abiertas en MT5."""
        try:
            positions = mt5.positions_get()
            return positions is not None and len(positions) > 0
        except Exception:
            return False

        def on_sidebar_risk_changed(self) -> None:
            """Recalcula los Pips en tiempo real cuando el usuario escribe en la Sidebar."""
            try:
                acc_info = mt5.account_info()
                balance = acc_info.balance if acc_info else 0.0
                risk_pct = self.sidebar.get_parameters().get("risk_pct", 0.01)

                max_risk_usd = balance * risk_pct
                self.symbol_selector.set_max_risk_usd(max_risk_usd)
            except Exception:
                pass

    def _update_account_loop(self) -> None:
        """Bucle secundario en segundo plano."""
        try:
            acc_info = mt5.account_info()
            if acc_info is not None:
                balance = acc_info.balance
                self.sidebar.update_account_info(balance, acc_info.equity)

                risk_pct = self.sidebar.get_parameters().get("risk_pct", 0.01)
                self.symbol_selector.set_max_risk_usd(balance * risk_pct)

                # Mantener estado de controles sincronizado con MT5
                self.update_controls_state()
            else:
                self.sidebar.update_account_info(0.0, 0.0)

        except Exception as e:
            print(f"[DEBUG ACCOUNT] Excepción en loop: {e}")

        self.after(5000, self._update_account_loop)

    def on_symbols_changed(self, new_symbols: List[str]) -> None:
        """Callback cuando cambia la selección de símbolos activos."""
        self.symbols = list(new_symbols)
        self.config_data["active_symbols"] = self.symbols
        save_config(self.config_data)

        # Asegurar que la consola tenga pestaña para todos los activos
        if hasattr(self, "console_tabview"):
            self.console_tabview.sync_tabs(self.symbols)

        self.update_controls_state()

if __name__ == "__main__":
    app = QuantBotApp()
    app.mainloop()
