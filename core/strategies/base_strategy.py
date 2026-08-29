from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable, Tuple, List
import pandas as pd
from config import StrategyConfig, STRATEGY_CONFIG


class BaseStrategy(ABC):
    """
    Clase Base Abstracta para todas las estrategias de trading.
    Define la interfaz estándar para:
    - Cálculo de indicadores (calculate_indicators).
    - Gestión activa de posiciones abiertas (analyze_open_position).
    - Generación de señales para nuevas órdenes (generate_signal).
    - Filtro de correlación de pares de Pearson (validate_correlation_filter).
    """

    name: str = "BaseStrategy"
    description: str = "Estrategia cuantitativa base"

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        logger: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> None:
        self.config: StrategyConfig = config or STRATEGY_CONFIG
        self.symbol: str = symbol or ""
        self._logger: Optional[Callable[[str, str], None]] = logger

    def _log(self, message: str, level: str = "INFO") -> None:
        """Envía logs al GUI si hay un logger registrado, o a la consola estándar."""
        if self._logger is not None:
            self._logger(message, level)
        else:
            print(f"[{level}] {message}")

    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula los indicadores técnicos sobre el DataFrame de velas."""
        pass

    @abstractmethod
    def analyze_open_position(self, df: pd.DataFrame, position: Any) -> Dict[str, Any]:
        """
        Analiza una posición abierta para trailing stop, break-even o cierre prematuro.
        Retorna dict con 'action': 'EARLY_CLOSE' | 'MODIFY_SLTP' | 'MONITOR' | 'HOLD'
        """
        pass

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Evalúa el mercado y genera señales para nuevas entradas:
        Retorna dict con 'signal': 'BUY' | 'SELL' | 'HOLD'
        """
        pass

    # =========================================================================
    # 🟢 MÓDULO DE GESTIÓN Y FILTRADO DE CORRELACIÓN DE PARES (PEARSON)
    # =========================================================================

    def calculate_pair_correlations(self, market_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Calcula la matriz de correlación de Pearson basada en los retornos y precios
        de cierre de todos los pares entregados por el bot.
        """
        correlation_window = getattr(self, "correlation_window", getattr(self.config, "correlation_window", 50))
        close_prices: Dict[str, pd.Series] = {}

        for symbol, df in market_data.items():
            if df is not None and not df.empty and "close" in df.columns:
                close_series = df["close"].tail(correlation_window).reset_index(drop=True)
                if len(close_series) >= 5:
                    close_prices[symbol] = close_series

        if len(close_prices) < 2:
            return pd.DataFrame()

        prices_df = pd.DataFrame(close_prices)
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
        """
        use_corr = getattr(self, "use_correlation_filter", getattr(self.config, "use_correlation_filter", True))
        corr_threshold = getattr(self, "correlation_threshold", getattr(self.config, "correlation_threshold", 0.70))

        if not use_corr:
            return True, "Filtro de correlación desactivado"

        if not active_positions:
            return True, "Sin posiciones abiertas en otros pares"

        corr_matrix = self.calculate_pair_correlations(market_data)

        if corr_matrix.empty or target_symbol not in corr_matrix.columns:
            return True, "Fallback seguro: Matriz de correlación no disponible o insuficiente historial"

        for pos in active_positions:
            open_symbol = pos.get("symbol", "")
            open_type = pos.get("type", "").upper()

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
                if correlation_value >= corr_threshold:
                    if signal_type != open_type:
                        block_msg = (
                            f"🚫 [FILTRO CORRELACIÓN] Señal {signal_type} en {target_symbol} bloqueada. "
                            f"Conflicto directo con {open_symbol} ({open_type}) ➔ Correlación: {correlation_value:+.2f} "
                            f"(Umbral >= {corr_threshold:.2f})"
                        )
                        self._log(block_msg, "WARNING")
                        return False, block_msg

                # 2. Correlación NEGATIVA ALTA (ej: EURUSD y USDCHF ~ -0.85)
                elif correlation_value <= -corr_threshold:
                    if signal_type == open_type:
                        block_msg = (
                            f"🚫 [FILTRO CORRELACIÓN] Señal {signal_type} en {target_symbol} bloqueada. "
                            f"Sobreexposición inversa con {open_symbol} ({open_type}) ➔ Correlación: {correlation_value:+.2f} "
                            f"(Umbral <= -{corr_threshold:.2f})"
                        )
                        self._log(block_msg, "WARNING")
                        return False, block_msg

        return True, "Validación de correlación exitosa: Sin conflictos de riesgo con posiciones activas"
