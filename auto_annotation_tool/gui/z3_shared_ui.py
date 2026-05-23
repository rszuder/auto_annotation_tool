from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING

from ..campaign_manager import CAMPAIGN
from .web_slim_scrollbar import blend_hex_colors
from .z3_view_models import (
    Step3ExtractStepCardViewModel,
    Step3ExtractWorkflowViewModel,
    Step3Pz3DatasetModeViewModel,
    Step3Pz3StatusPanelViewModel,
)

if TYPE_CHECKING:
    from .tab_character_annotation import CharacterAnnotationTab


def _format_pz3_source_breakdown(source_counts: dict) -> str:
    labels = {
        "auto_preview": "auto z PZ2",
        "local_manual": "poprawki lokalne",
        "cvat_manual": "poprawki CVAT",
    }
    parts = []
    for key in ("auto_preview", "local_manual", "cvat_manual"):
        try:
            count = int((source_counts or {}).get(key, 0) or 0)
        except Exception:
            count = 0
        parts.append(f"{labels[key]}: {count}")
    return " | ".join(parts)


def build_step3_pz3_dataset_mode_view_model(
    host: "CharacterAnnotationTab",
) -> Step3Pz3DatasetModeViewModel:
    try:
        in_campaign = bool(getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())
    except Exception:
        in_campaign = False

    mode = "perfect"

    perfect_selected = mode == "perfect"

    if perfect_selected:
        export_pool = host._build_campaign_aware_gold_export_counts(
            selected_strategies=host._get_selected_gold_export_strategy_buckets(),
            selected_sources=host._get_selected_gold_export_source_buckets(),
        )
        selected_plate_count = int(export_pool.get("selected_plate_count", 0) or 0)
        selected_char_count = int(export_pool.get("selected_char_count", 0) or 0)
        export_ready = bool(selected_plate_count > 0 and selected_char_count > 0)
        try:
            preview_context = host._get_active_preview_context()
        except Exception:
            preview_context = {
                "ready": False,
                "message": "Nie udało się odczytać aktywnego preview PZ2.",
                "preview_dir": None,
                "plate_count": 0,
            }
        preview_ready = bool(preview_context.get("ready"))
        if preview_ready:
            preview_dir = preview_context.get("preview_dir")
            preview_name = preview_dir.name if isinstance(preview_dir, Path) else str(preview_dir or "aktywny run")
            preview_plate_count = int(preview_context.get("plate_count", 0) or 0)
            source_preview_text = f"Aktywny preview PZ2: {preview_name} | wycięte tablice: {preview_plate_count}"
            source_preview_tone = "success"
        else:
            source_preview_text = str(preview_context.get("message") or "Brak aktywnego preview PZ2.")
            source_preview_tone = "warning"

        source_breakdown = _format_pz3_source_breakdown(dict(export_pool.get("source_counts", {}) or {}))
        if selected_plate_count > 0 or selected_char_count > 0:
            source_pool_text = (
                f"Gotowe do gold packa: {selected_plate_count} tablic perfect | "
                f"znaki: {selected_char_count}. Źródła: {source_breakdown}."
            )
            source_pool_tone = "success" if export_ready else "warning"
        else:
            source_pool_text = (
                "Gotowe do gold packa: 0 tablic perfect. Oznacz tablice jako perfect w PZ2 "
                "albo zaimportuj poprawki CVAT."
            )
            source_pool_tone = "warning"
        source_next_text = (
            "Następny krok: wybierz zakres gold packa i wyeksportuj dataset źródłowy znaków."
            if export_ready
            else (
                "Następny krok: przygotuj lub wskaż preview run w PZ1/PZ2, a potem oznacz "
                "co najmniej jedną tablicę jako perfect. PZ3 nie wybiera źródła samodzielnie."
                if not preview_ready
                else (
                    "Następny krok: wróć do PZ2 i uzupełnij poprawne boxy znaków na tablicach perfect. "
                    "Dataset YOLO wymaga tablic perfect z co najmniej jednym eksportowalnym znakiem."
                    if selected_plate_count > 0
                    else "Następny krok: wróć do PZ2/PZ3 i przygotuj co najmniej jedną tablicę perfect."
                )
            )
        )
        source_next_tone = "muted" if export_ready else "warning"
        return Step3Pz3DatasetModeViewModel(
            in_campaign=in_campaign,
            mode="perfect",
            dataset_source_title="",
            dataset_source_intro="Status materiału wejściowego dla PZ3:",
            source_preview_text=source_preview_text,
            source_preview_tone=source_preview_tone,
            source_pool_text=source_pool_text,
            source_pool_tone=source_pool_tone,
            source_next_text=source_next_text,
            source_next_tone=source_next_tone,
            show_dataset_source_cards=False,
            perfect_selected=True,
            existing_selected=False,
            perfect_badge_text="PZ2",
            perfect_title_text="Perfecty z aktywnego runu",
            perfect_desc_text="Buduj źródłowy dataset bezpośrednio z wyniku PZ2 i aktualnych perfectów.",
            existing_badge_text="DATASET",
            existing_title_text="Gotowy dataset YOLO",
            existing_desc_text="Gotowe datasety i ich warianty wybierzesz w Z4.",
            show_existing_dataset_panel=False,
            cvat_option2_title="Źródło danych",
            cvat_option2_tone="success",
            cvat_option2_desc=(
                "PZ3 buduje dataset źródłowy z aktywnego preview PZ2 oraz ręcznych poprawek. "
                "Gotowe warianty treningowe i split wybierasz później w Z4."
            ),
            show_gold_filters=True,
            split_title="",
            split_label="",
            primary_export_label="WYEKSPORTUJ DATASET ŹRÓDŁOWY ZNAKÓW",
            primary_export_command_id="run_yolo_gold_export",
            primary_export_enabled=export_ready,
            primary_export_columnspan=1,
            show_classifier_export=True,
            classifier_export_enabled=bool(selected_char_count > 0),
            action_hint=(
                (
                    f"Tor kampanii: gotowe do eksportu {selected_plate_count} tablic perfect i {selected_char_count} znaków."
                    if in_campaign
                    else f"Źródłowy dataset: do eksportu {selected_plate_count} tablic i {selected_char_count} znaków z aktualnie dostępnej puli."
                )
                if (selected_plate_count > 0 or selected_char_count > 0)
                else (
                    "Tor kampanii: brak tablic perfect gotowych do eksportu."
                    if in_campaign
                    else "Źródłowy dataset: brak tablic perfect gotowych do eksportu."
                )
            ),
            action_hint_tone=("muted" if export_ready else "warning"),
            existing_dataset_status="",
            existing_dataset_status_tone="muted",
        )

    source_dir_raw = str(host.pz3_existing_dataset_var.get() or "").strip()
    source_info = host._inspect_pz3_dataset_source_dir(Path(source_dir_raw) if source_dir_raw else None)
    status_tone = "success" if source_info.get("ok") else ("warning" if source_dir_raw else "muted")
    action_hint = "Gotowe datasety i warianty treningowe obsługuje Z4."
    action_tone = status_tone if source_info.get("ok") else "muted"

    return Step3Pz3DatasetModeViewModel(
        in_campaign=in_campaign,
        mode="existing",
        dataset_source_title="",
        dataset_source_intro=(
            "PZ3 pracuje na perfectach z aktywnego runu PZ2 oraz ręcznych importach. "
            "Gotowe datasety, warianty treningowe i split przygotujesz w Z4."
        ),
        source_preview_text="Ten tryb został przeniesiony do Z4.",
        source_preview_tone="muted",
        source_pool_text="W PZ3 zostaje tylko budowa datasetu źródłowego znaków.",
        source_pool_tone="muted",
        source_next_text="Wybierz źródło w Z4, jeśli chcesz pracować na gotowym datasecie.",
        source_next_tone="muted",
        show_dataset_source_cards=True,
        perfect_selected=False,
        existing_selected=True,
        perfect_badge_text="PZ2",
        perfect_title_text="Perfecty z aktywnego runu",
        perfect_desc_text="Buduj nowy dataset bezpośrednio z wyniku PZ2 i aktualnych perfectów.",
        existing_badge_text="DATASET",
        existing_title_text="Gotowy dataset YOLO",
        existing_desc_text="Gotowe datasety i ich warianty wybierzesz w Z4.",
        show_existing_dataset_panel=True,
        cvat_option2_title="Gotowy dataset YOLO",
        cvat_option2_tone="default",
        cvat_option2_desc="Ten tryb jest przeniesiony do Z4. W PZ3 tworzysz tylko źródłowy dataset znaków.",
        show_gold_filters=False,
        split_title="",
        split_label="",
        primary_export_label="WRÓĆ DO ŹRÓDŁOWEGO DATASETU PZ3",
        primary_export_command_id="run_yolo_gold_export",
        primary_export_enabled=False,
        primary_export_columnspan=2,
        show_classifier_export=False,
        action_hint=action_hint,
        action_hint_tone=action_tone,
        existing_dataset_status=str(source_info.get("message") or ""),
        existing_dataset_status_tone=status_tone,
    )


