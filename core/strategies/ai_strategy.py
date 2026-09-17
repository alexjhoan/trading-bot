"""
========================================================================================
ESTRATEGIA CUANTITATIVA EVOLUTIVA: AI-STRATEGY (FUSIÓN FOREX FIBONACCI + AUTOAPRENDIZAJE)
========================================================================================

DESCRIPCIÓN Y FUNCIONAMIENTO DE LA ESTRATEGIA:
----------------------------------------------
AIStrategy es una estrategia híbrida cuantitativa con autoaprendizaje continuo diseñada para
operar en MetaTrader 5 (MT5). Fusiona la solidez matemática de acción del precio y retrocesos
de Fibonacci de `forex.py` con el motor adaptativo de inteligencia artificial y memoria
persistente (`ai_backtest_learnings.json` y `trade_memory.json`).

OBJETIVO CUANTITATIVO:
Superar el 60% de efectividad (Win Rate) y maximizar el ratio ganancia/pérdida (R:R >= 1.8)
eliminando entradas en ruido lateral y sobreextensiones, restringiendo reentradas arriesgadas y
ejecutando una gestión activa de Break-Even y trailing stops dinámicos.

PILARES DE LA ESTRATEGIA:
1. ESTRUCTURA Y GATILLO DE ENTRADA (Basada en forex.py):
   - Tendencia Macro: Determinada por la EMA 200 con buffer de entrada configurable.
   - Confirmación Multi-Temporal (HTF): Verifica alineación con marcos temporales mayores
     (M15/H1/H4) mediante cache en memoria para garantizar scalping/intradía a favor del flujo institucional.
   - Retroceso Fibonacci 61.8%: El precio debe retroceder a la zona de descuento óptimo (OTE)
     entre swing high (resistencia) y swing low (soporte).
   - Score de Confluencia Institucional: Evalúa 4 factores clave:
       (1) Tendencia macro EMA 200
       (2) Volumen institucional por encima de su media móvil (SMA 20)
       (3) Patrón de vela de confirmación (Hammer, Shooting Star, Engulfing o vela con cuerpo >= 50%)
       (4) Estocástico (K <= 35 o cruce alcista para compras; K >= 65 o cruce bajista para ventas)
   - Filtro de Tendencia / Lateralidad (ADX): Bloquea nuevas entradas si el ADX está por debajo
     del umbral de tendencia, evitando mercados en rango o consolidación errática.
   - Filtro de Sobreextensión: Evita comprar en techos o vender en suelos si el precio se aleja
     más del 50% del rango del swing respecto a la EMA 200.

2. REGLA ESTRICTA DE REENTRADAS (Corrección de la Escalera Fibo):
   - Se ELIMINAN por completo las reentradas peligrosas en niveles >= 100%, 132% y 161.8%
     que promediaban pérdidas contra tendencias fuertes y destruían la cuenta.
   - Las reentradas quedan LIMITADAS ÚNICAMENTE hasta el nivel Fibonacci 78.6% (o Pullback dinámico
     a EMA 200) siempre y cuando la estructura macro no haya sido invalidada.
   - Incorpora control anti-spam por distancia ATR y número de velas transcurridas.

3. AUTOAPRENDIZAJE Y MODULACIÓN DINÁMICA DE LA IA:
   - Lectura en tiempo real de `ai_backtest_learnings.json` y `trade_memory.json` vía `_get_symbol_rules()`.
   - Modulación dinámica de umbrales RSI: Si el aprendizaje detecta trampas de sobrecompra/sobreventa
     o reversiones tempranas, ajusta dinámicamente los techos/pisos (ej. 65.0/35.0 en lugar de 70/30).
   - Modulación del umbral ADX: Incrementa la exigencia de tendencia en pares con alta tasa de whipsaws.
   - Modulación de la puntuación de confluencia (Score de 2/4 a 4/4): Si el par presenta un win-rate
     histórico bajo o patrones de trampa identificados, la exigencia sube a 3/4 o 4/4; en pares con
     alta fiabilidad y rendimiento constante, permite operar con 2/4 o 3/4.
   - Evaluación del sesgo en operaciones pasadas en memoria (`trade_memory.json`).

4. GESTIÓN ACTIVA Y SALIDAS INTELIGENTES:
   - Break-Even temprano por IA: Tras alcanzar +0.9R o +1.2R (según el consejo heurístico del par),
     mueve el Stop Loss al punto de entrada (+ margen de seguridad) para riesgo cero.
   - Trailing Stop Dinámico por ATR: A partir de +1.8R o avance favorable sustancial, asegura beneficios
     siguiendo los swings mínimos/máximos con un colchón basado en ATR.
   - Extensión de Take Profit por continuación Fibonacci (127.2% y 161.8%).
   - Cierre de Emergencia por Invalidación Estructural: Cierra inmediatamente si el precio quiebra
     la EMA 50 en contra de la posición con pérdida acumulada, o si rompe la EMA 200 con buffer ATR
     confirmando cambio de tendencia macro.

========================================================================================
VARIABLES PRINCIPALES Y PARÁMETROS CONFIGURABLES:
========================================================================================
- pivot_window (int): Ventana de velas a la izquierda/derecha para validar Pivot High / Low.
- lookback_swing (int): Cantidad de velas históricas para buscar los swings extremos de soporte y resistencia.
- atr_period (int): Período para el cálculo de volatilidad del Average True Range (ATR).
- atr_sl_mult (float): Multiplicador del ATR aplicado a la distancia del Stop Loss inicial.
- atr_tp_mult (float): Multiplicador del ATR aplicado a la distancia del Take Profit inicial.
- min_confluence_score (int): Puntuación base mínima de confluencias requeridas (1 a 4).
- min_risk_reward (float): Ratio mínimo Beneficio / Riesgo proyectado para aprobar una orden.
- ema_fast_period (int): Período de la EMA rápida (ej. 9) para evaluar aceleración a corto plazo.
- ema_med_period (int): Período de la EMA intermedia (ej. 21) para evaluar alineación de tendencia.
- ema_slow_period (int): Período de la EMA lenta (ej. 50) para soporte dinámico e invalidación estructural.
- ema_trend_period (int): Período de la EMA macro (ej. 200) como filtro direccional institucional.
- ema_buffer_pct (float): Tolerancia en % de ATR para respiración / cierre por invalidación en EMA 200.
- ema_entry_buffer_pct (float): Margen más estricto en % de ATR para validar nuevas entradas.
- rsi_period (int): Período del oscilador RSI (Relative Strength Index).
- rsi_overbought_base (float): Nivel de sobrecompra base (modulado dinámicamente por la IA).
- rsi_oversold_base (float): Nivel de sobreventa base (modulado dinámicamente por la IA).
- adx_period (int): Período del Average Directional Index para cuantificar la fuerza de la tendencia.
- adx_trend_threshold (float): Umbral mínimo de ADX para evitar operar en consolidaciones o rangos.
- volume_ma_period (int): Período de la media móvil de volumen para detectar volumen institucional.
- use_htf_confirmation (bool): Activa la verificación de tendencia en marcos de tiempo superiores (HTF).
- use_session_filter (bool): Activa el filtro de horarios operativos por sesión de divisa.
- enable_dynamic_learning (bool): Activa la lectura y modulación por IA desde archivos de aprendizaje.
- max_reentries (int): Límite máximo de reentradas permitidas por posición (0 a 3, máx nivel 78.6%).
========================================================================================
"""

from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime, time
import time as time_module
import numpy as np
import pandas as pd
import pandas_ta as ta
import MetaTrader5 as mt5

from .base_strategy import BaseStrategy
from config import StrategyConfig, STRATEGY_CONFIG
from core.candlestick_patterns import detect_candlestick_patterns, format_candlestick_summary_for_ai

# Cache en memoria para confirmación multi-temporal (símbolo, timeframe_superior)
_HTF_TREND_CACHE: Dict[Tuple[str, int], Dict[str, Any]] = {}


