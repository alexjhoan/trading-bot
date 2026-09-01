import time
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple

from core.ai_memory import AIMemoryManager


def get_broker_server_time_and_offset() -> Tuple[datetime, float]:
    """
    Obtiene la hora actual del servidor del broker en MT5 y calcula
    la diferencia exacta (offset en segundos) respecto a la hora local.
    """
    try:
        symbols = mt5.symbols_get()
        if symbols:
            for s in symbols[:10]:
                tick = mt5.symbol_info_tick(s.name)
                if tick and tick.time > 0:
                    broker_dt = datetime.fromtimestamp(tick.time)
                    offset_sec = tick.time - time.time()
                    return broker_dt, offset_sec
        # Intento con rates de símbolo común
        for sym_cand in ["EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "Volatility 75 Index"]:
            rates = mt5.copy_rates_from_pos(sym_cand, mt5.TIMEFRAME_M1, 0, 1)
            if rates is not None and len(rates) > 0:
                broker_ts = int(rates[0]['time'])
                broker_dt = datetime.fromtimestamp(broker_ts)
                offset_sec = broker_ts - time.time()
                return broker_dt, offset_sec
    except Exception:
        pass

    return datetime.now(), 0.0


def calculate_closed_trades_stats(period: str = "Día", time_mode: str = "Hora Broker") -> Dict[str, Any]:
    """
    Calcula con precisión matemática exacta las estadísticas de posiciones cerradas en MT5:
    - period: 'Día' | 'Semana'
    - time_mode: 'Hora Broker' | 'Hora Local' (o 'Broker' | 'Local')
    1. Agrupa por 'position_id' para sumar ganancias netas, comisiones totales (in/out) y swaps.
    2. Convierte y filtra las operaciones exactamente desde la medianoche (00:00:00) del horario elegido.
    3. Excluye depósitos, retiros, créditos o ajustes de balance.
    """
    is_broker_time = "broker" in str(time_mode).strip().lower()
    broker_now, broker_offset = get_broker_server_time_and_offset()
    local_now = datetime.now()
    is_day = str(period).strip().lower() in ("día", "dia", "day", "hoy", "today")

    if is_broker_time:
        ref_time = broker_now
        time_badge = f"Broker {broker_now.strftime('%H:%M')}"
        if is_day:
            filter_start_dt = datetime(ref_time.year, ref_time.month, ref_time.day, 0, 0, 0)
            period_label = f"Hoy ({ref_time.strftime('%d/%m')} [{time_badge}])"
        else:
            start_of_week = ref_time - timedelta(days=ref_time.weekday())
            filter_start_dt = datetime(start_of_week.year, start_of_week.month, start_of_week.day, 0, 0, 0)
            period_label = f"Semana #{ref_time.strftime('%V')} (Desde {start_of_week.strftime('%d/%m')} [{time_badge}])"

        # En MT5 history_deals_get usa la escala del broker
        query_start = filter_start_dt - timedelta(hours=2)
        query_end = broker_now + timedelta(days=1)
        filter_start_timestamp = filter_start_dt.timestamp()
    else:
        ref_time = local_now
        time_badge = f"Local {local_now.strftime('%H:%M')}"
        if is_day:
            filter_start_dt = datetime(ref_time.year, ref_time.month, ref_time.day, 0, 0, 0)
            period_label = f"Hoy ({ref_time.strftime('%d/%m')} [{time_badge}])"
        else:
            start_of_week = ref_time - timedelta(days=ref_time.weekday())
            filter_start_dt = datetime(start_of_week.year, start_of_week.month, start_of_week.day, 0, 0, 0)
            period_label = f"Semana #{ref_time.strftime('%V')} (Desde {start_of_week.strftime('%d/%m')} [{time_badge}])"

        # Convertir medianoche local al equivalente en hora de broker para consultar MT5
        query_start = filter_start_dt + timedelta(seconds=broker_offset) - timedelta(hours=2)
        query_end = local_now + timedelta(seconds=broker_offset) + timedelta(days=1)
        # La marca de tiempo límite en la escala del deal
        filter_start_timestamp = (filter_start_dt + timedelta(seconds=broker_offset)).timestamp()

    win_count = 0
    loss_count = 0
    be_count = 0
    win_total = 0.0
    loss_total = 0.0
    net_total = 0.0

    try:
        deals = mt5.history_deals_get(query_start, query_end)
        if deals:
            positions_map: Dict[int, Dict[str, Any]] = {}

            for d in deals:
                deal_type = getattr(d, "type", -1)
                pos_id = getattr(d, "position_id", 0)

                # Filtrar solo transacciones de trading BUY / SELL (ignora balance, depósitos, retiros)
                if deal_type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL) and pos_id > 0:
                    if pos_id not in positions_map:
                        positions_map[pos_id] = {
                            "profit": 0.0,
                            "commission": 0.0,
                            "swap": 0.0,
                            "fee": 0.0,
                            "has_exit": False,
                            "symbol": getattr(d, "symbol", ""),
                            "close_time": getattr(d, "time", 0)
                        }

                    entry_type = getattr(d, "entry", -1)
                    # DEAL_ENTRY_OUT (1), DEAL_ENTRY_OUT_BY (3), DEAL_ENTRY_INOUT (2)
                    if entry_type in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT, 1, 3, 2):
                        positions_map[pos_id]["has_exit"] = True
                        positions_map[pos_id]["close_time"] = getattr(d, "time", positions_map[pos_id]["close_time"])

                    positions_map[pos_id]["profit"] += float(getattr(d, "profit", 0.0))
                    positions_map[pos_id]["commission"] += float(getattr(d, "commission", 0.0))
                    positions_map[pos_id]["swap"] += float(getattr(d, "swap", 0.0))
                    positions_map[pos_id]["fee"] += float(getattr(d, "fee", 0.0))

            # Contabilizar únicamente posiciones cerradas que hayan finalizado dentro del período seleccionado
            for pos_id, data in positions_map.items():
                if data["has_exit"]:
                    close_ts = data["close_time"]
                    # Validar si el cierre ocurrió después del inicio del período seleccionado
                    if close_ts >= filter_start_timestamp:
                        net_pos_profit = data["profit"] + data["commission"] + data["swap"] + data["fee"]
                        net_total += net_pos_profit

                        if net_pos_profit > 0.0001:
                            win_count += 1
                            win_total += net_pos_profit
                        elif net_pos_profit < -0.0001:
                            loss_count += 1
                            loss_total += net_pos_profit
                        else:
                            be_count += 1
    except Exception as e:
        print(f"[DEBUG STATS] Error calculando estadísticas de MT5: {e}")

    total_ops = win_count + loss_count + be_count
    win_rate = (win_count / total_ops * 100.0) if total_ops > 0 else 0.0

    return {
        "period": "Día" if is_day else "Semana",
        "period_label": period_label,
        "win_count": win_count,
        "win_total": win_total,
        "loss_count": loss_count,
        "loss_total": loss_total,
        "net_total": net_total,
        "total_ops": total_ops,
        "win_rate": win_rate
    }


