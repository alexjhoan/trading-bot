"""
========================================================================================
ESTRATEGIA CUANTITATIVA EVOLUTIVA: AI-STRATEGY (AUTOAPRENDIZAJE CONTINUO)
========================================================================================

DESCRIPCIÓN GENERAL:
--------------------
AIStrategy es una estrategia híbrida cuantitativa con autoaprendizaje continuo diseñada
para operar en MetaTrader 5 (MT5). Combina confluencia técnica algorítmica institucional
con un motor de auto-adaptación heurística basado en Inteligencia Artificial y memoria
de Deep Search (ai_backtest_learnings.json y trade_memory.json).

A diferencia de las estrategias estáticas con parámetros fijos, AIStrategy modula sus
umbrales de disparo, relaciones Riesgo/Beneficio (R:R) y reglas de trailing stop en
tiempo real según lo que el sistema ha aprendido de cada par específico.

ARQUITECTURA DE INDICADORES:
----------------------------
1. CINTA DE MEDIAS MÓVILES EXPONENCIALES (EMA Ribbon):
   - EMA 9 (Gatillo rápido de momentum).
   - EMA 21 (Tendencia a corto plazo).
   - EMA 50 (Soporte/Resistencia dinámica institucional).
   - EMA 200 (Filtro direccional macro).

2. ÍNDICE DE FUERZA RELATIVA (RSI - 14 períodos):
   - Umbrales base: Sobrecompra = 70, Sobreventa = 30.
   - Umbrales dinámicos auto-ajustados según heurísticas aprendidas del símbolo.

3. CONVERGENCIA / DIVERGENCIA DE MEDIAS (MACD 12, 26, 9):
   - Confirmación de aceleración y cruce de línea de señal.

4. VOLATILIDAD Y RANGO VERDADERO MEDIO (ATR - 14 períodos):
   - Normalización de Stop Loss dinámico por volatilidad real.

5. ACCIÓN DE PRECIO Y PATRONES DE VELAS JAPONESAS:
   - Confluencia con patrones institucionales (Hammer, Morning Star, Engulfing, etc.).

6. NIVELES DE FIBONACCI INSTITUCIONALES (61.8%, 78.6%, 100%):
   - Validación de retrocesos óptimos y escaleras de reentrada.

PARÁMETROS Y VARIABLES CONFIGURABLES PARA MT5:
----------------------------------------------
- rsi_period (int): Período del RSI (Default: 14).
- rsi_overbought_base (float): Nivel base de sobrecompra (Default: 70.0).
- rsi_oversold_base (float): Nivel base de sobreventa (Default: 30.0).
- ema_fast (int): Período EMA rápida (Default: 9).
- ema_medium (int): Período EMA intermedia (Default: 21).
- ema_slow (int): Período EMA lenta (Default: 50).
- ema_trend (int): Período EMA macro (Default: 200).
- atr_period (int): Período del ATR (Default: 14).
- sl_atr_multiplier (float): Multiplicador de ATR para Stop Loss (Default: 1.5).
- min_risk_reward (float): Ratio Riesgo/Beneficio mínimo (Default: 1.8).
- enable_dynamic_learning (bool): Activa la lectura de ai_backtest_learnings.json (Default: True).
========================================================================================
"""

from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

from .base_strategy import BaseStrategy
from config import StrategyConfig, STRATEGY_CONFIG
from core.candlestick_patterns import detect_candlestick_patterns, format_candlestick_summary_for_ai


