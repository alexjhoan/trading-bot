# gui/config_window.py
import threading
import customtkinter as ctk
import MetaTrader5 as mt5
from tkinter import filedialog
from typing import Callable, Optional, Dict, Any, Tuple, List
from core.config_manager import load_config, save_config
from core.connector import get_all_available_symbols, get_all_symbol_specs
from core.ai_advisor import test_ai_connection, fetch_available_models, PROVIDER_PRESETS


class ConfigWindow(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, on_save_callback: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent)
        self.title("Configuración de Conexión, MT5 & Inteligencia Artificial")
        self.geometry("580x760")
        self.minsize(540, 700)
        self.resizable(True, True)

        self.transient(parent)
        self.grab_set()

        self.on_save_callback: Optional[Callable[[], None]] = on_save_callback
        self.config_data: Dict[str, Any] = load_config()
        self.entries: Dict[str, ctk.CTkEntry] = {}

        self.selected_provider = ctk.StringVar(value=self.config_data.get("ai_provider", "Google Gemini"))
        self.selected_model = ctk.StringVar(value=self.config_data.get("ai_model", "gemini-2.5-flash"))

        self._build_ui()
        self._load_values()

    def _browse_terminal_path(self) -> None:
        file_path: str = filedialog.askopenfilename(
            title="Seleccionar terminal64.exe",
            initialdir="C:\\Program Files",
            filetypes=[("Executable", "terminal64.exe"), ("All Executables", "*.exe"), ("All Files", "*.*")]
        )
        if file_path and "path_entry" in self.entries:
            self.entries["path_entry"].delete(0, "end")
            self.entries["path_entry"].insert(0, file_path)

    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Contenedor con scroll para organizar cómodamente MT5 e IA
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=10)
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        # ----------------------------------------------------
        # SECCIÓN 1: METATRADER 5
        # ----------------------------------------------------
        mt5_header = ctk.CTkLabel(
            self.scroll_frame,
            text="📊 Conexión con MetaTrader 5",
            font=("Arial", 15, "bold"),
            anchor="w"
        )
        mt5_header.grid(row=0, column=0, columnspan=2, pady=(5, 10), sticky="w")

        labels_mt5 = [
            ("ID de Cuenta (Login):", "login_entry"),
            ("Contraseña:", "password_entry"),
            ("Servidor Bróker:", "server_entry"),
            ("Sufijo de Símbolo (ej: .m):", "suffix_entry"),
            ("Ruta terminal64.exe (Opcional):", "path_entry"),
            ("Magic Number (ID Bot):", "magic_entry"),
            ("Max Slippage (puntos):", "slippage_entry"),
        ]

        current_row = 1
        for label_text, key in labels_mt5:
            lbl = ctk.CTkLabel(self.scroll_frame, text=label_text, anchor="w")
            lbl.grid(row=current_row, column=0, padx=(5, 10), pady=4, sticky="w")

            if key == "path_entry":
                path_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
                path_frame.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
                path_frame.grid_columnconfigure(0, weight=1)

                entry = ctk.CTkEntry(path_frame)
                entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
                self.entries[key] = entry

                browse_btn = ctk.CTkButton(
                    path_frame,
                    text="📁 Buscar",
                    width=75,
                    command=self._browse_terminal_path
                )
                browse_btn.grid(row=0, column=1, sticky="e")
            else:
                show_char = "*" if "password" in key else ""
                entry = ctk.CTkEntry(self.scroll_frame, show=show_char)
                entry.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
                self.entries[key] = entry

            current_row += 1

        # ----------------------------------------------------
        # SECCIÓN 2: INTELIGENCIA ARTIFICIAL & GESTIÓN DE RIESGO
        # ----------------------------------------------------
        ai_separator = ctk.CTkFrame(self.scroll_frame, height=2, fg_color="#374151")
        ai_separator.grid(row=current_row, column=0, columnspan=2, pady=(15, 10), sticky="ew")
        current_row += 1

        ai_header = ctk.CTkLabel(
            self.scroll_frame,
            text="🧠 Inteligencia Artificial & Optimización de Riesgo",
            font=("Arial", 15, "bold"),
            anchor="w"
        )
        ai_header.grid(row=current_row, column=0, columnspan=2, pady=(0, 10), sticky="w")
        current_row += 1

        # Switch de habilitación de IA
        self.ai_enabled_var = ctk.BooleanVar(value=True)
        self.ai_switch = ctk.CTkSwitch(
            self.scroll_frame,
            text="Activar Validación de Entradas y SL/TP con IA",
            variable=self.ai_enabled_var,
            font=("Arial", 12, "bold")
        )
        self.ai_switch.grid(row=current_row, column=0, columnspan=2, pady=(0, 8), sticky="w")
        current_row += 1

        # 1. SELECT DE PROVEEDOR DE IA
        provider_lbl = ctk.CTkLabel(self.scroll_frame, text="Proveedor de IA:", anchor="w")
        provider_lbl.grid(row=current_row, column=0, padx=(5, 10), pady=4, sticky="w")

        provider_names = list(PROVIDER_PRESETS.keys())
        self.provider_menu = ctk.CTkOptionMenu(
            self.scroll_frame,
            values=provider_names,
            variable=self.selected_provider,
            command=self._on_provider_change,
            fg_color="#374151",
            button_color="#4B5563"
        )
        self.provider_menu.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
        current_row += 1

        # 2. SELECT DINÁMICO DE MODELO DE IA
        model_lbl = ctk.CTkLabel(self.scroll_frame, text="Modelo de IA:", anchor="w")
        model_lbl.grid(row=current_row, column=0, padx=(5, 10), pady=4, sticky="w")

        model_select_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        model_select_frame.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
        model_select_frame.grid_columnconfigure(0, weight=1)

        initial_provider = self.selected_provider.get()
        initial_models = PROVIDER_PRESETS.get(initial_provider, {}).get("models", ["gemini-2.5-flash"])

        self.model_menu = ctk.CTkOptionMenu(
            model_select_frame,
            values=initial_models,
            variable=self.selected_model,
            fg_color="#1E293B",
            button_color="#334155"
        )
        self.model_menu.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.btn_fetch_models = ctk.CTkButton(
            model_select_frame,
            text="🔄 Actualizar",
            width=85,
            command=self._fetch_models_async,
            fg_color="#4B5563",
            hover_color="#374151"
        )
        self.btn_fetch_models.grid(row=0, column=1, sticky="e")
        current_row += 1

        # 3. API KEY Y URL BASE
        labels_ai_inputs = [
            ("API Key (Secret Token):", "ai_api_key_entry"),
            ("URL Base / Proxy (Opcional):", "ai_base_url_entry"),
        ]

        for label_text, key in labels_ai_inputs:
            lbl = ctk.CTkLabel(self.scroll_frame, text=label_text, anchor="w")
            lbl.grid(row=current_row, column=0, padx=(5, 10), pady=4, sticky="w")

            entry = ctk.CTkEntry(self.scroll_frame, show="*" if "api_key" in key else "")
            entry.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
            self.entries[key] = entry
            current_row += 1

        # Botones de Prueba en la sección inferior
        test_buttons_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        test_buttons_frame.grid(row=current_row, column=0, columnspan=2, pady=(10, 5), sticky="ew")
        test_buttons_frame.grid_columnconfigure((0, 1), weight=1)
        current_row += 1

        self.btn_test_mt5 = ctk.CTkButton(
            test_buttons_frame,
            text="🔍 Probar MT5",
            command=self._test_connection,
            fg_color="#3B82F6"
        )
        self.btn_test_mt5.grid(row=0, column=0, padx=4, sticky="ew")

        self.btn_test_ai = ctk.CTkButton(
            test_buttons_frame,
            text="🧠 Probar Conexión IA",
            command=self._test_ai_connection_async,
            fg_color="#8B5CF6"
        )
        self.btn_test_ai.grid(row=0, column=1, padx=4, sticky="ew")

        # Label de Estado
        self.status_label = ctk.CTkLabel(self.scroll_frame, text="", font=("Arial", 11), wraplength=480)
        self.status_label.grid(row=current_row, column=0, columnspan=2, pady=(8, 4))
        current_row += 1

        # Botón Guardar en la barra fija inferior
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=1, column=0, pady=(5, 15), padx=20, sticky="ew")
        bottom_frame.grid_columnconfigure(0, weight=1)

        self.btn_save = ctk.CTkButton(
            bottom_frame,
            text="💾 Guardar Toda la Configuración",
            command=self._save,
            height=36,
            font=("Arial", 13, "bold"),
            fg_color="#10B981"
        )
        self.btn_save.grid(row=0, column=0, sticky="ew")

    def _on_provider_change(self, choice: str) -> None:
        """Actualiza los modelos disponibles y valores por defecto al cambiar de proveedor."""
        preset = PROVIDER_PRESETS.get(choice, PROVIDER_PRESETS["Google Gemini"])
        models = preset.get("models", [])
        default_m = preset.get("default_model", models[0] if models else "")

        self.model_menu.configure(values=models)
        self.selected_model.set(default_m)

        # Si el campo URL base está vacío o tenía el default del anterior proveedor, sugerir el nuevo
        if "ai_base_url_entry" in self.entries:
            current_url = self.entries["ai_base_url_entry"].get().strip()
            if not current_url or any(p.get("default_url") == current_url for p in PROVIDER_PRESETS.values()):
                self.entries["ai_base_url_entry"].delete(0, "end")
                if choice != "Google Gemini":
                    self.entries["ai_base_url_entry"].insert(0, preset.get("default_url", ""))

    def _fetch_models_async(self) -> None:
        """Consulta dinámicamente la lista de modelos desde la API del proveedor."""
        provider = self.selected_provider.get()
        api_key = self.entries.get("ai_api_key_entry", ctk.CTkEntry(self)).get().strip()
        base_url = self.entries.get("ai_base_url_entry", ctk.CTkEntry(self)).get().strip()

        self.status_label.configure(text=f"⏳ Consultando modelos disponibles de {provider}...", text_color="yellow")
        self.btn_fetch_models.configure(state="disabled")

        def run_fetch():
            ok, models, msg = fetch_available_models(provider=provider, api_key=api_key, base_url=base_url)
            self.after(0, lambda: self._on_models_fetched(ok, models, msg))

        threading.Thread(target=run_fetch, daemon=True).start()

    def _on_models_fetched(self, ok: bool, models: List[str], msg: str) -> None:
        self.btn_fetch_models.configure(state="normal")
        if models:
            self.model_menu.configure(values=models)
            if self.selected_model.get() not in models:
                self.selected_model.set(models[0])
        self.status_label.configure(text=msg, text_color="#10B981" if ok else "#EF4444")

    def _load_values(self) -> None:
        self.entries["login_entry"].insert(0, str(self.config_data.get("login", "")))
        self.entries["password_entry"].insert(0, str(self.config_data.get("password", "")))
        self.entries["server_entry"].insert(0, str(self.config_data.get("server", "")))
        self.entries["suffix_entry"].insert(0, str(self.config_data.get("symbol_suffix", "")))
        self.entries["path_entry"].insert(0, str(self.config_data.get("path", "")))
        self.entries["magic_entry"].insert(0, str(self.config_data.get("magic_number", 999111)))
        self.entries["slippage_entry"].insert(0, str(self.config_data.get("max_slippage", 10)))

        # Valores de IA
        self.ai_enabled_var.set(self.config_data.get("ai_enabled", True))
        provider = self.config_data.get("ai_provider", "Google Gemini")
        if provider in PROVIDER_PRESETS:
            self.selected_provider.set(provider)
            self._on_provider_change(provider)

        saved_model = self.config_data.get("ai_model", "gemini-2.5-flash")
        self.selected_model.set(saved_model)

        self.entries["ai_api_key_entry"].insert(0, str(self.config_data.get("ai_api_key", "")))
        self.entries["ai_base_url_entry"].insert(0, str(self.config_data.get("ai_base_url", "")))

    def _get_form_data(self) -> Dict[str, Any]:
        data = self.config_data.copy()
        raw_login = self.entries["login_entry"].get().strip()
        try:
            login_val = int(raw_login) if raw_login else 0
        except ValueError:
            login_val = 0

        data.update({
            "login": login_val,
            "password": self.entries["password_entry"].get().strip(),
            "server": self.entries["server_entry"].get().strip(),
            "symbol_suffix": self.entries["suffix_entry"].get().strip(),
            "path": self.entries["path_entry"].get().strip(),
            "magic_number": int(self.entries["magic_entry"].get().strip() or 999111),
            "max_slippage": int(self.entries["slippage_entry"].get().strip() or 10),
            # Campos de IA
            "ai_enabled": self.ai_enabled_var.get(),
            "ai_provider": self.selected_provider.get(),
            "ai_api_key": self.entries["ai_api_key_entry"].get().strip(),
            "ai_model": self.selected_model.get().strip() or "gemini-2.5-flash",
            "ai_base_url": self.entries["ai_base_url_entry"].get().strip(),
        })
        return data

    def _validate_inputs(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """Valida que los campos obligatorios para MT5 no estén vacíos."""
        if not data.get("login") or data.get("login") <= 0:
            return False, "❌ Debe ingresar un ID de Cuenta (Login) numérico válido."
        if not data.get("password"):
            return False, "❌ Debe ingresar la contraseña de su cuenta MT5."
        if not data.get("server"):
            return False, "❌ Debe ingresar el Servidor del Bróker (ej: MetaQuotes-Demo)."
        return True, "Ok"

    def _test_connection(self) -> None:
        data = self._get_form_data()
        is_valid, msg = self._validate_inputs(data)
        if not is_valid:
            self.status_label.configure(text=msg, text_color="#EF4444")
            return

        self.status_label.configure(text="Intentando conectar a MT5...", text_color="yellow")
        self.update()

        init_kwargs = {}
        if data["path"]:
            init_kwargs["path"] = data["path"]

        if not mt5.initialize(**init_kwargs):
            self.status_label.configure(text=f"❌ Error al inicializar MT5: {mt5.last_error()}", text_color="#EF4444")
            return

        authorized = mt5.login(login=data["login"], password=data["password"], server=data["server"])

        if authorized:
            acc_info = mt5.account_info()
            broker = acc_info.company if acc_info else "Desconocido"
            self.status_label.configure(
                text=f"✅ MT5 Conectado exitosamente | Bróker: {broker}", text_color="#10B981"
            )
        else:
            self.status_label.configure(
                text=f"❌ Fallo de autenticación en MT5: {mt5.last_error()}", text_color="#EF4444"
            )

        mt5.shutdown()

    def _test_ai_connection_async(self) -> None:
        """Prueba la API Key y conexión con el modelo de IA en un hilo secundario para no congelar la UI."""
        api_key = self.entries["ai_api_key_entry"].get().strip()
        model = self.selected_model.get().strip() or "gemini-2.5-flash"
        base_url = self.entries["ai_base_url_entry"].get().strip()

        if not api_key:
            self.status_label.configure(text="❌ Ingrese una API Key para probar la conexión con la IA.", text_color="#EF4444")
            return

        self.status_label.configure(text=f"⏳ Conectando y probando {model}...", text_color="yellow")
        self.btn_test_ai.configure(state="disabled")

        def run_test():
            success, msg = test_ai_connection(api_key=api_key, model_name=model, base_url=base_url)
            self.after(0, lambda: self._on_ai_test_finished(success, msg))

        threading.Thread(target=run_test, daemon=True).start()

    def _on_ai_test_finished(self, success: bool, message: str) -> None:
        self.btn_test_ai.configure(state="normal")
        self.status_label.configure(
            text=message,
            text_color="#10B981" if success else "#EF4444"
        )

    def _save(self) -> None:
        try:
            data = self._get_form_data()
            is_valid, msg = self._validate_inputs(data)
            if not is_valid:
                self.status_label.configure(text=msg, text_color="#EF4444")
                return

            current_config = load_config()

            # Mantener active_symbols y configuraciones de lotes/riesgo
            data["active_symbols"] = current_config.get("active_symbols", [])
            data["symbol_lots"] = current_config.get("symbol_lots", {})
            data["symbol_risk_pcts"] = current_config.get("symbol_risk_pcts", {})
            data["symbol_timeframes"] = current_config.get("symbol_timeframes", {})
            data["selected_strategy"] = current_config.get("selected_strategy", "forex")

            # Intentar conectarse a MT5 para descargar todos los símbolos del broker
            init_kwargs = {}
            if data.get("path"):
                init_kwargs["path"] = data["path"]

            self.status_label.configure(text="Guardando y sincronizando con MT5...", text_color="yellow")
            self.update()

            if mt5.initialize(**init_kwargs):
                if data.get("login") and data.get("password") and data.get("server"):
                    mt5.login(
                        login=int(data["login"]),
                        password=str(data["password"]),
                        server=str(data["server"])
                    )

                broker_symbols = get_all_available_symbols()
                if broker_symbols:
                    data["available_symbols"] = broker_symbols
                    data["symbol_specs"] = get_all_symbol_specs(broker_symbols)

                mt5.shutdown()

            if save_config(data):
                self.status_label.configure(
                    text="✅ Configuración guardada exitosamente",
                    text_color="#10B981"
                )
                if self.on_save_callback:
                    self.on_save_callback()
                self.after(1000, self.destroy)
            else:
                self.status_label.configure(
                    text="❌ Error al guardar config.json",
                    text_color="#EF4444"
                )
        except Exception as e:
            self.status_label.configure(
                text=f"❌ Error: {str(e)}",
                text_color="#EF4444"
            )
