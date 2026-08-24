"""
Módulo Core: Contiene la lógica del motor de trading, conexión con MT5,
gestión de riesgo, estrategias y registro de operaciones.
"""

try:
    from .connector import initialize_mt5, shutdown_mt5, check_account_safety, check_algo_trading_enabled, get_account_type_and_symbols
except ImportError:
    initialize_mt5 = None
    shutdown_mt5 = None
    check_account_safety = None
    check_algo_trading_enabled = None
    get_account_type_and_symbols = None

try:
    from .executor import OrderExecutor
except ImportError:
    OrderExecutor = None

try:
    from .risk_manager import RiskManager
except ImportError:
    RiskManager = None

try:
    from .strategy import PriceActionStrategy
except ImportError:
    PriceActionStrategy = None

try:
    from .journal_logger import TradingJournal
except ImportError:
    TradingJournal = None

from .ai_logger import AILogger, ai_logger
from .ai_advisor import evaluate_trade_setup, test_ai_connection, fetch_available_models

__all__ = [
    "initialize_mt5",
    "shutdown_mt5",
    "check_account_safety",
    "check_algo_trading_enabled",
    "get_account_type_and_symbols",
    "OrderExecutor",
    "RiskManager",
    "PriceActionStrategy",
    "TradingJournal",
    "AILogger",
    "ai_logger",
    "evaluate_trade_setup",
    "test_ai_connection",
    "fetch_available_models",
]
