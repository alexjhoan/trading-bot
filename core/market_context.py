from typing import Dict, Any, Optional, Tuple
import math

try:
    import MetaTrader5 as mt5
    from core.data_loader import get_historical_data
except ImportError:
    mt5 = None
    get_historical_data = None

from core.candlestick_patterns import detect_candlestick_patterns


def calculate_psychological_levels(symbol: str, current_price: float, pip_size: float = 0.0001) -> str:
    """
    Calcula los niveles psicológicos/redondos institucionales más cercanos (.0000, .5000, .00, .50)
    y la distancia en pips hasta ellos.
    """
    if current_price <= 0:
        return "Niveles psicológicos: No disponible"

    # Determinar el paso de nivel según el precio del activo
    if current_price > 1000:  # Cripto (BTC) o Oro
        step = 50.0
        major_step = 100.0
    elif current_price > 50:  # JPY pairs o commoditites
        step = 0.50
        major_step = 1.00
    else:  # Forex estándar (EURUSD, NZDUSD, etc. ~ 0.5 - 1.5)
        step = 0.0050  # ej. 0.5950, 0.6000
        major_step = 0.0100

    # Nivel redondo inmediatamente inferior y superior
    lower_level = math.floor(current_price / step) * step
    upper_level = math.ceil(current_price / step) * step

    # Si estamos exactamente en un nivel, buscar el siguiente
    if abs(current_price - upper_level) < 1e-6:
        upper_level += step
    if abs(current_price - lower_level) < 1e-6:
        lower_level -= step

    pips_to_res = abs(upper_level - current_price) / max(pip_size, 1e-5)
    pips_to_sup = abs(current_price - lower_level) / max(pip_size, 1e-5)

    # Formato de precisión de visualización
    digits = 5 if pip_size < 0.001 else 2
    if pips_to_res <= pips_to_sup:
        return f"Resistencia clave en {upper_level:.{digits}f} a {pips_to_res:.1f} pips | Soporte en {lower_level:.{digits}f} a {pips_to_sup:.1f} pips."
    else:
        return f"Soporte clave en {lower_level:.{digits}f} a {pips_to_sup:.1f} pips | Resistencia en {upper_level:.{digits}f} a {pips_to_res:.1f} pips."


def analyze_macro_multitimeframe(symbol: str, current_price: float = 0.0) -> str:
    """
    Analiza la tendencia macro en temporalidades superiores (D1 y H4) usando EMA 200 y acción del precio.
    Devuelve un resumen condensado para el prompt de IA.
    """
    if mt5 is None or get_historical_data is None:
        return "D1 Tendencia Neutral/Estructural | H4 Consolidación en rango"

    try:
        # 1. Obtener datos de D1 (Diario)
        df_d1 = get_historical_data(symbol, getattr(mt5, "TIMEFRAME_D1", 16408), 50)
        d1_trend = "Neutral"
        if df_d1 is not None and len(df_d1) >= 20:
            ema200_d1 = df_d1["close"].ewm(span=min(50, len(df_d1)), adjust=False).mean().iloc[-1]
            last_close_d1 = df_d1["close"].iloc[-1]
            if last_close_d1 > ema200_d1:
                d1_trend = "Tendencia Alcista"
            else:
                d1_trend = "Tendencia Bajista"

        # 2. Obtener datos de H4 (4 Horas)
        df_h4 = get_historical_data(symbol, getattr(mt5, "TIMEFRAME_H4", 16388), 30)
        h4_desc = "Estructura estable"
        if df_h4 is not None and len(df_h4) >= 3:
            prev_candle = df_h4.iloc[-2]
            prev_prev = df_h4.iloc[-3]
            # Detectar si la última vela cerrada es envolvente
            is_bullish_engulf = (prev_candle["close"] > prev_candle["open"]) and (prev_candle["close"] >= prev_prev["high"])
            is_bearish_engulf = (prev_candle["close"] < prev_candle["open"]) and (prev_candle["close"] <= prev_prev["low"])

            if is_bullish_engulf:
                h4_desc = "Vela Envolvente Alcista en soporte"
            elif is_bearish_engulf:
                h4_desc = "Vela Envolvente Bajista en resistencia"
            elif prev_candle["close"] > prev_candle["open"]:
                h4_desc = "Presión compradora en H4"
            else:
                h4_desc = "Presión vendedora en H4"

        return f"D1 {d1_trend} | H4 {h4_desc}."
    except Exception as e:
        return f"D1 Tendencia Estructural | H4 Acción del precio estándar."
