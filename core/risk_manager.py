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

    def validate_new_trade(
        self, symbol: str, proposed_lot: float
    ) -> Tuple[bool, str]:
        """Verifica límites de seguridad y estado de mercado antes de colocar la orden."""
        symbol_info: Optional[Any] = mt5.symbol_info(symbol)
        if symbol_info is None:
            return False, f"Símbolo {symbol} no encontrado en MT5."

        if symbol_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False, f"Mercado cerrado para {symbol} (Fines de semana). Usa crypto para pruebas."

        open_positions: Optional[int] = mt5.positions_total()
        if (
            open_positions is not None
            and open_positions >= self.config.max_open_positions
        ):
            return (
                False,
                f"Límite de posiciones alcanzado ({open_positions}/{self.config.max_open_positions})",
            )

        return True, "Validación de riesgo superada"
