from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING

from ..campaign_manager import CAMPAIGN
from .z4_campaign_flow import return_to_campaign_from_step4
from .z4_flow_models import TrainingInputContext

if TYPE_CHECKING:
    from .tab_training import TrainingTab


def _build_plate_ready_dataset_summary(host: "TrainingTab") -> str:
    try:
        dataset_value = str(host.dataset_var.get() or "").strip()
    except Exception:
        dataset_value = ""
    if not dataset_value:
        return ""

    try:
        dataset_path = Path(dataset_value)
        yaml_path = dataset_path / "data.yaml" if dataset_path.is_dir() else dataset_path
        if not yaml_path.exists() or yaml_path.name.lower() != "data.yaml":
            return ""
        dataset_root = yaml_path.parent
    except Exception:
        return ""

    try:
        inferred_target = str(host._infer_dataset_target(str(dataset_root)) or "").strip().lower()
        if inferred_target and inferred_target != "plate":
            return ""
    except Exception:
        pass

    try:
        display_path = host._format_workspace_relative_path(dataset_root)
    except Exception:
        display_path = str(dataset_root)

    try:
        counts = host._get_dataset_split_image_counts(dataset_root)
    except Exception:
        counts = {}

    total = int(counts.get("total", 0) or 0)
    if total > 0:
        split_text = (
            f"Split: train={int(counts.get('train', 0) or 0)}, "
            f"val={int(counts.get('val', 0) or 0)}, "
            f"test={int(counts.get('test', 0) or 0)}."
        )
    else:
        split_text = "Split: data.yaml wykryty, licznik obrazów nie został jeszcze obliczony."

    return (
        "Gotowy wariant datasetu tablic jest już podpięty jako wejście treningowe.\n"
        f"Dataset: {display_path}\n"
        f"{split_text}\n"
        "Możesz przejść dalej do PZ2 i wybrać go z listy wariantów bez wskazywania XML i obrazów."
    )


