from dataclasses import dataclass, field
from typing import Optional
import MetaTrader5 as mt5


@dataclass
class AccountConfig:
    """Configuración de credenciales de la cuenta MT5."""

    login: Optional[int] = None
    password: Optional[str] = None
    server: Optional[str] = None
    path: Optional[str] = None


@dataclass
class SymbolConfig:
    """Configuración principal de activo y marco temporal."""

    symbol: str = "AUDNZD"
    suffix: Optional[str] = "_r"
    timeframe: int = mt5.TIMEFRAME_M1  # ⏱️ ÚNICO LUGAR para cambiar la temporalidad del bot
    rates_count: int = 100

    @property
    def full_symbol(self) -> str:
        """Retorna el símbolo completo con su sufijo (ej. EURUSD_r)."""
        return f"{self.symbol}{self.suffix}" if self.suffix else self.symbol


@dataclass
class RiskConfig:
    """Estructura de configuración de parámetros de riesgo modificables."""

    symbol_config: SymbolConfig  # Toma las variables de símbolo/sufijo automáticamente
    risk_per_trade_pct = 0.01   # 0.01 representa el 1% del capital total por operación
    max_daily_drawdown_pct: float = 5.0
    max_open_positions: int = 3
    min_lot_size: float = 0.01
    max_lot_size: float = 10.0
    use_equity_instead_of_balance: bool = True
    default_sl_pips = 20 
    default_tp_pips = 40

    @property
    def symbol(self) -> str:
        """Acceso directo al nombre de símbolo completo."""
        return self.symbol_config.full_symbol


@dataclass
class StrategyConfig:
    """Configuración de parámetros para la estrategia de medias móviles + RSI."""

    fast_sma_period: int = 10
    slow_sma_period: int = 30
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0


@dataclass
class BotConfig:
    """Configuración de ejecución general del Bot."""

    symbol_config: SymbolConfig
    dry_run: bool = False  # True para simular, False para operar en vivo

    @property
    def symbol(self) -> str:
        """Símbolo completo unificado."""
        return self.symbol_config.full_symbol

    @property
    def timeframe(self) -> int:
        """Acceso directo al timeframe global."""
        return self.symbol_config.timeframe


# =====================================================================
# INSTANCIAS GLOBALES (AQUÍ ES DONDE CENTRALIZAMOS TODO)
# =====================================================================

# 1. Configuración principal de Símbolo y Tiempo (Modifica solo esto)
SYMBOL_CONFIG = SymbolConfig(
    symbol="GBPCHF",
    suffix="_r",
    timeframe=mt5.TIMEFRAME_M1,  # 👈 Si cambias a M15, M1, etc., todo el bot lo adopta
)

# 2. Resto de módulos (Leen automáticamente de SYMBOL_CONFIG)
ACCOUNT_CONFIG = AccountConfig()
RISK_CONFIG = RiskConfig(symbol_config=SYMBOL_CONFIG)
STRATEGY_CONFIG = StrategyConfig()
BOT_CONFIG = BotConfig(symbol_config=SYMBOL_CONFIG)