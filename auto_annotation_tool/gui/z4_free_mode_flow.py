from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING

from ..campaign_manager import CAMPAIGN

if TYPE_CHECKING:
    from .tab_training import TrainingTab


def bind_training_route_card(host: "TrainingTab", widget, mode: str):
    if widget is None:
        return

    try:
        widget.configure(cursor="hand2")
    except Exception:
        pass

    try:
        widget.bind("<Button-1>", lambda _e, m=mode: host._set_step4_dataset_mode(m), add="+")
        widget.bind("<Enter>", lambda _e, m=mode: set_training_route_card_hover(host, m, True), add="+")
        widget.bind("<Leave>", lambda _e, m=mode: set_training_route_card_hover(host, m, False), add="+")
    except Exception:
        pass


def set_training_route_card_hover(host: "TrainingTab", mode: str, enabled: bool):
    host._free_route_hover_mode = mode if enabled else None
    refresh_free_training_route_cards(host)


def _is_training_input_dataset_ready(dataset_value: str) -> bool:
    value = str(dataset_value or "").strip()
    if not value:
        return False
    try:
        path = Path(value)
        if path.is_file():
            return path.name.lower() == "data.yaml"
        if path.is_dir():
            return (path / "data.yaml").exists()
    except Exception:
        pass
    return False


def _format_training_input_dataset(host: "TrainingTab", dataset_value: str, target: str = "") -> str:
    target = str(target or "").strip().lower()
    dataset_label = "Dataset YOLO Pose" if target == "plate" else "Dataset YOLO Detect"
    value = str(dataset_value or "").strip()
    if not value:
        return f"{dataset_label}: brak - wróć do PZ1 i przygotuj wejście treningowe."
    try:
        display = host._format_workspace_relative_path(value)
    except Exception:
        display = value
    return f"{dataset_label}: {display}"


def refresh_training_input_summary(host: "TrainingTab"):
    frame = getattr(host, "training_input_summary_frame", None)
    if frame is None:
        return

    palette = getattr(host.app, "palette", {})
    panel_alt = palette.get("panel_alt", "#2d2d30")
    field = palette.get("field", panel_alt)
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    accent = palette.get("accent", "#0e639c")
    success = palette.get("success", "#4ec9b0")
    accent_text = palette.get("accent_text", "#ffffff")

    try:
        target = host._get_selected_training_target()
    except Exception:
        target = getattr(host, "_step4_dataset_mode", "char")
    target = str(target or "char").strip().lower()
    if target not in ("char", "plate"):
        target = "char"

    try:
        target_label = host._format_training_target_label(target)
    except Exception:
        target_label = "Tablice" if target == "plate" else "Znaki tablic"

    try:
        dataset_value = str(host.dataset_var.get() or "").strip()
    except Exception:
        dataset_value = ""
    dataset_ready = _is_training_input_dataset_ready(dataset_value)
    if dataset_ready and not CAMPAIGN.get_active_project_name():
        variant_guard = getattr(host, "_is_free_training_dataset_variant_selected", None)
        if callable(variant_guard):
            try:
                dataset_ready = bool(variant_guard(dataset_value))
            except Exception:
                dataset_ready = False

    context = getattr(host, "_last_training_input_context", None)
    source = str(getattr(context, "source", "") or "").strip().lower()
    source_labels = {
        "z2_export": "Źródło: eksport Z2",
        "pz1": "Źródło: PZ1",
        "pz2_variant": "Źródło: wariant wybrany w PZ2",
    }
    source_text = source_labels.get(source, "Źródło: wariant wybrany w PZ2")

    badge_text = "WEJŚCIE GOTOWE" if dataset_ready else "BRAK WEJŚCIA"
    badge_color = success if dataset_ready else panel_alt
    badge_fg = accent_text if dataset_ready else muted
    border_color = accent if dataset_ready else border
    summary_bg = field if dataset_ready else panel_alt
    dataset_text = _format_training_input_dataset(host, dataset_value, target)
    if dataset_value and not dataset_ready and not CAMPAIGN.get_active_project_name():
        dataset_label = "Dataset YOLO Pose" if target == "plate" else "Dataset YOLO Detect"
        dataset_text = f"{dataset_label}: wybierz gotowy wariant z listy albo wróć do PZ1 i utwórz nowy."

    try:
        frame.configure(
            bg=summary_bg,
            highlightbackground=border_color,
            highlightcolor=border_color,
            highlightthickness=0,
            cursor="",
        )
    except Exception:
        pass

    for attr, text, color in (
        ("training_input_route_lbl", f"Tor: {target_label}", fg),
        ("training_input_dataset_lbl", dataset_text, fg if dataset_ready else muted),
        ("training_input_source_lbl", source_text, muted),
    ):
        widget = getattr(host, attr, None)
        if widget is None:
            continue
        try:
            widget.configure(text=text, bg=summary_bg, fg=color, cursor="")
        except Exception:
            pass

    badge = getattr(host, "training_input_badge_lbl", None)
    if badge is not None:
        try:
            badge.configure(
                text=badge_text,
                bg=badge_color,
                fg=badge_fg,
                highlightbackground=border,
                highlightcolor=border,
                cursor="",
            )
        except Exception:
            pass

    intro = getattr(host, "free_training_route_intro_lbl", None)
    if intro is not None:
        try:
            campaign_active = bool(CAMPAIGN.get_active_project_name())
            intro.configure(
                text=(
                    "PZ2 w kampanii korzysta z toru i datasetu ustawionych przez workflow projektu. "
                    "To podgląd wejścia treningowego przed uruchomieniem treningu."
                    if campaign_active
                    else "PZ2 nie wybiera już toru samodzielnie. Korzysta z kontekstu przygotowanego w PZ1 albo przekazanego z eksportu Z2."
                )
            )
        except Exception:
            pass

    button = getattr(host, "training_input_change_btn", None)
    if button is not None:
        try:
            button.pack_forget()
        except Exception:
            pass

    title = getattr(host, "free_training_route_title_lbl", None)
    if title is not None:
        try:
            title.configure(text="Wejście treningowe")
        except Exception:
            pass


