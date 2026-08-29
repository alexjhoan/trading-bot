import json
import re
import time
import socket
import threading
import random
import urllib.request
import urllib.error
from typing import Dict, Any, List, Tuple, Optional, Union
from core.ai_logger import ai_logger
from core.news_manager import news_manager
from core.market_context import calculate_psychological_levels, analyze_macro_multitimeframe
from core.candlestick_patterns import format_candlestick_summary_for_ai, detect_candlestick_patterns


DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"

# Control global de Rate Limit / Cooldown para evitar tormentas de peticiones 429
_GLOBAL_RATE_LIMIT_LOCK = threading.Lock()
_GLOBAL_RATE_LIMIT_UNTIL: float = 0.0
_LAST_AI_REQUEST_TIME: float = 0.0
_MIN_AI_REQUEST_SPACING: float = 1.5  # Espacio mínimo obligatorio entre peticiones individuales


def _wait_for_global_cooldown() -> None:
    """Espera si existe un cooldown activo por Rate Limit (HTTP 429) o asegura espaciado mínimo."""
    global _GLOBAL_RATE_LIMIT_UNTIL, _LAST_AI_REQUEST_TIME
    with _GLOBAL_RATE_LIMIT_LOCK:
        now = time.time()
        # 1. Cooldown de seguridad por 429
        if now < _GLOBAL_RATE_LIMIT_UNTIL:
            wait_remaining = _GLOBAL_RATE_LIMIT_UNTIL - now
            time.sleep(wait_remaining)
            now = time.time()

        # 2. Espaciado mínimo entre peticiones sucesivas para evitar bursts
        time_since_last = now - _LAST_AI_REQUEST_TIME
        if time_since_last < _MIN_AI_REQUEST_SPACING:
            time.sleep(_MIN_AI_REQUEST_SPACING - time_since_last)

        _LAST_AI_REQUEST_TIME = time.time()


def _set_global_cooldown(seconds: float) -> None:
    """Establece una pausa global para todas las peticiones tras detectar un 429."""
    global _GLOBAL_RATE_LIMIT_UNTIL
    with _GLOBAL_RATE_LIMIT_LOCK:
        _GLOBAL_RATE_LIMIT_UNTIL = max(_GLOBAL_RATE_LIMIT_UNTIL, time.time() + seconds)

