#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z3 subtab navigation and preview-source state helpers extracted from tab_character_annotation.py."""

from __future__ import annotations

import json
from pathlib import Path

from ..campaign_manager import CAMPAIGN
from ..config import CONFIG
from ..config import logger


def _refresh_preview_source_panel(self):
    status_lbl = getattr(self, "preview_source_status_lbl", None)
    detail_lbl = getattr(self, "preview_source_detail_lbl", None)

    if status_lbl is None or detail_lbl is None:
        return

    preview_dir_raw = str(self.preview_dir_var.get() if hasattr(self, "preview_dir_var") else "").strip()
    count = 0
    try:
        loaded_meta_path = getattr(self, "_loaded_meta_path", None)
        loaded_preview_dir = str(Path(loaded_meta_path).parent) if loaded_meta_path else ""
        if preview_dir_raw and loaded_preview_dir and Path(preview_dir_raw).resolve() == Path(loaded_preview_dir).resolve():
            count = len(getattr(self, "preview_metadata", {}) or {})
    except Exception:
        count = 0
    if count <= 0:
        count = self._get_preview_dir_plate_count(preview_dir_raw) if preview_dir_raw else 0
    preview_name = ""
    if preview_dir_raw:
        try:
            preview_name = Path(preview_dir_raw).name
        except Exception:
            preview_name = preview_dir_raw

    if preview_dir_raw and count > 0:
        status_text = f"Aktywny preview run z PZ1: {preview_name}"
        detail_text = f"Wyodrębnione tablice: {count}. PZ2 pracuje teraz na tym zestawie cropów."
        tone = "success"
    elif preview_dir_raw:
        status_text = f"Aktywny preview run wymaga sprawdzenia: {preview_name}"
        detail_text = "Nie widzę poprawnego metadata.json + images/ albo zestaw nie zawiera tablic. Wróć do PZ1 i ponownie wyodrębnij tablice."
        tone = "warning"
    else:
        status_text = "Brak aktywnego preview runu z PZ1"
        detail_text = "Najpierw uruchom wyodrębnianie w PZ1. PZ2 nie wybiera źródła ręcznie, tylko pracuje na wyniku PZ1."
        tone = "warning"

    self._set_inline_status_label_state(status_lbl, text=status_text, tone=tone, emphasis=True)
    self._set_inline_status_label_state(detail_lbl, text=detail_text, tone="muted", emphasis=False)

def _select_subtab(self, tab_widget):
    if not self._ensure_step3_subtab_built(tab_widget):
        return

    try:
        self.main_nb.select(str(tab_widget))
    except Exception as e:
        logger.debug(f"Nie udało się przełączyć podzakładki: {e}")

    if (
        tab_widget is getattr(self, "tab_detect", None)
        and not bool(getattr(self, "_campaign_pz2_sync_loading", False))
    ):
        try:
            self._schedule_detection_preview_autoload()
        except Exception:
            pass

def _on_main_nb_tab_changed(self, event=None):
    if event is not None and getattr(event, "widget", None) is not self.main_nb:
        return

    try:
        notify = getattr(self.app, "notify_free_mode_assistant_context_changed", None)
        if callable(notify):
            notify()
    except Exception:
        pass

    try:
        selected_tab = str(self.main_nb.select())
    except Exception:
        selected_tab = ""

    if selected_tab == str(getattr(self, "tab_detect", "")):
        if not self._ensure_detect_tab_built():
            return
    elif selected_tab == str(getattr(self, "tab_dataset", "")):
        if not self._ensure_dataset_tab_built():
            return

    if selected_tab == str(getattr(self, "tab_detect", "")):
        try:
            if not bool(getattr(self, "_campaign_pz2_sync_loading", False)):
                self._schedule_detection_preview_autoload()
        except Exception:
            pass
        try:
            self._sync_step3_access_from_preview_state(getattr(self, "preview_metadata", None))
        except Exception:
            pass
        try:
            self.frame.after(
                180,
                lambda: self._sync_step3_access_from_preview_state(getattr(self, "preview_metadata", None)),
            )
        except Exception:
            pass

    if not getattr(self, "_step3_linear_mode", False):
        return

    if not CAMPAIGN.get_active_project_name():
        return

    self._persist_step3_progress()

