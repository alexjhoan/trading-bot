import customtkinter as ctk
from tkinter import messagebox
import threading
import time
from typing import Callable, Dict, Any, List, Optional
import MetaTrader5 as mt5

from core.backtester import (
    run_deep_search,
    find_best_timeframe,
    get_cached_results,
    get_strategy_comparison_summary,
    get_all_strategy_backtests,
    compare_strategies_for_symbol,
    get_best_strategy_per_symbol,
)
from core.strategies import get_available_strategies
from core.config_manager import load_config
from core.ai_backtest_learner import (
    train_ai_from_backtest,
    train_ai_batch_from_backtest,
    get_backtest_learnings_for_symbol,
    get_all_backtest_learnings
)
from core.ai_strategy_changelog import (
    load_all_changelogs,
    get_symbol_changelog,
    CHANGELOG_MD_FILE
)


class DeepSearchWindow(ctk.CTkToplevel):
    """
    Ventana de Deep Search y Ranking de Mejores Pares:
    - Ejecuta backtesting profundo sobre el universo de símbolos seleccionado.
    - Guarda los resultados aislados por estrategia (backtest_{estrategia}.json).
    - Muestra la tabla de Mejores Pares con métricas (Win Rate, Trades, Avg R, Veredicto).
    - Incluye el botón '📥 Montar Pares Seleccionados' para cargar automáticamente los
      pares en la vista de Mejores Pares y en symbol_selector.py.
    """

    def __init__(
        self,
        parent: Any,
        available_symbols: Optional[List[str]] = None,
        current_symbols: Optional[List[str]] = None,
        default_strategy: str = "forex",
        on_mount_symbols_callback: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        **kwargs: Any
    ) -> None:
        # CustomTkinter CTkToplevel rechaza cualquier kwarg no soportado por Tkinter
        valid_toplevel_kwargs = {"fg_color"}
        safe_kwargs = {k: v for k, v in kwargs.items() if k in valid_toplevel_kwargs}
        super().__init__(parent, **safe_kwargs)

        self.title("🔬 Deep Search & Ranking de Mejores Pares")
        self.configure(fg_color="#181a20")

        # Dimensiones y centrado adaptativo según resolución real de la pantalla
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = min(1120, max(840, int(screen_w * 0.88)))
        win_h = min(740, max(560, int(screen_h * 0.82)))
        pos_x = max(10, (screen_w - win_w) // 2)
        pos_y = max(10, (screen_h - win_h) // 2)
        self.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.minsize(760, 480)
        self.resizable(True, True)

        try:
            self.transient(parent)
        except Exception:
            pass

        self.available_symbols: List[str] = available_symbols or [
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
            "EURGBP", "EURJPY", "GBPJPY", "XAUUSD"
        ]
        self.current_symbols: List[str] = current_symbols or []
        self.selected_strategy: str = default_strategy
        self.on_mount_symbols_callback = on_mount_symbols_callback

        self._is_alive: bool = True
        self._is_running: bool = False
        self._cancel_event: Optional[threading.Event] = None
        self._worker_thread: Optional[threading.Thread] = None

        self._check_vars: Dict[str, ctk.BooleanVar] = {}
        self._results_data: List[Dict[str, Any]] = []

        # Estado para la pestaña de Comparativa
        self._comp_check_vars: Dict[str, ctk.BooleanVar] = {}
        self._comp_pairs_data: List[Dict[str, Any]] = []
        self._comp_summary_data: List[Dict[str, Any]] = []

        # Estado de ordenamiento dinámico
        self._current_sort_col: str = "win_rate"
        self._current_sort_desc: bool = True
        self._header_buttons: Dict[str, ctk.CTkButton] = {}
        self._sort_columns_info: List[Tuple[str, str, int]] = [
            ("symbol", "Símbolo", 90),
            ("strategy", "Estrategia", 85),
            ("timeframe", "Timeframe", 75),
            ("trades", "Trades", 60),
            ("win_rate", "Win Rate %", 85),
            ("avg_r", "Avg R", 85),
            ("verdict", "Veredicto", 140),
        ]

        self._build_ui()

        # Cargar resultados cacheados con un pequeño delay para evitar parpadeos y asegurar cálculo limpio de geometría
        self.after(50, self._load_cached_results)
        self.after(80, self._load_strategy_comparison)

        # Mantener foco al frente
        self.after(100, self.lift)

    def destroy(self) -> None:
        """Marca el ciclo de vida como destruido para cancelar cualquier callback asíncrono pendiente."""
        self._is_alive = False
        super().destroy()

    def _safe_ui(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Ejecuta una función en el hilo principal de Tkinter solo si la ventana y sus widgets siguen activos."""
        if not getattr(self, "_is_alive", True):
            return
        try:
            if not self.winfo_exists():
                return
            def _runner():
                try:
                    if getattr(self, "_is_alive", True) and self.winfo_exists():
                        fn(*args, **kwargs)
                except Exception:
                    pass
            self.after(0, _runner)
        except Exception:
            pass

    def _build_ui(self) -> None:
        # 1. Cabecera Principal
        header_frame = ctk.CTkFrame(self, fg_color="#1f2430", height=46, corner_radius=0)
        header_frame.pack(fill="x", padx=0, pady=0)

        lbl_title = ctk.CTkLabel(
            header_frame,
            text="🔬 Deep Search & Comparativa Multiestrategia",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#38BDF8"
        )
        lbl_title.pack(side="left", padx=16, pady=10)

        lbl_sub = ctk.CTkLabel(
            header_frame,
            text="Ranking Cuantitativo • Detección Óptima por Par • Asignación Multialgoritmo",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8"
        )
        lbl_sub.pack(side="right", padx=16, pady=10)

        # Tabview principal
        self.tabview = ctk.CTkTabview(
            self,
            fg_color="#161a23",
            segmented_button_selected_color="#0284C7",
            segmented_button_selected_hover_color="#0369A1",
            segmented_button_unselected_color="#1f2430",
            segmented_button_unselected_hover_color="#283042",
            text_color="#F8FAFC"
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(4, 8))

        self.tab_deep_search = self.tabview.add("🔬 Deep Search por Símbolo")
        self.tab_compare = self.tabview.add("⚖️ Comparativa de Estrategias & Mejor por Par")

        self._build_search_tab()
        self._build_compare_tab()

    def _build_search_tab(self) -> None:
        # Barra de Configuración de Deep Search
        control_frame = ctk.CTkFrame(self.tab_deep_search, fg_color="#222733", corner_radius=8)
        control_frame.pack(fill="x", padx=14, pady=(8, 4))

        # Selector de Estrategia
        lbl_strat = ctk.CTkLabel(
            control_frame,
            text="🎯 Estrategia:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#F59E0B"
        )
        lbl_strat.pack(side="left", padx=(10, 4), pady=8)

        available_strats = get_available_strategies() or ["forex", "syntx", "ai_strategy"]
        init_strat = self.selected_strategy if self.selected_strategy in available_strats else available_strats[0]
        self.opt_strat = ctk.CTkOptionMenu(
            control_frame,
            values=available_strats,
            command=self._on_strategy_changed,
            width=110,
            fg_color="#D97706",
            button_color="#B45309",
            button_hover_color="#92400E",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.opt_strat.set(init_strat)
        self.opt_strat.pack(side="left", padx=(0, 8), pady=8)

        # Selector de Días Históricos
        lbl_days = ctk.CTkLabel(
            control_frame,
            text="📅 Historial:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94A3B8"
        )
        lbl_days.pack(side="left", padx=(8, 4), pady=8)

        self.opt_days = ctk.CTkOptionMenu(
            control_frame,
            values=["15 Días", "30 Días", "45 Días", "60 Días"],
            width=90,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.opt_days.set("30 Días")
        self.opt_days.pack(side="left", padx=(0, 8), pady=8)

        # Selector de Timeframe
        lbl_tf = ctk.CTkLabel(
            control_frame,
            text="⏱️ Timeframe:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94A3B8"
        )
        lbl_tf.pack(side="left", padx=(8, 4), pady=8)

        self.opt_tf = ctk.CTkOptionMenu(
            control_frame,
            values=["Auto (Mejor TF)", "M5", "M15", "M30", "H1", "H4"],
            width=115,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.opt_tf.set("Auto (Mejor TF)")
        self.opt_tf.pack(side="left", padx=(0, 10), pady=8)

        # Botón Iniciar / Detener (A la derecha con margen seguro)
        self.btn_run = ctk.CTkButton(
            control_frame,
            text="▶️ Iniciar Deep Search",
            fg_color="#059669",
            hover_color="#047857",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=150,
            command=self._toggle_deep_search
        )
        self.btn_run.pack(side="right", padx=10, pady=8)

        # Asegurar visibilidad al frente del canvas
        for widget in (lbl_strat, self.opt_strat, lbl_days, self.opt_days, lbl_tf, self.opt_tf, self.btn_run):
            widget.lift()

        # 3. Barra de Progreso y Estado
        progress_frame = ctk.CTkFrame(self.tab_deep_search, fg_color="transparent")
        progress_frame.pack(fill="x", padx=10, pady=(2, 4))

        self.progress_bar = ctk.CTkProgressBar(progress_frame, height=7, corner_radius=4)
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", pady=(1, 3))

        self.lbl_status = ctk.CTkLabel(
            progress_frame,
            text="Listo para ejecutar Deep Search o consultar resultados guardados.",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8"
        )
        self.lbl_status.pack(anchor="w")

        # 4. Barra de Acciones de Selección y Montado de Pares
        action_bar = ctk.CTkFrame(self.tab_deep_search, fg_color="#1e222d", corner_radius=6)
        action_bar.pack(fill="x", padx=10, pady=(2, 4))

        lbl_section = ctk.CTkLabel(
            action_bar,
            text="🏆 Ranking:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F1F5F9"
        )
        lbl_section.pack(side="left", padx=(10, 4), pady=5)

        # Botones de Selección Rápida compactos
        btn_select_all = ctk.CTkButton(
            action_bar,
            text="☑️ Todos",
            width=65,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=self._select_all
        )
        btn_select_all.pack(side="left", padx=3, pady=5)

        btn_select_top5 = ctk.CTkButton(
            action_bar,
            text="⭐ Top 5",
            width=65,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#0369A1",
            hover_color="#0284C7",
            command=self._select_top5
        )
        btn_select_top5.pack(side="left", padx=3, pady=5)

        btn_deselect = ctk.CTkButton(
            action_bar,
            text="◻️ Ninguno",
            width=65,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=self._deselect_all
        )
        btn_deselect.pack(side="left", padx=3, pady=5)

        # Selector de ordenamiento dinámico rápido
        lbl_sort = ctk.CTkLabel(
            action_bar,
            text="↕ Orden:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94A3B8"
        )
        lbl_sort.pack(side="left", padx=(8, 3), pady=5)

        self.opt_sort = ctk.CTkOptionMenu(
            action_bar,
            values=[
                "Mayor Win Rate",
                "Mayor Avg R",
                "Más Trades",
                "Símbolo (A-Z)",
                "Símbolo (Z-A)",
                "Timeframe",
                "Mejor Veredicto",
            ],
            command=self._on_sort_option_changed,
            width=125,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#334155",
            button_color="#475569",
            button_hover_color="#64748B"
        )
        self.opt_sort.set("Mayor Win Rate")
        self.opt_sort.pack(side="left", padx=(0, 6), pady=5)

        # 🟢 BOTÓN PRINCIPAL: Montar pares seleccionados (Dimensionado proporcional y visible siempre)
        self.btn_mount_selected = ctk.CTkButton(
            action_bar,
            text="📥 Montar Pares Seleccionados",
            width=210,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=self._mount_selected_pairs
        )
        self.btn_mount_selected.pack(side="right", padx=(4, 10), pady=5)

        # 🧠 BOTÓN IA: Enviar trades para aprendizaje y optimización
        self.btn_send_to_ai = ctk.CTkButton(
            action_bar,
            text="🧠 Enviar a IA (Aprendizaje)",
            width=185,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#7C3AED",
            hover_color="#6D28D9",
            command=self._send_trades_to_ai_learning
        )
        self.btn_send_to_ai.pack(side="right", padx=(4, 4), pady=5)

        # 📜 BOTÓN CHANGELOG: Ver registro histórico de cambios MR para AI Strategy
        self.btn_view_changelog = ctk.CTkButton(
            action_bar,
            text="📜 Changelog AI",
            width=120,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=self._open_ai_strategy_changelog_dialog
        )
        self.btn_view_changelog.pack(side="right", padx=(4, 4), pady=5)

        for widget in (lbl_section, btn_select_all, btn_select_top5, btn_deselect, lbl_sort, self.opt_sort, self.btn_mount_selected, self.btn_send_to_ai, self.btn_view_changelog):
            widget.lift()

        # 5. Cabecera de la Tabla de Resultados con Ordenamiento Dinámico por Columna
        table_header = ctk.CTkFrame(self.tab_deep_search, fg_color="#131722", height=28, corner_radius=4)
        table_header.pack(fill="x", padx=10, pady=(2, 2))

        lbl_sel = ctk.CTkLabel(
            table_header,
            text="Sel",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#64748B",
            width=38,
            anchor="center"
        )
        lbl_sel.pack(side="left", padx=2, pady=2)
        lbl_sel.lift()

        for col_key, title, width in self._sort_columns_info:
            btn = ctk.CTkButton(
                table_header,
                text=f"{title} ↕",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#94A3B8",
                fg_color="transparent",
                hover_color="#1f293d",
                width=width,
                height=24,
                corner_radius=3,
                anchor="center",
                command=lambda k=col_key: self._on_header_sort_click(k)
            )
            btn.pack(side="left", padx=2, pady=2)
            btn.lift()
            self._header_buttons[col_key] = btn

        # 6. Contenedor Scrolleable para las Filas (Con scrollbar de alto contraste y visible)
        self.scroll_table = ctk.CTkScrollableFrame(
            self.tab_deep_search,
            fg_color="#161a23",
            corner_radius=6,
            scrollbar_button_color="#0284C7",
            scrollbar_button_hover_color="#38BDF8",
            scrollbar_fg_color="#1e2430"
        )
        self.scroll_table.pack(fill="both", expand=True, padx=10, pady=(0, 6))

    def _build_compare_tab(self) -> None:
        """Construye la interfaz de la pestaña de Comparativa de Estrategias y Mejor Estrategia por Par."""
        # 1. Barra Superior Informativa y de Acciones Globales
        comp_top_bar = ctk.CTkFrame(self.tab_compare, fg_color="#1e2430", corner_radius=6)
        comp_top_bar.pack(fill="x", padx=6, pady=(6, 6))

        top_left = ctk.CTkFrame(comp_top_bar, fg_color="transparent")
        top_left.pack(side="left", fill="both", expand=True, padx=10, pady=6)

        lbl_comp_title = ctk.CTkLabel(
            top_left,
            text="⚖️ Comparativa Multialgoritmo & Detección Óptima por Par",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#F8FAFC"
        )
        lbl_comp_title.pack(anchor="w")

        lbl_comp_desc = ctk.CTkLabel(
            top_left,
            text="Determina automáticamente qué estrategia es líder global y cuál es el mejor algoritmo y timeframe para cada par.",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8"
        )
        lbl_comp_desc.pack(anchor="w")

        top_right = ctk.CTkFrame(comp_top_bar, fg_color="transparent")
        top_right.pack(side="right", padx=10, pady=6)

        btn_refresh_comp = ctk.CTkButton(
            top_right,
            text="🔄 Recargar Datos",
            width=120,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=self._load_strategy_comparison
        )
        btn_refresh_comp.pack(side="left", padx=4)

        btn_mount_best = ctk.CTkButton(
            top_right,
            text="⚡ Aplicar Mejores a la Tabla",
            width=210,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            command=self._mount_best_strategies_selected
        )
        btn_mount_best.pack(side="left", padx=4)

        # 2. Sección Superior: Resumen Global por Estrategia
        summary_outer = ctk.CTkFrame(self.tab_compare, fg_color="#181c25", corner_radius=6)
        summary_outer.pack(fill="x", padx=6, pady=(0, 6))

        lbl_sec_strat = ctk.CTkLabel(
            summary_outer,
            text="🏆 Ranking Global de Rendimiento por Estrategia:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F59E0B"
        )
        lbl_sec_strat.pack(anchor="w", padx=10, pady=(6, 4))

        self.scroll_strat_cards = ctk.CTkScrollableFrame(
            summary_outer,
            fg_color="transparent",
            orientation="horizontal",
            height=85,
            scrollbar_button_color="#0284C7",
            scrollbar_button_hover_color="#38BDF8"
        )
        self.scroll_strat_cards.pack(fill="x", padx=6, pady=(0, 6))

        # 3. Sección Inferior: Matriz de Mejor Estrategia por Par
        pairs_outer = ctk.CTkFrame(self.tab_compare, fg_color="transparent")
        pairs_outer.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        # Barra de control y filtrado de pares
        pairs_action_bar = ctk.CTkFrame(pairs_outer, fg_color="#1e222d", corner_radius=6)
        pairs_action_bar.pack(fill="x", pady=(0, 4))

        lbl_matrix_title = ctk.CTkLabel(
            pairs_action_bar,
            text="🎯 Estrategia Ganadora por Par:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38BDF8"
        )
        lbl_matrix_title.pack(side="left", padx=(10, 6), pady=6)

        # Filtro de texto dinámico
        self.entry_comp_filter = ctk.CTkEntry(
            pairs_action_bar,
            placeholder_text="🔍 Filtrar par (ej. EURUSD)...",
            width=180,
            height=26,
            font=ctk.CTkFont(size=11)
        )
        self.entry_comp_filter.pack(side="left", padx=4, pady=6)
        self.entry_comp_filter.bind("<KeyRelease>", lambda e: self._render_comp_pairs_table())

        # Botones de selección rápida para la matriz
        btn_comp_all = ctk.CTkButton(
            pairs_action_bar,
            text="☑️ Todos",
            width=65,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=self._select_all_comp
        )
        btn_comp_all.pack(side="left", padx=3, pady=6)

        btn_comp_rent = ctk.CTkButton(
            pairs_action_bar,
            text="⭐ Rentables (>0R)",
            width=110,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#0369A1",
            hover_color="#0284C7",
            command=self._select_profitable_comp
        )
        btn_comp_rent.pack(side="left", padx=3, pady=6)

        btn_comp_none = ctk.CTkButton(
            pairs_action_bar,
            text="◻️ Ninguno",
            width=65,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=self._deselect_all_comp
        )
        btn_comp_none.pack(side="left", padx=3, pady=6)

        # Mensaje de estado en vivo para esta pestaña
        self.lbl_comp_status = ctk.CTkLabel(
            pairs_action_bar,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#34D399"
        )
        self.lbl_comp_status.pack(side="right", padx=10, pady=6)

        # Cabecera de la tabla de la matriz
        comp_header = ctk.CTkFrame(pairs_outer, fg_color="#131722", height=28, corner_radius=4)
        comp_header.pack(fill="x", pady=(0, 2))

        headers_info = [
            ("Sel", 38),
            ("Símbolo", 85),
            ("Estrategia Óptima", 125),
            ("TF Óptimo", 75),
            ("Win Rate %", 85),
            ("Avg R", 85),
            ("Trades", 60),
            ("Evaluadas", 75),
            ("Ventaja / Margen vs Otras", 180),
            ("Acciones", 160),
        ]
        for title, w in headers_info:
            lbl = ctk.CTkLabel(
                comp_header,
                text=title,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#94A3B8",
                width=w,
                anchor="center"
            )
            lbl.pack(side="left", padx=2, pady=2)

        # Scrollable table container
        self.scroll_comp_table = ctk.CTkScrollableFrame(
            pairs_outer,
            fg_color="#161a23",
            corner_radius=6,
            scrollbar_button_color="#0284C7",
            scrollbar_button_hover_color="#38BDF8",
            scrollbar_fg_color="#1e2430"
        )
        self.scroll_comp_table.pack(fill="both", expand=True, pady=(0, 4))

    def _on_strategy_changed(self, choice: str) -> None:
        self.selected_strategy = choice
        self._update_ai_button_style()
        self._load_cached_results()

    def _update_ai_button_style(self) -> None:
        """Actualiza el estilo visual del botón de aprendizaje según la estrategia activa."""
        if not hasattr(self, "btn_send_to_ai"):
            return
        is_ai = "ai" in self.selected_strategy.lower()
        if is_ai:
            self.btn_send_to_ai.configure(
                text="🧠 Enviar a IA (Aprendizaje)",
                fg_color="#7C3AED",
                hover_color="#6D28D9",
                border_width=1,
                border_color="#A78BFA"
            )
        else:
            self.btn_send_to_ai.configure(
                text="🧠 Entrenar IA con Trades",
                fg_color="#4C1D95",
                hover_color="#5B21B6",
                border_width=0
            )

    def _update_header_indicators(self) -> None:
        """Actualiza el texto y estilo visual de los botones de la cabecera según la columna y dirección activa."""
        for col_key, title, _ in self._sort_columns_info:
            btn = self._header_buttons.get(col_key)
            if not btn:
                continue
            if col_key == self._current_sort_col:
                arrow = "▼" if self._current_sort_desc else "▲"
                btn.configure(
                    text=f"{title} {arrow}",
                    text_color="#38BDF8",
                    fg_color="#1e293b"
                )
            else:
                btn.configure(
                    text=f"{title} ↕",
                    text_color="#94A3B8",
                    fg_color="transparent"
                )

    def _on_header_sort_click(self, col: str) -> None:
        """Invierte la dirección si se pulsa la columna activa o cambia de columna de ordenamiento."""
        if self._current_sort_col == col:
            self._current_sort_desc = not self._current_sort_desc
        else:
            self._current_sort_col = col
            # Para columnas textuales o timeframes orden ascendente por defecto; para métricas de rendimiento, descendente
            self._current_sort_desc = False if col in ("symbol", "strategy", "timeframe") else True

        self._update_header_indicators()
        self._sync_sort_dropdown()
        self._render_results_table(self._results_data)

    def _sync_sort_dropdown(self) -> None:
        """Sincroniza el menú desplegable rápido con la selección de la cabecera."""
        reverse_map = {
            ("win_rate", True): "Mayor Win Rate",
            ("avg_r", True): "Mayor Avg R",
            ("trades", True): "Más Trades",
            ("symbol", False): "Símbolo (A-Z)",
            ("symbol", True): "Símbolo (Z-A)",
            ("timeframe", False): "Timeframe",
            ("verdict", True): "Mejor Veredicto",
        }
        val = reverse_map.get((self._current_sort_col, self._current_sort_desc))
        if val and hasattr(self, "opt_sort"):
            self.opt_sort.set(val)

    def _on_sort_option_changed(self, choice: str) -> None:
        """Maneja el cambio en el selector de ordenamiento rápido."""
        sort_map = {
            "Mayor Win Rate": ("win_rate", True),
            "Mayor Avg R": ("avg_r", True),
            "Más Trades": ("trades", True),
            "Símbolo (A-Z)": ("symbol", False),
            "Símbolo (Z-A)": ("symbol", True),
            "Timeframe": ("timeframe", False),
            "Mejor Veredicto": ("verdict", True),
        }
        if choice in sort_map:
            col, desc = sort_map[choice]
            self._current_sort_col = col
            self._current_sort_desc = desc
            self._update_header_indicators()
            self._render_results_table(self._results_data)

    def _get_sort_key(self, r: Dict[str, Any], col: str):
        if col == "symbol":
            sym = r.get("symbol") or r.get("resolved_symbol") or ""
            return str(sym).upper()
        elif col == "strategy":
            strat = r.get("strategy") or self.selected_strategy or ""
            return str(strat).upper()
        elif col == "timeframe":
            raw_tf = r.get("timeframe", 0)
            tf_weights = {
                mt5.TIMEFRAME_M1: 1, mt5.TIMEFRAME_M5: 5, mt5.TIMEFRAME_M15: 15,
                mt5.TIMEFRAME_M30: 30, mt5.TIMEFRAME_H1: 60, mt5.TIMEFRAME_H4: 240,
                mt5.TIMEFRAME_D1: 1440,
                1: 1, 5: 5, 15: 15, 30: 30, 16385: 60, 16388: 240, 16408: 1440,
                "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440
            }
            return tf_weights.get(raw_tf, 0)
        elif col == "trades":
            return int(r.get("trades", 0))
        elif col == "win_rate":
            return (float(r.get("win_rate", 0.0)), float(r.get("avg_r", 0.0)))
        elif col == "avg_r":
            return (float(r.get("avg_r", 0.0)), float(r.get("win_rate", 0.0)))
        elif col == "verdict":
            wr = float(r.get("win_rate", 0.0))
            avg_r = float(r.get("avg_r", 0.0))
            if wr >= 65.0 and avg_r >= 0.5:
                v_score = 4
            elif wr >= 50.0 and avg_r >= 0.1:
                v_score = 3
            elif wr >= 40.0:
                v_score = 2
            else:
                v_score = 1
            return (v_score, wr, avg_r)
        return 0

    def _sort_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        try:
            return sorted(
                records,
                key=lambda r: self._get_sort_key(r, self._current_sort_col),
                reverse=self._current_sort_desc
            )
        except Exception as e:
            print(f"[SORT ERROR] Error ordenando por {self._current_sort_col}: {e}")
            return records

    def _load_cached_results(self) -> None:
        """Carga y muestra los resultados ya existentes para la estrategia seleccionada."""
        cached = get_cached_results(self.selected_strategy)
        self._results_data = cached
        self._update_header_indicators()
        self._render_results_table(cached)
        strat_file_info = f"backtests/backtest_{self.selected_strategy}.json"
        display_count = min(len(cached), 60)
        dir_icon = "▼" if self._current_sort_desc else "▲"
        sort_info = f" [Orden: {self._current_sort_col.upper()} {dir_icon}]"
        if len(cached) > 60:
            self.lbl_status.configure(
                text=f"Mostrando los mejores {display_count} de {len(cached)} pares evaluados en {strat_file_info}{sort_info}."
            )
        else:
            self.lbl_status.configure(
                text=f"Resultados cargados para '{self.selected_strategy}' ({len(cached)} pares evaluados en {strat_file_info}){sort_info}."
            )

    def _render_results_table(self, records: List[Dict[str, Any]]) -> None:
        """Renderiza la lista de resultados en la tabla con anchos sincronizados, orden dinámico y preservación de selecciones."""
        # Guardar selecciones actuales para no perderlas al reordenar
        current_selections = {sym: var.get() for sym, var in self._check_vars.items()}

        # Limpiar filas existentes
        for child in self.scroll_table.winfo_children():
            child.destroy()
        self._check_vars.clear()

        if not records:
            lbl_empty = ctk.CTkLabel(
                self.scroll_table,
                text="No hay resultados guardados para esta estrategia. Inicie un Deep Search para comenzar.",
                font=ctk.CTkFont(size=12),
                text_color="#64748B"
            )
            lbl_empty.pack(pady=40)
            return

        # Aplicar ordenamiento dinámico activo
        sorted_records = self._sort_records(records)

        tf_labels = {
            mt5.TIMEFRAME_M1: "M1", mt5.TIMEFRAME_M5: "M5", mt5.TIMEFRAME_M15: "M15",
            mt5.TIMEFRAME_M30: "M30", mt5.TIMEFRAME_H1: "H1", mt5.TIMEFRAME_H4: "H4", mt5.TIMEFRAME_D1: "D1",
        }

        # Renderizar hasta 60 pares ordenados por mérito para rendimiento óptimo y scroll instantáneo
        display_records = sorted_records[:60]

        for idx, r in enumerate(display_records):
            sym = r.get("symbol") or r.get("resolved_symbol") or f"SYM_{idx}"
            strat = r.get("strategy") or self.selected_strategy
            raw_tf = r.get("timeframe", mt5.TIMEFRAME_M15)
            tf_str = tf_labels.get(raw_tf, str(raw_tf))
            trades = r.get("trades", 0)
            wr = r.get("win_rate", 0.0)
            avg_r = r.get("avg_r", 0.0)

            # Veredicto cualitativo
            if wr >= 65.0 and avg_r >= 0.5:
                verdict = "🏆 Top Recomendado"
                verdict_color = "#34D399"
            elif wr >= 50.0 and avg_r >= 0.1:
                verdict = "✅ Favorable"
                verdict_color = "#38BDF8"
            elif wr >= 40.0:
                verdict = "⚠️ Requiere Cautela"
                verdict_color = "#FBBF24"
            else:
                verdict = "❌ Descartado"
                verdict_color = "#F87171"

            # Fila
            row_bg = "#1f2430" if idx % 2 == 0 else "#252b3b"
            row_frame = ctk.CTkFrame(self.scroll_table, fg_color=row_bg, corner_radius=4, height=30)
            row_frame.pack(fill="x", pady=2, padx=2)

            # 1. Checkbox (width 38)
            if sym in current_selections:
                is_checked = current_selections[sym]
            else:
                is_checked = (wr >= 50.0 and avg_r >= 0.0)

            var = ctk.BooleanVar(value=is_checked)
            self._check_vars[sym] = var
            chk = ctk.CTkCheckBox(
                row_frame,
                text="",
                variable=var,
                width=26,
                checkbox_width=18,
                checkbox_height=18
            )
            chk.pack(side="left", padx=(6, 2), pady=3)

            # 2. Símbolo (width 90)
            lbl_sym = ctk.CTkLabel(
                row_frame,
                text=sym,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#F8FAFC",
                width=90,
                anchor="w"
            )
            lbl_sym.pack(side="left", padx=2)

            # 3. Estrategia (width 85)
            lbl_strat = ctk.CTkLabel(
                row_frame,
                text=strat,
                font=ctk.CTkFont(size=11),
                text_color="#F59E0B",
                width=85,
                anchor="center"
            )
            lbl_strat.pack(side="left", padx=2)

            # 4. Timeframe (width 75)
            lbl_tf_val = ctk.CTkLabel(
                row_frame,
                text=tf_str,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#A78BFA",
                width=75,
                anchor="center"
            )
            lbl_tf_val.pack(side="left", padx=2)

            # 5. Trades (width 60)
            lbl_trades = ctk.CTkLabel(
                row_frame,
                text=str(trades),
                font=ctk.CTkFont(size=11),
                text_color="#E2E8F0",
                width=60,
                anchor="center"
            )
            lbl_trades.pack(side="left", padx=2)

            # 6. Win Rate % (width 85)
            wr_color = "#34D399" if wr >= 50.0 else "#F87171"
            lbl_wr = ctk.CTkLabel(
                row_frame,
                text=f"{wr:.1f}%",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=wr_color,
                width=85,
                anchor="center"
            )
            lbl_wr.pack(side="left", padx=2)

            # 7. Expectativa Avg R (width 85)
            r_color = "#34D399" if avg_r > 0 else ("#94A3B8" if avg_r == 0 else "#F87171")
            lbl_avgr = ctk.CTkLabel(
                row_frame,
                text=f"{avg_r:+.2f} R",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=r_color,
                width=85,
                anchor="center"
            )
            lbl_avgr.pack(side="left", padx=2)

            # 8. Veredicto (width 140)
            lbl_verd = ctk.CTkLabel(
                row_frame,
                text=verdict,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=verdict_color,
                width=140,
                anchor="w"
            )
            lbl_verd.pack(side="left", padx=2)

    def _select_all(self) -> None:
        for var in self._check_vars.values():
            var.set(True)

    def _deselect_all(self) -> None:
        for var in self._check_vars.values():
            var.set(False)

    def _select_top5(self) -> None:
        self._deselect_all()
        for idx, (sym, var) in enumerate(self._check_vars.items()):
            if idx < 5:
                var.set(True)

    def _mount_selected_pairs(self) -> None:
        """
        Monta los pares seleccionados en la vista de Mejores Pares y en SymbolSelectorComponent.
        Transmite la lista completa al callback principal de la aplicación.
        """
        selected_pairs: List[Dict[str, Any]] = []

        tf_labels = {
            mt5.TIMEFRAME_M1: "M1", mt5.TIMEFRAME_M5: "M5", mt5.TIMEFRAME_M15: "M15",
            mt5.TIMEFRAME_M30: "M30", mt5.TIMEFRAME_H1: "H1", mt5.TIMEFRAME_H4: "H4", mt5.TIMEFRAME_D1: "D1",
        }

        for r in self._results_data:
            sym = r.get("symbol") or r.get("resolved_symbol")
            if sym and self._check_vars.get(sym) and self._check_vars[sym].get():
                raw_tf = r.get("timeframe", mt5.TIMEFRAME_M15)
                tf_name = tf_labels.get(raw_tf, "M15")
                selected_pairs.append({
                    "symbol": sym,
                    "strategy": r.get("strategy") or self.selected_strategy,
                    "timeframe": tf_name,
                    "win_rate": r.get("win_rate", 0.0),
                    "avg_r": r.get("avg_r", 0.0),
                    "trades": r.get("trades", 0),
                })

        if not selected_pairs:
            self.lbl_status.configure(
                text="⚠️ Por favor seleccione al menos un par de la tabla marcando su casilla."
            )
            return

        replace_existing = messagebox.askyesno(
            "Aplicar Pares a la Tabla",
            f"¿Deseas quitar los pares que ya están en la tabla antes de agregar los {len(selected_pairs)} seleccionados?\n\n"
            "• Sí: Se eliminan todos los pares actuales de la tabla y se agregan los seleccionados.\n"
            "• No: Se conservan los pares actuales y se agregan/actualizan los seleccionados.",
            parent=self
        )

        if self.on_mount_symbols_callback:
            try:
                try:
                    self.on_mount_symbols_callback(selected_pairs, replace_existing=replace_existing)
                except TypeError:
                    self.on_mount_symbols_callback(selected_pairs)
                mounted_symbols = [p["symbol"] for p in selected_pairs]
                self.lbl_status.configure(
                    text=f"✅ {len(selected_pairs)} pares montados en Symbol Selector: {', '.join(mounted_symbols)}"
                )
            except Exception as e:
                self.lbl_status.configure(text=f"❌ Error al montar pares en Symbol Selector: {e}")
        else:
            self.lbl_status.configure(
                text=f"✅ {len(selected_pairs)} pares listos para montar."
            )

    def _send_trades_to_ai_learning(self) -> None:
        """
        Envía los datos de backtesting a la IA (Google Gemini / OpenAI / Groq) o ejecuta
        síntesis cuantitativa si la IA no está disponible, para que aprenda patrones
        y module los filtros dinámicos de AIStrategy.
        """
        if not self._results_data:
            messagebox.showinfo(
                "Aprendizaje IA",
                "⚠️ No hay resultados de backtesting disponibles para analizar.\n\n"
                "Inicia primero 'Deep Search' (preferentemente con la estrategia 'ai_strategy') "
                "para generar y recopilar los trades que alimentarán el aprendizaje de la IA.",
                parent=self
            )
            return

        selected_symbols = [sym for sym, var in self._check_vars.items() if var.get()]
        if not selected_symbols:
            confirm = messagebox.askyesno(
                "Enviar Trades a IA",
                f"No has marcado ningún par específico en la tabla.\n\n"
                f"¿Deseas enviar los datos de todos los {len(self._results_data)} pares analizados "
                f"a la IA para que aprenda sus trampas técnicas y optimice las reglas?",
                parent=self
            )
            if not confirm:
                return
            target_items = list(self._results_data)
        else:
            target_items = [r for r in self._results_data if r.get("symbol") in selected_symbols]

        if not target_items:
            messagebox.showwarning("Aprendizaje IA", "No se encontraron datos para los pares seleccionados.", parent=self)
            return

        cfg = load_config()
        api_key = str(cfg.get("ai_api_key", "")).strip()
        model_name = str(cfg.get("ai_model", "gemini-2.5-flash"))
        base_url = str(cfg.get("ai_base_url", ""))

        self.btn_send_to_ai.configure(state="disabled", text="⏳ Procesando con IA...")
        provider_hint = "Modelo de IA" if api_key else "Síntesis Cuantitativa Heurística"
        self.lbl_status.configure(
            text=f"🧠 Procesando {len(target_items)} pares vía {provider_hint} (Lotes optimizados con control de cuota)...",
            text_color="#C084FC"
        )

        def _bg_learn():
            def _progress_cb(sym: str, idx: int, tot: int, status_text: str = ""):
                self._safe_ui(lambda s=sym, i=idx, t=tot, st=status_text: self.lbl_status.configure(
                    text=f"🧠 {st} para {s} ({min(i+1, t)}/{t})...",
                    text_color="#C084FC"
                ))

            try:
                learned_results = train_ai_batch_from_backtest(
                    items=target_items,
                    default_strategy=self.selected_strategy,
                    api_key=api_key,
                    model_name=model_name,
                    base_url=base_url,
                    progress_callback=_progress_cb
                )
            except Exception as e_learn:
                print(f"❌ Error crítico en ejecución de aprendizaje: {e_learn}")
                learned_results = []

            self._safe_ui(lambda: self._on_ai_learning_finished(learned_results))

        threading.Thread(target=_bg_learn, daemon=True).start()

    def _on_ai_learning_finished(self, learned_results: List[Dict[str, Any]]) -> None:
        """Callback invocado al finalizar el procesamiento de aprendizaje con IA."""
        self.btn_send_to_ai.configure(state="normal")
        self._update_ai_button_style()

        if not learned_results:
            self.lbl_status.configure(
                text="❌ No se pudo completar el aprendizaje de IA para los pares seleccionados.",
                text_color="#F87171"
            )
            messagebox.showerror(
                "Aprendizaje IA",
                "No se pudo extraer el aprendizaje. Verifica que los pares tengan operaciones ejecutadas en el backtest.",
                parent=self
            )
            return

        heuristic_count = sum(1 for r in learned_results if "QUANT_HEURISTIC" in str(r.get("source", "")))
        ai_count = len(learned_results) - heuristic_count
        summary_txt = f"✅ Aprendizaje completado ({ai_count} con IA, {heuristic_count} con Síntesis Cuantitativa). MR Changelog generado."
        self.lbl_status.configure(
            text=summary_txt,
            text_color="#34D399"
        )

        self._show_ai_learning_results_modal(learned_results)

    def _show_ai_learning_results_modal(self, learned_results: List[Dict[str, Any]]) -> None:
        """Muestra un modal detallado con las reglas, trampas a evitar, consejos y el MR Changelog de parámetros."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("🧠 Aprendizaje y Modulación Dinámica de Parámetros (MR Changelog)")
        dlg.geometry("780x560")
        dlg.configure(fg_color="#181a20")
        try:
            dlg.transient(self)
            dlg.grab_set()
        except Exception:
            pass

        # Cabecera
        header_frame = ctk.CTkFrame(dlg, fg_color="#1e1b4b", corner_radius=6)
        header_frame.pack(fill="x", padx=14, pady=(14, 8))

        lbl_title = ctk.CTkLabel(
            header_frame,
            text="🧠 Modulación de Parámetros y MR Changelog (AI Strategy)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#C084FC"
        )
        lbl_title.pack(padx=12, pady=(10, 2), anchor="w")

        lbl_sub = ctk.CTkLabel(
            header_frame,
            text="Las reglas y parámetros se registraron en ai_strategy_changelog.json y docs/AI_STRATEGY_CHANGELOG.md.\n"
                 "AI Strategy aplicará estos umbrales dinámicos (ADX, RSI, Score 2/4 a 4/4 y Break-Even) en tiempo real.",
            font=ctk.CTkFont(size=11),
            text_color="#CBD5E1",
            justify="left"
        )
        lbl_sub.pack(padx=12, pady=(0, 10), anchor="w")

        # Contenedor scrollable de tarjetas
        scroll = ctk.CTkScrollableFrame(
            dlg,
            fg_color="#131722",
            corner_radius=6,
            scrollbar_button_color="#7C3AED",
            scrollbar_button_hover_color="#9333EA"
        )
        scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        for rec in learned_results:
            sym = rec.get("symbol", "N/A")
            wr = rec.get("win_rate", 0.0)
            avg_r = rec.get("avg_r", 0.0)
            trades = rec.get("trades", 0)
            opt_tf = rec.get("optimal_tf", "M15")
            conf = rec.get("confidence_score", 80.0)
            source = rec.get("source", "IA")
            mr_id = rec.get("mr_id", f"MR-{sym}")
            changes = rec.get("changes", [])
            avoid_patterns = rec.get("avoid_patterns", [])
            risk_adv = rec.get("risk_advice", "Sin recomendaciones específicas.")

            card = ctk.CTkFrame(scroll, fg_color="#1C212D", corner_radius=6, border_width=1, border_color="#312E81")
            card.pack(fill="x", pady=6, padx=4)

            # Barra superior de la tarjeta
            top_bar = ctk.CTkFrame(card, fg_color="transparent")
            top_bar.pack(fill="x", padx=10, pady=(8, 4))

            lbl_sym = ctk.CTkLabel(
                top_bar,
                text=sym,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#F8FAFC"
            )
            lbl_sym.pack(side="left")

            mr_badge = ctk.CTkLabel(
                top_bar,
                text=mr_id,
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color="#C084FC",
                fg_color="#2E1065",
                corner_radius=4,
                padx=6,
                pady=1
            )
            mr_badge.pack(side="left", padx=6)

            tf_badge = ctk.CTkLabel(
                top_bar,
                text=f"TF: {opt_tf}",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#0284C7",
                fg_color="#082F49",
                corner_radius=4,
                width=65,
                height=20
            )
            tf_badge.pack(side="left", padx=4)

            wr_color = "#34D399" if wr >= 55.0 else ("#FBBF24" if wr >= 45.0 else "#F87171")
            lbl_stats = ctk.CTkLabel(
                top_bar,
                text=f"WR: {wr:.1f}% | Avg R: {avg_r:+.2f}R | Trades: {trades}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=wr_color
            )
            lbl_stats.pack(side="left", padx=8)

            src_badge = ctk.CTkLabel(
                top_bar,
                text=f"Conf: {conf:.0f}% ({source})",
                font=ctk.CTkFont(size=10),
                text_color="#A78BFA"
            )
            src_badge.pack(side="right")

            # Sección de cambios de parámetros (MR Changelog diff)
            if changes:
                lbl_chg_head = ctk.CTkLabel(
                    card,
                    text="🔄 Modulación de Parámetros (Anterior ➔ Nuevo):",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#FCD34D"
                )
                lbl_chg_head.pack(padx=10, pady=(4, 2), anchor="w")

                diff_frame = ctk.CTkFrame(card, fg_color="#121620", corner_radius=4)
                diff_frame.pack(fill="x", padx=10, pady=(0, 4))

                for ch in changes:
                    p = ch.get("parameter", "")
                    old_v = ch.get("old_value", "")
                    new_v = ch.get("new_value", "")
                    delta = ch.get("difference", "")
                    desc = ch.get("description", "")
                    row_txt = f"• {p}:  {old_v}  ➔  {new_v}  ({delta})  |  {desc}"
                    lbl_ch = ctk.CTkLabel(
                        diff_frame,
                        text=row_txt,
                        font=ctk.CTkFont(size=10),
                        text_color="#E2E8F0",
                        justify="left",
                        anchor="w"
                    )
                    lbl_ch.pack(padx=8, pady=2, anchor="w")

            # Patrones a evitar
            if avoid_patterns:
                lbl_avoid_head = ctk.CTkLabel(
                    card,
                    text="🚫 Trampas y patrones a evitar detectados:",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#F87171"
                )
                lbl_avoid_head.pack(padx=10, pady=(4, 2), anchor="w")

                for pat in avoid_patterns:
                    lbl_pat = ctk.CTkLabel(
                        card,
                        text=f"   • {pat}",
                        font=ctk.CTkFont(size=10),
                        text_color="#E2E8F0",
                        justify="left"
                    )
                    lbl_pat.pack(padx=10, pady=1, anchor="w")

            # Consejo de gestión de riesgo
            if risk_adv:
                lbl_risk_head = ctk.CTkLabel(
                    card,
                    text="🛡️ Consejo de riesgo y modulación dinámica:",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#38BDF8"
                )
                lbl_risk_head.pack(padx=10, pady=(6, 2), anchor="w")

                lbl_risk_body = ctk.CTkLabel(
                    card,
                    text=f"   {risk_adv}",
                    font=ctk.CTkFont(size=10),
                    text_color="#CBD5E1",
                    justify="left"
                )
                lbl_risk_body.pack(padx=10, pady=(0, 6), anchor="w")

        # Botones inferiores de acción
        bottom_bar = ctk.CTkFrame(dlg, fg_color="transparent")
        bottom_bar.pack(fill="x", padx=14, pady=(4, 12))

        btn_view_full_changelog = ctk.CTkButton(
            bottom_bar,
            text="📜 Ver Historial Completo de MR Changelog",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#4338CA",
            hover_color="#3730A3",
            height=32,
            command=lambda: [dlg.destroy(), self._open_ai_strategy_changelog_dialog()]
        )
        btn_view_full_changelog.pack(side="left", padx=5)

        btn_close = ctk.CTkButton(
            bottom_bar,
            text="✅ Entendido y Aplicar",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=32,
            command=dlg.destroy
        )
        btn_close.pack(side="right", padx=5)

    def _open_ai_strategy_changelog_dialog(self, initial_symbol: Optional[str] = None) -> None:
        """Abre un diálogo interactivo dedicado con el registro histórico de cambios (MR Changelog) de AI Strategy."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("📜 Historial de Cambios y Modulación de Parámetros (MR Changelog) - AI Strategy")
        dlg.geometry("860x600")
        dlg.configure(fg_color="#181a20")
        try:
            dlg.transient(self)
            dlg.grab_set()
        except Exception:
            pass

        # Cabecera
        header = ctk.CTkFrame(dlg, fg_color="#1f2430", height=50, corner_radius=6)
        header.pack(fill="x", padx=14, pady=(14, 8))

        lbl_head_title = ctk.CTkLabel(
            header,
            text="📜 MR Changelog: Registro de Modificaciones de Parámetros",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#F8FAFC"
        )
        lbl_head_title.pack(side="left", padx=12, pady=10)

        # Filtro de símbolos
        all_logs = load_all_changelogs()
        existing_symbols = sorted(list(set(str(e.get("symbol", "")).upper() for e in all_logs if e.get("symbol"))))
        filter_options = ["Todos los Pares"] + existing_symbols

        filter_frame = ctk.CTkFrame(dlg, fg_color="#1e222d", corner_radius=6)
        filter_frame.pack(fill="x", padx=14, pady=(0, 8))

        lbl_filt = ctk.CTkLabel(
            filter_frame,
            text="Filtrar por Par:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94A3B8"
        )
        lbl_filt.pack(side="left", padx=(10, 5), pady=6)

        opt_symbol_filter = ctk.CTkOptionMenu(
            filter_frame,
            values=filter_options,
            width=150,
            height=26,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#334155",
            button_color="#475569"
        )
        if initial_symbol and initial_symbol.upper() in existing_symbols:
            opt_symbol_filter.set(initial_symbol.upper())
        else:
            opt_symbol_filter.set("Todos los Pares")
        opt_symbol_filter.pack(side="left", padx=5, pady=6)

        lbl_count = ctk.CTkLabel(
            filter_frame,
            text=f"Total Registros: {len(all_logs)}",
            font=ctk.CTkFont(size=11),
            text_color="#A78BFA"
        )
        lbl_count.pack(side="right", padx=12, pady=6)

        # Contenedor con scroll para las entradas del MR
        cards_scroll = ctk.CTkScrollableFrame(
            dlg,
            fg_color="#131722",
            corner_radius=6,
            scrollbar_button_color="#475569",
            scrollbar_button_hover_color="#64748B"
        )
        cards_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        def _render_entries(selected_sym_filter: str):
            # Limpiar contenido anterior
            for widget in cards_scroll.winfo_children():
                widget.destroy()

            cur_logs = load_all_changelogs()
            if selected_sym_filter != "Todos los Pares":
                cur_logs = [e for e in cur_logs if e.get("symbol", "").upper() == selected_sym_filter.upper()]

            lbl_count.configure(text=f"Mostrando: {len(cur_logs)} registros")

            if not cur_logs:
                lbl_empty = ctk.CTkLabel(
                    cards_scroll,
                    text="No hay registros de cambios en el MR Changelog para los filtros seleccionados.\n"
                         "Ejecuta 'Enviar a IA (Aprendizaje)' en Deep Search para generar el primer registro.",
                    font=ctk.CTkFont(size=12),
                    text_color="#94A3B8"
                )
                lbl_empty.pack(pady=40)
                return

            for entry in cur_logs:
                mr_id = entry.get("mr_id", "MR-UNKNOWN")
                ts = entry.get("timestamp", "N/A")
                sym = entry.get("symbol", "N/A")
                source = entry.get("source", "IA")
                summary = entry.get("summary", "")
                changes = entry.get("changes", [])
                avoid_pats = entry.get("avoid_patterns", [])
                risk_adv = entry.get("risk_advice", "")

                card = ctk.CTkFrame(cards_scroll, fg_color="#1C212D", corner_radius=6, border_width=1, border_color="#334155")
                card.pack(fill="x", padx=4, pady=5)

                top_f = ctk.CTkFrame(card, fg_color="transparent")
                top_f.pack(fill="x", padx=10, pady=(8, 4))

                lbl_mr = ctk.CTkLabel(
                    top_f,
                    text=f"📌 [{mr_id}] {sym}",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#F8FAFC"
                )
                lbl_mr.pack(side="left")

                lbl_time = ctk.CTkLabel(
                    top_f,
                    text=f"🕒 {ts}",
                    font=ctk.CTkFont(size=10),
                    text_color="#94A3B8"
                )
                lbl_time.pack(side="left", padx=10)

                src_col = "#A78BFA" if "AI" in source.upper() else "#38BDF8"
                lbl_src = ctk.CTkLabel(
                    top_f,
                    text=f"Origen: {source}",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color=src_col
                )
                lbl_src.pack(side="right")

                if summary:
                    lbl_summ = ctk.CTkLabel(
                        card,
                        text=f"📝 {summary}",
                        font=ctk.CTkFont(size=11),
                        text_color="#CBD5E1",
                        justify="left",
                        wraplength=780
                    )
                    lbl_summ.pack(padx=10, pady=(2, 4), anchor="w")

                # Tabla de cambios (Anterior vs Nuevo)
                if changes:
                    diff_box = ctk.CTkFrame(card, fg_color="#121620", corner_radius=4)
                    diff_box.pack(fill="x", padx=10, pady=(2, 6))

                    h_row = ctk.CTkLabel(
                        diff_box,
                        text="Parámetro              | Anterior    ➔  Nuevo        | Variación  | Motivo del Ajuste",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color="#FCD34D"
                    )
                    h_row.pack(padx=8, pady=(4, 2), anchor="w")

                    for ch in changes:
                        p = ch.get("parameter", "")
                        old_v = ch.get("old_value", "")
                        new_v = ch.get("new_value", "")
                        delta = ch.get("difference", "")
                        desc = ch.get("description", "")
                        row_line = f"• {p:<20} | {old_v:<11} ➔  {new_v:<11} | {delta:<9} | {desc}"
                        lbl_row = ctk.CTkLabel(
                            diff_box,
                            text=row_line,
                            font=ctk.CTkFont(family="Consolas", size=10),
                            text_color="#E2E8F0",
                            anchor="w"
                        )
                        lbl_row.pack(padx=8, pady=1, anchor="w")

                if avoid_pats:
                    lbl_av = ctk.CTkLabel(
                        card,
                        text="🚫 Trampas: " + " | ".join(avoid_pats[:2]),
                        font=ctk.CTkFont(size=10),
                        text_color="#F87171",
                        anchor="w"
                    )
                    lbl_av.pack(padx=10, pady=(1, 4), anchor="w")

        opt_symbol_filter.configure(command=lambda val: _render_entries(val))
        _render_entries(opt_symbol_filter.get())

        # Barra inferior
        btn_bar = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_bar.pack(fill="x", padx=14, pady=(4, 12))

        lbl_file_hint = ctk.CTkLabel(
            btn_bar,
            text=f"📁 Archivo sincronizado: {CHANGELOG_MD_FILE.name} (docs/)",
            font=ctk.CTkFont(size=10),
            text_color="#94A3B8"
        )
        lbl_file_hint.pack(side="left", padx=5)

        btn_close_cl = ctk.CTkButton(
            btn_bar,
            text="Cerrar",
            width=100,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=dlg.destroy
        )
        btn_close_cl.pack(side="right", padx=5)


    def _toggle_deep_search(self) -> None:
        """Inicia o detiene la ejecución asíncrona de Deep Search."""
        if self._is_running:
            self._stop_deep_search()
        else:
            self._start_deep_search()

    def _start_deep_search(self) -> None:
        self._is_running = True
        self._cancel_event = threading.Event()
        self.btn_run.configure(text="⏹️ Detener Deep Search", fg_color="#DC2626", hover_color="#B91C1C")
        self.progress_bar.set(0.0)

        strat = self.opt_strat.get()
        days_map = {"15 Días": 15, "30 Días": 30, "45 Días": 45, "60 Días": 60}
        target_days = days_map.get(self.opt_days.get(), 30)
        tf_choice = self.opt_tf.get()

        tf_code_map = {
            "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4
        }
        fixed_tf = tf_code_map.get(tf_choice)

        symbols_to_test = list(self.available_symbols)

        def _bg_worker():
            total = len(symbols_to_test)
            results = []

            for i, sym in enumerate(symbols_to_test):
                if self._cancel_event and self._cancel_event.is_set():
                    break

                self.after(0, lambda s=sym, idx=i: self._update_progress_ui(s, idx, total))

                try:
                    if fixed_tf:
                        tf_map = {sym: fixed_tf}
                        sub_res = run_deep_search(
                            symbols=[sym],
                            strategy_name=strat,
                            timeframe_map=tf_map,
                            target_days=target_days,
                            force_refresh=True,
                            cancel_event=self._cancel_event
                        )
                        if sub_res:
                            results.extend(sub_res)
                    else:
                        best_tf_res = find_best_timeframe(
                            symbol=sym,
                            strategy_name=strat,
                            target_days=target_days,
                            force_refresh=True,
                            cancel_event=self._cancel_event
                        )
                        if best_tf_res.get("conclusive") and best_tf_res.get("best_timeframe"):
                            results.append({
                                "symbol": sym,
                                "resolved_symbol": sym,
                                "strategy": strat,
                                "timeframe": best_tf_res["best_timeframe"],
                                "win_rate": best_tf_res.get("best_win_rate", 0.0),
                                "avg_r": best_tf_res.get("best_avg_r", 0.0),
                                "trades": best_tf_res.get("best_trades", 0),
                                "cancelled": False,
                                "updated_at": time.time(),
                            })
                except Exception as e:
                    print(f"[DEEP SEARCH ERROR] {sym}: {e}")

            self.after(0, lambda: self._on_deep_search_completed(strat))

        self._worker_thread = threading.Thread(target=_bg_worker, daemon=True)
        self._worker_thread.start()

    def _update_progress_ui(self, current_sym: str, index: int, total: int) -> None:
        fraction = index / max(1, total)
        self.progress_bar.set(fraction)
        self.lbl_status.configure(
            text=f"Analizando {current_sym}... ({index + 1}/{total}) en historial"
        )

    def _stop_deep_search(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()
        self.lbl_status.configure(text="Deteniendo Deep Search...")

    def _on_deep_search_completed(self, strat: str) -> None:
        self._is_running = False
        self.btn_run.configure(text="▶️ Iniciar Deep Search", fg_color="#059669", hover_color="#047857")
        self.progress_bar.set(1.0)
        self._load_cached_results()
        self._load_strategy_comparison()
        self.lbl_status.configure(
            text=f"✅ Deep Search completado para '{strat}'. Resultados guardados en backtests/backtest_{strat}.json"
        )

    def _load_strategy_comparison(self) -> None:
        """Carga y procesa los datos globales de backtesting para todas las estrategias y por símbolo."""
        try:
            self._comp_summary_data = get_strategy_comparison_summary()
            self._comp_pairs_data = get_best_strategy_per_symbol(self.available_symbols)
            self._render_comp_summary(self._comp_summary_data)
            self._render_comp_pairs_table()
            total_strats = len(self._comp_summary_data)
            total_pairs = len(self._comp_pairs_data)
            if hasattr(self, "lbl_comp_status"):
                self.lbl_comp_status.configure(
                    text=f"Analizadas {total_strats} estrategias en {total_pairs} pares evaluados.",
                    text_color="#38BDF8"
                )
        except Exception as e:
            print(f"[COMP ERROR] Error cargando comparativa de estrategias: {e}")
            if hasattr(self, "lbl_comp_status"):
                self.lbl_comp_status.configure(
                    text=f"Error cargando comparativa: {e}",
                    text_color="#F87171"
                )

    def _render_comp_summary(self, summary_list: List[Dict[str, Any]]) -> None:
        for child in self.scroll_strat_cards.winfo_children():
            child.destroy()

        if not summary_list:
            lbl_empty = ctk.CTkLabel(
                self.scroll_strat_cards,
                text="No hay datos de estrategias para comparar. Ejecute Deep Search en la primera pestaña.",
                font=ctk.CTkFont(size=11),
                text_color="#64748B"
            )
            lbl_empty.pack(padx=20, pady=10)
            return

        for idx, s in enumerate(summary_list):
            strat_name = s.get("strategy", "unknown")
            symbols_count = s.get("symbols_count", 0)
            total_trades = s.get("total_trades", 0)
            wr = s.get("win_rate", 0.0)
            wr_conf = s.get("win_rate_confidence", 0.0)
            avg_r = s.get("avg_r", 0.0)

            is_leader = (idx == 0 and total_trades > 0)
            card_border = "#F59E0B" if is_leader else "#334155"
            card_bg = "#1e2433" if is_leader else "#1a202c"

            card = ctk.CTkFrame(
                self.scroll_strat_cards,
                fg_color=card_bg,
                corner_radius=6,
                border_width=1,
                border_color=card_border,
                width=220
            )
            card.pack(side="left", padx=5, pady=3, fill="y")

            # Header de la tarjeta
            card_top = ctk.CTkFrame(card, fg_color="transparent")
            card_top.pack(fill="x", padx=8, pady=(4, 2))

            strat_title = strat_name.upper().replace("_", " ")
            lbl_name = ctk.CTkLabel(
                card_top,
                text=f"{'🏆 ' if is_leader else ''}{strat_title}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#FBBF24" if is_leader else "#38BDF8"
            )
            lbl_name.pack(side="left")

            if is_leader:
                lbl_tag = ctk.CTkLabel(
                    card_top,
                    text="LÍDER",
                    font=ctk.CTkFont(size=9, weight="bold"),
                    text_color="#FEF08A",
                    fg_color="#854D0E",
                    corner_radius=4,
                    width=45
                )
                lbl_tag.pack(side="right")

            # Métricas en línea
            stats_line = ctk.CTkLabel(
                card,
                text=f"WR: {wr:.1f}% ({wr_conf:.1f}% conf)  |  Exp: {avg_r:+.2f}R",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#34D399" if wr >= 50 else "#F87171"
            )
            stats_line.pack(anchor="w", padx=8, pady=(1, 2))

            detail_line = ctk.CTkLabel(
                card,
                text=f"📊 {symbols_count} pares evaluados  •  {total_trades} ops",
                font=ctk.CTkFont(size=10),
                text_color="#94A3B8"
            )
            detail_line.pack(anchor="w", padx=8, pady=(0, 4))

    def _render_comp_pairs_table(self) -> None:
        """Renderiza la matriz de mejor estrategia por par."""
        for child in self.scroll_comp_table.winfo_children():
            child.destroy()

        if not self._comp_pairs_data:
            lbl_empty = ctk.CTkLabel(
                self.scroll_comp_table,
                text="No hay resultados comparativos disponibles todavía. Ejecute Deep Search para poblar la matriz.",
                font=ctk.CTkFont(size=12),
                text_color="#64748B"
            )
            lbl_empty.pack(pady=40)
            return

        filter_q = self.entry_comp_filter.get().strip().upper() if hasattr(self, "entry_comp_filter") else ""

        filtered_pairs = [
            p for p in self._comp_pairs_data
            if not filter_q or filter_q in p.get("symbol", "").upper()
        ]

        if not filtered_pairs:
            lbl_no_match = ctk.CTkLabel(
                self.scroll_comp_table,
                text=f"No se encontraron pares que coincidan con '{filter_q}'.",
                font=ctk.CTkFont(size=12),
                text_color="#64748B"
            )
            lbl_no_match.pack(pady=30)
            return

        for idx, item in enumerate(filtered_pairs):
            sym = item.get("symbol", "")
            best_strat = item.get("best_strategy", "forex")
            tf_str = item.get("timeframe", "M15")
            wr = item.get("win_rate", 0.0)
            avg_r = item.get("avg_r", 0.0)
            trades = item.get("trades", 0)
            strats_tested = item.get("total_strategies_tested", 1)
            adv_desc = item.get("advantage_desc", "")

            # Variable de check
            if sym not in self._comp_check_vars:
                # Por defecto seleccionado si es rentable
                self._comp_check_vars[sym] = ctk.BooleanVar(value=(avg_r >= 0.0 and wr >= 50.0))

            var = self._comp_check_vars[sym]

            row_bg = "#1f2430" if idx % 2 == 0 else "#252b3b"
            row_frame = ctk.CTkFrame(self.scroll_comp_table, fg_color=row_bg, corner_radius=4, height=32)
            row_frame.pack(fill="x", pady=2, padx=2)

            # 1. Checkbox (width 38)
            chk = ctk.CTkCheckBox(
                row_frame,
                text="",
                variable=var,
                width=26,
                checkbox_width=18,
                checkbox_height=18
            )
            chk.pack(side="left", padx=(6, 2), pady=3)

            # 2. Símbolo (width 85)
            lbl_sym = ctk.CTkLabel(
                row_frame,
                text=sym,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#F8FAFC",
                width=85,
                anchor="w"
            )
            lbl_sym.pack(side="left", padx=2)

            # 3. Estrategia Ganadora Badge (width 125)
            strat_colors = {
                "forex": ("#064E3B", "#34D399"),
                "ai_strategy": ("#4C1D95", "#C4B5FD"),
                "simple_trend": ("#78350F", "#FCD34D"),
                "syntx": ("#1E3A8A", "#93C5FD"),
                "crypto": ("#831843", "#F472B6"),
            }
            bg_c, text_c = strat_colors.get(best_strat.lower(), ("#1E293B", "#38BDF8"))

            badge_frame = ctk.CTkFrame(row_frame, fg_color=bg_c, corner_radius=4, width=125, height=24)
            badge_frame.pack(side="left", padx=2)
            badge_frame.pack_propagate(False)

            lbl_strat_b = ctk.CTkLabel(
                badge_frame,
                text=f"⚡ {best_strat.upper()}",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=text_c
            )
            lbl_strat_b.pack(expand=True)

            # 4. TF Óptimo (width 75)
            lbl_tf = ctk.CTkLabel(
                row_frame,
                text=tf_str,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#A78BFA",
                width=75,
                anchor="center"
            )
            lbl_tf.pack(side="left", padx=2)

            # 5. Win Rate % (width 85)
            wr_c = "#34D399" if wr >= 50.0 else "#F87171"
            lbl_wr = ctk.CTkLabel(
                row_frame,
                text=f"{wr:.1f}%",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=wr_c,
                width=85,
                anchor="center"
            )
            lbl_wr.pack(side="left", padx=2)

            # 6. Avg R (width 85)
            r_c = "#34D399" if avg_r > 0 else ("#94A3B8" if avg_r == 0 else "#F87171")
            lbl_avgr = ctk.CTkLabel(
                row_frame,
                text=f"{avg_r:+.2f} R",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=r_c,
                width=85,
                anchor="center"
            )
            lbl_avgr.pack(side="left", padx=2)

            # 7. Trades (width 60)
            lbl_trades = ctk.CTkLabel(
                row_frame,
                text=str(trades),
                font=ctk.CTkFont(size=11),
                text_color="#E2E8F0",
                width=60,
                anchor="center"
            )
            lbl_trades.pack(side="left", padx=2)

            # 8. Evaluadas (width 75)
            lbl_tested = ctk.CTkLabel(
                row_frame,
                text=f"{strats_tested} est.",
                font=ctk.CTkFont(size=10),
                text_color="#94A3B8",
                width=75,
                anchor="center"
            )
            lbl_tested.pack(side="left", padx=2)

            # 9. Ventaja / Margen (width 180)
            lbl_adv = ctk.CTkLabel(
                row_frame,
                text=adv_desc,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#38BDF8" if "+" in adv_desc else "#94A3B8",
                width=180,
                anchor="w"
            )
            lbl_adv.pack(side="left", padx=2)

            # 10. Acciones: Botón Aplicar y Botón Desglose (width 160)
            act_frame = ctk.CTkFrame(row_frame, fg_color="transparent", width=160)
            act_frame.pack(side="left", padx=2)

            btn_apply = ctk.CTkButton(
                act_frame,
                text="⚡ Aplicar",
                width=75,
                height=24,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#059669",
                hover_color="#047857",
                command=lambda p=item: self._mount_single_best_strategy(p)
            )
            btn_apply.pack(side="left", padx=2)

            btn_detail = ctk.CTkButton(
                act_frame,
                text="🔍 Desglose",
                width=75,
                height=24,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#334155",
                hover_color="#475569",
                command=lambda s=sym, comp=item.get("comparison", []): self._show_symbol_breakdown_dialog(s, comp)
            )
            btn_detail.pack(side="left", padx=2)

    def _select_all_comp(self) -> None:
        for var in self._comp_check_vars.values():
            var.set(True)

    def _deselect_all_comp(self) -> None:
        for var in self._comp_check_vars.values():
            var.set(False)

    def _select_profitable_comp(self) -> None:
        for p in self._comp_pairs_data:
            sym = p.get("symbol")
            if sym in self._comp_check_vars:
                is_prof = p.get("avg_r", 0.0) >= 0.0 and p.get("win_rate", 0.0) >= 50.0
                self._comp_check_vars[sym].set(is_prof)

    def _mount_single_best_strategy(self, item: Dict[str, Any]) -> None:
        """Aplica directamente la mejor estrategia y timeframe para este par específico."""
        sym = item.get("symbol", "")
        strat = item.get("best_strategy", "forex")
        tf = item.get("timeframe", "M15")
        if not sym:
            return

        payload = [{
            "symbol": sym,
            "strategy": strat,
            "timeframe": tf,
            "win_rate": item.get("win_rate", 0.0),
            "avg_r": item.get("avg_r", 0.0),
            "trades": item.get("trades", 0),
        }]

        if self.on_mount_symbols_callback:
            try:
                try:
                    self.on_mount_symbols_callback(payload, replace_existing=False)
                except TypeError:
                    self.on_mount_symbols_callback(payload)
                if hasattr(self, "lbl_comp_status"):
                    self.lbl_comp_status.configure(
                        text=f"✅ {sym} configurado con '{strat.upper()}' ({tf}) en la tabla principal.",
                        text_color="#34D399"
                    )
            except Exception as e:
                if hasattr(self, "lbl_comp_status"):
                    self.lbl_comp_status.configure(text=f"❌ Error al aplicar {sym}: {e}", text_color="#F87171")
        else:
            if hasattr(self, "lbl_comp_status"):
                self.lbl_comp_status.configure(
                    text=f"✅ {sym} -> {strat.upper()} ({tf}) preparado.",
                    text_color="#34D399"
                )

    def _mount_best_strategies_selected(self) -> None:
        """Monta todos los pares marcados en la matriz con sus respectivas estrategias óptimas y timeframes."""
        selected_pairs: List[Dict[str, Any]] = []
        for item in self._comp_pairs_data:
            sym = item.get("symbol")
            if sym and self._comp_check_vars.get(sym) and self._comp_check_vars[sym].get():
                selected_pairs.append({
                    "symbol": sym,
                    "strategy": item.get("best_strategy", "forex"),
                    "timeframe": item.get("timeframe", "M15"),
                    "win_rate": item.get("win_rate", 0.0),
                    "avg_r": item.get("avg_r", 0.0),
                    "trades": item.get("trades", 0),
                })

        if not selected_pairs:
            if hasattr(self, "lbl_comp_status"):
                self.lbl_comp_status.configure(
                    text="⚠️ Marque al menos un par en la matriz para montar sus mejores estrategias.",
                    text_color="#FBBF24"
                )
            return

        replace_existing = messagebox.askyesno(
            "Aplicar Pares a la Tabla",
            f"¿Deseas quitar los pares que ya están en la tabla antes de agregar los {len(selected_pairs)} seleccionados?\n\n"
            "• Sí: Se eliminan todos los pares actuales de la tabla y se agregan los seleccionados.\n"
            "• No: Se conservan los pares actuales y se agregan/actualizan los seleccionados.",
            parent=self
        )

        if self.on_mount_symbols_callback:
            try:
                try:
                    self.on_mount_symbols_callback(selected_pairs, replace_existing=replace_existing)
                except TypeError:
                    self.on_mount_symbols_callback(selected_pairs)
                count = len(selected_pairs)
                mounted_summary = [f"{p['symbol']} ({p['strategy'].upper()}/{p['timeframe']})" for p in selected_pairs]
                summary_str = ", ".join(mounted_summary[:4]) + ("..." if count > 4 else "")
                if hasattr(self, "lbl_comp_status"):
                    self.lbl_comp_status.configure(
                        text=f"✅ {count} pares aplicados con sus estrategias óptimas: {summary_str}",
                        text_color="#34D399"
                    )
            except Exception as e:
                if hasattr(self, "lbl_comp_status"):
                    self.lbl_comp_status.configure(text=f"❌ Error al aplicar pares: {e}", text_color="#F87171")
        else:
            if hasattr(self, "lbl_comp_status"):
                self.lbl_comp_status.configure(
                    text=f"✅ {len(selected_pairs)} pares listos para aplicar.",
                    text_color="#34D399"
                )

    def _show_symbol_breakdown_dialog(self, symbol: str, comparison: List[Dict[str, Any]]) -> None:
        """Muestra un modal con el desglose detallado de todas las estrategias evaluadas para ese símbolo."""
        dlg = ctk.CTkToplevel(self)
        dlg.title(f"📊 Desglose Multiestrategia: {symbol}")
        dlg.geometry("660x380")
        dlg.configure(fg_color="#181a20")
        try:
            dlg.transient(self)
            dlg.grab_set()
        except Exception:
            pass

        lbl_head = ctk.CTkLabel(
            dlg,
            text=f"🔍 Rendimiento por Estrategia en {symbol}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#38BDF8"
        )
        lbl_head.pack(padx=16, pady=(14, 4), anchor="w")

        lbl_sub = ctk.CTkLabel(
            dlg,
            text="Comparación directa vela a vela de cada algoritmo evaluado en este activo:",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8"
        )
        lbl_sub.pack(padx=16, pady=(0, 10), anchor="w")

        # Tabla interna
        head_row = ctk.CTkFrame(dlg, fg_color="#131722", height=26, corner_radius=4)
        head_row.pack(fill="x", padx=14, pady=(0, 4))

        for col_name, w in [
            ("Puesto", 55),
            ("Estrategia", 110),
            ("Timeframe", 70),
            ("Win Rate", 85),
            ("Avg R", 80),
            ("Operaciones", 85),
            ("Acción", 100),
        ]:
            lbl = ctk.CTkLabel(
                head_row,
                text=col_name,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#94A3B8",
                width=w,
                anchor="center"
            )
            lbl.pack(side="left", padx=2, pady=2)

        scroll_dlg = ctk.CTkScrollableFrame(dlg, fg_color="#161a23", corner_radius=6)
        scroll_dlg.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        tf_labels = {
            mt5.TIMEFRAME_M1: "M1", mt5.TIMEFRAME_M5: "M5", mt5.TIMEFRAME_M15: "M15",
            mt5.TIMEFRAME_M30: "M30", mt5.TIMEFRAME_H1: "H1", mt5.TIMEFRAME_H4: "H4", mt5.TIMEFRAME_D1: "D1",
        }

        if not comparison:
            lbl_no_data = ctk.CTkLabel(
                scroll_dlg,
                text=f"No hay registros comparativos guardados para {symbol}.",
                font=ctk.CTkFont(size=11),
                text_color="#64748B"
            )
            lbl_no_data.pack(pady=20)
        else:
            for rank_idx, c_item in enumerate(comparison):
                strat = c_item.get("strategy", "unknown")
                raw_tf = c_item.get("timeframe", "M5")
                tf_name = tf_labels.get(raw_tf, str(raw_tf))
                wr = c_item.get("win_rate", 0.0)
                avg_r = c_item.get("avg_r", 0.0)
                trades = c_item.get("trades", 0)
                wins = c_item.get("wins", 0)
                losses = c_item.get("losses", 0)

                is_best = (rank_idx == 0)
                row_f = ctk.CTkFrame(
                    scroll_dlg,
                    fg_color="#1e2433" if is_best else "#1e222d",
                    corner_radius=4,
                    height=30
                )
                row_f.pack(fill="x", pady=2, padx=2)

                medal = "🥇 1°" if rank_idx == 0 else ("🥈 2°" if rank_idx == 1 else ("🥉 3°" if rank_idx == 2 else f"{rank_idx+1}°"))
                lbl_rank = ctk.CTkLabel(
                    row_f,
                    text=medal,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#FBBF24" if is_best else "#94A3B8",
                    width=55,
                    anchor="center"
                )
                lbl_rank.pack(side="left", padx=2)

                lbl_strat = ctk.CTkLabel(
                    row_f,
                    text=strat.upper(),
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#34D399" if is_best else "#E2E8F0",
                    width=110,
                    anchor="w"
                )
                lbl_strat.pack(side="left", padx=2)

                lbl_tf = ctk.CTkLabel(
                    row_f,
                    text=tf_name,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#A78BFA",
                    width=70,
                    anchor="center"
                )
                lbl_tf.pack(side="left", padx=2)

                wr_color = "#34D399" if wr >= 50.0 else "#F87171"
                lbl_wr = ctk.CTkLabel(
                    row_f,
                    text=f"{wr:.1f}%",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=wr_color,
                    width=85,
                    anchor="center"
                )
                lbl_wr.pack(side="left", padx=2)

                r_color = "#34D399" if avg_r > 0 else ("#94A3B8" if avg_r == 0 else "#F87171")
                lbl_r = ctk.CTkLabel(
                    row_f,
                    text=f"{avg_r:+.2f}R",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=r_color,
                    width=80,
                    anchor="center"
                )
                lbl_r.pack(side="left", padx=2)

                lbl_ops = ctk.CTkLabel(
                    row_f,
                    text=f"{trades} ({wins}W/{losses}L)",
                    font=ctk.CTkFont(size=10),
                    text_color="#CBD5E1",
                    width=85,
                    anchor="center"
                )
                lbl_ops.pack(side="left", padx=2)

                btn_choose = ctk.CTkButton(
                    row_f,
                    text="⚡ Asignar",
                    width=90,
                    height=24,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    fg_color="#059669" if is_best else "#334155",
                    hover_color="#047857" if is_best else "#475569",
                    command=lambda s=symbol, st=strat, t=tf_name, w=wr, ar=avg_r, tr=trades: (
                        self._mount_single_best_strategy({
                            "symbol": s,
                            "best_strategy": st,
                            "timeframe": t,
                            "win_rate": w,
                            "avg_r": ar,
                            "trades": tr
                        }),
                        dlg.destroy()
                    )
                )
                btn_choose.pack(side="left", padx=2)

    def destroy(self) -> None:
        """Limpia los menús nativos y sub-widgets al cerrar la ventana para evitar el error 'no more menus can be allocated'."""
        menu_widgets = [
            getattr(self, "opt_strat", None),
            getattr(self, "opt_days", None),
            getattr(self, "opt_tf", None),
            getattr(self, "opt_sort", None)
        ]
        for w in menu_widgets:
            if w is not None:
                try:
                    if hasattr(w, "_dropdown_menu") and w._dropdown_menu:
                        w._dropdown_menu.destroy()
                except Exception:
                    pass
        super().destroy()
