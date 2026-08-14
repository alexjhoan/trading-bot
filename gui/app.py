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

    def _handle_symbol_toggle(self, symbol: str, is_active: bool) -> None:
        if is_active:
            # Usar get_sidebar_values() en lugar de get_sidebar_values()
            if hasattr(self.sidebar, "get_sidebar_values"):
                sidebar_vals = self.sidebar.get_sidebar_values()
            elif hasattr(self.sidebar, "get_values"):
                sidebar_vals = self.sidebar.get_values()
            else:
                sidebar_vals = {"risk_pct": 0.01, "test_mode": False, "timeframe_val": 1}

            stop_evt = threading.Event()
            self.stop_events[symbol] = stop_evt

            # Crear worker asegurando que self.on_worker_log exista
            worker = SymbolWorker(
                symbol=symbol,
                log_callback=self.on_worker_log,  # 👈 Ahora ya existe
                stop_event=stop_evt,
                timeframe=sidebar_vals.get("timeframe_val", 1),
                test_mode=sidebar_vals.get("test_mode", False),
                risk_pct=sidebar_vals.get("risk_pct", 0.01)
            )

            self.workers[symbol] = worker
            worker.start()

            if hasattr(self, "on_worker_log"):
                self.on_worker_log(symbol, f"Hilo iniciado para {symbol}", "INFO")
        else:
            if symbol in self.stop_events:
                self.stop_events[symbol].set()
            if symbol in self.workers:
                del self.workers[symbol]
            if hasattr(self, "on_worker_log"):
                self.on_worker_log(symbol, f"Deteniendo hilo para {symbol}...", "WARN")

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
                params = self.sidebar.get_sidebar_values()
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

            # 1. Obtener valores actuales del Sidebar
            sidebar_vals = self.sidebar.get_sidebar_values()

            # 2. Instanciar SymbolWorker pasando los parámetros extraídos
            worker = SymbolWorker(
                symbol=symbol,
                log_callback=self.on_worker_log,
                stop_event=self.stop_events[symbol],
                timeframe=sidebar_vals["timeframe_val"],  # 👈 Se envía el timeframe seleccionado
                test_mode=sidebar_vals["test_mode"],      # 👈 Se envía si el switch 'Test Mode' está activo
                risk_pct=sidebar_vals["risk_pct"]
            )
            worker.start()
            self.workers[symbol] = worker
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
        """Sincroniza el estado de los controles verificando si hay hilos/workers ejecutándose."""
        # En lugar de bloquear por cualquier orden en MT5, verificamos si hay bots activos en ejecución
        has_active_workers = len(self.workers) > 0

        self.sidebar.set_inputs_state(enabled=not has_active_workers)
        self.symbol_selector.update_all_inputs_state(active_symbols=has_active_workers)

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
                risk_pct = self.sidebar.get_sidebar_values().get("risk_pct", 0.01)

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

                risk_pct = self.sidebar.get_sidebar_values().get("risk_pct", 0.01)
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
