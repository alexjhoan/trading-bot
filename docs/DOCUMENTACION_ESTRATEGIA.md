# 📖 Documentación Técnica: Estrategia de Acción del Precio con Confluencia

## 1. Visión General
La estrategia `PriceActionStrategy` es un motor de decisión cuantitativo y determinista. Su objetivo es identificar **Rompimientos de Estructura de Mercado (BOS - Break of Structure)** válidos en niveles clave de Soporte y Resistencia, filtrados mediante un **Sistema de Puntuación de Confluencia (Confluence Score)** para evitar entradas en falsos rompimientos (*fakeouts*).

---

## 2. Lógica Algorítmica Paso a Paso

### A. Detección de Pivotes y Estructura (Soportes / Resistencias)
1. **Pivot High (Resistencia):** Se detecta cuando el precio máximo de una vela es estrictamente mayor que el máximo de las $N$ velas a la izquierda y a la derecha (`pivot_window`, por defecto 3).
2. **Pivot Low (Soporte):** Se detecta cuando el precio mínimo de una vela es estrictamente menor que el mínimo de las $N$ velas a la izquierda y a la derecha.
3. **Proyección (Forward Fill):** Los niveles de Soporte y Resistencia activos se proyectan hacia el futuro hasta que ocurra un nuevo pivote.

### B. Trigger Principal (Rompimiento de Estructura - BOS)
* **Rompimiento Alcista (BOS Buy):** Ocurre cuando el precio de cierre de la vela anterior estaba dentro/debajo de la resistencia (`prev_close <= resistance`) y el cierre de la vela actual rompe por encima (`curr_close > resistance`).
* **Rompimiento Bajista (BOS Sell):** Ocurre cuando el precio de cierre de la vela anterior estaba dentro/encima del soporte (`prev_close >= support`) y el cierre de la vela actual rompe por debajo (`curr_close < support`).

### C. Evaluación de Confluencia (Puntuación de 0 a 3 Puntos)
Si ocurre un rompimiento de estructura (BOS), el bot evalúa 3 confirmaciones adicionales:

1. **Volumen Institucional (+1 punto):** - Condición: `Tick Volume` actual $>$ `Media Móvil de Volumen (vol_ma, 20)`.
2. **Momentum del RSI (+1 punto):**
   - En Compras: `RSI(14) > 50`.
   - En Ventas: `RSI(14) < 50`.
3. **Fuerza del Cuerpo de Vela (+1 punto):**
   - Condición: `(Close - Open) / (High - Low) >= 0.50` (el cuerpo representa el 50% o más del rango total de la vela).

### D. Regla de Aprobación
* Si `Score Total >= min_confluence_score` (por defecto 2 de 3): **SE EMITE LA SEÑAL (BUY / SELL)**.
* Si `Score Total < min_confluence_score`: **SE CANCELA LA SEÑAL (HOLD)** por falta de confluencia técnica.

---

## 3. Integración con el Registro GUI / Debug Logs

Para reflejar el análisis detallado en la consola gráfica de la interfaz del Bot, la estrategia genera la siguiente estructura de logs de depuración:

```python
# 🟢 REGISTRO DE DEPURACIÓN EN GUI
debug_msg = (
    f"🔍 [ANALISIS ESTRATEGIA] {self.symbol} | Cierre: {curr_close:.5f}
"
    f"   ├─ Resistencia (Pivot High): {resistance:.5f}
"
    f"   ├─ Soporte (Pivot Low): {support:.5f}
"
    f"   ├─ Score Confluencia: {score}/{3} ({', '.join(score_details)})
"
    f"   ├─ ATR (14): {current_atr:.5f}
"
    f"   └─ Resultado: {signal_type} ➔ Razón: {reason}"
)
self._log(debug_msg, "INFO")
```

---

## 4. Retorno de Metadatos hacia `risk_manager.py`

La estrategia retorna un diccionario completo con la información técnica necesaria para la gestión de órdenes:

```python
{
    "signal": "BUY" | "SELL" | "HOLD",
    "support": float,      # Mínimo del pivote (soporte actual)
    "resistance": float,   # Máximo del pivote (resistencia actual)
    "atr": float,          # Volatilidad actual en ATR
    "score": int,          # Puntuación obtenida (0 a 3)
    "reason": str          # Descripción del motivo de entrada/descarte
}
```
