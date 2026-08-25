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
from core.strategy import PriceActionStrategy
from core.config_manager import load_config
from core.licensing import verify_license_token, get_hardware_id



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
    # 1. Sobrescribir símbolo si se pasa por línea de comandos (ej: python main.py EURUSD_r)
    if len(sys.argv) > 1:
        custom_symbol = sys.argv[1].strip()
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

        # -------------------------------------------------------------
        # Validación de Licencia Criptográfica y Hardware ID
        # -------------------------------------------------------------
        cfg = load_config()
        acc_info = mt5.account_info()
        current_login = acc_info.login if acc_info else cfg.get("login", 0)
        lic_ok, lic_msg, _ = verify_license_token(
            token=cfg.get("license_key", ""),
            current_account_login=current_login
        )
        if not lic_ok:
            print("\n" + "🔒" * 30)
            print(f"❌ ERROR DE LICENCIA: {lic_msg}")
            print(f"💻 Machine ID de este equipo: {get_hardware_id()}")
            print("👉 Contacte al desarrollador para obtener una clave válida.")
            print("🔒" * 30 + "\n")
            return
        else:
            print(f"🔒 [LICENCIA ACTIVA] {lic_msg}")

        # Verificar tipo de cuenta (Demo / Real)
        if not connector.check_account_safety(require_demo=True):
            return

        # Verificar si Algo Trading está activo
        if not connector.check_algo_trading_enabled():
            print("🛑 Deteniendo ejecución: Activa 'Algo Trading' en MT5.")
            return

        strategy = PriceActionStrategy(STRATEGY_CONFIG)
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
            TEST_MODE = False  # 👈 Cambia a False para volver a la estrategia real

            if TEST_MODE:
                signal = "BUY"
                print(f"🧪 [MODO TEST] Señal FORZADA generada: {signal}")
            else:
                signal_res = strategy.generate_signal(df)
                signal = signal_res.get("signal", "HOLD") if isinstance(signal_res, dict) else str(signal_res)
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

                # 1. Definir o tomar parámetros de riesgo (de RISK_CONFIG o variables locales)
                fixed_lot = RISK_CONFIG.max_lot_size  # O un lote fijo configurado, p. ej. 0.1
                risk_pct = RISK_CONFIG.risk_per_trade_pct # ej. 0.01 (1%)

                # 2. Calcular los pips de Stop Loss dinámicos basados en el riesgo y lotaje
                sl_pips = risk_mgr.calculate_sl_pips_from_risk(
                    balance=acc_info.balance,
                    fixed_lot=fixed_lot,
                    risk_pct=risk_pct,
                    symbol=active_symbol
                )

                # 3. Validar el trade con las reglas de gestión de riesgo
                is_valid, reason = risk_mgr.validate_new_trade(
                    symbol=active_symbol, proposed_lot=fixed_lot
                )

                if is_valid:
                    if not BOT_CONFIG.dry_run:
                        print(f"🚀 Enviando orden {signal} por {fixed_lot} lotes en {active_symbol} (SL: {sl_pips} pips)...")
                        # Asegúrate de pasar el sl_pips correspondiente al executor
                        executor.send_order(order_type=signal, volume=fixed_lot, sl_pips=sl_pips)
                    else:
                        print(f"🧪 [DRY_RUN] Simulando orden {signal} en {active_symbol} con SL de {sl_pips} pips.")
                else:
                    print(f"🚫 Rechazado por Riesgo: {reason}")

    except KeyboardInterrupt:
        print(f"\n🛑 Bot para {active_symbol} detenido manualmente.")
    finally:
        connector.shutdown_mt5()
        lock.release()  # Liberar el par para poder volver a ejecutarlo


if __name__ == "__main__":
    run_bot()
