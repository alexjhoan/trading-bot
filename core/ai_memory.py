import json
import os
import re
import time
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
        """Verifica que el archivo exista y contenga un JSON válido. Si está vacío o corrupto, lo inicializa con []."""
        with _LOCK:
            try:
                # Asegurar que el directorio padre exista
                if isinstance(self.filepath, Path):
                    self.filepath.parent.mkdir(parents=True, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)

                if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
                    with open(self.filepath, "w", encoding="utf-8") as f:
                        json.dump([], f, indent=2)
                else:
                    # Validar que el contenido sea JSON parseable
                    try:
                        with open(self.filepath, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                            if not content:
                                raise ValueError("Archivo vacío")
                            json.loads(content)
                    except Exception:
                        with open(self.filepath, "w", encoding="utf-8") as f:
                            json.dump([], f, indent=2)
            except Exception as e:
                print(f"❌ [AI_MEMORY] Error inicializando {self.filepath}: {e}")

    def _read_data_safe(self) -> List[Dict[str, Any]]:
        """Lee el archivo de memoria de forma segura y devuelve la lista de registros."""
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                parsed = json.loads(content)
                return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError, Exception) as e:
            print(f"⚠️ [AI_MEMORY] Archivo de memoria corrupto o vacío, regenerando: {e}")
            try:
                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)
            except Exception:
                pass
            return []

    def _write_data_safe(self, data: List[Dict[str, Any]]) -> bool:
        """Escribe los datos de memoria de forma segura y atómica."""
        try:
            tmp_path = f"{str(self.filepath)}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.filepath)
            return True
        except Exception as e:
            # Fallback a escritura directa si replace falla
            try:
                with open(self.filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
            except Exception as e_inner:
                print(f"❌ [AI_MEMORY] Error escribiendo en disco: {e_inner}")
                return False

    def save_analysis(self, trade_data: Dict[str, Any]) -> None:
        """Guarda una nueva entrada analizada por el bot y evaluada por la IA, sanitizando el símbolo sin sufijos."""
        with _LOCK:
            try:
                data = self._read_data_safe()

                # Limpiar y normalizar el símbolo guardado (sin sufijos .pro, _r, etc.)
                if "symbol" in trade_data and trade_data["symbol"]:
                    trade_data["symbol"] = _normalize_sym(str(trade_data["symbol"]))

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

                self._write_data_safe(data)
            except Exception as e:
                print(f"❌ [AI_MEMORY] Error guardando análisis: {e}")

    def log_position_evaluation(self, ticket: int, symbol: str, ai_action: str, ai_opinion: str, close_reason: str = "", profit_pips: float = 0.0, profit_usd: float = 0.0) -> None:
        """
        Registra el análisis de gestión de posición en curso (mantener HOLD, ajuste SL/TP o cierre prematuro)
        asociándolo a la orden en memoria.
        """
        clean_sym = _normalize_sym(symbol)
        with _LOCK:
            try:
                data = self._read_data_safe()
                found = False
                now_str = time.strftime("%Y-%m-%d %H:%M:%S")

                eval_record = {
                    "time": now_str,
                    "action": ai_action.upper(),  # HOLD, MODIFY_SLTP, EARLY_CLOSE
                    "opinion": ai_opinion,
                    "close_reason": close_reason,
                    "profit_pips": round(float(profit_pips), 1),
                    "profit_usd": round(float(profit_usd), 2)
                }

                for trade in data:
                    if trade.get("trade_id") == ticket:
                        if "position_evaluations" not in trade:
                            trade["position_evaluations"] = []
                        trade["position_evaluations"].append(eval_record)
                        # Mantener las últimas 10 evaluaciones para no sobrecargar el JSON
                        if len(trade["position_evaluations"]) > 10:
                            trade["position_evaluations"] = trade["position_evaluations"][-10:]
                        trade["last_ai_management"] = eval_record
                        found = True
                        break

                # Si no existía el trade_id aún (ej. orden abierta manualmente o bot reiniciado), crear registro base
                if not found and ticket:
                    new_entry = {
                        "trade_id": ticket,
                        "symbol": clean_sym,
                        "signal": "POSITION",
                        "ai_opinion": ai_opinion,
                        "position_evaluations": [eval_record],
                        "last_ai_management": eval_record,
                        "outcome": {"status": "OPEN", "result": "PENDING"}
                    }
                    data.append(new_entry)
                    if len(data) > 200:
                        data = data[-200:]

                self._write_data_safe(data)
            except Exception as e:
                print(f"❌ [AI_MEMORY] Error guardando evaluación de posición #{ticket}: {e}")

    def update_trade_result(self, trade_id: int, result: str, pnl_r: float, exit_reason: str, pnl_usd: float = 0.0) -> bool:
        """Actualiza el resultado cuando la operación se cierra en MT5 (WIN/LOSS, R alcanzado)."""
        with _LOCK:
            try:
                data = self._read_data_safe()
                if not data:
                    return False

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
                    self._write_data_safe(data)
                    return True
                return False
            except Exception as e:
                print(f"❌ [AI_MEMORY] Error actualizando resultado de trade #{trade_id}: {e}")
                return False

    def get_relevant_past_trades(self, symbol: str, signal: str = "", limit: int = 4) -> List[Dict[str, Any]]:
        """
        Recupera los casos históricos cerrados correspondientes estrictamente al par indicado (normalizado).
        Garantiza aislamiento por símbolo en trade_memory.json y prioriza la dirección de la señal.
        """
        clean_target = _normalize_sym(symbol)
        with _LOCK:
            try:
                data = self._read_data_safe()
                if not data:
                    return []

                # Filtrar trades cerrados que pertenecen exclusivamente al mismo par (normalizado)
                closed_same_sym = [
                    t for t in data
                    if t.get("outcome", {}).get("status") == "CLOSED"
                    and _normalize_sym(str(t.get("symbol", ""))) == clean_target
                ]

                # Si se especifica señal (ej. BUY / SELL), priorizar los casos de esa misma dirección
                if signal:
                    same_signal = [t for t in closed_same_sym if str(t.get("signal", "")).upper() == signal.upper()]
                    if same_signal:
                        return same_signal[-limit:]

                return closed_same_sym[-limit:]
            except Exception as e:
                print(f"❌ [AI_MEMORY] Error recuperando memoria pasada para {clean_target}: {e}")
                return []

    def get_recent_trades_context(self, symbol: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Alias de compatibilidad para recuperar trades cerrados relevantes del símbolo."""
        return self.get_relevant_past_trades(symbol=symbol, limit=limit)

    def get_all_memory(self) -> List[Dict[str, Any]]:
        """Retorna toda la lista de memoria guardada."""
        with _LOCK:
            try:
                return self._read_data_safe()
            except Exception:
                return []

