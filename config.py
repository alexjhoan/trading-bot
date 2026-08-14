from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict
import MetaTrader5 as mt5
import re


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

    # 🟢 NUEVAS CONFIGURACIONES DE SESIÓN Y FILTRO
    use_session_filter: bool = True

    # Mapa base de sesiones por divisa (Horarios estándar UTC)
    # Ejemplo: Europa/Londres (07:00 - 16:00 UTC), Nueva York (12:00 - 21:00 UTC), Asia/Sídney (22:00 - 08:00 UTC)
    SESSION_MAP: Dict[str, Tuple[str, str]] = field(
        default_factory=lambda: {
            "USD": ("12:00", "21:00"),  # Sesión Nueva York
            "CAD": ("12:00", "21:00"),
            "EUR": ("07:00", "16:00"),  # Sesión Londres / Europa
            "GBP": ("07:00", "16:00"),
            "CHF": ("07:00", "16:00"),
            "JPY": ("00:00", "09:00"),  # Sesión Tokio / Asia
            "AUD": ("22:00", "07:00"),  # Sesión Sídney / Australia
            "NZD": ("22:00", "07:00"),
        }
    )

    def get_session_times_for_symbol(self, symbol: str) -> Tuple[str, str]:
        """
        Determina dinámicamente la hora de inicio y fin combinando
        las divisas del par (Base y Cotizada).
        """
        # Extrae exactamente los primeros 6 caracteres alfabéticos (ej: "GBPCHF_r" -> "GBPCHF")
        match = re.search(r"([A-Z]{6})", symbol.upper())
        clean_symbol = match.group(1) if match else symbol.upper()

        # Extraer divisa base y cotizada (ejemplo: GBPCHF -> base: GBP, quote: CHF)
        base_ccy = clean_symbol[:3] if len(clean_symbol) >= 3 else ""
        quote_ccy = clean_symbol[3:6] if len(clean_symbol) >= 6 else ""

        times_base = self.SESSION_MAP.get(base_ccy)
        times_quote = self.SESSION_MAP.get(quote_ccy)

        if times_base and times_quote:
            # Si ambas divisas tienen horario, tomamos la hora de inicio de la primera en abrir
            # y la hora de fin de la última en cerrar.
            start = min(times_base[0], times_quote[0])
            end = max(times_base[1], times_quote[1])
            return start, end
        elif times_base:
            return times_base
        elif times_quote:
            return times_quote

        # Horario por defecto si el símbolo es un índice o no está mapeado (07:00 a 21:00)
        return "07:00", "21:00"

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
