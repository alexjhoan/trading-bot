from typing import Optional, Dict, Any, List
import MetaTrader5 as mt5
from core.config_manager import load_config

def get_symbol_specs(symbol: str) -> Dict[str, Any]:
    """
    Obtiene las especificaciones de volumen y precio directamente de MT5.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return {
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "point": 0.00001,
            "trade_tick_value": 1.0
        }

    return {
        "volume_min": info.volume_min,
        "volume_max": info.volume_max,
        "volume_step": info.volume_step,
        "point": info.point,
        "trade_tick_value": info.trade_tick_value if info.trade_tick_value > 0 else 1.0
    }


def get_all_symbol_specs(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Obtiene un diccionario con las especificaciones de una lista de símbolos."""
    specs = {}
    for sym in symbols:
        specs[sym] = get_symbol_specs(sym)
    return specs

def get_all_available_symbols() -> List[str]:
    """
    Obtiene la lista de nombres de todos los símbolos disponibles en MT5.
    Si no está conectado o falla, retorna una lista vacía.
    """
    symbols = mt5.symbols_get()
    if symbols is None:
        return []
    return [s.name for s in symbols]

def initialize_mt5() -> bool:
    """Inicializa la conexión con la terminal de MetaTrader 5 usando config.json."""
    config: Dict[str, Any] = load_config()
    path: str = str(config.get("path", "") or "")
    login: int = int(config.get("login", 0) or 0)
    password: str = str(config.get("password", "") or "")
    server: str = str(config.get("server", "") or "")

    init_kwargs: Dict[str, Any] = {}
    if path:
        init_kwargs["path"] = path

    if not mt5.initialize(**init_kwargs):
        print(f"❌ Error al inicializar MT5: {mt5.last_error()}")
        return False

    if login and password and server:
        if not mt5.login(login=login, password=password, server=server):
            print(f"❌ Error al autenticar en MT5: {mt5.last_error()}")
            return False

    print("✅ Conexión exitosa con MetaTrader 5.")
    return True


def shutdown_mt5() -> None:
    """Cierra la conexión activa con la terminal MetaTrader 5."""
    mt5.shutdown()
    print("🔌 Conexión con MetaTrader 5 finalizada correctamente.")


def check_account_safety(require_demo: bool = True) -> bool:
    """Verifica si la cuenta activa es DEMO o REAL para prevenir errores."""
    acc_info: Optional[Any] = mt5.account_info()
    if acc_info is None:
        print("❌ No se pudo obtener la información de la cuenta en MT5.")
        return False

    is_demo: bool = acc_info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO

    print("\n" + "=" * 55)
    print(f"👤 CUENTA CONECTADA : {acc_info.login}")
    print(f"🏦 SERVIDOR / BROKER: {acc_info.server}")
    print(f"💰 BALANCE          : {acc_info.balance} {acc_info.currency}")

    if is_demo:
        print("🟢 TIPO DE CUENTA   : DEMO (Segura para pruebas)")
        print("=" * 55 + "\n")
        return True
    else:
        print("🔴 TIPO DE CUENTA   : REAL / EN VIVO ⚠️⚠️⚠️")
        print("=" * 55)
        if require_demo:
            print("🛑 [BLOQUEO DE SEGURIDAD]: El bot está configurado solo para DEMO.")
            return False
        return True


def check_algo_trading_enabled() -> bool:
    """Verifica si el trading algorítmico (Algo Trading) está activado en MT5 y en la cuenta."""
    terminal_info: Optional[Any] = mt5.terminal_info()
    account_info: Optional[Any] = mt5.account_info()

    if terminal_info is None or account_info is None:
        print("❌ Error al obtener información del terminal o cuenta.")
        return False

    if not terminal_info.trade_allowed:
        print("\n" + "🚨" * 25)
        print("❌ ERROR CRÍTICO: El 'Algo Trading' (Trading Algorítmico) ESTÁ DESACTIVADO.")
        print("👉 Activa el botón 'Algo Trading' en la barra superior de MT5.")
        print("🚨" * 25 + "\n")
        return False

    if not account_info.trade_expert:
        print("\n" + "🚨" * 25)
        print("❌ ERROR: La cuenta de trading no permite ejecución de Asesores Expertos (EAs).")
        print("👉 Revisa la configuración de tu cuenta con el broker.")
        print("🚨" * 25 + "\n")
        return False

    return True


def check_symbol_market_open(symbol: str) -> bool:
    """Verifica si el mercado para un símbolo está abierto para operar."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return False

    if not info.visible:
        mt5.symbol_select(symbol, True)

    return info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL


def get_account_type_and_symbols() -> Dict[str, Any]:
    """Obtiene información del servidor y filtra símbolos dinámicamente según el tipo de cuenta."""
    acc_info = mt5.account_info()
    if acc_info is None:
        return {
            "account_id": "Desconectado",
            "server": "Desconectado",
            "account_type": "DESCONOCIDO",
            "symbols": []
        }

    server_name = acc_info.server.lower()
    all_symbols = mt5.symbols_get()
    symbol_names = [s.name for s in all_symbols] if all_symbols else []

    if "deriv" in server_name or "synthetic" in server_name:
        account_type = "SINTETICOS"
        targets = ["Boom", "Crash", "Volatility", "Step", "Jump"]
        sug_symbols = [s for s in symbol_names if any(t in s for t in targets)]
    else:
        account_type = "FOREX_CFD"
        targets = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "NAS100"]
        sug_symbols = [s for s in symbol_names if any(s.startswith(t) for t in targets)]

    if not sug_symbols and symbol_names:
        sug_symbols = symbol_names[:6]

    return {
        "account_id": acc_info.login,
        "server": acc_info.server,
        "account_type": account_type,
        "symbols": sug_symbols
    }
