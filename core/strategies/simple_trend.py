from typing import Optional, Dict, Any, Callable
from datetime import datetime
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
from config import StrategyConfig
from .base_strategy import BaseStrategy

# =============================================================================
# PARÁMETROS AJUSTABLES — cambia estos valores para experimentar sin tocar la
# lógica de abajo. Todos son solo los valores POR DEFECTO (se pueden sobreescribir
# al crear la estrategia, ej. create_strategy_instance("simple_trend", rsi_period=7)).
# =============================================================================

# EMA de tendencia: define el sesgo (alcista si el precio está sobre la EMA, bajista si
# está debajo). Período más corto = más sensible/reactivo pero con más señales falsas;
# más largo = tendencia más "macro" y más lenta a cambiar.
EMA_PERIOD = 100

# Buffer de tolerancia para la EMA, como fracción del ATR actual. Permite considerar
# "tendencia alcista/bajista" aunque el precio esté ligeramente del otro lado de la EMA
# (no estrictamente cruzada) — captura entradas en el límite que de otro modo se perderían.
# Hay dos valores separados (misma idea que en ForexStrategy): el de ENTRADA es más
# estricto que el de INVALIDACIÓN, para dejar margen real entre "entrar" y "que la posición
# se invalide casi de inmediato" por la misma fluctuación menor cerca de la EMA.
EMA_ENTRY_BUFFER_ATR_MULT = 0.15        # 0.0 = sin margen (cruce estricto, comportamiento original)
EMA_INVALIDATION_BUFFER_ATR_MULT = 0.30  # más ancho que el de entrada a propósito

# RSI (oscilador): mide sobrecompra/sobreventa. Período más corto = más reactivo, cruza
# los niveles con más frecuencia (más señales, algo más ruidosas); más largo = más suave,
# señales más espaciadas pero más "confirmadas".
RSI_PERIOD = 9

# Niveles de sobreventa/sobrecompra del RSI. La señal dispara cuando el RSI CRUZA de
# vuelta estos niveles (antes dentro de la zona, ahora fuera) — no cuando simplemente los
# toca. Más cerca de 50 = más señales pero de retrocesos más superficiales; más cerca de
# 0/100 = menos señales pero de retrocesos más profundos/significativos.
RSI_OVERSOLD = 40.0
RSI_OVERBOUGHT = 60.0

# ATR: mide volatilidad, no genera señal — solo dimensiona el SL/TP dinámico y los
# buffers de EMA de arriba.
ATR_PERIOD = 14

# Multiplicadores de SL/TP sobre el ATR actual al momento de la entrada
# (Riesgo:Beneficio resultante = ATR_TP_MULT / ATR_SL_MULT, default 1:2).
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0

# Respaldo estático en pips si el ATR no está disponible (ej. datos insuficientes).
STATIC_SL_PIPS = 20.0
STATIC_TP_PIPS = 40.0

# Ventana (en velas) para soporte/resistencia informativos (máximo/mínimo simple).
# No se usan como condición de entrada, solo para poder graficarlos.
SR_LOOKBACK = 50


