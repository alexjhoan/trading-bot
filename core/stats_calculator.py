import time
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple


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


def get_broker_server_time() -> datetime:
    """Retorna la hora del servidor del broker."""
    b_time, _ = get_broker_server_time_and_offset()
    return b_time


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