def build_step3_extract_workflow_view_model(
    host: "CharacterAnnotationTab",
) -> Step3ExtractWorkflowViewModel:
    current = host._get_extract_workflow_step()
    route = host._get_extract_entry_mode()
    source_ready = bool(getattr(host, "_extract_last_source_binding_result", {}).get("ok"))
    try:
        has_preview = bool(host._is_extract_preview_ready())
    except Exception:
        has_preview = bool(str(host.preview_dir_var.get() or "").strip())
    has_run = bool(str(host.annotation_run_dir_var.get() or "").strip())
    linear_mode = bool(getattr(host, "_step3_linear_mode", False))
    candidate = host._get_preferred_z2_source_candidate()
    step3_status = ""
    if linear_mode:
        try:
            step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower()
        except Exception:
            step3_status = ""

    if linear_mode and step3_status == "needs_rework":
        source_intro = (
            "Wróciłeś do etapu 3 po poprawkach tablic w Z2. Z3 nadal pracuje na tej samej iteracji "
            "i użyje odświeżonego źródła tablic automatycznie."
        )
        source_hint = (
            "Nie musisz ponownie wskazywać runu, XML ani folderu obrazów. "
            "W tym kroku przebudujesz tylko zestaw wyciętych tablic potrzebny do dalszej pracy nad znakami."
        )
    elif linear_mode:
        source_intro = (
            "Kampania ma już przypięte źródło tablic dla tego etapu. "
            "Nie musisz ręcznie wybierać runu Z2 ani przepisywać ścieżek."
        )
        source_hint = (
            "Gdy źródło tablic będzie spójne, Z3 samo przygotuje zestaw wyciętych tablic dla PZ2."
        )
    elif route == "continue":
        if has_preview:
            source_intro = (
                "PZ2 jest już gotowe dla przejętego runu Z2. "
                "PZ1 pokazuje tutaj tabelę kontrolną źródła i wynik wycinania, ale nie wymaga ponownej pracy."
            )
            source_hint = (
                "Sprawdź tabelę i przejdź do PZ2. Jeśli chcesz świadomie przygotować inny zestaw wyciętych tablic, wróć do wyboru "
                "i użyj kafla 'Wskaż anotacje do wyodrębnienia'."
            )
        else:
            source_intro = (
                "Kontynuacja przejmuje aktywne albo ostatnie źródło z Z2. "
                "Nie wskazujesz tutaj ręcznie folderu runu, XML ani obrazów; PZ1 tylko pokazuje, co zostało przejęte."
            )
            source_hint = (
                "Jeśli chcesz pracować na innym XML lub innym katalogu obrazów, wróć do wyboru i użyj kafla "
                "'Wskaż anotacje do wyodrębnienia'."
            )
    else:
        source_intro = "W tym trybie wskazujesz annotations.xml oraz oryginalny katalog obrazów. System dopilnuje zgodności XML z katalogiem."
        source_hint = "Po wskazaniu XML mogę dodatkowo spróbować dopasować katalog obrazów z Workspace/1_raw_images/."

    if linear_mode:
        if has_preview:
            start_hint = (
                "Zestaw wyciętych tablic dla znaków jest już odświeżony. "
                "Za chwilę otwieram PZ2, aby kontynuować OCR i korektę znaków."
            )
        elif source_ready:
            start_hint = (
                "Źródło tablic tej iteracji jest już gotowe. "
                "Wyodrębnianie uruchomi się automatycznie i odświeży zestaw wyciętych tablic dla PZ2."
            )
        else:
            start_hint = (
                "Czekam na spójne źródło tablic dla tej iteracji. "
                "Gdy będzie gotowe, ponowne wycinanie uruchomi się automatycznie."
            )
    elif route == "continue":
        if has_run and source_ready:
            run_name = Path(str(host.annotation_run_dir_var.get() or "")).name
            if has_preview:
                start_hint = (
                    f"Przejęty run Z2: {run_name}. Tablice są już wycięte, a tabela poniżej potwierdza źródło i gotowy wynik dla PZ2."
                )
            else:
                start_hint = (
                    f"Przejęty run Z2: {run_name}. Sprawdź tabelę i wybierz jedną z akcji na dole karty."
                )
        else:
            start_hint = (
                "Nie widzę jeszcze aktywnego źródła z Z2. "
                "Wróć do wyboru i użyj trybu ręcznego wskazania XML oraz obrazów."
            )
    else:
        if has_preview:
            start_hint = (
                "Katalog wyodrębnionych tablic dla PZ2 jest już gotowy. "
                "Ponowne wycinanie jest zablokowane dla tego zestawu."
            )
        else:
            start_hint = (
                "Źródła są gotowe. Możesz uruchomić wyodrębnianie i przygotować katalog wyodrębnionych tablic do PZ2."
                if source_ready
                else "Najpierw potwierdź zgodność źródeł, a potem uruchom wyodrębnianie."
            )

    if linear_mode and step3_status == "needs_rework":
        run_hint = (
            "Źródło tablic dla tej iteracji jest już podpięte automatycznie. "
            "Po tym kroku odświeżysz zestaw wyciętych tablic, a potem wrócisz do OCR i korekty znaków."
        )
        run_hint_tone = "success"
    elif linear_mode:
        run_hint = "Źródło tablic dla tej iteracji jest obsługiwane automatycznie przez kampanię."
        run_hint_tone = "success"
    elif route == "continue":
        if has_run:
            run_name = Path(str(host.annotation_run_dir_var.get() or "")).name
            if has_preview:
                run_hint = (
                    f"Wybrany run anotacji: {run_name}. PZ2 jest już gotowe; XML, obrazy i wynik wycinania "
                    "są pokazane w tabeli kontrolnej."
                )
            else:
                run_hint = f"Wybrany run anotacji: {run_name}. XML i katalog obrazów są wyprowadzone z tego runu."
            run_hint_tone = "success"
        elif candidate:
            run_hint = (
                f"Dostępne jest {candidate.get('label', 'źródło z Z2')}. "
                "PZ1 przejmie je automatycznie w trybie kontynuacji."
            )
            run_hint_tone = "muted"
        else:
            run_hint = (
                "Nie znaleziono aktywnego runu Z2. Zakończ pracę w Z2 albo wróć do wyboru i użyj trybu ręcznego "
                "z annotations.xml oraz zgodnym katalogiem obrazów."
            )
            run_hint_tone = "muted"
    else:
        run_hint = "Ten tryb nie wymaga folderu runu anotacji. Wystarczy annotations.xml oraz zgodny katalog obrazów."
        run_hint_tone = "muted"

    step_state = {
        "entry": "done" if route else "active",
        "source": "active",
        "start": "pending",
    }
    if source_ready:
        step_state["source"] = "done"
        step_state["start"] = "done" if has_preview else "active"

    if linear_mode:
        source_title = "Potwierdź źródło tablic"
        start_title = "Przebuduj zestaw wyciętych tablic"
        entry_card_description = "Kampania prowadzi ten etap na gotowym źródle tablic."
        source_card_description = "Źródło tablic tej iteracji jest obsługiwane automatycznie."
        start_card_description = (
            "Zestaw wyciętych tablic dla PZ2 jest już odświeżony." if has_preview
            else "Odśwież zestaw wyciętych tablic, aby wrócić do OCR i korekty znaków."
        )
    else:
        source_title = "Źródła wejścia"
        start_title = (
            "PZ2 gotowe dla przejętego runu Z2" if route == "continue" and has_preview
            else "Przejęty run anotacji Z2" if route == "continue"
            else "Uruchom wyodrębnianie"
        )
        if route == "continue" and has_preview:
            entry_card_description = "PZ2 jest już gotowe: otwórz podsumowanie i przejdź do PZ2."
        elif route == "continue":
            entry_card_description = "Kontynuacja po runie anotacji Z2 bez ręcznego wybierania źródeł."
        else:
            entry_card_description = "Wskażesz annotations.xml i obrazy."
        if route == "continue" and has_preview:
            source_card_description = "Zestaw PZ2 istnieje. Tabela pokazuje przejęty run i gotowy wynik."
        elif route == "continue" and source_ready:
            source_card_description = "Run anotacji jest potwierdzony i gotowy do wycinania."
        elif route == "continue":
            source_card_description = "Podłącz run Z2; XML i obrazy zostaną wyprowadzone automatycznie."
        else:
            source_card_description = "Powiąż annotations.xml z katalogiem obrazów."
        if route == "continue":
            start_card_description = (
                "PZ2 gotowe. Nie wycinaj ponownie; przejdź do PZ2." if has_preview
                else "Sprawdź przejęty run i wytnij tablice do PZ2."
            )
        else:
            start_card_description = (
                "Katalog wyodrębnionych tablic do PZ2 jest już gotowy." if has_preview
                else "Wytnij tablice i przygotuj preview do PZ2."
            )

    next_enabled = False
    if current == "entry":
        next_enabled = bool(route)
    elif current == "source":
        next_enabled = bool(route and (source_ready or has_preview))

    return Step3ExtractWorkflowViewModel(
        route=route,
        current_step=current,
        linear_mode=linear_mode,
        show_entry=(current == "entry" and not linear_mode),
        show_source=(current == "source" and (route in {"manual", "continue"} or linear_mode)),
        show_start=(current == "start" or (linear_mode and current == "entry")),
        source_title=source_title,
        start_title=start_title,
        source_intro=source_intro,
        source_hint=source_hint,
        run_hint=run_hint,
        run_hint_tone=run_hint_tone,
        start_hint=start_hint,
        start_hint_tone=("success" if (source_ready or has_preview) else "muted"),
        show_step_nav=(current in {"source", "start"} and not (route == "continue" and current == "start")),
        prev_enabled=(current in {"source", "start"} and not (route == "continue" and current == "start")),
        next_enabled=next_enabled,
        next_visible=current != "start",
        show_tab_nav=(
            not linear_mode
            and (not (route == "continue" and current == "start") or has_preview)
        ),
        show_back_nav=False,
        show_detect_nav=not linear_mode,
        clear_detect_emphasis=not linear_mode,
        step_cards=[
            Step3ExtractStepCardViewModel(
                key="entry",
                state=str(step_state.get("entry", "pending")),
                title="Wybierz wejście",
                description=entry_card_description,
            ),
            Step3ExtractStepCardViewModel(
                key="source",
                state=str(step_state.get("source", "pending")),
                title="Potwierdź źródła",
                description=source_card_description,
            ),
            Step3ExtractStepCardViewModel(
                key="start",
                state=str(step_state.get("start", "pending")),
                title=("PZ2 gotowe" if route == "continue" and has_preview else "Uruchom wyodrębnianie"),
                description=start_card_description,
            ),
        ],
    )


