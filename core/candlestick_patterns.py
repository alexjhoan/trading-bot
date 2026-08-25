try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None

from typing import Dict, Any, List, Optional, Tuple, Union


def _extract_ohlc_arrays(data: Any) -> Tuple[List[float], List[float], List[float], List[float]]:
    """Extrae listas de (opens, highs, lows, closes) a partir de DataFrame o lista de diccionarios."""
    if data is None:
        return [], [], [], []

    # Caso pandas DataFrame
    if pd is not None and isinstance(data, pd.DataFrame):
        if len(data) == 0:
            return [], [], [], []
        # En MT5/Trading, la última fila puede ser la barra en formación. Evaluamos las últimas velas cerradas.
        sub = data.iloc[-6:-1] if len(data) >= 6 else data.iloc[:-1]
        if len(sub) < 3:
            sub = data
        return (
            [float(x) for x in sub["open"].values],
            [float(x) for x in sub["high"].values],
            [float(x) for x in sub["low"].values],
            [float(x) for x in sub["close"].values]
        )

    # Caso lista de dicts (ej. [{"open": ..., "high": ...}, ...])
    if isinstance(data, list) and data:
        sub = data[-6:-1] if len(data) >= 6 else data[:-1]
        if len(sub) < 3:
            sub = data
        opens = [float(c.get("open", 0.0)) for c in sub]
        highs = [float(c.get("high", 0.0)) for c in sub]
        lows = [float(c.get("low", 0.0)) for c in sub]
        closes = [float(c.get("close", 0.0)) for c in sub]
        return opens, highs, lows, closes

    # Caso dict de listas (ej. {"open": [...], "high": [...]})
    if isinstance(data, dict) and "close" in data:
        n = len(data["close"])
        start = max(0, n - 6)
        end = max(1, n - 1) if n >= 6 else n
        return (
            [float(x) for x in data.get("open", [])[start:end]],
            [float(x) for x in data.get("high", [])[start:end]],
            [float(x) for x in data.get("low", [])[start:end]],
            [float(x) for x in data.get("close", [])[start:end]]
        )

    return [], [], [], []


