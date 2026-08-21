import customtkinter as ctk
from typing import List, Callable, Dict, Any, Optional
import MetaTrader5 as mt5
from datetime import datetime

from config import STRATEGY_CONFIG

TIMEFRAME_MAP: Dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


class SymbolSelectorComponent(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        symbols: List[str],
        available_symbols: Optional[List[str]] = None,
        symbol_specs: Optional[Dict[str, Dict[str, Any]]] = None,
        symbol_lots: Optional[Dict[str, float]] = None,
        symbol_risk_pcts: Optional[Dict[str, float]] = None,
        symbol_timeframes: Optional[Dict[str, str]] = None,
        account_balance: float = 0.0,
        on_toggle_callback: Optional[Callable[[str, bool], None]] = None,
        on_symbols_changed_callback: Optional[Callable[[List[str]], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(master, **kwargs)

        self.symbols: List[str] = list(symbols)
        self.available_symbols: List[str] = available_symbols or []
        self.symbol_specs: Dict[str, Dict[str, Any]] = symbol_specs or {}
        self.symbol_lots: Dict[str, float] = symbol_lots or {}
        self.symbol_risk_pcts: Dict[str, float] = symbol_risk_pcts or {}
        self.symbol_timeframes: Dict[str, str] = symbol_timeframes or {}
        self.account_balance: float = account_balance

        self.on_toggle_callback = on_toggle_callback
        self.on_symbols_changed_callback = on_symbols_changed_callback

        self.switch_vars: Dict[str, ctk.BooleanVar] = {}
        self.entry_lots: Dict[str, ctk.CTkEntry] = {}
        self.entry_risk_pcts: Dict[str, ctk.CTkEntry] = {}
        self.opt_timeframes: Dict[str, ctk.CTkOptionMenu] = {}
        self.lbl_risk_usd: Dict[str, ctk.CTkLabel] = {}
        self.lbl_sl_pips: Dict[str, ctk.CTkLabel] = {}
        self.lbl_schedule_dict: Dict[str, ctk.CTkLabel] = {}
        self.symbol_rows: Dict[str, ctk.CTkFrame] = {}
        self.suggestion_buttons: List[ctk.CTkButton] = []

        self._build_ui()

    def set_account_balance(self, balance: float) -> None:
        """Actualiza el balance de la cuenta para recalcular el riesgo USD en cada par."""
        self.account_balance = balance
        for symbol in self.symbols:
            self._update_symbol_calc(symbol)

    def _build_ui(self) -> None:
        # Título
        lbl_title = ctk.CTkLabel(
            self,
            text="🎯 Selección de Símbolos y Configuración por Par",
            font=ctk.CTkFont(size=15, weight="bold")
        )
        lbl_title.pack(padx=15, pady=(12, 5), anchor="w")

        # Frame de Búsqueda
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(fill="x", padx=15, pady=4)

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

        # Frame Encabezado de Tabla (<th>)
        self._build_table_header()

        # Lista de símbolos activos
        self.symbols_container = ctk.CTkScrollableFrame(self, fg_color="transparent", height=200)
        self.symbols_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Renderizar filas iniciales
        for symbol in self.symbols:
            self._add_symbol_row(symbol)

        # Iniciar loop periódico de actualización de colores de horario (cada segundo)
        self._start_schedule_clock_loop()

    def _start_schedule_clock_loop(self) -> None:
        """Loop continuo para actualizar el color del horario en tiempo real cuando llega la hora de apertura/cierre."""
        try:
            self.update_schedules_color()
        except Exception:
            pass
        self.after(1000, self._start_schedule_clock_loop)

    def _build_table_header(self) -> None:
        """Crea la fila de encabezados tipo tabla (<th>) con títulos de columnas."""
        header = ctk.CTkFrame(self, fg_color="#1a1a1a", height=30, corner_radius=4)
        header.pack(fill="x", padx=10, pady=(8, 2))

        headers = [
            ("Activo", 60),
            ("Símbolo", 110),
            ("Lote", 70),
            ("Riesgo %", 70),
            ("Riesgo $", 80),
            ("SL Máx", 90),
            ("Timeframe", 80),
            ("Horario", 115),
            ("Acciones", 50),
        ]

        for text, width in headers:
            lbl = ctk.CTkLabel(
                header,
                text=text,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#AAAAAA",
                width=width,
                anchor="center"
            )
            lbl.pack(side="left", padx=2, pady=4)

    def _add_symbol_row(self, symbol: str) -> None:
        """Añade una nueva fila de símbolo a la tabla preservando las filas existentes."""
        if symbol in self.symbol_rows:
            return

        row = ctk.CTkFrame(self.symbols_container, fg_color="#2b2b2b", corner_radius=6)
        row.pack(fill="x", pady=3, padx=2)
        self.symbol_rows[symbol] = row

        # 1. Switch Activo (width ~60)
        var = ctk.BooleanVar(value=False)
        self.switch_vars[symbol] = var
        switch = ctk.CTkSwitch(
            row,
            text="",
            variable=var,
            width=50,
            command=lambda s=symbol: self._on_toggle(s)
        )
        switch.pack(side="left", padx=(10, 0), pady=6)

        # 2. Símbolo Label (width ~110)
        lbl_sym = ctk.CTkLabel(
            row,
            text=symbol,
            font=ctk.CTkFont(size=12, weight="bold"),
            width=100,
            anchor="w"
        )
        lbl_sym.pack(side="left", padx=5)

        # 3. Lote Entry (width ~70)
        specs = self.symbol_specs.get(symbol, {})
        min_lot = specs.get("volume_min", 0.01)
        default_lot = self.symbol_lots.get(symbol, min_lot)
        entry_lot = ctk.CTkEntry(row, width=65, justify="center")
        entry_lot.insert(0, str(default_lot))
        entry_lot.pack(side="left", padx=3)
        entry_lot.bind("<KeyRelease>", lambda e, s=symbol: self._on_input_changed(s))
        self.entry_lots[symbol] = entry_lot

        # 4. Riesgo % Entry (width ~70)
        default_risk = self.symbol_risk_pcts.get(symbol, 1.0)
        entry_risk = ctk.CTkEntry(row, width=65, justify="center")
        entry_risk.insert(0, str(default_risk))
        entry_risk.pack(side="left", padx=3)
        entry_risk.bind("<KeyRelease>", lambda e, s=symbol: self._on_input_changed(s))
        self.entry_risk_pcts[symbol] = entry_risk

        # 5. Riesgo $ Label (width ~80)
        lbl_risk = ctk.CTkLabel(
            row,
            text="$0.00",
            text_color="#F59E0B",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=75,
            anchor="center"
        )
        lbl_risk.pack(side="left", padx=3)
        self.lbl_risk_usd[symbol] = lbl_risk

        # 6. SL Máx Pips Label (width ~90)
        lbl_pips = ctk.CTkLabel(
            row,
            text="0.0 pips",
            text_color="#10B981",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=85,
            anchor="center"
        )
        lbl_pips.pack(side="left", padx=3)
        self.lbl_sl_pips[symbol] = lbl_pips

        # 7. Timeframe OptionMenu (width ~80)
        default_tf = self.symbol_timeframes.get(symbol, "M1")
        opt_tf = ctk.CTkOptionMenu(
            row,
            values=list(TIMEFRAME_MAP.keys()),
            width=75,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        opt_tf.set(default_tf)
        opt_tf.pack(side="left", padx=3)
        self.opt_timeframes[symbol] = opt_tf

        # 8. Horario Label (width ~115)
        start_time, end_time = STRATEGY_CONFIG.get_session_times_for_symbol(symbol)
        schedule_text = f"🕒 {start_time}-{end_time}"
        is_active_session = self.is_current_time_in_range(symbol, start_time, end_time)
        text_color = "#2ECC71" if is_active_session else "#E74C3C"

        lbl_schedule = ctk.CTkLabel(
            row,
            text=schedule_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=text_color,
            width=110,
            anchor="center"
        )
        lbl_schedule.pack(side="left", padx=3)
        self.lbl_schedule_dict[symbol] = lbl_schedule

        # 9. Botón Eliminar (width ~50)
        btn_del = ctk.CTkButton(
            row,
            text="❌",
            width=32,
            fg_color="#991B1B",
            hover_color="#7F1D1D",
            command=lambda s=symbol: self._remove_symbol(s)
        )
        btn_del.pack(side="left", padx=(5, 10))

        # Calcular valores iniciales de la fila
        self._update_symbol_calc(symbol)

    @staticmethod
    def is_current_time_in_range(symbol: str, start_str: str, end_str: str) -> bool:
        """
        Comprueba si el mercado esta abierto para el simbolo y si la hora local se encuentra dentro del rango horario.
        """
        try:
            # 1. Validar si el mercado está abierto (retorna False si el mercado está cerrado/fin de semana)
            market_open, _ = STRATEGY_CONFIG.is_market_open(symbol)
            if not market_open:
                return False

            now_time = datetime.now().time()
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()

            if start_time <= end_time:
                return start_time <= now_time <= end_time
            else:
                return now_time >= start_time or now_time <= end_time
        except Exception:
            return False

    def update_schedules_color(self) -> None:
        """Actualiza el color de todos los labels de horario segun la hora actual."""
        for symbol, lbl in self.lbl_schedule_dict.items():
            start_time, end_time = STRATEGY_CONFIG.get_session_times_for_symbol(symbol)
            is_active_session = self.is_current_time_in_range(symbol, start_time, end_time)
            text_color = "#2ECC71" if is_active_session else "#E74C3C"
            lbl.configure(text_color=text_color)

    def _update_symbol_calc(self, symbol: str) -> None:
        """Calcula el Riesgo en USD y SL en pips para un símbolo específico."""
        if symbol not in self.entry_lots or symbol not in self.entry_risk_pcts:
            return

        try:
            lot_str = self.entry_lots[symbol].get().replace(",", ".").strip()
            risk_str = self.entry_risk_pcts[symbol].get().replace(",", ".").strip()

            lot = float(lot_str) if lot_str else 0.01
            risk_pct = float(risk_str) if risk_str else 1.0

            # 1. Riesgo USD = Balance * (Riesgo % / 100)
            risk_usd = self.account_balance * (risk_pct / 100.0) if self.account_balance > 0 else 0.0
            if symbol in self.lbl_risk_usd:
                self.lbl_risk_usd[symbol].configure(text=f"${risk_usd:.2f}")

            # 2. SL Pips
            if lot <= 0 or risk_usd <= 0:
                sl_pips = 0.0
            else:
                specs = self.symbol_specs.get(symbol, {})
                trade_tick_value = specs.get("trade_tick_value", 1.0)
                point = specs.get("point", 0.00001)
                digits = specs.get("digits", 5)
                tick_size = specs.get("trade_tick_size", point)

                pip_size = point * 10.0 if digits in (3, 5) else point
                ticks_per_pip = (pip_size / tick_size) if tick_size > 0 else 1.0
                pip_value_std = trade_tick_value * ticks_per_pip

                sl_pips = risk_usd / (lot * pip_value_std)

            if symbol in self.lbl_sl_pips:
                self.lbl_sl_pips[symbol].configure(text=f"{sl_pips:.1f} pips")
        except (ValueError, KeyError, ZeroDivisionError):
            if symbol in self.lbl_sl_pips:
                self.lbl_sl_pips[symbol].configure(text="N/A")

    def _on_input_changed(self, symbol: str) -> None:
        self._update_symbol_calc(symbol)
        try:
            if symbol in self.entry_lots:
                lot_str = self.entry_lots[symbol].get().replace(",", ".").strip()
                if lot_str:
                    self.symbol_lots[symbol] = float(lot_str)
            if symbol in self.entry_risk_pcts:
                risk_str = self.entry_risk_pcts[symbol].get().replace(",", ".").strip()
                if risk_str:
                    self.symbol_risk_pcts[symbol] = float(risk_str)
            if symbol in self.opt_timeframes:
                self.symbol_timeframes[symbol] = self.opt_timeframes[symbol].get()
        except Exception:
            pass

    def _add_symbol(self) -> None:
        raw_sym = self.entry_symbol.get().strip()
        if not raw_sym:
            return

        # Buscar si existe coincidencia exacta (insensible a mayúsculas) en available_symbols (nombres reales de MT5)
        matched = None
        for s in self.available_symbols:
            if s.lower() == raw_sym.lower():
                matched = s
                break

        sym = matched if matched else raw_sym

        specs = self.symbol_specs.get(sym, {})
        min_lot = specs.get("volume_min", 0.01)

        if sym not in self.symbols:
            self.symbols.append(sym)
            self.symbol_lots[sym] = min_lot
            self.symbol_risk_pcts[sym] = 1.0
            self.symbol_timeframes[sym] = "M1"
            self.entry_symbol.delete(0, "end")
            self._hide_suggestions()

            # Añadir SOLO la nueva fila manteniendo intactas las existentes
            self._add_symbol_row(sym)

            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _remove_symbol(self, symbol: str) -> None:
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            self.symbol_lots.pop(symbol, None)
            self.symbol_risk_pcts.pop(symbol, None)
            self.symbol_timeframes.pop(symbol, None)

            # Eliminar widgets de esta fila únicamente
            if symbol in self.symbol_rows:
                self.symbol_rows[symbol].destroy()
                del self.symbol_rows[symbol]

            self.switch_vars.pop(symbol, None)
            self.entry_lots.pop(symbol, None)
            self.entry_risk_pcts.pop(symbol, None)
            self.opt_timeframes.pop(symbol, None)
            self.lbl_risk_usd.pop(symbol, None)
            self.lbl_sl_pips.pop(symbol, None)
            self.lbl_schedule_dict.pop(symbol, None)

            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _on_search_changed(self, event: Any) -> None:
        query = self.entry_symbol.get().strip().lower()
        if not query:
            self._hide_suggestions()
            return

        matches = [s for s in self.available_symbols if query in s.lower()][:5]
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
            start_time, end_time = STRATEGY_CONFIG.get_session_times_for_symbol(symbol)
            display_text = f"{symbol} -- 🕒 {start_time}-{end_time}"

            btn = ctk.CTkButton(
                self.suggestions_frame,
                text=display_text,
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

    def _on_toggle(self, symbol: str) -> None:
        """Se ejecuta al presionar el switch de un símbolo."""
        is_active = self.switch_vars[symbol].get()

        # Bloquear o desbloquear SOLO los controles de este par específico
        self._update_single_symbol_input_state(symbol)

        if self.on_toggle_callback:
            self.on_toggle_callback(symbol, is_active)

    def _update_single_symbol_input_state(self, symbol: str) -> None:
        """Actualiza los inputs de un símbolo especifico según si su switch individual está activado."""
        if symbol not in self.entry_lots:
            return

        is_switch_on = self.switch_vars.get(symbol, ctk.BooleanVar()).get()

        entry_lot = self.entry_lots[symbol]
        entry_risk = self.entry_risk_pcts[symbol]
        opt_tf = self.opt_timeframes[symbol]

        if is_switch_on:
            entry_lot.configure(state="disabled", fg_color="#1A1A1A", text_color="#555555")
            entry_risk.configure(state="disabled", fg_color="#1A1A1A", text_color="#555555")
            opt_tf.configure(state="disabled")
        else:
            entry_lot.configure(state="normal", fg_color="#333333", text_color="#FFFFFF")
            entry_risk.configure(state="normal", fg_color="#333333", text_color="#FFFFFF")
            opt_tf.configure(state="normal")

    def update_available_symbols(self, available: List[str]) -> None:
        self.available_symbols = available

    def update_symbol_specs(self, symbol_specs: Dict[str, Dict[str, Any]]) -> None:
        self.symbol_specs = symbol_specs
        for symbol in self.symbols:
            self._update_symbol_calc(symbol)

    def is_symbol_active(self, symbol: str) -> bool:
        """Indica si el switch de este símbolo está encendido."""
        if symbol in self.switch_vars:
            return bool(self.switch_vars[symbol].get())
        return False

    def ensure_symbol_present(self, symbol: str, lot: Optional[float] = None) -> None:
        """Si el símbolo no existe en la lista de la tabla, lo agrega con el lote especificado."""
        if symbol not in self.symbols:
            specs = self.symbol_specs.get(symbol, {})
            min_lot = specs.get("volume_min", 0.01)
            use_lot = lot if (lot is not None and lot > 0) else min_lot

            self.symbols.append(symbol)
            self.symbol_lots[symbol] = use_lot
            self.symbol_risk_pcts[symbol] = 1.0
            self.symbol_timeframes[symbol] = "M1"

            self._add_symbol_row(symbol)

            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def set_symbol_active(self, symbol: str, active: bool = True) -> None:
        """Activa o desactiva programáticamente el switch de un símbolo disparando su callback."""
        if symbol in self.switch_vars:
            current_state = self.switch_vars[symbol].get()
            if current_state != active:
                self.switch_vars[symbol].set(active)
                self._update_single_symbol_input_state(symbol)
                if self.on_toggle_callback:
                    self.on_toggle_callback(symbol, active)

    def get_symbol_config(self, symbol: str) -> Dict[str, Any]:
        """Obtiene la configuración individual completa de un par específico."""
        try:
            lot = float(self.entry_lots[symbol].get().replace(",", ".").strip())
        except (ValueError, KeyError):
            lot = 0.01

        try:
            risk_pct_val = float(self.entry_risk_pcts[symbol].get().replace(",", ".").strip())
            risk_pct = risk_pct_val / 100.0
        except (ValueError, KeyError):
            risk_pct = 0.01

        tf_str = str(self.opt_timeframes[symbol].get()) if symbol in self.opt_timeframes else "M1"
        tf_val = TIMEFRAME_MAP.get(tf_str, mt5.TIMEFRAME_M1)

        return {
            "lot": lot,
            "risk_pct": risk_pct,
            "timeframe_str": tf_str,
            "timeframe_val": tf_val,
        }

    def get_all_symbol_configs(self) -> Dict[str, Dict[str, Any]]:
        """Devuelve un diccionario con las configuraciones actuales de todos los símbolos."""
        configs = {}
        for sym in self.symbols:
            configs[sym] = self.get_symbol_config(sym)
        return configs