def refresh_extract_step_nav_buttons(
    host: "CharacterAnnotationTab",
    vm: Step3ExtractWorkflowViewModel | None = None,
):
    workflow_vm = vm or host._get_step3_extract_workflow_view_model()
    nav_row = getattr(host, "extract_step_nav_row", None)
    prev_btn = getattr(host, "extract_step_back_btn", None)
    next_btn = getattr(host, "extract_step_next_btn", None)
    main_nav_panel = getattr(host, "extract_main_nav_panel", None)
    back_btn = getattr(host, "btn_back_to_wizard_step3", None)
    detect_frame = getattr(host, "btn_to_detect_frame", None)

    if prev_btn is not None:
        try:
            prev_btn.config(state=tk.NORMAL if workflow_vm.prev_enabled else tk.DISABLED)
        except Exception:
            pass

    if next_btn is not None:
        try:
            next_btn.config(state=tk.NORMAL if workflow_vm.next_enabled else tk.DISABLED)
        except Exception:
            pass

        try:
            if not workflow_vm.next_visible:
                if str(next_btn.winfo_manager()):
                    next_btn.pack_forget()
            elif not str(next_btn.winfo_manager()):
                next_btn.pack(side=tk.LEFT, padx=(8, 0))
        except Exception:
            pass

    if back_btn is not None:
        try:
            if workflow_vm.show_back_nav:
                if not str(back_btn.winfo_manager()):
                    back_btn.grid(row=0, column=0, sticky="w")
            elif str(back_btn.winfo_manager()):
                back_btn.grid_remove()
        except Exception:
            pass

    if detect_frame is not None:
        try:
            if not workflow_vm.show_detect_nav:
                if str(detect_frame.winfo_manager()):
                    detect_frame.grid_remove()
            elif not str(detect_frame.winfo_manager()):
                detect_frame.grid(row=0, column=2, sticky="e")
        except Exception:
            pass

    try:
        if nav_row is not None and str(nav_row.winfo_manager()):
            nav_row.pack_forget()
        if main_nav_panel is not None and str(main_nav_panel.winfo_manager()):
            main_nav_panel.grid_remove()

        if workflow_vm.show_step_nav and nav_row is not None:
            nav_row.pack(fill=tk.X, pady=(0, 8))

        if workflow_vm.show_tab_nav and main_nav_panel is not None:
            main_nav_panel.grid()
    except Exception:
        pass

    if workflow_vm.clear_detect_emphasis:
        try:
            host._set_button_emphasis("btn_to_detect_frame", False)
        except Exception:
            pass
    try:
        host._refresh_campaign_step3_navigation_visibility()
    except Exception:
        pass


