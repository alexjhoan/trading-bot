import customtkinter as ctk
from typing import Callable, Dict, Any, Optional
from .config_window import ConfigWindow


class TopbarComponent(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        on_test_order_callback: Optional[Callable[[], None]] = None,
        on_config_saved_callback: Optional[Callable[[], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(master, height=60, fg_color="#1f1f1f", corner_radius=8, **kwargs)

        self.on_test_order_callback = on_test_order_callback
        self.on_config_saved_callback = on_config_saved_callback

        self._build_ui()

    def _build_ui(self) -> None:
        # Título / Logo
        lbl_title = ctk.CTkLabel(
            self,
            text="🤖 Quant Trading Bot",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        lbl_title.pack(side="left", padx=15, pady=10)

        # Card Info Cuenta (Balance & Equidad)
        account_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=6)
        account_frame.pack(side="left", padx=15, pady=8)

        self.lbl_balance = ctk.CTkLabel(
            account_frame,
            text="💰 Balance: $0.00",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.lbl_balance.pack(side="left", padx=(10, 15), pady=5)

        self.lbl_equity = ctk.CTkLabel(
            account_frame,
            text="📊 Equidad: $0.00",
            font=ctk.CTkFont(size=13)
        )
        self.lbl_equity.pack(side="left", padx=(0, 10), pady=5)

        # Switch Modo Test
        self.switch_test_mode = ctk.CTkSwitch(
            self,
            text="🧪 Modo Test (Forzar BUY)",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.switch_test_mode.pack(side="left", padx=15, pady=10)

        # Botón Orden Test
        self.btn_test_order = ctk.CTkButton(
            self,
            text="🧪 ORDEN TEST",
            fg_color="#D97706",
            hover_color="#B45309",
            width=120,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_test_click
        )
        self.btn_test_order.pack(side="right", padx=(5, 15), pady=10)

        # Botón Configuración MT5
        self.btn_config = ctk.CTkButton(
            self,
            text="🔌 CONEXIÓN MT5",
            fg_color="#1D4ED8",
            hover_color="#2563EB",
            width=130,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_config_modal
        )
        self.btn_config.pack(side="right", padx=5, pady=10)

    def _open_config_modal(self) -> None:
        ConfigWindow(parent=self, on_save_callback=self._reload_config)

    def _reload_config(self) -> None:
        if self.on_config_saved_callback:
            self.on_config_saved_callback()

    def _on_test_click(self) -> None:
        if self.on_test_order_callback:
            self.on_test_order_callback()

    def update_account_info(self, balance: float, equity: float) -> None:
        """Actualiza las etiquetas de Balance y Equidad."""
        self.lbl_balance.configure(text=f"💰 Balance: ${balance:,.2f}")
        self.lbl_equity.configure(text=f"📊 Equidad: ${equity:,.2f}")

    def get_topbar_values(self) -> Dict[str, Any]:
        """Retorna los parámetros configurados en el Topbar (modo test)."""
        return {
            "test_mode": self.switch_test_mode.get() == 1
        }
