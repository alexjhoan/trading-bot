# ForexStrategy — Documentación Técnica

Documentación detallada de `core/strategies/forex.py`. El docstring de la clase en el código
mantiene solo un resumen corto; esta guía tiene la lógica completa y la configuración de
indicadores equivalente para poder visualizarla en un gráfico de MT5.

---

## 1. Filtros de entrada (orden de evaluación en `generate_signal`)

Cada filtro puede devolver `HOLD` y detener la evaluación antes de llegar al siguiente:

1. **Mercado abierto** (`STRATEGY_CONFIG.is_market_open`) — bloquea fines de semana / símbolo deshabilitado en MT5.
2. **Horario de sesión** (`use_session_filter`) — solo opera dentro de la sesión activa de las divisas del par (Londres/NY/Asia, calculado dinámicamente por símbolo).
3. **Filtro ADX (tendencia/lateralidad)** — si `ADX < adx_trend_threshold` (default 20), el mercado se considera lateral y se bloquean nuevas entradas.
4. **Filtro de sobreextensión EMA200** — si el precio está a más del 50% del rango de swing (o 1.5x ATR) de la EMA200, se bloquea: el impulso está agotado y es probable un retroceso.
5. **Tendencia macro EMA200 (buffer de entrada)** — el precio debe estar del lado correcto de la EMA200 dentro de `ema_entry_buffer_pct` (10% ATR por defecto). Este buffer es **más estricto** que el buffer de invalidación (`ema_buffer_pct`, 20% ATR) usado en `analyze_open_position`, para dejar margen real entre "entrar" e "invalidarse".
6. **Confirmación multi-timeframe (HTF)** — ver sección 3.
7. **Trigger: retroceso Fibonacci >= 61.8%** dentro de la estructura de swing reciente (pivotes de 3 velas).
8. **Score de confluencia >= `min_confluence_score`** (default 3 de 4) — ver sección 2.

## 2. Score de confluencia (máximo 4 puntos)

| Factor | Condición | Puntos |
|---|---|---|
| Tendencia macro | Precio a favor de EMA200 (dentro del buffer de entrada) | +1 |
| Volumen | Tick Volume > Media Móvil de Volumen (20) | +1 |
| Patrón de vela | Bias de vela (`candlestick_patterns`), Hammer/Shooting Star, o cuerpo >= 50% **en la dirección correcta** | +1 |
| Estocástico | %K <= 35 (sobreventa) o %K cruzando sobre %D en zona <= 50 (BUY) — simétrico para SELL | +1 |

Se requieren **3 de 4** por defecto (`min_confluence_score`).

## 3. Confirmación Multi-Timeframe (HTF)

`_get_htf_trend_alignment()` infiere la temporalidad de las velas recibidas (a partir de sus
timestamps) y elige automáticamente un timeframe superior de confirmación:

| Timeframe de entrada | Timeframe de confirmación |
|---|---|
| M1 / M5 | M15 |
| M15 | H1 |
| M30 / H1 | H4 |
| H4+ | D1 |

Se calcula el cierre y la EMA200 del timeframe superior directamente por MT5 (`mt5.copy_rates_from_pos`).
Si el cierre está sobre su EMA200, se permite BUY (bloquea SELL) y viceversa. El resultado se
**cachea en memoria local por símbolo** (`_HTF_TREND_CACHE`, a nivel de módulo) y se refresca
cada ~¼ de la vela del timeframe superior (mínimo 60s), para no golpear MT5 en cada evaluación.
Si no hay datos suficientes o falla la consulta, el filtro **no bloquea** (fail-open).

## 4. Gestión de posiciones abiertas (`analyze_open_position`)

- **Cierre prematuro por invalidación de EMA200**: si el precio rompe la EMA200 en contra un
  20% del ATR (`ema_buffer_pct`) más allá de la entrada.
- **Cierre preventivo en ganancia**: patrón de vela fuerte contrario + RSI en sobrecompra (>70)
  o sobreventa (<30).
- **Trailing stop**: se activa tras 1x ATR de ganancia, ajustando el SL al mínimo/máximo reciente
  menos/más `max(2.0, atr_sl_mult) * ATR`.