def detect_candlestick_patterns(df: Any, lookback: int = 5) -> Dict[str, Any]:
    """
    Analiza las últimas velas y detecta patrones de velas japonesas basados
    en la guía institucional (Reversión Alcista, Reversión Bajista, Continuación Alcista,
    Continuación Bajista y Velas Neutras).

    Retorna un diccionario con:
    - primary_pattern: Nombre del patrón más relevante detectado en las últimas barras.
    - pattern_type: 'BULLISH_REVERSAL', 'BEARISH_REVERSAL', 'BULLISH_CONTINUATION', 'BEARISH_CONTINUATION', 'NEUTRAL', 'NONE'
    - bias: 'BULLISH', 'BEARISH', 'NEUTRAL'
    - strength: 'STRONG', 'MEDIUM', 'MODERATE', 'WEAK'
    - description: Explicación textual detallada lista para el prompt de la IA y logs del bot.
    - recent_patterns: Lista de patrones detectados en las últimas barras.
    - candle_metrics: Métricas de la última vela cerrada (cuerpo, mechas, ratio).
    """
    opens, highs, lows, closes = _extract_ohlc_arrays(df)
    n = len(closes)

    if n < 2:
        return {
            "primary_pattern": "None",
            "pattern_type": "NONE",
            "bias": "NEUTRAL",
            "strength": "WEAK",
            "description": "Insuficientes velas para análisis de patrones.",
            "recent_patterns": [],
            "candle_metrics": {}
        }

    # Métricas de las 3 últimas velas (index -1: última cerrada c1, -2: penúltima c2, -3: antepenúltima c3)
    c1_o, c1_h, c1_l, c1_c = opens[-1], highs[-1], lows[-1], closes[-1]  # Última cerrada
    c2_o, c2_h, c2_l, c2_c = opens[-2], highs[-2], lows[-2], closes[-2]  # Penúltima
    c3_o, c3_h, c3_l, c3_c = (opens[-3], highs[-3], lows[-3], closes[-3]) if n >= 3 else (c2_o, c2_h, c2_l, c2_c)

    def get_candle_props(o: float, h: float, l: float, c: float):
        rng = max(h - l, 1e-6)
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        is_bull = c > o
        is_bear = c < o
        body_pct = body / rng
        upper_pct = upper_wick / rng
        lower_pct = lower_wick / rng
        is_doji = body_pct <= 0.12
        is_marubozu = body_pct >= 0.82 and upper_pct <= 0.10 and lower_pct <= 0.10
        is_spinning_top = body_pct <= 0.35 and upper_pct >= 0.20 and lower_pct >= 0.20
        return {
            "rng": rng, "body": body, "upper_wick": upper_wick, "lower_wick": lower_wick,
            "is_bull": is_bull, "is_bear": is_bear, "body_pct": body_pct,
            "upper_pct": upper_pct, "lower_pct": lower_pct,
            "is_doji": is_doji, "is_marubozu": is_marubozu, "is_spinning_top": is_spinning_top
        }

    p1 = get_candle_props(c1_o, c1_h, c1_l, c1_c)  # Vela actual
    p2 = get_candle_props(c2_o, c2_h, c2_l, c2_c)  # Vela anterior
    p3 = get_candle_props(c3_o, c3_h, c3_l, c3_c)  # Vela ante-anterior

    detected_patterns: List[Dict[str, Any]] = []

    # =========================================================================
    # 1. PATRONES DE 3 VELAS (MÁXIMA PRIORIDAD ESTRUCTURAL)
    # =========================================================================
    if n >= 3:
        # A) MORNING STAR (Estrella de la Mañana) & BULLISH ABANDONED BABY
        is_morning_star = (
            p3["is_bear"] and (p3["body_pct"] >= 0.35 or p3["body"] >= p2["body"] * 1.5) and
            (p2["body"] <= p3["body"] * 0.75 or p2["is_doji"] or p2["is_spinning_top"] or p2["body_pct"] <= 0.45) and
            (c2_l <= min(c3_l, c1_l) or c2_o <= c3_c or c2_c <= c3_c) and
            p1["is_bull"] and (p1["body_pct"] >= 0.35) and (c1_c >= (c3_o + c3_c) / 2)
        )
        if is_morning_star:
            if p2["is_doji"]:
                detected_patterns.append({
                    "name": "Bullish Abandoned Baby / Morning Doji Star",
                    "type": "BULLISH_REVERSAL",
                    "bias": "BULLISH",
                    "strength": "STRONG",
                    "desc": "Estrella Doji de la Mañana: Suelo firme con Doji aislado en mínimo y fuerte vela alcista de confirmación."
                })
            else:
                detected_patterns.append({
                    "name": "Morning Star",
                    "type": "BULLISH_REVERSAL",
                    "bias": "BULLISH",
                    "strength": "STRONG",
                    "desc": "Estrella de la Mañana (Morning Star): Confirmación institucional de cambio a tendencia alcista."
                })

        # B) EVENING STAR (Estrella del Atardecer) & BEARISH ABANDONED BABY
        is_evening_star = (
            p3["is_bull"] and (p3["body_pct"] >= 0.35 or p3["body"] >= p2["body"] * 1.5) and
            (p2["body"] <= p3["body"] * 0.75 or p2["is_doji"] or p2["is_spinning_top"] or p2["body_pct"] <= 0.45) and
            (c2_h >= max(c3_h, c1_h) or c2_o >= c3_c or c2_c >= c3_c) and
            p1["is_bear"] and (p1["body_pct"] >= 0.35) and (c1_c <= (c3_o + c3_c) / 2)
        )
        if is_evening_star:
            if p2["is_doji"]:
                detected_patterns.append({
                    "name": "Bearish Abandoned Baby / Evening Doji Star",
                    "type": "BEARISH_REVERSAL",
                    "bias": "BEARISH",
                    "strength": "STRONG",
                    "desc": "Estrella Doji del Atardecer: Techo firme con Doji aislado y fuerte vela bajista de confirmación."
                })
            else:
                detected_patterns.append({
                    "name": "Evening Star",
                    "type": "BEARISH_REVERSAL",
                    "bias": "BEARISH",
                    "strength": "STRONG",
                    "desc": "Estrella del Atardecer (Evening Star): Confirmación institucional de techo y giro bajista."
                })

        # C) THREE WHITE SOLDIERS (Tres Soldados Blancos)
        if (p3["is_bull"] and p2["is_bull"] and p1["is_bull"] and
            c1_c > c2_c > c3_c and c1_o > c2_o > c3_o and
            p1["body_pct"] >= 0.45 and p2["body_pct"] >= 0.45 and p3["body_pct"] >= 0.45):
            detected_patterns.append({
                "name": "Three White Soldiers",
                "type": "BULLISH_REVERSAL",
                "bias": "BULLISH",
                "strength": "STRONG",
                "desc": "Tres Soldados Blancos: Presión compradora institucional sostenida en avance consecutivo."
            })

        # D) THREE BLACK CROWS (Tres Cuervos Negros)
        if (p3["is_bear"] and p2["is_bear"] and p1["is_bear"] and
            c1_c < c2_c < c3_c and c1_o < c2_o < c3_o and
            p1["body_pct"] >= 0.45 and p2["body_pct"] >= 0.45 and p3["body_pct"] >= 0.45):
            detected_patterns.append({
                "name": "Three Black Crows",
                "type": "BEARISH_REVERSAL",
                "bias": "BEARISH",
                "strength": "STRONG",
                "desc": "Tres Cuervos Negros: Presión vendedora institucional sostenida en caída consecutiva."
            })

        # E) THREE INSIDE UP (Tres Velas Internas Alcistas)
        if (p3["is_bear"] and p2["is_bull"] and c2_c <= c3_o and c2_o >= c3_c and
            p1["is_bull"] and c1_c > c3_o):
            detected_patterns.append({
                "name": "Three Inside Up",
                "type": "BULLISH_REVERSAL",
                "bias": "BULLISH",
                "strength": "STRONG",
                "desc": "Three Inside Up: Harami alcista confirmado con ruptura al alza de máximos previos."
            })

        # F) THREE INSIDE DOWN (Tres Velas Internas Bajistas)
        if (p3["is_bull"] and p2["is_bear"] and c2_c >= c3_o and c2_o <= c3_c and
            p1["is_bear"] and c1_c < c3_o):
            detected_patterns.append({
                "name": "Three Inside Down",
                "type": "BEARISH_REVERSAL",
                "bias": "BEARISH",
                "strength": "STRONG",
                "desc": "Three Inside Down: Harami bajista confirmado con ruptura a la baja de mínimos previos."
            })

        # G) THREE OUTSIDE UP (Tres Velas Externas Alcistas)
        if (p3["is_bear"] and p2["is_bull"] and c2_o <= c3_c and c2_c >= c3_o and
            p1["is_bull"] and c1_c > c2_h):
            detected_patterns.append({
                "name": "Three Outside Up",
                "type": "BULLISH_REVERSAL",
                "bias": "BULLISH",
                "strength": "STRONG",
                "desc": "Three Outside Up: Envolvente alcista confirmada con expansión de rango."
            })

        # H) THREE OUTSIDE DOWN (Tres Velas Externas Bajistas)
        if (p3["is_bull"] and p2["is_bear"] and c2_o >= c3_c and c2_c <= c3_o and
            p1["is_bear"] and c1_c < c2_l):
            detected_patterns.append({
                "name": "Three Outside Down",
                "type": "BEARISH_REVERSAL",
                "bias": "BEARISH",
                "strength": "STRONG",
                "desc": "Three Outside Down: Envolvente bajista confirmada con expansión bajista."
            })

        # I) BULLISH STICK SANDWICH & BEARISH STICK SANDWICH
        if p3["is_bear"] and p2["is_bull"] and p1["is_bear"] and abs(c1_c - c3_c) <= p1["rng"] * 0.15:
            detected_patterns.append({
                "name": "Bullish Stick Sandwich",
                "type": "BULLISH_REVERSAL",
                "bias": "BULLISH",
                "strength": "MEDIUM",
                "desc": "Bullish Stick Sandwich: Doble cierre idéntico en soporte con absorción compradora."
            })
        elif p3["is_bull"] and p2["is_bear"] and p1["is_bull"] and abs(c1_c - c3_c) <= p1["rng"] * 0.15:
            detected_patterns.append({
                "name": "Bearish Stick Sandwich",
                "type": "BEARISH_REVERSAL",
                "bias": "BEARISH",
                "strength": "MEDIUM",
                "desc": "Bearish Stick Sandwich: Doble cierre en techo con absorción vendedora."
            })

        # J) ADVANCE BLOCK (Bloque de Avance - Agotamiento Comprador)
        if (p3["is_bull"] and p2["is_bull"] and p1["is_bull"] and
            c1_c > c2_c > c3_c and p1["upper_pct"] >= 0.35 and p1["body"] < p2["body"] < p3["body"]):
            detected_patterns.append({
                "name": "Advance Block",
                "type": "BEARISH_REVERSAL",
                "bias": "BEARISH",
                "strength": "MEDIUM",
                "desc": "Advance Block: Cuerpos alcistas decrecientes con mechas superiores largas (agotamiento de compra)."
            })

        # K) 3 STARS IN THE SOUTH (3 Estrellas del Sur - Agotamiento Bajista)
        if (p3["is_bear"] and p2["is_bear"] and p1["is_bear"] and
            c1_c < c2_c < c3_c and p1["lower_pct"] >= 0.35 and p1["body"] < p2["body"] < p3["body"]):
            detected_patterns.append({
                "name": "3 Stars In The South",
                "type": "BULLISH_REVERSAL",
                "bias": "BULLISH",
                "strength": "MEDIUM",
                "desc": "3 Estrellas del Sur: Cuerpos bajistas decrecientes con mechas inferiores (agotamiento de venta)."
            })

        # L) RISING THREE METHODS (Triple Formación Alcista - Continuación)
        if (p3["is_bull"] and p3["body_pct"] >= 0.45 and
            p2["is_bear"] and c2_h <= c3_h and c2_l >= c3_l and
            p1["is_bull"] and c1_c > c3_h):
            detected_patterns.append({
                "name": "Rising Three Methods",
                "type": "BULLISH_CONTINUATION",
                "bias": "BULLISH",
                "strength": "STRONG",
                "desc": "Triple Formación Alcista (Rising Three): Consolidación de respiro y continuación alcista."
            })

        # M) FALLING THREE METHODS (Triple Formación Bajista - Continuación)
        if (p3["is_bear"] and p3["body_pct"] >= 0.45 and
            p2["is_bull"] and c2_h <= c3_h and c2_l >= c3_l and
            p1["is_bear"] and c1_c < c3_l):
            detected_patterns.append({
                "name": "Falling Three Methods",
                "type": "BEARISH_CONTINUATION",
                "bias": "BEARISH",
                "strength": "STRONG",
                "desc": "Triple Formación Bajista (Falling Three): Consolidación y continuación bajista."
            })

    # =========================================================================
    # 2. PATRONES DE 2 VELAS
    # =========================================================================
    # A) BULLISH ENGULFING (Envolvente Alcista)
    if (p2["is_bear"] and p1["is_bull"] and
        c1_o <= c2_c and c1_c >= c2_o and p1["body_pct"] >= 0.45):
        detected_patterns.append({
            "name": "Bullish Engulfing",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "STRONG",
            "desc": "Vela Envolvente Alcista: Compradores absorben completamente la oferta previa."
        })

    # B) BEARISH ENGULFING (Envolvente Bajista)
    if (p2["is_bull"] and p1["is_bear"] and
        c1_o >= c2_c and c1_c <= c2_o and p1["body_pct"] >= 0.45):
        detected_patterns.append({
            "name": "Bearish Engulfing",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "STRONG",
            "desc": "Vela Envolvente Bajista: Vendedores absorben completamente la demanda previa."
        })

    # C) PIERCING LINE (Pauta Penetrante Alcista)
    if (p2["is_bear"] and p2["body_pct"] >= 0.35 and
        p1["is_bull"] and c1_o <= c2_l and c1_c >= (c2_o + c2_c) / 2 and c1_c < c2_o):
        detected_patterns.append({
            "name": "Piercing Line",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "STRONG",
            "desc": "Pauta Penetrante Alcista: Rechazo de nuevos mínimos y penetración >50% en la vela previa."
        })

    # D) DARK CLOUD COVER (Nube Oscura Bajista)
    if (p2["is_bull"] and p2["body_pct"] >= 0.35 and
        p1["is_bear"] and c1_o >= c2_h and c1_c <= (c2_o + c2_c) / 2 and c1_c > c2_o):
        detected_patterns.append({
            "name": "Dark Cloud Cover",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "STRONG",
            "desc": "Nube Oscura Bajista: Rechazo de máximos y penetración bajista profunda >50%."
        })

    # E) BULLISH HARAMI
    if (p2["is_bear"] and p2["body_pct"] >= 0.40 and
        p1["is_bull"] and c1_o >= c2_c and c1_c <= c2_o and p1["body_pct"] <= 0.45):
        detected_patterns.append({
            "name": "Bullish Harami",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "MEDIUM",
            "desc": "Harami Alcista: Frenazo en la presión vendedora en zona de soporte."
        })

    # F) BEARISH HARAMI
    if (p2["is_bull"] and p2["body_pct"] >= 0.40 and
        p1["is_bear"] and c1_o <= c2_c and c1_c >= c2_o and p1["body_pct"] <= 0.45):
        detected_patterns.append({
            "name": "Bearish Harami",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "MEDIUM",
            "desc": "Harami Bajista: Agotamiento de la presión compradora en resistencia."
        })

    # G) TWEEZER BOTTOM (Pinzas Inferiores)
    if (abs(c1_l - c2_l) <= p1["rng"] * 0.08 and p1["lower_pct"] >= 0.25 and p2["lower_pct"] >= 0.25):
        detected_patterns.append({
            "name": "Tweezer Bottom",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "MEDIUM",
            "desc": "Pinzas Inferiores (Tweezer Bottom): Doble rechazo exacto en soporte clave."
        })

    # H) TWEEZER TOP (Pinzas Superiores)
    if (abs(c1_h - c2_h) <= p1["rng"] * 0.08 and p1["upper_pct"] >= 0.25 and p2["upper_pct"] >= 0.25):
        detected_patterns.append({
            "name": "Tweezer Top",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "MEDIUM",
            "desc": "Pinzas Superiores (Tweezer Top): Doble rechazo exacto en resistencia clave."
        })

    # I) BULLISH MEETING / BEARISH MEETING
    if p2["is_bear"] and p1["is_bull"] and abs(c1_c - c2_c) <= p1["rng"] * 0.08:
        detected_patterns.append({
            "name": "Bullish Meeting Lines",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "MEDIUM",
            "desc": "Líneas de Encuentro Alcista: Cierre alcista emparejado con cierre previo."
        })
    elif p2["is_bull"] and p1["is_bear"] and abs(c1_c - c2_c) <= p1["rng"] * 0.08:
        detected_patterns.append({
            "name": "Bearish Meeting Lines",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "MEDIUM",
            "desc": "Líneas de Encuentro Bajista: Cierre bajista emparejado con techo previo."
        })

    # J) MATCHING LOW & MATCHING HIGH
    if p2["is_bear"] and p1["is_bear"] and abs(c1_c - c2_c) <= p1["rng"] * 0.06:
        detected_patterns.append({
            "name": "Matching Low",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "MEDIUM",
            "desc": "Matching Low: Suelo de soporte confirmado por cierres bajistas idénticos."
        })
    elif p2["is_bull"] and p1["is_bull"] and abs(c1_c - c2_c) <= p1["rng"] * 0.06:
        detected_patterns.append({
            "name": "Matching High",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "MEDIUM",
            "desc": "Matching High: Techo de resistencia confirmado por cierres alcistas idénticos."
        })

    # K) BULLISH KICKER & BEARISH KICKER
    if (p2["is_bear"] and p1["is_bull"] and c1_o >= c2_o and p1["body_pct"] >= 0.70):
        detected_patterns.append({
            "name": "Bullish Kicker",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "STRONG",
            "desc": "Bullish Kicker: Brecha explosiva y cambio violento a control comprador."
        })
    elif (p2["is_bull"] and p1["is_bear"] and c1_o <= c2_o and p1["body_pct"] >= 0.70):
        detected_patterns.append({
            "name": "Bearish Kicker",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "STRONG",
            "desc": "Bearish Kicker: Brecha bajista explosiva y control vendedor institucional."
        })

    # L) UPSIDE / DOWNSIDE TASUKI GAP & SXS WHITE LINES (Continuaciones)
    if (p2["is_bull"] and p1["is_bull"] and c1_o >= c2_c and p1["body_pct"] >= 0.40):
        detected_patterns.append({
            "name": "Bullish Side-by-Side Lines / Gap",
            "type": "BULLISH_CONTINUATION",
            "bias": "BULLISH",
            "strength": "MEDIUM",
            "desc": "Líneas Lado a Lado / Gap Alcista: Continuación de impulso comprador con brecha."
        })
    elif (p2["is_bear"] and p1["is_bear"] and c1_o <= c2_c and p1["body_pct"] >= 0.40):
        detected_patterns.append({
            "name": "Bearish Side-by-Side Lines / Gap",
            "type": "BEARISH_CONTINUATION",
            "bias": "BEARISH",
            "strength": "MEDIUM",
            "desc": "Líneas Lado a Lado / Gap Bajista: Continuación de impulso vendedor con brecha."
        })

    # =========================================================================
    # 3. PATRONES DE 1 VELA INDIVIDUAL
    # =========================================================================
    # A) HAMMER (Martillo Alcista)
    if (p1["lower_wick"] >= 1.8 * p1["body"] and p1["upper_wick"] <= p1["body"] * 0.40 and p1["body_pct"] >= 0.12):
        detected_patterns.append({
            "name": "Hammer (Martillo)",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "MEDIUM",
            "desc": "Martillo Alcista: Rechazo contundente de precios bajos y fuerte absorción compradora."
        })

    # B) INVERTED HAMMER (Martillo Invertido)
    elif (p1["upper_wick"] >= 1.8 * p1["body"] and p1["lower_wick"] <= p1["body"] * 0.40 and p1["is_bull"] and p1["body_pct"] >= 0.12):
        detected_patterns.append({
            "name": "Inverted Hammer (Martillo Invertido)",
            "type": "BULLISH_REVERSAL",
            "bias": "BULLISH",
            "strength": "MODERATE",
            "desc": "Martillo Invertido: Presión compradora en base buscando confirmar giro."
        })

    # C) SHOOTING STAR (Estrella Fugaz Bajista)
    if (p1["upper_wick"] >= 1.8 * p1["body"] and p1["lower_wick"] <= p1["body"] * 0.40 and p1["body_pct"] >= 0.12):
        detected_patterns.append({
            "name": "Shooting Star (Estrella Fugaz)",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "MEDIUM",
            "desc": "Estrella Fugaz: Fuerte rechazo en máximos por presencia masiva de vendedores."
        })

    # D) HANGING MAN (Hombre Colgado)
    elif (p1["lower_wick"] >= 1.8 * p1["body"] and p1["upper_wick"] <= p1["body"] * 0.40 and p1["is_bear"] and p1["body_pct"] >= 0.12):
        detected_patterns.append({
            "name": "Hanging Man (Hombre Colgado)",
            "type": "BEARISH_REVERSAL",
            "bias": "BEARISH",
            "strength": "MODERATE",
            "desc": "Hombre Colgado: Advertencia de agotamiento comprador en zona alta."
        })

    # E) DRAGONFLY DOJI / GRAVESTONE DOJI
    if p1["is_doji"]:
        if p1["lower_pct"] >= 0.65:
            detected_patterns.append({
                "name": "Dragonfly Doji (Libélula)",
                "type": "BULLISH_REVERSAL",
                "bias": "BULLISH",
                "strength": "MEDIUM",
                "desc": "Doji Libélula: Rechazo total de mínimos con cierre en máximos."
            })
        elif p1["upper_pct"] >= 0.65:
            detected_patterns.append({
                "name": "Gravestone Doji (Lápida)",
                "type": "BEARISH_REVERSAL",
                "bias": "BEARISH",
                "strength": "MEDIUM",
                "desc": "Doji Lápida: Rechazo total de máximos con cierre en mínimos."
            })
        else:
            detected_patterns.append({
                "name": "Doji Clásico",
                "type": "NEUTRAL",
                "bias": "NEUTRAL",
                "strength": "WEAK",
                "desc": "Doji Clásico: Indecisión y equilibrio temporal entre oferta y demanda."
            })

    # F) MARUBOZU (Vela de Impulso Pleno)
    if p1["is_marubozu"]:
        if p1["is_bull"]:
            detected_patterns.append({
                "name": "Bullish Marubozu",
                "type": "BULLISH_CONTINUATION",
                "bias": "BULLISH",
                "strength": "STRONG",
                "desc": "Marubozu Alcista: Impulso comprador dominante y sin mechas."
            })
        else:
            detected_patterns.append({
                "name": "Bearish Marubozu",
                "type": "BEARISH_CONTINUATION",
                "bias": "BEARISH",
                "strength": "STRONG",
                "desc": "Marubozu Bajista: Impulso vendedor dominante y sin mechas."
            })

    # G) SPINNING TOP
    if p1["is_spinning_top"] and not p1["is_doji"]:
        detected_patterns.append({
            "name": "Spinning Top (Peonza)",
            "type": "NEUTRAL",
            "bias": "NEUTRAL",
            "strength": "WEAK",
            "desc": "Peonza: Indecisión en el mercado con fuerzas equilibradas."
        })

    # =========================================================================
    # SELECCIONAR PATRÓN PRINCIPAL
    # =========================================================================
    if not detected_patterns:
        bias = "BULLISH" if p1["is_bull"] else "BEARISH"
        strength = "MODERATE" if p1["body_pct"] >= 0.50 else "WEAK"
        type_str = "BULLISH_CONTINUATION" if p1["is_bull"] else "BEARISH_CONTINUATION"
        desc = f"Vela {('Alcista' if p1['is_bull'] else 'Bajista')} ({p1['body_pct']*100:.0f}% cuerpo)"
        return {
            "primary_pattern": f"Vela {('Alcista' if p1['is_bull'] else 'Bajista')}",
            "pattern_type": type_str,
            "bias": bias,
            "strength": strength,
            "description": desc,
            "recent_patterns": [],
            "candle_metrics": {
                "body_pct": round(p1["body_pct"], 2),
                "upper_pct": round(p1["upper_pct"], 2),
                "lower_pct": round(p1["lower_pct"], 2),
                "is_bull": p1["is_bull"]
            }
        }

    # Ordenar por prioridad: STRONG (3) > MEDIUM (2) > MODERATE (1) > WEAK (0)
    priority_map = {"STRONG": 3, "MEDIUM": 2, "MODERATE": 1, "WEAK": 0}
    detected_patterns.sort(key=lambda x: priority_map.get(x["strength"], 0), reverse=True)

    primary = detected_patterns[0]
    return {
        "primary_pattern": primary["name"],
        "pattern_type": primary["type"],
        "bias": primary["bias"],
        "strength": primary["strength"],
        "description": primary["desc"],
        "recent_patterns": [p["name"] for p in detected_patterns],
        "candle_metrics": {
            "body_pct": round(p1["body_pct"], 2),
            "upper_pct": round(p1["upper_pct"], 2),
            "lower_pct": round(p1["lower_pct"], 2),
            "is_bull": p1["is_bull"]
        }
    }


def format_candlestick_summary_for_ai(df: Any) -> str:
    """
    Genera una línea concisa y directa de patrones de velas japonesas para enriquecer los prompts de IA
    en evaluación de entradas y gestión activa de posiciones.
    """
    info = detect_candlestick_patterns(df)
    pat = info.get("primary_pattern", "None")
    bias = info.get("bias", "NEUTRAL")
    desc = info.get("description", "")
    strength = info.get("strength", "MODERATE")
    other = info.get("recent_patterns", [])

    if len(other) > 1:
        extra_str = f" (Confluencia: {', '.join(other[1:3])})"
    else:
        extra_str = ""

    return f"Patrón de Vela: {pat} [{bias} - {strength}]{extra_str} ➔ {desc}"
