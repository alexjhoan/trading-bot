from typing import Optional, Any
import pandas as pd
import pandas_ta as ta
from config import StrategyConfig, STRATEGY_CONFIG


class SimpleTrendStrategy:

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        cfg: StrategyConfig = config or STRATEGY_CONFIG
        self.symbol: str = symbol or ""
        self.fast_sma: int = cfg.fast_sma_period
        self.slow_sma: int = cfg.slow_sma_period
        self.rsi_period: int = cfg.rsi_period
        self.rsi_overbought: float = cfg.rsi_overbought
        self.rsi_oversold: float = cfg.rsi_oversold

    def generate_signal(self, df: pd.DataFrame) -> str:
        """Analiza el DataFrame y genera 'BUY', 'SELL' o 'HOLD'."""
        if df is None or len(df) < self.slow_sma + 2:
            return "HOLD"

        # Cálculo con pandas_ta
        df["sma_fast"] = ta.sma(df["close"], length=self.fast_sma)
        df["sma_slow"] = ta.sma(df["close"], length=self.slow_sma)
        df["rsi"] = ta.rsi(df["close"], length=self.rsi_period)

        # Precios de cierre e indicadores de las últimas dos velas
        prev_fast = df["sma_fast"].iloc[-3]
        prev_slow = df["sma_slow"].iloc[-3]

        curr_fast = df["sma_fast"].iloc[-2]
        curr_slow = df["sma_slow"].iloc[-2]
        curr_rsi = df["rsi"].iloc[-2]

        print(
            f"🔍 [Análisis] SMA Rápida ({self.fast_sma}): {curr_fast:.5f} | "
            f"SMA Lenta ({self.slow_sma}): {curr_slow:.5f} | RSI: {curr_rsi:.2f}"
        )

        # Condición Alcista (Cruce de SMA hacia arriba + RSI > 50)
        if (prev_fast <= prev_slow) and (curr_fast > curr_slow) and (curr_rsi > 50):
            return "BUY"

        # Condición Bajista (Cruce de SMA hacia abajo + RSI < 50)
        if (prev_fast >= prev_slow) and (curr_fast < curr_slow) and (curr_rsi < 50):
            return "SELL"

        return "HOLD"