## Estrategia v1.0 Simple Trend + RSI

## 📌 Lógica Interna de la Estrategia Actual (`SimpleTrendStrategy`)

La estrategia analiza únicamente la **última vela cerrada** en la temporalidad configurada (`timeframe` en `config.py`, ej. M5, M15 o H1) utilizando 3 indicadores principales:

1. **SMA Rápida:** Media Móvil Simple de **10 periodos** (`fast_sma_period`).
2. **SMA Lenta:** Media Móvil Simple de **30 periodos** (`slow_sma_period`).
3. **RSI:** Índice de Fuerza Relativa de **14 periodos** (`rsi_period`).

---

### 1. Reglas para Entrada en COMPRA (`BUY`)

Se requiere que se cumplan **2 condiciones simultáneas** al cierre de la vela:

1. **Cruce Alcista de Tendencia:** La `SMA_10` debe estar **por encima** de la `SMA_30` ($\text{SMA}_{10} > \text{SMA}_{30}$). Esto indica que el impulso de corto plazo es más fuerte que la media de mediano plazo.
2. **Filtro de Momento / No Sobrecompra:** El RSI debe ser **menor a 70.0** ($\text{RSI} < 70$). Nos asegura entrar con impulso pero evitando comprar en el "techo" cuando el mercado está saturado.

$$\text{Fórmula BUY: } (\text{SMA}_{10} > \text{SMA}_{30}) \ \land \ (\text{RSI} < 70)$$

---

### 2. Reglas para Entrada en VENTA (`SELL`)

Se requiere que se cumplan **2 condiciones simultáneas** al cierre de la vela:

1. **Cruce Bajista de Tendencia:** La `SMA_10` debe estar **por debajo** de la `SMA_30` ($\text{SMA}_{10} < \text{SMA}_{30}$). Muestra que la presión vendedora reciente está dominando.
2. **Filtro de Momento / No Sobreventa:** El RSI debe ser **mayor a 30.0** ($\text{RSI} > 30$). Evitamos vender en el "fondo" cuando los vendedores ya están exhaustos.

$$\text{Fórmula SELL: } (\text{SMA}_{10} < \text{SMA}_{30}) \ \land \ (\text{RSI} > 30)$$

---

### 3. Reglas para SALIDAS y Cierres de Operaciones

Las salidas no dependen únicamente del TP o SL fijo; el bot las gestiona activamente bajo 3 criterios:

1. **Stop Loss (SL) Fijo de Protección:** Se coloca a **25 pips** (o el valor en `default_sl_pips`) del precio de entrada para limitar la pérdida máxima por operación según tu gestión de riesgo.
2. **Take Profit (TP) Objetivo:** Se coloca por defecto a **1.5 veces el SL** (37.5 pips) buscando una relación Riesgo:Beneficio de $1 : 1.5$.
3. **Salida Anticipada por Cambio de Tendencia (Early Exit):** Si el bot detecta que la condición de tendencia se invierte al cierre de una vela (ej. teníamos una posición en `BUY` y las medias se cruzan hacia `SELL`), el bot **cierra la operación de inmediato a precio de mercado** sin esperar a que toque el SL.
4. **Trailing Stop a Break-Even:** Si la operación avanza a favor por más de **15 pips**, el Stop Loss se traslada automáticamente al precio de entrada para asegurar riesgo cero.
