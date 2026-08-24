import json
from pathlib import Path
from typing import Dict, Any

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "login": 0,
    "password": "",
    "server": "",
    "path": "",
    "symbol_suffix": "",
    "magic_number": 999111,
    "max_slippage": 10,
    "selected_strategy": "forex",
    "active_symbols": [],
    "available_symbols": [],
    "symbol_lots": {},
    "symbol_risk_pcts": {},
    "symbol_timeframes": {}
}

def load_config() -> Dict[str, Any]:
    """Carga la configuración desde config.json o crea una por defecto."""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Asegurar que existan todas las claves requeridas
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception as e:
        print(f"❌ [ERROR] No se pudo leer config.json: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config_data: Dict[str, Any]) -> bool:
    """Guarda los datos de configuración en config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ [ERROR] No se pudo guardar config.json: {e}")
        return False