def refresh_free_training_route_cards(host: "TrainingTab"):
    refresh_training_input_summary(host)

    cards = getattr(host, "_free_training_route_cards", {})
    if not cards:
        return

    palette = getattr(host.app, "palette", {})
    panel_bg = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    hover_bg = palette.get("button_hover", panel_alt)
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    accent = palette.get("accent", "#0e639c")
    accent_text = palette.get("accent_text", "#ffffff")
    success = palette.get("success", "#4ec9b0")
    surface_info = palette.get("surface_info", hover_bg)
    surface_success = palette.get("surface_success", hover_bg)

    active_mode = host._get_selected_training_target()
    hover_mode = getattr(host, "_free_route_hover_mode", None)

    for mode, widgets in cards.items():
        frame = widgets.get("frame")
        title = widgets.get("title")
        badge_row = widgets.get("badge_row")
        badge = widgets.get("badge")
        choice_badge = widgets.get("choice_badge")
        desc = widgets.get("desc")
        meta = widgets.get("meta")
        if frame is None:
            continue

        is_active = mode == active_mode
        is_hover = mode == hover_mode
        if mode == "plate":
            accent_color = accent
            active_bg = surface_info
        else:
            accent_color = success
            active_bg = surface_success

        bg = active_bg if is_active else (hover_bg if is_hover else panel_alt)
        frame_border = accent_color if is_active else border
        title_fg = accent_color if is_active else fg
        badge_bg = accent_color if is_active else panel_bg
        badge_fg = accent_text if is_active else muted
        choice_text = "WYBRANO" if is_active else "DO WYBORU"
        choice_bg = accent_color if is_active else (hover_bg if is_hover else panel_bg)
        choice_fg = accent_text if is_active else (fg if is_hover else muted)
        desc_fg = fg if is_active else muted

        try:
            frame.configure(bg=bg, highlightbackground=frame_border, highlightcolor=frame_border)
        except Exception:
            pass
        try:
            if badge_row is not None:
                badge_row.configure(bg=bg)
        except Exception:
            pass
        for label, color in ((title, title_fg), (desc, desc_fg), (meta, muted)):
            try:
                if label is not None:
                    label.configure(bg=bg, fg=color)
            except Exception:
                pass
        try:
            if badge is not None:
                badge.configure(
                    bg=badge_bg,
                    fg=badge_fg,
                    highlightbackground=frame_border,
                    highlightcolor=frame_border
                )
        except Exception:
            pass
        try:
            if choice_badge is not None:
                choice_badge.configure(
                    text=choice_text,
                    bg=choice_bg,
                    fg=choice_fg,
                    highlightbackground=frame_border,
                    highlightcolor=frame_border,
                )
        except Exception:
            pass

    title = getattr(host, "free_training_route_title_lbl", None)
    if title is not None:
        try:
            title.configure(text=("Wejście treningowe" if not CAMPAIGN.get_active_project_name() else "Wybrany tor treningu"))
        except Exception:
            pass


def refresh_free_training_route_ui(host: "TrainingTab"):
    route_host = getattr(host, "free_training_route_host", None)
    if route_host is None:
        return

    try:
        pack_options = {"anchor": tk.W, "fill": tk.X, "pady": (0, 12)}
        parent = route_host.master
        siblings = []
        try:
            siblings = [widget for widget in parent.pack_slaves() if widget is not route_host]
        except Exception:
            siblings = []
        if siblings:
            route_host.pack(**pack_options, before=siblings[0])
        else:
            route_host.pack(**pack_options)
    except Exception:
        pass

    refresh_free_training_route_cards(host)
    host._refresh_training_start_state()


def update_step4_notebook_mode(host: "TrainingTab"):
    if not hasattr(host, "main_nb"):
        return

    campaign_active = bool(CAMPAIGN.get_active_project_name())
    dataset_label = "[PZ1] Produkcja datasetu"
    train_label = "[PZ2] Trening i analiza"

    try:
        host.main_nb.tab(host.tab_train, text=train_label)
    except Exception:
        pass

    if not getattr(host, "_step4_dataset_tab_visible", False):
        try:
            host.main_nb.insert(0, host.tab_dataset, text=dataset_label)
        except Exception:
            try:
                host.main_nb.add(host.tab_dataset, text=dataset_label)
            except Exception:
                pass
        host._step4_dataset_tab_visible = True
    else:
        try:
            host.main_nb.tab(host.tab_dataset, text=dataset_label)
        except Exception:
            pass

    if campaign_active:
        return

    try:
        current_tab = str(host.main_nb.select() or "").strip()
        if current_tab not in {str(host.tab_dataset), str(host.tab_train)}:
            host.main_nb.select(host.tab_dataset)
    except Exception:
        pass
