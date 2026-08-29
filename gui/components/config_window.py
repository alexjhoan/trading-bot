# gui/config_window.py
import threading
import customtkinter as ctk
import MetaTrader5 as mt5
from tkinter import filedialog
from typing import Callable, Optional, Dict, Any, Tuple, List
from core.config_manager import load_config, save_config
from core.connector import get_all_available_symbols, get_all_symbol_specs
from core.ai_advisor import test_ai_connection, fetch_available_models, PROVIDER_PRESETS
from core.licensing import (
    generate_client_key_id,
    parse_client_key_id,
    verify_license_token,
)


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
            ("Reentradas Máx. por Par (0 a 5):", "max_reentries_entry"),
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

        # 3. API KEY (VISIBLE POR DEFECTO PARA VERIFICACIÓN)
        api_key_lbl = ctk.CTkLabel(self.scroll_frame, text="API Key (Token de Acceso):", anchor="w")
        api_key_lbl.grid(row=current_row, column=0, padx=(5, 10), pady=4, sticky="w")

        api_key_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        api_key_frame.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
        api_key_frame.grid_columnconfigure(0, weight=1)

        self.api_key_visible = True
        self.api_key_entry = ctk.CTkEntry(api_key_frame, show="", placeholder_text="Pega aquí tu API Key...")
        self.api_key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.entries["ai_api_key_entry"] = self.api_key_entry

        self.btn_toggle_key = ctk.CTkButton(
            api_key_frame,
            text="👁️ Ocultar",
            width=85,
            command=self._toggle_api_key_visibility,
            fg_color="#374151",
            hover_color="#4B5563"
        )
        self.btn_toggle_key.grid(row=0, column=1, sticky="e")
        current_row += 1

        # 4. URL BASE / PROXY (OPCIONAL)
        url_lbl = ctk.CTkLabel(self.scroll_frame, text="URL Base / Proxy (Opcional):", anchor="w")
        url_lbl.grid(row=current_row, column=0, padx=(5, 10), pady=4, sticky="w")

        url_entry = ctk.CTkEntry(self.scroll_frame, placeholder_text="https://generativelanguage.googleapis.com...")
        url_entry.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
        self.entries["ai_base_url_entry"] = url_entry
        current_row += 1

        # 5. SWITCH PARA MODO THINKING (RAZONAMIENTO PROFUNDO)
        self.ai_thinking_enabled_var = ctk.BooleanVar(value=False)
        self.ai_thinking_switch = ctk.CTkSwitch(
            self.scroll_frame,
            text="Activar Razonamiento Profundo (Thinking / Reasoning)",
            variable=self.ai_thinking_enabled_var,
            command=self._on_thinking_switch_toggle,
            font=("Arial", 12, "bold"),
            progress_color="#8B5CF6"
        )
        self.ai_thinking_switch.grid(row=current_row, column=0, columnspan=2, pady=(8, 4), sticky="w")
        current_row += 1

        # Cuadro de Advertencia de Thinking (se muestra al pasar a ON)
        self.thinking_warning_frame = ctk.CTkFrame(
            self.scroll_frame,
            fg_color="#3B2607",
            border_color="#D97706",
            border_width=1,
            corner_radius=6
        )
        self.thinking_warning_label = ctk.CTkLabel(
            self.thinking_warning_frame,
            text="⚠️ Advertencia: El modo Thinking incrementa la profundidad analítica,\npero aumenta el tiempo de respuesta (latencia) y genera mayor consumo de tokens en la API.",
            font=("Arial", 11),
            text_color="#FDE68A",
            justify="left"
        )
        self.thinking_warning_label.pack(padx=10, pady=6, fill="x")
        self.thinking_warning_row = current_row
        # Por defecto oculto hasta que se active
        current_row += 1


        # ----------------------------------------------------
        # SECCIÓN 3: SEGURIDAD & LICENCIA DEL BOT
        # ----------------------------------------------------
        lic_separator = ctk.CTkFrame(self.scroll_frame, height=2, fg_color="#374151")
        lic_separator.grid(row=current_row, column=0, columnspan=2, pady=(15, 10), sticky="ew")
        current_row += 1

        lic_header = ctk.CTkLabel(
            self.scroll_frame,
            text="🔐 Licencia & Hardware Binding (Seguridad)",
            font=("Arial", 15, "bold"),
            anchor="w"
        )
        lic_header.grid(row=current_row, column=0, columnspan=2, pady=(0, 10), sticky="w")
        current_row += 1

        # 1. KEY ID (Hardware ID + Cuenta MT5 empaquetados) con botón de copiar
        mid_lbl = ctk.CTkLabel(self.scroll_frame, text="KEY ID:", anchor="w")
        mid_lbl.grid(row=current_row, column=0, padx=(5, 10), pady=4, sticky="w")

        mid_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        mid_frame.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
        mid_frame.grid_columnconfigure(0, weight=1)

        saved_login = int(self.config_data.get("login", 0))
        self.key_id_val = generate_client_key_id(saved_login)
        self.machine_id_val, _ = parse_client_key_id(self.key_id_val)
        self.mid_entry = ctk.CTkEntry(mid_frame, fg_color="#181b22", text_color="#38BDF8", font=("Arial", 11))
        self.mid_entry.insert(0, self.key_id_val)
        self.mid_entry.configure(state="readonly")
        self.mid_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.btn_copy_mid = ctk.CTkButton(
            mid_frame,
            text="📋 Copiar",
            width=75,
            command=self._copy_machine_id,
            fg_color="#0284C7",
            hover_color="#0369A1"
        )
        self.btn_copy_mid.grid(row=0, column=1, sticky="e")
        current_row += 1

        # 2. Clave de Licencia Token
        lic_lbl = ctk.CTkLabel(self.scroll_frame, text="Clave de Licencia (Token):", anchor="w")
        lic_lbl.grid(row=current_row, column=0, padx=(5, 10), pady=4, sticky="w")

        lic_entry = ctk.CTkEntry(self.scroll_frame, placeholder_text="Pega aquí tu llave de validación...")
        lic_entry.grid(row=current_row, column=1, padx=(0, 5), pady=4, sticky="ew")
        self.entries["license_key_entry"] = lic_entry
        current_row += 1

        # Botones de Prueba en la sección inferior
        test_buttons_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        test_buttons_frame.grid(row=current_row, column=0, columnspan=2, pady=(10, 5), sticky="ew")
        test_buttons_frame.grid_columnconfigure((0, 1, 2), weight=1)
        current_row += 1

        self.btn_test_lic = ctk.CTkButton(
            test_buttons_frame,
            text="🔑 Validar Licencia",
            command=self._test_license_validation,
            fg_color="#059669",
            hover_color="#047857"
        )
        self.btn_test_lic.grid(row=0, column=0, padx=3, sticky="ew")

        self.btn_test_mt5 = ctk.CTkButton(
            test_buttons_frame,
            text="🔍 Probar MT5",
            command=self._test_connection,
            fg_color="#3B82F6"
        )
        self.btn_test_mt5.grid(row=0, column=1, padx=3, sticky="ew")

        self.btn_test_ai = ctk.CTkButton(
            test_buttons_frame,
            text="🧠 Probar IA",
            command=self._test_ai_connection_async,
            fg_color="#8B5CF6"
        )
        self.btn_test_ai.grid(row=0, column=2, padx=3, sticky="ew")

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

    def _toggle_api_key_visibility(self) -> None:
        """Alterna la visibilidad del texto de la API Key para que el usuario verifique lo copiado."""
        if self.api_key_visible:
            self.api_key_entry.configure(show="*")
            self.btn_toggle_key.configure(text="👁️ Mostrar")
            self.api_key_visible = False
        else:
            self.api_key_entry.configure(show="")
            self.btn_toggle_key.configure(text="👁️ Ocultar")
            self.api_key_visible = True

    def _on_thinking_switch_toggle(self) -> None:
        """Muestra u oculta la advertencia de latencia/tokens y ajusta el thinking budget por defecto a 128."""
        is_enabled = self.ai_thinking_enabled_var.get()
        if is_enabled:
            self.thinking_warning_frame.grid(
                row=self.thinking_warning_row,
                column=0,
                columnspan=2,
                padx=5,
                pady=(4, 8),
                sticky="ew"
            )
        else:
            self.thinking_warning_frame.grid_forget()

    def _copy_machine_id(self) -> None:
        """Copia el key ID al portapapeles del sistema."""
        try:
            raw_login = self.entries["login_entry"].get().strip()
            try:
                cur_acc = int(raw_login) if raw_login else 0
            except ValueError:
                cur_acc = 0
            self.key_id_val = generate_client_key_id(cur_acc)
            self.mid_entry.configure(state="normal")
            self.mid_entry.delete(0, "end")
            self.mid_entry.insert(0, self.key_id_val)
            self.mid_entry.configure(state="readonly")

            self.clipboard_clear()
            self.clipboard_append(self.key_id_val)
            self.update()
            self.status_label.configure(
                text=f"📋 KEY ID copiado al portapapeles (Hardware + Cuenta #{cur_acc}). Pégalo y envíaselo al desarrollador.",
                text_color="#38BDF8"
            )
        except Exception as e:
            self.status_label.configure(text=f"Error copiando al portapapeles: {e}", text_color="#EF4444")

    def _test_license_validation(self) -> None:
        """Prueba en vivo la clave de licencia introducida."""
        token = self.entries.get("license_key_entry", ctk.CTkEntry(self)).get().strip()
        if not token:
            self.status_label.configure(
                text="❌ Ingrese una clave de licencia (Token) para validar.",
                text_color="#EF4444"
            )
            return

        raw_login = self.entries["login_entry"].get().strip()
        try:
            current_login = int(raw_login) if raw_login else 0
        except ValueError:
            current_login = 0

        is_valid, msg, payload = verify_license_token(
            token=token,
            current_account_login=current_login,
            current_machine_id=self.machine_id_val
        )

        self.status_label.configure(
            text=msg,
            text_color="#10B981" if is_valid else "#EF4444"
        )

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
        if "max_reentries_entry" in self.entries:
            self.entries["max_reentries_entry"].insert(0, str(self.config_data.get("max_reentries", 0)))

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

        # Configuración de Thinking y Thinking Budget
        saved_budget = int(self.config_data.get("ai_thinking_budget", 0))
        saved_thinking_on = bool(self.config_data.get("ai_thinking_enabled", False) or (saved_budget > 0))
        self.ai_thinking_enabled_var.set(saved_thinking_on)

        self._on_thinking_switch_toggle()

        # Valor de Licencia
        if "license_key_entry" in self.entries:
            self.entries["license_key_entry"].insert(0, str(self.config_data.get("license_key", "")))

    def _get_form_data(self) -> Dict[str, Any]:
        data = self.config_data.copy()
        raw_login = self.entries["login_entry"].get().strip()
        try:
            login_val = int(raw_login) if raw_login else 0
        except ValueError:
            login_val = 0

        is_thinking_on = bool(self.ai_thinking_enabled_var.get())
        final_budget = int(self.config_data.get("ai_thinking_budget", 128)) if is_thinking_on else 0
        if is_thinking_on and final_budget <= 0:
            final_budget = 128

        data.update({
            "login": login_val,
            "password": self.entries["password_entry"].get().strip(),
            "server": self.entries["server_entry"].get().strip(),
            "symbol_suffix": self.entries["suffix_entry"].get().strip(),
            "path": self.entries["path_entry"].get().strip(),
            "magic_number": int(self.entries["magic_entry"].get().strip() or 999111),
            "max_slippage": int(self.entries["slippage_entry"].get().strip() or 10),
            "max_reentries": max(0, min(5, int(self.entries["max_reentries_entry"].get().strip() or 0))) if "max_reentries_entry" in self.entries else 0,
            # Campos de IA
            "ai_enabled": self.ai_enabled_var.get(),
            "ai_provider": self.selected_provider.get(),
            "ai_api_key": self.entries["ai_api_key_entry"].get().strip(),
            "ai_model": self.selected_model.get().strip() or "gemini-2.5-flash",
            "ai_base_url": self.entries["ai_base_url_entry"].get().strip(),
            "ai_thinking_enabled": is_thinking_on,
            "ai_thinking_budget": final_budget,
            # Campo de Licencia
            "license_key": self.entries["license_key_entry"].get().strip() if "license_key_entry" in self.entries else "",
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
