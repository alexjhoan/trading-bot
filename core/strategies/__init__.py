from typing import Dict, Type, List, Optional, Any
from .base_strategy import BaseStrategy
from .ai_strategy import AIStrategy

# Diccionario de estrategias disponibles en el sistema
AVAILABLE_STRATEGIES: Dict[str, Type[BaseStrategy]] = {
    "ai_strategy": AIStrategy,
    "forex": AIStrategy,
    "syntx": AIStrategy,
}


def get_available_strategies() -> List[str]:
    """Retorna la lista de nombres de estrategias disponibles."""
    return list(AVAILABLE_STRATEGIES.keys())


def get_strategy_class(strategy_name: str) -> Type[BaseStrategy]:
    """Retorna la clase de estrategia asociada al nombre o AIStrategy por defecto."""
    clean_name = (strategy_name or "ai_strategy").strip().lower()
    return AVAILABLE_STRATEGIES.get(clean_name, AIStrategy)


def create_strategy_instance(
    strategy_name: Optional[str] = None,
    symbol: Optional[str] = None,
    name: Optional[str] = None,
    **kwargs: Any
) -> BaseStrategy:
    """Instancia y retorna un objeto de estrategia configurado."""
    chosen_name = strategy_name or name or "forex"
    cls = get_strategy_class(chosen_name)
    return cls(symbol=symbol, **kwargs)


__all__ = [
    "BaseStrategy",
    "AIStrategy",
    "AVAILABLE_STRATEGIES",
    "get_available_strategies",
    "get_strategy_class",
    "create_strategy_instance",
]
