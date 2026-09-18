import os
import sys
import json
import time
import asyncio
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Añadir raíz al sys.path para importar core
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
CONFIG_FILE = ROOT_DIR / "config.json"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Intentar importar MetaTrader5 con salvaguarda para Windows / Linux
MT5_AVAILABLE = False
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

try:
    from core.config_manager import load_config, save_config, DEFAULT_CONFIG
    from core.ai_strategy_changelog import load_all_changelogs
    from core.ai_backtest_learner import train_ai_batch_from_backtest
    from core.ai_advisor import test_ai_connection, fetch_available_models, PROVIDER_PRESETS
except ImportError as e:
    print(f"⚠️ [API] Import error: {e}")

app = FastAPI(title="Trading Bot API & WebSocket Engine", version="1.1.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Conexiones WebSocket activas
active_websockets: List[WebSocket] = []

class ConfigSaveRequest(BaseModel):
    login: Optional[int] = 0
    password: Optional[str] = ""
    server: Optional[str] = ""
    path: Optional[str] = ""
    symbol_suffix: Optional[str] = ""
    magic_number: Optional[int] = 999111
    max_slippage: Optional[int] = 10
    max_reentries: Optional[int] = 0
    selected_strategy: Optional[str] = "ai_strategy"
    ai_enabled: Optional[bool] = True
    ai_provider: Optional[str] = "Google Gemini"
    ai_api_key: Optional[str] = ""
    ai_model: Optional[str] = "gemini-3.6-flash"
    ai_base_url: Optional[str] = ""
    ai_thinking_enabled: Optional[bool] = False
    ai_thinking_budget: Optional[int] = 128
    active_symbols: Optional[List[str]] = []
    connect_mt5: Optional[bool] = False

class TestMT5Request(BaseModel):
    login: Optional[int] = 0
    password: Optional[str] = ""
    server: Optional[str] = ""
    path: Optional[str] = ""

class TestAIRequest(BaseModel):
    provider: Optional[str] = "Google Gemini"
    api_key: Optional[str] = ""
    model_name: Optional[str] = "gemini-3.6-flash"
    base_url: Optional[str] = ""

class FetchModelsRequest(BaseModel):
    provider: str
    api_key: Optional[str] = ""
    base_url: Optional[str] = ""

class LearnRequest(BaseModel):
    items: List[Dict[str, Any]]
    default_strategy: Optional[str] = "ai_strategy"
    api_key: Optional[str] = None
    model_name: Optional[str] = None

class MountSymbolsRequest(BaseModel):
    symbols: List[str]

# ---------------------------------------------------------
# Utilidades MT5: Verificación y Lanzamiento Automático
# ---------------------------------------------------------
def check_mt5_running_process(exe_name: str = "terminal64.exe") -> bool:
    """Verifica si el proceso terminal64.exe está en ejecución en el sistema."""
    if os.name != "nt":
        return False
    try:
        output = subprocess.check_output("tasklist", shell=True).decode("utf-8", errors="ignore")
        return exe_name.lower() in output.lower()
    except Exception:
        return False

def check_and_launch_mt5() -> Dict[str, Any]:
    """
    Verifica si MT5 está conectado; si no está abierto, intenta abrirlo
    utilizando la ruta de config.json y luego autenticarse.
    """
    if not MT5_AVAILABLE or mt5 is None:
        return {
            "connected": False,
            "terminal_running": False,
            "platform_supported": False,
            "message": "Librería MetaTrader5 solo disponible en Windows con terminal MT5 instalada."
        }

    # 1. Verificar si ya hay conexión activa y válida
    try:
        terminal_info = mt5.terminal_info()
        if terminal_info is not None and terminal_info.connected:
            acc = mt5.account_info()
            return {
                "connected": True,
                "terminal_running": True,
                "platform_supported": True,
                "message": "MT5 conectado y en línea.",
                "account": {
                    "login": acc.login if acc else 0,
                    "server": acc.server if acc else "",
                    "balance": acc.balance if acc else 0.0,
                    "equity": acc.equity if acc else 0.0,
                    "margin": acc.margin if acc else 0.0,
                    "freeMargin": acc.margin_free if acc else 0.0,
                    "profit": acc.profit if acc else 0.0,
                    "currency": acc.currency if acc else "USD",
                    "connected": True
                }
            }
    except Exception:
        pass

    # 2. Intentar inicializar y abrir MT5 usando core.connector.initialize_mt5
    try:
        from core.connector import initialize_mt5
        ok = initialize_mt5()
        if ok:
            acc = mt5.account_info()
            return {
                "connected": True,
                "terminal_running": True,
                "platform_supported": True,
                "message": "✅ MT5 iniciado y conectado exitosamente.",
                "account": {
                    "login": acc.login if acc else 0,
                    "server": acc.server if acc else "",
                    "balance": acc.balance if acc else 0.0,
                    "equity": acc.equity if acc else 0.0,
                    "margin": acc.margin if acc else 0.0,
                    "freeMargin": acc.margin_free if acc else 0.0,
                    "profit": acc.profit if acc else 0.0,
                    "currency": acc.currency if acc else "USD",
                    "connected": True
                }
            }
    except Exception as e:
        print(f"❌ [MT5] Error en initialize_mt5: {e}")

    err = mt5.last_error() if hasattr(mt5, "last_error") else "Desconocido"
    return {
        "connected": False,
        "terminal_running": check_mt5_running_process(),
        "platform_supported": True,
        "message": f"No se pudo conectar a MT5: {err}. Verifique la ruta de terminal64.exe y credenciales."
    }

@app.on_event("startup")
def startup_event():
    """Al iniciar el backend en Python, verifica e intenta abrir y conectar automáticamente MT5."""
    def _auto_start():
        time.sleep(1.0)
        try:
            print("🚀 [STARTUP] Inicializando conexión y apertura automática de MetaTrader 5...")
            from core.connector import initialize_mt5
            ok = initialize_mt5()
            if ok:
                print("✅ [STARTUP] MetaTrader 5 inicializado y conectado exitosamente.")
            else:
                print("ℹ️ [STARTUP] MetaTrader 5 en espera (revise credenciales o ruta en Configuración).")
        except Exception as e:
            print(f"⚠️ [STARTUP] Excepción al iniciar MT5: {e}")

    threading.Thread(target=_auto_start, daemon=True).start()

# ---------------------------------------------------------
# WebSocket Manager
# ---------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        await websocket.send_json({
            "type": "SYSTEM_LOG",
            "log": {
                "id": f"log-{int(time.time()*1000)}",
                "timestamp": time.strftime("%H:%M:%S"),
                "level": "SUCCESS",
                "message": "Conectado al motor Python de Trading Bot en tiempo real."
            }
        })
        while True:
            data = await websocket.receive_text()
            # Posible recepción de comandos por WebSocket
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)
    except Exception:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

