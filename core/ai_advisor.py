import json
import re
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Tuple, Optional
from core.ai_logger import ai_logger

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# Proveedores soportados con sus configuraciones por defecto
PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "Google Gemini": {
        "default_model": "gemini-2.5-flash",
        "models": [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro"
        ],
        "default_url": "https://generativelanguage.googleapis.com"
    },
    "OpenAI": {
        "default_model": "gpt-4o-mini",
        "models": [
            "gpt-4o-mini",
            "gpt-4o",
            "o3-mini",
            "o1-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo"
        ],
        "default_url": "https://api.openai.com/v1"
    },
    "Groq (Ultra Rápido)": {
        "default_model": "llama-3.3-70b-versatile",
        "models": [
            "llama-3.3-70b-versatile",
            "deepseek-r1-distill-llama-70b",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768"
        ],
        "default_url": "https://api.groq.com/openai/v1"
    },
    "OpenRouter (Multi-Proveedor)": {
        "default_model": "google/gemini-2.5-flash",
        "models": [
            "google/gemini-2.5-flash",
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o-mini",
            "deepseek/deepseek-chat"
        ],
        "default_url": "https://openrouter.ai/api/v1"
    },
    "Ollama / Localhost": {
        "default_model": "llama3.2",
        "models": [
            "llama3.2",
            "mistral",
            "deepseek-r1",
            "qwen2.5"
        ],
        "default_url": "http://localhost:11434/v1"
    }
}


def _detect_provider(model_name: str, base_url: str) -> str:
    """Identifica el nombre del proveedor en base al endpoint o modelo."""
    url = (base_url or "").lower()
    m = (model_name or "").lower()
    if "groq.com" in url:
        return "Groq"
    elif "openrouter.ai" in url:
        return "OpenRouter"
    elif "openai.com" in url:
        return "OpenAI"
    elif "localhost" in url or "127.0.0.1" in url or "11434" in url:
        return "Ollama / Localhost"
    elif "gemini" in m or "googleapis.com" in url or not url:
        return "Google Gemini"
    return "Custom Provider"


