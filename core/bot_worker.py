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
from core.ai_advisor import evaluate_trade_setup
from core.ai_memory import AIMemoryManager

TIMEFRAME_SECONDS_MAP: Dict[int, int] = {
    mt5.TIMEFRAME_M1: 60,
    mt5.TIMEFRAME_M5: 300,
    mt5.TIMEFRAME_M15: 900,
    mt5.TIMEFRAME_M30: 1800,
    mt5.TIMEFRAME_H1: 3600,
    mt5.TIMEFRAME_H4: 14400,
    mt5.TIMEFRAME_D1: 86400,
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

    def _check_closed_trades(self) -> None:
        """Verifica si alguna de las operaciones rastreadas se cerró para registrar el feedback (WIN/LOSS) en trade_memory.json."""
        if not self.tracked_tickets:
            return

        current_positions = mt5.positions_get(symbol=self.symbol)
        open_tickets = {p.ticket for p in current_positions} if current_positions else set()

        closed_tickets = [t for t in self.tracked_tickets.keys() if t not in open_tickets]
        for ticket in closed_tickets:
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

    def run(self) -> None:
        self._log(f"Iniciando monitoreo para {self.symbol} con estrategia '{self.strategy_name}'...", "INFO")

        while not self.stop_event.is_set():
            try:
                # 0. Verificar si trades anteriores se han cerrado para actualizar la memoria
                self._check_closed_trades()

                # 1. Obtener datos según la temporalidad configurada para este símbolo
                df = get_historical_data(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    rates_count=300,
                    log_callback=self.log_callback
                )

                if df is None or df.empty:
                    time.sleep(3)
                    continue

                # 2. Verificar si ya existe al menos una posición abierta en este par
                open_positions = mt5.positions_get(symbol=self.symbol)

                # ⚠️ FILTRO DE SEGURIDAD 1: VERIFICAR VENTANA DE ROLLOVER Y CIERRE DE MERCADO
                cfg = load_config()
                max_spread_allowed = float(cfg.get("max_spread_pips", 3.5))
                close_on_rollover = bool(cfg.get("close_before_rollover", True))
                rollover_start = str(cfg.get("rollover_start_utc", "21:30"))
                rollover_end = str(cfg.get("rollover_end_utc", "22:30"))
                min_before_close = int(cfg.get("weekend_close_minutes_before", 15))

                is_danger_zone, danger_reason, danger_action = self.risk_manager.is_rollover_or_market_close_window(
                    minutes_before_close=min_before_close,
                    rollover_start=rollover_start,
                    rollover_end=rollover_end
                )

                if open_positions and len(open_positions) > 0:
                    # 🟢 RAMA A: POSICIÓN ABIERTA ACTIVA ➔ GESTIÓN DE SL/TP Y CIERRE PREMATURO / ROLLOVER
                    for pos in open_positions:
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
                        self._log(
                            f"🛡️ [POSICIÓN ACTIVA DETECTADA] {self.symbol} #{pos.ticket} ({pos_type_str} {pos.volume} lotes | PnL: ${pnl_current:+.2f} | Spread: {curr_spread:.1f} pips). "
                            f"Omitiendo búsqueda de nuevas entradas. Analizando SL/TP y posibles cierres prematuros...",
                            "INFO"
                        )

                        # Análisis de la posición abierta con la estrategia cuantitativa
                        mgmt_result = self.strategy.analyze_open_position(df=df, position=pos)
                        action = mgmt_result.get("action", "MONITOR")
                        reason = mgmt_result.get("reason", "")

                        self._log(f"🔎 [ANÁLISIS GESTIÓN POSICIÓN] #{pos.ticket} ➔ Acción: {action} | Razón: {reason}", "INFO")

                        # Ejecutar acción recomendada (Cierre prematuro, modificación de SL/TP, Break-Even)
                        self.executor.manage_position_with_strategy(position=pos, management_result=mgmt_result)

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

                    # 2. Comprobar Filtro de Spread Máximo antes de avanzar a validaciones complejas
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

                            ai_eval = evaluate_trade_setup(
                                account_info=account_data,
                                candidate_setup=candidate_setup,
                                past_trades=past_trades,
                                api_key=api_key,
                                model_name=model_name,
                                base_url=base_url
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
