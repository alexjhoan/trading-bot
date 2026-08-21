from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict
import MetaTrader5 as mt5
import re
from datetime import datetime, timezone


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
    risk_per_trade_pct: float = 0.01   # 0.01 representa el 1% del capital total por operación
    max_daily_drawdown_pct: float = 5.0
    max_open_positions: int = 3
    min_lot_size: float = 0.01
    max_lot_size: float = 10.0
    use_equity_instead_of_balance: bool = True
    default_sl_pips: int = 20
    default_tp_pips: int = 40

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

    # 🟢 FILTRO DE CORRELACIÓN DE PARES (PEARSON)
    use_correlation_filter: bool = True
    correlation_threshold: float = 0.70  # 70% de correlación alta
    correlation_window: int = 80  # Ventana de 50 velas para el cálculo de Pearson

    def is_market_open(self, symbol: str, current_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Valida si el mercado está abierto para operar.
        Verifica el estado del símbolo en MT5 y el fin de semana para Forex/CFDs.
        """
        current_dt = current_dt or datetime.now()
        if symbol:
            try:
                info = mt5.symbol_info(symbol)
                if info is not None and info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
                    return False, f"Mercado cerrado en MT5 ({symbol})"
            except Exception:
                pass

        # Respaldo por día de la semana para pares Forex/Metales/Índices (Sábado=5, Domingo=6)
        is_weekend = current_dt.weekday() in (5, 6)
        is_crypto_or_synthetic = any(
            k in symbol.upper()
            for k in ["BTC", "ETH", "SOL", "BOOM", "CRASH", "VOLATILITY", "STEP", "JUMP"]
        )

        if is_weekend and not is_crypto_or_synthetic:
            return False, "Mercado cerrado por Fin de Semana"

        return True, "Mercado abierto"

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

    @staticmethod
    def _utc_str_to_local_str(utc_time_str: str) -> str:
        """
        Convierte un string de hora en formato "HH:MM" (UTC)
        a la hora local del computador en formato "HH:MM".
        """
        try:
            now = datetime.now()
            # Construimos un objeto datetime naive para el día de hoy con la hora especificada
            h, m = map(int, utc_time_str.split(":"))
            utc_dt = datetime(now.year, now.month, now.day, h, m, tzinfo=timezone.utc)

            # Convertimos al huso horario local del sistema
            local_dt = utc_dt.astimezone()
            return local_dt.strftime("%H:%M")
        except Exception:
            return utc_time_str  # Si falla por algún motivo, retorna el string original

    def get_session_times_for_symbol(self, symbol: str) -> Tuple[str, str]:
        """
        Determina dinámicamente la hora de inicio y fin combinando
        las divisas del par (Base y Cotizada) y convierte el resultado a la HORA LOCAL.
        """
        # 1. Limpiar el símbolo dejando solo las 6 letras del par
        match = re.search(r"([A-Z]{6})", symbol.upper())
        clean_symbol = match.group(1) if match else symbol.upper()

        base_ccy = clean_symbol[:3] if len(clean_symbol) >= 3 else ""
        quote_ccy = clean_symbol[3:6] if len(clean_symbol) >= 6 else ""

        times_base = self.SESSION_MAP.get(base_ccy)
        times_quote = self.SESSION_MAP.get(quote_ccy)

        # 2. Determinar horarios de inicio y fin en UTC
        if times_base and times_quote:
            start_utc = min(times_base[0], times_quote[0])
            end_utc = max(times_base[1], times_quote[1])
        elif times_base:
            start_utc, end_utc = times_base
        elif times_quote:
            start_utc, end_utc = times_quote
        else:
            start_utc, end_utc = "07:00", "21:00"

        # 3. Convertir de UTC a Hora Local
        start_local = StrategyConfig._utc_str_to_local_str(start_utc)
        end_local = StrategyConfig._utc_str_to_local_str(end_utc)

        return start_local, end_local

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