def fetch_available_models(provider: str, api_key: str = "", base_url: str = "") -> Tuple[bool, List[str], str]:
    """
    Obtiene dinámicamente la lista de modelos disponibles para el proveedor seleccionado.
    Si se proporciona una API Key, consulta la API oficial en vivo.
    Si falla o no hay key, devuelve la lista curada por defecto para ese proveedor.
    """
    clean_key = (api_key or "").strip()
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["Google Gemini"])
    fallback_models = preset["models"]

    if not clean_key and provider != "Ollama / Localhost":
        return True, fallback_models, "Modelos por defecto (ingrese API Key para consultar en vivo)."

    try:
        if provider == "Google Gemini" and (not base_url or "googleapis.com" in base_url):
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models?key={clean_key}"
            req = urllib.request.Request(endpoint, headers={"Content-Type": "application/json"}, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models_list = []
                for m in data.get("models", []):
                    name = m.get("name", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        clean_name = name.replace("models/", "")
                        # Filtrar modelos de texto/chat relevantes
                        if any(k in clean_name.lower() for k in ["gemini", "gemma"]):
                            models_list.append(clean_name)

                if models_list:
                    # Ordenar priorizando modelos más recientes (2.5, 2.0, 1.5)
                    models_list.sort(reverse=True)
                    return True, models_list, f"✅ {len(models_list)} modelos de Gemini cargados dinámicamente."

        else:
            # Protocolo compatible OpenAI / OpenRouter / Groq / Ollama
            target_url = (base_url or preset.get("default_url", "")).rstrip("/")
            if not target_url.endswith("/models"):
                target_url = f"{target_url}/models"

            headers = {"Content-Type": "application/json"}
            if clean_key:
                headers["Authorization"] = f"Bearer {clean_key}"

            req = urllib.request.Request(target_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_models = data.get("data", [])
                models_list = [m.get("id") for m in raw_models if m.get("id")]
                if models_list:
                    # Filtrar modelos de audio/embeddings irrelevantes si hay muchos
                    chat_models = [m for m in models_list if not any(x in m for x in ["tts", "whisper", "embed", "dall-e", "moderation"])]
                    final_list = chat_models if chat_models else models_list
                    return True, sorted(final_list)[:50], f"✅ {len(final_list)} modelos obtenidos dinámicamente de {provider}."

    except Exception as e:
        return True, fallback_models, f"⚠️ Usando lista por defecto ({str(e)[:60]})."

    return True, fallback_models, "Modelos por defecto."



def _clean_json_text(raw_text: str) -> str:
    """Limpia bloques de código markdown ```json ... ``` para parsear JSON de forma limpia."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def test_ai_connection(api_key: str, model_name: str = DEFAULT_GEMINI_MODEL, base_url: str = "") -> Tuple[bool, str]:
    """
    Prueba la conexión con la API de IA (Google Gemini por defecto o endpoint personalizado).
    Registra toda la interacción en el log semanal/diario de depuración.
    Retorna (éxito, mensaje descriptivo).
    """
    if not api_key or not api_key.strip():
        return False, "❌ Debe ingresar una API Key válida."

    clean_key = api_key.strip()
    model = (model_name or DEFAULT_GEMINI_MODEL).strip()
    custom_url = (base_url or "").strip()
    provider = _detect_provider(model, custom_url)

    start_time = time.time()
    endpoint = ""
    req_headers: Dict[str, str] = {}
    payload_obj: Any = None
    status_code = 0
    raw_res_text = ""

    try:
        if custom_url and "googleapis.com" not in custom_url:
            # Modo OpenAI / Endpoint compatible personalizado
            endpoint = custom_url.rstrip("/")
            if not endpoint.endswith("/chat/completions"):
                endpoint = f"{endpoint}/chat/completions"

            payload_obj = {
                "model": model,
                "messages": [{"role": "user", "content": "Responde únicamente 'OK'"}],
                "max_tokens": 10
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {clean_key}"
            }

            req = urllib.request.Request(
                endpoint,
                data=payload_bytes,
                headers=req_headers,
                method="POST"
            )
        else:
            # Modo Oficial Google Gemini API
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
            payload_obj = {
                "contents": [
                    {"parts": [{"text": "Responde únicamente 'OK'"}]}
                ],
                "generationConfig": {
                    "maxOutputTokens": 10,
                    "temperature": 0.1
                }
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {"Content-Type": "application/json"}

            req = urllib.request.Request(
                endpoint,
                data=payload_bytes,
                headers=req_headers,
                method="POST"
            )

        with urllib.request.urlopen(req, timeout=12) as response:
            status_code = response.getcode()
            raw_res_text = response.read().decode("utf-8")
            duration_ms = (time.time() - start_time) * 1000.0

            ai_logger.log_interaction(
                event_type="TEST_CONNECTION",
                symbol="SYSTEM",
                provider=provider,
                model=model,
                endpoint=endpoint,
                request_headers=req_headers,
                request_payload=payload_obj,
                response_status=status_code,
                duration_ms=duration_ms,
                raw_response=raw_res_text,
                parsed_response={"status": "OK" if status_code in (200, 201) else "ERROR"}
            )

            if status_code in (200, 201):
                return True, f"✅ Conexión con IA exitosa (Modelo: {model} | {duration_ms:.0f}ms)"
            else:
                return False, f"❌ Respuesta inesperada ({status_code}): {raw_res_text[:100]}"

    except urllib.error.HTTPError as he:
        duration_ms = (time.time() - start_time) * 1000.0
        err_msg = he.read().decode("utf-8", errors="ignore")
        ai_logger.log_interaction(
            event_type="TEST_CONNECTION_FAILED",
            symbol="SYSTEM",
            provider=provider,
            model=model,
            endpoint=endpoint,
            request_headers=req_headers,
            request_payload=payload_obj,
            response_status=he.code,
            duration_ms=duration_ms,
            raw_response=err_msg,
            error=f"HTTP Error {he.code}: {err_msg}"
        )
        if he.code == 400:
            return False, f"❌ Error 400 (Bad Request / Clave inválida): {err_msg[:120]}"
        elif he.code == 403:
            return False, "❌ Error 403 (Acceso denegado o API no habilitada)."
        elif he.code == 404:
            return False, f"❌ Error 404 (Modelo '{model}' no encontrado)."
        elif he.code == 429:
            return False, "⚠️ Error 429 (Cuota o límite de peticiones excedido)."
        return False, f"❌ Error HTTP {he.code}: {err_msg[:120]}"
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000.0
        ai_logger.log_interaction(
            event_type="TEST_CONNECTION_ERROR",
            symbol="SYSTEM",
            provider=provider,
            model=model,
            endpoint=endpoint,
            request_headers=req_headers,
            request_payload=payload_obj,
            response_status=500,
            duration_ms=duration_ms,
            error=str(e)
        )
        return False, f"❌ Excepción de conexión: {str(e)}"


def evaluate_trade_setup(
    account_info: Dict[str, Any],
    candidate_setup: Dict[str, Any],
    past_trades: List[Dict[str, Any]],
    api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = ""
) -> Dict[str, Any]:
    """
    Evalúa una señal candidata mediante la IA con inyección de memoria histórica (Few-Shot Context).
    Realiza gestión de riesgo sobre el capital total y calcula/ajusta SL y TP óptimos.
    Registra automáticamente el payload, request, response y depuración en ia-log/semana_WW_YYYY/YYYY-MM-DD.log.

    Si la IA falla o no tiene tokens, aplica fallback transparente para no bloquear la operativa.
    """
    symbol = candidate_setup.get("symbol", "UNKNOWN")
    signal = candidate_setup.get("signal", "HOLD")
    current_price = float(candidate_setup.get("price", 0.0))
    strat_sl = float(candidate_setup.get("default_sl", 0.0))
    strat_tp = float(candidate_setup.get("default_tp", 0.0))
    strat_lot = float(candidate_setup.get("default_lot", 0.01))

    # 1. Fallback si no hay API Key configurada
    if not api_key or not api_key.strip():
        return {
            "approved": True,
            "confidence": 1.0,
            "ai_sl": strat_sl,
            "ai_tp": strat_tp,
            "suggested_lot": strat_lot,
            "risk_reward_ratio": 2.0,
            "opinion": "Operación ejecutada con SL/TP de la estrategia cuantitativa (IA no configurada)",
            "rejection_reason": "",
            "fallback": True,
            "latency_ms": 0.0
        }

    clean_key = api_key.strip()
    model = (model_name or DEFAULT_GEMINI_MODEL).strip()
    custom_url = (base_url or "").strip()
    provider = _detect_provider(model, custom_url)

    # 2. Formulación del Prompt con Aprendizaje por Contexto y Gestión de Riesgo
    balance = float(account_info.get("balance", 0.0))
    equity = float(account_info.get("equity", 0.0))
    free_margin = float(account_info.get("free_margin", 0.0))

    system_instruction = (
        "Eres un Gestor de Riesgo y Analista Cuantitativo Senior de Trading Algorítmico.\n"
        "Tu misión es validar o rechazar una señal candidata y optimizar la gestión de riesgo (SL y TP) "
        "en función del capital total de la cuenta, la volatilidad y los errores/aciertos pasados.\n\n"
        "REGLAS OBLIGATORIAS:\n"
        "1. Revisa el historial de trades recientes en este par. Si detectas el mismo patrón que causó una pérdida ('LOSS'), "
        "o si el contexto macro/volatilidad es adverso, RECHAZA la operación ('approved': false).\n"
        "2. Si la apruebas ('approved': true), calcula un SL (Stop Loss) y TP (Take Profit) precisos como precios absolutos. "
        "El SL debe colocarse en una zona de protección estructural lógica y el TP debe garantizar un Ratio Riesgo/Beneficio mínimo de 1:1.8 a 1:3.\n"
        "3. Debes responder ÚNICAMENTE en formato JSON válido, sin texto adicional fuera del JSON."
    )

    user_content = f"""
INFORMACIÓN DE CUENTA:
- Balance Total: ${balance:,.2f} USD
- Equidad: ${equity:,.2f} USD
- Margen Libre: ${free_margin:,.2f} USD

MEMORIA HISTÓRICA RECIENTE EN ESTE PAR (APRENDIZAJE PASADO):
{json.dumps(past_trades, indent=2, ensure_ascii=False) if past_trades else "No hay operaciones cerradas registradas aún para este par."}

SEÑAL CANDIDATA A EVALUAR:
- Símbolo: {symbol}
- Dirección: {signal}
- Precio Actual: {current_price}
- SL Sugerido por Estrategia: {strat_sl}
- TP Sugerido por Estrategia: {strat_tp}
- Lote Sugerido: {strat_lot}
- Confluencias Técnicas: {candidate_setup.get('confluence_score', 'N/A')}
- Detalles/Indicadores: {json.dumps(candidate_setup.get('details', {}), ensure_ascii=False)}

RESPONDE ÚNICAMENTE CON ESTE OBJETO JSON:
{{
  "approved": true,
  "confidence": 0.85,
  "ai_sl": {strat_sl},
  "ai_tp": {strat_tp},
  "suggested_lot": {strat_lot},
  "risk_reward_ratio": 2.0,
  "opinion": "Explicación breve de la confirmación o rechazo",
  "rejection_reason": ""
}}
"""

    start_time = time.time()
    endpoint = ""
    req_headers: Dict[str, str] = {}
    payload_obj: Any = None
    status_code = 0
    raw_res_text = ""

    try:
        if custom_url and "googleapis.com" not in custom_url:
            endpoint = custom_url.rstrip("/")
            if not endpoint.endswith("/chat/completions"):
                endpoint = f"{endpoint}/chat/completions"

            payload_obj = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {clean_key}"
            }

            req = urllib.request.Request(
                endpoint,
                data=payload_bytes,
                headers=req_headers,
                method="POST"
            )
        else:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
            payload_obj = {
                "systemInstruction": {
                    "parts": [{"text": system_instruction}]
                },
                "contents": [
                    {"parts": [{"text": user_content}]}
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.2,
                    "maxOutputTokens": 1000
                }
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {"Content-Type": "application/json"}

            req = urllib.request.Request(
                endpoint,
                data=payload_bytes,
                headers=req_headers,
                method="POST"
            )

        with urllib.request.urlopen(req, timeout=15) as response:
            status_code = response.getcode()
            raw_res_text = response.read().decode("utf-8")
            duration_ms = (time.time() - start_time) * 1000.0
            raw_json = json.loads(raw_res_text)

            # Extraer contenido de la respuesta según el proveedor
            ai_text = ""
            if "candidates" in raw_json and raw_json["candidates"]:
                parts = raw_json["candidates"][0].get("content", {}).get("parts", [])
                if parts:
                    ai_text = parts[0].get("text", "")
            elif "choices" in raw_json and raw_json["choices"]:
                ai_text = raw_json["choices"][0].get("message", {}).get("content", "")

            cleaned_text = _clean_json_text(ai_text)
            parsed_result: Dict[str, Any] = json.loads(cleaned_text)

            # Validar y asegurar campos de respuesta
            approved = bool(parsed_result.get("approved", True))
            confidence = float(parsed_result.get("confidence", 0.8))
            ai_sl = float(parsed_result.get("ai_sl", strat_sl))
            ai_tp = float(parsed_result.get("ai_tp", strat_tp))
            suggested_lot = float(parsed_result.get("suggested_lot", strat_lot))
            rr = float(parsed_result.get("risk_reward_ratio", 2.0))
            opinion = str(parsed_result.get("opinion", "Validado por IA"))
            rejection_reason = str(parsed_result.get("rejection_reason", ""))

            # Protección de seguridad básica de SL/TP
            if signal == "BUY":
                if ai_sl <= 0 or (current_price > 0 and ai_sl >= current_price):
                    ai_sl = strat_sl
                if ai_tp <= 0 or (current_price > 0 and ai_tp <= current_price):
                    ai_tp = strat_tp
            elif signal == "SELL":
                if ai_sl <= 0 or (current_price > 0 and ai_sl <= current_price):
                    ai_sl = strat_sl
                if ai_tp <= 0 or (current_price > 0 and ai_tp >= current_price):
                    ai_tp = strat_tp

            output_dict = {
                "approved": approved,
                "confidence": round(confidence, 2),
                "ai_sl": ai_sl,
                "ai_tp": ai_tp,
                "suggested_lot": suggested_lot,
                "risk_reward_ratio": round(rr, 2),
                "opinion": opinion,
                "rejection_reason": rejection_reason,
                "fallback": False,
                "latency_ms": round(duration_ms, 1),
                "provider": provider,
                "model": model
            }

            # Guardar log completo de la interacción
            log_file = ai_logger.log_interaction(
                event_type="EVALUATE_TRADE_SETUP",
                symbol=symbol,
                provider=provider,
                model=model,
                endpoint=endpoint,
                request_headers=req_headers,
                request_payload=payload_obj,
                response_status=status_code,
                duration_ms=duration_ms,
                raw_response=raw_res_text,
                parsed_response=output_dict,
                extra_meta={
                    "signal": signal,
                    "current_price": current_price,
                    "balance": balance,
                    "score": candidate_setup.get('confluence_score')
                }
            )
            output_dict["log_file"] = log_file
            return output_dict

    except Exception as e:
        # 🟢 Fallback ante errores de cuota (429), límites de tokens o errores de red
        duration_ms = (time.time() - start_time) * 1000.0
        err_str = str(e)

        fallback_output = {
            "approved": True,
            "confidence": 1.0,
            "ai_sl": strat_sl,
            "ai_tp": strat_tp,
            "suggested_lot": strat_lot,
            "risk_reward_ratio": 2.0,
            "opinion": f"Ejecución según análisis cuantitativo (Fallback IA: {err_str[:80]})",
            "rejection_reason": "",
            "fallback": True,
            "fallback_error": err_str,
            "latency_ms": round(duration_ms, 1),
            "provider": provider,
            "model": model
        }

        log_file = ai_logger.log_interaction(
            event_type="EVALUATE_TRADE_SETUP_FALLBACK",
            symbol=symbol,
            provider=provider,
            model=model,
            endpoint=endpoint,
            request_headers=req_headers,
            request_payload=payload_obj,
            response_status=status_code if status_code else 500,
            duration_ms=duration_ms,
            raw_response=raw_res_text,
            parsed_response=fallback_output,
            error=err_str,
            extra_meta={"signal": signal, "current_price": current_price}
        )
        fallback_output["log_file"] = log_file
        return fallback_output