def refresh_extract_step_cards(
    host: "CharacterAnnotationTab",
    vm: Step3ExtractWorkflowViewModel | None = None,
):
    cards = getattr(host, "_extract_step_cards", []) or []
    if not cards:
        return

    palette = getattr(host.app, "palette", {})
    panel = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    hover_bg = palette.get("button_hover", panel_alt)
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    active_bg = blend_hex_colors(panel_alt, hover_bg, 0.42)
    done_bg = blend_hex_colors(panel_alt, hover_bg, 0.18)
    workflow_vm = vm or host._get_step3_extract_workflow_view_model()
    step_cards_by_key = {
        str(card.key or ""): card
        for card in list(getattr(workflow_vm, "step_cards", []) or [])
    }

    for entry in cards:
        key = str(entry.get("key") or "").strip()
        card_vm = step_cards_by_key.get(key)
        state = str(getattr(card_vm, "state", "pending") or "pending")
        frame = entry.get("frame")
        badge = entry.get("badge")
        title_lbl = entry.get("title")
        desc_lbl = entry.get("desc")

        if state == "done":
            card_bg = done_bg
            border_color = border
            badge_fg = fg
            title_fg = fg
            desc_fg = fg
        elif state == "active":
            card_bg = active_bg
            border_color = border
            badge_fg = fg
            title_fg = fg
            desc_fg = fg
        else:
            card_bg = panel_alt
            border_color = border
            badge_fg = muted
            title_fg = fg
            desc_fg = muted

        for widget in (frame, badge, title_lbl, desc_lbl):
            if widget is None:
                continue
            try:
                widget.configure(bg=card_bg, highlightbackground=border_color, highlightcolor=border_color)
            except Exception:
                pass

        try:
            badge.configure(fg=badge_fg)
        except Exception:
            pass
        try:
            title_lbl.configure(
                fg=title_fg,
                text=str(getattr(card_vm, "title", "") or entry.get("default_title", "")),
            )
        except Exception:
            pass
        try:
            desc_lbl.configure(
                fg=desc_fg,
                text=str(getattr(card_vm, "description", "") or entry.get("default_desc", "")),
            )
        except Exception:
            pass


