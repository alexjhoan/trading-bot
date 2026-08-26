from datetime import datetime
from typing import Optional, Callable
import MetaTrader5 as mt5
import pandas as pd


def resolve_mt5_symbol(symbol: str) -> Optional[str]:
    """
    Busca inteligentemente el nombre exacto del símbolo en MT5,
    gestionando sufijos y prefijos del broker (ej. EURAUD.r, EURAUDm, EURAUDpro).
    """
    import re
    sym_info = mt5.symbol_info(symbol)
    if sym_info is not None:
        if not sym_info.visible:
            mt5.symbol_select(symbol, True)
        return symbol

    all_symbols = mt5.symbols_get()
    if not all_symbols:
        return None

    target_clean = re.sub(r'[^A-Za-z0-9]', '', symbol).upper()

    # 1. Coincidencia exacta insensible a mayúsculas
    for s in all_symbols:
        if s.name.lower() == symbol.lower():
            if not s.visible:
                mt5.symbol_select(s.name, True)
            return s.name

    # 2. Coincidencia por prefijo (ej: EURAUD_r, EURAUD.r, EURAUDm, EURAUDpro)
    for s in all_symbols:
        s_clean = re.sub(r'[^A-Za-z0-9]', '', s.name).upper()
        if s_clean.startswith(target_clean) or s.name.upper().startswith(symbol.upper()):
            if not s.visible:
                mt5.symbol_select(s.name, True)
            return s.name

    # 3. Coincidencia que contenga el par base
    if len(target_clean) >= 6:
        for s in all_symbols:
            if target_clean[:6] in s.name.upper():
                if not s.visible:
                    mt5.symbol_select(s.name, True)
                return s.name

    return None


def get_historical_data(
    symbol: str,
    timeframe: int,
    rates_count: int,
    log_callback: Optional[Callable[[str, str, str], None]] = None
) -> Optional[pd.DataFrame]:
    """Extrae velas históricas de MT5 y las devuelve en un DataFrame de Pandas.

    :param symbol: Par o activo a consultar (ej. "EURUSD", "BTCUSD").
    :param timeframe: Temporalidad de MT5 (ej. mt5.TIMEFRAME_M15,
        mt5.TIMEFRAME_H1).
    :param rates_count: Cantidad de velas hacia atrás a extraer.
    :param log_callback: Callback opcional para enviar logs a la GUI/usuario (symbol, message, level).
    :return: DataFrame procesado o None si ocurre un error.
    """
    resolved = resolve_mt5_symbol(symbol)
    if resolved:
        symbol = resolved
    else:
        msg = f"❌ El símbolo '{symbol}' no está activo o no existe en la terminal MT5. Código: {mt5.last_error()}"
        print(msg)
        if log_callback:
            log_callback(symbol, msg, "ERROR")
        return None

    # 2. Solicitar los datos a la API de MT5
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, rates_count)

    # Manejo defensivo de errores si no se obtienen datos
    if rates is None or len(rates) == 0:
        err_code, err_msg = mt5.last_error()
        msg = f"❌ Error al obtener datos para {symbol}. Código: ({err_code}, '{err_msg}')"
        print(msg)
        if log_callback:
            log_callback(symbol, msg, "ERROR")
        return None

    # 2. Convertir la tupla de registros estructurados a un DataFrame de Pandas
    df = pd.DataFrame(rates)

    # 3. Formatear la columna de tiempo (viene en Unix timestamp segundos)
    df["time"] = pd.to_datetime(df["time"], unit="s")

    # 4. Seleccionar y renombrar las columnas clave para trading/análisis
    df = df[["time", "open", "high", "low", "close", "tick_volume"]]
    df.rename(columns={"tick_volume": "volume"}, inplace=True)

    return df


if __name__ == "__main__":
    # Importamos nuestro conector previo para asegurar la sesión
    import connector
    from config import SYMBOL_CONFIG

    print("🚀 Iniciando extracción de datos de prueba...\n")

    if connector.initialize_mt5():
        # Configuración de prueba
        SYMBOL = SYMBOL_CONFIG.full_symbol
        TIMEFRAME = SYMBOL_CONFIG.timeframe
        CANDLES = SYMBOL_CONFIG.rates_count

        # Obtener datos
        df_rates = get_historical_data(SYMBOL, TIMEFRAME, CANDLES)

        if df_rates is not None:
            print(f"✅ Datos obtenidos exitosamente para {SYMBOL}:")
            print(f"Total de registros: {len(df_rates)}")
            print("\n--- ÚLTIMAS 5 VELAS (TAIL) ---")
            print(df_rates.tail())

        connector.shutdown_mt5()
