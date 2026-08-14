# 📈 Estrategia: Acción del Precio + Confluencia Cuantitativa (BOS + Score)

## 1. Resumen Ejecutivo

Esta estrategia combina el **Análisis de Acción del Precio (Price Action)** basado en **Rompimientos de Estructura (BOS - Breakout of Structure)** con un **Sistema de Confluencia Cuantitativa** (+1 punto por cada filtro validado).

El objetivo es reducir los "falsos rompimientos" asegurando que cada orden solo se abra cuando el precio rompa un nivel clave **Y** cumpla con un mínimo de métricas estadísticas y de momentum a su favor.

## 2. Pilares de la Estrategia

La estrategia funciona bajo una condición jerárquica estricta:

[ Trigger Obligatorio: Rompimiento de Soporte/Resistencia (BOS) ]
│
▼
[ Evaluación de Confluencia (Puntuación de 0 a 3) ]
├─ Confirmación A: Volumen Institucional Superior a la Media (+1)
├─ Confirmación B: Momentum RSI alineado con la dirección (+1)
└─ Confirmación C: Vela con cuerpo fuerte (≥ 50% del rango) (+1)
│
▼
¿Score Total >= Min_Score (ej. 2 de 3)? ──► 🟢 [ ENTRAR (BUY / SELL) ]
│
└──► 🔴 [ RECHAZAR (HOLD) ]

## 3. Lógica Interna y Funcionamiento Técnico

### A. Detección de Niveles Clave (Pivot High / Pivot Low)

Para identificar Soportes y Resistencias dinámicos sin "mirar al futuro" _(evitando el sesgo de look-ahead / repaint)_:

- **Pivot High (Resistencia):** Es el punto máximo (`high`) de una ventana de velas centrales donde no hay ningún máximo mayor en un rango `w` (por defecto `pivot_window = 3`).
- **Pivot Low (Soporte):** Es el punto mínimo (`low`) donde no hay ningún mínimo menor en ese mismo rango `w`.
- **Proyección:** Los niveles se arrastran hacia adelante con un _Forward Fill_ (`ffill()`) para mantener las resistencias y soportes actuales.

### B. Trigger Obligatorio: Rompimiento de Estructura (BOS)

La estrategia revisa el comportamiento del precio utilizando la **última vela cerrada** (`iloc[-2]`) para evitar cambios durante la formación de la vela actual (`iloc[-1]`):

- **Señal Cruda Alcista (`raw_buy`):** $$\text{Precio Cierre Anterior} \le \text{Resistencia} \quad \text{y} \quad \text{Precio Cierre Actual} > \text{Resistencia}$$
- **Señal Cruda Bajista (`raw_sell`):** $$\text{Precio Cierre Anterior} \ge \text{Soporte} \quad \text{y} \quad \text{Precio Cierre Actual} < \text{Soporte}$$

> ⚠️ **Nota:** Si no hay un rompimiento del nivel previo, la estrategia emite inmediatamente `HOLD` independientemente de los otros indicadores.

### C. Sistema de Confluencia (Filtros de Calidad)

Si hay un BOS, la estrategia calcula una puntuación de confluencia (máximo 3 puntos):

1. **Volumen Institucional (+1 Punto):**
   - Evalúa el `tick_volume` de la vela actual frente a su Media Móvil Simple (SMA) de $N$ periodos (`volume_ma_period = 20`).
   - **Condición:** Si `tick_volume > vol_ma` $\rightarrow$ **+1 punto**.

2. **Momentum del RSI (+1 Punto):**
   - Mide el momentum relativo de 14 periodos (`rsi_period = 14`).
   - **Compra:** Si `RSI > 50` $\rightarrow$ **+1 punto**.
   - **Venta:** Si `RSI < 50` $\rightarrow$ **+1 punto**.

