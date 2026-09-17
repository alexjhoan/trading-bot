import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

CHANGELOG_JSON_FILE = Path(__file__).resolve().parent.parent / "ai_strategy_changelog.json"
CHANGELOG_MD_FILE = Path(__file__).resolve().parent.parent / "docs" / "AI_STRATEGY_CHANGELOG.md"
_LOCK = threading.Lock()

# Parámetros base por defecto de AIStrategy para comparar la primera vez
DEFAULT_AISTRATEGY_BASE = {
    "min_confluence": 2,
    "adx_threshold": 20.0,
    "rsi_overbought": 70.0,
    "rsi_oversold": 30.0,
    "be_trigger_r": 1.0,
    "avoid_patterns": [],
    "risk_advice": "Confluencia estándar base 2/4. Break-Even en +1.0R."
}


def _ensure_files() -> None:
    """Asegura que los archivos de registro y documentación existan."""
    with _LOCK:
        try:
            CHANGELOG_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not CHANGELOG_JSON_FILE.exists() or CHANGELOG_JSON_FILE.stat().st_size == 0:
                with open(CHANGELOG_JSON_FILE, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)

            CHANGELOG_MD_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not CHANGELOG_MD_FILE.exists() or CHANGELOG_MD_FILE.stat().st_size == 0:
                header = (
                    "# 📜 Historial de Cambios y Modulación de Parámetros (MR Changelog) - AI Strategy\n\n"
                    "Este documento registra cronológicamente cada Merge Record (MR) y ajuste dinámico de parámetros\n"
                    "aprendidos por el Asesor de Inteligencia Artificial y el motor cuantitativo de Deep Search para `ai_strategy`.\n\n"
                    "---\n\n"
                )
                with open(CHANGELOG_MD_FILE, "w", encoding="utf-8") as f:
                    f.write(header)
        except Exception as e:
            print(f"❌ [CHANGELOG] Error inicializando archivos de changelog: {e}")


def load_all_changelogs() -> List[Dict[str, Any]]:
    """Lee todos los registros de cambios desde ai_strategy_changelog.json."""
    _ensure_files()
    with _LOCK:
        try:
            with open(CHANGELOG_JSON_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                data = json.loads(content)
                return data if isinstance(data, list) else []
        except Exception as e:
            print(f"⚠️ [CHANGELOG] Error leyendo {CHANGELOG_JSON_FILE}: {e}")
            return []


def _save_all_changelogs(entries: List[Dict[str, Any]]) -> bool:
    """Guarda de forma atómica la lista de changelogs en JSON."""
    _ensure_files()
    with _LOCK:
        try:
            tmp = CHANGELOG_JSON_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CHANGELOG_JSON_FILE)
            return True
        except Exception as e:
            print(f"❌ [CHANGELOG] Error guardando {CHANGELOG_JSON_FILE}: {e}")
            return False


def _append_to_markdown_changelog(entry: Dict[str, Any]) -> None:
    """Añade una entrada estructurada en formato Markdown al archivo docs/AI_STRATEGY_CHANGELOG.md."""
    _ensure_files()
    with _LOCK:
        try:
            mr_id = entry.get("mr_id", "MR-UNKNOWN")
            timestamp = entry.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
            symbol = entry.get("symbol", "N/A")
            source = entry.get("source", "IA")
            summary = entry.get("summary", "Ajuste de parámetros.")
            diffs = entry.get("changes", [])
            avoid_pats = entry.get("avoid_patterns", [])
            risk_advice = entry.get("risk_advice", "")
            metrics = entry.get("metrics", {})

            lines: List[str] = []
            lines.append(f"## 📌 [{mr_id}] {symbol} — {timestamp}\n")
            lines.append(f"**Origen / Trigger:** `{source}`  ")
            lines.append(f"**Estrategia Objetivo:** `AI_STRATEGY`  ")
            if metrics:
                wr = metrics.get("win_rate", "N/A")
                avg_r = metrics.get("avg_r", "N/A")
                trades = metrics.get("trades", "N/A")
                lines.append(f"**Métricas Backtest:** Win Rate: `{wr}%` | Avg R: `{avg_r}R` | Trades: `{trades}`  ")
            lines.append(f"\n### 📝 Resumen del Cambio\n{summary}\n")

            if diffs:
                lines.append("### 🔄 Comparativa de Parámetros (Anterior vs Nuevo)\n")
                lines.append("| Parámetro | Valor Anterior | Valor Nuevo | Variación | Razón del Ajuste |")
                lines.append("| :--- | :---: | :---: | :---: | :--- |")
                for d in diffs:
                    p = d.get("parameter", "")
                    old_v = d.get("old_value", "N/A")
                    new_v = d.get("new_value", "N/A")
                    delta = d.get("difference", "")
                    desc = d.get("description", "")
                    lines.append(f"| **`{p}`** | `{old_v}` | **`{new_v}`** | `{delta}` | {desc} |")
                lines.append("")

            if avoid_pats:
                lines.append("### 🚫 Trampas y Patrones Técnicos a Evitar")
                for p in avoid_pats:
                    lines.append(f"- ⚠️ {p}")
                lines.append("")

            if risk_advice:
                lines.append(f"### 🛡️ Recomendación de Gestión de Riesgo\n> {risk_advice}\n")

            lines.append("\n---\n\n")

            # Insertar la nueva entrada arriba o apendizar
            current_md = ""
            if CHANGELOG_MD_FILE.exists():
                with open(CHANGELOG_MD_FILE, "r", encoding="utf-8") as f:
                    current_md = f.read()

            entry_text = "".join(lines)
            # Si tiene encabezado, insertar justo después del encabezado
            if "---\n\n" in current_md:
                parts = current_md.split("---\n\n", 1)
                new_md = parts[0] + "---\n\n" + entry_text + parts[1]
            else:
                new_md = current_md + "\n" + entry_text

            with open(CHANGELOG_MD_FILE, "w", encoding="utf-8") as f:
                f.write(new_md)

        except Exception as e:
            print(f"❌ [CHANGELOG] Error actualizando Markdown changelog: {e}")


