from typing import Optional, Dict, Any, Callable, Tuple
from datetime import datetime, time
import numpy as np
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
from config import StrategyConfig, STRATEGY_CONFIG


class PriceActionStrategy:
    """
    Estrategia Cuantitativa de Acción del Precio con Puntuación de Confluencia:
    - Trigger Obligatorio: Retest / Reacción en Soportes y Resistencias a favor de Tendencia.
    - Puntuación (Score):
        1. Tendencia Macro (Filtro EMA 200).
        2. Volumen Institucional (Tick Volume > Media Móvil de Volumen).
        3. Patrón de Vela / Fuerza de Reacción (Hammer, Engulfing o Cuerpo Fuerte).
    - Regla: Requiere min_confluence_score (ej. 2 de 3) para habilitar la orden.
    - Gestión de Riesgo: Niveles dinámicos SL / TP basados en ATR con Respaldo Estático.
    - Filtro Dinámico de Horarios: Identifica la ventana de liquidez según las divisas del par.
    """

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        pivot_window: int = 3,
        atr_period: int = 14,
        volume_ma_period: int = 20,
        rsi_period: int = 14,  # Mantenido para retrocompatibilidad
        min_confluence_score: int = 2,
        use_session_filter: bool = True,
        logger: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> None:
        self.config: StrategyConfig = config or STRATEGY_CONFIG
        self.symbol: str = symbol or ""
        self.pivot_window: int = pivot_window
        self.atr_period: int = atr_period
        self.volume_ma_period: int = volume_ma_period
        self.rsi_period: int = rsi_period
        self.min_confluence_score: int = min_confluence_score
        self.use_session_filter: bool = getattr(self.config, "use_session_filter", use_session_filter)
        self._logger: Optional[Callable[[str, str], None]] = logger

        # Parámetros de gestión de riesgo ATR y Fallback Estático
        self.ema_trend_period: int = kwargs.get("ema_trend_period", 200)
        self.atr_sl_mult: float = kwargs.get("atr_sl_mult", 1.5)
        self.atr_tp_mult: float = kwargs.get("atr_tp_mult", 3.0)
        self.static_sl_pips: float = kwargs.get("static_sl_pips", 20.0)
        self.static_tp_pips: float = kwargs.get("static_tp_pips", 40.0)

        # 🟢 ASIGNACIÓN DINÁMICA DE HORARIOS SEGÚN EL SÍMBOLO
        start_str, end_str = self.config.get_session_times_for_symbol(self.symbol)
        self.session_start: time = datetime.strptime(start_str, "%H:%M").time()
        self.session_end: time = datetime.strptime(end_str, "%H:%M").time()

    def _log(self, message: str, level: str = "INFO") -> None:
        """Envía logs al GUI si hay un logger registrado, o a la consola estándar."""
        if self._logger is not None:
            self._logger(message, level)
        else:
            print(f"[{level}] {message}")

    def _is_within_session(self, current_time: time) -> bool:
        """Valida si la hora actual está dentro de la ventana operativa dinámica."""
        if self.session_start <= self.session_end:
            return self.session_start <= current_time <= self.session_end
        else:  # Para sesiones que cruzan la medianoche (ej. Asia/Australia: 22:00 a 08:00)
            return current_time >= self.session_start or current_time <= self.session_end

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula pivotes en tiempo real (sin lag de ventana centrada), EMA 200, ATR y patrones de vela."""
        w = self.pivot_window
        df = df.copy()

        # 1. Detección de Pivot High y Pivot Low (Sin center=True para evitar repaint en tiempo real)
        df["pivot_high"] = np.nan
        df["pivot_low"] = np.nan

        # Causa pivote usando ventana retrospectiva pura
        rolling_max = df["high"].shift(1).rolling(window=w).max()
        rolling_min = df["low"].shift(1).rolling(window=w).min()

        is_pivot_high = (df["high"].shift(w) > rolling_max) & (df["high"].shift(w) > df["high"].rolling(window=w).max())
        is_pivot_low = (df["low"].shift(w) < rolling_min) & (df["low"].shift(w) < df["low"].rolling(window=w).min())

        df.loc[is_pivot_high, "pivot_high"] = df["high"].shift(w)
        df.loc[is_pivot_low, "pivot_low"] = df["low"].shift(w)

        # Resistencia y Soporte proyectados
        df["resistance"] = df["pivot_high"].ffill()
        df["support"] = df["pivot_low"].ffill()

        # 2. Indicadores Estándar (ATR y EMA Trend)
        df["atr"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=self.atr_period)
        df["ema_trend"] = ta.ema(close=df["close"], length=self.ema_trend_period)

        # 3. Análisis de Volumen (Tick Volume en MT5)
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            df["vol_ma"] = ta.sma(df[vol_col], length=self.volume_ma_period)
            df["high_volume"] = df[vol_col] > df["vol_ma"]
        else:
            df["high_volume"] = True

        # 4. Métrica de Estructura de Vela y Patrones (Hammer / Engulfing)
        candle_range = df["high"] - df["low"]
        candle_body = (df["close"] - df["open"]).abs()
        upper_wick = df["high"] - np.maximum(df["open"], df["close"])
        lower_wick = np.minimum(df["open"], df["close"]) - df["low"]

        df["body_ratio"] = np.where(candle_range > 0, candle_body / candle_range, 0.0)

        # Detección de Patrón Martillo (Hammer / Bullish Rejection)
        df["is_bullish_hammer"] = (lower_wick >= 2 * candle_body) & (upper_wick <= candle_body * 0.5) & (candle_range > 0)
        # Detección de Patrón Estrella Fugaz (Shooting Star / Bearish Rejection)
        df["is_bearish_hammer"] = (upper_wick >= 2 * candle_body) & (lower_wick <= candle_body * 0.5) & (candle_range > 0)

        return df

    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evalúa las reglas de trading y calcula la confluencia de la entrada basada en Retest.
        """
        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period, self.ema_trend_period) + 10
        if df is None or len(df) < min_bars:

            debug_msg = (
                f"🔍 [ANALISIS ESTRATEGIA] {self.symbol}\n"
                f"   ├─ Resistencia (Pivot High): 0.0\n"
                f"   ├─ Soporte (Pivot Low): 0.0\n"
                f"   ├─ Score Confluencia: 0/3 (Ninguno)\n"
                f"   ├─ ATR (14): 0\n"
                f"   └─ Resultado: Insuficiente historial de datos"
            )
            self._log(debug_msg, "INFO")

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

        # Usar la última vela cerrada (iloc[-2]) para evitar repaint
        prev_candle = df_analyzed.iloc[-3]
        curr_candle = df_analyzed.iloc[-2]

        # 🟢 EVALUACIÓN DE MERCADO CERRADO (FINES DE SEMANA / MT5 DISABLED)
        now_dt = datetime.now()
        market_open, open_reason = self.config.is_market_open(self.symbol, now_dt)
        if not market_open:
            debug_msg = (
                f"🛑 [MERCADO CERRADO] {self.symbol} | {open_reason}\n"
                f"   └─ El análisis de estrategia se suspende hasta la apertura del mercado."
            )
            self._log(debug_msg, "WARNING")

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

        # 🟢 EVALUACIÓN DINÁMICA DEL FILTRO DE HORARIO
        if self.use_session_filter:
            candle_time = (
                pd.to_datetime(curr_candle.name).time()
                if hasattr(curr_candle, "name") and isinstance(curr_candle.name, (pd.Timestamp, datetime))
                else datetime.now().time()
            )

            if not self._is_within_session(candle_time):
                start_str = self.session_start.strftime("%H:%M")
                end_str = self.session_end.strftime("%H:%M")
                debug_msg = (
                    f"⏰ [FILTRO HORARIO DINÁMICO] {self.symbol} | Hora actual: {candle_time.strftime('%H:%M:%S')}\n"
                    f"   ├─ Estado: Fuera de rango de alta liquidez para este par ({start_str} - {end_str} UTC).\n"
                    f"   └─ El bot se reactivará automáticamente a las: {start_str} hrs."
                )
                self._log(debug_msg, "WARNING")

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

        curr_close = float(curr_candle["close"])
        curr_low = float(curr_candle["low"])
        curr_high = float(curr_candle["high"])
        resistance = float(curr_candle["resistance"])
        support = float(curr_candle["support"])
        current_atr = float(curr_candle.get("atr", 0.0))
        ema_trend = float(curr_candle.get("ema_trend", curr_close))

        # Tolerancia de retest en base al ATR (0.25 ATR de margen para tocar el nivel)
        retest_margin = current_atr * 0.25 if current_atr > 0 else 0.0005

        # 1. TRIGGER DE RETEST (Reacción en zona clave)
        # Compra: El mínimo de la vela testeó el soporte y cerró por encima
        retest_buy = (curr_low <= (support + retest_margin)) and (curr_close > support)
        # Venta: El máximo de la vela testeó la resistencia y cerró por debajo
        retest_sell = (curr_high >= (resistance - retest_margin)) and (curr_close < resistance)

        # 2. SISTEMA DE PUNTUACIÓN DE CONFLUENCIA
        score = 0
        score_details = []

        # Confirmación A: Tendencia Macro con EMA 200
        if retest_buy and curr_close > ema_trend:
            score += 1
            score_details.append(f"Tendencia Alcista (Precio > EMA{self.ema_trend_period}) (+1)")
        elif retest_sell and curr_close < ema_trend:
            score += 1
            score_details.append(f"Tendencia Bajista (Precio < EMA{self.ema_trend_period}) (+1)")

        # Confirmación B: Volumen Institucional Superior a la Media
        vol_ok = bool(curr_candle.get("high_volume", False))
        if vol_ok:
            score += 1
            score_details.append("Volumen Alto (+1)")

        # Confirmación C: Patrón de Reacción / Fuerza de Vela (Hammer o Cuerpo Fuerte)
        body_ratio = float(curr_candle.get("body_ratio", 0.0))
        is_bull_hammer = bool(curr_candle.get("is_bullish_hammer", False))
        is_bear_hammer = bool(curr_candle.get("is_bearish_hammer", False))

        if retest_buy and (is_bull_hammer or body_ratio >= 0.50):
            patron = "Hammer Alcista" if is_bull_hammer else f"Vela Fuerte ({body_ratio * 100:.0f}%)"
            score += 1
            score_details.append(f"Patrón: {patron} (+1)")
        elif retest_sell and (is_bear_hammer or body_ratio >= 0.50):
            patron = "Shooting Star" if is_bear_hammer else f"Vela Fuerte ({body_ratio * 100:.0f}%)"
            score += 1
            score_details.append(f"Patrón: {patron} (+1)")

        if retest_buy:
            signal_type = "BUY"
        elif retest_sell:
            signal_type = "SELL"
        else:
            signal_type = "HOLD"

        is_valid = (signal_type != "HOLD") and (score >= self.min_confluence_score)
        final_signal = signal_type if is_valid else "HOLD"

        # 3. CÁLCULO DE STOP LOSS Y TAKE PROFIT (ATR O FALLBACK ESTÁTICO)
        sl_price = 0.0
        tp_price = 0.0

        if final_signal != "HOLD":
            # Determinación del tamaño de pip/punto para el respaldo estático
            point = 0.0001 if "JPY" not in self.symbol else 0.01

            if current_atr > 0:
                sl_dist = current_atr * self.atr_sl_mult
                tp_dist = current_atr * self.atr_tp_mult
            else:
                # Fallback estático en pips si el ATR no está disponible o da cero
                sl_dist = self.static_sl_pips * point
                tp_dist = self.static_tp_pips * point

            if final_signal == "BUY":
                sl_price = curr_close - sl_dist
                tp_price = curr_close + tp_dist
            elif final_signal == "SELL":
                sl_price = curr_close + sl_dist
                tp_price = curr_close - tp_dist

        reason = (
            f"Retest Confirmado ({signal_type}) con Score {score}/3: {', '.join(score_details)}"
            if is_valid
            else (
                f"Sin retest en zonas clave"
                if signal_type == "HOLD"
                else f"Retest {signal_type} descartado por baja confluencia ({score}/{self.min_confluence_score} requerido)"
            )
        )

        # 🟢 REGISTRO DE DEPURACIÓN EN GUI / CONSOLA

        if final_signal == "HOLD":
            debug_msg = (
                f"🔍 [ANALISIS ESTRATEGIA] {self.symbol}: {final_signal} ➔ Razón: {reason}"
            )
            self._log(debug_msg, "WARNING")
        else:
            debug_msg = (
                f"🔍 [ANALISIS ESTRATEGIA] {self.symbol} | Cierre: {curr_close:.5f}\n"
                f"   ├─ Resistencia (Pivot High): {resistance:.5f}\n"
                f"   ├─ Soporte (Pivot Low): {support:.5f}\n"
                f"   ├─ Score Confluencia: {score}/3 ({', '.join(score_details) if score_details else 'Ninguno'})\n"
                f"   ├─ ATR (14): {current_atr:.5f} | SL: {sl_price:.5f} | TP: {tp_price:.5f}\n"
                f"   └─ Resultado: {final_signal} ➔ Razón: {reason}"
            )
            self._log(debug_msg, "INFO")

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