3. **Fuerza del Cuerpo de la Vela (+1 Punto):**
   - Calcula el ratio del cuerpo respecto al rango completo (sombras + cuerpo):
     $$\text{body\_ratio} = \frac{|\text{Close} - \text{Open}|}{\text{High} - \text{Low}}$$
   - **Condición:** Si $\text{body\_ratio} \ge 0.50$ (el cuerpo representa el 50% o más de la vela) $\rightarrow$ **+1 punto**.

## 4. Regla de Decisión Final

Para ejecutar una orden, el puntaje acumulado debe ser mayor o igual a `min_confluence_score` (configurable, valor predeterminado = `2`).

| BOS Detectado | Score Obtenido | Requerido |             Resultado Emitido             |
| :-----------: | :------------: | :-------: | :---------------------------------------: |
|     ❌ No     |  Irrelevante   |     2     |                  `HOLD`                   |
|  ✅ Alcista   |     1 / 3      |     2     | `HOLD` _(Rechazado por baja confluencia)_ |
|  ✅ Alcista   |     2 / 3      |     2     |                 🟢 `BUY`                  |
|  ✅ Bajista   |     3 / 3      |     2     |                 🔴 `SELL`                 |

Además, el bot retorna el valor del **ATR (Average True Range)** de 14 periodos, el cual se transfiere al `risk_manager.py` para definir dinámicamente el Stop Loss y Take Profit.

## 5. Parámetros de Configuración (`__init__`)

- `pivot_window` (Default: `3`): Define la sensibilidad de los niveles clave. Un valor más pequeño genera más soportes/resistencias; un valor más alto detecta solo niveles macro.
- `atr_period` (Default: `14`): Periodo para el cálculo del volatilidad ATR.
- `volume_ma_period` (Default: `20`): Periodo de la media móvil sobre el volumen.
- `rsi_period` (Default: `14`): Periodo del oscilador RSI.
- `min_confluence_score` (Default: `2`): Umbral mínimo de validación de filtros.

## 💡 Sugerencias de Seguimiento y Mejora en MT5

Al probar esta estrategia en tiempo real o en Backtest sobre MT5, te sugiero evaluar los siguientes aspectos:

1. **Gestión de Sesiones/Horarios:** La estrategia depende fuertemente del volumen. En horarios de baja liquidez (p. ej. sesión asiática en pares de USD/EUR), se pueden generar rupturas falsas. Podrías añadir un filtro de horario operacional.
2. **Filtro de Tendencia Macro:** Actualmente evalúa rupturas locales. Podrías agregar una EMA de 200 periodos; autorizar solo compras si el precio está por encima de la EMA200 y ventas si está por debajo.
3. **Calibración de `pivot_window` según el Timeframe:** \* En $M5$ o $M15$, un `pivot_window = 3` o `5` funciona bien para capturar impulsos intradía.
   - En $H1$ o $H4$, podrías requerir un `pivot_window = 2` o `3`.

## para usar en MT5

Para replicar **exactamente** en los gráficos de MetaTrader 5 la misma lógica que ejecuta `strategy.py`, necesitas combinar **3 indicadores/herramientas estándar** (2 de ellos osciladores) y un indicador personalizado opcional para visualizar los niveles de pivote.

Aquí tienes el desglose técnico de cada uno, su categoría y su configuración exacta en la plataforma.

---

## 1. RSI (Relative Strength Index) — _Oscilador_

Mide la fuerza y momentum del precio para validar si la tendencia del rompimiento (BOS) tiene impulso a favor.

- **Categoría:** Oscilador.
- **Ubicación en MT5:** `Insertar` ➔ `Indicadores` ➔ `Osciladores` ➔ `Relative Strength Index`.
- **Configuración de Parámetros:**
- **Periodo:** `14`
- **Aplicar a:** `Close`

- **Niveles (Sección Niveles):**
- Elimina los niveles habituales (70 y 30) o agrégale el nivel **`50`**.
- **Uso en la estrategia:** \* Si la señal cruda es **BUY**, el RSI debe estar **> 50** (+1 punto).
- Si la señal cruda es **SELL**, el RSI debe estar **< 50** (+1 punto).