def refresh_step4_campaign_builder_inputs_ui(host: "TrainingTab"):
    vm = host._get_step4_dataset_workflow_view_model()

    def _set_pack_visible(widget, visible: bool, **pack_kwargs):
        if widget is None:
            return
        try:
            manager = str(widget.winfo_manager())
        except Exception:
            manager = ""
        try:
            if visible:
                if manager != "pack":
                    widget.pack(**pack_kwargs)
                elif pack_kwargs:
                    widget.pack_configure(**pack_kwargs)
            elif manager == "pack":
                widget.pack_forget()
        except Exception:
            pass

    try:
        route_manager = str(host.step4_route_panel_frame.winfo_manager())
    except Exception:
        route_manager = ""

    if not bool(vm.show_route_panel):
        if route_manager == "pack":
            try:
                host.step4_route_panel_frame.pack_forget()
            except Exception:
                pass
    else:
        if route_manager != "pack":
            try:
                host.step4_route_panel_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8), before=host.step4_mode_right_host)
            except Exception:
                pass

    try:
        if vm.mode == "plate":
            context = getattr(host, "_last_training_input_context", None)
            source = str(getattr(context, "source", "") or "").strip().lower()
            if bool(vm.in_campaign):
                creator_intro = (
                    "Dataset tablic powstaje z zatwierdzonych anotacji projektu. "
                    "Ręczny wybór XML i folderu obrazów jest tutaj ukryty, bo źródła przygotował wcześniejszy etap."
                )
            elif source == "z2_export":
                creator_intro = (
                    "Masz już gotowy dataset tablic przekazany z eksportu Z2. "
                    "Ten panel jest miejscem jawnego tworzenia nowych wariantów: użyj go tylko wtedy, "
                    "gdy chcesz zbudować kolejny wariant YOLO Pose z pliku anotacji XML i zgodnego folderu obrazów. "
                    "Utworzone warianty są dostępne w PZ2 na liście wariantów."
                )
            else:
                creator_intro = (
                    "PZ1 tworzy wariant datasetu YOLO Pose. Wskaż plik anotacji XML oraz zgodny folder obrazów, "
                    "a program zapisze osobny wariant treningowy z własnym splitem train / val / test. "
                    "Utworzone tutaj datasety są dostępne w PZ2 na liście wariantów."
                )
            host._set_training_widget_text(host.creator_intro_lbl, creator_intro)
            host._set_training_widget_text(
                host.btn_step4_create,
                "Utwórz wariant datasetu",
            )
            try:
                host._refresh_dataset_creator_cta_state()
            except Exception:
                pass
    except Exception:
        pass

    try:
        if vm.mode == "plate":
            in_campaign = bool(vm.in_campaign)
            source_mode_frame = getattr(host, "creator_source_mode_frame", None)
            ready_label = getattr(host, "creator_ready_dataset_lbl", None)
            ready_radio = getattr(host, "creator_source_ready_radio", None)
            xml_radio = getattr(host, "creator_source_xml_radio", None)
            xml_row = getattr(host, "creator_xml_row", None)
            images_row = getattr(host, "creator_images_row", None)
            source_summary = getattr(host, "creator_source_summary_lbl", None)
            output_row = getattr(host, "creator_output_row", None)
            ratios_frame = getattr(host, "creator_ratios_frame", None)
            create_frame = getattr(host, "btn_step4_create_frame", None)
            progress = getattr(host, "ds_progress", None)
            status = getattr(host, "ds_status", None)

            if in_campaign:
                _set_pack_visible(source_mode_frame, False)
                try:
                    host._set_creator_source_mode("xml")
                except Exception:
                    pass
                if ready_label is not None:
                    _set_pack_visible(ready_label, False)
                _set_pack_visible(xml_row, False)
                _set_pack_visible(images_row, False)
                if source_summary is not None:
                    host._set_training_widget_text(source_summary, str(vm.creator_summary or ""))
                    _set_pack_visible(source_summary, True, anchor=tk.W, fill=tk.X, pady=(0, 8), after=host.creator_intro_lbl)
                _set_pack_visible(output_row, True, fill=tk.X, pady=2, after=source_summary)
                _set_pack_visible(ratios_frame, True, fill=tk.X, pady=10, after=output_row)
                _set_pack_visible(create_frame, True, anchor=tk.W, pady=(10, 5))
                _set_pack_visible(progress, True, fill=tk.X, pady=2)
                _set_pack_visible(status, True, anchor=tk.W)
            else:
                ready_summary = _build_plate_ready_dataset_summary(host)
                _set_pack_visible(source_mode_frame, True, fill=tk.X, pady=(0, 10), after=host.creator_intro_lbl)
                try:
                    if ready_radio is not None:
                        ready_radio.configure(state=tk.NORMAL)
                    if xml_radio is not None:
                        xml_radio.configure(state=tk.NORMAL)
                except Exception:
                    pass

                try:
                    xml_raw = str(host.cvat_xml_var.get() or "").strip()
                    images_raw = str(host.cvat_images_var.get() or "").strip()
                except Exception:
                    xml_raw = images_raw = ""

                try:
                    current_mode = host._get_creator_source_mode()
                    if current_mode not in {"ready", "xml"}:
                        host._set_creator_source_mode("xml")
                except Exception:
                    pass

                try:
                    mode = host._get_creator_source_mode()
                except Exception:
                    mode = "xml"
                show_ready_dataset = mode == "ready"
                show_xml_builder = not show_ready_dataset

                if ready_label is not None:
                    if show_ready_dataset:
                        host._set_training_widget_text(
                            ready_label,
                            ready_summary
                            or (
                                "Nie podpięto jeszcze gotowego datasetu tablic.\n"
                                "Możesz przejść dalej i wybrać gotowy wariant w PZ2, "
                                "albo przełączyć poniżej na utworzenie nowego wariantu z XML + obrazów."
                            ),
                        )
                        _set_pack_visible(
                            ready_label,
                            True,
                            anchor=tk.W,
                            fill=tk.X,
                            pady=(0, 8),
                            after=source_mode_frame,
                        )
                    else:
                        _set_pack_visible(ready_label, False)

                if source_summary is not None:
                    _set_pack_visible(source_summary, False)
                _set_pack_visible(xml_row, show_xml_builder, fill=tk.X, pady=2, after=source_mode_frame)
                _set_pack_visible(images_row, show_xml_builder, fill=tk.X, pady=2, after=xml_row)
                _set_pack_visible(output_row, show_xml_builder, fill=tk.X, pady=2, after=images_row)
                _set_pack_visible(ratios_frame, show_xml_builder, fill=tk.X, pady=10, after=output_row)
                _set_pack_visible(create_frame, show_xml_builder, anchor=tk.W, pady=(10, 5), after=ratios_frame)
                _set_pack_visible(progress, show_xml_builder, fill=tk.X, pady=2, after=create_frame)
                _set_pack_visible(status, show_xml_builder, anchor=tk.W, after=progress)

            try:
                host._refresh_dataset_creator_cta_state()
            except Exception:
                pass
        else:
            _set_pack_visible(getattr(host, "creator_source_mode_frame", None), False)
    except Exception:
        pass

    try:
        if bool(vm.in_campaign) and vm.mode == "char":
            _set_pack_visible(getattr(host, "split_source_hint_lbl", None), False)
            host.split_source_row.pack_forget()
            host._set_training_widget_text(host.split_intro_lbl, str(vm.split_intro or ""))
            try:
                if bool(vm.show_split_toggle):
                    host._set_training_widget_text(host.btn_step4_split_toggle, str(vm.split_toggle_label or "Popraw split"))
                    if str(host.btn_step4_split_toggle.winfo_manager()) != "pack":
                        host.btn_step4_split_toggle.pack(anchor=tk.W, pady=(0, 8))
                elif str(host.btn_step4_split_toggle.winfo_manager()) == "pack":
                    host.btn_step4_split_toggle.pack_forget()
            except Exception:
                pass
            host._set_training_widget_text(host.btn_step4_split, str(vm.split_action_label or "Utwórz wariant datasetu"))
            try:
                host._refresh_dataset_split_cta_state()
            except Exception:
                pass
            host._set_training_widget_text(host.split_source_summary_lbl, str(vm.split_summary or ""))
            if str(host.split_source_summary_lbl.winfo_manager()) != "pack":
                host.split_source_summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
            for widget, kwargs in (
                (host.split_output_row, {"fill": tk.X, "pady": 2}),
                (host.split_ratios_frame, {"fill": tk.X, "pady": 10}),
                (host.btn_step4_split_frame, {"anchor": tk.W, "pady": 10}),
            ):
                try:
                    if bool(vm.show_split_details):
                        if str(widget.winfo_manager()) != "pack":
                            widget.pack(**kwargs)
                    elif str(widget.winfo_manager()) == "pack":
                        widget.pack_forget()
                except Exception:
                    pass
            try:
                split_busy = bool(getattr(host, "dataset_split_is_running", False))
                split_progress = float(getattr(host, "split_progress_var", tk.DoubleVar(value=0.0)).get() or 0.0)
                if bool(vm.show_split_details) or split_busy or split_progress > 0.0:
                    host._set_split_feedback_visibility(True)
                elif str(host.split_feedback_frame.winfo_manager()) == "pack":
                    host.split_feedback_frame.pack_forget()
            except Exception:
                pass
        else:
            host._set_training_widget_text(host.split_intro_lbl, str(vm.split_intro or ""))
            host._set_training_widget_text(host.btn_step4_split, str(vm.split_action_label or "Utwórz wariant datasetu"))
            try:
                host._refresh_dataset_split_cta_state()
            except Exception:
                pass
            try:
                host._step4_char_split_details_visible = False
                if str(host.btn_step4_split_toggle.winfo_manager()) == "pack":
                    host.btn_step4_split_toggle.pack_forget()
            except Exception:
                pass
            _set_pack_visible(
                getattr(host, "split_source_hint_lbl", None),
                True,
                anchor=tk.W,
                fill=tk.X,
                pady=(0, 6),
                before=host.split_source_row,
            )
            if str(host.split_source_row.winfo_manager()) != "pack":
                host.split_source_row.pack(fill=tk.X, pady=2, before=host.split_source_summary_lbl)
            if str(host.split_source_summary_lbl.winfo_manager()) == "pack":
                host.split_source_summary_lbl.pack_forget()
            for widget, kwargs in (
                (host.split_output_row, {"fill": tk.X, "pady": 2}),
                (host.split_ratios_frame, {"fill": tk.X, "pady": 10}),
                (host.btn_step4_split_frame, {"anchor": tk.W, "pady": 10}),
            ):
                try:
                    if str(widget.winfo_manager()) != "pack":
                        widget.pack(**kwargs)
                except Exception:
                    pass
            try:
                split_busy = bool(getattr(host, "dataset_split_is_running", False))
                split_progress = float(getattr(host, "split_progress_var", tk.DoubleVar(value=0.0)).get() or 0.0)
                if split_busy or split_progress > 0.0:
                    host._set_split_feedback_visibility(True)
            except Exception:
                pass
    except Exception:
        pass