class AIStrategy(BaseStrategy):
    """
    Estrategia Cuantitativa Adaptativa con Autoaprendizaje Heurístico e Integración
    de la Acción del Precio, Fibonacci 61.8%/78.6% y Filtro Multitemporal (HTF).
    """

    name: str = "ai_strategy"
    description: str = (
        "Estrategia IA Adaptativa: Fibo 61.8%/78.6% + Confluencia Dinámica (2-4/4) + "
        "Filtro HTF + Aprendizaje Continuo (Backtest/Memoria) + Break-Even y Trailing ATR"
    )

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

        # 1. Parámetros de Estructura y Pivotes
        self.pivot_window: int = pivot_window
        self.lookback_swing: int = kwargs.get("lookback_swing", 50)
        self.volume_ma_period: int = volume_ma_period

        # 2. Medias Móviles y Tendencia
        self.ema_fast_period: int = kwargs.get("ema_fast", 9)
        self.ema_med_period: int = kwargs.get("ema_medium", 21)
        self.ema_slow_period: int = kwargs.get("ema_slow", 50)
        self.ema_trend_period: int = kwargs.get("ema_trend", kwargs.get("ema_trend_period", 200))
        self.ema_buffer_pct: float = getattr(self.config, "ema_buffer_pct", kwargs.get("ema_buffer_pct", 0.20))
        self.ema_entry_buffer_pct: float = getattr(
            self.config,
            "ema_entry_buffer_pct",
            kwargs.get("ema_entry_buffer_pct", self.ema_buffer_pct * 0.5)
        )

        # 3. Osciladores y Filtros
        self.rsi_period: int = rsi_period
        self.rsi_overbought_base: float = kwargs.get("rsi_overbought_base", 70.0)
        self.rsi_oversold_base: float = kwargs.get("rsi_oversold_base", 30.0)
        self.adx_period: int = getattr(self.config, "adx_period", kwargs.get("adx_period", 14))
        self.adx_trend_threshold_base: float = getattr(
            self.config,
            "adx_trend_threshold",
            kwargs.get("adx_trend_threshold", 20.0)
        )

        # 4. Parámetros Cuantitativos de Gestión de Riesgo y ATR
        self.atr_period: int = atr_period
        self.atr_sl_mult: float = kwargs.get("atr_sl_mult", kwargs.get("sl_atr_multiplier", 1.5))
        self.atr_tp_mult: float = kwargs.get("atr_tp_mult", 3.0)
        self.min_risk_reward: float = kwargs.get("min_risk_reward", 1.8)
        self.static_sl_pips: float = kwargs.get("static_sl_pips", 20.0)
        self.static_tp_pips: float = kwargs.get("static_tp_pips", 40.0)

        # 5. Confluencia y Reentradas
        self.base_confluence_score: int = min_confluence_score
        # Límite máximo estricto de reentradas por diseño cuantitativo (máximo nivel 78.6%)
        self.max_reentries: int = getattr(self.config, "max_reentries", kwargs.get("max_reentries", 0))

        # 6. Autoaprendizaje Heurístico e Integración con IA
        self.enable_dynamic_learning: bool = kwargs.get("enable_dynamic_learning", True)
        self.use_htf_confirmation: bool = kwargs.get("use_htf_confirmation", True)
        self.use_session_filter: bool = getattr(self.config, "use_session_filter", use_session_filter)

        # 7. Horarios de Sesión Dinámicos
        start_str, end_str = self.config.get_session_times_for_symbol(self.symbol)
        self.session_start: time = datetime.strptime(start_str, "%H:%M").time()
        self.session_end: time = datetime.strptime(end_str, "%H:%M").time()

    # =========================================================================
    # 🧠 MÓDULO DE AUTOAPRENDIZAJE Y MODULACIÓN DINÁMICA POR IA
    # =========================================================================

    def _get_symbol_rules(self) -> Dict[str, Any]:
        """
        Recupera de forma segura el conocimiento consolidado de Deep Search
        (ai_backtest_learnings.json) y el historial de trade_memory.json
        específico para el símbolo actual.
        """
        if not self.enable_dynamic_learning or not self.symbol:
            return {}

        rules: Dict[str, Any] = {
            "backtest_learnings": {},
            "recent_memory": [],
            "avoid_patterns": [],
            "risk_advice": "",
            "win_rate": 50.0,
            "avg_r": 0.0,
            "trades_count": 0,
            "optimal_tf": "",
            "is_high_performer": False,
            "is_low_performer": False,
        }

        # 1. Cargar aprendizaje de backtest consolidado
        try:
            from core.ai_backtest_learner import get_symbol_learning
            learning = get_symbol_learning(self.symbol)
            if learning:
                rules["backtest_learnings"] = learning
                rules["avoid_patterns"] = learning.get("avoid_patterns", [])
                rules["risk_advice"] = learning.get("risk_advice", "")
                rules["win_rate"] = float(learning.get("win_rate", 50.0))
                rules["avg_r"] = float(learning.get("avg_r", 0.0))
                rules["trades_count"] = int(learning.get("trades", 0))
                rules["optimal_tf"] = str(learning.get("optimal_tf", ""))

                if rules["win_rate"] >= 65.0 and rules["avg_r"] >= 0.5 and rules["trades_count"] >= 5:
                    rules["is_high_performer"] = True
                elif (rules["win_rate"] < 45.0 or rules["avg_r"] < -0.2) and rules["trades_count"] >= 5:
                    rules["is_low_performer"] = True
        except Exception as e:
            self._log(f"⚠️ Error cargando ai_backtest_learnings para {self.symbol}: {e}", "DEBUG")

        # 2. Cargar memoria viva reciente de trade_memory.json
        try:
            from core.ai_memory import AIMemoryManager
            memory_mgr = AIMemoryManager()
            past_trades = memory_mgr.get_relevant_past_trades(symbol=self.symbol, limit=6)
            rules["recent_memory"] = past_trades
        except Exception as e:
            self._log(f"⚠️ Error cargando trade_memory para {self.symbol}: {e}", "DEBUG")

        return rules

    def _get_dynamic_thresholds(self, learned_rules: Dict[str, Any]) -> Dict[str, Any]:
        """
        Modula dinámicamente los parámetros operativos para el símbolo:
        - Umbrales de RSI (Sobrecompra / Sobreventa).
        - Umbral de ADX para filtro de lateralidad.
        - Puntuación mínima de confluencia (Score de 2/4 a 4/4).
        - Multiplicador de Stop Loss / Take Profit.
        - Gatillo de Break-Even en R.
        """
        # Valores por defecto base
        rsi_ob = float(self.rsi_overbought_base)
        rsi_os = float(self.rsi_oversold_base)
        adx_thresh = float(self.adx_trend_threshold_base)
        confluence_req = int(self.base_confluence_score)
        be_trigger_r = 1.0
        applied_notes: List[str] = []

        if not learned_rules:
            return {
                "rsi_overbought": rsi_ob,
                "rsi_oversold": rsi_os,
                "adx_threshold": adx_thresh,
                "min_confluence": max(2, min(confluence_req, 4)),
                "be_trigger_r": be_trigger_r,
                "notes": ["Configuración Estándar Base"]
            }

        avoid_patterns = [str(x) for x in learned_rules.get("avoid_patterns", [])]
        risk_advice = str(learned_rules.get("risk_advice", ""))
        win_rate = float(learned_rules.get("win_rate", 50.0))
        is_high_perf = bool(learned_rules.get("is_high_performer", False))
        is_low_perf = bool(learned_rules.get("is_low_performer", False))

        # 1. Modulación de RSI según trampas detectadas
        for avoid in avoid_patterns:
            avoid_upper = avoid.upper()
            if "RSI > 6" in avoid_upper or "SOBRECOMPRA" in avoid_upper:
                rsi_ob = min(rsi_ob, 65.0)
                applied_notes.append("Filtro RSI Sobrecompra Ajustado a 65.0")
            if "RSI < 3" in avoid_upper or "SOBREVENTA" in avoid_upper:
                rsi_os = max(rsi_os, 35.0)
                applied_notes.append("Filtro RSI Sobreventa Ajustado a 35.0")

        # 2. Modulación de ADX según tendencia y whipsaws
        for avoid in avoid_patterns:
            avoid_upper = avoid.upper()
            if "ADX" in avoid_upper or "LATERAL" in avoid_upper or "RANGO" in avoid_upper or "CONSOLIDACION" in avoid_upper:
                adx_thresh = max(adx_thresh, 23.0)
                applied_notes.append("Filtro ADX Exigente: 23.0 (Evitar Rango)")

        # 3. Modulación de Puntuación de Confluencia (Score 2/4 a 4/4)
        if is_low_perf or win_rate < 45.0:
            # En pares débiles o con pérdidas, exigir máxima confluencia estricta
            confluence_req = 4
            adx_thresh = max(adx_thresh, 24.0)
            applied_notes.append("Exigencia Confluencia Máxima 4/4 (Bajo Win Rate Histórico)")
        elif is_high_perf and win_rate >= 70.0:
            # En pares con alta consistencia institucional demostrada, permitir entradas con 2/4 o 3/4
            confluence_req = 2
            applied_notes.append("Exigencia Confluencia Flexible 2/4 (Par Altamente Consistente)")
        else:
            confluence_req = 3
            applied_notes.append("Exigencia Confluencia Equilibrada 3/4")

        # 4. Modulación de Break-Even según consejo del par
        if "0.9R" in risk_advice or "BREAK-EVEN TEMPRANO" in risk_advice.upper() or "RETROCESOS RAPIDOS" in risk_advice.upper():
            be_trigger_r = 0.9
            applied_notes.append("Break-Even Rápido Activado a +0.9R")
        elif "1.2R" in risk_advice or "1.5R" in risk_advice:
            be_trigger_r = 1.2
            applied_notes.append("Break-Even Calibrado a +1.2R")

        return {
            "rsi_overbought": rsi_ob,
            "rsi_oversold": rsi_os,
            "adx_threshold": adx_thresh,
            "min_confluence": max(2, min(confluence_req, 4)),
            "be_trigger_r": be_trigger_r,
            "notes": applied_notes
        }

    # =========================================================================
    # ⏱️ FILTROS MULTITEMPORALES (HTF) Y SESIONES
    # =========================================================================

    def _is_within_session(self, current_time: time) -> bool:
        """Valida si la hora actual está dentro de la ventana operativa del símbolo."""
        if self.session_start <= self.session_end:
            return self.session_start <= current_time <= self.session_end
        else:
            return current_time >= self.session_start or current_time <= self.session_end

    def _infer_timeframe_seconds(self, df: pd.DataFrame) -> int:
        """Infiere la temporalidad (en segundos) de las velas a partir de sus timestamps."""
        try:
            if "time" in df.columns and len(df) >= 3:
                deltas = df["time"].diff().dropna()
                deltas = deltas[deltas > 0]
                if len(deltas) > 0:
                    return int(deltas.median())
        except Exception:
            pass
        return 300  # Fallback a M5 (300 segundos)

    def _pick_htf_constant(self, tf_seconds: int) -> int:
        """Determina el marco temporal superior (HTF) según el timeframe de entrada."""
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
        Verifica la tendencia en temporalidad superior para no operar en contra
        del flujo institucional macro. Utiliza cache en memoria para rendimiento óptimo.
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
            mt5.TIMEFRAME_M15: "M15",
            mt5.TIMEFRAME_H1: "H1",
            mt5.TIMEFRAME_H4: "H4",
            mt5.TIMEFRAME_D1: "D1",
        }.get(htf_constant, "TF Superior")

        try:
            rates = mt5.copy_rates_from_pos(self.symbol, htf_constant, 0, 250)
            if rates is None or len(rates) < self.ema_trend_period + 5:
                result = (True, True, f"Datos insuficientes en {tf_label}, filtro HTF omitido")
            else:
                htf_df = pd.DataFrame(rates)
                htf_ema = ta.ema(close=htf_df["close"], length=self.ema_trend_period)
                htf_close = float(htf_df["close"].iloc[-1])
                htf_ema_val = (
                    float(htf_ema.iloc[-1])
                    if htf_ema is not None and not pd.isna(htf_ema.iloc[-1])
                    else htf_close
                )
                is_htf_bullish = htf_close >= htf_ema_val
                reason = (
                    f"Tendencia {tf_label}: {'Alcista' if is_htf_bullish else 'Bajista'} "
                    f"(Cierre {htf_close:.5f} vs EMA{self.ema_trend_period} {htf_ema_val:.5f})"
                )
                result = (is_htf_bullish, not is_htf_bullish, reason)
        except Exception:
            result = (True, True, f"Error consultando {tf_label}, filtro HTF omitido")

        _HTF_TREND_CACHE[cache_key] = {
            "allow_buy": result[0],
            "allow_sell": result[1],
            "reason": result[2],
            "fetched_at": now,
        }
        return result

    # =========================================================================
    # 📊 CÁLCULO DE INDICADORES TÉCNICOS INTEGRADOS
    # =========================================================================

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula toda la batería de indicadores cuantitativos integrados:
        - Pivotes en tiempo real y Swings extremos (Soporte / Resistencia).
        - Niveles de Fibonacci Institucionales (61.8% entrada, 78.6% reentrada máxima).
        - Cinta de EMAs (9, 21, 50, 200).
        - Oscilador RSI (14) y MACD (12, 26, 9).
        - Oscilador Estocástico (14, 3, 3) para confirmación de rebotes.
        - Filtro de Fuerza de Tendencia ADX (14).
        - Volatilidad ATR (14) y Volumen Institucional vs SMA 20.
        - Patrones de Vela Japonesa (Hammer, Shooting Star, Ratios de Cuerpo).
        """
        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period, self.ema_trend_period) + 10
        if df is None or len(df) < min_bars:
            return df if df is not None else pd.DataFrame()

        df = df.copy()
        w = self.pivot_window

        # 1. Pivotes High / Low y Swings Dinámicos
        df["pivot_high"] = np.nan
        df["pivot_low"] = np.nan

        rolling_max = df["high"].shift(1).rolling(window=w).max()
        rolling_min = df["low"].shift(1).rolling(window=w).min()

        is_pivot_high = (df["high"].shift(w) > rolling_max) & (df["high"].shift(w) > df["high"].rolling(window=w).max())
        is_pivot_low = (df["low"].shift(w) < rolling_min) & (df["low"].shift(w) < df["low"].rolling(window=w).min())

        df.loc[is_pivot_high, "pivot_high"] = df["high"].shift(w)
        df.loc[is_pivot_low, "pivot_low"] = df["low"].shift(w)

        df["resistance"] = df["pivot_high"].ffill()
        df["support"] = df["pivot_low"].ffill()

        rolling_swing_high = df["high"].rolling(window=self.lookback_swing, min_periods=1).max()
        rolling_swing_low = df["low"].rolling(window=self.lookback_swing, min_periods=1).min()

        df["resistance"] = df["resistance"].fillna(rolling_swing_high).bfill().ffill()
        df["support"] = df["support"].fillna(rolling_swing_low).bfill().ffill()

        # 2. Niveles de Fibonacci Institucionales (61.8% Entrada Base y 78.6% Límite Máximo de Reentrada)
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

        # 3. Medias Móviles Exponenciales (EMA Ribbon: 9, 21, 50, 200)
        df["ema_9"] = ta.ema(close=df["close"], length=self.ema_fast_period)
        df["ema_21"] = ta.ema(close=df["close"], length=self.ema_med_period)
        df["ema_50"] = ta.ema(close=df["close"], length=self.ema_slow_period)
        df["ema_trend"] = ta.ema(close=df["close"], length=self.ema_trend_period)
        df["ema_200"] = df["ema_trend"]

        # 4. Volatilidad ATR (14)
        df["atr"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=self.atr_period)

        # 5. Oscilador RSI (14)
        df["rsi"] = ta.rsi(close=df["close"], length=self.rsi_period)

        # 6. MACD (12, 26, 9)
        macd_df = ta.macd(close=df["close"], fast=12, slow=26, signal=9)
        if macd_df is not None and "MACD_12_26_9" in macd_df.columns:
            df["macd"] = macd_df["MACD_12_26_9"]
            df["macd_signal"] = macd_df["MACDs_12_26_9"]
            df["macd_hist"] = macd_df["MACDh_12_26_9"]
        else:
            df["macd"] = 0.0
            df["macd_signal"] = 0.0
            df["macd_hist"] = 0.0

        # 7. Filtro ADX (14)
        adx_df = ta.adx(high=df["high"], low=df["low"], close=df["close"], length=self.adx_period)
        adx_col = f"ADX_{self.adx_period}"
        df["adx"] = adx_df[adx_col] if adx_df is not None and adx_col in adx_df.columns else 0.0

        # 8. Oscilador Estocástico (14, 3, 3) para confirmar rebotes reales en zona Fibo
        stoch_df = ta.stoch(high=df["high"], low=df["low"], close=df["close"], k=14, d=3, smooth_k=3)
        if stoch_df is not None and "STOCHk_14_3_3" in stoch_df.columns:
            df["stoch_k"] = stoch_df["STOCHk_14_3_3"]
            df["stoch_d"] = stoch_df["STOCHd_14_3_3"]
        else:
            df["stoch_k"] = 50.0
            df["stoch_d"] = 50.0

        # 9. Volumen Institucional vs Media Móvil de Volumen (SMA 20)
        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        if vol_col in df.columns:
            df["vol_ma"] = ta.sma(df[vol_col], length=self.volume_ma_period)
            df["high_volume"] = df[vol_col] > df["vol_ma"]
        else:
            df["high_volume"] = True

        # 10. Métricas y Patrones de Velas
        candle_range = df["high"] - df["low"]
        candle_body = (df["close"] - df["open"]).abs()
        upper_wick = df["high"] - np.maximum(df["open"], df["close"])
        lower_wick = np.minimum(df["open"], df["close"]) - df["low"]

        df["body_ratio"] = np.where(candle_range > 0, candle_body / candle_range, 0.0)
        df["is_bullish_hammer"] = (lower_wick >= 2 * candle_body) & (upper_wick <= candle_body * 0.5) & (candle_range > 0)
        df["is_bearish_hammer"] = (upper_wick >= 2 * candle_body) & (lower_wick <= candle_body * 0.5) & (candle_range > 0)

        return df

    # =========================================================================
    # 🎯 GENERACIÓN DE SEÑALES PARA NUEVAS ENTRADAS
    # =========================================================================

    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evalúa el mercado y genera señales para nuevas entradas basadas en:
        1. Estado de mercado abierto y filtro horario por sesión.
        2. Modulación dinámica de parámetros por IA según aprendizaje del par.
        3. Filtro ADX modulado para descartar rangos y baja volatilidad.
        4. Filtro de sobreextensión vs EMA 200 (< 50% del swing range).
        5. Tendencia Macro EMA 200 con buffer de entrada y filtro HTF (M15/H1/H4).
        6. Gatillo de retroceso Fibonacci 61.8% en zona de descuento OTE.
        7. Sistema de Confluencia Institucional Calibrado (Score 2/4 a 4/4):
           - Tendencia macro EMA 200 + alineación HTF.
           - Volumen institucional por encima de su SMA 20.
           - Patrón de vela de rechazo/fuerza (Hammer, Engulfing, cuerpo >= 50%).
           - Confirmación por Estocástico (sobreventa/sobrecompra o cruce de momentum).
        """
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
                "reason": "Insuficiente historial de datos para evaluación técnica"
            }

        # 1. EVALUACIÓN DE MERCADO ABIERTO
        now_dt = datetime.now()
        market_open, open_reason = self.config.is_market_open(self.symbol, now_dt)
        if not market_open:
            return {
                "signal": "HOLD",
                "support": 0.0,
                "resistance": 0.0,
                "atr": 0.0,
                "score": 0,
                "sl": 0.0,
                "tp": 0.0,
                "reason": open_reason
            }

        df_analyzed = self.calculate_indicators(df)
        curr_candle = df_analyzed.iloc[-2]  # Última vela cerrada para evitar repintado

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

        # 3. MODULACIÓN DINÁMICA POR APRENDIZAJE IA
        learned_rules = self._get_symbol_rules()
        thresholds = self._get_dynamic_thresholds(learned_rules)
        adx_threshold = thresholds["adx_threshold"]
        min_confluence = thresholds["min_confluence"]
        rsi_overbought = thresholds["rsi_overbought"]
        rsi_oversold = thresholds["rsi_oversold"]

        # 4. FILTRO DE TENDENCIA Y LATERALIDAD ADX
        current_adx = float(curr_candle.get("adx", 0.0) if not pd.isna(curr_candle.get("adx", 0.0)) else 0.0)
        if current_adx > 0 and current_adx < adx_threshold:
            return {
                "signal": "HOLD",
                "support": 0.0,
                "resistance": 0.0,
                "atr": float(curr_candle.get("atr", 0.0)),
                "score": 0,
                "sl": 0.0,
                "tp": 0.0,
                "reason": f"[Filtro ADX] Mercado lateral/sin tendencia clara (ADX {current_adx:.1f} < {adx_threshold:.1f}). Nuevas entradas bloqueadas."
            }

        curr_close = float(curr_candle["close"])
        raw_res = curr_candle.get("resistance", np.nan)
        raw_sup = curr_candle.get("support", np.nan)
        resistance = float(curr_close * 1.001 if pd.isna(raw_res) else raw_res)
        support = float(curr_close * 0.999 if pd.isna(raw_sup) else raw_sup)
        current_atr = float(curr_candle.get("atr", 0.0) if not pd.isna(curr_candle.get("atr", 0.0)) else 0.0010)
        ema_trend = float(curr_candle.get("ema_trend", curr_close) if not pd.isna(curr_candle.get("ema_trend", curr_close)) else curr_close)

        raw_fibo_buy = curr_candle.get("fibo_618_buy", 0.0)
        raw_fibo_sell = curr_candle.get("fibo_618_sell", 0.0)
        fibo_618_buy = float(0.0 if pd.isna(raw_fibo_buy) else raw_fibo_buy)
        fibo_618_sell = float(0.0 if pd.isna(raw_fibo_sell) else raw_fibo_sell)

        # 5. FILTRO DE SOBREEXTENSIÓN DE EMA 200 (Máximo 50% de distancia del swing)
        dist_to_ema = abs(curr_close - ema_trend)
        swing_span = abs(resistance - support)
        max_ema_distance = max(swing_span * 0.50, current_atr * 1.5) if swing_span > 0 else (current_atr * 1.5)

        if dist_to_ema > max_ema_distance:
            return {
                "signal": "HOLD",
                "support": support,
                "resistance": resistance,
                "atr": current_atr,
                "score": 0,
                "sl": 0.0,
                "tp": 0.0,
                "reason": (
                    f"[Filtro EMA] Precio sobreextendido ({curr_close:.5f}) muy lejos de EMA200 ({ema_trend:.5f}) "
                    f"[Distancia: {dist_to_ema:.5f} > 50% Rango: {max_ema_distance:.5f}]. Alto riesgo de reversión."
                )
            }

        # 6. VALIDACIÓN DE TENDENCIA MACRO CON BUFFER DE ENTRADA ESTRICTO
        ema_buffer = (current_atr * self.ema_entry_buffer_pct) if current_atr > 0 else (ema_trend * 0.0005)
        is_bullish_trend = curr_close >= (ema_trend - ema_buffer)
        is_bearish_trend = curr_close <= (ema_trend + ema_buffer)

        # 7. CONFIRMACIÓN MULTI-TEMPORAL (HTF)
        if self.use_htf_confirmation:
            htf_allows_buy, htf_allows_sell, htf_reason = self._get_htf_trend_alignment(df)
        else:
            htf_allows_buy, htf_allows_sell, htf_reason = True, True, "Confirmación multi-timeframe deshabilitada"

        # 8. GATILLO DE RETROCESO FIBONACCI 61.8%
        raw_fibo_buy_trigger = is_bullish_trend and (fibo_618_buy > 0) and (curr_close <= fibo_618_buy) and (curr_close >= support)
        raw_fibo_sell_trigger = is_bearish_trend and (fibo_618_sell > 0) and (curr_close >= fibo_618_sell) and (curr_close <= resistance)
        fibo_buy = raw_fibo_buy_trigger and htf_allows_buy
        fibo_sell = raw_fibo_sell_trigger and htf_allows_sell

        # 9. SISTEMA DE SCORE DE CONFLUENCIA INSTITUCIONAL (2/4 a 4/4)
        score = 0
        score_details: List[str] = []

        # Criterio 1: Tendencia Macro EMA 200 + HTF
        if fibo_buy:
            score += 1
            score_details.append(f"Tendencia Alcista Macro EMA{self.ema_trend_period} (+1)")
        elif fibo_sell:
            score += 1
            score_details.append(f"Tendencia Bajista Macro EMA{self.ema_trend_period} (+1)")

        # Criterio 2: Volumen Institucional Superior a Media
        vol_ok = bool(curr_candle.get("high_volume", False))
        if vol_ok:
            score += 1
            score_details.append("Volumen Institucional Alto (+1)")

        # Criterio 3: Patrón de Vela Japonesa de Rebote / Rechazo
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
            score_details.append(f"Patrón Vela: {patron_label} (+1)")
        elif fibo_sell and (candle_bias == "BEARISH" or is_bear_hammer or (body_ratio >= 0.50 and is_bear_candle)):
            patron_label = candle_pattern_name if candle_bias == "BEARISH" else ("Shooting Star" if is_bear_hammer else f"Vela Fuerte ({body_ratio * 100:.0f}%)")
            score += 1
            score_details.append(f"Patrón Vela: {patron_label} (+1)")

        # Criterio 4: Confirmación por Estocástico (Rebote real en zona Fibo)
        stoch_k = float(curr_candle.get("stoch_k", 50.0) if not pd.isna(curr_candle.get("stoch_k", 50.0)) else 50.0)
        stoch_d = float(curr_candle.get("stoch_d", 50.0) if not pd.isna(curr_candle.get("stoch_d", 50.0)) else 50.0)
        stoch_bull_ok = (stoch_k <= 35.0) or (stoch_k > stoch_d and stoch_k <= 50.0)
        stoch_bear_ok = (stoch_k >= 65.0) or (stoch_k < stoch_d and stoch_k >= 50.0)

        if fibo_buy and stoch_bull_ok:
            score += 1
            score_details.append(f"Estocástico Confirmado ({stoch_k:.0f}%) (+1)")
        elif fibo_sell and stoch_bear_ok:
            score += 1
            score_details.append(f"Estocástico Confirmado ({stoch_k:.0f}%) (+1)")

        # Criterio 5: Filtro Adicional de RSI Dinámico (Protección Anti-Agotamiento)
        curr_rsi = float(curr_candle.get("rsi", 50.0) if not pd.isna(curr_candle.get("rsi", 50.0)) else 50.0)
        if fibo_buy and curr_rsi > rsi_overbought:
            fibo_buy = False
            score_details.append(f"Bloqueo RSI Sobrecompra ({curr_rsi:.1f} > {rsi_overbought:.1f})")
        elif fibo_sell and curr_rsi < rsi_oversold:
            fibo_sell = False
            score_details.append(f"Bloqueo RSI Sobreventa ({curr_rsi:.1f} < {rsi_oversold:.1f})")

        # 10. RESOLUCIÓN DE SEÑAL FINAL
        if fibo_buy:
            signal_type = "BUY"
        elif fibo_sell:
            signal_type = "SELL"
        else:
            signal_type = "HOLD"

        is_valid = (signal_type != "HOLD") and (score >= min_confluence)
        final_signal = signal_type if is_valid else "HOLD"

        # 11. CÁLCULO DE STOP LOSS Y TAKE PROFIT CON RELACIÓN R:R ÓPTIMA (>= 1.8)
        sl_price = 0.0
        tp_price = 0.0

        if final_signal != "HOLD":
            point = 0.0001 if "JPY" not in self.symbol else 0.01
            if current_atr > 0:
                sl_dist = current_atr * self.atr_sl_mult
                # Garantizar mínimo de beneficio/riesgo configurado
                tp_dist = max(current_atr * self.atr_tp_mult, sl_dist * self.min_risk_reward)
            else:
                sl_dist = self.static_sl_pips * point
                tp_dist = self.static_tp_pips * point

            if final_signal == "BUY":
                sl_price = round(curr_close - sl_dist, 5)
                tp_price = round(curr_close + tp_dist, 5)
            elif final_signal == "SELL":
                sl_price = round(curr_close + sl_dist, 5)
                tp_price = round(curr_close - tp_dist, 5)

        htf_blocked = (raw_fibo_buy_trigger and not htf_allows_buy) or (raw_fibo_sell_trigger and not htf_allows_sell)

        notes_str = f" [IA: {', '.join(thresholds.get('notes', []))}]" if thresholds.get("notes") else ""
        if is_valid:
            reason = f"[AIStrategy] Fibo >= 61.8% ({signal_type}) con Confluencia {score}/{min_confluence}: {', '.join(score_details)}{notes_str}"
        elif htf_blocked:
            reason = f"[AIStrategy] Retroceso Fibo {'BUY' if raw_fibo_buy_trigger else 'SELL'} descartado por tendencia opuesta en TF superior ({htf_reason})"
        elif signal_type == "HOLD":
            reason = f"[AIStrategy] Esperando retroceso Fibo >= 61.8% alineado con EMA{self.ema_trend_period}{notes_str}"
        else:
            reason = f"[AIStrategy] Fibo {signal_type} descartado por confluencia insuficiente ({score}/{min_confluence} requerido){notes_str}"

        return {
            "signal": final_signal,
            "support": support,
            "resistance": resistance,
            "atr": current_atr,
            "score": score,
            "min_confluence_required": min_confluence,
            "sl": sl_price,
            "tp": tp_price,
            "reason": reason,
            "learned_rules_applied": bool(learned_rules)
        }

    # =========================================================================
    # ⚡ GESTIÓN ESTRICTA DE REENTRADAS (LIMITADA A NIVEL MÁXIMO 78.6%)
    # =========================================================================

    def evaluate_reentry_signal(
        self,
        df: pd.DataFrame,
        open_positions: List[Any],
        max_reentries: int = 0
    ) -> Dict[str, Any]:
        """
        Evalúa oportunidades de reentrada de alta probabilidad.

        REGLA DE ORO DE SEGURIDAD CUANTITATIVA (Anti-Martingala peligrosa):
        - Se eliminan por completo las reentradas en 100%, 132% y 161.8%.
        - Las reentradas quedan LIMITADAS ESTRICTAMENTE hasta el nivel Fibonacci 78.6%
          (o Pullback dinámico a EMA 200) y solo si la estructura macro se mantiene íntegra.

        RUTAS PERMITIDAS:
        1. RUTA A (Retroceso Profundo Fibo 78.6%):
           - Solo 1 reentrada en descuento institucional profundo (0.786).
           - Exige que el precio mejore el precio de entrada anterior y mantenga la EMA 200.
        2. RUTA B (Pullback Dinámico a EMA 200 a favor de tendencia):
           - El precio testea la EMA 200 sin violarla.
           - Confirmación con vela de fuerza/rechazo (Hammer, etc.).
           - Filtro Anti-Spam: Mínimo 3 velas y distancia >= 1.0 * ATR respecto a la orden previa.
        """
        if max_reentries <= 0 or not open_positions:
            return {"signal": "HOLD", "reason": "Reentradas deshabilitadas o sin posición base"}

        current_count = len(open_positions)
        # Límite cuantitativo: Nunca permitir más de 2 órdenes totales (1 orden base + 1 reentrada al 78.6%)
        # o el límite configurado si es menor
        effective_max = min(max_reentries, 1)
        if current_count >= (effective_max + 1):
            return {
                "signal": "HOLD",
                "reason": f"Límite de seguridad de reentradas alcanzado ({current_count - 1}/{effective_max}). Prohibidas reentradas más allá del 78.6%."
            }

        base_pos = open_positions[0]
        is_buy = getattr(base_pos, "type", 0) == mt5.POSITION_TYPE_BUY
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

        current_atr = float(curr_candle.get("atr", 0.0) if not pd.isna(curr_candle.get("atr", 0.0)) else 0.0010)
        ema_trend = float(curr_candle.get("ema_trend", curr_close))
        ema_buffer = (current_atr * self.ema_buffer_pct) if current_atr > 0 else (ema_trend * 0.002)
        ema_entry_buffer = (current_atr * self.ema_entry_buffer_pct) if current_atr > 0 else (ema_trend * 0.001)

        # Confluencias: Patrón de vela y Volumen
        vol_ok = bool(curr_candle.get("high_volume", False))
        body_ratio = float(curr_candle.get("body_ratio", 0.0))
        is_bull_hammer = bool(curr_candle.get("is_bullish_hammer", False))
        is_bear_hammer = bool(curr_candle.get("is_bearish_hammer", False))

        candlestick_info = detect_candlestick_patterns(df)
        candle_bias = candlestick_info.get("bias", "NEUTRAL")
        candle_pattern_name = candlestick_info.get("primary_pattern", "Vela")

        if is_buy:
            candle_confirmed = (candle_bias == "BULLISH") or is_bull_hammer or (body_ratio >= 0.40 and curr_close >= curr_open)
            patron_label = candle_pattern_name if candle_bias == "BULLISH" else ("Hammer Alcista" if is_bull_hammer else f"Rebote Vela ({body_ratio * 100:.0f}%)")
        else:
            candle_confirmed = (candle_bias == "BEARISH") or is_bear_hammer or (body_ratio >= 0.40 and curr_close <= curr_open)
            patron_label = candle_pattern_name if candle_bias == "BEARISH" else ("Shooting Star" if is_bear_hammer else f"Rechazo Vela ({body_ratio * 100:.0f}%)")

        # Control Anti-Spam (Tiempo y Distancia)
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
        # RUTA A: Retroceso Profundo Fibo 78.6% (ÚNICO NIVEL PERMITIDO)
        # -------------------------------------------------------------
        target_fibo_ratio = 0.786
        target_fibo_pct = 78.6

        route_a_valid = False
        route_a_score = 0
        route_a_details: List[str] = []
        route_a_reject = ""

        if is_buy:
            target_fibo_price = float(resistance - (swing_range * target_fibo_ratio))
            lowest_open_price = min(float(p.price_open) for p in open_positions)
            level_reached = (curr_close <= target_fibo_price) or (curr_low <= target_fibo_price)
            better_price = curr_close < lowest_open_price

            # La estructura macro NO debe estar rota
            macro_trend_intact = curr_close >= (ema_trend - ema_entry_buffer)

            if not macro_trend_intact:
                route_a_reject = f"Estructura macro alcista violada en EMA{self.ema_trend_period} ({curr_close:.5f} < {ema_trend - ema_entry_buffer:.5f})"
            elif not level_reached:
                route_a_reject = f"Precio ({curr_close:.5f}) aún no alcanza Fibo 78.6% ({target_fibo_price:.5f})"
            elif not better_price:
                route_a_reject = f"Precio ({curr_close:.5f}) no mejora precio previo ({lowest_open_price:.5f})"
            elif not anti_spam_passed:
                route_a_reject = f"Anti-spam bloqueado ({bars_since_last_pos} velas / {price_dist_atr:.1f} ATR)"
            else:
                route_a_score += 1
                route_a_details.append(f"Zona Fibo 78.6% sobre EMA{self.ema_trend_period} (+1)")
                if vol_ok:
                    route_a_score += 1
                    route_a_details.append("Volumen Institucional (+1)")
                if candle_confirmed:
                    route_a_score += 1
                    route_a_details.append(f"Patrón: {patron_label} (+1)")

                if route_a_score >= 2:
                    route_a_valid = True
                else:
                    route_a_reject = f"Score insuficiente ({route_a_score}/2)"
        else:
            target_fibo_price = float(support + (swing_range * target_fibo_ratio))
            highest_open_price = max(float(p.price_open) for p in open_positions)
            level_reached = (curr_close >= target_fibo_price) or (curr_high >= target_fibo_price)
            better_price = curr_close > highest_open_price

            macro_trend_intact = curr_close <= (ema_trend + ema_entry_buffer)

            if not macro_trend_intact:
                route_a_reject = f"Estructura macro bajista violada en EMA{self.ema_trend_period} ({curr_close:.5f} > {ema_trend + ema_entry_buffer:.5f})"
            elif not level_reached:
                route_a_reject = f"Precio ({curr_close:.5f}) aún no alcanza Fibo 78.6% ({target_fibo_price:.5f})"
            elif not better_price:
                route_a_reject = f"Precio ({curr_close:.5f}) no mejora precio previo ({highest_open_price:.5f})"
            elif not anti_spam_passed:
                route_a_reject = f"Anti-spam bloqueado ({bars_since_last_pos} velas / {price_dist_atr:.1f} ATR)"
            else:
                route_a_score += 1
                route_a_details.append(f"Zona Fibo 78.6% bajo EMA{self.ema_trend_period} (+1)")
                if vol_ok:
                    route_a_score += 1
                    route_a_details.append("Volumen Institucional (+1)")
                if candle_confirmed:
                    route_a_score += 1
                    route_a_details.append(f"Patrón: {patron_label} (+1)")

                if route_a_score >= 2:
                    route_a_valid = True
                else:
                    route_a_reject = f"Score insuficiente ({route_a_score}/2)"

        # -------------------------------------------------------------
        # RUTA B: Retroceso / Pullback Dinámico a EMA 200
        # -------------------------------------------------------------
        route_b_valid = False
        route_b_score = 0
        route_b_details: List[str] = []
        route_b_reject = ""

        if is_buy:
            is_macro_bullish = curr_close >= (ema_trend - ema_entry_buffer)
            touches_ema = (curr_low <= (ema_trend + ema_buffer)) and (curr_close >= (ema_trend - ema_entry_buffer))

            if not is_macro_bullish:
                route_b_reject = f"Precio ({curr_close:.5f}) bajo zona EMA{self.ema_trend_period}"
            elif not touches_ema:
                route_b_reject = f"Precio fuera de zona de pullback EMA{self.ema_trend_period} (EMA: {ema_trend:.5f} ± {ema_buffer:.5f})"
            elif not anti_spam_passed:
                route_b_reject = f"Anti-spam bloqueado ({bars_since_last_pos}/{min_bars_anti_spam} velas y {price_dist_atr:.2f}/{min_atr_dist_anti_spam:.1f} ATR)"
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

                if route_b_score >= 2:
                    route_b_valid = True
                else:
                    route_b_reject = f"Score insuficiente ({route_b_score}/2)"
        else:
            is_macro_bearish = curr_close <= (ema_trend + ema_entry_buffer)
            touches_ema = (curr_high >= (ema_trend - ema_buffer)) and (curr_close <= (ema_trend + ema_entry_buffer))

            if not is_macro_bearish:
                route_b_reject = f"Precio ({curr_close:.5f}) sobre zona EMA{self.ema_trend_period}"
            elif not touches_ema:
                route_b_reject = f"Precio fuera de zona de pullback EMA{self.ema_trend_period} (EMA: {ema_trend:.5f} ± {ema_buffer:.5f})"
            elif not anti_spam_passed:
                route_b_reject = f"Anti-spam bloqueado ({bars_since_last_pos}/{min_bars_anti_spam} velas y {price_dist_atr:.2f}/{min_atr_dist_anti_spam:.1f} ATR)"
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

                if route_b_score >= 2:
                    route_b_valid = True
                else:
                    route_b_reject = f"Score insuficiente ({route_b_score}/2)"

        # -------------------------------------------------------------
        # CÁLCULO DE NIVELES DE SALIDA PARA REENTRADA
        # -------------------------------------------------------------
        point = 0.0001 if "JPY" not in self.symbol else 0.01
        sl_dist = (current_atr * self.atr_sl_mult) if current_atr > 0 else (self.static_sl_pips * point)
        tp_dist = (current_atr * self.atr_tp_mult) if current_atr > 0 else (self.static_tp_pips * point)

        sl_price = round(curr_close - sl_dist if is_buy else curr_close + sl_dist, 5)
        tp_price = round(curr_close + tp_dist if is_buy else curr_close - tp_dist, 5)

        if route_a_valid:
            return {
                "signal": expected_signal,
                "is_reentry": True,
                "reentry_route": "FIBO_786",
                "reentry_tag": "Fibo 78.6%",
                "order_comment": f"AI Reentry #{current_count} Fibo 78.6%",
                "reentry_number": current_count,
                "max_reentries": effective_max,
                "fibo_level_pct": 78.6,
                "fibo_target_price": target_fibo_price,
                "support": support,
                "resistance": resistance,
                "atr": current_atr,
                "score": route_a_score,
                "sl": sl_price,
                "tp": tp_price,
                "reason": (
                    f"⚡ [REENTRADA CONTROLADA #{current_count}/{effective_max} - RUTA A: FIBO 78.6%] "
                    f"Nivel 78.6% {expected_signal} @ {curr_close:.5f} (Objetivo: {target_fibo_price:.5f}) "
                    f"con Confluencia: {', '.join(route_a_details)}"
                )
            }

        if route_b_valid:
            return {
                "signal": expected_signal,
                "is_reentry": True,
                "reentry_route": "EMA_PULLBACK",
                "reentry_tag": "EMA Pullback",
                "order_comment": f"AI Reentry #{current_count} EMA Pullback",
                "reentry_number": current_count,
                "max_reentries": effective_max,
                "fibo_level_pct": 78.6,
                "fibo_target_price": ema_trend,
                "support": support,
                "resistance": resistance,
                "atr": current_atr,
                "score": route_b_score,
                "sl": sl_price,
                "tp": tp_price,
                "reason": (
                    f"⚡ [REENTRADA CONTROLADA #{current_count}/{effective_max} - RUTA B: PULLBACK EMA{self.ema_trend_period}] "
                    f"{expected_signal} @ {curr_close:.5f} (EMA: {ema_trend:.5f} ± {ema_buffer:.5f}) "
                    f"con Confluencia: {', '.join(route_b_details)}"
                )
            }

        return {
            "signal": "HOLD",
            "reason": f"Reentrada #{current_count} en espera | Fibo 78.6%: {route_a_reject} | Pullback EMA: {route_b_reject}"
        }

    # =========================================================================
    # 🛡️ GESTIÓN ACTIVA Y DINÁMICA DE POSICIONES ABIERTAS (FUSIONADA)
    # =========================================================================

    def analyze_open_position(self, df: pd.DataFrame, position: Any) -> Dict[str, Any]:
        """
        Gestión activa inteligente de posiciones abiertas que combina:
        1. Break-Even Temprano (+0.9R o +1.2R según consejos de aprendizaje para el par).
        2. Trailing Stop Dinámico basado en ATR y mínimos/máximos para proteger beneficios acumulados.
        3. Extensión de Take Profit por continuación de tendencia y niveles de Fibonacci (127.2% / 161.8%).
        4. Cierre de Emergencia por Invalidación Estructural:
           - Quiebre y cierre del precio por debajo de la EMA 50 en compras (o por encima en ventas) con pérdida.
           - Violación de la EMA 200 con buffer de 20% de ATR (cambio de tendencia macro).
           - Confirmación de agotamiento extremo por RSI + patrón de reversión mayor.
        """
        min_bars = max(self.pivot_window * 2, self.atr_period, self.volume_ma_period, self.ema_trend_period) + 10
        if df is None or len(df) < min_bars:
            return {"action": "HOLD", "reason": "Insuficiente historial para análisis de posición"}

        df_analyzed = self.calculate_indicators(df)
        curr_candle = df_analyzed.iloc[-2]

        curr_close = float(curr_candle["close"])
        curr_low = float(curr_candle["low"])
        curr_high = float(curr_candle["high"])
        curr_rsi = float(curr_candle.get("rsi", 50.0))
        ema_50 = float(curr_candle.get("ema_50", curr_close))
        ema_trend = float(curr_candle.get("ema_trend", curr_close))
        current_atr = float(curr_candle.get("atr", 0.0) if not pd.isna(curr_candle.get("atr", 0.0)) else 0.0010)

        is_buy = getattr(position, "type", 0) == mt5.POSITION_TYPE_BUY
        pos_type_str = "BUY" if is_buy else "SELL"
        price_open = float(getattr(position, "price_open", curr_close))
        current_sl = float(getattr(position, "sl", 0.0))
        current_tp = float(getattr(position, "tp", 0.0))

        # Cálculo de R actual (Riesgo / Beneficio alcanzado)
        pnl_dist = (curr_close - price_open) if is_buy else (price_open - curr_close)
        initial_risk = abs(price_open - current_sl) if current_sl > 0 else (current_atr * self.atr_sl_mult)
        current_r = (pnl_dist / initial_risk) if initial_risk > 1e-9 else 0.0

        # Cargar heurísticas del par para modular Break-Even
        learned_rules = self._get_symbol_rules()
        thresholds = self._get_dynamic_thresholds(learned_rules)
        be_trigger_r = thresholds["be_trigger_r"]

        # Detección de patrones de agotamiento
        pat_info = detect_candlestick_patterns(df)
        pat_bias = pat_info.get("bias", "NEUTRAL")
        pat_name = pat_info.get("primary_pattern", "Vela Estándar")
        pat_strength = pat_info.get("strength", "MODERATE")

        ema_buffer = (current_atr * self.ema_buffer_pct) if current_atr > 0 else (ema_trend * 0.002)

        # -------------------------------------------------------------
        # A. CIERRE DE EMERGENCIA POR INVALIDACIÓN ESTRUCTURAL
        # -------------------------------------------------------------
        if is_buy:
            # 1. Ruptura y cambio de tendencia macro en EMA 200 (Precio < EMA200 - buffer)
            if curr_close < (ema_trend - ema_buffer):
                return {
                    "action": "EARLY_CLOSE",
                    "reason": (
                        f"Cierre de emergencia: Precio ({curr_close:.5f}) perforó EMA200 ({ema_trend:.5f}) "
                        f"un 20% ATR por debajo ({ema_trend - ema_buffer:.5f}). Tendencia macro alcista invalidada."
                    ),
                    "close_reason": "Cambio_Tendencia_EMA200"
                }

            # 2. Ruptura de EMA 50 con pérdida acumulada (estructura a corto plazo perdida)
            if curr_close < ema_50 and current_r <= -0.5:
                return {
                    "action": "EARLY_CLOSE",
                    "reason": (
                        f"Cierre preventivo: Precio ({curr_close:.5f}) perdió EMA50 ({ema_50:.5f}) "
                        f"con drawdown ({current_r:.2f}R). Invalidación de impulso alcista."
                    ),
                    "close_reason": "Invalidacion_Estructura_EMA50"
                }

            # 3. Agotamiento extremo en zona alta con patrón fuerte y sobrecompra
            if (curr_close > price_open) and pat_bias == "BEARISH" and pat_strength == "STRONG" and curr_rsi > 72.0:
                return {
                    "action": "EARLY_CLOSE",
                    "reason": (
                        f"Toma de ganancias preventiva: Confirmación de agotamiento en sobrecompra "
                        f"(RSI {curr_rsi:.1f}) con patrón bajista {pat_name}."
                    ),
                    "close_reason": "Agotamiento_Sobrecompra"
                }
        else:
            # 1. Ruptura y cambio de tendencia macro en EMA 200 (Precio > EMA200 + buffer)
            if curr_close > (ema_trend + ema_buffer):
                return {
                    "action": "EARLY_CLOSE",
                    "reason": (
                        f"Cierre de emergencia: Precio ({curr_close:.5f}) superó EMA200 ({ema_trend:.5f}) "
                        f"un 20% ATR por encima ({ema_trend + ema_buffer:.5f}). Tendencia macro bajista invalidada."
                    ),
                    "close_reason": "Cambio_Tendencia_EMA200"
                }

            # 2. Ruptura de EMA 50 con pérdida acumulada
            if curr_close > ema_50 and current_r <= -0.5:
                return {
                    "action": "EARLY_CLOSE",
                    "reason": (
                        f"Cierre preventivo: Precio ({curr_close:.5f}) superó EMA50 ({ema_50:.5f}) "
                        f"con drawdown ({current_r:.2f}R). Invalidación de impulso bajista."
                    ),
                    "close_reason": "Invalidacion_Estructura_EMA50"
                }

            # 3. Agotamiento extremo en zona baja con patrón fuerte y sobreventa
            if (curr_close < price_open) and pat_bias == "BULLISH" and pat_strength == "STRONG" and curr_rsi < 28.0:
                return {
                    "action": "EARLY_CLOSE",
                    "reason": (
                        f"Toma de ganancias preventiva: Confirmación de agotamiento en sobreventa "
                        f"(RSI {curr_rsi:.1f}) con patrón alcista {pat_name}."
                    ),
                    "close_reason": "Agotamiento_Sobreventa"
                }

        # -------------------------------------------------------------
        # B. BREAK-EVEN TEMPRANO (+0.9R / +1.2R SEGÚN APRENDIZAJE)
        # -------------------------------------------------------------
        suggested_sl = current_sl
        suggested_tp = current_tp
        needs_sl_update = False
        needs_tp_update = False
        update_reasons: List[str] = []

        is_already_be = (current_sl >= price_open) if is_buy else (current_sl > 0 and current_sl <= price_open)

        if current_r >= be_trigger_r and not is_already_be:
            be_offset = current_atr * 0.10 if current_atr > 0 else (price_open * 0.0001)
            new_be_sl = round(price_open + be_offset if is_buy else price_open - be_offset, 5)

            if is_buy and new_be_sl > current_sl:
                suggested_sl = new_be_sl
                needs_sl_update = True
                update_reasons.append(f"Break-Even Protegido (+{current_r:.1f}R >= +{be_trigger_r:.1f}R)")
            elif not is_buy and (current_sl == 0.0 or new_be_sl < current_sl):
                suggested_sl = new_be_sl
                needs_sl_update = True
                update_reasons.append(f"Break-Even Protegido (+{current_r:.1f}R >= +{be_trigger_r:.1f}R)")

        # -------------------------------------------------------------
        # C. TRAILING STOP DINÁMICO BASADO EN ATR
        # -------------------------------------------------------------
        if current_atr > 0 and current_r >= 1.5:
            trailing_offset = current_atr * max(1.5, self.atr_sl_mult)
            if is_buy:
                new_trailing_sl = round(curr_low - trailing_offset, 5)
                if new_trailing_sl > suggested_sl and new_trailing_sl > price_open:
                    suggested_sl = new_trailing_sl
                    needs_sl_update = True
                    update_reasons.append(f"Trailing SL ATR: {suggested_sl:.5f} (+{current_r:.1f}R)")
            else:
                new_trailing_sl = round(curr_high + trailing_offset, 5)
                if (suggested_sl == 0.0 or new_trailing_sl < suggested_sl) and new_trailing_sl < price_open:
                    suggested_sl = new_trailing_sl
                    needs_sl_update = True
                    update_reasons.append(f"Trailing SL ATR: {suggested_sl:.5f} (+{current_r:.1f}R)")

        # -------------------------------------------------------------
        # D. EXTENSIÓN DINÁMICA DE TAKE PROFIT POR NIVELES FIBONACCI (127.2% / 161.8%)
        # -------------------------------------------------------------
        lookback = min(len(df_analyzed), max(self.lookback_swing, 40))
        swing_slice = df_analyzed.iloc[-lookback:-1]
        swing_high = float(swing_slice["high"].max())
        swing_low = float(swing_slice["low"].min())
        swing_span = max(swing_high - swing_low, current_atr * 2.0)

        if is_buy:
            fibo_ext_127 = swing_low + (swing_span * 1.272)
            fibo_ext_161 = swing_low + (swing_span * 1.618)
            resistance_lvl = float(curr_candle.get("resistance", swing_high))

            is_strong_continuation = (curr_close > ema_trend) and (50.0 <= curr_rsi <= 75.0) and (pat_bias != "BEARISH")
            in_profit = curr_close > (price_open + current_atr * 0.5)

            if is_strong_continuation and in_profit:
                if current_tp == 0.0 or curr_close >= (current_tp - current_atr * 0.8) or curr_close >= (swing_high - current_atr * 0.5):
                    target_tp = fibo_ext_161 if curr_close >= (fibo_ext_127 - current_atr * 0.3) else fibo_ext_127
                    target_tp = round(max(target_tp, resistance_lvl, swing_high + current_atr), 5)
                    if target_tp > current_tp and target_tp > (curr_close + current_atr * 0.8):
                        suggested_tp = target_tp
                        needs_tp_update = True
                        update_reasons.append(f"Extensión TP Fibo: {suggested_tp:.5f}")
        else:
            fibo_ext_127 = swing_high - (swing_span * 1.272)
            fibo_ext_161 = swing_high - (swing_span * 1.618)
            support_lvl = float(curr_candle.get("support", swing_low))

            is_strong_continuation = (curr_close < ema_trend) and (25.0 <= curr_rsi <= 50.0) and (pat_bias != "BULLISH")
            in_profit = curr_close < (price_open - current_atr * 0.5)

            if is_strong_continuation and in_profit:
                if current_tp == 0.0 or curr_close <= (current_tp + current_atr * 0.8) or curr_close <= (swing_low + current_atr * 0.5):
                    target_tp = fibo_ext_161 if curr_close <= (fibo_ext_127 + current_atr * 0.3) else fibo_ext_127
                    target_tp = round(min(target_tp, support_lvl, swing_low - current_atr), 5)
                    if (current_tp == 0.0 or target_tp < current_tp) and target_tp < (curr_close - current_atr * 0.8):
                        suggested_tp = target_tp
                        needs_tp_update = True
                        update_reasons.append(f"Extensión TP Fibo: {suggested_tp:.5f}")

        # -------------------------------------------------------------
        # E. RESOLUCIÓN FINAL DE GESTIÓN
        # -------------------------------------------------------------
        if needs_sl_update or needs_tp_update:
            return {
                "action": "MODIFY_SLTP",
                "suggested_sl": suggested_sl,
                "suggested_tp": suggested_tp,
                "reason": f"Ajuste dinámico #{getattr(position, 'ticket', 0)} ({pos_type_str}) ➔ {' | '.join(update_reasons)}"
            }

        return {
            "action": "MONITOR",
            "current_sl": current_sl,
            "current_tp": current_tp,
            "reason": f"Posición {pos_type_str} #{getattr(position, 'ticket', 0)} monitoreada en rango de respiración (+{current_r:.2f}R)"
        }