# Proveedores soportados con sus configuraciones por defecto
PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "Google Gemini": {
        "default_model": "gemini-3.6-flash",
        "models": [
            "gemini-3.6-flash"
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
        "default_model": "google/gemini-3.6-flash",
        "models": [
            "google/gemini-3.6-flash",
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



def clean_symbol_name(symbol: str) -> str:
    """
    Limpia sufijos y prefijos de brokers en símbolos de Forex, Criptos e Índices usando Regex.
    Ejemplos:
      - EURUSD_r, EURUSD.pro, EURUSD_RAW, EURUSDm -> EURUSD
      - US30_r, US30.cash, US500.pro, USTEC_i -> US30, US500, USTEC
      - XAUUSD_r, XAUUSD.a -> XAUUSD
      - BTCUSD_r, ETHUSD.ecn -> BTCUSD, ETHUSD
      - GER40.cash, DE40_r, UK100_r -> GER40, DE40, UK100
      - NAS100_r, SPX500_r -> NAS100, SPX500
    """
    if not symbol:
        return ""
    sym = symbol.strip().upper()

    # 1. Quitar separadores como slashes o guiones
    sym = sym.replace("/", "").replace("\\", "")

    # 2. Expresión regular para remover sufijos típicos de brokers (.r, _r, _pro, .cash, _ecn, .raw, _i, etc.)
    # Detecta punto, guión bajo o final de string con sufijos conocidos
    sym_cleaned = re.sub(r"([._-])?(RAW|PRO|ECN|STP|CASH|PLUS|MINI|MICRO|STD|ZERO|VIP|[A-Z])$", "", sym, flags=re.IGNORECASE)

    # Si la limpieza anterior dejó el símbolo intacto o vacío, aplicar regex de divisas e índices
    # Para pares Forex estándar de 6 letras (ej. EURUSD, AUDNZD)
    match_forex = re.match(r"^([A-Z]{6})", sym)
    if match_forex:
        return match_forex.group(1)

    # Para Commodities / Metales (XAUUSD, XAGUSD, GOLD, SILVER)
    match_metals = re.match(r"^(XAUUSD|XAGUSD|GOLD|SILVER|USOIL|UKOIL|BRENT|WTI)", sym)
    if match_metals:
        return match_metals.group(1)

    # Para Criptomonedas (BTCUSD, ETHUSD, SOLUSD, XRPUSD, etc.)
    match_crypto = re.match(r"^(BTCUSD|ETHUSD|SOLUSD|XRPUSD|BNBUSD|DOGEUSD|LTCUSD|ADAUSD)", sym)
    if match_crypto:
        return match_crypto.group(1)

    # Para Índices sintéticos y bursátiles (US30, US500, US100, NAS100, SPX500, GER40, DE40, UK100, JP225, HK50, EU50, AUS200, VOLATILITY 75, etc.)
    match_index = re.match(r"^([A-Z]{2,6}\d{2,4}|[A-Z]+\d+)", sym)
    if match_index:
        return match_index.group(1)

    # Si no hubo match específico, remover cualquier sufijo posterior a '.', '_' o '-'
    generic_clean = re.split(r"[._-]", sym)[0]
    return generic_clean if len(generic_clean) >= 3 else sym


def _clean_json_text(raw_text: str) -> Any:
    """
    Limpia y extrae un bloque JSON (objeto dict o array list) de la respuesta de la IA.
    Soporta bloques de código markdown ```json ... ``` y respuestas con prefijos explicativos.
    """
    if not raw_text:
        return {}
    cleaned = raw_text.strip()

    # 1. Intentar decodificar directo si ya viene como JSON válido
    try:
        res = json.loads(cleaned)
        if isinstance(res, (dict, list)):
            return res
    except Exception:
        pass

    # 2. Intentar extraer de bloques ```json ... ``` o ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if match:
        block = match.group(1).strip()
        try:
            res = json.loads(block)
            if isinstance(res, (dict, list)):
                return res
        except Exception:
            cleaned = block

    # 3. Detectar si el inicio prioritario es un array '[' o un objeto '{'
    start_brace = cleaned.find("{")
    start_bracket = cleaned.find("[")

    # Caso Array [...]
    if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
        end_bracket = cleaned.rfind("]")
        if end_bracket != -1 and end_bracket > start_bracket:
            sub_str = cleaned[start_bracket:end_bracket + 1].strip()
            try:
                res = json.loads(sub_str)
                if isinstance(res, list):
                    return res
            except Exception:
                pass
        # Reparación de array truncado
        sub_str = cleaned[start_bracket:].strip()
        for closure in ["]", '"}]', '"}]', '}]', "}]"]:
            try:
                res = json.loads(sub_str + closure)
                if isinstance(res, list):
                    return res
            except Exception:
                pass

    # Caso Objeto {...}
    if start_brace != -1:
        end_brace = cleaned.rfind("}")
        if end_brace != -1 and end_brace > start_brace:
            sub_str = cleaned[start_brace:end_brace + 1].strip()
            try:
                res = json.loads(sub_str)
                if isinstance(res, dict):
                    return res
            except Exception:
                pass
        # Reparación de objeto truncado
        sub_str = cleaned[start_brace:].strip()
        for closure in ["}", '"}', '" }', '0 }', 'false }', '"" }']:
            try:
                res = json.loads(sub_str + closure)
                if isinstance(res, dict):
                    return res
            except Exception:
                pass

    # Si todo falla, intentar json.loads estándar para que arroje la excepción controlada
    return json.loads(cleaned)


def send_ai_http_with_retry(
    endpoint: str,
    payload_bytes: bytes,
    headers: Dict[str, str],
    max_retries: int = 3,
    timeout_seconds: float = 8.0,
    action_label: str = "IA_CALL"
) -> Tuple[int, str, float]:
    """
    Envía peticiones HTTP a la API de IA (Gemini / OpenAI / Groq) con reintento automático
    ante timeouts o errores transitorios del servidor (500, 502, 503, 504, 429).

    Aplica cooldown global y backoff exponencial con jitter cuando detecta HTTP 429 (Rate Limit).
    Retorna: (status_code, raw_response_text, total_duration_ms)
    """
    start_total_time = time.time()
    last_exception: Optional[Exception] = None

    for intento in range(max_retries):
        try:
            # Respetar cualquier cooldown activo por un 429 anterior
            _wait_for_global_cooldown()

            req = urllib.request.Request(
                endpoint,
                data=payload_bytes,
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                status_code = response.getcode()
                raw_text = response.read().decode("utf-8", errors="replace")
                total_duration_ms = (time.time() - start_total_time) * 1000.0
                return status_code, raw_text, total_duration_ms

        except urllib.error.HTTPError as he:
            last_exception = he
            err_body = he.read().decode("utf-8", errors="ignore")

            # Manejo específico y robusto para HTTP 429 (Rate Limit / Quota)
            if he.code == 429:
                wait_time = 5.0 * (2 ** intento) + random.uniform(0.5, 1.5)
                _set_global_cooldown(wait_time)
                print(f"⚠️ [{action_label}] Rate Limit / 429 detectado. Cooldown activo ({wait_time:.1f}s) - Reintento {intento + 1}/{max_retries}...")
                if intento < max_retries - 1:
                    time.sleep(wait_time)
                    continue

            # Errores transitorios del servidor (500, 502, 503, 504)
            elif he.code in (500, 502, 503, 504) and intento < max_retries - 1:
                wait_time = 1.0 + (intento * 0.5)
                print(f"⚠️ [{action_label}] Error HTTP {he.code} en servidor de IA. Reintentando ({intento + 1}/{max_retries}) en {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            # Error no recuperable o se agotaron los reintentos
            he.msg = f"{he.msg} | {err_body}"
            raise he

        except (socket.timeout, TimeoutError) as te:
            last_exception = te
            if intento < max_retries - 1:
                wait_time = 0.8 + (intento * 0.4)
                print(f"⏳ [{action_label}] Timeout ({timeout_seconds}s) en intento {intento + 1}/{max_retries}. Reintentando petición en {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ [{action_label}] Timeout definitivo tras {max_retries} intentos ({timeout_seconds}s c/u). Activando fallback...")
                raise te

        except urllib.error.URLError as ue:
            last_exception = ue
            reason_str = str(ue.reason).lower()
            is_timeout = "timed out" in reason_str or isinstance(ue.reason, (socket.timeout, TimeoutError))
            if intento < max_retries - 1:
                wait_time = 1.0
                tag = "Timeout" if is_timeout else "Error de red"
                print(f"⏳ [{action_label}] {tag} ({ue.reason}) en intento {intento + 1}/{max_retries}. Reintentando en {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            else:
                raise ue

        except Exception as e:
            last_exception = e
            if intento < max_retries - 1 and any(k in str(e).lower() for k in ["timeout", "connection", "disconnected", "reset"]):
                wait_time = 1.0
                print(f"⚠️ [{action_label}] Error de conexión ({e}). Reintentando ({intento + 1}/{max_retries}) en {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            raise e

    if last_exception:
        raise last_exception
    raise RuntimeError(f"[{action_label}] Fallo desconocido tras {max_retries} reintentos.")


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

        # Petición con reintento automático y timeout controlado
        status_code, raw_res_text, duration_ms = send_ai_http_with_retry(
            endpoint=endpoint,
            payload_bytes=payload_bytes,
            headers=req_headers,
            max_retries=2,
            timeout_seconds=8.0,
            action_label="TEST_IA"
        )

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
        err_msg = str(he.msg)
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


def evaluate_trade_setup_direct(
    account_info: Dict[str, Any],
    candidate_setup: Dict[str, Any],
    past_trades: List[Dict[str, Any]],
    api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    thinking_budget: Optional[int] = 128
) -> Dict[str, Any]:
    """
    Evalúa una señal candidata individual directamente mediante la IA con inyección de memoria histórica (Few-Shot Context).
    Realiza gestión de riesgo sobre el capital total y calcula/ajusta SL y TP óptimos.
    Registra automáticamente el payload, request, response y depuración en ia-log/semana_WW_YYYY/YYYY-MM-DD.log.

    Si la IA falla o no tiene tokens, aplica fallback transparente para no bloquear la operativa.
    """
    symbol = candidate_setup.get("symbol", "UNKNOWN")
    clean_symbol = clean_symbol_name(symbol)
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

    # 2. Formulación del Prompt Optimizado para Bajo Consumo de Tokens y Estricta Validación
    balance = float(account_info.get("balance", 0.0))
    equity = float(account_info.get("equity", 0.0))
    free_margin = float(account_info.get("free_margin", 0.0))

    # Resumen de memoria histórica compacto (Few-Shot Context)
    if not past_trades:
        history_summary = "Sin operaciones previas registradas."
    else:
        hist_items = []
        for t in past_trades[:4]:
            out = t.get("outcome", {})
            res = out.get("result", "N/A")
            pnl_usd = float(out.get("pnl_usd", out.get("profit", 0.0)))
            pnl_r = float(out.get("pnl_r", 0.0))
            exit_r = out.get("exit_reason", "")
            hist_items.append(f"[{t.get('signal', 'ORD')} -> {res} ({pnl_r:+.1f}R / ${pnl_usd:+.2f}, Salida: {exit_r})]")
        history_summary = " | ".join(hist_items)

    # Filtros avanzados en vivo
    timeframe = str(candidate_setup.get("timeframe", "M15"))
    details = candidate_setup.get("details", {})
    atr_val = candidate_setup.get("atr", details.get("atr", "0.00015"))
    if isinstance(atr_val, (int, float)):
        atr_str = f"{float(atr_val):.5f}"
    else:
        atr_str = str(atr_val)

    news_summary = candidate_setup.get("news_summary") or news_manager.format_news_summary_for_ai(clean_symbol)
    macro_summary = candidate_setup.get("macro_summary") or analyze_macro_multitimeframe(symbol, current_price)
    psych_summary = candidate_setup.get("psych_summary") or calculate_psychological_levels(symbol, current_price)
    spread_info = candidate_setup.get("spread_info", "Spread normal")
    candlestick_summary = candidate_setup.get("candlestick_summary")
    if not candlestick_summary and "df" in candidate_setup:
        candlestick_summary = format_candlestick_summary_for_ai(candidate_setup["df"])
    if not candlestick_summary:
        candlestick_summary = "Patrón de Vela: Acción de precio estándar [NEUTRAL]"

    is_reentry = candidate_setup.get("is_reentry") or details.get("is_reentry", False)
    reentry_num = details.get("reentry_number", 1)
    fibo_pct = details.get("fibo_level_pct", 78.6)
    fibo_px = details.get("fibo_target_price", current_price)
    reentry_tag = f" [⚡ REENTRADA #{reentry_num} - Nivel Fibonacci {fibo_pct}% | Objetivo: {fibo_px}]" if is_reentry else " [NUEVA ENTRADA BASE - Fibo 61.8%]"

    system_instruction = (
        "Eres un Gestor de Riesgo Cuantitativo Senior de Trading Algorítmico.\n"
        "Validas o rechazas señales candidatas analizando micro-contexto, macro-tendencia, liquidez, patrones de velas, niveles de Fibonacci y riesgo.\n\n"
        "REGLAS DE BLOQUEO Y APROBACIÓN ESTRICTAS:\n"
        "1. Rechaza ('approved': false) si hay noticias de alto impacto (HIGH) en <30 min.\n"
        "2. Rechaza ('approved': false) si el spread actual es anómalo/alto (>3.0 pips) o coincide con cierre de sesión/rollover.\n"
        "3. Rechaza o ajusta si la entrada/TP choca directamente contra un nivel psicológico institucional (ej. 0.XX00 / 0.XX50).\n"
        "4. Rechaza si la señal en M15 contradice la estructura Macro (H4/D1).\n"
        "5. CONFLUENCIA DE VELAS: Prioriza ('approved': true) compras BUY respaldadas por patrones alcistas (Morning Star, Hammer, Bullish Engulfing, Three White Soldiers, Rising Three, Piercing Line, Bullish Harami); y ventas SELL respaldadas por patrones bajistas (Evening Star, Shooting Star, Bearish Engulfing, Three Black Crows, Falling Three, Dark Cloud Cover, Bearish Harami).\n"
        "6. ESCALERA DE REENTRADAS EN FIBONACCI (78.6%, 92%, 100%, 132%, etc.): Si se evalúa una REENTRADA, valida que el precio se encuentre en un retroceso institucional óptimo, respetando la estructura con volumen o rechazo.\n"
        "7. Si apruebas, define SL/TP con R:R de 1:1.8 a 1:3 responder estricto en el esquema definido."
    )

    user_content = (
        f"CUENTA: Eq ${equity:,.2f} USD | Historial {clean_symbol}: {history_summary}\n\n"
        f"SEÑAL EN EVALUACIÓN ({timeframe}){reentry_tag}:\n"
        f"- Par: {clean_symbol} | Dirección: {signal} | Precio: {current_price}\n"
        f"- Sugerido: SL {strat_sl} | TP {strat_tp} | Lote {strat_lot} | ATR {atr_str}\n\n"
        f"FILTROS AVANZADOS (CONTEXTO EN VIVO):\n"
        f"- SPREAD & LIQUIDEZ: {spread_info}\n"
        f"- PATRÓN DE VELAS: {candlestick_summary}\n"
        f"- NOTICIAS: {news_summary}\n"
        f"- MACRO (D1/H4): {macro_summary}\n"
        f"- NIVELES INSTITUCIONALES: {psych_summary}"
    )

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "approved": {"type": "BOOLEAN"},
            "confidence": {"type": "NUMBER"},
            "ai_sl": {"type": "NUMBER"},
            "ai_tp": {"type": "NUMBER"},
            "suggested_lot": {"type": "NUMBER"},
            "risk_reward_ratio": {"type": "NUMBER"},
            "opinion": {"type": "STRING", "description": "Breve razón técnica de validación o bloqueo"},
            "rejection_reason": {"type": "STRING", "description": "SPREAD_ANOMALY, NEWS_HIGH_IMPACT, MACRO_DIVERGENCE, PSYCHOLOGICAL_LEVEL u OK"}
        },
        "required": ["approved", "confidence", "ai_sl", "ai_tp", "suggested_lot", "risk_reward_ratio", "opinion", "rejection_reason"]
    }

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
                "temperature": 0.1,
                "max_tokens": 1024,
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
            gen_cfg: Dict[str, Any] = {
                "responseMimeType": "application/json",
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "responseSchema": response_schema
            }
            if thinking_budget is not None and thinking_budget >= 0:
                gen_cfg["thinkingConfig"] = {
                    "thinkingBudget": int(thinking_budget)
                }

            payload_obj = {
                "systemInstruction": {
                    "parts": [{"text": system_instruction}]
                },
                "contents": [
                    {"parts": [{"text": user_content}]}
                ],
                "generationConfig": gen_cfg
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {"Content-Type": "application/json"}

        # Enviar petición a IA con reintento automático ante timeouts o saturación
        status_code, raw_res_text, duration_ms = send_ai_http_with_retry(
            endpoint=endpoint,
            payload_bytes=payload_bytes,
            headers=req_headers,
            max_retries=3,
            timeout_seconds=8.0,
            action_label=f"EVAL_{clean_symbol}"
        )

        raw_json = json.loads(raw_res_text)

        # Extraer contenido de la respuesta según el proveedor
        ai_text = ""
        if "candidates" in raw_json and raw_json["candidates"]:
            first_cand = raw_json["candidates"][0]
            parts = first_cand.get("content", {}).get("parts", [])
            if parts:
                texts = [p.get("text", "") for p in parts if "text" in p and p.get("text")]
                ai_text = "\n".join(texts)
        elif "choices" in raw_json and raw_json["choices"]:
            ai_text = raw_json["choices"][0].get("message", {}).get("content", "")

        parsed_result = _clean_json_text(ai_text)
        if not isinstance(parsed_result, dict):
            parsed_result = json.loads(str(parsed_result))

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

    except urllib.error.HTTPError as he:
        duration_ms = (time.time() - start_time) * 1000.0
        err_body = he.read().decode("utf-8", errors="ignore")
        err_str = f"HTTP Error {he.code}: {err_body}"

        fallback_output = {
            "approved": True,
            "confidence": 1.0,
            "ai_sl": strat_sl,
            "ai_tp": strat_tp,
            "suggested_lot": strat_lot,
            "risk_reward_ratio": 2.0,
            "opinion": f"Ejecución según estrategia cuantitativa (Fallback IA HTTP {he.code})",
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
            response_status=he.code,
            duration_ms=duration_ms,
            raw_response=err_body,
            parsed_response=fallback_output,
            error=err_str,
            extra_meta={"signal": signal, "current_price": current_price}
        )
        fallback_output["log_file"] = log_file
        return fallback_output

    except Exception as e:
        # Fallback ante errores de cuota (429), límites de tokens o errores de red
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


def evaluate_batch_trade_setups(
    account_info: Dict[str, Any],
    candidate_setups: List[Dict[str, Any]],
    past_trades_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    api_key: str = "",
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    thinking_budget: Optional[int] = 100
) -> Dict[str, Dict[str, Any]]:
    """
    Evalúa un LOTE de señales candidatas en una ÚNICA petición HTTP a la IA.
    Evita de raíz el error 429 por exceso de peticiones concurrentes y distribuye
    las respuestas resultantes a sus respectivos análisis y consolas por símbolo.

    Retorna un diccionario {symbol: output_dict}.
    """
    if not candidate_setups:
        return {}

    # Si no hay API key, retornar fallback inmediato para todos los pares del lote
    if not api_key or not api_key.strip():
        fallbacks: Dict[str, Dict[str, Any]] = {}
        for cs in candidate_setups:
            sym = cs.get("symbol", "UNKNOWN")
            sl = float(cs.get("default_sl", 0.0))
            tp = float(cs.get("default_tp", 0.0))
            lot = float(cs.get("default_lot", 0.01))
            fallbacks[sym] = {
                "symbol": sym,
                "approved": True,
                "confidence": 1.0,
                "ai_sl": sl,
                "ai_tp": tp,
                "suggested_lot": lot,
                "risk_reward_ratio": 2.0,
                "opinion": "Operación ejecutada con SL/TP cuantitativo (IA no configurada)",
                "rejection_reason": "",
                "fallback": True,
                "latency_ms": 0.0
            }
        return fallbacks

    clean_key = api_key.strip()
    model = (model_name or DEFAULT_GEMINI_MODEL).strip()
    custom_url = (base_url or "").strip()
    provider = _detect_provider(model, custom_url)
    balance = float(account_info.get("balance", 0.0))
    equity = float(account_info.get("equity", 0.0))

    # 1. Construcción del Prompt del Lote (Batch Content)
    system_instruction = (
        "Eres un Gestor de Riesgo Cuantitativo Senior de Trading Algorítmico.\n"
        "Tu misión es evaluar una lista de señales candidatas en paralelo de forma independiente.\n\n"
        "REGLAS:\n"
        "1. Rechaza ('approved': false) si detectas spread alto, noticias en <30 min, o conflicto macro.\n"
        "2. Si apruebas, define SL/TP con R:R 1:1.8 a 1:3.\n"
        "3. Responde una lista JSON donde cada objeto corresponde exactamente a un par ingresado."
    )

    prompt_items = []
    for idx, setup in enumerate(candidate_setups, 1):
        sym = setup.get("symbol", f"PAIR_{idx}")
        clean_sym = clean_symbol_name(sym)
        sig = setup.get("signal", "HOLD")
        px = float(setup.get("price", 0.0))
        sl = float(setup.get("default_sl", 0.0))
        tp = float(setup.get("default_tp", 0.0))
        lot = float(setup.get("default_lot", 0.01))

        details = setup.get("details", {})
        atr_val = setup.get("atr", details.get("atr", "0.0010"))
        atr_str = f"{float(atr_val):.5f}" if isinstance(atr_val, (int, float)) else str(atr_val)

        spread = setup.get("spread_info", "Spread normal")
        news = setup.get("news_summary") or news_manager.format_news_summary_for_ai(clean_sym)
        macro = setup.get("macro_summary") or analyze_macro_multitimeframe(sym, px)
        candle = setup.get("candlestick_summary")
        if not candle and "df" in setup:
            candle = format_candlestick_summary_for_ai(setup["df"])
        if not candle:
            candle = "Estructura de velas estándar"

        is_reentry = setup.get("is_reentry") or details.get("is_reentry", False)
        reentry_num = details.get("reentry_number", 1)
        fibo_pct = details.get("fibo_level_pct", 78.6)
        reentry_tag = f" ⚡ REENTRADA #{reentry_num} (Fibo {fibo_pct}%)" if is_reentry else ""

        # Recuperar memoria histórica específica de este par
        trades_for_sym = []
        if past_trades_by_symbol:
            trades_for_sym = past_trades_by_symbol.get(sym) or past_trades_by_symbol.get(clean_sym) or []
        if not trades_for_sym and "past_trades" in setup:
            trades_for_sym = setup.get("past_trades", [])

        if trades_for_sym:
            hist_parts = []
            for t in trades_for_sym[:3]:
                out = t.get("outcome", {})
                res = out.get("result", "N/A")
                pnl_r = float(out.get("pnl_r", 0.0))
                pnl_usd = float(out.get("pnl_usd", 0.0))
                hist_parts.append(f"{t.get('signal', 'ORD')}->{res}({pnl_r:+.1f}R/${pnl_usd:+.2f})")
            hist_str = f"Historial {clean_sym}: " + " | ".join(hist_parts)
        else:
            hist_str = f"Historial {clean_sym}: Sin operaciones previas"

        prompt_items.append(
            f"{idx}. [{clean_sym}]{reentry_tag}\n"
            f"   - Dirección: {sig} | Precio: {px} | SL Sugerido: {sl} | TP: {tp} | Lote: {lot} | ATR: {atr_str}\n"
            f"   - Contexto: {spread} | {news} | Macro: {macro} | {candle}\n"
            f"   - {hist_str}."
        )

    user_content = "EVALÚA LAS SIGUIENTES SEÑALES CANDIDATAS:\n\n" + "\n\n".join(prompt_items)

    # 2. Esquema JSON de Respuesta en Lista (Array de Objetos)
    batch_response_schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "pair": {"type": "STRING"},
                "approved": {"type": "BOOLEAN"},
                "confidence": {"type": "NUMBER"},
                "ai_sl": {"type": "NUMBER"},
                "ai_tp": {"type": "NUMBER"},
                "suggested_lot": {"type": "NUMBER"},
                "opinion": {"type": "STRING"},
                "rejection_reason": {"type": "STRING"}
            },
            "required": ["pair", "approved", "confidence", "ai_sl", "ai_tp", "suggested_lot", "opinion", "rejection_reason"]
        }
    }

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
                    {"role": "system", "content": system_instruction + "\nResponde un array JSON [ {pair, approved, confidence, ai_sl, ai_tp, suggested_lot, opinion, rejection_reason}, ... ]"},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.1,
                "max_tokens": 2048,
                "response_format": {"type": "json_object"}
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {clean_key}"
            }
        else:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
            gen_cfg: Dict[str, Any] = {
                "responseMimeType": "application/json",
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "responseSchema": batch_response_schema
            }
            if thinking_budget is not None and thinking_budget >= 0:
                gen_cfg["thinkingConfig"] = {
                    "thinkingBudget": int(thinking_budget)
                }

            payload_obj = {
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "contents": [{"parts": [{"text": user_content}]}],
                "generationConfig": gen_cfg
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {"Content-Type": "application/json"}

        # Enviar ÚNICA petición para todos los símbolos
        status_code, raw_res_text, duration_ms = send_ai_http_with_retry(
            endpoint=endpoint,
            payload_bytes=payload_bytes,
            headers=req_headers,
            max_retries=3,
            timeout_seconds=10.0,
            action_label=f"BATCH_{len(candidate_setups)}_PAIRS"
        )

        raw_json = json.loads(raw_res_text)
        ai_text = ""
        if "candidates" in raw_json and raw_json["candidates"]:
            first_cand = raw_json["candidates"][0]
            parts = first_cand.get("content", {}).get("parts", [])
            if parts:
                texts = [p.get("text", "") for p in parts if "text" in p and p.get("text")]
                ai_text = "\n".join(texts)
        elif "choices" in raw_json and raw_json["choices"]:
            ai_text = raw_json["choices"][0].get("message", {}).get("content", "")

        parsed_array = _clean_json_text(ai_text)

        # Normalizar si vino envuelto en un diccionario
        if isinstance(parsed_array, dict):
            for k in ["evaluations", "pairs", "signals", "results", "items", "data", "list"]:
                if k in parsed_array and isinstance(parsed_array[k], list):
                    parsed_array = parsed_array[k]
                    break
            if isinstance(parsed_array, dict):
                parsed_array = [parsed_array]

        if not isinstance(parsed_array, list):
            parsed_array = []

        # 3. Separar y distribuir las respuestas por símbolo correspondiente
        results_by_symbol: Dict[str, Dict[str, Any]] = {}
        for idx, setup in enumerate(candidate_setups):
            orig_symbol = setup.get("symbol", f"PAIR_{idx+1}")
            clean_sym = clean_symbol_name(orig_symbol)
            sig = setup.get("signal", "HOLD")
            px = float(setup.get("price", 0.0))
            strat_sl = float(setup.get("default_sl", 0.0))
            strat_tp = float(setup.get("default_tp", 0.0))
            strat_lot = float(setup.get("default_lot", 0.01))

            # Buscar el objeto correspondiente en el array de respuestas
            matched_item: Optional[Dict[str, Any]] = None
            for item in parsed_array:
                if not isinstance(item, dict):
                    continue
                item_pair = clean_symbol_name(str(item.get("pair", "")))
                if item_pair == clean_sym or item.get("pair") == orig_symbol:
                    matched_item = item
                    break

            # Si no hubo match por nombre, intentar por posición de índice
            if matched_item is None and idx < len(parsed_array) and isinstance(parsed_array[idx], dict):
                matched_item = parsed_array[idx]

            if matched_item:
                appr = bool(matched_item.get("approved", True))
                conf = float(matched_item.get("confidence", 0.8))
                ai_sl = float(matched_item.get("ai_sl", strat_sl))
                ai_tp = float(matched_item.get("ai_tp", strat_tp))
                lot = float(matched_item.get("suggested_lot", strat_lot))
                op = str(matched_item.get("opinion", "Evaluado en lote de IA"))
                rej = str(matched_item.get("rejection_reason", ""))

                # Validación de seguridad geométrica para SL y TP
                if sig == "BUY":
                    if ai_sl >= px:
                        ai_sl = strat_sl
                    if ai_tp <= px:
                        ai_tp = strat_tp
                elif sig == "SELL":
                    if ai_sl <= px:
                        ai_sl = strat_sl
                    if ai_tp >= px:
                        ai_tp = strat_tp

                sl_dist = abs(px - ai_sl)
                tp_dist = abs(ai_tp - px)
                rr_val = round(tp_dist / sl_dist, 2) if sl_dist > 1e-6 else 2.0

                sym_output = {
                    "symbol": orig_symbol,
                    "approved": appr,
                    "confidence": round(conf, 2),
                    "ai_sl": ai_sl,
                    "ai_tp": ai_tp,
                    "suggested_lot": lot,
                    "risk_reward_ratio": rr_val,
                    "opinion": op,
                    "rejection_reason": rej,
                    "fallback": False,
                    "latency_ms": round(duration_ms, 1),
                    "provider": provider,
                    "model": model,
                    "batch_size": len(candidate_setups)
                }
            else:
                sym_output = {
                    "symbol": orig_symbol,
                    "approved": True,
                    "confidence": 1.0,
                    "ai_sl": strat_sl,
                    "ai_tp": strat_tp,
                    "suggested_lot": strat_lot,
                    "risk_reward_ratio": 2.0,
                    "opinion": "Operación ejecutada con SL/TP cuantitativo (Fallback de lote)",
                    "rejection_reason": "",
                    "fallback": True,
                    "latency_ms": round(duration_ms, 1),
                    "provider": provider,
                    "model": model,
                    "batch_size": len(candidate_setups)
                }

            # Registrar log individual para auditoría
            log_file = ai_logger.log_interaction(
                event_type="EVALUATE_TRADE_SETUP_BATCH_ITEM",
                symbol=orig_symbol,
                provider=provider,
                model=model,
                endpoint=endpoint,
                request_headers=req_headers,
                request_payload={"batch_count": len(candidate_setups), "item": setup},
                response_status=status_code,
                duration_ms=duration_ms,
                raw_response=raw_res_text,
                parsed_response=sym_output,
                extra_meta={"signal": sig, "price": px, "batch": True}
            )
            sym_output["log_file"] = log_file
            results_by_symbol[orig_symbol] = sym_output

        return results_by_symbol

    except urllib.error.HTTPError as he:
        duration_ms = (time.time() - start_time) * 1000.0
        err_body = he.read().decode("utf-8", errors="ignore")
        err_str = f"HTTP Error {he.code}: {err_body}"

        fallbacks = {}
        for setup in candidate_setups:
            sym = setup.get("symbol", "UNKNOWN")
            sl = float(setup.get("default_sl", 0.0))
            tp = float(setup.get("default_tp", 0.0))
            lot = float(setup.get("default_lot", 0.01))
            fallbacks[sym] = {
                "symbol": sym,
                "approved": True,
                "confidence": 1.0,
                "ai_sl": sl,
                "ai_tp": tp,
                "suggested_lot": lot,
                "risk_reward_ratio": 2.0,
                "opinion": f"Ejecución según estrategia cuantitativa (Fallback Lote HTTP {he.code})",
                "rejection_reason": "",
                "fallback": True,
                "fallback_error": err_str,
                "latency_ms": round(duration_ms, 1),
                "provider": provider,
                "model": model
            }
        return fallbacks

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000.0
        err_str = str(e)
        fallbacks = {}
        for setup in candidate_setups:
            sym = setup.get("symbol", "UNKNOWN")
            sl = float(setup.get("default_sl", 0.0))
            tp = float(setup.get("default_tp", 0.0))
            lot = float(setup.get("default_lot", 0.01))
            fallbacks[sym] = {
                "symbol": sym,
                "approved": True,
                "confidence": 1.0,
                "ai_sl": sl,
                "ai_tp": tp,
                "suggested_lot": lot,
                "risk_reward_ratio": 2.0,
                "opinion": f"Ejecución cuantitativa (Fallback Lote: {err_str[:60]})",
                "rejection_reason": "",
                "fallback": True,
                "fallback_error": err_str,
                "latency_ms": round(duration_ms, 1),
                "provider": provider,
                "model": model
            }
        return fallbacks


class AIBatchCoordinator:
    """
    Coordinador de Lote de Inteligencia Artificial para Setups de Entrada.
    Agrupa peticiones de múltiples hilos (SymbolWorker) generadas simultáneamente
    en una única llamada batch a la API de IA para erradicar por completo los errores HTTP 429.
    Desempaqueta las respuestas y notifica a cada hilo individualmente con su análisis correspondiente.
    """
    def __init__(self, coalesce_window_seconds: float = 0.25):
        self._window = coalesce_window_seconds
        self._lock = threading.Lock()
        self._pending: List[Dict[str, Any]] = []
        self._timer: Optional[threading.Timer] = None

    def submit_trade_setup(
        self,
        account_info: Dict[str, Any],
        candidate_setup: Dict[str, Any],
        past_trades: List[Dict[str, Any]],
        api_key: str,
        model_name: str = DEFAULT_GEMINI_MODEL,
        base_url: str = "",
        thinking_budget: Optional[int] = 128
    ) -> Dict[str, Any]:
        """
        Encola una petición de evaluación de setup y espera a que el lote sea procesado.
        Si sólo hay una petición tras expirar la ventana, se procesa individualmente.
        """
        if not api_key or not api_key.strip():
            return evaluate_trade_setup_direct(
                account_info, candidate_setup, past_trades, api_key, model_name, base_url, thinking_budget
            )

        event = threading.Event()
        item = {
            "account_info": account_info,
            "setup": candidate_setup,
            "past_trades": past_trades,
            "api_key": api_key,
            "model_name": model_name,
            "base_url": base_url,
            "thinking_budget": thinking_budget,
            "event": event,
            "result": None
        }

        with self._lock:
            self._pending.append(item)
            if self._timer is None:
                self._timer = threading.Timer(self._window, self._flush)
                self._timer.daemon = True
                self._timer.start()

        # Esperar la resolución del lote (timeout seguro de 25s)
        event_ok = event.wait(timeout=25.0)
        if event_ok and item.get("result") is not None:
            return item["result"]

        return evaluate_trade_setup_direct(
            account_info, candidate_setup, past_trades, api_key, model_name, base_url, thinking_budget
        )

    def _flush(self) -> None:
        with self._lock:
            items_to_process = list(self._pending)
            self._pending.clear()
            self._timer = None

        if not items_to_process:
            return

        if len(items_to_process) == 1:
            it = items_to_process[0]
            try:
                res = evaluate_trade_setup_direct(
                    it["account_info"], it["setup"], it["past_trades"],
                    it["api_key"], it["model_name"], it["base_url"], it["thinking_budget"]
                )
                it["result"] = res
            except Exception as e:
                it["result"] = {
                    "approved": True,
                    "confidence": 1.0,
                    "ai_sl": float(it["setup"].get("default_sl", 0.0)),
                    "ai_tp": float(it["setup"].get("default_tp", 0.0)),
                    "suggested_lot": float(it["setup"].get("default_lot", 0.01)),
                    "risk_reward_ratio": 2.0,
                    "opinion": f"Fallback por excepción ({str(e)[:60]})",
                    "rejection_reason": "",
                    "fallback": True,
                    "latency_ms": 0.0
                }
            finally:
                it["event"].set()
            return

        # Peticiones múltiples concurrentes -> Batch unificado
        first = items_to_process[0]
        account_info = first["account_info"]
        api_key = first["api_key"]
        model_name = first["model_name"]
        base_url = first["base_url"]
        thinking_budget = first["thinking_budget"]

        setups = [it["setup"] for it in items_to_process]
        past_trades_map = {it["setup"].get("symbol", f"S_{i}"): it["past_trades"] for i, it in enumerate(items_to_process)}

        try:
            batch_results = evaluate_batch_trade_setups(
                account_info=account_info,
                candidate_setups=setups,
                past_trades_by_symbol=past_trades_map,
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
                thinking_budget=thinking_budget
            )
            for it in items_to_process:
                sym = it["setup"].get("symbol", "UNKNOWN")
                clean_sym = clean_symbol_name(sym)
                res = batch_results.get(sym) or batch_results.get(clean_sym)
                if not res:
                    res = {
                        "symbol": sym,
                        "approved": True,
                        "confidence": 1.0,
                        "ai_sl": float(it["setup"].get("default_sl", 0.0)),
                        "ai_tp": float(it["setup"].get("default_tp", 0.0)),
                        "suggested_lot": float(it["setup"].get("default_lot", 0.01)),
                        "risk_reward_ratio": 2.0,
                        "opinion": "Fallback cuantitativo (Resultado no hallado en lote)",
                        "rejection_reason": "",
                        "fallback": True,
                        "latency_ms": 0.0
                    }
                it["result"] = res
                it["event"].set()
        except Exception as e:
            for it in items_to_process:
                sym = it["setup"].get("symbol", "UNKNOWN")
                it["result"] = {
                    "symbol": sym,
                    "approved": True,
                    "confidence": 1.0,
                    "ai_sl": float(it["setup"].get("default_sl", 0.0)),
                    "ai_tp": float(it["setup"].get("default_tp", 0.0)),
                    "suggested_lot": float(it["setup"].get("default_lot", 0.01)),
                    "risk_reward_ratio": 2.0,
                    "opinion": f"Fallback por error en lote ({str(e)[:60]})",
                    "rejection_reason": "",
                    "fallback": True,
                    "latency_ms": 0.0
                }
                it["event"].set()


# Instancia singleton del coordinador de lote de setups
_ai_batch_coordinator = AIBatchCoordinator(coalesce_window_seconds=1.2)


def evaluate_trade_setup(
    account_info: Dict[str, Any],
    candidate_setup: Dict[str, Any],
    past_trades: List[Dict[str, Any]],
    api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    thinking_budget: Optional[int] = 128,
    use_batch_coordinator: bool = True
) -> Dict[str, Any]:
    """
    Evalúa una señal candidata mediante la IA con gestión de riesgo y SL/TP óptimos.
    Utiliza el coordinador de lotes para encapsular llamadas simultáneas en una única petición
    y evitar errores HTTP 429.
    """
    if use_batch_coordinator:
        return _ai_batch_coordinator.submit_trade_setup(
            account_info=account_info,
            candidate_setup=candidate_setup,
            past_trades=past_trades,
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            thinking_budget=thinking_budget
        )
    return evaluate_trade_setup_direct(
        account_info=account_info,
        candidate_setup=candidate_setup,
        past_trades=past_trades,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        thinking_budget=thinking_budget
    )


def evaluate_open_position_ai_direct(
    account_info: Dict[str, Any],
    position_info: Dict[str, Any],
    market_context: Dict[str, Any],
    api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    thinking_budget: Optional[int] = 128,
    past_trades: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Evalúa una posición abierta individual en tiempo real mediante IA con inyección de memoria histórica del par.
    """
    ticket = position_info.get("ticket", 0)
    symbol = position_info.get("symbol", "UNKNOWN")
    clean_symbol = clean_symbol_name(symbol)
    pos_type = position_info.get("type", "BUY")
    open_price = float(position_info.get("price_open", 0.0))
    current_price = float(position_info.get("price_current", open_price))
    current_sl = float(position_info.get("sl", 0.0))
    current_tp = float(position_info.get("tp", 0.0))
    volume = float(position_info.get("volume", 0.01))
    profit_pips = float(position_info.get("profit_pips", 0.0))
    profit_usd = float(position_info.get("profit_usd", 0.0))

    # Fallback inmediato si no hay API Key
    if not api_key or not api_key.strip():
        return {
            "action": "HOLD",
            "suggested_sl": current_sl,
            "suggested_tp": current_tp,
            "close_reason": "",
            "confidence": 1.0,
            "opinion": "Estrategia local activa (IA no configurada)",
            "fallback": True
        }

    clean_key = api_key.strip()
    model = (model_name or DEFAULT_GEMINI_MODEL).strip()
    custom_url = (base_url or "").strip()
    provider = _detect_provider(model, custom_url)

    ema_trend = float(market_context.get("ema_trend", current_price))
    current_atr = float(market_context.get("atr", 0.0))
    spread_pips = float(market_context.get("spread_pips", 1.0))
    macro_info = market_context.get("macro_summary", "Estructura estable")
    news_info = market_context.get("news_summary", "Sin noticias críticas")
    candlestick_summary = market_context.get("candlestick_summary")
    if not candlestick_summary and "df" in market_context:
        candlestick_summary = format_candlestick_summary_for_ai(market_context["df"])
    if not candlestick_summary:
        candlestick_summary = "Patrón de Vela: Estructura normal [NEUTRAL]"

    # Historial de trades específicos de este par
    if not past_trades:
        history_summary = "Sin operaciones previas registradas"
    else:
        hist_parts = []
        for t in past_trades[:3]:
            out = t.get("outcome", {})
            res = out.get("result", "N/A")
            pnl_r = float(out.get("pnl_r", 0.0))
            pnl_u = float(out.get("pnl_usd", 0.0))
            hist_parts.append(f"{t.get('signal', 'ORD')}->{res}({pnl_r:+.1f}R/${pnl_u:+.2f})")
        history_summary = " | ".join(hist_parts) if hist_parts else "Sin operaciones previas registradas"

    system_instruction = (
        "Eres un Gestor Cuantitativo de Posiciones Abiertas y Salidas de Emergencia en Forex.\n"
        "Tu misión es decidir si una operación activa debe MANTENERSE ('HOLD'), AJUSTAR SL/TP ('MODIFY_SLTP') o CERRARSE INMEDIATAMENTE ('EARLY_CLOSE').\n\n"
        "REGLAS ESTRICTAS DE MANTENIMIENTO ('HOLD') Y SALIDA ('EARLY_CLOSE'):\n"
        "1. 'HOLD' (MANTENER POSICIÓN ALCISTA - OBLIGATORIO): Si la posición es BUY y el patrón de velas reciente es de reversión alcista o continuación (ej. Morning Star, Hammer, Inverted Hammer, Bullish Engulfing, Three White Soldiers, Rising Three Methods, Piercing Line, Bullish Harami, Matching Low), DEBES MANTENER la orden abierta ('HOLD'). ¡NUNCA apruebes un cierre prematuro cuando el gráfico confirma soporte o rebote alcista institucional a favor de la operación!\n"
        "2. 'HOLD' (MANTENER POSICIÓN BAJISTA - OBLIGATORIO): Si la posición es SELL y el patrón de velas es bajista (ej. Evening Star, Shooting Star, Hanging Man, Bearish Engulfing, Three Black Crows, Falling Three Methods, Dark Cloud Cover, Bearish Harami, Matching High), DEBES MANTENER la orden abierta ('HOLD'). ¡NUNCA cierres antes de tiempo cuando el gráfico confirma la presión vendedora a favor de la orden!\n"
        "3. 'EARLY_CLOSE' (Cierre Prematuro Justificado): SOLO emitir 'EARLY_CLOSE' si se confirma un patrón de reversión FUERTE DIRECTAMENTE OPUESTO a la posición (ej. Evening Star o Shooting Star contra una compra BUY; o Morning Star o Hammer contra una venta SELL) sumado a quiebre de estructura o noticias críticas inminentes.\n"
        "4. 'MODIFY_SLTP' (Asegurar Ganancias): Si la posición está en beneficio (>10 pips) y el patrón confirma continuación, sugiere mover SL a Break-Even o asegurar ganancias protegiendo detrás del patrón de velas.\n"
        "Responde ESTRICTAMENTE con el esquema JSON indicado."
    )

    user_content = (
        f"ESTADO DE POSICIÓN ACTIVA #{ticket} ({clean_symbol}):\n"
        f"- Tipo: {pos_type} | Volumen: {volume} lotes | Precio Entrada: {open_price}\n"
        f"- Precio Actual: {current_price} | Flotante: ${profit_usd:+.2f} USD ({profit_pips:+.1f} pips)\n"
        f"- SL Actual: {current_sl} | TP Actual: {current_tp}\n"
        f"- Historial Previo ({clean_symbol}): {history_summary}\n\n"
        f"MÉTRICAS DE MERCADO Y ESTRUCTURA:\n"
        f"- EMA 200 Macro: {ema_trend:.5f} | ATR: {current_atr:.5f} | Spread: {spread_pips:.1f} pips\n"
        f"- PATRÓN DE VELAS RECIENTE: {candlestick_summary}\n"
        f"- Contexto Macro: {macro_info}\n"
        f"- Noticias: {news_info}"
    )

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["HOLD", "MODIFY_SLTP", "EARLY_CLOSE"]
            },
            "suggested_sl": {"type": "NUMBER"},
            "suggested_tp": {"type": "NUMBER"},
            "close_reason": {"type": "STRING", "description": "Razón en caso de EARLY_CLOSE (ej. 'Invalidacion_Tendencia_Macro')"},
            "confidence": {"type": "NUMBER"},
            "opinion": {"type": "STRING", "description": "Resumen técnico de la decisión de gestión"}
        },
        "required": ["action", "suggested_sl", "suggested_tp", "close_reason", "confidence", "opinion"]
    }

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
                "temperature": 0.1,
                "max_tokens": 1024,
                "response_format": {"type": "json_object"}
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {clean_key}"
            }
        else:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
            gen_cfg: Dict[str, Any] = {
                "responseMimeType": "application/json",
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "responseSchema": response_schema
            }
            if thinking_budget is not None and thinking_budget >= 0:
                gen_cfg["thinkingConfig"] = {
                    "thinkingBudget": int(thinking_budget)
                }

            payload_obj = {
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "contents": [{"parts": [{"text": user_content}]}],
                "generationConfig": gen_cfg
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {"Content-Type": "application/json"}

        # Enviar petición a IA con reintento automático ante timeouts o saturación
        status_code, raw_res_text, duration_ms = send_ai_http_with_retry(
            endpoint=endpoint,
            payload_bytes=payload_bytes,
            headers=req_headers,
            max_retries=3,
            timeout_seconds=8.0,
            action_label=f"POS_{clean_symbol}"
        )

        raw_json = json.loads(raw_res_text)

        ai_text = ""
        if "candidates" in raw_json and raw_json["candidates"]:
            first_cand = raw_json["candidates"][0]
            parts = first_cand.get("content", {}).get("parts", [])
            if parts:
                texts = [p.get("text", "") for p in parts if "text" in p and p.get("text")]
                ai_text = "\n".join(texts)
        elif "choices" in raw_json and raw_json["choices"]:
            ai_text = raw_json["choices"][0].get("message", {}).get("content", "")

        parsed = _clean_json_text(ai_text)
        if not isinstance(parsed, dict):
            parsed = json.loads(str(parsed))

        action = parsed.get("action", "HOLD").upper()
        if action not in ("HOLD", "MODIFY_SLTP", "EARLY_CLOSE"):
            action = "HOLD"

        suggested_sl = float(parsed.get("suggested_sl", current_sl))
        suggested_tp = float(parsed.get("suggested_tp", current_tp))
        close_reason = str(parsed.get("close_reason", "AI_Early_Close"))
        confidence = float(parsed.get("confidence", 0.9))
        opinion = str(parsed.get("opinion", "Posición evaluada por IA"))

        output = {
            "action": action,
            "suggested_sl": suggested_sl,
            "suggested_tp": suggested_tp,
            "close_reason": close_reason,
            "confidence": round(confidence, 2),
            "opinion": opinion,
            "fallback": False,
            "latency_ms": round(duration_ms, 1),
            "provider": provider,
            "model": model
        }

        ai_logger.log_interaction(
            event_type="EVALUATE_OPEN_POSITION_AI",
            symbol=symbol,
            provider=provider,
            model=model,
            endpoint=endpoint,
            request_headers=req_headers,
            request_payload=payload_obj,
            response_status=status_code,
            duration_ms=duration_ms,
            raw_response=raw_res_text,
            parsed_response=output,
            extra_meta={"ticket": ticket, "action": action, "profit_pips": profit_pips}
        )
        return output

    except urllib.error.HTTPError as he:
        duration_ms = (time.time() - start_time) * 1000.0
        err_body = he.read().decode("utf-8", errors="ignore")
        err_str = f"HTTP Error {he.code}: {err_body}"
        ai_logger.log_interaction(
            event_type="EVALUATE_OPEN_POSITION_AI_FALLBACK",
            symbol=symbol,
            provider=provider,
            model=model,
            endpoint=endpoint,
            request_headers=req_headers,
            request_payload=payload_obj,
            response_status=he.code,
            duration_ms=duration_ms,
            raw_response=err_body,
            error=err_str
        )
        return {
            "action": "HOLD",
            "suggested_sl": current_sl,
            "suggested_tp": current_tp,
            "close_reason": "",
            "confidence": 1.0,
            "opinion": f"Fallback estrategia local (Error HTTP {he.code})",
            "fallback": True
        }

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000.0
        err_str = str(e)
        ai_logger.log_interaction(
            event_type="EVALUATE_OPEN_POSITION_AI_FALLBACK",
            symbol=symbol,
            provider=provider,
            model=model,
            endpoint=endpoint,
            request_headers=req_headers,
            request_payload=payload_obj,
            response_status=500,
            duration_ms=duration_ms,
            error=err_str
        )
        return {
            "action": "HOLD",
            "suggested_sl": current_sl,
            "suggested_tp": current_tp,
            "close_reason": "",
            "confidence": 1.0,
            "opinion": f"Fallback estrategia local (Error IA: {err_str[:60]})",
            "fallback": True
        }


def evaluate_batch_open_positions_ai(
    account_info: Dict[str, Any],
    positions_list: List[Dict[str, Any]],
    api_key: str = "",
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    thinking_budget: Optional[int] = 100,
    past_trades_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Evalúa un LOTE de posiciones abiertas en una ÚNICA petición HTTP a la IA.
    Evita saturación de rate-limits y distribuye las acciones ('HOLD', 'MODIFY_SLTP', 'EARLY_CLOSE')
    a cada posición activa identificada por su ticket/símbolo, inyectando la memoria histórica de cada par.
    """
    if not positions_list:
        return {}

    if not api_key or not api_key.strip():
        fallbacks: Dict[str, Dict[str, Any]] = {}
        for pos_item in positions_list:
            p_info = pos_item.get("position_info", {})
            sym = p_info.get("symbol", "UNKNOWN")
            sl = float(p_info.get("sl", 0.0))
            tp = float(p_info.get("tp", 0.0))
            key_id = str(p_info.get("ticket", sym))
            fallbacks[key_id] = {
                "action": "HOLD",
                "suggested_sl": sl,
                "suggested_tp": tp,
                "close_reason": "",
                "confidence": 1.0,
                "opinion": "Estrategia local activa (IA no configurada)",
                "fallback": True
            }
        return fallbacks

    clean_key = api_key.strip()
    model = (model_name or DEFAULT_GEMINI_MODEL).strip()
    custom_url = (base_url or "").strip()
    provider = _detect_provider(model, custom_url)

    system_instruction = (
        "Eres un Gestor Cuantitativo de Posiciones Abiertas y Salidas de Emergencia en Forex.\n"
        "Tu misión es evaluar una lista de posiciones activas simultáneas y decidir para cada una: 'HOLD', 'MODIFY_SLTP' o 'EARLY_CLOSE'.\n\n"
        "REGLAS:\n"
        "1. 'HOLD': Si la orden va a favor de la tendencia o el patrón de velas apoya la dirección (BUY con rebote alcista / SELL con rechazo bajista).\n"
        "2. 'EARLY_CLOSE': Solo si hay cambio estructural severo, reversión fuerte opuesta confirmada o noticias críticas inminentes.\n"
        "3. 'MODIFY_SLTP': Para mover SL a Break-Even o asegurar ganancias flotantes en velas de continuación.\n"
        "Responde un array JSON donde cada objeto corresponda a una posición."
    )

    prompt_items = []
    for idx, item in enumerate(positions_list, 1):
        p_info = item.get("position_info", {})
        m_ctx = item.get("market_context", {})
        t_id = p_info.get("ticket", idx)
        sym = p_info.get("symbol", f"POS_{idx}")
        clean_sym = clean_symbol_name(sym)
        p_type = p_info.get("type", "BUY")
        open_px = float(p_info.get("price_open", 0.0))
        cur_px = float(p_info.get("price_current", open_px))
        cur_sl = float(p_info.get("sl", 0.0))
        cur_tp = float(p_info.get("tp", 0.0))
        pnl_pips = float(p_info.get("profit_pips", 0.0))
        pnl_usd = float(p_info.get("profit_usd", 0.0))

        candle = m_ctx.get("candlestick_summary")
        if not candle and "df" in m_ctx:
            candle = format_candlestick_summary_for_ai(m_ctx["df"])
        if not candle:
            candle = "Estructura estándar"

        macro = m_ctx.get("macro_summary", "Estructura estable")
        news = m_ctx.get("news_summary", "Sin noticias críticas")

        # Historial de trades del par
        trades_for_sym = []
        if past_trades_by_symbol:
            trades_for_sym = past_trades_by_symbol.get(sym) or past_trades_by_symbol.get(clean_sym) or []
        if not trades_for_sym and "past_trades" in item:
            trades_for_sym = item.get("past_trades", [])

        if trades_for_sym:
            hist_parts = []
            for t in trades_for_sym[:3]:
                out = t.get("outcome", {})
                res = out.get("result", "N/A")
                pnl_r = float(out.get("pnl_r", 0.0))
                pnl_u = float(out.get("pnl_usd", 0.0))
                hist_parts.append(f"{t.get('signal', 'ORD')}->{res}({pnl_r:+.1f}R/${pnl_u:+.2f})")
            hist_str = f"Historial {clean_sym}: " + " | ".join(hist_parts)
        else:
            hist_str = f"Historial {clean_sym}: Sin operaciones previas"

        prompt_items.append(
            f"{idx}. [Ticket #{t_id} | {clean_sym}]\n"
            f"   - Tipo: {p_type} | Entrada: {open_px} | Actual: {cur_px} | Flotante: ${pnl_usd:+.2f} ({pnl_pips:+.1f} pips)\n"
            f"   - SL: {cur_sl} | TP: {cur_tp} | Vela: {candle} | Macro: {macro} | {news}\n"
            f"   - {hist_str}"
        )

    user_content = "EVALÚA LAS SIGUIENTES POSICIONES ACTIVAS:\n\n" + "\n\n".join(prompt_items)

    batch_pos_schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "ticket": {"type": "STRING"},
                "action": {"type": "STRING", "enum": ["HOLD", "MODIFY_SLTP", "EARLY_CLOSE"]},
                "suggested_sl": {"type": "NUMBER"},
                "suggested_tp": {"type": "NUMBER"},
                "close_reason": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
                "opinion": {"type": "STRING"}
            },
            "required": ["ticket", "action", "suggested_sl", "suggested_tp", "close_reason", "confidence", "opinion"]
        }
    }

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
                    {"role": "system", "content": system_instruction + "\nResponde un array JSON [ {ticket, action, suggested_sl, suggested_tp, close_reason, confidence, opinion}, ... ]"},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.1,
                "max_tokens": 2048,
                "response_format": {"type": "json_object"}
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {clean_key}"
            }
        else:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
            gen_cfg: Dict[str, Any] = {
                "responseMimeType": "application/json",
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "responseSchema": batch_pos_schema
            }
            if thinking_budget is not None and thinking_budget >= 0:
                gen_cfg["thinkingConfig"] = {
                    "thinkingBudget": int(thinking_budget)
                }

            payload_obj = {
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "contents": [{"parts": [{"text": user_content}]}],
                "generationConfig": gen_cfg
            }
            payload_bytes = json.dumps(payload_obj).encode("utf-8")
            req_headers = {"Content-Type": "application/json"}

        status_code, raw_res_text, duration_ms = send_ai_http_with_retry(
            endpoint=endpoint,
            payload_bytes=payload_bytes,
            headers=req_headers,
            max_retries=3,
            timeout_seconds=10.0,
            action_label=f"BATCH_{len(positions_list)}_POSITIONS"
        )

        raw_json = json.loads(raw_res_text)
        ai_text = ""
        if "candidates" in raw_json and raw_json["candidates"]:
            first_cand = raw_json["candidates"][0]
            parts = first_cand.get("content", {}).get("parts", [])
            if parts:
                texts = [p.get("text", "") for p in parts if "text" in p and p.get("text")]
                ai_text = "\n".join(texts)
        elif "choices" in raw_json and raw_json["choices"]:
            ai_text = raw_json["choices"][0].get("message", {}).get("content", "")

        parsed_array = _clean_json_text(ai_text)
        if isinstance(parsed_array, dict):
            for k in ["evaluations", "positions", "results", "items", "data", "list"]:
                if k in parsed_array and isinstance(parsed_array[k], list):
                    parsed_array = parsed_array[k]
                    break
            if isinstance(parsed_array, dict):
                parsed_array = [parsed_array]

        if not isinstance(parsed_array, list):
            parsed_array = []

        results_by_id: Dict[str, Dict[str, Any]] = {}
        for idx, item in enumerate(positions_list):
            p_info = item.get("position_info", {})
            t_id = str(p_info.get("ticket", idx + 1))
            sym = p_info.get("symbol", "UNKNOWN")
            cur_sl = float(p_info.get("sl", 0.0))
            cur_tp = float(p_info.get("tp", 0.0))

            matched = None
            for r in parsed_array:
                if isinstance(r, dict) and str(r.get("ticket", "")).strip() in (t_id, f"#{t_id}"):
                    matched = r
                    break
            if matched is None and idx < len(parsed_array) and isinstance(parsed_array[idx], dict):
                matched = parsed_array[idx]

            if matched:
                act = matched.get("action", "HOLD").upper()
                if act not in ("HOLD", "MODIFY_SLTP", "EARLY_CLOSE"):
                    act = "HOLD"
                out = {
                    "action": act,
                    "suggested_sl": float(matched.get("suggested_sl", cur_sl)),
                    "suggested_tp": float(matched.get("suggested_tp", cur_tp)),
                    "close_reason": str(matched.get("close_reason", "")),
                    "confidence": round(float(matched.get("confidence", 0.9)), 2),
                    "opinion": str(matched.get("opinion", "Evaluación de posición en lote")),
                    "fallback": False,
                    "latency_ms": round(duration_ms, 1),
                    "provider": provider,
                    "model": model,
                    "batch_size": len(positions_list)
                }
            else:
                out = {
                    "action": "HOLD",
                    "suggested_sl": cur_sl,
                    "suggested_tp": cur_tp,
                    "close_reason": "",
                    "confidence": 1.0,
                    "opinion": "Fallback en lote para posición",
                    "fallback": True,
                    "latency_ms": round(duration_ms, 1),
                    "provider": provider,
                    "model": model,
                    "batch_size": len(positions_list)
                }

            ai_logger.log_interaction(
                event_type="EVALUATE_OPEN_POSITION_AI_BATCH_ITEM",
                symbol=sym,
                provider=provider,
                model=model,
                endpoint=endpoint,
                request_headers=req_headers,
                request_payload={"ticket": t_id, "batch_count": len(positions_list)},
                response_status=status_code,
                duration_ms=duration_ms,
                raw_response=raw_res_text,
                parsed_response=out,
                extra_meta={"ticket": t_id, "action": out.get("action")}
            )
            results_by_id[t_id] = out
            results_by_id[sym] = out

        return results_by_id

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000.0
        err_str = str(e)
        fallbacks = {}
        for item in positions_list:
            p_info = item.get("position_info", {})
            t_id = str(p_info.get("ticket", "0"))
            sym = p_info.get("symbol", "UNKNOWN")
            cur_sl = float(p_info.get("sl", 0.0))
            cur_tp = float(p_info.get("tp", 0.0))
            f_res = {
                "action": "HOLD",
                "suggested_sl": cur_sl,
                "suggested_tp": cur_tp,
                "close_reason": "",
                "confidence": 1.0,
                "opinion": f"Fallback lote posición ({err_str[:50]})",
                "fallback": True,
                "latency_ms": round(duration_ms, 1),
                "provider": provider,
                "model": model
            }
            fallbacks[t_id] = f_res
            fallbacks[sym] = f_res
        return fallbacks


