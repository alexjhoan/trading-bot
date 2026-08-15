# test_journal.py
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.journal_logger import TradingJournal, _safe_print

# Instanciar el diario
journal = TradingJournal()

# Simular una operación de prueba cerrada
journal.log_trade(
    ticket=1001234,
    symbol="EURUSD_r",
    strategy_name="PriceActionStrategy",
    order_type="BUY",
    volume=0.01,
    price_open=1.08500,
    price_close=1.08750,
    pnl=25.00,  # Ganancia simultada de $25
)

_safe_print("\n✨ Revisa la carpeta 'history/'. Deberías ver el nuevo archivo .md generado.")
