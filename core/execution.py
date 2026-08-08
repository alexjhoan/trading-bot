from typing import Any, Dict, Optional, Tuple
import MetaTrader5 as mt5

# Importamos las configuraciones específicas desde config.py
from config import RISK_CONFIG, SYMBOL_CONFIG


class ExecutionHandler:

    def __init__(
        self, magic_number: int = 202408, deviation_slippage: int = 10
    ) -> None:
        self.magic_number: int = magic_number
        self.deviation: int = deviation_slippage

    def _get_prices(self, symbol: str) -> Optional[Tuple[float, float]]:
        """Obtiene los precios Ask y Bid actuales del símbolo."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            print(f"❌ Error al obtener tick actual para {symbol}")
            return None
        return tick.ask, tick.bid

    def open_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        sl_pips: float,
        tp_pips: float,
    ) -> bool:
        """Envia una orden a mercado (BUY o SELL) a MetaTrader 5.

        :param symbol: Símbolo del activo (ej: EURUSD_r).
        :param order_type: "BUY" o "SELL".
        :param volume: Tamaño del lote.
        :param sl_pips: Distancia al Stop Loss en pips.
        :param tp_pips: Distancia al Take Profit en pips.
        :return: True si se ejecutó con éxito, False en caso contrario.
        """
        prices = self._get_prices(symbol)
        if prices is None:
            return False

        ask, bid = prices
        symbol_info = mt5.symbol_info(symbol)

        if symbol_info is None:
            print(f"❌ Error al consultar información del símbolo: {symbol}")
            return False

        # Convertir pips a valor de precio (1 pip = 10 puntos en activos de 3/5 dígitos)
        point = symbol_info.point
        pip_value = point * 10.0 if symbol_info.digits in (3, 5) else point

        if order_type.upper() == "BUY":
            trade_action = mt5.ORDER_TYPE_BUY
            price = ask
            sl_price = price - (sl_pips * pip_value)
            tp_price = price + (tp_pips * pip_value)
        elif order_type.upper() == "SELL":
            trade_action = mt5.ORDER_TYPE_SELL
            price = bid
            sl_price = price + (sl_pips * pip_value)
            tp_price = price - (tp_pips * pip_value)
        else:
            print(f"⚠️ Tipo de orden no reconocido: {order_type}")
            return False

        # Estructura de solicitud (Request) para MT5 API
        request: Dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": trade_action,
            "price": price,
            "sl": round(sl_price, symbol_info.digits),
            "tp": round(tp_price, symbol_info.digits),
            "deviation": self.deviation,
            "magic": self.magic_number,
            "comment": "Bot Algoritmic Trade",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Envío de la orden a la plataforma
        result = mt5.order_send(request)

        if result is None:
            print("❌ Error crítico: mt5.order_send devolvió None")
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(
                f"❌ Error al ejecutar orden. Código MT5: {result.retcode} | Detalle: {result.comment}"
            )
            return False

        print(
            f"✅ ¡Orden {order_type} Ejecutada! Ticket ID: {result.order} | Lotes: {volume} | Precio: {price}"
        )
        return True


if __name__ == "__main__":
    import connector

    print("🚀 Probando Módulo de Ejecución (`execution.py`)...\n")

    if connector.initialize_mt5():
        executor = ExecutionHandler()

        # Usamos el símbolo completo configurado en SYMBOL_CONFIG
        full_symbol = SYMBOL_CONFIG.full_symbol
        mt5.symbol_select(full_symbol, True)

        print(f"--- Simulación de preparación de orden para {full_symbol} ---")

        # Modifica a True si deseas lanzar una orden REAL a tu cuenta DEMO
        EJECUTAR_ORDEN_REAL = False

        if EJECUTAR_ORDEN_REAL:
            exito = executor.open_order(
                symbol=full_symbol,
                order_type="BUY",
                volume=RISK_CONFIG.min_lot_size,
                sl_pips=RISK_CONFIG.default_sl_pips,
                tp_pips=RISK_CONFIG.default_sl_pips * 2.0,  # Ratio 1:2
            )
        else:
            print(
                "ℹ️ Ejecución simulada (Modo pasivo). Cambia 'EJECUTAR_ORDEN_REAL = True' para probar en Demo."
            )

        connector.shutdown_mt5()