class AIPositionBatchCoordinator:
    """
    Coordinador de Lote de Posiciones Abiertas.
    Agrupa comprobaciones de trailing/cierre prematuro de múltiples órdenes en una única llamada.
    """
    def __init__(self, coalesce_window_seconds: float = 0.25):
        self._window = coalesce_window_seconds
        self._lock = threading.Lock()
        self._pending: List[Dict[str, Any]] = []
        self._timer: Optional[threading.Timer] = None

    def submit_open_position(
        self,
        account_info: Dict[str, Any],
        position_info: Dict[str, Any],
        market_context: Dict[str, Any],
        api_key: str,
        model_name: str = DEFAULT_GEMINI_MODEL,
        base_url: str = "",
        thinking_budget: Optional[int] = 128,
        past_trades: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        if not api_key or not api_key.strip():
            return evaluate_open_position_ai_direct(
                account_info, position_info, market_context, api_key, model_name, base_url, thinking_budget, past_trades
            )

        event = threading.Event()
        item = {
            "account_info": account_info,
            "position_info": position_info,
            "market_context": market_context,
            "api_key": api_key,
            "model_name": model_name,
            "base_url": base_url,
            "thinking_budget": thinking_budget,
            "past_trades": past_trades,
            "event": event,
            "result": None
        }

        with self._lock:
            self._pending.append(item)
            if self._timer is None:
                self._timer = threading.Timer(self._window, self._flush)
                self._timer.daemon = True
                self._timer.start()

        event_ok = event.wait(timeout=25.0)
        if event_ok and item.get("result") is not None:
            return item["result"]

        return evaluate_open_position_ai_direct(
            account_info, position_info, market_context, api_key, model_name, base_url, thinking_budget, past_trades
        )

    def _flush(self) -> None:
        with self._lock:
            items_to_process = list(self._pending)
            self._pending.clear()
            self._timer = None

        if not items_to_process:
            return

        if len(items_to_process) == 1:
            it = items_to_process[0]
            try:
                it["result"] = evaluate_open_position_ai_direct(
                    it["account_info"], it["position_info"], it["market_context"],
                    it["api_key"], it["model_name"], it["base_url"], it["thinking_budget"],
                    it.get("past_trades")
                )
            except Exception as e:
                it["result"] = {
                    "action": "HOLD",
                    "suggested_sl": float(it["position_info"].get("sl", 0.0)),
                    "suggested_tp": float(it["position_info"].get("tp", 0.0)),
                    "close_reason": "",
                    "confidence": 1.0,
                    "opinion": f"Fallback posición ({str(e)[:50]})",
                    "fallback": True
                }
            finally:
                it["event"].set()
            return

        first = items_to_process[0]
        pos_list = [
            {
                "position_info": it["position_info"],
                "market_context": it["market_context"],
                "past_trades": it.get("past_trades", [])
            }
            for it in items_to_process
        ]
        try:
            batch_res = evaluate_batch_open_positions_ai(
                account_info=first["account_info"],
                positions_list=pos_list,
                api_key=first["api_key"],
                model_name=first["model_name"],
                base_url=first["base_url"],
                thinking_budget=first["thinking_budget"]
            )
            for it in items_to_process:
                t_id = str(it["position_info"].get("ticket", ""))
                sym = it["position_info"].get("symbol", "")
                res = batch_res.get(t_id) or batch_res.get(sym) or {
                    "action": "HOLD",
                    "suggested_sl": float(it["position_info"].get("sl", 0.0)),
                    "suggested_tp": float(it["position_info"].get("tp", 0.0)),
                    "close_reason": "",
                    "confidence": 1.0,
                    "opinion": "Fallback en lote de posiciones",
                    "fallback": True
                }
                it["result"] = res
                it["event"].set()
        except Exception as e:
            for it in items_to_process:
                it["result"] = {
                    "action": "HOLD",
                    "suggested_sl": float(it["position_info"].get("sl", 0.0)),
                    "suggested_tp": float(it["position_info"].get("tp", 0.0)),
                    "close_reason": "",
                    "confidence": 1.0,
                    "opinion": f"Fallback por error en lote ({str(e)[:50]})",
                    "fallback": True
                }
                it["event"].set()


# Coordinador de lote para posiciones abiertas
_ai_pos_batch_coordinator = AIPositionBatchCoordinator(coalesce_window_seconds=1.2)


def evaluate_open_position_ai(
    account_info: Dict[str, Any],
    position_info: Dict[str, Any],
    market_context: Dict[str, Any],
    api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    thinking_budget: Optional[int] = 128,
    use_batch_coordinator: bool = True,
    past_trades: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Evalúa una posición abierta en tiempo real mediante IA con batching automático contra 429.
    """
    if use_batch_coordinator:
        return _ai_pos_batch_coordinator.submit_open_position(
            account_info=account_info,
            position_info=position_info,
            market_context=market_context,
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            thinking_budget=thinking_budget,
            past_trades=past_trades
        )
    return evaluate_open_position_ai_direct(
        account_info=account_info,
        position_info=position_info,
        market_context=market_context,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
        thinking_budget=thinking_budget,
        past_trades=past_trades
    )


def test_ai_payload_terminal(api_key: str, model_name: str = DEFAULT_GEMINI_MODEL, base_url: str = "") -> Dict[str, Any]:
    """
    Ejecuta un test de Evaluación por Lote (Batch) con 3 señales simultáneas (EURUSD, GBPUSD, NZDUSD)
    para verificar que una sola llamada HTTP evalúa y distribuye todas las respuestas correctamente.
    """
    print("\n" + "=" * 75)
    print("🧠 [DEBUG TERMINAL] INICIANDO TEST DE EVALUACIÓN POR LOTE (BATCH REQUEST)...")
    print("=" * 75)

    sample_account = {
        "balance": 10000.0,
        "equity": 10150.0,
        "free_margin": 9800.0
    }

    sample_batch_candidates = [
        {
            "symbol": "EURUSD",
            "signal": "BUY",
            "price": 1.08500,
            "default_sl": 1.08200,
            "default_tp": 1.09100,
            "default_lot": 0.10,
            "timeframe": "M15",
            "atr": 0.00120,
            "spread_info": "Spread 0.8 pips",
            "news_summary": "Sin noticias de alto impacto en próximas 2 horas",
            "macro_summary": "H4 Alcista por encima de EMA 200",
            "candlestick_summary": "Patrón Hammer Alcista en soporte"
        },
        {
            "symbol": "GBPUSD",
            "signal": "SELL",
            "price": 1.29500,
            "default_sl": 1.29850,
            "default_tp": 1.28800,
            "default_lot": 0.08,
            "timeframe": "M15",
            "atr": 0.00180,
            "spread_info": "Spread 1.2 pips",
            "news_summary": "Sin noticias en los próximos 45 min",
            "macro_summary": "D1 Bajista bajo EMA 200",
            "candlestick_summary": "Patrón Shooting Star en resistencia"
        },
        {
            "symbol": "NZDUSD",
            "signal": "BUY",
            "price": 0.59200,
            "default_sl": 0.58950,
            "default_tp": 0.59700,
            "default_lot": 0.12,
            "timeframe": "M15",
            "atr": 0.00095,
            "spread_info": "Spread 1.0 pips",
            "news_summary": "Noticia HIGH IMPACT en 15 minutos",
            "macro_summary": "Estructura lateral",
            "candlestick_summary": "Doji Neutral"
        }
    ]

    print(f"📡 Proveedor / Modelo: {model_name}")
    print(f"🔑 API Key: {api_key[:6]}...{api_key[-4:] if len(api_key) > 10 else ''}")
    if base_url:
        print(f"🌐 Base URL: {base_url}")
    print(f"📦 Lote Enviado en 1 Sola Petición: {[c['symbol'] for c in sample_batch_candidates]}")
    print("-" * 75)

    results = evaluate_batch_trade_setups(
        account_info=sample_account,
        candidate_setups=sample_batch_candidates,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url
    )

    print("📥 [RESPUESTAS DESEMPAQUETADAS Y DISTRIBUIDAS POR PAR]:")
    for sym, res in results.items():
        appr_icon = "✅ APROBADO" if res.get("approved") else "❌ RECHAZADO"
        print(f"\n🔹 {sym} -> {appr_icon} (Confianza: {res.get('confidence', 0)*100:.0f}%)")
        print(f"   - SL IA: {res.get('ai_sl')} | TP IA: {res.get('ai_tp')} | Lote: {res.get('suggested_lot')} | R:R: {res.get('risk_reward_ratio')}")
        print(f"   - Opinión: {res.get('opinion')}")
        if res.get("rejection_reason"):
            print(f"   - Razón de Rechazo: {res.get('rejection_reason')}")

    print("\n" + "=" * 75 + "\n")
    return results
