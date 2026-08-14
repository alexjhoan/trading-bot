"""
Módulo Core: Contiene la lógica del motor de trading, conexión con MT5,
gestión de riesgo, estrategias y registro de operaciones.
"""

from .connector import initialize_mt5, shutdown_mt5, check_account_safety, check_algo_trading_enabled, get_account_type_and_symbols
from .executor import OrderExecutor
from .risk_manager import RiskManager
from .strategy import PriceActionStrategy
from .journal_logger import TradingJournal

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
]