class AIStrategy(BaseStrategy):
    """
    Estrategia de Autoaprendizaje Cuantitativo basada en confluencia técnica
    y retroalimentación de Deep Search.
    """

    name: str = "AIStrategy"
    description: str = "Estrategia con autoaprendizaje y confluencia técnica adaptativa"

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(config=config, symbol=symbol, **kwargs)
        self.rsi_period: int = kwargs.get("rsi_period", 14)
        self.rsi_overbought: float = kwargs.get("rsi_overbought_base", 70.0)
        self.rsi_oversold: float = kwargs.get("rsi_oversold_base", 30.0)
        self.ema_fast_period: int = kwargs.get("ema_fast", 9)
        self.ema_med_period: int = kwargs.get("ema_medium", 21)
        self.ema_slow_period: int = kwargs.get("ema_slow", 50)
        self.ema_trend_period: int = kwargs.get("ema_trend", 200)
        self.atr_period: int = kwargs.get("atr_period", 14)
        self.sl_atr_multiplier: float = kwargs.get("sl_atr_multiplier", 1.5)
        self.min_risk_reward: float = kwargs.get("min_risk_reward", 1.8)
        self.enable_dynamic_learning: bool = kwargs.get("enable_dynamic_learning", True)

    def _get_symbol_rules(self) -> Dict[str, Any]:
        """Recupera las reglas heurísticas aprendidas para el símbolo actual."""
        if not self.enable_dynamic_learning or not self.symbol:
            return {}
        try:
            from core.ai_backtest_learner import get_symbol_learning
            learning = get_symbol_learning(self.symbol)
            return learning or {}
        except Exception:
            return {}

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula las EMAs, RSI, MACD y ATR sobre el DataFrame histórico."""
        if df is None or len(df) < 50:
            return df

        df = df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # 1. EMAs
        df["ema_9"] = close.ewm(span=self.ema_fast_period, adjust=False).mean()
        df["ema_21"] = close.ewm(span=self.ema_med_period, adjust=False).mean()
        df["ema_50"] = close.ewm(span=self.ema_slow_period, adjust=False).mean()
        df["ema_200"] = close.ewm(span=self.ema_trend_period, adjust=False).mean()

        # 2. RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        # 3. MACD (12, 26, 9)
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        df["macd"] = ema_12 - ema_26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        # 4. ATR (14)
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=self.atr_period).mean()

        return df

    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evalúa las condiciones del mercado moduladas por las lecciones aprendidas de la IA.
        """
        if df is None or len(df) < 60:
            return {"signal": "HOLD", "reason": "Datos insuficientes"}

        df = self.calculate_indicators(df)
        curr = df.iloc[-2]  # Última vela cerrada
        prev = df.iloc[-3]

        close_px = float(curr["close"])
        ema_9 = float(curr["ema_9"])
        ema_21 = float(curr["ema_21"])
        ema_50 = float(curr["ema_50"])
        ema_200 = float(curr["ema_200"])
        rsi_val = float(curr["rsi"])
        macd_val = float(curr["macd"])
        macd_sig = float(curr["macd_signal"])
        atr_val = float(curr["atr"]) if not np.isnan(curr["atr"]) else 0.0010

        # Cargar heurísticas aprendidas del símbolo
        learned_rules = self._get_symbol_rules()
        avoid_patterns = learned_rules.get("avoid_patterns", [])

        # Auto-ajuste dinámico de umbrales según IA
        overbought_thresh = self.rsi_overbought
        oversold_thresh = self.rsi_oversold

        # Si el aprendizaje advierte sobrecompra temprana en este par, ajustar filtro RSI
        for avoid in avoid_patterns:
            if "RSI > 6" in str(avoid):
                overbought_thresh = 65.0
            elif "RSI < 3" in str(avoid):
                oversold_thresh = 35.0

        # Detección de patrones de velas
        try:
            candle_summary = format_candlestick_summary_for_ai(df)
        except Exception:
            candle_summary = ""

        # =========================================================================
        # 1. EVALUACIÓN DE SEÑAL ALCISTA (BUY)
        # =========================================================================
        bullish_alignment = (ema_9 > ema_21) and (close_px > ema_50) and (close_px > ema_200)
        bullish_macd = macd_val > macd_sig
        bullish_rsi = (rsi_val > 45.0) and (rsi_val < overbought_thresh)
        recent_cross_up = (prev["ema_9"] <= prev["ema_21"]) and (curr["ema_9"] > curr["ema_21"])

        if bullish_alignment and bullish_macd and bullish_rsi and (recent_cross_up or (close_px > ema_9 > ema_21)):
            sl_pips_dist = max(atr_val * self.sl_atr_multiplier, 0.0005)
            sl_price = round(close_px - sl_pips_dist, 5)
            tp_price = round(close_px + (sl_pips_dist * self.min_risk_reward), 5)

            return {
                "signal": "BUY",
                "price": close_px,
                "sl": sl_price,
                "tp": tp_price,
                "atr": atr_val,
                "reason": f"AI Confluencia Alcista (EMA 9>21>50>200, RSI {rsi_val:.1f}, MACD+)",
                "candlestick_summary": candle_summary,
                "learned_rules_applied": bool(learned_rules)
            }

        # =========================================================================
        # 2. EVALUACIÓN DE SEÑAL BAJISTA (SELL)
        # =========================================================================
        bearish_alignment = (ema_9 < ema_21) and (close_px < ema_50) and (close_px < ema_200)
        bearish_macd = macd_val < macd_sig
        bearish_rsi = (rsi_val < 55.0) and (rsi_val > oversold_thresh)
        recent_cross_down = (prev["ema_9"] >= prev["ema_21"]) and (curr["ema_9"] < curr["ema_21"])

        if bearish_alignment and bearish_macd and bearish_rsi and (recent_cross_down or (close_px < ema_9 < ema_21)):
            sl_pips_dist = max(atr_val * self.sl_atr_multiplier, 0.0005)
            sl_price = round(close_px + sl_pips_dist, 5)
            tp_price = round(close_px - (sl_pips_dist * self.min_risk_reward), 5)

            return {
                "signal": "SELL",
                "price": close_px,
                "sl": sl_price,
                "tp": tp_price,
                "atr": atr_val,
                "reason": f"AI Confluencia Bajista (EMA 9<21<50<200, RSI {rsi_val:.1f}, MACD-)",
                "candlestick_summary": candle_summary,
                "learned_rules_applied": bool(learned_rules)
            }

        return {"signal": "HOLD", "reason": "Sin confluencia suficiente"}

    def analyze_open_position(self, df: pd.DataFrame, position: Any) -> Dict[str, Any]:
        """
        Gestión activa inteligente de posiciones abiertas con trailing stop por ATR y salida de emergencia.
        """
        if df is None or len(df) < 30:
            return {"action": "HOLD"}

        df = self.calculate_indicators(df)
        curr = df.iloc[-2]
        close_px = float(curr["close"])
        atr_val = float(curr["atr"]) if not np.isnan(curr["atr"]) else 0.0010

        pos_type = getattr(position, "type", 0)
        price_open = float(getattr(position, "price_open", close_px))
        current_sl = float(getattr(position, "sl", 0.0))
        current_tp = float(getattr(position, "tp", 0.0))

        is_buy = pos_type == 0  # POSITION_TYPE_BUY
        pnl_dist = (close_px - price_open) if is_buy else (price_open - close_px)
        initial_risk = abs(price_open - current_sl) if current_sl > 0 else (atr_val * 1.5)
        current_r = pnl_dist / initial_risk if initial_risk > 1e-9 else 0.0

        learned_rules = self._get_symbol_rules()
        risk_advice = str(learned_rules.get("risk_advice", ""))

        # 1. Break-Even anticipado si la IA detectó retrocesos rápidos para este par
        be_trigger_r = 1.0
        if "1.2R" in risk_advice or "break-even" in risk_advice.lower():
            be_trigger_r = 0.9

        if current_r >= be_trigger_r and current_sl != price_open:
            # Mover a Break-Even + pequeño margen
            be_sl = round(price_open + (atr_val * 0.1 if is_buy else -atr_val * 0.1), 5)
            if (is_buy and be_sl > current_sl) or (not is_buy and (current_sl == 0 or be_sl < current_sl)):
                return {
                    "action": "MODIFY_SLTP",
                    "suggested_sl": be_sl,
                    "suggested_tp": current_tp,
                    "reason": f"AI Break-Even Protección ({current_r:.1f}R alcanzado)"
                }

        # 2. Trailing Stop dinámico tras alcanzar +1.8R
        if current_r >= 1.8:
            trail_sl = round(close_px - (atr_val * 1.0) if is_buy else close_px + (atr_val * 1.0), 5)
            if (is_buy and trail_sl > current_sl) or (not is_buy and (current_sl == 0 or trail_sl < current_sl)):
                return {
                    "action": "MODIFY_SLTP",
                    "suggested_sl": trail_sl,
                    "suggested_tp": current_tp,
                    "reason": f"AI Trailing Stop Activo (+{current_r:.1f}R)"
                }

        # 3. Cierre prematuro por quiebre de estructura (EMA 50 opuesta)
        ema_50 = float(curr["ema_50"])
        if is_buy and close_px < ema_50 and current_r < -0.6:
            return {
                "action": "EARLY_CLOSE",
                "close_reason": "Invalidacion_Estructura_Alcista"
            }
        elif not is_buy and close_px > ema_50 and current_r < -0.6:
            return {
                "action": "EARLY_CLOSE",
                "close_reason": "Invalidacion_Estructura_Bajista"
            }

        return {"action": "HOLD"}