def refresh_step4_training_inputs_mode_ui(host: "TrainingTab"):
    vm = host._get_step4_training_inputs_view_model()

    def _set_pack_visible(widget, visible: bool, **pack_kwargs):
        if widget is None:
            return
        try:
            manager = str(widget.winfo_manager())
        except Exception:
            manager = ""
        try:
            if visible:
                if manager != "pack":
                    widget.pack(**pack_kwargs)
            elif manager == "pack":
                widget.pack_forget()
        except Exception:
            pass

    session_row = getattr(host, "train_session_name_row", None)
    dataset_section = getattr(host, "train_dataset_section_frame", None)
    dataset_title = getattr(host, "train_dataset_title_lbl", None)
    dataset_required = getattr(host, "train_dataset_required_lbl", None)
    dataset_caption = getattr(host, "train_dataset_caption_lbl", None)
    dataset_path_label = getattr(host, "train_dataset_path_lbl", None)
    dataset_entry = getattr(host, "train_dataset_entry", None)
    dataset_btn = getattr(host, "train_dataset_pick_btn", None)
    dataset_yaml_btn = getattr(host, "train_dataset_yaml_btn", None)
    dataset_row = getattr(host, "train_dataset_row", None)
    dataset_variant_row = getattr(host, "dataset_variant_row", None)
    dataset_variant_title = getattr(host, "dataset_variant_title_lbl", None)
    dataset_variant_caption = getattr(host, "dataset_variant_caption_lbl", None)
    dataset_hint = getattr(host, "train_dataset_hint_lbl", None)
    scope_hint = getattr(host, "train_scope_hint_lbl", None)
    pose_warning = getattr(host, "train_pose_warning_lbl", None)
    base_caption = getattr(host, "train_base_caption_lbl", None)
    base_combo = getattr(host, "base_combo", None)
    custom_row = getattr(host, "custom_row", None)
    custom_entry = getattr(host, "base_custom_entry", None)
    custom_btn = getattr(host, "base_custom_btn", None)

    _set_pack_visible(session_row, bool(vm.show_session_name), fill=tk.X, pady=(0, host._train_left_section_gap))
    _set_pack_visible(
        dataset_section,
        bool(vm.show_dataset_section),
        fill=tk.X,
        pady=(0, host._train_left_section_gap),
        before=scope_hint,
    )
    if dataset_title is not None:
        try:
            if not bool(vm.show_dataset_section):
                dataset_title.pack_forget()
            elif not str(dataset_title.winfo_manager()):
                dataset_title.pack(anchor=tk.W, fill=tk.X)
        except Exception:
            pass
    show_dataset_section = bool(vm.show_dataset_section)
    # PZ2 consumes prepared variants only. Manual source selection belongs to PZ1.
    show_manual_dataset_path = False

    _set_pack_visible(dataset_required, show_dataset_section, anchor=tk.W, fill=tk.X, pady=(0, 4))
    _set_pack_visible(dataset_caption, show_dataset_section, anchor=tk.W, fill=tk.X, pady=(2, 6))
    _set_pack_visible(dataset_path_label, show_manual_dataset_path, anchor=tk.W, fill=tk.X, pady=(2, 2))
    _set_pack_visible(dataset_row, show_manual_dataset_path, fill=tk.X, pady=2)
    _set_pack_visible(dataset_variant_row, bool(vm.show_dataset_section), fill=tk.X, pady=(4, 2))
    _set_pack_visible(dataset_hint, bool(vm.show_dataset_hint), anchor=tk.W, fill=tk.X, pady=(4, 8))
    _set_pack_visible(scope_hint, bool(vm.show_scope_hint), anchor=tk.W, fill=tk.X, pady=(0, host._train_left_section_gap))
    _set_pack_visible(
        pose_warning,
        (bool(vm.show_pose_warning) and bool(str(getattr(pose_warning, "cget", lambda _x: "")("text") or "").strip())),
        anchor=tk.W,
        fill=tk.X,
        pady=(0, host._train_left_section_gap),
    )

    try:
        selected_target = host._get_selected_training_target()
    except Exception:
        selected_target = getattr(host, "_step4_dataset_mode", "char")
    selected_target = str(selected_target or "char").strip().lower()

    if dataset_title is not None:
        title_text = "Wariant datasetu YOLO Pose" if selected_target == "plate" else "Wariant datasetu YOLO Detect"
        host._set_training_widget_text(dataset_title, title_text)

    if bool(vm.in_campaign):
        dataset_caption_text = (
            "PZ2 korzysta z wariantów przygotowanych w PZ1. "
            "Możesz przełączyć split, ale nowych źródeł nie wybieramy w tej karcie."
        )
        dataset_required_text = "Wymagane: gotowy wariant datasetu zgodny z torem kampanii."
    elif selected_target == "plate":
        dataset_required_text = "Wymagane: gotowy wariant datasetu YOLO Pose z data.yaml."
        dataset_caption_text = (
            "PZ2 nie podmienia ręcznie źródła datasetu. Jeśli chcesz zbudować albo przepiąć źródło, "
            "wróć do PZ1. Tutaj wybierasz tylko gotowy wariant utworzony wcześniej."
        )
    else:
        dataset_required_text = "Wymagane: gotowy wariant datasetu YOLO Detect z data.yaml."
        dataset_caption_text = (
            "PZ2 nie wskazuje już folderu YOLO ręcznie. W PZ1 wybierasz źródło i tworzysz wariant splitu, "
            "a tutaj wskazujesz gotowy wariant treningowy. Katalogi OCR/klasyfikacyjne manifest.json są pomijane."
        )
    host._set_training_widget_text(dataset_required, dataset_required_text)
    host._set_training_widget_text(dataset_caption, dataset_caption_text)
    host._set_training_widget_text(
        dataset_path_label,
        "Ścieżka gotowego datasetu YOLO Pose:" if selected_target == "plate" else "Ścieżka gotowego datasetu YOLO Detect:",
    )

    if dataset_variant_title is not None:
        variant_text = (
            "Gotowe warianty datasetu tablic:"
            if selected_target == "plate"
            else "Gotowe warianty datasetu znaków:"
        )
        host._set_training_widget_text(dataset_variant_title, variant_text)
    if dataset_variant_caption is not None:
        variant_caption_text = (
            "Lista pokazuje gotowe warianty YOLO Pose z katalogu tablic. Wybór wariantu ustawia aktywny dataset treningowy."
            if selected_target == "plate"
            else "Lista pokazuje tylko gotowe warianty YOLO Detect z data.yaml. Jeśli lista jest pusta, wróć do PZ1 i przygotuj wariant."
        )
        host._set_training_widget_text(dataset_variant_caption, variant_caption_text)

    if dataset_entry is not None:
        try:
            dataset_entry.configure(state=str(vm.dataset_entry_state or "normal"))
        except Exception:
            pass

    if dataset_btn is not None:
        try:
            dataset_btn.pack_forget()
        except Exception:
            pass

    if dataset_yaml_btn is not None:
        try:
            dataset_yaml_btn.pack_forget()
        except Exception:
            pass

    try:
        host._refresh_dataset_variant_choices()
    except Exception:
        pass

    base_caption_text = (
        "Projekt może podstawić model z poprzedniej iteracji. Możesz go zmienić przed startem."
        if bool(vm.in_campaign)
        else "Wybierz model zgodny z torem: tablice = Pose, znaki = Detect."
    )
    host._set_training_widget_text(base_caption, base_caption_text)

    if base_combo is not None:
        try:
            base_combo.configure(state=str(vm.base_combo_state or "readonly"))
        except Exception:
            pass

    if custom_row is not None:
        try:
            if not bool(vm.show_custom_model):
                custom_row.pack_forget()
            elif not str(custom_row.winfo_manager()):
                custom_row.pack(fill=tk.X, pady=2, after=base_combo)
        except Exception:
            pass

    if custom_entry is not None:
        try:
            custom_entry.configure(state=str(vm.custom_entry_state or "disabled"))
        except Exception:
            pass

    if custom_btn is not None:
        try:
            if not bool(vm.show_custom_pick_button):
                custom_btn.pack_forget()
            elif not str(custom_btn.winfo_manager()):
                custom_btn.pack(side=tk.LEFT, padx=(8, 0))
            if bool(vm.show_custom_pick_button):
                custom_btn.configure(state=tk.NORMAL if host.base_model_var.get() == "Custom" else tk.DISABLED)
        except Exception:
            pass

    if not bool(vm.in_campaign):
        try:
            host._on_base_model_change()
        except Exception:
            pass