def campaign_step3_pz2_base_ready(self) -> bool:
    """
    Lokalny warunek przejścia PZ2 -> PZ3.

    Nie sprawdza jeszcze datasetu PZ3 ani zakresu eksportu. To tylko pytanie,
    czy PZ2 ma minimalną bazę tablic perfect, z którą użytkownik może przejść
    do kroku eksportu.
    """
    try:
        if not bool(getattr(self, "_step3_linear_mode", False)):
            return False
        if bool(getattr(self, "_campaign_step3_hold_pz2_after_reextract", False)):
            return False
    except Exception:
        return False

    try:
        min_required = int(getattr(CONFIG, "CAMPAIGN_MIN_CHAR_PLATES", 10) or 10)
    except Exception:
        min_required = 10

    try:
        counts = self._count_preview_statuses()
        perfect_count = int((counts or {}).get("perfect", 0) or 0)
        return perfect_count >= max(1, int(min_required))
    except Exception:
        pass

    preview_dir_raw = ""
    try:
        preview_dir_raw = str(self.preview_dir_var.get() or "").strip()
    except Exception:
        preview_dir_raw = ""
    if not preview_dir_raw:
        try:
            preview_dir_raw = str(self._get_saved_step3_preview_dir(require_plates=True) or "").strip()
        except Exception:
            preview_dir_raw = ""
    if preview_dir_raw:
        try:
            summary_path = Path(preview_dir_raw) / "last_detection_summary.json"
            if summary_path.exists():
                with open(summary_path, "r", encoding="utf-8") as handle:
                    summary = json.load(handle)
                perfect_count = int((summary or {}).get("perfect", 0) or 0)
                if perfect_count >= max(1, int(min_required)):
                    return True
        except Exception:
            pass

    try:
        readiness = self._get_campaign_step3_annotation_readiness()
        perfect_count = int(readiness.get("perfect_count", 0) or 0)
        fallback_min = int(readiness.get("min_exportable_plate_count", min_required) or min_required)
        return perfect_count >= max(1, int(fallback_min))
    except Exception:
        return False


def can_restore_step3_substep(self, substep: int) -> bool:
    """
    Sprawdza, czy dla zapisanego substepu istnieją realne artefakty
    pozwalające wejść do tego miejsca workflow.
    """
    substep = int(substep)

    # substep 1 zawsze można otworzyć, jeśli mamy źródła z wizarda
    if substep <= 1:
        xml_ok = bool((self.xml_path_var.get() or "").strip())
        img_ok = bool((self.images_dir_var.get() or "").strip())
        return xml_ok and img_ok

    # substep 2 i 3 wymagają preview runu z metadata i katalogiem images
    preview_dir_raw = (self.preview_dir_var.get() or "").strip()
    if not preview_dir_raw:
        try:
            preview_dir_raw = str(self._get_saved_step3_preview_dir(require_plates=True) or "").strip()
        except Exception:
            preview_dir_raw = ""
    if not preview_dir_raw:
        try:
            preview_dir_raw = str(
                self._get_preferred_step3_preview_dir(require_plates=True, allow_fallback=False)
                or ""
            ).strip()
        except Exception:
            preview_dir_raw = ""
    if not preview_dir_raw:
        return False

    preview_dir = Path(preview_dir_raw)
    if not self._is_usable_step3_preview_dir(
        preview_dir,
        require_plates=True,
        check_campaign_inflated=False,
    ):
        return False

    try:
        if str(self.preview_dir_var.get() or "").strip() != str(preview_dir):
            self.preview_dir_var.set(str(preview_dir))
    except Exception:
        pass

    meta_file = preview_dir / "metadata.json"
    images_dir = preview_dir / "images"

    if not meta_file.exists():
        return False

    if not images_dir.exists() or not images_dir.is_dir():
        return False

    if substep >= 2 and not self._campaign_preview_meets_min_extracted_plate_count(preview_dir):
        return False

    # substep 3 dodatkowo wymaga, żeby etap 2 był realnie zakończony
    if substep >= 3:
        try:
            if bool(getattr(self, "_campaign_step3_hold_pz2_after_reextract", False)):
                return False
        except Exception:
            pass
        try:
            if bool(CAMPAIGN.is_step3_stage2_done()):
                return True
        except Exception:
            pass
        if campaign_step3_pz2_base_ready(self):
            return True
        try:
            if bool(getattr(self, "_step3_linear_mode", False)) and bool(
                self._get_campaign_step3_annotation_readiness().get("ok")
            ):
                return True
        except Exception:
            pass
        return self._preview_dir_has_completed_detection_output(preview_dir)

    return True