def _derive_thresholds_for_learning(learning: Dict[str, Any]) -> Dict[str, Any]:
    """Deduce los parámetros operativos concretos que AIStrategy aplicará a partir del aprendizaje."""
    if not learning:
        return dict(DEFAULT_AISTRATEGY_BASE)

    win_rate = float(learning.get("win_rate", 50.0))
    avoid_patterns = [str(x).upper() for x in learning.get("avoid_patterns", [])]
    risk_advice = str(learning.get("risk_advice", "")).upper()

    # Base
    rsi_ob = 70.0
    rsi_os = 30.0
    adx_thresh = 20.0
    confluence = 3
    be_r = 1.0

    for avoid in avoid_patterns:
        if "RSI > 6" in avoid or "SOBRECOMPRA" in avoid:
            rsi_ob = 65.0
        if "RSI < 3" in avoid or "SOBREVENTA" in avoid:
            rsi_os = 35.0
        if "ADX" in avoid or "LATERAL" in avoid or "RANGO" in avoid or "CONSOLIDACION" in avoid:
            adx_thresh = 23.0

    if win_rate < 45.0:
        confluence = 4
        adx_thresh = max(adx_thresh, 24.0)
    elif win_rate >= 70.0:
        confluence = 2
    else:
        confluence = 3

    if "0.9R" in risk_advice or "BREAK-EVEN" in risk_advice or "TEMPRANO" in risk_advice:
        be_r = 0.9
    elif "1.2R" in risk_advice:
        be_r = 1.2

    return {
        "min_confluence": confluence,
        "adx_threshold": adx_thresh,
        "rsi_overbought": rsi_ob,
        "rsi_oversold": rsi_os,
        "be_trigger_r": be_r,
        "avoid_patterns": learning.get("avoid_patterns", []),
        "risk_advice": learning.get("risk_advice", "")
    }


