import customtkinter as ctk
from typing import Callable, Dict, Any, Optional, List
from .config_window import ConfigWindow
from core.strategies import get_available_strategies


class TopbarComponent(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        selected_strategy: str = "forex",
        on_strategy_changed_callback: Optional[Callable[[str], None]] = None,
        on_config_saved_callback: Optional[Callable[[], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(master, height=60, fg_color="#1f1f1f", corner_radius=8, **kwargs)

        self.selected_strategy = selected_strategy
        self.on_strategy_changed_callback = on_strategy_changed_callback
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

        # Botón Configuración MT5 (A la derecha)
        self.btn_config = ctk.CTkButton(
            self,
            text="🔌 CONEXIÓN MT5",
            fg_color="#1D4ED8",
            hover_color="#2563EB",
            width=130,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_config_modal
        )
        self.btn_config.pack(side="right", padx=(5, 15), pady=10)

        # 🟢 Selector de Estrategia Dinámica (En reemplazo de Botón Orden Test)
        strategy_frame = ctk.CTkFrame(self, fg_color="#262626", corner_radius=6)
        strategy_frame.pack(side="right", padx=(5, 10), pady=8)

        lbl_strategy = ctk.CTkLabel(
            strategy_frame,
            text="🎯 Estrategia:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F59E0B"
        )
        lbl_strategy.pack(side="left", padx=(8, 4), pady=5)

        available_strategies: List[str] = get_available_strategies()
        if not available_strategies:
            available_strategies = ["forex", "syntx"]

        # Determinar valor inicial
        initial_val = self.selected_strategy if self.selected_strategy in available_strategies else available_strategies[0]

        self.opt_strategy = ctk.CTkOptionMenu(
            strategy_frame,
            values=available_strategies,
            command=self._on_strategy_selected,
            width=110,
            fg_color="#D97706",
            button_color="#B45309",
            button_hover_color="#92400E",
            font=ctk.CTkFont(size=12, weight="bold"),
            dropdown_font=ctk.CTkFont(size=12)
        )
        self.opt_strategy.set(initial_val)
        self.opt_strategy.pack(side="left", padx=(0, 6), pady=5)

    def _open_config_modal(self) -> None:
        ConfigWindow(parent=self, on_save_callback=self._reload_config)

    def _reload_config(self) -> None:
        if self.on_config_saved_callback:
            self.on_config_saved_callback()

    def _on_strategy_selected(self, choice: str) -> None:
        self.selected_strategy = choice
        if self.on_strategy_changed_callback:
            self.on_strategy_changed_callback(choice)

    def update_account_info(self, balance: float, equity: float) -> None:
        """Actualiza las etiquetas de Balance y Equidad."""
        self.lbl_balance.configure(text=f"💰 Balance: ${balance:,.2f}")
        self.lbl_equity.configure(text=f"📊 Equidad: ${equity:,.2f}")

    def get_selected_strategy(self) -> str:
        """Retorna la estrategia actualmente seleccionada."""
        return self.opt_strategy.get()

    def set_selected_strategy(self, strategy_name: str) -> None:
        """Establece visualmente la estrategia seleccionada."""
        self.selected_strategy = strategy_name
        self.opt_strategy.set(strategy_name)

    def get_topbar_values(self) -> Dict[str, Any]:
        """Retorna los parámetros configurados en el Topbar."""
        return {
            "test_mode": self.switch_test_mode.get() == 1,
            "strategy": self.opt_strategy.get()
        }
