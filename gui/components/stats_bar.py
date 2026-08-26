import customtkinter as ctk
from typing import Callable, Dict, Any, Optional


class StatsBarComponent(ctk.CTkFrame):
    """
    Componente de Estadísticas en Tiempo Real situado debajo del Topbar:
    - Muestra operaciones cerradas positivas (Wins), negativas (Losses), totales y balance neto del período.
    - Incluye selector de filtro con opciones 'Día' (por defecto) o 'Semana'.
    - Incluye selector de horario entre 'Hora Broker' y 'Hora Local'.
    - Permite guardar y recordar la selección del usuario entre sesiones.
    """
    def __init__(
        self,
        master: Any,
        selected_period: str = "Día",
        selected_time_mode: str = "Hora Broker",
        on_filter_changed_callback: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(master, height=72, fg_color="#181a20", corner_radius=8, **kwargs)

        self.selected_period = selected_period if selected_period in ("Día", "Semana") else "Día"
        self.selected_time_mode = selected_time_mode if selected_time_mode in ("Hora Broker", "Hora Local") else "Hora Broker"
        self.on_filter_changed_callback = on_filter_changed_callback

        self._build_ui()

    def _build_ui(self) -> None:
        # Configurar Grid de 4 columnas (Col 0: Filtros, Col 1: Positivas, Col 2: Negativas, Col 3: Balance Neto)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self.grid_columnconfigure(3, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # -------------------------------------------------------------
        # 1. Filtros (Período: Día/Semana + Horario: Broker/Local)
        # -------------------------------------------------------------
        filter_frame = ctk.CTkFrame(self, fg_color="#222631", corner_radius=6)
        filter_frame.grid(row=0, column=0, padx=(10, 8), pady=6, sticky="nsw")

        # Período
        lbl_period = ctk.CTkLabel(
            filter_frame,
            text="📅 Período:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94A3B8"
        )
        lbl_period.grid(row=0, column=0, padx=(8, 4), pady=(4, 2), sticky="w")

        self.seg_period = ctk.CTkSegmentedButton(
            filter_frame,
            values=["Día", "Semana"],
            command=self._handle_period_change,
            selected_color="#2563EB",
            selected_hover_color="#1D4ED8",
            unselected_color="#181B22",
            unselected_hover_color="#2D3748",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=24
        )
        self.seg_period.set(self.selected_period)
        self.seg_period.grid(row=0, column=1, padx=(0, 8), pady=(4, 2), sticky="w")

        # Horario (Broker vs Local)
        lbl_tz = ctk.CTkLabel(
            filter_frame,
            text="🕒 Horario:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94A3B8"
        )
        lbl_tz.grid(row=1, column=0, padx=(8, 4), pady=(2, 4), sticky="w")

        self.seg_tz = ctk.CTkSegmentedButton(
            filter_frame,
            values=["Hora Broker", "Hora Local"],
            command=self._handle_time_mode_change,
            selected_color="#0284C7",
            selected_hover_color="#0369A1",
            unselected_color="#181B22",
            unselected_hover_color="#2D3748",
            font=ctk.CTkFont(size=10, weight="bold"),
            height=24
        )
        self.seg_tz.set(self.selected_time_mode)
        self.seg_tz.grid(row=1, column=1, padx=(0, 8), pady=(2, 4), sticky="w")

        # -------------------------------------------------------------
        # 2. Card: Operaciones Positivas (Ganadoras)
        # -------------------------------------------------------------
        win_card = ctk.CTkFrame(self, fg_color="#13241B", border_color="#065F46", border_width=1, corner_radius=6)
        win_card.grid(row=0, column=1, padx=4, pady=6, sticky="nsew")

        lbl_win_header = ctk.CTkLabel(
            win_card,
            text="🟢 CERRADAS EN POSITIVO",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#34D399"
        )
        lbl_win_header.pack(anchor="w", padx=10, pady=(4, 0))

        self.lbl_win_stats = ctk.CTkLabel(
            win_card,
            text="0 Ops  |  +$0.00 USD",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#10B981"
        )
        self.lbl_win_stats.pack(anchor="w", padx=10, pady=(0, 4))

        # -------------------------------------------------------------
        # 3. Card: Operaciones Negativas (Perdedoras)
        # -------------------------------------------------------------
        loss_card = ctk.CTkFrame(self, fg_color="#271418", border_color="#881337", border_width=1, corner_radius=6)
        loss_card.grid(row=0, column=2, padx=4, pady=6, sticky="nsew")

        lbl_loss_header = ctk.CTkLabel(
            loss_card,
            text="🔴 CERRADAS EN NEGATIVO",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#F87171"
        )
        lbl_loss_header.pack(anchor="w", padx=10, pady=(4, 0))

        self.lbl_loss_stats = ctk.CTkLabel(
            loss_card,
            text="0 Ops  |  -$0.00 USD",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#EF4444"
        )
        self.lbl_loss_stats.pack(anchor="w", padx=10, pady=(0, 4))

        # -------------------------------------------------------------
        # 4. Card: Total del Momento (Neto & Tasa de Acierto)
        # -------------------------------------------------------------
        self.net_card = ctk.CTkFrame(self, fg_color="#1A202C", border_color="#334155", border_width=1, corner_radius=6)
        self.net_card.grid(row=0, column=3, padx=(4, 10), pady=6, sticky="nsew")

        self.lbl_net_header = ctk.CTkLabel(
            self.net_card,
            text="📊 RESULTADO NETO DEL MOMENTO",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#94A3B8"
        )
        self.lbl_net_header.pack(anchor="w", padx=10, pady=(4, 0))

        self.lbl_net_stats = ctk.CTkLabel(
            self.net_card,
            text="$0.00 USD  (Win Rate: 0.0% - 0 Ops)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F8FAFC"
        )
        self.lbl_net_stats.pack(anchor="w", padx=10, pady=(0, 4))

    def _handle_period_change(self, choice: str) -> None:
        self.selected_period = choice
        if self.on_filter_changed_callback:
            self.on_filter_changed_callback(self.selected_period, self.selected_time_mode)

    def _handle_time_mode_change(self, choice: str) -> None:
        self.selected_time_mode = choice
        if self.on_filter_changed_callback:
            self.on_filter_changed_callback(self.selected_period, self.selected_time_mode)

    def get_selected_period(self) -> str:
        return self.selected_period

    def get_selected_time_mode(self) -> str:
        return self.selected_time_mode

    def set_filters(self, period: str, time_mode: str) -> None:
        self.selected_period = period if period in ("Día", "Semana") else "Día"
        self.selected_time_mode = time_mode if time_mode in ("Hora Broker", "Hora Local") else "Hora Broker"
        self.seg_period.set(self.selected_period)
        self.seg_tz.set(self.selected_time_mode)

    def update_stats(self, stats: Dict[str, Any]) -> None:
        """Actualiza todas las etiquetas numéricas a partir del cálculo de operaciones cerradas."""
        win_count = stats.get("win_count", 0)
        win_total = stats.get("win_total", 0.0)
        loss_count = stats.get("loss_count", 0)
        loss_total = stats.get("loss_total", 0.0)
        net_total = stats.get("net_total", 0.0)
        total_ops = stats.get("total_ops", 0)
        win_rate = stats.get("win_rate", 0.0)
        period_label = stats.get("period_label", "")

        # 1. Positivas
        self.lbl_win_stats.configure(text=f"{win_count} Ops  |  +${win_total:,.2f} USD")

        # 2. Negativas
        self.lbl_loss_stats.configure(text=f"{loss_count} Ops  |  -${abs(loss_total):,.2f} USD")

        # 3. Balance Neto
        sign = "+" if net_total >= 0 else "-"
        net_color = "#10B981" if net_total > 0 else ("#EF4444" if net_total < 0 else "#94A3B8")

        self.lbl_net_header.configure(text=f"📊 RESULTADO NETO ({period_label})")
        self.lbl_net_stats.configure(
            text=f"{sign}${abs(net_total):,.2f} USD  (Win Rate: {win_rate:.1f}% | {total_ops} Ops)",
            text_color=net_color
        )
