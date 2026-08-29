from typing import Optional, Dict, Any, Callable, Tuple, List
from datetime import datetime, time
import time as time_module
import numpy as np
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
from config import StrategyConfig, STRATEGY_CONFIG
from .base_strategy import BaseStrategy
from core.candlestick_patterns import detect_candlestick_patterns

# Memoria local (en proceso) de tendencia en timeframe superior, cacheada por (símbolo, timeframe superior)
# para no golpear MT5 en cada evaluación de señal. Ver ForexStrategy._get_htf_trend_alignment.
_HTF_TREND_CACHE: Dict[Tuple[str, int], Dict[str, Any]] = {}


class ForexStrategy(BaseStrategy):
    """
    Estrategia de Price Action + Fibonacci + Multi-Timeframe para pares Forex.

    Entrada: tendencia EMA200 (buffer de entrada más estricto que el de invalidación) +
    confirmación de tendencia en timeframe superior (M15/H1/H4 según el TF de entrada,
    cacheada localmente por símbolo) + retroceso Fibonacci >= 61.8% + score de confluencia
    >= 3/4 (tendencia, volumen, patrón de vela, estocástico). Filtro ADX bloquea entradas en
    mercado lateral. Gestión de posición abierta: cierre prematuro por invalidación de EMA200,
    cierre preventivo por agotamiento (RSI + patrón), trailing stop y extensión de TP por
    ATR/Fibonacci. Reentradas (hasta 5) por escalera Fibonacci o pullback a EMA200.

    El filtro de correlación de pares y las reglas horarias de fin de jornada (16:00/16:15/16:50)
    se aplican desde core/bot_worker.py y core/risk_manager.py, no dentro de esta clase.

    Documentación técnica completa (lógica detallada de cada filtro) y la configuración de
    indicadores equivalente para visualizar en MT5: core/strategies/FOREX_STRATEGY.md
    """

    name: str = "forex"
    description: str = "Forex Price Action + Fibonacci 61.8%/78.6% + Confluence Scoring + EMA 200 Buffer 20%"

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        pivot_window: int = 3,
        atr_period: int = 14,
        volume_ma_period: int = 20,
        rsi_period: int = 14,
        min_confluence_score: int = 3,
        use_session_filter: bool = True,
        logger: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(config=config, symbol=symbol, logger=logger, **kwargs)
        self.pivot_window: int = pivot_window
        self.atr_period: int = atr_period
        self.volume_ma_period: int = volume_ma_period
        self.rsi_period: int = rsi_period
        self.min_confluence_score: int = min_confluence_score
        self.use_session_filter: bool = getattr(self.config, "use_session_filter", use_session_filter)

        # Parámetros de gestión de riesgo ATR, Fibonacci y Fallback Estático
        self.ema_trend_period: int = kwargs.get("ema_trend_period", 200)
        self.atr_sl_mult: float = kwargs.get("atr_sl_mult", 1.5)
        self.atr_tp_mult: float = kwargs.get("atr_tp_mult", 3.0)
        self.static_sl_pips: float = kwargs.get("static_sl_pips", 20.0)
        self.static_tp_pips: float = kwargs.get("static_tp_pips", 40.0)
        self.lookback_swing: int = kwargs.get("lookback_swing", 50)
        self.ema_buffer_pct: float = getattr(self.config, "ema_buffer_pct", kwargs.get("ema_buffer_pct", 0.20))
        self.ema_entry_buffer_pct: float = getattr(self.config, "ema_entry_buffer_pct", kwargs.get("ema_entry_buffer_pct", self.ema_buffer_pct * 0.5))
        self.max_reentries: int = getattr(self.config, "max_reentries", kwargs.get("max_reentries", 0))

        # Parámetros de correlación
        self.use_correlation_filter: bool = getattr(self.config, "use_correlation_filter", kwargs.get("use_correlation_filter", True))
        self.correlation_threshold: float = getattr(self.config, "correlation_threshold", kwargs.get("correlation_threshold", 0.70))
        self.correlation_window: int = getattr(self.config, "correlation_window", kwargs.get("correlation_window", 50))

        # Parámetros de Filtro de Tendencia / Lateralidad (ADX)
        self.adx_period: int = getattr(self.config, "adx_period", kwargs.get("adx_period", 14))
        self.adx_trend_threshold: float = getattr(self.config, "adx_trend_threshold", kwargs.get("adx_trend_threshold", 20.0))

        # Asignación dinámica de horarios según el símbolo
        start_str, end_str = self.config.get_session_times_for_symbol(self.symbol)
        self.session_start: time = datetime.strptime(start_str, "%H:%M").time()
        self.session_end: time = datetime.strptime(end_str, "%H:%M").time()

    def _is_within_session(self, current_time: time) -> bool:
        """Valida si la hora actual está dentro de la ventana operativa dinámica."""
        if self.session_start <= self.session_end:
            return self.session_start <= current_time <= self.session_end
        else:
            return current_time >= self.session_start or current_time <= self.session_end

    def _infer_timeframe_seconds(self, df: pd.DataFrame) -> int:
        """Infiere la temporalidad (en segundos) de las velas recibidas, a partir de sus timestamps."""
        try:
            if "time" in df.columns and len(df) >= 3:
                deltas = df["time"].diff().dropna()
                deltas = deltas[deltas > 0]
                if len(deltas) > 0:
                    return int(deltas.median())
        except Exception:
            pass
        return 300  # Fallback: asume M5 si no se puede inferir de las velas recibidas

    def _pick_htf_constant(self, tf_seconds: int) -> int:
        """Elige el timeframe superior de confirmación de tendencia según la temporalidad de entrada (scalping -> M15/H1)."""
        if tf_seconds <= 300:
            return mt5.TIMEFRAME_M15
        elif tf_seconds <= 900:
            return mt5.TIMEFRAME_H1
        elif tf_seconds <= 3600:
            return mt5.TIMEFRAME_H4
        else:
            return mt5.TIMEFRAME_D1

    def _get_htf_trend_alignment(self, df: pd.DataFrame) -> Tuple[bool, bool, str]:
        """
        Verifica la tendencia del símbolo en un timeframe superior (M15/H1/H4 según la temporalidad
        de entrada) para confirmar que las entradas de scalping van a favor de la tendencia mayor.
        Cachea el resultado en memoria local por (símbolo, timeframe superior) para no golpear MT5
        en cada evaluación de señal. Si no hay datos disponibles, no bloquea (fail-open).
        """
        tf_seconds = self._infer_timeframe_seconds(df)
        htf_constant = self._pick_htf_constant(tf_seconds)
        htf_seconds_map = {
            mt5.TIMEFRAME_M15: 900,
            mt5.TIMEFRAME_H1: 3600,
            mt5.TIMEFRAME_H4: 14400,
            mt5.TIMEFRAME_D1: 86400,
        }
        htf_seconds = htf_seconds_map.get(htf_constant, 3600)

        cache_key = (self.symbol, htf_constant)
        cached = _HTF_TREND_CACHE.get(cache_key)
        now = time_module.time()
        refresh_interval = max(60, htf_seconds // 4)

        if cached is not None and (now - cached["fetched_at"]) < refresh_interval:
            return cached["allow_buy"], cached["allow_sell"], cached["reason"]

        tf_label = {
            mt5.TIMEFRAME_M15: "M15", mt5.TIMEFRAME_H1: "H1",
            mt5.TIMEFRAME_H4: "H4", mt5.TIMEFRAME_D1: "D1"
        }.get(htf_constant, "TF Superior")

        try:
            rates = mt5.copy_rates_from_pos(self.symbol, htf_constant, 0, 250)
            if rates is None or len(rates) < self.ema_trend_period + 5:
                result = (True, True, f"Datos insuficientes en {tf_label}, filtro multi-temporalidad omitido")
            else:
                htf_df = pd.DataFrame(rates)
                htf_ema = ta.ema(close=htf_df["close"], length=self.ema_trend_period)
                htf_close = float(htf_df["close"].iloc[-1])
                htf_ema_val = float(htf_ema.iloc[-1]) if htf_ema is not None and not pd.isna(htf_ema.iloc[-1]) else htf_close
                is_htf_bullish = htf_close >= htf_ema_val
                reason = f"Tendencia {tf_label}: {'Alcista' if is_htf_bullish else 'Bajista'} (Cierre {htf_close:.5f} vs EMA{self.ema_trend_period} {htf_ema_val:.5f})"
                result = (is_htf_bullish, not is_htf_bullish, reason)
        except Exception:
            result = (True, True, f"Error consultando {tf_label}, filtro multi-temporalidad omitido")

        _HTF_TREND_CACHE[cache_key] = {
            "allow_buy": result[0], "allow_sell": result[1], "reason": result[2], "fetched_at": now
        }
        return result

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

        # 2. Niveles de Fibonacci Progresivos (Entrada Base 61.8% y Escalera de Reentradas: 78.6%, 92%, 100%, 132%, 161.8%)
        swing_range = (df["resistance"] - df["support"]).abs()
        zero_range_mask = (swing_range <= 1e-6) | swing_range.isna()
        if zero_range_mask.any():
            fallback_offset = df["close"] * 0.001
            df.loc[zero_range_mask, "resistance"] = df.loc[zero_range_mask, "close"] + fallback_offset
            df.loc[zero_range_mask, "support"] = df.loc[zero_range_mask, "close"] - fallback_offset
            swing_range = (df["resistance"] - df["support"]).abs()

        df["fibo_618_buy"] = df["resistance"] - (swing_range * 0.618)
        df["fibo_618_sell"] = df["support"] + (swing_range * 0.618)
        df["fibo_786_buy"] = df["resistance"] - (swing_range * 0.786)
        df["fibo_786_sell"] = df["support"] + (swing_range * 0.786)
        df["fibo_920_buy"] = df["resistance"] - (swing_range * 0.920)
        df["fibo_920_sell"] = df["support"] + (swing_range * 0.920)
        df["fibo_1000_buy"] = df["resistance"] - (swing_range * 1.000)
        df["fibo_1000_sell"] = df["support"] + (swing_range * 1.000)
        df["fibo_1320_buy"] = df["resistance"] - (swing_range * 1.320)
        df["fibo_1320_sell"] = df["support"] + (swing_range * 1.320)
        df["fibo_1618_buy"] = df["resistance"] - (swing_range * 1.618)
        df["fibo_1618_sell"] = df["support"] + (swing_range * 1.618)

        # 3. Indicadores Estándar
        df["atr"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=self.atr_period)
        df["ema_trend"] = ta.ema(close=df["close"], length=self.ema_trend_period)
        df["rsi"] = ta.rsi(close=df["close"], length=self.rsi_period)

        adx_df = ta.adx(high=df["high"], low=df["low"], close=df["close"], length=self.adx_period)
        adx_col = f"ADX_{self.adx_period}"
        df["adx"] = adx_df[adx_col] if adx_df is not None and adx_col in adx_df.columns else 0.0

        # 3b. Estocástico (confirmación de rebote real en zona de retroceso, no solo "toque" del nivel Fibo)
        stoch_df = ta.stoch(high=df["high"], low=df["low"], close=df["close"], k=14, d=3, smooth_k=3)
        if stoch_df is not None and "STOCHk_14_3_3" in stoch_df.columns:
            df["stoch_k"] = stoch_df["STOCHk_14_3_3"]
            df["stoch_d"] = stoch_df["STOCHd_14_3_3"]
        else:
            df["stoch_k"] = 50.0
            df["stoch_d"] = 50.0

        # 4. Volumen
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
        """Analiza una posición abierta para trailing stop dinámico, extensión de TP por continuación de tendencia y cierre prematuro."""
        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period, self.ema_trend_period) + 10
        if df is None or len(df) < min_bars:
            return {"action": "HOLD", "reason": "Insuficiente historial para análisis de posición"}

        df_analyzed = self.calculate_indicators(df)
        curr_candle = df_analyzed.iloc[-2]
        curr_close = float(curr_candle["close"])
        curr_low = float(curr_candle["low"])
        curr_high = float(curr_candle["high"])
        curr_rsi = float(curr_candle.get("rsi", 50.0))

        ema_trend = float(curr_candle.get("ema_trend", curr_close))
        current_atr = float(curr_candle.get("atr", 0.0))

        is_buy = position.type == mt5.POSITION_TYPE_BUY
        pos_type_str = "BUY" if is_buy else "SELL"
        price_open = float(position.price_open)
        current_sl = float(position.sl)
        current_tp = float(position.tp)

        # A. Cierre prematuro por confirmación de retroceso o cambio de tendencia
        pat_info = detect_candlestick_patterns(df)
        pat_bias = pat_info.get("bias", "NEUTRAL")
        pat_name = pat_info.get("primary_pattern", "Vela Estándar")
        pat_strength = pat_info.get("strength", "MODERATE")

        ema_buffer = (current_atr * self.ema_buffer_pct) if current_atr > 0 else (ema_trend * 0.002)

        # Reglas de Cierre Prematuro: Salida cuando el precio quiebra la EMA200 un 20% del ATR del lado opuesto
        if is_buy:
            # 1. Ruptura de EMA200 un 20% del ATR por debajo (Precio < EMA200 - 0.20 * ATR)
            if curr_close < (ema_trend - ema_buffer):
                return {
                    "action": "EARLY_CLOSE",
                    "reason": f"Cierre prematuro: Precio ({curr_close:.5f}) rompió EMA200 ({ema_trend:.5f}) un 20% por debajo ({ema_trend - ema_buffer:.5f}) invalidando tendencia alcista",
                    "close_reason": "Cambio_Tendencia_EMA200"
                }
            # 2. Rechazo fuerte en zona alta con patrón bajista mayor en sobrecompra
            elif (curr_close > price_open) and pat_bias == "BEARISH" and pat_strength == "STRONG" and curr_rsi > 70:
                return {
                    "action": "EARLY_CLOSE",
                    "reason": f"Cierre preventivo en ganancia: Confirmación de agotamiento/retroceso por {pat_name} (RSI {curr_rsi:.1f} en sobrecompra)",
                    "close_reason": "Agotamiento_Sobrecompra"
                }
        else:
            # 1. Ruptura de EMA200 un 20% del ATR por encima (Precio > EMA200 + 0.20 * ATR)
            if curr_close > (ema_trend + ema_buffer):
                return {
                    "action": "EARLY_CLOSE",
                    "reason": f"Cierre prematuro: Precio ({curr_close:.5f}) superó EMA200 ({ema_trend:.5f}) un 20% por encima ({ema_trend + ema_buffer:.5f}) invalidando tendencia bajista",
                    "close_reason": "Cambio_Tendencia_EMA200"
                }
            # 2. Rebote fuerte en zona baja con patrón alcista mayor en sobreventa
            elif (curr_close < price_open) and pat_bias == "BULLISH" and pat_strength == "STRONG" and curr_rsi < 30:
                return {
                    "action": "EARLY_CLOSE",
                    "reason": f"Cierre preventivo en ganancia: Confirmación de rebote/retroceso por {pat_name} (RSI {curr_rsi:.1f} en sobreventa)",
                    "close_reason": "Agotamiento_Sobreventa"
                }

        # B. Trailing Stop inteligente por ATR y Mínimos/Máximos
        suggested_sl = current_sl
        suggested_tp = current_tp
        needs_sl_update = False
        needs_tp_update = False
        update_reasons = []

        if current_atr > 0:
            trailing_offset = current_atr * max(2.0, self.atr_sl_mult)
            activation_buffer = current_atr * 1.0

            if is_buy:
                if curr_close >= (price_open + activation_buffer):
                    new_trailing_sl = curr_low - trailing_offset
                    if new_trailing_sl > current_sl and new_trailing_sl > price_open:
                        suggested_sl = new_trailing_sl
                        needs_sl_update = True
                        update_reasons.append(f"Trailing SL: {suggested_sl:.5f}")
            else:
                if curr_close <= (price_open - activation_buffer):
                    new_trailing_sl = curr_high + trailing_offset
                    if (current_sl == 0.0 or new_trailing_sl < current_sl) and new_trailing_sl < price_open:
                        suggested_sl = new_trailing_sl
                        needs_sl_update = True
                        update_reasons.append(f"Trailing SL: {suggested_sl:.5f}")

        # C. 📈 AJUSTE DINÁMICO DE TAKE PROFIT POR CONTINUACIÓN DE TENDENCIA (Extensiones Fibonacci y Máximos/Mínimos Anteriores)
        lookback = min(len(df_analyzed), max(self.lookback_swing, 40))
        swing_slice = df_analyzed.iloc[-lookback:-1]
        swing_high = float(swing_slice["high"].max())
        swing_low = float(swing_slice["low"].min())
        swing_range = max(swing_high - swing_low, current_atr * 2.0)

        if is_buy:
            fibo_ext_127 = swing_low + (swing_range * 1.272)
            fibo_ext_161 = swing_low + (swing_range * 1.618)
            resistance_lvl = float(curr_candle.get("resistance", swing_high))

            # Si hay fuerte continuación alcista (precio sobre EMA, momentum sano y sin patrón bajista)
            is_strong_continuation = (curr_close > ema_trend) and (curr_rsi >= 50 and curr_rsi <= 75) and (pat_bias != "BEARISH")
            in_profit = curr_close > (price_open + current_atr * 0.5)

            if is_strong_continuation and in_profit:
                # Si el precio se acerca al TP actual o supera el máximo previo, proyectar TP al siguiente nivel Fibonacci
                if current_tp == 0.0 or curr_close >= (current_tp - current_atr * 0.8) or curr_close >= (swing_high - current_atr * 0.5):
                    target_tp = fibo_ext_161 if curr_close >= (fibo_ext_127 - current_atr * 0.3) else fibo_ext_127
                    target_tp = max(target_tp, resistance_lvl, swing_high + current_atr)

                    if target_tp > current_tp and target_tp > (curr_close + current_atr * 0.8):
                        suggested_tp = target_tp
                        needs_tp_update = True
                        update_reasons.append(f"Extensión TP Fibo: {suggested_tp:.5f}")

        else:
            fibo_ext_127 = swing_high - (swing_range * 1.272)
            fibo_ext_161 = swing_high - (swing_range * 1.618)
            support_lvl = float(curr_candle.get("support", swing_low))

            # Si hay fuerte continuación bajista
            is_strong_continuation = (curr_close < ema_trend) and (curr_rsi <= 50 and curr_rsi >= 25) and (pat_bias != "BULLISH")
            in_profit = curr_close < (price_open - current_atr * 0.5)

            if is_strong_continuation and in_profit:
                # Si el precio se acerca al TP actual o quiebra el mínimo previo, proyectar TP a la siguiente extensión
                if current_tp == 0.0 or curr_close <= (current_tp + current_atr * 0.8) or curr_close <= (swing_low + current_atr * 0.5):
                    target_tp = fibo_ext_161 if curr_close <= (fibo_ext_127 + current_atr * 0.3) else fibo_ext_127
                    target_tp = min(target_tp, support_lvl, swing_low - current_atr)

                    if (current_tp == 0.0 or target_tp < current_tp) and target_tp < (curr_close - current_atr * 0.8):
                        suggested_tp = target_tp
                        needs_tp_update = True
                        update_reasons.append(f"Extensión TP Fibo: {suggested_tp:.5f}")

        if needs_sl_update or needs_tp_update:
            reason_str = " | ".join(update_reasons)
            return {
                "action": "MODIFY_SLTP",
                "suggested_sl": suggested_sl,
                "suggested_tp": suggested_tp,
                "reason": f"Ajuste dinámico #{position.ticket} ({pos_type_str}) ➔ {reason_str}"
            }

        return {
            "action": "MONITOR",
            "current_sl": current_sl,
            "current_tp": current_tp,
            "reason": f"Posición {pos_type_str} #{position.ticket} monitoreada en rango de respiración"
        }

    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Evalúa las reglas de trading para NUEVAS ENTRADAS en Forex."""
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

        # 1. EVALUACIÓN DE MERCADO CERRADO
        now_dt = datetime.now()
        market_open, open_reason = self.config.is_market_open(self.symbol, now_dt)
        if not market_open:
            return {
                "signal": "HOLD",
                "support": 0.0,
                "resistance": 0.0,
                "atr": float(curr_candle.get("atr", 0.0)),
                "score": 0,
                "sl": 0.0,
                "tp": 0.0,
                "reason": open_reason
            }

        # 2. FILTRO DE HORARIO DE SESIÓN
        if self.use_session_filter:
            candle_time = (
                pd.to_datetime(curr_candle.name).time()
                if hasattr(curr_candle, "name") and isinstance(curr_candle.name, (pd.Timestamp, datetime))
                else datetime.now().time()
            )

            if not self._is_within_session(candle_time):
                start_str = self.session_start.strftime("%H:%M")
                return {
                    "signal": "HOLD",
                    "support": 0.0,
                    "resistance": 0.0,
                    "atr": float(curr_candle.get("atr", 0.0)),
                    "score": 0,
                    "sl": 0.0,
                    "tp": 0.0,
                    "reason": f"Fuera de Horario Operativo para {self.symbol}. Se reactiva a las {start_str}"
                }

        # 2b. FILTRO DE TENDENCIA / LATERALIDAD (ADX)
        current_adx = float(curr_candle.get("adx", 0.0) if not pd.isna(curr_candle.get("adx", 0.0)) else 0.0)
        if current_adx > 0 and current_adx < self.adx_trend_threshold:
            return {
                "signal": "HOLD",
                "support": 0.0,
                "resistance": 0.0,
                "atr": float(curr_candle.get("atr", 0.0)),
                "score": 0,
                "sl": 0.0,
                "tp": 0.0,
                "reason": f"[Filtro ADX] Mercado lateral/sin tendencia clara (ADX {current_adx:.1f} < {self.adx_trend_threshold:.1f}). Nuevas entradas bloqueadas."
            }

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

        # 3. FILTRO DE SOBREEXTENSIÓN DE EMA 200 (MÁXIMO 50% DE DISTANCIA DEL RANGO)
        dist_to_ema = abs(curr_close - ema_trend)
        swing_span = abs(resistance - support)
        max_ema_distance = max(swing_span * 0.50, current_atr * 1.5) if swing_span > 0 else (current_atr * 1.5 if current_atr > 0 else ema_trend * 0.01)

        if dist_to_ema > max_ema_distance:
            return {
                "signal": "HOLD",
                "support": support,
                "resistance": resistance,
                "atr": current_atr,
                "score": 0,
                "sl": 0.0,
                "tp": 0.0,
                "reason": f"[Filtro EMA] Precio sobreextendido ({curr_close:.5f}) muy lejos de EMA200 ({ema_trend:.5f}) [Distancia: {dist_to_ema:.5f} > 50% Rango: {max_ema_distance:.5f}]. Posible retroceso inminente."
            }

        # 4. VALIDACIÓN FLEXIBLE DE TENDENCIA MACRO CON BUFFER (EMA 200)
        # Usa un buffer de ENTRADA más estricto que el de invalidación (ema_buffer_pct), para dejar
        # margen real entre "entrada válida" y la línea que dispara el cierre por invalidación de tendencia.
        ema_buffer = (current_atr * self.ema_entry_buffer_pct) if current_atr > 0 else (ema_trend * 0.0005)
        is_bullish_trend = curr_close >= (ema_trend - ema_buffer)
        is_bearish_trend = curr_close <= (ema_trend + ema_buffer)

        # 4b. CONFIRMACIÓN DE TENDENCIA EN TIMEFRAME SUPERIOR (Multi-Timeframe, memoria local por símbolo)
        htf_allows_buy, htf_allows_sell, htf_reason = self._get_htf_trend_alignment(df)

        # 5. VALIDACIÓN DE RETROCESO DE FIBONACCI >= 61.8%
        raw_fibo_buy_trigger = is_bullish_trend and (fibo_618_buy > 0) and (curr_close <= fibo_618_buy) and (curr_close >= support)
        raw_fibo_sell_trigger = is_bearish_trend and (fibo_618_sell > 0) and (curr_close >= fibo_618_sell) and (curr_close <= resistance)
        fibo_buy = raw_fibo_buy_trigger and htf_allows_buy
        fibo_sell = raw_fibo_sell_trigger and htf_allows_sell

        # 6. SCORE DE CONFLUENCIA
        score = 0
        score_details = []

        if fibo_buy:
            score += 1
            score_details.append(f"Tendencia Alcista Macro (Precio >= EMA{self.ema_trend_period} - buffer) (+1)")
        elif fibo_sell:
            score += 1
            score_details.append(f"Tendencia Bajista Macro (Precio <= EMA{self.ema_trend_period} + buffer) (+1)")

        vol_ok = bool(curr_candle.get("high_volume", False))
        if vol_ok:
            score += 1
            score_details.append("Volumen Institucional Alto (+1)")

        body_ratio = float(curr_candle.get("body_ratio", 0.0))
        is_bull_hammer = bool(curr_candle.get("is_bullish_hammer", False))
        is_bear_hammer = bool(curr_candle.get("is_bearish_hammer", False))

        candlestick_info = detect_candlestick_patterns(df)
        candle_bias = candlestick_info.get("bias", "NEUTRAL")
        candle_pattern_name = candlestick_info.get("primary_pattern", "Vela")

        is_bull_candle = bool(curr_candle["close"] > curr_candle["open"])
        is_bear_candle = bool(curr_candle["close"] < curr_candle["open"])

        if fibo_buy and (candle_bias == "BULLISH" or is_bull_hammer or (body_ratio >= 0.50 and is_bull_candle)):
            patron_label = candle_pattern_name if candle_bias == "BULLISH" else ("Hammer Alcista" if is_bull_hammer else f"Vela Fuerte ({body_ratio * 100:.0f}%)")
            score += 1
            score_details.append(f"Patrón: {patron_label} (+1)")
        elif fibo_sell and (candle_bias == "BEARISH" or is_bear_hammer or (body_ratio >= 0.50 and is_bear_candle)):
            patron_label = candle_pattern_name if candle_bias == "BEARISH" else ("Shooting Star" if is_bear_hammer else f"Vela Fuerte ({body_ratio * 100:.0f}%)")
            score += 1
            score_details.append(f"Patrón: {patron_label} (+1)")

        # Confirmación de Estocástico: exige rebote/momentum real en la zona Fibo, no solo el "toque" del nivel
        stoch_k = float(curr_candle.get("stoch_k", 50.0) if not pd.isna(curr_candle.get("stoch_k", 50.0)) else 50.0)
        stoch_d = float(curr_candle.get("stoch_d", 50.0) if not pd.isna(curr_candle.get("stoch_d", 50.0)) else 50.0)
        stoch_bull_ok = (stoch_k <= 35) or (stoch_k > stoch_d and stoch_k <= 50)
        stoch_bear_ok = (stoch_k >= 65) or (stoch_k < stoch_d and stoch_k >= 50)

        if fibo_buy and stoch_bull_ok:
            score += 1
            score_details.append(f"Confirmación Estocástico ({stoch_k:.0f}) (+1)")
        elif fibo_sell and stoch_bear_ok:
            score += 1
            score_details.append(f"Confirmación Estocástico ({stoch_k:.0f}) (+1)")

        if fibo_buy:
            signal_type = "BUY"
        elif fibo_sell:
            signal_type = "SELL"
        else:
            signal_type = "HOLD"

        is_valid = (signal_type != "HOLD") and (score >= self.min_confluence_score)
        final_signal = signal_type if is_valid else "HOLD"

        # 6. STOP LOSS Y TAKE PROFIT
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

        htf_blocked = (raw_fibo_buy_trigger and not htf_allows_buy) or (raw_fibo_sell_trigger and not htf_allows_sell)

        reason = (
            f"[Forex] Fibo >= 61.8% ({signal_type}) con Score {score}/4: {', '.join(score_details)}"
            if is_valid
            else (
                f"[Forex] Zona Fibo {'BUY' if raw_fibo_buy_trigger else 'SELL'} válida en temporalidad de entrada pero descartada por tendencia contraria en TF superior ({htf_reason})"
                if htf_blocked
                else (
                    f"[Forex] Esperando retroceso Fibo >= 61.8% alineado con EMA{self.ema_trend_period}"
                    if signal_type == "HOLD"
                    else f"[Forex] Zona Fibo {signal_type} descartada por baja confluencia ({score}/{self.min_confluence_score} requerido)"
                )
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

    def evaluate_reentry_signal(self, df: pd.DataFrame, open_positions: List[Any], max_reentries: int = 0) -> Dict[str, Any]:
        """
        Evalúa si el mercado ofrece una REENTRADA de alta probabilidad mediante DOS RUTAS:

        1. RUTA A (Escalera Fibo Progresiva - Descuento Profundo):
           - Reentrada #1: Fibo 78.6% (0.786)
           - Reentrada #2: Fibo 92.0% (0.920)
           - Reentrada #3: Fibo 100.0% (1.000 / Origen del Swing)
           - Reentrada #4: Fibo 132.0% (1.320 / Extensión)
           - Reentrada #5: Fibo 161.8% (1.618 / Extensión)
           Requiere que el precio alcance el nivel objetivo de Fibo y supere/mejore el precio de las órdenes previas.

        2. RUTA B (Retroceso / Pullback Dinámico a EMA 200 a Favor de Tendencia):
           - El precio realiza un pullback testeando la EMA 200 (dentro del ema_buffer).
           - Confirmación con patrón de vela de rechazo/fuerza (Hammer, bias alcista/bajista o cuerpo >= 40%).
           - Filtro Anti-Spam: Mínimo 3 velas desde la apertura de la última orden O distancia >= 1.0 * ATR respecto al precio de la última orden.
        """
        if max_reentries <= 0 or not open_positions:
            return {"signal": "HOLD", "reason": "Reentradas deshabilitadas o sin posición base"}

        current_count = len(open_positions)
        if current_count >= (max_reentries + 1):
            return {"signal": "HOLD", "reason": f"Límite de reentradas alcanzado ({current_count - 1}/{max_reentries})"}

        # Determinar la dirección de las órdenes existentes
        base_pos = open_positions[0]
        is_buy = base_pos.type == mt5.POSITION_TYPE_BUY
        expected_signal = "BUY" if is_buy else "SELL"

        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period, self.ema_trend_period) + 10
        if df is None or len(df) < min_bars:
            return {"signal": "HOLD", "reason": "Insuficiente historial para evaluar reentrada"}

        df_analyzed = self.calculate_indicators(df)
        curr_candle = df_analyzed.iloc[-2]
        curr_close = float(curr_candle["close"])
        curr_open = float(curr_candle.get("open", curr_close))
        curr_low = float(curr_candle.get("low", curr_close))
        curr_high = float(curr_candle.get("high", curr_close))

        support = float(curr_candle.get("support", curr_close * 0.999))
        resistance = float(curr_candle.get("resistance", curr_close * 1.001))
        swing_range = abs(resistance - support)
        if swing_range <= 1e-6:
            swing_range = curr_close * 0.002

        current_atr = float(curr_candle.get("atr", 0.0))
        ema_trend = float(curr_candle.get("ema_trend", curr_close))
        ema_buffer = (current_atr * self.ema_buffer_pct) if current_atr > 0 else (ema_trend * 0.002)

        # -------------------------------------------------------------
        # Confluencias compartidas: Patrones de Vela y Volumen
        # -------------------------------------------------------------
        vol_ok = bool(curr_candle.get("high_volume", False))
        body_ratio = float(curr_candle.get("body_ratio", 0.0))
        is_bull_hammer = bool(curr_candle.get("is_bullish_hammer", False))
        is_bear_hammer = bool(curr_candle.get("is_bearish_hammer", False))

        candlestick_info = detect_candlestick_patterns(df)
        candle_bias = candlestick_info.get("bias", "NEUTRAL")
        candle_pattern_name = candlestick_info.get("primary_pattern", "Vela")

        if is_buy:
            candle_confirmed = (candle_bias == "BULLISH") or is_bull_hammer or (body_ratio >= 0.40 and curr_close >= curr_open)
            patron_label = candle_pattern_name if candle_bias == "BULLISH" else ("Hammer Alcista" if is_bull_hammer else f"Rebote Vela Fuerte ({body_ratio * 100:.0f}%)")
        else:
            candle_confirmed = (candle_bias == "BEARISH") or is_bear_hammer or (body_ratio >= 0.40 and curr_close <= curr_open)
            patron_label = candle_pattern_name if candle_bias == "BEARISH" else ("Shooting Star" if is_bear_hammer else f"Rechazo Vela Fuerte ({body_ratio * 100:.0f}%)")

        # -------------------------------------------------------------
        # Control Anti-Spam: Tiempo y Distancia respecto a la última orden abierta
        # -------------------------------------------------------------
        latest_pos = max(open_positions, key=lambda p: getattr(p, "time", 0))
        last_open_price = float(getattr(latest_pos, "price_open", 0.0))
        last_open_time = int(getattr(latest_pos, "time", 0))

        bars_since_last_pos = 0
        if "time" in df.columns and last_open_time > 0:
            try:
                first_val = df["time"].iloc[0]
                if isinstance(first_val, (int, float, np.integer)):
                    bars_since_last_pos = int((df["time"] > last_open_time).sum())
                else:
                    last_dt = pd.to_datetime(last_open_time, unit="s")
                    bars_since_last_pos = int((pd.to_datetime(df["time"]) > last_dt).sum())
            except Exception:
                bars_since_last_pos = 99
        else:
            bars_since_last_pos = 99

        price_dist_atr = (abs(curr_close - last_open_price) / current_atr) if current_atr > 0 else 999.0
        min_bars_anti_spam = 3
        min_atr_dist_anti_spam = 1.0
        anti_spam_passed = (bars_since_last_pos >= min_bars_anti_spam) or (price_dist_atr >= min_atr_dist_anti_spam)

        # -------------------------------------------------------------
        # RUTA A: Escalera Progresiva de Fibonacci
        # -------------------------------------------------------------
        fibo_ladder = [0.786, 0.920, 1.000, 1.320, 1.618, 2.000, 2.618]
        reentry_idx = current_count - 1
        if reentry_idx < len(fibo_ladder):
            target_fibo_ratio = fibo_ladder[reentry_idx]
        else:
            target_fibo_ratio = fibo_ladder[-1] + (reentry_idx - len(fibo_ladder) + 1) * 0.5

        target_fibo_pct = round(target_fibo_ratio * 100, 1)

        route_a_valid = False
        route_a_score = 0
        route_a_details = []
        route_a_reject = ""

        if is_buy:
            target_fibo_price = float(resistance - (swing_range * target_fibo_ratio))
            lowest_open_price = min(float(p.price_open) for p in open_positions)
            level_reached = (curr_close <= target_fibo_price) or (curr_low <= target_fibo_price)
            better_price = curr_close < lowest_open_price

            if not level_reached:
                route_a_reject = f"Precio ({curr_close:.5f}) aún no alcanza Fibo {target_fibo_pct}% ({target_fibo_price:.5f})"
            elif not better_price:
                route_a_reject = f"Precio ({curr_close:.5f}) no mejora precio previo ({lowest_open_price:.5f})"
            else:
                trend_ok = curr_close >= (ema_trend - ema_buffer)
                if trend_ok:
                    route_a_score += 1
                    route_a_details.append(f"Zona Fibo {target_fibo_pct}% sobre EMA{self.ema_trend_period} (+1)")
                elif curr_close >= (target_fibo_price - ema_buffer):
                    route_a_score += 1
                    route_a_details.append(f"Zona Fibo {target_fibo_pct}% Institucional (+1)")

                if vol_ok:
                    route_a_score += 1
                    route_a_details.append("Volumen Institucional (+1)")

                if candle_confirmed:
                    route_a_score += 1
                    route_a_details.append(f"Patrón: {patron_label} (+1)")

                if route_a_score >= self.min_confluence_score:
                    route_a_valid = True
                else:
                    route_a_reject = f"Score insuficiente ({route_a_score}/{self.min_confluence_score})"
        else:
            target_fibo_price = float(support + (swing_range * target_fibo_ratio))
            highest_open_price = max(float(p.price_open) for p in open_positions)
            level_reached = (curr_close >= target_fibo_price) or (curr_high >= target_fibo_price)
            better_price = curr_close > highest_open_price

            if not level_reached:
                route_a_reject = f"Precio ({curr_close:.5f}) aún no alcanza Fibo {target_fibo_pct}% ({target_fibo_price:.5f})"
            elif not better_price:
                route_a_reject = f"Precio ({curr_close:.5f}) no mejora precio previo ({highest_open_price:.5f})"
            else:
                trend_ok = curr_close <= (ema_trend + ema_buffer)
                if trend_ok:
                    route_a_score += 1
                    route_a_details.append(f"Zona Fibo {target_fibo_pct}% bajo EMA{self.ema_trend_period} (+1)")
                elif curr_close <= (target_fibo_price + ema_buffer):
                    route_a_score += 1
                    route_a_details.append(f"Zona Fibo {target_fibo_pct}% Institucional (+1)")

                if vol_ok:
                    route_a_score += 1
                    route_a_details.append("Volumen Institucional (+1)")

                if candle_confirmed:
                    route_a_score += 1
                    route_a_details.append(f"Patrón: {patron_label} (+1)")

                if route_a_score >= self.min_confluence_score:
                    route_a_valid = True
                else:
                    route_a_reject = f"Score insuficiente ({route_a_score}/{self.min_confluence_score})"

        # -------------------------------------------------------------
        # RUTA B: Retroceso / Pullback Dinámico a EMA 200
        # -------------------------------------------------------------
        route_b_valid = False
        route_b_score = 0
        route_b_details = []
        route_b_reject = ""

        if is_buy:
            is_macro_bullish = curr_close >= (ema_trend - ema_buffer)
            touches_ema = (curr_low <= (ema_trend + ema_buffer)) and (curr_close >= (ema_trend - ema_buffer))

            if not is_macro_bullish:
                route_b_reject = f"Precio ({curr_close:.5f}) bajo zona EMA{self.ema_trend_period}"
            elif not touches_ema:
                route_b_reject = f"Precio fuera de zona de pullback EMA{self.ema_trend_period} (EMA: {ema_trend:.5f} ± {ema_buffer:.5f})"
            elif not anti_spam_passed:
                route_b_reject = f"Anti-spam bloqueado ({bars_since_last_pos}/{min_bars_anti_spam} velas y {price_dist_atr:.2f}/{min_atr_dist_anti_spam:.1f} ATR de última orden)"
            elif not candle_confirmed:
                route_b_reject = f"Sin vela de rebote alcista en EMA{self.ema_trend_period}"
            else:
                route_b_score += 1
                route_b_details.append(f"Pullback Dinámico a EMA{self.ema_trend_period} (+1)")

                if vol_ok:
                    route_b_score += 1
                    route_b_details.append("Volumen Institucional (+1)")

                route_b_score += 1
                route_b_details.append(f"Patrón de Rebote: {patron_label} (+1)")

                if route_b_score >= self.min_confluence_score:
                    route_b_valid = True
                else:
                    route_b_reject = f"Score insuficiente ({route_b_score}/{self.min_confluence_score})"
        else:
            is_macro_bearish = curr_close <= (ema_trend + ema_buffer)
            touches_ema = (curr_high >= (ema_trend - ema_buffer)) and (curr_close <= (ema_trend + ema_buffer))

            if not is_macro_bearish:
                route_b_reject = f"Precio ({curr_close:.5f}) sobre zona EMA{self.ema_trend_period}"
            elif not touches_ema:
                route_b_reject = f"Precio fuera de zona de pullback EMA{self.ema_trend_period} (EMA: {ema_trend:.5f} ± {ema_buffer:.5f})"
            elif not anti_spam_passed:
                route_b_reject = f"Anti-spam bloqueado ({bars_since_last_pos}/{min_bars_anti_spam} velas y {price_dist_atr:.2f}/{min_atr_dist_anti_spam:.1f} ATR de última orden)"
            elif not candle_confirmed:
                route_b_reject = f"Sin vela de rechazo bajista en EMA{self.ema_trend_period}"
            else:
                route_b_score += 1
                route_b_details.append(f"Pullback Dinámico a EMA{self.ema_trend_period} (+1)")

                if vol_ok:
                    route_b_score += 1
                    route_b_details.append("Volumen Institucional (+1)")

                route_b_score += 1
                route_b_details.append(f"Patrón de Rechazo: {patron_label} (+1)")

                if route_b_score >= self.min_confluence_score:
                    route_b_valid = True
                else:
                    route_b_reject = f"Score insuficiente ({route_b_score}/{self.min_confluence_score})"

        # -------------------------------------------------------------
        # Cálculo de Stop Loss / Take Profit para Reentradas
        # -------------------------------------------------------------
        point = 0.0001 if "JPY" not in self.symbol else 0.01
        sl_dist = (current_atr * self.atr_sl_mult) if current_atr > 0 else (self.static_sl_pips * point)
        tp_dist = (current_atr * self.atr_tp_mult) if current_atr > 0 else (self.static_tp_pips * point)

        sl_price = (curr_close - sl_dist) if is_buy else (curr_close + sl_dist)
        tp_price = (curr_close + tp_dist) if is_buy else (curr_close - tp_dist)

        # -------------------------------------------------------------
        # Retorno de Señal según la Ruta Activada
        # -------------------------------------------------------------
        if route_a_valid:
            return {
                "signal": expected_signal,
                "is_reentry": True,
                "reentry_route": "FIBO_LADDER",
                "reentry_tag": f"Fibo {target_fibo_pct}%",
                "order_comment": f"Reentry #{current_count} Fibo {target_fibo_pct}%",
                "reentry_number": current_count,
                "max_reentries": max_reentries,
                "fibo_level_pct": target_fibo_pct,
                "fibo_target_price": target_fibo_price,
                "support": support,
                "resistance": resistance,
                "atr": current_atr,
                "score": route_a_score,
                "sl": sl_price,
                "tp": tp_price,
                "reason": f"⚡ [REENTRADA #{current_count}/{max_reentries} - RUTA A: FIBO] Nivel {target_fibo_pct}% {expected_signal} @ {curr_close:.5f} (Objetivo: {target_fibo_price:.5f}) con Score {route_a_score}/3: {', '.join(route_a_details)}"
            }

        if route_b_valid:
            return {
                "signal": expected_signal,
                "is_reentry": True,
                "reentry_route": "EMA_PULLBACK",
                "reentry_tag": "EMA Pullback",
                "order_comment": f"Reentry #{current_count} EMA Pullback",
                "reentry_number": current_count,
                "max_reentries": max_reentries,
                "fibo_level_pct": target_fibo_pct,
                "fibo_target_price": ema_trend,
                "support": support,
                "resistance": resistance,
                "atr": current_atr,
                "score": route_b_score,
                "sl": sl_price,
                "tp": tp_price,
                "reason": f"⚡ [REENTRADA #{current_count}/{max_reentries} - RUTA B: PULLBACK EMA200] {expected_signal} @ {curr_close:.5f} (EMA200: {ema_trend:.5f} ± {ema_buffer:.5f} | Anti-Spam: {bars_since_last_pos} velas / {price_dist_atr:.1f} ATR) con Score {route_b_score}/3: {', '.join(route_b_details)}"
            }

        return {
            "signal": "HOLD",
            "reason": f"Reentrada #{current_count} en espera | Ruta A (Fibo {target_fibo_pct}%): {route_a_reject} | Ruta B (Pullback EMA{self.ema_trend_period}): {route_b_reject}"
        }


# Alias para retrocompatibilidad
PriceActionStrategy = ForexStrategy
