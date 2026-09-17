from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, List
import pandas as pd
from config import StrategyConfig, STRATEGY_CONFIG


class BaseStrategy(ABC):
    """
    Clase base abstracta para todas las estrategias cuantitativas del bot.
    Define interfaz estándar y utilidades comunes (logging, configuración, correlación).
    """

    name: str = "base_strategy"
    description: str = "Estrategia Base Cuantitativa"

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        symbol: Optional[str] = None,
        logger: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> None:
        self.config: StrategyConfig = config or STRATEGY_CONFIG
        self.symbol: str = symbol or "EURUSD"
        self.logger: Optional[Callable[[str, str], None]] = logger
        self.use_correlation_filter: bool = kwargs.get("use_correlation_filter", False)
        self.correlation_window: int = kwargs.get("correlation_window", 50)
        self.extra_params: Dict[str, Any] = kwargs

    def _log(self, message: str, level: str = "INFO") -> None:
        """Emite un log a través del callback logger si está configurado."""
        if self.logger:
            try:
                self.logger(message, level)
            except Exception:
                pass

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Genera una señal de trading (BUY, SELL o HOLD) basada en el DataFrame de precios.
        Retorna diccionario con: signal, sl, tp, score, reason, etc.
        """
        pass

    def analyze_open_position(self, df: pd.DataFrame, position: Any) -> Dict[str, Any]:
        """
        Gestiona una posición abierta en tiempo real (Break-Even, Trailing Stop, Cierre anticipado).
        Retorna dict con: action ("MONITOR", "EARLY_CLOSE", "MODIFY_SLTP"), close_reason, suggested_sl, suggested_tp.
        """
        return {"action": "MONITOR"}

    def validate_correlation_filter(
        self,
        symbol: str,
        signal: str,
        open_positions: List[Any],
        df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Filtro de correlación cuantitativa para evitar sobreexposición en monedas vinculadas.
        """
        return {"allowed": True, "reason": "Filtro de correlación superado"}