def _contrast_text_for_badge(bg_color: str, fallback: str = "#ffffff") -> str:
    raw = str(bg_color or "").strip().lstrip("#")
    if len(raw) != 6:
        return fallback
    try:
        r = int(raw[0:2], 16) / 255.0
        g = int(raw[2:4], 16) / 255.0
        b = int(raw[4:6], 16) / 255.0
    except Exception:
        return fallback

    luminance = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
    return "#111827" if luminance > 0.58 else "#ffffff"


def refresh_step4_route_choice_cards(host: "TrainingTab"):
    cards = getattr(host, "_step4_route_choice_cards", {})
    if not cards:
        return

    palette = getattr(host.app, "palette", {})
    panel_bg = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    accent = palette.get("accent", "#0e639c")
    success = palette.get("success", "#4ec9b0")
    accent_text = palette.get("accent_text", "#ffffff")
    surface_info = palette.get("surface_info", panel_alt)
    surface_success = palette.get("surface_success", panel_alt)

    mode = str(getattr(host, "_step4_dataset_mode", "char") or "char").strip().lower()
    route_selected = bool(getattr(host, "_step4_route_selected", False))

    for card_mode, widgets in cards.items():
        is_active = bool(route_selected and card_mode == mode)
        accent_color = accent if card_mode == "plate" else success
        active_bg = surface_info if card_mode == "plate" else surface_success
        card_bg = active_bg if is_active else panel_alt
        card_border = accent_color if is_active else border
        title_fg = accent_color if is_active else fg
        desc_fg = fg if is_active else muted
        badge_bg = accent_color if is_active else panel_bg
        badge_fg = _contrast_text_for_badge(badge_bg, accent_text) if is_active else fg
        badge_text = "WYBRANO" if is_active else "DO WYBORU"

        frame = widgets.get("frame")
        title_row = widgets.get("title_row")
        title = widgets.get("title")
        badge = widgets.get("badge")
        desc = widgets.get("desc")

        for widget in (frame, title_row):
            try:
                if widget is not None:
                    widget.configure(bg=card_bg)
            except Exception:
                pass
        try:
            if frame is not None:
                frame.configure(highlightbackground=card_border, highlightcolor=card_border)
        except Exception:
            pass
        try:
            if title is not None:
                title.configure(bg=card_bg, fg=title_fg)
        except Exception:
            pass
        try:
            if desc is not None:
                desc.configure(bg=card_bg, fg=desc_fg)
        except Exception:
            pass
        try:
            if badge is not None:
                badge.configure(
                    text=badge_text,
                    width=10,
                    anchor=tk.CENTER,
                    bg=badge_bg,
                    fg=badge_fg,
                    highlightbackground=card_border,
                    highlightcolor=card_border,
                )
        except Exception:
            pass


