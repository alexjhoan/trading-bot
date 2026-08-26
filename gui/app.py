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
from core.connector import initialize_mt5, shutdown_mt5, get_symbol_specs, check_user_credentials_exist
from core.licensing import verify_license_token, get_hardware_id
from core.ai_advisor import test_ai_payload_terminal

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
        self.selected_strategy: str = self.config_data.get("selected_strategy", "forex")
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
        # 0. Validar Licencia y Hardware ID de la Máquina al iniciar el Bot
        # -----------------------------------------------------------------
        license_key = self.config_data.get("license_key", "")
        current_login = int(self.config_data.get("login", 0))
        lic_ok, lic_msg, self.license_payload = verify_license_token(
            token=license_key,
            current_account_login=current_login
        )
        if not lic_ok:
            self.console.log("General", f"🔒 [VALIDACIÓN DE LICENCIA AL INICIO] {lic_msg}", "ERROR")
            self.console.log("General", f"💻 Machine ID de este equipo: {get_hardware_id()}", "INFO")
            self.console.log("General", "👉 Para activar el bot, proporcione este Machine ID al desarrollador y pegue su llave en Configuración.", "WARNING")
        else:
            self.console.log("General", f"🔒 [LICENCIA AUTORIZADA] {lic_msg}", "SUCCESS")

        # -----------------------------------------------------------------
        # 1. Validar credenciales de usuario antes de inicializar MT5
        # -----------------------------------------------------------------
        creds_ok, creds_msg = check_user_credentials_exist()
        if not creds_ok:
            print(f"[DEBUG MT5] ⚠️ {creds_msg} Solicitando datos de acceso...")
            self.console.log("General", f"⚠️ {creds_msg}", "WARNING")
            self.console.log("General", "👉 Por favor configure su ID de Cuenta (Login), Contraseña y Servidor para conectar con MT5.", "INFO")
            # Abrir modal de configuración para pedir que llene los datos
            self.after(400, self._open_credentials_prompt)
        else:
            if initialize_mt5():
                print("[DEBUG MT5] ✅ Conexión inicializada correctamente con la terminal MT5.")
                self.console.log("General", "🔌 Conexión con MT5 establecida.", "SUCCESS")
                # Detectar y tomar las riendas de operaciones abiertas
                self._adopt_open_positions()
            else:
                print("[DEBUG MT5] ❌ No se pudo conectar a MT5 al iniciar la app.")
                self.console.log("General", "❌ No se pudo autenticar en MT5. Verifique sus credenciales.", "ERROR")
                self.after(400, self._open_credentials_prompt)

        # -----------------------------------------------------------------
        # 2. Iniciar el bucle de actualización de la cuenta
        # -----------------------------------------------------------------
        self._update_account_loop()
        self.console_tabview = self.console

    def _open_credentials_prompt(self) -> None:
        """Abre la ventana modal de configuración para que el usuario ingrese sus datos de acceso."""
        ConfigWindow(parent=self, on_save_callback=self._on_credentials_saved)

    def _on_credentials_saved(self) -> None:
        """Se ejecuta al guardar las credenciales en la ventana de configuración."""
        self._on_config_reloaded()
        if initialize_mt5():
            self.console.log("General", "🔌 Conexión con MT5 establecida tras ingresar credenciales.", "SUCCESS")
            self._adopt_open_positions()
        else:
            self.console.log("General", "❌ Falló la conexión con las credenciales ingresadas. Verifique el servidor y contraseña.", "ERROR")

    def _adopt_open_positions(self) -> None:
        """Detecta operaciones abiertas en MT5, agrega el par a la lista si no está y enciende el switch de monitoreo."""
        try:
            positions = mt5.positions_get()
            if not positions:
                return

            for pos in positions:
                sym = pos.symbol
                pos_type = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"

                # 1. Asegurar que el símbolo esté en la lista
                if sym not in self.symbols:
                    self.symbol_selector.ensure_symbol_present(sym, lot=pos.volume)
                    self.console.log("General", f"➕ Agregado par {sym} detectado por orden abierta #{pos.ticket}", "INFO")

                # 2. Encender el switch si está apagado
                if not self.symbol_selector.is_symbol_active(sym):
                    self.console.log(
                        "General",
                        f"⚡ [OPERACIÓN DETECTADA] #{pos.ticket} {sym} ({pos_type} {pos.volume} lotes a {pos.price_open}). Activando switch y tomando control...",
                        "SUCCESS"
                    )
                    self.symbol_selector.set_symbol_active(sym, True)
        except Exception as e:
            print(f"[DEBUG ADOPT POSITIONS] Error al adoptar operaciones abiertas: {e}")

    def _build_ui(self) -> None:
        # 1. Topbar Superior (Fila 0)
        self.topbar = TopbarComponent(
            self,
            selected_strategy=self.selected_strategy,
            on_strategy_changed_callback=self._handle_strategy_changed,
            on_config_saved_callback=self._on_config_reloaded,
            on_test_ai_callback=self._handle_test_ai_terminal
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
            symbol_lots=self.config_data.get("symbol_lots", {}),
            symbol_risk_pcts=self.config_data.get("symbol_risk_pcts", {}),
            symbol_timeframes=self.config_data.get("symbol_timeframes", {}),
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

    def _handle_strategy_changed(self, new_strategy: str) -> None:
        """Maneja el cambio dinámico de estrategia desde el selector del Topbar."""
        self.selected_strategy = new_strategy
        self.config_data["selected_strategy"] = new_strategy
        self.save_settings()
        self.console.log("General", f"🎯 Estrategia activa cambiada a: '{new_strategy.upper()}'. Los próximos análisis se ejecutarán con esta estrategia.", "SUCCESS")

    def _handle_symbol_toggle(self, symbol: str, is_active: bool) -> None:
        """Maneja el encendido / apagado del monitoreo de un símbolo específico."""
        if is_active:
            # -------------------------------------------------------------
            # Validación 2: Verificar Licencia cuando el usuario pasa a ON
            # -------------------------------------------------------------
            license_key = self.config_data.get("license_key", "")
            current_login = int(self.config_data.get("login", 0))
            lic_ok, lic_msg, _ = verify_license_token(
                token=license_key,
                current_account_login=current_login
            )

            if not lic_ok:
                # Mostrar en la consola de console_tabview que la llave no es correcta o está vencida
                self.console.log("General", f"❌ [ERROR DE LICENCIA AL ACTIVAR {symbol}] {lic_msg}", "ERROR")
                self.console.log(symbol, f"❌ [BLOQUEO POR LICENCIA] No se puede iniciar el bot en {symbol}: {lic_msg}", "ERROR")
                # Revertir estado visual del switch a apagado
                self.symbol_selector.set_symbol_active(symbol, False)
                return

            # Obtener configuración propia de este par desde symbol_selector
            sym_config = self.symbol_selector.get_symbol_config(symbol)
            topbar_vals = self.topbar.get_topbar_values()
            active_strat = topbar_vals.get("strategy", self.selected_strategy)

            # Guardar inmediatamente la configuración de este par en config.json
            if "symbol_lots" not in self.config_data:
                self.config_data["symbol_lots"] = {}
            if "symbol_risk_pcts" not in self.config_data:
                self.config_data["symbol_risk_pcts"] = {}
            if "symbol_timeframes" not in self.config_data:
                self.config_data["symbol_timeframes"] = {}

            self.config_data["symbol_lots"][symbol] = sym_config["lot"]
            self.config_data["symbol_risk_pcts"][symbol] = round(sym_config["risk_pct"] * 100.0, 2)
            self.config_data["symbol_timeframes"][symbol] = sym_config["timeframe_str"]
            self.save_settings()

            stop_evt = threading.Event()
            self.stop_events[symbol] = stop_evt

            worker = SymbolWorker(
                symbol=symbol,
                log_callback=self.on_worker_log,
                stop_event=stop_evt,
                timeframe=sym_config["timeframe_val"],
                test_mode=topbar_vals.get("test_mode", False),
                risk_pct=sym_config["risk_pct"],
                lot=sym_config["lot"],
                strategy_name=active_strat
            )

            self.workers[symbol] = worker
            worker.start()

            self.console.log(symbol, f"🚀 Monitoreo activado ({symbol} | Estrategia: {active_strat.upper()} | Lote: {sym_config['lot']} | Riesgo: {sym_config['risk_pct']*100:.1f}% | TF: {sym_config['timeframe_str']})", "INFO")
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

        # Sincronizar y verificar la conexión con MT5 inmediatamente tras guardar
        if initialize_mt5():
            acc_info = mt5.account_info()
            if acc_info is not None:
                self.topbar.update_account_info(acc_info.balance, acc_info.equity)
                self.symbol_selector.set_account_balance(acc_info.balance)
                self.symbol_selector.update_schedules_color()
                self._adopt_open_positions()
                self.console.log("General", f"🔌 Conexión con MT5 activa | Balance: ${acc_info.balance:.2f} | Bróker: {acc_info.company}", "SUCCESS")
            else:
                self.console.log("General", "🔄 Configuración guardada. MT5 inicializado.", "SUCCESS")
        else:
            self.console.log("General", "⚠️ No se pudo autenticar en MT5 con las credenciales ingresadas.", "WARNING")

        self.console.log("General", "🔄 Configuración recargada exitosamente.", "INFO")

    def _handle_test_ai_terminal(self) -> None:
        """Dispara una petición de prueba genérica a la IA e imprime todo el payload y respuesta en la consola de terminal."""
        def run_terminal_test():
            self.console.log("General", "🧠 [TEST API IA] Iniciando prueba con payload genérico...", "INFO")
            self.console.log("General", "👉 Revisa la consola de PowerShell/Terminal para ver el Payload JSON exacto y la respuesta cruda de la IA.", "INFO")
            cfg = load_config()
            api_key = str(cfg.get("ai_api_key", ""))
            model_name = str(cfg.get("ai_model", "gemini-2.5-flash"))
            base_url = str(cfg.get("ai_base_url", ""))

            res = test_ai_payload_terminal(
                api_key=api_key,
                model_name=model_name,
                base_url=base_url
            )

            if res.get("status") == "success":
                action = res.get("response", {}).get("action", "N/A")
                opinion = res.get("response", {}).get("opinion", "")
                self.console.log(
                    "General",
                    f"✅ [TEST API IA EXITOSO] Decisión IA: {action} | Opinión: \"{opinion}\" | Latencia: {res.get('latency_ms', 0):.0f}ms",
                    "SUCCESS"
                )
            else:
                err_msg = res.get("error", "Error desconocido")
                self.console.log(
                    "General",
                    f"❌ [TEST API IA FALLIDO] Código {res.get('http_code')}: {err_msg}",
                    "ERROR"
                )

        threading.Thread(target=run_terminal_test, daemon=True).start()

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
        """Guarda los símbolos activos y configuraciones individuales en config.json."""
        self.config_data["active_symbols"] = self.symbols
        self.config_data["selected_strategy"] = self.selected_strategy

        if hasattr(self, "symbol_selector"):
            all_configs = self.symbol_selector.get_all_symbol_configs()
            if "symbol_lots" not in self.config_data:
                self.config_data["symbol_lots"] = {}
            if "symbol_risk_pcts" not in self.config_data:
                self.config_data["symbol_risk_pcts"] = {}
            if "symbol_timeframes" not in self.config_data:
                self.config_data["symbol_timeframes"] = {}

            for s, cfg in all_configs.items():
                self.config_data["symbol_lots"][s] = cfg["lot"]
                self.config_data["symbol_risk_pcts"][s] = round(cfg["risk_pct"] * 100.0, 2)
                self.config_data["symbol_timeframes"][s] = cfg["timeframe_str"]

        if save_config(self.config_data):
            self.console.log("General", "✅ Configuración guardada en config.json.", "SUCCESS")
        else:
            self.console.log("General", "❌ Error al guardar configuración.", "ERROR")

    def destroy(self) -> None:
        for event in self.stop_events.values():
            event.set()
        shutdown_mt5()
        super().destroy()

    def _update_account_loop(self) -> None:
        """Bucle secundario en segundo plano para actualizar balance, equidad y detectar operaciones abiertas."""
        try:
            acc_info = mt5.account_info()
            if acc_info is None:
                # Intentar reconexión automática si existen credenciales válidas
                creds_ok, _ = check_user_credentials_exist()
                if creds_ok:
                    if initialize_mt5():
                        acc_info = mt5.account_info()

            if acc_info is not None:
                balance = acc_info.balance
                equity = acc_info.equity
                self.topbar.update_account_info(balance, equity)
                self.symbol_selector.set_account_balance(balance)
                # Actualizar colores de horarios de mercado
                self.symbol_selector.update_schedules_color()
                # Verificar y adoptar operaciones abiertas en tiempo real
                self._adopt_open_positions()

                # 🟢 Sincronizar estado de las pestañas en la consola según las órdenes vivas en MT5
                if hasattr(self, "console") and self.console:
                    positions = mt5.positions_get()
                    open_symbols = {p.symbol for p in positions} if positions else set()

                    for sym in self.symbols:
                        is_active = self.symbol_selector.is_symbol_active(sym)
                        if not is_active:
                            self.console.set_symbol_status(sym, "INACTIVE")
                        elif sym in open_symbols:
                            self.console.set_symbol_status(sym, "OPEN_ORDER", f"[{sym}] Operación abierta activa. Monitoreando SL/TP...")
                        else:
                            # Si no hay orden abierta y el bot está activo, asegurar estado WAITING (🟢)
                            if self.console.symbol_status.get(sym) == "OPEN_ORDER":
                                self.console.set_symbol_status(sym, "WAITING", f"[{sym}] Operación cerrada. Analizando mercado en espera de confluencias")
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
