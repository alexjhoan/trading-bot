from typing import Tuple, Optional, Any
import MetaTrader5 as mt5
from config import RISK_CONFIG, RiskConfig


class RiskManager:

    def __init__(self, config: RiskConfig = RISK_CONFIG) -> None:
        self.config: RiskConfig = config

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

          # 2. Valor aproximado por pip de 1.0 lote estándar ($10 por pip en pares USD)
          pip_value_per_lot: float = 10.0

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