def refresh_step4_dataset_mode_ui(host: "TrainingTab"):
    try:
        host._refresh_free_training_route_ui()
    except Exception:
        pass

    try:
        host._refresh_step4_analysis_tab_visibility()
    except Exception:
        pass

    try:
        refresh_step4_route_choice_cards(host)
    except Exception:
        pass

    if not hasattr(host, "ds_mode_host"):
        return

    vm = host._get_step4_dataset_workflow_view_model()
    mode = getattr(host, "_step4_dataset_mode", "char")
    campaign_active = bool(CAMPAIGN.get_active_project_name())
    route_selected = bool(getattr(host, "_step4_route_selected", False))
    locked_target = host._get_locked_campaign_training_target()
    route_locked = campaign_active and locked_target in ("char", "plate")

    try:
        host.ds_creator_frame.pack_forget()
    except Exception:
        pass
    try:
        host.ds_split_frame.pack_forget()
    except Exception:
        pass
    try:
        host.ds_mode_waiting_frame.pack_forget()
    except Exception:
        pass

    if bool(vm.show_waiting_panel):
        host.ds_mode_title_var.set(str(vm.title or "Wybierz tor po lewej stronie"))
        host.ds_mode_desc_var.set(str(vm.description or ""))
        host.btn_choose_plate.configure(state=tk.NORMAL)
        host.btn_choose_char.configure(state=tk.NORMAL)
        refresh_step4_route_choice_cards(host)
        host.ds_mode_waiting_frame.pack(fill=tk.X, expand=False)
        host.btn_step4_next.configure(
            text=str(vm.next_label or "Wybierz tor"),
            state=tk.DISABLED
        )
        return

    if mode == "plate":
        host.ds_mode_title_var.set(str(vm.title or "Tor tablic (YOLO Pose)"))
        host.ds_mode_desc_var.set(str(vm.description or ""))
        host.btn_choose_plate.configure(state=tk.DISABLED)
        host.btn_choose_char.configure(state=(tk.DISABLED if route_locked else tk.NORMAL))
        if bool(vm.show_creator_section):
            host.ds_creator_frame.pack(fill=tk.X, expand=False)
        host.btn_step4_next.configure(text=str(vm.next_label or "Dalej do treningu"))
    else:
        host.ds_mode_title_var.set(str(vm.title or "Tor znaków (YOLO Detect)"))
        host.ds_mode_desc_var.set(str(vm.description or ""))
        host.btn_choose_plate.configure(state=(tk.DISABLED if route_locked else tk.NORMAL))
        host.btn_choose_char.configure(state=tk.DISABLED)
        if bool(vm.show_split_section):
            host.ds_split_frame.pack(fill=tk.X, expand=False)
        host.btn_step4_next.configure(text=str(vm.next_label or "Dalej do treningu"))

    if route_locked:
        host.btn_choose_plate.configure(state=tk.DISABLED)
        host.btn_choose_char.configure(state=tk.DISABLED)

    refresh_step4_route_choice_cards(host)

    try:
        refresh_step4_campaign_builder_inputs_ui(host)
    except Exception:
        pass

    try:
        refresh_step4_training_inputs_mode_ui(host)
    except Exception:
        pass

    try:
        host._sync_dataset_mode_canvas_width()
        host._sync_dataset_mode_scrollregion()
    except Exception:
        pass


def refresh_step4_campaign_navigation_ui(host: "TrainingTab"):
    vm = host._get_step4_campaign_navigation_view_model()

    try:
        host._update_step4_notebook_mode()
    except Exception:
        pass

    try:
        host._refresh_step4_analysis_tab_visibility()
    except Exception:
        pass

    try:
        if bool(vm.in_campaign) and bool(vm.dataset_tab_enabled):
            host.main_nb.tab(host.tab_dataset, state="normal")
        host.main_nb.tab(
            host.tab_train,
            state=("normal" if bool(vm.train_tab_enabled) else "disabled")
        )
    except Exception:
        pass

    try:
        host.btn_step4_next.configure(
            text=str(vm.next_label or "Dalej do treningu"),
            state=(tk.NORMAL if bool(vm.next_enabled) else tk.DISABLED),
        )
    except Exception:
        pass

    try:
        host.btn_step4_back.configure(text=str(vm.dataset_back_label or "Wstecz"))
        if not bool(vm.show_dataset_back):
            host.btn_step4_back.grid_remove()
        else:
            host.btn_step4_back.grid()
    except Exception:
        pass

    try:
        if bool(vm.force_dataset_tab_selection) and str(host.main_nb.select()) == str(host.tab_train):
            host.main_nb.select(host.tab_dataset)
    except Exception:
        pass

    if not hasattr(host, "step4_train_nav"):
        return

    try:
        if bool(vm.show_train_nav):
            host.step4_train_nav.grid()
        else:
            host.step4_train_nav.grid_remove()
    except Exception:
        pass

    try:
        host._update_training_dataset_hint()
    except Exception:
        pass

    try:
        host.btn_step4_train_back.configure(text=str(vm.train_back_label or "Wstecz do toru"))
        if not bool(vm.show_train_back):
            host.btn_step4_train_back.pack_forget()
        elif not str(host.btn_step4_train_back.winfo_manager()):
            host.btn_step4_train_back.pack(side=tk.RIGHT, padx=(8, 0))
    except Exception:
        pass

    try:
        host.btn_step4_finish.configure(state=tk.DISABLED)
    except Exception:
        pass

    try:
        active_target = str(host.get_campaign_training_target() or "").strip().lower()
        show_dataset_adjust_cta = bool(
            CAMPAIGN.get_active_project_name()
            and active_target in {"char", "plate"}
            and bool(getattr(host, "_step4_train_unlocked", False))
        )
        if show_dataset_adjust_cta:
            host.btn_step4_finish.configure(
                text="Ustaw inny split",
                command=host._open_step4_dataset_stage,
                width=22,
                state=(tk.DISABLED if host._step4_has_active_operation() else tk.NORMAL),
            )
            if not str(host.btn_step4_finish.winfo_manager()):
                host.btn_step4_finish.pack(side=tk.LEFT)
        else:
            host.btn_step4_finish.pack_forget()
    except Exception:
        pass

    try:
        if bool(vm.show_complete_project):
            if not str(host.btn_step4_complete_project.winfo_manager()):
                host.btn_step4_complete_project.pack(side=tk.LEFT, padx=(0, 8))
        else:
            host.btn_step4_complete_project.pack_forget()
    except Exception:
        pass


