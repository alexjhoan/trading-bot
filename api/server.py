import os
import sys
import json
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Añadir raíz al sys.path para importar core
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from core.config_manager import load_config
    from core.ai_strategy_changelog import load_all_changelogs, get_symbol_changelog
    from core.ai_backtest_learner import train_ai_batch_from_backtest
except ImportError as e:
    print(f"⚠️ [API] Import error: {e}")

app = FastAPI(title="Trading Bot API & WebSocket Engine", version="1.0.0")

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

class LearnRequest(BaseModel):
    items: List[Dict[str, Any]]
    default_strategy: Optional[str] = "ai_strategy"
    api_key: Optional[str] = None
    model_name: Optional[str] = None

class MountSymbolsRequest(BaseModel):
    symbols: List[str]

# WebSocket Manager
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        # Enviar estado inicial
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
            # Echo o comandos entrantes
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

async def broadcast_event(event_type: str, payload: Any):
    dead_sockets = []
    for ws in active_websockets:
        try:
            await ws.send_json({"type": event_type, "payload": payload})
        except Exception:
            dead_sockets.append(ws)
    for ws in dead_sockets:
        if ws in active_websockets:
            active_websockets.remove(ws)

@app.get("/api/status")
def get_bot_status():
    """Devuelve estado de cuenta y del bot."""
    cfg = {}
    try:
        cfg = load_config()
    except Exception:
        pass
    
    # Leer archivo de memoria de trades si existe
    trade_memory = {}
    tm_path = ROOT_DIR / "trade_memory.json"
    if tm_path.exists():
        try:
            with open(tm_path, "r", encoding="utf-8") as f:
                trade_memory = json.load(f)
        except Exception:
            pass

    return {
        "account": {
            "connected": False, # MT5 se conecta localmente en Windows
            "balance": 10000.0,
            "equity": 10000.0,
            "margin": 0.0,
            "freeMargin": 10000.0,
            "profit": 0.0,
            "currency": "USD",
            "server": "MetaQuotes-Demo",
            "login": "12345678"
        },
        "bot": {
            "isRunning": False,
            "activePairs": cfg.get("symbols", ["EURUSD", "GBPUSD", "USDCAD", "USDJPY", "AUDUSD"]),
            "currentStrategy": cfg.get("default_strategy", "ai_strategy"),
            "mode": "DEMO",
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
            # data puede ser lista o dict con "results"
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
    try:
        cfg = load_config()
    except Exception:
        pass

    api_key = req.api_key or cfg.get("ai", {}).get("api_key") or os.environ.get("GEMINI_API_KEY", "")
    model_name = req.model_name or cfg.get("ai", {}).get("model", "gemini-2.5-flash")

    try:
        learned = train_ai_batch_from_backtest(
            items=req.items,
            default_strategy=req.default_strategy or "ai_strategy",
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

@app.post("/api/mount-symbols")
def mount_symbols(req: MountSymbolsRequest):
    """Actualiza la lista de símbolos activos en config.json."""
    try:
        from core.config_manager import save_config
        cfg = load_config()
        cfg["symbols"] = req.symbols
        save_config(cfg)
        return {"success": True, "symbols": req.symbols}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
