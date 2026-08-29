import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Callable, Dict, Any, Optional, Set

import MetaTrader5 as mt5
import pandas as pd

from core.connector import check_account_safety, check_algo_trading_enabled
from strategies import create_strategy_instance, get_strategy_class
from core.executor import OrderExecutor
from core.risk_manager import RiskManager
from core.data_loader import get_historical_data
from core.config_manager import load_config
from core.ai_advisor import evaluate_trade_setup, evaluate_open_position_ai
from core.ai_memory import AIMemoryManager
from core.news_manager import news_manager
from core.market_context import analyze_macro_multitimeframe
from core.candlestick_patterns import format_candlestick_summary_for_ai
from config import STRATEGY_CONFIG

TIMEFRAME_SECONDS_MAP: Dict[int, int] = {
    mt5.TIMEFRAME_M1: 60,
    mt5.TIMEFRAME_M5: 300,
    mt5.TIMEFRAME_M15: 900,
    mt5.TIMEFRAME_M30: 1800,
    mt5.TIMEFRAME_H1: 3600,
    mt5.TIMEFRAME_H4: 14400,
    mt5.TIMEFRAME_D1: 86400,
}

TIMEFRAME_NAMES: Dict[int, str] = {
    mt5.TIMEFRAME_M1: "M1",
    mt5.TIMEFRAME_M5: "M5",
    mt5.TIMEFRAME_M15: "M15",
    mt5.TIMEFRAME_M30: "M30",
    mt5.TIMEFRAME_H1: "H1",
    mt5.TIMEFRAME_H4: "H4",
    mt5.TIMEFRAME_D1: "D1",
}


def calculate_sleep_seconds(timeframe_seconds: int) -> float:
    """Calcula el tiempo exacto restante hasta el cierre de la vela actual + 1s extra de margen."""
    current_time: float = time.time()
    elapsed: float = current_time % timeframe_seconds
    return (timeframe_seconds - elapsed) + 1.0