def open_step4_dataset_stage(host: "TrainingTab"):
    try:
        host.main_nb.select(host.tab_dataset)
    except Exception:
        pass

    try:
        host._guide_step4_builder_action()
    except Exception:
        pass


def _normalize_training_context_target(target: str | None) -> str:
    value = str(target or "").strip().lower()
    return value if value in ("char", "plate") else "char"


def accept_training_input_context(
    host: "TrainingTab",
    context: TrainingInputContext | None = None,
    *,
    source: str = "",
    target: str = "",
    dataset_path: str | Path | None = None,
    select_training: bool = False,
) -> bool:
    if context is not None:
        source = context.source or source
        target = context.target or target
        dataset_path = context.dataset_path or dataset_path

    mode = _normalize_training_context_target(target or getattr(host, "_step4_dataset_mode", "char"))
    campaign_active = bool(CAMPAIGN.get_active_project_name())
    locked_target = host._get_locked_campaign_training_target()
    if campaign_active and locked_target in ("char", "plate"):
        mode = locked_target

    dataset_text = str(dataset_path or "").strip()
    if dataset_text:
        try:
            host.dataset_var.set(dataset_text)
        except Exception:
            pass

    try:
        host._step4_dataset_mode = mode
    except Exception:
        pass
    try:
        host.set_campaign_training_target(mode)
    except Exception:
        pass
    try:
        host._step4_route_selected = True
    except Exception:
        pass
    try:
        host._step4_train_unlocked = True
    except Exception:
        pass
    try:
        host._last_training_input_context = TrainingInputContext(
            source=str(source or "pz1"),
            target=mode,
            dataset_path=dataset_text,
            ready=bool(dataset_text),
        )
    except Exception:
        pass

    if mode == "plate" and dataset_text:
        try:
            host._set_creator_source_mode("ready")
        except Exception:
            pass

    if not campaign_active:
        try:
            host._rebind_free_mode_training_storage(target=mode)
        except Exception:
            pass
        try:
            host.rank_models_dir.set(str(host._get_ranking_models_default_dir()))
        except Exception:
            pass

    for callback_name in (
        "_refresh_base_model_choices",
        "_apply_training_recommended_start_params",
        "_refresh_training_recommendation_table",
        "_refresh_dataset_variant_choices",
        "_update_step4_notebook_mode",
        "_refresh_step4_dataset_mode_ui",
        "_refresh_step4_campaign_navigation_ui",
        "_refresh_free_training_route_ui",
        "_update_training_dataset_hint",
        "_refresh_training_start_state",
    ):
        try:
            callback = getattr(host, callback_name, None)
            if callable(callback):
                callback()
        except Exception:
            pass

    if select_training:
        try:
            host.main_nb.select(host.tab_train)
        except Exception:
            pass
        try:
            host._select_step4_analysis_tab(host.hist_tab)
        except Exception:
            pass

    return True


def mark_step4_dataset_ready(host: "TrainingTab", dataset_path: str | Path | None = None):
    if dataset_path:
        try:
            host.dataset_var.set(str(dataset_path))
        except Exception:
            pass

    try:
        dataset_text = str(dataset_path or host.dataset_var.get() or "").strip()
    except Exception:
        dataset_text = str(dataset_path or "").strip()

    target = _normalize_training_context_target(getattr(host, "_step4_dataset_mode", "char"))
    try:
        host._last_training_input_context = TrainingInputContext(
            source="pz1",
            target=target,
            dataset_path=dataset_text,
            ready=bool(dataset_text),
        )
    except Exception:
        pass

    if target == "plate" and dataset_text:
        try:
            host._set_creator_source_mode("ready")
        except Exception:
            pass

    try:
        host._step4_route_selected = True
    except Exception:
        pass
    try:
        host._step4_train_unlocked = True
    except Exception:
        pass

    try:
        host._refresh_step4_campaign_navigation_ui()
    except Exception:
        pass

    try:
        host._guide_step4_next_action()
    except Exception:
        pass
    try:
        host._refresh_step4_dataset_mode_ui()
    except Exception:
        pass
    try:
        host._refresh_dataset_variant_choices()
    except Exception:
        pass
    try:
        host._update_training_dataset_hint()
    except Exception:
        pass
    try:
        host._refresh_training_start_state()
    except Exception:
        pass


