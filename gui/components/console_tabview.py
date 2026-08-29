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


class ConsoleTabviewComponent(ctk.CTkFrame):
    """
    Componente de Consola Multi-Pestaña con ajuste dinámico de botones multilínea (Wrap).
    Permite visualizar cómodamente 10, 20 o más pares sin que se amontonen ni corten horizontalmente.
    Soporta íconos de estado en tiempo real, tooltips descriptivos y salida de logs por par y general.
    """
    def __init__(self, master: Any, active_symbols: Optional[List[str]] = None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self.symbols: List[str] = list(active_symbols) if active_symbols else []
        self.console_boxes: Dict[str, ctk.CTkTextbox] = {}
        self.symbol_status: Dict[str, str] = {}
        self.tab_tooltips: Dict[str, ToolTip] = {}

        self.tab_buttons: Dict[str, ctk.CTkButton] = {}
        self.tab_frames: Dict[str, ctk.CTkFrame] = {}
        self.tab_keys: List[str] = []
        self.current_tab: str = "🌐 General"

        # Control de resize / debouncing para reposicionar botones
        self._last_wrap_width: int = 0
        self._resize_after_id: Optional[str] = None

        # Cola thread-safe para recibir llamadas de workers en hilos secundarios
        self._gui_queue: queue.Queue = queue.Queue()
        self._main_thread_ident = threading.main_thread().ident

        # Contenedor superior para la barra de pestañas (Wrap / Multi-línea)
        self.tab_bar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_bar_frame.pack(fill="x", padx=2, pady=(2, 4))
        self.tab_bar_frame.bind("<Configure>", self._on_tab_bar_configure)

        # Contenedor inferior para el contenido activo (Textboxes)
        self.content_container = ctk.CTkFrame(self, fg_color=("gray88", "gray16"), corner_radius=8)
        self.content_container.pack(fill="both", expand=True, padx=2, pady=(0, 2))

        self._build_tabs()
        self._start_queue_consumer()

    def _start_queue_consumer(self):
        """Consume periódicamente las acciones GUI encoladas desde hilos secundarios (Thread-safe)."""
        try:
            while True:
                func = self._gui_queue.get_nowait()
                try:
                    func()
                except Exception as e:
                    print(f"[GUI QUEUE ERROR] {e}")
        except queue.Empty:
            pass
        finally:
            self.after(50, self._start_queue_consumer)

    def run_on_gui_thread(self, func):
        """Ejecuta una función en el hilo principal de la GUI de forma segura."""
        if threading.get_ident() == self._main_thread_ident:
            try:
                func()
            except Exception as e:
                print(f"[GUI EXEC ERROR] {e}")
        else:
            self._gui_queue.put(func)

    def _on_tab_bar_configure(self, event):
        """Detecta cambios de ancho de la ventana y reacomoda los tabs en múltiples líneas si no caben."""
        new_width = event.width
        if abs(new_width - self._last_wrap_width) > 15:
            self._last_wrap_width = new_width
            if self._resize_after_id:
                self.after_cancel(self._resize_after_id)
            self._resize_after_id = self.after(30, self._reposition_buttons)

    def _reposition_buttons(self):
        """Calcula el ancho disponible y coloca los botones en filas automáticas para que bajen de línea."""
        width = self.tab_bar_frame.winfo_width()
        if width <= 50:
            width = self.winfo_width()
        if width <= 50:
            width = 800

        max_available_width = max(200, width - 15)
        current_x = 0
        current_row = 0
        current_col = 0

        for key in self.tab_keys:
            btn = self.tab_buttons.get(key)
            if not btn:
                continue

            btn_req_width = btn.winfo_reqwidth()
            # Si el botón aún no ha sido renderizado, estimar ancho según caracteres
            if btn_req_width <= 20:
                txt = btn.cget("text")
                btn_req_width = max(85, len(txt) * 9 + 28)

            btn_total_w = btn_req_width + 6

            if current_col > 0 and (current_x + btn_total_w > max_available_width):
                current_row += 1
                current_col = 0
                current_x = 0

            btn.grid(row=current_row, column=current_col, padx=2, pady=2, sticky="w")
            current_x += btn_total_w
            current_col += 1

    def _build_tabs(self):
        """Construye la pestaña General y las pestañas de símbolos iniciales."""
        # 1. Pestaña General siempre presente
        self.add("🌐 General")
        gen_box = self._create_textbox(self.tab_frames["🌐 General"])
        self.console_boxes["General"] = gen_box
        self.console_boxes["🌐 General"] = gen_box

        # 2. Agregar pestañas para cada símbolo activo
        for sym in self.symbols:
            self.add_symbol_tab(sym)

        self.set("🌐 General")

    def _create_textbox(self, parent_frame: ctk.CTkFrame) -> ctk.CTkTextbox:
        """Crea un textbox de logs estilizado."""
        box = ctk.CTkTextbox(
            parent_frame,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=("gray95", "gray12"),
            text_color=("gray10", "gray90"),
            corner_radius=6
        )
        box.pack(fill="both", expand=True, padx=4, pady=4)
        return box

    def add(self, tab_key: str) -> ctk.CTkFrame:
        """Crea una nueva pestaña y su botón asociado."""
        if tab_key in self.tab_frames:
            return self.tab_frames[tab_key]

        # Crear frame de contenido para este tab
        tab_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.tab_frames[tab_key] = tab_frame

        # Crear botón en la barra de tabs
        btn = ctk.CTkButton(
            self.tab_bar_frame,
            text=tab_key,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray80", "gray25"),
            hover_color=("gray72", "gray35"),
            text_color=("gray10", "gray95"),
            command=lambda k=tab_key: self.set(k)
        )
        self.tab_buttons[tab_key] = btn
        self.tab_keys.append(tab_key)

        self._reposition_buttons()
        return tab_frame

    def set(self, tab_key: str):
        """Selecciona y activa una pestaña."""
        target_key = tab_key
        if target_key not in self.tab_frames:
            if target_key == "General" and "🌐 General" in self.tab_frames:
                target_key = "🌐 General"
            elif f"⚪ {target_key}" in self.tab_frames:
                target_key = f"⚪ {target_key}"
            elif target_key in self.symbols:
                target_key = target_key
            else:
                return

        self.current_tab = target_key

        # Actualizar colores de los botones
        for key, btn in self.tab_buttons.items():
            if key == target_key:
                btn.configure(
                    fg_color=("#1F6AA5", "#144870"),
                    text_color="#FFFFFF"
                )
            else:
                btn.configure(
                    fg_color=("gray80", "gray25"),
                    text_color=("gray10", "gray95")
                )

        # Mostrar el frame correspondiente y ocultar los demás
        for key, frame in self.tab_frames.items():
            if key == target_key:
                frame.pack(fill="both", expand=True, padx=2, pady=2)
            else:
                frame.pack_forget()

    def get(self) -> str:
        """Retorna la pestaña actualmente activa."""
        return self.current_tab

    def delete(self, tab_key: str):
        """Elimina una pestaña y libera sus recursos."""
        if tab_key in self.tab_buttons:
            btn = self.tab_buttons.pop(tab_key)
            btn.destroy()

        if tab_key in self.tab_frames:
            frm = self.tab_frames.pop(tab_key)
            frm.destroy()

        if tab_key in self.tab_keys:
            self.tab_keys.remove(tab_key)

        if tab_key in self.tab_tooltips:
            del self.tab_tooltips[tab_key]

        if tab_key in self.console_boxes:
            del self.console_boxes[tab_key]

        if tab_key in self.symbol_status:
            del self.symbol_status[tab_key]

        self._reposition_buttons()

        if self.current_tab == tab_key:
            self.set("🌐 General")

    def _get_status_icon_and_tip(self, status: str) -> tuple:
        """Devuelve el ícono y tooltip para un estado dado."""
        cfg = TAB_STATUS_CONFIG.get(status, TAB_STATUS_CONFIG["INACTIVE"])
        return cfg["icon"], cfg["tooltip"]

    def _bind_tab_tooltip(self, tab_key: str, tooltip_text: str):
        """Enlaza un ToolTip al botón de la pestaña correspondiente."""
        btn = self.tab_buttons.get(tab_key)
        if not btn:
            return

        if tab_key in self.tab_tooltips:
            tt = self.tab_tooltips[tab_key]
            if hasattr(tt, "set_text"):
                tt.set_text(tooltip_text)
            elif hasattr(tt, "update_text"):
                tt.update_text(tooltip_text)
            else:
                tt.text = tooltip_text
        else:
            self.tab_tooltips[tab_key] = ToolTip(btn, text=tooltip_text)

    def add_symbol_tab(self, symbol: str, initial_status: str = "INACTIVE"):
        """Agrega una pestaña para un símbolo con ícono de estado y tooltip descriptivo."""
        tab_key = symbol
        if tab_key in self.console_boxes:
            return

        try:
            tab_frame = self.add(tab_key)
            box = self._create_textbox(tab_frame)
            self.console_boxes[symbol] = box

            self.symbol_status[symbol] = initial_status
            icon, default_tip = self._get_status_icon_and_tip(initial_status)
            tooltip_text = f"[{symbol}] {default_tip}"

            btn = self.tab_buttons.get(tab_key)
            if btn:
                btn.configure(text=f"{icon} {symbol}")

            self._bind_tab_tooltip(tab_key, tooltip_text)

        except Exception as e:
            print(f"[ERROR ADD SYMBOL TAB] {symbol}: {e}")

        if symbol not in self.symbols:
            self.symbols.append(symbol)

        self._reposition_buttons()

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
            return

        icon, default_tip = self._get_status_icon_and_tip(status)
        tooltip_text = custom_tooltip or f"[{symbol}] {default_tip}"

        def _do_update():
            try:
                self.symbol_status[symbol] = status
                btn = self.tab_buttons.get(symbol)
                if btn:
                    btn.configure(text=f"{icon} {symbol}")
                self._bind_tab_tooltip(symbol, tooltip_text)
                self._reposition_buttons()
            except Exception as e:
                print(f"[ERROR SET SYMBOL STATUS] {symbol}: {e}")

        self.run_on_gui_thread(_do_update)

    def remove_symbol_tab(self, symbol: str):
        """Elimina una pestaña de símbolo de la interfaz de forma segura."""
        if symbol in ("General", "🌐 General"):
            return

        if symbol in self.symbols:
            self.symbols.remove(symbol)

        self.delete(symbol)

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
                        curr_st = self.symbol_status.get(sym, "INACTIVE")
                        icon, _ = self._get_status_icon_and_tip(curr_st)
                        btn = self.tab_buttons.get(sym)
                        if btn:
                            btn.configure(text=f"{icon} {sym}")

                # 3. Mantener el tab activo visible
                if current_active and (current_active in self.tab_frames or current_active == "🌐 General"):
                    self.set(current_active)
                else:
                    self.set("🌐 General")

                self._reposition_buttons()
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

            box = self.console_boxes.get(target)
            if not box:
                # Si el par no tiene pestaña abierta (está inactivo/apagado), registrar en General
                box = self.console_boxes.get("General")
                if target not in ("General", "🌐 General"):
                    formatted_msg = f"{timestamp}{prefix}[{target}] {message}\n"

            if box:
                current_state = box.cget("state")
                if current_state == "disabled":
                    box.configure(state="normal")

                box.insert("end", formatted_msg)
                box.see("end")

                if current_state == "disabled":
                    box.configure(state="disabled")

            # 🟢 ACTUALIZAR AUTOMÁTICAMENTE EL ÍCONO Y TOOLTIP SEGÚN EL LOG SI TIENE TAB
            if target in self.console_boxes and target not in ("General", "🌐 General"):
                msg_upper = message.upper()

                if "POSICIÓN ACTIVA DETECTADA" in msg_upper or "OPERACIÓN DETECTADA" in msg_upper or "OPERACIÓN ABIERTA" in msg_upper:
                    self.set_symbol_status(target, "OPEN_ORDER", f"[{target}] Operación abierta activa. Modificando SL/TP y protegiendo...")
                elif "MONITOREO DETENIDO" in msg_upper:
                    self.set_symbol_status(target, "INACTIVE", f"[{target}] Monitoreo apagado")
                elif "CERRADA" in msg_upper or "CIERRE PREMATURO" in msg_upper or "SL ALCANZADO" in msg_upper or "TP ALCANZADO" in msg_upper or "STOP LOSS" in msg_upper or "TAKE PROFIT" in msg_upper:
                    self.set_symbol_status(target, "WAITING", f"[{target}] Operación cerrada. Reanudando análisis en espera de confluencias")
                elif "SIN ÓRDENES ABIERTAS" in msg_upper or "ANALIZANDO" in msg_upper or "MONITOREO ACTIVADO" in msg_upper or "PRÓXIMO ANÁLISIS" in msg_upper:
                    self.set_symbol_status(target, "WAITING", f"[{target}] Activo: Analizando velas y buscando confluencia de entrada")
                elif "FILTRO HORARIO" in msg_upper or "MERCADO CERRADO" in msg_upper or "FILTRO CORRELACIÓN" in msg_upper or level in ["WARN", "WARNING"]:
                    if self.symbol_status.get(target) != "OPEN_ORDER":
                        self.set_symbol_status(target, "WARNING", f"[{target}] Advertencia / Fuera de sesión o filtro activo")
                elif level == "ERROR":
                    if self.symbol_status.get(target) != "OPEN_ORDER":
                        self.set_symbol_status(target, "ERROR", f"[{target}] Error reportado en el procesamiento")

        self.run_on_gui_thread(_update_gui)
