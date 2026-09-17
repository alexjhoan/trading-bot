from core.strategies.base_strategy import BaseStrategy
from core.strategies.ai_strategy import AIStrategy
from core.strategies import (
    get_available_strategies,
    get_strategy_class,
    create_strategy_instance,
    AVAILABLE_STRATEGIES,
)

# Aliases de compatibilidad
ForexStrategy = AIStrategy
PriceActionStrategy = AIStrategy
SyntxStrategy = AIStrategy

__all__ = [
    "BaseStrategy",
    "AIStrategy",
    "ForexStrategy",
    "PriceActionStrategy",
    "SyntxStrategy",
    "get_available_strategies",
    "get_strategy_class",
    "create_strategy_instance",
    "AVAILABLE_STRATEGIES",
]

