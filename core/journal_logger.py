import os
from datetime import datetime
import MetaTrader5 as mt5


def _safe_print(msg: str) -> None:
    """Imprime mensajes de forma segura evitando fallos de codificación Unicode en Windows."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="ignore").decode("ascii"))


class TradingJournal:
    def __init__(self, base_folder="history"):
        self.base_folder = base_folder
        self.filename = self._get_weekly_filepath()
        self._ensure_folder_and_header()

    def _get_weekly_filepath(self) -> str:
        """Calcula la ruta del archivo Markdown basándose en el número de la semana actual."""
        # %V obtiene el número de semana ISO (01 a 53)
        week_number = datetime.now().strftime("%V")
        year = datetime.now().strftime("%Y")

        file_name = f"semana_{week_number}_{year}.md"
        return os.path.join(self.base_folder, file_name)

    def _ensure_folder_and_header(self):
        """Crea la carpeta 'history' y el archivo con su cabecera si aún no existen."""
        # 1. Crear carpeta si no existe
        if not os.path.exists(self.base_folder):
            os.makedirs(self.base_folder, exist_ok=True)

        # 2. Re-verificar ruta por si cambió de semana durante la ejecución
        self.filename = self._get_weekly_filepath()

        # 3. Crear cabecera de la tabla en el archivo semanal si es nuevo
        if not os.path.exists(self.filename):
            try:
                with open(self.filename, "w", encoding="utf-8") as f:
                    week_num = datetime.now().strftime("%V")
                    f.write(f"# 📈 Historial de Operaciones - Semana {week_num}\n\n")
                    f.write("| Fecha/Hora | Ticket | Símbolo | Tipo | Lotes | Precio Ent. | SL | TP | Estado | PnL ($) |\n")
                    f.write("|---|---|---|---|---|---|---|---|---|---|\n")
                _safe_print(f"📄 [LOG] Archivo semanal creado: {self.filename}")
            except Exception as e:
                _safe_print(f"❌ [LOG ERROR] Error creando archivo semanal {self.filename}: {e}")

    def log_entry(self, ticket: int, symbol: str, order_type: str, volume: float, price: float, sl: float, tp: float):
        """Registra la APERTURA de una posición inmediatamente en el diario semanal."""
        self._ensure_folder_and_header()  # Asegura que apunte al archivo semanal correcto
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"| {now} | {ticket} | {symbol} | {order_type} | {volume} | {price:.5f} | {sl:.5f} | {tp:.5f} | 🟢 ABIERTA | Pendiente |\n"

        try:
            with open(self.filename, "a", encoding="utf-8") as f:
                f.write(line)
            _safe_print(f"📝 [LOG APERTURA] Orden #{ticket} guardada en {self.filename}")
        except Exception as e:
            _safe_print(f"❌ [LOG ERROR] No se pudo escribir apertura en {self.filename}: {e}")

    def log_trade(self, ticket: int, symbol: str, strategy_name: str, order_type: str, volume: float, price_open: float, price_close: float, pnl: float):
        """Registra el CIERRE de una operación con su PnL final."""
        self._ensure_folder_and_header()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"| {now} | {ticket} | {symbol} | {order_type} | {volume} | {price_open:.5f} | - | - | 🔴 CERRADA | ${pnl:+.2f} |\n"

        try:
            with open(self.filename, "a", encoding="utf-8") as f:
                f.write(line)
            _safe_print(f"📝 [LOG CIERRE] Orden #{ticket} actualizada en {self.filename}")
        except Exception as e:
            _safe_print(f"❌ [LOG ERROR] No se pudo escribir cierre en {self.filename}: {e}")