def refresh_pz3_status_panel_ui(
    host: "CharacterAnnotationTab",
    vm: Step3Pz3StatusPanelViewModel | None = None,
):
    status_vm = vm or host._get_step3_pz3_status_panel_view_model()

    try:
        title_lbl = getattr(host, "dataset_status_title_lbl", None)
        if title_lbl is not None:
            title_lbl.configure(text=str(status_vm.title or "Podsumowanie"))
    except Exception:
        pass

    for key_widget_name, value_widget_name, row_vm in (
        ("export_status_key_lbl", "export_console", status_vm.export_row),
        ("import_status_key_lbl", "import_console", status_vm.import_row),
    ):
        key_widget = getattr(host, key_widget_name, None)
        if key_widget is not None:
            try:
                key_widget.configure(text=str(row_vm.label or ""))
            except Exception:
                pass

        widget = getattr(host, value_widget_name, None)
        if widget is None:
            continue
        try:
            host._set_inline_status_label_state(
                widget,
                text=str(row_vm.text or ""),
                tone=str(row_vm.tone or "muted"),
                emphasis=False,
            )
        except Exception:
            try:
                widget.configure(text=str(row_vm.text or ""))
            except Exception:
                pass

    btn = getattr(host, "btn_finish_step3", None)
    btn_frame = getattr(host, "btn_finish_step3_frame", None)
    card_frame = getattr(host, "step3_finish_card", None)
    action_card = getattr(host, "step3_finish_action_card", None)
    finish_vm = status_vm.finish_action
    if btn is None:
        return

    try:
        if card_frame is not None:
            if bool(finish_vm.visible):
                if not str(card_frame.winfo_manager()):
                    card_frame.pack(anchor=tk.E)
            elif str(card_frame.winfo_manager()):
                card_frame.pack_forget()
        if btn_frame is not None:
            if bool(finish_vm.visible):
                if not str(btn_frame.winfo_manager()):
                    btn_frame.pack(fill=tk.X)
            elif str(btn_frame.winfo_manager()):
                btn_frame.pack_forget()
    except Exception:
        pass

    if not bool(finish_vm.visible):
        try:
            if action_card is not None:
                action_card.set_emphasis(False)
            else:
                host._set_button_emphasis("btn_finish_step3_frame", False)
        except Exception:
            pass
        host._set_step3_finish_hint("")
        return

    try:
        command = host._resolve_step3_campaign_action_command(finish_vm.command_id)
        target_style = "Accent.TButton" if bool(finish_vm.emphasize) else "WorkflowCard.TButton"
        if action_card is not None:
            action_card.configure_action(
                text=str(finish_vm.label or ""),
                command=command,
                state=("normal" if bool(finish_vm.enabled) else "disabled"),
                width=host.NAV_BUTTON_WIDTH + 2 if hasattr(host, "NAV_BUTTON_WIDTH") else 20,
                style=target_style,
                padding=(10, 3),
            )
        else:
            btn.config(
                text=str(finish_vm.label or ""),
                command=command,
                state=("normal" if bool(finish_vm.enabled) else "disabled"),
                width=18 + 2,
                style=target_style,
            )

        if bool(finish_vm.emphasize):
            if action_card is not None:
                action_card.set_emphasis(True)
            else:
                host._set_button_emphasis("btn_finish_step3_frame", True)
            host._set_step3_finish_hint("")
        else:
            if action_card is not None:
                action_card.set_emphasis(False)
            else:
                host._set_button_emphasis("btn_finish_step3_frame", False)
            host._set_step3_finish_hint(str(finish_vm.hint or ""), tone=str(finish_vm.hint_tone or "muted"))
    except Exception as exc:
        try:
            from ..config import logger

            logger.debug(f"Nie udało się odświeżyć panelu statusu PZ3: {exc}")
        except Exception:
            pass


def refresh_extract_entry_cards(host: "CharacterAnnotationTab"):
    cards = getattr(host, "_extract_entry_cards", {}) or {}
    if not cards:
        return

    palette = getattr(host.app, "palette", {})
    selected_mode = host._get_extract_entry_mode()
    hover_mode = getattr(host, "_extract_entry_hover_mode", None)
    panel = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    hover_bg = palette.get("button_hover", panel_alt)
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    selected_bg = blend_hex_colors(panel_alt, hover_bg, 0.42)
    try:
        preview_ready = bool(host._is_extract_preview_ready())
    except Exception:
        preview_ready = False
    source_ready = bool(getattr(host, "_extract_last_source_binding_result", {}).get("ok"))

    for mode, widgets in cards.items():
        is_selected = mode == selected_mode
        is_hovered = mode == hover_mode
        card_bg = selected_bg if is_selected else (hover_bg if is_hovered else panel_alt)
        border_color = border
        title_fg = fg
        desc_fg = fg if is_selected else muted
        badge_fg = fg if is_selected else muted

        for widget_name in ("frame", "badge", "title", "desc"):
            widget = widgets.get(widget_name)
            if widget is None:
                continue
            try:
                widget.configure(bg=card_bg, highlightbackground=border_color, highlightcolor=border_color)
            except Exception:
                pass

        try:
            widgets["badge"].configure(fg=badge_fg)
        except Exception:
            pass
        try:
            title_text = ""
            if mode == "continue":
                title_text = "Kontynuuj na runie anotacji"
            elif mode == "manual":
                title_text = "Wskaż anotacje do wyodrębnienia"
            widgets["title"].configure(fg=title_fg, text=title_text or str(widgets["title"].cget("text") or ""))
        except Exception:
            pass
        try:
            desc_text = ""
            if mode == "continue" and preview_ready:
                desc_text = (
                    "Tablice są już wycięte. Otwórz kafel, aby przejrzeć tabelę przejętego runu "
                    "i gotowego wyniku, lub od razu przejdź do podzakładki PZ3 aby z nimi pracować."
                )
            elif mode == "continue" and source_ready:
                desc_text = (
                    "Przejmij potwierdzony run Z2. PZ1 pokaże tabelę źródła i pozwoli wyciąć tablice do PZ2."
                )
            elif mode == "continue":
                desc_text = (
                    "Przejmij aktywny albo ostatni run anotacji Z2. "
                    "W tym torze nie wskazujesz ręcznie folderu runu, XML ani obrazów."
                )
            elif mode == "manual":
                desc_text = (
                    "Podaj annotations.xml oraz folder oryginalnych obrazów, z których mam "
                    "wyciąć tablice. To dobry tor dla importu z zewnątrz."
                )
            widgets["desc"].configure(fg=desc_fg, text=desc_text or str(widgets["desc"].cget("text") or ""))
        except Exception:
            pass
        try:
            badge = widgets.get("badge")
            title_widget = widgets.get("title")
            if mode == "continue" and preview_ready:
                badge.configure(text="TABLICE WYCIĘTE", fg=palette.get("success", badge_fg))
                if not str(badge.winfo_manager()):
                    badge.pack(anchor=tk.W, fill=tk.X, before=title_widget)
            elif mode == "continue" and source_ready:
                badge.configure(text="ŹRÓDŁO OK", fg=palette.get("success", badge_fg))
                if not str(badge.winfo_manager()):
                    badge.pack(anchor=tk.W, fill=tk.X, before=title_widget)
            elif badge is not None and str(badge.winfo_manager()):
                badge.pack_forget()
        except Exception:
            pass


