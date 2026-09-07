"""
Motor de Aprendizaje y Síntesis IA para Backtesting (Deep Search).
Audita las simulaciones históricas bar-a-bar guardadas en backtest_results.json,
analiza patrones de éxito y fallo sistemáticos con un LLM y genera el archivo
persistente de conocimiento 'ai_backtest_learnings.json'.
"""

import json
import os
import re
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable

from core.backtester import get_cached_results
from core.ai_advisor import (
    send_ai_http_with_retry,
    _detect_provider,
    _clean_json_text,
    DEFAULT_GEMINI_MODEL,
)

LEARNINGS_FILE = Path(__file__).resolve().parent.parent / "ai_backtest_learnings.json"
_LEARNINGS_LOCK = threading.Lock()


def _normalize_symbol(symbol: str) -> str:
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


def load_backtest_learnings() -> Dict[str, Any]:
    """Carga de forma segura el archivo ai_backtest_learnings.json."""
    if not os.path.exists(LEARNINGS_FILE):
        return {}
    with _LEARNINGS_LOCK:
        try:
            with open(LEARNINGS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else {}
        except Exception as e:
            print(f"⚠️ [AI_BACKTEST_LEARNER] Error leyendo {LEARNINGS_FILE}: {e}")
            return {}


def save_backtest_learnings(data: Dict[str, Any]) -> bool:
    """Guarda atómicamente el archivo ai_backtest_learnings.json."""
    with _LEARNINGS_LOCK:
        try:
            tmp_file = f"{str(LEARNINGS_FILE)}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, LEARNINGS_FILE)
            return True
        except Exception as e:
            try:
                with open(LEARNINGS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
            except Exception as e2:
                print(f"❌ [AI_BACKTEST_LEARNER] Error guardando {LEARNINGS_FILE}: {e2}")
                return False


def get_symbol_learning(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene las reglas de aprendizaje y heurísticas generadas por la IA
    para un símbolo específico a partir de ai_backtest_learnings.json.
    """
    learnings = load_backtest_learnings()
    if not learnings:
        return None

    per_symbol = learnings.get("symbols", {})
    clean_sym = _normalize_symbol(symbol)

    # 1. Búsqueda exacta o normalizada
    if symbol in per_symbol:
        return per_symbol[symbol]
    if clean_sym in per_symbol:
        return per_symbol[clean_sym]

    for k, v in per_symbol.items():
        if _normalize_symbol(k) == clean_sym or clean_sym.startswith(_normalize_symbol(k)):
            return v
    return None


def format_backtest_learning_for_ai(symbol: str, timeframe: str = "") -> str:
    """
    Formatea un resumen compacto de las lecciones del backtest para inyectarlo
    en el prompt en vivo de AIAdvisor.
    """
    s_data = get_symbol_learning(symbol)
    if not s_data:
        return "Sin lecciones de backtesting sintetizadas aún para este par."

    opt_tf = s_data.get("optimal_tf", "")
    avg_r = s_data.get("avg_r", 0.0)
    wr = s_data.get("win_rate", 0.0)
    trades = s_data.get("trades", 0)
    avoid_rules = s_data.get("avoid_patterns", [])
    strengths = s_data.get("strengths", "")
    risk_advice = s_data.get("risk_advice", "")

    avoid_str = "; ".join(avoid_rules[:2]) if avoid_rules else "Ninguno crítico"
    tf_txt = f" (TF Óptimo: {opt_tf})" if opt_tf else ""

    summary_parts = [
        f"Histórico Simulado{tf_txt}: WR {wr:.0f}%, Exp {avg_r:+.2f}R ({trades} ops)",
        f"Trampas a Evitar: {avoid_str}",
    ]
    if risk_advice:
        summary_parts.append(f"Gestión Sugerida: {risk_advice}")
    if strengths:
        summary_parts.append(f"Fortaleza: {strengths}")

    return " | ".join(summary_parts)


def generate_backtest_learnings(
    api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    strategy_name: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None
) -> Tuple[bool, Dict[str, Any], str]:
    """
    Lee los resultados de Deep Search (backtest_results.json), compila el dataset
    de simulaciones y consulta a la IA para generar una síntesis de aprendizaje.
    Actualiza ai_backtest_learnings.json con las reglas descubiertas.
    """
    if progress_callback:
        progress_callback("📂 Leyendo resultados de Deep Search...")

    results = get_cached_results(strategy_name)
    if not results:
        msg = "No se encontraron resultados de backtest en backtest_results.json. Ejecuta primero un Deep Search."
        return False, {}, msg

    if not api_key or not api_key.strip():
        msg = "API Key de IA no configurada. Ingresa tu API Key en la configuración para usar el Motor de Aprendizaje."
        return False, {}, msg

    # Filtrar resultados válidos
    valid_results = [r for r in results if not r.get("error") and r.get("trades", 0) >= 1]
    if not valid_results:
        msg = "Los resultados de backtest no tienen suficientes operaciones para analizar."
        return False, {}, msg

    if progress_callback:
        progress_callback(f"📊 Compilando estadísticas de {len(valid_results)} configuraciones...")

    # Organizar resumen de datos para la IA
    summary_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    all_sample_trades: List[Dict[str, Any]] = []

    for r in valid_results:
        sym = r.get("symbol", "UNKNOWN")
        if sym not in summary_by_symbol:
            summary_by_symbol[sym] = []
        summary_by_symbol[sym].append(r)

        samples = r.get("sample_trades", [])
        for s in samples:
            s_copy = dict(s)
            s_copy["symbol"] = sym
            s_copy["timeframe"] = r.get("timeframe")
            all_sample_trades.append(s_copy)

    # Construir texto de auditoría
    ranking_lines = []
    for sym, records in list(summary_by_symbol.items())[:18]:
        best_rec = max(records, key=lambda x: x.get("avg_r", -999))
        ranking_lines.append(
            f"• {sym}: Mejor TF={best_rec.get('timeframe')}, Trades={best_rec.get('trades')}, "
            f"WR={best_rec.get('win_rate')}%, Exp={best_rec.get('avg_r'):+.2f}R"
        )

    trades_lines = []
    # Muestra de pérdidas (trampas de mercado) y ganancias
    loss_samples = [t for t in all_sample_trades if t.get("result") == "LOSS"][:15]
    win_samples = [t for t in all_sample_trades if t.get("result") == "WIN"][:10]

    for t in loss_samples:
        trades_lines.append(
            f"PÉRDIDA: {t.get('symbol')} ({t.get('signal')}) | R={t.get('pnl_r')}R | "
            f"Salida={t.get('exit_reason')} | Patrón={t.get('pattern')} | Motivo={t.get('entry_reason')}"
        )
    for t in win_samples:
        trades_lines.append(
            f"GANANCIA: {t.get('symbol')} ({t.get('signal')}) | R={t.get('pnl_r')}R | "
            f"Salida={t.get('exit_reason')} | Patrón={t.get('pattern')} | MFE={t.get('mfe_r')}R"
        )

    ranking_text = "\n".join(ranking_lines)
    trades_text = "\n".join(trades_lines)

    prompt = (
        "Eres el Director Cuantitativo e Inteligencia de Trading de un Fondo de Cobertura.\n"
        "Se ha ejecutado un backtest real exhaustivo bar-a-bar (Deep Search) sobre el mercado Forex/CFD.\n\n"
        "OBJETIVO:\n"
        "Auditar las simulaciones, identificar por qué fallaron las operaciones perdedoras, "
        "detectar falsos rompimientos y patrones tóxicos, y generar reglas heurísticas específicas por par "
        "para que el bot en vivo filtre entradas engañosas.\n\n"
        f"--- RANKING DE PARES Y RENDIMIENTO GENERAL ---\n{ranking_text}\n\n"
        f"--- MUESTRA DE OPERACIONES SIMULADAS (WINS Y LOSSES) ---\n{trades_text}\n\n"
        "RESPONDE ESTRICTAMENTE EN FORMATO JSON VÁLIDO CON ESTA ESTRUCTURA:\n"
        "{\n"
        '  "global_diagnostic": "Diagnóstico general de la estrategia y comportamiento de mercado...",\n'
        '  "symbols": {\n'
        '    "SIMBOLO_EJ_EURUSD": {\n'
        '      "optimal_tf": "M15",\n'
        '      "win_rate": 50.0,\n'
        '      "avg_r": 0.62,\n'
        '      "trades": 8,\n'
        '      "strengths": "Excelente seguimiento en sesiones Londres/NY con confluencia EMA",\n'
        '      "avoid_patterns": ["Evitar compras en sobrecompra RSI > 68", "Cuidado con dojis en soporte sin confirmación"],\n'
        '      "risk_advice": "Asegurar break-even tras alcanzar +1.2R por retrocesos rápidos"\n'
        "    }\n"
        "  },\n"
        '  "key_learnings": [\n'
        '    "Lección clave 1 descubierta...",\n'
        '    "Lección clave 2 descubierta..."\n'
        "  ],\n"
        '  "recommended_bot_adjustments": "Ajustes sugeridos de trailing, horarios o filtros..."\n'
        "}\n"
    )

    if progress_callback:
        progress_callback("🧠 Consultando al modelo de IA para sintetizar el aprendizaje...")

    provider = _detect_provider(model_name, base_url)
    clean_key = api_key.strip()
    clean_model = model_name.strip()
    custom_url = (base_url or "").strip()

    try:
        if provider == "Google Gemini":
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={clean_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json"
                }
            }
            payload_bytes = json.dumps(payload).encode("utf-8")
            status, raw_resp, _ = send_ai_http_with_retry(
                endpoint, payload_bytes, headers, max_retries=2, timeout_seconds=25.0, action_label="AI_BACKTEST_LEARNER"
            )
            data = json.loads(raw_resp)
            text_out = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed_json = _clean_json_text(text_out)
        else:
            endpoint = f"{custom_url}/chat/completions" if custom_url else "https://api.openai.com/v1/chat/completions"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {clean_key}"}
            payload = {
                "model": clean_model,
                "messages": [
                    {"role": "system", "content": "Eres un analista cuantitativo senior. Responde únicamente en JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            }
            payload_bytes = json.dumps(payload).encode("utf-8")
            status, raw_resp, _ = send_ai_http_with_retry(
                endpoint, payload_bytes, headers, max_retries=2, timeout_seconds=25.0, action_label="AI_BACKTEST_LEARNER"
            )
            data = json.loads(raw_resp)
            text_out = data["choices"][0]["message"]["content"]
            parsed_json = _clean_json_text(text_out)

        if not isinstance(parsed_json, dict) or "symbols" not in parsed_json:
            return False, {}, "La IA no devolvió una estructura JSON válida de aprendizaje."

        parsed_json["generated_at"] = time.time()
        parsed_json["generated_at_str"] = time.strftime("%Y-%m-%d %H:%M:%S")
        parsed_json["model_used"] = clean_model
        parsed_json["total_symbols_analyzed"] = len(parsed_json.get("symbols", {}))

        # Guardar en ai_backtest_learnings.json
        save_backtest_learnings(parsed_json)

        if progress_callback:
            progress_callback("✅ Aprendizaje sintetizado y guardado con éxito en ai_backtest_learnings.json.")

        return True, parsed_json, "Aprendizaje sintetizado con éxito."

    except Exception as e:
        msg = f"Error durante la síntesis IA: {e}"
        print(f"❌ [AI_BACKTEST_LEARNER] {msg}")
        return False, {}, msg
