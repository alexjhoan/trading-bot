from typing import Optional, Dict, Any, Callable
from datetime import datetime, time
import numpy as np
import pandas as pd
import pandas_ta as ta
from config import StrategyConfig, STRATEGY_CONFIG


class PriceActionStrategy:
    """
    Estrategia Cuantitativa de Acción del Precio con Puntuación de Confluencia:
    - Trigger Obligatorio: Rompimiento de Estructura (BOS en Soportes / Resistencias).
    - Puntuación (Score):
        1. Volumen Institucional (Tick Volume > Media Móvil de Volumen).
        2. Momentum (RSI favor del movimiento).
        3. Fuerza de Vela (Relación Cuerpo/Sombras).
    - Regla: Requiere min_confluence_score (ej. 2 de 3) para habilitar la orden.
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
        """Calcula pivotes, indicadores técnicos y métricas de velas."""
        w = self.pivot_window
        df = df.copy()

        # 1. Detección de Pivot High y Pivot Low
        df["pivot_high"] = np.nan
        df["pivot_low"] = np.nan

        is_pivot_high = df["high"] == df["high"].rolling(window=2 * w + 1, center=True).max()
        is_pivot_low = df["low"] == df["low"].rolling(window=2 * w + 1, center=True).min()

        df.loc[is_pivot_high, "pivot_high"] = df.loc[is_pivot_high, "high"]
        df.loc[is_pivot_low, "pivot_low"] = df.loc[is_pivot_low, "low"]

        # Resistencia y Soporte proyectados
        df["resistance"] = df["pivot_high"].ffill()
        df["support"] = df["pivot_low"].ffill()

        # 2. Indicadores Estándar (ATR y RSI)
        df["atr"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=self.atr_period)
        df["rsi"] = ta.rsi(close=df["close"], length=self.rsi_period)

        # 3. Análisis de Volumen (Tick Volume en MT5)
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            df["vol_ma"] = ta.sma(df[vol_col], length=self.volume_ma_period)
            df["high_volume"] = df[vol_col] > df["vol_ma"]
        else:
            df["high_volume"] = True

        # 4. Métrica de Estructura de Vela (Fuerza del Cuerpo)
        candle_range = df["high"] - df["low"]
        candle_body = (df["close"] - df["open"]).abs()
        df["body_ratio"] = np.where(candle_range > 0, candle_body / candle_range, 0.0)

        return df

    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evalúa las reglas de trading y calcula la confluencia de la entrada.
        """
        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period) + 10
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
                "reason": "Insuficiente historial de datos"
            }

        df_analyzed = self.calculate_indicators(df)

        # Usar la última vela cerrada (iloc[-2]) para evitar repaint
        prev_candle = df_analyzed.iloc[-3]
        curr_candle = df_analyzed.iloc[-2]

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
                    "reason": f"Fuera de Horario Operativo para {self.symbol}. Se reactiva a las {start_str}"
                }

        curr_close = float(curr_candle["close"])
        prev_close = float(prev_candle["close"])
        resistance = float(curr_candle["resistance"])
        support = float(curr_candle["support"])
        current_atr = float(curr_candle["atr"])

        # 1. TRIGGER OBLIGATORIO: Rompimiento de Estructura (BOS)
        raw_buy = (prev_close <= resistance) and (curr_close > resistance)
        raw_sell = (prev_close >= support) and (curr_close < support)

        # 2. SISTEMA DE PUNTUACIÓN DE CONFLUENCIA
        score = 0
        score_details = []

        # Confirmación A: Volumen Institucional Superior a la Media
        vol_ok = bool(curr_candle.get("high_volume", False))
        if vol_ok:
            score += 1
            score_details.append("Volumen Alto (+1)")

        # Confirmación B: Momentum del RSI
        rsi_val = float(curr_candle.get("rsi", 50.0))
        if raw_buy and rsi_val > 50.0:
            score += 1
            score_details.append(f"RSI Alcista {rsi_val:.1f} (+1)")
        elif raw_sell and rsi_val < 50.0:
            score += 1
            score_details.append(f"RSI Bajista {rsi_val:.1f} (+1)")

        # Confirmación C: Fuerza del Cuerpo de la Vela (>= 50% del rango)
        body_ratio = float(curr_candle.get("body_ratio", 0.0))
        if body_ratio >= 0.50:
            score += 1
            score_details.append(f"Vela Fuerte {body_ratio * 100:.0f}% (+1)")

        signal_type = "BUY" if raw_buy else "SELL"
        is_valid = score >= self.min_confluence_score
        final_signal = signal_type if is_valid else "HOLD"
        reason = (
            f"BOS Confirmado con Score {score}/{3}: {', '.join(score_details)}"
            if is_valid
            else f"BOS descartado por baja confluencia ({score}/{self.min_confluence_score} requerido)"
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
                f"   ├─ ATR (14): {current_atr:.5f}\n"
                f"   └─ Resultado: {final_signal} ➔ Razón: {reason}"
            )
            self._log(debug_msg, "INFO")

        return {
            "signal": final_signal,
            "support": support,
            "resistance": resistance,
            "atr": current_atr,
            "score": score,
            "reason": reason
        }