async def broadcast_log(level: str, message: str):
    log_obj = {
        "id": f"log-{int(time.time()*1000)}",
        "timestamp": time.strftime("%H:%M:%S"),
        "level": level,
        "message": message
    }
    dead_sockets = []
    for ws in active_websockets:
        try:
            await ws.send_json({"type": "SYSTEM_LOG", "log": log_obj})
        except Exception:
            dead_sockets.append(ws)
    for ws in dead_sockets:
        if ws in active_websockets:
            active_websockets.remove(ws)

# ---------------------------------------------------------
# Endpoints de Configuración y Arranque
# ---------------------------------------------------------
@app.get("/api/config")
def get_config_endpoint():
    """
    Verifica si config.json existe físicamente y si contiene credenciales válidas.
    Si no existe o no está configurado, el frontend debe mostrar ConfigWindow.
    """
    exists = CONFIG_FILE.exists()
    cfg = {}
    if exists:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"Error leyendo config.json: {e}")
            exists = False

    login = cfg.get("login", 0)
    server = cfg.get("server", "")
    password = cfg.get("password", "")

    # Se considera configurado si existe el archivo y tiene login (>0) y servidor definidos
    try:
        login_int = int(login or 0)
    except (ValueError, TypeError):
        login_int = 0

    is_configured = exists and (login_int > 0) and bool(str(server).strip())

    return {
        "exists": exists,
        "is_configured": is_configured,
        "config": cfg if exists else DEFAULT_CONFIG
    }

