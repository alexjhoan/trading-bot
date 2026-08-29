import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Dict, List, Type, Any, Optional

from .base_strategy import BaseStrategy
from .forex import ForexStrategy
from .syntx import SyntxStrategy

# Registro estático inicial de estrategias disponibles
AVAILABLE_STRATEGIES: Dict[str, Type[BaseStrategy]] = {
    "forex": ForexStrategy,
    "syntx": SyntxStrategy,
}


def discover_strategies() -> Dict[str, Type[BaseStrategy]]:
    """
    Escanea dinámicamente la carpeta 'strategies' para registrar cualquier
    nueva estrategia (.py) que herede de BaseStrategy.
    """
    strategies_dir = Path(__file__).resolve().parent
    discovered: Dict[str, Type[BaseStrategy]] = dict(AVAILABLE_STRATEGIES)

    for py_file in strategies_dir.glob("*.py"):
        if py_file.stem in ("__init__", "base_strategy"):
            continue

        key = py_file.stem.lower()
        if key in discovered:
            continue

        try:
            mod = None
            # 1. Intentar importación relativa
            try:
                mod = importlib.import_module(f".{py_file.stem}", package=__package__ or "strategies")
            except Exception:
                pass

            # 2. Intentar importación absoluta
            if mod is None:
                try:
                    mod = importlib.import_module(f"strategies.{py_file.stem}")
                except Exception:
                    pass

            # 3. Fallback directo con spec_from_file_location
            if mod is None:
                spec = importlib.util.spec_from_file_location(f"strategies.{py_file.stem}", py_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[f"strategies.{py_file.stem}"] = mod
                    spec.loader.exec_module(mod)

            if mod is not None:
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        inspect.isclass(attr)
                        and issubclass(attr, BaseStrategy)
                        and attr is not BaseStrategy
                    ):
                        discovered[key] = attr
        except Exception as e:
            print(f"[DEBUG STRATEGIES] Error cargando estrategia {py_file.stem}: {e}")

    return discovered


def get_available_strategies() -> List[str]:
    """Retorna la lista de nombres de estrategias disponibles (ej. ['forex', 'syntx'])."""
    return list(discover_strategies().keys())


def get_strategy_class(name: str) -> Type[BaseStrategy]:
    """Obtiene la clase de la estrategia por nombre, con fallback a ForexStrategy."""
    strategies = discover_strategies()
    normalized_name = (name or "forex").strip().lower()
    return strategies.get(normalized_name, ForexStrategy)


def create_strategy_instance(name: str, symbol: Optional[str] = None, **kwargs: Any) -> BaseStrategy:
    """Crea e inicializa una instancia de la estrategia especificada."""
    cls = get_strategy_class(name)
    return cls(symbol=symbol, **kwargs)


__all__ = [
    "BaseStrategy",
    "ForexStrategy",
    "SyntxStrategy",
    "AVAILABLE_STRATEGIES",
    "get_available_strategies",
    "get_strategy_class",
    "create_strategy_instance",
]
