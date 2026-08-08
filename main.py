import sys
import time
import os
from datetime import datetime
import pandas as pd
import MetaTrader5 as mt5

from config import BOT_CONFIG, RISK_CONFIG, STRATEGY_CONFIG, SYMBOL_CONFIG
import core.connector as connector
from core.executor import OrderExecutor
from core.risk_manager import RiskManager
from core.strategy import SimpleTrendStrategy



class ProcessLock:
    """Evita ejecutar múltiples consolas simultáneas para el mismo par."""

    def __init__(self, symbol: str):
        self.lock_file = f".lock_{symbol.upper()}"

    def acquire(self) -> bool:
        if os.path.exists(self.lock_file):
            return False
        # Crear archivo lock
        with open(self.lock_file, "w") as f:
            f.write(str(os.getpid()))
        return True

    def release(self):
        if os.path.exists(self.lock_file):
            try:
                os.remove(self.lock_file)
            except OSError:
                pass


def get_timeframe_seconds(timeframe: int) -> int:
    timeframe_map = {
        mt5.TIMEFRAME_M1: 60,
        mt5.TIMEFRAME_M5: 300,
        mt5.TIMEFRAME_M15: 900,
        mt5.TIMEFRAME_H1: 3600,
    }
    return timeframe_map.get(timeframe, 300)


def calculate_sleep_seconds(timeframe_seconds: int) -> float:
    current_time = time.time()
    elapsed = current_time % timeframe_seconds
    return timeframe_seconds - elapsed + 1.0


def run_bot():
    # 1. Sobrescribir símbolo si se pasa por línea de comandos (ej: python main.py GBPUSD)
    if len(sys.argv) > 1:
        custom_symbol = sys.argv[1].strip().upper()
        SYMBOL_CONFIG.symbol = custom_symbol

    active_symbol = SYMBOL_CONFIG.full_symbol

    # 2. Validar que no haya otra consola operando el mismo par
    lock = ProcessLock(active_symbol)
    if not lock.acquire():
        print("\n" + "🛑" * 25)
        print(f"❌ ERROR: Ya existe una instancia del bot corriendo para el par '{active_symbol}'.")
        print("👉 Si deseas operar este par, cierra la otra consola primero.")
        print("🛑" * 25 + "\n")
        return

    print("=" * 55)
    print("🤖 BOT DE TRADING MULTI-PAR CON REGISTRO (.MD)")
    print(f"📌 Símbolo Activo: {active_symbol}")
    print("=" * 55)

    try:
        # Inicializar conexión MT5
        if not connector.initialize_mt5():
            return

        # Verificar tipo de cuenta (Demo / Real)
        if not connector.check_account_safety(require_demo=True):
            return

        # Verificar si Algo Trading está activo
        if not connector.check_algo_trading_enabled():
            print("🛑 Deteniendo ejecución: Activa 'Algo Trading' en MT5.")
            return

        strategy = SimpleTrendStrategy(STRATEGY_CONFIG)
        risk_mgr = RiskManager(RISK_CONFIG)
        executor = OrderExecutor(SYMBOL_CONFIG, RISK_CONFIG, STRATEGY_CONFIG)

        tf_seconds = get_timeframe_seconds(BOT_CONFIG.timeframe)

        while True:
            executor.print_performance_summary()

            sleep_needed = calculate_sleep_seconds(tf_seconds)
            next_check = datetime.fromtimestamp(time.time() + sleep_needed)

            print(
                f"⏳ Esperando {sleep_needed:.1f}s hasta cierre de vela "
                f"({active_symbol} | Análisis: {next_check.strftime('%H:%M:%S')})..."
            )
            time.sleep(sleep_needed)

            print(
                f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] ¡Vela cerrada en {active_symbol}! Analizando..."
            )

            # 1. Obtener datos de mercado
            rates = mt5.copy_rates_from_pos(
                active_symbol,
                BOT_CONFIG.timeframe,
                0,
                STRATEGY_CONFIG.slow_sma_period + 10,
            )
            if rates is None or len(rates) == 0:
                print("⚠️ No se pudieron obtener datos de mercado.")
                continue

            df = pd.DataFrame(rates)

            # 2. Verificar posiciones abiertas en MT5 para este símbolo
            positions = mt5.positions_get(symbol=active_symbol)
            has_open_position = positions is not None and len(positions) > 0

            # 3. Determinación de la Señal
            TEST_MODE = True  # 👈 Cambia a False para volver a la estrategia real

            if TEST_MODE:
                signal = "BUY"
                print(f"🧪 [MODO TEST] Señal FORZADA generada: {signal}")
            else:
                signal = strategy.generate_signal(df)
                print(f"📡 Señal obtenida ({active_symbol}): {signal}")

            # 4. Gestión de posiciones existentes (ej. trailing stop o cierres por señal contraria)
            executor.manage_open_positions(current_signal=signal)

            # 5. Evaluación para NUEVA Entrada
            if has_open_position:
                print(f"⏳ [Info] Ya existe una posición abierta en {active_symbol}. Omitiendo nueva entrada...")
            elif signal in ["BUY", "SELL"]:
                # Obtener información de la cuenta para gestión de riesgo
                acc_info = mt5.account_info()
                if acc_info is None:
                    continue

                # Calcular lotaje seguro
                lot_size = risk_mgr.calculate_position_size(
                    balance=acc_info.balance,
                    sl_pips=RISK_CONFIG.default_sl_pips,
                )

                # Validar reglas de gestión de riesgo
                is_valid, reason = risk_mgr.validate_new_trade(
                    symbol=active_symbol, proposed_lot=lot_size
                )

                if is_valid:
                    if not BOT_CONFIG.dry_run:
                        print(f"🚀 Enviando orden {signal} por {lot_size} lotes en {active_symbol}...")
                        executor.send_order(signal=signal, volume=lot_size)
                    else:
                        print(f"🧪 [DRY_RUN] Simulando orden {signal} en {active_symbol}.")
                else:
                    print(f"🚫 Rechazado por Riesgo: {reason}")

    except KeyboardInterrupt:
        print(f"\n🛑 Bot para {active_symbol} detenido manualmente.")
    finally:
        connector.shutdown_mt5()
        lock.release()  # Liberar el par para poder volver a ejecutarlo


if __name__ == "__main__":
    run_bot()
