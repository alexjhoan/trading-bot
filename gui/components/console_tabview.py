import customtkinter as ctk
import time
from typing import List, Dict, Any


class ConsoleTabviewComponent(ctk.CTkTabview):
    def __init__(self, master: Any, symbols: List[str], **kwargs):
        super().__init__(master, **kwargs)

        self.symbols: List[str] = list(symbols)
        self.console_boxes: Dict[str, ctk.CTkTextbox] = {}

        self._build_tabs()

    def _build_tabs(self):
        # Tab General siempre presente
        self.add("🌐 General")
        box_gen = ctk.CTkTextbox(
            self.tab("🌐 General"),
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word"
        )
        box_gen.pack(fill="both", expand=True, padx=5, pady=5)
        self.console_boxes["General"] = box_gen

        # Pestañas por Símbolo
        for symbol in self.symbols:
            self.add_symbol_tab(symbol)

    def add_symbol_tab(self, symbol: str):
        """Agrega dinámicamente una nueva pestaña para un símbolo si no existe."""
        tab_name = f"⚪ {symbol}"
        if symbol not in self.console_boxes and tab_name not in self._tab_dict:
            self.add(tab_name)
            box = ctk.CTkTextbox(
                self.tab(tab_name),
                font=ctk.CTkFont(family="Consolas", size=12),
                wrap="word"
            )
            box.pack(fill="both", expand=True, padx=5, pady=5)
            self.console_boxes[symbol] = box

    def remove_symbol_tab(self, symbol: str):
        """Elimina una pestaña de símbolo dinámicamente."""
        tab_name = f"⚪ {symbol}"
        if symbol in self.console_boxes:
            del self.console_boxes[symbol]
        try:
            self.delete(tab_name)
        except Exception:
            pass

    def sync_tabs(self, new_symbols: List[str]):
        """Sincroniza todas las pestañas de acuerdo a la nueva lista de símbolos."""
        # Agregar los nuevos
        for sym in new_symbols:
            if sym not in self.symbols:
                self.add_symbol_tab(sym)

        # Eliminar los quitados
        for sym in list(self.symbols):
            if sym not in new_symbols:
                self.remove_symbol_tab(sym)

        self.symbols = list(new_symbols)

    # En gui/components/console_tabview.py

    def log(self, target: str, message: str, level: str = "INFO"):
        """Escribe un log en la pestaña especificada."""
        timestamp = time.strftime("[%H:%M:%S] ")
        prefix = {
            "INFO": "ℹ️ ",
            "WARN": "⚠️ [WARN] ",
            "ERROR": "❌ [ERROR] ",
            "SUCCESS": "✅ [SUCCESS] "
        }.get(level, "")

        formatted_msg = f"{timestamp}{prefix}{message}\n"

        # Determinar en qué caja escribir
        box = self.console_boxes.get(target) or self.console_boxes.get("General")

        if box:
            # Permitir escritura si estuviera deshabilitada
            current_state = box.cget("state")
            if current_state == "disabled":
                box.configure(state="normal")

            box.insert("end", formatted_msg)
            box.see("end")  # 👈 Auto-scroll siempre al final del mensaje

            if current_state == "disabled":
                box.configure(state="disabled")