- **Extensión de TP**: en continuación fuerte de tendencia (RSI 50-75/25-50, sin patrón contrario),
  proyecta el TP a extensiones Fibonacci 127.2%/161.8% o al swing previo.

## 5. Reentradas (`evaluate_reentry_signal`, hasta 5 por par)

- **Ruta A (Escalera Fibonacci)**: reentradas en niveles 78.6% → 92% → 100% → 132% → 161.8%,
  exige mejorar el precio de la orden anterior y score >= `min_confluence_score` (de un máximo
  de 3 puntos: tendencia/institucional, volumen, patrón — esta ruta no usa ADX/Estocástico/HTF).
- **Ruta B (Pullback a EMA200)**: pullback dentro del buffer + vela de rechazo/fuerza, con
  anti-spam (mínimo 3 velas o 1.0x ATR desde la última orden).

## 6. Lógica que vive fuera de esta clase

- **Filtro de correlación de Pearson** (`use_correlation_filter`, `correlation_threshold`): se
  evalúa desde `core/bot_worker.py` llamando a `validate_correlation_filter` (definido en
  `base_strategy.py`), no dentro de `forex.py`.
- **Reglas horarias de fin de jornada** (16:00 bloqueo de entradas, 16:15 Break-Even, 16:50
  cierre forzoso): implementadas en `core/risk_manager.py`
  (`get_daily_session_rules`, `is_rollover_or_market_close_window`) y aplicadas desde
  `core/bot_worker.py`.

---

## 7. Configuración de indicadores equivalente para MT5

Para visualizar en un gráfico de MT5 lo mismo que el bot calcula internamente (útil para
verificar visualmente las señales), agrega estos indicadores con estos parámetros exactos:

| Indicador (MT5) | Parámetros | Aplicado a | Para qué se usa en el bot |
|---|---|---|---|
| Moving Average | Período 200, tipo **Exponential** | Close, en el **timeframe de entrada** (el que uses en `symbol_selector.py`) | Tendencia macro (`ema_trend`) |
| Moving Average | Período 200, tipo **Exponential** | Close, en el **timeframe superior** (ver tabla de la sección 3) | Confirmación Multi-Timeframe (HTF) |
| Average True Range (ATR) | Período 14 | — | Volatilidad: SL/TP dinámico, buffers de entrada/invalidación, trailing stop |
| Relative Strength Index (RSI) | Período 14 | Close | Cierre preventivo en ganancia (sobrecompra >70 / sobreventa <30) |
| Average Directional Movement Index (ADX) | Período 14 | — | Filtro de tendencia/lateralidad (umbral 20) |
| Stochastic Oscillator | %K=14, %D=3, Slowing=3 (Low/High, Simple) | — | Confirmación de rebote real en la zona Fibo (score de confluencia) |
| Volumes (Tick Volume) + Moving Average del volumen | MA período 20 sobre el volumen | — | Confirmación de "volumen institucional" en el score |
| Fibonacci Retracement | Niveles 61.8% / 78.6% / 92% / 100% / 132% / 161.8% | Dibujado sobre el último swing high/low | **No es un indicador estándar de MT5**: el bot detecta el swing automáticamente con pivotes de 3 velas (`pivot_window`). Para verlo manualmente, dibuja un Fibonacci retracement entre el último máximo y mínimo relevante del gráfico. |

### Dónde cambiar estos valores en el código

Todos los períodos/umbrales tienen su default en `config.py` (`StrategyConfig`) y pueden
sobreescribirse por instancia vía kwargs al crear la estrategia:

| Parámetro | Default | Campo en `StrategyConfig` |
|---|---|---|
| Período RSI | 14 | `rsi_period` |
| Período ADX | 14 | `adx_period` |
| Umbral ADX (lateral) | 20.0 | `adx_trend_threshold` |
| Buffer de invalidación EMA200 | 20% ATR | `ema_buffer_pct` |
| Buffer de entrada EMA200 | 10% ATR | `ema_entry_buffer_pct` |
| Score mínimo de confluencia | 3 (de 4) | — (parámetro del constructor, no en `StrategyConfig`) |