def refresh_pz3_dataset_source_card(
    host: "CharacterAnnotationTab",
    card_info,
    *,
    selected: bool,
    hovered: bool,
    badge_text: str,
    title_text: str,
    desc_text: str,
):
    card_palette = host._get_pz3_card_palette()
    current_card_bg = card_palette["card_active_bg"] if selected else (
        card_palette["card_hover_bg"] if hovered else card_palette["card_bg"]
    )
    border_color = card_palette["card_border"]
    for widget in (
        card_info.get("frame"),
        card_info.get("top_row"),
        card_info.get("badge"),
        card_info.get("state_badge"),
        card_info.get("title"),
        card_info.get("desc"),
    ):
        if widget is None:
            continue
        try:
            widget.configure(
                bg=current_card_bg,
                highlightbackground=border_color,
                highlightcolor=border_color,
                cursor="hand2",
            )
        except Exception:
            pass
    try:
        card_info["badge"].configure(
            text=host._normalize_pz3_card_badge_text(badge_text),
            fg=(card_palette["card_fg"] if selected else card_palette["card_muted"]),
        )
    except Exception:
        pass
    host._refresh_pz3_card_state_badge(
        card_info,
        selected=bool(selected),
        current_card_bg=current_card_bg,
        card_palette=card_palette,
    )
    try:
        card_info["title"].configure(text=title_text, fg=card_palette["card_fg"])
    except Exception:
        pass
    host._set_inline_status_label_state(
        card_info["desc"],
        text=desc_text,
        tone=("default" if selected else "muted"),
        emphasis=False,
    )
    try:
        card_info["desc"].configure(fg=(card_palette["card_fg"] if selected else card_palette["card_muted"]))
    except Exception:
        pass