class SimpleTrendStrategy(BaseStrategy):
    """
    Estrategia mínima de comparación: Tendencia (EMA) + Oscilador (RSI) únicamente.
    Sin Fibonacci, sin patrones de vela, sin ADX, sin confirmación multi-timeframe,
    sin reentradas ni filtro de sobreextensión.

    Existe para comparar contra ForexStrategy (que combina ~10 indicadores/filtros) y medir
    si reducir los grados de libertad (menor riesgo de sobreajuste) da mejor tasa de acierto
    real en cuenta demo. Ver core/strategies/SIMPLE_TREND_STRATEGY.md para el plan de pruebas.

    Entrada: precio sobre/bajo la EMA de tendencia (sesgo, con buffer de tolerancia) + RSI
    cruzando de vuelta desde sobreventa/sobrecompra (confirmación de rebote real, no solo
    "tocar" el nivel). Salida: invalidación si el precio cruza la EMA en contra (buffer más
    ancho que el de entrada), más trailing stop por ATR. Parámetros ajustables al inicio de
    este archivo — ver core/strategies/SIMPLE_TREND_STRATEGY.md para el detalle de cada uno.
    """

    name: str = "simple_trend"
    description: str = "Tendencia EMA + RSI (oscilador) — estrategia mínima de comparación (2 indicadores)"

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        ema_period: int = EMA_PERIOD,
        rsi_period: int = RSI_PERIOD,
        atr_period: int = ATR_PERIOD,
        rsi_oversold: float = RSI_OVERSOLD,
        rsi_overbought: float = RSI_OVERBOUGHT,
        sr_lookback: int = SR_LOOKBACK,
        logger: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(config=config, symbol=symbol, logger=logger, **kwargs)
        self.ema_period: int = ema_period
        self.rsi_period: int = rsi_period
        self.atr_period: int = atr_period
        self.rsi_oversold: float = rsi_oversold
        self.rsi_overbought: float = rsi_overbought
        self.sr_lookback: int = sr_lookback  # Ventana de velas para soporte/resistencia (máx/mín simple, solo informativo)
        self.ema_entry_buffer_atr_mult: float = kwargs.get("ema_entry_buffer_atr_mult", EMA_ENTRY_BUFFER_ATR_MULT)
        self.ema_invalidation_buffer_atr_mult: float = kwargs.get("ema_invalidation_buffer_atr_mult", EMA_INVALIDATION_BUFFER_ATR_MULT)

        # Gestión de riesgo por ATR con respaldo estático (mismo esquema que ForexStrategy)
        self.atr_sl_mult: float = kwargs.get("atr_sl_mult", ATR_SL_MULT)
        self.atr_tp_mult: float = kwargs.get("atr_tp_mult", ATR_TP_MULT)
        self.static_sl_pips: float = kwargs.get("static_sl_pips", STATIC_SL_PIPS)
        self.static_tp_pips: float = kwargs.get("static_tp_pips", STATIC_TP_PIPS)

        # Requeridos por bot_worker.py (acceso directo, no opcional)
        self.use_correlation_filter: bool = getattr(self.config, "use_correlation_filter", kwargs.get("use_correlation_filter", True))
        self.correlation_threshold: float = getattr(self.config, "correlation_threshold", kwargs.get("correlation_threshold", 0.70))
        self.correlation_window: int = getattr(self.config, "correlation_window", kwargs.get("correlation_window", 50))

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula EMA de tendencia, RSI, ATR (gestión de riesgo) y soporte/resistencia
        (máximo/mínimo de las últimas sr_lookback velas — puramente informativo, no se usa
        como condición de entrada, solo para poder graficarlos)."""
        df = df.copy()
        df["ema_trend"] = ta.ema(close=df["close"], length=self.ema_period)
        df["rsi"] = ta.rsi(close=df["close"], length=self.rsi_period)
        df["atr"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=self.atr_period)
        df["resistance"] = df["high"].rolling(window=self.sr_lookback, min_periods=1).max()
        df["support"] = df["low"].rolling(window=self.sr_lookback, min_periods=1).min()
        return df

    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Evalúa las reglas de trading para NUEVAS ENTRADAS: Tendencia EMA + RSI girando en zona extrema."""
        min_bars = max(self.ema_period, self.rsi_period, self.atr_period) + 5
        if df is None or len(df) < min_bars:
            return {
                "signal": "HOLD", "support": 0.0, "resistance": 0.0, "atr": 0.0,
                "score": 0, "sl": 0.0, "tp": 0.0, "reason": "Insuficiente historial de datos"
            }

        df_analyzed = self.calculate_indicators(df)
        curr_candle = df_analyzed.iloc[-2]
        prev_candle = df_analyzed.iloc[-3] if len(df_analyzed) >= 3 else curr_candle

        curr_close = float(curr_candle["close"])
        support = float(curr_candle.get("support", curr_close))
        resistance = float(curr_candle.get("resistance", curr_close))

        now_dt = datetime.now()
        market_open, open_reason = self.config.is_market_open(self.symbol, now_dt)
        if not market_open:
            return {
                "signal": "HOLD", "support": support, "resistance": resistance,
                "atr": float(curr_candle.get("atr", 0.0)), "score": 0, "sl": 0.0, "tp": 0.0,
                "reason": open_reason
            }

        ema_trend = float(curr_candle.get("ema_trend", curr_close))
        current_atr = float(curr_candle.get("atr", 0.0))
        curr_rsi = float(curr_candle.get("rsi", 50.0))
        prev_rsi = float(prev_candle.get("rsi", 50.0))

        # Buffer de tolerancia (más estricto que el de invalidación, ver analyze_open_position):
        # permite considerar "tendencia" aunque el precio esté ligeramente del otro lado de la
        # EMA, para no perder entradas en el límite.
        ema_entry_buffer = (current_atr * self.ema_entry_buffer_atr_mult) if current_atr > 0 else 0.0
        is_uptrend = curr_close > (ema_trend - ema_entry_buffer)
        is_downtrend = curr_close < (ema_trend + ema_entry_buffer)

        # Condición 1 (Tendencia) + Condición 2 (Oscilador CRUZANDO de vuelta desde la zona extrema).
        # Antes exigía que el RSI siguiera <= umbral Y ya estuviera subiendo en la misma vela — eso
        # requiere acertar la vela exacta del piso, que casi nunca ocurre (el RSI suele saltar del
        # umbral hacia afuera en una sola vela). El cruce confirmado (antes dentro de la zona, ahora
        # fuera) es la construcción estándar y dispara de forma mucho más confiable sin perder calidad
        # de señal — sigue exigiendo el mismo evento real (rebote desde sobreventa/sobrecompra).
        buy_signal = is_uptrend and (prev_rsi <= self.rsi_oversold) and (curr_rsi > self.rsi_oversold)
        sell_signal = is_downtrend and (prev_rsi >= self.rsi_overbought) and (curr_rsi < self.rsi_overbought)

        final_signal = "BUY" if buy_signal else ("SELL" if sell_signal else "HOLD")

        sl_price = 0.0
        tp_price = 0.0
        if final_signal != "HOLD":
            point = 0.0001 if "JPY" not in self.symbol else 0.01
            if current_atr > 0:
                sl_dist = current_atr * self.atr_sl_mult
                tp_dist = current_atr * self.atr_tp_mult
            else:
                sl_dist = self.static_sl_pips * point
                tp_dist = self.static_tp_pips * point

            if final_signal == "BUY":
                sl_price = curr_close - sl_dist
                tp_price = curr_close + tp_dist
            else:
                sl_price = curr_close + sl_dist
                tp_price = curr_close - tp_dist

        if final_signal != "HOLD":
            reason = (
                f"[SimpleTrend] {final_signal}: Tendencia EMA{self.ema_period} "
                f"({'alcista' if is_uptrend else 'bajista'}) + RSI{self.rsi_period} cruzó de vuelta desde "
                f"{'sobreventa' if final_signal == 'BUY' else 'sobrecompra'} ({prev_rsi:.1f} -> {curr_rsi:.1f})"
            )
        else:
            reason = (
                f"[SimpleTrend] Sin señal: Tendencia {'alcista' if is_uptrend else ('bajista' if is_downtrend else 'plana')} "
                f"| RSI {curr_rsi:.1f} (requiere cruce de vuelta desde <= {self.rsi_oversold:.0f} o desde >= {self.rsi_overbought:.0f})"
            )

        return {
            "signal": final_signal,
            "support": support,
            "resistance": resistance,
            "atr": current_atr,
            "score": 2 if final_signal != "HOLD" else 0,
            "sl": sl_price,
            "tp": tp_price,
            "reason": reason
        }

    def analyze_open_position(self, df: pd.DataFrame, position: Any) -> Dict[str, Any]:
        """Gestión mínima de posición: invalidación por cruce de EMA + trailing stop por ATR."""
        min_bars = max(self.ema_period, self.rsi_period, self.atr_period) + 5
        if df is None or len(df) < min_bars:
            return {"action": "HOLD", "reason": "Insuficiente historial para análisis de posición"}

        df_analyzed = self.calculate_indicators(df)
        curr_candle = df_analyzed.iloc[-2]
        curr_close = float(curr_candle["close"])
        curr_low = float(curr_candle["low"])
        curr_high = float(curr_candle["high"])
        ema_trend = float(curr_candle.get("ema_trend", curr_close))
        current_atr = float(curr_candle.get("atr", 0.0))

        is_buy = position.type == mt5.POSITION_TYPE_BUY
        pos_type_str = "BUY" if is_buy else "SELL"
        price_open = float(position.price_open)
        current_sl = float(position.sl)
        current_tp = float(position.tp)

        # A. Invalidación por cruce de la EMA de tendencia en contra de la posición, con un
        # buffer más ancho que el de entrada (misma idea que ForexStrategy) para no cerrar la
        # posición por una fluctuación menor justo después de entrar cerca de la EMA.
        ema_invalidation_buffer = (current_atr * self.ema_invalidation_buffer_atr_mult) if current_atr > 0 else 0.0
        if is_buy and curr_close < (ema_trend - ema_invalidation_buffer):
            return {
                "action": "EARLY_CLOSE",
                "reason": f"Cierre por invalidación de tendencia: Precio ({curr_close:.5f}) cruzó bajo la EMA{self.ema_period} ({ema_trend:.5f})",
                "close_reason": "SimpleTrend_Invalidacion_EMA"
            }
        if (not is_buy) and curr_close > (ema_trend + ema_invalidation_buffer):
            return {
                "action": "EARLY_CLOSE",
                "reason": f"Cierre por invalidación de tendencia: Precio ({curr_close:.5f}) cruzó sobre la EMA{self.ema_period} ({ema_trend:.5f})",
                "close_reason": "SimpleTrend_Invalidacion_EMA"
            }

        # B. Trailing Stop simple por ATR
        suggested_sl = current_sl
        needs_sl_update = False

        if current_atr > 0:
            trailing_offset = current_atr * max(2.0, self.atr_sl_mult)
            activation_buffer = current_atr * 1.0

            if is_buy:
                if curr_close >= (price_open + activation_buffer):
                    new_trailing_sl = curr_low - trailing_offset
                    if new_trailing_sl > current_sl and new_trailing_sl > price_open:
                        suggested_sl = new_trailing_sl
                        needs_sl_update = True
            else:
                if curr_close <= (price_open - activation_buffer):
                    new_trailing_sl = curr_high + trailing_offset
                    if (current_sl == 0.0 or new_trailing_sl < current_sl) and new_trailing_sl < price_open:
                        suggested_sl = new_trailing_sl
                        needs_sl_update = True

        if needs_sl_update:
            return {
                "action": "MODIFY_SLTP",
                "suggested_sl": suggested_sl,
                "suggested_tp": current_tp,
                "reason": f"Trailing Stop SimpleTrend #{position.ticket} ({pos_type_str}) ➔ SL: {suggested_sl:.5f}"
            }

        return {
            "action": "MONITOR",
            "current_sl": current_sl,
            "current_tp": current_tp,
            "reason": f"Posición SimpleTrend {pos_type_str} #{position.ticket} monitoreada"
        }
