# 📖 Documentación Técnica: Estrategia de Acción del Precio con Confluencia

## 1. Visión General

La clase `PriceActionStrategy` implementa una estrategia cuantitativa determinista basada en Acción del Precio (_Price Action_) y Análisis de Liquidez. Identifica **Rompimientos de Estructura (BOS - Break of Structure)** sobre niveles clave de Soporte y Resistencia, filtrados mediante un **Sistema de Puntuación de Confluencia (Confluence Score)** para filtrar falsos rompimientos (_fakeouts_).

---

## 2. Funcionamiento Algorítmico

### A. Detección de Niveles Estructurales (Pivotes)

1. **Pivot High (Resistencia):** Se detecta si el precio máximo de una vela es el mayor dentro de una ventana de $2N + 1$ velas (donde $N$ es `pivot_window`).
2. **Pivot Low (Soporte):** Se detecta si el precio mínimo de una vela es el menor dentro de la ventana.
3. **Proyección (Forward Fill):** Los niveles detectados se extienden hacia adelante hasta la aparición de un nuevo pivote.

### B. Trigger Principal: Rompimiento de Estructura (BOS)

- **BOS Alcista (BUY):** Cierre de la vela anterior por debajo/dentro de la resistencia (`prev_close <= resistance`) y cierre de la vela actual por encima (`curr_close > resistance`).
- **BOS Bajista (SELL):** Cierre de la vela anterior por encima/dentro del soporte (`prev_close >= support`) y cierre de la vela actual por debajo (`curr_close < support`).

### C. Evaluación de Confluencia (0 a 3 Puntos)

Cuando ocurre un BOS, se suman puntos si se cumplen las siguientes condiciones:

1. **Volumen Institucional (+1 Pt):** `Tick Volume` actual $>$ `Media Móvil de Volumen (20 periodos)`.
2. **Momentum RSI (+1 Pt):** `RSI(14) > 50` para Compras, o `RSI(14) < 50` para Ventas.
3. **Fuerza del Cuerpo (+1 Pt):** El cuerpo de la vela representa al menos el $50\%$ del rango total de la vela `(High - Low)`.

### D. Regla de Aprobación

- Si `Score >= min_confluence_score` (ej. 2 de 3): **SE GENERA SEÑAL (BUY / SELL)**.
- Si `Score < min_confluence_score`: **SE DESCARTA LA ENTRADA (HOLD)**.
