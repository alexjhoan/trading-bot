from typing import Optional, Callable, Dict, Any
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
        log_callback: Optional[Callable[[str, str, str], None]] = None
    ) -> None:
        self.symbol = symbol or symbol_config.full_symbol
        self.symbol_config = symbol_config
        self.risk_config = risk_config
        self.strategy_config = strategy_config
        self.journal = TradingJournal()
        self.log_callback = log_callback

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
        order_type: str,
        volume: float,
        sl_pips: float = 0.0,
        tp_pips: float = 0.0,
        sl_price: float = 0.0,
        tp_price: float = 0.0,
        comment: str = ""
    ) -> Dict[str, Any]:
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            from core.data_loader import resolve_mt5_symbol
            resolved = resolve_mt5_symbol(self.symbol)
            if resolved:
                self.symbol = resolved
                symbol_info = mt5.symbol_info(self.symbol)

        if symbol_info is None:
            print(f"❌ [MT5] No se pudo obtener symbol_info para {self.symbol}")
            return {"status": False, "message": f"Símbolo {self.symbol} no encontrado"}

        # Asegurar que el símbolo esté seleccionado en MarketWatch
        if not symbol_info.visible:
            mt5.symbol_select(self.symbol, True)
            symbol_info = mt5.symbol_info(self.symbol)

        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            print(f"❌ [MT5] No se pudo obtener tick para {self.symbol}")
            return {"status": False, "message": f"Tick no disponible para {self.symbol}"}

        point = symbol_info.point
        digits = symbol_info.digits
        pip_size = self._get_pip_size(symbol_info)
        order_type_mt5 = mt5.ORDER_TYPE_BUY if order_type.upper() == "BUY" else mt5.ORDER_TYPE_SELL

        # 1. Determinar precio de entrada según tipo de orden
        price = tick.ask if order_type.upper() == "BUY" else tick.bid

        # 2. Calcular SL y TP absolutos
        final_sl_price = 0.0
        final_tp_price = 0.0

        if sl_price > 0:
            final_sl_price = round(sl_price, digits)
        elif sl_pips > 0:
            if order_type.upper() == "BUY":
                final_sl_price = round(price - (sl_pips * pip_size), digits)
            else:
                final_sl_price = round(price + (sl_pips * pip_size), digits)

        if tp_price > 0:
            final_tp_price = round(tp_price, digits)
        elif tp_pips > 0:
            if order_type.upper() == "BUY":
                final_tp_price = round(price + (tp_pips * pip_size), digits)
            else:
                final_tp_price = round(price - (tp_pips * pip_size), digits)

        # 3. Armar Request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": float(volume),
            "type": order_type_mt5,
            "price": price,
            "sl": final_sl_price,
            "tp": final_tp_price,
            "deviation": 10,
            "magic": 123456,
            "comment": comment or "Bot Order",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": get_filling_mode(self.symbol),
        }

        # Print de depuración en consola
        print("=" * 60)
        print(f"🔍 [DEBUG MT5 REQUEST] Enviando orden para {self.symbol}:")
        print(f"   ├─ Tipo: {order_type} ({'BUY' if order_type_mt5 == 0 else 'SELL'})")
        print(f"   ├─ Volumen/Lote: {request['volume']}")
        print(f"   ├─ Precio Entrada: {request['price']}")
        print(f"   ├─ Precio SL: {request['sl']}")
        print(f"   ├─ Precio TP: {request['tp']}")
        print(f"   ├─ Point: {point} | Digits: {digits}")
        print(f"   └─ Filling Mode: {request['type_filling']}")
        print("=" * 60)

        debug_msg = (
            f"🔍 [DEBUG MT5 REQUEST] Enviando orden para {self.symbol}:\n"
            f"   ├─ Tipo: {order_type}\n"
            f"   ├─ Volumen/Lote: {volume}\n"
            f"   ├─ Precio Entrada: {price}\n"
            f"   ├─ Precio SL: {request['sl']}\n"
            f"   └─ Precio TP: {request['tp']}"
        )
        self._log(debug_msg, "INFO")

        # 4. Enviar orden
        result = mt5.order_send(request)

        if result is None:
            msg = f"❌ Error crítico en order_send para {self.symbol}"
            print(msg)
            return {"status": False, "message": msg}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = f"❌ Error al ejecutar orden {result.order}: {result.comment} (código {result.retcode})"
            print(msg)
            return {"status": False, "message": msg, "retcode": result.retcode}

        print(f"✅ ¡Orden ejecutada con éxito! Ticket #{result.order} | Precio: {result.price}")

        # Guardar registro de la APERTURA en el diario
        try:
            self.journal.log_entry(
                ticket=result.order,
                symbol=self.symbol,
                order_type="BUY" if order_type_mt5 == mt5.ORDER_TYPE_BUY else "SELL",
                volume=volume,
                price=price,
                sl=sl_price,
                tp=tp_price
            )
        except Exception as log_err:
            print(f"⚠️ No se pudo escribir log de apertura: {log_err}")

        return {"status": True, "ticket": result.order, "price": result.price, "volume": result.volume}

    def close_position(self, position, reason: str = "EarlyExit") -> bool:
        """Cierra la posición y guarda el registro con PnL en el diario Markdown."""
        pos_obj = position
        if isinstance(position, (int, str)):
            try:
                ticket_id = int(position)
                positions = mt5.positions_get(ticket=ticket_id)
                if positions and len(positions) > 0:
                    pos_obj = positions[0]
                else:
                    print(f"⚠️ [MT5] No se encontró posición abierta con ticket #{ticket_id}")
                    return False
            except Exception as e:
                print(f"❌ [MT5] Error resolviendo ticket #{position}: {e}")
                return False

        sym = getattr(pos_obj, "symbol", self.symbol)
        symbol_info = mt5.symbol_info(sym)
        if symbol_info is None:
            from core.data_loader import resolve_mt5_symbol
            resolved = resolve_mt5_symbol(sym)
            if resolved:
                sym = resolved
                symbol_info = mt5.symbol_info(sym)

        if symbol_info is None:
            print(f"❌ [MT5] No se pudo obtener symbol_info para cerrar posición #{getattr(pos_obj, 'ticket', position)}")
            return False

        if not symbol_info.visible:
            mt5.symbol_select(sym, True)
            symbol_info = mt5.symbol_info(sym)

        tick = mt5.symbol_info_tick(sym)
        pos_type = getattr(pos_obj, "type", mt5.POSITION_TYPE_BUY)
        order_type = (
            mt5.ORDER_TYPE_SELL
            if pos_type == mt5.POSITION_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        )

        if tick is not None:
            price = tick.bid if pos_type == mt5.POSITION_TYPE_BUY else tick.ask
        else:
            price = symbol_info.bid if pos_type == mt5.POSITION_TYPE_BUY else symbol_info.ask

        ticket_id = getattr(pos_obj, "ticket", int(position) if isinstance(position, (int, str)) else 0)
        volume = float(getattr(pos_obj, "volume", 0.01))

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket_id,
            "symbol": sym,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 25,
            "magic": 123456,
            "comment": f"Bot_{reason}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": get_filling_mode(sym),
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            pos_type_str = "BUY" if pos_type == mt5.POSITION_TYPE_BUY else "SELL"
            pnl = float(getattr(pos_obj, "profit", 0.0)) + float(getattr(pos_obj, "swap", 0.0))

            msg = f"🔒 Posición #{ticket_id} ({sym}) cerrada por {reason} | PnL Final: ${pnl:+.2f}"
            print(msg)
            self._log(msg, "SUCCESS" if pnl >= 0 else "WARNING")

            # Escribir en el Diario Markdown al cerrar la operación
            try:
                self.journal.log_trade(
                    ticket=ticket_id,
                    symbol=sym,
                    strategy_name=self.strategy_name,
                    order_type=pos_type_str,
                    volume=volume,
                    price_open=float(getattr(pos_obj, "price_open", price)),
                    price_close=price,
                    pnl=pnl,
                )
            except Exception as j_err:
                print(f"⚠️ [JOURNAL] Error registrando cierre: {j_err}")
            return True

        ret_comment = result.comment if result else "No response"
        last_err = mt5.last_error()
        print(f"❌ Error cerrando posición #{ticket_id} ({sym}): {ret_comment} | Last MT5 Error: {last_err}")
        return False

    def modify_sltp(self, position, new_sl: float, new_tp: float, reason: str = "Ajuste") -> bool:
        """Modifica los niveles de Stop Loss y Take Profit en MT5."""
        pos_obj = position
        if isinstance(position, (int, str)):
            try:
                ticket_id = int(position)
                positions = mt5.positions_get(ticket=ticket_id)
                if positions and len(positions) > 0:
                    pos_obj = positions[0]
                else:
                    print(f"⚠️ [MT5] No se encontró posición activa para modificar SL/TP con ticket #{ticket_id}")
                    return False
            except Exception as e:
                print(f"❌ [MT5] Error resolviendo ticket #{position}: {e}")
                return False

        sym = getattr(pos_obj, "symbol", self.symbol)
        symbol_info = mt5.symbol_info(sym)
        if symbol_info is None:
            return False

        digits = symbol_info.digits
        curr_sl = getattr(pos_obj, "sl", 0.0)
        curr_tp = getattr(pos_obj, "tp", 0.0)
        sl_val = round(new_sl, digits) if new_sl > 0 else curr_sl
        tp_val = round(new_tp, digits) if new_tp > 0 else curr_tp
        ticket_id = getattr(pos_obj, "ticket", int(position) if isinstance(position, (int, str)) else 0)

        # Si no hay cambios reales significativos, omitir
        if abs(sl_val - curr_sl) < symbol_info.point and abs(tp_val - curr_tp) < symbol_info.point:
            return True

        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket_id,
            "symbol": sym,
            "sl": sl_val,
            "tp": tp_val,
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            msg = f"🛡️ [{reason.upper()}] Posición #{ticket_id} actualizada ➔ SL: {sl_val} | TP: {tp_val}"
            print(msg)
            self._log(msg, "SUCCESS")
            return True
        else:
            err_comment = res.comment if res else "Sin respuesta MT5"
            last_err = mt5.last_error()
            print(f"⚠️ Error actualizando SL/TP en #{ticket_id}: {err_comment} | Last MT5 Error: {last_err}")
            return False

    def modify_order_sltp(self, position_or_ticket: Any, sl: float = 0.0, tp: float = 0.0, reason: str = "Ajuste") -> bool:
        """Alias de compatibilidad para modify_sltp."""
        return self.modify_sltp(position=position_or_ticket, new_sl=sl, new_tp=tp, reason=reason)

    def manage_position_with_strategy(self, position: Any, management_result: Dict[str, Any]) -> None:
        """
        Ejecuta la acción recomendada por el análisis de posición de la estrategia:
        - EARLY_CLOSE: Cierre prematuro por invalidación de tendencia o confluencia
        - MODIFY_SLTP: Actualización de Stop Loss o Take Profit
        - BREAK-EVEN: Movimiento a precio de entrada cuando alcanza el objetivo parcial
        """
        action = management_result.get("action", "MONITOR")
        reason = management_result.get("reason", "")
        close_reason = management_result.get("close_reason", "EarlyExit")

        # 1. Cierre prematuro por invalidación
        if action == "EARLY_CLOSE":
            self._log(f"⚠️ [GESTIÓN ACTIVA] {reason}", "WARNING")
            self.close_position(position, reason=close_reason)
            return

        # 2. Modificación de SL / TP (Trailing o Estructura)
        if action == "MODIFY_SLTP":
            new_sl = float(management_result.get("suggested_sl", position.sl))
            new_tp = float(management_result.get("suggested_tp", position.tp))
            self.modify_sltp(position, new_sl=new_sl, new_tp=new_tp, reason="Trailing ATR")

        # 3. Break-Even dinámico estándar (Garantía de protección)
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info:
            is_buy = position.type == mt5.POSITION_TYPE_BUY
            pip_size = self._get_pip_size(symbol_info)
            curr_price = symbol_info.bid if is_buy else symbol_info.ask
            profit_pips = (
                (curr_price - position.price_open) / pip_size
                if is_buy
                else (position.price_open - curr_price) / pip_size
            )

            be_trigger = getattr(self.strategy_config, "breakeven_trigger_pips", 10.0)
            if profit_pips >= be_trigger:
                new_sl = position.price_open
                needs_update = (is_buy and (position.sl < new_sl or position.sl == 0.0)) or (not is_buy and (position.sl > new_sl or position.sl == 0.0))
                if needs_update:
                    self.modify_sltp(position, new_sl=new_sl, new_tp=position.tp, reason=f"Break-Even (+{profit_pips:.1f}p)")

    def manage_open_positions(self, current_signal: str) -> None:
        """Fallback de monitoreo de posiciones abiertas cuando no se pasa análisis detallado."""
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return

        for pos in positions:
            is_buy = pos.type == mt5.POSITION_TYPE_BUY
            if (is_buy and current_signal == "SELL") or (not is_buy and current_signal == "BUY"):
                msg = f"⚠️ [GESTIÓN ACTIVA] Cambio de tendencia ({current_signal}) en posición #{pos.ticket}. Cerrando anticipadamente..."
                print(msg)
                self._log(msg, "WARNING")
                self.close_position(pos, reason="Cambio_Tendencia")
                continue

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

            be_trigger = getattr(self.strategy_config, "breakeven_trigger_pips", 10.0)
            if profit_pips >= be_trigger:
                new_sl = pos.price_open
                needs_update = (is_buy and (pos.sl < new_sl or pos.sl == 0.0)) or (not is_buy and (pos.sl > new_sl or pos.sl == 0.0))
                if needs_update:
                    self.modify_sltp(pos, new_sl=new_sl, new_tp=pos.tp, reason=f"Break-Even (+{profit_pips:.1f}p)")

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