@app.post("/api/config")
def save_config_endpoint(req: ConfigSaveRequest):
    """Guarda la configuración en config.json y opcionalmente inicia/conecta MT5."""
    try:
        # Cargar configuración existente o por defecto
        current_cfg = {}
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    current_cfg = json.load(f)
            except Exception:
                current_cfg = DEFAULT_CONFIG.copy()
        else:
            current_cfg = DEFAULT_CONFIG.copy()

        # Actualizar campos
        current_cfg["login"] = req.login
        current_cfg["password"] = req.password
        current_cfg["server"] = req.server
        current_cfg["path"] = req.path
        current_cfg["symbol_suffix"] = req.symbol_suffix
        current_cfg["magic_number"] = req.magic_number
        current_cfg["max_slippage"] = req.max_slippage
        current_cfg["max_reentries"] = req.max_reentries
        current_cfg["selected_strategy"] = req.selected_strategy
        current_cfg["ai_enabled"] = req.ai_enabled
        current_cfg["ai_provider"] = req.ai_provider
        current_cfg["ai_api_key"] = req.ai_api_key
        current_cfg["ai_model"] = req.ai_model
        current_cfg["ai_base_url"] = req.ai_base_url
        current_cfg["ai_thinking_enabled"] = req.ai_thinking_enabled
        current_cfg["ai_thinking_budget"] = req.ai_thinking_budget
        if req.active_symbols:
            current_cfg["active_symbols"] = req.active_symbols
            current_cfg["symbols"] = req.active_symbols

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current_cfg, f, indent=4, ensure_ascii=False)

        mt5_status = None
        if req.connect_mt5:
            mt5_status = check_and_launch_mt5()

        return {
            "success": True,
            "message": "Configuración guardada exitosamente.",
            "mt5_status": mt5_status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando configuración: {e}")

@app.post("/api/mt5/test-connection")
def test_mt5_connection_endpoint(req: TestMT5Request):
    """Prueba la conexión y abre la terminal MT5 con las credenciales indicadas."""
    if not req.login or req.login <= 0:
        return {"success": False, "message": "❌ Debe ingresar un ID de Cuenta (Login) numérico válido."}
    if not req.password:
        return {"success": False, "message": "❌ Debe ingresar la contraseña de su cuenta MT5."}
    if not req.server:
        return {"success": False, "message": "❌ Debe ingresar el Servidor del Bróker (ej: Weltrade-Demo)."}

    if not MT5_AVAILABLE or mt5 is None:
        return {
            "success": False,
            "message": "⚠️ MetaTrader 5 no está disponible directamente en este contenedor Linux (requiere Windows con terminal MT5 instalada). En tu entorno local de Windows funcionará directamente."
        }

    try:
        from core.connector import initialize_mt5
        cfg = load_config()
        path = req.path or cfg.get("path", "")
        
        ok = initialize_mt5(path=path, login=req.login, password=req.password, server=req.server)
        if ok:
            acc_info = mt5.account_info()
            broker = acc_info.company if acc_info else req.server
            return {
                "success": True,
                "message": f"✅ MT5 Conectado exitosamente | Bróker: {broker}",
                "broker": broker,
                "account": {
                    "login": acc_info.login if acc_info else req.login,
                    "server": acc_info.server if acc_info else req.server,
                    "balance": acc_info.balance if acc_info else 0.0,
                    "equity": acc_info.equity if acc_info else 0.0,
                    "freeMargin": acc_info.margin_free if acc_info else 0.0
                }
            }
        else:
            err = mt5.last_error() if hasattr(mt5, "last_error") else "Fallo al inicializar o conectar"
            return {"success": False, "message": f"❌ Error al conectar con MT5: {err}"}
    except Exception as e:
        return {"success": False, "message": f"❌ Excepción al probar MT5: {str(e)}"}

@app.get("/api/ai/presets")
def get_ai_presets_endpoint():
    """Devuelve los presets y modelos por defecto para cada proveedor de IA."""
    try:
        from core.ai_advisor import PROVIDER_PRESETS
        return {"success": True, "presets": PROVIDER_PRESETS}
    except Exception as e:
        return {"success": False, "error": str(e), "presets": {}}

@app.post("/api/ai/fetch-models")
def fetch_ai_models_endpoint(req: FetchModelsRequest):
    """Consulta dinámicamente la lista de modelos desde la API del proveedor (Ollama, Gemini, OpenAI, etc.)."""
    try:
        from core.ai_advisor import fetch_available_models
        ok, models, msg = fetch_available_models(
            provider=req.provider,
            api_key=req.api_key or "",
            base_url=req.base_url or ""
        )
        return {"success": ok, "models": models, "message": msg}
    except Exception as e:
        return {"success": False, "models": [], "message": f"❌ Error consultando modelos: {str(e)}"}

@app.post("/api/ai/test-connection")
def test_ai_connection_endpoint(req: TestAIRequest):
    """Prueba la conexión y API Key con el proveedor o modelo de IA (Gemini, Ollama, OpenAI, etc.)."""
    try:
        from core.ai_advisor import test_ai_connection
        success, msg = test_ai_connection(
            api_key=req.api_key or "",
            model_name=req.model_name or "gemini-3.6-flash",
            base_url=req.base_url or ""
        )
        return {"success": success, "message": msg}
    except Exception as e:
        return {"success": False, "message": f"❌ Error probando IA: {str(e)}"}

@app.get("/api/mt5/status")
def get_mt5_status_endpoint():
    """Verifica si MT5 está activo o intenta abrirlo."""
    return check_and_launch_mt5()

@app.post("/api/mt5/launch")
def launch_mt5_endpoint():
    """Fuerza la apertura y reconexión con MetaTrader 5."""
    return check_and_launch_mt5()

@app.get("/api/status")
def get_bot_status():
    """Devuelve estado de cuenta, MT5 y del bot."""
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    # Intentar obtener estado de MT5 en vivo
    mt5_stat = check_and_launch_mt5()

    account = {
        "connected": mt5_stat.get("connected", False),
        "balance": 10000.0,
        "equity": 10000.0,
        "margin": 0.0,
        "freeMargin": 10000.0,
        "profit": 0.0,
        "currency": "USD",
        "server": cfg.get("server", "Weltrade-Demo"),
        "login": str(cfg.get("login", "43154893"))
    }

    if mt5_stat.get("connected") and "account" in mt5_stat:
        account.update(mt5_stat["account"])

    trade_memory = {}
    tm_path = ROOT_DIR / "trade_memory.json"
    if tm_path.exists():
        try:
            with open(tm_path, "r", encoding="utf-8") as f:
                trade_memory = json.load(f)
        except Exception:
            pass

    active_pairs = cfg.get("active_symbols") or cfg.get("symbols") or [
        "AUDJPY_r", "USDCAD_r", "GEREUR_r", "EURJPY_r", "GBPUSD_r"
    ]

    return {
        "account": account,
        "mt5": mt5_stat,
        "bot": {
            "isRunning": False,
            "activePairs": active_pairs,
            "currentStrategy": cfg.get("selected_strategy", "ai_strategy"),
            "mode": "DEMO" if "demo" in str(cfg.get("server", "")).lower() else "LIVE",
            "uptimeSeconds": 0
        },
        "trades_count": len(trade_memory)
    }

@app.get("/api/changelog")
def get_changelog(symbol: Optional[str] = None):
    """Devuelve el registro histórico del MR Changelog de AI Strategy."""
    try:
        logs = load_all_changelogs()
        if symbol:
            logs = [e for e in logs if e.get("symbol", "").upper() == symbol.upper()]
        return {"success": True, "count": len(logs), "changelog": logs}
    except Exception as e:
        return {"success": False, "error": str(e), "changelog": []}

@app.get("/api/deep-search/results")
def get_deep_search_results():
    """Devuelve los últimos resultados calculados en backtest_results.json."""
    bt_path = ROOT_DIR / "backtest_results.json"
    if not bt_path.exists():
        return {"success": True, "results": []}
    try:
        with open(bt_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            results = data if isinstance(data, list) else data.get("results", [])
            return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e), "results": []}

