import customtkinter as ctk
import time
import queue
import threading
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
        # Mapeo: símbolo -> estado actual ("INACTIVE", "WAITING", "OPEN_ORDER", "WARNING", "ERROR")
        self.symbol_status: Dict[str, str] = {}
        # Tooltips por pestaña
        self.tab_tooltips: Dict[str, ToolTip] = {}

        # Cola thread-safe para recibir llamadas de workers en hilos secundarios
        self._gui_queue: queue.Queue = queue.Queue()
        self._main_thread_ident = threading.main_thread().ident

        self._build_tabs()
        # Iniciar despachador periódico seguro en el hilo principal
        self._start_queue_consumer()

    def _start_queue_consumer(self):
        """Consume periódicamente las acciones GUI encoladas desde hilos secundarios (Thread-safe)."""
        try:
            while True:
                fn = self._gui_queue.get_nowait()
                try:
                    fn()
                except Exception as e:
                    print(f"[GUI QUEUE ERROR] {e}")
        except queue.Empty:
            pass
        except Exception:
            pass

        try:
            self.after(35, self._start_queue_consumer)
        except Exception:
            pass

    def run_on_gui_thread(self, fn):
        """Ejecuta una función en el hilo de la GUI de forma 100% segura entre hilos."""
        if threading.get_ident() == self._main_thread_ident:
            try:
                fn()
            except Exception as e:
                print(f"[GUI DIRECT CALL ERROR] {e}")
        else:
            self._gui_queue.put(fn)

    def _get_tab_button(self, tab_key: str) -> Optional[Any]:
        """Obtiene el botón de la barra de pestañas correspondiente a la clave."""
        try:
            if hasattr(self, "_segmented_button") and hasattr(self._segmented_button, "_buttons_dict"):
                return self._segmented_button._buttons_dict.get(tab_key)
        except Exception:
            pass
        return None

    def _bind_tab_tooltip(self, tab_key: str, text: str) -> None:
        """Enlaza o actualiza el ToolTip al botón correspondiente del segmented button."""
        try:
            btn = self._get_tab_button(tab_key)
            if btn:
                if tab_key in self.tab_tooltips:
                    self.tab_tooltips[tab_key].set_text(text)
                else:
                    self.tab_tooltips[tab_key] = ToolTip(btn, text=text, delay_ms=300)
        except Exception:
            pass

    def _get_status_icon_and_tip(self, status: str) -> tuple:
        cfg = TAB_STATUS_CONFIG.get(status, TAB_STATUS_CONFIG["INACTIVE"])
        return cfg["icon"], cfg["tooltip"]

    def _build_tabs(self):
        """Inicializa la pestaña General y las pestañas para todos los símbolos disponibles."""
        # 1. Pestaña General (Siempre presente con clave "🌐 General")
        gen_tab_key = "🌐 General"
        if gen_tab_key not in self._tab_dict:
            self.add(gen_tab_key)

        box_gen = ctk.CTkTextbox(
            self.tab(gen_tab_key),
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word"
        )
        box_gen.pack(fill="both", expand=True, padx=5, pady=5)
        self.console_boxes["General"] = box_gen

        # Asociar tooltip a la pestaña General
        self._bind_tab_tooltip(gen_tab_key, "Consola de eventos generales y estado de la cuenta")

        # 2. Pestañas iniciales para cada símbolo
        for symbol in list(self.symbols):
            self.add_symbol_tab(symbol)

        # Forzar selección inicial en General
        try:
            self.set(gen_tab_key)
        except Exception:
            pass

    def add_symbol_tab(self, symbol: str, initial_status: str = "INACTIVE"):
        """Agrega de forma estable una nueva pestaña para un símbolo con su textbox persistente."""
        if symbol == "General" or symbol == "🌐 General":
            return

        icon, tooltip_text = self._get_status_icon_and_tip(initial_status)
        tab_key = symbol

        if symbol not in self.console_boxes:
            try:
                if tab_key not in self._tab_dict:
                    self.add(tab_key)

                box = ctk.CTkTextbox(
                    self.tab(tab_key),
                    font=ctk.CTkFont(family="Consolas", size=12),
                    wrap="word"
                )
                box.pack(fill="both", expand=True, padx=5, pady=5)
                self.console_boxes[symbol] = box
                self.symbol_status[symbol] = initial_status

                # Actualizar el texto del botón en el segmented button para mostrar el ícono de estado
                btn = self._get_tab_button(tab_key)
                if btn:
                    btn.configure(text=f"{icon} {symbol}")

                # Tooltip explicativo en la pestaña
                self._bind_tab_tooltip(tab_key, f"[{symbol}] {tooltip_text}")

            except Exception as e:
                print(f"[ERROR ADD SYMBOL TAB] {symbol}: {e}")

        if symbol not in self.symbols:
            self.symbols.append(symbol)

    def set_symbol_status(self, symbol: str, status: str, custom_tooltip: Optional[str] = None):
        """
        Actualiza el ícono, estado y tooltip del tab para el símbolo dado sin destruir widgets ni perder el foco.
        Estados:
        - 'INACTIVE': ⚪ Bot no está analizando el par
        - 'WAITING': 🟢 Bot activo y en espera de una entrada
        - 'OPEN_ORDER': 🛡️ Operación activa en monitoreo de SL/TP
        - 'WARNING': ⚠️ Alerta / Fuera de tiempo / Spread alto
        - 'ERROR': ❌ Error crítico
        """
        if symbol not in self.console_boxes or symbol in ("General", "🌐 General"):
            return

        current_status = self.symbol_status.get(symbol, "INACTIVE")
        if current_status == status and not custom_tooltip:
            return  # No hay cambios necesarios

        icon, default_tip = self._get_status_icon_and_tip(status)
        tooltip_text = custom_tooltip or f"[{symbol}] {default_tip}"

        def _do_update():
            try:
                self.symbol_status[symbol] = status
                btn = self._get_tab_button(symbol)
                if btn:
                    btn.configure(text=f"{icon} {symbol}")
                self._bind_tab_tooltip(symbol, tooltip_text)
            except Exception as e:
                print(f"[ERROR SET SYMBOL STATUS] {symbol}: {e}")

        self.run_on_gui_thread(_do_update)

    def remove_symbol_tab(self, symbol: str):
        """Elimina una pestaña de símbolo de la interfaz de forma segura."""
        if symbol in ("General", "🌐 General"):
            return

        tab_key = symbol
        if symbol in self.console_boxes:
            del self.console_boxes[symbol]
        if symbol in self.symbol_status:
            del self.symbol_status[symbol]
        if tab_key in self.tab_tooltips:
            del self.tab_tooltips[tab_key]

        if symbol in self.symbols:
            self.symbols.remove(symbol)

        try:
            if tab_key in self._tab_dict:
                self.delete(tab_key)
        except Exception:
            pass

    def sync_tabs(self, new_symbols: List[str]):
        """Sincroniza la consola agregando nuevas pestañas o eliminando las retiradas sin perder visibilidad."""
        def _do_sync():
            try:
                current_active = self.get()
                target_symbols = list(new_symbols)

                # 1. Eliminar pestañas que ya no están en la lista de símbolos
                existing_symbols = [s for s in list(self.console_boxes.keys()) if s not in ("General", "🌐 General")]
                for sym in existing_symbols:
                    if sym not in target_symbols:
                        self.remove_symbol_tab(sym)

                # 2. Agregar pestañas para los símbolos nuevos
                for sym in target_symbols:
                    if sym not in self.console_boxes:
                        self.add_symbol_tab(sym)
                    else:
                        # Asegurar que el botón muestre el ícono correspondiente al estado actual
                        curr_st = self.symbol_status.get(sym, "INACTIVE")
                        icon, _ = self._get_status_icon_and_tip(curr_st)
                        btn = self._get_tab_button(sym)
                        if btn:
                            btn.configure(text=f"{icon} {sym}")

                # 3. Mantener el tab activo visible de forma garantizada
                if current_active and (current_active in self._tab_dict or current_active == "🌐 General"):
                    try:
                        self.set(current_active)
                    except Exception:
                        pass
                else:
                    try:
                        self.set("🌐 General")
                    except Exception:
                        pass

                # Forzar refresco de geometría para que el tab seleccionado sea visible inmediatamente
                self.update_idletasks()
            except Exception as e:
                print(f"[SYNC TABS ERROR] {e}")

        self.run_on_gui_thread(_do_sync)

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

            if target not in self.console_boxes and target not in ("General", "🌐 General"):
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
            if target not in ("General", "🌐 General") and target in self.console_boxes:
                msg_upper = message.upper()

                if "POSICIÓN ACTIVA DETECTADA" in msg_upper or "OPERACIÓN DETECTADA" in msg_upper or "OPERACIÓN ABIERTA" in msg_upper:
                    self.set_symbol_status(target, "OPEN_ORDER", f"[{target}] Operación abierta activa. Modificando SL/TP y protegiendo...")
                elif "MONITOREO DETENIDO" in msg_upper:
                    self.set_symbol_status(target, "INACTIVE", f"[{target}] Monitoreo apagado")
                elif "CERRADA" in msg_upper or "CIERRE PREMATURO" in msg_upper or "SL ALCANZADO" in msg_upper or "TP ALCANZADO" in msg_upper or "STOP LOSS" in msg_upper or "TAKE PROFIT" in msg_upper:
                    # 🟢 Al cerrarse cualquier posición, regresar inmediatamente al estado activo de búsqueda (WAITING)
                    self.set_symbol_status(target, "WAITING", f"[{target}] Operación cerrada. Reanudando análisis en espera de confluencias")
                elif "SIN ÓRDENES ABIERTAS" in msg_upper or "ANALIZANDO" in msg_upper or "MONITOREO ACTIVADO" in msg_upper or "PRÓXIMO ANÁLISIS" in msg_upper:
                    # Si el bot está analizando velas y no tiene órdenes activas, asegurar estado WAITING (🟢)
                    self.set_symbol_status(target, "WAITING", f"[{target}] Activo: Analizando velas y buscando confluencia de entrada")
                elif "FILTRO HORARIO" in msg_upper or "MERCADO CERRADO" in msg_upper or "FILTRO CORRELACIÓN" in msg_upper or level in ["WARN", "WARNING"]:
                    if self.symbol_status.get(target) != "OPEN_ORDER":
                        self.set_symbol_status(target, "WARNING", f"[{target}] Advertencia / Fuera de sesión o filtro activo")
                elif level == "ERROR":
                    if self.symbol_status.get(target) != "OPEN_ORDER":
                        self.set_symbol_status(target, "ERROR", f"[{target}] Error reportado en el procesamiento")

        # Delegar la ejecución al hilo de la GUI mediante la cola thread-safe
        self.run_on_gui_thread(_update_gui)

