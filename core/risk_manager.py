from typing import Tuple, Optional, Any
import MetaTrader5 as mt5
from config import RISK_CONFIG, RiskConfig


class RiskManager:

    def __init__(self, config: RiskConfig = RISK_CONFIG, log_callback: Optional[Any] = None) -> None:
        self.config: RiskConfig = config
        self.log_callback = log_callback

    def _log(self, message: str, level: str = "INFO") -> None:
        """Método auxiliar para imprimir o enviar logs a la GUI."""
        if self.log_callback:
            self.log_callback("RiskManager", message, level)
        else:
            print(f"[{level}] {message}")

    def calculate_sl_pips_from_risk(
        self,
        balance: float,
        fixed_lot: float,
        risk_pct: float = 0.01,
        symbol: Optional[str] = None
    ) -> float:
        """
        Calcula la distancia en Pips del Stop Loss basándose en el % de riesgo
        y el lotaje fijo seleccionados desde la GUI.

        Fórmula: Pips SL = (Balance * %Riesgo) / (Lotaje * Valor Pip)
        """
        if balance <= 0 or fixed_lot <= 0:
            return 20.0  # SL por defecto de seguridad en pips

        # 1. Monto en dinero a arriesgar en USD
        risk_amount: float = balance * risk_pct

        # 2. Valor del pip para 1.0 lote (Estándar $10/pip en Forex USD)
        pip_value_per_lot: float = 10.0

        if symbol:
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is not None and symbol_info.trade_tick_value > 0:
                pip_size = symbol_info.point * 10 if symbol_info.digits in (3, 5) else symbol_info.point
                pip_value_per_lot = (symbol_info.trade_tick_value / symbol_info.trade_tick_size) * pip_size

        # 3. Cálculo de Pips de Stop Loss
        sl_pips: float = risk_amount / (fixed_lot * pip_value_per_lot)

        print(
            f"🛡️ [RIESGO SL] Balance: ${balance:.2f} | Riesgo ({risk_pct * 100:.1f}%): ${risk_amount:.2f} | "
            f"Lote Fijo: {fixed_lot} ➔ SL Pips Calculado: {sl_pips:.1f}"
        )

        debug_msg = (
            f"🛡️ [RIESGO SL] Balance: ${balance:.2f} | Riesgo ({risk_pct * 100:.1f}%): ${risk_amount:.2f} | "
            f"Lote Fijo: {fixed_lot} ➔ SL Pips Calculado: {sl_pips:.1f}"
        )
        self._log(debug_msg, "INFO")

        return round(sl_pips, 1)

    def calculate_position_size(
          self,
          balance: float,
          sl_pips: float,
          risk_pct: Optional[float] = None,
          symbol: Optional[str] = None  # Se acepta por si en el futuro calculas el valor del pip según el símbolo
      ) -> float:
          """
          Calcula el lotaje arriesgando el % configurado o el especificado en risk_pct.
          """
          if balance <= 0 or sl_pips <= 0:
              return 0.01  # Lote mínimo de seguridad

          # Usar el risk_pct pasado como argumento o recurrir al de la configuración
          effective_risk_pct = risk_pct if risk_pct is not None else self.config.risk_per_trade_pct

          # 1. Dinero exacto a arriesgar en USD
          risk_amount: float = balance * effective_risk_pct

          # 2. Obtener valor de Pip dinámico según el símbolo en MT5
          pip_value_per_lot: float = 10.0
          if symbol:
              symbol_info = mt5.symbol_info(symbol)
              if symbol_info is not None and symbol_info.trade_tick_value > 0:
                  pip_size = symbol_info.point * 10 if symbol_info.digits in (3, 5) else symbol_info.point
                  pip_value_per_lot = (symbol_info.trade_tick_value / symbol_info.trade_tick_size) * pip_size

          # 3. Cálculo del tamaño de la posición
          raw_lot: float = risk_amount / (sl_pips * pip_value_per_lot)

          # 4. Normalizar el lotaje
          lot_step: float = 0.01
          calculated_lot: float = round(raw_lot / lot_step) * lot_step

          final_lot: float = max(0.01, min(calculated_lot, self.config.max_lot_size))

          print(f"📊 [GESTIÓN RIESGO] Capital: ${balance:.2f} | Riesgo ({effective_risk_pct * 100:.1f}%): ${risk_amount:.2f} | SL: {sl_pips} pips -> Lotaje: {final_lot}")

          return final_lot

    def get_current_spread_pips(self, symbol: str) -> float:
        """Calcula el spread actual en Pips para el símbolo."""
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return 999.0

        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.ask <= 0 or tick.bid <= 0:
            # Fallback usando el spread nativo en puntos
            pip_size = symbol_info.point * 10.0 if symbol_info.digits in (3, 5) else symbol_info.point
            return round((symbol_info.spread * symbol_info.point) / max(pip_size, 1e-6), 2)

        pip_size = symbol_info.point * 10.0 if symbol_info.digits in (3, 5) else symbol_info.point
        spread_raw = tick.ask - tick.bid
        spread_pips = spread_raw / max(pip_size, 1e-6)
        return round(spread_pips, 2)

    def validate_spread(self, symbol: str, max_allowed_pips: Optional[float] = None) -> Tuple[bool, float, str]:
        """
        Valida que el spread actual no supere el límite permitido para evitar que el ensanchamiento
        de spread o slippage dispare SL indeseados.
        """
        limit = max_allowed_pips if max_allowed_pips is not None else getattr(self.config, "max_spread_pips", 3.5)
        current_spread = self.get_current_spread_pips(symbol)

        if current_spread > limit:
            msg = f"Spread excesivo en {symbol}: {current_spread:.1f} pips (Límite: {limit:.1f} pips). Operación bloqueada para proteger gestión."
            return False, current_spread, msg

        return True, current_spread, f"Spread aceptable ({current_spread:.1f} pips <= {limit:.1f} pips)"

    def is_rollover_or_market_close_window(
        self,
        minutes_before_close: int = 15,
        rollover_start: str = "21:15",
        rollover_end: str = "22:30"
    ) -> Tuple[bool, str, str]:
        """
        Detecta si estamos en la ventana de Rollover interbancario diario (~17:00 EST / 21:15 - 22:30 UTC)
        o en el cierre semanal de fin de semana (Viernes noche).

        Para estrategias de Scalping, es OBLIGATORIO cerrar todas las operaciones diariamente
        antes del Rollover para evitar:
        1. Ensanchamiento extremo del Spread (que revienta el SL).
        2. Cobro de comisiones de Swap nocturno.
        3. Falta de liquidez en la apertura de la sesión asiática temprana.

        Retorna: (is_danger_zone, reason, action_needed: 'BLOCK_AND_CLOSE' | 'OK')
        """
        from datetime import datetime, timezone

        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()  # 0=Lunes, 4=Viernes, 5=Sábado, 6=Domingo
        current_hour_min = now_utc.strftime("%H:%M")
        total_now_minutes = now_utc.hour * 60 + now_utc.minute

        # 1. Fin de semana (Sábado y Domingo: Mercado cerrado)
        if weekday in (5, 6):
            return (
                True,
                f"Mercado cerrado por Fin de Semana ({now_utc.strftime('%A')} {current_hour_min} UTC).",
                "BLOCK_AND_CLOSE"
            )

        # 2. Cierre de Mercado de Fin de Semana (Viernes noche - Previo a cierre semanal)
        # Forex cierra los viernes a las 22:00 UTC (17:00 EST).
        if weekday == 4:  # Viernes
            close_minutes = 22 * 60  # 22:00 UTC
            if total_now_minutes >= (close_minutes - minutes_before_close):
                return (
                    True,
                    f"Cierre semanal de mercado en curso (Viernes {current_hour_min} UTC). Bloqueo total y liquidación por seguridad.",
                    "BLOCK_AND_CLOSE"
                )

        # 3. Ventana Diaria Universal de Rollover (Lunes a Viernes)
        # Se calcula en minutos desde medianoche UTC para máxima precisión
        def _to_minutes(t_str: str, default_val: int) -> int:
            try:
                parts = t_str.strip().split(":")
                return int(parts[0]) * 60 + int(parts[1])
            except Exception:
                return default_val

        start_rollover_min = _to_minutes(rollover_start, 21 * 60 + 15)  # Default 21:15 UTC (16:15 EST)
        end_rollover_min = _to_minutes(rollover_end, 22 * 60 + 30)      # Default 22:30 UTC (17:30 EST)

        if start_rollover_min <= total_now_minutes <= end_rollover_min:
            return (
                True,
                f"Ventana de Rollover Diario / Cambio de Sesión ({current_hour_min} UTC entre {rollover_start}-{rollover_end}). "
                f"Spreads bancarios elevados y Swap nocturno.",
                "BLOCK_AND_CLOSE"
            )

        return False, "Horario regular de mercado y liquidez adecuada.", "OK"

    def validate_new_trade(
        self, symbol: str, proposed_lot: float, max_spread_pips: Optional[float] = None
    ) -> Tuple[bool, str]:
        """Verifica límites de seguridad, spread y estado de mercado antes de colocar la orden."""
        symbol_info: Optional[Any] = mt5.symbol_info(symbol)
        if symbol_info is None:
            return False, f"Símbolo {symbol} no encontrado en MT5."

        if symbol_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False, f"Mercado cerrado para {symbol} (Fines de semana). Usa crypto para pruebas."

        # 1. Validación de ventana de rollover y cierre de mercado
        is_danger, danger_reason, _ = self.is_rollover_or_market_close_window()
        if is_danger:
            return False, f"🚫 Operación rechazada: {danger_reason}"

        # 2. Validación de Spread Máximo
        is_spread_ok, curr_spread, spread_msg = self.validate_spread(symbol, max_spread_pips)
        if not is_spread_ok:
            return False, f"🚫 Operación rechazada: {spread_msg}"

        open_positions: Optional[int] = mt5.positions_total()
        if (
            open_positions is not None
            and open_positions >= self.config.max_open_positions
        ):
            return (
                False,
                f"Límite de posiciones alcanzado ({open_positions}/{self.config.max_open_positions})",
            )

        return True, f"Validación de riesgo superada (Spread: {curr_spread:.1f} pips)"

