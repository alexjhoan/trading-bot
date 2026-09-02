import customtkinter as ctk
from tkinter import messagebox
import threading
import queue
from typing import List, Callable, Dict, Any, Optional
import MetaTrader5 as mt5
from datetime import datetime

from config import STRATEGY_CONFIG, RISK_CONFIG
from core.connector import get_symbol_atr_pips
from core.stats_calculator import rank_symbols_by_performance
from core.backtester import run_deep_search, get_cached_results, find_best_timeframe
from core.strategies import get_available_strategies

TIMEFRAME_MAP: Dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}
TIMEFRAME_MAP_REVERSE: Dict[int, str] = {v: k for k, v in TIMEFRAME_MAP.items()}


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
        self.lbl_suggested_lot: Dict[str, ctk.CTkLabel] = {}
        self.lbl_warning: Dict[str, ctk.CTkLabel] = {}
        self.symbol_atr_pips: Dict[str, float] = {}
        self.lbl_schedule_dict: Dict[str, ctk.CTkLabel] = {}
        self.symbol_rows: Dict[str, ctk.CTkFrame] = {}
        self.suggestion_buttons: List[ctk.CTkButton] = []

        self._schedule_loop_ticks: int = 0

        self._build_ui()

    def set_account_balance(self, balance: float) -> None:
        """Actualiza el balance de la cuenta para recalcular el riesgo USD en cada par."""
        self.account_balance = balance
        for symbol in self.symbols:
            self._update_symbol_calc(symbol)

    def _match_available_symbol(self, base_symbol: str) -> Optional[str]:
        """Encuentra el símbolo real del broker (con sufijo, ej. 'GBPUSD' -> 'GBPUSD_r') que
        corresponde a un símbolo base como el guardado en trade_memory.json (sin sufijo)."""
        base_lower = base_symbol.strip().lower()
        for s in self.available_symbols:
            if s.lower() == base_lower:
                return s
        for s in self.available_symbols:
            if s.lower().startswith(base_lower):
                return s
        return None

    def _apply_selected_best_pairs(
        self,
        checked_symbols: List[str],
        popup: ctk.CTkToplevel,
        timeframe_by_symbol: Optional[Dict[str, str]] = None
    ) -> None:
        """Agrega a la tabla los símbolos marcados en el popup de Mejores Pares o Deep Search,
        resolviendo cada uno a su símbolo real del broker. Pregunta si se deben eliminar antes
        los pares actuales para dejar solo los seleccionados. Si `timeframe_by_symbol` trae una
        sugerencia (del Deep Search comparando timeframes), la aplica al agregar cada símbolo."""
        if not checked_symbols:
            messagebox.showinfo("Mejores Pares", "No marcaste ningún par para agregar.")
            return

        timeframe_by_symbol = timeframe_by_symbol or {}
        resolved: List[str] = []
        unresolved: List[str] = []
        for base_sym in checked_symbols:
            matched = self._match_available_symbol(base_sym)
            if matched:
                resolved.append((matched, timeframe_by_symbol.get(base_sym)))
            else:
                unresolved.append(base_sym)

        if not resolved:
            messagebox.showwarning(
                "Mejores Pares",
                "No se pudo emparejar ninguno de los símbolos seleccionados con los símbolos "
                "disponibles del broker (¿la cuenta MT5 está conectada?)."
            )
            return

        replace_existing = messagebox.askyesno(
            "Mejores Pares",
            "¿Deseas eliminar todos los pares que ya están en la tabla y dejar solo los "
            "seleccionados?\n\nSí = reemplazar todo.\nNo = agregar estos sin quitar los que ya tienes."
        )

        if replace_existing:
            for existing_symbol in list(self.symbols):
                self._remove_symbol(existing_symbol)

        for sym, suggested_tf in resolved:
            self.ensure_symbol_present(sym, timeframe=suggested_tf)

        if unresolved:
            messagebox.showwarning(
                "Mejores Pares",
                f"No se encontraron en el broker: {', '.join(unresolved)} (se omitieron)."
            )

        popup.destroy()

    def _open_deep_search_popup(self) -> None:
        """Corre un backtest real (bar a bar, con la estrategia elegida) sobre un conjunto de
        símbolos para encontrar los más rentables, incluso si nunca se han operado antes.
        Los resultados se cachean en backtest_results.json (ver core/backtester.py)."""
        popup = ctk.CTkToplevel(self)
        popup.title("🔬 Deep Search — Backtest Real por Símbolo")
        popup.geometry("760x820")
        popup.minsize(700, 650)
        popup.transient(self.winfo_toplevel())

        config_frame = ctk.CTkFrame(popup, fg_color="#1a1a1a")
        config_frame.pack(fill="x", padx=15, pady=(12, 8))

        lbl_info = ctk.CTkLabel(
            config_frame,
            text=(
                "Simula vela a vela cómo se habría comportado la estrategia elegida sobre el\n"
                "historial REAL de MT5 de cada símbolo (misma ventana de 300 velas que usa el bot\n"
                "en vivo). Los resultados se guardan en caché — una próxima búsqueda solo actualiza\n"
                "lo que falte o esté vencido (>24h), no repite todo el trabajo."
            ),
            font=ctk.CTkFont(size=11), text_color="#AAAAAA", justify="left"
        )
        lbl_info.pack(padx=10, pady=(10, 8), anchor="w")

        row1 = ctk.CTkFrame(config_frame, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(row1, text="Estrategia:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        strategies = get_available_strategies() or ["forex"]
        opt_strategy = ctk.CTkOptionMenu(row1, values=strategies, width=130)
        opt_strategy.set(strategies[0])
        opt_strategy.pack(side="left", padx=(0, 15))

        ctk.CTkLabel(row1, text="Alcance:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        scope_options = ["Símbolos en mi tabla", "Todos los disponibles del broker"]
        opt_scope = ctk.CTkOptionMenu(row1, values=scope_options, width=210)
        opt_scope.set(scope_options[0])
        opt_scope.pack(side="left", padx=(0, 15))

        row1b = ctk.CTkFrame(config_frame, fg_color="transparent")
        row1b.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(row1b, text="Días de historial:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        history_days_options: Dict[str, int] = {
            "15 días (rápido)": 15,
            "30 días (default)": 30,
            "60 días": 60,
            "90 días": 90,
        }
        opt_history_days = ctk.CTkOptionMenu(row1b, values=list(history_days_options.keys()), width=170)
        opt_history_days.set("30 días (default)")
        opt_history_days.pack(side="left", padx=(0, 15))

        ctk.CTkLabel(row1b, text="Mín. operaciones:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        min_trades_options: Dict[str, int] = {
            "3 (más resultados, menos confiable)": 3,
            "5 (default)": 5,
            "10": 10,
            "15 (más confiable, menos resultados)": 15,
        }
        opt_min_trades = ctk.CTkOptionMenu(row1b, values=list(min_trades_options.keys()), width=250)
        opt_min_trades.set("5 (default)")
        opt_min_trades.pack(side="left")

        row2 = ctk.CTkFrame(config_frame, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(0, 4))

        chk_compare_tf_var = ctk.BooleanVar(value=False)
        chk_compare_tf = ctk.CTkCheckBox(
            row2, text="🕒 Comparar Timeframes (M5/M15/M30/H1/H4) y sugerir el mejor por símbolo — más lento",
            variable=chk_compare_tf_var, font=ctk.CTkFont(size=11)
        )
        chk_compare_tf.pack(side="left")

        progress_bar = ctk.CTkProgressBar(config_frame, mode="indeterminate")
        # Se muestra (pack) solo mientras hay una búsqueda corriendo, ver _start_search/_poll_queue

        lbl_progress = ctk.CTkLabel(config_frame, text="", font=ctk.CTkFont(size=11), text_color="#F59E0B")
        lbl_progress.pack(padx=10, pady=(0, 4), anchor="w")

        live_feed = ctk.CTkTextbox(config_frame, height=70, font=ctk.CTkFont(size=10, family="Consolas"))
        live_feed.configure(state="disabled")
        live_feed.pack(fill="x", padx=10, pady=(0, 8))

        lbl_criteria = ctk.CTkLabel(
            popup,
            text=(
                "🟢 Verde = rentable (Expectativa > 0R) con suficientes operaciones · 🔴 Rojo = no rentable · "
                "⚪ Gris = menos del mínimo elegido, aún no es confiable. Orden: por Expectativa (R promedio), no por Win Rate."
            ),
            font=ctk.CTkFont(size=10), text_color="#888888", justify="left"
        )
        lbl_criteria.pack(padx=15, pady=(0, 4), anchor="w")

        header = ctk.CTkFrame(popup, fg_color="#1a1a1a", height=28)
        header.pack(fill="x", padx=15)
        headers = [("", 30), ("Símbolo", 80), ("TF", 40), ("Trades", 55), ("Win Rate", 55), ("WR Ajust.", 60), ("R Prom.", 55), ("Velas", 55)]
        for text, width in headers:
            ctk.CTkLabel(header, text=text, font=ctk.CTkFont(size=11, weight="bold"), width=width, anchor="center").pack(side="left", padx=2, pady=4)

        rows_container = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        rows_container.pack(fill="both", expand=True, padx=15, pady=(4, 4))

        checkbox_vars: Dict[str, ctk.BooleanVar] = {}
        green_symbols: List[str] = []
        timeframe_by_symbol: Dict[str, str] = {}

        def _current_min_trades() -> int:
            # Se lee en el momento (solo desde el hilo principal: _render_results/_format_feed_line
            # se llaman siempre vía _poll_queue) para que un cambio del selector durante una
            # búsqueda en curso no rompa nada — la búsqueda ya en marcha usó el valor leído al
            # iniciar (ver _start_search); esto solo afecta cómo se PINTA/filtra lo ya obtenido.
            return min_trades_options.get(opt_min_trades.get(), 5)

        def _render_results(results: List[Dict[str, Any]]) -> None:
            for w in rows_container.winfo_children():
                w.destroy()
            checkbox_vars.clear()
            green_symbols.clear()
            timeframe_by_symbol.clear()

            min_trades = _current_min_trades()
            results_sorted = sorted(results, key=lambda r: r.get("avg_r", -999), reverse=True)

            for row in results_sorted:
                if row.get("error"):
                    row_frame = ctk.CTkFrame(rows_container, fg_color="transparent")
                    row_frame.pack(fill="x", pady=1)
                    ctk.CTkLabel(row_frame, text="", width=30).pack(side="left")
                    ctk.CTkLabel(row_frame, text=row["symbol"], text_color="#666666", width=80, anchor="center").pack(side="left", padx=2)
                    ctk.CTkLabel(row_frame, text=row["error"], text_color="#666666", font=ctk.CTkFont(size=10, slant="italic")).pack(side="left", padx=4)
                    continue

                trades = row.get("trades", 0)
                avg_r = row.get("avg_r", 0.0)
                wr_confidence = row.get("win_rate_confidence", 0.0)
                tf_label = TIMEFRAME_MAP_REVERSE.get(row.get("timeframe"), "?")
                if trades < min_trades:
                    row_color = "#666666"  # Menos operaciones que el mínimo elegido: informativo, sin opinar
                elif avg_r > 0:
                    row_color = "#2ECC71"
                    green_symbols.append(row["symbol"])
                else:
                    row_color = "#E74C3C"

                row_frame = ctk.CTkFrame(rows_container, fg_color="transparent")
                row_frame.pack(fill="x", pady=1)

                chk_var = ctk.BooleanVar(value=False)
                checkbox_vars[row["symbol"]] = chk_var
                timeframe_by_symbol[row["symbol"]] = tf_label
                ctk.CTkCheckBox(row_frame, text="", variable=chk_var, width=30, checkbox_width=18, checkbox_height=18).pack(side="left", padx=2)

                values = [
                    (row["symbol"], 80),
                    (tf_label, 40),
                    (f"{trades} ({row.get('wins', 0)}G/{row.get('losses', 0)}P)", 55),
                    (f"{row.get('win_rate', 0):.0f}%", 55),
                    (f"{wr_confidence:.0f}%", 60),
                    (f"{avg_r:+.2f}R", 55),
                    (f"{row.get('bars_analyzed', 0)}", 55),
                ]
                for text, width in values:
                    ctk.CTkLabel(row_frame, text=text, text_color=row_color, font=ctk.CTkFont(size=11), width=width, anchor="center").pack(side="left", padx=2)

                if trades < min_trades:
                    ctk.CTkLabel(row_frame, text=f"(< {min_trades} operaciones)", text_color="#666666", font=ctk.CTkFont(size=9, slant="italic")).pack(side="left", padx=4)

        def _append_live_feed(line: str) -> None:
            live_feed.configure(state="normal")
            live_feed.insert("end", line + "\n")
            live_feed.see("end")
            live_feed.configure(state="disabled")

        def _format_feed_line(row: Dict[str, Any]) -> str:
            if row.get("error"):
                return f"✗ {row['symbol']}: {row['error']}"
            tf_label = TIMEFRAME_MAP_REVERSE.get(row.get("timeframe"), "?")
            trades = row.get("trades", 0)
            min_trades = _current_min_trades()
            if trades < min_trades:
                return f"~ {row['symbol']} ({tf_label}): {trades} trades, {row.get('bars_analyzed', 0)} velas — menos de {min_trades} operaciones"
            return (
                f"✓ {row['symbol']} ({tf_label}): {trades} trades, WR {row.get('win_rate', 0):.0f}% "
                f"(ajust. {row.get('win_rate_confidence', 0):.0f}%), {row.get('avg_r', 0):+.2f}R"
            )

        # Comunicación entre el hilo de fondo y la GUI vía cola: el hilo de fondo NUNCA toca
        # widgets de Tk directamente (ni siquiera con self.after()) — eso no es seguro de forma
        # consistente desde un hilo que no es el principal. Solo escribe mensajes en la cola;
        # el sondeo (_poll_queue) se reprograma siempre desde el hilo principal con popup.after().
        progress_queue: "queue.Queue" = queue.Queue()
        cancel_event = threading.Event()
        accumulated_results: List[Dict[str, Any]] = []

        def _finish_search(status_text: str) -> None:
            lbl_progress.configure(text=status_text)
            _render_results(accumulated_results)
            btn_start.configure(state="normal", text="▶️ Iniciar Búsqueda")
            btn_cancel.configure(state="disabled")
            progress_bar.stop()
            progress_bar.pack_forget()

        def _poll_queue() -> None:
            try:
                while True:
                    msg_type, payload = progress_queue.get_nowait()
                    if msg_type == "progress":
                        done, total, current_symbol = payload
                        lbl_progress.configure(text=f"⏳ Analizando {current_symbol}... ({done}/{total})")
                    elif msg_type == "result":
                        accumulated_results.append(payload)
                        _append_live_feed(_format_feed_line(payload))
                    elif msg_type == "error":
                        _finish_search(f"❌ {payload}")
                    elif msg_type == "done":
                        _finish_search(f"✅ Búsqueda completa: {len(accumulated_results)} símbolos analizados.")
                    elif msg_type == "cancelled":
                        _finish_search(f"🛑 Búsqueda cancelada — {len(accumulated_results)} símbolos alcanzados a analizar antes de parar.")
            except queue.Empty:
                pass

            if popup.winfo_exists():
                popup.after(150, _poll_queue)

        def _update_progress(done: int, total: int, current_symbol: str) -> None:
            progress_queue.put(("progress", (done, total, current_symbol)))

        def _push_result(row: Dict[str, Any]) -> None:
            progress_queue.put(("result", row))

        def _run_search_thread(strategy_name: str, scope: str, compare_tf: bool, target_days: int, min_trades: int) -> None:
            # NOTA: strategy_name/scope/compare_tf/target_days/min_trades se reciben como
            # argumentos (no se leen aquí desde las variables de Tkinter) porque leer/escribir
            # widgets de Tk desde un hilo que no es el principal no es seguro y puede fallar.
            target_symbols = list(self.symbols) if scope == scope_options[0] else list(self.available_symbols)

            if not target_symbols:
                progress_queue.put(("error", "No hay símbolos disponibles para analizar."))
                return

            try:
                if compare_tf:
                    for idx, sym in enumerate(target_symbols):
                        if cancel_event.is_set():
                            break
                        _update_progress(idx + 1, len(target_symbols), sym)
                        tf_result = find_best_timeframe(
                            sym, strategy_name, target_days=target_days, min_trades=min_trades, cancel_event=cancel_event
                        )
                        if not tf_result.get("conclusive"):
                            _push_result({
                                "symbol": sym,
                                "error": tf_result.get("diagnostic", "Sin señales suficientes en ningún timeframe candidato")
                            })
                            continue
                        best_tf = tf_result["best_timeframe"]
                        best_entry = next((r for r in tf_result["per_timeframe"] if r.get("timeframe") == best_tf), {})
                        _push_result({
                            "symbol": sym,
                            "timeframe": best_tf,
                            "trades": tf_result.get("best_trades", 0),
                            "wins": best_entry.get("wins", 0),
                            "losses": best_entry.get("losses", 0),
                            "win_rate": tf_result.get("best_win_rate", 0.0),
                            "win_rate_confidence": best_entry.get("win_rate_confidence", 0.0),
                            "avg_r": tf_result.get("best_avg_r", 0.0),
                            "bars_analyzed": best_entry.get("bars_analyzed", 0),
                        })
                else:
                    timeframe_map = {
                        s: TIMEFRAME_MAP.get(self.symbol_timeframes.get(s, "M5"), mt5.TIMEFRAME_M5)
                        for s in target_symbols
                    }
                    run_deep_search(
                        target_symbols, strategy_name, timeframe_map, target_days=target_days,
                        progress_callback=_update_progress, result_callback=_push_result, cancel_event=cancel_event
                    )
            except Exception as e:
                progress_queue.put(("error", f"Error en la búsqueda: {e}"))
                return

            progress_queue.put(("cancelled" if cancel_event.is_set() else "done", None))

        def _start_search() -> None:
            accumulated_results.clear()
            live_feed.configure(state="normal")
            live_feed.delete("1.0", "end")
            live_feed.configure(state="disabled")
            cancel_event.clear()

            btn_start.configure(state="disabled", text="⏳ Buscando...")
            btn_cancel.configure(state="normal")
            lbl_progress.configure(text="⏳ Iniciando...")
            progress_bar.pack(fill="x", padx=10, pady=(0, 6), before=lbl_progress)
            progress_bar.start()
            # Leer los valores de los widgets en el hilo principal ANTES de lanzar el hilo:
            # leerlos desde el hilo de fondo no es seguro con Tkinter.
            strategy_name = opt_strategy.get()
            scope = opt_scope.get()
            compare_tf = chk_compare_tf_var.get()
            target_days = history_days_options.get(opt_history_days.get(), 30)
            min_trades = min_trades_options.get(opt_min_trades.get(), 5)
            threading.Thread(
                target=_run_search_thread, args=(strategy_name, scope, compare_tf, target_days, min_trades), daemon=True
            ).start()
            popup.after(150, _poll_queue)

        def _cancel_search() -> None:
            cancel_event.set()
            btn_cancel.configure(state="disabled")
            lbl_progress.configure(text="🛑 Cancelando... (termina el símbolo en curso)")

        def _select_green() -> None:
            for sym, var in checkbox_vars.items():
                if sym in green_symbols:
                    var.set(True)

        def _apply_selection() -> None:
            checked = [sym for sym, var in checkbox_vars.items() if var.get()]
            self._apply_selected_best_pairs(checked, popup, timeframe_by_symbol=timeframe_by_symbol)

        btn_row = ctk.CTkFrame(row1, fg_color="transparent")
        btn_row.pack(side="left")

        btn_start = ctk.CTkButton(
            btn_row, text="▶️ Iniciar Búsqueda", fg_color="#B45309", hover_color="#92400E",
            font=ctk.CTkFont(size=12, weight="bold"), command=_start_search
        )
        btn_start.pack(side="left")

        btn_cancel = ctk.CTkButton(
            btn_row, text="🛑 Cancelar", fg_color="#991B1B", hover_color="#7F1D1D", state="disabled",
            font=ctk.CTkFont(size=12, weight="bold"), command=_cancel_search
        )
        btn_cancel.pack(side="left", padx=(8, 0))

        actions_frame = ctk.CTkFrame(popup, fg_color="transparent")
        actions_frame.pack(fill="x", padx=15, pady=(4, 14))

        ctk.CTkButton(
            actions_frame, text="🟢 Seleccionar Verdes", fg_color="#059669", hover_color="#047857",
            font=ctk.CTkFont(size=12, weight="bold"), command=_select_green
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            actions_frame, text="➕ Agregar Seleccionados a la Tabla", fg_color="#1D4ED8", hover_color="#2563EB",
            font=ctk.CTkFont(size=12, weight="bold"), command=_apply_selection
        ).pack(side="left")

        # Mostrar resultados ya cacheados (si existen) apenas se abre el popup, sin esperar una búsqueda nueva
        try:
            cached = get_cached_results(strategies[0])
            if cached:
                lbl_progress.configure(text=f"ℹ️ Mostrando {len(cached)} resultados en caché (inicia una nueva búsqueda para actualizar).")
                _render_results(cached)
        except Exception:
            pass

    def _open_best_pairs_popup(self) -> None:
        """Muestra un ranking de símbolos por desempeño histórico REAL (trade_memory.json),
        no por indicadores predictivos. Permite marcar pares y agregarlos a la tabla."""
        try:
            ranking = rank_symbols_by_performance()
        except Exception as e:
            ranking = []
            print(f"[DEBUG MEJORES PARES] Error calculando ranking: {e}")

        popup = ctk.CTkToplevel(self)
        popup.title("📊 Mejores Pares (Histórico Real)")
        popup.geometry("660x540")
        popup.transient(self.winfo_toplevel())

        top_row = ctk.CTkFrame(popup, fg_color="transparent")
        top_row.pack(fill="x", padx=15, pady=(12, 0))

        btn_deep_search = ctk.CTkButton(
            top_row,
            text="🔬 Deep Search (Backtest Real)",
            fg_color="#B45309",
            hover_color="#92400E",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_deep_search_popup
        )
        btn_deep_search.pack(side="right")

        lbl_info = ctk.CTkLabel(
            popup,
            text=(
                "Ranking por Expectativa (R promedio) histórica real, no por predicción.\n"
                "Win Rate (ajust.) usa el límite inferior de Wilson: penaliza símbolos con pocas operaciones\n"
                "para no confiar en muestras chicas (ej. 1 ganada de 1 no es 100% confiable).\n"
                "¿Quieres analizar pares que nunca has operado? Usa Deep Search arriba."
            ),
            font=ctk.CTkFont(size=11),
            text_color="#AAAAAA",
            justify="left"
        )
        lbl_info.pack(padx=15, pady=(8, 8), anchor="w")

        header = ctk.CTkFrame(popup, fg_color="#1a1a1a", height=28)
        header.pack(fill="x", padx=15)
        headers = [("", 30), ("Símbolo", 90), ("Trades", 60), ("Win Rate", 65), ("WR Ajust.", 70), ("R Prom.", 60), ("USD", 65)]
        for text, width in headers:
            ctk.CTkLabel(header, text=text, font=ctk.CTkFont(size=11, weight="bold"), width=width, anchor="center").pack(side="left", padx=2, pady=4)

        rows_container = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        rows_container.pack(fill="both", expand=True, padx=15, pady=(4, 4))

        if not ranking:
            ctk.CTkLabel(rows_container, text="Sin historial suficiente todavía (trade_memory.json vacío o sin operaciones cerradas).").pack(pady=20)
            return

        checkbox_vars: Dict[str, ctk.BooleanVar] = {}
        green_symbols: List[str] = []

        for row in ranking:
            if not row["meets_min_sample"]:
                row_color = "#666666"  # Muestra insuficiente: informativo, sin opinar
            elif row["avg_r"] > 0:
                row_color = "#2ECC71"  # Rentable
                green_symbols.append(row["symbol"])
            else:
                row_color = "#E74C3C"  # No rentable

            row_frame = ctk.CTkFrame(rows_container, fg_color="transparent")
            row_frame.pack(fill="x", pady=1)

            chk_var = ctk.BooleanVar(value=False)
            checkbox_vars[row["symbol"]] = chk_var
            chk = ctk.CTkCheckBox(row_frame, text="", variable=chk_var, width=30, checkbox_width=18, checkbox_height=18)
            chk.pack(side="left", padx=2)

            values = [
                (row["symbol"], 90),
                (f"{row['trades']} ({row['wins']}G/{row['losses']}P)", 60),
                (f"{row['win_rate']:.0f}%", 65),
                (f"{row['win_rate_confidence']:.0f}%", 70),
                (f"{row['avg_r']:+.2f}R", 60),
                (f"${row['total_usd']:+.2f}", 65),
            ]
            for text, width in values:
                ctk.CTkLabel(row_frame, text=text, text_color=row_color, font=ctk.CTkFont(size=11), width=width, anchor="center").pack(side="left", padx=2)

            if not row["meets_min_sample"]:
                ctk.CTkLabel(row_frame, text="(muestra chica)", text_color="#666666", font=ctk.CTkFont(size=9, slant="italic")).pack(side="left", padx=4)

        def _select_green() -> None:
            for sym, var in checkbox_vars.items():
                if sym in green_symbols:
                    var.set(True)

        def _apply_selection() -> None:
            checked = [sym for sym, var in checkbox_vars.items() if var.get()]
            self._apply_selected_best_pairs(checked, popup)

        actions_frame = ctk.CTkFrame(popup, fg_color="transparent")
        actions_frame.pack(fill="x", padx=15, pady=(4, 14))

        btn_select_green = ctk.CTkButton(
            actions_frame,
            text="🟢 Seleccionar Verdes",
            fg_color="#059669",
            hover_color="#047857",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=_select_green
        )
        btn_select_green.pack(side="left", padx=(0, 8))

        btn_apply = ctk.CTkButton(
            actions_frame,
            text="➕ Agregar Seleccionados a la Tabla",
            fg_color="#1D4ED8",
            hover_color="#2563EB",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=_apply_selection
        )
        btn_apply.pack(side="left")

    def _build_ui(self) -> None:
        # Título + botón de ranking de pares
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=15, pady=(12, 5))

        lbl_title = ctk.CTkLabel(
            title_frame,
            text="🎯 Selección de Símbolos y Configuración por Par",
            font=ctk.CTkFont(size=15, weight="bold")
        )
        lbl_title.pack(side="left")

        btn_best_pairs = ctk.CTkButton(
            title_frame,
            text="📊 Mejores Pares",
            width=130,
            fg_color="#7C3AED",
            hover_color="#6D28D9",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_best_pairs_popup
        )
        btn_best_pairs.pack(side="right")

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

        # Cada ~60 segundos, refrescar el ATR/mínimo de SL recomendado (evita golpear MT5 en cada tick)
        self._schedule_loop_ticks += 1
        if self._schedule_loop_ticks % 60 == 0:
            for symbol in list(self.symbols):
                try:
                    self._refresh_symbol_atr(symbol)
                    self._update_symbol_calc(symbol)
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
            ("Lote Sugerido", 95),
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

        row_container = ctk.CTkFrame(self.symbols_container, fg_color="transparent")
        row_container.pack(fill="x", pady=3, padx=2)
        self.symbol_rows[symbol] = row_container

        row = ctk.CTkFrame(row_container, fg_color="#2b2b2b", corner_radius=6)
        row.pack(fill="x")

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

        # 6b. Lote Sugerido Label (width ~95) - lote calculado desde Riesgo $ y el SL mínimo recomendado (ATR)
        lbl_suggested = ctk.CTkLabel(
            row,
            text="--",
            text_color="#3B82F6",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=90,
            anchor="center"
        )
        lbl_suggested.pack(side="left", padx=3)
        self.lbl_suggested_lot[symbol] = lbl_suggested

        # 7. Timeframe OptionMenu (width ~80)
        default_tf = self.symbol_timeframes.get(symbol, "M5")
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

        # Etiqueta de advertencia (oculta por defecto): se muestra solo si el SL calculado
        # queda por debajo del mínimo recomendado (ATR) para este símbolo
        lbl_warning = ctk.CTkLabel(
            row_container,
            text="",
            text_color="#F59E0B",
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w"
        )
        self.lbl_warning[symbol] = lbl_warning

        # Calcular el ATR (en pips) del símbolo para usarlo como piso mínimo recomendado de SL
        self._refresh_symbol_atr(symbol)

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

    def _refresh_symbol_atr(self, symbol: str) -> None:
        """Recalcula y cachea el ATR (en pips) del símbolo, usando su timeframe seleccionado."""
        tf_str = self.symbol_timeframes.get(symbol, "M5")
        tf_val = TIMEFRAME_MAP.get(tf_str, mt5.TIMEFRAME_M5)
        self.symbol_atr_pips[symbol] = get_symbol_atr_pips(symbol, timeframe=tf_val)

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
            specs = self.symbol_specs.get(symbol, {})
            trade_tick_value = specs.get("trade_tick_value", 1.0)
            point = specs.get("point", 0.00001)
            digits = specs.get("digits", 5)
            tick_size = specs.get("trade_tick_size", point)

            pip_size = point * 10.0 if digits in (3, 5) else point
            ticks_per_pip = (pip_size / tick_size) if tick_size > 0 else 1.0
            pip_value_std = trade_tick_value * ticks_per_pip

            if lot <= 0 or risk_usd <= 0:
                sl_pips = 0.0
            else:
                sl_pips = risk_usd / (lot * pip_value_std)

            if symbol in self.lbl_sl_pips:
                self.lbl_sl_pips[symbol].configure(text=f"{sl_pips:.1f} pips")

            # 3. Lote Sugerido y advertencia de SL por debajo del mínimo recomendado (piso dinámico por ATR)
            atr_pips = self.symbol_atr_pips.get(symbol, 0.0)
            min_sl_pips = atr_pips * RISK_CONFIG.min_sl_atr_mult

            if min_sl_pips > 0 and risk_usd > 0 and pip_value_std > 0:
                volume_step = specs.get("volume_step", 0.01)
                volume_min = specs.get("volume_min", 0.01)
                volume_max = specs.get("volume_max", 100.0)

                raw_lot = risk_usd / (min_sl_pips * pip_value_std)
                suggested_lot = round(raw_lot / volume_step) * volume_step if volume_step > 0 else raw_lot
                suggested_lot = max(volume_min, min(suggested_lot, volume_max))

                if symbol in self.lbl_suggested_lot:
                    self.lbl_suggested_lot[symbol].configure(text=f"{suggested_lot:.2f}")

                if symbol in self.lbl_warning:
                    if sl_pips > 0 and sl_pips < min_sl_pips:
                        self.lbl_warning[symbol].configure(
                            text=(
                                f"⚠️ SL actual ({sl_pips:.1f} pips) por debajo del mínimo recomendado "
                                f"({min_sl_pips:.1f} pips, ATR x{RISK_CONFIG.min_sl_atr_mult:.1f}) para este par — "
                                f"considera bajar el lote a {suggested_lot:.2f} o subir el % de riesgo."
                            )
                        )
                        self.lbl_warning[symbol].pack(fill="x", padx=(4, 4), pady=(2, 0))
                    else:
                        self.lbl_warning[symbol].pack_forget()
            else:
                if symbol in self.lbl_suggested_lot:
                    self.lbl_suggested_lot[symbol].configure(text="--")
                if symbol in self.lbl_warning:
                    self.lbl_warning[symbol].pack_forget()
        except (ValueError, KeyError, ZeroDivisionError):
            if symbol in self.lbl_sl_pips:
                self.lbl_sl_pips[symbol].configure(text="N/A")
            if symbol in self.lbl_suggested_lot:
                self.lbl_suggested_lot[symbol].configure(text="N/A")
            if symbol in self.lbl_warning:
                self.lbl_warning[symbol].pack_forget()

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
            self.symbol_timeframes[sym] = "M5"
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
            self.lbl_suggested_lot.pop(symbol, None)
            self.lbl_warning.pop(symbol, None)
            self.symbol_atr_pips.pop(symbol, None)
            self.lbl_schedule_dict.pop(symbol, None)

            if self.on_symbols_changed_callback:
                self.on_symbols_changed_callback(self.symbols)

    def _on_search_changed(self, event: Any) -> None:
        query = self.entry_symbol.get().strip().lower()
        if not query:
            self._hide_suggestions()
            return

        # 🟢 Excluir del dropdown los pares que ya están en la ventana/tabla de uso
        current_symbols_lower = {s.lower() for s in self.symbols}
        matches = [s for s in self.available_symbols if (query in s.lower()) and (s.lower() not in current_symbols_lower)][:5]
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

    def ensure_symbol_present(self, symbol: str, lot: Optional[float] = None, timeframe: Optional[str] = None) -> None:
        """Si el símbolo no existe en la lista de la tabla, lo agrega con el lote y timeframe especificados."""
        if symbol not in self.symbols:
            specs = self.symbol_specs.get(symbol, {})
            min_lot = specs.get("volume_min", 0.01)
            use_lot = lot if (lot is not None and lot > 0) else min_lot
            use_tf = timeframe if (timeframe and timeframe in TIMEFRAME_MAP) else "M5"

            self.symbols.append(symbol)
            self.symbol_lots[symbol] = use_lot
            self.symbol_risk_pcts[symbol] = 1.0
            self.symbol_timeframes[symbol] = use_tf

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