def record_ai_strategy_change(
    symbol: str,
    old_learning: Optional[Dict[str, Any]],
    new_learning: Dict[str, Any],
    source: str = "AI_LEARNING"
) -> Dict[str, Any]:
    """
    Registra un Merge Record (MR) con el resumen de parámetros anteriores y nuevos
    para el símbolo especificado en AIStrategy.
    """
    clean_sym = symbol.strip().upper()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    timestamp_compact = time.strftime("%Y%m%d-%H%M%S")
    mr_id = f"MR-{timestamp_compact}-{clean_sym}"

    old_params = _derive_thresholds_for_learning(old_learning or {})
    new_params = _derive_thresholds_for_learning(new_learning)

    changes: List[Dict[str, Any]] = []

    # 1. min_confluence
    if old_params["min_confluence"] != new_params["min_confluence"] or not old_learning:
        diff_val = new_params["min_confluence"] - old_params["min_confluence"]
        sign = f"+{diff_val}" if diff_val > 0 else str(diff_val)
        wr = new_learning.get("win_rate", 50.0)
        desc = f"Calibración por Win Rate ({wr:.1f}%): " + (
            "Exigencia máxima 4/4 por debilidad o riesgo" if new_params["min_confluence"] == 4 else (
                "Permiso flexible 2/4 por alta consistencia" if new_params["min_confluence"] == 2 else "Confluencia equilibrada 3/4"
            )
        )
        changes.append({
            "parameter": "min_confluence",
            "old_value": f"{old_params['min_confluence']}/4",
            "new_value": f"{new_params['min_confluence']}/4",
            "difference": sign,
            "description": desc
        })

    # 2. adx_threshold
    if old_params["adx_threshold"] != new_params["adx_threshold"] or not old_learning:
        diff_val = new_params["adx_threshold"] - old_params["adx_threshold"]
        sign = f"+{diff_val:.1f}" if diff_val > 0 else f"{diff_val:.1f}"
        desc = "Filtro anti-consolidación activado" if new_params["adx_threshold"] >= 23.0 else "Umbral ADX estándar"
        changes.append({
            "parameter": "adx_trend_threshold",
            "old_value": f"{old_params['adx_threshold']:.1f}",
            "new_value": f"{new_params['adx_threshold']:.1f}",
            "difference": sign,
            "description": desc
        })

    # 3. rsi_overbought
    if old_params["rsi_overbought"] != new_params["rsi_overbought"] or not old_learning:
        diff_val = new_params["rsi_overbought"] - old_params["rsi_overbought"]
        sign = f"+{diff_val:.1f}" if diff_val > 0 else f"{diff_val:.1f}"
        desc = "Protección temprana ante techos de sobrecompra" if new_params["rsi_overbought"] <= 65.0 else "Nivel estándar base"
        changes.append({
            "parameter": "rsi_overbought",
            "old_value": f"{old_params['rsi_overbought']:.1f}",
            "new_value": f"{new_params['rsi_overbought']:.1f}",
            "difference": sign,
            "description": desc
        })

    # 4. rsi_oversold
    if old_params["rsi_oversold"] != new_params["rsi_oversold"] or not old_learning:
        diff_val = new_params["rsi_oversold"] - old_params["rsi_oversold"]
        sign = f"+{diff_val:.1f}" if diff_val > 0 else f"{diff_val:.1f}"
        desc = "Protección ante suelos de sobreventa" if new_params["rsi_oversold"] >= 35.0 else "Nivel estándar base"
        changes.append({
            "parameter": "rsi_oversold",
            "old_value": f"{old_params['rsi_oversold']:.1f}",
            "new_value": f"{new_params['rsi_oversold']:.1f}",
            "difference": sign,
            "description": desc
        })

    # 5. be_trigger_r
    if old_params["be_trigger_r"] != new_params["be_trigger_r"] or not old_learning:
        diff_val = new_params["be_trigger_r"] - old_params["be_trigger_r"]
        sign = f"+{diff_val:.1f}R" if diff_val > 0 else f"{diff_val:.1f}R"
        desc = "Break-Even ultra rápido a +0.9R para blindar capital" if new_params["be_trigger_r"] <= 0.9 else "Break-Even estándar"
        changes.append({
            "parameter": "be_trigger_r",
            "old_value": f"{old_params['be_trigger_r']:.1f}R",
            "new_value": f"{new_params['be_trigger_r']:.1f}R",
            "difference": sign,
            "description": desc
        })

    # Generar un resumen claro en lenguaje natural de lo que se hizo
    wr_cur = new_learning.get("win_rate", 50.0)
    avg_r_cur = new_learning.get("avg_r", 0.0)
    pats_count = len(new_learning.get("avoid_patterns", []))

    summary_parts = [
        f"Se analizó el comportamiento histórico de {clean_sym} en Deep Search ({wr_cur:.1f}% Win Rate, {avg_r_cur:+.2f}R).",
        f"Se identificaron {pats_count} patrones/trampas críticas a evitar.",
        f"Se ajustó la confluencia a {new_params['min_confluence']}/4 y ADX a {new_params['adx_threshold']:.1f} con Break-Even a {new_params['be_trigger_r']:.1f}R."
    ]
    summary = " ".join(summary_parts)

    entry = {
        "mr_id": mr_id,
        "timestamp": now_str,
        "symbol": clean_sym,
        "strategy": "AI_STRATEGY",
        "source": source,
        "summary": summary,
        "changes": changes,
        "avoid_patterns": new_learning.get("avoid_patterns", []),
        "risk_advice": new_learning.get("risk_advice", ""),
        "metrics": {
            "win_rate": wr_cur,
            "avg_r": avg_r_cur,
            "trades": new_learning.get("trades", 0),
            "confidence_score": new_learning.get("confidence_score", 80.0)
        }
    }

    # Guardar en JSON (historial cronológico)
    all_entries = load_all_changelogs()
    # Insertar al inicio (más reciente primero)
    all_entries.insert(0, entry)
    # Limitar a los últimos 200 registros
    if len(all_entries) > 200:
        all_entries = all_entries[:200]
    _save_all_changelogs(all_entries)

    # Actualizar documento Markdown docs/AI_STRATEGY_CHANGELOG.md
    _append_to_markdown_changelog(entry)

    return entry


def get_symbol_changelog(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Obtiene el historial de cambios registrado para un símbolo particular."""
    clean = symbol.strip().upper()
    all_entries = load_all_changelogs()
    filtered = [e for e in all_entries if e.get("symbol") == clean]
    return filtered[:limit]
