# test_journal.py
from journal_logger import TradingJournal

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
    pnl=25.00,  # Ganancia simulated de $25
)

print("\n✨ Revisa la carpeta 'logs/'. Deberías ver el nuevo archivo .md generado.")
