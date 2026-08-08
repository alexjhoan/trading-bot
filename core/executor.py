from typing import Optional, Callable
import MetaTrader5 as mt5
from config import RISK_CONFIG, STRATEGY_CONFIG, SYMBOL_CONFIG, SymbolConfig, RiskConfig, StrategyConfig
from .journal_logger import TradingJournal


def get_filling_mode(symbol: str) -> int:
    """Detecta y mapea correctamente el modo de llenado soportado por el broker."""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return mt5.ORDER_FILLING_RETURN

    filling_flags = symbol_info.filling_mode

    # Si el valor de filling_flags es 1 -> Es exclusivamente FOK
    if filling_flags == 1:
        return mt5.ORDER_FILLING_FOK
    elif filling_flags == 2:
        return mt5.ORDER_FILLING_IOC
    elif filling_flags in (0, 4):
        return mt5.ORDER_FILLING_RETURN

    # Verificación por bits como fallback seguro
    if filling_flags & mt5.ORDER_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    elif filling_flags & mt5.ORDER_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC

    return mt5.ORDER_FILLING_RETURN


class OrderExecutor:
    def __init__(
        self,
        symbol: Optional[str] = None,
        symbol_config: SymbolConfig = SYMBOL_CONFIG,
        risk_config: RiskConfig = RISK_CONFIG,
        strategy_config: StrategyConfig = STRATEGY_CONFIG,
        strategy_name: any = "SimpleTrend",
        log_callback: Optional[Callable[[str, str, str], None]] = None # 👈 Callback opcional
    ) -> None:
        self.symbol = symbol or symbol_config.full_symbol
        self.symbol_config = symbol_config
        self.risk_config = risk_config
        self.strategy_config = strategy_config
        self.journal = TradingJournal()
        self.log_callback = log_callback

        # 🛡️ Garantizar que sea un string sin importar qué le hayan pasado:
        if isinstance(strategy_name, str):
            self.strategy_name = strategy_name
        elif hasattr(strategy_name, "__class__"):
            self.strategy_name = strategy_name.__class__.__name__
        else:
            self.strategy_name = str(strategy_name)

    def _log(self, message: str, level: str = "INFO"):
        """Método auxiliar para enviar mensajes a la GUI o consola."""
        if self.log_callback:
            target = self.symbol if self.symbol else "General"
            self.log_callback(target, message, level)
        else:
            print(message)

    def _get_pip_size(self, symbol_info) -> float:
        point = symbol_info.point
        return point * 10.0 if symbol_info.digits in (3, 5) else point

    def send_order(
        self,
        signal: str,
        volume: float,
        sl_pips: Optional[float] = None,
        tp_pips: Optional[float] = None,
    ) -> Optional[int]:
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None or not symbol_info.visible:
            print(f"❌ Error: El símbolo {self.symbol} no está disponible.")
            return None

        order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
        price = symbol_info.ask if signal == "BUY" else symbol_info.bid
        pip_size = self._get_pip_size(symbol_info)

        sl_pips = sl_pips or self.risk_config.default_sl_pips
        tp_pips = tp_pips or (sl_pips * 1.5)

        if signal == "BUY":
            sl_price = price - (sl_pips * pip_size)
            tp_price = price + (tp_pips * pip_size)
        else:
            sl_price = price + (sl_pips * pip_size)
            tp_price = price - (tp_pips * pip_size)

        filling_mode = get_filling_mode(self.symbol)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": round(sl_price, symbol_info.digits),
            "tp": round(tp_price, symbol_info.digits),
            "deviation": 20,
            "magic": 123456,
            "comment": f"Bot_{self.strategy_name[:10]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result = mt5.order_send(request)

        if result is None:
            err_msg = f"❌ Error crítico al enviar orden a MT5: {mt5.last_error()}"
            self._log(err_msg, "ERROR")
            return {"status": False, "message": err_msg}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            err_msg = f"❌ Error al ejecutar orden {order_type}: {result.comment} (código {result.retcode})"
            self._log(err_msg, "ERROR")
            return {"status": False, "message": err_msg}

        # Si fue exitoso:
        success_msg = f"✅ Orden {order_type} colocada. Lote: {volume}, Ticket: {result.order}"
        self._log(success_msg, "SUCCESS")
        return {"status": True, "ticket": result.order, "message": success_msg}


        print(
            f"✅ ¡ORDEN EJECUTADA EN MT5! | Ticket: {result.order} | {signal} {volume} lotes "
            f"| Precio: {price:.5f} | SL: {sl_price:.5f} | TP: {tp_price:.5f}"
        )

        # 📌 Guardar registro de la APERTURA en el diario inmediatamente
        self.journal.log_entry(
            ticket=result.order,
            symbol=self.symbol,
            order_type=signal,
            volume=volume,
            price=price,
            sl=sl_price,
            tp=tp_price
        )

        return result.order

    def close_position(self, position, reason: str = "EarlyExit") -> bool:
        """Cierra la posición y guarda el registro con PnL en el diario Markdown."""
        symbol_info = mt5.symbol_info(position.symbol)
        if symbol_info is None:
            return False

        order_type = (
            mt5.ORDER_TYPE_SELL
            if position.type == mt5.ORDER_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        )
        price = symbol_info.bid if position.type == mt5.ORDER_TYPE_BUY else symbol_info.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": position.ticket,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 123456,
            "comment": f"Bot_{reason}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": get_filling_mode(position.symbol),
        }



        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            pos_type_str = "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL"
            pnl = position.profit + position.swap  # PnL real incluyendo swap

            print(
                f"🔒 Posición #{position.ticket} cerrada por {reason} | PnL Final: ${pnl:+.2f}"
            )

            # Escribir en el Diario Markdown al cerrar la operación
            self.journal.log_trade(
                ticket=position.ticket,
                symbol=position.symbol,
                strategy_name=self.strategy_name,
                order_type=pos_type_str,
                volume=position.volume,
                price_open=position.price_open,
                price_close=price,
                pnl=pnl,
            )
            return True

        ret_comment = result.comment if result else "No response"
        print(f"❌ Error cerrando posición #{position.ticket}: {ret_comment}")
        return False

    def manage_open_positions(self, current_signal: str) -> None:
        """Monitorea posiciones abiertas, aplica cierres por señal opuesta y Trailing Stop / Break-Even."""
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return

        for pos in positions:
            if pos.magic != 123456:
                continue

            is_buy = pos.type == mt5.POSITION_TYPE_BUY

            # Cierre por cambio de tendencia
            if (is_buy and current_signal == "SELL") or (not is_buy and current_signal == "BUY"):
                print("⚠️ Cambio de tendencia detectado. Cerrando anticipadamente...")
                self.close_position(pos, reason="Cambio_Tendencia")
                continue

            # Trailing Stop / Break-Even
            symbol_info = mt5.symbol_info(self.symbol)
            if symbol_info is None:
                continue

            pip_size = self._get_pip_size(symbol_info)
            curr_price = symbol_info.bid if is_buy else symbol_info.ask
            profit_pips = (
                (curr_price - pos.price_open) / pip_size
                if is_buy
                else (pos.price_open - curr_price) / pip_size
            )

            if profit_pips > 15.0:
                new_sl = pos.price_open
                if (is_buy and pos.sl < new_sl) or (not is_buy and pos.sl > new_sl):
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": pos.ticket,
                        "sl": round(new_sl, symbol_info.digits),
                        "tp": pos.tp,
                    }
                    mt5.order_send(req)
                    print(f"🛡️ SL movido a Break-Even en posición #{pos.ticket}")

    def print_performance_summary(self):
        """Muestra en consola el resumen de flotante actual y balance general."""
        acc_info = mt5.account_info()
        positions = mt5.positions_get(symbol=self.symbol)

        if acc_info is None:
            return

        floating_pnl = (
            sum([p.profit + p.swap for p in positions if p.magic == 123456])
            if positions
            else 0.0
        )

        print("-" * 55)
        print(f"💰 Balance: ${acc_info.balance:.2f} | Equidad: ${acc_info.equity:.2f}")
        print(
            f"📊 Posiciones Abiertas: {len(positions) if positions else 0} | PnL Flotante: ${floating_pnl:+.2f}"
        )
        print("-" * 55)