class SymbolWorker(threading.Thread):
    """
    Hilo de ejecución independiente por cada par de divisas.
    - Si ya existe una posición abierta: omite análisis de nuevas entradas y ejecuta
      análisis de gestión activa (modificación de SL/TP, Trailing Stop y Cierre Prematuro).
    - Si no existe posición abierta: analiza el mercado buscando confluencias para nuevas entradas.
    - Validación y Optimización de Riesgo por IA con Memoria Histórica Local (Few-Shot Context).
    """

    def __init__(
        self,
        symbol: str,
        log_callback: Callable[[str, str, str], None],
        stop_event: Optional[threading.Event] = None,
        timeframe: int = mt5.TIMEFRAME_M1,
        test_mode: bool = False,
        risk_pct: float = 0.01,
        lot: float = 0.01,
        strategy_name: str = "forex",
    ) -> None:
        super().__init__(daemon=True)
        self.symbol = symbol
        self.log_callback = log_callback
        self.stop_event = stop_event or threading.Event()
        self.timeframe = timeframe
        self.test_mode = test_mode
        self.risk_pct = risk_pct
        self.lot = lot
        self.strategy_name = (strategy_name or "forex").strip().lower()

        self.strategy = create_strategy_instance(
            name=self.strategy_name,
            symbol=self.symbol,
            logger=lambda msg, lvl="INFO": self._log(msg, lvl)
        )
        self.executor = OrderExecutor(
            symbol=self.symbol,
            log_callback=self.log_callback
        )
        self.risk_manager = RiskManager()
        self.ai_memory = AIMemoryManager()
        self.tracked_tickets: Dict[int, Dict[str, Any]] = {}
        self.last_ai_pos_eval_time: Dict[int, float] = {}  # {ticket: timestamp_epoch}
        self.last_ai_pos_eval_bar_time: Dict[int, Any] = {}  # {ticket: candle_time}

    def _check_closed_trades(self) -> None:
        """Verifica si alguna de las operaciones rastreadas se cerró para registrar el feedback (WIN/LOSS) en trade_memory.json."""
        if not self.tracked_tickets:
            return

        current_positions = mt5.positions_get(symbol=self.symbol)
        open_tickets = {p.ticket for p in current_positions} if current_positions else set()

        closed_tickets = [t for t in self.tracked_tickets.keys() if t not in open_tickets]
        for ticket in closed_tickets:
            self.last_ai_pos_eval_time.pop(ticket, None)
            self.last_ai_pos_eval_bar_time.pop(ticket, None)
            trade_info = self.tracked_tickets.pop(ticket)
            try:
                # Consultar historial de deals de MT5 para este ticket
                from_date = datetime.now() - timedelta(days=2)
                deals = mt5.history_deals_get(position=ticket)
                if deals and len(deals) > 1:
                    close_deal = deals[-1]
                    profit = float(close_deal.profit + close_deal.swap + close_deal.fee)
                    result_str = "WIN" if profit > 0 else "LOSS"
                    initial_risk = trade_info.get("risk_usd", 10.0) or 10.0
                    pnl_r = profit / initial_risk if initial_risk > 0 else (1.0 if profit > 0 else -1.0)
                    exit_reason = close_deal.comment or "SL_or_TP_Hit"

                    self.ai_memory.update_trade_result(
                        trade_id=ticket,
                        result=result_str,
                        pnl_r=pnl_r,
                        exit_reason=exit_reason,
                        pnl_usd=profit
                    )
                    self._log(
                        f"📊 [MEMORIA IA ACTUALIZADA] Trade #{ticket} cerrado ({result_str} | PnL: ${profit:+.2f} | {pnl_r:+.2f}R). Registrado para aprendizaje futuro.",
                        "SUCCESS" if profit > 0 else "WARNING"
                    )
            except Exception as e:
                print(f"[DEBUG CLOSED TRADES] Error actualizando trade #{ticket}: {e}")

    @staticmethod
    def _is_within_session(start_str: str, end_str: str) -> bool:
        """Verifica si la hora actual local está dentro del rango horario de la sesión."""
        now = datetime.now()
        current_t = now.time()
        try:
            start_t = datetime.strptime(start_str.strip(), "%H:%M").time()
            end_t = datetime.strptime(end_str.strip(), "%H:%M").time()
            if start_t <= end_t:
                return start_t <= current_t <= end_t
            else:
                return current_t >= start_t or current_t <= end_t
        except Exception:
            return True

    @staticmethod
    def _get_seconds_until_session_start(start_str: str) -> int:
        """Calcula los segundos exactos restantes hasta la próxima apertura de sesión."""
        now = datetime.now()
        try:
            start_h, start_m = map(int, start_str.strip().split(":"))
            target_today = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
            if target_today <= now:
                target = target_today + timedelta(days=1)
            else:
                target = target_today
            return max(5, int((target - now).total_seconds()))
        except Exception:
            return 60

    def run(self) -> None:
        self._log(f"Iniciando monitoreo para {self.symbol} con estrategia '{self.strategy_name}'...", "INFO")

        while not self.stop_event.is_set():
            try:
                # 0. Verificar si trades anteriores se han cerrado para actualizar la memoria
                self._check_closed_trades()

                # 1. Verificar si ya existe al menos una posición abierta en este par
                open_positions = mt5.positions_get(symbol=self.symbol)

                # ⚠️ FILTRO DE SEGURIDAD 1: VERIFICAR VENTANA DE ROLLOVER Y CIERRE DE MERCADO
                cfg = load_config()
                max_spread_allowed = float(cfg.get("max_spread_pips", 3.5))
                close_on_rollover = bool(cfg.get("close_before_rollover", True))
                rollover_start = str(cfg.get("rollover_start_utc", "16:40"))
                rollover_end = str(cfg.get("rollover_end_utc", "17:20"))
                min_before_close = int(cfg.get("weekend_close_minutes_before", 15))

                is_danger_zone, danger_reason, danger_action = self.risk_manager.is_rollover_or_market_close_window(
                    minutes_before_close=min_before_close,
                    rollover_start=rollover_start,
                    rollover_end=rollover_end
                )

                # ⏰ FILTRO DE HORARIO Y SESIÓN CUANDO NO HAY POSICIONES ABIERTAS
                # Si el par no tiene trades abiertos y está fuera de horario, esperar pacíficamente
                # hasta la hora de reinicio/apertura sin consultar MT5 ni gastar CPU en cada vela.
                if not open_positions or len(open_positions) == 0:
                    market_open, open_reason = STRATEGY_CONFIG.is_market_open(self.symbol)
                    if not market_open:
                        self._log(f"⏸️ [MERCADO CERRADO] {self.symbol}: {open_reason}. En pausa hasta apertura...", "INFO")
                        sleep_count = 0
                        while sleep_count < 120 and not self.stop_event.is_set():
                            time.sleep(2.0)
                            sleep_count += 2
                        continue

                    use_session = getattr(self.strategy, "use_session_filter", True)
                    if use_session:
                        start_str, end_str = STRATEGY_CONFIG.get_session_times_for_symbol(self.symbol)
                        if not self._is_within_session(start_str, end_str):
                            secs_left = self._get_seconds_until_session_start(start_str)
                            hrs = secs_left // 3600
                            mins = (secs_left % 3600) // 60
                            self._log(
                                f"⏸️ [FUERA DE HORARIO] {self.symbol} fuera de sesión activa ({start_str}-{end_str}). "
                                f"Reanudación automática programada a las {start_str} (en {hrs}h {mins}m). Hilo en reposo.",
                                "INFO"
                            )
                            # Espera silenciosa e interrumpible hasta que llegue la hora
                            while secs_left > 0 and not self.stop_event.is_set():
                                sleep_step = min(5.0, float(secs_left))
                                time.sleep(sleep_step)
                                secs_left -= int(sleep_step)
                                if self._is_within_session(start_str, end_str):
                                    break

                            if not self.stop_event.is_set():
                                self._log(f"🟢 [HORARIO ACTIVO ALCANZADO] Sesión {start_str} iniciada para {self.symbol}. Reiniciando análisis en tiempo real...", "SUCCESS")
                            continue

                    # Si estamos en ventana de peligro (16:40 - 17:20) y no hay posiciones
                    if is_danger_zone:
                        self._log(f"⏸️ [PAUSA POR RIESGO] {self.symbol}: {danger_reason}. Esperando que pase la ventana de spread/swap...", "INFO")
                        sleep_count = 0
                        while sleep_count < 30 and not self.stop_event.is_set():
                            time.sleep(2.0)
                            sleep_count += 2
                        continue

                # 2. Obtener datos según la temporalidad configurada para este símbolo
                df = get_historical_data(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    rates_count=300,
                    log_callback=self.log_callback
                )

                if df is None or df.empty:
                    time.sleep(3)
                    continue

                if open_positions and len(open_positions) > 0:
                    # 🟢 RAMA A: POSICIÓN ABIERTA ACTIVA ➔ GESTIÓN DE SL/TP, CIERRE PREMATURO E EVALUACIÓN DE REENTRADAS
                    ai_enabled = bool(cfg.get("ai_enabled", True))
                    api_key = str(cfg.get("ai_api_key", ""))
                    model_name = str(cfg.get("ai_model", "gemini-2.5-flash"))
                    base_url = str(cfg.get("ai_base_url", ""))
                    max_reentries = int(cfg.get("max_reentries", 0))

                    for pos in open_positions:
                        # 0. CONTROL DE HORARIO FIN DE JORNADA (16:15+ Y 16:50)
                        session_rules = self.risk_manager.get_daily_session_rules()
                        if session_rules.get("is_after_1650", False):
                            self._log(
                                f"⏰ [FIN DE JORNADA 16:50] Cerrando posición #{pos.ticket} ({self.symbol}) preventivamente "
                                f"para evitar swaps nocturnos y apertura de spread bancario.",
                                "WARNING"
                            )
                            self.executor.close_position(pos, reason="SessionEnd_1650_RiskProtection")
                            continue

                        # Si estamos en ventana de peligro (Rollover / Cierre de mercado) y está configurado cerrar
                        if is_danger_zone and danger_action == "BLOCK_AND_CLOSE" and close_on_rollover:
                            self._log(
                                f"⚠️ [ADVERTENCIA GESTIÓN RIESGO] Cerrando posición #{pos.ticket} ({self.symbol}) preventivamente: "
                                f"{danger_reason}. Protegiendo capital contra ensanchamiento de spread / slippage bancario.",
                                "WARNING"
                            )
                            self.executor.close_position(pos, reason="SpreadRollover_RiskProtection")
                            continue

                        # Rastrear ticket para feedback loop cuando cierre
                        if pos.ticket not in self.tracked_tickets:
                            acc_info = mt5.account_info()
                            balance = acc_info.balance if acc_info else 1000.0
                            self.tracked_tickets[pos.ticket] = {
                                "symbol": self.symbol,
                                "type": "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
                                "open_price": pos.price_open,
                                "risk_usd": balance * self.risk_pct
                            }

                        pos_type_str = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                        pnl_current = pos.profit + pos.swap
                        curr_spread = self.risk_manager.get_current_spread_pips(self.symbol)
                        sym_info = mt5.symbol_info(self.symbol)
                        pip_size = (sym_info.point * 10.0 if sym_info and sym_info.digits in (3, 5) else (sym_info.point if sym_info else 0.0001))
                        profit_pips = ((sym_info.bid - pos.price_open) / pip_size) if (sym_info and pos.type == mt5.POSITION_TYPE_BUY) else (((pos.price_open - sym_info.ask) / pip_size) if sym_info else 0.0)

                        # GESTIÓN 16:15+ (Mover a BE si está en positivo o si recupera >10% de ganancia)
                        if session_rules.get("is_after_1615", False):
                            is_buy_pos = pos.type == mt5.POSITION_TYPE_BUY
                            is_already_be = (is_buy_pos and pos.sl >= pos.price_open - 1e-5) or (not is_buy_pos and pos.sl > 0 and pos.sl <= pos.price_open + 1e-5)

                            if (pnl_current > 0 and profit_pips > 0):
                                if not is_already_be:
                                    self._log(
                                        f"🛡️ [PROTECCIÓN 16:15+] Posición #{pos.ticket} ({self.symbol} {pos_type_str}) en positivo (+{profit_pips:.1f}p | ${pnl_current:+.2f}). "
                                        f"Moviendo SL a punto de entrada (Break Even: {pos.price_open:.5f}).",
                                        "SUCCESS"
                                    )
                                    self.executor.modify_sltp(pos, new_sl=pos.price_open, new_tp=pos.tp, reason="BE_1615")
                            else:
                                # Si está en negativo o neutra, monitorear si superó el 10% de ganancia esperada
                                tp_dist = abs(pos.tp - pos.price_open) if pos.tp > 0 else (pip_size * 20.0)
                                curr_gain_dist = (sym_info.bid - pos.price_open) if is_buy_pos else (pos.price_open - sym_info.ask)
                                gain_pct_target = (curr_gain_dist / max(tp_dist, 1e-5)) if tp_dist > 0 else 0.0

                                if (gain_pct_target >= 0.10 or profit_pips >= 2.0) and pnl_current > 0:
                                    if not is_already_be:
                                        self._log(
                                            f"🎯 [RECUPERACIÓN >10% 16:15+] Posición #{pos.ticket} recuperó ganancia ({gain_pct_target*100:.1f}% de TP | +{profit_pips:.1f}p). "
                                            f"Moviendo SL a punto de entrada (Break Even: {pos.price_open:.5f}).",
                                            "SUCCESS"
                                        )
                                        self.executor.modify_sltp(pos, new_sl=pos.price_open, new_tp=pos.tp, reason="Recuperacion_BE_1615")

                        self._log(
                            f"🛡️ [POSICIÓN ACTIVA DETECTADA] {self.symbol} #{pos.ticket} ({pos_type_str} {pos.volume} lotes | PnL: ${pnl_current:+.2f} ({profit_pips:+.1f}p) | Spread: {curr_spread:.1f} pips). "
                            f"Analizando gestión activa y validación con IA...",
                            "INFO"
                        )

                        # 1. EVALUACIÓN CON IA PARA CIERRE PREMATURO / AJUSTE SL-TP (CON THROTTLING: MÍNIMO 10 MIN O CIERRE DE VELA)
                        ai_managed = False
                        if ai_enabled and api_key.strip():
                            curr_candle = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
                            curr_bar_time = curr_candle.get("time", None) if isinstance(curr_candle, dict) or hasattr(curr_candle, "get") else getattr(curr_candle, "name", None)

                            tf_seconds = TIMEFRAME_SECONDS_MAP.get(self.timeframe, 60)
                            # Intervalo mínimo: 10 minutos (600s) o el timeframe si es mayor (ej. M15: 900s, H1: 3600s)
                            min_interval_sec = max(600, tf_seconds)

                            now_ts = time.time()
                            last_eval_ts = self.last_ai_pos_eval_time.get(pos.ticket, 0.0)
                            last_bar = self.last_ai_pos_eval_bar_time.get(pos.ticket, None)

                            time_passed_sec = now_ts - last_eval_ts
                            is_new_bar = (curr_bar_time is not None and curr_bar_time != last_bar)

                            # Condición para consultar a la IA:
                            # 1) Nunca se ha evaluado con IA (last_eval_ts == 0)
                            # 2) Han pasado mínimo 10 minutos (600s) Y hubo cierre de vela (o si pasaron más de min_interval_sec)
                            should_query_ai = (last_eval_ts == 0.0) or (time_passed_sec >= min_interval_sec and (is_new_bar or tf_seconds < 600))

                            if should_query_ai:
                                self._log(f"🧠 [GESTIÓN IA] Evaluando posición #{pos.ticket} con IA (Intervalo cumplido: {int(time_passed_sec/60)} min / nueva vela)...", "INFO")
                                ema_trend_val = float(curr_candle.get("ema_trend", pos.price_current if hasattr(pos, "price_current") else pos.price_open))
                                atr_val = float(curr_candle.get("atr", 0.0010))

                                pos_data = {
                                    "ticket": pos.ticket,
                                    "symbol": self.symbol,
                                    "type": pos_type_str,
                                    "price_open": pos.price_open,
                                    "price_current": sym_info.bid if pos_type_str == "BUY" else sym_info.ask if sym_info else pos.price_open,
                                    "sl": pos.sl,
                                    "tp": pos.tp,
                                    "volume": pos.volume,
                                    "profit_pips": profit_pips,
                                    "profit_usd": pnl_current
                                }
                                mkt_context = {
                                    "ema_trend": ema_trend_val,
                                    "atr": atr_val,
                                    "spread_pips": curr_spread,
                                    "macro_summary": f"EMA 200: {ema_trend_val:.5f} | ATR: {atr_val:.5f}",
                                    "news_summary": "Sin impacto inmediato"
                                }

                                acc_info = mt5.account_info()
                                account_data = {
                                    "balance": acc_info.balance if acc_info else 0.0,
                                    "equity": acc_info.equity if acc_info else 0.0,
                                    "free_margin": acc_info.margin_free if acc_info else 0.0
                                }

                                thinking_budget = int(cfg.get("ai_thinking_budget", 128))
                                # Recuperar memoria histórica de trades cerrados correspondientes al par
                                pos_past_trades = self.ai_memory.get_relevant_past_trades(symbol=self.symbol, signal=pos_type_str, limit=3)

                                ai_res = evaluate_open_position_ai(
                                    account_info=account_data,
                                    position_info=pos_data,
                                    market_context=mkt_context,
                                    api_key=api_key,
                                    model_name=model_name,
                                    base_url=base_url,
                                    thinking_budget=thinking_budget,
                                    past_trades=pos_past_trades
                                )

                                # Actualizar timestamp y barra de última consulta IA para este ticket
                                self.last_ai_pos_eval_time[pos.ticket] = now_ts
                                self.last_ai_pos_eval_bar_time[pos.ticket] = curr_bar_time

                                if not ai_res.get("fallback", False):
                                    ai_action = ai_res.get("action", "HOLD")
                                    ai_opinion = ai_res.get("opinion", "")
                                    ai_close_reason = ai_res.get("close_reason", "AI_Trend_Reversal")

                                    # Registrar en memoria histórica el análisis de posición
                                    self.ai_memory.log_position_evaluation(
                                        ticket=pos.ticket,
                                        symbol=self.symbol,
                                        ai_action=ai_action,
                                        ai_opinion=ai_opinion,
                                        close_reason=ai_close_reason if ai_action == "EARLY_CLOSE" else "",
                                        profit_pips=profit_pips,
                                        profit_usd=pnl_current
                                    )

                                    if ai_action == "EARLY_CLOSE":
                                        self._log(
                                            f"🛑 ────────── [GESTIÓN IA: CIERRE PREMATURO INMEDIATO] ──────────\n"
                                            f"   ├─ Posición: #{pos.ticket} {self.symbol} ({pos_type_str})\n"
                                            f"   ├─ Motivo IA: {ai_close_reason}\n"
                                            f"   ├─ Diagnóstico: \"{ai_opinion}\"\n"
                                            f"   └─ Acción: Cerrando orden en mercado inmediatamente\n"
                                            f"───────────────────────────────────────────────────────────────────────",
                                            "WARNING"
                                        )
                                        self.executor.close_position(pos, reason=f"AI_{ai_close_reason}")
                                        ai_managed = True
                                        continue
                                    elif ai_action == "MODIFY_SLTP":
                                        new_sl = float(ai_res.get("suggested_sl", pos.sl))
                                        new_tp = float(ai_res.get("suggested_tp", pos.tp))
                                        self._log(
                                            f"🛡️ [GESTIÓN IA: AJUSTE SL/TP] #{pos.ticket} ➔ SL: {new_sl} | TP: {new_tp} ({ai_opinion})",
                                            "SUCCESS"
                                        )
                                        self.executor.modify_sltp(pos, new_sl=new_sl, new_tp=new_tp, reason="AI_Adjustment")
                                        ai_managed = True
                                    else:
                                        self._log(
                                            f"🟢 [GESTIÓN IA: MANTENER ENTRADA] #{pos.ticket} ➔ Posición válida ({ai_opinion})",
                                            "INFO"
                                        )
                                        ai_managed = True
                            else:
                                remaining_min = max(0.0, (min_interval_sec - time_passed_sec) / 60.0)
                                self._log(
                                    f"⏳ [GESTIÓN IA EN ESPERA] Posición #{pos.ticket} ({pos_type_str}) protegida. Próxima consulta IA en {remaining_min:.1f} min o cierre de vela.",
                                    "INFO"
                                )

                        # 2. FALLBACK A ESTRATEGIA CUANTITATIVA LOCAL SI IA NO APLICA O FALLA
                        if not ai_managed:
                            mgmt_result = self.strategy.analyze_open_position(df=df, position=pos)
                            action = mgmt_result.get("action", "MONITOR")
                            reason = mgmt_result.get("reason", "")
                            self._log(f"🔎 [GESTIÓN ESTRATEGIA LOCAL] #{pos.ticket} ➔ Acción: {action} | Razón: {reason}", "INFO")
                            self.executor.manage_position_with_strategy(position=pos, management_result=mgmt_result)

                    # 3. ⚡ EVALUACIÓN DE REENTRADAS POR ESCALERA PROGRESIVA DE FIBONACCI (78.6%, 92%, 100%, 132%, ...)
                    if (len(open_positions) < (max_reentries + 1)) and (max_reentries > 0) and not is_danger_zone:
                        if hasattr(self.strategy, "evaluate_reentry_signal"):
                            reentry_eval = self.strategy.evaluate_reentry_signal(
                                df=df,
                                open_positions=open_positions,
                                max_reentries=max_reentries
                            )
                            reentry_sig = reentry_eval.get("signal", "HOLD")

                            if reentry_sig in ["BUY", "SELL"]:
                                is_spread_ok, curr_spread, sp_msg = self.risk_manager.validate_spread(self.symbol, max_allowed_pips=max_spread_allowed)
                                if not is_spread_ok:
                                    self._log(f"⚠️ [REENTRADA BLOQUEADA] {sp_msg}", "WARNING")
                                else:
                                    self._log(f"⚡ [OPORTUNIDAD DE REENTRADA DETECTADA] {reentry_eval.get('reason')}", "SUCCESS")
                                    reentry_num = reentry_eval.get("reentry_number", len(open_positions))
                                    reentry_tag = reentry_eval.get("reentry_tag", f"Fibo {reentry_eval.get('fibo_level_pct', 78.6)}%")
                                    reentry_comment = reentry_eval.get("order_comment", f"Reentry #{reentry_num} {reentry_tag}")
                                    reentry_sl = reentry_eval.get("sl", 0.0)
                                    reentry_tp = reentry_eval.get("tp", 0.0)
                                    reentry_lot = self.lot

                                    # Validación y recomendación por IA (si está habilitada)
                                    reentry_approved = True
                                    curr_close = float(df['close'].iloc[-1]) if not df.empty else 0.0
                                    tf_name = TIMEFRAME_NAMES.get(self.timeframe, "M15")

                                    ai_api_key = str(cfg.get("ai_api_key", api_key if 'api_key' in locals() else ""))
                                    ai_model = str(cfg.get("ai_model", model_name if 'model_name' in locals() else "gemini-2.5-flash"))
                                    ai_base_url = str(cfg.get("ai_base_url", base_url if 'base_url' in locals() else ""))
                                    ai_budget = int(cfg.get("ai_thinking_budget", 128))

                                    acc_info_now = mt5.account_info()
                                    acct_dict = {
                                        "balance": acc_info_now.balance if acc_info_now else 0.0,
                                        "equity": acc_info_now.equity if acc_info_now else 0.0,
                                        "free_margin": acc_info_now.margin_free if acc_info_now else 0.0
                                    }

                                    if ai_enabled and ai_api_key.strip():
                                        self._log(f"🧠 [IA CONSULTOR] Evaluando Reentrada #{reentry_num} ({reentry_tag}) en {self.symbol}...", "INFO")

                                        # Preparar contexto para la IA
                                        news_txt = news_manager.format_news_summary_for_ai(self.symbol)
                                        macro_txt = analyze_macro_multitimeframe(self.symbol, float(curr_close))
                                        candle_txt = format_candlestick_summary_for_ai(df)
                                        spread_txt = f"Spread: {curr_spread:.1f} pips (Límite: {max_spread_allowed} pips)"
                                        past_trades = self.ai_memory.get_relevant_past_trades(symbol=self.symbol, signal=reentry_sig, limit=3)

                                        reentry_setup = {
                                            "symbol": self.symbol,
                                            "timeframe": tf_name,
                                            "signal": reentry_sig,
                                            "price": float(curr_close),
                                            "default_sl": reentry_sl,
                                            "default_tp": reentry_tp,
                                            "default_lot": reentry_lot,
                                            "is_reentry": True,
                                            "details": reentry_eval,
                                            "news_summary": news_txt,
                                            "macro_summary": macro_txt,
                                            "candlestick_summary": candle_txt,
                                            "spread_info": spread_txt,
                                            "df": df
                                        }

                                        ai_result = evaluate_trade_setup(
                                            candidate_setup=reentry_setup,
                                            account_info=acct_dict,
                                            past_trades=past_trades,
                                            api_key=ai_api_key,
                                            model_name=ai_model,
                                            base_url=ai_base_url,
                                            thinking_budget=ai_budget
                                        )

                                        reentry_approved = ai_result.get("approved", True)
                                        opinion = ai_result.get("opinion", "")
                                        confidence = ai_result.get("confidence", 1.0)
                                        ai_sl = float(ai_result.get("ai_sl", reentry_sl))
                                        ai_tp = float(ai_result.get("ai_tp", reentry_tp))
                                        ai_lot = float(ai_result.get("suggested_lot", reentry_lot))

                                        if reentry_approved:
                                            self._log(f"✅ [IA APROBÓ REENTRADA #{reentry_num}] Confianza: {confidence * 100:.0f}% | {opinion}", "SUCCESS")
                                            if ai_sl > 0:
                                                reentry_sl = ai_sl
                                            if ai_tp > 0:
                                                reentry_tp = ai_tp
                                            if ai_lot > 0:
                                                reentry_lot = ai_lot
                                        else:
                                            reentry_rej = ai_result.get("rejection_reason", "Descartado por IA")
                                            self._log(f"🛑 [IA BLOQUEÓ REENTRADA #{reentry_num}] Razón: {reentry_rej} | {opinion}", "WARNING")

                                    if reentry_approved:
                                        self.executor.send_order(
                                            order_type=reentry_sig,
                                            volume=reentry_lot,
                                            sl_price=reentry_sl,
                                            tp_price=reentry_tp,
                                            comment=reentry_comment
                                        )
                                        self._log(f"🚀 [REENTRADA #{reentry_num}/{max_reentries} ENVIADA] {self.symbol} {reentry_sig} ({reentry_tag}) | Lote: {reentry_lot} | SL: {reentry_sl} | TP: {reentry_tp}", "SUCCESS")

                else:
                    # 🟢 RAMA B: NO HAY POSICIONES ABIERTAS ➔ BUSCAR NUEVAS ENTRADAS
                    # 1. Comprobar si estamos en zona de peligro (Rollover / Cierre semanal)
                    if is_danger_zone:
                        self._log(f"⏸️ [OPERATIVA EN PAUSA] {danger_reason} No se buscan nuevas entradas.", "INFO")
                        signal = "HOLD"
                    elif self.test_mode:
                        signal = "BUY"
                        signal_data = {"signal": "BUY", "reason": "Modo Test Activo", "score": 3}
                        self._log(f"🧪 [MODO TEST] Señal forzada BUY en {self.symbol}", "INFO")
                    else:
                        self._log(f"🧠 [ANALIZANDO] Sin órdenes abiertas en {self.symbol}. Evaluando confluencias para nueva entrada...", "INFO")
                        signal_data = self.strategy.generate_signal(df)
                        signal = signal_data.get("signal", "HOLD") if isinstance(signal_data, dict) else str(signal_data)
                        self._log(f"🧠 [RESULTADO ANÁLISIS] {signal_data} - {self.symbol}", "INFO")

                    # 2. Comprobar Filtro de Horario (16:00+) y Filtro de Spread Máximo antes de avanzar a validaciones complejas
                    if signal in ["BUY", "SELL"]:
                        daily_rules = self.risk_manager.get_daily_session_rules()
                        if not daily_rules.get("allow_new_entries", True):
                            self._log(
                                f"⏸️ [ENTRADA BLOQUEADA POR VENTANA ROLLOVER 16:00-17:20] Señal {signal} en {self.symbol} descartada. "
                                f"Hora actual ({daily_rules.get('current_time_str')}). Nuevas entradas en pausa hasta las 17:20.",
                                "WARNING"
                            )
                            signal = "HOLD"

                    if signal in ["BUY", "SELL"]:
                        is_spread_ok, curr_spread, spread_msg = self.risk_manager.validate_spread(
                            self.symbol, max_allowed_pips=max_spread_allowed
                        )
                        if not is_spread_ok:
                            self._log(f"🚫 [ENTRADA BLOQUEADA POR SPREAD] {spread_msg}", "WARNING")
                            signal = "HOLD"


                    if signal in ["BUY", "SELL"]:
                        # 🟢 VALIDACIÓN DE FILTRO DE CORRELACIÓN DE PARES (PEARSON)
                        all_open_positions = mt5.positions_get()
                        other_positions = [
                            {
                                "symbol": p.symbol,
                                "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                                "ticket": p.ticket
                            }
                            for p in all_open_positions
                            if p.symbol != self.symbol
                        ] if all_open_positions else []

                        if other_positions and self.strategy.use_correlation_filter:
                            market_data: Dict[str, pd.DataFrame] = {self.symbol: df}
                            rates_needed = max(self.strategy.correlation_window + 10, 60)

                            for pos in other_positions:
                                sym_other = pos["symbol"]
                                if sym_other not in market_data:
                                    df_other = get_historical_data(
                                        symbol=sym_other,
                                        timeframe=self.timeframe,
                                        rates_count=rates_needed
                                    )
                                    if df_other is not None and not df_other.empty:
                                        market_data[sym_other] = df_other

                            is_safe_to_trade, corr_reason = self.strategy.validate_correlation_filter(
                                target_symbol=self.symbol,
                                signal_type=signal,
                                active_positions=other_positions,
                                market_data=market_data
                            )

                            if not is_safe_to_trade:
                                self._log(f"🚫 [ORDEN CANCELADA POR CORRELACIÓN] {corr_reason}", "WARNING")
                                signal = "HOLD"

                    if signal in ["BUY", "SELL"]:
                        acc_info = mt5.account_info()
                        balance = acc_info.balance if acc_info else 0.0
                        equity = acc_info.equity if acc_info else balance
                        free_margin = acc_info.margin_free if acc_info else balance

                        tick = mt5.symbol_info_tick(self.symbol)
                        current_price = tick.ask if signal == "BUY" else (tick.bid if tick else float(df['close'].iloc[-1]))

                        # 1. Cálculo base de SL / TP por Estrategia / Gestión de Riesgo
                        sl_pips = self.risk_manager.calculate_sl_pips_from_risk(
                            balance=balance,
                            fixed_lot=self.lot,
                            risk_pct=self.risk_pct,
                            symbol=self.symbol
                        )
                        rr_ratio = getattr(self.strategy.config, "risk_reward_ratio", 2.0)
                        tp_pips = round(sl_pips * rr_ratio, 1)

                        sym_info = mt5.symbol_info(self.symbol)
                        pip_size = (sym_info.point * 10.0 if sym_info and sym_info.digits in (3, 5) else (sym_info.point if sym_info else 0.0001))
                        default_sl_price = round(current_price - (sl_pips * pip_size) if signal == "BUY" else current_price + (sl_pips * pip_size), sym_info.digits if sym_info else 5)
                        default_tp_price = round(current_price + (tp_pips * pip_size) if signal == "BUY" else current_price - (tp_pips * pip_size), sym_info.digits if sym_info else 5)

                        # 2. Cargar configuración de IA
                        cfg = load_config()
                        ai_enabled = cfg.get("ai_enabled", True)
                        api_key = cfg.get("ai_api_key", "")
                        model_name = cfg.get("ai_model", "gemini-2.5-flash")
                        base_url = cfg.get("ai_base_url", "")

                        final_sl_price = default_sl_price
                        final_tp_price = default_tp_price
                        final_lot = self.lot
                        trade_approved = True
                        ai_opinion = ""

                        if ai_enabled and api_key.strip():
                            self._log(f"🧠 [CONSULTA IA] Validando setup y optimizando SL/TP con IA ({model_name})...", "INFO")

                            # Recuperar memoria histórica de operaciones similares
                            past_trades = self.ai_memory.get_relevant_past_trades(symbol=self.symbol, signal=signal, limit=3)

                            atr_val = signal_data.get("atr", round(sl_pips * pip_size, 5)) if isinstance(signal_data, dict) else round(sl_pips * pip_size, 5)
                            current_spread_val = self.risk_manager.get_current_spread_pips(self.symbol)
                            candidate_setup = {
                                "symbol": self.symbol,
                                "signal": signal,
                                "price": current_price,
                                "default_sl": default_sl_price,
                                "default_tp": default_tp_price,
                                "default_lot": self.lot,
                                "timeframe": "M15",
                                "atr": atr_val,
                                "spread_info": f"Spread actual: {current_spread_val:.1f} pips (Máx permitido: {max_spread_allowed} pips)",
                                "confluence_score": signal_data.get("score", 2) if isinstance(signal_data, dict) else 2,
                                "details": signal_data if isinstance(signal_data, dict) else {"reason": str(signal_data)}
                            }

                            account_data = {
                                "balance": balance,
                                "equity": equity,
                                "free_margin": free_margin
                            }

                            thinking_budget = int(cfg.get("ai_thinking_budget", 128))
                            ai_eval = evaluate_trade_setup(
                                account_info=account_data,
                                candidate_setup=candidate_setup,
                                past_trades=past_trades,
                                api_key=api_key,
                                model_name=model_name,
                                base_url=base_url,
                                thinking_budget=thinking_budget
                            )

                            if ai_eval.get("fallback", False):
                                err_info = ai_eval.get('fallback_error', 'N/A')
                                self._log(
                                    f"⚠️ ────────── [RESPUESTA IA: {self.symbol} - FALLBACK ACTIVADO] ──────────\n"
                                    f"   ├─ Estado: Fallback cuantitativo ejecutado sin detener la operativa\n"
                                    f"   ├─ Motivo: {err_info[:90]}\n"
                                    f"   ├─ Log Detalle: {ai_eval.get('log_file', 'ia-log/')}\n"
                                    f"   └─ SL Estrategia: {default_sl_price} | TP Estrategia: {default_tp_price}\n"
                                    f"───────────────────────────────────────────────────────────────────────",
                                    "WARNING"
                                )
                                trade_approved = True
                                ai_opinion = ai_eval.get("opinion", "Fallback")
                            elif not ai_eval.get("approved", True):
                                trade_approved = False
                                rej_reason = ai_eval.get("rejection_reason") or ai_eval.get("opinion", "Rechazada por riesgo")
                                conf_pct = int(ai_eval.get("confidence", 0.5) * 100)
                                latency = ai_eval.get("latency_ms", 0.0)
                                self._log(
                                    f"🛑 ────────── [RESPUESTA IA: {self.symbol} - ENTRADA BLOQUEADA] ──────────\n"
                                    f"   ├─ Decisión: RECHAZADA (Confianza: {conf_pct}% | Latencia: {latency}ms)\n"
                                    f"   ├─ Modelo: {model_name}\n"
                                    f"   ├─ Razón: \"{rej_reason}\"\n"
                                    f"   └─ Log Completo: {ai_eval.get('log_file', 'ia-log/')}\n"
                                    f"───────────────────────────────────────────────────────────────────────",
                                    "WARNING"
                                )
                                # Registrar análisis rechazado en memoria
                                self.ai_memory.save_analysis({
                                    "trade_id": int(time.time()),
                                    "symbol": self.symbol,
                                    "signal": signal,
                                    "score": candidate_setup.get("confluence_score", 0),
                                    "ai_opinion": f"RECHAZADO: {rej_reason}",
                                    "ai_confidence": ai_eval.get("confidence", 0.0),
                                    "outcome": {"status": "REJECTED_BY_AI", "result": "BLOCKED"}
                                })
                            else:
                                trade_approved = True
                                final_sl_price = float(ai_eval.get("ai_sl", default_sl_price))
                                final_tp_price = float(ai_eval.get("ai_tp", default_tp_price))
                                ai_opinion = ai_eval.get("opinion", "Aprobado por IA")
                                conf_pct = int(ai_eval.get("confidence", 0.8) * 100)
                                latency = ai_eval.get("latency_ms", 0.0)
                                rr_val = ai_eval.get('risk_reward_ratio', 2.0)
                                self._log(
                                    f"🧠 ────────── [RESPUESTA IA: {self.symbol} - ENTRADA APROBADA] ──────────\n"
                                    f"   ├─ Decisión: APROBADA (Confianza: {conf_pct}% | Latencia: {latency}ms)\n"
                                    f"   ├─ Modelo: {model_name}\n"
                                    f"   ├─ SL Optimizado IA: {final_sl_price} | TP Optimizado IA: {final_tp_price} (R:R 1:{rr_val})\n"
                                    f"   ├─ Análisis: \"{ai_opinion}\"\n"
                                    f"   └─ Log Debug: {ai_eval.get('log_file', 'ia-log/')}\n"
                                    f"───────────────────────────────────────────────────────────────────────",
                                    "SUCCESS"
                                )

                        if trade_approved:
                            # Ejecutar orden con lote, SL y TP calculados (optimizados por IA o por la estrategia)
                            resultado = self.executor.send_order(
                                order_type=signal,
                                volume=final_lot,
                                sl_price=final_sl_price,
                                tp_price=final_tp_price,
                                comment=f"AI_{self.strategy_name[:4]}"
                            )
                            if isinstance(resultado, dict) and not resultado.get("status", False):
                                self._log(f"❌ Error al ejecutar orden: {resultado.get('message', 'Desconocido')}", "ERROR")
                            else:
                                ticket_num = resultado.get("ticket", 0)
                                self._log(f"✅ [ORDEN EJECUTADA] Ticket #{ticket_num} {self.symbol} {signal} @ {resultado.get('price')} (SL: {final_sl_price} | TP: {final_tp_price})", "SUCCESS")

                                # Registrar en memoria para el loop de aprendizaje
                                self.ai_memory.save_analysis({
                                    "trade_id": ticket_num,
                                    "symbol": self.symbol,
                                    "signal": signal,
                                    "entry_price": resultado.get("price"),
                                    "sl": final_sl_price,
                                    "tp": final_tp_price,
                                    "volume": final_lot,
                                    "ai_opinion": ai_opinion,
                                    "ai_confidence": ai_eval.get("confidence", 1.0) if 'ai_eval' in locals() else 1.0,
                                    "context": {
                                        "timeframe": self.timeframe,
                                        "strategy": self.strategy_name,
                                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    },
                                    "outcome": {"status": "OPEN", "result": "PENDING"}
                                })

                                # Guardar en rastreo para detectar cuando cierre
                                self.tracked_tickets[ticket_num] = {
                                    "symbol": self.symbol,
                                    "type": signal,
                                    "open_price": resultado.get("price"),
                                    "risk_usd": balance * self.risk_pct
                                }

            except Exception as e:
                self._log(f"Error en worker {self.symbol}: {e}", "ERROR")
                traceback.print_exc()

            # Calcular segundos restantes para la siguiente vela
            seconds = TIMEFRAME_SECONDS_MAP.get(self.timeframe, 60)
            sleep_time = calculate_sleep_seconds(seconds)

            # Notificación enviada a la consola de la GUI
            self._log(f"⏳ Próximo análisis de vela en {int(sleep_time)} segundos...", "INFO")

            # Espera interrumpible
            sleep_counter = 0.0
            while sleep_counter < sleep_time and not self.stop_event.is_set():
                time.sleep(1.0)
                sleep_counter += 1.0

    def _log(self, message: str, level: str = "INFO") -> None:
        """Envía el log de vuelta a la GUI en la pestaña correspondiente."""
        self.log_callback(self.symbol, message, level)