def set_step4_dataset_mode(host: "TrainingTab", mode: str, *, show_locked_message: bool = True):
    mode = (mode or "char").strip().lower()
    if mode not in ("char", "plate"):
        mode = "char"

    previous_mode = str(getattr(host, "_step4_dataset_mode", "char") or "char").strip().lower()
    if previous_mode not in ("char", "plate"):
        previous_mode = "char"
    route_changed = mode != previous_mode
    clear_dataset_for_route_change = False

    if route_changed:
        active_label = host._get_active_step4_operation_label()
        if active_label:
            messagebox.showinfo(
                "Proces w toku",
                "Nie można teraz zmienic toru treningu.\n\n"
                f"Najpierw poczekaj na zakonczenie: {active_label}.",
            )
            return

    campaign_active = bool(CAMPAIGN.get_active_project_name())
    locked_target = host._get_locked_campaign_training_target()
    if campaign_active and locked_target in ("char", "plate"):
        if mode != locked_target:
            if show_locked_message:
                messagebox.showinfo(
                    "Tor iteracji jest stały",
                    "Tor treningu został już ustalony dla bieżącej iteracji.\n\n"
                    f"Ta iteracja pozostaje w torze {host._format_training_target_label(locked_target)}."
                )
        mode = locked_target
        route_changed = mode != previous_mode

    if route_changed and not campaign_active:
        try:
            current_dataset = str(host.dataset_var.get() or "").strip()
        except Exception:
            current_dataset = ""
        if current_dataset:
            try:
                inferred_target = str(host._infer_dataset_target(current_dataset) or "").strip().lower()
            except Exception:
                inferred_target = ""
            if inferred_target in {"char", "plate", "vehicle"} and inferred_target != mode:
                previous_label = host._format_training_target_label(previous_mode)
                new_label = host._format_training_target_label(mode)
                dataset_label = host._format_training_target_label(inferred_target)
                try:
                    display_path = host._format_workspace_relative_path(current_dataset)
                except Exception:
                    display_path = current_dataset
                confirm_switch = messagebox.askyesno(
                    "Zmiana toru treningu",
                    "Wybrany dataset należy do innego toru niż ten, który chcesz teraz uruchomić.\n\n"
                    f"Obecny tor: {previous_label}\n"
                    f"Nowy tor: {new_label}\n"
                    f"Dataset: {display_path}\n"
                    f"Rozpoznany jako: {dataset_label}\n\n"
                    "Po zmianie toru odłączymy ten dataset, wyczyścimy wariant splitu i kontekst PZ2. "
                    "Eksporty oraz pliki na dysku pozostaną bez zmian.\n\n"
                    "Kontynuować zmianę toru?",
                    parent=getattr(host, "frame", None),
                )
                if not confirm_switch:
                    return
                clear_dataset_for_route_change = True

    host._step4_dataset_mode = mode
    host.set_campaign_training_target(mode)
    if campaign_active:
        host._step4_route_selected = True
        host._step4_train_unlocked = False
    else:
        if clear_dataset_for_route_change:
            try:
                host.dataset_var.set("")
            except Exception:
                pass
            try:
                host.dataset_variant_var.set("")
            except Exception:
                pass
            try:
                host._last_training_input_context = TrainingInputContext(
                    source="pz1",
                    target=mode,
                    dataset_path="",
                    ready=False,
                )
            except Exception:
                pass
        elif mode == "plate":
            try:
                current_dataset = str(host.dataset_var.get() or "").strip()
            except Exception:
                current_dataset = ""
            if current_dataset:
                try:
                    inferred_target = str(host._infer_dataset_target(current_dataset) or "").strip().lower()
                except Exception:
                    inferred_target = ""
                if not inferred_target or inferred_target == "plate":
                    try:
                        host._set_creator_source_mode("ready")
                    except Exception:
                        pass
        if route_changed and not clear_dataset_for_route_change:
            try:
                current_dataset = str(host.dataset_var.get() or "").strip()
            except Exception:
                current_dataset = ""
            if not current_dataset:
                try:
                    host._last_training_input_context = TrainingInputContext(
                        source="pz1",
                        target=mode,
                        dataset_path="",
                        ready=False,
                    )
                except Exception:
                    pass

        host._rebind_free_mode_training_storage(target=mode)
        try:
            host.rank_models_dir.set(str(host._get_ranking_models_default_dir()))
        except Exception:
            pass
    try:
        host._refresh_base_model_choices()
    except Exception:
        pass
    try:
        host._apply_training_recommended_start_params()
    except Exception:
        pass
    try:
        host._refresh_training_recommendation_table()
    except Exception:
        pass
    try:
        host._refresh_dataset_variant_choices()
    except Exception:
        pass
    host._refresh_step4_dataset_mode_ui()
    host._refresh_step4_campaign_navigation_ui()
    try:
        host._refresh_free_training_route_ui()
    except Exception:
        pass
    try:
        host._update_training_dataset_hint()
    except Exception:
        pass

    try:
        label = "tablic (YOLO Pose)" if mode == "plate" else "znaków (YOLO Detect)"
        host._append_step4_builder_log(f"[TRYB] Wybrano tor budowy datasetu dla modelu {label}.")
    except Exception:
        pass

    if campaign_active:
        try:
            host._guide_step4_builder_action()
        except Exception:
            pass


def step4_dataset_go_next(host: "TrainingTab"):
    if CAMPAIGN.get_active_project_name() and not getattr(host, "_step4_train_unlocked", False):
        return

    try:
        mode = getattr(host, "_step4_dataset_mode", "char")
        host.set_campaign_training_target(mode)
    except Exception:
        pass

    try:
        host._refresh_step4_campaign_navigation_ui()
    except Exception:
        pass

    try:
        host.main_nb.select(host.tab_train)
    except Exception:
        pass

    try:
        host._select_step4_analysis_tab(host.hist_tab)
    except Exception:
        pass

    if CAMPAIGN.get_active_project_name():
        try:
            if getattr(host, "_step4_campaign_finish_ready", False):
                host._guide_step4_finish_action()
            else:
                host._guide_step4_training_action()
        except Exception:
            pass


def step4_dataset_go_back(host: "TrainingTab"):
    if CAMPAIGN.get_active_project_name():
        return_to_campaign_from_step4(host)
        return

    host._append_step4_builder_log(
        "[NAWIGACJA] Tryb swobodny: brak poprzedniego kroku wizardowego do otwarcia."
    )


