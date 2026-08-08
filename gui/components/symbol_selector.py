import customtkinter as ctk
from typing import List, Callable, Dict, Any, Optional


class SymbolSelectorComponent(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        symbols: List[str],
        available_symbols: Optional[List[str]] = None,
        on_toggle_callback: Optional[Callable[[str, bool], None]] = None,
        on_symbols_changed_callback: Optional[Callable[[List[str]], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(master, **kwargs)

        self.symbols: List[str] = list(symbols)
        self.available_symbols: List[str] = available_symbols or []
        self.on_toggle_callback = on_toggle_callback
        self.on_symbols_changed_callback = on_symbols_changed_callback

        self.switch_vars: Dict[str, ctk.BooleanVar] = {}
        self.status_labels: Dict[str, ctk.CTkLabel] = {}
        self.suggestion_buttons: List[ctk.CTkButton] = []

        self._build_ui()

    def update_available_symbols(self, new_available: List[str]) -> None:
        """Actualiza la lista base para el autocomplete."""
        self.available_symbols = new_available

    def _build_ui(self) -> None:
        # Header / Barra superior
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=10, pady=(10, 5))

        lbl_title = ctk.CTkLabel(
            top_frame,
            text="🎯 Selección & Monitoreo de Símbolos",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        lbl_title.pack(side="left")

        # Selector Autocomplete + Botón Agregar
        self.input_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.input_frame.pack(fill="x", padx=10, pady=(0, 5))

        self.entry_symbol = ctk.CTkEntry(
            self.input_frame,
            placeholder_text="🔍 Escribe para buscar (ej: EURUSD)..."
        )
        self.entry_symbol.pack(side="left", padx=(0, 5), fill="x", expand=True)
        self.entry_symbol.bind("<KeyRelease>", self._on_key_release_filter)
        self.entry_symbol.bind("<FocusOut>", self._on_focus_out)

        btn_add = ctk.CTkButton(
            self.input_frame,
            text="➕ Añadir",
            width=80,
            command=self._add_symbol
        )
        btn_add.pack(side="right")

        # Marco flotante para Sugerencias (se crea antes de scroll_frame)
        self.suggestions_frame = ctk.CTkScrollableFrame(self, height=110, fg_color="#1e1e1e")

        # Contenedor con scroll para la lista de símbolos activos
        self.scroll_frame = ctk.CTkScrollableFrame(self, height=180)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._render_symbol_items()

    def _on_key_release_filter(self, event: Any) -> None:
        """Muestra automáticamente una lista desplegable filtrada al escribir."""
        query = self.entry_symbol.get().strip().lower()

        # Limpiar sugerencias anteriores
        for btn in self.suggestion_buttons:
            btn.destroy()
        self.suggestion_buttons.clear()

        if not query or not self.available_symbols:
            self._hide_suggestions()
            return

        filtered = [s for s in self.available_symbols if query in s.lower()]

        if not filtered:
            self._hide_suggestions()
            return

        # Reordenar elementos mediante pack/pack_forget sin usar 'before'
        self.scroll_frame.pack_forget()
        self.suggestions_frame.pack(fill="x", padx=10, pady=(0, 5))
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        for sym in filtered[:6]:  # Mostrar máximo 6 coincidencias
            btn = ctk.CTkButton(
                self.suggestions_frame,
                text=sym,
                anchor="w",
                fg_color="transparent",
                hover_color="#333333",
                text_color="#E0E0E0",
                height=25,
                command=lambda s=sym: self._select_suggestion(s)
            )
            btn.pack(fill="x", padx=2, pady=1)
            self.suggestion_buttons.append(btn)

    def _select_suggestion(self, symbol: str) -> None:
        self.entry_symbol.delete(0, "end")
        self.entry_symbol.insert(0, symbol)
        self._hide_suggestions()

    def _on_focus_out(self, event: Any) -> None:
        # Retardo breve para dar tiempo a que se procese el click en los botones de sugerencias
        self.after(250, self._hide_suggestions)

    def _hide_suggestions(self, *args: Any) -> None:
        """Oculta las sugerencias de la lista."""
        if hasattr(self, "suggestions_frame"):
            self.suggestions_frame.pack_forget()

    def _render_symbol_items(self) -> None:
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        self.switch_vars.clear()
        self.status_labels.clear()

        for symbol in self.symbols:
            row_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)

            var = ctk.BooleanVar(value=True)
            self.switch_vars[symbol] = var

            switch = ctk.CTkSwitch(
                row_frame,
                text=symbol,
                variable=var,
                command=lambda s=symbol: self._handle_toggle(s)
            )
            switch.pack(side="left", padx=5)

            btn_remove = ctk.CTkButton(
                row_frame,
                text="❌",
                width=30,
                height=24,
                fg_color="#dc3545",
                hover_color="#c82333",
                command=lambda s=symbol: self._remove_symbol(s)
            )
            btn_remove.pack(side="right", padx=(0, 5))

            lbl_status = ctk.CTkLabel(row_frame, text="🟢 Monitoreando", text_color="#2ea043")
            lbl_status.pack(side="right", padx=5)
            self.status_labels[symbol] = lbl_status

    def _add_symbol(self) -> None:
        new_symbol = self.entry_symbol.get().strip()
        if not new_symbol:
            return

        if new_symbol not in self.symbols:
            self.symbols.append(new_symbol)
            self._render_symbol_items()
            self.entry_symbol.delete(0, "end")
            self._hide_suggestions()

            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _remove_symbol(self, symbol: str) -> None:
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            self._render_symbol_items()

            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _handle_toggle(self, symbol: str) -> None:
        is_active = self.switch_vars[symbol].get()
        lbl = self.status_labels[symbol]

        if is_active:
            lbl.configure(text="🟢 Monitoreando", text_color="#2ea043")
        else:
            lbl.configure(text="⚪ Inactivo", text_color="gray")

        if self.on_toggle_callback:
            self.on_toggle_callback(symbol, is_active)

    def get_active_symbols(self) -> List[str]:
        return [sym for sym, var in self.switch_vars.items() if var.get()]
