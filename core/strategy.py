from typing import Optional, Dict, Any, Callable, Tuple, List
from datetime import datetime, time
import numpy as np
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5
from config import StrategyConfig, STRATEGY_CONFIG


class PriceActionStrategy:
    """
    Estrategia Cuantitativa de Acción del Precio con Puntuación de Confluencia:
    - 1. Filtro Previo de Tendencia Macro: EMA 200 (Solo compras si Precio > EMA200, solo ventas si Precio < EMA200).
    - 2. Trigger Obligatorio: Retroceso de Fibonacci igual o mayor al 61.8% (Zona dorada / descuento profundo >= 61.8%).
    - 3. Puntuación de Confluencia (Score):
        a. Tendencia Macro (Filtro EMA 200).
        b. Volumen Institucional (Tick Volume > Media Móvil de Volumen).
        c. Patrón de Vela / Fuerza de Reacción (Hammer, Shooting Star o Vela con cuerpo >= 50%).
    - 4. Módulo de Gestión Activa de Posiciones Abiertas:
        - Análisis de Trailing Stop dinámico por ATR / Estructura.
        - Análisis de Cierre Prematuro por inversión de tendencia (cruce EMA 200 opuesta).
        - Modificación dinámica de SL / TP si el mercado genera nuevos swings favorables.
    - Regla: Requiere min_confluence_score (ej. 2 de 3) para habilitar nuevas órdenes.
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
        rsi_period: int = 14,
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

        # Parámetros de gestión de riesgo ATR, Fibonacci y Fallback Estático
        self.ema_trend_period: int = kwargs.get("ema_trend_period", 200)
        self.atr_sl_mult: float = kwargs.get("atr_sl_mult", 1.5)
        self.atr_tp_mult: float = kwargs.get("atr_tp_mult", 3.0)
        self.static_sl_pips: float = kwargs.get("static_sl_pips", 20.0)
        self.static_tp_pips: float = kwargs.get("static_tp_pips", 40.0)
        self.lookback_swing: int = kwargs.get("lookback_swing", 50)

        # 🟢 PARÁMETROS DE FILTRO DE CORRELACIÓN DE PARES (PEARSON)
        self.use_correlation_filter: bool = getattr(self.config, "use_correlation_filter", kwargs.get("use_correlation_filter", True))
        self.correlation_threshold: float = getattr(self.config, "correlation_threshold", kwargs.get("correlation_threshold", 0.70))
        self.correlation_window: int = getattr(self.config, "correlation_window", kwargs.get("correlation_window", 50))

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
        """Calcula pivotes en tiempo real, niveles de Fibonacci 61.8%, EMA 200, ATR y patrones de vela."""
        w = self.pivot_window
        df = df.copy()

        # 1. Detección de Pivot High y Pivot Low (Sin center=True para evitar repaint)
        df["pivot_high"] = np.nan
        df["pivot_low"] = np.nan

        rolling_max = df["high"].shift(1).rolling(window=w).max()
        rolling_min = df["low"].shift(1).rolling(window=w).min()

        is_pivot_high = (df["high"].shift(w) > rolling_max) & (df["high"].shift(w) > df["high"].rolling(window=w).max())
        is_pivot_low = (df["low"].shift(w) < rolling_min) & (df["low"].shift(w) < df["low"].rolling(window=w).min())

        df.loc[is_pivot_high, "pivot_high"] = df["high"].shift(w)
        df.loc[is_pivot_low, "pivot_low"] = df["low"].shift(w)

        # Resistencia y Soporte proyectados (Swing High y Swing Low)
        df["resistance"] = df["pivot_high"].ffill()
        df["support"] = df["pivot_low"].ffill()

        # 🟢 SALVAGUARDA ANTI-NaN MULTICAPA:
        # Capa 1: Si no hay pivotes formados, usar el Swing High/Low de las últimas `lookback_swing` velas
        rolling_swing_high = df["high"].rolling(window=self.lookback_swing, min_periods=1).max()
        rolling_swing_low = df["low"].rolling(window=self.lookback_swing, min_periods=1).min()

        df["resistance"] = df["resistance"].fillna(rolling_swing_high)
        df["support"] = df["support"].fillna(rolling_swing_low)

        # Capa 2: Relleno hacia atrás (bfill) por si el inicio de la serie no tiene datos
        df["resistance"] = df["resistance"].bfill().ffill()
        df["support"] = df["support"].bfill().ffill()

        # 2. Cálculo de Niveles de Fibonacci 61.8% basados en el impulso swing actual
        swing_range = (df["resistance"] - df["support"]).abs()

        # Capa 3: Si resistance == support (rango plano), asegurar una distancia mínima basada en el precio
        zero_range_mask = (swing_range <= 1e-6) | swing_range.isna()
        if zero_range_mask.any():
            fallback_offset = df["close"] * 0.001
            df.loc[zero_range_mask, "resistance"] = df.loc[zero_range_mask, "close"] + fallback_offset
            df.loc[zero_range_mask, "support"] = df.loc[zero_range_mask, "close"] - fallback_offset
            swing_range = (df["resistance"] - df["support"]).abs()

        # Para compras (retroceso desde Swing High): el nivel 61.8% está en resistance - (0.618 * swing_range)
        df["fibo_618_buy"] = df["resistance"] - (swing_range * 0.618)

        # Para ventas (retroceso desde Swing Low): el nivel 61.8% está en support + (0.618 * swing_range)
        df["fibo_618_sell"] = df["support"] + (swing_range * 0.618)

        # 3. Indicadores Estándar (ATR y EMA Trend)
        df["atr"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=self.atr_period)
        df["ema_trend"] = ta.ema(close=df["close"], length=self.ema_trend_period)

        # 4. Análisis de Volumen (Tick Volume en MT5)
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            df["vol_ma"] = ta.sma(df[vol_col], length=self.volume_ma_period)
            df["high_volume"] = df[vol_col] > df["vol_ma"]
        else:
            df["high_volume"] = True

        # 5. Métrica de Estructura de Vela y Patrones (Hammer / Engulfing)
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

    def analyze_open_position(self, df: pd.DataFrame, position: Any) -> Dict[str, Any]:
        """
        Analiza una posición abierta para determinar:
        1. Cierre prematuro por invalidación de tendencia (inversión contra EMA 200).
        2. Actualización / Optimización de SL (Trailing Stop dinámico por ATR o Swings).
        3. Ajuste de TP si la estructura de soporte/resistencia ha cambiado.
        """
        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period, self.ema_trend_period) + 10
        if df is None or len(df) < min_bars:
            return {"action": "HOLD", "reason": "Insuficiente historial para análisis de posición"}

        df_analyzed = self.calculate_indicators(df)
        curr_candle = df_analyzed.iloc[-2]
        curr_close = float(curr_candle["close"])
        ema_trend = float(curr_candle.get("ema_trend", curr_close))
        current_atr = float(curr_candle.get("atr", 0.0))

        is_buy = position.type == mt5.POSITION_TYPE_BUY
        pos_type_str = "BUY" if is_buy else "SELL"
        price_open = position.price_open
        current_sl = position.sl
        current_tp = position.tp

        # A. Cierre prematuro por invalidación de tendencia macro (EMA 200)
        if is_buy and curr_close < ema_trend:
            return {
                "action": "EARLY_CLOSE",
                "reason": f"Cierre prematuro: Precio ({curr_close:.5f}) cerró por debajo de la EMA200 ({ema_trend:.5f}) invalidando la compra",
                "close_reason": "Invalidacion_EMA200"
            }
        elif not is_buy and curr_close > ema_trend:
            return {
                "action": "EARLY_CLOSE",
                "reason": f"Cierre prematuro: Precio ({curr_close:.5f}) cerró por encima de la EMA200 ({ema_trend:.5f}) invalidando la venta",
                "close_reason": "Invalidacion_EMA200"
            }

        # B. Trailing Stop dinámico por ATR (Protección de ganancias sin ahogar la operación)
        suggested_sl = current_sl
        suggested_tp = current_tp
        needs_sl_update = False
        needs_tp_update = False

        if current_atr > 0:
            trailing_offset = current_atr * self.atr_sl_mult
            if is_buy:
                new_trailing_sl = curr_close - trailing_offset
                # Solo mover el SL hacia arriba (nunca hacia abajo) y si ya está protegiendo en positivo o mejorando el SL inicial
                if new_trailing_sl > current_sl and new_trailing_sl > price_open:
                    suggested_sl = new_trailing_sl
                    needs_sl_update = True
            else:
                new_trailing_sl = curr_close + trailing_offset
                # Solo mover el SL hacia abajo en ventas (nunca hacia arriba)
                if (current_sl == 0.0 or new_trailing_sl < current_sl) and new_trailing_sl < price_open:
                    suggested_sl = new_trailing_sl
                    needs_sl_update = True

        if needs_sl_update or needs_tp_update:
            return {
                "action": "MODIFY_SLTP",
                "suggested_sl": suggested_sl,
                "suggested_tp": suggested_tp,
                "reason": f"Ajuste dinámico Trailing Stop ATR ({current_atr:.5f}) en {pos_type_str} #{position.ticket}"
            }

        return {
            "action": "MONITOR",
            "current_sl": current_sl,
            "current_tp": current_tp,
            "reason": f"Posición {pos_type_str} #{position.ticket} en monitoreo activo y alineada con la tendencia"
        }

    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evalúa las reglas de trading para NUEVAS ENTRADAS en orden estricto:
        1. Filtro de Horario y Mercado Abierto.
        2. Validación de Tendencia Macro (EMA 200).
        3. Retroceso de Fibonacci >= 61.8% en la dirección de la tendencia.
        4. Sistema de Puntuación de Confluencia (Volumen y Patrón de Vela).
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

        # 🟢 1. EVALUACIÓN DE MERCADO CERRADO (FINES DE SEMANA / MT5 DISABLED)
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

        # 🟢 2. EVALUACIÓN DINÁMICA DEL FILTRO DE HORARIO DE SESIÓN
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
        raw_res = curr_candle.get("resistance", np.nan)
        raw_sup = curr_candle.get("support", np.nan)
        resistance = float(curr_close * 1.001 if pd.isna(raw_res) else raw_res)
        support = float(curr_close * 0.999 if pd.isna(raw_sup) else raw_sup)
        current_atr = float(curr_candle.get("atr", 0.0) if not pd.isna(curr_candle.get("atr", 0.0)) else 0.0)
        ema_trend = float(curr_candle.get("ema_trend", curr_close) if not pd.isna(curr_candle.get("ema_trend", curr_close)) else curr_close)

        # Niveles de Fibonacci 61.8%
        raw_fibo_buy = curr_candle.get("fibo_618_buy", 0.0)
        raw_fibo_sell = curr_candle.get("fibo_618_sell", 0.0)
        fibo_618_buy = float(0.0 if pd.isna(raw_fibo_buy) else raw_fibo_buy)
        fibo_618_sell = float(0.0 if pd.isna(raw_fibo_sell) else raw_fibo_sell)

        # 🟢 3. VALIDACIÓN PREVIA DE TENDENCIA MACRO (EMA 200)
        is_bullish_trend = curr_close > ema_trend
        is_bearish_trend = curr_close < ema_trend

        # 🟢 4. VALIDACIÓN DE RETROCESO DE FIBONACCI >= 61.8% (SEGÚN LA TENDENCIA)
        fibo_buy = is_bullish_trend and (fibo_618_buy > 0) and (curr_close <= fibo_618_buy) and (curr_close >= support)
        fibo_sell = is_bearish_trend and (fibo_618_sell > 0) and (curr_close >= fibo_618_sell) and (curr_close <= resistance)

        # 🟢 5. SISTEMA DE PUNTUACIÓN DE CONFLUENCIA (SCORE)
        score = 0
        score_details = []

        # Confirmación A: Tendencia Macro alineada con EMA 200
        if fibo_buy:
            score += 1
            score_details.append(f"Tendencia Alcista Macro (Precio > EMA{self.ema_trend_period}) (+1)")
        elif fibo_sell:
            score += 1
            score_details.append(f"Tendencia Bajista Macro (Precio < EMA{self.ema_trend_period}) (+1)")

        # Confirmación B: Volumen Institucional Superior a la Media
        vol_ok = bool(curr_candle.get("high_volume", False))
        if vol_ok:
            score += 1
            score_details.append("Volumen Institucional Alto (+1)")

        # Confirmación C: Patrón de Reacción / Fuerza de Vela (Hammer o Cuerpo Fuerte >= 50%)
        body_ratio = float(curr_candle.get("body_ratio", 0.0))
        is_bull_hammer = bool(curr_candle.get("is_bullish_hammer", False))
        is_bear_hammer = bool(curr_candle.get("is_bearish_hammer", False))

        if fibo_buy and (is_bull_hammer or body_ratio >= 0.50):
            patron = "Hammer Alcista" if is_bull_hammer else f"Vela Fuerte ({body_ratio * 100:.0f}%)"
            score += 1
            score_details.append(f"Patrón: {patron} (+1)")
        elif fibo_sell and (is_bear_hammer or body_ratio >= 0.50):
            patron = "Shooting Star" if is_bear_hammer else f"Vela Fuerte ({body_ratio * 100:.0f}%)"
            score += 1
            score_details.append(f"Patrón: {patron} (+1)")

        if fibo_buy:
            signal_type = "BUY"
        elif fibo_sell:
            signal_type = "SELL"
        else:
            signal_type = "HOLD"

        is_valid = (signal_type != "HOLD") and (score >= self.min_confluence_score)
        final_signal = signal_type if is_valid else "HOLD"

        # 🟢 6. CÁLCULO DE STOP LOSS Y TAKE PROFIT (ATR O FALLBACK ESTÁTICO)
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
            f"Fibo >= 61.8% ({signal_type}) con Score {score}/3: {', '.join(score_details)}"
            if is_valid
            else (
                f"Esperando retroceso Fibo >= 61.8% alineado con EMA{self.ema_trend_period}"
                if signal_type == "HOLD"
                else f"Zona Fibo {signal_type} descartada por baja confluencia ({score}/{self.min_confluence_score} requerido)"
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
                f"   ├─ Fibo 61.8%: {fibo_618_buy if final_signal == 'BUY' else fibo_618_sell:.5f}\n"
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

    # =========================================================================
    # 🟢 MÓDULO DE GESTIÓN Y FILTRADO DE CORRELACIÓN DE PARES (PEARSON)
    # =========================================================================

    def calculate_pair_correlations(self, market_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Calcula la matriz de correlación de Pearson basada en los retornos y precios
        de cierre de todos los pares entregados por el bot.

        :param market_data: Diccionario { 'EURUSD': df1, 'GBPUSD': df2, ... }
        :return: DataFrame con la matriz de correlación entre pares
        """
        close_prices: Dict[str, pd.Series] = {}

        for symbol, df in market_data.items():
            if df is not None and not df.empty and "close" in df.columns:
                # Tomar los últimos N cierres configurados en la ventana de correlación
                close_series = df["close"].tail(self.correlation_window).reset_index(drop=True)
                if len(close_series) >= 5:
                    close_prices[symbol] = close_series

        if len(close_prices) < 2:
            return pd.DataFrame()  # No hay suficientes pares para calcular correlación

        prices_df = pd.DataFrame(close_prices)
        # Matriz de correlación de Pearson entre los retornos porcentuales
        returns_df = prices_df.pct_change().dropna()

        if len(returns_df) >= 3:
            correlation_matrix = returns_df.corr(method="pearson")
        else:
            correlation_matrix = prices_df.corr(method="pearson")

        return correlation_matrix

    def validate_correlation_filter(
        self,
        target_symbol: str,
        signal_type: str,
        active_positions: List[Dict[str, Any]],
        market_data: Dict[str, pd.DataFrame]
    ) -> Tuple[bool, str]:
        """
        Valida si una nueva señal en 'target_symbol' entra en conflicto o sobreexpone
        el riesgo con las posiciones ya abiertas en la cuenta.

        :param target_symbol: Par que generó la nueva señal (ej: 'GBPUSD')
        :param signal_type: 'BUY' o 'SELL'
        :param active_positions: Lista de órdenes abiertas [ {'symbol': 'EURUSD', 'type': 'SELL'}, ... ]
        :param market_data: Diccionario con los DataFrames de todos los pares relevantes
        :return: (True, motivo) si la operación está permitida, (False, motivo) si se bloquea por correlación.
        """
        if not self.use_correlation_filter:
            return True, "Filtro de correlación desactivado"

        if not active_positions:
            return True, "Sin posiciones abiertas en otros pares"

        corr_matrix = self.calculate_pair_correlations(market_data)

        if corr_matrix.empty or target_symbol not in corr_matrix.columns:
            return True, "Fallback seguro: Matriz de correlación no disponible o insuficiente historial"

        for pos in active_positions:
            open_symbol = pos.get("symbol", "")
            open_type = pos.get("type", "").upper()  # 'BUY' o 'SELL'

            # Ignorar si es el mismo par (el control de posición única por par ya lo gestiona)
            if open_symbol == target_symbol:
                continue

            if open_symbol in corr_matrix.columns:
                try:
                    correlation_value = float(corr_matrix.loc[target_symbol, open_symbol])
                except Exception:
                    continue

                if pd.isna(correlation_value):
                    continue

                # 1. Correlación POSITIVA ALTA (ej: GBPUSD y EURUSD ~ +0.85)
                # Si se mueven igual, NO abrir direcciones opuestas (evita arbitraje / conflicto de divisa)
                if correlation_value >= self.correlation_threshold:
                    if signal_type != open_type:
                        block_msg = (
                            f"🚫 [FILTRO CORRELACIÓN] Señal {signal_type} en {target_symbol} bloqueada. "
                            f"Conflicto directo con {open_symbol} ({open_type}) ➔ Correlación: {correlation_value:+.2f} "
                            f"(Umbral >= {self.correlation_threshold:.2f})"
                        )
                        self._log(block_msg, "WARNING")
                        return False, block_msg

                # 2. Correlación NEGATIVA ALTA (ej: EURUSD y USDCHF ~ -0.85)
                # Si se mueven opuestos, una COMPRA en uno equivale a una VENTA en el otro
                elif correlation_value <= -self.correlation_threshold:
                    if signal_type == open_type:
                        block_msg = (
                            f"🚫 [FILTRO CORRELACIÓN] Señal {signal_type} en {target_symbol} bloqueada. "
                            f"Sobreexposición inversa con {open_symbol} ({open_type}) ➔ Correlación: {correlation_value:+.2f} "
                            f"(Umbral <= -{self.correlation_threshold:.2f})"
                        )
                        self._log(block_msg, "WARNING")
                        return False, block_msg

        return True, "Validación de correlación exitosa: Sin conflictos de riesgo con posiciones activas"

