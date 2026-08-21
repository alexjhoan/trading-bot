# Documentación de Estrategia: Acción del Precio Cuantitativa (Retest + Confluencia)

Esta documentación describe la estrategia cuantitativa de acción del precio implementada en el bot de trading para **MetaTrader 5 (MT5)**, detallando sus fundamentos teóricos, la lógica de confluencia, los parámetros clave y la configuración paso a paso en la plataforma MT5 para réplica manual o supervisión.

---

## 1. Resumen de la Estrategia

La estrategia **Price Action Quantitative Strategy** abandona las entradas por ruptura directa (_Breakout_) para enfocar su operativa en **Retests en Niveles Clave (Soportes y Resistencias)** a favor de la tendencia principal.

### Pilares Fundamentales

1. **Filtro de Tendencia Macro (EMA 200):**
   - Solo se buscan **compras (BUY)** si el precio está cotizando **por encima** de la EMA de 200 períodos.
   - Solo se buscan **ventas (SELL)** si el precio está cotizando **por debajo** de la EMA de 200 períodos.

2. **Estructura e Identificación de Niveles:**
   - **Pivotes sin Lag:** Identificación en tiempo real de _Pivot Highs_ y _Pivot Lows_ para proyectar zonas dinámicas de **Resistencia** y **Soporte**.

3. **Gatillo de Entrada (Retest / Reacción):**
   - **Compra:** El mínimo de la vela ingresa en la zona del soporte (con tolerancia basada en volatilidad) y el cierre de la vela logra mantenerse por encima de dicho nivel.
   - **Venta:** El máximo de la vela ingresa en la zona de resistencia y el cierre de la vela logra mantenerse por debajo.

4. **Sistema de Confluencia (Score 0 a 3):**
   Para habilitar una orden, se requiere un puntaje mínimo (**mínimo 2 de 3 confluencias**):
   - **Confluencia A:** Alineación con la EMA de 200 períodos (+1 punto).
   - **Confluencia B:** Volumen institucional alto (`Tick Volume` superior a la Media Móvil de Volumen de 20 períodos) (+1 punto).
   - **Confluencia C:** Confirmación por patrón de vela (_Hammer_ / _Shooting Star_) o fuerza del cuerpo de la vela ($\ge 50\%$ del rango total) (+1 punto).

5. **Gestión de Riesgo Dinámica (ATR):**
   - **Stop Loss (SL):** Distancia calculada mediante $1.5 	imes 	ext{ATR}(14)$.
   - **Take Profit (TP):** Distancia calculada mediante $3.0 	imes 	ext{ATR}(14)$ (Ratio Riesgo:Beneficio $1:2$).
   - **Mecanismo de Respaldo (_Fallback_):** Si el cálculo de ATR arroja cero o no está disponible, se aplican niveles estáticos fijados en pips (ej. 20 pips SL / 40 pips TP).

---

## 2. Parámetros Técnicos y Configuración del Algoritmo

| Parámetro              | Valor por Defecto | Descripción                                                      |
| :--------------------- | :---------------- | :--------------------------------------------------------------- |
| `pivot_window`         | `3`               | Ventana de velas para cálculo de Pivotes High/Low.               |
| `atr_period`           | `14`              | Período del Average True Range para SL/TP dinámicos.             |
| `atr_sl_mult`          | `1.5`             | Multiplicador de ATR para establecer el Stop Loss.               |
| `atr_tp_mult`          | `3.0`             | Multiplicador de ATR para establecer el Take Profit.             |
| `ema_trend_period`     | `200`             | Período de la Media Móvil Exponencial para filtro de tendencia.  |
| `volume_ma_period`     | `20`              | Período de la Media Móvil Simple aplicada al Volumen.            |
| `min_confluence_score` | `2`               | Puntuación mínima requerida para ejecutar orden (de 3 posibles). |
| `min_bars`             | `$\ge 210$`       | Mínimo de velas necesarias en el histórico descargado de MT5.    |

---

## 3. Guía Paso a Paso para Configurar y Replicar en MetaTrader 5

Para poder visualizar, validar y replicar manualmente las señales que genera el bot dentro de la plataforma MetaTrader 5, sigue estos pasos:

### Paso 1: Configurar el Histórico de Velas en MT5

Para evitar el error de `Insuficiente historial de datos` (`min_bars < 210`):

1. Abre tu terminal MetaTrader 5.
2. Ve al menú superior: **Herramientas $
ightarrow$ Opciones $
ightarrow$ Gráficos**.
3. En la opción **Máx. barras en gráfico**, selecciona **Unlimited** (Ilimitado) o ingresa al menos `50000`.
4. Haz clic en **Aceptar**.
5. Abre el gráfico del par a operar (ej. `EURUSD`, M15 o H1) y presiona la tecla **Inicio (Home)** varias veces para forzar la descarga de datos históricos.

### Paso 2: Agregar los Indicadores Visuales en el Gráfico

1. **Media Móvil Exponencial (EMA 200):**
   - Menú: **Insertar $
ightarrow$ Indicadores $
ightarrow$ Tendencia $
ightarrow$ Moving Average**.
   - Período: `200`.
   - Método: `Exponential` (Exponencial).
   - Aplicar a: `Close` (Cierre).
   - Estilo: Color llamativo (ej. Azul o Rojo, grosor medio).

2. **Volumen con Media Móvil:**
   - Menú: **Insertar $
ightarrow$ Indicadores $
ightarrow$ Volúmenes $
ightarrow$ Volumes**.
   - Para agregar la Media Móvil de 20 períodos sobre el volumen:
     _ Abre el **Navegador** (`Ctrl + N`).
     _ Ve a **Indicadores $
ightarrow$ Tendencia $
ightarrow$ Moving Average**.
     * Arrastra la `Moving Average` directamente dentro de la ventana inferior del indicador de *Volumes*.
     * En el menú desplegable **Aplicar a**, selecciona **Previous Indicator's Data** (Datos del indicador anterior). \* Período: `20`, Método: `Simple`.

3. **Average True Range (ATR 14):**
   - Menú: **Insertar $
ightarrow$ Indicadores $
ightarrow$ Osciladores $
ightarrow$ Average True Range**.
   - Período: `14`.

### Paso 3: Identificación Manual de la Estrategia

- **Paso A (Dirección):** Revisa si el precio está por encima de la EMA 200 (Buscar Compras) o por debajo (Buscar Ventas).
- **Paso B (Zona):** Traza las líneas horizontales en los máximos/mínimos locales más recientes (Pivotes).
- **Paso C (Trigger):** Espera a que la vela actual testee el nivel de soporte/resistencia y cierre dentro de la zona respetando la estructura.
- **Paso D (Confluencia):**
  1. ¿Está a favor de la EMA 200?
  2. ¿El volumen de la vela supera la media de 20 de volumen?
  3. ¿La vela formó un patrón _Hammer_ / _Shooting Star_ o su cuerpo representa más del 50% del rango total?
- Si acumula al menos **2 síes**, se ejecuta la operación posicionando el SL a $1.5 	imes 	ext{ATR}$ y el TP a $3.0 	imes 	ext{ATR}$.

---

_Documento generado para integración y réplica en MetaTrader 5 con Python._
