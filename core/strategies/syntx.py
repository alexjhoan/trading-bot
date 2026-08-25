from typing import Optional, Dict, Any, Callable, Tuple, List
from datetime import datetime, time
import numpy as np
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
from config import StrategyConfig, STRATEGY_CONFIG
from .base_strategy import BaseStrategy
from core.candlestick_patterns import detect_candlestick_patterns, format_candlestick_summary_for_ai


class SyntxStrategy(BaseStrategy):
    """
    Estrategia Cuantitativa SYNTX para Índices Sintéticos / Volatilidad y Swings:
    - 1. Filtro Previo de Tendencia Macro: EMA 200 con Buffer Flexible de Tolerancia (15% ATR).
    - 2. Trigger de Entrada: Retroceso de Fibonacci >= 61.8% en Swings de Volatilidad.
    - 3. Puntuación de Confluencia (Score):
        a. Tendencia Macro (Filtro EMA 200 con buffer de respiración).
        b. Volumen / Momentum de Ticks (Tick Volume > Media Móvil de Volumen).
        c. Patrón de Vela de Reacción / Rechazo (Hammer, Shooting Star o Vela con cuerpo >= 50%).
    - 4. Módulo de Gestión Activa de Posiciones Abiertas:
        - Trailing Stop dinámico por ATR + Estructura de vela previa.
        - Cierre Prematuro por invalidación de tendencia (quiebre EMA 200 más allá del buffer).
        - Modificación dinámica de SL / TP con margen de respiración previo (1.0x ATR).
    - 5. Operativa Continua 24/7 adaptada a mercados sintéticos y de alta volatilidad.
    """

    name: str = "syntx"
    description: str = "Syntx Volatility & Swings + Fibonacci Pullback + Dynamic ATR Trailing"

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        pivot_window: int = 3,
        atr_period: int = 14,
        volume_ma_period: int = 20,
        rsi_period: int = 14,
        min_confluence_score: int = 2,
        use_session_filter: bool = False,  # Synthetics operan 24/7 por defecto
        logger: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(config=config, symbol=symbol, logger=logger, **kwargs)
        self.pivot_window: int = pivot_window
        self.atr_period: int = atr_period
        self.volume_ma_period: int = volume_ma_period
        self.rsi_period: int = rsi_period
        self.min_confluence_score: int = min_confluence_score
        self.use_session_filter: bool = use_session_filter

        # Parámetros de gestión de riesgo ATR, Fibonacci y Fallback Estático
        self.ema_trend_period: int = kwargs.get("ema_trend_period", 200)
        self.atr_sl_mult: float = kwargs.get("atr_sl_mult", 1.8)
        self.atr_tp_mult: float = kwargs.get("atr_tp_mult", 3.2)
        self.static_sl_pips: float = kwargs.get("static_sl_pips", 30.0)
        self.static_tp_pips: float = kwargs.get("static_tp_pips", 60.0)
        self.lookback_swing: int = kwargs.get("lookback_swing", 50)
        self.ema_buffer_pct: float = getattr(self.config, "ema_buffer_pct", kwargs.get("ema_buffer_pct", 0.15))

        # Parámetros de correlación
        self.use_correlation_filter: bool = getattr(self.config, "use_correlation_filter", kwargs.get("use_correlation_filter", False))
        self.correlation_threshold: float = getattr(self.config, "correlation_threshold", kwargs.get("correlation_threshold", 0.75))
        self.correlation_window: int = getattr(self.config, "correlation_window", kwargs.get("correlation_window", 50))

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula pivotes en tiempo real, niveles de Fibonacci 61.8%, EMA 200, ATR y patrones de vela."""
        w = self.pivot_window
        df = df.copy()

        # 1. Detección de Pivot High y Pivot Low
        df["pivot_high"] = np.nan
        df["pivot_low"] = np.nan

        rolling_max = df["high"].shift(1).rolling(window=w).max()
        rolling_min = df["low"].shift(1).rolling(window=w).min()

        is_pivot_high = (df["high"].shift(w) > rolling_max) & (df["high"].shift(w) > df["high"].rolling(window=w).max())
        is_pivot_low = (df["low"].shift(w) < rolling_min) & (df["low"].shift(w) < df["low"].rolling(window=w).min())

        df.loc[is_pivot_high, "pivot_high"] = df["high"].shift(w)
        df.loc[is_pivot_low, "pivot_low"] = df["low"].shift(w)

        # Resistencia y Soporte proyectados
        df["resistance"] = df["pivot_high"].ffill()
        df["support"] = df["pivot_low"].ffill()

        # Salvaguarda Anti-NaN
        rolling_swing_high = df["high"].rolling(window=self.lookback_swing, min_periods=1).max()
        rolling_swing_low = df["low"].rolling(window=self.lookback_swing, min_periods=1).min()

        df["resistance"] = df["resistance"].fillna(rolling_swing_high)
        df["support"] = df["support"].fillna(rolling_swing_low)
        df["resistance"] = df["resistance"].bfill().ffill()
        df["support"] = df["support"].bfill().ffill()

        # 2. Niveles de Fibonacci 61.8%
        swing_range = (df["resistance"] - df["support"]).abs()
        zero_range_mask = (swing_range <= 1e-6) | swing_range.isna()
        if zero_range_mask.any():
            fallback_offset = df["close"] * 0.001
            df.loc[zero_range_mask, "resistance"] = df.loc[zero_range_mask, "close"] + fallback_offset
            df.loc[zero_range_mask, "support"] = df.loc[zero_range_mask, "close"] - fallback_offset
            swing_range = (df["resistance"] - df["support"]).abs()

        df["fibo_618_buy"] = df["resistance"] - (swing_range * 0.618)
        df["fibo_618_sell"] = df["support"] + (swing_range * 0.618)

        # 3. Indicadores Estándar
        df["atr"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=self.atr_period)
        df["ema_trend"] = ta.ema(close=df["close"], length=self.ema_trend_period)

        # 4. Volumen / Tick Activity
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            df["vol_ma"] = ta.sma(df[vol_col], length=self.volume_ma_period)
            df["high_volume"] = df[vol_col] > df["vol_ma"]
        else:
            df["high_volume"] = True

        # 5. Patrones de Vela
        candle_range = df["high"] - df["low"]
        candle_body = (df["close"] - df["open"]).abs()
        upper_wick = df["high"] - np.maximum(df["open"], df["close"])
        lower_wick = np.minimum(df["open"], df["close"]) - df["low"]

        df["body_ratio"] = np.where(candle_range > 0, candle_body / candle_range, 0.0)
        df["is_bullish_hammer"] = (lower_wick >= 2 * candle_body) & (upper_wick <= candle_body * 0.5) & (candle_range > 0)
        df["is_bearish_hammer"] = (upper_wick >= 2 * candle_body) & (lower_wick <= candle_body * 0.5) & (candle_range > 0)

        return df

    def analyze_open_position(self, df: pd.DataFrame, position: Any) -> Dict[str, Any]:
        """Analiza una posición abierta para trailing stop o cierre prematuro."""
        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period, self.ema_trend_period) + 10
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

        # A. Cierre prematuro o Mantenimiento ('HOLD') según Acción del Precio y Patrones de Velas
        pat_info = detect_candlestick_patterns(df)
        pat_bias = pat_info.get("bias", "NEUTRAL")
        pat_name = pat_info.get("primary_pattern", "Vela Estándar")
        pat_strength = pat_info.get("strength", "MODERATE")

        ema_buffer = (current_atr * self.ema_buffer_pct) if current_atr > 0 else (ema_trend * 0.001)

        # Regla de Oro SYNTX: Si hay patrón de confirmación alcista a favor de BUY o bajista a favor de SELL, MANTENER
        if is_buy:
            if pat_bias == "BULLISH" and pat_strength in ["STRONG", "MEDIUM"]:
                pass
            elif curr_close < (ema_trend - ema_buffer):
                return {
                    "action": "EARLY_CLOSE",
                    "reason": f"Cierre prematuro SYNTX: Precio ({curr_close:.5f}) rompió la EMA200 ({ema_trend:.5f}) superando el buffer ({ema_buffer:.5f}) y sin patrón alcista protector",
                    "close_reason": "Invalidacion_EMA200"
                }
        else:
            if pat_bias == "BEARISH" and pat_strength in ["STRONG", "MEDIUM"]:
                pass
            elif curr_close > (ema_trend + ema_buffer):
                return {
                    "action": "EARLY_CLOSE",
                    "reason": f"Cierre prematuro SYNTX: Precio ({curr_close:.5f}) superó la EMA200 ({ema_trend:.5f}) superando el buffer ({ema_buffer:.5f}) y sin patrón bajista protector",
                    "close_reason": "Invalidacion_EMA200"
                }

        # B. Trailing Stop inteligente por ATR y Mínimos/Máximos de Vela
        suggested_sl = current_sl
        suggested_tp = current_tp
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
                "suggested_tp": suggested_tp,
                "reason": f"Trailing Stop SYNTX ajustado ({pos_type_str} #{position.ticket})"
            }

        return {
            "action": "MONITOR",
            "current_sl": current_sl,
            "current_tp": current_tp,
            "reason": f"Posición SYNTX {pos_type_str} #{position.ticket} en margen de seguimiento"
        }

    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Evalúa las reglas de trading para NUEVAS ENTRADAS en SYNTX."""
        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period, self.ema_trend_period) + 10
        if df is None or len(df) < min_bars:
            return {
                "signal": "HOLD",
                "support": 0.0,
                "resistance": 0.0,
                "atr": 0.0,
                "score": 0,
                "sl": 0.0,
                "tp": 0.0,
                "reason": "Insuficiente historial de datos"
            }

        df_analyzed = self.calculate_indicators(df)
        curr_candle = df_analyzed.iloc[-2]

        curr_close = float(curr_candle["close"])
        raw_res = curr_candle.get("resistance", np.nan)
        raw_sup = curr_candle.get("support", np.nan)
        resistance = float(curr_close * 1.001 if pd.isna(raw_res) else raw_res)
        support = float(curr_close * 0.999 if pd.isna(raw_sup) else raw_sup)
        current_atr = float(curr_candle.get("atr", 0.0) if not pd.isna(curr_candle.get("atr", 0.0)) else 0.0)
        ema_trend = float(curr_candle.get("ema_trend", curr_close) if not pd.isna(curr_candle.get("ema_trend", curr_close)) else curr_close)

        raw_fibo_buy = curr_candle.get("fibo_618_buy", 0.0)
        raw_fibo_sell = curr_candle.get("fibo_618_sell", 0.0)
        fibo_618_buy = float(0.0 if pd.isna(raw_fibo_buy) else raw_fibo_buy)
        fibo_618_sell = float(0.0 if pd.isna(raw_fibo_sell) else raw_fibo_sell)

        # Validación Flexible de Tendencia Macro (EMA 200 + Buffer 15% ATR)
        ema_buffer = (current_atr * self.ema_buffer_pct) if current_atr > 0 else (ema_trend * 0.001)
        is_bullish_trend = curr_close >= (ema_trend - ema_buffer)
        is_bearish_trend = curr_close <= (ema_trend + ema_buffer)

        # Validación Fibo 61.8%
        fibo_buy = is_bullish_trend and (fibo_618_buy > 0) and (curr_close <= fibo_618_buy) and (curr_close >= support)
        fibo_sell = is_bearish_trend and (fibo_618_sell > 0) and (curr_close >= fibo_618_sell) and (curr_close <= resistance)

        # Score Confluencia
        score = 0
        score_details = []

        if fibo_buy:
            score += 1
            score_details.append(f"Tendencia Alcista Macro EMA{self.ema_trend_period} (+1)")
        elif fibo_sell:
            score += 1
            score_details.append(f"Tendencia Bajista Macro EMA{self.ema_trend_period} (+1)")

        vol_ok = bool(curr_candle.get("high_volume", False))
        if vol_ok:
            score += 1
            score_details.append("Actividad de Volumen Alta (+1)")

        body_ratio = float(curr_candle.get("body_ratio", 0.0))
        is_bull_hammer = bool(curr_candle.get("is_bullish_hammer", False))
        is_bear_hammer = bool(curr_candle.get("is_bearish_hammer", False))

        candlestick_info = detect_candlestick_patterns(df)
        candle_bias = candlestick_info.get("bias", "NEUTRAL")
        candle_pattern_name = candlestick_info.get("primary_pattern", "Vela")

        if fibo_buy and (candle_bias == "BULLISH" or is_bull_hammer or body_ratio >= 0.50):
            patron_label = candle_pattern_name if candle_bias == "BULLISH" else ("Hammer Alcista" if is_bull_hammer else f"Impulso Fuerte ({body_ratio * 100:.0f}%)")
            score += 1
            score_details.append(f"Patrón: {patron_label} (+1)")
        elif fibo_sell and (candle_bias == "BEARISH" or is_bear_hammer or body_ratio >= 0.50):
            patron_label = candle_pattern_name if candle_bias == "BEARISH" else ("Shooting Star" if is_bear_hammer else f"Impulso Bajista ({body_ratio * 100:.0f}%)")
            score += 1
            score_details.append(f"Patrón: {patron_label} (+1)")

        if fibo_buy:
            signal_type = "BUY"
        elif fibo_sell:
            signal_type = "SELL"
        else:
            signal_type = "HOLD"

        is_valid = (signal_type != "HOLD") and (score >= self.min_confluence_score)
        final_signal = signal_type if is_valid else "HOLD"

        # Cálculo de SL y TP
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
            elif final_signal == "SELL":
                sl_price = curr_close + sl_dist
                tp_price = curr_close - tp_dist

        reason = (
            f"[SYNTX] Fibo >= 61.8% ({signal_type}) con Score {score}/3: {', '.join(score_details)}"
            if is_valid
            else (
                f"[SYNTX] Monitoreando retroceso Fibo >= 61.8% alineado con EMA{self.ema_trend_period}"
                if signal_type == "HOLD"
                else f"[SYNTX] Señal {signal_type} descartada por confluencia insuficiente ({score}/{self.min_confluence_score})"
            )
        )

        return {
            "signal": final_signal,
            "support": support,
            "resistance": resistance,
            "atr": current_atr,
            "score": score,
            "sl": sl_price,
            "tp": tp_price,
            "reason": reason
        }