---

## 2. Volumes (Con Media Móvil Integrada) — _Oscilador / Volumen_

Evalúa si la vela de ruptura tiene participación del capital institucional comparando el volumen de la vela actual contra el promedio reciente.

- **Categoría:** Volumen.
- **Ubicación en MT5:** `Insertar` ➔ `Indicadores` ➔ `Volúmenes` ➔ `Volumes`.
- **Configuración de Parámetros:**
- **Volúmenes:** `Tick` (ya que los brokers de Forex en MT5 trabajan con _Tick Volume_).

- **Cómo agregar la Media Móvil (SMA 20) sobre el Volumen:**

1. Ve a la ventana **Navegador** (`Ctrl + N`).
2. Despliega `Indicadores` ➔ `Tendencia` ➔ **Moving Average**.
3. **Arrastra y suelta** la `Moving Average` **dentro de la sub-ventana donde está el indicador de Volúmenes**.
4. Configura en la ventana emergente:

- **Periodo:** `20`
- **Método:** `Simple`
- **Aplicar a:** Cambia la opción a **`First Indicator's Data`** (o _Datos del primer indicador_).

- **Uso en la estrategia:** \* Si la barra de volumen actual es más alta que la línea de la SMA 20 (+1 punto).

---

## 3. ATR (Average True Range) — _Oscilador de Volatilidad_

Mide la volatilidad promedio del mercado en pips/puntos para que `risk_manager.py` determine las distancias del Stop Loss y Take Profit.

- **Categoría:** Oscilador.
- **Ubicación en MT5:** `Insertar` ➔ `Indicadores` ➔ `Osciladores` ➔ `Average True Range`.
- **Configuración de Parámetros:**
- **Periodo:** `14`

- **Uso en la estrategia:** \* No otorga puntuación en la confluencia, pero sirve para la gestión de riesgo dinámica.

---

## 4. Niveles de Soporte y Resistencia (Pivotes) — _Acción del Precio_

El algoritmo calcula los Pivotes dinámicos analizando un rango hacia la izquierda y derecha de `pivot_window = 3` (revisando si el High/Low es el máximo/mínimo en una ventana de 7 velas: $2 \times W + 1$).

- **En MT5 Estándar:** Puedes usar la herramienta nativa **ZigZag** (`Insertar` ➔ `Indicadores` ➔ `Ejemplos` ➔ `ZigZag`) o dibujar líneas horizontales manuales en los máximos/mínimos locales.
- **Configuración ZigZag recomendada:**
- **Depth:** `7`
- **Deviation:** `5`
- **Backstep:** `3`

---

## 📊 Resumen de Configuración en Pantalla

| Indicador            | Tipo              | Parámetros clave                               | Función en la estrategia                                                |
| -------------------- | ----------------- | ---------------------------------------------- | ----------------------------------------------------------------------- |
| **Pivot High / Low** | Acción del Precio | `pivot_window = 3`                             | **Trigger Obligatorio:** Nivel para detectar el BOS (Breakout).         |
| **RSI**              | Oscilador         | `Periodo = 14`, Nivel `50`                     | **Confluencia (+1 pts):** RSI > 50 para compras / RSI < 50 para ventas. |
| **Volumes + SMA**    | Volumen           | `SMA = 20` aplicada a `First Indicator's Data` | **Confluencia (+1 pts):** Tick Volume mayor a su media de 20 periodos.  |
| **Vela de Fuerza**   | Acción del Precio | Criterio $Cuerpo \ge 50\%$ del Rango Total     | **Confluencia (+1 pts):** Confirmación visual de intención.             |
| **ATR**              | Oscilador         | `Periodo = 14`                                 | Métricas de volatilidad para el cálculo del Stop Loss / Take Profit.    |