@app.post("/api/ai/learn")
def execute_ai_learning(req: LearnRequest):
    """Ejecuta el aprendizaje de patrones y genera el MR Changelog para los pares enviados."""
    if not req.items:
        raise HTTPException(status_code=400, detail="No se suministraron pares para el aprendizaje.")

    cfg = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    api_key = req.api_key or cfg.get("ai_api_key") or os.environ.get("GEMINI_API_KEY", "")
    model_name = req.model_name or cfg.get("ai_model", "gemini-3.6-flash")

    try:
        learned = train_ai_batch_from_backtest(
            items=req.items,
            default_strategy=req.default_strategy or cfg.get("selected_strategy", "ai_strategy"),
            api_key=api_key,
            model_name=model_name
        )
        return {
            "success": True,
            "count": len(learned),
            "results": learned
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error durante el aprendizaje de IA: {e}")

@app.get("/api/symbols")
def get_symbols_catalog():
    """Devuelve el catálogo de símbolos activos, disponibles y sus sugerencias cuantitativas."""
    try:
        cfg = {}
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)

        bt_path = ROOT_DIR / "backtest_results.json"
        bt_records = []
        if bt_path.exists():
            with open(bt_path, "r", encoding="utf-8") as f:
                raw_bt = json.load(f)
                bt_records = raw_bt if isinstance(raw_bt, list) else list(raw_bt.values())

        available = cfg.get("available_symbols", [
            "AUDUSD_r", "EURCHF_r", "EURGBP_r", "EURJPY_r", "EURUSD_r",
            "GBPCHF_r", "GBPJPY_r", "GBPUSD_r", "NZDUSD_r", "USDCAD_r",
            "USDCHF_r", "USDJPY_r", "AUDCAD_r", "AUDCHF_r", "AUDJPY_r"
        ])
        active = cfg.get("active_symbols", cfg.get("symbols", ["AUDJPY_r", "USDCAD_r", "GEREUR_r", "EURJPY_r", "GBPUSD_r"]))

        metadata = {}
        tf_map = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 16385: "H1", 16388: "H4", 16408: "D1"}

        for sym in available:
            base_sym = sym.replace("_r", "").lower()
            matches = [
                r for r in bt_records
                if not r.get("cancelled") and not r.get("error") and (
                    base_sym in str(r.get("symbol", "")).lower() or
                    str(r.get("symbol", "")).lower() in base_sym
                )
            ]

            best_sugg = None
            if matches:
                valid = [m for m in matches if m.get("trades", 0) >= 1]
                if valid:
                    valid.sort(key=lambda x: x.get("avg_r", 0), reverse=True)
                    top = valid[0]
                    best_sugg = {
                        "timeframe_str": tf_map.get(top.get("timeframe"), "M15"),
                        "timeframe_val": top.get("timeframe", 15),
                        "avg_r": top.get("avg_r", 0),
                        "win_rate": top.get("win_rate", 0),
                        "win_rate_confidence": top.get("win_rate_confidence", 0),
                        "trades": top.get("trades", 0),
                        "strategy": top.get("strategy", "simple_trend")
                    }

            metadata[sym] = {
                "symbol": sym,
                "category": "Forex",
                "session": {"startTime": "00:00", "endTime": "23:59", "isActive": True},
                "suggested_timeframe": best_sugg,
                "suggested_strategy": best_sugg.get("strategy", "simple_trend") if best_sugg else "simple_trend",
                "lot": cfg.get("symbol_lots", {}).get(sym, 0.01),
                "risk_pct": cfg.get("symbol_risk_pcts", {}).get(sym, 1.0),
                "timeframe": cfg.get("symbol_timeframes", {}).get(sym, best_sugg.get("timeframe_str", "M15") if best_sugg else "M15"),
                "strategy": cfg.get("symbol_strategies", {}).get(sym, best_sugg.get("strategy", "simple_trend") if best_sugg else "simple_trend"),
                "isActive": sym in active
            }

        return {
            "success": True,
            "available_symbols": available,
            "active_symbols": active,
            "symbols_metadata": metadata,
            "symbol_lots": cfg.get("symbol_lots", {}),
            "symbol_risk_pcts": cfg.get("symbol_risk_pcts", {}),
            "symbol_timeframes": cfg.get("symbol_timeframes", {}),
            "symbol_strategies": cfg.get("symbol_strategies", {})
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/symbols/update")
def update_symbols_config(req: Dict[str, Any]):
    """Actualiza configuración individual o masiva de símbolos."""
    try:
        cfg = {}
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)

        if "active_symbols" in req:
            cfg["active_symbols"] = req["active_symbols"]
            cfg["symbols"] = req["active_symbols"]
        if "symbol_lots" in req:
            cfg.setdefault("symbol_lots", {}).update(req["symbol_lots"])
        if "symbol_risk_pcts" in req:
            cfg.setdefault("symbol_risk_pcts", {}).update(req["symbol_risk_pcts"])
        if "symbol_timeframes" in req:
            cfg.setdefault("symbol_timeframes", {}).update(req["symbol_timeframes"])
        if "symbol_strategies" in req:
            cfg.setdefault("symbol_strategies", {}).update(req["symbol_strategies"])

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return {"success": True, "message": "Configuración de símbolos actualizada"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/deep-search/comparison")
def get_deep_search_comparison():
    """Genera la comparativa multiestrategia y detección de ganador por par."""
    bt_path = ROOT_DIR / "backtest_results.json"
    if not bt_path.exists():
        return {"success": True, "strategies_summary": [], "best_per_symbol": []}
    try:
        with open(bt_path, "r", encoding="utf-8") as f:
            raw_bt = json.load(f)
            records = raw_bt if isinstance(raw_bt, list) else list(raw_bt.values())

        tf_map = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 16385: "H1", 16388: "H4", 16408: "D1"}
        valid = [r for r in records if not r.get("cancelled") and not r.get("error")]

        # Summary per strategy
        strat_map = {}
        symbol_map = {}
        for r in valid:
            st = r.get("strategy", "simple_trend")
            sym = r.get("symbol") or r.get("resolved_symbol")
            strat_map.setdefault(st, []).append(r)
            if sym:
                symbol_map.setdefault(sym, []).append(r)

        strat_summary = []
        for st, items in strat_map.items():
            tot_trades = sum(it.get("trades", 0) for it in items)
            tot_wins = sum(it.get("wins", 0) for it in items)
            wr = round((tot_wins / tot_trades * 100), 1) if tot_trades > 0 else 0
            avg_r = round(sum(it.get("avg_r", 0) * it.get("trades", 0) for it in items) / tot_trades, 2) if tot_trades > 0 else 0
            strat_summary.append({
                "strategy": st,
                "symbols_count": len(set(it.get("symbol") for it in items)),
                "total_trades": tot_trades,
                "total_wins": tot_wins,
                "win_rate": wr,
                "win_rate_confidence": max(0, wr - 4.5),
                "avg_r": avg_r
            })

        best_per_symbol = []
        for sym, items in symbol_map.items():
            # sort by avg_r and win_rate
            items.sort(key=lambda x: (x.get("avg_r", 0), x.get("win_rate", 0)), reverse=True)
            top = items[0]
            best_per_symbol.append({
                "symbol": sym,
                "winning_strategy": top.get("strategy", "simple_trend"),
                "optimal_timeframe": tf_map.get(top.get("timeframe"), "M15"),
                "timeframe_val": top.get("timeframe", 15),
                "win_rate": top.get("win_rate", 0),
                "win_rate_confidence": top.get("win_rate_confidence", 0),
                "avg_r": top.get("avg_r", 0),
                "trades": top.get("trades", 0),
                "category": "Forex",
                "tested_strategies_count": len(set(it.get("strategy") for it in items))
            })

        return {
            "success": True,
            "strategies_summary": strat_summary,
            "best_per_symbol": best_per_symbol
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/mount-symbols")
def mount_symbols(req: MountSymbolsRequest):
    """Actualiza la lista de símbolos activos en config.json."""
    try:
        cfg = {}
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["active_symbols"] = req.symbols
        cfg["symbols"] = req.symbols
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return {"success": True, "symbols": req.symbols}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
