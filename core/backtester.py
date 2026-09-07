"""
Motor de backtesting: recorre el historial REAL de velas de MT5 y simula, vela a vela,
las señales y la gestión de posición que la estrategia habría generado en producción —
usando la misma ventana móvil de 300 velas por evaluación que usa core/bot_worker.py en
vivo (get_historical_data rates_count=300) — para estimar win rate / expectativa reales
por símbolo, incluso en símbolos que el bot nunca ha operado todavía.

Los resultados se cachean en backtest_results.json (raíz del proyecto) para no tener que
recorrer todo el historial de nuevo en cada "Deep Search" — solo se re-analizan los
símbolos sin resultado cacheado o con caché vencida.
"""

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Any, List, Optional, Callable
import MetaTrader5 as mt5
import pandas as pd

from core.strategies import create_strategy_instance
from core.data_loader import resolve_mt5_symbol
from core.stats_calculator import wilson_lower_bound

BACKTEST_RESULTS_FILE = Path(__file__).resolve().parent.parent / "backtest_results.json"
LIVE_ROLLING_WINDOW = 300  # Misma ventana que bot_worker.py pide en vivo (rates_count=300)
CACHE_MAX_AGE_HOURS = 24.0

# Timeframes candidatos para sugerir cuál rinde mejor por símbolo (M1 excluido: demasiado
# ruidoso y costoso de recorrer; D1 excluido: muy pocas señales en un historial manejable)
CANDIDATE_TIMEFRAMES: List[int] = [
    mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_M30, mt5.TIMEFRAME_H1, mt5.TIMEFRAME_H4
]

_TF_SECONDS: Dict[int, int] = {
    mt5.TIMEFRAME_M1: 60, mt5.TIMEFRAME_M5: 300, mt5.TIMEFRAME_M15: 900,
    mt5.TIMEFRAME_M30: 1800, mt5.TIMEFRAME_H1: 3600, mt5.TIMEFRAME_H4: 14400, mt5.TIMEFRAME_D1: 86400,
}


def _default_history_bars_for_tf(timeframe: int, target_days: int = 30) -> int:
    """Calcula cuántas velas pedir para cubrir ~target_days de calendario en ese timeframe,
    con un piso y techo razonables para mantener el backtest en un tiempo manejable."""
    seconds = _TF_SECONDS.get(timeframe, 300)
    bars = int((target_days * 86400) / seconds)
    return max(500, min(bars, 8000))


