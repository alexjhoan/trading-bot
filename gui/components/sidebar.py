import customtkinter as ctk
from typing import Callable, Dict, Any, Optional
import MetaTrader5 as mt5
from .config_window import ConfigWindow


TIMEFRAME_OPTIONS: Dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


class SidebarComponent(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        on_test_order_callback: Optional[Callable[[], None]] = None,
        on_config_saved_callback: Optional[Callable[[], None]] = None,
        default_risk_pct: float = 1.0,
        **kwargs: Any
    ) -> None:
        super().__init__(master, width=280, corner_radius=0, **kwargs)

        self.on_test_order_callback = on_test_order_callback
        self.on_config_saved_callback = on_config_saved_callback
        self.default_risk_pct = default_risk_pct

        self._build_ui()

    def _open_config_modal(self) -> None:
        ConfigWindow(parent=self, on_save_callback=self._reload_config)

    def _reload_config(self) -> None:
        if self.on_config_saved_callback:
            self.on_config_saved_callback()

    def _on_test_click(self) -> None:
        if self.on_test_order_callback:
            self.on_test_order_callback()

    def _build_ui(self) -> None:
        # Título
        lbl_title = ctk.CTkLabel(
            self,
            text="⚙️ Parámetros Bot",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        lbl_title.pack(padx=20, pady=(20, 15), anchor="w")

        # Timeframe OptionMenu
        lbl_tf = ctk.CTkLabel(self, text="Timeframe (Temporalidad):", font=ctk.CTkFont(weight="bold"))
        lbl_tf.pack(padx=20, pady=(5, 2), anchor="w")

        self.opt_tf = ctk.CTkOptionMenu(
            self,
            values=list(TIMEFRAME_OPTIONS.keys())
        )
        self.opt_tf.set("M1")
        self.opt_tf.pack(fill="x", padx=20, pady=(0, 15))

        # Riesgo % por Operación
        lbl_risk = ctk.CTkLabel(self, text="Riesgo Global por Operación (%):", font=ctk.CTkFont(weight="bold"))
        lbl_risk.pack(padx=20, pady=(5, 2), anchor="w")

        self.entry_risk = ctk.CTkEntry(self, placeholder_text="Ej: 1.0")
        self.entry_risk.insert(0, str(self.default_risk_pct))
        self.entry_risk.pack(fill="x", padx=20, pady=(0, 15))

        # Modo Test Switch
        self.switch_test_mode = ctk.CTkSwitch(
            self,
            text="🧪 Modo Test (Forzar BUY)",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.switch_test_mode.pack(anchor="w", padx=20, pady=(5, 10))

        # Card de Cuenta
        self.card_account = ctk.CTkFrame(self, fg_color="#2b2b2b")
        self.card_account.pack(fill="x", padx=15, pady=10)

        self.lbl_balance = ctk.CTkLabel(
            self.card_account,
            text="💰 Balance: $0.00",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.lbl_balance.pack(anchor="w", padx=15, pady=(10, 2))

        self.lbl_equity = ctk.CTkLabel(
            self.card_account,
            text="📊 Equidad: $0.00",
            font=ctk.CTkFont(size=13)
        )
        self.lbl_equity.pack(anchor="w", padx=15, pady=(0, 10))

        # Separador / Espaciador
        spacer = ctk.CTkFrame(self, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        # Botón Configuración MT5 (Modal)
        self.btn_config = ctk.CTkButton(
            self,
            text="🔌 CONEXIÓN MT5",
            fg_color="#1D4ED8",
            hover_color="#2563EB",
            font=ctk.CTkFont(weight="bold"),
            command=self._open_config_modal
        )
        self.btn_config.pack(fill="x", padx=20, pady=(10, 5))

        # Botón Orden Test
        self.btn_test_order = ctk.CTkButton(
            self,
            text="🧪 ENVIAR ORDEN TEST",
            fg_color="#D97706",
            hover_color="#B45309",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_test_click
        )
        self.btn_test_order.pack(fill="x", padx=20, pady=(5, 20))

    def update_account_info(self, balance: float, equity: float) -> None:
        """Actualiza dinámicamente las etiquetas de Balance y Equidad."""
        self.lbl_balance.configure(text=f"💰 Balance: ${balance:,.2f}")
        self.lbl_equity.configure(text=f"📊 Equidad: ${equity:,.2f}")

    def get_parameters(self) -> Dict[str, Any]:
        """Retorna los parámetros actualizados del Sidebar."""
        try:
            raw_val = float(self.entry_risk.get().replace(",", "."))
            # Si el usuario ingresa un valor como 1.0 (que significa 1%), lo convertimos a 0.01.
            # Si ingresa 0.01 (que ya es decimal), lo mantenemos.
            risk_pct = raw_val / 100.0 if raw_val >= 0.1 else raw_val
        except ValueError:
            risk_pct = 0.01  # Fallback a 1% de riesgo en caso de input inválido

        tf_str: str = str(self.opt_tf.get())
        tf_val: int = TIMEFRAME_OPTIONS.get(tf_str, mt5.TIMEFRAME_M1)

        return {
            "risk_pct": risk_pct,             # Ej: 0.01 para 1%
            "test_mode": self.switch_test_mode.get() == 1,
            "timeframe_str": tf_str,
            "timeframe_val": tf_val,
        }