def refresh_pz3_dataset_mode_ui(host: "CharacterAnnotationTab"):
    vm = host._get_step3_pz3_dataset_mode_view_model()
    dataset_source_lf = getattr(host, "_pz3_dataset_source_lf", None)
    dataset_source_cards = getattr(host, "_pz3_dataset_source_cards", None)
    dataset_source_perfect_card = getattr(host, "_pz3_dataset_source_perfect_card", None)
    dataset_source_existing_card = getattr(host, "_pz3_dataset_source_existing_card", None)
    dataset_source_card_state = getattr(host, "_pz3_dataset_source_card_state", {}) or {}

    try:
        if dataset_source_lf is not None:
            dataset_source_lf.configure(text=str(vm.dataset_source_title or ""))
    except Exception:
        pass
    host._set_inline_status_label_state(
        host.pz3_dataset_source_intro_lbl,
        text=str(vm.dataset_source_intro or ""),
        tone="muted",
        emphasis=False,
    )
    for widget_name, text_value, tone_value in (
        ("pz3_source_preview_status_lbl", vm.source_preview_text, vm.source_preview_tone),
        ("pz3_source_pool_status_lbl", vm.source_pool_text, vm.source_pool_tone),
        ("pz3_source_next_status_lbl", vm.source_next_text, vm.source_next_tone),
    ):
        widget = getattr(host, widget_name, None)
        if widget is None:
            continue
        host._set_inline_status_label_state(
            widget,
            text=str(text_value or ""),
            tone=str(tone_value or "muted"),
            emphasis=False,
        )

    try:
        if dataset_source_cards is not None:
            if not bool(vm.show_dataset_source_cards):
                if str(dataset_source_cards.winfo_manager()):
                    dataset_source_cards.pack_forget()
            elif not str(dataset_source_cards.winfo_manager()):
                dataset_source_cards.pack(fill=tk.X)
    except Exception:
        pass

    if dataset_source_perfect_card is not None:
        refresh_pz3_dataset_source_card(
            host,
            dataset_source_perfect_card,
            selected=bool(vm.perfect_selected),
            hovered=bool(dataset_source_card_state.get("perfect_hovered", False)),
            badge_text=str(vm.perfect_badge_text or ""),
            title_text=str(vm.perfect_title_text or ""),
            desc_text=str(vm.perfect_desc_text or ""),
        )
    if dataset_source_existing_card is not None:
        refresh_pz3_dataset_source_card(
            host,
            dataset_source_existing_card,
            selected=bool(vm.existing_selected),
            hovered=bool(dataset_source_card_state.get("existing_hovered", False)),
            badge_text=str(vm.existing_badge_text or ""),
            title_text=str(vm.existing_title_text or ""),
            desc_text=str(vm.existing_desc_text or ""),
        )

    if bool(vm.perfect_selected):
        if str(host.pz3_existing_dataset_panel.winfo_manager()):
            host.pz3_existing_dataset_panel.pack_forget()
        try:
            host.cvat_option2_title_lbl.configure(text=str(vm.cvat_option2_title or ""))
        except Exception:
            pass
        host._set_inline_status_label_state(
            host.cvat_option2_title_lbl,
            tone=str(vm.cvat_option2_tone or "muted"),
            emphasis=str(vm.cvat_option2_tone or "").strip().lower() == "success",
        )
        host._set_inline_status_label_state(host.cvat_option2_desc_lbl, text=str(vm.cvat_option2_desc or ""), tone="muted", emphasis=False)
        try:
            goldpack_lf = getattr(host, "gold_export_goldpack_lf", None) or getattr(host, "gold_export_filters_lf", None)
            if bool(vm.show_gold_filters) and goldpack_lf is not None:
                goldpack_lf.grid()
            elif goldpack_lf is not None and str(goldpack_lf.winfo_manager()):
                goldpack_lf.grid_remove()
        except Exception:
            pass
        try:
            if str(host.gold_export_split_lf.winfo_manager()):
                host.gold_export_split_lf.grid_remove()
        except Exception:
            pass
        try:
            host.btn_yolo_gold_export.configure(
                text=str(vm.primary_export_label or ""),
                command=(
                    host._run_yolo_gold_export
                    if str(vm.primary_export_command_id or "") == "run_yolo_gold_export"
                    else host._run_pz3_existing_dataset_split
                ),
                style="Accent.TButton",
                state=(tk.NORMAL if bool(vm.primary_export_enabled) else tk.DISABLED),
            )
            host.btn_yolo_gold_export.grid_configure(
                column=0,
                columnspan=max(1, int(vm.primary_export_columnspan or 1)),
                padx=((0, 4) if int(vm.primary_export_columnspan or 1) == 1 else (0, 0)),
            )
        except Exception:
            pass
        try:
            if bool(vm.show_classifier_export) and not str(host.btn_char_classifier_export.winfo_manager()):
                host.btn_char_classifier_export.grid(row=0, column=1, sticky="ew", padx=(4, 0), ipady=4)
            elif (not bool(vm.show_classifier_export)) and str(host.btn_char_classifier_export.winfo_manager()):
                host.btn_char_classifier_export.grid_remove()
        except Exception:
            pass
        try:
            host.btn_char_classifier_export.configure(
                state=(tk.NORMAL if bool(vm.classifier_export_enabled) else tk.DISABLED)
            )
        except Exception:
            pass
        host._set_inline_status_label_state(
            host.pz3_dataset_action_hint_lbl,
            text=str(vm.action_hint or ""),
            tone=str(vm.action_hint_tone or "muted"),
            emphasis=False,
        )
        return

    if bool(vm.show_existing_dataset_panel) and not str(host.pz3_existing_dataset_panel.winfo_manager()):
        host.pz3_existing_dataset_panel.pack(fill=tk.X, pady=(10, 0))

    try:
        host.cvat_option2_title_lbl.configure(text=str(vm.cvat_option2_title or ""))
    except Exception:
        pass
    host._set_inline_status_label_state(
        host.cvat_option2_title_lbl,
        tone=str(vm.cvat_option2_tone or "default"),
        emphasis=str(vm.cvat_option2_tone or "").strip().lower() == "success",
    )
    host._set_inline_status_label_state(host.cvat_option2_desc_lbl, text=str(vm.cvat_option2_desc or ""), tone="muted", emphasis=False)
    host._set_inline_status_label_state(
        host.pz3_existing_dataset_status_lbl,
        text=str(vm.existing_dataset_status or ""),
        tone=str(vm.existing_dataset_status_tone or "muted"),
        emphasis=False,
    )
    try:
        goldpack_lf = getattr(host, "gold_export_goldpack_lf", None) or getattr(host, "gold_export_filters_lf", None)
        if not bool(vm.show_gold_filters) and goldpack_lf is not None and str(goldpack_lf.winfo_manager()):
            goldpack_lf.grid_remove()
        elif bool(vm.show_gold_filters) and goldpack_lf is not None:
            goldpack_lf.grid()
    except Exception:
        pass
    try:
        if str(host.gold_export_split_lf.winfo_manager()):
            host.gold_export_split_lf.grid_remove()
    except Exception:
        pass
    try:
        if not bool(vm.show_classifier_export):
            host.btn_char_classifier_export.grid_remove()
    except Exception:
        pass
    try:
        host.btn_yolo_gold_export.configure(
            text=str(vm.primary_export_label or ""),
            command=(
                host._run_yolo_gold_export
                if str(vm.primary_export_command_id or "") == "run_yolo_gold_export"
                else host._run_pz3_existing_dataset_split
            ),
            style="Accent.TButton",
            state=(tk.NORMAL if bool(vm.primary_export_enabled) else tk.DISABLED),
        )
        host.btn_yolo_gold_export.grid_configure(
            column=0,
            columnspan=max(1, int(vm.primary_export_columnspan or 1)),
            padx=((0, 4) if int(vm.primary_export_columnspan or 1) == 1 else (0, 0)),
        )
    except Exception:
        pass
    host._set_inline_status_label_state(
        host.pz3_dataset_action_hint_lbl,
        text=str(vm.action_hint or ""),
        tone=str(vm.action_hint_tone or "muted"),
        emphasis=False,
    )


def refresh_pz3_dataset_card(host: "CharacterAnnotationTab"):
    panel_vm = host._get_step3_pz3_path_selection_view_model()
    card_info = getattr(host, "_pz3_dataset_card", None)
    state = getattr(host, "_pz3_dataset_card_state", {}) or {}
    if card_info is None:
        return
    selected = bool(panel_vm.dataset_card_selected)
    hovered = bool(state.get("hovered", False))
    card_palette = host._get_pz3_card_palette()
    current_card_bg = card_palette["card_active_bg"] if selected else (
        card_palette["card_hover_bg"] if hovered else card_palette["card_bg"]
    )
    border_color = card_palette["card_border"]

    for widget in (
        card_info.get("frame"),
        card_info.get("top_row"),
        card_info.get("badge"),
        card_info.get("state_badge"),
        card_info.get("title"),
        card_info.get("desc"),
    ):
        if widget is None:
            continue
        try:
            widget.configure(bg=current_card_bg, highlightbackground=border_color, highlightcolor=border_color, cursor="hand2")
        except Exception:
            pass
    try:
        card_info["badge"].configure(
            text=host._normalize_pz3_card_badge_text(str(panel_vm.dataset_badge_text or "")),
            fg=(card_palette["card_fg"] if selected else card_palette["card_muted"]),
        )
    except Exception:
        pass
    host._refresh_pz3_card_state_badge(
        card_info,
        selected=bool(selected),
        current_card_bg=current_card_bg,
        card_palette=card_palette,
    )
    try:
        card_info["title"].configure(text=str(panel_vm.dataset_title_text or ""), fg=card_palette["card_fg"])
    except Exception:
        pass
    host._set_inline_status_label_state(
        card_info["desc"],
        text=str(panel_vm.dataset_desc_text or ""),
        tone=("default" if selected else "muted"),
        emphasis=False,
    )
    try:
        card_info["desc"].configure(fg=(card_palette["card_fg"] if selected else card_palette["card_muted"]))
    except Exception:
        pass


