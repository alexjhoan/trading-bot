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
        **kwargs: Any
    ) -> None:
        super().__init__(master, width=280, corner_radius=0, **kwargs)

        self.on_test_order_callback: Optional[Callable[[], None]] = on_test_order_callback
        self.on_config_saved_callback: Optional[Callable[[], None]] = on_config_saved_callback

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
        self.logo_label = ctk.CTkLabel(
            self,
            text="⚙️ Parámetros Bot",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.logo_label.pack(padx=20, pady=(20, 15))

        # Inputs
        self.lbl_risk = ctk.CTkLabel(self, text="Riesgo por Trade (%):")
        self.lbl_risk.pack(anchor="w", padx=20, pady=(5, 0))
        self.entry_risk = ctk.CTkEntry(self, placeholder_text="1.0")
        self.entry_risk.insert(0, "1.0")
        self.entry_risk.pack(fill="x", padx=20, pady=(2, 10))

        self.lbl_sl = ctk.CTkLabel(self, text="Default SL (Pips):")
        self.lbl_sl.pack(anchor="w", padx=20, pady=(5, 0))
        self.entry_sl = ctk.CTkEntry(self, placeholder_text="15.0")
        self.entry_sl.insert(0, "15.0")
        self.entry_sl.pack(fill="x", padx=20, pady=(2, 10))

        self.lbl_tp = ctk.CTkLabel(self, text="Default TP (Pips):")
        self.lbl_tp.pack(anchor="w", padx=20, pady=(5, 0))
        self.entry_tp = ctk.CTkEntry(self, placeholder_text="30.0")
        self.entry_tp.insert(0, "30.0")
        self.entry_tp.pack(fill="x", padx=20, pady=(2, 10))

        # Selector Temporalidad Vela
        self.lbl_tf = ctk.CTkLabel(self, text="⏱️ Temporalidad Vela:")
        self.lbl_tf.pack(anchor="w", padx=20, pady=(5, 0))
        self.opt_tf = ctk.CTkOptionMenu(
            self,
            values=list(TIMEFRAME_OPTIONS.keys())
        )
        self.opt_tf.set("M1")
        self.opt_tf.pack(fill="x", padx=20, pady=(2, 10))

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

        # Botón Configuración
        self.btn_config = ctk.CTkButton(
            self,
            text="⚙️ CONFIGURACIÓN",
            fg_color="#3B82F6",
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
        self.btn_test_order.pack(fill="x", padx=20, pady=(5, 10))

    def get_parameters(self) -> Dict[str, Any]:
        """Retorna los valores ingresados en las entradas de texto."""
        try:
            risk = float(self.entry_risk.get())
            sl = float(self.entry_sl.get())
            tp = float(self.entry_tp.get())
        except ValueError:
            risk, sl, tp = 1.0, 15.0, 30.0

        tf_str: str = str(self.opt_tf.get())
        tf_val: int = TIMEFRAME_OPTIONS.get(tf_str, mt5.TIMEFRAME_M1)

        return {
            "risk_pct": risk,
            "sl_pips": sl,
            "tp_pips": tp,
            "timeframe_str": tf_str,
            "timeframe": tf_val,
            "test_mode": bool(self.switch_test_mode.get()),
        }

    def update_account_info(self, balance: float, equity: float) -> None:
        """Actualiza la vista de balance y equidad."""
        self.lbl_balance.configure(text=f"💰 Balance: ${balance:,.2f}")
        self.lbl_equity.configure(text=f"📊 Equidad: ${equity:,.2f}")