def _load_results_cache() -> Dict[str, Any]:
    if not os.path.exists(BACKTEST_RESULTS_FILE):
        return {}
    try:
        with open(BACKTEST_RESULTS_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except Exception:
        return {}


def _save_results_cache(data: Dict[str, Any]) -> None:
    try:
        with open(BACKTEST_RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[DEBUG BACKTEST] Error guardando backtest_results.json: {e}")


def _cache_key(symbol: str, strategy_name: str, timeframe: int) -> str:
    return f"{symbol}|{strategy_name}|{timeframe}"


def backtest_symbol(
    symbol: str,
    strategy_name: str,
    timeframe: int,
    history_bars: int = 3000,
    rolling_window: int = LIVE_ROLLING_WINDOW,
    cancel_event: Optional[threading.Event] = None
) -> Dict[str, Any]:
    """
    Simula bar a bar cómo se habría comportado `strategy_name` sobre el historial real de
    `symbol` en `timeframe`, replicando exactamente la ventana móvil de 300 velas que usa
    el bot en producción (no una ventana creciente con todo el historial, para que el
    resultado sea fiel a lo que el bot realmente vería en vivo).

    Simula entradas (generate_signal), gestión activa de la posición abierta
    (analyze_open_position: trailing stop, cierre prematuro, ajuste de SL/TP) y el cierre
    final por SL o TP tocado en el rango High/Low de cada vela.

    Si `cancel_event` se activa a mitad de camino, se detiene y retorna los resultados
    parciales acumulados hasta ese punto (marcados con "cancelled": True), en vez de
    descartar el trabajo ya hecho.
    """
    resolved = resolve_mt5_symbol(symbol)
    if not resolved:
        return {"symbol": symbol, "trades": 0, "bars_analyzed": 0, "error": "Símbolo no encontrado en MT5"}

    rates = mt5.copy_rates_from_pos(resolved, timeframe, 0, history_bars)
    bars_returned = 0 if rates is None else len(rates)
    if rates is None or bars_returned < rolling_window + 50:
        return {
            "symbol": symbol, "trades": 0, "bars_analyzed": bars_returned,
            "error": (
                f"MT5 solo devolvió {bars_returned} velas para este timeframe "
                f"(se necesitan al menos {rolling_window + 50}). El broker/terminal no tiene "
                f"más historial disponible para este símbolo en este timeframe — pedir más "
                f"velas no va a ayudar aquí."
            )
        }

    df_full = pd.DataFrame(rates)
    df_full = df_full[["time", "open", "high", "low", "close", "tick_volume"]].reset_index(drop=True)

    try:
        strategy = create_strategy_instance(strategy_name, symbol=resolved)
    except Exception as e:
        return {"symbol": symbol, "trades": 0, "error": f"No se pudo crear la estrategia: {e}"}

    # Desactivar filtros que dependen de la hora REAL del reloj (no de la vela histórica
    # simulada): el filtro de horario de sesión y la confirmación multi-timeframe (que
    # consulta MT5 "ahora mismo"). Dejarlos activos en backtest da resultados falsos —
    # dependerían de a qué hora del día se corre la búsqueda, no del período simulado.
    # No-op seguro para estrategias que no tengan estos atributos (ej. SimpleTrendStrategy).
    if hasattr(strategy, "use_session_filter"):
        strategy.use_session_filter = False
    if hasattr(strategy, "use_htf_confirmation"):
        strategy.use_htf_confirmation = False

    open_trade: Optional[Dict[str, Any]] = None
    closed_trades: List[Dict[str, Any]] = []

    total_bars = len(df_full)
    start_idx = rolling_window
    was_cancelled = False

    for i in range(start_idx, total_bars):
        if cancel_event is not None and cancel_event.is_set():
            was_cancelled = True
            break

        window = df_full.iloc[i - rolling_window:i + 1].reset_index(drop=True)
        curr = window.iloc[-2]  # última vela "cerrada" en el instante simulado i (misma convención -2 del bot)

        if open_trade is None:
            try:
                sig = strategy.generate_signal(window)
            except Exception:
                continue

            signal = sig.get("signal", "HOLD")
            if signal in ("BUY", "SELL"):
                sl = float(sig.get("sl", 0.0) or 0.0)
                tp = float(sig.get("tp", 0.0) or 0.0)
                entry_price = float(curr["close"])
                if sl > 0 and tp > 0:
                    try:
                        from core.candlestick_patterns import format_candlestick_summary_for_ai
                        pattern_summary = format_candlestick_summary_for_ai(window)
                    except Exception:
                        pattern_summary = "Estándar"

                    open_trade = {
                        "signal": signal,
                        "entry_price": entry_price,
                        "sl": sl,
                        "tp": tp,
                        "entry_time": int(curr.get("time", 0)),
                        "entry_idx": i,
                        "reason": sig.get("reason", "Señal Estrategia"),
                        "pattern": pattern_summary,
                        "mfe_r": 0.0,
                        "mae_r": 0.0,
                    }
        else:
            is_buy = open_trade["signal"] == "BUY"
            hit_sl = (curr["low"] <= open_trade["sl"]) if is_buy else (curr["high"] >= open_trade["sl"])
            hit_tp = (curr["high"] >= open_trade["tp"]) if is_buy else (curr["low"] <= open_trade["tp"])

            sl_dist_curr = abs(open_trade["entry_price"] - open_trade["sl"])
            if sl_dist_curr > 1e-9:
                curr_high = float(curr["high"])
                curr_low = float(curr["low"])
                fav_dist = (curr_high - open_trade["entry_price"]) if is_buy else (open_trade["entry_price"] - curr_low)
                adv_dist = (open_trade["entry_price"] - curr_low) if is_buy else (curr_high - open_trade["entry_price"])
                open_trade["mfe_r"] = max(open_trade.get("mfe_r", 0.0), round(fav_dist / sl_dist_curr, 2))
                open_trade["mae_r"] = max(open_trade.get("mae_r", 0.0), round(adv_dist / sl_dist_curr, 2))

            exit_price = None
            exit_reason = "MONITOR"
            if hit_sl:
                # Si ambos (SL y TP) se tocan en la misma vela, se asume el peor caso (SL) por seguridad.
                exit_price = open_trade["sl"]
                exit_reason = "SL_HIT"
            elif hit_tp:
                exit_price = open_trade["tp"]
                exit_reason = "TP_HIT"
            else:
                fake_position = SimpleNamespace(
                    type=mt5.POSITION_TYPE_BUY if is_buy else mt5.POSITION_TYPE_SELL,
                    price_open=open_trade["entry_price"],
                    sl=open_trade["sl"],
                    tp=open_trade["tp"],
                    ticket=0
                )
                try:
                    mgmt = strategy.analyze_open_position(window, fake_position)
                except Exception:
                    mgmt = {"action": "MONITOR"}

                action = mgmt.get("action", "MONITOR")
                if action == "EARLY_CLOSE":
                    exit_price = float(curr["close"])
                    exit_reason = mgmt.get("close_reason", "EARLY_CLOSE")
                elif action == "MODIFY_SLTP":
                    new_sl = mgmt.get("suggested_sl")
                    new_tp = mgmt.get("suggested_tp")
                    if new_sl:
                        open_trade["sl"] = float(new_sl)
                    if new_tp:
                        open_trade["tp"] = float(new_tp)

            if exit_price is not None:
                sl_dist = abs(open_trade["entry_price"] - open_trade["sl"])
                pnl_price = (exit_price - open_trade["entry_price"]) if is_buy else (open_trade["entry_price"] - exit_price)
                pnl_r = round(pnl_price / sl_dist, 2) if sl_dist > 1e-9 else 0.0
                is_win = pnl_r > 0
                trade_record = {
                    "signal": open_trade["signal"],
                    "entry_price": open_trade["entry_price"],
                    "exit_price": exit_price,
                    "sl": open_trade["sl"],
                    "tp": open_trade["tp"],
                    "pnl_r": pnl_r,
                    "result": "WIN" if is_win else "LOSS",
                    "exit_reason": exit_reason,
                    "holding_bars": i - open_trade.get("entry_idx", i),
                    "pattern": open_trade.get("pattern", "Estándar"),
                    "entry_reason": open_trade.get("reason", "Señal Estrategia"),
                    "mfe_r": open_trade.get("mfe_r", 0.0),
                    "mae_r": open_trade.get("mae_r", 0.0),
                }
                closed_trades.append(trade_record)
                open_trade = None

    n = len(closed_trades)
    wins = sum(1 for t in closed_trades if t["result"] == "WIN")
    win_rate = round((wins / n * 100.0), 1) if n else 0.0
    avg_r = round((sum(t["pnl_r"] for t in closed_trades) / n), 2) if n else 0.0
    win_rate_confidence = round(wilson_lower_bound(wins, n), 1) if n else 0.0

    sample_wins = [t for t in closed_trades if t["result"] == "WIN"][-8:]
    sample_losses = [t for t in closed_trades if t["result"] == "LOSS"][-8:]
    sample_trades = sample_wins + sample_losses

    return {
        "symbol": symbol,
        "resolved_symbol": resolved,
        "strategy": strategy_name,
        "timeframe": timeframe,
        "bars_analyzed": total_bars,
        "trades": n,
        "wins": wins,
        "losses": n - wins,
        "win_rate": win_rate,
        "win_rate_confidence": win_rate_confidence,
        "avg_r": avg_r,
        "cancelled": was_cancelled,
        "updated_at": time.time(),
        "sample_trades": sample_trades,
    }


def run_deep_search(
    symbols: List[str],
    strategy_name: str,
    timeframe_map: Dict[str, int],
    target_days: int = 30,
    force_refresh: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    result_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[threading.Event] = None
) -> List[Dict[str, Any]]:
    """
    Corre backtest_symbol sobre una lista de símbolos y guarda/actualiza los resultados en
    backtest_results.json. Si un símbolo ya tiene un resultado cacheado y reciente
    (< CACHE_MAX_AGE_HOURS) para la misma estrategia+timeframe, lo reutiliza en vez de
    recalcularlo (salvo que force_refresh=True).

    `timeframe_map`: {símbolo: timeframe_mt5} — el timeframe a usar por símbolo (normalmente
    el mismo que tiene configurado en la tabla de símbolos activos).
    `target_days`: cuántos días de calendario cubrir — la cantidad de velas se calcula por
    símbolo según su propio timeframe (_default_history_bars_for_tf), para que un símbolo en
    M5 y otro en H4 cubran el mismo período real en vez de la misma cantidad de velas.
    `progress_callback(done, total, current_symbol)`: opcional, para reportar avance a la GUI.
    `result_callback(result)`: opcional, se llama con el resultado de CADA símbolo apenas
    está listo (para mostrarlo en la GUI sin esperar a que termine todo el lote).
    `cancel_event`: si se activa, se detiene antes del próximo símbolo (los resultados
    parciales de un símbolo cancelado a mitad de camino no se cachean, para reintentarlo
    completo la próxima vez).
    """
    cache = _load_results_cache()
    now = time.time()
    results: List[Dict[str, Any]] = []
    total = len(symbols)

    for idx, symbol in enumerate(symbols):
        if cancel_event is not None and cancel_event.is_set():
            break

        timeframe = timeframe_map.get(symbol, mt5.TIMEFRAME_M5)
        history_bars = _default_history_bars_for_tf(timeframe, target_days)
        key = _cache_key(symbol, strategy_name, timeframe)

        cached = cache.get(key)
        is_fresh = cached is not None and (now - cached.get("updated_at", 0)) < (CACHE_MAX_AGE_HOURS * 3600)

        if is_fresh and not force_refresh:
            result = cached
        else:
            result = backtest_symbol(symbol, strategy_name, timeframe, history_bars=history_bars, cancel_event=cancel_event)
            if not result.get("cancelled"):
                cache[key] = result
                _save_results_cache(cache)  # Guardar incrementalmente: si se corta a mitad de camino, no se pierde lo ya hecho

        results.append(result)

        if progress_callback:
            progress_callback(idx + 1, total, symbol)
        if result_callback:
            result_callback(result)

    return results


def find_best_timeframe(
    symbol: str,
    strategy_name: str,
    candidate_timeframes: Optional[List[int]] = None,
    force_refresh: bool = False,
    target_days: int = 30,
    history_bars_override: Optional[int] = None,
    min_trades: int = 5,
    cancel_event: Optional[threading.Event] = None
) -> Dict[str, Any]:
    """
    Corre backtest_symbol para el mismo símbolo+estrategia en varios timeframes candidatos
    (cacheando cada combinación igual que run_deep_search) y retorna cuál dio mejor
    Expectativa (avg_r) con muestra mínima de señales, para sugerir el timeframe más
    adecuado por par — la misma idea que "Lote Sugerido", pero para el timeframe.

    `target_days`: días de calendario a cubrir por timeframe candidato (se traduce a
    cantidad de velas automáticamente, distinta para M5 que para H4, para que todos cubran
    el mismo período real). `history_bars_override`, si se da, fuerza la misma cantidad
    exacta de velas para TODOS los candidatos en vez de calcularla por calendario.

    `min_trades`: mínimo de operaciones para considerar un timeframe como muestra válida
    (default 5 — con menos que eso el Win Rate ajustado por Wilson ya lo señala como poco
    confiable, no hace falta descartarlo del todo con un umbral más alto).
    """
    candidates = candidate_timeframes or CANDIDATE_TIMEFRAMES
    cache = _load_results_cache()
    now = time.time()
    per_timeframe: List[Dict[str, Any]] = []

    for tf in candidates:
        if cancel_event is not None and cancel_event.is_set():
            break

        key = _cache_key(symbol, strategy_name, tf)
        cached = cache.get(key)
        is_fresh = cached is not None and (now - cached.get("updated_at", 0)) < (CACHE_MAX_AGE_HOURS * 3600)

        if is_fresh and not force_refresh:
            result = cached
        else:
            bars = history_bars_override or _default_history_bars_for_tf(tf, target_days)
            result = backtest_symbol(symbol, strategy_name, tf, history_bars=bars, cancel_event=cancel_event)
            if not result.get("cancelled"):
                cache[key] = result
                _save_results_cache(cache)

        per_timeframe.append(result)

    valid = [r for r in per_timeframe if not r.get("error") and r.get("trades", 0) >= min_trades]

    if not valid:
        tf_labels = {
            mt5.TIMEFRAME_M1: "M1", mt5.TIMEFRAME_M5: "M5", mt5.TIMEFRAME_M15: "M15",
            mt5.TIMEFRAME_M30: "M30", mt5.TIMEFRAME_H1: "H1", mt5.TIMEFRAME_H4: "H4", mt5.TIMEFRAME_D1: "D1",
        }
        diag_parts = []
        for r in per_timeframe:
            label = tf_labels.get(r.get("timeframe"), "?")
            if r.get("error"):
                diag_parts.append(f"{label}: {r['error']}")
            else:
                diag_parts.append(f"{label}: {r.get('bars_analyzed', 0)}velas/{r.get('trades', 0)}trades")
        diagnostic = f"Ningún timeframe llegó a {min_trades} operaciones — " + " | ".join(diag_parts)

        return {
            "symbol": symbol,
            "best_timeframe": None,
            "best_win_rate": 0.0,
            "best_avg_r": 0.0,
            "per_timeframe": per_timeframe,
            "conclusive": False,
            "diagnostic": diagnostic
        }

    best = max(valid, key=lambda r: r["avg_r"])
    return {
        "symbol": symbol,
        "best_timeframe": best["timeframe"],
        "best_win_rate": best["win_rate"],
        "best_avg_r": best["avg_r"],
        "best_trades": best["trades"],
        "per_timeframe": per_timeframe,
        "conclusive": True
    }


def get_cached_results(strategy_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retorna todos los resultados cacheados (opcionalmente filtrados por estrategia)."""
    cache = _load_results_cache()
    results = list(cache.values())
    if strategy_name:
        results = [r for r in results if r.get("strategy") == strategy_name]
    return results


def run_daily_incremental_backtest(
    symbols: List[str],
    strategy_name: str,
    timeframe_map: Dict[str, int],
    cancel_event: Optional[threading.Event] = None
) -> List[Dict[str, Any]]:
    """
    Ejecuta un backtest ligero únicamente sobre las últimas 24h de velas (1 día de historial)
    para cada símbolo y FUSIONA acumulativamente las nuevas operaciones simuladas
    en 'backtest_results.json' sin recalcular ni borrar el histórico anterior.
    """
    cache = _load_results_cache()
    updated_records = []

    for sym in symbols:
        if cancel_event is not None and cancel_event.is_set():
            break

        tf = timeframe_map.get(sym, mt5.TIMEFRAME_M15)
        # 1 día de velas + ventana de 300 velas para inicializar indicadores
        day_bars = _default_history_bars_for_tf(tf, target_days=1)
        total_bars_request = max(350, day_bars + LIVE_ROLLING_WINDOW)

        daily_res = backtest_symbol(
            sym, strategy_name, tf,
            history_bars=total_bars_request,
            rolling_window=LIVE_ROLLING_WINDOW,
            cancel_event=cancel_event
        )

        if daily_res.get("error") or daily_res.get("cancelled"):
            continue

        key = _cache_key(sym, strategy_name, tf)
        existing = cache.get(key)

        if existing:
            # Fusión acumulativa de métricas
            prev_trades = existing.get("trades", 0)
            prev_wins = existing.get("wins", 0)
            prev_losses = existing.get("losses", 0)
            prev_avg_r = existing.get("avg_r", 0.0)
            prev_samples = existing.get("sample_trades", [])

            new_trades = daily_res.get("trades", 0)
            new_wins = daily_res.get("wins", 0)
            new_losses = daily_res.get("losses", 0)
            new_avg_r = daily_res.get("avg_r", 0.0)
            new_samples = daily_res.get("sample_trades", [])

            total_trades = prev_trades + new_trades
            total_wins = prev_wins + new_wins
            total_losses = prev_losses + new_losses

            if total_trades > 0:
                combined_win_rate = round((total_wins / total_trades) * 100.0, 1)
                combined_avg_r = round(((prev_avg_r * prev_trades) + (new_avg_r * new_trades)) / total_trades, 2)
                combined_confidence = round(wilson_lower_bound(total_wins, total_trades), 1)
            else:
                combined_win_rate = 0.0
                combined_avg_r = 0.0
                combined_confidence = 0.0

            merged_samples = (prev_samples + new_samples)[-20:]

            merged_record = {
                "symbol": sym,
                "resolved_symbol": daily_res.get("resolved_symbol", sym),
                "strategy": strategy_name,
                "timeframe": tf,
                "bars_analyzed": existing.get("bars_analyzed", 0) + daily_res.get("bars_analyzed", 0),
                "trades": total_trades,
                "wins": total_wins,
                "losses": total_losses,
                "win_rate": combined_win_rate,
                "win_rate_confidence": combined_confidence,
                "avg_r": combined_avg_r,
                "cancelled": False,
                "updated_at": time.time(),
                "sample_trades": merged_samples,
                "last_daily_incremental": time.time(),
            }
            cache[key] = merged_record
            updated_records.append(merged_record)
        else:
            cache[key] = daily_res
            updated_records.append(daily_res)

    if updated_records:
        _save_results_cache(cache)

    return updated_records

