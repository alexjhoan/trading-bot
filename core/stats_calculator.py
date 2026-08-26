import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List


def get_broker_server_time() -> datetime:
    """
    Obtiene la hora actual del servidor del broker en MT5 para sincronizar
    exactamente los filtros de 'Día' y 'Semana' sin desfases de zona horaria local.
    """
    try:
        # Intentar obtener la hora del último tick en algún símbolo visible
        symbols = mt5.symbols_get()
        if symbols:
            for s in symbols[:5]:
                tick = mt5.symbol_info_tick(s.name)
                if tick and tick.time > 0:
                    return datetime.fromtimestamp(tick.time)
    except Exception:
        pass
    return datetime.now()


def calculate_closed_trades_stats(period: str = "Día", time_mode: str = "Hora Broker") -> Dict[str, Any]:
    """
    Calcula con precisión exacta las estadísticas de posiciones cerradas en MT5:
    - period: 'Día' | 'Semana'
    - time_mode: 'Hora Broker' | 'Hora Local' (o 'Broker' | 'Local')
    1. Agrupa por 'position_id' para sumar ganancias, comisiones totales (entrada y salida) y swaps.
    2. Usa la hora del broker o la hora local según la preferencia seleccionada.
    3. Excluye depósitos, retiros, créditos o ajustes de balance.
    """
    is_broker_time = "broker" in str(time_mode).strip().lower()
    ref_time = get_broker_server_time() if is_broker_time else datetime.now()
    is_day = str(period).strip().lower() in ("día", "dia", "day", "hoy", "today")
    time_badge = "Broker" if is_broker_time else "Local"

    if is_day:
        start_dt = datetime(ref_time.year, ref_time.month, ref_time.day, 0, 0, 0)
        period_label = f"Hoy ({ref_time.strftime('%d/%m')} [{time_badge}])"
    else:
        # Lunes de la semana actual a las 00:00:00
        start_of_week = ref_time - timedelta(days=ref_time.weekday())
        start_dt = datetime(start_of_week.year, start_of_week.month, start_of_week.day, 0, 0, 0)
        period_label = f"Semana #{ref_time.strftime('%V')} (Desde {start_of_week.strftime('%d/%m')} [{time_badge}])"

    end_dt = ref_time + timedelta(days=1)

    win_count = 0
    loss_count = 0
    be_count = 0
    win_total = 0.0
    loss_total = 0.0
    net_total = 0.0

    try:
        # Solicitar historial de transacciones (deals) en el rango horario
        deals = mt5.history_deals_get(start_dt, end_dt)
        if deals:
            # Agrupar todos los deals por position_id para calcular el PnL neto real de cada posición
            positions_map: Dict[int, Dict[str, Any]] = {}

            for d in deals:
                deal_type = getattr(d, "type", -1)
                pos_id = getattr(d, "position_id", 0)

                # Filtrar solo transacciones de trading BUY / SELL (ignora balance, créditos, etc.)
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
                    # DEAL_ENTRY_OUT (1) o DEAL_ENTRY_OUT_BY (3) o DEAL_ENTRY_INOUT (2)
                    if entry_type in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT, 1, 3, 2):
                        positions_map[pos_id]["has_exit"] = True
                        positions_map[pos_id]["close_time"] = getattr(d, "time", positions_map[pos_id]["close_time"])

                    positions_map[pos_id]["profit"] += float(getattr(d, "profit", 0.0))
                    positions_map[pos_id]["commission"] += float(getattr(d, "commission", 0.0))
                    positions_map[pos_id]["swap"] += float(getattr(d, "swap", 0.0))
                    positions_map[pos_id]["fee"] += float(getattr(d, "fee", 0.0))

            # Solo contabilizar posiciones que efectivamente hayan tenido deal de salida (cerradas)
            for pos_id, data in positions_map.items():
                if data["has_exit"]:
                    # PnL neto = Beneficio de precio + Comisiones + Swap + Fee
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

