# SimpleTrendStrategy — Documentación y Plan de Pruebas

## 1. Por qué existe

`ForexStrategy` combina ~10 indicadores/filtros simultáneos (EMA200, ATR, RSI, ADX, Estocástico,
6 niveles de Fibonacci, MA de volumen, ~30 patrones de vela, confirmación multi-timeframe, filtro
de correlación, filtro de horario). La literatura de trading algorítmico es consistente en que
más de ~3 indicadores por estrategia aumenta significativamente el riesgo de sobreajuste
(curve-fitting): ajustarse al ruido histórico en vez de a un patrón real y repetible.

`SimpleTrendStrategy` (`core/strategies/simple_trend.py`) es el experimento de control: la misma
idea central (operar a favor de la tendencia, con un oscilador confirmando el punto de entrada)
reducida a **2 indicadores de señal** (EMA de tendencia + RSI) más ATR solo para dimensionar
SL/TP (gestión de riesgo, no generación de señal). Sin Fibonacci, sin patrones de vela, sin ADX,
sin confirmación multi-timeframe, sin reentradas.

No reemplaza a `ForexStrategy` — se registra aparte y se selecciona desde el mismo dropdown
"Estrategia" de la GUI (`core/strategies/__init__.py` la descubre automáticamente).

## 2. Lógica

- **Tendencia**: EMA de 100 períodos. El precio debe estar sobre la EMA (alcista) o bajo la EMA
  (bajista), con un pequeño buffer de tolerancia (`EMA_ENTRY_BUFFER_ATR_MULT`) para no perder
  entradas en el límite por un margen mínimo.
- **Entrada**: `BUY` cuando el RSI **cruza de vuelta** el nivel de sobreventa (antes <= umbral,
  ahora > umbral) estando en tendencia alcista. Simétrico para `SELL` (cruce de vuelta desde
  sobrecompra, en tendencia bajista). Es un cruce CONFIRMADO, no "tocar" el nivel — evita
  depender de acertar la vela exacta del piso/techo del RSI, que casi nunca ocurre porque el
  RSI suele saltar del umbral hacia afuera en una sola vela.
- **Salida**: cierre por invalidación si el precio cruza la EMA en contra de la posición (con un
  buffer más ancho que el de entrada, para no cerrar por una fluctuación menor justo después de
  entrar cerca de la EMA), más trailing stop simple por ATR. Sin cierre preventivo por patrones
  ni extensión de TP por Fibonacci.
- **SL/TP**: ATR × multiplicador (mismo esquema que `ForexStrategy`, R:R por defecto 1:2).

## 2.1 Parámetros ajustables

Todos viven como constantes al inicio de `core/strategies/simple_trend.py`, con su propio
comentario explicando qué controla cada uno y el efecto de subirlo/bajarlo. Resumen:

| Parámetro | Default | Qué controla |
|---|---|---|
| `EMA_PERIOD` | 100 | Período de la EMA de tendencia. Más corto = más reactivo, más señales falsas. Más largo = tendencia más "macro", más lenta a cambiar. |
| `EMA_ENTRY_BUFFER_ATR_MULT` | 0.15 | Tolerancia (en múltiplos del ATR actual) para considerar "tendencia" aunque el precio esté ligeramente del otro lado de la EMA. `0.0` = cruce estricto. |
| `EMA_INVALIDATION_BUFFER_ATR_MULT` | 0.30 | Igual que el anterior pero para el cierre por invalidación de una posición abierta — deliberadamente más ancho que el de entrada, para no auto-invalidarse por la misma fluctuación menor que permitió la entrada. |
| `RSI_PERIOD` | 9 | Período del RSI. Más corto = más reactivo, cruza los niveles con más frecuencia (más señales, algo más ruidosas). |
| `RSI_OVERSOLD` / `RSI_OVERBOUGHT` | 40.0 / 60.0 | Niveles donde se considera sobreventa/sobrecompra. Más cerca de 50 = más señales pero de retrocesos más superficiales. |
| `ATR_PERIOD` | 14 | Período del ATR (solo gestión de riesgo, no genera señal). |
| `ATR_SL_MULT` / `ATR_TP_MULT` | 1.5 / 3.0 | Distancia de SL/TP en múltiplos del ATR (R:R resultante 1:2 por defecto). |
| `STATIC_SL_PIPS` / `STATIC_TP_PIPS` | 20.0 / 40.0 | Respaldo en pips si el ATR no está disponible. |
| `SR_LOOKBACK` | 50 | Ventana de velas para soporte/resistencia informativos (no afecta la señal). |

