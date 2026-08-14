# Resumen de Estrategia y Roadmap de Desarrollo: Bot de Trading Algorítmico

## 1. Perfil del Proyecto y Filosofía de Diseño
* **Arquitectura:** Modular, orientada a objetos (POO), con tipado estricto en Python (`typing`).
* **Conexión & Ejecución:** MetaTrader 5 (MT5 API) en local, desacoplada de peticiones externas bloqueantes para asegurar latencia mínima en milisegundos.
* **Enfoque Cuantitativo:** Reglas deterministas primarias basadas en Acción del Precio y Análisis Técnico + Filtro Secundario de Machine Learning (IA) + Gestión de Riesgo Estricta.

---

## 2. Puntos Clave Acordados

### A. Uso de Librerías vs. Código Puro
* **Decisión:** Se utilizarán librerías consolidadas y altamente optimizadas (`pandas`, `pandas_ta`, `numpy`, `scikit-learn`, `xgboost`).
* **Justificación:** Estas librerías ejecutan rutinas compiladas en C/C++, garantizando cálculos matriciales vectorizados extremadamente rápidos y eficientes. El código propio actuará como el orquestador de lógica de negocio y ejecución.

### B. Acción del Precio Algorítmica (Determinista)
* **Soportes y Resistencias:** Calculados matemáticamente mediante Pivotes (*Pivot Points*), máximos/mínimos locales en ventanas deslizantes (`rolling max/min`), o aglomeración de precios (*clusters*).
* **Estructura de Mercado (BOS / CHoCH):** Identificación automática de rompimientos válidos por cierre de vela sobre el pivote anterior.
* **Líneas de Tendencia y Zonas:** Modeladas con regresiones lineales o cálculo vectorial entre máximos/mínimos relativos.

### C. Sistema de Dos Fases: Generación de Señal + Filtro IA
```
[Velas OHLCV / MT5] 
        │
        ▼
[Fase 1: Motor Determinista (strategy.py)] ──(Señal BUY/SELL)
        │
        ▼
[Fase 2: Filtro Contextual / IA] ────(Evaluación de Riesgo / Confianza)
        │
        ├─► Confianza >= Umbral ──> [Ejecución en MT5 (execution.py)]
        └─► Confianza < Umbral  ──> [CANCELAR / No Operar]
```
1. **Fase 1 (Rápida - Milisegundos):** Reglas técnicas estricta (Acción del precio + Indicadores) emiten la señal base.
2. **Fase 2 (Filtro Decisor):** Un modelo de ML evalúa la calidad del contexto (volatilidad, riesgo de falso rompimiento/trampa, probabilidad de manipulación). Si no supera el umbral, la orden se descarta.

### D. Gestión de Riesgo Dinámica (`risk_manager.py`)
* **Lógica de Lotaje:** Calculado automáticamente según el % de riesgo máximo por operación definido por el usuario y la distancia al Stop Loss.
* **Stop Loss (SL) Inicial:** Definido según estructura técnica (pivote/mínimo/máximo reciente) o múltiplos de ATR.
* **Take Profit (TP) Inicial:** Basado en zonas opuestas de liquidez / estructura anterior con ratio Beneficio/Riesgo mínimo (ej. 1:1.5).
* **Ajustes Dinámicos en Vivo:**
  * **Break-Even (BE):** Tras alcanzar un nivel predefinido (+1 ATR o ratio 1:1), el SL se mueve a precio de entrada.
  * **Cierre Invalidador:** El bot puede cerrar la posición de manera anticipada si la lógica técnica detecta una invalidación o cambio de estructura contrario.

### E. Base de Datos Global Colaborativa (Trading Federado / Crowdsourcing)
* **Operación Desacoplada:** Cada bot opera de forma 100% autónoma en tiempo real usando un modelo `.pkl` local.
* **Telemetría Asíncrona:** Al finalizar un trade, los bots envían las *features*, contexto y resultado a una DB central (ej. Supabase / AWS PostgreSQL).
* **Re-entrenamiento Offline:** Semanalmente, un pipeline offline consume los datos agregados, entrena una versión mejorada del modelo de IA y distribuye el archivo `.pkl` actualizado a todos los bots.

---

## 3. Roadmap de Implementación Paso a Paso

### 📍 Paso 1: Motor Técnico Determinista (`strategy.py`)
- [ ] Definir la estructura de detección de Pivotes (High/Low pivotes).
- [ ] Implementar la detección matemática de Soportes y Resistencias.
- [ ] Incorporar confirmación de estructura (Rompimientos / BOS).
- [ ] Integrar filtro de volatilidad/tendencia con `pandas_ta` (ATR, SMA/EMA, RSI).

### 📍 Paso 2: Módulo de Gestión de Riesgo y Posicionamiento (`risk_manager.py`)
- [ ] Implementar función de cálculo de lotaje exacto según % de balance y distancia SL.
- [ ] Programar lógica de asignación inicial de SL y TP basados en pivotes/ATR.
- [ ] Desarrollar lógica de seguimiento: Break-Even y Trailing Stop.
- [ ] Definir validaciones pre-orden (Drawdown máximo, margen libre, spread máximo).

### 📍 Paso 3: Módulo de Ejecución y Control de Órdenes (`execution.py`)
- [ ] Crear wrappers para envío de órdenes `BUY`/`SELL` en MT5.
- [ ] Implementar modificación dinámica de SL/TP en MT5 (`order_send` para `TRADE_ACTION_SLTP`).
- [ ] Programar cierre anticipado de posiciones por invalidación.

### 📍 Paso 4: Backtesting y Validación Estadística (`backtester.py`)
- [ ] Probar la estrategia determinista sobre >1000 velas históricas en diferentes pares.
- [ ] Evaluar métricas clave: Esperanza Matemática ($E$), Profit Factor, Max Drawdown, Win Rate real.

### 📍 Paso 5: Módulo de IA / Filtro Contextual (Fase 2)
- [ ] Extracción y preparación de las 14 *features* técnicas y estructurales.
- [ ] Entrenamiento offline del clasificador (XGBoost / Random Forest).
- [ ] Integración del modelo `.pkl` en el flujo de decisión del bot.

### 📍 Paso 6: Telemetría y Base de Datos Global
- [ ] Diseñar esquema de base de datos para registrar trades y *features*.
- [ ] Crear cliente de envío asíncrono post-trade.
- [ ] Configurar pipeline de entrenamiento periódico offline.
