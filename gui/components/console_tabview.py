import customtkinter as ctk
import time
from typing import List, Dict, Any


class ConsoleTabviewComponent(ctk.CTkTabview):
    def __init__(self, master: Any, symbols: List[str] = None, **kwargs):
        super().__init__(master, **kwargs)

        self.symbols: List[str] = list(symbols) if symbols else []
        self.console_boxes: Dict[str, ctk.CTkTextbox] = {}

        self._build_tabs()

    def _build_tabs(self):
        """Inicializa la pestaña General y las pestañas para todos los símbolos disponibles."""
        # 1. Pestaña General (Siempre presente)
        self.add("🌐 General")
        box_gen = ctk.CTkTextbox(
            self.tab("🌐 General"),
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word"
        )
        box_gen.pack(fill="both", expand=True, padx=5, pady=5)
        self.console_boxes["General"] = box_gen

        # 2. Pestañas iniciales para cada símbolo disponible
        for symbol in list(self.symbols):
            self.add_symbol_tab(symbol)

    def add_symbol_tab(self, symbol: str):
        """Agrega dinámicamente una nueva pestaña para un símbolo si no existe aún."""
        tab_name = f"⚪ {symbol}"

        if symbol not in self.console_boxes:
            try:
                if tab_name not in self._tab_dict:
                    self.add(tab_name)

                box = ctk.CTkTextbox(
                    self.tab(tab_name),
                    font=ctk.CTkFont(family="Consolas", size=12),
                    wrap="word"
                )
                box.pack(fill="both", expand=True, padx=5, pady=5)
                self.console_boxes[symbol] = box

            except Exception:
                pass

        if symbol not in self.symbols:
            self.symbols.append(symbol)

    def remove_symbol_tab(self, symbol: str):
        """Elimina una pestaña de símbolo de la interfaz de forma segura."""
        tab_name = f"⚪ {symbol}"
        if symbol in self.console_boxes:
            del self.console_boxes[symbol]

        if symbol in self.symbols:
            self.symbols.remove(symbol)

        try:
            self.delete(tab_name)
        except Exception:
            pass

    def sync_tabs(self, new_symbols: List[str]):
        """Sincroniza la consola agregando nuevas pestañas o eliminando las retiradas."""
        target_symbols = list(new_symbols)

        # 1. Eliminar pestañas que ya no están en la lista de símbolos
        existing_symbols = [s for s in list(self.console_boxes.keys()) if s != "General"]
        for sym in existing_symbols:
            if sym not in target_symbols:
                self.remove_symbol_tab(sym)

        # 2. Agregar pestañas para los símbolos nuevos
        created_any = False
        for sym in target_symbols:
            if sym not in self.console_boxes:
                self.add_symbol_tab(sym)
                created_any = True

        # 3. Forzar renderizado visual inmediato
        self.update_idletasks()

    def log(self, target: str, message: str, level: str = "INFO"):
        """
        Escribe un log en la pestaña especificada.
        Si la pestaña objetivo no existe, la crea dinámicamente.
        """
        timestamp = time.strftime("[%H:%M:%S] ")
        prefix = {
            "INFO": "ℹ️ ",
            "WARN": "⚠️ [WARN] ",
            "ERROR": "❌ [ERROR] ",
            "SUCCESS": "✅ [SUCCESS] "
        }.get(level, "")

        formatted_msg = f"{timestamp}{prefix}{message}\n"

        # Auto-creación de emergencia si llega log de un símbolo sin pestaña
        if target not in self.console_boxes and target != "General":
            self.add_symbol_tab(target)

        box = self.console_boxes.get(target) or self.console_boxes.get("General")

        if box:
            current_state = box.cget("state")
            if current_state == "disabled":
                box.configure(state="normal")

            box.insert("end", formatted_msg)
            box.see("end")  # Auto-scroll siempre al final

            if current_state == "disabled":
                box.configure(state="disabled")
