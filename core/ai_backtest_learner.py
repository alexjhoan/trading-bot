import json
import os
import re
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

LEARNINGS_FILE = Path(__file__).resolve().parent.parent / "ai_backtest_learnings.json"
_LOCK = threading.Lock()


def _normalize_sym(symbol: str) -> str:
    """Normaliza el símbolo eliminando sufijos de broker (.pro, _r, etc.)."""
    if not symbol:
        return ""
    sym = symbol.strip().upper()
    sym = sym.replace("/", "").replace("\\", "")
    sym_cleaned = re.sub(
        r"([._-])?(RAW|PRO|ECN|STP|CASH|PLUS|MINI|MICRO|STD|ZERO|VIP|[A-Z])$",
        "",
        sym,
        flags=re.IGNORECASE
    )
    match_forex = re.match(r"^([A-Z]{6})", sym)
    if match_forex:
        return match_forex.group(1)
    generic = re.split(r"[._-]", sym)[0]
    return generic if len(generic) >= 3 else sym


def _ensure_learnings_file() -> None:
    """Asegura que el archivo ai_backtest_learnings.json exista y contenga un JSON válido."""
    with _LOCK:
        try:
            LEARNINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not LEARNINGS_FILE.exists() or LEARNINGS_FILE.stat().st_size == 0:
                with open(LEARNINGS_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f, indent=2)
            else:
                try:
                    with open(LEARNINGS_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        with open(LEARNINGS_FILE, "w", encoding="utf-8") as f:
                            json.dump({}, f, indent=2)
                except Exception:
                    with open(LEARNINGS_FILE, "w", encoding="utf-8") as f:
                        json.dump({}, f, indent=2)
        except Exception as e:
            print(f"❌ [AI_BACKTEST_LEARNER] Error asegurando archivo {LEARNINGS_FILE}: {e}")


def _read_learnings_safe() -> Dict[str, Any]:
    """Lee el archivo ai_backtest_learnings.json de forma segura."""
    _ensure_learnings_file()
    with _LOCK:
        try:
            with open(LEARNINGS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                parsed = json.loads(content)
                return parsed if isinstance(parsed, dict) else {}
        except Exception as e:
            print(f"⚠️ [AI_BACKTEST_LEARNER] Error leyendo {LEARNINGS_FILE}: {e}")
            return {}


def _write_learnings_safe(data: Dict[str, Any]) -> bool:
    """Escribe atómicamente el archivo de aprendizajes."""
    _ensure_learnings_file()
    with _LOCK:
        try:
            tmp_file = LEARNINGS_FILE.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, LEARNINGS_FILE)
            return True
        except Exception as e:
            try:
                with open(LEARNINGS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
            except Exception as e_inner:
                print(f"❌ [AI_BACKTEST_LEARNER] Error escribiendo en {LEARNINGS_FILE}: {e_inner}")
                return False


def get_backtest_learnings_for_symbol(symbol: str) -> Dict[str, Any]:
    """
    Recupera el aprendizaje consolidado de backtest para el símbolo especificado.
    Normaliza el nombre para compatibilidad multiplataforma.
    """
    clean_sym = _normalize_sym(symbol)
    data = _read_learnings_safe()
    return data.get(clean_sym, {})


def get_symbol_learning(symbol: str) -> Dict[str, Any]:
    """Alias para get_backtest_learnings_for_symbol utilizado directamente por AIStrategy."""
    return get_backtest_learnings_for_symbol(symbol)


def get_all_backtest_learnings() -> Dict[str, Any]:
    """Retorna todo el diccionario de aprendizajes guardados por símbolo."""
    return _read_learnings_safe()


def save_backtest_learning(symbol: str, learning_data: Dict[str, Any]) -> bool:
    """
    Guarda o actualiza las reglas aprendidas de backtesting para un símbolo específico.
    """
    clean_sym = _normalize_sym(symbol)
    if not clean_sym:
        return False
    data = _read_learnings_safe()
    data[clean_sym] = learning_data
    return _write_learnings_safe(data)


def _build_heuristic_learning(
    symbol: str,
    strategy: str,
    backtest_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Genera reglas de aprendizaje cuantitativas analizando directamente las operaciones
    (ganadoras y perdedoras) del backtest en caso de no tener API key o fallo de conexión.
    """
    win_rate = float(backtest_data.get("win_rate", 50.0))
    avg_r = float(backtest_data.get("avg_r", 0.0))
    trades_count = int(backtest_data.get("trades", 0))
    raw_tf = backtest_data.get("timeframe", "M15")
    tf_str = str(raw_tf)

    sample_trades = backtest_data.get("sample_trades", [])
    wins = [t for t in sample_trades if t.get("result") == "WIN"]
    losses = [t for t in sample_trades if t.get("result") == "LOSS"]

    avoid_patterns: List[str] = []
    key_takeaways: List[str] = []

    # 1. Análisis de patrones en pérdidas
    loss_patterns = [t.get("pattern", "Estándar") for t in losses if t.get("pattern")]
    from collections import Counter
    pattern_counts = Counter(loss_patterns)
    for pat, count in pattern_counts.most_common(2):
        if pat and pat != "Estándar" and count >= 2:
            avoid_patterns.append(f"Patrón de vela débil '{pat}' en retrocesos sin soporte institucional")

    # 2. Análisis de MAE / MFE en pérdidas
    mfe_values = [float(t.get("mfe_r", 0.0)) for t in losses if "mfe_r" in t]
    high_mfe_losses = sum(1 for v in mfe_values if v >= 0.8)
    if high_mfe_losses >= 2:
        avoid_patterns.append("Operaciones con ganancia flotante (+0.8R) devueltas a Stop Loss sin Break-Even")
        key_takeaways.append("Activar Break-Even temprano estricto a +0.9R para blindar ganancias iniciales.")

    # 3. Reglas según régimen de rendimiento del par
    if win_rate >= 65.0 and avg_r >= 0.4:
        key_takeaways.append(f"Par de alta eficacia demostrada ({win_rate}% WR, +{avg_r}R). Confluencia 2/4 a 3/4 aprobada.")
        risk_advice = "Mantener trailing stop dinámico por ATR tras superar +1.8R. Permitir reentradas protegidas al 78.6%."
    elif win_rate < 45.0 or avg_r < -0.1:
        avoid_patterns.append("ADX < 23.0 en fases de consolidación lateral o baja volatilidad")
        avoid_patterns.append("RSI > 65 en sobrecompra al buscar compras o RSI < 35 en ventas")
        key_takeaways.append(f"Par con baja consistencia histórica ({win_rate}% WR). Se exige máxima confluencia 4/4 estricta.")
        risk_advice = "Exigir confluencia 4/4 con confirmación direccional estricta; Stop Loss protegido más allá del swing ATR."
    else:
        avoid_patterns.append("Entradas en retroceso profundo que pierden la EMA 50")
        key_takeaways.append(f"Rendimiento equilibrado ({win_rate}% WR, +{avg_r}R). Operar con confluencia base 3/4.")
        risk_advice = "Bloquear nuevas entradas durante ventana de rollover y asegurar BE en +1.0R."

    if not avoid_patterns:
        avoid_patterns = [
            "ADX < 20.0 en rango lateral sin tendencia definida",
            "RSI > 65 en sobrecompra extrema al comprar"
        ]

    confidence = 85.0 if trades_count >= 10 else (70.0 if trades_count >= 5 else 55.0)

    return {
        "symbol": _normalize_sym(symbol),
        "strategy": strategy,
        "win_rate": win_rate,
        "avg_r": avg_r,
        "trades": trades_count,
        "optimal_tf": tf_str,
        "avoid_patterns": avoid_patterns,
        "risk_advice": risk_advice,
        "key_takeaways": key_takeaways,
        "confidence_score": confidence,
        "sample_wins": len(wins),
        "sample_losses": len(losses),
        "learned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "QUANT_HEURISTIC"
    }


def train_ai_from_backtest(
    symbol: str,
    strategy: str,
    backtest_data: Dict[str, Any],
    api_key: str = "",
    model_name: str = "",
    base_url: str = ""
) -> Tuple[bool, Dict[str, Any], str]:
    """
    Envía los datos y trades del backtest a la IA (Gemini / OpenAI / Groq) o ejecuta
    síntesis cuantitativa si la IA no está disponible.
    Guarda el resultado en ai_backtest_learnings.json y nutre trade_memory.json.
    Retorna: (éxito, learning_record, mensaje_descriptivo)
    """
    clean_sym = _normalize_sym(symbol)
    if not clean_sym:
        return False, {}, "Símbolo inválido."

    # Cargar configuración si no se proporcionaron credenciales
    if not api_key:
        try:
            from core.config_manager import load_config
            cfg = load_config()
            api_key = str(cfg.get("ai_api_key", "")).strip()
            model_name = model_name or str(cfg.get("ai_model", "gemini-2.5-flash"))
            base_url = base_url or str(cfg.get("ai_base_url", ""))
        except Exception:
            pass

    win_rate = float(backtest_data.get("win_rate", 50.0))
    avg_r = float(backtest_data.get("avg_r", 0.0))
    trades_count = int(backtest_data.get("trades", 0))
    raw_tf = backtest_data.get("timeframe", "M15")
    tf_str = str(raw_tf)

    sample_trades = backtest_data.get("sample_trades", [])
    wins_sample = [t for t in sample_trades if t.get("result") == "WIN"]
    losses_sample = [t for t in sample_trades if t.get("result") == "LOSS"]

    learning_record: Optional[Dict[str, Any]] = None
    ai_used = False

    if api_key:
        try:
            from core.ai_advisor import (
                send_ai_http_with_retry,
                _clean_json_text,
                DEFAULT_GEMINI_MODEL
            )

            model = model_name or DEFAULT_GEMINI_MODEL
            is_custom_provider = bool(base_url) or not model.startswith("gemini")

            # Preparar resumen de trades para el prompt
            trades_summary_text = []
            for idx, t in enumerate(sample_trades[:14]):
                sig = t.get("signal", "N/A")
                res = t.get("result", "N/A")
                pnl = t.get("pnl_r", 0.0)
                exit_r = t.get("exit_reason", "N/A")
                pat = t.get("pattern", "Estándar")
                bars = t.get("holding_bars", 0)
                trades_summary_text.append(
                    f"- Trade #{idx+1}: {sig} | Resultado: {res} ({pnl:+.2f}R) | Razón Salida: {exit_r} | Patrón: {pat} | Duración: {bars} velas"
                )

            trades_block = "\n".join(trades_summary_text) if trades_summary_text else "No hay operaciones individuales registradas."

            prompt = (
                f"Actúa como un Analista Cuantitativo Institucional y Mentor de Machine Learning para un bot de trading.\n"
                f"Hemos completado el backtest de la estrategia '{strategy.upper()}' para el par '{clean_sym}' en timeframe '{tf_str}'.\n\n"
                f"📊 MÉTRICAS GLOBALES DEL BACKTEST:\n"
                f"- Total de Trades: {trades_count}\n"
                f"- Win Rate: {win_rate}%\n"
                f"- Retorno Promedio por Trade: {avg_r:+.2f}R\n"
                f"- Operaciones Ganadoras (Muestra): {len(wins_sample)}\n"
                f"- Operaciones Perdedoras (Muestra): {len(losses_sample)}\n\n"
                f"📝 MUESTRA DE OPERACIONES EJECUTADAS:\n"
                f"{trades_block}\n\n"
                f"🎯 TU OBJETIVO:\n"
                f"1. Analizar qué condiciones técnicas o comportamientos provocaron las pérdidas (ej. sobrecompra RSI, whipsaws, consolidaciones ADX, mechas falsas).\n"
                f"2. Formular 'avoid_patterns': lista de 2 a 4 condiciones de mercado o trampas técnicas a EVITAR específicamente para este símbolo (ej. 'RSI > 65 en sobrecompra', 'ADX < 22 en rango lateral', 'Pérdida de EMA 50 en retroceso').\n"
                f"3. Formular 'risk_advice': recomendación clara de gestión de riesgo dinámico (ej. 'Exigir confluencia 4/4 estricta y asegurar Break-Even a +0.9R').\n"
                f"4. Formular 'key_takeaways': lista de 2 o 3 lecciones clave aprendidas del comportamiento del par.\n"
                f"5. Asignar 'confidence_score': valor numérico de 1 a 100 evaluando la fiabilidad de las reglas inferidas.\n\n"
                f"RESPONDE ÚNICAMENTE UN OBJETO JSON VÁLIDO CON ESTA ESTRUCTURA EXACTA (sin texto previo ni markdown exterior):\n"
                f"{{\n"
                f'  "avoid_patterns": ["patrón 1", "patrón 2"],\n'
                f'  "risk_advice": "texto con recomendación de riesgo",\n'
                f'  "key_takeaways": ["lección 1", "lección 2"],\n'
                f'  "confidence_score": 85\n'
                f"}}"
            )

            if is_custom_provider:
                endpoint = f"{base_url.rstrip('/')}/chat/completions" if base_url else "https://api.openai.com/v1/chat/completions"
                payload_obj = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Eres un analista cuantitativo institucional que responde únicamente JSON estricto."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 500
                }
                payload_bytes = json.dumps(payload_obj).encode("utf-8")
                req_headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
            else:
                endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload_obj = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 600
                    }
                }
                payload_bytes = json.dumps(payload_obj).encode("utf-8")
                req_headers = {"Content-Type": "application/json"}

            status_code, raw_res_text, duration_ms = send_ai_http_with_retry(
                endpoint=endpoint,
                payload_bytes=payload_bytes,
                headers=req_headers,
                max_retries=2,
                timeout_seconds=12.0,
                action_label=f"AI_LEARNING_{clean_sym}"
            )

            if status_code == 200 and raw_res_text:
                parsed_json = _clean_json_text(raw_res_text)
                if isinstance(parsed_json, dict):
                    # Si viene envuelto en candidates (Gemini) o choices (OpenAI)
                    if "candidates" in parsed_json:
                        candidate_text = parsed_json["candidates"][0]["content"]["parts"][0]["text"]
                        parsed_json = _clean_json_text(candidate_text)
                    elif "choices" in parsed_json:
                        choice_text = parsed_json["choices"][0]["message"]["content"]
                        parsed_json = _clean_json_text(choice_text)

                if isinstance(parsed_json, dict) and ("avoid_patterns" in parsed_json or "risk_advice" in parsed_json):
                    avoid_pats = [str(x) for x in parsed_json.get("avoid_patterns", [])]
                    risk_adv = str(parsed_json.get("risk_advice", ""))
                    takeaways = [str(x) for x in parsed_json.get("key_takeaways", [])]
                    conf = float(parsed_json.get("confidence_score", 85.0))

                    learning_record = {
                        "symbol": clean_sym,
                        "strategy": strategy,
                        "win_rate": win_rate,
                        "avg_r": avg_r,
                        "trades": trades_count,
                        "optimal_tf": tf_str,
                        "avoid_patterns": avoid_pats,
                        "risk_advice": risk_adv,
                        "key_takeaways": takeaways,
                        "confidence_score": conf,
                        "sample_wins": len(wins_sample),
                        "sample_losses": len(losses_sample),
                        "learned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "source": f"AI_{model}"
                    }
                    ai_used = True
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "Quota exceeded" in err_msg:
                print(f"ℹ️ [AI_BACKTEST_LEARNER] Cuota de IA agotada / 429 para {clean_sym}. Aplicando síntesis cuantitativa heurística local...")
            else:
                print(f"⚠️ [AI_BACKTEST_LEARNER] Error consultando IA para {clean_sym}: {e}. Aplicando síntesis cuantitativa...")

    # Si no se pudo obtener de la IA, aplicar síntesis cuantitativa robusta
    if not learning_record:
        learning_record = _build_heuristic_learning(clean_sym, strategy, backtest_data)

    # 1. Recuperar reglas anteriores para calcular el diferencial de parámetros
    old_learning = get_backtest_learnings_for_symbol(clean_sym)

    # 2. Guardar en ai_backtest_learnings.json
    save_backtest_learning(clean_sym, learning_record)

    # 3. Registrar el Merge Record (MR Changelog) de cambios para AI Strategy
    try:
        from core.ai_strategy_changelog import record_ai_strategy_change
        mr_record = record_ai_strategy_change(
            symbol=clean_sym,
            old_learning=old_learning,
            new_learning=learning_record,
            source=learning_record.get("source", "QUANT_HEURISTIC")
        )
        learning_record["mr_id"] = mr_record.get("mr_id")
        learning_record["changelog_summary"] = mr_record.get("summary")
        learning_record["changes"] = mr_record.get("changes")
    except Exception as e:
        print(f"⚠️ [AI_BACKTEST_LEARNER] Error registrando MR Changelog para {clean_sym}: {e}")

    # 4. Nutrir trade_memory.json con trades representativos del backtest
    try:
        from core.ai_memory import AIMemoryManager
        memory_mgr = AIMemoryManager()
        timestamp_base = int(time.time()) - (len(sample_trades) * 3600)
        for i, t in enumerate(sample_trades[-8:]):
            ticket_id = int(f"90{abs(hash(clean_sym)) % 1000:03d}{i:02d}")
            sig = t.get("signal", "BUY")
            res = t.get("result", "WIN")
            pnl_r = float(t.get("pnl_r", 0.0))
            pnl_usd = round(pnl_r * 50.0, 2)
            exit_reason = t.get("exit_reason", "BACKTEST_EXIT")

            trade_entry = {
                "trade_id": ticket_id,
                "symbol": clean_sym,
                "signal": sig,
                "ai_opinion": f"Operación de backtesting optimizada ({strategy.upper()}). Patrón: {t.get('pattern', 'Estándar')}",
                "outcome": {
                    "status": "CLOSED",
                    "result": res,
                    "pnl_r": pnl_r,
                    "pnl_usd": pnl_usd,
                    "exit_reason": exit_reason
                }
            }
            memory_mgr.save_analysis(trade_entry)
    except Exception as e:
        print(f"⚠️ [AI_BACKTEST_LEARNER] Error sincronizando con trade_memory: {e}")

    src_label = "Modelo de IA (" + learning_record.get("source", "IA") + ")" if ai_used else "Síntesis Cuantitativa Heurística"
    msg = f"Aprendizaje completado vía {src_label}. Reglas guardadas para {clean_sym} ({win_rate}% WR | {len(learning_record.get('avoid_patterns', []))} patrones evitados)."
    return True, learning_record, msg


def train_ai_batch_from_backtest(
    items: List[Dict[str, Any]],
    default_strategy: str = "ai_strategy",
    api_key: str = "",
    model_name: str = "",
    base_url: str = "",
    progress_callback: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Procesa el aprendizaje para múltiples pares en lotes (batch) optimizados.
    Agrupa hasta 4 pares por solicitud a la IA para reducir el consumo de tokens
    y evitar el límite de 20 peticiones diarias / rate limits (429).
    Si se detecta cuota agotada (RESOURCE_EXHAUSTED / 429), conmuta de inmediato
    a síntesis cuantitativa local para todos los pares restantes sin bloqueos.
    Retorna la lista de registros de aprendizaje enriquecidos con su MR Changelog.
    """
    if not items:
        return []

    # Cargar configuración si faltan parámetros
    if not api_key:
        try:
            from core.config_manager import load_config
            cfg = load_config()
            api_key = str(cfg.get("ai_api_key", "")).strip()
            model_name = model_name or str(cfg.get("ai_model", "gemini-2.5-flash"))
            base_url = base_url or str(cfg.get("ai_base_url", ""))
        except Exception:
            pass

    results: List[Dict[str, Any]] = []
    quota_exhausted = False
    total_count = len(items)

    # Si no hay API key o la cuota ya se agotó, procesar todo en heurística local rápidamente
    if not api_key:
        for idx, item in enumerate(items):
            sym = item.get("symbol", "")
            strat = item.get("strategy", default_strategy)
            if progress_callback:
                progress_callback(sym, idx, total_count, "Síntesis Cuantitativa Local")
            ok, rec, _ = train_ai_from_backtest(sym, strat, item, api_key="", model_name=model_name)
            if ok and rec:
                results.append(rec)
        return results

    # Agrupar en lotes de hasta 3 pares para un análisis comparativo y ahorro de cuota
    chunk_size = 3
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    current_idx = 0
    for chunk in chunks:
        # Si ya se detectó cuota agotada, procesar el resto en heurístico inmediatamente
        if quota_exhausted:
            for item in chunk:
                sym = item.get("symbol", "")
                strat = item.get("strategy", default_strategy)
                if progress_callback:
                    progress_callback(sym, current_idx, total_count, "Heurística (Cuota IA Agotada)")
                ok, rec, _ = train_ai_from_backtest(sym, strat, item, api_key="")
                if ok and rec:
                    results.append(rec)
                current_idx += 1
            continue

        # Si el lote tiene 1 solo par, usar función individual
        if len(chunk) == 1:
            item = chunk[0]
            sym = item.get("symbol", "")
            strat = item.get("strategy", default_strategy)
            if progress_callback:
                progress_callback(sym, current_idx, total_count, f"Consultando IA ({model_name})")
            ok, rec, _ = train_ai_from_backtest(
                symbol=sym,
                strategy=strat,
                backtest_data=item,
                api_key=api_key,
                model_name=model_name,
                base_url=base_url
            )
            if rec and "RESOURCE_EXHAUSTED" in str(rec.get("source", "")):
                quota_exhausted = True
            if ok and rec:
                results.append(rec)
            current_idx += 1
            continue

        # Lote múltiple: preparar prompt consolidado en una sola petición HTTP
        sym_names = [item.get("symbol", "") for item in chunk]
        if progress_callback:
            progress_callback(", ".join(sym_names), current_idx, total_count, f"Consultando IA en Lote ({len(chunk)} pares)")

        batch_prompt_parts = [
            f"Actúa como un Analista Cuantitativo Institucional y Mentor de Trading.\n"
            f"Hemos completado el backtest de la estrategia '{default_strategy.upper()}' para los siguientes {len(chunk)} pares de divisas:\n"
        ]

        for item in chunk:
            s_name = _normalize_sym(item.get("symbol", ""))
            wr = item.get("win_rate", 50.0)
            avg_r = item.get("avg_r", 0.0)
            trades_cnt = item.get("trades", 0)
            tf_s = item.get("timeframe", "M15")
            sample_tr = item.get("sample_trades", [])

            loss_cnt = sum(1 for t in sample_tr if t.get("result") == "LOSS")
            win_cnt = sum(1 for t in sample_tr if t.get("result") == "WIN")

            tr_summary = []
            for t in sample_tr[:6]:
                tr_summary.append(
                    f"{t.get('signal')}: {t.get('result')} ({t.get('pnl_r', 0):+.2f}R, {t.get('exit_reason')}, patrón {t.get('pattern', 'N/A')})"
                )
            tr_text = " | ".join(tr_summary) if tr_summary else "N/A"

            batch_prompt_parts.append(
                f"\n--- SÍMBOLO: {s_name} (TF: {tf_s}) ---\n"
                f"- Trades: {trades_cnt} (Wins: {win_cnt}, Losses: {loss_cnt}) | Win Rate: {wr}% | Avg R: {avg_r:+.2f}R\n"
                f"- Muestra Trades: {tr_text}\n"
            )

        batch_prompt_parts.append(
            f"\n🎯 TU OBJETIVO:\n"
            f"Para CADA símbolo, deduce qué trampas técnicas provocaron pérdidas (avoid_patterns), la recomendación de gestión de riesgo (risk_advice) y la confianza (confidence_score).\n"
            f"RESPONDE ÚNICAMENTE UN OBJETO JSON VÁLIDO donde las claves sean los símbolos exactos:\n"
            f"{{\n"
        )
        for i_s, s_name in enumerate(sym_names):
            comma = "," if i_s < len(sym_names) - 1 else ""
            clean_s = _normalize_sym(s_name)
            batch_prompt_parts.append(
                f'  "{clean_s}": {{\n'
                f'    "avoid_patterns": ["patrón 1 a evitar", "patrón 2 a evitar"],\n'
                f'    "risk_advice": "recomendación de gestión de riesgo dinámico",\n'
                f'    "key_takeaways": ["conclusión 1", "conclusión 2"],\n'
                f'    "confidence_score": 85\n'
                f'  }}{comma}\n'
            )
        batch_prompt_parts.append("}")

        full_batch_prompt = "".join(batch_prompt_parts)

        ai_batch_success = False
        parsed_batch_map: Dict[str, Any] = {}

        try:
            from core.ai_advisor import (
                send_ai_http_with_retry,
                _clean_json_text,
                DEFAULT_GEMINI_MODEL
            )
            model = model_name or DEFAULT_GEMINI_MODEL
            is_custom = bool(base_url) or not model.startswith("gemini")

            if is_custom:
                endpoint = f"{base_url.rstrip('/')}/chat/completions" if base_url else "https://api.openai.com/v1/chat/completions"
                payload_obj = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Eres un analista cuantitativo institucional que responde únicamente JSON estricto."},
                        {"role": "user", "content": full_batch_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1200
                }
                payload_bytes = json.dumps(payload_obj).encode("utf-8")
                req_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            else:
                endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload_obj = {
                    "contents": [{"parts": [{"text": full_batch_prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1400}
                }
                payload_bytes = json.dumps(payload_obj).encode("utf-8")
                req_headers = {"Content-Type": "application/json"}

            status_code, raw_res_text, duration_ms = send_ai_http_with_retry(
                endpoint=endpoint,
                payload_bytes=payload_bytes,
                headers=req_headers,
                max_retries=1,
                timeout_seconds=15.0,
                action_label="AI_BATCH_LEARN"
            )

            if status_code == 200 and raw_res_text:
                raw_json = _clean_json_text(raw_res_text)
                if isinstance(raw_json, dict):
                    if "candidates" in raw_json:
                        c_text = raw_json["candidates"][0]["content"]["parts"][0]["text"]
                        raw_json = _clean_json_text(c_text)
                    elif "choices" in raw_json:
                        c_text = raw_json["choices"][0]["message"]["content"]
                        raw_json = _clean_json_text(c_text)

                if isinstance(raw_json, dict):
                    parsed_batch_map = raw_json
                    ai_batch_success = True
        except Exception as e_batch:
            err_text = str(e_batch)
            if "429" in err_text or "RESOURCE_EXHAUSTED" in err_text or "Quota exceeded" in err_text:
                quota_exhausted = True
                print(f"ℹ️ [AI_BACKTEST_LEARNER] Cuota diaria de IA agotada durante lote. Conmutando a heurística local...")
            else:
                print(f"⚠️ [AI_BACKTEST_LEARNER] Error en lote IA: {e_batch}. Aplicando heurística...")

        # Consolidar resultados para cada símbolo del lote
        for item in chunk:
            s_name = item.get("symbol", "")
            clean_s = _normalize_sym(s_name)
            strat = item.get("strategy", default_strategy)

            ai_info = parsed_batch_map.get(clean_s, {}) if ai_batch_success else {}
            if isinstance(ai_info, dict) and ("avoid_patterns" in ai_info or "risk_advice" in ai_info):
                rec = {
                    "symbol": clean_s,
                    "strategy": strat,
                    "win_rate": float(item.get("win_rate", 50.0)),
                    "avg_r": float(item.get("avg_r", 0.0)),
                    "trades": int(item.get("trades", 0)),
                    "optimal_tf": str(item.get("timeframe", "M15")),
                    "avoid_patterns": [str(x) for x in ai_info.get("avoid_patterns", [])],
                    "risk_advice": str(ai_info.get("risk_advice", "")),
                    "key_takeaways": [str(x) for x in ai_info.get("key_takeaways", [])],
                    "confidence_score": float(ai_info.get("confidence_score", 85.0)),
                    "sample_wins": sum(1 for t in item.get("sample_trades", []) if t.get("result") == "WIN"),
                    "sample_losses": sum(1 for t in item.get("sample_trades", []) if t.get("result") == "LOSS"),
                    "learned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "source": f"AI_BATCH_{model_name}"
                }
                old_l = get_backtest_learnings_for_symbol(clean_s)
                save_backtest_learning(clean_s, rec)
                try:
                    from core.ai_strategy_changelog import record_ai_strategy_change
                    mr_rec = record_ai_strategy_change(clean_s, old_l, rec, source=rec["source"])
                    rec["mr_id"] = mr_rec.get("mr_id")
                    rec["changelog_summary"] = mr_rec.get("summary")
                    rec["changes"] = mr_rec.get("changes")
                except Exception:
                    pass
                results.append(rec)
            else:
                # Fallback heurístico para este símbolo
                ok, rec, _ = train_ai_from_backtest(s_name, strat, item, api_key="")
                if ok and rec:
                    results.append(rec)

            current_idx += 1

    return results