def step4_train_go_back(host: "TrainingTab"):
    if CAMPAIGN.get_active_project_name():
        try:
            return_to_campaign_from_step4(host)
            return
        except Exception:
            pass

    try:
        open_step4_dataset_stage(host)
    except Exception:
        try:
            host.main_nb.select(host.tab_dataset)
        except Exception:
            pass

    try:
        host._refresh_step4_dataset_mode_ui()
    except Exception:
        pass

    try:
        host._refresh_free_training_route_ui()
    except Exception:
        pass


def refresh_step4_analysis_tab_visibility(host: "TrainingTab"):
    if not hasattr(host, "right_nb") or not hasattr(host, "ranking_tab"):
        return

    ranking_enabled = host._is_ranking_available_for_selected_target()

    if ranking_enabled:
        if not getattr(host, "_step4_ranking_tab_visible", False):
            try:
                host.right_nb.add(host.ranking_tab, text="Ranking")
            except Exception:
                try:
                    host.right_nb.insert("end", host.ranking_tab, text="Ranking")
                except Exception:
                    pass
            host._step4_ranking_tab_visible = True
        else:
            try:
                host.right_nb.tab(host.ranking_tab, text="Ranking", state="normal")
            except Exception:
                pass
        if host._is_ranking_tab_active():
            try:
                host._prefill_ranking_reference_if_empty()
            except Exception:
                pass
            try:
                host._refresh_ranking_reference_ui()
            except Exception:
                pass
        return

    try:
        if str(host.right_nb.select()) == str(host.ranking_tab):
            host.right_nb.select(host.hist_tab)
    except Exception:
        pass

    if getattr(host, "_step4_ranking_tab_visible", False):
        try:
            host.right_nb.hide(host.ranking_tab)
        except Exception:
            pass
        host._step4_ranking_tab_visible = False


def sync_step4_analysis_nav_buttons(host: "TrainingTab", event=None):
    try:
        refresh_step4_analysis_tab_visibility(host)
    except Exception:
        pass


def resolve_step4_guidance_buttons(host: "TrainingTab", attr_name: str):
    if attr_name == "step4_route_panel_frame":
        return []
    if attr_name == "btn_step4_start_train_frame":
        return [getattr(host, "btn_start_train", None)]
    if attr_name == "btn_step4_finish_frame":
        return [
            getattr(host, "btn_step4_finish", None),
            getattr(host, "btn_step4_complete_project", None),
        ]

    candidates = [attr_name]
    if attr_name.endswith("_frame"):
        candidates.append(attr_name[:-6])

    resolved = []
    for candidate in candidates:
        widget = getattr(host, candidate, None)
        try:
            import tkinter.ttk as ttk  # local import to avoid unused at top
            if isinstance(widget, ttk.Button):
                resolved.append(widget)
        except Exception:
            pass

    unique_buttons = []
    seen = set()
    for btn in resolved:
        if btn is None:
            continue
        btn_id = str(btn)
        if btn_id not in seen:
            unique_buttons.append(btn)
            seen.add(btn_id)
    return unique_buttons


def resolve_step4_guidance_frame(host: "TrainingTab", attr_name: str):
    if not attr_name:
        return None

    if attr_name == "step4_route_panel_frame":
        return getattr(host, "step4_route_panel_frame", None)
    if attr_name == "btn_step4_start_train_frame":
        return getattr(host, "btn_step4_start_train_pulse_frame", None)

    candidates = [attr_name]

    for candidate in candidates:
        widget = getattr(host, candidate, None)
        if isinstance(widget, tk.Frame):
            return widget

    return None


def set_step4_emphasis(host: "TrainingTab", frame_attr: str, enabled: bool, color: str = "#f39c12"):
    frame = resolve_step4_guidance_frame(host, frame_attr)
    if frame is not None:
        try:
            bg = host.app.palette.get("bg", "#1e1e1e") if frame_attr == "step4_route_panel_frame" else host.app.palette.get("panel", "#252526")
            host.app.set_frame_emphasis(frame, enabled, background=bg)
        except Exception:
            pass

    buttons = resolve_step4_guidance_buttons(host, frame_attr)
    for btn in buttons:
        try:
            host.app.set_button_emphasis(btn, enabled)
        except Exception:
            pass


def clear_step4_guidance(host: "TrainingTab"):
    for attr_name in (
        "step4_route_panel_frame",
        "btn_step4_create_frame",
        "btn_step4_split_frame",
        "btn_step4_next_frame",
        "btn_step4_start_train_frame",
        "btn_step4_finish_frame",
        "btn_step4_train_back",
    ):
        try:
            set_step4_emphasis(host, attr_name, False)
        except Exception:
            pass


def guide_step4_route_selection(host: "TrainingTab"):
    if not CAMPAIGN.get_active_project_name():
        return
    clear_step4_guidance(host)
    set_step4_emphasis(host, "step4_route_panel_frame", True)


def guide_step4_builder_action(host: "TrainingTab"):
    if not CAMPAIGN.get_active_project_name():
        return
    clear_step4_guidance(host)
    frame_attr = "btn_step4_create_frame" if host._step4_dataset_mode == "plate" else "btn_step4_split_frame"
    set_step4_emphasis(host, frame_attr, True)


def guide_step4_next_action(host: "TrainingTab"):
    if not CAMPAIGN.get_active_project_name():
        return
    clear_step4_guidance(host)
    set_step4_emphasis(host, "btn_step4_next_frame", True)


def guide_step4_training_action(host: "TrainingTab"):
    if not CAMPAIGN.get_active_project_name():
        return
    clear_step4_guidance(host)
    set_step4_emphasis(host, "btn_step4_start_train_frame", True)


def guide_step4_finish_action(host: "TrainingTab"):
    if not CAMPAIGN.get_active_project_name():
        return
    clear_step4_guidance(host)
    set_step4_emphasis(host, "btn_step4_train_back", True)
