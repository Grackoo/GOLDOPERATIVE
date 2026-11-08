# AUREUS-SMC Motor Algorítmico Institucional de Oro (XAU/USD)

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![Arquitectura](https://img.shields.io/badge/arquitectura-Event--Driven-gold.svg)
![Base de Datos](https://img.shields.io/badge/sqlite-Modo%20WAL-green.svg)
![Dashboard](https://img.shields.io/badge/dashboard-FastAPI%20%7C%20TradingView%20v4-cyan.svg)
![Latencia](https://img.shields.io/badge/latencia-%3C5ms%20Equinix%20NY4-red.svg)

**AUREUS-SMC** es un sistema de trading cuantitativo institucional de eventos de alta concurrencia programado en **Python 3.11+** para el CFD de **Oro (XAU/USD)**. Automatiza la estrategia de **Barrido de Liquidez de la Sesión de Londres y Desplazamiento en la Apertura de Nueva York** bajo conceptos institucionales (Smart Money Concepts - SMC) durante la ventana operativa (08:00 AM – 10:30 AM EST/EDT) con soporte dinámico para horario de verano (Daylight Saving Time - DST).

---

## 🏛️ Arquitectura Modular del Sistema

El sistema implementa una arquitectura desacoplada basada en el patrón **Event Bus / Observador**:

```
GOLDOPERATIVE/
├── config.py                 # Configuración tipada con Pydantic Settings
├── .env.example              # Plantilla estandarizada de variables de entorno
├── requirements.txt          # Dependencias fijadas del proyecto
├── iniciar_sistema.bat       # Lanzador en 1 clic para Windows (abre el dashboard)
├── probar_sandbox.bat        # Ejecutor en 1 clic del simulador de prueba
├── core/
│   ├── models.py             # Modelos de datos: Tick, Bar, FVG, Order, Position, TradeRecord
│   ├── events.py             # Eventos tipados del Event Bus
│   ├── event_bus.py          # Bus de eventos asíncrono desacoplado
│   ├── state_machine.py      # Máquina de estados con transiciones determinísticas
│   └── time_manager.py       # Gestor horario (America/New_York) con soporte dinámico DST
├── data/
│   ├── ring_buffer.py        # Buffers circulares O(1) para ticks y velas
│   ├── bar_aggregator.py     # Agregador de velas en tiempo real M1 y M5
│   └── feed_manager.py       # Normalización de ticks y feeds de correlación DXY / US10Y
├── strategy/
│   ├── london_range.py       # Rango de Londres (03:00 - 08:00 EST): High/Low BSL/SSL
│   ├── liquidity_sweep.py    # Detección de barrido de liquidez con rechazo inmediato
│   ├── displacement.py       # Quiebre de estructura (MSS / CHOCH) validado con ATR > 1.5
│   ├── fvg_detector.py       # Detección de FVG y Consequent Encroachment (50% CE)
│   ├── fractals.py           # Swings fractales Williams
│   ├── indicators.py         # Indicador ATR(14) de alta velocidad
│   └── smc_engine.py         # Orquestador del ciclo completo SMC
├── risk/
│   ├── position_sizer.py     # Dimensionamiento matemático de lotes por capital
│   ├── spread_filter.py      # Filtro de microestructura (límite máx. spread $0.30)
│   ├── circuit_breaker.py    # Circuit Breakers: Máx 2 operaciones y Hard Stop 2% Drawdown
│   └── order_manager.py      # Gestión activa: Break-Even a 1:1.5 RRR y cierre parcial 50% a 1:2.0 RRR
├── execution/
│   ├── base_broker.py        # Interfaz abstracta BaseBrokerClient
│   ├── paper_broker.py       # Simulador institucional (latencia 10-35ms y deslizamiento estocástico)
│   ├── mt5_broker.py         # Adaptador oficial para MetaTrader 5
│   └── oanda_broker.py       # Adaptador asíncrono para OANDA v20 REST y Streaming
├── storage/
│   ├── db.py                 # Conexión SQLite asíncrona en modo WAL
│   ├── repository.py         # Persistencia de trades y rehidratación automática de estado
│   └── metrics_calc.py       # Cálculo de métricas: Win Rate, Profit Factor, Sharpe Ratio
├── macro/
│   ├── news_calendar.py      # Extracción de calendario económico (ForexFactory / Investing)
│   └── news_filter.py        # Bloqueo de entradas 15m antes y 15m después de noticias rojas
├── web/
│   ├── server.py             # Servidor FastAPI y WebSocket hub
│   └── static/
│       ├── index.html        # Frontend interactivo para trading desk
│       ├── css/style.css     # Estilos Dark institucionales
│       └── js/app.js         # Cliente WebSocket y renderizado TradingView Lightweight Charts v4
├── scripts/
│   ├── run_sandbox.py        # Replay y validación completa de las 7 fases de la estrategia
│   └── run_live.py           # Lanzador del sistema en vivo con servidor web
└── deployment/
    ├── Dockerfile            # Imagen de producción Docker
    ├── docker-compose.yml    # Orquestación de contenedores
    ├── aureus-trading.service# Servicio systemd para Linux VPS
    ├── deploy_ny4.sh         # Script de despliegue automatizado para Equinix NY4
    └── GUIA_DESPLIEGUE_NY4.md# Guía completa de optimización de kernel y red
```

---

## ⚡ Especificación de la Estrategia SMC (XAU/USD)

1. **Rango de Londres (03:00 AM - 08:00 AM EST):** Identificación automática del Máximo (Buy-Side Liquidity) y Mínimo (Sell-Side Liquidity).
2. **Barrido de Liquidez en la Apertura de NY (08:00 AM - 10:30 AM EST):** Penetración con mecha fuera del rango de Londres en M5/M1 con rechazo inmediato (cierre de vela nuevamente dentro del rango).
3. **Desplazamiento y Market Structure Shift (MSS / CHOCH):** Quiebre de estructura con vela de rango amplio calificada mediante ATR ($\text{Cuerpo} > 1.5 \times \text{ATR}(14)$).
4. **Fair Value Gap (FVG):** Localización de desequilibrio de 3 velas. Entrada al toque del 50% del FVG (Consequent Encroachment) o al borde.
5. **Filtro de Noticias:** Bloqueo automático de entradas desde 15 minutos antes hasta 15 minutos después de noticias de alto impacto en USD (NFP, CPI, FOMC).

---

## 📐 Motor de Riesgo Matemático y Gestión Activa

### Ecuación de Dimensionamiento:
$$\text{Lotes} = \frac{\text{Balance} \times (\% \text{Riesgo} / 100)}{\text{Distancia\_SL}_{\$} \times \text{Contract Size}}$$
- 1 Lote estándar = **100 onzas troy**.
- Tick size = **$0.01**.
- Ejemplo: Balance de $100,000 con 1.0% de riesgo ($1,000) y SL de $7.60:
  $$\text{Lotes} = \frac{1000}{7.60 \times 100} = 1.31\text{ lotes}$$

### Gestión Dinámica:
- **Take Profit inicial:** Mínimo **1:3.0 RRR**.
- **A 1:1.5 RRR:** Desplazamiento automático del Stop Loss a **Break-Even + $0.10** (cubre comisiones y spread).
- **A 1:2.0 RRR:** Cierre parcial del **50% del volumen**, permitiendo al remanente buscar el 1:3 RRR protegido.
- **Circuit Breakers:** Máximo 2 operaciones por sesión matutina y Hard Stop por Drawdown diario del 2%.

---

## 🚀 Puesta en Marcha Rápida (Local)

### 1. Probar la Simulación Sandbox en 1 Clic
Haga doble clic en `probar_sandbox.bat` o ejecute:
```powershell
.venv\Scripts\python.exe scripts\run_sandbox.py
```

### 2. Iniciar el Sistema en Vivo y Dashboard
Haga doble clic en `iniciar_sistema.bat` o ejecute:
```powershell
.venv\Scripts\python.exe scripts\run_live.py
```
El panel web se abrirá automáticamente en:
```
http://localhost:8000
```

---

## 🌐 Despliegue en VPS Linux (Equinix NY4)

Para desplegar en Ubuntu 22.04 / 24.04 LTS en Equinix NY4 (Secaucus, NJ) con latencia < 5ms:

```bash
chmod +x deployment/deploy_ny4.sh
sudo ./deployment/deploy_ny4.sh
```

Consulte [GUIA_DESPLIEGUE_NY4.md](deployment/GUIA_DESPLIEGUE_NY4.md) para más detalles.