Se pueden sobreescribir por instancia sin tocar el archivo, ej.:
`create_strategy_instance("simple_trend", rsi_period=7, ema_entry_buffer_atr_mult=0.20)`.

## 2.2 Configuración de indicadores equivalente para MT5

Para visualizar en un gráfico de MT5 lo mismo que la estrategia calcula internamente:

| Indicador (MT5) | Parámetros | Aplicado a | Para qué se usa |
|---|---|---|---|
| Moving Average | Período 100, tipo **Exponential** | Close | Tendencia (`ema_trend`) |
| Relative Strength Index (RSI) | Período 9 | Close | Disparo de entrada (cruce de vuelta desde 40/60) |
| Average True Range (ATR) | Período 14 | — | SL/TP dinámico y buffers de EMA (entrada/invalidación) |

No hace falta agregar nada para soporte/resistencia — son solo el máximo/mínimo de las últimas
50 velas (`SR_LOOKBACK`), se pueden aproximar visualmente con un indicador de Canal de Donchian
de 50 períodos si se quiere referencia visual exacta.

## 3. Plan de pruebas (comparación real, no teórica)

### Fase 0 — Preparación
1. Confirmar que se sigue en cuenta **DEMO**.
2. Fijar el universo de símbolos para AMBAS fases: los 3 mejores por histórico real ya
   identificados (**GBPUSD, USDJPY, CADJPY**) — mismo universo en las dos fases para no mezclar
   "mejoró por cambiar de par" con "mejoró por cambiar de estrategia".
3. Registrar balance inicial y fecha/hora exacta de inicio de cada fase.
4. Nota: la arquitectura actual solo permite **una estrategia activa a la vez** para todos los
   símbolos (dropdown único en el Topbar) — por eso el plan es secuencial, no paralelo. Si más
   adelante quieres una comparación paralela (dos instancias del bot corriendo simultáneamente
   con la misma condición de mercado), se puede evaluar agregar soporte para apuntar cada
   instancia a un `config.json` distinto — no está implementado todavía.

### Fase 1 — Baseline: ForexStrategy (ya con los fixes de esta sesión)
- Correr con los 3 símbolos fijados hasta acumular **mínimo 30 operaciones cerradas** (no un
  número fijo de días — con menos de ~20 operaciones el intervalo de Wilson que ya usamos en
  "Mejores Pares" muestra que casi cualquier resultado es ruido estadístico).
- Registrar al final: win rate, win rate ajustado (Wilson), R promedio (expectancy), USD neto,
  motivo de salida más frecuente.

### Fase 2 — SimpleTrendStrategy
- Cambiar la estrategia en el dropdown del Topbar a `simple_trend`.
- Mismos 3 símbolos, mismo tamaño de cuenta/riesgo por operación.
- Mismo criterio de corte: mínimo 30 operaciones cerradas.
- Mismas métricas registradas.

### Fase 3 — Comparación
Usar la función ya construida para esto (agrupa automáticamente por `context.strategy`, que
cada estrategia ya guarda sola en cada trade):

```python
from core.stats_calculator import rank_strategies_by_performance
for row in rank_strategies_by_performance(min_trades=30):
    print(row)
```

Devuelve por estrategia: `trades`, `win_rate`, `win_rate_confidence` (ajustado por Wilson, para
no confiar en muestras chicas), `avg_r` (expectancy real) y `total_usd`.

### Criterio de decisión
- Si `simple_trend` tiene **R promedio y win rate ajustado claramente superiores** con muestra
  suficiente (>=30 trades cada una) → la hipótesis de sobreajuste se confirma; seguir
  simplificando `ForexStrategy` en esa dirección en vez de seguir agregando filtros.
- Si son **estadísticamente indistinguibles** (dentro del margen de Wilson) → la complejidad de
  `ForexStrategy` no está agregando valor neto. Preferir igual la más simple: menos superficie de
  bugs, más fácil de mantener y diagnosticar (ya vimos en esta sesión lo costoso que es depurar
  10 filtros interactuando entre sí).
- Si `ForexStrategy` es claramente mejor → el problema original no era "demasiados indicadores"
  sino algo más específico (hay que revisar de nuevo el diagnóstico: ejecución, costos de spread,
  timeframe, etc., no la cantidad de indicadores en sí).