def refresh_pz3_cvat_card(host: "CharacterAnnotationTab"):
    panel_vm = host._get_step3_pz3_path_selection_view_model()
    card_info = getattr(host, "_pz3_review_card", None)
    state = getattr(host, "_pz3_cvat_card_state", {}) or {}
    if card_info is None:
        return
    expanded = bool(panel_vm.cvat_card_selected)
    hovered = bool(state.get("hovered", False))
    card_palette = host._get_pz3_card_palette()
    current_card_bg = card_palette["card_active_bg"] if expanded else (
        card_palette["card_hover_bg"] if hovered else card_palette["card_bg"]
    )
    border_color = card_palette["card_border"]
    desc_text = str(panel_vm.cvat_desc_text or "")
    badge_text = str(panel_vm.cvat_badge_text or "")
    title_text = str(panel_vm.cvat_title_text or "")

    for widget in (
        card_info.get("frame"),
        card_info.get("top_row"),
        card_info.get("badge"),
        card_info.get("state_badge"),
        card_info.get("title"),
        card_info.get("desc"),
    ):
        if widget is None:
            continue
        try:
            widget.configure(bg=current_card_bg, highlightbackground=border_color, highlightcolor=border_color, cursor="hand2")
        except Exception:
            pass
    try:
        card_info["badge"].configure(
            text=host._normalize_pz3_card_badge_text(badge_text),
            fg=(card_palette["card_fg"] if expanded else card_palette["card_muted"]),
        )
    except Exception:
        pass
    host._refresh_pz3_card_state_badge(
        card_info,
        selected=bool(expanded),
        current_card_bg=current_card_bg,
        card_palette=card_palette,
    )
    try:
        card_info["title"].configure(text=title_text, fg=card_palette["card_fg"])
    except Exception:
        pass
    host._set_inline_status_label_state(card_info["desc"], text=desc_text, tone=("default" if expanded else "muted"), emphasis=False)
    try:
        card_info["desc"].configure(fg=(card_palette["card_fg"] if expanded else card_palette["card_muted"]))
    except Exception:
        pass


def refresh_pz3_cards_ui(host: "CharacterAnnotationTab"):
    panel_vm = host._get_step3_pz3_path_selection_view_model()
    dataset_section = getattr(host, "pz3_dataset_section", None)
    overview_section = getattr(host, "_pz3_overview_section", None)
    host._pz3_cvat_expanded = str(panel_vm.selected_path or "") == "cvat"
    try:
        if dataset_section is not None:
            if not str(dataset_section.winfo_manager()):
                dataset_section.pack(fill=tk.X, pady=(12, 0), after=overview_section)
        if bool(panel_vm.show_cvat_section):
            if not str(host.pz3_cvat_section.winfo_manager()):
                host.pz3_cvat_section.pack(fill=tk.X, pady=(12, 0))
        else:
            if str(host.pz3_cvat_section.winfo_manager()):
                host.pz3_cvat_section.pack_forget()
    except Exception:
        pass
    try:
        status_section_widget = getattr(host, "pz3_status_section", None)
        if status_section_widget is not None:
            if str(status_section_widget.winfo_manager()):
                status_section_widget.pack_forget()
    except Exception:
        pass
    refresh_pz3_dataset_card(host)
    refresh_pz3_cvat_card(host)
    try:
        refresh_pz3_status_panel_ui(host)
    except Exception:
        pass


def refresh_step3_mode_specific_ui(host: "CharacterAnnotationTab"):
    in_campaign = bool(getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())

    host._set_grid_visibility(getattr(host, "preview_source_lf", None), (not in_campaign))
    host._set_grid_visibility(getattr(host, "preview_counts_frame", None), (not in_campaign))
    host._set_grid_visibility(getattr(host, "preview_fusion_info_lbl", None), False)
    host._set_grid_visibility(getattr(host, "preview_box_mode_info_lbl", None), False)
    for attr_name in (
        "preview_repair_progress_title_lbl",
        "preview_repair_progress",
        "preview_repair_progress_status_lbl",
    ):
        host._set_grid_visibility(getattr(host, attr_name, None), True)

    try:
        note = getattr(host, "preview_load_note_lbl", None)
        if note is not None:
            note_text = (
                "Szczegóły stanu i liczbę tablic sprawdzisz na liście po lewej stronie."
                if in_campaign
                else (
                    "Poniżej widzisz liczbę tablic perfect oraz ocenę, "
                    "czy zbiór ma sens jako źródło treningowe."
                )
            )
            host._set_inline_status_label_state(
                note,
                text=note_text,
                tone="muted",
                emphasis=False,
            )
    except Exception:
        pass

    host._set_grid_visibility(getattr(host, "test_progress_row", None), (not in_campaign))

    try:
        refresh = getattr(host, "_refresh_pz3_dataset_mode_ui", None)
        if callable(refresh):
            refresh()
    except Exception:
        pass

    try:
        refresh = getattr(host, "_refresh_pz3_cards_ui", None)
        if callable(refresh):
            refresh()
    except Exception:
        pass

    for refresh_name in (
        "_refresh_gold_export_filter_labels",
        "_refresh_gold_export_source_labels",
        "_refresh_gold_export_scope_label",
    ):
        try:
            refresh_fn = getattr(host, refresh_name, None)
            if callable(refresh_fn):
                refresh_fn()
        except Exception:
            pass

    try:
        host._update_preview_repair_progress_ui()
        if not in_campaign:
            host._set_test_progress_counter()
    except Exception:
        pass


def sync_step3_nav_buttons(host: "CharacterAnnotationTab"):
    detect_enabled = host._get_subtab_state(host.tab_detect) == "normal"
    dataset_enabled = host._get_subtab_state(host.tab_dataset) == "normal"

    if hasattr(host, "btn_to_detect"):
        host.btn_to_detect.config(state=tk.NORMAL if detect_enabled else tk.DISABLED)

    if hasattr(host, "btn_to_dataset"):
        host.btn_to_dataset.config(state=tk.NORMAL if dataset_enabled else tk.DISABLED)
