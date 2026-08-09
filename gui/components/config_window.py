# gui/config_window.py
import customtkinter as ctk
import MetaTrader5 as mt5
from tkinter import filedialog
from typing import Callable, Optional, Dict, Any
from core.config_manager import load_config, save_config
from core.connector import get_all_available_symbols


class ConfigWindow(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, on_save_callback: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent)
        self.title("Configuración de Conexión & Bot")
        self.geometry("520x580")
        self.resizable(False, False)

        self.transient(parent)
        self.grab_set()

        self.on_save_callback: Optional[Callable[[], None]] = on_save_callback
        self.config_data: Dict[str, Any] = load_config()
        self.entries: Dict[str, ctk.CTkEntry] = {}

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
        self.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(self, text="⚙️ Configuración MT5 & Parámetros", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(15, 15), padx=20, sticky="ew")

        labels = [
            ("ID de Cuenta (Login):", "login_entry"),
            ("Contraseña:", "password_entry"),
            ("Servidor Bróker:", "server_entry"),
            ("Sufijo de Símbolo (ej: .m):", "suffix_entry"),
            ("Ruta terminal64.exe (Opcional):", "path_entry"),
            ("Magic Number (ID Bot):", "magic_entry"),
            ("Max Slippage (puntos):", "slippage_entry"),
        ]

        for idx, (label_text, key) in enumerate(labels, start=1):
            lbl = ctk.CTkLabel(self, text=label_text, anchor="w")
            lbl.grid(row=idx, column=0, padx=(20, 10), pady=6, sticky="w")

            if key == "path_entry":
                path_frame = ctk.CTkFrame(self, fg_color="transparent")
                path_frame.grid(row=idx, column=1, padx=(0, 20), pady=6, sticky="ew")
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
                entry = ctk.CTkEntry(self, show=show_char)
                entry.grid(row=idx, column=1, padx=(0, 20), pady=6, sticky="ew")
                self.entries[key] = entry

        self.status_label = ctk.CTkLabel(self, text="", font=("Arial", 11))
        self.status_label.grid(row=8, column=0, columnspan=2, pady=(10, 5))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=9, column=0, columnspan=2, pady=15, padx=20, sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_test = ctk.CTkButton(btn_frame, text="🔍 Probar Conexión", command=self._test_connection, fg_color="#3B82F6")
        self.btn_test.grid(row=0, column=0, padx=5, sticky="ew")

        self.btn_save = ctk.CTkButton(btn_frame, text="💾 Guardar", command=self._save, fg_color="#10B981")
        self.btn_save.grid(row=0, column=1, padx=5, sticky="ew")

    def _load_values(self) -> None:
        self.entries["login_entry"].insert(0, str(self.config_data.get("login", "")))
        self.entries["password_entry"].insert(0, str(self.config_data.get("password", "")))
        self.entries["server_entry"].insert(0, str(self.config_data.get("server", "")))
        self.entries["suffix_entry"].insert(0, str(self.config_data.get("symbol_suffix", "")))
        self.entries["path_entry"].insert(0, str(self.config_data.get("path", "")))
        self.entries["magic_entry"].insert(0, str(self.config_data.get("magic_number", 999111)))
        self.entries["slippage_entry"].insert(0, str(self.config_data.get("max_slippage", 10)))

    def _get_form_data(self) -> Dict[str, Any]:
        # Mantener las listas existentes al construir el diccionario
        data = self.config_data.copy()
        data.update({
            "login": int(self.entries["login_entry"].get().strip() or 0),
            "password": self.entries["password_entry"].get().strip(),
            "server": self.entries["server_entry"].get().strip(),
            "symbol_suffix": self.entries["suffix_entry"].get().strip(),
            "path": self.entries["path_entry"].get().strip(),
            "magic_number": int(self.entries["magic_entry"].get().strip() or 999111),
            "max_slippage": int(self.entries["slippage_entry"].get().strip() or 10),
        })
        return data

    def _test_connection(self) -> None:
        data = self._get_form_data()
        self.status_label.configure(text="Intentando conectar a MT5...", text_color="yellow")
        self.update()

        init_kwargs = {}
        if data["path"]:
            init_kwargs["path"] = data["path"]

        if not mt5.initialize(**init_kwargs):
            self.status_label.configure(text=f"Error al inicializar MT5: {mt5.last_error()}", text_color="#EF4444")
            return

        authorized = mt5.login(login=data["login"], password=data["password"], server=data["server"])

        if authorized:
            acc_info = mt5.account_info()
            broker = acc_info.company if acc_info else "Desconocido"
            self.status_label.configure(
                text=f"✅ Conexión exitosa | Bróker: {broker}", text_color="#10B981"
            )
        else:
            self.status_label.configure(
                text=f"❌ Fallo de autenticación: {mt5.last_error()}", text_color="#EF4444"
            )

        mt5.shutdown()

    def _save(self) -> None:
        try:
            data = self._get_form_data()

            # Cargar la configuración actual para preservar 'active_symbols' o 'max_risk_usd' si no están en la ventana modal
            current_config = load_config()

            # Mantener los active_symbols con sus lotes actuales si existen
            data["active_symbols"] = current_config.get("active_symbols", {})
            data["max_risk_usd"] = current_config.get("max_risk_usd", 10.0)

            # Intentar conectarse a MT5 para descargar todos los símbolos del broker
            init_kwargs = {}
            if data.get("path"):
                init_kwargs["path"] = data["path"]

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

              mt5.shutdown()

            # Guardar en config.json
            if save_config(data):
              self.status_label.configure(
                  text="✅ Configuración guardada y símbolos actualizados",
                  text_color="#10B981"
              )
              if self.on_save_callback:
                  self.on_save_callback()
              self.after(1200, self.destroy)
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
