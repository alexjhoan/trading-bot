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
        self.lbl_sl_pips: Dict[str, ctk.CTkLabel] = {}
        self.suggestion_buttons: List[ctk.CTkButton] = []

        self._build_ui()

    def set_max_risk_usd(self, risk_usd: float) -> None:
        """Actualiza el riesgo máximo en USD proveniente del Balance * % de la Sidebar."""
        self.max_risk_usd = risk_usd
        # Recalcular las etiquetas de pips para todos los símbolos
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
                command=lambda s=symbol: self._on_switch_toggled(s)
            )
            switch.pack(side="left", padx=10, pady=8)

            # Botón Eliminar
            btn_del = ctk.CTkButton(
                row,
                text="❌",
                width=30,
                height=25,
                fg_color="#991B1B",
                hover_color="#7F1D1D",
                command=lambda s=symbol: self._remove_symbol(s)
            )
            btn_del.pack(side="right", padx=(5, 10))

            # Contenedor para Lote Manual (Directo al broker)
            lot_frame = ctk.CTkFrame(row, fg_color="transparent")
            lot_frame.pack(side="right", padx=10)

            lbl_lot_tag = ctk.CTkLabel(lot_frame, text="Lote:", font=ctk.CTkFont(size=12))
            lbl_lot_tag.pack(side="left", padx=(0, 2))

            entry_lot = ctk.CTkEntry(lot_frame, width=65)
            default_lot = self.symbol_lots.get(symbol, 0.01)
            entry_lot.insert(0, str(default_lot))
            entry_lot.pack(side="left", padx=(0, 5))
            entry_lot.bind("<KeyRelease>", lambda e, s=symbol: self._on_lot_entry_changed(s))
            self.entry_lots[symbol] = entry_lot

            # Label dinámico para mostrar cuántos pips equivale el SL
            lbl_pips = ctk.CTkLabel(
                lot_frame,
                text="SL: 0 Pips",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#3B82F6"
            )
            lbl_pips.pack(side="left", padx=(5, 0))
            self.lbl_sl_pips[symbol] = lbl_pips

            # Calcular los pips iniciales
            self._update_sl_pips_label(symbol)

    def _update_sl_pips_label(self, symbol: str) -> None:
        """Calcula los pips de Stop Loss basados en el LOTE FIJO y el RIESGO en USD."""
        if symbol not in self.entry_lots or symbol not in self.lbl_sl_pips:
            return

        try:
            lot = float(self.entry_lots[symbol].get().replace(",", "."))
            if lot <= 0:
                self.lbl_sl_pips[symbol].configure(text="SL: --")
                return
        except ValueError:
            self.lbl_sl_pips[symbol].configure(text="SL: Error")
            return

        # -----------------------------------------------------------------
        # Obtener información del símbolo directamente de MT5
        # -----------------------------------------------------------------
        info = mt5.symbol_info(symbol)
        if info is None:
            # Si no hay datos de MT5 aún, estimación genérica Forex (1 pip = $10 / lote)
            sl_pips = self.max_risk_usd / (lot * 10.0) if lot > 0 else 0
            self.lbl_sl_pips[symbol].configure(text=f"SL: ~{sl_pips:.1f} pips")
            return

        # 1. Determinar tamaño de pip (Forex vs Sintéticos/Criptos)
        # En Forex (5 dígitos): point = 0.00001, pip_size = 0.0001 (point * 10)
        # En Sintéticos / Índices: pip_size = point
        pip_size = info.point * 10.0 if info.digits in (3, 5) else info.point

        # 2. Obtener el valor en USD de un Tick/Punto por cada 1 Lote
        tick_value = info.trade_tick_value
        tick_size = info.trade_tick_size

        if tick_value == 0 or tick_size == 0:
            # Fallback a contract_size si la terminal aún no liquida el tick
            pip_value_per_lot = info.trade_contract_size * pip_size
        else:
            # Valor real de 1 Pip por 1 Lote completo
            pip_value_per_lot = (tick_value / tick_size) * pip_size

        # 3. Calcular la distancia de SL en pips para NO superar max_risk_usd
        if pip_value_per_lot > 0 and lot > 0:
            sl_pips = self.max_risk_usd / (lot * pip_value_per_lot)
            self.lbl_sl_pips[symbol].configure(text=f"SL: {sl_pips:.1f} pips")
        else:
            self.lbl_sl_pips[symbol].configure(text="SL: --")

    def _on_lot_entry_changed(self, symbol: str) -> None:
        self._update_sl_pips_label(symbol)
        if self.on_lot_changed_callback:
            try:
                val = float(self.entry_lots[symbol].get().replace(",", "."))
                self.on_lot_changed_callback(symbol, val)
            except ValueError:
                pass

    def _on_switch_toggled(self, symbol: str) -> None:
        is_active = self.switch_vars[symbol].get()
        if self.on_toggle_callback:
            self.on_toggle_callback(symbol, is_active)

    def _add_symbol(self) -> None:
        symbol = self.entry_symbol.get().strip().upper()
        if symbol and symbol not in self.symbols:
            self.symbols.append(symbol)
            self.entry_symbol.delete(0, "end")
            self._hide_suggestions()
            self._render_symbol_list()

            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _remove_symbol(self, symbol: str) -> None:
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            self._render_symbol_list()

            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _on_search_changed(self, event: Any) -> None:
        query = self.entry_symbol.get().strip().upper()
        if not query:
            self._hide_suggestions()
            return

        matches = [
            s for s in self.available_symbols
            if query in s.upper() and s not in self.symbols
        ][:5]

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

    def get_selected_symbols(self) -> List[str]:
        return [s for s, var in self.switch_vars.items() if var.get()]

    def get_symbol_lots(self) -> Dict[str, float]:
        lots = {}
        for s, entry in self.entry_lots.items():
            try:
                lots[s] = float(entry.get().replace(",", "."))
            except ValueError:
                lots[s] = 0.01
        return lots
