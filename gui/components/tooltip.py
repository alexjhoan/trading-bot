import tkinter as tk
from typing import Optional


class ToolTip:
    """
    Crea un tooltip elegante flotante cuando el cursor se posiciona sobre cualquier widget de Tkinter / CustomTkinter.
    """
    def __init__(self, widget: tk.Widget, text: str = "", delay_ms: int = 400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip_window: Optional[tk.Toplevel] = None
        self.after_id: Optional[str] = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")

    def set_text(self, text: str) -> None:
        self.text = text
        if self.tip_window:
            self._update_text()

    def update_text(self, text: str) -> None:
        """Alias para set_text."""
        self.set_text(text)

    def _on_enter(self, event=None) -> None:
        self._cancel_schedule()
        if not self.text:
            return
        self.after_id = self.widget.after(self.delay_ms, self._show_tip)

    def _on_leave(self, event=None) -> None:
        self._cancel_schedule()
        self._hide_tip()

    def _cancel_schedule(self) -> None:
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _show_tip(self) -> None:
        if self.tip_window or not self.text:
            return

        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        except Exception:
            return

        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        self.tip_window.attributes("-topmost", True)

        label = tk.Label(
            self.tip_window,
            text=self.text,
            justify=tk.LEFT,
            background="#1e2330",
            foreground="#e2e8f0",
            relief=tk.SOLID,
            borderwidth=1,
            padx=8,
            pady=4,
            font=("Segoe UI", 9, "normal")
        )
        label.pack(ipadx=1)

    def _update_text(self) -> None:
        if self.tip_window:
            for child in self.tip_window.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(text=self.text)

    def _hide_tip(self) -> None:
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None
