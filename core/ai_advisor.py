import json
import re
import time
import socket
import urllib.request
import urllib.error
from typing import Dict, Any, List, Tuple, Optional
from core.ai_logger import ai_logger
from core.news_manager import news_manager
from core.market_context import calculate_psychological_levels, analyze_macro_multitimeframe
from core.candlestick_patterns import format_candlestick_summary_for_ai, detect_candlestick_patterns


DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"

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


def _clean_json_text(raw_text: str) -> Dict[str, Any]:
    """
    Limpia y extrae un bloque JSON de la respuesta de la IA.
    Soporta bloques de código markdown ```json ... ``` y respuestas con prefijos explicativos.
    """
    if not raw_text:
        return {}
    cleaned = raw_text.strip()

    # 1. Intentar decodificar directo si ya viene como JSON válido
    try:
        res = json.loads(cleaned)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # 2. Intentar extraer de bloques ```json ... ``` o ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if match:
        block = match.group(1).strip()
        try:
            res = json.loads(block)
            if isinstance(res, dict):
                return res
        except Exception:
            cleaned = block

    # 3. Buscar el primer '{' y el último '}' para extraer el objeto JSON puro
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        sub_str = cleaned[start_idx:end_idx + 1].strip()
        try:
            res = json.loads(sub_str)
            if isinstance(res, dict):
                return res
        except Exception:
            pass

    # 4. Si el JSON fue cortado por límite de tokens (MAX_TOKENS), intentar repararlo cerrando llaves
    if start_idx != -1 and (end_idx == -1 or end_idx <= start_idx):
        sub_str = cleaned[start_idx:].strip()
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

    Retorna: (status_code, raw_response_text, total_duration_ms)
    Lanza: HTTPError o Exception si todos los reintentos fallan o si es un error fatal de cliente (400, 401, 403, 404).
    """
    start_total_time = time.time()
    last_exception: Optional[Exception] = None

    for intento in range(max_retries):
        try:
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
            # Errores transitorios del servidor o Rate limit (429, 500, 502, 503, 504): Reintentar
            if he.code in (500, 502, 503, 504, 429) and intento < max_retries - 1:
                wait_time = 1.0 + (intento * 0.5)
                print(f"⚠️ [{action_label}] Error HTTP {he.code} en servidor de IA. Reintentando ({intento + 1}/{max_retries}) en {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            # Error no recuperable (400, 401, 403, 404) o se agotaron los reintentos
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


def evaluate_trade_setup(
    account_info: Dict[str, Any],
    candidate_setup: Dict[str, Any],
    past_trades: List[Dict[str, Any]],
    api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    thinking_budget: Optional[int] = 128
) -> Dict[str, Any]:
    """
    Evalúa una señal candidata mediante la IA con inyección de memoria histórica (Few-Shot Context).
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
    macro_summary = candidate_setup.get("macro_summary") or analyze_macro_multitimeframe(clean_symbol, current_price)
    psych_summary = candidate_setup.get("psych_summary") or calculate_psychological_levels(clean_symbol, current_price)
    spread_info = candidate_setup.get("spread_info", "Spread normal")
    candlestick_summary = candidate_setup.get("candlestick_summary")
    if not candlestick_summary and "df" in candidate_setup:
        candlestick_summary = format_candlestick_summary_for_ai(candidate_setup["df"])
    if not candlestick_summary:
        candlestick_summary = "Patrón de Vela: Acción de precio estándar [NEUTRAL]"

    system_instruction = (
        "Eres un Gestor de Riesgo Cuantitativo Senior de Trading Algorítmico.\n"
        "Validas o rechazas señales candidatas analizando micro-contexto, macro-tendencia, liquidez, patrones de velas y riesgo.\n\n"
        "REGLAS DE BLOQUEO Y APROBACIÓN ESTRICTAS:\n"
        "1. Rechaza ('approved': false) si hay noticias de alto impacto (HIGH) en <30 min.\n"
        "2. Rechaza ('approved': false) si el spread actual es anómalo/alto (>3.0 pips) o coincide con cierre de sesión/rollover.\n"
        "3. Rechaza o ajusta si la entrada/TP choca directamente contra un nivel psicológico institucional (ej. 0.XX00 / 0.XX50).\n"
        "4. Rechaza si la señal en M15 contradice la estructura Macro (H4/D1).\n"
        "5. CONFLUENCIA DE VELAS: Prioriza ('approved': true) compras BUY respaldadas por patrones alcistas (Morning Star, Hammer, Bullish Engulfing, Three White Soldiers, Rising Three, Piercing Line, Bullish Harami); y ventas SELL respaldadas por patrones bajistas (Evening Star, Shooting Star, Bearish Engulfing, Three Black Crows, Falling Three, Dark Cloud Cover, Bearish Harami).\n"
        "6. Si apruebas, define SL/TP con R:R de 1:1.8 a 1:3 responder estricto en el esquema definido."
    )

    user_content = (
        f"CUENTA: Eq ${equity:,.2f} USD | Historial {clean_symbol}: {history_summary}\n\n"
        f"SEÑAL EN EVALUACIÓN ({timeframe}):\n"
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


def evaluate_open_position_ai(
    account_info: Dict[str, Any],
    position_info: Dict[str, Any],
    market_context: Dict[str, Any],
    api_key: str,
    model_name: str = DEFAULT_GEMINI_MODEL,
    base_url: str = "",
    thinking_budget: Optional[int] = 128
) -> Dict[str, Any]:
    """
    Evalúa una posición abierta en tiempo real mediante IA para:
    1. Confirmar si se MANTIENE la entrada (HOLD).
    2. Modificar dinámicamente SL / TP para asegurar ganancias o trailing (MODIFY_SLTP).
    3. CIERRE PREMATURO INMEDIATO por confirmación de cambio de estructura / tendencia o alto riesgo (EARLY_CLOSE).

    Prioridad: Si la IA responde válidamente, se ejecuta su recomendación.
    Si la IA falla o está deshabilitada, se retorna fallback: True para que el bot use la estrategia local.
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
        f"- SL Actual: {current_sl} | TP Actual: {current_tp}\n\n"
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


def test_ai_payload_terminal(api_key: str, model_name: str = DEFAULT_GEMINI_MODEL, base_url: str = "") -> Dict[str, Any]:
    """
    Ejecuta un test completo con un Payload Genérico de Trading Setup y muestra la respuesta detallada
    directamente en la consola PowerShell / Terminal para depuración inmediata.
    """
    print("\n" + "=" * 70)
    print("🧠 [DEBUG TERMINAL] INICIANDO TEST DE LLAMADA AL API DE IA...")
    print("=" * 70)

    sample_account = {
        "balance": 10000.0,
        "equity": 10150.0,
        "free_margin": 9800.0
    }
    sample_candidate = {
        "symbol": "EURUSD",
        "signal": "BUY",
        "price": 1.08500,
        "default_sl": 1.08200,
        "default_tp": 1.09100,
        "default_lot": 0.10,
        "timeframe": "M15",
        "atr": 0.00120,
        "confluence_score": 3,
        "spread_info": "Spread normal (0.8 pips)",
        "news_summary": "Sin noticias de alto impacto en próximas 4 horas",
        "macro_summary": "H4 Alcista por encima de EMA 200, D1 en zona de soporte",
        "psych_summary": "Nivel psicológico cercano: 1.08000 (Soporte)"
    }
    sample_past_trades = [
        {"signal": "BUY", "outcome": {"result": "TP_HIT", "profit": 150.0}},
        {"signal": "SELL", "outcome": {"result": "BE_HIT", "profit": 0.0}}
    ]

    print(f"📡 Proveedor / Modelo: {model_name}")
    print(f"🔑 API Key: {api_key[:6]}...{api_key[-4:] if len(api_key) > 10 else ''}")
    if base_url:
        print(f"🌐 Base URL: {base_url}")
    print(f"📦 Setup Genérico Enviado: {sample_candidate['symbol']} {sample_candidate['signal']} @ {sample_candidate['price']}")
    print("-" * 70)

    result = evaluate_trade_setup(
        account_info=sample_account,
        candidate_setup=sample_candidate,
        past_trades=sample_past_trades,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url
    )

    print("📥 [RESPUESTA OBTENIDA DE LA IA]:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 70 + "\n")
    return result
