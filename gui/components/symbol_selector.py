import customtkinter as ctk
from typing import List, Callable, Dict, Any, Optional
import MetaTrader5 as mt5


class SymbolSelectorComponent(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        symbols: List[str],
        available_symbols: Optional[List[str]] = None,
        symbol_specs: Optional[Dict[str, Dict[str, Any]]] = None,
        symbol_lots: Optional[Dict[str, float]] = None,
        max_risk_usd: float = 10.0,
        on_toggle_callback: Optional[Callable[[str, bool], None]] = None,
        on_symbols_changed_callback: Optional[Callable[[List[str]], None]] = None,
        on_lot_changed_callback: Optional[Callable[[str, float], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(master, **kwargs)

        self.symbols: List[str] = list(symbols)
        self.available_symbols: List[str] = available_symbols or []
        self.symbol_specs: Dict[str, Dict[str, Any]] = symbol_specs or {}
        self.symbol_lots: Dict[str, float] = symbol_lots or {}
        self.max_risk_usd: float = max_risk_usd

        self.on_toggle_callback = on_toggle_callback
        self.on_symbols_changed_callback = on_symbols_changed_callback
        self.on_lot_changed_callback = on_lot_changed_callback

        self.switch_vars: Dict[str, ctk.BooleanVar] = {}
        self.entry_lots: Dict[str, ctk.CTkEntry] = {}
        self.lbl_risk_usd: Dict[str, ctk.CTkLabel] = {}
        self.lbl_sl_pips: Dict[str, ctk.CTkLabel] = {}
        self.suggestion_buttons: List[ctk.CTkButton] = []

        self._build_ui()

    def set_max_risk_usd(self, risk_usd: float) -> None:
        """Actualiza el riesgo máximo en USD proveniente del Balance * % de la Sidebar."""
        self.max_risk_usd = risk_usd
        # Recalcular las etiquetas de USD y Pips para todos los símbolos
        for symbol in self.symbols:
            self._update_sl_pips_label(symbol)

    def _build_ui(self) -> None:
        lbl_title = ctk.CTkLabel(
            self,
            text="🎯 Selección de Símbolos y Ajuste de Lotaje",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        lbl_title.pack(padx=15, pady=(15, 5), anchor="w")

        # Frame de Búsqueda
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(fill="x", padx=15, pady=5)

        self.entry_symbol = ctk.CTkEntry(
            search_frame,
            placeholder_text="Añadir símbolo (ej. EURUSD, Volatility 100 Index)..."
        )
        self.entry_symbol.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.entry_symbol.bind("<KeyRelease>", self._on_search_changed)

        btn_add = ctk.CTkButton(
            search_frame,
            text="➕ Añadir",
            width=80,
            command=self._add_symbol
        )
        btn_add.pack(side="right")

        # Frame de Sugerencias
        self.suggestions_frame = ctk.CTkFrame(self, fg_color="#1e1e1e")

        # Lista de símbolos activos
        self.symbols_container = ctk.CTkFrame(self, fg_color="transparent")
        self.symbols_container.pack(fill="both", expand=True, padx=15, pady=10)

        self._render_symbol_list()

    def _render_symbol_list(self) -> None:
        for widget in self.symbols_container.winfo_children():
            widget.destroy()

        self.switch_vars.clear()
        self.entry_lots.clear()
        self.lbl_risk_usd.clear()
        self.lbl_sl_pips.clear()

        for symbol in self.symbols:
            row = ctk.CTkFrame(self.symbols_container, fg_color="#2b2b2b")
            row.pack(fill="x", pady=4, padx=2)

            # Switch Activo/Inactivo
            var = ctk.BooleanVar(value=False)
            self.switch_vars[symbol] = var
            switch = ctk.CTkSwitch(
                row,
                text=symbol,
                variable=var,
                font=ctk.CTkFont(weight="bold"),
                command=lambda s=symbol: self._on_toggle(s)
            )
            switch.pack(side="left", padx=10, pady=8)

            # Botón Eliminar
            btn_del = ctk.CTkButton(
                row,
                text="❌",
                width=30,
                fg_color="#991B1B",
                hover_color="#7F1D1D",
                command=lambda s=symbol: self._remove_symbol(s)
            )
            btn_del.pack(side="right", padx=10)

            # Entrada de Lotaje
            lbl_lot = ctk.CTkLabel(row, text="Lote:")
            lbl_lot.pack(side="left", padx=(15, 2))

            specs = self.symbol_specs.get(symbol, {})
            min_lot = specs.get("volume_min", 0.01)
            default_lot = self.symbol_lots.get(symbol, min_lot)
            entry = ctk.CTkEntry(row, width=60)
            entry.insert(0, str(default_lot))
            entry.pack(side="left", padx=2)
            entry.bind("<KeyRelease>", lambda e, s=symbol: self._on_lot_changed(s))
            self.entry_lots[symbol] = entry

            # 1. Label de Pérdida en USD
            lbl_risk = ctk.CTkLabel(
                row,
                text=f"Riesgo: ${self.max_risk_usd:.2f}",
                text_color="#F59E0B",
                font=ctk.CTkFont(weight="bold")
            )
            lbl_risk.pack(side="left", padx=(15, 5))
            self.lbl_risk_usd[symbol] = lbl_risk

            # 2. Label de SL Dinámico en Pips
            lbl_pips = ctk.CTkLabel(
                row,
                text="SL Max: 0 pips",
                text_color="#10B981",
                font=ctk.CTkFont(weight="bold")
            )
            lbl_pips.pack(side="left", padx=5)
            self.lbl_sl_pips[symbol] = lbl_pips

            # Calcular el SL inicial
            self._update_sl_pips_label(symbol)

    def _update_sl_pips_label(self, symbol: str) -> None:
        """Actualiza las etiquetas de Riesgo $ y SL (pips) según el lotaje y max_risk_usd."""
        if symbol in self.lbl_risk_usd:
            self.lbl_risk_usd[symbol].configure(text=f"Riesgo: ${self.max_risk_usd:.2f}")

        try:
            lot_str = self.entry_lots[symbol].get().replace(",", ".")
            lot = float(lot_str)
            if lot <= 0:
                sl_pips = 0.0
            else:
                specs = self.symbol_specs.get(symbol, {})
                trade_tick_value = specs.get("trade_tick_value", 1.0)
                point = specs.get("point", 0.00001)
                digits = specs.get("digits", 5)
                tick_size = specs.get("trade_tick_size", point)

                # Definición del tamaño del pip según decimales (Forex 3/5 dígitos = 10 points; otros = 1 point/tick)
                pip_size = point * 10.0 if digits in (3, 5) else point
                ticks_per_pip = (pip_size / tick_size) if tick_size > 0 else 1.0

                # Valor en $ de 1 Pip para 1 lote estándar
                pip_value_std = trade_tick_value * ticks_per_pip

                # Pips = Riesgo USD / (Lotaje * Valor Pip Standard)
                sl_pips = self.max_risk_usd / (lot * pip_value_std)

            if symbol in self.lbl_sl_pips:
                self.lbl_sl_pips[symbol].configure(text=f"SL Max: {sl_pips:.1f} pips")
        except (ValueError, KeyError, ZeroDivisionError):
            if symbol in self.lbl_sl_pips:
                self.lbl_sl_pips[symbol].configure(text="SL Max: N/A")

    def _on_lot_changed(self, symbol: str) -> None:
        self._update_sl_pips_label(symbol)
        if self.on_lot_changed_callback:
            try:
                lot = float(self.entry_lots[symbol].get().replace(",", "."))
                self.symbol_lots[symbol] = lot
                self.on_lot_changed_callback(symbol, lot)
            except ValueError:
                pass

    def _add_symbol(self) -> None:
        sym = self.entry_symbol.get().strip()
        specs = self.symbol_specs.get(sym, {})
        min_lot = specs.get("volume_min", 0.01)

        if sym and sym not in self.symbols:
            self.symbols.append(sym)
            self.symbol_lots[sym] = min_lot
            self.entry_symbol.delete(0, "end")
            self._render_symbol_list()
            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _remove_symbol(self, symbol: str) -> None:
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            self.symbol_lots.pop(symbol, None)
            self._render_symbol_list()
            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _on_search_changed(self, event: Any) -> None:
        query = self.entry_symbol.get().strip().upper()
        if not query:
            self._hide_suggestions()
            return

        matches = [s for s in self.available_symbols if query in s.upper()][:5]
        if matches:
            self._show_suggestions(matches)
        else:
            self._hide_suggestions()

    def _show_suggestions(self, matches: List[str]) -> None:
        for btn in self.suggestion_buttons:
            btn.destroy()
        self.suggestion_buttons.clear()

        self.suggestions_frame.pack(fill="x", padx=15, pady=(0, 5))

        for symbol in matches:
            btn = ctk.CTkButton(
                self.suggestions_frame,
                text=symbol,
                anchor="w",
                fg_color="#2b2b2b",
                hover_color="#3b3b3b",
                height=25,
                command=lambda s=symbol: self._select_suggestion(s),
            )
            btn.pack(fill="x", pady=1)
            self.suggestion_buttons.append(btn)

    def _select_suggestion(self, symbol: str) -> None:
        self.entry_symbol.delete(0, "end")
        self.entry_symbol.insert(0, symbol)
        self._hide_suggestions()
        self._add_symbol()

    def _hide_suggestions(self) -> None:
        for btn in self.suggestion_buttons:
            btn.destroy()
        self.suggestion_buttons.clear()
        self.suggestions_frame.pack_forget()

    def update_available_symbols(self, available: List[str]) -> None:
        self.available_symbols = available

    def get_selected_symbols(self) -> List[str]:
        return [s for s, var in self.switch_vars.items() if var.get()]

    def get_symbol_lots(self) -> Dict[str, float]:
        return self.symbol_lots

    def set_inputs_enabled(self, force_all_disabled: bool = False) -> None:
        """
        Garantiza que:
        - Si force_all_disabled es True (hay operaciones reales en MT5), bloquea todo.
        - Si force_all_disabled es False, deshabilita solo los lotes de los símbolos con switch ACTIVO.
        """
        for symbol, entry in self.entry_lots.items():
            is_switch_on = self.switch_vars.get(symbol, ctk.BooleanVar()).get()
            should_disable = force_all_disabled or is_switch_on

            if should_disable:
                entry.configure(
                    state="disabled",
                    fg_color="#1F1F1F",
                    text_color="#666666"
                )
            else:
                entry.configure(
                    state="normal",
                    fg_color="#333333",
                    text_color="#FFFFFF"
                )

    def _on_toggle(self, symbol: str) -> None:
        """Se ejecuta inmediatamente al presionar el switch de un símbolo."""
        is_active = self.switch_vars[symbol].get()

        # 1. Actualizar el estado visual e interactivo de este símbolo individual
        self._update_single_symbol_input_state(symbol)

        # 2. Ejecutar el callback en app.py (crear/destruir worker y refrescar sidebar)
        if self.on_toggle_callback:
            self.on_toggle_callback(symbol, is_active)

    def _update_single_symbol_input_state(self, symbol: str, force_disable: bool = False) -> None:
        """Actualiza el estado de un único input de lotaje según su switch individual."""
        if symbol not in self.entry_lots:
            return

        entry = self.entry_lots[symbol]
        is_switch_on = self.switch_vars.get(symbol, ctk.BooleanVar()).get()
        should_disable = force_disable or is_switch_on

        if should_disable:
            entry.configure(
                state="disabled",
                fg_color="#1A1A1A",   # Gris muy oscuro (desvanecido)
                text_color="#555555"  # Texto apagado
            )
        else:
            entry.configure(
                state="normal",
                fg_color="#333333",   # Color normal
                text_color="#FFFFFF"  # Texto blanco
            )
        entry.update_idletasks()

    def update_all_inputs_state(self, force_all_disabled: bool = False) -> None:
        """
        Recorre todos los símbolos y actualiza sus inputs individualmente.
        Si force_all_disabled es True (operaciones reales en MT5), bloquea todos.
        Si es False, evalúa el switch de cada símbolo por separado.
        """
        for symbol in self.symbols:
            self._update_single_symbol_input_state(symbol, force_disable=force_all_disabled)

    def update_symbol_specs(self, symbol_specs: Dict[str, Dict[str, Any]]) -> None:
        """Actualiza el diccionario de especificaciones de símbolos y refresca la UI."""
        self.symbol_specs = symbol_specs
        for symbol in self.symbols:
            self._update_sl_pips_label(symbol)
