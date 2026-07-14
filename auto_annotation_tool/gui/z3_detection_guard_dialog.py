#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Dialog ochrony wyników PZ2 przed uruchomieniem detekcji znaków."""

import tkinter as tk

from .web_slim_scrollbar import blend_hex_colors

def prompt_pz2_detection_guard_options(host, method_key: str) -> dict | None:
    self = host
    method_key = self._normalize_detection_method_key(method_key or self._get_detection_method_key())
    method_has_yolo = method_key in {"YOLO", "BOTH", "YOLO_OCR"}
    counts = self._build_pz2_detection_guard_counts()
    result = {"value": None}

    palette = getattr(self.app, "palette", {}) or {}
    panel_bg = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    success = palette.get("success", "#2ecc71")
    warning = palette.get("warning", "#f1c40f")
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

    dialog = tk.Toplevel(self.frame)
    try:
        dialog.withdraw()
    except Exception:
        pass

    styler = getattr(self.app, "style_dialog_window", None)
    if callable(styler):
        try:
            styler(
                dialog,
                title="Ochrona i refiner wyników PZ2",
                geometry="700x575",
                parent=self.frame,
            )
        except Exception:
            dialog.title("Ochrona i refiner wyników PZ2")
            dialog.resizable(False, False)
    else:
        dialog.title("Ochrona i refiner wyników PZ2")
        dialog.resizable(False, False)

    try:
        dialog.configure(bg=panel_bg, highlightbackground=panel_bg, highlightcolor=panel_bg)
    except Exception:
        pass

    surface_builder = getattr(self.app, "_build_themed_dialog_surface", None)
    if callable(surface_builder):
        try:
            surface = surface_builder(dialog, tone="info")
        except Exception:
            surface = tk.Frame(dialog, bg=panel_bg, bd=0, highlightthickness=0)
            surface.pack(fill=tk.BOTH, expand=True)
    else:
        surface = tk.Frame(dialog, bg=panel_bg, bd=0, highlightthickness=0)
        surface.pack(fill=tk.BOTH, expand=True)

    body = tk.Frame(surface, bg=panel_bg, bd=0, highlightthickness=0)
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

    tk.Label(
        body,
        text="Detekcja może nadpisać istniejące boxy znaków",
        bg=panel_bg,
        fg=fg,
        font=("Segoe UI", 10, "bold"),
        anchor="w",
        justify=tk.LEFT,
    ).pack(anchor=tk.W, fill=tk.X)

    tk.Label(
        body,
        text=(
            "Wybierz, czy pipeline ma chronić ręczne poprawki i tablice ze statusem perfect. "
            "Refiner działa tylko jako bezpieczna korekta geometrii boxów, bez zmiany odczytu znaków."
        ),
        bg=panel_bg,
        fg=muted,
        font=("Segoe UI", 9),
        anchor="w",
        justify=tk.LEFT,
        wraplength=640,
    ).pack(anchor=tk.W, fill=tk.X, pady=(4, 7))

    summary = tk.Frame(body, bg=panel_alt, bd=0, highlightthickness=1, highlightbackground=border)
    summary.pack(fill=tk.X, pady=(0, 8))
    for col, weight in ((0, 1), (1, 1), (2, 1), (3, 1)):
        summary.grid_columnconfigure(col, weight=weight)

    summary_rows = [
        ("Wszystkie tablice", int(counts.get("total", 0)), "Tablice cropy w PZ2"),
        ("Ze statusem perfect", int(counts.get("perfect", 0)), "Chronione domyślnie"),
        ("Perfect z OCR", int(counts.get("perfect_ocr", 0)), "Perfect uzyskane przez OCR"),
        ("Z ręcznymi boxami", int(counts.get("manual", 0)), f"{int(counts.get('manual_boxes', 0))} boxów"),
    ]
    for idx, (label, value, note) in enumerate(summary_rows):
        cell = tk.Frame(summary, bg=panel_alt, bd=0, highlightthickness=0)
        cell.grid(row=0, column=idx, sticky="nsew", padx=(8 if idx == 0 else 4, 8 if idx == len(summary_rows) - 1 else 4), pady=6)
        tk.Label(
            cell,
            text=f"{int(value)}",
            bg=panel_alt,
            fg=success if int(value) > 0 else muted,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        ).pack(anchor=tk.W, fill=tk.X)
        tk.Label(
            cell,
            text=str(label),
            bg=panel_alt,
            fg=muted,
            font=("Segoe UI", 7, "bold"),
            anchor="w",
        ).pack(anchor=tk.W, fill=tk.X)
        tk.Label(
            cell,
            text=str(note),
            bg=panel_alt,
            fg=blend_hex_colors(muted, panel_alt, 0.18),
            font=("Segoe UI", 7),
            anchor="w",
        ).pack(anchor=tk.W, fill=tk.X)

    protect_manual_var = tk.BooleanVar(value=True)
    protect_perfect_var = tk.BooleanVar(value=bool(self.detect_protect_perfect_var.get()))
    refine_perfect_yolo_var = tk.BooleanVar(value=bool(self.detect_refine_perfect_yolo_var.get()))
    process_perfect_only_var = tk.BooleanVar(value=False)
    try:
        continuity_guard_default = bool(self.detect_refiner_continuity_guard_var.get())
    except Exception:
        continuity_guard_default = True
    continuity_guard_var = tk.BooleanVar(value=continuity_guard_default)

    options = tk.Frame(body, bg=panel_bg, bd=0, highlightthickness=0)
    options.pack(fill=tk.X)

    def add_check(text, variable, note, *, disabled=False):
        row = tk.Frame(options, bg=panel_bg, bd=0, highlightthickness=0)
        row.pack(fill=tk.X, pady=(0, 4))
        chk = tk.Checkbutton(
            row,
            text=text,
            variable=variable,
            bg=panel_bg,
            fg=fg,
            activebackground=panel_bg,
            activeforeground=fg,
            selectcolor=panel_alt,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            state=(tk.DISABLED if disabled else tk.NORMAL),
        )
        chk.pack(anchor=tk.W, fill=tk.X)
        tk.Label(
            row,
            text=note,
            bg=panel_bg,
            fg=muted if not disabled else blend_hex_colors(muted, panel_bg, 0.45),
            font=("Segoe UI", 7),
            anchor="w",
            justify=tk.LEFT,
            wraplength=620,
        ).pack(anchor=tk.W, fill=tk.X, padx=(24, 0), pady=(0, 0))
        return chk

    add_check(
        "Chroń ręczne boxy znaków",
        protect_manual_var,
        "Manualne boxy są chronione bezwzględnie. OCR/YOLO może uzupełniać lub poprawiać pozostałe ramki, ale nie nadpisze ręcznych korekt.",
        disabled=True,
    )
    perfect_count = int(counts.get("perfect", 0) or 0)
    perfect_scope_check = add_check(
        "Przetwarzaj tylko tablice perfect",
        process_perfect_only_var,
        "Ogranicza ten przebieg do tablic ze statusem perfect. Przydatne przy refinerze boxów, bez uruchamiania detekcji na całej dużej liście.",
        disabled=perfect_count <= 0,
    )
    add_check(
        "Chroń tablice ze statusem perfect",
        protect_perfect_var,
        "Perfect oznacza, że tekst znaków zgadza się z oczekiwanym odczytem z nazwy pliku. Domyślnie nie niszczymy takiego wyniku.",
    )
    refine_check = add_check(
        "Włącz refiner boxów dla tablic perfect",
        refine_perfect_yolo_var,
        "Refiner używa propozycji YOLO tylko jako punktu startowego. Zawęża lub przesuwa box, jeśli poprawia pokrycie właściwego znaku. Opcja działa tylko w pipeline z YOLO.",
        disabled=not method_has_yolo,
    )

    continuity_check = add_check(
        "Pilnuj ciągłości znaku",
        continuity_guard_var,
        "Dodatkowy bezpiecznik refinera: box musi obejmować tę samą spójną strukturę znaku i nie może przejmować sąsiedniego znaku.",
        disabled=not method_has_yolo,
    )

    def sync_refine_state(*_args):
        try:
            refiner_available = method_has_yolo and bool(protect_perfect_var.get())
            state = tk.NORMAL if refiner_available else tk.DISABLED
            refine_check.configure(state=state)
            continuity_state = tk.NORMAL if (refiner_available and bool(refine_perfect_yolo_var.get())) else tk.DISABLED
            continuity_check.configure(state=continuity_state)
            perfect_scope_check.configure(state=(tk.NORMAL if perfect_count > 0 else tk.DISABLED))
        except Exception:
            pass

    try:
        protect_perfect_var.trace_add("write", sync_refine_state)
        refine_perfect_yolo_var.trace_add("write", sync_refine_state)
        sync_refine_state()
    except Exception:
        pass

    hint_color = warning if int(counts.get("perfect", 0) or 0) > 0 or int(counts.get("manual", 0) or 0) > 0 else muted
    tk.Label(
        body,
        text=(
            "Jeśli chcesz przebudować automatyczne wyniki od zera, możesz odznaczyć ochronę perfectów. "
            "Ręczne korekty pozostają chronione."
        ),
        bg=panel_bg,
        fg=hint_color,
        font=("Segoe UI", 8, "bold"),
        anchor="w",
        justify=tk.LEFT,
        wraplength=640,
    ).pack(anchor=tk.W, fill=tk.X, pady=(4, 0))

    buttons = tk.Frame(body, bg=panel_bg, bd=0, highlightthickness=0, height=46)
    buttons.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
    try:
        buttons.pack_propagate(False)
    except Exception:
        pass

    def close(value):
        if value:
            try:
                self.detect_protect_manual_var.set(True)
                self.detect_protect_perfect_var.set(bool(protect_perfect_var.get()))
                self.detect_refine_perfect_yolo_var.set(bool(refine_perfect_yolo_var.get()))
                self.detect_refiner_continuity_guard_var.set(bool(continuity_guard_var.get()))
                self._save_local_setting("char_detect_protect_manual", True)
                self._save_local_setting("char_detect_protect_perfect", bool(self.detect_protect_perfect_var.get()))
                self._save_local_setting("char_detect_refine_perfect_yolo", bool(self.detect_refine_perfect_yolo_var.get()))
                self._save_local_setting("char_detect_refiner_continuity_guard", bool(self.detect_refiner_continuity_guard_var.get()))
                self._refresh_detection_refiner_guard_label()
            except Exception:
                pass
            use_perfect_refiner = bool(
                method_has_yolo and protect_perfect_var.get() and refine_perfect_yolo_var.get()
            )
            use_continuity_guard = bool(use_perfect_refiner and continuity_guard_var.get())
            result["value"] = {
                "protect_manual_boxes": True,
                "protect_perfect_plates": bool(protect_perfect_var.get()),
                "allow_yolo_geometry_on_perfect": use_perfect_refiner,
                "use_perfect_box_refiner": use_perfect_refiner,
                "use_perfect_refiner_continuity_guard": use_continuity_guard,
                "process_scope": "perfect_only" if bool(process_perfect_only_var.get()) else "all",
                "counts": dict(counts),
            }
        else:
            result["value"] = None
        try:
            dialog.destroy()
        except Exception:
            pass

    def make_action_button(parent, text, command, *, primary=False):
        fill = (
            blend_hex_colors(success, panel_alt, 0.28)
            if primary
            else blend_hex_colors(panel_alt, panel_bg, 0.18)
        )
        outline = success if primary else border
        text_color = self._get_readable_text_color(fill, preferred=fg if not primary else "#ffffff")
        active_fill = (
            blend_hex_colors(success, fill, 0.18)
            if primary
            else blend_hex_colors(fill, success, 0.08)
        )
        button_host = tk.Frame(
            parent,
            bg=outline,
            bd=0,
            highlightthickness=0,
            width=176 if primary else 104,
            height=36,
        )
        button_host.pack_propagate(False)
        button = tk.Button(
            button_host,
            text=str(text),
            command=command,
            bg=fill,
            fg=text_color,
            activebackground=active_fill,
            activeforeground=self._get_readable_text_color(active_fill, preferred=text_color),
            font=("Segoe UI", 9),
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
            padx=10,
            pady=3,
            cursor="hand2",
            takefocus=True,
        )
        button.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        return button_host

    make_action_button(buttons, "Anuluj", lambda: close(False)).pack(side=tk.RIGHT)
    make_action_button(buttons, "Zatwierdź i uruchom", lambda: close(True), primary=True).pack(side=tk.RIGHT, padx=(0, 8))

    try:
        dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))
        dialog.bind("<Escape>", lambda _e: close(False))
        dialog.bind("<Return>", lambda _e: close(True))
    except Exception:
        pass

    try:
        dialog.update_idletasks()
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
    except Exception:
        pass

    dialog.wait_window()
    return result.get("value")


