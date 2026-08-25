import json
import os
import re
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

MEMORY_FILE = Path(__file__).resolve().parent.parent / "trade_memory.json"
_LOCK = threading.Lock()


def _normalize_sym(symbol: str) -> str:
    """Normaliza el símbolo para que coincida independientemente de sufijos como _r, .pro, etc."""
    if not symbol:
        return ""
    sym = symbol.strip().upper()
    sym = sym.replace("/", "").replace("\\", "")
    sym_cleaned = re.sub(r"([._-])?(RAW|PRO|ECN|STP|CASH|PLUS|MINI|MICRO|STD|ZERO|VIP|[A-Z])$", "", sym, flags=re.IGNORECASE)
    match_forex = re.match(r"^([A-Z]{6})", sym)
    if match_forex:
        return match_forex.group(1)
    generic = re.split(r"[._-]", sym)[0]
    return generic if len(generic) >= 3 else sym


class AIMemoryManager:
    """
    Gestor de memoria de operaciones para Aprendizaje por Contexto (Few-Shot Context Injection).
    Almacena el contexto de análisis, decisiones de la IA y resultados reales en MT5 (WIN/LOSS, +/-R).
    """

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = filepath or MEMORY_FILE
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        with _LOCK:
            if not os.path.exists(self.filepath):
                try:
                    with open(self.filepath, "w", encoding="utf-8") as f:
                        json.dump([], f, indent=2)
                except Exception as e:
                    print(f"❌ [AI_MEMORY] Error creando {self.filepath}: {e}")

    def save_analysis(self, trade_data: Dict[str, Any]) -> None:
        """Guarda una nueva entrada analizada por el bot y evaluada por la IA."""
        with _LOCK:
            try:
                data: List[Dict[str, Any]] = []
                if os.path.exists(self.filepath):
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)

                # Si ya existe el trade_id, actualizarlo; si no, agregarlo
                trade_id = trade_data.get("trade_id")
                updated = False
                if trade_id:
                    for i, t in enumerate(data):
                        if t.get("trade_id") == trade_id:
                            data[i] = trade_data
                            updated = True
                            break

                if not updated:
                    data.append(trade_data)

                # Mantener un máximo de 200 operaciones para optimizar lectura
                if len(data) > 200:
                    data = data[-200:]

                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"❌ [AI_MEMORY] Error guardando análisis: {e}")

    def update_trade_result(self, trade_id: int, result: str, pnl_r: float, exit_reason: str, pnl_usd: float = 0.0) -> bool:
        """Actualiza el resultado cuando la operación se cierra en MT5 (WIN/LOSS, R alcanzado)."""
        with _LOCK:
            try:
                if not os.path.exists(self.filepath):
                    return False

                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                found = False
                for trade in data:
                    if trade.get("trade_id") == trade_id:
                        trade["outcome"] = {
                            "status": "CLOSED",
                            "result": result.upper(),  # 'WIN' o 'LOSS'
                            "pnl_r": round(float(pnl_r), 2),  # +2.0 R o -1.0 R
                            "pnl_usd": round(float(pnl_usd), 2),
                            "exit_reason": exit_reason
                        }
                        found = True
                        break

                if found:
                    with open(self.filepath, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    return True
                return False
            except Exception as e:
                print(f"❌ [AI_MEMORY] Error actualizando resultado de trade #{trade_id}: {e}")
                return False

    def get_relevant_past_trades(self, symbol: str, signal: str = "", limit: int = 4) -> List[Dict[str, Any]]:
        """
        Recupera los casos históricos cerrados más relevantes para inyectar como memoria a la IA.
        Prioriza operaciones cerradas del mismo par (normalizado) y dirección de señal.
        """
        clean_target = _normalize_sym(symbol)
        with _LOCK:
            try:
                if not os.path.exists(self.filepath):
                    return []

                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Filtrar trades cerrados del mismo par (limpio)
                closed_same_sym = [
                    t for t in data
                    if t.get("outcome", {}).get("status") == "CLOSED"
                    and _normalize_sym(str(t.get("symbol", ""))) == clean_target
                ]

                # Si hay operaciones con la misma señal (ej. BUY), priorizarlas
                if signal:
                    same_signal = [t for t in closed_same_sym if str(t.get("signal", "")).upper() == signal.upper()]
                    if len(same_signal) >= limit:
                        return same_signal[-limit:]

                # Si hay pocos del mismo par, traer también los últimos generales cerrados
                if len(closed_same_sym) < limit:
                    closed_all = [
                        t for t in data
                        if t.get("outcome", {}).get("status") == "CLOSED"
                        and t not in closed_same_sym
                    ]
                    combined = closed_all + closed_same_sym
                    return combined[-limit:]

                return closed_same_sym[-limit:]
            except Exception as e:
                print(f"❌ [AI_MEMORY] Error recuperando memoria pasada: {e}")
                return []

    def get_all_memory(self) -> List[Dict[str, Any]]:
        """Retorna toda la lista de memoria guardada."""
        with _LOCK:
            try:
                if not os.path.exists(self.filepath):
                    return []
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []

