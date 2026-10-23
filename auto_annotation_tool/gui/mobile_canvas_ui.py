"""Small local Tk presentation components used only by mobile review.

No global theme changes, no session writes, no inference. Colors have text
labels as well; no state is communicated by color alone.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def palette(widget, background):
    try:
        rgb = widget.winfo_rgb(background)
        dark = sum(rgb) / (3 * 65535) < .45
    except tk.TclError:
        dark = False
    if dark:
        return dict(bg="#17232D", surface="#21323E", fg="#EBF2F6", muted="#B5C4CE",
                    border="#3A5364", blue="#77CBF0", blue_bg="#193E54",
                    green="#83DEB5", green_bg="#203F36", amber="#FFD087", amber_bg="#493A25",
                    red="#FF9CA7", red_bg="#4A2932", purple="#C8B4FF", purple_bg="#35334C")
    return dict(bg="#F2F5F8", surface="#FFFFFF", fg="#213547", muted="#5E7283",
                border="#D7E1E8", blue="#14628B", blue_bg="#E5F2FA",
                green="#176B4D", green_bg="#E4F4EC", amber="#86540E", amber_bg="#FFF2D9",
                red="#AB3545", red_bg="#FDECEF", purple="#6952A5", purple_bg="#F0EBFA")


def label(parent, text="", *, p, size=10, bold=False, fg=None, bg=None, wrap=0):
    return tk.Label(parent, text=text, bg=bg or p["surface"], fg=fg or p["fg"],
                    font=("Segoe UI", size, "bold" if bold else "normal"),
                    anchor="w", justify="left", wraplength=wrap)


class MetricCard(tk.Frame):
    def __init__(self, parent, title, *, p, tone="blue", compact=False):
        super().__init__(parent, bg=p["surface"], highlightbackground=p["border"], highlightthickness=1)
        self.p, self.tone = p, tone
        tk.Frame(self, bg=p[tone], height=3).pack(fill="x")
        inside = tk.Frame(self, bg=p["surface"], padx=10 if compact else 14, pady=7 if compact else 11)
        inside.pack(fill="both", expand=True)
        self.title = label(inside, title, p=p, size=9, bold=True, fg=p["muted"])
        self.title.configure(width=1)
        self.title.pack(fill="x")
        self.value = label(inside, "—", p=p, size=18 if compact else 23, bold=True, fg=p[tone])
        self.value.configure(width=1)
        self.value.pack(fill="x", pady=(3, 0))
        self.note = label(inside, "", p=p, size=9, fg=p["muted"])
        self.note.configure(width=1)
        self.note.pack(fill="x", pady=(2, 0))
        self._wrap_width = None
        inside.bind("<Configure>", self._wrap, add="+")

    def _wrap(self, event):
        width = max(55, event.width - 28)
        if width == self._wrap_width:
            return
        self._wrap_width = width
        for w in (self.title, self.value, self.note):
            w.configure(wraplength=width)

    def set(self, value, note=""):
        self.value.configure(text=value)
        self.note.configure(text=note)
        if note:
            self.note.pack(fill="x", pady=(2, 0))
        else:
            self.note.pack_forget()


class Disclosure(tk.Frame):
    """A full-width section header, not an action-looking CTA button."""
    def __init__(self, parent, title, *, p, opened=False, command=None):
        super().__init__(parent, bg=p["surface"], highlightbackground=p["border"], highlightthickness=1)
        self.opened, self.title, self.command = opened, title, command
        self.header = tk.Label(self, bg=p["blue_bg"], fg=p["blue"], cursor="hand2", takefocus=True,
                               font=("Segoe UI", 10, "bold"), anchor="w", padx=10, pady=9,
                               highlightthickness=1, highlightbackground=p["blue_bg"], highlightcolor=p["blue"])
        self.header.pack(fill="x")
        self.body = tk.Frame(self, bg=p["surface"], padx=10, pady=8)
        for seq in ("<Button-1>", "<Return>", "<space>"):
            self.header.bind(seq, self.toggle)
        self._sync()

    def _sync(self):
        self.header.configure(text=("▾  " if self.opened else "▸  ") + self.title)
        if self.opened:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()

    def toggle(self, event=None):
        self.opened = not self.opened
        self._sync()
        if self.command:
            self.command(self.opened)
        return "break"


class ScrollPane(tk.Frame):
    def __init__(self, parent, *, p):
        super().__init__(parent, bg=p["bg"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=p["bg"], bd=0, highlightthickness=0, yscrollincrement=22)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=bar.set)
        self.body = tk.Frame(self.canvas, bg=p["bg"])
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.item, width=e.width))
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.bind_wheel(self)

    def wheel(self, event):
        num, delta = getattr(event, "num", None), getattr(event, "delta", 0)
        if num not in (4, 5) and not delta:
            return None
        step = -1 if num == 4 or (num != 5 and delta > 0) else 1
        self.canvas.yview_scroll(step * 3, "units")
        return "break"

    def bind_wheel(self, widget):
        # Called again after dynamic content is created; replace, never double bind.
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(seq, self.wheel)
        for child in widget.winfo_children():
            self.bind_wheel(child)
