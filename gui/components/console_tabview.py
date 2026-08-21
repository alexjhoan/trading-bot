import customtkinter as ctk
import time
from typing import List, Dict, Any, Optional
from .tooltip import ToolTip

# Diccionario de estados con sus íconos y descripciones para el tooltip
TAB_STATUS_CONFIG: Dict[str, Dict[str, str]] = {
    "INACTIVE": {
        "icon": "⚪",
        "label": "Inactivo",
        "tooltip": "Bot inactivo / No está analizando este par actualmente",
    },
    "WAITING": {
        "icon": "🟢",
        "label": "Activo / Esperando",
        "tooltip": "Bot activo y analizando el mercado en espera de confluencias de entrada",
    },
    "OPEN_ORDER": {
        "icon": "🛡️",
        "label": "Operación Activa",
        "tooltip": "Hay una operación abierta en este par. Nueva búsqueda pausada; en modo gestión activa de SL/TP",
    },
    "WARNING": {
        "icon": "⚠️",
        "label": "Atención / Alerta",
        "tooltip": "Alerta / Fuera de horario de alta liquidez o mercado cerrado",
    },
    "ERROR": {
        "icon": "❌",
        "label": "Error",
        "tooltip": "Error en ejecución o conexión en este par",
    },
}


class ConsoleTabviewComponent(ctk.CTkTabview):
    def __init__(self, master: Any, symbols: List[str] = None, **kwargs):
        super().__init__(master, **kwargs)

        self.symbols: List[str] = list(symbols) if symbols else []
        self.console_boxes: Dict[str, ctk.CTkTextbox] = {}
        # Mapeo: símbolo -> nombre actual de la pestaña (ej: "⚪ EURUSD")
        self.symbol_tab_names: Dict[str, str] = {}
        # Mapeo: símbolo -> estado actual ("INACTIVE", "WAITING", "OPEN_ORDER", "WARNING", "ERROR")
        self.symbol_status: Dict[str, str] = {}
        # Tooltips por pestaña
        self.tab_tooltips: Dict[str, ToolTip] = {}

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
        self.symbol_tab_names["General"] = "🌐 General"

        # Asociar tooltip a la pestaña General si es accesible
        self._bind_tab_tooltip("🌐 General", "Consola de eventos generales y estado de la cuenta")

        # 2. Pestañas iniciales para cada símbolo disponible
        for symbol in list(self.symbols):
            self.add_symbol_tab(symbol)

    def _get_status_icon_and_tip(self, status: str) -> tuple:
        cfg = TAB_STATUS_CONFIG.get(status, TAB_STATUS_CONFIG["INACTIVE"])
        return cfg["icon"], cfg["tooltip"]

    def _bind_tab_tooltip(self, tab_name: str, text: str) -> None:
        """Intenta enlazar el ToolTip al botón correspondiente del tabview."""
        try:
            # CustomTkinter CTkTabview contiene internamente los botones en self._segmented_button
            if hasattr(self, "_segmented_button") and hasattr(self._segmented_button, "_buttons_dict"):
                btn = self._segmented_button._buttons_dict.get(tab_name)
                if btn:
                    if tab_name in self.tab_tooltips:
                        self.tab_tooltips[tab_name].set_text(text)
                    else:
                        self.tab_tooltips[tab_name] = ToolTip(btn, text=text, delay_ms=300)
        except Exception:
            pass

    def add_symbol_tab(self, symbol: str, initial_status: str = "INACTIVE"):
        """Agrega dinámicamente una nueva pestaña para un símbolo con su ícono y tooltip de estado."""
        if symbol == "General":
            return

        icon, tooltip_text = self._get_status_icon_and_tip(initial_status)
        tab_name = f"{icon} {symbol}"

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
                self.symbol_tab_names[symbol] = tab_name
                self.symbol_status[symbol] = initial_status

                # Tooltip explicativo en la pestaña
                self._bind_tab_tooltip(tab_name, f"[{symbol}] {tooltip_text}")

            except Exception:
                pass

        if symbol not in self.symbols:
            self.symbols.append(symbol)

    def set_symbol_status(self, symbol: str, status: str, custom_tooltip: Optional[str] = None):
        """
        Actualiza el ícono, estado y tooltip del tab para el símbolo dado.
        Estados:
        - 'INACTIVE': ⚪ Bot no está analizando el par
        - 'WAITING': 🟢 Bot activo y en espera de una entrada
        - 'OPEN_ORDER': 🛡️ Operación activa en monitoreo de SL/TP
        - 'WARNING': ⚠️ Alerta / Fuera de tiempo / Spread alto
        - 'ERROR': ❌ Error crítico
        """
        if symbol not in self.console_boxes or symbol == "General":
            return

        current_status = self.symbol_status.get(symbol, "INACTIVE")
        if current_status == status and not custom_tooltip:
            return  # No hay cambios necesarios

        old_tab_name = self.symbol_tab_names.get(symbol, f"⚪ {symbol}")
        icon, default_tip = self._get_status_icon_and_tip(status)
        new_tab_name = f"{icon} {symbol}"
        tooltip_text = custom_tooltip or f"[{symbol}] {default_tip}"

        if old_tab_name == new_tab_name:
            self.symbol_status[symbol] = status
            self._bind_tab_tooltip(new_tab_name, tooltip_text)
            return

        def _do_update():
            try:
                # Guardar el contenido del textbox actual
                box = self.console_boxes.get(symbol)
                content = box.get("1.0", "end") if box else ""
                is_selected = (self.get() == old_tab_name)

                # Eliminar pestaña vieja
                try:
                    self.delete(old_tab_name)
                except Exception:
                    pass

                # Crear pestaña nueva con el nuevo ícono
                if new_tab_name not in self._tab_dict:
                    self.add(new_tab_name)

                new_box = ctk.CTkTextbox(
                    self.tab(new_tab_name),
                    font=ctk.CTkFont(family="Consolas", size=12),
                    wrap="word"
                )
                new_box.pack(fill="both", expand=True, padx=5, pady=5)
                if content.strip():
                    new_box.insert("1.0", content)
                    new_box.see("end")

                self.console_boxes[symbol] = new_box
                self.symbol_tab_names[symbol] = new_tab_name
                self.symbol_status[symbol] = status

                if is_selected:
                    self.set(new_tab_name)

                self._bind_tab_tooltip(new_tab_name, tooltip_text)
            except Exception:
                pass

        self.after(0, _do_update)

    def remove_symbol_tab(self, symbol: str):
        """Elimina una pestaña de símbolo de la interfaz de forma segura."""
        tab_name = self.symbol_tab_names.get(symbol, f"⚪ {symbol}")
        if symbol in self.console_boxes:
            del self.console_boxes[symbol]
        if symbol in self.symbol_tab_names:
            del self.symbol_tab_names[symbol]
        if symbol in self.symbol_status:
            del self.symbol_status[symbol]
        if tab_name in self.tab_tooltips:
            del self.tab_tooltips[tab_name]

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
        Escribe un log en la pestaña especificada y actualiza inteligentemente
        el estado del tabview (ícono y tooltip) según los mensajes que recibe.
        """
        def _update_gui():
            timestamp = time.strftime("[%H:%M:%S] ")
            prefix = {
                "INFO": "ℹ️ ",
                "WARN": "⚠️ [WARN] ",
                "WARNING": "⚠️ [WARN] ",
                "ERROR": "❌ [ERROR] ",
                "SUCCESS": "✅ [SUCCESS] "
            }.get(level, "")

            formatted_msg = f"{timestamp}{prefix}{message}\n"

            if target not in self.console_boxes and target != "General":
                self.add_symbol_tab(target)

            box = self.console_boxes.get(target) or self.console_boxes.get("General")

            if box:
                current_state = box.cget("state")
                if current_state == "disabled":
                    box.configure(state="normal")

                box.insert("end", formatted_msg)
                box.see("end")

                if current_state == "disabled":
                    box.configure(state="disabled")

            # 🟢 ACTUALIZAR AUTOMÁTICAMENTE EL ÍCONO Y TOOLTIP SEGÚN EL LOG
            if target != "General" and target in self.console_boxes:
                if "POSICIÓN ACTIVA DETECTADA" in message or "OPERACIÓN DETECTADA" in message or "Operación abierta" in message:
                    self.set_symbol_status(target, "OPEN_ORDER", f"[{target}] Operación abierta activa. Modificando SL/TP y protegiendo...")
                elif "Monitoreo detenido" in message:
                    self.set_symbol_status(target, "INACTIVE", f"[{target}] Monitoreo apagado")
                elif "ANALIZANDO" in message or "Monitoreo activado" in message or "Próximo análisis" in message:
                    if self.symbol_status.get(target) != "OPEN_ORDER":
                        self.set_symbol_status(target, "WAITING", f"[{target}] Activo: Analizando velas y buscando confluencia de entrada")
                elif "FILTRO HORARIO" in message or "MERCADO CERRADO" in message or level in ["WARN", "WARNING"]:
                    if self.symbol_status.get(target) != "OPEN_ORDER":
                        self.set_symbol_status(target, "WARNING", f"[{target}] Advertencia / Fuera de sesión operativa de alta liquidez")
                elif level == "ERROR":
                    self.set_symbol_status(target, "ERROR", f"[{target}] Error reportado en el procesamiento")

        # Delegar la ejecución al hilo de la GUI
        self.after(0, _update_gui)
