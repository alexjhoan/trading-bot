from typing import Optional, Dict, Any, Callable
from datetime import datetime
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
from config import StrategyConfig
from .base_strategy import BaseStrategy


class SimpleTrendStrategy(BaseStrategy):
    """
    Estrategia mínima de comparación: Tendencia (EMA) + Oscilador (RSI) únicamente.
    Sin Fibonacci, sin patrones de vela, sin ADX, sin confirmación multi-timeframe,
    sin reentradas ni filtro de sobreextensión.

    Existe para comparar contra ForexStrategy (que combina ~10 indicadores/filtros) y medir
    si reducir los grados de libertad (menor riesgo de sobreajuste) da mejor tasa de acierto
    real en cuenta demo. Ver core/strategies/SIMPLE_TREND_STRATEGY.md para el plan de pruebas.

    Entrada: precio sobre/bajo la EMA de tendencia (sesgo) + RSI en sobreventa/sobrecompra
    girando de vuelta hacia la zona media (confirmación de rebote, no solo "tocar" el nivel).
    Salida: invalidación simple si el precio cruza la EMA en contra, más trailing stop por ATR.
    """

    name: str = "simple_trend"
    description: str = "Tendencia EMA + RSI (oscilador) — estrategia mínima de comparación (2 indicadores)"

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        ema_period: int = 100,
        rsi_period: int = 14,
        atr_period: int = 14,
        rsi_oversold: float = 40.0,
        rsi_overbought: float = 60.0,
        logger: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(config=config, symbol=symbol, logger=logger, **kwargs)
        self.ema_period: int = ema_period
        self.rsi_period: int = rsi_period
        self.atr_period: int = atr_period
        self.rsi_oversold: float = rsi_oversold
        self.rsi_overbought: float = rsi_overbought

        # Gestión de riesgo por ATR con respaldo estático (mismo esquema que ForexStrategy)
        self.atr_sl_mult: float = kwargs.get("atr_sl_mult", 1.5)
        self.atr_tp_mult: float = kwargs.get("atr_tp_mult", 3.0)
        self.static_sl_pips: float = kwargs.get("static_sl_pips", 20.0)
        self.static_tp_pips: float = kwargs.get("static_tp_pips", 40.0)

        # Requeridos por bot_worker.py (acceso directo, no opcional)
        self.use_correlation_filter: bool = getattr(self.config, "use_correlation_filter", kwargs.get("use_correlation_filter", True))
        self.correlation_threshold: float = getattr(self.config, "correlation_threshold", kwargs.get("correlation_threshold", 0.70))
        self.correlation_window: int = getattr(self.config, "correlation_window", kwargs.get("correlation_window", 50))

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula únicamente EMA de tendencia, RSI y ATR (gestión de riesgo)."""
        df = df.copy()
        df["ema_trend"] = ta.ema(close=df["close"], length=self.ema_period)
        df["rsi"] = ta.rsi(close=df["close"], length=self.rsi_period)
        df["atr"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=self.atr_period)
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

        now_dt = datetime.now()
        market_open, open_reason = self.config.is_market_open(self.symbol, now_dt)
        if not market_open:
            return {
                "signal": "HOLD", "support": 0.0, "resistance": 0.0,
                "atr": float(curr_candle.get("atr", 0.0)), "score": 0, "sl": 0.0, "tp": 0.0,
                "reason": open_reason
            }

        curr_close = float(curr_candle["close"])
        ema_trend = float(curr_candle.get("ema_trend", curr_close))
        current_atr = float(curr_candle.get("atr", 0.0))
        curr_rsi = float(curr_candle.get("rsi", 50.0))
        prev_rsi = float(prev_candle.get("rsi", 50.0))

        is_uptrend = curr_close > ema_trend
        is_downtrend = curr_close < ema_trend

        # Condición 1 (Tendencia) + Condición 2 (Oscilador girando, no solo tocando el extremo)
        buy_signal = is_uptrend and (curr_rsi <= self.rsi_oversold) and (curr_rsi > prev_rsi)
        sell_signal = is_downtrend and (curr_rsi >= self.rsi_overbought) and (curr_rsi < prev_rsi)

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
                f"({'alcista' if is_uptrend else 'bajista'}) + RSI{self.rsi_period} girando desde "
                f"{'sobreventa' if final_signal == 'BUY' else 'sobrecompra'} ({prev_rsi:.1f} -> {curr_rsi:.1f})"
            )
        else:
            reason = (
                f"[SimpleTrend] Sin señal: Tendencia {'alcista' if is_uptrend else ('bajista' if is_downtrend else 'plana')} "
                f"| RSI {curr_rsi:.1f} (requiere <= {self.rsi_oversold:.0f} o >= {self.rsi_overbought:.0f} y girando)"
            )

        return {
            "signal": final_signal,
            "support": 0.0,
            "resistance": 0.0,
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

        # A. Invalidación simple: el precio cruza la EMA de tendencia en contra de la posición
        if is_buy and curr_close < ema_trend:
            return {
                "action": "EARLY_CLOSE",
                "reason": f"Cierre por invalidación de tendencia: Precio ({curr_close:.5f}) cruzó bajo la EMA{self.ema_period} ({ema_trend:.5f})",
                "close_reason": "SimpleTrend_Invalidacion_EMA"
            }
        if (not is_buy) and curr_close > ema_trend:
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