def wilson_lower_bound(wins: int, n: int, confidence_z: float = 1.28) -> float:
    """
    Límite inferior del intervalo de Wilson para una tasa de acierto (wins/n), en porcentaje
    (0-100). Penaliza muestras chicas: 1 ganada de 1 (100% crudo) da un límite inferior bajo,
    mientras que 8 ganadas de 10 (80% crudo) da un límite inferior más alto y confiable.
    confidence_z=1.28 ≈ 80% de confianza, razonable dado el tamaño típico de muestra de este bot.
    """
    if n <= 0:
        return 0.0
    p = wins / n
    z = confidence_z
    denom = 1 + (z ** 2) / n
    center = p + (z ** 2) / (2 * n)
    margin = z * ((p * (1 - p) + (z ** 2) / (4 * n)) / n) ** 0.5
    return max(0.0, (center - margin) / denom) * 100.0


def rank_symbols_by_performance(min_trades: int = 5, confidence_z: float = 1.28) -> List[Dict[str, Any]]:
    """
    Rankea los símbolos según su desempeño histórico REAL registrado en trade_memory.json
    (no según indicadores predictivos nuevos). Para no sobrevalorar símbolos con pocas
    operaciones (ej. 1 ganada de 1 = 100% no es una muestra confiable), el Win Rate ajustado
    usa el límite inferior del intervalo de Wilson (confidence_z=1.28 ≈ 80% de confianza,
    razonable dado el tamaño típico de muestra por par en este bot).

    El orden final es por Expectativa (R promedio), que es lo que realmente determina si un
    par es rentable a largo plazo (un símbolo puede tener Win Rate bajo pero ser rentable si
    sus ganancias son mucho mayores que sus pérdidas, y viceversa).
    """
    memory = AIMemoryManager().get_all_memory()

    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for trade in memory:
        outcome = trade.get("outcome", {})
        if outcome.get("status") != "CLOSED" or outcome.get("result") not in ("WIN", "LOSS"):
            continue
        symbol = trade.get("symbol", "?")
        by_symbol.setdefault(symbol, []).append(outcome)

    ranking: List[Dict[str, Any]] = []
    for symbol, outcomes in by_symbol.items():
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o.get("result") == "WIN")
        win_rate = (wins / n * 100.0) if n > 0 else 0.0
        avg_r = sum(float(o.get("pnl_r", 0.0)) for o in outcomes) / n if n > 0 else 0.0
        total_usd = sum(float(o.get("pnl_usd", 0.0)) for o in outcomes)
        win_rate_confidence = wilson_lower_bound(wins, n, confidence_z)

        ranking.append({
            "symbol": symbol,
            "trades": n,
            "wins": wins,
            "losses": n - wins,
            "win_rate": round(win_rate, 1),
            "win_rate_confidence": round(win_rate_confidence, 1),
            "avg_r": round(avg_r, 2),
            "total_usd": round(total_usd, 2),
            "meets_min_sample": n >= min_trades,
        })

    ranking.sort(key=lambda r: (r["meets_min_sample"], r["avg_r"]), reverse=True)
    return ranking


def rank_strategies_by_performance(min_trades: int = 15, confidence_z: float = 1.28) -> List[Dict[str, Any]]:
    """
    Igual que rank_symbols_by_performance, pero agrupando por estrategia (context.strategy
    en trade_memory.json) en vez de por símbolo. Pensado para comparar ForexStrategy vs.
    SimpleTrendStrategy (u otras) en el mismo plan de pruebas, sin mezclar sus resultados.
    """
    memory = AIMemoryManager().get_all_memory()

    by_strategy: Dict[str, List[Dict[str, Any]]] = {}
    for trade in memory:
        outcome = trade.get("outcome", {})
        if outcome.get("status") != "CLOSED" or outcome.get("result") not in ("WIN", "LOSS"):
            continue
        strategy_name = trade.get("context", {}).get("strategy", "?")
        by_strategy.setdefault(strategy_name, []).append(outcome)

    ranking: List[Dict[str, Any]] = []
    for strategy_name, outcomes in by_strategy.items():
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o.get("result") == "WIN")
        win_rate = (wins / n * 100.0) if n > 0 else 0.0
        avg_r = sum(float(o.get("pnl_r", 0.0)) for o in outcomes) / n if n > 0 else 0.0
        total_usd = sum(float(o.get("pnl_usd", 0.0)) for o in outcomes)
        win_rate_confidence = wilson_lower_bound(wins, n, confidence_z)

        ranking.append({
            "strategy": strategy_name,
            "trades": n,
            "wins": wins,
            "losses": n - wins,
            "win_rate": round(win_rate, 1),
            "win_rate_confidence": round(win_rate_confidence, 1),
            "avg_r": round(avg_r, 2),
            "total_usd": round(total_usd, 2),
            "meets_min_sample": n >= min_trades,
        })

    ranking.sort(key=lambda r: (r["meets_min_sample"], r["avg_r"]), reverse=True)
    return ranking

