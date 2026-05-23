#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Panel kampanii i etapow projektu.
"""

import json
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from textwrap import shorten
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
import xml.etree.ElementTree as ET
import shutil
import threading

from ..config import CONFIG, logger, PIL_AVAILABLE, Image, ImageTk, ImageDraw, ImageFont
from ..campaign_manager import CAMPAIGN
from ..campaign_ingest_planner import CHAR_ALPHABET, CampaignIngestPlanner
from ..validators import validate_model_file, format_yolo_model_identity
from ..icons import IconManager
from ..project_cache import PROJECT_CACHE
from .help_manager import HELP
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors
from .z2_view_models import Step2CtaViewModel, Step2ViewModel
from .z3_view_models import Step3ViewModel


@dataclass
class WizardStageStatus:
    key: str
    title: str
    state: str
    summary: str = ""
    details: str = ""
    primary_label: str = ""
    primary_command: object = None
    secondary_label: str = ""
    secondary_command: object = None
    badge_action_label: str = ""
    badge_action_command: object = None
    body_mode: str = ""
    body_visible: bool = False
    visible: bool = True
    is_current: bool = False


class CampaignTab:
    _PROJECT_VIEW_CACHE_SCHEMA_VERSION = 2
    STEP1_CHAR_MIN_IMAGES = int(getattr(CONFIG, "CAMPAIGN_MIN_CHAR_IMAGES", 10) or 10)
    STEP2_PLATE_MIN_PLATES = int(getattr(CONFIG, "CAMPAIGN_MIN_PLATE_ANNOTATIONS", 10) or 10)
    STEP3_CHAR_MIN_PLATES = int(getattr(CONFIG, "CAMPAIGN_MIN_CHAR_PLATES", 10) or 10)

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        self.frame = ttk.Frame(parent)
        self._startup_ui_ready = False

        # UI state
        self.right_panel = None
        self.right_panel_canvas = None
        self.right_content = None
        self.right_content_window = None
        self._model_status_title_labels = []
        self._model_status_meta_labels = []
        self.project_listbox = None
        self.project_list_scrollbar = None
        self.project_list_host = None
        self.project_list_status_lbl = None
        self.project_list_status_labels = []
        self._project_name_by_index = []
        self._project_list_refreshing = False
        self.project_start_mode_var = tk.StringVar(master=self.frame, value="")
        self.ingest_master_pool_var = tk.StringVar(master=self.frame, value="")
        self.ingest_status_labels = []
        self.ingest_status_shell = None
        self.ingest_status_summary_lbl = None
        self.ingest_status_table = None
        self.ingest_status_meta_lbl = None
        self.ingest_status_table_value_labels = []
        self.ingest_plan_listbox = None
        self.ingest_plan_host = None
        self.ingest_plan_items = []
        self.current_ingest_plan = {}
        self.ingest_panel_frame = None
        self.step1_panel_expanded = False
        self.step1_ingest_host_item = None
        self.last_ingest_snapshot = {}
        self._existing_iteration_ingest_plan_signature = None
        self.ingest_start_shell = None
        self.ingest_start_panel = None
        self.ingest_start_title_lbl = None
        self.ingest_start_summary_lbl = None
        self.ingest_start_detected_lbl = None
        self.ingest_start_next_lbl = None
        self.ingest_start_assets_table_shell = None
        self.ingest_start_assets_table = None
        self.ingest_start_assets_title_lbl = None
        self.ingest_start_asset_row_widgets = {}
        self.project_start_asset_scope_vars = {}
        self.btn_ingest_asset_more = {}
        self.btn_ingest_clear_asset = {}
        self.btn_ingest_start_fresh = None
        self.btn_ingest_start_assets = None
        self.btn_ingest_import_plate_run = None
        self.btn_ingest_pick_plate_model = None
        self.btn_ingest_pick_char_model = None
        self.ingest_list_title_lbl = None
        self.ingest_logic_lbl = None
        self.ingest_selection_lbl = None
        self.ingest_balance_canvas = None
        self.ingest_balance_summary_lbl = None
        self.ingest_insights_shell = None
        self.ingest_insights_toggle_shell = None
        self.ingest_insights_toggle_btn = None
        self.ingest_insights_hint_lbl = None
        self.ingest_insights_expanded = False
        self.ingest_chart_panel = None
        self.ingest_info_panel = None
        self.campaign_banner_shell = None
        self.banner_progress_row = None
        self.wizard_header_shell = None
        self.wizard_header_title_lbl = None
        self.wizard_header_summary_lbl = None
        self.wizard_header_metro_canvas = None
        self.wizard_exit_button_canvas = None
        self._wizard_header_metro_photo = None
        self.project_add_button_canvas = None
        self.project_browser_footer = None
        self.project_status_top_row = None
        self._icon_button_images = {}
        self._pil_font_cache = {}
        self._icon_button_state = {
            "project_add": {"hover": False, "pressed": False, "enabled": True},
            "exit_project": {"hover": False, "pressed": False, "enabled": False},
        }
        self._scroll_inertia_jobs = {}
        self._iteration_target_change_after_id = None
        self._dashboard_perf_cache = {
            "image_counts": {},
            "json_payloads": {},
            "model_created": {},
            "approved_stats": {},
            "step2_source_states": {},
            "step2_view_models": {},
        }
        self._wizard_header_metro_statuses = []
        self._wizard_step2_target_var = tk.StringVar(master=self.frame, value="")
        self.wizard_empty_state_card = None
        self.wizard_stage_cards = {}
        self.wizard_stage_cards_host = None
        self.project_loading_overlay = None
        self.project_loading_card = None
        self.project_loading_title_lbl = None
        self.project_loading_body_lbl = None
        self.project_loading_progress = None
        self._project_loading_overlay_visible = False
        self._project_open_refresh_after_id = None
        self._project_open_context_after_id = None
        self._project_open_post_refresh_after_id = None
        self._wizard_stage_badge_stabilize_after_id = None
        self._project_switch_in_progress = False
        self._wizard_focus_stage_request = ""
        self._wizard_focus_after_id = None
        self._wizard_assistant_stage_key = ""
        self._iteration_advance_thread = None
        self._iteration_advance_result = None
        self._iteration_advance_mode = ""
        self._iteration_advance_poll_after_id = None

        self._build_ui()
        self._refresh_dashboard()
        self.frame.after_idle(self._mark_startup_ui_ready)

    def _mark_startup_ui_ready(self):
        self._startup_ui_ready = True

    def _get_project_list_selection_bg(self) -> str:
        try:
            return self.app.get_list_selection_colors()[0]
        except Exception:
            return "#f8fafc"

    def _get_project_list_selection_fg(self) -> str:
        try:
            return self.app.get_list_selection_colors()[1]
        except Exception:
            return "#111827"

    def _get_campaign_green_accent(self) -> str:
        palette = getattr(self.app, "palette", {})
        success = palette.get("success", "#27ae60")
        panel = palette.get("panel", "#252526")
        try:
            return blend_hex_colors(success, panel, 0.10)
        except Exception:
            return "#2b8f57"

    def is_startup_ui_ready(self) -> bool:
        return bool(getattr(self, "_startup_ui_ready", False))

    def get_free_mode_assistant_context(self) -> dict:
        active_project = str(CAMPAIGN.get_active_project_name() or "").strip()
        if not active_project:
            return {
                "location": "[Z1] Wizard",
                "goal": "Wybierz istniejący projekt albo utwórz nowy. Dopiero aktywny projekt pokazuje karty etapów E1-E4.",
                "workflow": (
                    "Otwórz projekt z listy albo rozpocznij nowy projekt.",
                    "Po otwarciu projektu AS będzie opisywał aktualną kartę wizarda.",
                ),
                "glossary": (
                    "Z1 = wizard kampanii",
                    "kampania = projekt prowadzony etapami",
                    "wizard = prowadzenie po etapach projektu",
                ),
                "caution": "AS jest pasywną podpowiedzią. Nie wykonuje akcji i nie zmienia stanu projektu.",
            }

        status = self._get_wizard_assistant_stage_status()
        if status is not None:
            return self._build_wizard_stage_assistant_context(status)

        return {
            "location": "[Z1] Wizard",
            "goal": "Karty wizarda pokazują aktualny etap projektu i akcje, które prowadzą do Z2, Z3 albo Z4.",
            "workflow": (
                "Najpierw sprawdź kartę oznaczoną jako aktywną albo wymagającą uwagi.",
                "Jeśli karta ma przycisk akcji, przejdź nim do właściwej zakładki roboczej.",
                "Jeśli karta ma badge zatwierdzający, użyj go dopiero po spełnieniu warunków etapu.",
            ),
            "glossary": (
                "Z1 = wizard kampanii",
                "przycisk akcji = przejście do właściwej zakładki roboczej",
                    "badge = wyróżniony przycisk statusowy przy karcie etapu",
            ),
            "caution": "Jeśli AS nie opisuje tej karty, najedź kursorem na kartę wizarda i otwórz AS ponownie.",
        }

    def _ensure_wizard_stage_ui_ready(self) -> None:
        if not getattr(self, "wizard_stage_cards_host", None) or not getattr(self, "wizard_stage_cards", None):
            self._rebuild_wizard_stage_ui()

    def _clear_dashboard_perf_cache(self) -> None:
        cache = getattr(self, "_dashboard_perf_cache", None)
        if not isinstance(cache, dict):
            self._dashboard_perf_cache = {
                "image_counts": {},
                "json_payloads": {},
                "model_created": {},
                "approved_stats": {},
                "step2_source_states": {},
                "step2_view_models": {},
            }
            return
        for key in (
            "image_counts",
            "json_payloads",
            "model_created",
            "approved_stats",
            "step2_source_states",
            "step2_view_models",
            "image_name_sets",
        ):
            value = cache.get(key)
            if isinstance(value, dict):
                value.clear()
            else:
                cache[key] = {}

    @staticmethod
    def _build_cache_token_for_path(path: Path | None):
        if path is None:
            return ("missing", "")
        try:
            candidate = Path(path)
        except Exception:
            return ("invalid", str(path))
        if not candidate.exists():
            return ("missing", str(candidate))
        try:
            stat = candidate.stat()
            resolved = str(candidate.resolve())
            return (resolved, int(stat.st_mtime_ns), int(stat.st_size))
        except Exception:
            return ("exists", str(candidate))

    def _get_dashboard_cache_bucket(self, key: str) -> dict:
        cache = getattr(self, "_dashboard_perf_cache", None)
        if not isinstance(cache, dict):
            self._clear_dashboard_perf_cache()
            cache = getattr(self, "_dashboard_perf_cache", {})

        bucket = cache.get(key)
        if isinstance(bucket, dict):
            return bucket

        bucket = {}
        cache[key] = bucket
        return bucket

    def _get_project_view_cache_path(self) -> Path | None:
        try:
            state_dir = CAMPAIGN.get_project_state_dir()
        except Exception:
            state_dir = None
        if state_dir is None:
            return None
        try:
            return Path(state_dir) / "wizard_view_cache.json"
        except Exception:
            return None

    @classmethod
    def _normalize_project_view_cache_value(cls, value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {
                str(key): cls._normalize_project_view_cache_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [cls._normalize_project_view_cache_value(item) for item in value]
        if isinstance(value, set):
            return sorted(cls._normalize_project_view_cache_value(item) for item in value)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @classmethod
    def _serialize_project_view_cache_signature(cls, payload: dict) -> str:
        try:
            normalized = cls._normalize_project_view_cache_value(payload)
            return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            return ""

    def _build_directory_children_signature(self, path_value: Path | None, *, dirs_only: bool = False) -> list:
        if path_value is None:
            return ["missing", ""]
        try:
            root = Path(path_value)
        except Exception:
            return ["invalid", str(path_value)]
        try:
            if not root.exists() or not root.is_dir():
                return ["missing", str(root)]
        except Exception:
            return ["missing", str(root)]

        items: list[list] = []
        try:
            children = sorted(root.iterdir(), key=lambda item: str(item.name).lower())
        except Exception:
            return ["error", str(root)]

        for child in children:
            try:
                is_dir = bool(child.is_dir())
                if dirs_only and not is_dir:
                    continue
                stat = child.stat()
                items.append(
                    [
                        "d" if is_dir else "f",
                        str(child.name),
                        int(getattr(stat, "st_mtime_ns", 0) or 0),
                        int(getattr(stat, "st_size", 0) or 0),
                    ]
                )
            except Exception:
                continue

        return [str(root), items]

    def _load_project_view_cache_store(self) -> dict:
        default_store = {
            "version": int(self._PROJECT_VIEW_CACHE_SCHEMA_VERSION),
            "entries": {},
        }
        cache_path = self._get_project_view_cache_path()
        if cache_path is None:
            return dict(default_store)

        loaded = PROJECT_CACHE.load_json(cache_path, default=default_store)
        if not isinstance(loaded, dict):
            return dict(default_store)
        if int(loaded.get("version", 0) or 0) != int(self._PROJECT_VIEW_CACHE_SCHEMA_VERSION):
            return dict(default_store)
        entries = loaded.get("entries", {})
        if not isinstance(entries, dict):
            loaded["entries"] = {}
        return loaded

    def _save_project_view_cache_store(self, store: dict) -> None:
        if not isinstance(store, dict):
            return
        cache_path = self._get_project_view_cache_path()
        if cache_path is None:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    self._normalize_project_view_cache_value(store),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            PROJECT_CACHE.invalidate_json(cache_path)
        except Exception as e:
            logger.debug(f"Nie udało się zapisać cache widoków projektu: {e}")

    def _get_project_view_cache_entry(self, scope: str, signature: str) -> dict | None:
        if not scope or not signature:
            return None
        store = self._load_project_view_cache_store()
        entries = store.get("entries", {})
        if not isinstance(entries, dict):
            return None
        cached = entries.get(str(scope), {})
        if not isinstance(cached, dict):
            return None
        if str(cached.get("signature", "") or "") != str(signature or ""):
            return None
        payload = cached.get("payload")
        if not isinstance(payload, dict):
            return None
        return dict(payload)

    def _set_project_view_cache_entry(self, scope: str, signature: str, payload: dict) -> None:
        if not scope or not signature or not isinstance(payload, dict):
            return
        store = self._load_project_view_cache_store()
        entries = store.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            store["entries"] = entries
        entries[str(scope)] = {
            "signature": str(signature or ""),
            "payload": self._normalize_project_view_cache_value(payload),
        }
        self._save_project_view_cache_store(store)

    def _build_step1_manifest_context_signature(self, manifest: dict | None, iter_num: int) -> str:
        manifest = manifest if isinstance(manifest, dict) else {}
        try:
            manifest_path = CAMPAIGN.get_ingest_manifest_path(iter_num)
        except Exception:
            manifest_path = None
        try:
            approved_set_path = CAMPAIGN.get_plate_approved_set_path()
        except Exception:
            approved_set_path = None
        try:
            raw_root = CAMPAIGN.get_dir("raw")
        except Exception:
            raw_root = None
        try:
            target_iter_dir = CAMPAIGN.get_iteration_raw_dir(iter_num)
        except Exception:
            target_iter_dir = None
        try:
            master_pool_dir = CAMPAIGN.get_master_pool_dir()
        except Exception:
            master_pool_dir = None

        signature_payload = {
            "scope": "step1_manifest_context",
            "iteration": int(iter_num or 0),
            "selection_mode": str(manifest.get("selection_mode", "") or "").strip().lower(),
            "selected_count": int(manifest.get("selected_count", 0) or 0),
            "manifest_token": list(self._build_cache_token_for_path(manifest_path)),
            "approved_set_token": list(self._build_cache_token_for_path(approved_set_path)),
            "raw_root_dirs_token": self._build_directory_children_signature(
                Path(raw_root) if raw_root is not None else None,
                dirs_only=True,
            ),
            "target_iteration_dir_token": list(
                self._build_cache_token_for_path(
                    Path(target_iter_dir) if target_iter_dir is not None else None
                )
            ),
            "target_iteration_children_token": self._build_directory_children_signature(
                Path(target_iter_dir) if target_iter_dir is not None else None,
                dirs_only=False,
            ),
            "master_pool_dir_token": list(
                self._build_cache_token_for_path(
                    Path(master_pool_dir) if master_pool_dir is not None else None
                )
            ),
            "master_pool_children_token": self._build_directory_children_signature(
                Path(master_pool_dir) if master_pool_dir is not None else None,
                dirs_only=False,
            ),
        }
        return self._serialize_project_view_cache_signature(signature_payload)

    def _build_step2_source_state_signature(self, target: str) -> str:
        normalized_target = self._normalize_iteration_target(target)
        if normalized_target not in {"plate", "char"}:
            return ""

        try:
            current_step = int(CAMPAIGN.get_current_step() or 0)
            current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
            step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
            step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower()
            plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
            ingest_manifest_path = CAMPAIGN.get_ingest_manifest_path(current_iteration)
            approved_set_path = CAMPAIGN.get_plate_approved_set_path()
            artifact_registry_path = CAMPAIGN.get_artifact_registry_path()
            iter_image_source_dir = CAMPAIGN.get_iteration_image_source_dir(current_iteration)
            raw_iter_dir = CAMPAIGN.get_iteration_raw_dir(current_iteration)
            auto_ann_dir = CAMPAIGN.get_dir("auto_ann")
            step2_staging_run = CAMPAIGN.get_step2_staging_run()
            project_state_dir = CAMPAIGN.get_project_state_dir()
            project_start_mode = str(
                getattr(CAMPAIGN, "get_project_start_mode", lambda *_a, **_k: "fresh")() or "fresh"
            ).strip().lower()
            last_manual_source = dict(CAMPAIGN.get_last_plate_manual_source() or {})
        except Exception:
            return ""

        char_effective_state_path = None
        if project_state_dir is not None:
            try:
                char_effective_state_path = Path(project_state_dir) / "char_effective_source" / "source_state.json"
            except Exception:
                char_effective_state_path = None

        signature_payload = {
            "scope": "step2_source_state",
            "source_state_version": 2,
            "target": normalized_target,
            "iteration": int(current_iteration or 0),
            "current_step": int(current_step or 0),
            "step2_status": step2_status,
            "step3_status": step3_status,
            "project_start_mode": project_start_mode,
            "plate_model_token": list(
                self._build_cache_token_for_path(Path(plate_model_path) if plate_model_path else None)
            ),
            "ingest_manifest_token": list(self._build_cache_token_for_path(ingest_manifest_path)),
            "approved_set_token": list(self._build_cache_token_for_path(approved_set_path)),
            "artifact_registry_token": list(self._build_cache_token_for_path(artifact_registry_path)),
            "iter_image_source_dir_token": list(
                self._build_cache_token_for_path(Path(iter_image_source_dir) if iter_image_source_dir is not None else None)
            ),
            "raw_iter_dir_token": list(
                self._build_cache_token_for_path(Path(raw_iter_dir) if raw_iter_dir is not None else None)
            ),
            "auto_ann_dirs_token": self._build_directory_children_signature(
                Path(auto_ann_dir) if auto_ann_dir is not None else None,
                dirs_only=True,
            ),
            "step2_staging_run_token": list(
                self._build_cache_token_for_path(Path(step2_staging_run) if str(step2_staging_run or "").strip() else None)
            ),
            "char_effective_state_token": list(self._build_cache_token_for_path(char_effective_state_path)),
            "last_manual_source": {
                "source_run_path": str(last_manual_source.get("source_run_path") or "").strip(),
                "source_xml_path": str(last_manual_source.get("source_xml_path") or "").strip(),
                "source_input_path": str(last_manual_source.get("source_input_path") or "").strip(),
            },
        }
        return self._serialize_project_view_cache_signature(signature_payload)

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        try:
            return max(0.0, (perf_counter() - float(started_at)) * 1000.0)
        except Exception:
            return 0.0

    def _log_perf(self, label: str, started_at: float, *, threshold_ms: float = 40.0, extra: str = "") -> None:
        elapsed_ms = self._elapsed_ms(started_at)
        if elapsed_ms < float(threshold_ms):
            return

        extra_text = f" | {extra}" if str(extra or "").strip() else ""
        logger.debug(f"[CampaignTab][PERF] {label}: {elapsed_ms:.1f} ms{extra_text}")

    # ======================================================
    # UI BUILD
    # ======================================================

    def _build_ui(self):
        palette = getattr(self.app, "palette", {})

        # ---------------- HEADER ----------------
        header_bg = palette.get("panel", "#252526")
        header_f = tk.Frame(self.frame, bg=header_bg, bd=0, highlightthickness=0, padx=14, pady=10)
        header_f.pack(fill=tk.X)
        header_f.columnconfigure(0, weight=1)
        header_f.columnconfigure(1, weight=1)
        header_f.columnconfigure(2, weight=0)
        self.header_frame = header_f

        self.lbl_title = tk.Label(
            header_f,
            text="PANEL KAMPANII",
            font=("Segoe UI", 14, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=header_bg
        )
        self.lbl_title.grid(row=0, column=0, sticky="w")

        proj_frame = tk.Frame(header_f, bg=header_bg, bd=0, highlightthickness=0)
        proj_frame.grid(row=0, column=1, sticky="ew")
        self.proj_frame = proj_frame

        self.btn_open_proj = ttk.Button(proj_frame, text="Otwórz projekt", command=self._open_selected_project)

        self.btn_del_proj = ttk.Button(proj_frame, text="Usuń projekt", command=self._delete_project)

        self.btn_exit_project = ttk.Button(proj_frame, text="Wyjdź z projektu", command=self._exit_project_mode)

        # Pasek z metrem etapów widocznym także przy scrollu.
        banner_bg = palette.get("panel", "#252526")
        self.campaign_banner_shell = tk.Frame(
            self.frame,
            bg=banner_bg,
            bd=0,
            highlightthickness=0
        )
        self.campaign_banner_shell.pack(fill=tk.X, padx=15, pady=(0, 6))

        self.banner_progress_row = tk.Frame(
            self.campaign_banner_shell,
            bg=banner_bg,
            bd=0,
            highlightthickness=0
        )
        self.banner_progress_row.pack(fill=tk.X, padx=8, pady=(0, 4))

        metro_bg = palette.get("panel", "#252526")
        self.wizard_header_metro_canvas = tk.Canvas(
            self.banner_progress_row,
            height=84,
            bd=0,
            highlightthickness=0,
            bg=metro_bg,
        )
        self.wizard_header_metro_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.wizard_header_metro_canvas.bind("<Configure>", self._draw_wizard_stage_metro, add="+")
        HELP.bind_help(self.wizard_header_metro_canvas, "camp_open_project")

        self.wizard_exit_button_canvas = tk.Canvas(
            self.banner_progress_row,
            width=184,
            height=34,
            bd=0,
            highlightthickness=0,
            bg=banner_bg,
            cursor="hand2",
        )
        self.wizard_exit_button_canvas.pack(side=tk.RIGHT, padx=(8, 0), pady=(14, 0), anchor="n")
        HELP.bind_help(self.wizard_exit_button_canvas, "camp_exit_project")
        self._bind_icon_button(self.wizard_exit_button_canvas, role="exit_project", command=self._exit_project_mode)
        self.frame.after_idle(lambda: self._draw_icon_button("exit_project"))
        self._refresh_wizard_stage_metro()

        ttk.Separator(self.frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15)

        # ---------------- MAIN 2-COLUMN GRID ----------------
        main_container = ttk.Frame(self.frame, padding=15)
        main_container.pack(fill=tk.BOTH, expand=True)
        self.main_container = main_container

        self.project_loading_overlay = tk.Frame(
            main_container,
            bd=0,
            highlightthickness=0,
        )
        self.project_loading_card = tk.Frame(
            self.project_loading_overlay,
            bd=0,
            highlightthickness=1,
            padx=22,
            pady=20,
        )
        self.project_loading_card.place(relx=0.5, rely=0.18, anchor="n")
        self.project_loading_card.grid_columnconfigure(0, weight=1)
        self.project_loading_title_lbl = tk.Label(
            self.project_loading_card,
            text="Ładuję projekt",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI Semibold", 13),
            bd=0,
            highlightthickness=0,
        )
        self.project_loading_title_lbl.grid(row=0, column=0, sticky="ew")
        self.project_loading_body_lbl = tk.Label(
            self.project_loading_card,
            text="Odtwarzam stan etapów i kontekst roboczy projektu.",
            anchor="w",
            justify=tk.LEFT,
            wraplength=560,
            bd=0,
            highlightthickness=0,
        )
        self.project_loading_body_lbl.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.project_loading_progress = ttk.Progressbar(
            self.project_loading_card,
            mode="indeterminate",
        )
        self.project_loading_progress.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.project_loading_overlay.place_forget()

        # Stały układ dwukolumnowy.
        main_container.columnconfigure(0, weight=1, minsize=700)
        main_container.columnconfigure(1, weight=0, minsize=420)
        main_container.rowconfigure(0, weight=1)

        # RIGHT SIDEBAR: projekty i modele
        left_panel_host = ttk.Frame(main_container, width=420)
        left_panel_host.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        try:
            left_panel_host.grid_propagate(False)
            left_panel_host.columnconfigure(0, weight=1)
            left_panel_host.rowconfigure(0, weight=1)
        except Exception:
            pass
        self.left_panel_host = left_panel_host

        left_panel = ttk.LabelFrame(
            left_panel_host,
            text=" Projekt ",
            padding=15
        )
        left_panel.grid(row=0, column=0, sticky="nsew")
        self.left_panel = left_panel
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(0, weight=1)

        self.left_scroll_host = ttk.Frame(left_panel)
        self.left_scroll_host.grid(row=0, column=0, sticky="nsew")
        self.left_scroll_host.columnconfigure(0, weight=1)
        self.left_scroll_host.rowconfigure(0, weight=1)

        self.left_panel_canvas = tk.Canvas(
            self.left_scroll_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0
        )
        self.left_panel_canvas.grid(row=0, column=0, sticky="nsew")

        self.left_panel_scrollbar = WebSlimScrollbar(
            self.left_scroll_host,
            command=self.left_panel_canvas.yview
        )
        self.left_panel_scrollbar.grid(row=0, column=1, sticky="ns")
        try:
            green = self._get_campaign_green_accent()
            self.left_panel_scrollbar.configure_style(
                track_color=palette.get("panel", "#252526"),
                thumb_color=green,
                thumb_hover_color=blend_hex_colors(green, "#ffffff", 0.18),
            )
        except Exception:
            pass
        self.left_panel_canvas.configure(yscrollcommand=self.left_panel_scrollbar.set)

        self.left_content = ttk.Frame(self.left_panel_canvas)
        self.left_content_window = self.left_panel_canvas.create_window(
            (0, 0),
            window=self.left_content,
            anchor="nw"
        )
        self.left_content.bind("<Configure>", self._sync_left_panel_scrollregion, add="+")
        self.left_panel_canvas.bind("<Configure>", self._sync_left_panel_canvas_width, add="+")

        self.left_footer = ttk.Frame(left_panel)
        self.left_footer.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.left_panel_hint_lbl = tk.Label(
            self.left_content,
            text="",
            justify=tk.LEFT,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526")
        )
        self.left_panel_hint_lbl.pack(anchor=tk.W, pady=(0, 0))
        self._build_projects_browser(self.left_content)

        self._build_model_status(self.left_content, "Model Pojazdów (Detect):", "vehicle", Path(CONFIG.DIR_6_MODELS))
        self._build_model_status(self.left_content, "Model Tablic (Pose):", "plate", Path(CONFIG.DIR_6_MODELS))
        self._build_model_status(self.left_content, "Model Znaków (OCR/YOLO):", "char", Path(CONFIG.DIR_6_MODELS))

        self.btn_advance = ttk.Button(
            self.left_footer,
            text="Awansuj do Nowej Iteracji",
            command=self._advance_iteration,
            style="Accent.TButton"
        )

        self.btn_complete_project = ttk.Button(
            self.left_footer,
            text="Zakończ projekt",
            command=self._toggle_project_completion
        )
        self.btn_complete_project.pack(fill=tk.X, pady=(8, 0))

        HELP.bind_help(self.btn_open_proj, "camp_open_project")
        HELP.bind_help(self.btn_del_proj, "camp_delete_project")
        HELP.bind_help(self.btn_exit_project, "camp_exit_project")
        HELP.bind_help(left_panel, "camp_models")
        HELP.bind_help(self.btn_advance, "camp_advance")
        HELP.bind_help(self.btn_complete_project, "camp_advance")

        # LEFT MAIN PANEL: workflow
        self.right_panel = ttk.LabelFrame(
            main_container,
            text=" Etapy ",
            padding=15
        )
        self.right_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.right_panel.columnconfigure(0, weight=1)
        self.right_panel.rowconfigure(0, weight=1)

        self.right_scroll_host = ttk.Frame(self.right_panel)
        self.right_scroll_host.grid(row=0, column=0, sticky="nsew")
        self.right_scroll_host.columnconfigure(0, weight=1)
        self.right_scroll_host.rowconfigure(0, weight=1)

        self.right_panel_canvas = tk.Canvas(
            self.right_scroll_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0
        )
        self.right_panel_canvas.grid(row=0, column=0, sticky="nsew")

        self.right_panel_scrollbar = WebSlimScrollbar(
            self.right_scroll_host,
            command=self.right_panel_canvas.yview
        )
        self.right_panel_scrollbar.grid(row=0, column=1, sticky="ns")
        try:
            green = self._get_campaign_green_accent()
            self.right_panel_scrollbar.configure_style(
                track_color=palette.get("panel", "#252526"),
                thumb_color=green,
                thumb_hover_color=blend_hex_colors(green, "#ffffff", 0.18),
            )
        except Exception:
            pass
        self.right_panel_canvas.configure(yscrollcommand=self.right_panel_scrollbar.set)

        self.right_content = ttk.Frame(self.right_panel_canvas)
        self.right_content_window = self.right_panel_canvas.create_window(
            (0, 0),
            window=self.right_content,
            anchor="nw"
        )
        self.right_content.bind("<Configure>", self._sync_right_panel_scrollregion, add="+")
        self.right_panel_canvas.bind("<Configure>", self._sync_right_panel_canvas_width, add="+")

        self._rebuild_wizard_stage_ui()
        self.frame.after_idle(self._sync_left_panel_scrollregion)
        self.frame.after_idle(self._sync_left_panel_canvas_width)
        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self.frame.after_idle(self._sync_right_panel_canvas_width)
        self.frame.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_global_mousewheel, add="+")

    def _sync_left_panel_scrollregion(self, event=None):
        if not hasattr(self, "left_panel_canvas") or self.left_panel_canvas is None:
            return

        try:
            self.left_panel_canvas.configure(scrollregion=self.left_panel_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_left_panel_canvas_width(self, event=None):
        if not hasattr(self, "left_panel_canvas") or self.left_panel_canvas is None:
            return

        try:
            width = max(50, int(self.left_panel_canvas.winfo_width()))
            self.left_panel_canvas.itemconfigure(self.left_content_window, width=width)
        except Exception:
            pass

    def _sync_right_panel_scrollregion(self, event=None):
        if not hasattr(self, "right_panel_canvas") or self.right_panel_canvas is None:
            return

        try:
            self.right_panel_canvas.configure(scrollregion=self.right_panel_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_right_panel_canvas_width(self, event=None):
        if not hasattr(self, "right_panel_canvas") or self.right_panel_canvas is None:
            return

        try:
            width = max(50, int(self.right_panel_canvas.winfo_width()))
            self.right_panel_canvas.itemconfigure(self.right_content_window, width=width)
        except Exception:
            pass

    @staticmethod
    def _wizard_stage_key_from_step_num(step_num: int | None) -> str:
        try:
            normalized = int(step_num or 1)
        except Exception:
            normalized = 1
        normalized = min(max(normalized, 1), 4)
        return f"step{normalized}"

    def request_wizard_stage_focus(self, step_num: int | None = None, *, stage_key: str | None = None) -> None:
        key = str(stage_key or "").strip().lower()
        if not key:
            key = self._wizard_stage_key_from_step_num(step_num)
        if key not in {"step1", "step2", "step3", "step4"}:
            return
        self._wizard_focus_stage_request = key

    def _set_wizard_assistant_stage_context(self, stage_key: str) -> None:
        key = str(stage_key or "").strip().lower()
        if key not in {"step1", "step2", "step3", "step4"}:
            return
        if str(getattr(self, "_wizard_assistant_stage_key", "") or "").strip().lower() == key:
            return
        self._wizard_assistant_stage_key = key
        try:
            notify = getattr(self.app, "notify_free_mode_assistant_context_changed", None)
            if callable(notify):
                notify()
        except Exception:
            pass

    def _get_wizard_assistant_stage_status(self) -> WizardStageStatus | None:
        statuses: list[WizardStageStatus] = []
        for status in list(getattr(self, "_wizard_header_metro_statuses", []) or []):
            if isinstance(status, WizardStageStatus) and bool(getattr(status, "visible", True)):
                statuses.append(status)

        if not statuses:
            for card in dict(getattr(self, "wizard_stage_cards", {}) or {}).values():
                if not isinstance(card, dict):
                    continue
                status = card.get("status")
                if isinstance(status, WizardStageStatus) and bool(getattr(status, "visible", True)):
                    statuses.append(status)

        if not statuses:
            return None

        requested_key = str(getattr(self, "_wizard_assistant_stage_key", "") or "").strip().lower()
        if requested_key:
            for status in statuses:
                if str(getattr(status, "key", "") or "").strip().lower() == requested_key:
                    return status

        for status in statuses:
            if bool(getattr(status, "is_current", False)):
                return status

        for wanted_state in ("needs_attention", "ready", "in_progress"):
            for status in statuses:
                if str(getattr(status, "state", "") or "").strip().lower() == wanted_state:
                    return status

        return statuses[0]

    @staticmethod
    def _wizard_state_assistant_label(state: str) -> str:
        state_key = str(state or "").strip().lower()
        labels = {
            "locked": "zablokowana",
            "in_progress": "w toku",
            "needs_attention": "wymaga uwagi",
            "ready": "gotowa do decyzji",
            "done": "zakończona",
            "skipped": "pominięta",
        }
        return labels.get(state_key, state_key or "nieznany")

    @staticmethod
    def _is_step3_z2_repair_status(status: WizardStageStatus) -> bool:
        if str(getattr(status, "key", "") or "").strip().lower() != "step3":
            return False
        haystack = " ".join(
            str(value or "")
            for value in (
                getattr(status, "title", ""),
                getattr(status, "summary", ""),
                getattr(status, "details", ""),
                getattr(status, "primary_label", ""),
                getattr(status, "secondary_label", ""),
            )
        ).casefold()
        return bool("z2" in haystack and ("więcej tablic" in haystack or "popraw tablice" in haystack or "przygotuj więcej tablic" in haystack))

    def _build_wizard_stage_assistant_context(self, status: WizardStageStatus) -> dict:
        key = str(getattr(status, "key", "") or "").strip().lower()
        title = str(getattr(status, "title", "") or "").strip() or "Karta wizarda"
        state_label = self._wizard_state_assistant_label(getattr(status, "state", ""))
        summary = str(getattr(status, "summary", "") or "").strip()
        details = str(getattr(status, "details", "") or "").strip()
        primary = str(getattr(status, "primary_label", "") or "").strip()
        secondary = str(getattr(status, "secondary_label", "") or "").strip()
        badge = str(getattr(status, "badge_action_label", "") or "").strip()

        if self._is_step3_z2_repair_status(status):
            return {
                "location": f"[Z1] Wizard / {title}",
                "goal": (
                    "Jeśli już dysponujesz wystarczająco dobrym modelem tablic (na poziomie map50-90>0.8) "
                    "możesz go wykorzystać do automatycznej anotacji tablic. Jeśli zechcesz, możesz też dokonać "
                    "anotacji manualnej, która jest wymagająca czasowo, ale daje lepszą dokładność. Po utworzeniu/korekcie "
                    "anotacji (ramki) tablicy widocznej na zdjęciu, pamiętaj o jego zatwierdzeniu, czyli nadaniu statusu [OK]. "
                    "Możesz tego dokonać na liście wyników, używając do tego celu prawego przycisku myszy (PPM) na wybranej pozycji. "
                    "Choć jest to możliwe, lepszym sposobem jest po prostu tworzenie ramek w trybie pełnoekranowym "
                    "(aktywowanym/deaktywowanym klawiszem ENTER) i po utworzeniu odpowiedniej ich liczby zaznaczyć całą grupę "
                    "zmodyfikowanych zdjęć na liście i grupowym zatwierdzeniu (do wybrania zakresu pozycji na liście używamy "
                    "standardowego shift i lewego przycisku myszy LPM)."
                ),
                "workflow": (
                    "Jeśli chcesz dopisać albo poprawić tablice, użyj przycisku prowadzącego do Z2.",
                    "Po pracy w Z2 wróć do E3 i kontynuuj budowę albo korektę danych znaków.",
                ),
                "glossary": (
                    "map50-90 = orientacyjna jakość modelu; im bliżej 1.0, tym pewniejsza detekcja",
                    "status [OK] = zatwierdzenie zdjęcia/anotacji jako gotowej do dalszych etapów",
                    "PPM = prawy przycisk myszy",
                    "LPM = lewy przycisk myszy",
                    "tryb pełnoekranowy = powiększony canvas aktywowany klawiszem ENTER",
                    "ramka = obrys tablicy na zdjęciu",
                    "autoanotacja = model PT tworzy wstępne ramki",
                    "anotacja manualna = ręczne tworzenie albo poprawianie ramek",
                ),
                "caution": f"Stan karty: {state_label}. Zatwierdzaj tylko zdjęcia, które mają poprawnie utworzone ramki tablic.",
            }

        if key == "step1":
            return {
                "location": f"[Z1] Wizard / {title}",
                "goal": summary or "W E1 wybierasz katalog zdjęć wejściowych i tor iteracji.",
                "workflow": (
                    "Wskaż albo przygotuj zdjęcia wejściowe dla iteracji.",
                    "Wybierz tor: tablice albo znaki.",
                    "Zatwierdź E1, żeby odblokować E2/Z2.",
                ),
                "glossary": (
                    "E1 = wejście i tor iteracji",
                    "tor = decyzja, czy iteracja służy tablicom czy znakom",
                    "katalog zdjęć wejściowych = zdjęcia wybrane do bieżącej iteracji",
                ),
                "caution": details or f"Stan karty: {state_label}.",
            }

        if key == "step2":
            return {
                "location": f"[Z1] Wizard / {title}",
                "goal": summary or "E2 prowadzi do Z2, gdzie powstają anotacje tablic.",
                "workflow": tuple(
                    item
                    for item in (
                        details,
                        f"Użyj przycisku „{primary}”, jeśli chcesz przejść do pracy w Z2." if primary else "",
                        f"Badge „{badge}” zamyka E2, gdy bramka jest spełniona." if badge else "",
                    )
                    if str(item or "").strip()
                ),
                "glossary": (
                    "E2 = etap tablic w Z2",
                    "Z2 = zakładka pracy nad tablicami",
                    "XML = plik współrzędnych ramek tablic",
                    "badge = wyróżniony przycisk zatwierdzający etap",
                ),
                "caution": f"Stan karty: {state_label}. E2 zawsze dotyczy tablic, nawet gdy wybrany tor iteracji prowadzi później do znaków.",
            }

        if key == "step3":
            return {
                "location": f"[Z1] Wizard / {title}",
                "goal": summary or "E3 prowadzi do Z3, gdzie pracujesz nad znakami wyciętymi z tablic.",
                "workflow": tuple(
                    item
                    for item in (
                        details,
                        f"Przycisk „{primary}” uruchamia główną akcję tej karty." if primary else "",
                        f"Przycisk „{secondary}” daje alternatywny powrót albo korektę." if secondary else "",
                        f"Badge „{badge}” formalnie zamyka E3." if badge else "",
                    )
                    if str(item or "").strip()
                ),
                "glossary": (
                    "E3 = etap znaków",
                    "Z3 = zakładka pracy nad znakami",
                    "gold pack = wybrane poprawne przykłady znaków",
                    "crop = wycięty fragment obrazu, np. sama tablica",
                ),
                "caution": f"Stan karty: {state_label}. Jeśli wracasz do Z2 po więcej tablic, potem przebuduj dane znaków w Z3.",
            }

        if key == "step4":
            return {
                "location": f"[Z1] Wizard / {title}",
                "goal": summary or "E4 prowadzi do Z4, gdzie przygotowujesz dataset i trening wybranego toru.",
                "workflow": tuple(
                    item
                    for item in (
                        details,
                        f"Użyj przycisku „{primary}”, aby przejść do Z4." if primary else "",
                        f"Badge „{badge}” kończy etap bezpośrednio z wizarda." if badge else "",
                    )
                    if str(item or "").strip()
                ),
                "glossary": (
                    "E4 = etap datasetu i treningu",
                    "Z4 = zakładka treningu",
                    "dataset = obrazy i etykiety przygotowane do uczenia modelu",
                    "split = podział datasetu na train, val i test",
                ),
                "caution": f"Stan karty: {state_label}. Zakończenie E4 powinno prowadzić przez modal decyzji o dalszej pracy.",
            }

        return {
            "location": f"[Z1] Wizard / {title}",
            "goal": summary or "Ta karta pokazuje stan jednego etapu projektu.",
            "workflow": tuple(item for item in (details, primary, secondary, badge) if str(item or "").strip()),
            "glossary": ("Z1 = wizard kampanii", "etap = część procesu projektu"),
            "caution": f"Stan karty: {state_label}.",
        }

    def _cancel_pending_wizard_stage_focus(self) -> None:
        pending = getattr(self, "_wizard_focus_after_id", None)
        if not pending:
            return
        try:
            self.frame.after_cancel(pending)
        except Exception:
            pass
        self._wizard_focus_after_id = None

    def _schedule_pending_wizard_stage_focus(self, *, attempts_left: int = 4) -> None:
        self._cancel_pending_wizard_stage_focus()
        if not str(getattr(self, "_wizard_focus_stage_request", "") or "").strip():
            return

        def _run():
            self._wizard_focus_after_id = None
            applied = self._apply_pending_wizard_stage_focus()
            if applied:
                self._wizard_focus_stage_request = ""
                return
            if attempts_left > 1:
                try:
                    self._wizard_focus_after_id = self.frame.after(
                        60,
                        lambda: self._schedule_pending_wizard_stage_focus(attempts_left=attempts_left - 1),
                    )
                except Exception:
                    self._wizard_focus_after_id = None

        try:
            self._wizard_focus_after_id = self.frame.after_idle(_run)
        except Exception:
            self._wizard_focus_after_id = None

    def _apply_pending_wizard_stage_focus(self) -> bool:
        stage_key = str(getattr(self, "_wizard_focus_stage_request", "") or "").strip().lower()
        if stage_key not in {"step1", "step2", "step3", "step4"}:
            return False

        canvas = getattr(self, "right_panel_canvas", None)
        card = dict(getattr(self, "wizard_stage_cards", {}) or {}).get(stage_key)
        shell = card.get("shell") if isinstance(card, dict) else None
        if canvas is None or shell is None:
            return False

        try:
            if not bool(canvas.winfo_ismapped()) or not bool(shell.winfo_ismapped()):
                return False
        except Exception:
            return False

        try:
            self.frame.update_idletasks()
            canvas.update_idletasks()
            shell.update_idletasks()
        except Exception:
            pass

        try:
            scroll_bbox = canvas.bbox("all")
        except Exception:
            scroll_bbox = None
        if not scroll_bbox:
            return False

        try:
            canvas_height = max(1, int(canvas.winfo_height() or 1))
            current_top = float(canvas.canvasy(0))
            widget_top = float(shell.winfo_rooty() - canvas.winfo_rooty()) + current_top
        except Exception:
            return False

        content_top = float(scroll_bbox[1])
        content_bottom = float(scroll_bbox[3])
        max_scroll = max(0.0, content_bottom - content_top - float(canvas_height))
        target_y = max(content_top, float(widget_top) - 10.0)
        if max_scroll <= 0.0:
            try:
                canvas.yview_moveto(0.0)
                return True
            except Exception:
                return False

        fraction = max(0.0, min(1.0, float(target_y - content_top) / float(max_scroll)))
        try:
            canvas.yview_moveto(fraction)
            return True
        except Exception:
            return False

    def _widget_contains_point(self, widget, x_root: int, y_root: int) -> bool:
        if widget is None:
            return False
        try:
            wx = int(widget.winfo_rootx())
            wy = int(widget.winfo_rooty())
            return wx <= x_root < (wx + int(widget.winfo_width())) and wy <= y_root < (wy + int(widget.winfo_height()))
        except Exception:
            return False

    def _mousewheel_units(self, event) -> int:
        event_num = getattr(event, "num", None)
        if event_num == 4:
            return -1
        if event_num == 5:
            return 1

        delta = int(getattr(event, "delta", 0) or 0)
        if delta == 0:
            return 0
        if abs(delta) >= 120:
            units = -int(delta / 120)
        else:
            units = -1 if delta > 0 else 1
        return units if units != 0 else (-1 if delta > 0 else 1)

    def _mousewheel_magnitude(self, event) -> float:
        event_num = getattr(event, "num", None)
        if event_num in {4, 5}:
            return 1.0
        try:
            delta = abs(int(getattr(event, "delta", 0) or 0))
        except Exception:
            delta = 0
        if delta <= 0:
            return 1.0
        return max(1.0, min(3.0, float(delta) / 120.0))

    def _compute_canvas_scroll_delta(self, canvas, units: int, *, magnitude: float = 1.0) -> float:
        if canvas is None or units == 0:
            return 0.0
        try:
            first, last = canvas.yview()
            span = max(0.02, float(last) - float(first))
            base_step = max(0.0035, min(0.018, span * 0.08))
            step = base_step * max(1.0, min(3.0, float(magnitude or 1.0)))
            return float(units) * step
        except Exception:
            return 0.0

    def _compute_listbox_scroll_delta(self, listbox, units: int, *, magnitude: float = 1.0) -> float:
        if listbox is None or units == 0:
            return 0.0
        try:
            first, last = listbox.yview()
            span = max(0.02, float(last) - float(first))
            base_step = max(0.008, min(0.035, span * 0.12))
            step = base_step * max(1.0, min(3.0, float(magnitude or 1.0)))
            return float(units) * step
        except Exception:
            return 0.0

    def _apply_canvas_scroll_delta(self, canvas, delta_fraction: float) -> bool:
        if canvas is None or abs(float(delta_fraction or 0.0)) < 1e-6:
            return False
        try:
            first, last = canvas.yview()
            first = float(first)
            last = float(last)
            span = max(0.02, last - first)
            target = max(0.0, min(max(0.0, 1.0 - span), first + float(delta_fraction)))
            if abs(target - first) < 1e-6:
                return False
            canvas.yview_moveto(target)
            return True
        except Exception:
            return False

    def _apply_listbox_scroll_delta(self, listbox, delta_fraction: float) -> bool:
        if listbox is None or abs(float(delta_fraction or 0.0)) < 1e-6:
            return False
        try:
            first, last = listbox.yview()
            first = float(first)
            last = float(last)
            span = max(0.02, last - first)
            target = max(0.0, min(max(0.0, 1.0 - span), first + float(delta_fraction)))
            if abs(target - first) < 1e-6:
                return False
            listbox.yview_moveto(target)
            return True
        except Exception:
            return False

    def _queue_scroll_inertia(self, widget, *, mode: str, delta_fraction: float) -> bool:
        if widget is None:
            return False
        delta_fraction = float(delta_fraction or 0.0)
        if abs(delta_fraction) < 1e-6:
            return False

        key = f"{mode}:{str(widget)}"
        state = self._scroll_inertia_jobs.get(key)
        if not isinstance(state, dict):
            state = {
                "widget": widget,
                "mode": str(mode or "").strip().lower(),
                "velocity": 0.0,
                "after_id": None,
            }
            self._scroll_inertia_jobs[key] = state

        velocity = float(state.get("velocity", 0.0) or 0.0) + delta_fraction
        state["velocity"] = max(-0.14, min(0.14, velocity))

        if state.get("after_id") is None:
            try:
                state["after_id"] = self.frame.after(14, lambda scroll_key=key: self._advance_scroll_inertia(scroll_key))
            except Exception:
                state["after_id"] = None
                return False
        return True

    def _advance_scroll_inertia(self, key: str):
        state = self._scroll_inertia_jobs.get(str(key or "").strip())
        if not isinstance(state, dict):
            return

        state["after_id"] = None
        widget = state.get("widget")
        mode = str(state.get("mode", "") or "").strip().lower()
        velocity = float(state.get("velocity", 0.0) or 0.0)
        if abs(velocity) < 0.0007:
            self._scroll_inertia_jobs.pop(key, None)
            return

        if mode == "canvas":
            moved = self._apply_canvas_scroll_delta(widget, velocity)
        else:
            moved = self._apply_listbox_scroll_delta(widget, velocity)

        if not moved:
            self._scroll_inertia_jobs.pop(key, None)
            return

        state["velocity"] = velocity * 0.78
        if abs(float(state.get("velocity", 0.0) or 0.0)) < 0.0007:
            self._scroll_inertia_jobs.pop(key, None)
            return

        try:
            state["after_id"] = self.frame.after(14, lambda scroll_key=key: self._advance_scroll_inertia(scroll_key))
        except Exception:
            self._scroll_inertia_jobs.pop(key, None)

    def _canvas_can_scroll(self, canvas, units: int) -> bool:
        if canvas is None or units == 0:
            return False
        try:
            first, last = canvas.yview()
            if units < 0 and float(first) <= 0.0:
                return False
            if units > 0 and float(last) >= 1.0:
                return False
            return True
        except Exception:
            return False

    def _listbox_can_scroll(self, listbox, units: int) -> bool:
        if listbox is None or units == 0:
            return False
        try:
            first, last = listbox.yview()
            if units < 0 and float(first) <= 0.0:
                return False
            if units > 0 and float(last) >= 1.0:
                return False
            return True
        except Exception:
            return False

    def _on_listbox_mousewheel(self, event, listbox):
        try:
            if callable(getattr(self.app, "handle_help_panel_scroll_override", None)):
                result = self.app.handle_help_panel_scroll_override(event)
                if result == "break":
                    return "break"
        except Exception:
            pass

        units = self._mousewheel_units(event)
        magnitude = self._mousewheel_magnitude(event)
        if listbox is None or units == 0:
            return None
        host_canvas = None
        if listbox is self.project_listbox:
            host_canvas = self.left_panel_canvas
        elif listbox is self.ingest_plan_listbox:
            host_canvas = self.right_panel_canvas
        if host_canvas is not None and self._canvas_can_scroll(host_canvas, units):
            try:
                delta_fraction = self._compute_canvas_scroll_delta(host_canvas, units, magnitude=magnitude)
                self._queue_scroll_inertia(host_canvas, mode="canvas", delta_fraction=delta_fraction)
            except Exception:
                pass
            return "break"
        if not self._listbox_can_scroll(listbox, units):
            return None
        try:
            delta_fraction = self._compute_listbox_scroll_delta(listbox, units, magnitude=magnitude)
            self._queue_scroll_inertia(listbox, mode="listbox", delta_fraction=delta_fraction)
        except Exception:
            pass
        return "break"

    def _on_global_mousewheel(self, event):
        try:
            if callable(getattr(self.app, "handle_help_panel_scroll_override", None)):
                result = self.app.handle_help_panel_scroll_override(event)
                if result == "break":
                    return "break"
        except Exception:
            pass

        units = self._mousewheel_units(event)
        magnitude = self._mousewheel_magnitude(event)
        if units == 0:
            return None

        try:
            x_root = int(getattr(event, "x_root", 0) or self.frame.winfo_pointerx())
            y_root = int(getattr(event, "y_root", 0) or self.frame.winfo_pointery())
        except Exception:
            return None

        for listbox in (self.ingest_plan_listbox, self.project_listbox):
            if not self._widget_contains_point(listbox, x_root, y_root):
                continue
            try:
                host_canvas = None
                if listbox is self.project_listbox:
                    host_canvas = self.left_panel_canvas
                elif listbox is self.ingest_plan_listbox:
                    host_canvas = self.right_panel_canvas

                if host_canvas is not None and self._canvas_can_scroll(host_canvas, units):
                    delta_fraction = self._compute_canvas_scroll_delta(host_canvas, units, magnitude=magnitude)
                    self._queue_scroll_inertia(host_canvas, mode="canvas", delta_fraction=delta_fraction)
                    return "break"
                if self._listbox_can_scroll(listbox, units):
                    delta_fraction = self._compute_listbox_scroll_delta(listbox, units, magnitude=magnitude)
                    self._queue_scroll_inertia(listbox, mode="listbox", delta_fraction=delta_fraction)
                return "break"
            except Exception:
                return "break"

        for canvas in (self.right_panel_canvas, self.left_panel_canvas):
            if not self._widget_contains_point(canvas, x_root, y_root):
                continue
            if not self._canvas_can_scroll(canvas, units):
                continue
            try:
                delta_fraction = self._compute_canvas_scroll_delta(canvas, units, magnitude=magnitude)
                self._queue_scroll_inertia(canvas, mode="canvas", delta_fraction=delta_fraction)
                return "break"
            except Exception:
                return None
        return None

    def _bind_icon_button(self, canvas, *, role: str, command):
        if canvas is None:
            return

        canvas.bind("<Configure>", lambda _e, r=role: self._draw_icon_button(r), add="+")
        canvas.bind("<Enter>", lambda _e, r=role: self._set_icon_button_visual(r, hover=True), add="+")
        canvas.bind("<Leave>", lambda _e, r=role: self._set_icon_button_visual(r, hover=False, pressed=False), add="+")
        canvas.bind("<ButtonPress-1>", lambda _e, r=role: self._set_icon_button_visual(r, pressed=True), add="+")
        canvas.bind(
            "<ButtonRelease-1>",
            lambda e, r=role, cmd=command: self._on_icon_button_release(e, role=r, command=cmd),
            add="+",
        )
        self._draw_icon_button(role)

    def _set_icon_button_enabled(self, role: str, enabled: bool):
        state = self._icon_button_state.setdefault(role, {"hover": False, "pressed": False, "enabled": True})
        state["enabled"] = bool(enabled)
        if not enabled:
            state["hover"] = False
            state["pressed"] = False
        self._draw_icon_button(role)

    def _set_icon_button_visual(self, role: str, *, hover: bool | None = None, pressed: bool | None = None):
        state = self._icon_button_state.setdefault(role, {"hover": False, "pressed": False, "enabled": True})
        if not state.get("enabled", True):
            hover = False
            pressed = False
        if hover is not None:
            state["hover"] = bool(hover)
        if pressed is not None:
            state["pressed"] = bool(pressed)
        self._draw_icon_button(role)
        return "break"

    def _on_icon_button_release(self, event, *, role: str, command):
        state = self._icon_button_state.setdefault(role, {"hover": False, "pressed": False, "enabled": True})
        state["pressed"] = False
        self._draw_icon_button(role)
        if not state.get("enabled", True) or command is None:
            return "break"
        try:
            if self._widget_contains_point(event.widget, int(event.x_root), int(event.y_root)):
                command()
        except Exception:
            pass
        return "break"

    def _get_pil_font(self, size: int, *, bold: bool = False):
        cache_key = (int(size), bool(bold))
        cached = self._pil_font_cache.get(cache_key)
        if cached is not None:
            return cached

        font_names = (
            ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
            if bold
            else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
        )
        for font_name in font_names:
            try:
                font = ImageFont.truetype(font_name, int(size))
                self._pil_font_cache[cache_key] = font
                return font
            except Exception:
                continue

        font = ImageFont.load_default()
        self._pil_font_cache[cache_key] = font
        return font

    @staticmethod
    def _hex_to_rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
        value = str(color or "").strip().lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        if len(value) != 6:
            return (0, 0, 0, int(alpha))
        try:
            rgb = tuple(int(value[idx:idx + 2], 16) for idx in (0, 2, 4))
            return (rgb[0], rgb[1], rgb[2], int(alpha))
        except Exception:
            return (0, 0, 0, int(alpha))

    @classmethod
    def _pick_readable_text_color(cls, background: str, *, dark_text: str = "#111111", light_text: str = "#f3f3f3") -> str:
        red, green, blue, _alpha = cls._hex_to_rgba(background, 255)
        luminance = ((0.2126 * red) + (0.7152 * green) + (0.0722 * blue)) / 255.0
        return dark_text if luminance >= 0.62 else light_text

    @staticmethod
    def _format_tail_text(text: str, width: int = 42) -> str:
        value = str(text or "").replace("\\", "/").strip()
        if not value:
            return ""
        max_width = max(12, int(width or 42))
        if len(value) <= max_width:
            return value
        return "..." + value[-max(1, max_width - 3):]

    def _style_project_start_badge_button(self, widget, *, host_bg: str | None = None):
        if widget is None:
            return

        palette = getattr(self.app, "palette", {})
        try:
            enabled = bool(getattr(widget, "_project_start_badge_enabled", True))
        except Exception:
            enabled = True
        try:
            hover = bool(getattr(widget, "_project_start_badge_hover", False))
        except Exception:
            hover = False
        try:
            tone = str(getattr(widget, "_project_start_badge_tone", "info") or "info").strip().lower()
        except Exception:
            tone = "info"

        base_bg = str(host_bg or palette.get("panel", "#252526"))
        crt_tone = palette.get("success", "#27ae60")
        tone_color = {
            "primary": palette.get("accent", "#2980b9"),
            "info": palette.get("accent", "#2980b9"),
            "success": palette.get("success", "#27ae60"),
            "crt": crt_tone,
            "warning": palette.get("warning", "#d35400"),
            "danger": palette.get("error", "#c0392b"),
            "muted": palette.get("muted", "#c7c7c7"),
        }.get(tone, palette.get("accent", "#2980b9"))
        if tone == "crt":
            field_bg = palette.get("field", "#1a1a1a")
            if enabled:
                badge_bg = blend_hex_colors(
                    base_bg,
                    crt_tone,
                    0.24 if hover else 0.20,
                )
                badge_border = blend_hex_colors(crt_tone, base_bg, 0.18)
                badge_fg = palette.get("fg", "#f3f3f3")
            else:
                badge_bg = blend_hex_colors(base_bg, field_bg, 0.12)
                badge_border = blend_hex_colors(base_bg, field_bg, 0.26)
                badge_fg = palette.get("muted", "#c7c7c7")
        elif not enabled:
            tone_color = palette.get("muted_dim", "#777777")
            bg_mix = 0.30 if hover and enabled else 0.18
            badge_bg = blend_hex_colors(tone_color, base_bg, bg_mix)
            badge_border = blend_hex_colors(tone_color, base_bg, 0.08 if enabled else 0.42)
            badge_fg = self._pick_readable_text_color(badge_bg)
            if not enabled:
                badge_fg = palette.get("muted", "#999999")
        else:
            bg_mix = 0.30 if hover and enabled else 0.18
            badge_bg = blend_hex_colors(tone_color, base_bg, bg_mix)
            badge_border = blend_hex_colors(tone_color, base_bg, 0.08 if enabled else 0.42)
            badge_fg = self._pick_readable_text_color(badge_bg)

        try:
            widget.config(
                bg=badge_bg,
                fg=badge_fg,
                activebackground=badge_bg,
                activeforeground=badge_fg,
                highlightthickness=1,
                highlightbackground=badge_border,
                highlightcolor=badge_border,
                cursor=("hand2" if enabled else ""),
            )
        except Exception:
            pass

    def _create_project_start_badge_button(self, parent, *, text: str, command, tone: str = "info"):
        palette = getattr(self.app, "palette", {})
        widget = tk.Label(
            parent,
            text=str(text or "").strip(),
            font=("Segoe UI", 8),
            padx=7,
            pady=2,
            bd=0,
            relief=tk.FLAT,
            bg=palette.get("panel", "#252526"),
            fg=palette.get("fg", "#f3f3f3"),
            anchor="center",
            justify=tk.CENTER,
            takefocus=0,
        )
        widget._project_start_badge_command = command
        widget._project_start_badge_enabled = True
        widget._project_start_badge_tone = str(tone or "info").strip().lower() or "info"
        widget._project_start_badge_hover = False

        def _on_click(_event=None, target=widget):
            if not bool(getattr(target, "_project_start_badge_enabled", True)):
                return
            callback = getattr(target, "_project_start_badge_command", None)
            if callable(callback):
                callback()

        def _on_enter(_event=None, target=widget):
            target._project_start_badge_hover = True
            self._style_project_start_badge_button(target)

        def _on_leave(_event=None, target=widget):
            target._project_start_badge_hover = False
            self._style_project_start_badge_button(target)

        widget.bind("<Button-1>", _on_click, add="+")
        widget.bind("<Enter>", _on_enter, add="+")
        widget.bind("<Leave>", _on_leave, add="+")
        self._style_project_start_badge_button(widget)
        return widget

    def _set_project_start_badge_button_state(self, widget, *, enabled: bool | None = None, text: str | None = None, tone: str | None = None):
        if widget is None:
            return
        if enabled is not None:
            try:
                widget._project_start_badge_enabled = bool(enabled)
            except Exception:
                pass
        if text is not None:
            try:
                widget.config(text=str(text or "").strip())
            except Exception:
                pass
        if tone is not None:
            try:
                widget._project_start_badge_tone = str(tone or "info").strip().lower() or "info"
            except Exception:
                pass
        self._style_project_start_badge_button(widget)

    def _draw_icon_button(self, role: str):
        canvas = (
            self.project_add_button_canvas
            if role == "project_add"
            else self.wizard_exit_button_canvas
        )
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        bg = str(canvas.cget("bg") or palette.get("panel", "#252526"))
        state = self._icon_button_state.setdefault(role, {"hover": False, "pressed": False, "enabled": True})
        enabled = bool(state.get("enabled", True))
        hover = bool(state.get("hover", False))
        pressed = bool(state.get("pressed", False))
        width = max(int(canvas.winfo_width() or int(canvas.cget("width") or 34)), 24)
        height = max(int(canvas.winfo_height() or int(canvas.cget("height") or 34)), 24)

        canvas.delete("all")
        cursor = "hand2" if enabled else "arrow"
        try:
            canvas.config(cursor=cursor)
        except Exception:
            pass

        label_text = "Utwórz projekt" if role == "project_add" else "Wyjdź z projektu"

        if PIL_AVAILABLE and Image is not None and ImageTk is not None and ImageDraw is not None and ImageFont is not None:
            scale = 4
            hi_w = max(width * scale, 4)
            hi_h = max(height * scale, 4)
            image = Image.new("RGBA", (hi_w, hi_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image, "RGBA")

            if role == "project_add":
                neutral = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted_dim", "#8c8c8c")
                success = palette.get("success", "#27ae60") if enabled else palette.get("muted", "#c7c7c7")
                outline = blend_hex_colors(neutral, bg, 0.34 if enabled else 0.60)
                icon_color = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted", "#c7c7c7")
                label_color = success
            else:
                neutral = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted_dim", "#8c8c8c")
                outline = blend_hex_colors(neutral, bg, 0.34 if enabled else 0.60)
                icon_color = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted", "#c7c7c7")
                label_color = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted", "#c7c7c7")

            circle_d = min(hi_h - (6 * scale), 28 * scale)
            circle_left = 6 * scale
            circle_top = max(scale, (hi_h - circle_d) // 2)
            circle_box = [circle_left, circle_top, circle_left + circle_d, circle_top + circle_d]
            inner_box = [circle_box[0] + scale, circle_box[1] + scale, circle_box[2] - scale, circle_box[3] - scale]

            if role == "project_add":
                draw.ellipse(circle_box, fill=self._hex_to_rgba(bg, 0), outline=self._hex_to_rgba(outline), width=max(scale, 2))
            else:
                draw.ellipse(circle_box, fill=self._hex_to_rgba(bg, 0), outline=self._hex_to_rgba(outline), width=max(scale, 2))

            cx = (inner_box[0] + inner_box[2]) / 2.0
            cy = (inner_box[1] + inner_box[3]) / 2.0
            if role == "project_add":
                line_w = max(scale, 3)
                line_len = 6 * scale
                draw.line(
                    (cx - line_len, cy, cx + line_len, cy),
                    fill=self._hex_to_rgba(icon_color),
                    width=line_w,
                )
                draw.line(
                    (cx, cy - line_len, cx, cy + line_len),
                    fill=self._hex_to_rgba(icon_color),
                    width=line_w,
                )
            else:
                stop_half = 4.6 * scale
                draw.rectangle(
                    [cx - stop_half, cy - stop_half, cx + stop_half, cy + stop_half],
                    outline=self._hex_to_rgba(icon_color),
                    fill=self._hex_to_rgba(bg, 0),
                    width=max(scale, 2),
                )

            font = self._get_pil_font(13 * scale, bold=False)
            text_x = circle_box[2] + (8 * scale)
            try:
                text_box = draw.textbbox((0, 0), label_text, font=font)
                text_h = max(1, text_box[3] - text_box[1])
            except Exception:
                text_h = 10 * scale
            text_y = max(0, int((hi_h - text_h) / 2) - (scale // 2))
            draw.text((text_x, text_y), label_text, font=font, fill=self._hex_to_rgba(label_color))

            try:
                resampling = Image.Resampling.LANCZOS
            except Exception:
                resampling = Image.LANCZOS
            image = image.resize((width, height), resampling)
            photo = ImageTk.PhotoImage(image)
            self._icon_button_images[role] = photo
            canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            return

        if role == "project_add":
            neutral = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted_dim", "#8c8c8c")
            success = palette.get("success", "#27ae60") if enabled else palette.get("muted", "#c7c7c7")
            outline = blend_hex_colors(neutral, bg, 0.34 if enabled else 0.60)
            icon_color = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted", "#c7c7c7")
            label_color = success
        else:
            neutral = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted_dim", "#8c8c8c")
            outline = blend_hex_colors(neutral, bg, 0.34 if enabled else 0.60)
            icon_color = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted", "#c7c7c7")
            label_color = palette.get("fg", "#f3f3f3") if enabled else palette.get("muted", "#c7c7c7")

        circle_top = max(3, int((height - 28) / 2))
        circle_box = (4, circle_top, 32, circle_top + 28)
        if role == "project_add":
            canvas.create_oval(*circle_box, fill="", outline=outline, width=2)
        else:
            canvas.create_oval(*circle_box, fill="", outline=outline, width=2)

        cx = (circle_box[0] + circle_box[2]) / 2.0
        cy = (circle_box[1] + circle_box[3]) / 2.0
        if role == "project_add":
            canvas.create_line(cx - 6, cy, cx + 6, cy, fill=icon_color, width=2, capstyle=tk.ROUND)
            canvas.create_line(cx, cy - 6, cx, cy + 6, fill=icon_color, width=2, capstyle=tk.ROUND)
        else:
            canvas.create_rectangle(cx - 4.5, cy - 4.5, cx + 4.5, cy + 4.5, outline=icon_color, width=2)
        canvas.create_text(42, height / 2.0, text=label_text, anchor=tk.W, fill=label_color, font=("Segoe UI", 12, "normal"))

    def _build_projects_browser(self, parent):
        palette = getattr(self.app, "palette", {})

        browser_lf = ttk.LabelFrame(parent, text=" Zapisane projekty ", padding=10)
        browser_lf.pack(fill=tk.X, pady=(0, 12))
        self.project_browser_frame = browser_lf

        status_panel = tk.Frame(
            browser_lf,
            bg=palette.get("panel", "#252526")
        )
        status_panel.pack(fill=tk.X, pady=(0, 6))
        self.project_list_status_lbl = status_panel
        self.project_list_status_labels = []
        self.project_status_top_row = tk.Frame(
            status_panel,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
        )
        self.project_status_top_row.pack(fill=tk.X)

        status_fonts = [
            ("Segoe UI", 10, "bold"),
            ("Segoe UI", 9),
            ("Segoe UI", 9),
        ]

        first_lbl = tk.Label(
            self.project_status_top_row,
            text="",
            justify=tk.LEFT,
            anchor="w",
            height=1,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
            font=status_fonts[0]
        )
        first_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.project_list_status_labels.append(first_lbl)

        self.project_add_button_canvas = tk.Canvas(
            self.project_status_top_row,
            width=196,
            height=38,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", "#252526"),
            cursor="hand2",
        )
        self.project_add_button_canvas.pack(side=tk.RIGHT, padx=(8, 0))
        HELP.bind_help(self.project_add_button_canvas, "camp_new_project")
        self._bind_icon_button(self.project_add_button_canvas, role="project_add", command=self._add_new_project)
        self.frame.after_idle(lambda: self._draw_icon_button("project_add"))

        for font_spec in status_fonts[1:]:
            lbl = tk.Label(
                status_panel,
                text="",
                justify=tk.LEFT,
                anchor="w",
                height=1,
                fg=palette.get("muted", "#b8b8b8"),
                bg=palette.get("panel", "#252526"),
                font=font_spec
            )
            lbl.pack(fill=tk.X)
            self.project_list_status_labels.append(lbl)

        list_host = tk.Frame(
            browser_lf,
            bg=palette.get("field", "#1a1a1a"),
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
        )
        list_host.pack(fill=tk.X, expand=False)
        self.project_list_host = list_host

        scroll = WebSlimScrollbar(list_host, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.project_list_scrollbar = scroll
        try:
            green = self._get_campaign_green_accent()
            scroll.configure_style(
                track_color=palette.get("field", "#1a1a1a"),
                thumb_color=green,
                thumb_hover_color=blend_hex_colors(green, "#ffffff", 0.18),
            )
        except Exception:
            pass

        self.project_listbox = tk.Listbox(
            list_host,
            exportselection=False,
            selectmode=tk.EXTENDED,
            height=5,
            width=1,
            font=("Segoe UI", 10),
            bg=palette.get("field", "#1a1a1a"),
            fg=palette.get("fg", "#f3f3f3"),
            selectbackground=self._get_project_list_selection_bg(),
            selectforeground=self._get_project_list_selection_fg(),
            activestyle="none",
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("accent", "#2980b9"),
            takefocus=1,
            yscrollcommand=scroll.set
        )
        self.project_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.project_listbox.bind("<<ListboxSelect>>", self._on_project_changed)
        self.project_listbox.bind("<Double-Button-1>", lambda _e: self._open_selected_project())
        self.project_listbox.bind("<Button-1>", lambda _e: self.project_listbox.focus_set(), add="+")
        self.project_listbox.bind("<Button-3>", self._show_project_context_menu)
        self.project_listbox.bind("<MouseWheel>", lambda e: self._on_listbox_mousewheel(e, self.project_listbox))
        self.project_listbox.bind("<Button-4>", lambda e: self._on_listbox_mousewheel(e, self.project_listbox))
        self.project_listbox.bind("<Button-5>", lambda e: self._on_listbox_mousewheel(e, self.project_listbox))
        scroll.config(command=self.project_listbox.yview)

        self.project_context_menu = tk.Menu(self.frame, tearoff=0)
        self.project_context_menu.add_command(label="Otwórz projekt", command=self._open_selected_project)
        self.project_context_menu.add_separator()
        self.project_context_menu.add_command(label="Usuń zaznaczone projekty", command=self._delete_project)

        self.project_browser_footer = None

        HELP.bind_help(browser_lf, "camp_open_project")
        HELP.bind_help(status_panel, "camp_open_project")
        for lbl in self.project_list_status_labels:
            HELP.bind_help(lbl, "camp_open_project")
        HELP.bind_help(self.project_listbox, "camp_open_project")

    def _build_ingest_panel(self, parent):
        palette = getattr(self.app, "palette", {})
        subtle_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        ingest_lf = tk.Frame(
            parent,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border
        )
        ingest_lf.pack(fill=tk.X, pady=(4, 0))
        self.ingest_panel_frame = ingest_lf

        header_lbl = tk.Label(
            ingest_lf,
            text="Panel E1: Wejście i tor iteracji",
            font=("Segoe UI", 10, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        self.ingest_header_lbl = header_lbl

        intro_lbl = tk.Label(
            ingest_lf,
            text="",
            justify=tk.LEFT,
            wraplength=620,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        intro_lbl.pack(anchor=tk.W, padx=10, pady=(10, 6))
        self.ingest_intro_lbl = intro_lbl

        start_shell = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        start_shell.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.ingest_start_shell = start_shell

        start_panel = tk.Frame(start_shell, bg=palette.get("panel", "#252526"))
        start_panel.pack(fill=tk.X, padx=0, pady=0)
        self.ingest_start_panel = start_panel

        self.ingest_start_title_lbl = tk.Label(
            start_panel,
            text="Start 1. iteracji",
            font=("Segoe UI", 10, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w",
            justify=tk.LEFT,
        )
        self.ingest_start_title_lbl.pack(fill=tk.X)

        self.ingest_start_summary_lbl = tk.Label(
            start_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=620,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        self.ingest_start_summary_lbl.pack(fill=tk.X, pady=(4, 8))

        start_mode_row = tk.Frame(start_panel, bg=palette.get("panel", "#252526"))
        self.ingest_start_mode_row = start_mode_row

        route_shell = tk.Frame(
            start_panel,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        route_shell.pack(fill=tk.X, pady=(2, 10))
        self.ingest_route_shell = route_shell

        route_body = tk.Frame(route_shell, bg=palette.get("panel", "#252526"))
        route_body.pack(fill=tk.X, padx=10, pady=8)
        self.ingest_route_body = route_body

        start_assets_row = tk.Frame(start_panel, bg=palette.get("panel", "#252526"))
        start_assets_row.pack(fill=tk.X, pady=(10, 0))
        self.ingest_start_assets_row = start_assets_row

        self.ingest_start_assets_title_lbl = tk.Label(
            start_assets_row,
            text="Zasoby startowe iteracji",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w",
            justify=tk.LEFT,
        )
        self.ingest_start_assets_title_lbl.pack(fill=tk.X, pady=(0, 6))

        assets_table_shell = tk.Frame(
            start_assets_row,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        assets_table_shell.pack(fill=tk.X, expand=True)
        self.ingest_start_assets_table_shell = assets_table_shell

        assets_table = tk.Frame(
            assets_table_shell,
            bg=subtle_border,
            bd=0,
            highlightthickness=0,
        )
        assets_table.pack(fill=tk.X, expand=True, padx=0, pady=0)
        self.ingest_start_assets_table = assets_table
        assets_table.grid_columnconfigure(0, weight=0, minsize=96)
        assets_table.grid_columnconfigure(1, weight=0, minsize=150)
        assets_table.grid_columnconfigure(2, weight=0, minsize=168)
        assets_table.grid_columnconfigure(3, weight=1, minsize=126)
        assets_table.grid_columnconfigure(4, weight=0, minsize=156)
        assets_table.grid_columnconfigure(5, weight=0, minsize=72)

        table_base_bg = palette.get("panel", "#252526")
        table_field_bg = palette.get("field", "#1a1a1a")
        header_bg = blend_hex_colors(
            palette.get("success", "#27ae60"),
            table_base_bg,
            0.16,
        )
        header_fg = self._pick_readable_text_color(header_bg)
        try:
            ttk.Style().configure(
                "ProjectStartAsset.TButton",
                anchor="center",
                padding=(8, 2),
            )
        except Exception:
            pass
        self.ingest_start_assets_header_labels = []
        for column, title in enumerate(("Zasób", "Źródło", "Walidacja", "Źródło ścieżki danych", "Akcja", "Więcej")):
            header_lbl = tk.Label(
                assets_table,
                text=title,
                font=("Segoe UI", 8, "bold"),
                anchor=("w" if column < 3 else "center"),
                justify=tk.LEFT,
                fg=header_fg,
                bg=header_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=subtle_border,
                highlightcolor=subtle_border,
                wraplength=(138 if column == 3 else 0),
                padx=8,
                pady=3,
            )
            header_lbl.grid(row=0, column=column, sticky="ew", padx=(0, 1), pady=(0, 1))
            self.ingest_start_assets_header_labels.append(header_lbl)

        self.ingest_start_asset_row_widgets = {}
        self.project_start_asset_scope_vars = {}

        def _build_asset_row(row_index: int, key: str, label_text: str):
            row_bg = blend_hex_colors(table_base_bg, table_field_bg, 0.10 if (row_index % 2 == 1) else 0.18)
            source_var = tk.StringVar(master=self.frame, value="Nie wskazano")
            scope_var = tk.StringVar(master=self.frame, value=("na" if key == "images" else "project"))

            name_lbl = tk.Label(
                assets_table,
                text=label_text,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
                justify=tk.LEFT,
                fg=palette.get("fg", "#f3f3f3"),
                bg=row_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=subtle_border,
                highlightcolor=subtle_border,
                padx=8,
                pady=4,
            )
            name_lbl.grid(row=row_index, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))

            source_lbl = tk.Label(
                assets_table,
                textvariable=source_var,
                font=("Consolas", 8),
                anchor="w",
                justify=tk.LEFT,
                fg=palette.get("accent", "#4fc1ff"),
                bg=row_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=subtle_border,
                highlightcolor=subtle_border,
                padx=8,
                pady=3,
                height=1,
                width=24,
            )
            source_lbl.grid(row=row_index, column=1, sticky="nsew", padx=(0, 1), pady=(0, 1))
            source_lbl.bind(
                "<Button-3>",
                lambda event, rk=key: self._show_project_start_asset_source_context_menu(event, rk),
                add="+",
            )

            validation_lbl = tk.Label(
                assets_table,
                text="Brak",
                font=("Segoe UI", 8, "bold"),
                anchor="w",
                justify=tk.LEFT,
                fg=palette.get("muted", "#c7c7c7"),
                bg=row_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=subtle_border,
                highlightcolor=subtle_border,
                padx=8,
                pady=3,
                wraplength=220,
            )
            validation_lbl.grid(row=row_index, column=2, sticky="nsew", padx=(0, 1), pady=(0, 1))

            source_scope_host = tk.Frame(
                assets_table,
                bg=row_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=subtle_border,
                highlightcolor=subtle_border,
                padx=4,
                pady=1,
            )
            source_scope_host.grid(row=row_index, column=3, sticky="nsew", pady=(0, 1))
            source_scope_host.grid_propagate(False)
            source_scope_host.pack_propagate(False)

            action_host = tk.Frame(
                assets_table,
                bg=row_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=subtle_border,
                highlightcolor=subtle_border,
                padx=4,
                pady=1,
            )
            action_host.grid(row=row_index, column=4, sticky="nsew", pady=(0, 1))
            action_host.grid_propagate(False)
            action_host.pack_propagate(False)
            action_host.grid_columnconfigure(0, minsize=62, weight=0)
            action_host.grid_columnconfigure(1, minsize=74, weight=0)
            action_host.grid_rowconfigure(0, weight=1)

            action_primary_slot = tk.Frame(
                action_host,
                bg=row_bg,
                bd=0,
                highlightthickness=0,
                width=62,
                height=28,
            )
            action_primary_slot.grid(row=0, column=0, sticky="w", padx=(0, 4), pady=0)
            action_primary_slot.grid_propagate(False)
            action_primary_slot.pack_propagate(False)

            action_clear_slot = tk.Frame(
                action_host,
                bg=row_bg,
                bd=0,
                highlightthickness=0,
                width=74,
                height=28,
            )
            action_clear_slot.grid(row=0, column=1, sticky="w", padx=(0, 0), pady=0)
            action_clear_slot.grid_propagate(False)
            action_clear_slot.pack_propagate(False)

            details_host = tk.Frame(
                assets_table,
                bg=row_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=subtle_border,
                highlightcolor=subtle_border,
                padx=4,
                pady=1,
            )
            details_host.grid(row=row_index, column=5, sticky="nsew", pady=(0, 1))
            details_host.grid_propagate(False)
            details_host.pack_propagate(False)

            scope_widgets = []
            scope_badges = []
            if key == "images":
                scope_lbl = tk.Label(
                    source_scope_host,
                    text="—",
                    font=("Segoe UI", 9),
                    fg=palette.get("muted", "#c7c7c7"),
                    bg=row_bg,
                    anchor="center",
                    justify=tk.CENTER,
                )
                scope_lbl.pack(anchor=tk.CENTER)
                scope_widgets.append(scope_lbl)
            else:
                for idx, (scope_value, scope_label) in enumerate((("project", "Projekt"), ("freemode", "Freemode"))):
                    badge_shell = tk.Frame(
                        source_scope_host,
                        bg=row_bg,
                        bd=0,
                        padx=6,
                        pady=3,
                        relief=tk.FLAT,
                        highlightthickness=0,
                        cursor="hand2",
                    )
                    badge_shell.pack(side=tk.LEFT, padx=(0 if idx == 0 else 6, 0))

                    lamp = tk.Canvas(
                        badge_shell,
                        width=10,
                        height=10,
                        bg=row_bg,
                        bd=0,
                        highlightthickness=0,
                        cursor="hand2",
                    )
                    lamp.pack(side=tk.LEFT, padx=(0, 5))
                    lamp_id = lamp.create_oval(1, 1, 9, 9, outline="", fill=palette.get("muted_dim", "#4a4a4a"))

                    text_lbl = tk.Label(
                        badge_shell,
                        text=scope_label,
                        font=("Segoe UI", 8),
                        fg=palette.get("fg", "#f3f3f3"),
                        bg=row_bg,
                        anchor="w",
                        justify=tk.LEFT,
                        cursor="hand2",
                    )
                    text_lbl.pack(side=tk.LEFT)

                    for clickable in (badge_shell, lamp, text_lbl):
                        clickable.bind(
                            "<Button-1>",
                            lambda _event, rk=key, sv=scope_value: self._select_project_start_asset_scope(rk, sv),
                            add="+",
                        )

                    scope_badges.append(
                        {
                            "value": scope_value,
                            "shell": badge_shell,
                            "lamp": lamp,
                            "lamp_id": lamp_id,
                            "label": text_lbl,
                            "full_label": scope_label,
                            "compact_label": ("Proj." if scope_value == "project" else "Free"),
                        }
                    )
                    scope_widgets.extend([badge_shell, lamp, text_lbl])

            self.project_start_asset_scope_vars[key] = scope_var

            self.ingest_start_asset_row_widgets[key] = {
                "row_key": key,
                "source_var": source_var,
                "scope_var": scope_var,
                "name_lbl": name_lbl,
                "source_lbl": source_lbl,
                "source_full_path": "",
                "validation_lbl": validation_lbl,
                "source_scope_host": source_scope_host,
                "scope_widgets": scope_widgets,
                "scope_badges": scope_badges,
                "action_host": action_host,
                "action_primary_slot": action_primary_slot,
                "action_clear_slot": action_clear_slot,
                "details_host": details_host,
                "tone": "muted",
            }

        _build_asset_row(1, "images", "Obrazy iteracji")
        _build_asset_row(2, "plate_run", "Anotacje tablic")
        _build_asset_row(3, "plate_model", "Model tablic")
        _build_asset_row(4, "char_model", "Model znaków")

        self.btn_ingest_start_fresh = self._create_project_start_badge_button(
            self.ingest_start_asset_row_widgets["images"]["action_primary_slot"],
            text="Wybierz",
            command=self._choose_master_pool_dir,
            tone="crt",
        )
        self.btn_ingest_start_fresh.pack(anchor=tk.W, pady=2)

        self.btn_ingest_import_plate_run = self._create_project_start_badge_button(
            self.ingest_start_asset_row_widgets["plate_run"]["action_primary_slot"],
            text="Import",
            command=self._import_project_start_plate_run,
            tone="crt",
        )
        self.btn_ingest_import_plate_run.pack(anchor=tk.W, pady=2)

        self.btn_ingest_pick_plate_model = self._create_project_start_badge_button(
            self.ingest_start_asset_row_widgets["plate_model"]["action_primary_slot"],
            text="Wskaż",
            command=lambda: self._choose_project_start_model("plate"),
            tone="crt",
        )
        self.btn_ingest_pick_plate_model.pack(anchor=tk.W, pady=2)

        self.btn_ingest_pick_char_model = self._create_project_start_badge_button(
            self.ingest_start_asset_row_widgets["char_model"]["action_primary_slot"],
            text="Wskaż",
            command=lambda: self._choose_project_start_model("char"),
            tone="crt",
        )
        self.btn_ingest_pick_char_model.pack(anchor=tk.W, pady=2)

        self.btn_ingest_asset_more = {}
        self.btn_ingest_clear_asset = {}
        for row_key, button_text in (
            ("images", "Analiza"),
            ("plate_run", "Więcej"),
            ("plate_model", "Więcej"),
            ("char_model", "Więcej"),
        ):
            button = self._create_project_start_badge_button(
                self.ingest_start_asset_row_widgets[row_key]["details_host"],
                text=button_text,
                command=lambda key=row_key: self._show_project_start_asset_details(key),
                tone="crt",
            )
            button.pack(anchor=tk.CENTER, pady=2)
            self.btn_ingest_asset_more[row_key] = button

            clear_button = self._create_project_start_badge_button(
                self.ingest_start_asset_row_widgets[row_key]["action_clear_slot"],
                text="Wyczyść",
                command=lambda key=row_key: self._clear_project_start_asset(key),
                tone="crt",
            )
            self._set_project_start_badge_button_state(clear_button, enabled=False)
            clear_button.pack(anchor=tk.W, pady=2)
            self.btn_ingest_clear_asset[row_key] = clear_button

        try:
            self._restore_project_start_asset_scopes_from_state()
        except Exception:
            pass
        try:
            self._refresh_project_start_assets_table_theme(self._get_step1_ingest_frame_bg())
        except Exception:
            pass

        self.ingest_start_detected_lbl = tk.Label(
            start_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=620,
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
        )
        self.ingest_start_detected_lbl.pack(fill=tk.X, pady=(10, 0))

        self.ingest_start_next_lbl = tk.Label(
            start_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=620,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        self.ingest_start_next_lbl.pack(fill=tk.X, pady=(6, 0))

        ingest_top_section = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        ingest_top_section.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.ingest_top_section = ingest_top_section

        master_row = tk.Frame(ingest_top_section, bg=palette.get("panel", "#252526"))
        master_row.pack(fill=tk.X, padx=10, pady=(8, 4))
        self.ingest_master_row = master_row

        self.lbl_ingest_master_title = tk.Label(
            master_row,
            text="Główna pula zdjęć:",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
        )
        self.lbl_ingest_master_title.pack(anchor=tk.W)

        master_value_row = tk.Frame(ingest_top_section, bg=palette.get("panel", "#252526"))
        master_value_row.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.ingest_master_value_row = master_value_row

        self.lbl_ingest_master_value = tk.Label(
            master_value_row,
            textvariable=self.ingest_master_pool_var,
            justify=tk.LEFT,
            anchor="w",
            wraplength=260,
            fg=palette.get("accent", "#4fc1ff"),
            bg=palette.get("panel", "#252526"),
            font=("Consolas", 9),
        )
        self.lbl_ingest_master_value.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.btn_choose_master_pool = ttk.Button(
            master_value_row,
            text="Wybierz...",
            command=self._choose_master_pool_dir,
        )
        self.btn_choose_master_pool.pack(side=tk.RIGHT, padx=(8, 0))

        self.btn_ingest_master_analysis = ttk.Button(
            master_value_row,
            text="Analiza",
            command=self._show_project_start_images_analysis_dialog,
        )
        self.btn_ingest_master_analysis.pack(side=tk.RIGHT, padx=(0, 8))

        summary_style = self._get_ingest_summary_style()
        status_shell = tk.Frame(
            ingest_top_section,
            bg=summary_style["bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=summary_style["border"],
            highlightcolor=summary_style["border"],
        )
        status_shell.pack(fill=tk.X, padx=10, pady=(2, 6))
        self.ingest_status_shell = status_shell

        status_panel = tk.Frame(
            status_shell,
            bg=summary_style["bg"],
        )
        status_panel.pack(fill=tk.X, padx=8, pady=6)
        self.ingest_status_panel = status_panel
        self.ingest_status_table = tk.Frame(
            status_panel,
            bg=summary_style["border"],
            bd=0,
            highlightthickness=1,
            highlightbackground=summary_style["border"],
            highlightcolor=summary_style["border"],
        )
        self.ingest_status_table.pack(fill=tk.X)
        self.ingest_status_meta_lbl = tk.Label(
            status_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            fg=summary_style["muted"],
            bg=summary_style["bg"],
            font=("Segoe UI", 9),
            wraplength=620,
        )
        self.ingest_status_meta_lbl.pack(fill=tk.X, pady=(8, 0))
        self.ingest_status_labels = [self.ingest_status_meta_lbl]
        self.ingest_status_summary_lbl = self.ingest_status_meta_lbl

        ingest_body = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
        )
        ingest_body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        ingest_body.grid_columnconfigure(0, weight=1, minsize=300)
        ingest_body.grid_rowconfigure(0, weight=1)
        self.ingest_body = ingest_body

        left_col = tk.Frame(ingest_body, bg=palette.get("panel", "#252526"))
        left_col.config(
            bd=0,
            highlightthickness=0,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        left_col.grid(row=0, column=0, sticky="nsew")
        self.ingest_left_col = left_col

        self.ingest_right_col = None

        self.ingest_config_row = None
        self.lbl_ingest_batch_title = None
        self.spn_ingest_batch = None

        self.ingest_actions_row = None
        self.btn_refresh_ingest_stats = None
        self.btn_generate_ingest_plan = None
        self.btn_manual_ingest = None
        self.ingest_list_title_lbl = None
        self.ingest_plan_host = None
        self.ingest_plan_listbox = None
        self.ingest_footer_row = None
        self.btn_remove_ingest_item = None

        approve_row = tk.Frame(left_col, bg=palette.get("panel", "#252526"))
        self.ingest_approve_row = approve_row

        insights_toggle_shell = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
        )
        self.ingest_insights_toggle_shell = insights_toggle_shell

        self.btn_apply_ingest_plan = ttk.Button(
            insights_toggle_shell,
            text="Zatwierdź E1",
            command=self._apply_current_ingest_plan,
            style="Accent.TButton",
            width=18,
        )

        self.ingest_insights_shell = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
        )
        self.ingest_insights_shell.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.ingest_insights_shell.grid_columnconfigure(0, weight=1, minsize=420)

        self.ingest_chart_panel = tk.Frame(self.ingest_insights_shell, bg=palette.get("panel", "#252526"))
        self.ingest_chart_panel.grid(row=0, column=0, sticky="nsew", pady=6)

        self.ingest_balance_title_lbl = tk.Label(
            self.ingest_chart_panel,
            text="Histogram znaków w wybranym folderze zdjęć",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        self.ingest_balance_title_lbl.pack(fill=tk.X, pady=(0, 2))

        self.ingest_balance_canvas = tk.Canvas(
            self.ingest_chart_panel,
            height=220,
            bg=palette.get("field", "#1a1a1a"),
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
        )
        self.ingest_balance_canvas.pack(fill=tk.X)
        self.ingest_balance_canvas.bind("<Configure>", lambda _e: self._refresh_ingest_balance_chart())

        self.ingest_balance_summary_lbl = tk.Label(
            self.ingest_chart_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=520,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        self.ingest_balance_summary_lbl.pack(fill=tk.X, pady=(6, 0))

        self.ingest_info_panel = None
        self.ingest_logic_title_lbl = None
        self.ingest_logic_lbl = None
        self.ingest_selection_title_lbl = None
        self.ingest_selection_lbl = None
        ingest_lf.bind("<Configure>", self._sync_ingest_wraps, add="+")
        self.ingest_insights_shell.bind("<Configure>", self._sync_ingest_wraps, add="+")

        for widget in (
            ingest_lf,
            header_lbl,
            intro_lbl,
            self.lbl_ingest_master_value,
        ):
            HELP.bind_help(widget, "camp_e1_panel")
        HELP.bind_help(self.lbl_ingest_master_title, "camp_e1_master_pool")
        HELP.bind_help(self.lbl_ingest_master_value, "camp_e1_master_pool")
        HELP.bind_help(self.btn_choose_master_pool, "camp_e1_master_pool")
        HELP.bind_help(self.btn_ingest_master_analysis, "camp_e1_master_pool")
        HELP.bind_help(self.ingest_balance_title_lbl, "camp_e1_balance_chart")
        HELP.bind_help(self.ingest_balance_canvas, "camp_e1_balance_chart")
        HELP.bind_help(self.ingest_balance_summary_lbl, "camp_e1_balance_chart")
        HELP.bind_help(self.btn_apply_ingest_plan, "camp_e1_apply")
        HELP.bind_help(self.ingest_insights_toggle_btn, "camp_e1_balance_chart")
        self._refresh_ingest_insights_visibility(mode_selected=False)

    def _build_model_status(self, parent, title, model_type, initial_dir: Path):
        palette = getattr(self.app, "palette", {})

        f = ttk.Frame(parent)
        f.pack(fill=tk.X, pady=10)

        title_lbl = tk.Label(
            f,
            text=title,
            font=("Segoe UI", 10, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526")
        )
        title_lbl.pack(anchor=tk.W)
        self._model_status_title_labels.append(title_lbl)

        row = ttk.Frame(f)
        row.pack(fill=tk.X)

        lbl_val = tk.Label(
            row,
            text="Domyslny/Brak",
            fg=palette.get("accent", "#4fc1ff"),
            bg=palette.get("panel", "#252526"),
            font=("Consolas", 10)
        )
        lbl_val.pack(side=tk.LEFT, expand=True, anchor=tk.W)

        setattr(self, f"lbl_model_{model_type}", lbl_val)

        lbl_meta = tk.Label(
            f,
            text="Utworzono: -",
            fg=palette.get("muted", "#b0b0b0"),
            bg=palette.get("panel", "#252526"),
            font=("Segoe UI", 8),
        )
        lbl_meta.pack(anchor=tk.W, pady=(2, 0))
        self._model_status_meta_labels.append(lbl_meta)
        setattr(self, f"lbl_model_{model_type}_meta", lbl_meta)
        setattr(self, f"btn_model_{model_type}", None)

    def _format_model_created_label(self, model_path: str | Path | None) -> str:
        path_text = str(model_path or "").strip()
        if not path_text:
            return "Utworzono: -"

        try:
            path = Path(path_text)
        except Exception:
            return "Utworzono: -"

        if not path.exists():
            return "Utworzono: -"

        cache = getattr(self, "_dashboard_perf_cache", {})
        model_cache = cache.get("model_created", {}) if isinstance(cache, dict) else {}
        cache_token = self._build_cache_token_for_path(path)
        cache_key = ("created_label", cache_token)
        cached = model_cache.get(cache_key) if isinstance(model_cache, dict) else None
        if isinstance(cached, str):
            return cached

        try:
            created_at = datetime.fromtimestamp(path.stat().st_ctime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "Utworzono: -"
        label = f"Utworzono: {created_at}"
        if isinstance(model_cache, dict):
            if len(model_cache) > 128:
                model_cache.clear()
            model_cache[cache_key] = label
        return label

    def _get_model_identity_label(self, model_path: str | Path | None) -> str:
        path_text = str(model_path or "").strip()
        if not path_text:
            return ""

        try:
            path = Path(path_text)
        except Exception:
            return ""
        if not path.exists():
            return ""

        cache = getattr(self, "_dashboard_perf_cache", {})
        model_cache = cache.get("model_identity", {}) if isinstance(cache, dict) else {}
        cache_token = self._build_cache_token_for_path(path)
        cache_key = ("identity_label", cache_token)
        cached = model_cache.get(cache_key) if isinstance(model_cache, dict) else None
        if isinstance(cached, str):
            return cached

        try:
            _ok, _message, info = validate_model_file(path)
        except Exception:
            info = {}
        label = format_yolo_model_identity(info)
        if label and isinstance(model_cache, dict):
            if len(model_cache) > 128:
                model_cache.clear()
            model_cache[cache_key] = label
        return label

    def _format_model_meta_label(self, model_path: str | Path | None) -> str:
        identity_label = self._get_model_identity_label(model_path)
        created_label = self._format_model_created_label(model_path)
        if identity_label and created_label != "Utworzono: -":
            return f"{identity_label} | {created_label}"
        if identity_label:
            return identity_label
        return created_label

    def _count_images_in_dir(self, directory: Path | None, recursive: bool = True) -> int:
        if directory is None or not directory.exists() or not directory.is_dir():
            return 0

        cache = getattr(self, "_dashboard_perf_cache", {})
        image_cache = cache.get("image_counts", {}) if isinstance(cache, dict) else {}
        cache_key = (self._build_cache_token_for_path(directory), bool(recursive))
        cached = image_cache.get(cache_key) if isinstance(image_cache, dict) else None
        if isinstance(cached, int):
            return cached

        try:
            iterator = directory.rglob("*") if recursive else directory.iterdir()
            count = sum(
                1
                for image_path in iterator
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            )
            if isinstance(image_cache, dict):
                if len(image_cache) > 256:
                    image_cache.clear()
                image_cache[cache_key] = int(count)
            return int(count)
        except Exception:
            return 0

    def _collect_image_names_in_dir(self, directory: Path | None, recursive: bool = True) -> set[str]:
        if directory is None or not directory.exists() or not directory.is_dir():
            return set()

        cache = getattr(self, "_dashboard_perf_cache", {})
        name_cache = cache.get("image_name_sets", {}) if isinstance(cache, dict) else {}
        cache_key = (self._build_cache_token_for_path(directory), bool(recursive))
        cached = name_cache.get(cache_key) if isinstance(name_cache, dict) else None
        if isinstance(cached, set):
            return set(cached)

        names: set[str] = set()
        try:
            iterator = directory.rglob("*") if recursive else directory.iterdir()
            for image_path in iterator:
                if not image_path.is_file() or image_path.suffix.lower() not in CONFIG.IMAGE_EXTENSIONS:
                    continue
                filename = str(image_path.name or "").strip().lower()
                if filename:
                    names.add(filename)
        except Exception:
            return set()

        if isinstance(name_cache, dict):
            if len(name_cache) > 128:
                name_cache.clear()
            name_cache[cache_key] = set(names)
        return names

    def _collect_previous_project_image_names_for_step1(self) -> set[str]:
        try:
            current_iter = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            current_iter = None
        try:
            registry = CAMPAIGN.get_project_packet_filename_registry(exclude_iteration_num=current_iter)
        except Exception:
            return set()
        return {
            str(name or "").strip().lower()
            for name in list((registry or {}).get("filenames") or [])
            if str(name or "").strip()
        }

    @staticmethod
    def _normalize_project_start_mode(mode: str | None) -> str:
        value = str(mode or "").strip().lower()
        if not value:
            return ""
        return "assets" if value == "assets" else "fresh"

    def _is_first_iteration_start_context(self) -> bool:
        if not CAMPAIGN.get_active_project_name():
            return False
        try:
            return int(CAMPAIGN.get_current_iteration_num() or 1) == 1 and CAMPAIGN.get_step1_status() != "approved"
        except Exception:
            return False

    def _is_step1_operational_context(self) -> bool:
        if not CAMPAIGN.get_active_project_name():
            return False
        try:
            return (
                int(CAMPAIGN.get_current_step() or 1) == 1
                and str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved"
            )
        except Exception:
            return False

    def _get_step1_presentation_mode(self) -> str:
        if not CAMPAIGN.get_active_project_name():
            return "summary"
        try:
            current_step = int(CAMPAIGN.get_current_step() or 1)
        except Exception:
            current_step = 1
        step1_status = str(CAMPAIGN.get_step1_status() or "").strip().lower()
        if current_step != 1 or step1_status == "approved":
            return "summary"
        return "operational_assets"

    def _get_project_start_mode(self) -> str:
        try:
            mode = CAMPAIGN.get_project_start_mode()
        except Exception:
            mode = ""
        mode = self._normalize_project_start_mode(mode)
        if not mode and self._is_step1_operational_context():
            mode = "fresh"
            try:
                CAMPAIGN.set_project_start_mode(mode)
            except Exception:
                pass
        try:
            self.project_start_mode_var.set(mode)
        except Exception:
            pass
        return mode

    def _get_active_step1_draft_plan(self) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {}
        if str(CAMPAIGN.get_step1_status() or "").strip().lower() == "approved":
            return {}
        plan = getattr(self, "current_ingest_plan", None)
        if not isinstance(plan, dict) or not plan:
            return {}
        try:
            current_iter = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            current_iter = 1
        current_proj = str(CAMPAIGN.get_active_project_name() or "").strip()
        try:
            plan_iter = int(plan.get("iteration", 0) or 0)
        except Exception:
            plan_iter = 0
        plan_proj = str(plan.get("project", "") or "").strip()
        if plan_iter != current_iter or plan_proj != current_proj:
            return {}
        if plan.get("selected") is None:
            return {}
        return plan

    def _set_project_start_mode(self, mode: str | None, *, refresh: bool = True) -> None:
        normalized = self._normalize_project_start_mode(mode)
        try:
            self.project_start_mode_var.set(normalized)
        except Exception:
            pass

        try:
            CAMPAIGN.set_project_start_mode(normalized)
        except Exception:
            pass

        if refresh:
            self._refresh_ingest_panel()

    def _choose_project_start_model(self, model_type: str) -> None:
        self._set_project_start_mode("assets", refresh=False)
        row_key = "plate_model" if str(model_type or "").strip().lower() == "plate" else "char_model"
        self._set_model(model_type, initial_dir=self._get_project_start_asset_initial_dir(row_key))

    @staticmethod
    def _looks_like_character_model_classes(class_names: list[str]) -> bool:
        normalized = [str(name).strip().upper() for name in class_names if str(name).strip()]
        if len(normalized) < 8:
            return False

        allowed = set(CHAR_ALPHABET)
        for token in normalized:
            if len(token) != 1 or token not in allowed:
                return False
        return True

    def _validate_project_model_selection(self, model_type: str, model_path: Path) -> tuple[bool, str]:
        ok, message, info = validate_model_file(model_path)
        if not ok:
            return False, message or "Nie udało się odczytać modelu."

        task = str(info.get("task") or "").strip().lower()
        inferred_type = str(info.get("type") or "").strip().lower()
        is_pose = bool(info.get("keypoints")) or task == "pose" or inferred_type == "pose"
        class_names = [str(name).strip() for name in (info.get("classes") or []) if str(name).strip()]
        class_names_lower = [name.lower() for name in class_names]
        joined_names = " ".join(class_names_lower)

        if model_type == "plate":
            if not is_pose:
                return False, "Model tablic musi być modelem YOLO Pose z punktami kluczowymi."
            if class_names and not any(
                (name in CONFIG.PLATE_LABELS) or ("plate" in name) or ("tablic" in name) or ("rejestr" in name)
                for name in class_names_lower
            ):
                return False, "To nie wygląda na model tablic: w klasach nie widać znacznika plate/tablica."
            return True, ""

        if model_type == "char":
            if is_pose:
                return False, "Model znaków nie może być modelem Pose."
            if not class_names:
                return False, "Nie udało się odczytać klas modelu znaków z pliku .pt."
            if not self._looks_like_character_model_classes(class_names):
                return False, "Model znaków powinien mieć klasy znaków 0-9 i A-Z."
            return True, ""

        if model_type == "vehicle":
            if is_pose:
                return False, "Model pojazdów powinien być modelem detekcyjnym, nie Pose."
            if class_names and self._looks_like_character_model_classes(class_names):
                return False, "To wygląda na model znaków, nie pojazdów."
            vehicle_markers = (
                "vehicle", "car", "truck", "bus", "motorcycle", "motorbike", "van",
                "pickup", "suv", "pojazd", "samochod", "auto"
            )
            if class_names and not any(marker in joined_names for marker in vehicle_markers):
                return False, "To nie wygląda na model pojazdów: w klasach nie widać typowych znacznikow pojazdów."
            return True, ""

        return True, ""

    def _resolve_project_start_run_images_dir(self, run_dir: Path | None) -> Path | None:
        if run_dir is None:
            return None

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return None

        try:
            manifest = annotation_tab._load_annotation_run_manifest(run_dir)
        except Exception:
            manifest = {}

        for raw_path in (
            str(manifest.get("imported_source_input_dir") or "").strip(),
            str(manifest.get("input_dir") or "").strip(),
        ):
            if not raw_path:
                continue
            try:
                candidate = Path(raw_path)
            except Exception:
                continue
            if candidate.exists() and candidate.is_dir() and self._count_images_in_dir(candidate, recursive=True) > 0:
                return candidate

        return None

    @staticmethod
    def _normalize_project_start_asset_full_path(path_value) -> str:
        raw_text = str(path_value or "").strip()
        if not raw_text:
            return ""
        try:
            return str(Path(raw_text).resolve())
        except Exception:
            return raw_text

    def _format_workspace_relative_path(self, path_like) -> str:
        raw_text = self._normalize_project_start_asset_full_path(path_like)
        if not raw_text:
            return ""
        try:
            workspace_root = Path(CONFIG.WORKSPACE_DIR).resolve()
            return os.path.relpath(raw_text, str(workspace_root))
        except Exception:
            try:
                candidate = Path(raw_text)
                parent_name = str(candidate.parent.name or "").strip()
                if parent_name:
                    return f"{parent_name}/{candidate.name}"
                return candidate.name
            except Exception:
                return str(raw_text)

    def _format_project_relative_path(self, path_value: str) -> str:
        raw_text = self._normalize_project_start_asset_full_path(path_value)
        if not raw_text:
            return ""
        try:
            project_root = CAMPAIGN.get_active_project_root_dir()
            if project_root is not None:
                project_root = Path(project_root).resolve()
                candidate = Path(raw_text)
                return os.path.relpath(str(candidate), str(project_root))
        except Exception:
            pass
        return self._format_workspace_relative_path(raw_text)

    def _format_project_start_asset_source(self, path_value) -> str:
        normalized_full_path = self._normalize_project_start_asset_full_path(path_value)
        if not normalized_full_path:
            return "Nie wskazano"
        try:
            return self._format_project_relative_path(normalized_full_path)
        except Exception:
            try:
                return self._format_workspace_relative_path(normalized_full_path)
            except Exception:
                return Path(normalized_full_path).name

    def _collect_project_start_image_names(
        self,
        images_dir: Path | None = None,
        manifest: dict | None = None,
    ) -> list[str]:
        image_names: list[str] = []

        for item in list((self.current_ingest_plan or {}).get("selected", []) or []):
            name = str(item.get("name") or "").strip()
            if not name:
                try:
                    name = str(Path(str(item.get("source_path") or "").strip()).name or "").strip()
                except Exception:
                    name = ""
            if name:
                image_names.append(name)

        if not image_names and isinstance(manifest, dict):
            for item in list(manifest.get("selected_images", []) or []):
                name = str((item or {}).get("name") or "").strip()
                if name:
                    image_names.append(name)

        if not image_names and isinstance(images_dir, Path):
            try:
                for image_path in images_dir.rglob("*"):
                    if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS:
                        image_names.append(image_path.name)
            except Exception:
                pass

        return image_names

    def _build_project_start_image_set_token(
        self,
        images_dir: Path | None = None,
        manifest: dict | None = None,
    ) -> tuple[str, int]:
        image_names = self._collect_project_start_image_names(images_dir=images_dir, manifest=manifest)
        token = CAMPAIGN.build_image_name_set_token(image_names, images_dir=images_dir)
        unique_count = len(
            {
                CAMPAIGN._normalize_image_set_name(name)
                for name in image_names
                if CAMPAIGN._normalize_image_set_name(name)
            }
        )
        return token, int(unique_count or 0)

    def _build_project_start_plate_xml_image_set_token(self, run_dir: Path | None) -> tuple[str, int]:
        if run_dir is None:
            return "", 0

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return "", 0

        try:
            safe_run_dir = annotation_tab._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
        except Exception:
            safe_run_dir = None
        if safe_run_dir is None:
            return "", 0

        try:
            annotations = annotation_tab._parse_cvat_preview_annotations(safe_run_dir / "annotations.xml")
        except Exception:
            annotations = []
        image_names = [str(getattr(ann, "filename", "") or "").strip() for ann in annotations if str(getattr(ann, "filename", "") or "").strip()]
        token = CAMPAIGN.build_image_name_set_token(image_names)
        unique_count = len(
            {
                CAMPAIGN._normalize_image_set_name(name)
                for name in image_names
                if CAMPAIGN._normalize_image_set_name(name)
            }
        )
        return token, int(unique_count or 0)

    def _show_project_start_asset_source_context_menu(self, event, row_key: str) -> None:
        rows = getattr(self, "ingest_start_asset_row_widgets", {}) or {}
        row = rows.get(str(row_key or "").strip())
        if not isinstance(row, dict):
            return

        source_full_path = str(row.get("source_full_path") or "").strip()
        if not source_full_path:
            return

        menu = tk.Menu(self.frame, tearoff=0)
        menu.add_command(
            label="Kopiuj pełną ścieżkę",
            command=lambda value=source_full_path: self._copy_project_start_asset_source_path(value),
        )
        menu.add_separator()
        menu.add_command(
            label="Wyczyść wybór",
            command=lambda key=str(row_key or "").strip(): self._clear_project_start_asset(key),
            state=("normal" if self._is_project_start_asset_clearable(row_key) else "disabled"),
        )
        try:
            menu.tk_popup(int(event.x_root), int(event.y_root))
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _copy_project_start_asset_source_path(self, full_path: str) -> None:
        safe_value = str(full_path or "").strip()
        if not safe_value:
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(safe_value)
            self.frame.update_idletasks()
        except Exception:
            return
        try:
            self.app.update_status("Skopiowano pełną ścieżkę zasobu.", "info")
        except Exception:
            pass

    def _is_project_start_asset_clearable(self, row_key: str) -> bool:
        row_key = str(row_key or "").strip()
        if row_key == "images":
            plan = getattr(self, "current_ingest_plan", None)
            if isinstance(plan, dict):
                try:
                    if int(plan.get("selected_total", 0) or 0) > 0:
                        return True
                except Exception:
                    pass
                try:
                    if len(list(plan.get("selected", []) or [])) > 0:
                        return True
                except Exception:
                    pass

            try:
                master_pool = CAMPAIGN.get_master_pool_dir()
            except Exception:
                master_pool = None
            if master_pool is None:
                return False
            try:
                master_pool_path = Path(master_pool)
                return bool(
                    master_pool_path.exists()
                    and master_pool_path.is_dir()
                    and self._count_images_in_dir(master_pool_path, recursive=True) > 0
                )
            except Exception:
                return False
        if row_key == "plate_run":
            try:
                source = CAMPAIGN.get_project_start_plate_source() or {}
            except Exception:
                source = {}
            return bool(
                str(source.get("source_run_path", "") or "").strip()
                or str(source.get("source_xml_path", "") or "").strip()
                or str(source.get("source_input_path", "") or "").strip()
            )
        if row_key == "plate_model":
            try:
                return bool(str(CAMPAIGN.get_global_model("plate") or "").strip())
            except Exception:
                return False
        if row_key == "char_model":
            try:
                return bool(str(CAMPAIGN.get_global_model("char") or "").strip())
            except Exception:
                return False
        return False

    def _refresh_project_start_clear_buttons(self) -> None:
        buttons = getattr(self, "btn_ingest_clear_asset", {}) or {}
        if not isinstance(buttons, dict):
            return
        for row_key, button in buttons.items():
            if button is None:
                continue
            try:
                self._set_project_start_badge_button_state(
                    button,
                    enabled=self._is_project_start_asset_clearable(row_key),
                )
            except Exception:
                pass

    def _clear_project_start_asset(self, row_key: str) -> None:
        row_key = str(row_key or "").strip()
        if row_key not in {"images", "plate_run", "plate_model", "char_model"}:
            return
        if not self._is_project_start_asset_clearable(row_key):
            return

        label_map = {
            "images": "katalogu zdjęć",
            "plate_run": "anotacji tablic",
            "plate_model": "modelu tablic",
            "char_model": "modelu znaków",
        }
        label = label_map.get(row_key, "zasobu")

        try:
            confirmed = messagebox.askyesno(
                "Wyczyść wybór",
                f"Czy wyczyścić wybór {label} w E1?\n\n"
                "Operacja usuwa wskazanie z projektu, ale nie kasuje plików z dysku.",
                parent=self.frame,
            )
        except Exception:
            confirmed = True
        if not confirmed:
            return

        try:
            if row_key == "images":
                try:
                    CAMPAIGN.clear_master_pool_dir()
                except Exception:
                    pass
                try:
                    CAMPAIGN.clear_latest_ingest_plan()
                except Exception:
                    pass
                self.current_ingest_plan = {}
                self.ingest_plan_items = []
                try:
                    self._existing_iteration_ingest_plan_signature = None
                except Exception:
                    pass
            elif row_key == "plate_run":
                try:
                    CAMPAIGN.clear_project_start_plate_source()
                except Exception:
                    pass
                self._set_project_start_asset_scope("plate_run", "", persist=True)
            elif row_key == "plate_model":
                try:
                    CAMPAIGN.set_global_model("plate", "")
                except Exception:
                    pass
                self._set_project_start_asset_scope("plate_model", "", persist=True)
            elif row_key == "char_model":
                try:
                    CAMPAIGN.set_global_model("char", "")
                except Exception:
                    pass
                self._set_project_start_asset_scope("char_model", "", persist=True)

            if self._get_iteration_target() == "char" and self._get_step1_char_route_block_reason():
                try:
                    CAMPAIGN.clear_iteration_target()
                except Exception:
                    pass

            try:
                self._clear_dashboard_perf_cache()
            except Exception:
                pass
            try:
                self._sync_iteration_artifact_registry_from_project_start()
            except Exception:
                pass
            self._refresh_dashboard()
            try:
                self.app.update_status(f"Wyczyszczono wybór {label} w E1.", "info")
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Nie udało się wyczyścić zasobu E1 ({row_key}): {e}")

    @staticmethod
    def _short_project_start_asset_validation(message: str, width: int = 72) -> str:
        text = str(message or "").replace("\n", " ").strip()
        if not text:
            return "Brak"
        return shorten(text, width=max(24, int(width or 72)), placeholder="...")

    def _get_step1_ingest_frame_bg(self) -> str:
        palette = getattr(self.app, "palette", {})
        fallback_bg = palette.get("panel", "#252526")
        if self.step1_ingest_host_item is not None:
            extra_frame = self.step1_ingest_host_item.get("extra_actions_frame")
            if extra_frame is not None:
                try:
                    return str(extra_frame.cget("bg") or fallback_bg)
                except Exception:
                    return fallback_bg
        return fallback_bg

    def _get_project_start_asset_scope(self, row_key: str) -> str:
        row_key = str(row_key or "").strip()
        if row_key == "images":
            return "na"
        vars_map = getattr(self, "project_start_asset_scope_vars", {}) or {}
        var = vars_map.get(row_key)
        try:
            value = str(var.get() or "").strip().lower()
        except Exception:
            value = ""
        if value in {"project", "freemode", "na"}:
            return value
        try:
            persisted = str(CAMPAIGN.get_project_start_asset_scope(row_key) or "").strip().lower()
        except Exception:
            persisted = ""
        if persisted in {"project", "freemode", "na"}:
            return persisted
        return "project"

    def _set_project_start_asset_scope(self, row_key: str, scope: str, *, persist: bool = True) -> None:
        row_key = str(row_key or "").strip()
        vars_map = getattr(self, "project_start_asset_scope_vars", {}) or {}
        var = vars_map.get(row_key)
        normalized = str(scope or "").strip().lower()
        if row_key == "images":
            normalized = "na"
        elif normalized not in {"project", "freemode", "na"}:
            normalized = "project"
        if var is None:
            try:
                if persist and row_key != "images":
                    CAMPAIGN.set_project_start_asset_scope(row_key, normalized)
            except Exception:
                pass
            return
        try:
            var.set(normalized)
        except Exception:
            pass
        try:
            if persist and row_key != "images":
                CAMPAIGN.set_project_start_asset_scope(row_key, normalized)
        except Exception:
            pass

    def _restore_project_start_asset_scopes_from_state(self) -> None:
        try:
            imported_plate_source = CAMPAIGN.get_project_start_plate_source() or {}
        except Exception:
            imported_plate_source = {}
        restore_specs = (
            (
                "plate_run",
                str(CAMPAIGN.get_project_start_asset_scope("plate_run") or "").strip().lower(),
                str(imported_plate_source.get("source_xml_path") or "").strip()
                or str(imported_plate_source.get("source_run_path") or "").strip(),
            ),
            (
                "plate_model",
                str(CAMPAIGN.get_project_start_asset_scope("plate_model") or "").strip().lower(),
                str(CAMPAIGN.get_global_model("plate") or "").strip(),
            ),
            (
                "char_model",
                str(CAMPAIGN.get_project_start_asset_scope("char_model") or "").strip().lower(),
                str(CAMPAIGN.get_global_model("char") or "").strip(),
            ),
        )

        for row_key, persisted_scope, fallback_path in restore_specs:
            scope_value = persisted_scope or self._infer_project_start_asset_scope_from_path(row_key, fallback_path)
            self._set_project_start_asset_scope(row_key, scope_value, persist=False)

    def _select_project_start_asset_scope(self, row_key: str, scope: str) -> None:
        if self._get_project_start_asset_scope(row_key) == str(scope or "").strip().lower():
            return
        self._set_project_start_asset_scope(row_key, scope)
        try:
            self._refresh_project_start_assets_table_theme(self._get_step1_ingest_frame_bg())
            self._sync_ingest_wraps()
            self.frame.update_idletasks()
        except Exception:
            pass

    @staticmethod
    def _path_is_inside_root(candidate: Path | None, root: Path | None) -> bool:
        if candidate is None or root is None:
            return False
        try:
            candidate.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    def _infer_project_start_asset_scope_from_path(self, row_key: str, path_value) -> str:
        row_key = str(row_key or "").strip()
        if row_key == "images":
            return "na"
        raw_path = str(path_value or "").strip()
        if not raw_path:
            return self._get_project_start_asset_scope(row_key)
        try:
            candidate = Path(raw_path)
        except Exception:
            return self._get_project_start_asset_scope(row_key)
        project_root = CAMPAIGN.get_active_project_root_dir()
        if self._path_is_inside_root(candidate, project_root):
            return "project"
        return "freemode"

    def _get_project_start_plate_source_info(self) -> dict:
        stored_plate_source = dict(CAMPAIGN.get_project_start_plate_source() or {})

        run_path = str(
            stored_plate_source.get("source_run_path")
            or ""
        ).strip()
        xml_path = str(stored_plate_source.get("source_xml_path") or "").strip()
        images_path = str(stored_plate_source.get("source_input_path") or "").strip()

        run_dir = None
        if run_path:
            try:
                candidate = Path(run_path)
                if candidate.exists() and candidate.is_dir():
                    run_dir = candidate
            except Exception:
                run_dir = None

        if not xml_path and run_dir is not None:
            try:
                candidate_xml = run_dir / "annotations.xml"
                if candidate_xml.exists() and candidate_xml.is_file():
                    xml_path = str(candidate_xml.resolve())
            except Exception:
                pass

        if run_dir is None and xml_path:
            try:
                xml_candidate = Path(xml_path)
                if xml_candidate.exists() and xml_candidate.is_file():
                    run_dir = xml_candidate.parent
                    run_path = str(run_dir.resolve())
            except Exception:
                run_dir = None

        return {
            "run_path": str(run_path or "").strip(),
            "xml_path": str(xml_path or "").strip(),
            "images_path": str(images_path or "").strip(),
            "run_dir": run_dir,
        }

    def _get_project_start_asset_initial_dir(self, row_key: str) -> Path:
        row_key = str(row_key or "").strip()
        scope = self._get_project_start_asset_scope(row_key)
        project_root = CAMPAIGN.get_active_project_root_dir()
        project_models_dir = CAMPAIGN.get_dir("models")
        project_auto_ann_dir = CAMPAIGN.get_dir("auto_ann")

        if row_key == "plate_run":
            plate_source_info = self._get_project_start_plate_source_info()
            current_path = str(
                plate_source_info.get("xml_path")
                or plate_source_info.get("run_path")
                or ""
            ).strip()
            if current_path:
                try:
                    current_candidate = Path(current_path)
                    current_dir = current_candidate.parent if current_candidate.is_file() else current_candidate
                    if current_dir.exists() and current_dir.is_dir():
                        if scope == "project" and self._path_is_inside_root(current_dir, project_root):
                            return current_dir
                        if scope == "freemode" and not self._path_is_inside_root(current_dir, project_root):
                            return current_dir
                except Exception:
                    pass
            if scope == "project" and project_auto_ann_dir is not None:
                candidate = Path(project_auto_ann_dir) / "plates"
                return candidate if candidate.exists() else Path(project_auto_ann_dir)
            return Path(CONFIG.get_auto_annotations_dir("plate"))

        if row_key == "plate_model":
            current_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
            if current_path:
                try:
                    current_file = Path(current_path)
                    if current_file.exists() and current_file.is_file():
                        current_dir = current_file.parent
                        if scope == "project" and self._path_is_inside_root(current_dir, project_root):
                            return current_dir
                        if scope == "freemode" and not self._path_is_inside_root(current_dir, project_root):
                            return current_dir
                except Exception:
                    pass
            if scope == "project" and project_models_dir is not None:
                return Path(project_models_dir)
            for candidate in CONFIG.get_model_search_dirs("plate"):
                if candidate.exists():
                    return candidate
            return Path(CONFIG.DIR_6_MODELS)

        if row_key == "char_model":
            current_path = str(CAMPAIGN.get_global_model("char") or "").strip()
            if current_path:
                try:
                    current_file = Path(current_path)
                    if current_file.exists() and current_file.is_file():
                        current_dir = current_file.parent
                        if scope == "project" and self._path_is_inside_root(current_dir, project_root):
                            return current_dir
                        if scope == "freemode" and not self._path_is_inside_root(current_dir, project_root):
                            return current_dir
                except Exception:
                    pass
            if scope == "project" and project_models_dir is not None:
                return Path(project_models_dir)
            for candidate in CONFIG.get_model_search_dirs("char"):
                if candidate.exists():
                    return candidate
            return Path(CONFIG.DIR_6_MODELS)

        return Path(CONFIG.WORKSPACE_DIR)

    def _sync_iteration_artifact_registry_from_project_start(self) -> None:
        if not CAMPAIGN.get_active_project_name():
            return

        try:
            iteration_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            iteration_num = 1

        master_pool = CAMPAIGN.get_iteration_image_source_dir(iteration_num) or CAMPAIGN.get_master_pool_dir()
        if master_pool is None:
            master_pool = CAMPAIGN.get_iteration_raw_dir(iteration_num)
        if master_pool is None:
            return

        try:
            master_pool_path = Path(master_pool)
        except Exception:
            return

        try:
            manifest_path = CAMPAIGN.get_ingest_manifest_path(iteration_num)
        except Exception:
            manifest_path = None

        try:
            manifest = CAMPAIGN.load_ingest_manifest(iteration_num) or {}
        except Exception:
            manifest = {}

        image_set_token, image_set_count = self._build_project_start_image_set_token(
            images_dir=master_pool_path,
            manifest=manifest,
        )
        package_id = str(
            CAMPAIGN.build_iteration_artifact_package_id(
                master_pool_path,
                iteration_num=iteration_num,
                image_set_token=image_set_token,
            ) or ""
        ).strip()

        stored_plate_source = dict(CAMPAIGN.get_project_start_plate_source() or {})
        existing_bundle = dict(
            CAMPAIGN.get_iteration_artifact_bundle(
                images_dir=master_pool_path,
                iteration_num=iteration_num,
            ) or {}
        )
        existing_char_effective = dict(existing_bundle.get("char_effective_source") or {})

        plate_run_dir_raw = str(
            stored_plate_source.get("source_run_path")
            or ""
        ).strip()
        plate_xml_raw = str(stored_plate_source.get("source_xml_path") or "").strip()
        plate_images_raw = str(stored_plate_source.get("source_input_path") or "").strip()

        plate_run_dir = None
        if plate_run_dir_raw:
            try:
                candidate = Path(plate_run_dir_raw)
                if candidate.exists() and candidate.is_dir():
                    plate_run_dir = candidate
            except Exception:
                plate_run_dir = None
        if plate_run_dir is not None and not plate_xml_raw:
            try:
                candidate_xml = plate_run_dir / "annotations.xml"
                if candidate_xml.exists():
                    plate_xml_raw = str(candidate_xml.resolve())
            except Exception:
                pass
        if plate_run_dir is not None and not plate_images_raw:
            try:
                resolved_images = self._resolve_project_start_run_images_dir(plate_run_dir)
                if resolved_images is not None:
                    plate_images_raw = str(resolved_images.resolve())
            except Exception:
                pass

        plate_xml_image_set_token, plate_xml_image_count = self._build_project_start_plate_xml_image_set_token(
            plate_run_dir
        )
        plate_image_set_match = bool(
            image_set_token
            and plate_xml_image_set_token
            and image_set_token == plate_xml_image_set_token
        )

        plate_images_with_plates = 0
        plate_total_plates = 0
        if plate_run_dir is not None:
            try:
                annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
                if annotation_tab is not None and hasattr(annotation_tab, "_get_run_plate_annotation_counts"):
                    plate_images_with_plates, plate_total_plates = annotation_tab._get_run_plate_annotation_counts(plate_run_dir)
            except Exception:
                plate_images_with_plates, plate_total_plates = 0, 0

        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())
        plate_run_ready = bool(plate_run_dir is not None and plate_xml_raw)

        plate_entry_mode = "manual_template"
        if plate_run_ready:
            plate_entry_mode = "ready_run"
        elif plate_model_ready:
            plate_entry_mode = "auto"

        char_images_with_plates = int(existing_char_effective.get("images_with_plates", 0) or 0)
        char_total_plates = int(existing_char_effective.get("total_plates", 0) or 0)
        min_char_plates = int(getattr(self, "STEP3_CHAR_MIN_PLATES", 10) or 10)
        char_entry_mode = "blocked"
        if char_total_plates >= min_char_plates:
            char_entry_mode = "ready"
        elif plate_total_plates > 0 or char_total_plates > 0 or plate_run_ready:
            char_entry_mode = "needs_more_tables"

        updates = {
            "image_source": {
                "package_id": package_id,
                "master_pool_dir": str(master_pool_path.resolve()) if master_pool_path.exists() else str(master_pool_path),
                "master_pool_token": CAMPAIGN._build_registry_path_token(master_pool_path),
                "iteration_raw_dir": str(CAMPAIGN.get_iteration_raw_dir(iteration_num) or ""),
                "ingest_manifest_path": str(manifest_path or ""),
                "ingest_manifest_token": CAMPAIGN._build_registry_path_token(manifest_path),
                "selected_count": int(manifest.get("selected_count", 0) or 0),
                "image_set_token": str(image_set_token or "").strip(),
                "image_set_count": int(image_set_count or 0),
                "selection_mode": str(manifest.get("selection_mode") or "").strip(),
            },
            "plate_source": {
                "package_id": package_id,
                "run_dir": str(plate_run_dir.resolve()) if plate_run_dir is not None else "",
                "run_token": CAMPAIGN._build_registry_path_token(plate_run_dir),
                "xml_path": plate_xml_raw,
                "xml_token": CAMPAIGN._build_registry_path_token(plate_xml_raw),
                "xml_image_set_token": str(plate_xml_image_set_token or "").strip(),
                "xml_image_count": int(plate_xml_image_count or 0),
                "images_dir": plate_images_raw,
                "images_token": CAMPAIGN._build_registry_path_token(plate_images_raw),
                "expected_image_set_token": str(image_set_token or "").strip(),
                "expected_image_count": int(image_set_count or 0),
                "image_set_match": bool(plate_image_set_match),
                "scope": self._get_project_start_asset_scope("plate_run"),
                "input_source": "project_start_import" if plate_run_ready else "",
                "images_with_plates": int(plate_images_with_plates or 0),
                "total_plates": int(plate_total_plates or 0),
            },
            "plate_model": {
                "path": plate_model_path,
                "token": CAMPAIGN._build_registry_path_token(plate_model_path),
                "scope": self._get_project_start_asset_scope("plate_model"),
                "identity": self._get_model_identity_label(plate_model_path) if plate_model_ready else "",
            },
            "char_model": {
                "path": char_model_path,
                "token": CAMPAIGN._build_registry_path_token(char_model_path),
                "scope": self._get_project_start_asset_scope("char_model"),
                "identity": self._get_model_identity_label(char_model_path) if (char_model_path and Path(char_model_path).exists()) else "",
            },
            "route_hints": {
                "plate_entry_mode": plate_entry_mode,
                "char_entry_mode": char_entry_mode,
                "char_ready": bool(char_entry_mode == "ready"),
                "char_has_source": bool(plate_run_ready or char_total_plates > 0),
                "needs_more_tables": bool(char_entry_mode == "needs_more_tables"),
                "images_with_plates": int(char_images_with_plates or plate_images_with_plates or 0),
                "total_plates": int(char_total_plates or plate_total_plates or 0),
            },
        }
        try:
            CAMPAIGN.upsert_iteration_artifact_bundle(
                images_dir=master_pool_path,
                iteration_num=iteration_num,
                image_set_token=image_set_token,
                updates=updates,
            )
        except Exception as e:
            logger.debug(f"Nie udało się zsynchronizować rejestru artefaktów E1: {e}")

    def _set_project_start_asset_row_state(
        self,
        row_key: str,
        *,
        source_text: str = "",
        source_path: str = "",
        validation_text: str = "",
        tone: str = "muted",
    ) -> None:
        rows = getattr(self, "ingest_start_asset_row_widgets", {}) or {}
        row = rows.get(str(row_key or "").strip())
        if not isinstance(row, dict):
            return

        try:
            display_text = self._format_tail_text(str(source_text or "").strip() or "Nie wskazano", width=26)
            row["source_var"].set(display_text or "Nie wskazano")
        except Exception:
            pass
        row["source_full_path"] = self._normalize_project_start_asset_full_path(source_path)

        row["tone"] = str(tone or "muted").strip().lower() or "muted"
        try:
            row["validation_lbl"].config(text=self._short_project_start_asset_validation(validation_text))
        except Exception:
            pass

    def _refresh_project_start_assets_table_theme(self, frame_bg: str | None = None) -> None:
        rows = getattr(self, "ingest_start_asset_row_widgets", {}) or {}
        if not isinstance(rows, dict) or not rows:
            return

        palette = getattr(self.app, "palette", {})
        base_bg = str(frame_bg or self._get_step1_ingest_frame_bg())
        panel_bg = palette.get("field", "#1a1a1a")
        muted = palette.get("muted", "#c7c7c7")
        fg = palette.get("fg", "#f3f3f3")
        accent = palette.get("accent", "#4fc1ff")
        success = palette.get("success", "#27ae60")
        grid_border = blend_hex_colors(
            success,
            base_bg,
            0.80,
        )
        header_bg = blend_hex_colors(success, base_bg, 0.16)
        header_fg = self._pick_readable_text_color(header_bg)
        tone_map = {
            "muted": muted,
            "info": accent,
            "success": success,
            "warning": palette.get("warning", "#d35400"),
            "error": palette.get("error", "#c0392b"),
        }

        shell = getattr(self, "ingest_start_assets_table_shell", None)
        table = getattr(self, "ingest_start_assets_table", None)
        title_lbl = getattr(self, "ingest_start_assets_title_lbl", None)
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        if shell is not None:
            try:
                shell.config(
                    bg=grid_border,
                    highlightthickness=1,
                    highlightbackground=grid_border,
                    highlightcolor=grid_border,
                )
            except Exception:
                pass
        if table is not None:
            try:
                table.config(bg=grid_border)
            except Exception:
                pass
        if title_lbl is not None:
            try:
                title_lbl.config(bg=base_bg, fg=fg)
            except Exception:
                pass
        try:
            for header_lbl in list(getattr(self, "ingest_start_assets_header_labels", []) or []):
                if header_lbl is None:
                    continue
                header_lbl.config(
                    bg=header_bg,
                    fg=header_fg,
                    highlightthickness=1,
                    highlightbackground=grid_border,
                    highlightcolor=grid_border,
                )
        except Exception:
            pass

        for row_index, row_key in enumerate(("images", "plate_run", "plate_model", "char_model"), start=1):
            row = rows.get(row_key)
            if not isinstance(row, dict):
                continue
            row_bg = blend_hex_colors(base_bg, panel_bg, 0.10 if (row_index % 2 == 1) else 0.18)
            row_fg = self._pick_readable_text_color(row_bg)
            validation_fg = tone_map.get(str(row.get("tone", "muted") or "muted").strip().lower(), muted)

            for widget_name, fg_value in (
                ("name_lbl", row_fg),
                ("source_lbl", accent),
                ("validation_lbl", validation_fg),
            ):
                widget = row.get(widget_name)
                if widget is None:
                    continue
                try:
                    widget.config(
                        bg=row_bg,
                        fg=fg_value,
                        highlightthickness=1,
                        highlightbackground=grid_border,
                        highlightcolor=grid_border,
                    )
                except Exception:
                    pass

            source_scope_host = row.get("source_scope_host")
            if source_scope_host is not None:
                try:
                    source_scope_host.config(
                        bg=row_bg,
                        highlightthickness=1,
                        highlightbackground=grid_border,
                        highlightcolor=grid_border,
                    )
                except Exception:
                    pass
            current_scope = self._get_project_start_asset_scope(row_key)
            managed_scope_widgets = set()
            for badge in row.get("scope_badges", []) or []:
                badge_value = str(badge.get("value") or "").strip().lower()
                shell_widget = badge.get("shell")
                lamp_widget = badge.get("lamp")
                lamp_id = badge.get("lamp_id")
                label_widget = badge.get("label")
                active = bool(badge_value == current_scope)
                shell_bg = (
                    blend_hex_colors(row_bg, palette.get("success", "#27ae60"), 0.20)
                    if active
                    else blend_hex_colors(row_bg, palette.get("field", "#1a1a1a"), 0.12)
                )
                lamp_fill = palette.get("success", "#27ae60") if active else palette.get("muted_dim", "#4a4a4a")
                text_fg = fg if active else muted
                border_color = (
                    blend_hex_colors(palette.get("success", "#27ae60"), row_bg, 0.18)
                    if active
                    else blend_hex_colors(row_bg, palette.get("field", "#1a1a1a"), 0.26)
                )
                for managed_widget in (shell_widget, lamp_widget, label_widget):
                    if managed_widget is not None:
                        managed_scope_widgets.add(managed_widget)
                if shell_widget is not None:
                    try:
                        shell_widget.config(
                            bg=shell_bg,
                            highlightthickness=1,
                            highlightbackground=border_color,
                            highlightcolor=border_color,
                        )
                    except Exception:
                        pass
                if lamp_widget is not None:
                    try:
                        lamp_widget.config(bg=shell_bg)
                        if lamp_id is not None:
                            lamp_widget.itemconfig(lamp_id, fill=lamp_fill)
                    except Exception:
                        pass
                if label_widget is not None:
                    try:
                        label_widget.config(bg=shell_bg, fg=text_fg)
                    except Exception:
                        pass
            for widget in row.get("scope_widgets", []) or []:
                if widget in managed_scope_widgets:
                    continue
                try:
                    widget_class = str(widget.winfo_class() or "").lower()
                except Exception:
                    widget_class = ""
                try:
                    if "label" in widget_class:
                        widget.config(bg=row_bg, fg=muted)
                    elif "canvas" in widget_class:
                        widget.config(bg=row_bg)
                    else:
                        widget.config(bg=row_bg)
                except Exception:
                    pass

            action_host = row.get("action_host")
            if action_host is not None:
                try:
                    action_host.config(
                        bg=row_bg,
                        highlightthickness=1,
                        highlightbackground=grid_border,
                        highlightcolor=grid_border,
                    )
                except Exception:
                    pass
            for slot_name in ("action_primary_slot", "action_clear_slot"):
                slot = row.get(slot_name)
                if slot is not None:
                    try:
                        slot.config(bg=row_bg)
                    except Exception:
                        pass
            details_host = row.get("details_host")
            if details_host is not None:
                try:
                    details_host.config(
                        bg=row_bg,
                        highlightthickness=1,
                        highlightbackground=grid_border,
                        highlightcolor=grid_border,
                    )
                except Exception:
                    pass
            for button in (
                getattr(self, "btn_ingest_start_fresh", None) if row_key == "images" else None,
                getattr(self, "btn_ingest_import_plate_run", None) if row_key == "plate_run" else None,
                getattr(self, "btn_ingest_pick_plate_model", None) if row_key == "plate_model" else None,
                getattr(self, "btn_ingest_pick_char_model", None) if row_key == "char_model" else None,
                dict(getattr(self, "btn_ingest_clear_asset", {}) or {}).get(row_key),
            ):
                if button is not None:
                    self._style_project_start_badge_button(button, host_bg=row_bg)
            more_button = dict(getattr(self, "btn_ingest_asset_more", {}) or {}).get(row_key)
            if more_button is not None:
                self._style_project_start_badge_button(more_button, host_bg=row_bg)

    def _render_ingest_balance_chart(
        self,
        canvas: tk.Canvas | None,
        summary_label: tk.Label | None,
        package_balance: Counter | dict | None,
        package_images: int = 0,
        raw_package_images: int = 0,
    ) -> None:
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        field_bg = palette.get("field", "#1a1a1a")
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#b8b8b8")
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        accent_color = "#f29f05"
        top_color = "#ffbf47"

        balance = Counter(package_balance or {})
        total = sum(int(v) for v in balance.values())

        try:
            canvas.config(
                bg=field_bg,
                highlightbackground=panel_border,
                highlightcolor=panel_border,
            )
        except Exception:
            pass
        canvas.delete("all")

        if total <= 0:
            width = max(int(canvas.winfo_width() or 280), 280)
            canvas.create_text(
                width // 2,
                95,
                text="Brak danych E1 do pokazania.",
                fill=muted,
                justify=tk.CENTER,
                font=("Segoe UI", 9),
            )
            if summary_label is not None:
                try:
                    summary_label.config(
                        text=(
                            "Histogram pokazuje liczbę wystąpień każdego znaku w nazwach tablic zdjęć "
                            "należących do aktualnie wybranej puli E1."
                        )
                    )
                except Exception:
                    pass
            return

        width = max(int(canvas.winfo_width() or 560), 560)
        height = max(int(canvas.winfo_height() or 220), 220)
        left_margin = 26
        right_margin = 16
        top_margin = 18
        bottom_margin = 42
        plot_height = max(height - top_margin - bottom_margin, 80)
        plot_width = max(width - left_margin - right_margin, 180)
        max_value = max([int(balance.get(ch, 0)) for ch in CHAR_ALPHABET] + [1])
        cell_width = plot_width / float(len(CHAR_ALPHABET))
        top_chars = {
            ch for ch, value in sorted(
                ((ch, int(balance.get(ch, 0))) for ch in CHAR_ALPHABET),
                key=lambda entry: (-entry[1], entry[0])
            )[:4]
            if value > 0
        }

        base_y = top_margin + plot_height
        canvas.create_line(left_margin, base_y, width - right_margin, base_y, fill=panel_border)
        for grid_ratio, label in ((1.0, str(max_value)), (0.5, str(max(1, round(max_value / 2)))), (0.0, "0")):
            y = top_margin + int((1.0 - grid_ratio) * plot_height)
            canvas.create_line(left_margin, y, width - right_margin, y, fill=panel_border)
            canvas.create_text(4, y, text=label, anchor="w", fill=muted, font=("Segoe UI", 7))

        for idx, ch in enumerate(CHAR_ALPHABET):
            count = int(balance.get(ch, 0))
            x0 = left_margin + (idx * cell_width) + 1
            x1 = left_margin + ((idx + 1) * cell_width) - 1
            if x1 <= x0:
                x1 = x0 + 2
            bar_height = int(plot_height * (count / max_value)) if max_value > 0 else 0
            y0 = base_y - bar_height
            fill = top_color if ch in top_chars else accent_color
            if count > 0:
                canvas.create_rectangle(x0, y0, x1, base_y, fill=fill, width=0)
            else:
                canvas.create_line(x0, base_y - 1, x1, base_y - 1, fill=panel_border)
            canvas.create_text((x0 + x1) / 2, base_y + 10, text=ch, fill=fg, font=("Consolas", 7))
            if count > 0 and ch in top_chars:
                canvas.create_text((x0 + x1) / 2, max(y0 - 8, 8), text=str(count), fill=muted, font=("Segoe UI", 7))

        dominant = [
            (ch, int(balance.get(ch, 0)))
            for ch in CHAR_ALPHABET
            if int(balance.get(ch, 0)) > 0
        ]
        dominant.sort(key=lambda entry: (-entry[1], entry[0]))
        dominant_text = ", ".join(
            f"{ch}:{count} ({(count / total) * 100:.1f}%)"
            for ch, count in dominant[:6]
        ) or "brak"
        missing = [ch for ch in CHAR_ALPHABET if int(balance.get(ch, 0)) == 0]
        missing_text = ", ".join(missing[:10]) if missing else "brak"
        summary = (
            "Wysokość słupka oznacza liczbę wystąpień danego znaku w nazwach tablic zdjęć należących do "
            "aktualnie wybranej puli E1.\n"
            f"Wybrana pula zawiera teraz {int(raw_package_images or package_images)} zdjęć"
            + (
                f", z czego {int(package_images or 0)} weszło do planu E1"
                if int(raw_package_images or package_images) != int(package_images or 0)
                else ""
            )
            + f", oraz {total} znaków GT w planie. "
            + f"Najczęstsze znaki: {dominant_text}.\n"
            + f"Brakujące znaki w tej puli: {missing_text}."
        )
        if summary_label is not None:
            try:
                summary_label.config(text=summary)
            except Exception:
                pass

    def _show_project_start_images_analysis_dialog(self) -> None:
        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#b8b8b8")
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        accent = palette.get("accent", "#4fc1ff")

        master_pool = CAMPAIGN.get_master_pool_dir()
        master_pool_exists = bool(master_pool and master_pool.exists() and master_pool.is_dir())
        master_pool_images = self._count_images_in_dir(master_pool, recursive=True) if master_pool_exists else 0
        step1_context = self._get_step1_manifest_context(self._load_ingest_manifest_cached())
        source_total = int(step1_context.get("source_total", 0) or 0)
        project_overlap = int(step1_context.get("project_overlap_filenames", 0) or 0)
        new_to_project = int(step1_context.get("new_to_project_count", 0) or 0)
        approved_overlap = int(step1_context.get("skipped_duplicate_approved", 0) or 0)
        selected_total = int(
            step1_context.get("current_iteration_package_count", 0)
            or self.current_ingest_plan.get("selected_total", 0)
            or 0
        )
        if master_pool_exists:
            source_names = self._collect_image_names_in_dir(master_pool, recursive=True)
            previous_project_names = self._collect_previous_project_image_names_for_step1()
            if source_names:
                project_overlap = int(len(source_names & previous_project_names))
                new_to_project = int(max(0, len(source_names) - project_overlap))
                source_total = int(len(source_names))
                master_pool_images = int(len(source_names))
        source_diverged = bool(
            master_pool_images > 0
            and selected_total > 0
            and master_pool_images != selected_total
        )
        selected_balance = Counter(self.current_ingest_plan.get("selected_balance", {}) or {})
        current_balance = Counter((self.last_ingest_snapshot or {}).get("char_balance", {}) or {})

        dialog = tk.Toplevel(self.frame)
        self.app.style_dialog_window(dialog, title="Analiza obrazów iteracji", geometry="820x660", parent=self.frame)

        build_surface = getattr(self.app, "_build_themed_dialog_surface", None)
        if callable(build_surface):
            body = build_surface(dialog, tone="info")
        else:
            body = tk.Frame(dialog, bg=panel_bg, bd=0, highlightthickness=0)
            body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text="Analiza obrazów iteracji",
            font=("Segoe UI", 11, "bold"),
            fg=fg,
            bg=panel_bg,
            anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(14, 4))

        tk.Label(
            body,
            text=(
                "Tutaj sprawdzisz bieżącą pulę E1: źródło obrazów, liczebność iteracji i histogram znaków, "
                "który pokazuje rozkład tablic w wybranym katalogu zdjęć."
            ),
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
            fg=muted,
            bg=panel_bg,
        ).pack(fill=tk.X, padx=14, pady=(0, 10))

        summary_shell = tk.Frame(body, bg=panel_bg)
        summary_shell.pack(fill=tk.X, padx=14, pady=(0, 10))
        summary_shell.grid_columnconfigure(1, weight=1)

        summary_rows = [
            ("Katalog źródłowy projektu", self._format_project_start_asset_source(master_pool)),
            ("Obrazy w katalogu iteracji", str(selected_total)),
            ("Faktycznie nowe dla projektu", str(new_to_project)),
            ("Już wcześniej w projekcie", str(project_overlap)),
        ]
        if source_diverged:
            summary_rows.insert(1, ("Obrazy w obecnym katalogu źródłowym", str(master_pool_images)))
        if approved_overlap > 0:
            summary_rows.append(("W tym już w pudełku zatwierdzonych", str(approved_overlap)))
        if source_total > 0 and source_total != selected_total:
            summary_rows.append(("Historyczny zapis źródła zdjęć", str(source_total)))

        for row_idx, (label_text, value_text) in enumerate(summary_rows):
            tk.Label(
                summary_shell,
                text=f"{label_text}:",
                font=("Segoe UI", 9, "bold"),
                fg=fg,
                bg=panel_bg,
                anchor="w",
            ).grid(row=row_idx, column=0, sticky="w", padx=(0, 10), pady=1)
            tk.Label(
                summary_shell,
                text=value_text,
                fg=accent,
                bg=panel_bg,
                justify=tk.LEFT,
                anchor="w",
                wraplength=560,
            ).grid(row=row_idx, column=1, sticky="ew", pady=1)

        tk.Label(
            body,
            text="Histogram znaków w aktualnym planie E1",
            font=("Segoe UI", 9, "bold"),
            fg=fg,
            bg=panel_bg,
            anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(2, 4))

        chart_canvas = tk.Canvas(
            body,
            height=240,
            bg=palette.get("field", "#1a1a1a"),
            bd=0,
            highlightthickness=1,
            highlightbackground=panel_border,
            highlightcolor=panel_border,
        )
        chart_canvas.pack(fill=tk.X, padx=14)

        chart_summary_lbl = tk.Label(
            body,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
            fg=muted,
            bg=panel_bg,
        )
        chart_summary_lbl.pack(fill=tk.X, padx=14, pady=(8, 0))

        top_chars_text = self._format_histogram_compact(selected_balance, limit=8) if selected_balance else "brak danych"
        project_chars_text = self._format_histogram_compact(current_balance, limit=8) if current_balance else "brak danych"
        tk.Label(
            body,
            text=(
                f"Najczęstsze znaki w tej iteracji: {top_chars_text}\n"
                f"Przegląd znaków w dotychczas zatwierdzonym zbiorze projektu: {project_chars_text}"
            ),
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
            fg=muted,
            bg=panel_bg,
        ).pack(fill=tk.X, padx=14, pady=(8, 0))

        if source_diverged:
            tk.Label(
                body,
                text=(
                    f"Uwaga: katalog zdjęć iteracji ma {selected_total} zdjęć, ale obecny katalog źródłowy projektu ma teraz {master_pool_images}. "
                    "Dalsza praca tej iteracji opiera się na katalogu zdjęć iteracji."
                ),
                justify=tk.LEFT,
                anchor="w",
                wraplength=760,
                fg=muted,
                bg=panel_bg,
            ).pack(fill=tk.X, padx=14, pady=(8, 0))

        tk.Label(
            body,
            text=(
                "Obrazy iteracji są wymagane. Pozostałe zasoby E1 są opcjonalne: anotacje tablic "
                "mogą przenieść do projektu wcześniej wykonaną ręczną pracę, a modele wskazują punkt startowy, "
                "który chcesz dalej wykorzystywać i dotrenowywać w kolejnych iteracjach."
            ),
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
            fg=muted,
            bg=panel_bg,
        ).pack(fill=tk.X, padx=14, pady=(10, 0))

        button_row = tk.Frame(body, bg=panel_bg)
        button_row.pack(fill=tk.X, padx=14, pady=(14, 14))
        ttk.Button(button_row, text="Zamknij", command=dialog.destroy, width=14).pack(side=tk.RIGHT)

        def _refresh_modal_chart(_event=None):
            if not dialog.winfo_exists():
                return
            self._render_ingest_balance_chart(
                chart_canvas,
                chart_summary_lbl,
                selected_balance,
                package_images=selected_total,
                raw_package_images=max(source_total, selected_total, master_pool_images),
            )

        chart_canvas.bind("<Configure>", _refresh_modal_chart)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        _refresh_modal_chart()

        fit_dialog = getattr(self.app, "_fit_dialog_to_content", None)
        if callable(fit_dialog):
            fit_dialog(dialog, parent=self.frame, min_width=820, min_height=660)

    def _get_project_start_effective_images_source(self) -> dict:
        master_pool = CAMPAIGN.get_master_pool_dir()
        master_pool_exists = bool(master_pool and master_pool.exists() and master_pool.is_dir())
        master_pool_count = self._count_images_in_dir(master_pool, recursive=True) if master_pool_exists else 0

        try:
            iteration_images_dir = CAMPAIGN.get_iteration_raw_dir()
        except Exception:
            iteration_images_dir = None
        try:
            logical_iteration_dir = CAMPAIGN.get_iteration_image_source_dir()
        except Exception:
            logical_iteration_dir = iteration_images_dir
        try:
            visible_iteration_dir = Path(logical_iteration_dir) if logical_iteration_dir is not None else None
        except Exception:
            visible_iteration_dir = Path(iteration_images_dir) if iteration_images_dir is not None else None
        iteration_images_exists = bool(
            visible_iteration_dir
            and visible_iteration_dir.exists()
            and visible_iteration_dir.is_dir()
        )
        try:
            iteration_images_count = int(CAMPAIGN.get_iteration_image_count() or 0)
        except Exception:
            iteration_images_count = (
                self._count_images_in_dir(visible_iteration_dir, recursive=True)
                if iteration_images_exists
                else 0
            )

        effective_images_dir = (
            Path(logical_iteration_dir)
            if iteration_images_count > 0 and logical_iteration_dir is not None
            else master_pool
        )
        effective_images_count = iteration_images_count if iteration_images_count > 0 else master_pool_count
        effective_images_exists = bool(
            effective_images_dir
            and Path(effective_images_dir).exists()
            and Path(effective_images_dir).is_dir()
        )

        return {
            "master_dir": master_pool,
            "master_count": int(master_pool_count or 0),
            "master_exists": bool(master_pool_exists),
            "iteration_dir": visible_iteration_dir,
            "physical_iteration_dir": Path(iteration_images_dir) if iteration_images_dir is not None else None,
            "iteration_count": int(iteration_images_count or 0),
            "iteration_exists": bool(iteration_images_exists),
            "effective_dir": effective_images_dir,
            "effective_count": int(effective_images_count or 0),
            "effective_exists": bool(effective_images_exists),
        }

    def _scan_project_start_normalized_image_names(self, images_dir: Path | None) -> set[str]:
        if images_dir is None:
            return set()

        try:
            safe_dir = Path(images_dir)
        except Exception:
            return set()

        image_names: set[str] = set()
        try:
            if not safe_dir.exists() or not safe_dir.is_dir():
                return set()
        except Exception:
            return set()

        try:
            for image_path in safe_dir.rglob("*"):
                if not image_path.is_file():
                    continue
                if image_path.suffix.lower() not in CONFIG.IMAGE_EXTENSIONS:
                    continue
                normalized = CAMPAIGN._normalize_image_set_name(image_path.name)
                if normalized:
                    image_names.add(normalized)
        except Exception:
            return set()
        return image_names

    def _collect_project_start_image_paths_by_normalized_name(self, images_dir: Path | None) -> dict[str, Path]:
        if images_dir is None:
            return {}

        try:
            safe_dir = Path(images_dir)
        except Exception:
            return {}

        try:
            if not safe_dir.exists() or not safe_dir.is_dir():
                return {}
        except Exception:
            return {}

        image_paths: dict[str, Path] = {}
        try:
            for image_path in safe_dir.rglob("*"):
                if not image_path.is_file() or image_path.suffix.lower() not in CONFIG.IMAGE_EXTENSIONS:
                    continue
                normalized = CAMPAIGN._normalize_image_set_name(image_path.name)
                if normalized and normalized not in image_paths:
                    image_paths[normalized] = image_path
        except Exception:
            return dict(image_paths)
        return image_paths

    def _maybe_extend_project_start_images_from_annotation_package(
        self,
        *,
        current_images_dir: Path | None,
        package_images_dir: Path | None,
        compatibility: dict,
    ) -> Path | None:
        if current_images_dir is None or package_images_dir is None:
            return None

        missing_normalized = {
            str(name or "").strip().lower()
            for name in list((compatibility or {}).get("missing_normalized_names") or [])
            if str(name or "").strip()
        }
        if not missing_normalized:
            return None

        current_paths = self._collect_project_start_image_paths_by_normalized_name(current_images_dir)
        package_paths = self._collect_project_start_image_paths_by_normalized_name(package_images_dir)
        addable_names = sorted(name for name in missing_normalized if name in package_paths and name not in current_paths)
        if not addable_names:
            return None

        preview_names = "\n".join(Path(package_paths[name]).name for name in addable_names[:6])
        extra_count = max(0, len(addable_names) - 6)
        suffix = f"\n... i jeszcze {extra_count} zdjęć." if extra_count else ""
        should_extend = self.app.themed_confirm(
            "Import anotacji tablic",
            (
                "Wybrany pakiet anotacji zawiera zdjęcia, których nie ma w aktualnym katalogu zdjęć E1.\n\n"
                f"Możliwe do dołączenia z pakietu: {len(addable_names)}\n"
                f"Przykłady:\n{preview_names}{suffix}\n\n"
                "Program nie zmieni oryginalnego katalogu zdjęć. Utworzy roboczy katalog scalony w projekcie: "
                "obecne zdjęcia + brakujące zdjęcia z pakietu, bez kopiowania duplikatów nazw.\n\n"
                "Czy dołączyć brakujące zdjęcia i ponowić walidację importu?"
            ),
            parent=self.frame,
            confirm_label="Dołącz zdjęcia",
            cancel_label="Importuj tylko zgodne",
            tone="info",
        )
        if not should_extend:
            return None

        raw_root = CAMPAIGN.get_dir("raw")
        if raw_root is None:
            self.app.themed_error(
                "Import anotacji tablic",
                "Nie udało się ustalić katalogu projektu dla scalonego źródła zdjęć.",
                parent=self.frame,
            )
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        merged_dir = Path(raw_root) / "_imported_annotation_images" / f"import_anotacji_tablic_{timestamp}"
        try:
            merged_dir.mkdir(parents=True, exist_ok=False)
            copied_names: set[str] = set()
            for normalized, source_path in sorted(current_paths.items()):
                if normalized in copied_names:
                    continue
                target_path = merged_dir / Path(source_path).name
                shutil.copy2(source_path, target_path)
                copied_names.add(normalized)
            for normalized in addable_names:
                if normalized in copied_names:
                    continue
                source_path = package_paths.get(normalized)
                if source_path is None:
                    continue
                target_path = merged_dir / Path(source_path).name
                shutil.copy2(source_path, target_path)
                copied_names.add(normalized)
        except Exception as e:
            try:
                shutil.rmtree(merged_dir)
            except Exception:
                pass
            self.app.themed_error(
                "Import anotacji tablic",
                f"Nie udało się utworzyć roboczego katalogu scalonego:\n{e}",
                parent=self.frame,
            )
            return None

        if not CAMPAIGN.set_master_pool_dir(merged_dir):
            self.app.themed_error(
                "Import anotacji tablic",
                "Roboczy katalog scalony został utworzony, ale nie udało się ustawić go jako katalogu zdjęć E1.",
                parent=self.frame,
            )
            return None

        self.current_ingest_plan = {}
        self._existing_iteration_ingest_plan_signature = None
        try:
            self.app.update_status(
                f"Dołączono {len(addable_names)} zdjęć z pakietu anotacji do roboczego katalogu E1.",
                "info",
            )
        except Exception:
            pass
        return merged_dir

    def _get_project_start_approved_normalized_image_names(self) -> set[str]:
        approved_names: set[str] = set()

        try:
            registry = CAMPAIGN.get_used_image_registry() or {}
            for name in list(registry.get("filenames") or []):
                normalized = CAMPAIGN._normalize_image_set_name(name)
                if normalized:
                    approved_names.add(normalized)
        except Exception:
            pass

        try:
            for entry in list(CAMPAIGN.list_plate_approved_entries() or []):
                if not isinstance(entry, dict):
                    continue
                for raw_name in (
                    entry.get("image_name", ""),
                    Path(str(entry.get("source_image_path", "") or "")).name if str(entry.get("source_image_path", "") or "").strip() else "",
                ):
                    normalized = CAMPAIGN._normalize_image_set_name(raw_name)
                    if normalized:
                        approved_names.add(normalized)
        except Exception:
            pass

        return approved_names

    def _get_project_start_adoptable_normalized_image_names(self, images_dir: Path | None) -> set[str]:
        all_names = self._scan_project_start_normalized_image_names(images_dir)
        if not all_names:
            all_names = self._get_project_start_normalized_image_names(images_dir)
        approved_names = self._get_project_start_approved_normalized_image_names()
        return set(all_names) - set(approved_names)

    def _show_project_start_asset_details(self, row_key: str) -> None:
        row_key = str(row_key or "").strip()
        if not row_key:
            return

        image_source = self._get_project_start_effective_images_source()
        master_pool = CAMPAIGN.get_master_pool_dir()
        master_pool_exists = bool(master_pool and master_pool.exists() and master_pool.is_dir())
        master_pool_images = self._count_images_in_dir(master_pool, recursive=True) if master_pool_exists else 0
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()

        title = "Szczegóły zasobu"
        body_lines: list[str] = []

        if row_key == "images":
            self._show_project_start_images_analysis_dialog()
            return
        elif row_key == "plate_run":
            title = "Anotacje tablic"
            plate_source_info = self._get_project_start_plate_source_info()
            plate_run_path = str(plate_source_info.get("run_path") or "").strip()
            plate_xml_path = str(plate_source_info.get("xml_path") or "").strip()
            body_lines.append(f"Źródło: {self._format_project_start_asset_source(plate_xml_path or plate_run_path)}")
            if plate_run_path:
                try:
                    plate_run_dir = Path(plate_run_path)
                except Exception:
                    plate_run_dir = None
                effective_images_dir = image_source.get("effective_dir")
                effective_images_count = int(image_source.get("effective_count", 0) or 0)
                compatibility = (
                    self._check_project_start_run_compatibility(plate_run_dir, effective_images_dir, adoptable_only=True)
                    if plate_run_dir is not None and effective_images_dir is not None and effective_images_count > 0
                    else {}
                )
                if compatibility.get("checked"):
                    approved_overlap = int(compatibility.get("approved_overlap", 0) or 0)
                    incomplete_count = int(compatibility.get("incomplete", 0) or 0)
                    body_lines.extend(
                        [
                            f"Porównuję z roboczą pulą zdjęć E1: {self._format_project_start_asset_source(effective_images_dir)}",
                            self._format_project_start_annotation_adoption_summary(compatibility),
                        ]
                    )
                    if approved_overlap > 0:
                        body_lines.append(f"Pominięte, bo już zatwierdzone w projekcie: {approved_overlap}")
                    if incomplete_count > 0:
                        body_lines.append(
                            f"Pominięte, bo anotacje nie obejmują wszystkich tablic zapisanych w nazwie pliku: {incomplete_count}"
                        )
                    missing_preview = [str(name) for name in (compatibility.get("missing_names") or []) if str(name).strip()]
                    if missing_preview:
                        body_lines.append("")
                        body_lines.append("Przykłady brakujących plików:")
                        body_lines.extend(f"- {name}" for name in missing_preview[:5])
                else:
                    body_lines.append("Walidacja zgodności pojawi się po wskazaniu obrazów iteracji.")
            else:
                body_lines.append("Plik annotations.xml nie został jeszcze wskazany.")
            body_lines.append("")
            body_lines.append(
                "Ten zasób ma sens wtedy, gdy dla części albo całości wybranego katalogu zdjęć E1 istnieją już dobre, "
                "ręczne anotacje tablic. Program porównuje nazwy obrazów z pliku annotations.xml z obrazami "
                "w roboczej puli E1 i pozwala przyjąć tylko zgodne anotacje dla zdjęć, które nie są jeszcze zatwierdzone."
            )
            body_lines.append("")
            body_lines.append(
                "Po adopcji E2 może otworzyć Z2 na gotowych tablicach zamiast startować od zera. "
                "Jeśli zgodnych anotacji jest wystarczająco dużo, tor znaków może szybciej przejść do Z3."
            )
        elif row_key in {"plate_model", "char_model"}:
            is_plate = row_key == "plate_model"
            title = "Model tablic" if is_plate else "Model znaków"
            model_path = plate_model_path if is_plate else char_model_path
            source_text = self._format_project_start_asset_source(model_path)
            body_lines.append(f"Źródło: {source_text}")
            if model_path:
                identity = self._get_model_identity_label(model_path)
                created = self._format_model_created_label(model_path)
                if identity:
                    body_lines.append(f"Typ modelu: {identity}")
                if created and created != "Utworzono: -":
                    body_lines.append(created)
                try:
                    is_valid, validation_message = self._validate_project_model_selection("plate" if is_plate else "char", Path(model_path))
                except Exception:
                    is_valid, validation_message = False, "Nie udało się zweryfikować modelu."
                body_lines.append("")
                body_lines.append("Walidacja: " + ("OK" if is_valid else validation_message))
            else:
                body_lines.append("Model nie został jeszcze wskazany.")
            body_lines.append("")
            if is_plate:
                body_lines.append(
                    "Model tablic w E1 jest opcjonalnym zasobem startowym projektu. Wybierz go wtedy, "
                    "gdy chcesz używać go do autoanotacji tablic w Z2 i traktować jako model, który "
                    "zamierzasz dalej poprawiać treningiem w kolejnych iteracjach."
                )
                body_lines.append("")
                body_lines.append(
                    "Jeśli później w Z2 wskażesz inny model tylko dla bieżącego runu, "
                    "nie nadpisze to automatycznie modelu projektu."
                )
            else:
                body_lines.append(
                    "Model znaków w E1 jest opcjonalnym zasobem startowym projektu. Wybierz go wtedy, "
                    "gdy chcesz używać go w Z3 do detekcji znaków i traktować jako model, który "
                    "zamierzasz dalej dotrenowywać na kolejnych datasetach znaków."
                )
                body_lines.append("")
                body_lines.append(
                    "Ten model pozostaje też dostępny później jako projektowy punkt startowy pracy nad znakami."
                )
        else:
            body_lines.append("Brak dodatkowych szczegółów dla tego zasobu.")

        message = "\n".join(str(line or "").strip() for line in body_lines if str(line or "").strip())
        self.app.themed_info(title, message or "Brak danych.", parent=self.frame, tone="info")

    @staticmethod
    def _count_project_start_plate_detections(annotation_tab, ann) -> int:
        getter = getattr(annotation_tab, "_get_plate_detections", None)
        if callable(getter):
            try:
                return int(len(list(getter(ann) or [])))
            except Exception:
                pass

        plate_labels = {str(label or "").strip().lower() for label in getattr(CONFIG, "PLATE_LABELS", [])}
        count = 0
        for det in list(getattr(ann, "detections", []) or []):
            label = str(getattr(det, "label", "") or "").strip().lower()
            if label and label in plate_labels:
                count += 1
        return int(count)

    @staticmethod
    def _get_project_start_filename_plate_texts(filename: str) -> list[str]:
        try:
            planner = CampaignIngestPlanner()
            return [
                str(text or "").strip().upper()
                for text in planner.extract_true_texts_from_filename(str(filename or ""))
                if str(text or "").strip()
            ]
        except Exception:
            return []

    def _project_start_annotation_covers_filename_plates(self, filename: str, plate_count: int) -> tuple[bool, int]:
        expected_texts = self._get_project_start_filename_plate_texts(filename)
        expected_count = int(len(expected_texts) or 0)
        if expected_count <= 0:
            return True, 0
        return bool(int(plate_count or 0) >= expected_count), expected_count

    @staticmethod
    def _format_project_start_annotation_adoption_summary(compatibility: dict | None) -> str:
        payload = dict(compatibility or {})
        matched = int(payload.get("matched", 0) or 0)
        plates = int(payload.get("matched_plate_count", 0) or 0)
        return (
            f"Zamierzasz importować {matched} kompatybilnych anotacji dla niezatwierdzonych obrazów. "
            f"Zostaną one zastosowane do {matched} zgodnych po nazwie niezatwierdzonych obrazów, "
            f"co obejmie {plates} tablic."
        )

    def _check_project_start_run_compatibility(
        self,
        run_dir: Path | None,
        expected_images_dir: Path | None,
        *,
        adoptable_only: bool = False,
    ) -> dict:
        result = {
            "ok": False,
            "checked": False,
            "total": 0,
            "matched": 0,
            "missing": 0,
            "missing_names": [],
            "approved_overlap": 0,
            "approved_overlap_names": [],
            "adoptable_image_count": 0,
            "matched_plate_count": 0,
            "incomplete": 0,
            "incomplete_names": [],
            "matched_normalized_names": [],
            "missing_normalized_names": [],
            "images_dir": None,
            "package_image_set_token": "",
            "package_image_count": 0,
            "xml_image_set_token": "",
            "xml_image_count": 0,
            "plate_images": 0,
            "plate_count": 0,
            "token_match": False,
        }

        if run_dir is None or expected_images_dir is None:
            return result

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return result

        try:
            safe_run_dir = annotation_tab._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
        except Exception:
            safe_run_dir = None

        if safe_run_dir is None:
            try:
                external_run_dir = Path(run_dir)
                if external_run_dir.exists() and external_run_dir.is_dir() and (external_run_dir / "annotations.xml").exists():
                    safe_run_dir = external_run_dir
                else:
                    return result
            except Exception:
                return result

        try:
            images_dir = Path(expected_images_dir)
        except Exception:
            return result

        try:
            if not images_dir.exists() or not images_dir.is_dir():
                return result
        except Exception:
            return result

        if adoptable_only:
            package_normalized_names = self._scan_project_start_normalized_image_names(images_dir)
            if not package_normalized_names:
                package_normalized_names = self._get_project_start_normalized_image_names(images_dir)
            package_image_count = len(package_normalized_names)
            package_image_set_token = CAMPAIGN.build_image_name_set_token(package_normalized_names, images_dir=images_dir)
        else:
            package_image_set_token, package_image_count = self._build_project_start_image_set_token(
                images_dir=images_dir,
                manifest=self._load_ingest_manifest_cached(),
            )
        result["package_image_set_token"] = str(package_image_set_token or "").strip()
        result["package_image_count"] = int(package_image_count or 0)

        try:
            annotations = annotation_tab._parse_cvat_preview_annotations(safe_run_dir / "annotations.xml")
        except Exception:
            return result

        plate_annotations = []
        plate_count = 0
        plate_count_by_normalized: dict[str, int] = {}
        incomplete_name_by_normalized: dict[str, str] = {}
        for ann in annotations:
            ann_plate_count = self._count_project_start_plate_detections(annotation_tab, ann)
            if ann_plate_count <= 0:
                continue
            filename = str(getattr(ann, "filename", "") or "").strip()
            if not filename:
                continue
            normalized_name = CAMPAIGN._normalize_image_set_name(filename)
            if not normalized_name:
                continue
            covers_filename, expected_plate_count = self._project_start_annotation_covers_filename_plates(
                filename,
                ann_plate_count,
            )
            if not covers_filename:
                try:
                    incomplete_name_by_normalized[normalized_name] = (
                        f"{Path(filename).name} ({int(ann_plate_count)} z {int(expected_plate_count)} tablic z nazwy)"
                    )
                except Exception:
                    incomplete_name_by_normalized[normalized_name] = str(filename)
            plate_annotations.append(ann)
            plate_count += int(ann_plate_count)
            plate_count_by_normalized[normalized_name] = (
                int(plate_count_by_normalized.get(normalized_name, 0) or 0)
                + int(ann_plate_count)
            )

        xml_image_names = [
            str(getattr(ann, "filename", "") or "").strip()
            for ann in plate_annotations
            if str(getattr(ann, "filename", "") or "").strip()
        ]
        xml_name_by_normalized: dict[str, str] = {}
        for name in xml_image_names:
            normalized_name = CAMPAIGN._normalize_image_set_name(name)
            if normalized_name and normalized_name not in xml_name_by_normalized:
                try:
                    xml_name_by_normalized[normalized_name] = Path(name).name
                except Exception:
                    xml_name_by_normalized[normalized_name] = name
        xml_normalized_names = set(xml_name_by_normalized.keys())
        complete_xml_normalized_names = xml_normalized_names - set(incomplete_name_by_normalized.keys())

        xml_image_set_token = CAMPAIGN.build_image_name_set_token(xml_image_names)
        xml_image_count = len(xml_normalized_names)
        result["xml_image_set_token"] = str(xml_image_set_token or "").strip()
        result["xml_image_count"] = int(xml_image_count or 0)
        result["plate_images"] = int(xml_image_count or 0)
        result["plate_count"] = int(plate_count or 0)
        result["token_match"] = bool(
            package_image_set_token
            and xml_image_set_token
            and package_image_set_token == xml_image_set_token
        )

        if not plate_annotations:
            result["checked"] = True
            result["images_dir"] = images_dir
            return result

        if not adoptable_only:
            package_image_names = self._collect_project_start_image_names(
                images_dir=images_dir,
                manifest=self._load_ingest_manifest_cached(),
            )
            package_normalized_names = {
                CAMPAIGN._normalize_image_set_name(name)
                for name in package_image_names
                if CAMPAIGN._normalize_image_set_name(name)
            }

        approved_normalized_names = (
            self._get_project_start_approved_normalized_image_names()
            if adoptable_only
            else set()
        )
        adoption_candidate_names = set(package_normalized_names) - set(approved_normalized_names)
        matched_normalized_names = complete_xml_normalized_names & adoption_candidate_names
        missing_normalized_names = sorted(xml_normalized_names - matched_normalized_names)
        approved_overlap_names = sorted(xml_normalized_names & set(approved_normalized_names) & set(package_normalized_names))
        missing_names = [
            xml_name_by_normalized.get(name, name)
            for name in missing_normalized_names
            if name not in incomplete_name_by_normalized
            and name not in set(approved_overlap_names)
        ]
        approved_overlap_preview = [
            xml_name_by_normalized.get(name, name)
            for name in approved_overlap_names
        ]
        incomplete_names = [
            incomplete_name_by_normalized.get(name, xml_name_by_normalized.get(name, name))
            for name in sorted(set(incomplete_name_by_normalized.keys()) & xml_normalized_names)
        ]
        matched_plate_count = sum(
            int(plate_count_by_normalized.get(name, 0) or 0)
            for name in set(matched_normalized_names)
        )

        result.update(
            checked=True,
            total=len(xml_normalized_names),
            matched=len(matched_normalized_names),
            missing=len(missing_names),
            missing_names=list(missing_names[:5]),
            approved_overlap=len(approved_overlap_names),
            approved_overlap_names=list(approved_overlap_preview[:5]),
            adoptable_image_count=len(adoption_candidate_names),
            matched_plate_count=int(matched_plate_count or 0),
            incomplete=len(incomplete_names),
            incomplete_names=list(incomplete_names[:5]),
            matched_normalized_names=sorted(matched_normalized_names),
            missing_normalized_names=sorted(missing_normalized_names),
            images_dir=images_dir,
        )
        result["ok"] = bool(xml_normalized_names and not missing_normalized_names)
        return result

    def _get_project_start_normalized_image_names(self, images_dir: Path | None) -> set[str]:
        if images_dir is None:
            return set()

        try:
            manifest = CAMPAIGN.load_ingest_manifest() or {}
        except Exception:
            manifest = {}
        if isinstance(manifest, dict):
            selected_manifest_names = {
                CAMPAIGN._normalize_image_set_name(str(item.get("name", "") or "").strip())
                for item in list(manifest.get("selected_images") or [])
                if isinstance(item, dict) and str(item.get("name", "") or "").strip()
            }
            selected_manifest_names = {name for name in selected_manifest_names if name}
            if selected_manifest_names:
                try:
                    manifest_source_dir = CAMPAIGN.get_iteration_image_source_dir()
                except Exception:
                    manifest_source_dir = None
                candidate_dirs = [
                    manifest_source_dir,
                    manifest.get("source_dir"),
                    manifest.get("master_pool_dir"),
                    manifest.get("target_dir"),
                ]
                for candidate_dir in candidate_dirs:
                    if candidate_dir and self._campaign_paths_equivalent(images_dir, candidate_dir):
                        return selected_manifest_names

        image_names: list[str] = []
        try:
            for image_path in Path(images_dir).rglob("*"):
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS:
                    image_names.append(str(image_path.name or "").strip())
        except Exception:
            image_names = []
        return {
            CAMPAIGN._normalize_image_set_name(name)
            for name in image_names
            if CAMPAIGN._normalize_image_set_name(name)
        }

    def _summarize_project_start_xml_match(self, xml_path: Path | None, images_dir: Path | None) -> dict:
        summary = {
            "checked": False,
            "total": 0,
            "matched": 0,
            "missing": 0,
            "missing_names": [],
            "package_image_count": 0,
            "plate_images": 0,
            "plate_count": 0,
        }
        if xml_path is None or images_dir is None:
            return summary

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return summary

        try:
            annotations = annotation_tab._parse_cvat_preview_annotations(Path(xml_path))
        except Exception:
            return summary

        xml_name_by_normalized: dict[str, str] = {}
        plate_count = 0
        for ann in annotations:
            ann_plate_count = self._count_project_start_plate_detections(annotation_tab, ann)
            if ann_plate_count <= 0:
                continue
            filename = str(getattr(ann, "filename", "") or "").strip()
            normalized_name = CAMPAIGN._normalize_image_set_name(filename)
            if normalized_name and normalized_name not in xml_name_by_normalized:
                xml_name_by_normalized[normalized_name] = Path(filename).name
            plate_count += int(ann_plate_count)

        package_names = self._get_project_start_normalized_image_names(images_dir)
        missing_names = sorted(set(xml_name_by_normalized.keys()) - package_names)
        summary.update(
            checked=True,
            total=len(xml_name_by_normalized),
            matched=max(0, len(xml_name_by_normalized) - len(missing_names)),
            missing=len(missing_names),
            missing_names=[xml_name_by_normalized.get(name, name) for name in missing_names[:5]],
            package_image_count=len(package_names),
            plate_images=len(xml_name_by_normalized),
            plate_count=int(plate_count or 0),
        )
        return summary

    def _import_project_start_plate_run(self) -> None:
        if not CAMPAIGN.get_active_project_name():
            return

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            self.app.themed_error(
                "Brak Z2",
                "Nie udało się odnalezc zakładki Z2 potrzebnej do importu gotowych anotacji tablic.",
                parent=self.frame,
            )
            return

        self._set_project_start_mode("assets", refresh=False)

        try:
            initial_dir = self._get_project_start_asset_initial_dir("plate_run")
        except Exception:
            initial_dir = Path(CONFIG.get_auto_annotations_dir("plate"))

        selected_xml = filedialog.askopenfilename(
            initialdir=str(initial_dir),
            title="Wskaż plik annotations.xml z gotowymi anotacjami tablic",
            filetypes=[
                ("Plik anotacji CVAT", "annotations.xml"),
                ("Pliki XML", "*.xml"),
                ("Wszystkie pliki", "*.*"),
            ],
        )
        if not selected_xml:
            return

        try:
            selected_xml_path = Path(selected_xml)
        except Exception:
            self.app.themed_error("Błąd importu", "Nieprawidłowa ścieżka pliku annotations.xml.", parent=self.frame)
            return

        if str(selected_xml_path.name or "").strip().lower() != "annotations.xml":
            self.app.themed_error(
                "Błąd importu",
                "Wskaż właściwy plik annotations.xml z katalogu runu anotacji tablic.",
                parent=self.frame,
            )
            return

        try:
            if not selected_xml_path.exists() or not selected_xml_path.is_file():
                raise FileNotFoundError
        except Exception:
            self.app.themed_error(
                "Błąd importu",
                "Nie znaleziono wskazanego pliku annotations.xml.",
                parent=self.frame,
            )
            return
        selected_run_dir = selected_xml_path.parent
        package_images_dir = selected_run_dir / "images"
        try:
            if (
                not package_images_dir.exists()
                or not package_images_dir.is_dir()
                or self._count_images_in_dir(package_images_dir, recursive=True) <= 0
            ):
                package_images_dir = None
        except Exception:
            package_images_dir = None

        image_source = self._get_project_start_effective_images_source()
        project_images_dir = (
            image_source.get("effective_dir")
            or CAMPAIGN.get_master_pool_dir()
            or CAMPAIGN.get_iteration_image_source_dir()
            or CAMPAIGN.get_iteration_raw_dir()
        )

        try:
            safe_run_dir = annotation_tab._resolve_safe_annotation_run_dir(selected_run_dir, require_xml=True)
        except Exception:
            safe_run_dir = None

        final_run_dir = safe_run_dir
        selected_images_dir = Path(project_images_dir) if project_images_dir is not None else None
        if selected_images_dir is not None:
            try:
                if not selected_images_dir.exists() or not selected_images_dir.is_dir() or self._count_images_in_dir(selected_images_dir, recursive=True) <= 0:
                    selected_images_dir = None
            except Exception:
                selected_images_dir = None
        if selected_images_dir is None and package_images_dir is not None:
            selected_images_dir = package_images_dir
        selected_image_names = self._get_project_start_adoptable_normalized_image_names(selected_images_dir)
        original_xml_match = self._summarize_project_start_xml_match(selected_xml_path, selected_images_dir)

        if selected_images_dir is not None and package_images_dir is not None:
            pre_import_compatibility = self._check_project_start_run_compatibility(
                selected_run_dir,
                selected_images_dir,
                adoptable_only=True,
            )
            if pre_import_compatibility.get("checked") and not pre_import_compatibility.get("ok"):
                extended_images_dir = self._maybe_extend_project_start_images_from_annotation_package(
                    current_images_dir=selected_images_dir,
                    package_images_dir=package_images_dir,
                    compatibility=pre_import_compatibility,
                )
                if extended_images_dir is not None:
                    selected_images_dir = extended_images_dir
                    selected_image_names = self._get_project_start_adoptable_normalized_image_names(selected_images_dir)
                    original_xml_match = self._summarize_project_start_xml_match(selected_xml_path, selected_images_dir)

        if selected_images_dir is not None and not selected_image_names:
            self.app.themed_error(
                "Import anotacji tablic",
                (
                    "W wybranym katalogu nie ma zdjęć roboczych do adopcji anotacji.\n\n"
                    "Wszystkie rozpoznane zdjęcia z tej puli są już zatwierdzone w projekcie albo katalog nie zawiera "
                    "obrazów możliwych do powiązania z annotations.xml."
                ),
                parent=self.frame,
            )
            return

        if final_run_dir is None:
            imported_run_dir, error_message, needs_image_dir = annotation_tab._import_external_annotation_run_to_workspace(
                selected_run_dir,
                compatible_images_dir=selected_images_dir,
                allowed_normalized_names=(selected_image_names or None),
                copy_images=False,
            )
            if imported_run_dir is None and needs_image_dir:
                prompt_dir = selected_images_dir or package_images_dir or Path(CONFIG.DIR_1_RAW)
                compatible_dir = filedialog.askdirectory(
                    initialdir=str(prompt_dir),
                    title="Wskaż folder obrazów zgodnych z annotations.xml",
                )
                if not compatible_dir:
                    return
                selected_images_dir = Path(compatible_dir)
                selected_image_names = self._get_project_start_adoptable_normalized_image_names(selected_images_dir)
                original_xml_match = self._summarize_project_start_xml_match(selected_xml_path, selected_images_dir)
                if not selected_image_names:
                    self.app.themed_error(
                        "Import anotacji tablic",
                        (
                            "W wybranym katalogu nie ma zdjęć roboczych do adopcji anotacji.\n\n"
                            "Import E1 pomija zdjęcia już zatwierdzone w projekcie."
                        ),
                        parent=self.frame,
                    )
                    return
                imported_run_dir, error_message, _needs_image_dir = annotation_tab._import_external_annotation_run_to_workspace(
                    selected_run_dir,
                    compatible_images_dir=selected_images_dir,
                    allowed_normalized_names=(selected_image_names or None),
                    copy_images=False,
                )
            if imported_run_dir is None:
                self.app.themed_error(
                    "Import anotacji tablic",
                    error_message or "Nie udało się zaimportowac wskazanych anotacji tablic.",
                    parent=self.frame,
                )
                return
            final_run_dir = imported_run_dir

        if final_run_dir is None:
            return

        resolved_images_dir = selected_images_dir or self._resolve_project_start_run_images_dir(final_run_dir)
        if resolved_images_dir is not None:
            try:
                if not resolved_images_dir.exists() or not resolved_images_dir.is_dir() or self._count_images_in_dir(resolved_images_dir, recursive=True) <= 0:
                    resolved_images_dir = None
            except Exception:
                resolved_images_dir = None
        if resolved_images_dir is None:
            self.app.themed_error(
                "Import anotacji tablic",
                (
                    "Nie udało się ustalić katalogu zdjęć zgodnych z annotations.xml.\n\n"
                    "Wskaż najpierw katalog zdjęć w E1 albo wybierz run anotacji, który zawiera obrazy lub manifest z input_dir."
                ),
                parent=self.frame,
            )
            return

        if not selected_image_names:
            selected_image_names = self._get_project_start_adoptable_normalized_image_names(resolved_images_dir)
            original_xml_match = self._summarize_project_start_xml_match(selected_xml_path, resolved_images_dir)

        if not selected_image_names:
            self.app.themed_error(
                "Import anotacji tablic",
                (
                    "W wybranej puli projektu nie ma zdjęć, do których można adoptować anotacje.\n\n"
                    "Import E1 pomija obrazy, które są już zatwierdzone w projekcie. "
                    "Wskaż katalog zawierający zdjęcia jeszcze robocze albo usuń błędnie wybrane źródło."
                ),
                parent=self.frame,
            )
            return

        compatibility = self._check_project_start_run_compatibility(final_run_dir, resolved_images_dir, adoptable_only=True)
        if compatibility.get("checked") and not compatibility.get("ok"):
            matched_count = int(compatibility.get("matched", 0) or 0)
            if matched_count > 0 and selected_image_names:
                matched_names = {
                    str(name or "").strip()
                    for name in list(compatibility.get("matched_normalized_names") or [])
                    if str(name or "").strip()
                }
                imported_run_dir, error_message, _needs_image_dir = annotation_tab._import_external_annotation_run_to_workspace(
                    final_run_dir,
                    compatible_images_dir=resolved_images_dir,
                    allowed_normalized_names=(matched_names or selected_image_names),
                    copy_images=False,
                )
                if imported_run_dir is None:
                    self.app.themed_error(
                        "Import anotacji tablic",
                        error_message or "Nie udało się przygotować zgodnego podzbioru anotacji.",
                        parent=self.frame,
                    )
                    return
                final_run_dir = imported_run_dir
                compatibility = self._check_project_start_run_compatibility(final_run_dir, resolved_images_dir, adoptable_only=True)
            else:
                images_dir = compatibility.get("images_dir")
                missing_preview = "\n".join(str(name) for name in (compatibility.get("missing_names") or []))
                approved_overlap = int(compatibility.get("approved_overlap", 0) or 0)
                missing_count = int(compatibility.get("missing", 0) or 0)
                incomplete_count = int(compatibility.get("incomplete", 0) or 0)
                missing_suffix = ""
                remaining_missing = int(compatibility.get("missing", 0) or 0) - len(compatibility.get("missing_names") or [])
                if remaining_missing > 0:
                    missing_suffix = f"\n... i jeszcze {remaining_missing} plikow."
                approved_line = (
                    f"\nPominięte, bo już zatwierdzone w projekcie: {approved_overlap}"
                    if approved_overlap > 0
                    else ""
                )
                missing_line = f"\nBrakujące anotowane obrazy w roboczej puli: {missing_count}" if missing_count > 0 else ""
                incomplete_line = (
                    f"\nPominięte, bo anotacje nie obejmują wszystkich tablic zapisanych w nazwie pliku: {incomplete_count}"
                    if incomplete_count > 0
                    else ""
                )
                self.app.themed_error(
                    "Import anotacji tablic",
                    (
                        "Wybrane anotacje tablic nie pasują do roboczych zdjęć projektu.\n\n"
                        f"Pula zdjęć E1: {Path(images_dir).name if images_dir is not None else 'brak'}\n"
                        f"{self._format_project_start_annotation_adoption_summary(compatibility)}"
                        f"{missing_line}{approved_line}{incomplete_line}\n\n"
                        "Nie znaleziono żadnego zgodnego wpisu do adopcji."
                        + (f"\n\nPrzykłady brakujących plików:\n{missing_preview}{missing_suffix}" if missing_preview else "")
                    ),
                    parent=self.frame,
                )
                return

        if compatibility.get("checked") and not compatibility.get("ok"):
            images_dir = compatibility.get("images_dir")
            missing_preview = "\n".join(str(name) for name in (compatibility.get("missing_names") or []))
            approved_overlap = int(compatibility.get("approved_overlap", 0) or 0)
            missing_count = int(compatibility.get("missing", 0) or 0)
            incomplete_count = int(compatibility.get("incomplete", 0) or 0)
            missing_suffix = ""
            remaining_missing = int(compatibility.get("missing", 0) or 0) - len(compatibility.get("missing_names") or [])
            if remaining_missing > 0:
                missing_suffix = f"\n... i jeszcze {remaining_missing} plikow."
            approved_line = (
                f"\nPominięte, bo już zatwierdzone w projekcie: {approved_overlap}"
                if approved_overlap > 0
                else ""
            )
            missing_line = f"\nBrakujące anotowane obrazy w roboczej puli: {missing_count}" if missing_count > 0 else ""
            incomplete_line = (
                f"\nPominięte, bo anotacje nie obejmują wszystkich tablic zapisanych w nazwie pliku: {incomplete_count}"
                if incomplete_count > 0
                else ""
            )
            self.app.themed_error(
                "Import anotacji tablic",
                (
                    "Wybrane anotacje tablic nie pasują do roboczych zdjęć projektu.\n\n"
                    f"Pula zdjęć E1: {Path(images_dir).name if images_dir is not None else 'brak'}\n"
                    f"{self._format_project_start_annotation_adoption_summary(compatibility)}"
                    f"{missing_line}{approved_line}{incomplete_line}\n\n"
                    "Najpierw wskaż katalog zdjęć zawierający niezatwierdzone obrazy zgodne z annotations.xml."
                    + (f"\n\nPrzyklady brakujacych plikow:\n{missing_preview}{missing_suffix}" if missing_preview else "")
                ),
                parent=self.frame,
            )
            return
        if compatibility.get("checked") and compatibility.get("ok"):
            images_dir = compatibility.get("images_dir")
            matched_count = int(compatibility.get("matched", 0) or 0)
            total_count = int(compatibility.get("total", 0) or 0)
            original_total_count = int(original_xml_match.get("total", 0) or total_count)
            original_missing_count = max(0, original_total_count - matched_count)
            xml_label = self._format_project_start_asset_source(selected_xml_path)
            images_label = (
                self._format_project_start_asset_source(images_dir)
                if images_dir is not None
                else "brak"
            )
            partial_line = (
                f"XML zawiera też {original_missing_count} anotowanych obrazów spoza roboczej puli do adopcji. "
                "Program zaadoptuje tylko zgodny podzbiór zdjęć jeszcze niezatwierdzonych."
                if original_missing_count > 0
                else "Wszystkie anotowane obrazy z XML pasują do zdjęć roboczych możliwych do adopcji."
            )
            should_adopt = self.app.themed_confirm(
                "Import anotacji tablic",
                (
                    "Program znalazł anotacje zgodne ze zdjęciami roboczymi w E1.\n\n"
                    f"Plik anotacji: {xml_label}\n"
                    f"Pula zdjęć E1: {images_label}\n"
                    f"{self._format_project_start_annotation_adoption_summary(compatibility)}\n\n"
                    f"{partial_line}\n\n"
                    "Czy adoptować te anotacje do projektu? Po potwierdzeniu zostaną powiązane tylko ze zdjęciami, "
                    "które nie są jeszcze zatwierdzone. E2 użyje ich jako gotowego źródła tablic, "
                    "a w Z2 nadal będzie można je sprawdzić i poprawić."
                ),
                parent=self.frame,
                confirm_label="Adoptuj anotacje",
                cancel_label="Anuluj",
                tone="info",
            )
            if not should_adopt:
                return

        if resolved_images_dir is not None and resolved_images_dir.exists() and resolved_images_dir.is_dir():
            try:
                CAMPAIGN.set_master_pool_dir(resolved_images_dir)
            except Exception:
                pass

        try:
            annotation_tab._remember_campaign_manual_plate_source(
                run_dir=final_run_dir,
                input_dir=resolved_images_dir,
            )
        except Exception as e:
            logger.debug(f"Nie udało się zapamietac importowanego runu tablic dla kampanii: {e}")
        try:
            CAMPAIGN.set_project_start_plate_source(
                source_run_path=str(final_run_dir.resolve()),
                source_xml_path=str((final_run_dir / "annotations.xml").resolve()),
                source_input_path=str(resolved_images_dir.resolve()),
            )
        except Exception as e:
            logger.debug(f"Nie udało się zapamietac źródła anotacji startowych E1: {e}")

        self.current_ingest_plan = {}
        self._set_project_start_asset_scope(
            "plate_run",
            self._infer_project_start_asset_scope_from_path("plate_run", final_run_dir),
        )
        try:
            self._sync_iteration_artifact_registry_from_project_start()
        except Exception:
            pass
        if resolved_images_dir is not None and self._get_iteration_image_count() == 0:
            self._generate_ingest_plan()
        else:
            self._refresh_dashboard()

        try:
            run_name = final_run_dir.name
        except Exception:
            run_name = "anotacje tablic"
        try:
            self.app.update_status(
                (
                    f"Adoptowano gotowe anotacje tablic z pliku {run_name}/annotations.xml. "
                    "E2 może użyć ich jako źródła tablic zamiast startować od zera."
                ),
                "info",
            )
        except Exception:
            pass

    @staticmethod
    def _get_step1_assets_intro_text() -> str:
        return (
            "Wybierz obowiązkowy katalog zdjęć. Opcjonalnie możesz dołączyć zgodne anotacje tablic "
            "z wcześniejszej pracy oraz modele, które mają być projektowym punktem startowym do dalszego "
            "używania i dotrenowywania."
        )

    def _refresh_project_start_panel(self) -> None:
        shell = getattr(self, "ingest_start_shell", None)
        if shell is None:
            return

        try:
            CAMPAIGN.ensure_step1_image_source_restored_from_previous_iteration()
        except Exception:
            pass

        try:
            self._restore_project_start_asset_scopes_from_state()
        except Exception:
            pass

        step1_mode = self._get_step1_presentation_mode()
        panel_visible = step1_mode in {"operational_assets", "operational_summary"}
        show_summary_operational = bool(step1_mode == "operational_summary")
        show_assets_operational = bool(step1_mode == "operational_assets")
        try:
            self._set_pack_visibility(shell, panel_visible, fill=tk.X, padx=10, pady=(0, 6))
        except Exception:
            pass
        if not panel_visible:
            return

        mode = self._get_project_start_mode()
        palette = getattr(self.app, "palette", {})
        mode_selected = mode in {"fresh", "assets"}
        mode_is_assets = mode == "assets"

        image_source = self._get_project_start_effective_images_source()
        master_pool = image_source.get("master_dir")
        master_pool_exists = bool(image_source.get("master_exists"))
        master_pool_images = int(image_source.get("master_count", 0) or 0)
        iteration_images_dir = image_source.get("iteration_dir")
        iteration_images_exists = bool(image_source.get("iteration_exists"))
        iteration_images_count = int(image_source.get("iteration_count", 0) or 0)
        effective_images_dir = image_source.get("effective_dir")
        effective_images_count = int(image_source.get("effective_count", 0) or 0)
        effective_images_exists = bool(image_source.get("effective_exists"))
        plate_ready_source = self._get_plate_route_ready_source()
        char_ready_source = self._get_char_route_ready_source()
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())
        char_model_ready = bool(char_model_path and Path(char_model_path).exists())

        header_text = "Panel E1: Zasoby startowe iteracji"
        intro_text = ""
        master_title = "Glowne obrazy iteracji:"
        choose_label = "Wybierz obrazy"

        if mode_is_assets:
            intro_text = ""
            master_title = "Obrazy tej iteracji:"
        elif mode_selected:
            intro_text = ""

        try:
            self.ingest_header_lbl.config(text=header_text)
            self.ingest_intro_lbl.config(text=intro_text, fg=palette.get("muted", "#c7c7c7"))
            self.lbl_ingest_master_title.config(text=master_title)
            self.btn_choose_master_pool.config(text=choose_label)
        except Exception:
            pass

        try:
            self._set_pack_visibility(self.ingest_header_lbl, False)
            self._set_pack_visibility(
                self.ingest_intro_lbl,
                False,
            )
            self._set_pack_visibility(
                self.ingest_top_section,
                bool(mode_selected and show_summary_operational),
                fill=tk.X,
                padx=10,
                pady=(0, 6),
                before=self.ingest_body,
            )
            self._set_pack_visibility(
                self.ingest_body,
                bool(mode_selected and show_assets_operational),
                fill=tk.BOTH,
                expand=True,
                padx=10,
                pady=(0, 6),
                before=self.ingest_insights_toggle_shell,
            )
            self._set_pack_visibility(
                self.ingest_insights_toggle_shell,
                False,
                fill=tk.X,
                padx=10,
                pady=(0, 6),
                before=self.ingest_insights_shell,
            )
            self._set_pack_visibility(self.ingest_start_title_lbl, mode_selected, fill=tk.X)
            self._set_pack_visibility(self.ingest_start_summary_lbl, False)
            self._set_pack_visibility(self.ingest_start_detected_lbl, False)
            self._set_pack_visibility(self.ingest_start_next_lbl, False)
            self._set_pack_visibility(self.ingest_status_shell, False)
            self._set_pack_visibility(self.btn_choose_master_pool, show_summary_operational, side=tk.RIGHT, padx=(8, 0))
            self._set_pack_visibility(self.btn_ingest_master_analysis, show_summary_operational, side=tk.RIGHT, padx=(0, 8))
        except Exception:
            pass

        try:
            if mode_selected and self.ingest_body is not None and show_summary_operational:
                self.ingest_top_section.pack_configure(before=self.ingest_body)
            if mode_selected and self.ingest_insights_toggle_shell is not None and show_assets_operational:
                self.ingest_body.pack_configure(before=self.ingest_insights_toggle_shell)
            if mode_selected and self.ingest_insights_shell is not None:
                self.ingest_insights_toggle_shell.pack_configure(before=self.ingest_insights_shell)
        except Exception:
            pass

        if self.ingest_start_title_lbl is not None:
            self.ingest_start_title_lbl.config(text="")
            self._set_pack_visibility(self.ingest_start_title_lbl, False)
        if self.ingest_start_summary_lbl is not None:
            self.ingest_start_summary_lbl.config(text="")
            self._set_pack_visibility(self.ingest_start_summary_lbl, False)
        if self.ingest_start_assets_title_lbl is not None:
            self.ingest_start_assets_title_lbl.config(text="Tabela startowa E1: zasoby, cel i walidacja")
        if self.ingest_start_next_lbl is not None:
            self.ingest_start_next_lbl.config(text="")

        try:
            self._set_project_start_badge_button_state(self.btn_ingest_start_fresh, text="Wybierz", enabled=True)
        except Exception:
            pass

        for widget, enabled in (
            (self.btn_ingest_import_plate_run, bool(mode_selected and show_assets_operational)),
            (self.btn_ingest_pick_plate_model, bool(mode_selected and show_assets_operational)),
            (self.btn_ingest_pick_char_model, bool(mode_selected and show_assets_operational)),
        ):
            if widget is None:
                continue
            try:
                self._set_project_start_badge_button_state(widget, enabled=enabled)
            except Exception:
                pass
        try:
            self._set_pack_visibility(
                self.ingest_start_assets_row,
                bool(mode_selected and show_assets_operational),
                fill=tk.X,
                pady=(10, 0),
            )
        except Exception:
            pass
        try:
            route_visible = bool(mode_selected and show_assets_operational)
            if self.ingest_route_shell is not None:
                if route_visible:
                    self.ingest_route_shell.pack_forget()
                    try:
                        self.ingest_route_shell.pack(
                            fill=tk.X,
                            pady=(8, 0),
                            after=self.ingest_start_assets_row,
                        )
                    except Exception:
                        self.ingest_route_shell.pack(fill=tk.X, pady=(8, 0))
                else:
                    self._set_pack_visibility(self.ingest_route_shell, False)
        except Exception:
            pass

        if not mode_selected:
            try:
                self._sync_ingest_wraps()
            except Exception:
                pass
            return

        images_source_text = self._format_project_start_asset_source(effective_images_dir)
        if effective_images_count > 0 and effective_images_dir is not None:
            images_validation_text = f"Wymagane | OK | {effective_images_count} obrazów"
            images_validation_tone = "success"
        elif effective_images_exists and effective_images_count <= 0:
            images_validation_text = "Wymagane | katalog nie zawiera obrazów."
            images_validation_tone = "error"
        else:
            images_validation_text = "Wymagane | wskaż katalog obrazów tej iteracji."
            images_validation_tone = "warning"
        self._set_project_start_asset_row_state(
            "images",
            source_text=images_source_text,
            source_path=str(effective_images_dir or ""),
            validation_text=images_validation_text,
            tone=images_validation_tone,
        )

        plate_source_info = self._get_project_start_plate_source_info()
        plate_run_path = str(plate_source_info.get("run_path") or "").strip()
        plate_xml_path = str(plate_source_info.get("xml_path") or "").strip()
        plate_run_source_text = self._format_project_start_asset_source(plate_xml_path or plate_run_path)
        plate_run_validation_text = "Opcjonalne | import wcześniejszych anotacji."
        plate_run_validation_tone = "muted"
        if plate_run_path:
            try:
                plate_run_dir = Path(plate_run_path)
            except Exception:
                plate_run_dir = None
            if plate_run_dir is None or not plate_run_dir.exists() or not plate_run_dir.is_dir():
                plate_run_validation_text = "Nie znaleziono pliku annotations.xml."
                plate_run_validation_tone = "error"
            elif not (plate_run_dir / "annotations.xml").exists():
                plate_run_validation_text = "Nie znaleziono pliku annotations.xml."
                plate_run_validation_tone = "error"
            elif effective_images_count <= 0:
                plate_run_validation_text = "Najpierw wskaż obrazy tej iteracji."
                plate_run_validation_tone = "warning"
            else:
                compatibility = self._check_project_start_run_compatibility(plate_run_dir, effective_images_dir, adoptable_only=True)
                if compatibility.get("checked") and int(compatibility.get("total", 0) or 0) <= 0:
                    plate_run_validation_text = "XML nie zawiera anotacji tablic do importu."
                    plate_run_validation_tone = "warning"
                elif compatibility.get("checked") and compatibility.get("ok"):
                    plate_run_validation_text = (
                        f"OK | {int(compatibility.get('matched', 0) or 0)} anotacji -> "
                        f"{int(compatibility.get('matched', 0) or 0)} obrazów / "
                        f"{int(compatibility.get('matched_plate_count', 0) or 0)} tablic"
                    )
                    plate_run_validation_tone = "success"
                elif compatibility.get("checked") and int(compatibility.get("matched", 0) or 0) > 0:
                    approved_overlap = int(compatibility.get("approved_overlap", 0) or 0)
                    incomplete_count = int(compatibility.get("incomplete", 0) or 0)
                    overlap_text = f" | pominięte zatwierdzone: {approved_overlap}" if approved_overlap > 0 else ""
                    incomplete_text = f" | niepełne wg nazwy: {incomplete_count}" if incomplete_count > 0 else ""
                    plate_run_validation_text = (
                        f"Do adopcji | {int(compatibility.get('matched', 0) or 0)} anotacji -> "
                        f"{int(compatibility.get('matched', 0) or 0)} obrazów / "
                        f"{int(compatibility.get('matched_plate_count', 0) or 0)} tablic"
                        f"{overlap_text}{incomplete_text}"
                    )
                    plate_run_validation_tone = "success"
                elif compatibility.get("checked"):
                    approved_overlap = int(compatibility.get("approved_overlap", 0) or 0)
                    incomplete_count = int(compatibility.get("incomplete", 0) or 0)
                    if approved_overlap > 0:
                        plate_run_validation_text = (
                            "Brak zdjęć do adopcji | zgodne anotacje dotyczą obrazów już zatwierdzonych."
                        )
                    elif incomplete_count > 0:
                        plate_run_validation_text = (
                            f"Brak adopcji | {incomplete_count} anotacji nie obejmuje wszystkich tablic z nazwy pliku."
                        )
                    else:
                        plate_run_validation_text = (
                            f"Niezgodne z roboczą pulą E1 | brak {int(compatibility.get('missing', 0) or 0)} "
                            f"z {int(compatibility.get('total', 0) or 0)} anotowanych obrazów."
                        )
                    plate_run_validation_tone = "error"
                else:
                    plate_run_validation_text = "Run zapisany. Sprawdź zgodność po wskazaniu roboczej puli E1."
                    plate_run_validation_tone = "warning"
        self._set_project_start_asset_row_state(
            "plate_run",
            source_text=plate_run_source_text,
            source_path=(plate_xml_path or plate_run_path),
            validation_text=plate_run_validation_text,
            tone=plate_run_validation_tone,
        )

        plate_model_source_text = self._format_project_start_asset_source(plate_model_path)
        if not plate_model_ready:
            plate_model_validation_text = "Opcjonalne | model do dalszego dotrenowania."
            plate_model_validation_tone = "muted"
        else:
            try:
                plate_model_ok, plate_model_error = self._validate_project_model_selection("plate", Path(plate_model_path))
            except Exception:
                plate_model_ok, plate_model_error = False, "Nie udało się zweryfikować modelu."
            if plate_model_ok:
                plate_model_identity = self._get_model_identity_label(plate_model_path)
                plate_model_validation_text = plate_model_identity or "OK | poprawny model YOLO Pose."
                plate_model_validation_tone = "success"
            else:
                plate_model_validation_text = plate_model_error or "Model tablic nie przeszedł walidacji."
                plate_model_validation_tone = "error"
        self._set_project_start_asset_row_state(
            "plate_model",
            source_text=plate_model_source_text,
            source_path=plate_model_path,
            validation_text=plate_model_validation_text,
            tone=plate_model_validation_tone,
        )

        char_model_source_text = self._format_project_start_asset_source(char_model_path)
        if not char_model_ready:
            char_model_validation_text = "Opcjonalne | model do dalszego dotrenowania."
            char_model_validation_tone = "muted"
        else:
            try:
                char_model_ok, char_model_error = self._validate_project_model_selection("char", Path(char_model_path))
            except Exception:
                char_model_ok, char_model_error = False, "Nie udało się zweryfikować modelu."
            if char_model_ok:
                char_model_identity = self._get_model_identity_label(char_model_path)
                char_model_validation_text = char_model_identity or "OK | poprawny model YOLO Detect."
                char_model_validation_tone = "success"
            else:
                char_model_validation_text = char_model_error or "Model znaków nie przeszedł walidacji."
                char_model_validation_tone = "error"
        self._set_project_start_asset_row_state(
            "char_model",
            source_text=char_model_source_text,
            source_path=char_model_path,
            validation_text=char_model_validation_text,
            tone=char_model_validation_tone,
        )

        next_lines = []
        if effective_images_count <= 0:
            next_lines.append("Dalej: najpierw wskaż obrazy tej iteracji w pierwszym wierszu tabeli.")
        elif plate_ready_source and char_ready_source:
            next_lines.append("Dalej: zatwierdź etap E1. Tor A otworzy korektę runu, a tor B będzie mógł wejść od razu do Z3.")
        elif plate_ready_source:
            next_lines.append("Dalej: zatwierdź etap E1. Tor A otworzy korektę wykrytego runu.")
            next_lines.append("Tor B odblokuje się, jesli ten run zawiera komplet tablic dla Z3.")
        elif plate_model_ready:
            next_lines.append("Dalej: zatwierdź etap E1. Tor A uruchomi autoanotację tablic na modelu projektu.")
        else:
            next_lines.append("Dalej: zatwierdź etap E1. Tor A wystartuje od nowego XML do ręcznej anotacji tablic.")

        if char_model_ready:
            next_lines.append(
                "Model znaków jest już zapisany w projekcie i w Z3 zostanie podstawiony automatycznie, "
                "ale sam nie odblokowuje jeszcze toru B bez przygotowania tablic."
            )

        if self.ingest_start_next_lbl is not None:
            self.ingest_start_next_lbl.config(text="")

        try:
            self._refresh_project_start_clear_buttons()
        except Exception:
            pass

        try:
            if show_assets_operational:
                self.ingest_insights_expanded = False
                self._set_pack_visibility(self.ingest_insights_toggle_shell, False)
                self._set_pack_visibility(self.ingest_insights_shell, False)
                self._set_pack_visibility(self.ingest_insights_toggle_btn, False)
                self._set_pack_visibility(self.ingest_insights_hint_lbl, False)
            else:
                self._refresh_ingest_insights_visibility(mode_selected=mode_selected)
            self._sync_ingest_wraps()
        except Exception:
            pass

        try:
            self._sync_iteration_artifact_registry_from_project_start()
        except Exception:
            pass

    def _refresh_ingest_insights_visibility(self, mode_selected: bool | None = None) -> None:
        if mode_selected is None:
            mode_selected = bool(CAMPAIGN.get_active_project_name())

        expanded = bool(self.ingest_insights_expanded) and bool(mode_selected)
        btn = getattr(self, "ingest_insights_toggle_btn", None)
        hint = getattr(self, "ingest_insights_hint_lbl", None)

        if btn is not None:
            try:
                btn.config(text=("Ukryj analizę puli" if expanded else "Pokaż analizę puli"))
            except Exception:
                pass

        if hint is not None:
            hint_text = (
                "Histogram i rozkład znaków pomagają ocenić wybrany katalog zdjęć, ale nie są wymagane do zatwierdzenia E1."
                if expanded
                else "Histogram i rozkład znaków są dostępne jako sekcja dodatkowa."
            )
            try:
                hint.config(text=hint_text)
            except Exception:
                pass

        try:
            self._set_pack_visibility(self.ingest_insights_shell, expanded, fill=tk.X, padx=10, pady=(0, 6))
        except Exception:
            pass

        if expanded:
            try:
                self._refresh_ingest_balance_chart()
            except Exception:
                pass

    def _get_ingest_summary_style(self) -> dict:
        palette = getattr(self.app, "palette", {})
        return {
            "bg": palette.get("panel", "#252526"),
            "border": palette.get("panel_border", palette.get("border", "#3c3c3c")),
            "fg": palette.get("fg", "#f3f3f3"),
            "muted": palette.get("muted", "#c7c7c7"),
        }

    def _sync_ingest_wraps(self, _event=None):
        try:
            panel_width = int(getattr(self, "ingest_panel_frame").winfo_width() or 0)
        except Exception:
            panel_width = 680
        if panel_width <= 1:
            panel_width = 680

        try:
            asset_table_width = int(getattr(self, "ingest_start_assets_table_shell").winfo_width() or 0)
        except Exception:
            asset_table_width = 0
        if asset_table_width <= 1:
            asset_table_width = max(0, panel_width - 10)
        asset_table_width = max(asset_table_width, 520)

        narrow_assets_table = bool(asset_table_width < 760)
        asset_col0 = 92 if narrow_assets_table else 96
        asset_col1 = 142 if narrow_assets_table else 150
        asset_col2 = 156 if narrow_assets_table else 168
        asset_col3 = 118 if narrow_assets_table else 126
        asset_col4 = 146 if narrow_assets_table else 156
        asset_col5 = 68 if narrow_assets_table else 72

        assets_table = getattr(self, "ingest_start_assets_table", None)
        if assets_table is not None:
            try:
                assets_table.grid_columnconfigure(0, minsize=asset_col0, weight=0)
                assets_table.grid_columnconfigure(1, minsize=asset_col1, weight=0)
                assets_table.grid_columnconfigure(2, minsize=asset_col2, weight=0)
                assets_table.grid_columnconfigure(3, minsize=asset_col3, weight=1)
                assets_table.grid_columnconfigure(4, minsize=asset_col4, weight=0)
                assets_table.grid_columnconfigure(5, minsize=asset_col5, weight=0)
            except Exception:
                pass

        try:
            header_texts = ("Zasób", "Źródło", "Walidacja", "Źródło ścieżki danych", "Akcja", "Więcej")
            for idx, header_lbl in enumerate(list(getattr(self, "ingest_start_assets_header_labels", []) or [])):
                if header_lbl is None or idx >= len(header_texts):
                    continue
                header_lbl.config(
                    text=header_texts[idx],
                    font=("Segoe UI", 8, "bold"),
                    wraplength=(max(110, asset_col3 - 12) if idx == 3 else 0),
                )
        except Exception:
            pass

        try:
            info_width = max(int(getattr(self, "ingest_info_panel").winfo_width() or 0) - 18, 260)
        except Exception:
            info_width = 320

        try:
            chart_width = max(int(getattr(self, "ingest_chart_panel").winfo_width() or 0) - 18, 320)
        except Exception:
            chart_width = 460

        master_wrap = max(280, panel_width - 220)
        intro_wrap = max(420, panel_width - 40)
        asset_validation_wrap = max(136, asset_col2 - 18)

        for widget_name, wrap_value in (
            ("lbl_ingest_master_value", master_wrap),
            ("ingest_intro_lbl", intro_wrap),
            ("ingest_start_summary_lbl", intro_wrap),
            ("ingest_start_detected_lbl", intro_wrap),
            ("ingest_start_next_lbl", intro_wrap),
            ("ingest_insights_hint_lbl", intro_wrap),
            ("ingest_logic_lbl", info_width),
            ("ingest_selection_lbl", info_width),
            ("ingest_balance_summary_lbl", chart_width),
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(wraplength=wrap_value)
            except Exception:
                pass

        for row in list(getattr(self, "ingest_start_asset_row_widgets", {}).values() or []):
            if not isinstance(row, dict):
                continue
            row_key = str(row.get("row_key", "") or "").strip()
            try:
                source_lbl = row.get("source_lbl")
                if source_lbl is not None:
                    source_lbl.config(wraplength=0, height=1, width=24)
            except Exception:
                pass
            try:
                validation_lbl = row.get("validation_lbl")
                if validation_lbl is not None:
                    validation_lbl.config(wraplength=asset_validation_wrap)
            except Exception:
                pass
            try:
                source_scope_host = row.get("source_scope_host")
                if source_scope_host is not None:
                    source_scope_host.config(width=max(110, asset_col3 - 6), height=30)
                action_host = row.get("action_host")
                if action_host is not None:
                    action_host.config(width=max(136, asset_col4 - 4), height=30)
                primary_slot = row.get("action_primary_slot")
                if primary_slot is not None:
                    primary_slot.config(width=62, height=28)
                clear_slot = row.get("action_clear_slot")
                if clear_slot is not None:
                    clear_slot.config(width=74, height=28)
                details_host = row.get("details_host")
                if details_host is not None:
                    details_host.config(width=max(58, asset_col5 - 4), height=30)
            except Exception:
                pass
            try:
                badge_list = list(row.get("scope_badges", []) or [])
                for idx, badge in enumerate(badge_list):
                    shell = badge.get("shell")
                    lamp = badge.get("lamp")
                    lamp_id = badge.get("lamp_id")
                    label = badge.get("label")
                    compact_text = str(badge.get("compact_label") or badge.get("full_label") or "").strip()
                    full_text = str(badge.get("full_label") or compact_text).strip()
                    if shell is not None:
                        try:
                            shell.pack_forget()
                        except Exception:
                            pass
                        shell.pack(
                            side=tk.LEFT,
                            anchor="center",
                            padx=(0 if idx == 0 else 6, 0),
                            pady=0,
                        )
                        shell.config(padx=6, pady=2)
                    if lamp is not None:
                        lamp.config(
                            width=8,
                            height=8,
                        )
                        if lamp_id is not None:
                            lamp.coords(
                                lamp_id,
                                1,
                                1,
                                7,
                                7,
                            )
                    if label is not None:
                        label.config(
                            text=(compact_text if narrow_assets_table else full_text),
                            font=("Segoe UI", 8),
                        )
            except Exception:
                pass

        try:
            if self.btn_ingest_start_fresh is not None:
                self._set_project_start_badge_button_state(self.btn_ingest_start_fresh, text="Wybierz")
            if self.btn_ingest_import_plate_run is not None:
                self._set_project_start_badge_button_state(self.btn_ingest_import_plate_run, text="Import")
            if self.btn_ingest_pick_plate_model is not None:
                self._set_project_start_badge_button_state(self.btn_ingest_pick_plate_model, text="Wskaż")
            if self.btn_ingest_pick_char_model is not None:
                self._set_project_start_badge_button_state(self.btn_ingest_pick_char_model, text="Wskaż")
            for row_key, button in dict(getattr(self, "btn_ingest_asset_more", {}) or {}).items():
                if button is None:
                    continue
                if row_key == "images":
                    self._set_project_start_badge_button_state(button, text="Analiza")
                else:
                    self._set_project_start_badge_button_state(button, text="Więcej")
        except Exception:
            pass

        status_wrap = max(440, panel_width - 70)
        for lbl in getattr(self, "ingest_status_labels", []):
            try:
                lbl.config(wraplength=status_wrap)
            except Exception:
                pass
        for value_lbl in list(getattr(self, "ingest_status_table_value_labels", []) or []):
            try:
                value_lbl.config(wraplength=max(180, status_wrap - 220))
            except Exception:
                pass

    def _set_ingest_status_lines(self, rows=None, meta=""):
        table = getattr(self, "ingest_status_table", None)
        if table is not None:
            try:
                for child in list(table.winfo_children()):
                    child.destroy()
            except Exception:
                pass
        self.ingest_status_table_value_labels = []
        labels = list(getattr(self, "ingest_status_labels", []) or [])
        for lbl in labels:
            try:
                lbl.config(text="")
            except Exception:
                pass
        try:
            self._set_pack_visibility(
                getattr(self, "ingest_status_shell", None),
                False,
            )
        except Exception:
            pass

    def _get_iteration_image_count(self) -> int:
        try:
            return int(CAMPAIGN.get_iteration_image_count() or 0)
        except Exception:
            iter_dir = CAMPAIGN.get_iteration_raw_dir()
            return self._count_images_in_dir(iter_dir, recursive=True)

    def _load_ingest_manifest_cached(self) -> dict:
        try:
            manifest_path = CAMPAIGN.get_ingest_manifest_path()
        except Exception:
            manifest_path = None

        cache = getattr(self, "_dashboard_perf_cache", {})
        json_cache = cache.get("json_payloads", {}) if isinstance(cache, dict) else {}
        cache_key = ("ingest_manifest", self._build_cache_token_for_path(manifest_path))
        cached = json_cache.get(cache_key) if isinstance(json_cache, dict) else None
        if isinstance(cached, dict):
            return dict(cached)

        try:
            manifest = CAMPAIGN.load_ingest_manifest()
        except Exception:
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}

        if isinstance(json_cache, dict):
            if len(json_cache) > 128:
                json_cache.clear()
            json_cache[cache_key] = dict(manifest)
        return dict(manifest)

    def _load_previous_iteration_ingest_manifest(self) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {}
        try:
            current_iter = max(1, int(CAMPAIGN.get_current_iteration_num() or 1))
        except Exception:
            current_iter = 1
        if current_iter <= 1:
            return {}

        for iter_num in range(current_iter - 1, 0, -1):
            try:
                manifest_path = CAMPAIGN.get_ingest_manifest_path(iter_num)
            except Exception:
                manifest_path = None
            cache = getattr(self, "_dashboard_perf_cache", {})
            json_cache = cache.get("json_payloads", {}) if isinstance(cache, dict) else {}
            cache_key = ("ingest_manifest_prev", iter_num, self._build_cache_token_for_path(manifest_path))
            cached = json_cache.get(cache_key) if isinstance(json_cache, dict) else None
            if isinstance(cached, dict) and cached:
                return dict(cached)
            try:
                manifest = CAMPAIGN.load_ingest_manifest(iter_num)
            except Exception:
                manifest = {}
            if not isinstance(manifest, dict) or not manifest:
                continue
            if isinstance(json_cache, dict):
                if len(json_cache) > 128:
                    json_cache.clear()
                json_cache[cache_key] = dict(manifest)
            return dict(manifest)
        return {}

    def _load_latest_ingest_plan_for_current_iteration(self) -> dict:
        try:
            plan_path = CAMPAIGN.get_latest_ingest_plan_path()
        except Exception:
            plan_path = None

        cache = getattr(self, "_dashboard_perf_cache", {})
        json_cache = cache.get("json_payloads", {}) if isinstance(cache, dict) else {}
        cache_key = ("latest_ingest_plan", self._build_cache_token_for_path(plan_path))
        cached = json_cache.get(cache_key) if isinstance(json_cache, dict) else None
        if isinstance(cached, dict):
            plan = dict(cached)
        else:
            plan = CAMPAIGN.load_latest_ingest_plan()
            if not isinstance(plan, dict):
                plan = {}
            if isinstance(json_cache, dict):
                if len(json_cache) > 128:
                    json_cache.clear()
                json_cache[cache_key] = dict(plan)
        if not isinstance(plan, dict):
            return {}
        if int(plan.get("iteration", 0) or 0) != CAMPAIGN.get_current_iteration_num():
            return {}
        if str(plan.get("project", "") or "").strip() != str(CAMPAIGN.get_active_project_name() or "").strip():
            return {}
        current_master_pool = CAMPAIGN.get_master_pool_dir()
        plan_master_pool = str(plan.get("master_pool_dir", "") or "").strip()
        if current_master_pool is None and plan_master_pool:
            return {}
        if current_master_pool is not None and plan_master_pool and plan_master_pool != str(current_master_pool):
            return {}
        return plan

    def _normalize_ingest_plan_for_display(self, plan: dict, current_balance: dict | None = None) -> dict:
        if not isinstance(plan, dict):
            return {}

        selected_items = list(plan.get("selected", []) or [])
        if not selected_items:
            return {}

        normalized = dict(plan)
        try:
            selected_total = int(normalized.get("selected_total", 0) or 0)
        except Exception:
            selected_total = 0
        if selected_total <= 0:
            normalized["selected_total"] = len(selected_items)

        try:
            raw_total = int(normalized.get("raw_total", 0) or 0)
        except Exception:
            raw_total = 0
        if raw_total <= 0:
            normalized["raw_total"] = int(normalized.get("selected_total", len(selected_items)) or len(selected_items))

        if current_balance:
            normalized["current_balance"] = {
                ch: int((current_balance or {}).get(ch, 0) or 0)
                for ch in CHAR_ALPHABET
            }
        elif not isinstance(normalized.get("current_balance"), dict):
            normalized["current_balance"] = {ch: 0 for ch in CHAR_ALPHABET}

        normalized["selected"] = selected_items
        return normalized

    def _build_ingest_plan_from_manifest_for_display(
        self,
        manifest: dict,
        current_balance: dict | None = None,
    ) -> dict:
        if not isinstance(manifest, dict) or not manifest:
            return {}

        selected_images = list(manifest.get("selected_images", []) or [])
        if not selected_images:
            return {}

        planner = CampaignIngestPlanner()
        selected_items = []
        selected_hist = Counter()
        master_pool_dir = CAMPAIGN.get_master_pool_dir()
        target_dir_text = str(manifest.get("target_dir", "") or "").strip()
        target_dir = Path(target_dir_text) if target_dir_text else CAMPAIGN.get_iteration_raw_dir()

        for item in selected_images:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue

            target_path_text = str(item.get("target_path", "") or "").strip()
            if not target_path_text and target_dir is not None:
                target_path_text = str((Path(target_dir) / name).resolve())

            source_path_text = str(item.get("source_path", "") or "").strip() or target_path_text
            ground_truth_texts = list(item.get("ground_truth_texts", []) or [])
            if not ground_truth_texts:
                ground_truth_texts = planner.extract_true_texts_from_filename(name)

            char_hist = item.get("char_histogram", {}) or {}
            if not isinstance(char_hist, dict) or not char_hist:
                char_hist = planner.build_char_histogram(ground_truth_texts)
            if not char_hist:
                continue

            selected_hist.update(char_hist)
            selected_items.append(
                {
                    "name": name,
                    "source_path": source_path_text,
                    "source_key": str(item.get("source_key", "") or ""),
                    "target_path": target_path_text,
                    "ground_truth_texts": list(ground_truth_texts),
                    "char_histogram": {ch: int(value) for ch, value in char_hist.items()},
                    "score": 0.0,
                    "score_details": {},
                }
            )

        if not selected_items:
            return {}

        current_counter = Counter()
        for ch in CHAR_ALPHABET:
            current_counter[ch] = int((current_balance or {}).get(ch, 0) or 0)
        predicted_counter = Counter(current_counter)
        predicted_counter.update(selected_hist)

        try:
            selected_count = int(manifest.get("selected_count", len(selected_items)) or len(selected_items))
        except Exception:
            selected_count = len(selected_items)

        return {
            "ok": True,
            "planner_version": "manifest_display_v1",
            "generated_at": str(manifest.get("created_at", "") or datetime.now().isoformat()),
            "project": str(manifest.get("project", CAMPAIGN.get_active_project_name() or "") or ""),
            "iteration": int(manifest.get("iteration", CAMPAIGN.get_current_iteration_num() or 1) or 1),
            "master_pool_dir": str(manifest.get("master_pool_dir", "") or ""),
            "source_dir": str(manifest.get("source_dir", "") or ""),
            "selection_mode": str(manifest.get("selection_mode", "") or ""),
            "manifest_only": bool(manifest.get("manifest_only", False)),
            "batch_size": 0,
            "raw_total": selected_count,
            "candidates_total": selected_count,
            "selected_total": len(selected_items),
            "new_to_project_total": int((manifest.get("proposal_summary") or {}).get("new_to_project_total", len(selected_items)) or len(selected_items)),
            "skipped_used": int((manifest.get("proposal_summary") or {}).get("skipped_used", 0) or 0),
            "skipped_duplicate_filenames": int((manifest.get("proposal_summary") or {}).get("skipped_duplicate_filenames", 0) or 0),
            "skipped_duplicate_approved_filenames": int((manifest.get("proposal_summary") or {}).get("skipped_duplicate_approved_filenames", 0) or 0),
            "project_overlap_filenames": int((manifest.get("proposal_summary") or {}).get("project_overlap_filenames", 0) or 0),
            "skipped_invalid_ground_truth": 0,
            "current_balance": {ch: int(current_counter.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected_balance": {ch: int(selected_hist.get(ch, 0)) for ch in CHAR_ALPHABET},
            "predicted_balance_after": {ch: int(predicted_counter.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected": selected_items,
        }

    def _build_ingest_plan_from_iteration_dir_for_display(
        self,
        iteration_dir: Path,
        current_balance: dict | None = None,
    ) -> dict:
        if iteration_dir is None:
            return {}
        iteration_dir = Path(iteration_dir)
        if not iteration_dir.exists() or not iteration_dir.is_dir():
            return {}

        planner = CampaignIngestPlanner()
        selected_items = []
        selected_hist = Counter()
        image_paths = sorted(
            (
                image_path
                for image_path in iteration_dir.rglob("*")
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            ),
            key=lambda path: path.as_posix().lower(),
        )

        master_pool_dir = CAMPAIGN.get_master_pool_dir()
        for image_path in image_paths:
            ground_truth_texts = planner.extract_true_texts_from_filename(image_path.name)
            char_hist = planner.build_char_histogram(ground_truth_texts)
            if not char_hist:
                continue

            selected_hist.update(char_hist)
            try:
                source_path = str(image_path.resolve())
            except Exception:
                source_path = str(image_path.absolute())
            selected_items.append(
                {
                    "name": image_path.name,
                    "source_path": source_path,
                    "source_key": planner.make_source_key(image_path, master_pool_dir=master_pool_dir),
                    "target_path": source_path,
                    "ground_truth_texts": list(ground_truth_texts),
                    "char_histogram": dict(char_hist),
                    "score": 0.0,
                    "score_details": {},
                }
            )

        if not selected_items:
            return {}

        current_counter = Counter()
        for ch in CHAR_ALPHABET:
            current_counter[ch] = int((current_balance or {}).get(ch, 0) or 0)
        predicted_counter = Counter(current_counter)
        predicted_counter.update(selected_hist)

        return {
            "ok": True,
            "planner_version": "iteration_dir_display_v1",
            "generated_at": datetime.now().isoformat(),
            "project": CAMPAIGN.get_active_project_name() or "",
            "iteration": int(CAMPAIGN.get_current_iteration_num() or 1),
            "master_pool_dir": str(master_pool_dir.resolve()) if master_pool_dir else "",
            "batch_size": 0,
            "raw_total": len(image_paths),
            "candidates_total": len(image_paths),
            "selected_total": len(selected_items),
            "new_to_project_total": len(selected_items),
            "skipped_used": 0,
            "skipped_duplicate_filenames": 0,
            "skipped_duplicate_approved_filenames": 0,
            "project_overlap_filenames": 0,
            "skipped_invalid_ground_truth": len(image_paths) - len(selected_items),
            "current_balance": {ch: int(current_counter.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected_balance": {ch: int(selected_hist.get(ch, 0)) for ch in CHAR_ALPHABET},
            "predicted_balance_after": {ch: int(predicted_counter.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected": selected_items,
        }

    def _restore_ingest_plan_from_existing_iteration(
        self,
        current_iter: int,
        current_proj: str,
        snapshot: dict | None = None,
    ) -> bool:
        try:
            iteration_dir = CAMPAIGN.get_iteration_raw_dir(current_iter, current_proj)
        except Exception:
            iteration_dir = None

        try:
            manifest_path = CAMPAIGN.get_ingest_manifest_path(current_iter, current_proj)
        except Exception:
            manifest_path = None
        try:
            plan_path = CAMPAIGN.get_latest_ingest_plan_path(current_proj)
        except Exception:
            plan_path = None

        signature = (
            str(current_proj or "").strip(),
            int(current_iter or 0),
            self._build_cache_token_for_path(iteration_dir),
            self._build_cache_token_for_path(manifest_path),
            self._build_cache_token_for_path(plan_path),
        )
        if (
            getattr(self, "_existing_iteration_ingest_plan_signature", None) == signature
            and isinstance(self.current_ingest_plan, dict)
            and self.current_ingest_plan.get("selected")
        ):
            return True

        current_balance = (snapshot or {}).get("char_balance", {}) if isinstance(snapshot, dict) else {}
        plan = self._normalize_ingest_plan_for_display(
            self._load_latest_ingest_plan_for_current_iteration(),
            current_balance=current_balance,
        )

        if not plan:
            try:
                manifest = CAMPAIGN.load_ingest_manifest(current_iter, current_proj)
            except Exception:
                manifest = {}
            plan = self._build_ingest_plan_from_manifest_for_display(
                manifest,
                current_balance=current_balance,
            )

        if not plan:
            plan = self._build_ingest_plan_from_iteration_dir_for_display(
                iteration_dir,
                current_balance=current_balance,
            )

        if not plan:
            self._existing_iteration_ingest_plan_signature = None
            return False

        plan["project"] = str(current_proj or plan.get("project", "") or "")
        plan["iteration"] = int(current_iter or plan.get("iteration", 1) or 1)
        self.current_ingest_plan = plan
        self._recalculate_current_ingest_plan()
        self._existing_iteration_ingest_plan_signature = signature
        return True

    def _recalculate_current_ingest_plan(self):
        if not isinstance(self.current_ingest_plan, dict):
            self.current_ingest_plan = {}
            return

        selected_items = self.current_ingest_plan.get("selected", []) or []
        current_balance = Counter(self.current_ingest_plan.get("current_balance", {}) or {})
        selected_balance = Counter()
        for item in selected_items:
            if not isinstance(item, dict):
                continue
            selected_balance.update(item.get("char_histogram", {}) or {})

        predicted = Counter(current_balance)
        predicted.update(selected_balance)

        self.current_ingest_plan["selected_total"] = len(selected_items)
        self.current_ingest_plan["selected_balance"] = {
            ch: int(selected_balance.get(ch, 0))
            for ch in CHAR_ALPHABET
        }
        self.current_ingest_plan["predicted_balance_after"] = {
            ch: int(predicted.get(ch, 0))
            for ch in CHAR_ALPHABET
        }

    def _format_histogram_compact(self, char_hist: dict, limit: int = 5) -> str:
        if not isinstance(char_hist, dict):
            return "brak"

        items = [
            (str(ch), int(value))
            for ch, value in char_hist.items()
            if int(value or 0) > 0
        ]
        if not items:
            return "brak"

        items.sort(key=lambda entry: (-entry[1], entry[0]))
        return ", ".join(f"{ch}:{value}" for ch, value in items[:limit])

    def _get_selected_ingest_indices(self) -> list[int]:
        if self.ingest_plan_listbox is None:
            return []
        try:
            indices = []
            for raw_idx in self.ingest_plan_listbox.curselection():
                idx = int(raw_idx)
                if 0 <= idx < len(self.ingest_plan_items):
                    indices.append(idx)
            return sorted(set(indices))
        except Exception:
            return []

    def _refresh_ingest_logic_text(self):
        if self.ingest_logic_lbl is None:
            return

        plan_count = int(self.current_ingest_plan.get("selected_total", 0) or 0)
        selected_balance = Counter(self.current_ingest_plan.get("selected_balance", {}) or {})
        snapshot_balance = Counter((self.last_ingest_snapshot or {}).get("char_balance", {}) or {})
        rare_chars = [
            ch for ch in CHAR_ALPHABET
            if int(snapshot_balance.get(ch, 0)) > 0
        ]
        rare_chars.sort(key=lambda ch: (int(snapshot_balance.get(ch, 0)), ch))
        rare_preview = ", ".join(
            f"{ch}:{int(snapshot_balance.get(ch, 0))}"
            for ch in rare_chars[:6]
        ) or "brak danych"

        if plan_count > 0:
            text = (
                "Załadowany został aktualny wybrany folder zdjęć dla E1.\n"
                "1. System wczytuje wszystkie poprawne zdjęcia z głównej puli.\n"
                "2. Z nazwy każdego pliku odczytuje tekst tablic i buduje histogram znaków.\n"
                "3. Możesz zatwierdzić zestaw zdjęć jako wejście do iteracji.\n"
                f"4. Najczęstsze znaki w tej chwili: {self._format_histogram_compact(selected_balance, limit=6)}."
            )
        else:
            text = ""

        try:
            self.ingest_logic_lbl.config(text=text)
        except Exception:
            pass

    def _refresh_ingest_selection_info(self):
        if self.ingest_selection_lbl is None:
            return

        if not self.current_ingest_plan or not self.ingest_plan_items:
            text = (
                "Po załadowaniu wybranego folderu zdjęć zaznacz jedno albo kilka zdjęć na liście. "
                "Panel pokaże, jaki wpływ będzie miało ich usunięcie z E1."
            )
            try:
                self.ingest_selection_lbl.config(text=text)
            except Exception:
                pass
            return

        selected_indices = self._get_selected_ingest_indices()
        if not selected_indices:
            text = (
                "Zaznacz jedno albo kilka zdjęć na liście. "
                "Możesz używać Ctrl i Shift jak w systemie Windows."
            )
            try:
                self.ingest_selection_lbl.config(text=text)
            except Exception:
                pass
            return

        selected_items = [
            self.ingest_plan_items[idx]
            for idx in selected_indices
            if 0 <= idx < len(self.ingest_plan_items)
        ]
        if not selected_items:
            return

        selected_texts = []
        removed_hist = Counter()
        for item in selected_items:
            for text_value in item.get("ground_truth_texts", []) or []:
                text_value = str(text_value).strip()
                if text_value and text_value not in selected_texts:
                    selected_texts.append(text_value)
            removed_hist.update(item.get("char_histogram", {}) or {})

        current_hist = Counter(self.current_ingest_plan.get("selected_balance", {}) or {})
        after_hist = Counter(current_hist)
        for ch, value in removed_hist.items():
            after_hist[ch] = max(0, int(after_hist.get(ch, 0)) - int(value))

        impact_rows = []
        for ch, removed_count in removed_hist.items():
            current_value = int(current_hist.get(ch, 0))
            after_value = int(after_hist.get(ch, 0))
            if removed_count > 0:
                impact_rows.append((str(ch), int(removed_count), current_value, after_value))
        impact_rows.sort(key=lambda entry: (-entry[1], entry[0]))

        zeroed_chars = [
            ch for ch, removed_count, current_value, after_value in impact_rows
            if current_value > 0 and after_value == 0
        ]

        texts_preview = ", ".join(selected_texts[:6])
        if len(selected_texts) > 6:
            texts_preview += f" +{len(selected_texts) - 6} więcej"
        if not texts_preview:
            texts_preview = "brak ground truth"

        impact_preview = ", ".join(
            f"{ch}: {before}->{after}"
            for ch, _removed, before, after in impact_rows[:6]
        ) or "brak danych"

        text = (
            f"Zaznaczono {len(selected_items)} zdjęć.\n"
            f"Tablice z nazw plików: {texts_preview}\n"
            f"Znaki w zaznaczeniu: {self._format_histogram_compact(removed_hist, limit=8)}\n"
            f"Po usunięciu z wybranego folderu zdjęć najbardziej spadną: {impact_preview}"
        )
        if zeroed_chars:
            text += f"\nPo usunięciu całkiem znikną z E1: {', '.join(zeroed_chars[:6])}."
        try:
            self.ingest_selection_lbl.config(text=text)
        except Exception:
            pass

    def _refresh_ingest_balance_chart(self):
        self._render_ingest_balance_chart(
            self.ingest_balance_canvas,
            self.ingest_balance_summary_lbl,
            self.current_ingest_plan.get("selected_balance", {}) or {},
            package_images=int(self.current_ingest_plan.get("selected_total", 0) or 0),
            raw_package_images=int(
                self.current_ingest_plan.get(
                    "raw_total",
                    self.current_ingest_plan.get("selected_total", 0),
                ) or self.current_ingest_plan.get("selected_total", 0) or 0
            ),
        )

    def _theme_step1_ingest_panel(self):
        palette = getattr(self.app, "palette", {})
        frame_bg = self._get_step1_ingest_frame_bg()

        try:
            if self.ingest_panel_frame is not None:
                self.ingest_panel_frame.config(
                    bg=frame_bg,
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
                )
        except Exception:
            pass

        for widget_name, fg_value in (
            ("ingest_header_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_intro_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_start_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_start_summary_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_start_detected_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_start_next_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_insights_hint_lbl", palette.get("muted", "#c7c7c7")),
            ("lbl_ingest_master_title", palette.get("fg", "#f3f3f3")),
            ("lbl_ingest_master_value", palette.get("accent", "#4fc1ff")),
            ("lbl_ingest_batch_title", palette.get("fg", "#f3f3f3")),
            ("ingest_list_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_logic_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_logic_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_balance_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_balance_summary_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_selection_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_selection_lbl", palette.get("muted", "#c7c7c7")),
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(bg=frame_bg, fg=fg_value)
            except Exception:
                pass

        for widget_name in (
            "ingest_start_shell",
            "ingest_start_panel",
            "ingest_route_shell",
            "ingest_route_body",
            "ingest_start_assets_row",
            "ingest_top_section",
            "ingest_body",
            "ingest_left_col",
            "ingest_right_col",
            "ingest_master_row",
            "ingest_master_value_row",
            "ingest_config_row",
            "ingest_actions_row",
            "ingest_approve_row",
            "ingest_footer_row",
            "ingest_insights_toggle_shell",
            "ingest_insights_shell",
            "ingest_chart_panel",
            "ingest_info_panel",
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(bg=frame_bg)
            except Exception:
                pass

        bordered_widgets = ("ingest_route_shell",)
        for widget_name in bordered_widgets:
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                )
            except Exception:
                pass

        try:
            if getattr(self, "ingest_insights_shell", None) is not None:
                self.ingest_insights_shell.config(
                    bg=frame_bg,
                    highlightthickness=0,
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
                )
        except Exception:
            pass

        try:
            summary_style = self._get_ingest_summary_style()
            if getattr(self, "ingest_status_shell", None) is not None:
                self.ingest_status_shell.config(
                    bg=summary_style["bg"],
                    highlightthickness=1,
                    highlightbackground=summary_style["border"],
                    highlightcolor=summary_style["border"],
                )
            if getattr(self, "ingest_status_panel", None) is not None:
                self.ingest_status_panel.config(bg=summary_style["bg"])
            if getattr(self, "ingest_status_table", None) is not None:
                self.ingest_status_table.config(
                    bg=summary_style["border"],
                    highlightbackground=summary_style["border"],
                    highlightcolor=summary_style["border"],
                    highlightthickness=1,
                )
            for idx, lbl in enumerate(getattr(self, "ingest_status_labels", [])):
                lbl.config(
                    bg=summary_style["bg"],
                    fg=(summary_style["fg"] if idx == 0 else summary_style["muted"]),
                    font=("Segoe UI", 9, "normal"),
                )
        except Exception:
            pass

        self._sync_ingest_wraps()
        self._refresh_ingest_balance_chart()

    def _populate_ingest_plan_list(self):
        self.ingest_plan_items = list(self.current_ingest_plan.get("selected", []) or [])
        if self.ingest_plan_listbox is None:
            return

        self.ingest_plan_listbox.delete(0, tk.END)
        for index, item in enumerate(self.ingest_plan_items, start=1):
            name = str(item.get("name", "") or "").strip()
            texts = ", ".join(item.get("ground_truth_texts", []) or [])
            left = texts if texts else "brak GT"
            label = (
                f"{index:03d}. "
                f"{shorten(left, width=28, placeholder='...')} | "
                f"{shorten(name, width=70, placeholder='...')}"
            )
            self.ingest_plan_listbox.insert(tk.END, label)

        if self.ingest_plan_items:
            try:
                self.ingest_plan_listbox.selection_clear(0, tk.END)
                self.ingest_plan_listbox.selection_set(0)
                self.ingest_plan_listbox.activate(0)
            except Exception:
                pass

    def _refresh_ingest_balance_only(self):
        if not CAMPAIGN.get_active_project_name():
            return

        snapshot = CAMPAIGN.refresh_ingest_balance_snapshot()
        self._refresh_ingest_panel(snapshot_override=snapshot)

        try:
            self.app.update_status("Odświeżono bilans znaków dla przygotowania wybranego folderu zdjęć E1.", "info")
        except Exception:
            pass

    def _refresh_ingest_panel(self, snapshot_override: dict = None):
        has_project = bool(CAMPAIGN.get_active_project_name())
        step1_status = CAMPAIGN.get_step1_status() if has_project else "pending"
        step1_approved = step1_status == "approved"
        master_pool = CAMPAIGN.get_master_pool_dir()
        master_pool_text = str(master_pool) if master_pool else "Brak ustawionej głównej puli zdjęć"
        self.ingest_master_pool_var.set(master_pool_text)
        master_pool_exists = bool(master_pool and master_pool.exists() and master_pool.is_dir())
        frame_bg = self._get_step1_ingest_frame_bg()
        self._theme_step1_ingest_panel()
        self._refresh_project_start_panel()
        try:
            self._render_step1_route_actions(getattr(self, "ingest_route_body", None))
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć wyboru toru E1: {e}")
        try:
            self._refresh_project_start_assets_table_theme(frame_bg)
        except Exception:
            pass
        project_start_mode = self._get_project_start_mode()

        snapshot = snapshot_override or CAMPAIGN.load_ingest_balance_snapshot()
        if has_project and not snapshot:
            snapshot = CAMPAIGN.refresh_ingest_balance_snapshot()
        self.last_ingest_snapshot = snapshot or {}

        iter_image_count = self._get_iteration_image_count() if has_project else 0
        master_pool_image_count = self._count_images_in_dir(master_pool, recursive=True) if master_pool_exists else 0

        if has_project:
            current_iter = CAMPAIGN.get_current_iteration_num()
            current_proj = CAMPAIGN.get_active_project_name()
            if iter_image_count > 0:
                restored = self._restore_ingest_plan_from_existing_iteration(
                    current_iter=current_iter,
                    current_proj=current_proj,
                    snapshot=snapshot,
                )
                if not restored:
                    self.current_ingest_plan = {}
            elif (
                isinstance(self.current_ingest_plan, dict)
                and int(self.current_ingest_plan.get("iteration", 0) or 0) == current_iter
                and str(self.current_ingest_plan.get("project", "") or "").strip() == str(current_proj or "").strip()
                and self.current_ingest_plan.get("selected") is not None
            ):
                self._recalculate_current_ingest_plan()
                self._existing_iteration_ingest_plan_signature = None
            else:
                self.current_ingest_plan = {}
                self._existing_iteration_ingest_plan_signature = None
            self._populate_ingest_plan_list()
        else:
            self.current_ingest_plan = {}
            self._existing_iteration_ingest_plan_signature = None
            self._populate_ingest_plan_list()

        plan_count = int(self.current_ingest_plan.get("selected_total", 0) or 0)
        raw_plan_count = int(self.current_ingest_plan.get("raw_total", plan_count) or plan_count)
        manifest = self._load_ingest_manifest_cached() if has_project else {}
        step1_context = self._get_step1_manifest_context(manifest if isinstance(manifest, dict) else None)
        project_pool_total = int(step1_context.get("project_pool_total_after", step1_context.get("project_pool_total", 0)) or 0)
        source_total = int(step1_context.get("source_total", 0) or 0)
        approved_images = int(step1_context.get("approved_images", 0) or 0)
        approved_plates = int(step1_context.get("approved_plates", 0) or 0)
        current_iteration_package = int(
            step1_context.get("current_iteration_package_count", 0)
            or iter_image_count
            or plan_count
            or 0
        )
        new_to_project_count = int(step1_context.get("new_to_project_count", 0) or 0)
        project_overlap_count = int(step1_context.get("project_overlap_filenames", 0) or 0)
        skipped_approved_count = int(step1_context.get("skipped_duplicate_approved", 0) or 0)

        if not step1_approved and plan_count > 0:
            project_pool_before = int(step1_context.get("project_pool_total_before", 0) or 0)
            new_to_project_count = int(
                self.current_ingest_plan.get(
                    "new_to_project_total",
                    plan_count,
                ) or 0
            )
            project_pool_total = max(project_pool_total, project_pool_before + new_to_project_count)
            current_iteration_package = max(current_iteration_package, plan_count)
            project_overlap_count = int(
                self.current_ingest_plan.get("project_overlap_filenames", self.current_ingest_plan.get("skipped_duplicate_filenames", 0)) or 0
            )
            skipped_approved_count = int(
                self.current_ingest_plan.get("skipped_duplicate_approved_filenames", 0) or 0
            )
            source_total = max(source_total, raw_plan_count)

        if project_pool_total <= 0:
            project_pool_total = max(int(source_total or 0), int(raw_plan_count or 0), int(current_iteration_package or 0))

        summary_rows = [
            ("Pudełko: tablice zatwierdzone", f"{approved_images} zdjęć / {approved_plates} tablic"),
            ("Zdjęcia tej iteracji", f"{current_iteration_package} zdjęć"),
            ("Nowe względem projektu", f"{new_to_project_count} zdjęć"),
            ("Pula projektu (informacyjnie)", f"{project_pool_total} zdjęć"),
        ]
        if source_total > 0:
            summary_rows.insert(0, ("Źródło zdjęć", f"{source_total} zdjęć"))
        if project_overlap_count > 0:
            summary_rows.append(("Już wcześniej w projekcie", f"{project_overlap_count} zdjęć"))
        if skipped_approved_count > 0:
            summary_rows.append(("W tym już zatwierdzone", f"{skipped_approved_count} zdjęć"))

        self._set_ingest_status_lines(summary_rows, "")

        enable_apply = bool((plan_count > 0 and iter_image_count == 0) or (iter_image_count > 0 and not step1_approved))
        for widget, enabled in (
            (self.btn_choose_master_pool, has_project),
            (self.btn_ingest_master_analysis, has_project),
            (self.btn_apply_ingest_plan, enable_apply),
        ):
            if widget is None:
                continue
            try:
                widget.config(state="normal" if enabled else "disabled")
            except Exception:
                pass

        self._refresh_ingest_logic_text()
        self._refresh_ingest_selection_info()
        self._refresh_ingest_balance_chart()

    def _choose_master_pool_dir(self) -> bool:
        if not CAMPAIGN.get_active_project_name():
            return False

        current = CAMPAIGN.get_master_pool_dir()
        initial = current if current and current.exists() else Path(CONFIG.DIR_1_RAW)
        dialog_title = "Wybierz obrazy tej iteracji"
        if not self._is_first_iteration_start_context():
            dialog_title = "Wybierz katalog głównej puli zdjęć dla aktywnego projektu"
        selected = filedialog.askdirectory(
            initialdir=str(initial),
            title="Wybierz katalog głównej puli zdjęć dla aktywnego projektu",
        )
        if not selected:
            return False

        if not CAMPAIGN.set_master_pool_dir(selected):
            self.app.themed_info(
                "Nieprawidłowy katalog zdjęć",
                (
                    "Wybrany katalog jest zbyt szeroki albo nie zawiera obrazów. "
                    "Wskaż konkretny katalog ze zdjęciami, a nie katalog aplikacji, Workspace ani katalog projektu."
                ),
                parent=self.frame,
                tone="warning",
            )
            return False
        try:
            self._sync_iteration_artifact_registry_from_project_start()
        except Exception:
            pass
        self.current_ingest_plan = {}
        image_count = self._count_images_in_dir(Path(selected), recursive=True)
        iter_image_count = self._get_iteration_image_count()

        if iter_image_count == 0:
            self._generate_ingest_plan()
        else:
            self._refresh_ingest_panel()

        try:
            if iter_image_count == 0:
                status_text = (
                    f"Zapisano katalog głównej puli zdjęć. Wykryto {image_count} obrazów. "
                    "Wybrany folder zdjęć został załadowany automatycznie."
                )
            else:
                status_text = (
                    f"Zapisano katalog głównej puli zdjęć. Wykryto {image_count} obrazów. "
                    "W folderze iteracji są już zdjęcia, więc aktywny pozostaje tylko etap zatwierdzenia E1."
                )
            self.app.update_status(status_text, "info")
        except Exception:
            pass
        return True

    def _build_main_pack_plan(
        self,
        master_pool_dir: Path,
        current_balance: dict | None = None,
    ) -> dict:
        master_pool_dir = Path(master_pool_dir)
        if not master_pool_dir.exists() or not master_pool_dir.is_dir():
            raise FileNotFoundError(f"Główna pula zdjęć nie istnieje: {master_pool_dir}")

        planner = CampaignIngestPlanner()
        selected_items = []
        selected_hist = Counter()
        skipped_invalid_gt = 0
        skipped_duplicate_filenames = 0
        skipped_duplicate_approved = 0
        project_overlap_filenames = 0
        pending_iteration_overlap_filenames = 0
        approved_registry = CAMPAIGN.get_used_image_registry()
        project_packet_registry = CAMPAIGN.get_project_packet_filename_registry(
            exclude_iteration_num=int(CAMPAIGN.get_current_iteration_num() or 1)
        )
        approved_names = {
            str(name or "").strip().lower()
            for name in (approved_registry.get("filenames", []) or [])
            if str(name or "").strip()
        }
        project_packet_names = {
            str(name or "").strip().lower()
            for name in (project_packet_registry.get("filenames", []) or [])
            if str(name or "").strip()
        }
        project_packet_total = int(project_packet_registry.get("total_filenames", 0) or 0)
        pending_iteration_names: set[str] = set()
        try:
            current_step = int(CAMPAIGN.get_current_step() or 1)
        except Exception:
            current_step = 1
        step1_status = str(CAMPAIGN.get_step1_status() or "").strip().lower()
        if current_step == 1 and step1_status != "approved":
            draft_plan = self._get_active_step1_draft_plan()
            if isinstance(draft_plan, dict) and draft_plan:
                latest_selected = list(draft_plan.get("selected") or [])
                latest_master_text = str(draft_plan.get("master_pool_dir") or "").strip()
                try:
                    latest_master_dir = Path(latest_master_text).resolve() if latest_master_text else None
                except Exception:
                    latest_master_dir = None
                try:
                    current_master_dir = master_pool_dir.resolve()
                except Exception:
                    current_master_dir = master_pool_dir
                if latest_selected and latest_master_dir is not None and latest_master_dir != current_master_dir:
                    pending_iteration_names = {
                        str(item.get("name", "") or "").strip().lower()
                        for item in latest_selected
                        if isinstance(item, dict) and str(item.get("name", "") or "").strip()
                    }

        current_counter = Counter()
        for ch in CHAR_ALPHABET:
            current_counter[ch] = int((current_balance or {}).get(ch, 0))

        image_paths = sorted(
            (
                image_path
                for image_path in master_pool_dir.rglob("*")
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            ),
            key=lambda p: p.as_posix().lower(),
        )
        raw_total = int(len(image_paths))

        for image_path in image_paths:
            image_name_key = str(image_path.name or "").strip().lower()
            if image_name_key and image_name_key in project_packet_names:
                skipped_duplicate_filenames += 1
                project_overlap_filenames += 1
                if image_name_key in approved_names:
                    skipped_duplicate_approved += 1
                continue
            if image_name_key and image_name_key in pending_iteration_names:
                skipped_duplicate_filenames += 1
                pending_iteration_overlap_filenames += 1
                continue

            gt_texts = planner.extract_true_texts_from_filename(image_path.name)
            if not gt_texts:
                skipped_invalid_gt += 1
                continue

            char_hist = planner.build_char_histogram(gt_texts)
            if not char_hist:
                skipped_invalid_gt += 1
                continue

            try:
                source_path = str(image_path.resolve())
            except Exception:
                source_path = str(image_path.absolute())

            selected_hist.update(char_hist)
            selected_items.append(
                {
                    "name": image_path.name,
                    "source_path": source_path,
                    "source_key": planner.make_source_key(image_path, master_pool_dir=master_pool_dir),
                    "ground_truth_texts": list(gt_texts),
                    "char_histogram": dict(char_hist),
                    "score": 0.0,
                    "score_details": {},
                }
            )

        predicted_counter = Counter(current_counter)
        predicted_counter.update(selected_hist)
        source_new_to_project_total = max(0, int(raw_total) - int(project_overlap_filenames))
        new_to_project_total = int(len(selected_items))

        return {
            "ok": True,
            "planner_version": "main_pack_v1",
            "generated_at": datetime.now().isoformat(),
            "project": CAMPAIGN.get_active_project_name() or "",
            "iteration": int(CAMPAIGN.get_current_iteration_num() or 1),
            "master_pool_dir": str(master_pool_dir.resolve()),
            "batch_size": 0,
            "raw_total": raw_total,
            "candidates_total": raw_total,
            "selected_total": len(selected_items),
            "new_to_project_total": new_to_project_total,
            "source_new_to_project_total": source_new_to_project_total,
            "skipped_used": skipped_duplicate_filenames,
            "skipped_duplicate_filenames": skipped_duplicate_filenames,
            "skipped_duplicate_approved_filenames": skipped_duplicate_approved,
            "project_overlap_filenames": project_overlap_filenames,
            "pending_iteration_overlap_filenames": pending_iteration_overlap_filenames,
            "project_pool_total_before_iteration": project_packet_total,
            "project_pool_total_after_iteration": project_packet_total + new_to_project_total,
            "skipped_invalid_ground_truth": skipped_invalid_gt,
            "current_balance": {ch: int(current_counter.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected_balance": {ch: int(selected_hist.get(ch, 0)) for ch in CHAR_ALPHABET},
            "predicted_balance_after": {ch: int(predicted_counter.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected": selected_items,
        }

    def _generate_ingest_plan(self):
        if not CAMPAIGN.get_active_project_name():
            return

        master_pool = CAMPAIGN.get_master_pool_dir()
        if master_pool is None:
            messagebox.showwarning("Brak wybranego folderu zdjęć", "Najpierw wskaż główną pulę zdjęć.")
            return
        if not master_pool.exists() or not master_pool.is_dir():
            messagebox.showwarning("Brak wybranego folderu zdjęć", f"Katalog nie istnieje:\n{master_pool}")
            return

        snapshot = CAMPAIGN.refresh_ingest_balance_snapshot()

        try:
            plan = self._build_main_pack_plan(
                master_pool_dir=master_pool,
                current_balance=(snapshot or {}).get("char_balance", {}),
            )
        except Exception as e:
            messagebox.showerror("Błąd ładowania wybranego folderu zdjęć E1", str(e))
            return

        if not plan.get("ok", False):
            messagebox.showwarning("Brak wybranego folderu zdjęć E1", str(plan.get("error", "Nie udało się załadować wybranego folderu zdjęć E1.")))
            return

        self.current_ingest_plan = plan
        self._recalculate_current_ingest_plan()
        selected_total = int(plan.get("selected_total", 0) or 0)
        raw_total = int(plan.get("raw_total", selected_total) or selected_total)
        skipped_invalid = int(plan.get("skipped_invalid_ground_truth", 0) or 0)
        skipped_duplicates = int(plan.get("skipped_duplicate_filenames", plan.get("skipped_used", 0)) or 0)
        try:
            CAMPAIGN.save_latest_ingest_plan(self.current_ingest_plan)
        except Exception:
            pass

        try:
            self._refresh_project_start_assets_table_theme(self._get_step1_ingest_frame_bg())
        except Exception:
            pass
        self._refresh_ingest_panel(snapshot_override=snapshot)
        try:
            self._refresh_active_project_wizard_only()
        except Exception:
            try:
                self._refresh_dashboard()
            except Exception:
                pass

        if selected_total <= 0:
            if skipped_duplicates > 0 and skipped_invalid <= 0:
                messagebox.showwarning(
                    "Brak nowych zdjęć do iteracji",
                    (
                        f"Wybrany folder zawiera {raw_total} zdjęć, ale wszystkie zostały odrzucone jako duble po nazwie.\n\n"
                        "Ten zestaw zdjęć nie wnosi nowych obrazów do projektu."
                    ),
                )
                return
            messagebox.showwarning(
                "Brak poprawnych pozycji w wybranym folderze zdjęć",
                (
                    "Nie znaleziono zdjęć z poprawnym ground truth w nazwie pliku.\n"
                    "Sprawdź nazewnictwo plików w głównej puli."
                ),
            )
            return

        try:
            status_text = f"Załadowano wybrany folder zdjęć E1: {raw_total} zdjęć w folderze."
            if raw_total != selected_total:
                status_text += f" Do planu E1 weszło {selected_total}."
            if skipped_duplicates > 0:
                status_text += f" Pominięto {skipped_duplicates} dubli po nazwie."
            if skipped_invalid > 0:
                status_text += f" Pominięto {skipped_invalid} plików bez poprawnego GT w nazwie."
            self.app.update_status(status_text, "info")
        except Exception:
            pass

    def _should_reuse_step1_source_despite_duplicate_plan(self, plan: dict) -> bool:
        if not isinstance(plan, dict) or not plan.get("ok", False):
            return False
        try:
            current_iter = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            current_iter = 1
        if current_iter <= 1:
            return False
        try:
            raw_total = int(plan.get("raw_total", 0) or 0)
            selected_total = int(plan.get("selected_total", 0) or 0)
            project_overlap = int(plan.get("project_overlap_filenames", 0) or 0)
            pending_overlap = int(plan.get("pending_iteration_overlap_filenames", 0) or 0)
            invalid_gt = int(plan.get("skipped_invalid_ground_truth", 0) or 0)
        except Exception:
            return False
        if raw_total <= 0 or selected_total > 0:
            return False
        if invalid_gt > 0:
            return False
        return bool(project_overlap + pending_overlap >= raw_total)

    def _build_step1_source_reuse_plan(self, base_plan: dict | None = None) -> dict:
        master_pool = CAMPAIGN.get_master_pool_dir()
        if master_pool is None:
            return {}
        try:
            master_pool = Path(master_pool)
        except Exception:
            return {}
        if not master_pool.exists() or not master_pool.is_dir():
            return {}

        image_paths = sorted(
            (
                image_path
                for image_path in master_pool.rglob("*")
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            ),
            key=lambda p: p.as_posix().lower(),
        )
        if not image_paths:
            return {}

        planner = CampaignIngestPlanner()
        selected_hist = Counter()
        selected_items = []
        skipped_invalid_gt = 0
        for image_path in image_paths:
            gt_texts = planner.extract_true_texts_from_filename(image_path.name)
            char_hist = planner.build_char_histogram(gt_texts)
            if not gt_texts or not char_hist:
                skipped_invalid_gt += 1
            selected_hist.update(char_hist)
            try:
                source_path = str(image_path.resolve())
            except Exception:
                source_path = str(image_path.absolute())
            selected_items.append(
                {
                    "name": image_path.name,
                    "source_path": source_path,
                    "source_key": planner.make_source_key(image_path, master_pool_dir=master_pool),
                    "ground_truth_texts": list(gt_texts or []),
                    "char_histogram": dict(char_hist or {}),
                    "score": 0.0,
                    "score_details": {"source_reuse": True},
                }
            )

        base_plan = dict(base_plan or {})
        raw_total = int(len(image_paths))
        project_overlap = int(base_plan.get("project_overlap_filenames", raw_total) or 0)
        pending_overlap = int(base_plan.get("pending_iteration_overlap_filenames", 0) or 0)
        source_new_total = max(0, raw_total - project_overlap)

        return {
            "ok": True,
            "planner_version": "source_reuse_v1",
            "generated_at": datetime.now().isoformat(),
            "project": CAMPAIGN.get_active_project_name() or "",
            "iteration": int(CAMPAIGN.get_current_iteration_num() or 1),
            "master_pool_dir": str(master_pool.resolve()),
            "batch_size": 0,
            "raw_total": raw_total,
            "candidates_total": raw_total,
            "selected_total": len(selected_items),
            "new_to_project_total": source_new_total,
            "source_new_to_project_total": source_new_total,
            "skipped_used": 0,
            "skipped_duplicate_filenames": 0,
            "skipped_duplicate_approved_filenames": int(base_plan.get("skipped_duplicate_approved_filenames", 0) or 0),
            "project_overlap_filenames": project_overlap,
            "pending_iteration_overlap_filenames": pending_overlap,
            "project_pool_total_before_iteration": int(base_plan.get("project_pool_total_before_iteration", project_overlap) or project_overlap),
            "project_pool_total_after_iteration": int(base_plan.get("project_pool_total_after_iteration", project_overlap + source_new_total) or (project_overlap + source_new_total)),
            "skipped_invalid_ground_truth": skipped_invalid_gt,
            "source_reuse": True,
            "current_balance": dict(base_plan.get("current_balance", {}) or {}),
            "selected_balance": {ch: int(selected_hist.get(ch, 0)) for ch in CHAR_ALPHABET},
            "predicted_balance_after": {ch: int(selected_hist.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected": selected_items,
        }

    def _ensure_current_ingest_plan_from_master_pool(self) -> bool:
        if (
            isinstance(self.current_ingest_plan, dict)
            and int(self.current_ingest_plan.get("selected_total", 0) or 0) > 0
            and self.current_ingest_plan.get("selected")
        ):
            return True

        plan = self._load_latest_ingest_plan_for_current_iteration()
        if isinstance(plan, dict) and int(plan.get("selected_total", 0) or 0) > 0 and plan.get("selected"):
            self.current_ingest_plan = dict(plan)
            self._recalculate_current_ingest_plan()
            return True

        manifest = self._load_ingest_manifest_cached()
        manifest_plan = self._build_ingest_plan_from_manifest_for_display(
            manifest,
            current_balance=(self.last_ingest_snapshot or {}).get("char_balance", {}),
        )
        if (
            isinstance(manifest_plan, dict)
            and int(manifest_plan.get("selected_total", 0) or 0) > 0
            and manifest_plan.get("selected")
        ):
            self.current_ingest_plan = manifest_plan
            self._recalculate_current_ingest_plan()
            return True

        master_pool = CAMPAIGN.get_master_pool_dir()
        if master_pool is None:
            return False
        try:
            master_pool = Path(master_pool)
        except Exception:
            return False
        if not master_pool.exists() or not master_pool.is_dir():
            return False
        if self._count_images_in_dir(master_pool, recursive=True) <= 0:
            return False

        snapshot = CAMPAIGN.refresh_ingest_balance_snapshot()
        try:
            plan = self._build_main_pack_plan(
                master_pool_dir=master_pool,
                current_balance=(snapshot or {}).get("char_balance", {}),
            )
        except Exception as e:
            logger.debug(f"Nie udało się odbudować planu E1 z wybranego katalogu: {e}")
            return False

        if not isinstance(plan, dict) or not plan.get("ok", False):
            return False
        if int(plan.get("selected_total", 0) or 0) <= 0 or not plan.get("selected"):
            if self._should_reuse_step1_source_despite_duplicate_plan(plan):
                reuse_plan = self._build_step1_source_reuse_plan(plan)
                if int(reuse_plan.get("selected_total", 0) or 0) > 0 and reuse_plan.get("selected"):
                    self.current_ingest_plan = reuse_plan
                    self._recalculate_current_ingest_plan()
                    try:
                        CAMPAIGN.save_latest_ingest_plan(self.current_ingest_plan)
                    except Exception:
                        pass
                    return True
            return False

        self.current_ingest_plan = plan
        self._recalculate_current_ingest_plan()
        try:
            CAMPAIGN.save_latest_ingest_plan(self.current_ingest_plan)
        except Exception:
            pass
        return True

    def _remove_selected_ingest_items(self):
        if self.ingest_plan_listbox is None or not self.current_ingest_plan:
            return

        selected_indices = list(self.ingest_plan_listbox.curselection())
        if not selected_indices:
            return

        selected_indices = sorted(selected_indices, reverse=True)
        plan_items = list(self.current_ingest_plan.get("selected", []) or [])
        for idx in selected_indices:
            if 0 <= idx < len(plan_items):
                plan_items.pop(idx)

        self.current_ingest_plan["selected"] = plan_items
        self._recalculate_current_ingest_plan()
        try:
            CAMPAIGN.save_latest_ingest_plan(self.current_ingest_plan)
        except Exception:
            pass
        self._refresh_ingest_panel()
        try:
            self._refresh_active_project_wizard_only()
        except Exception:
            try:
                self._refresh_dashboard()
            except Exception:
                pass

    def _ensure_step1_iteration_target_selected(self) -> bool:
        if self._get_iteration_target() in {"plate", "char"}:
            return True

        try:
            self.step1_panel_expanded = True
            self.request_wizard_stage_focus(step_num=1)
            self._refresh_active_project_wizard_only()
        except Exception:
            pass

        message = (
            "Zanim zatwierdzisz E1, wybierz tor tej iteracji w panelu E1.\n\n"
            "E2 jest etapem pracy na tablicach: w torze tablic prowadzi dalej do treningu tablic, "
            "a w torze znaków przygotowuje źródło dla E3/Z3."
        )
        try:
            self.app.themed_info(
                "Wybierz tor iteracji E1",
                message,
                parent=self.frame,
                tone="warning",
            )
        except Exception:
            messagebox.showwarning("Wybierz tor iteracji E1", message)
        return False

    def _continue_to_step3_after_step1_if_char_ready(self) -> bool:
        if self._get_iteration_target() != "char":
            return False
        if str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved":
            return False
        if int(CAMPAIGN.get_current_step() or 1) < 2:
            return False

        preflight = self._get_step1_char_route_preflight_state()
        if not bool(preflight.get("material_ready")):
            return False

        ready_source = self._get_char_route_ready_source()
        if not ready_source:
            return False

        logger.debug(
            "[CampaignTab] Tor znaków ma gotowe źródło tablic po E1, ale E2 nie jest zatwierdzane automatycznie. "
            "Użytkownik musi jawnie użyć badge'a E2."
        )
        return False

    def _approve_current_iteration_package(
        self,
        target_iter_dir: Path,
        source_dir: Path = None,
        selected_source_files=None,
        selection_mode: str = "manual",
        proposal_summary: dict = None,
    ) -> int:
        target_iter_dir = Path(target_iter_dir)
        target_iter_dir.mkdir(parents=True, exist_ok=True)

        selected_files = list(selected_source_files or [])
        if not selected_files:
            selected_files = [
                image_path for image_path in target_iter_dir.iterdir()
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            ]

        summary_payload = dict(proposal_summary or {})
        package_count = int(len(selected_files) or 0)
        new_to_project_count = int(
            summary_payload.get(
                "new_to_project_count",
                package_count,
            ) or 0
        )

        approved_stats = self._get_plate_approved_set_stats() or {}
        approved_images_before = int(summary_payload.get("approved_images_before_iteration", approved_stats.get("images", 0)) or 0)
        approved_plates_before = int(summary_payload.get("approved_plates_before_iteration", approved_stats.get("plates", 0)) or 0)
        project_pool_total_before = int(
            summary_payload.get(
                "project_pool_total_before_iteration",
                approved_images_before,
            ) or 0
        )
        project_pool_total_after = int(
            summary_payload.get(
                "project_pool_total_after_iteration",
                max(project_pool_total_before, approved_images_before) + new_to_project_count,
            ) or 0
        )

        if package_count > 0 and "source_total" not in summary_payload:
            summary_payload["source_total"] = package_count
        summary_payload["current_iteration_package_count"] = package_count
        summary_payload["new_to_project_count"] = new_to_project_count
        summary_payload["project_pool_total_before_iteration"] = project_pool_total_before
        summary_payload["project_pool_total_after_iteration"] = project_pool_total_after
        summary_payload["approved_images_before_iteration"] = approved_images_before
        summary_payload["approved_plates_before_iteration"] = approved_plates_before

        source_root = Path(source_dir) if source_dir else target_iter_dir
        try:
            CAMPAIGN.record_iteration_ingest(
                source_dir=source_root,
                selected_source_files=selected_files,
                selection_mode=selection_mode,
                proposal_summary=summary_payload,
            )
        except Exception as e:
            logger.debug(f"Nie udało się zapisać manifestu E1 dla {target_iter_dir}: {e}")

        CAMPAIGN.approve_step1()
        if CAMPAIGN.get_current_step() < 2:
            CAMPAIGN.set_current_step(2)
        self.step1_panel_expanded = False
        if self._continue_to_step3_after_step1_if_char_ready():
            self.current_ingest_plan = {}
            return len(selected_files)
        self.current_ingest_plan = {}
        self._refresh_dashboard()
        return len(selected_files)

    def _apply_current_ingest_plan(self):
        if not CAMPAIGN.get_active_project_name():
            return
        if CAMPAIGN.get_step1_status() != "approved" and not self._ensure_step1_iteration_target_selected():
            return
        if not self.current_ingest_plan:
            try:
                self._ensure_current_ingest_plan_from_master_pool()
            except Exception as e:
                logger.debug(f"Nie udało się przygotować planu E1 przed zatwierdzeniem: {e}")
        if not self.current_ingest_plan:
            raw_dir = CAMPAIGN.get_dir("raw")
            if raw_dir is None:
                return
            iter_num = CAMPAIGN.get_current_iteration_num()
            target_iter_dir = CAMPAIGN.get_iteration_raw_dir(iter_num) or (Path(raw_dir) / f"Iteracja_{iter_num:03d}")

            try:
                manifest = CAMPAIGN.load_ingest_manifest(iter_num) or {}
            except Exception:
                manifest = {}
            manifest_images = []
            if isinstance(manifest, dict):
                try:
                    manifest_images = list(CAMPAIGN.get_iteration_manifest_image_paths(iter_num) or [])
                except Exception:
                    manifest_images = []

            source_dir = CAMPAIGN.get_iteration_image_source_dir(iter_num) or target_iter_dir
            selected_images = list(manifest_images or [])
            if not selected_images and target_iter_dir.exists() and target_iter_dir.is_dir():
                selected_images = [
                    image_path for image_path in target_iter_dir.iterdir()
                    if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
                ]
                source_dir = target_iter_dir

            if not selected_images:
                messagebox.showwarning("Brak wybranego folderu zdjęć E1", "Załaduj najpierw wybrany folder zdjęć E1.")
                return
            if not self._validate_step1_char_preflight_for_approval():
                return
            if CAMPAIGN.get_step1_status() != "approved":
                selection_mode = (
                    str((manifest or {}).get("selection_mode", "") or "").strip()
                    if isinstance(manifest, dict)
                    else ""
                ) or ("planned_manifest" if manifest_images else "existing")
                should_approve = self.app.themed_confirm(
                    "Zatwierdzenie E1",
                    (
                        f"Wybrany katalog zdjęć zawiera {len(selected_images)} obrazów dla bieżącej iteracji:\n{source_dir}\n\n"
                        "Czy zatwierdzić ten zestaw zdjęć jako E1 i odblokować E2?"
                    ),
                    parent=self.frame,
                    confirm_label="Zatwierdź",
                    tone="info",
                )
                if not should_approve:
                    return
                self._approve_current_iteration_package(
                    target_iter_dir=target_iter_dir,
                    source_dir=source_dir,
                    selected_source_files=selected_images,
                    selection_mode=selection_mode,
                )
            return

        selected_items = list(self.current_ingest_plan.get("selected", []) or [])
        if not selected_items:
            messagebox.showwarning("Brak wybranego folderu zdjęć E1", "Załaduj najpierw wybrany folder zdjęć E1.")
            return
        if not self._validate_step1_char_preflight_for_approval():
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        if raw_dir is None:
            logger.error("Brak katalogu raw dla aktywnego projektu.")
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        target_iter_dir = CAMPAIGN.get_iteration_raw_dir(iter_num) or (Path(raw_dir) / f"Iteracja_{iter_num:03d}")
        target_iter_dir.mkdir(parents=True, exist_ok=True)

        selected_source_files = []
        for item in selected_items:
            source_path = Path(str(item.get("source_path", "") or "").strip())
            if not source_path.exists() or not source_path.is_file():
                continue
            selected_source_files.append(source_path)

        if not selected_source_files:
            messagebox.showwarning(
                "Brak obrazów w manifeście E1",
                "Nie udało się odczytać obrazów z wybranego katalogu zdjęć. Wybierz katalog ponownie.",
            )
            return

        selection_mode = str(self.current_ingest_plan.get("selection_mode") or "").strip()
        if not selection_mode:
            selection_mode = "source_reuse" if bool(self.current_ingest_plan.get("source_reuse")) else "planned_manifest"
        source_dir_text = str(self.current_ingest_plan.get("source_dir") or self.current_ingest_plan.get("master_pool_dir") or "").strip()
        source_dir = Path(source_dir_text) if source_dir_text else (CAMPAIGN.get_master_pool_dir() or target_iter_dir)
        try:
            if source_dir is None or not Path(source_dir).exists() or not Path(source_dir).is_dir():
                source_dir = selected_source_files[0].parent
        except Exception:
            source_dir = selected_source_files[0].parent
        self._approve_current_iteration_package(
            target_iter_dir=target_iter_dir,
            source_dir=source_dir,
            selected_source_files=selected_source_files,
            selection_mode=selection_mode,
            proposal_summary={
                "planner_version": self.current_ingest_plan.get("planner_version", ""),
                "generated_at": self.current_ingest_plan.get("generated_at", ""),
                "source_total": self.current_ingest_plan.get("raw_total", 0),
                "selected_total": self.current_ingest_plan.get("selected_total", 0),
                "current_iteration_package_count": self.current_ingest_plan.get("selected_total", 0),
                "batch_size": self.current_ingest_plan.get("batch_size", 0),
                "skipped_duplicate_filenames": self.current_ingest_plan.get("skipped_duplicate_filenames", self.current_ingest_plan.get("skipped_used", 0)),
                "skipped_duplicate_approved_filenames": self.current_ingest_plan.get("skipped_duplicate_approved_filenames", 0),
                "project_overlap_filenames": self.current_ingest_plan.get("project_overlap_filenames", 0),
                "new_to_project_count": self.current_ingest_plan.get("new_to_project_total", 0),
                "skipped_invalid_ground_truth": self.current_ingest_plan.get("skipped_invalid_ground_truth", 0),
            },
        )

        try:
            self.app.update_status(
                f"Zatwierdzono E1 manifestem: {len(selected_source_files)} zdjęć z wybranego katalogu. Odblokowano Krok 2.",
                "info",
            )
        except Exception:
            pass

        messagebox.showinfo(
            "E1 zatwierdzone",
            f"Zapisano manifest iteracji {iter_num:03d}: {len(selected_source_files)} zdjęć.\n\n"
            "Zdjęcia nie są kopiowane do kolejnej iteracji. Program będzie korzystał z wybranego katalogu źródłowego.",
        )

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        bg = palette.get("bg", "#1e1e1e")
        panel = palette.get("panel", "#252526")
        panel_alt = palette.get("surface_info", palette.get("panel_alt", panel))
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")

        try:
            self.app.style_panel_surface(self.frame, background=panel)
        except Exception:
            pass

        try:
            if getattr(self, "header_frame", None) is not None:
                self.header_frame.config(bg=panel)
            if getattr(self, "proj_frame", None) is not None:
                self.proj_frame.config(bg=panel)
        except Exception:
            pass

        try:
            self.lbl_title.config(bg=panel, fg=fg)
        except Exception:
            pass

        try:
            self._configure_campaign_banner(bg=panel)
        except Exception:
            pass

        try:
            if self.wizard_header_title_lbl is not None:
                self.wizard_header_title_lbl.config(bg=panel, fg=fg)
        except Exception:
            pass

        try:
            if self.wizard_header_summary_lbl is not None:
                self.wizard_header_summary_lbl.config(bg=panel, fg=muted)
        except Exception:
            pass

        try:
            self.left_panel_hint_lbl.config(bg=panel, fg=muted)
        except Exception:
            pass

        try:
            if getattr(self, "left_panel_canvas", None) is not None:
                self.left_panel_canvas.config(bg=panel)
        except Exception:
            pass

        try:
            if getattr(self, "right_panel_canvas", None) is not None:
                self.right_panel_canvas.config(bg=panel)
        except Exception:
            pass

        try:
            if self.project_list_status_lbl is not None:
                self.project_list_status_lbl.config(bg=panel)
            if self.project_status_top_row is not None:
                self.project_status_top_row.config(bg=panel)
            for lbl in getattr(self, "project_list_status_labels", []):
                lbl.config(bg=panel, fg=muted)
        except Exception:
            pass

        try:
            if self.project_list_host is not None:
                green = self._get_campaign_green_accent()
                self.project_list_host.config(
                    bg=palette.get("field", "#1a1a1a"),
                    highlightbackground=green,
                    highlightcolor=green
                )
        except Exception:
            pass

        try:
            if self.project_listbox is not None:
                green = self._get_campaign_green_accent()
                self.project_listbox.config(
                    bg=palette.get("field", "#1a1a1a"),
                    fg=fg,
                    selectbackground=self._get_project_list_selection_bg(),
                    selectforeground=self._get_project_list_selection_fg(),
                    highlightbackground=green,
                    highlightcolor=green,
                )
        except Exception:
            pass

        try:
            green = self._get_campaign_green_accent()
            if getattr(self, "project_list_scrollbar", None) is not None:
                self.project_list_scrollbar.configure_style(
                    track_color=palette.get("field", "#1a1a1a"),
                    thumb_color=green,
                    thumb_hover_color=blend_hex_colors(green, "#ffffff", 0.18),
                )
            if getattr(self, "left_panel_scrollbar", None) is not None:
                self.left_panel_scrollbar.configure_style(
                    track_color=palette.get("panel", "#252526"),
                    thumb_color=green,
                    thumb_hover_color=blend_hex_colors(green, "#ffffff", 0.18),
                )
            if getattr(self, "right_panel_scrollbar", None) is not None:
                self.right_panel_scrollbar.configure_style(
                    track_color=palette.get("panel", "#252526"),
                    thumb_color=green,
                    thumb_hover_color=blend_hex_colors(green, "#ffffff", 0.18),
                )
        except Exception:
            pass

        try:
            if self.project_browser_footer is not None:
                self.project_browser_footer.config(bg=panel)
            if self.project_add_button_canvas is not None:
                self.project_add_button_canvas.config(bg=panel)
            if self.wizard_exit_button_canvas is not None:
                self.wizard_exit_button_canvas.config(bg=panel)
        except Exception:
            pass

        for widget_name in (
            "ingest_header_lbl",
            "ingest_intro_lbl",
            "lbl_ingest_master_title",
            "lbl_ingest_master_value",
            "lbl_ingest_batch_title",
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(bg=panel)
            except Exception:
                pass
        self._theme_step1_ingest_panel()
        self._draw_wizard_stage_metro()
        self._draw_icon_button("project_add")
        self._draw_icon_button("exit_project")

        try:
            if self.ingest_plan_host is not None:
                self.ingest_plan_host.config(
                    bg=palette.get("field", "#1a1a1a"),
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
                )
        except Exception:
            pass

        try:
            if self.ingest_plan_listbox is not None:
                select_bg, select_fg = self.app.get_list_selection_colors()
                self.ingest_plan_listbox.config(
                    bg=palette.get("field", "#1a1a1a"),
                    fg=fg,
                    selectbackground=select_bg,
                    selectforeground=select_fg,
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("accent", "#2980b9"),
                )
        except Exception:
            pass

        for lbl in getattr(self, "_model_status_title_labels", []):
            try:
                lbl.config(bg=panel, fg=fg)
            except Exception:
                pass

        for model_type in ("vehicle", "plate", "char"):
            lbl_val = getattr(self, f"lbl_model_{model_type}", None)
            if lbl_val is not None:
                try:
                    lbl_val.config(bg=panel)
                except Exception:
                    pass
            lbl_meta = getattr(self, f"lbl_model_{model_type}_meta", None)
            if lbl_meta is not None:
                try:
                    lbl_meta.config(bg=panel, fg=palette.get("muted", "#b0b0b0"))
                except Exception:
                    pass

        try:
            self._refresh_dashboard()
        except Exception:
            pass

    def _ask_project_from_list(self, title="Wybierz projekt", action_label="OK"):
        """Wyświetla modalny wybór projektu i zwraca nazwę albo None."""
        projects = CAMPAIGN.get_all_projects()
        if not projects:
            self.app.themed_info("Brak projektów", "Nie ma żadnych zapisanych projektów.", parent=self.frame)
            return None

        dialog = tk.Toplevel(self.frame)
        self.app.style_dialog_window(dialog, title=title, geometry="460x300", parent=self.frame)
        palette = self.app.palette

        shell = tk.Frame(
            dialog,
            bg=palette["bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette["border"]),
            highlightcolor=palette.get("panel_border", palette["border"])
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        body = tk.Frame(shell, bg=palette["panel"])
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text=title,
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 11, "bold")
        ).pack(anchor=tk.W, padx=16, pady=(16, 8))

        tk.Label(
            body,
            text="Wybierz projekt z listy:",
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 10)
        ).pack(anchor=tk.W, padx=16, pady=(0, 6))

        list_frame = tk.Frame(body, bg=palette["panel"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        scroll = WebSlimScrollbar(list_frame, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        select_bg, select_fg = self.app.get_list_selection_colors()

        project_list = tk.Listbox(
            list_frame,
            exportselection=False,
            font=("Segoe UI", 10),
            bg=palette["field"],
            fg=palette["fg"],
            selectbackground=select_bg,
            selectforeground=select_fg,
            activestyle="none",
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette["border"]),
            highlightcolor=palette.get("panel_border", palette["border"]),
            yscrollcommand=scroll.set,
        )
        project_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=project_list.yview)

        for project in projects:
            project_list.insert(tk.END, project)
        project_list.selection_set(0)
        project_list.activate(0)
        project_list.focus_set()

        result = {"value": None}

        btn_row = tk.Frame(body, bg=palette["panel"])
        btn_row.pack(fill=tk.X, padx=16, pady=(0, 16))

        def accept():
            selection = project_list.curselection()
            if selection:
                result["value"] = project_list.get(selection[0]).strip()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        ttk.Button(btn_row, text=action_label, command=accept, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Anuluj", command=cancel).pack(side=tk.RIGHT, padx=(0, 8))

        project_list.bind("<Double-Button-1>", lambda _e: accept())
        fit_dialog = getattr(self.app, "_fit_dialog_to_content", None)
        if callable(fit_dialog):
            fit_dialog(dialog, parent=self.frame, min_width=460, min_height=300)
        dialog.bind("<Return>", lambda _e: accept())
        dialog.bind("<Escape>", lambda _e: cancel())
        dialog.wait_window()
        return result["value"]

    def _ask_iteration_advance_mode(self, *, completed_with_training: bool = True):
        dialog = tk.Toplevel(self.frame)
        self.app.style_dialog_window(dialog, title="Co dalej po E4", geometry="620x300", parent=self.frame)
        palette = self.app.palette
        try:
            parent_window = getattr(self.app, "root", None) or self.frame.winfo_toplevel()
        except Exception:
            parent_window = None
        try:
            if parent_window is not None:
                dialog.transient(parent_window)
        except Exception:
            pass

        shell = tk.Frame(
            dialog,
            bg=palette["bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette["border"]),
            highlightcolor=palette.get("panel_border", palette["border"])
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        body = tk.Frame(shell, bg=palette["panel"])
        body.pack(fill=tk.BOTH, expand=True)

        header_text = (
            "E4 jest gotowe do zamknięcia. Możesz przejść do E1 kolejnej iteracji."
            if completed_with_training
            else "E4 może zostać zamknięte bez treningu. Możesz przejść do E1."
        )
        intro_text = (
            "Jeśli wybierzesz przejście dalej, bieżąca iteracja zostanie domknięta, a nowa rozpocznie się w E1. "
            "Tam wybierzesz katalog zdjęć wejściowych, tor pracy oraz zatwierdzisz zdjęcia startowe. "
            "Aktywne modele projektu pozostają dostępne."
            if completed_with_training
            else "Jeśli wybierzesz przejście dalej, iteracja zostanie formalnie zamknięta bez treningu. "
            "Kolejny cykl rozpocznie się w E1, gdzie wybierzesz katalog zdjęć wejściowych, tor pracy "
            "oraz zatwierdzisz zdjęcia startowe. Modele projektu pozostają dostępne."
        )

        tk.Label(
            body,
            text=header_text,
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 11, "bold")
        ).pack(anchor=tk.W, padx=16, pady=(16, 6))

        tk.Label(
            body,
            text=intro_text,
            bg=palette["panel"],
            fg=palette.get("muted", palette["fg"]),
            font=("Segoe UI", 10),
            justify=tk.LEFT,
            wraplength=600
        ).pack(anchor=tk.W, padx=16, pady=(0, 12))

        result = {"value": None}

        def choose(mode: str):
            result["value"] = mode
            dialog.destroy()

        def choose_e1_transition():
            mode = "new_input"
            try:
                stage_state = CAMPAIGN.get_manual_plate_stage_images_state()
                if int(stage_state.get("image_count", 0) or 0) > 0:
                    mode = "reuse_input"
            except Exception:
                mode = "new_input"
            choose(mode)

        def cancel():
            dialog.destroy()

        info_card = tk.Frame(
            body,
            bg=palette["field"],
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette["border"]),
            highlightcolor=palette.get("panel_border", palette["border"]),
        )
        info_card.pack(fill=tk.X, padx=16, pady=(0, 14))
        tk.Label(
            info_card,
            text="Co stanie się po przejściu?",
            bg=palette["field"],
            fg=palette["fg"],
            font=("Segoe UI", 10, "bold"),
            justify=tk.LEFT,
            anchor=tk.W,
        ).pack(anchor=tk.W, fill=tk.X, padx=14, pady=(12, 4))
        tk.Label(
            info_card,
            text=(
                "Program utworzy kolejną iterację, wyczyści roboczy stan E2-E4 i otworzy E1. "
                "W E1 ustawisz wejścia, wybierzesz tor tablic albo znaków i zatwierdzisz etap dopiero wtedy, "
                "gdy zdjęcia startowe będą gotowe."
            ),
            bg=palette["field"],
            fg=palette.get("muted", palette["fg"]),
            font=("Segoe UI", 9),
            justify=tk.LEFT,
            anchor=tk.W,
            wraplength=540,
        ).pack(anchor=tk.W, fill=tk.X, padx=14, pady=(0, 12))

        btn_row = tk.Frame(body, bg=palette["panel"])
        btn_row.pack(fill=tk.X, padx=16, pady=(0, 16))
        ttk.Button(
            btn_row,
            text="Przejdź do E1",
            command=choose_e1_transition,
            style="Accent.TButton",
        ).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Zostań w E4", command=cancel).pack(side=tk.RIGHT, padx=(0, 8))

        fit_dialog = getattr(self.app, "_fit_dialog_to_content", None)
        if callable(fit_dialog):
            fit_dialog(dialog, parent=self.frame, min_width=620, min_height=300)
        try:
            dialog.lift()
            dialog.grab_set()
        except Exception:
            pass
        try:
            dialog.focus_force()
        except Exception:
            try:
                dialog.focus_set()
            except Exception:
                pass
        dialog.bind("<Escape>", lambda _e: cancel())
        dialog.wait_window()
        return result["value"]

    def _set_model(self, model_type, initial_dir: Path | None = None):
        # Otwórz wybór modelu od katalogu modeli aktywnego projektu.
        if initial_dir is None:
            initial_dir = CAMPAIGN.get_dir("models")
            if initial_dir is None:
                initial_dir = Path(CONFIG.DIR_6_MODELS)
            else:
                initial_dir = Path(initial_dir)
        else:
            initial_dir = Path(initial_dir)

        p = filedialog.askopenfilename(
            initialdir=str(initial_dir),
            filetypes=[("YOLO Model", "*.pt")]
        )
        if p:
            model_path = Path(p)
            is_valid, error_message = self._validate_project_model_selection(model_type, model_path)
            if not is_valid:
                self.app.themed_error(
                    "Nieprawidlowy model",
                    error_message,
                    parent=self.frame,
                )
                return
            CAMPAIGN.set_global_model(model_type, str(model_path))
            row_key = "plate_model" if str(model_type or "").strip().lower() == "plate" else "char_model"
            self._set_project_start_asset_scope(
                row_key,
                self._infer_project_start_asset_scope_from_path(row_key, model_path),
            )
            try:
                self._sync_iteration_artifact_registry_from_project_start()
            except Exception:
                pass
            self._refresh_dashboard()

    # ======================================================
    # WIZARD UI
    # ======================================================

    def _toggle_step1_panel(self):
        if not CAMPAIGN.get_active_project_name():
            return
        if CAMPAIGN.get_current_step() != 1:
            return

        self.step1_panel_expanded = not bool(self.step1_panel_expanded)
        self._rebuild_wizard_stage_ui()
        self._refresh_dashboard()

    def _rebuild_wizard_stage_ui(self):
        wizard_parent = self.right_content if self.right_content is not None else self.right_panel
        for widget in wizard_parent.winfo_children():
            widget.destroy()
        self.step1_ingest_host_item = None
        self.wizard_stage_cards = {}

        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")

        header_shell = tk.Frame(wizard_parent, bg=panel_bg, bd=0, highlightthickness=0)
        header_shell.pack(fill=tk.X, pady=(0, 8))
        self.wizard_header_shell = header_shell
        self.wizard_header_title_lbl = tk.Label(
            header_shell,
            text="Etapy projektu",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 13, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=panel_bg,
        )
        self.wizard_header_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.wizard_header_summary_lbl = tk.Label(
            header_shell,
            text="Stan projektu i kolejny krok.",
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
            fg=palette.get("muted", "#c7c7c7"),
            bg=panel_bg,
        )
        self.wizard_header_summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 0))

        self.wizard_empty_state_card = self._build_wizard_stage_card(
            wizard_parent,
            "empty",
            help_key="camp_open_project",
        )
        self.wizard_stage_cards_host = tk.Frame(wizard_parent, bg=panel_bg, bd=0, highlightthickness=0)
        self.wizard_stage_cards_host.pack(fill=tk.X)

        for key, help_key in (
            ("step1", "camp_step1"),
            ("step2", "camp_step2"),
            ("step3", "camp_step3"),
            ("step4", "camp_advance"),
        ):
            self.wizard_stage_cards[key] = self._build_wizard_stage_card(
                self.wizard_stage_cards_host,
                key,
                help_key=help_key,
            )

        self.step1_ingest_host_item = {
            "step_num": 1,
            "extra_actions_frame": self.wizard_stage_cards["step1"]["body"],
        }
        try:
            self._build_ingest_panel(self.wizard_stage_cards["step1"]["body"])
        except Exception as e:
            logger.debug(f"Nie udało się zbudować panelu E1 w nowym wizardzie: {e}")

        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self.frame.after_idle(self._sync_right_panel_canvas_width)

    def _set_pack_visibility(self, widget, visible: bool, **pack_kwargs):
        if widget is None:
            return
        try:
            manager = str(widget.winfo_manager())
        except Exception:
            manager = ""

        if visible:
            if manager != "pack":
                try:
                    widget.pack(**pack_kwargs)
                except Exception:
                    try:
                        fallback_kwargs = {
                            key: value
                            for key, value in dict(pack_kwargs or {}).items()
                            if key not in {"before", "after", "in_"}
                        }
                        widget.pack(**fallback_kwargs)
                    except Exception:
                        pass
            return

        if manager == "pack":
            try:
                widget.pack_forget()
            except Exception:
                pass

    def _set_grid_visibility(self, widget, visible: bool):
        if widget is None:
            return
        try:
            manager = str(widget.winfo_manager())
        except Exception:
            manager = ""

        if visible:
            if manager != "grid":
                try:
                    widget.grid()
                except Exception:
                    pass
            return

        if manager == "grid":
            try:
                widget.grid_remove()
            except Exception:
                pass

    def _cancel_wizard_stage_curtain_animation(self, card: dict):
        if not isinstance(card, dict):
            return
        pending = card.get("curtain_after_id")
        if not pending:
            return
        try:
            self.frame.after_cancel(pending)
        except Exception:
            pass
        card["curtain_after_id"] = None

    def _set_wizard_stage_curtain_height(self, card: dict, height: int):
        if not isinstance(card, dict):
            return
        clip = card.get("curtain_clip")
        toggle = card.get("curtain_toggle")
        if clip is None:
            return
        normalized_height = max(0, int(height))
        try:
            manager = str(clip.winfo_manager())
        except Exception:
            manager = ""
        if normalized_height <= 0:
            if manager == "pack":
                try:
                    clip.pack_forget()
                except Exception:
                    pass
        elif manager != "pack":
            try:
                clip.pack(fill=tk.X, pady=(0, 0), after=toggle)
            except Exception:
                try:
                    clip.pack(fill=tk.X, pady=(0, 0))
                except Exception:
                    pass
        try:
            clip.configure(height=normalized_height)
        except Exception:
            pass
        try:
            if normalized_height > 0:
                clip.pack_configure(pady=(6, 0))
        except Exception:
            pass
        try:
            self.frame.after_idle(self._sync_right_panel_scrollregion)
        except Exception:
            pass

    def _animate_wizard_stage_curtain(self, card: dict, expand: bool):
        if not isinstance(card, dict):
            return

        clip = card.get("curtain_clip")
        inner = card.get("curtain_inner")
        shell = card.get("curtain_shell")
        action_row = card.get("action_row")
        if clip is None or inner is None or shell is None:
            return

        self._cancel_wizard_stage_curtain_animation(card)
        self._set_pack_visibility(shell, True, fill=tk.X, pady=(10, 0), before=action_row)
        if expand:
            try:
                if str(clip.winfo_manager()) != "pack":
                    clip.pack(fill=tk.X, pady=(0, 0), after=card.get("curtain_toggle"))
            except Exception:
                try:
                    clip.pack(fill=tk.X, pady=(0, 0))
                except Exception:
                    pass

        try:
            inner.update_idletasks()
            clip.update_idletasks()
        except Exception:
            pass

        start_height = 0
        try:
            start_height = int(clip.cget("height") or 0)
        except Exception:
            try:
                start_height = int(clip.winfo_height() or 0)
            except Exception:
                start_height = 0

        target_height = 0
        if expand:
            try:
                target_height = max(0, int(inner.winfo_reqheight() or 0))
            except Exception:
                target_height = 0

        if start_height == target_height:
            self._set_wizard_stage_curtain_height(card, target_height)
            card["curtain_expanded"] = bool(expand)
            return

        total_steps = 10
        interval_ms = 18
        delta = target_height - start_height

        def _tick(step_index: int = 0):
            ratio = float(step_index + 1) / float(total_steps)
            eased = ratio * ratio * (3.0 - (2.0 * ratio))
            current_height = int(round(start_height + (delta * eased)))
            self._set_wizard_stage_curtain_height(card, current_height)
            if (step_index + 1) < total_steps:
                try:
                    card["curtain_after_id"] = self.frame.after(interval_ms, lambda: _tick(step_index + 1))
                except Exception:
                    card["curtain_after_id"] = None
            else:
                card["curtain_after_id"] = None
                self._set_wizard_stage_curtain_height(card, target_height)
                card["curtain_expanded"] = bool(expand)

        _tick(0)

    def _toggle_wizard_stage_curtain(self, stage_key: str):
        card = self.wizard_stage_cards.get(str(stage_key or "").strip())
        if not isinstance(card, dict):
            return "break"
        if not bool(card.get("curtain_visible", False)):
            return "break"

        card["curtain_user_touched"] = True
        expand = not bool(card.get("curtain_expanded", False))
        card["curtain_expanded"] = expand
        self._refresh_wizard_stage_curtain_style(card)
        self._animate_wizard_stage_curtain(card, expand)
        return "break"

    def _collapse_wizard_stage_curtain(self, stage_key: str, *, reset_user_touched: bool = True):
        card = self.wizard_stage_cards.get(str(stage_key or "").strip())
        if not isinstance(card, dict):
            return

        card["curtain_expanded"] = False
        if reset_user_touched:
            card["curtain_user_touched"] = False

        self._cancel_wizard_stage_curtain_animation(card)
        self._set_wizard_stage_curtain_height(card, 0)
        self._refresh_wizard_stage_curtain_style(card)

    def _collapse_all_wizard_stage_curtains(self, *, reset_user_touched: bool = True):
        for stage_key in list(getattr(self, "wizard_stage_cards", {}).keys()):
            try:
                self._collapse_wizard_stage_curtain(stage_key, reset_user_touched=reset_user_touched)
            except Exception:
                pass

    def _refresh_wizard_stage_curtain_style(self, card: dict):
        if not isinstance(card, dict):
            return

        palette = getattr(self.app, "palette", {})
        card_bg = palette.get("panel", "#252526")
        muted = palette.get("muted", "#c7c7c7")
        fg = palette.get("fg", "#f3f3f3")
        success = palette.get("success", "#27ae60")
        border = str(card.get("curtain_border", "") or palette.get("panel_border", palette.get("border", "#3c3c3c")))
        surface = str(card.get("curtain_surface", "") or palette.get("panel_alt", card_bg))
        expanded = bool(card.get("curtain_expanded", False))
        indicator_text = "▾" if expanded else "▸"

        for widget_name in ("curtain_shell", "curtain_clip", "curtain_inner"):
            widget = card.get(widget_name)
            if widget is None:
                continue
            try:
                widget.configure(bg=card_bg)
            except Exception:
                pass

        toggle = card.get("curtain_toggle")
        if toggle is not None:
            try:
                toggle.configure(
                    bg=surface,
                    highlightbackground=border,
                    highlightcolor=border,
                )
            except Exception:
                pass

        for widget_name in ("curtain_text_col", "curtain_table"):
            widget = card.get(widget_name)
            if widget is None:
                continue
            try:
                widget.configure(bg=surface, highlightbackground=border, highlightcolor=border)
            except Exception:
                pass

        indicator = card.get("curtain_indicator")
        if indicator is not None:
            try:
                indicator.configure(text=indicator_text, bg=surface, fg=success)
            except Exception:
                pass

        title = card.get("curtain_title")
        if title is not None:
            try:
                title.configure(bg=surface, fg=fg)
            except Exception:
                pass

        meta = card.get("curtain_meta")
        if meta is not None:
            try:
                meta.configure(bg=surface, fg=muted)
            except Exception:
                pass

    def _format_campaign_summary_path(self, path_like, *, fallback: str = "—", max_len: int = 78) -> str:
        raw = str(path_like or "").strip()
        if not raw:
            return fallback

        try:
            candidate = Path(raw).expanduser()
        except Exception:
            return shorten(raw, width=max(12, int(max_len)), placeholder="…")

        display = str(candidate)
        try:
            candidate_resolved = candidate.resolve()
        except Exception:
            candidate_resolved = candidate

        project_root = None
        try:
            project_root = CAMPAIGN.get_active_project_root_dir()
        except Exception:
            project_root = None

        for base in (
            project_root,
            Path(CONFIG.WORKSPACE_DIR),
        ):
            if base is None:
                continue
            try:
                display = str(candidate_resolved.relative_to(Path(base).resolve()))
                break
            except Exception:
                continue

        display = str(display).replace("\\", "/")
        return shorten(display, width=max(16, int(max_len)), placeholder="…")

    @staticmethod
    def _format_step1_selection_mode_label(selection_mode: str) -> str:
        normalized = str(selection_mode or "").strip().lower()
        labels = {
            "planned": "Wybrano zdjęcia z głównego katalogu zdjęć",
            "manual": "Wskazano katalog zdjęć ręcznie",
            "existing": "Użyto gotowego katalogu iteracji",
            "iteration_reuse": "Użyto tego samego zestawu zdjęć co poprzednio",
            "pool_reuse": "Przygotowano kolejny zestaw zdjęć z tej samej puli projektu",
            "stage_reuse": "Przejęto zdjęcia oczekujące w stage po poprzedniej iteracji",
        }
        return labels.get(normalized, "Tryb przygotowania nie jest jeszcze znany")

    @staticmethod
    def _format_effective_stage_reuse_label(base_count: int, manual_reuse_count: int) -> str:
        return f"Ten sam zestaw pracy: stage ({int(base_count)}) + wcześniejsze ręczne korekty ({int(manual_reuse_count)})"

    @staticmethod
    def _load_plate_annotated_filenames_from_xml(xml_path: Path | None) -> set[str]:
        if xml_path is None or not xml_path.exists():
            return set()
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception:
            return set()

        filenames: set[str] = set()
        for image_el in root.findall(".//image"):
            filename = str(image_el.get("name", "") or "").strip()
            if not filename:
                continue
            has_plate = False
            for poly_el in image_el.findall("polygon"):
                label = str(poly_el.get("label", "") or "").strip().lower()
                if label in CONFIG.PLATE_LABELS:
                    has_plate = True
                    break
            if not has_plate:
                for box_el in image_el.findall("box"):
                    label = str(box_el.get("label", "") or "").strip().lower()
                    if label in CONFIG.PLATE_LABELS:
                        has_plate = True
                        break
            if has_plate:
                filenames.add(filename)
        return filenames

    def _get_effective_iteration_package_breakdown(self, manifest: dict | None = None) -> dict:
        iter_image_count = int(self._get_iteration_image_count() or 0)
        payload = {
            "base_count": iter_image_count,
            "manual_reuse_count": 0,
            "effective_total": iter_image_count,
            "source_label": "",
        }

        if not isinstance(manifest, dict):
            return payload

        manifest_mode = str(manifest.get("selection_mode", "") or "").strip().lower()
        if manifest_mode != "stage_reuse":
            return payload

        stored_manual_source = CAMPAIGN.get_last_plate_manual_source()
        current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)

        def _extract_iteration_num(raw_value: str) -> int:
            text = str(raw_value or "").strip()
            if not text:
                return 0
            try:
                candidate = Path(text)
                parts = list(candidate.parts)
            except Exception:
                parts = [text]
            for part in reversed(parts):
                stripped = str(part).strip()
                lowered = stripped.lower()
                if lowered.startswith("iteracja_"):
                    try:
                        return int(stripped.split("_", 1)[1])
                    except Exception:
                        return 0
            return 0

        source_label = ""
        source_iteration = 0
        for raw_path in (
            str(stored_manual_source.get("source_input_path") or "").strip(),
            str(stored_manual_source.get("source_run_path") or "").strip(),
            str(stored_manual_source.get("source_xml_path") or "").strip(),
        ):
            if not raw_path:
                continue
            try:
                candidate = Path(raw_path)
                parts = list(candidate.parts)
            except Exception:
                parts = [raw_path]
            for part in reversed(parts):
                lowered = str(part).strip().lower()
                if lowered.startswith("iteracja_"):
                    source_label = str(part)
                    source_iteration = _extract_iteration_num(source_label)
                    break
            if source_label:
                break

        if source_iteration <= 0 or source_iteration >= current_iteration:
            payload["source_label"] = source_label
            return payload

        xml_path = None
        for raw_xml in (
            str(stored_manual_source.get("source_xml_path") or "").strip(),
            str(stored_manual_source.get("source_run_path") or "").strip(),
        ):
            if not raw_xml:
                continue
            try:
                candidate = Path(raw_xml)
                if candidate.suffix.lower() == ".xml":
                    xml_candidate = candidate
                else:
                    xml_candidate = candidate / "annotations.xml"
            except Exception:
                continue
            if xml_candidate.exists():
                xml_path = xml_candidate
                break

        manual_filenames = self._load_plate_annotated_filenames_from_xml(xml_path)
        payload["manual_reuse_count"] = len(manual_filenames)
        payload["effective_total"] = int(payload["base_count"]) + int(payload["manual_reuse_count"])
        payload["source_label"] = source_label
        return payload

    def _get_step1_manifest_context(self, manifest: dict | None = None) -> dict:
        manifest = manifest if isinstance(manifest, dict) else {}
        current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
        iter_num = int(manifest.get("iteration", current_iteration) or current_iteration)
        cache_scope = f"step1_manifest_context:iter_{int(iter_num or 0):03d}"
        cache_signature = self._build_step1_manifest_context_signature(manifest, iter_num)
        cached_context = self._get_project_view_cache_entry(cache_scope, cache_signature)
        if isinstance(cached_context, dict) and cached_context:
            return dict(cached_context)
        manifest_mode = str(manifest.get("selection_mode", "") or "").strip().lower()
        planned_manifest_modes = {"planned", "planned_manifest", "manual", "existing", "source_reuse"}
        selected_count = int(manifest.get("selected_count", 0) or 0)

        proposal_summary = manifest.get("proposal_summary", {})
        if not isinstance(proposal_summary, dict):
            proposal_summary = {}
        source_total = int(proposal_summary.get("source_total", 0) or 0)
        skipped_duplicate_filenames = int(proposal_summary.get("skipped_duplicate_filenames", 0) or 0)
        skipped_duplicate_approved = int(proposal_summary.get("skipped_duplicate_approved_filenames", 0) or 0)
        project_overlap_filenames = int(proposal_summary.get("project_overlap_filenames", 0) or 0)
        current_iteration_package_count = int(proposal_summary.get("current_iteration_package_count", selected_count) or selected_count)
        new_to_project_count = int(
            proposal_summary.get(
                "new_to_project_count",
                (
                    current_iteration_package_count
                    if manifest_mode in planned_manifest_modes
                    else max(0, current_iteration_package_count - project_overlap_filenames)
                ),
            ) or 0
        )
        project_pool_total_before = int(proposal_summary.get("project_pool_total_before_iteration", 0) or 0)
        project_pool_total_after = int(proposal_summary.get("project_pool_total_after_iteration", 0) or 0)
        approved_images_before = int(proposal_summary.get("approved_images_before_iteration", 0) or 0)
        approved_plates_before = int(proposal_summary.get("approved_plates_before_iteration", 0) or 0)

        source_iteration = int(proposal_summary.get("source_iteration", 0) or 0)
        source_kind = str(proposal_summary.get("source_kind", "") or "").strip().lower()

        if source_iteration <= 0:
            source_dir = str(manifest.get("source_dir", "") or "").strip()
            for raw_part in reversed(str(source_dir).replace("\\", "/").split("/")):
                lowered = str(raw_part).strip().lower()
                if lowered.startswith("iteracja_"):
                    try:
                        source_iteration = int(str(raw_part).split("_", 1)[1])
                    except Exception:
                        source_iteration = 0
                    break

        source_label = f"Iteracja_{source_iteration:03d}" if source_iteration > 0 else ""

        approved_stats = {}
        try:
            approved_stats = CAMPAIGN.get_plate_approved_set_stats() or {}
        except Exception:
            approved_stats = {}
        if approved_images_before <= 0:
            approved_images_before = int(approved_stats.get("images", 0) or 0)
        if approved_plates_before <= 0:
            approved_plates_before = int(approved_stats.get("plates", 0) or 0)
        if project_pool_total_before <= 0:
            project_pool_total_before = approved_images_before
        if project_pool_total_after <= 0:
            project_pool_total_after = max(project_pool_total_before, approved_images_before) + new_to_project_count

        try:
            master_pool_dir = CAMPAIGN.get_master_pool_dir()
        except Exception:
            master_pool_dir = None
        try:
            target_iter_dir = CAMPAIGN.get_iteration_raw_dir(iter_num)
        except Exception:
            target_iter_dir = None

        def _collect_image_names_in_dir(dir_path: Path | None, *, recursive: bool = False) -> set[str]:
            names: set[str] = set()
            if dir_path is None or not dir_path.exists() or not dir_path.is_dir():
                return names
            try:
                iterator = dir_path.rglob("*") if recursive else dir_path.iterdir()
                for image_path in iterator:
                    if not image_path.is_file():
                        continue
                    if image_path.suffix.lower() not in CONFIG.IMAGE_EXTENSIONS:
                        continue
                    filename = str(image_path.name or "").strip().lower()
                    if filename:
                        names.add(filename)
            except Exception:
                return names
            return names

        if target_iter_dir is not None:
            try:
                target_iter_dir = Path(target_iter_dir)
                registry = CAMPAIGN.get_project_packet_filename_registry(exclude_iteration_num=iter_num)
                previous_project_names: set[str] = {
                    str(name or "").strip().lower()
                    for name in list((registry or {}).get("filenames") or [])
                    if str(name or "").strip()
                }

                selected_names: set[str] = set()
                for selected_item in list(manifest.get("selected_images") or []):
                    if not isinstance(selected_item, dict):
                        continue
                    filename = str(selected_item.get("name", "") or "").strip().lower()
                    if filename:
                        selected_names.add(filename)
                if not selected_names:
                    selected_names = _collect_image_names_in_dir(target_iter_dir, recursive=False)

                if selected_names:
                    overlap_actual = len(selected_names & previous_project_names)
                    new_actual = max(0, len(selected_names) - overlap_actual)
                    project_pool_total_before = max(project_pool_total_before, len(previous_project_names))
                    project_pool_total_after = max(project_pool_total_after, len(previous_project_names | selected_names))
                    current_iteration_package_count = int(len(selected_names))
                    selected_count = int(len(selected_names))
                    if manifest_mode in planned_manifest_modes:
                        source_total = int(len(selected_names))

                    stale_overlap = int(project_overlap_filenames or 0)
                    stale_new = int(new_to_project_count or 0)
                    if (
                        manifest_mode in planned_manifest_modes
                        and (
                            stale_overlap != overlap_actual
                            or stale_new != new_actual
                        )
                    ):
                        project_overlap_filenames = int(overlap_actual)
                        new_to_project_count = int(new_actual)
            except Exception:
                pass

        if manifest_mode == "stage_reuse":
            if source_label:
                source_summary = f"Stage po {source_label}"
            else:
                source_summary = "Stage po poprzedniej iteracji"
        elif manifest_mode == "pool_reuse":
            source_summary = "Ta sama pula projektu"
        elif manifest_mode == "iteration_reuse":
            source_summary = "Ten sam zestaw zdjęć co poprzednio"
        elif manifest_mode in {"planned", "planned_manifest"}:
            source_summary = "Wybrany zestaw zdjęć z głównej puli projektu"
        elif manifest_mode == "source_reuse":
            source_summary = "Wybrany katalog zdjęć użyty ponownie w tej iteracji"
        elif manifest_mode == "manual":
            source_summary = "Ręcznie wskazany katalog zdjęć wejściowych"
        elif manifest_mode == "existing":
            source_summary = "Gotowy katalog bieżącej iteracji"
        else:
            source_summary = "Źródło zdjęć nie jest jeszcze znane"

        if manifest_mode in planned_manifest_modes and int(current_iteration_package_count or 0) > 0:
            source_total = max(int(source_total or 0), int(current_iteration_package_count or 0))

        result = {
            "iteration": iter_num,
            "selection_mode": manifest_mode,
            "selected_count": selected_count,
            "source_kind": source_kind,
            "source_iteration": source_iteration,
            "source_label": source_label,
            "source_summary": source_summary,
            "source_total": source_total,
            "skipped_duplicate_filenames": skipped_duplicate_filenames,
            "skipped_duplicate_approved": skipped_duplicate_approved,
            "project_overlap_filenames": project_overlap_filenames,
            "project_pool_total": int(project_pool_total_after or 0),
            "project_pool_total_before": int(project_pool_total_before or 0),
            "project_pool_total_after": int(project_pool_total_after or 0),
            "current_iteration_package_count": int(current_iteration_package_count or selected_count or 0),
            "new_to_project_count": int(new_to_project_count or 0),
            "approved_images": approved_images_before,
            "approved_plates": approved_plates_before,
        }
        self._set_project_view_cache_entry(cache_scope, cache_signature, result)
        return result

    def _build_step1_summary_payload(self) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {}

        manifest = self._load_ingest_manifest_cached()
        if not isinstance(manifest, dict) or not manifest:
            draft_plan = self._get_active_step1_draft_plan()
            if isinstance(draft_plan, dict) and draft_plan:
                latest_selected_total = int(draft_plan.get("selected_total", 0) or 0)
                if latest_selected_total > 0:
                    iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
                    target_dir = CAMPAIGN.get_iteration_raw_dir(iter_num)
                    manifest = {
                        "iteration": iter_num,
                        "selection_mode": "planned",
                        "source_dir": str(draft_plan.get("master_pool_dir") or ""),
                        "target_dir": str(target_dir or ""),
                        "master_pool_dir": str(draft_plan.get("master_pool_dir") or ""),
                        "selected_count": latest_selected_total,
                        "selected_images": list(draft_plan.get("selected") or []),
                        "char_histogram": dict(draft_plan.get("selected_balance") or {}),
                        "created_at": str(draft_plan.get("generated_at") or ""),
                        "proposal_summary": {
                            "source_total": int(draft_plan.get("raw_total", latest_selected_total) or latest_selected_total),
                            "selected_total": latest_selected_total,
                            "current_iteration_package_count": latest_selected_total,
                            "project_overlap_filenames": int(draft_plan.get("project_overlap_filenames", 0) or 0),
                            "new_to_project_count": int(draft_plan.get("new_to_project_total", 0) or 0),
                            "skipped_duplicate_filenames": int(draft_plan.get("skipped_duplicate_filenames", draft_plan.get("skipped_used", 0)) or 0),
                            "skipped_duplicate_approved_filenames": int(draft_plan.get("skipped_duplicate_approved_filenames", 0) or 0),
                            "project_pool_total_before_iteration": int(draft_plan.get("project_pool_total_before_iteration", 0) or 0),
                            "project_pool_total_after_iteration": int(draft_plan.get("project_pool_total_after_iteration", 0) or 0),
                            "skipped_invalid_ground_truth": int(draft_plan.get("skipped_invalid_ground_truth", 0) or 0),
                        },
                    }
            if not isinstance(manifest, dict) or not manifest:
                if (
                    int(CAMPAIGN.get_current_step() or 1) == 1
                    and str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved"
                ):
                    manifest = self._load_previous_iteration_ingest_manifest()
            if not isinstance(manifest, dict) or not manifest:
                iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
                target_dir = CAMPAIGN.get_iteration_raw_dir(iter_num)
                source_dir = CAMPAIGN.get_iteration_image_source_dir(iter_num) or target_dir
                try:
                    selected_count = int(CAMPAIGN.get_iteration_image_count(iter_num) or 0)
                except Exception:
                    selected_count = 0
                if selected_count <= 0 and target_dir is not None and target_dir.exists() and target_dir.is_dir():
                    selected_count = sum(
                        1
                        for image_path in target_dir.iterdir()
                        if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
                    )
                if selected_count <= 0:
                    return {}
                manifest = {
                    "iteration": iter_num,
                    "selection_mode": "existing",
                    "source_dir": str(source_dir or target_dir or ""),
                    "target_dir": str(target_dir or ""),
                    "master_pool_dir": str(CAMPAIGN.get_master_pool_dir() or ""),
                    "selected_count": selected_count,
                    "selected_images": [],
                    "char_histogram": {},
                    "created_at": "",
                    "proposal_summary": {},
                }

        selected_count = int(manifest.get("selected_count", 0) or 0)
        target_dir = str(manifest.get("target_dir", "") or "").strip()
        if selected_count <= 0 and not target_dir:
            return {}
        step1_context = self._get_step1_manifest_context(manifest)
        package_count = int(
            step1_context.get("current_iteration_package_count", 0)
            or self._get_iteration_image_count()
            or selected_count
            or 0
        )
        source_total = int(step1_context.get("source_total", 0) or 0)
        project_overlap_count = int(step1_context.get("project_overlap_filenames", 0) or 0)
        approved_overlap_count = int(step1_context.get("skipped_duplicate_approved", 0) or 0)
        project_pool_total = int(step1_context.get("project_pool_total_after", step1_context.get("project_pool_total", 0)) or 0)
        approved_images = int(step1_context.get("approved_images", 0) or 0)
        new_to_project_count = int(step1_context.get("new_to_project_count", 0) or 0)
        source_summary = str(step1_context.get("source_summary", "") or "").strip()
        source_label = str(step1_context.get("source_label", "") or "").strip()
        if source_label and str(step1_context.get("selection_mode", "") or "").strip().lower() == "stage_reuse":
            source_summary = f"{source_summary} ({source_label})"

        manifest_mode = str(manifest.get("selection_mode", "") or "").strip().lower()
        manifest_image_names = list(manifest.get("selected_images") or [])
        manifest_count = 0
        try:
            manifest_count = int(CAMPAIGN.get_iteration_manifest_image_count() or 0)
        except Exception:
            manifest_count = 0
        if manifest_count <= 0:
            manifest_count = int(len(manifest_image_names) or 0)
        manifest_contract_modes = {
            "planned",
            "planned_manifest",
            "source_reuse",
            "pool_reuse",
            "stage_reuse",
            "iteration_reuse",
        }
        uses_manifest_contract = bool(
            manifest.get("manifest_only", False)
            or manifest_mode in manifest_contract_modes
            or manifest_image_names
            or manifest_count > 0
        )
        source_contract_text = (
            "Manifestowy zestaw zdjęć"
            if uses_manifest_contract
            else "Fizyczny katalog iteracji"
        )
        if uses_manifest_contract and manifest_count > 0:
            source_contract_text = f"{source_contract_text} ({manifest_count} w manifeście)"
        selection_mode_text = self._format_step1_selection_mode_label(manifest_mode)
        current_iteration = int(manifest.get("iteration", CAMPAIGN.get_current_iteration_num()) or CAMPAIGN.get_current_iteration_num())
        total_pool_images = max(int(project_pool_total or 0), int(package_count or 0))
        previous_approved_images = max(0, int(approved_images or 0))
        current_iteration_package = int(package_count or 0)
        try:
            current_master_pool_dir = CAMPAIGN.get_master_pool_dir()
        except Exception:
            current_master_pool_dir = None
        current_source_dir_count = (
            self._count_images_in_dir(current_master_pool_dir, recursive=True)
            if current_master_pool_dir is not None and current_master_pool_dir.exists() and current_master_pool_dir.is_dir()
            else 0
        )
        plate_source_info = self._get_project_start_plate_source_info()
        plate_xml_path = str(plate_source_info.get("xml_path") or "").strip()
        plate_run_path = str(plate_source_info.get("run_path") or "").strip()
        plate_annotations_text = self._format_project_start_asset_source(plate_xml_path or plate_run_path)
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        plate_model_identity = self._get_model_identity_label(plate_model_path)
        plate_model_text = plate_model_identity or self._format_project_start_asset_source(plate_model_path)
        char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
        char_model_identity = self._get_model_identity_label(char_model_path)
        char_model_text = char_model_identity or self._format_project_start_asset_source(char_model_path)
        source_diverged = bool(
            current_source_dir_count > 0
            and current_iteration_package > 0
            and current_source_dir_count != current_iteration_package
        )

        rows = [
            ("Tryb wejścia", source_contract_text),
            ("Sposób wyboru", selection_mode_text),
            (
                "Pudełko: tablice zatwierdzone",
                f"{previous_approved_images} zdjęć / {int(step1_context.get('approved_plates', 0) or 0)} tablic",
            ),
            ("Anotacje tablic", plate_annotations_text),
            ("Model tablic", plate_model_text),
            ("Model znaków", char_model_text),
            ("Zdjęcia iteracji", f"{current_iteration_package} zdjęć"),
            ("Nowe w historii projektu", f"{new_to_project_count} zdjęć"),
            ("Duble względem wcześniejszych iteracji", f"{project_overlap_count} zdjęć"),
            ("Pula projektu po E1 (informacyjnie)", f"{total_pool_images} zdjęć"),
        ]
        if source_diverged:
            rows.insert(1, ("Obecny katalog źródłowy", f"{current_source_dir_count} zdjęć"))

        return {
            "title": "Co wybrano w E1",
            "meta": "",
            "rows": rows,
            "source_diverged": bool(source_diverged),
            "current_source_dir_count": int(current_source_dir_count or 0),
            "package_count": int(current_iteration_package or 0),
            "uses_manifest_contract": bool(uses_manifest_contract),
            "source_contract_text": source_contract_text,
        }

    def _render_step1_stage_curtain(self, card: dict, status: WizardStageStatus, style: dict):
        if not isinstance(card, dict):
            return

        payload = {}
        if str(getattr(status, "key", "") or "").strip() == "step1":
            payload = self._build_step1_summary_payload()

        rows = list(payload.get("rows", []) or [])
        step1_mode = ""
        if str(getattr(status, "key", "") or "").strip() == "step1":
            step1_mode = self._get_step1_presentation_mode()
        visible = bool(rows) and step1_mode != "operational_assets"
        card["curtain_visible"] = visible

        shell = card.get("curtain_shell")
        clip = card.get("curtain_clip")
        inner = card.get("curtain_inner")
        table = card.get("curtain_table")
        action_row = card.get("action_row")
        content = card.get("content")
        if shell is None or clip is None or inner is None or table is None or content is None:
            return

        if not visible:
            card["curtain_expanded"] = False
            card["curtain_user_touched"] = False
            self._cancel_wizard_stage_curtain_animation(card)
            self._set_wizard_stage_curtain_height(card, 0)
            self._set_pack_visibility(shell, False)
            return

        if not bool(card.get("curtain_user_touched", False)):
            card["curtain_expanded"] = False

        border = str(style.get("border", "") or getattr(self.app, "palette", {}).get("panel_border", "#3c3c3c"))
        surface = blend_hex_colors(border, getattr(self.app, "palette", {}).get("panel", "#252526"), 0.92)
        card["curtain_border"] = border
        card["curtain_surface"] = surface

        title_lbl = card.get("curtain_title")
        meta_lbl = card.get("curtain_meta")
        if title_lbl is not None:
            try:
                title_lbl.configure(text=str(payload.get("title", "Podsumowanie etapu") or "Podsumowanie etapu"))
            except Exception:
                pass
        if meta_lbl is not None:
            try:
                meta_lbl.configure(text=str(payload.get("meta", "") or ""))
            except Exception:
                pass
            try:
                self._set_pack_visibility(meta_lbl, bool(str(payload.get("meta", "") or "").strip()), fill=tk.X, pady=(4, 0))
            except Exception:
                pass

        for child in list(table.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass

        palette = getattr(self.app, "palette", {})
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        panel_bg = palette.get("panel", "#252526")
        grid_border = blend_hex_colors(border, panel_bg, 0.34)
        header_bg = blend_hex_colors(surface, panel_bg, 0.18)

        try:
            table.grid_columnconfigure(0, weight=1)
            table.grid_columnconfigure(1, weight=0, minsize=120)
        except Exception:
            pass
        try:
            table.configure(
                bg=grid_border,
                highlightbackground=grid_border,
                highlightcolor=grid_border,
                highlightthickness=1,
            )
        except Exception:
            pass

        header_left = tk.Label(
            table,
            text="Pozycja",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 8, "bold"),
            fg=muted,
            bg=header_bg,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=grid_border,
            highlightcolor=grid_border,
            padx=10,
            pady=6,
        )
        header_left.grid(row=0, column=0, sticky="ew")

        header_right = tk.Label(
            table,
            text="Wartość",
            anchor="e",
            justify=tk.LEFT,
            font=("Segoe UI", 8, "bold"),
            fg=muted,
            bg=header_bg,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=grid_border,
            highlightcolor=grid_border,
            padx=10,
            pady=6,
        )
        header_right.grid(row=0, column=1, sticky="ew")

        for row_idx, (label_text, value_text) in enumerate(rows, start=1):
            row_bg = blend_hex_colors(surface, panel_bg, 0.10 if ((row_idx - 1) % 2 == 0) else 0.18)

            key_lbl = tk.Label(
                table,
                text=str(label_text or "").strip() or "-",
                anchor="nw",
                justify=tk.LEFT,
                width=18,
                font=("Segoe UI", 9, "bold"),
                fg=muted,
                bg=row_bg,
                bd=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground=grid_border,
                highlightcolor=grid_border,
                padx=10,
                pady=8,
            )
            key_lbl.grid(row=row_idx, column=0, sticky="nsew")

            val_lbl = tk.Label(
                table,
                text=str(value_text or "").strip() or "-",
                anchor="e",
                justify=tk.RIGHT,
                font=("Segoe UI", 9, "bold"),
                fg=fg,
                bg=row_bg,
                bd=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground=grid_border,
                highlightcolor=grid_border,
                padx=10,
                pady=8,
            )
            val_lbl.grid(row=row_idx, column=1, sticky="nsew")

        self._set_pack_visibility(shell, True, fill=tk.X, pady=(10, 0), before=action_row)
        self._refresh_wizard_stage_curtain_style(card)
        try:
            inner.update_idletasks()
        except Exception:
            pass
        self._set_wizard_stage_curtain_height(
            card,
            int(inner.winfo_reqheight() or 0) if bool(card.get("curtain_expanded", False)) else 0,
        )

    def _refresh_wizard_stage_metro(self, statuses: list[WizardStageStatus] | None = None):
        filtered_statuses = []
        for key in ("step1", "step2", "step3", "step4"):
            matched = None
            if statuses:
                for status in statuses:
                    if getattr(status, "key", "") == key:
                        matched = status
                        break
            if matched is None:
                matched = WizardStageStatus(
                    key=key,
                    title="",
                    state="locked",
                    summary="",
                    details="",
                    is_current=False,
                )
            filtered_statuses.append(matched)

        self._wizard_header_metro_statuses = filtered_statuses
        self.frame.after_idle(self._draw_wizard_stage_metro)
        try:
            notify = getattr(self.app, "notify_free_mode_assistant_context_changed", None)
            if callable(notify):
                notify()
        except Exception:
            pass

    def _draw_wizard_stage_metro(self, _event=None):
        canvas = getattr(self, "wizard_header_metro_canvas", None)
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        panel_bg = str(canvas.cget("bg") or palette.get("panel", "#252526"))
        panel_alt = palette.get("panel_alt", "#2d2d30")
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        muted_dim = palette.get("muted_dim", "#9a9a9a")
        border = blend_hex_colors(
            palette.get("panel_border", palette.get("border", "#3c3c3c")),
            panel_bg,
            0.28,
        )
        success = palette.get("success", "#27ae60")
        current_fill = blend_hex_colors(success, panel_bg, 0.16)
        neutral_outline = blend_hex_colors(fg, panel_bg, 0.34)
        soft_label = blend_hex_colors(muted, panel_bg, 0.18)

        canvas.delete("all")

        statuses = list(getattr(self, "_wizard_header_metro_statuses", []) or [])
        if not statuses:
            statuses = [
                WizardStageStatus(key=f"step{idx}", title="", state="locked")
                for idx in range(1, 5)
            ]

        width = max(int(canvas.winfo_width() or 720), 360)
        height = max(int(canvas.winfo_height() or 84), 84)
        line_y = 31
        circle_r = 14
        top_y = 0
        label_y = 58
        label_map = {
            "step1": "Wejście",
            "step2": "Tor",
            "step3": "Znaki",
            "step4": "Trening",
        }

        usable_left = 46
        usable_right = width - 46
        if usable_right <= usable_left:
            usable_left = 28
            usable_right = width - 28
        count = max(len(statuses), 2)
        step_gap = (usable_right - usable_left) / max(count - 1, 1)
        positions = [usable_left + idx * step_gap for idx in range(len(statuses))]

        current_index = next((idx for idx, status in enumerate(statuses) if bool(getattr(status, "is_current", False))), None)
        if current_index is None and statuses and all(str(getattr(status, "state", "") or "").strip().lower() in {"done", "skipped"} for status in statuses):
            current_index = len(statuses) - 1

        marker_text = "W TOKU"
        if current_index is not None and 0 <= current_index < len(statuses):
            current_state = str(getattr(statuses[current_index], "state", "") or "").strip().lower()
            if current_state == "skipped":
                marker_text = "POMINIETY"
            elif current_state == "done":
                marker_text = "GOTOWE"

        def station_style(status: WizardStageStatus, *, highlighted: bool) -> dict:
            state_key = str(getattr(status, "state", "") or "").strip().lower()
            if state_key == "skipped":
                return {"fill": panel_bg, "outline": muted_dim, "text": muted_dim, "label": muted_dim, "dash": (3, 2)}
            if highlighted:
                return {"fill": current_fill, "outline": success, "text": fg, "label": success, "dash": None}
            if state_key == "done":
                return {"fill": panel_bg, "outline": success, "text": fg, "label": success, "dash": None}
            return {"fill": panel_bg, "outline": neutral_outline, "text": fg, "label": soft_label, "dash": None}

        if PIL_AVAILABLE and Image is not None and ImageTk is not None and ImageDraw is not None and ImageFont is not None:
            hi_pixel_budget = 4_500_000
            scale = 4 if (width * height) <= 180_000 else 2
            hi_w = max(width * scale, 4)
            hi_h = max(height * scale, 4)
            can_use_pil_metro = (hi_w * hi_h) <= hi_pixel_budget and width <= 2400 and height <= 280
            if can_use_pil_metro:
                try:
                    image = Image.new("RGBA", (hi_w, hi_h), self._hex_to_rgba(panel_bg))
                    draw = ImageDraw.Draw(image, "RGBA")
                    font_marker = self._get_pil_font(10 * scale, bold=False)
                    font_step = self._get_pil_font(10 * scale, bold=False)
                    font_label = self._get_pil_font(10 * scale, bold=False)
                    font_skipped = self._get_pil_font(9 * scale, bold=False)

                    def s(value: float) -> int:
                        return int(round(float(value) * scale))

                    for idx in range(len(positions) - 1):
                        segment_color = border
                        if current_index is not None:
                            if idx < current_index:
                                segment_color = success
                        elif statuses and all(str(getattr(status, "state", "") or "").strip().lower() in {"done", "skipped"} for status in statuses):
                            segment_color = success

                        draw.line(
                            [(s(positions[idx] + circle_r), s(line_y)), (s(positions[idx + 1] - circle_r), s(line_y))],
                            fill=self._hex_to_rgba(segment_color),
                            width=max(2, s(2)),
                        )

                    marker_bbox = None
                    if current_index is not None and 0 <= current_index < len(positions):
                        current_status = statuses[current_index]
                        current_style = station_style(current_status, highlighted=True)
                        marker_x = s(positions[current_index])
                        marker_y = s(top_y)
                        try:
                            bbox = draw.textbbox((0, 0), marker_text, font=font_marker)
                            text_w = max(1, bbox[2] - bbox[0])
                            text_h = max(1, bbox[3] - bbox[1])
                        except Exception:
                            text_w = 24 * scale
                            text_h = 8 * scale
                        text_pos = (marker_x - text_w // 2, marker_y)
                        draw.text(text_pos, marker_text, font=font_marker, fill=self._hex_to_rgba(current_style["outline"]))
                        marker_bbox = (text_pos[0], text_pos[1], text_pos[0] + text_w, text_pos[1] + text_h)
                        marker_line_top = marker_bbox[3] + (6 * scale)
                        marker_line_bottom = s(line_y - circle_r - 4)
                        if marker_line_bottom > marker_line_top:
                            draw.line(
                                [(marker_x, marker_line_top), (marker_x, marker_line_bottom)],
                                fill=self._hex_to_rgba(current_style["outline"]),
                                width=max(2, s(2)),
                            )

                    for idx, status in enumerate(statuses):
                        state_key = str(getattr(status, "state", "") or "").strip().lower()
                        if state_key != "skipped" or idx == current_index:
                            continue
                        skipped_style = station_style(status, highlighted=False)
                        skipped_text = "POMINIETO"
                        try:
                            bbox = draw.textbbox((0, 0), skipped_text, font=font_skipped)
                            text_w = max(1, bbox[2] - bbox[0])
                        except Exception:
                            text_w = 30 * scale
                        draw.text(
                            (s(positions[idx]) - text_w // 2, s(top_y + 2)),
                            skipped_text,
                            font=font_skipped,
                            fill=self._hex_to_rgba(skipped_style["label"]),
                        )

                    for idx, status in enumerate(statuses):
                        x = positions[idx]
                        highlighted = bool(current_index == idx)
                        style = station_style(status, highlighted=highlighted)

                        draw.ellipse(
                            [s(x - circle_r), s(line_y - circle_r), s(x + circle_r), s(line_y + circle_r)],
                            fill=self._hex_to_rgba(style["fill"]),
                            outline=self._hex_to_rgba(style["outline"]),
                            width=max(2, s(2)),
                        )

                        step_text = f"E{idx + 1}"
                        try:
                            bbox = draw.textbbox((0, 0), step_text, font=font_step)
                            step_x = s(x) - ((bbox[0] + bbox[2]) / 2.0)
                            step_y = s(line_y) - ((bbox[1] + bbox[3]) / 2.0)
                        except Exception:
                            step_x = s(x) - (7 * scale)
                            step_y = s(line_y) - (4 * scale)
                        draw.text(
                            (step_x, step_y),
                            step_text,
                            font=font_step,
                            fill=self._hex_to_rgba(style["text"]),
                        )

                        label_text_local = label_map.get(getattr(status, "key", ""), f"E{idx + 1}")
                        label_color = style["label"] if highlighted or str(getattr(status, "state", "") or "").strip().lower() in {"done", "in_progress", "needs_attention"} else soft_label
                        try:
                            bbox = draw.textbbox((0, 0), label_text_local, font=font_label)
                            label_w = max(1, bbox[2] - bbox[0])
                        except Exception:
                            label_w = 24 * scale
                        draw.text(
                            (s(x) - label_w // 2, s(label_y)),
                            label_text_local,
                            font=font_label,
                            fill=self._hex_to_rgba(label_color),
                        )

                    try:
                        resampling = Image.Resampling.LANCZOS
                    except Exception:
                        resampling = Image.LANCZOS
                    image = image.resize((width, height), resampling)
                    self._wizard_header_metro_photo = ImageTk.PhotoImage(image)
                    canvas.create_image(0, 0, anchor=tk.NW, image=self._wizard_header_metro_photo)
                    return
                except MemoryError:
                    logger.warning(
                        "Wizard metro PIL fallback po MemoryError: width=%s height=%s scale=%s hi=%sx%s",
                        width,
                        height,
                        scale,
                        hi_w,
                        hi_h,
                    )
                except Exception as exc:
                    logger.debug("Wizard metro PIL fallback do Canvas: %s", exc)

        for idx in range(len(positions) - 1):
            segment_color = border
            if current_index is not None:
                if idx < current_index:
                    segment_color = success
            elif statuses and all(str(getattr(status, "state", "") or "").strip().lower() in {"done", "skipped"} for status in statuses):
                segment_color = success

            canvas.create_line(
                positions[idx] + circle_r,
                line_y,
                positions[idx + 1] - circle_r,
                line_y,
                fill=segment_color,
                width=2,
                capstyle=tk.ROUND,
            )

        if current_index is not None and 0 <= current_index < len(positions):
            current_status = statuses[current_index]
            current_style = station_style(current_status, highlighted=True)
            marker_id = canvas.create_text(
                positions[current_index],
                top_y,
                text=marker_text,
                fill=current_style["outline"],
                font=("Segoe UI", 12, "normal"),
                anchor=tk.N,
            )
            try:
                marker_bbox = canvas.bbox(marker_id)
            except Exception:
                marker_bbox = None

            marker_line_top = (marker_bbox[3] + 6) if marker_bbox else (top_y + 14)
            marker_line_bottom = line_y - circle_r - 4
            if marker_line_bottom > marker_line_top:
                canvas.create_line(
                    positions[current_index],
                    marker_line_top,
                    positions[current_index],
                    marker_line_bottom,
                    fill=current_style["outline"],
                    width=2,
                )

        for idx, status in enumerate(statuses):
            state_key = str(getattr(status, "state", "") or "").strip().lower()
            if state_key != "skipped" or idx == current_index:
                continue
            skipped_style = station_style(status, highlighted=False)
            canvas.create_text(
                positions[idx],
                top_y + 2,
                text="POMINIETO",
                fill=skipped_style["label"],
                font=("Segoe UI", 11, "normal"),
                anchor=tk.N,
            )

        for idx, status in enumerate(statuses):
            x = positions[idx]
            highlighted = bool(current_index == idx)
            style = station_style(status, highlighted=highlighted)

            oval_id = canvas.create_oval(
                x - circle_r,
                line_y - circle_r,
                x + circle_r,
                line_y + circle_r,
                fill=style["fill"],
                outline=style["outline"],
                width=2,
            )
            if style["dash"]:
                canvas.itemconfigure(oval_id, dash=style["dash"])

            canvas.create_text(
                x,
                line_y,
                text=f"E{idx + 1}",
                fill=style["text"],
                font=("Segoe UI", 11, "normal"),
            )
            canvas.create_text(
                x,
                label_y,
                text=label_map.get(getattr(status, "key", ""), f"E{idx + 1}"),
                fill=(style["label"] if highlighted or str(getattr(status, "state", "") or "").strip().lower() in {"done", "in_progress", "needs_attention"} else soft_label),
                font=("Segoe UI", 11, "normal"),
            )

    def _build_wizard_stage_card(self, parent, key: str, *, help_key: str | None = None):
        palette = getattr(self.app, "palette", {})
        card_bg = palette.get("panel", "#252526")
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        shell = tk.Frame(parent, bg=border, bd=0, highlightthickness=0)
        shell.pack(fill=tk.X, pady=(0, 12))

        content = tk.Frame(shell, bg=card_bg, padx=14, pady=12)
        content.pack(fill=tk.X, padx=1, pady=1)

        header_row = tk.Frame(content, bg=card_bg, bd=0, highlightthickness=0)
        header_row.pack(fill=tk.X)

        title_lbl = tk.Label(
            header_row,
            text="",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 12, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=card_bg,
        )
        title_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        header_status_col = tk.Frame(header_row, bg=card_bg, bd=0, highlightthickness=0)
        header_status_col.pack(side=tk.RIGHT, padx=(10, 0))
        header_status_col.grid_columnconfigure(0, weight=1)

        badge_lbl = tk.Label(
            header_status_col,
            text="",
            anchor="e",
            justify=tk.RIGHT,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=3,
            bd=0,
            highlightthickness=0,
        )
        badge_lbl.grid(row=0, column=0, sticky="e")

        summary_lbl = tk.Label(
            content,
            text="",
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
            fg=palette.get("fg", "#f3f3f3"),
            bg=card_bg,
        )
        summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))

        details_lbl = tk.Label(
            content,
            text="",
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
            fg=palette.get("muted", "#c7c7c7"),
            bg=card_bg,
        )
        details_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))

        action_row = tk.Frame(content, bg=card_bg, bd=0, highlightthickness=0)
        action_row.pack(fill=tk.X, pady=(10, 0))

        primary_btn = ttk.Button(action_row, text="")
        secondary_btn = ttk.Button(action_row, text="")

        curtain_shell = tk.Frame(content, bg=card_bg, bd=0, highlightthickness=0)

        curtain_toggle = tk.Frame(
            curtain_shell,
            bg=card_bg,
            bd=0,
            highlightthickness=1,
            cursor="hand2",
            padx=10,
            pady=8,
        )
        curtain_toggle.pack(fill=tk.X)

        curtain_indicator = tk.Label(
            curtain_toggle,
            text="▸",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 10, "bold"),
            bg=card_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        curtain_indicator.pack(side=tk.LEFT)

        curtain_text_col = tk.Frame(curtain_toggle, bg=card_bg, bd=0, highlightthickness=0, cursor="hand2")
        curtain_text_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        curtain_title_lbl = tk.Label(
            curtain_text_col,
            text="",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 9, "bold"),
            bg=card_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        curtain_title_lbl.pack(anchor=tk.W, fill=tk.X)

        curtain_meta_lbl = tk.Label(
            curtain_text_col,
            text="",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 8),
            bg=card_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        curtain_meta_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 0))

        curtain_clip = tk.Frame(curtain_shell, bg=card_bg, bd=0, highlightthickness=0, height=0)
        curtain_clip.pack(fill=tk.X, pady=(6, 0))
        curtain_clip.pack_propagate(False)

        curtain_inner = tk.Frame(curtain_clip, bg=card_bg, bd=0, highlightthickness=0)
        curtain_inner.pack(fill=tk.X)

        curtain_table = tk.Frame(
            curtain_inner,
            bg=card_bg,
            bd=0,
            highlightthickness=1,
        )
        curtain_table.pack(fill=tk.X)

        body = tk.Frame(content, bg=card_bg, bd=0, highlightthickness=0)

        badge_cta_shell = tk.Frame(
            action_row,
            bg=card_bg,
            bd=0,
            highlightthickness=1,
            padx=1,
            pady=1,
        )
        badge_cta_btn = tk.Label(
            badge_cta_shell,
            text="ZATWIERDŹ ETAP",
            bd=0,
            highlightthickness=1,
            padx=14,
            pady=5,
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            anchor="center",
            justify=tk.CENTER,
        )
        badge_cta_btn.pack(anchor=tk.E)

        if help_key:
            for widget in (shell, content, header_row, header_status_col, title_lbl, summary_lbl, details_lbl, body, curtain_shell, curtain_toggle, curtain_table, badge_cta_shell, badge_cta_btn):
                HELP.bind_help(widget, help_key)

        for widget in (
            shell,
            content,
            header_row,
            header_status_col,
            title_lbl,
            summary_lbl,
            details_lbl,
            action_row,
            body,
            curtain_shell,
            curtain_toggle,
            badge_cta_shell,
            badge_cta_btn,
        ):
            try:
                widget.bind("<Enter>", lambda _event, stage_key=key: self._set_wizard_assistant_stage_context(stage_key), add="+")
            except Exception:
                pass

        card = {
            "key": key,
            "shell": shell,
            "content": content,
            "header_row": header_row,
            "header_status_col": header_status_col,
            "title": title_lbl,
            "badge": badge_lbl,
            "badge_cta_shell": badge_cta_shell,
            "badge_cta_btn": badge_cta_btn,
            "summary": summary_lbl,
            "details": details_lbl,
            "action_row": action_row,
            "primary_btn": primary_btn,
            "secondary_btn": secondary_btn,
            "body": body,
            "curtain_shell": curtain_shell,
            "curtain_toggle": curtain_toggle,
            "curtain_indicator": curtain_indicator,
            "curtain_text_col": curtain_text_col,
            "curtain_title": curtain_title_lbl,
            "curtain_meta": curtain_meta_lbl,
            "curtain_clip": curtain_clip,
            "curtain_inner": curtain_inner,
            "curtain_table": curtain_table,
            "curtain_visible": False,
            "curtain_expanded": False,
            "curtain_user_touched": False,
            "curtain_after_id": None,
            "status": None,
        }

        for widget in (curtain_toggle, curtain_indicator, curtain_text_col, curtain_title_lbl, curtain_meta_lbl):
            try:
                widget.bind("<Button-1>", lambda _event, stage_key=key: self._toggle_wizard_stage_curtain(stage_key), add="+")
            except Exception:
                pass

        return card

    def _is_wizard_stage_emphasized(self, status: WizardStageStatus) -> bool:
        state_key = str(getattr(status, "state", "") or "").strip().lower()
        if bool(getattr(status, "is_current", False)):
            return True
        return state_key in {"in_progress", "needs_attention"}

    def _get_wizard_stage_state_style(self, state: str, *, is_current: bool = False, emphasized: bool = True) -> dict:
        palette = getattr(self.app, "palette", {})
        state_key = str(state or "").strip().lower()
        style_map = {
            "locked": {
                "label": "ZABLOKOWANE",
                "border": palette.get("panel_border", palette.get("border", "#3c3c3c")),
                "badge_bg": palette.get("panel_alt", "#2f3136"),
                "badge_fg": palette.get("muted", "#c7c7c7"),
                "title_fg": palette.get("muted", "#c7c7c7"),
                "summary_fg": palette.get("muted", "#c7c7c7"),
                "details_fg": palette.get("muted_dim", "#9a9a9a"),
            },
            "ready": {
                "label": "GOTOWE",
                "border": palette.get("success", "#27ae60"),
                "badge_bg": palette.get("surface_success", palette.get("panel_alt", "#1f3320")),
                "badge_fg": palette.get("success", "#27ae60"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
                "details_fg": palette.get("muted", "#c7c7c7"),
            },
            "in_progress": {
                "label": "W TOKU",
                "border": palette.get("success", "#27ae60"),
                "badge_bg": palette.get("surface_success", palette.get("panel_alt", "#1f3320")),
                "badge_fg": palette.get("success", "#27ae60"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
                "details_fg": palette.get("muted", "#c7c7c7"),
            },
            "needs_attention": {
                "label": "UWAGA",
                "border": palette.get("warning", "#d35400"),
                "badge_bg": palette.get("surface_warning", palette.get("panel_alt", "#3a2323")),
                "badge_fg": palette.get("warning", "#d35400"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
                "details_fg": palette.get("muted", "#c7c7c7"),
            },
            "done": {
                "label": "GOTOWE",
                "border": blend_hex_colors(
                    palette.get("success", "#27ae60"),
                    palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    0.78,
                ),
                "badge_bg": blend_hex_colors(
                    palette.get("surface_success", palette.get("panel_alt", "#1f3320")),
                    palette.get("panel_alt", "#2f3136"),
                    0.42,
                ),
                "badge_fg": palette.get("success", "#27ae60"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
                "details_fg": palette.get("muted", "#c7c7c7"),
            },
            "skipped": {
                "label": "POMINIETE",
                "border": palette.get("panel_border", palette.get("border", "#3c3c3c")),
                "badge_bg": palette.get("panel_alt", "#2f3136"),
                "badge_fg": palette.get("muted_dim", "#9a9a9a"),
                "title_fg": palette.get("muted", "#c7c7c7"),
                "summary_fg": palette.get("muted", "#c7c7c7"),
                "details_fg": palette.get("muted_dim", "#9a9a9a"),
            },
        }
        base = dict(style_map.get(state_key, style_map["locked"]))
        if is_current and state_key in {"ready", "in_progress", "needs_attention"}:
            base["border"] = palette.get("success", "#27ae60")
        if not emphasized:
            panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
            panel_alt = palette.get("panel_alt", "#2f3136")
            base["border"] = blend_hex_colors(base.get("border", panel_border), panel_border, 0.82)
            base["badge_bg"] = blend_hex_colors(base.get("badge_bg", panel_alt), panel_alt, 0.42)
            base["badge_fg"] = palette.get("muted_dim", "#9a9a9a")
            base["title_fg"] = palette.get("muted", "#c7c7c7")
            base["summary_fg"] = palette.get("muted_dim", "#9a9a9a")
            base["details_fg"] = palette.get("muted_dim", "#9a9a9a")
        return base

    def _configure_wizard_stage_button(self, button, label: str, command, *, side=tk.LEFT, padx=(0, 0), debug_id: str = ""):
        if button is None:
            return
        label_text = str(label or "").strip()
        if not label_text or command is None:
            try:
                button.configure(text="", command=(lambda: None), state="disabled")
            except Exception:
                pass
            try:
                button.unbind("<ButtonPress-1>")
                button.unbind("<ButtonPress-3>")
            except Exception:
                pass
            self._set_pack_visibility(button, False)
            return

        debug_suffix = f" ({debug_id})" if str(debug_id or "").strip() else ""

        def _invoke_stage_button(event=None, _command=command, _button=button, _debug_id=debug_id):
            now = perf_counter()
            try:
                last_invoke = float(getattr(_button, "_wizard_stage_last_invoke_at", 0.0) or 0.0)
            except Exception:
                last_invoke = 0.0
            if now - last_invoke < 0.25:
                return "break" if event is not None else None
            try:
                setattr(_button, "_wizard_stage_last_invoke_at", now)
            except Exception:
                pass
            try:
                _command()
            except Exception as e:
                logger.error(f"Nie udało się wykonać akcji panelu wizarda {_debug_id}: {e}")
            return "break" if event is not None else None

        try:
            button.configure(text=f"{label_text}{debug_suffix}", command=_invoke_stage_button, state="normal")
            # Standardowy ttk.Button odpala komendę dopiero przy puszczeniu LPM.
            # Przy intensywnym odświeżaniu kart pierwszy klik potrafił zostać
            # zużyty przez focus/przerysowanie, więc dla CTA etapów startujemy
            # akcję już na naciśnięciu. PPM traktujemy tak samo dla tych CTA.
            button.bind("<ButtonPress-1>", _invoke_stage_button)
            button.bind("<ButtonPress-3>", _invoke_stage_button)
        except Exception:
            pass
        self._set_pack_visibility(button, True, side=side, padx=padx)

    def _configure_wizard_stage_badge_cta(self, card: dict, *, visible: bool, command=None, label: str = ""):
        if not card:
            return
        shell = card.get("badge_cta_shell")
        button = card.get("badge_cta_btn")
        if shell is None or button is None:
            return

        if not visible or command is None:
            try:
                button.unbind("<Button-1>")
                button.unbind("<Enter>")
                button.unbind("<Leave>")
            except Exception:
                pass
            try:
                shell.pack_forget()
            except Exception:
                pass
            try:
                shell.grid_remove()
            except Exception:
                pass
            return

        palette = getattr(self.app, "palette", {})
        success = palette.get("success", "#27ae60")
        surface_success = palette.get("surface_success", "#1f3320")
        panel_bg = palette.get("panel", "#252526")
        glow = blend_hex_colors(success, surface_success, 0.10)
        border = blend_hex_colors(success, panel_bg, 0.08)
        fill = blend_hex_colors(surface_success, panel_bg, 0.08)
        hover_fill = blend_hex_colors(fill, success, 0.18)
        hover_border = blend_hex_colors(success, palette.get("fg", "#f3f3f3"), 0.18)
        text_color = palette.get("fg", "#f3f3f3")
        button_label = (str(label or "").strip() or "Zatwierdź etap").upper()

        try:
            shell.configure(
                bg=glow,
                highlightbackground=border,
                highlightcolor=border,
                highlightthickness=1,
            )
        except Exception:
            pass
        try:
            button.configure(
                text=button_label,
                bg=fill,
                fg=text_color,
                activebackground=hover_fill,
                activeforeground=text_color,
                highlightbackground=border,
                highlightcolor=border,
                highlightthickness=1,
                padx=14,
                pady=5,
                font=("Segoe UI Semibold", 9),
            )
        except Exception:
            pass
        try:
            button.unbind("<Button-1>")
            button.unbind("<Enter>")
            button.unbind("<Leave>")
        except Exception:
            pass
        try:
            button.bind("<Button-1>", lambda _event, cmd=command: cmd(), add="+")
            button.bind(
                "<Enter>",
                lambda _event, widget=button, shell_widget=shell: (
                    shell_widget.configure(highlightbackground=hover_border, highlightcolor=hover_border),
                    widget.configure(bg=hover_fill),
                ),
                add="+",
            )
            button.bind(
                "<Leave>",
                lambda _event, widget=button, shell_widget=shell: (
                    shell_widget.configure(highlightbackground=border, highlightcolor=border),
                    widget.configure(bg=fill),
                ),
                add="+",
            )
        except Exception:
            pass
        try:
            if str(shell.winfo_manager()) == "pack":
                shell.pack_forget()
            elif str(shell.winfo_manager()) == "grid":
                shell.grid_remove()
            shell.pack(side=tk.RIGHT, padx=(8, 0))
            shell.lift()
        except Exception:
            pass

    def _get_step2_render_disk_approval_fallback(self, iteration_target: str = "") -> dict:
        target = self._normalize_iteration_target(iteration_target)
        if target not in {"plate", "char"}:
            try:
                target = self._normalize_iteration_target(CAMPAIGN.get_iteration_target())
            except Exception:
                target = ""
        if target not in {"plate", "char"}:
            return {}

        try:
            return dict(
                self._get_step2_disk_approval_fallback(
                    iteration_target=target,
                    plate_ready_source={},
                    char_ready_source={},
                )
                or {}
            )
        except Exception as e:
            logger.debug(f"Nie udało się sprawdzić trwałej bramki E2 z dysku: {e}")
            return {}

    def _force_current_step2_badge_from_disk(self) -> None:
        try:
            if not str(CAMPAIGN.get_active_project_name() or "").strip():
                return
            if str(CAMPAIGN.get_project_status() or "active").strip().lower() in {"completed", "paused"}:
                return
            if int(CAMPAIGN.get_current_step() or 0) != 2:
                return
            if str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved":
                return
            if str(CAMPAIGN.get_step2_status() or "").strip().lower() == "approved":
                return
            iteration_target = self._normalize_iteration_target(CAMPAIGN.get_iteration_target())
        except Exception:
            return

        if iteration_target not in {"plate", "char"}:
            return

        disk_fallback = self._get_step2_render_disk_approval_fallback(iteration_target)
        if not bool(disk_fallback.get("ready")):
            return

        next_stage_label = "E4" if iteration_target == "plate" else "E3"
        summary = "Etap 2 możesz już zamknąć, ale warto jeszcze rozważyć dopisanie tablic w Z2."
        details = (
            f"Minimalny próg projektu jest już spełniony, więc możesz od razu zamknąć E2 "
            f"i odblokować {next_stage_label}. Jeśli chcesz wzmocnić zbiór projektu, dopisz jeszcze "
            "kilka poprawnych anotacji tablic w Z2."
        )
        forced_status = None
        statuses = [
            status
            for status in list(getattr(self, "_wizard_header_metro_statuses", []) or [])
            if isinstance(status, WizardStageStatus)
        ]
        for index, status in enumerate(statuses):
            if str(getattr(status, "key", "") or "").strip().lower() != "step2":
                continue
            forced_status = WizardStageStatus(
                key="step2",
                title=str(getattr(status, "title", "") or "E2. Tablice"),
                state="ready",
                summary=summary,
                details=details,
                primary_label="Dodaj jeszcze tablice w Z2",
                primary_command=self._step_goto_auto_annotation,
                badge_action_label="Zatwierdź etap",
                badge_action_command=self._approve_step2_from_wizard,
                visible=bool(getattr(status, "visible", True)),
                is_current=True,
            )
            statuses[index] = forced_status
            break

        if forced_status is None:
            forced_status = WizardStageStatus(
                key="step2",
                title="E2. Tablice",
                state="ready",
                summary=summary,
                details=details,
                primary_label="Dodaj jeszcze tablice w Z2",
                primary_command=self._step_goto_auto_annotation,
                badge_action_label="Zatwierdź etap",
                badge_action_command=self._approve_step2_from_wizard,
                is_current=True,
            )
            statuses.append(forced_status)

        if statuses:
            self._wizard_header_metro_statuses = statuses
            try:
                self._refresh_wizard_stage_metro(statuses)
            except Exception:
                pass

        card = dict(getattr(self, "wizard_stage_cards", {}) or {}).get("step2")
        if card is not None:
            try:
                self._apply_wizard_stage_status(card, forced_status)
            except Exception as e:
                logger.debug(f"Nie udało się wymusić trwałego badge'a E2 na karcie wizarda: {e}")

    def _get_persistent_wizard_stage_badge_override(self, status: WizardStageStatus) -> tuple[str, object | None]:
        key = str(getattr(status, "key", "") or "").strip().lower()
        try:
            current_step = int(CAMPAIGN.get_current_step() or 0)
            step1_status = str(CAMPAIGN.get_step1_status() or "").strip().lower()
            step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
            step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower()
            iteration_target = self._normalize_iteration_target(CAMPAIGN.get_iteration_target())
            project_status = str(CAMPAIGN.get_project_status() or "active").strip().lower()
        except Exception:
            return "", None

        if project_status in {"completed", "paused"}:
            return "", None

        if key == "step1":
            if current_step != 1 or step1_status == "approved" or iteration_target not in {"plate", "char"}:
                return "", None
            try:
                master_pool = CAMPAIGN.get_master_pool_dir()
                has_images = bool(
                    master_pool
                    and Path(master_pool).exists()
                    and Path(master_pool).is_dir()
                    and self._count_images_in_dir(Path(master_pool), recursive=True) > 0
                )
            except Exception:
                has_images = False
            return ("Zatwierdź etap", self._approve_step1_from_wizard) if has_images else ("", None)

        if key == "step2":
            if (
                current_step != 2
                or step1_status != "approved"
                or step2_status == "approved"
                or iteration_target not in {"plate", "char"}
            ):
                return "", None

            try:
                disk_fallback = self._get_step2_render_disk_approval_fallback(iteration_target)
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzić trwałej bramki E2 przy renderze badge'a: {e}")
                disk_fallback = {}

            if bool(disk_fallback.get("ready")):
                return "Zatwierdź etap", self._approve_step2_from_wizard
            return "", None

        if key == "step3":
            if current_step != 3 or iteration_target != "char" or step2_status != "approved":
                return "", None
            if step3_status == "ready":
                return "Zatwierdź etap", self._approve_step3_from_wizard
            if step3_status in {"pending", "needs_rework"}:
                try:
                    readiness = self._detect_campaign_char_ready_dataset_state()
                    if bool(readiness.get("ok")) and int(readiness.get("perfect_count", 0) or 0) > 0:
                        return "Zatwierdź etap", self._approve_step3_from_wizard
                except Exception as e:
                    logger.debug(f"Nie udało się sprawdzić trwałej bramki E3 przy renderze badge'a: {e}")
            return "", None

        if key == "step4":
            if current_step != 4 or iteration_target not in {"plate", "char"}:
                return "", None
            try:
                training_tab = self.app.tabs.get("training") if getattr(self.app, "tabs", None) else None
                if training_tab is not None and hasattr(training_tab, "get_campaign_step4_finish_state"):
                    finish_state = training_tab.get_campaign_step4_finish_state(iteration_target=iteration_target) or {}
                else:
                    finish_state = CAMPAIGN.get_step4_finish_state() or {}
            except Exception:
                finish_state = {}
            try:
                finish_iteration = int(finish_state.get("iteration", 0) or 0)
            except Exception:
                finish_iteration = 0
            finish_target = self._normalize_iteration_target(finish_state.get("target", "")) or iteration_target
            try:
                current_iteration = int(CAMPAIGN.get_current_iteration_num() or 0)
            except Exception:
                current_iteration = 0
            if (
                bool(finish_state.get("ready", False))
                and finish_target == iteration_target
                and finish_iteration == current_iteration
            ):
                return "Zatwierdź etap", self._finish_step4_iteration
            return "Zakończ etap bez treningu", self._finish_step4_without_training

        return "", None

    def _stabilize_wizard_stage_badges(self) -> None:
        if not str(CAMPAIGN.get_active_project_name() or "").strip():
            return

        statuses = []
        try:
            self._clear_dashboard_perf_cache()
            active_state = self._build_active_project_dashboard_state()
            if active_state:
                statuses = self._get_wizard_stage_statuses(
                    active_project=str(active_state.get("active_project", "") or "").strip(),
                    current_step=int(active_state.get("current_step", 1) or 1),
                    iteration_target=str(active_state.get("iteration_target", "") or "").strip().lower(),
                    project_status=str(active_state.get("project_status", "active") or "active").strip().lower(),
                    project_paused_at=str(active_state.get("project_paused_at", "") or "").strip(),
                    project_completed_at=str(active_state.get("project_completed_at", "") or "").strip(),
                    step1_status=str(active_state.get("step1_status", "") or "").strip().lower(),
                    step2_status=str(active_state.get("step2_status", "") or "").strip().lower(),
                    step3_status=str(active_state.get("step3_status", "") or "").strip().lower(),
                )
        except Exception as e:
            logger.debug(f"Nie udało się ponownie przeliczyć badge'y etapów wizarda: {e}")

        if not statuses:
            statuses = [
                status
                for status in list(getattr(self, "_wizard_header_metro_statuses", []) or [])
                if isinstance(status, WizardStageStatus)
            ]
        if not statuses:
            return

        self._wizard_header_metro_statuses = list(statuses)
        try:
            self._refresh_wizard_stage_metro(statuses)
        except Exception:
            pass

        for status in statuses:
            card = self.wizard_stage_cards.get(str(getattr(status, "key", "") or ""))
            if card is None:
                continue
            try:
                self._apply_wizard_stage_status(card, status)
                continue
            except Exception as e:
                logger.debug(f"Nie udało się ustabilizować karty etapu {getattr(status, 'key', '')}: {e}")
            badge_label = str(getattr(status, "badge_action_label", "") or "").strip()
            badge_command = getattr(status, "badge_action_command", None)
            if not badge_label or badge_command is None:
                badge_label, badge_command = self._get_persistent_wizard_stage_badge_override(status)
            self._configure_wizard_stage_badge_cta(
                card,
                visible=bool(getattr(status, "visible", True) and badge_label and badge_command is not None),
                command=badge_command,
                label=badge_label,
            )

        try:
            self.frame.update_idletasks()
        except Exception:
            pass
        try:
            self.frame.after_idle(self._sync_right_panel_scrollregion)
        except Exception:
            pass
        try:
            self._force_current_step2_badge_from_disk()
        except Exception as e:
            logger.debug(f"Nie udało się wymusić badge'a E2 z trwałego stanu projektu: {e}")

    def _schedule_wizard_stage_badge_stabilization(self, delay_ms: int = 140) -> None:
        try:
            pending = getattr(self, "_wizard_stage_badge_stabilize_after_id", None)
            if pending:
                self.frame.after_cancel(pending)
        except Exception:
            pass

        def _run() -> None:
            self._wizard_stage_badge_stabilize_after_id = None
            try:
                self._stabilize_wizard_stage_badges()
            except Exception as e:
                logger.debug(f"Nie udało się ustabilizować badge zatwierdzania etapu: {e}")

        try:
            self._wizard_stage_badge_stabilize_after_id = self.frame.after(max(1, int(delay_ms or 1)), _run)
        except Exception:
            self._wizard_stage_badge_stabilize_after_id = None

    def _apply_wizard_stage_status(self, card: dict, status: WizardStageStatus):
        if not card:
            return
        card["status"] = status

        self._set_pack_visibility(card.get("shell"), bool(status.visible), fill=tk.X, pady=(0, 12))
        if not status.visible:
            return

        palette = getattr(self.app, "palette", {})
        card_bg = palette.get("panel", "#252526")
        emphasized = self._is_wizard_stage_emphasized(status)
        style = self._get_wizard_stage_state_style(status.state, is_current=status.is_current, emphasized=emphasized)

        badge_action_label = str(getattr(status, "badge_action_label", "") or "").strip()
        badge_action_command = getattr(status, "badge_action_command", None)
        if not badge_action_label or badge_action_command is None:
            badge_action_label, badge_action_command = self._get_persistent_wizard_stage_badge_override(status)

        inline_approve = bool(
            badge_action_label
            and badge_action_command is not None
        )
        badge_text = style["label"]
        if inline_approve:
            badge_text = "GOTOWE"
        elif (
            str(getattr(status, "key", "") or "").strip().lower() == "step2"
            and bool(getattr(status, "is_current", False))
            and str(getattr(status, "state", "") or "").strip().lower() in {"ready", "in_progress", "needs_attention"}
        ):
            badge_text = "W TOKU"

        try:
            card["shell"].config(bg=style["border"])
            card["content"].config(bg=card_bg)
            card["header_row"].config(bg=card_bg)
            card["header_status_col"].config(bg=card_bg)
            card["action_row"].config(bg=card_bg)
            card["body"].config(bg=card_bg)
            card["title"].config(text=status.title, fg=style["title_fg"], bg=card_bg)
            card["badge"].config(
                text=badge_text,
                fg=style["badge_fg"],
                bg=style["badge_bg"],
            )
            card["summary"].config(text=str(status.summary or "").strip(), fg=style["summary_fg"], bg=card_bg)
        except Exception:
            pass

        header_badge = card.get("badge")
        if header_badge is not None:
            try:
                header_badge.unbind("<Button-1>")
                header_badge.unbind("<Enter>")
                header_badge.unbind("<Leave>")
            except Exception:
                pass

            if inline_approve:
                success = palette.get("success", "#27ae60")
                surface_success = palette.get("surface_success", "#1f3320")
                badge_fill = blend_hex_colors(surface_success, card_bg, 0.08)
                badge_border = blend_hex_colors(success, card_bg, 0.08)
                badge_fg = palette.get("fg", "#f3f3f3")
                try:
                    header_badge.configure(
                        bg=badge_fill,
                        fg=badge_fg,
                        cursor="",
                        font=("Segoe UI Semibold", 8),
                        padx=10,
                        pady=4,
                        highlightthickness=1,
                        highlightbackground=badge_border,
                        highlightcolor=badge_border,
                    )
                except Exception:
                    pass
            else:
                try:
                    header_badge.configure(
                        cursor="",
                        font=("Segoe UI", 8, "bold"),
                        padx=8,
                        pady=3,
                        highlightthickness=0,
                    )
                except Exception:
                    pass

        summary_text = str(status.summary or "").strip()
        show_summary = bool(summary_text)
        self._set_pack_visibility(
            card.get("summary"),
            show_summary,
            anchor=tk.W,
            fill=tk.X,
            pady=(8, 0),
            before=card.get("details"),
        )

        details_text = str(status.details or "").strip()
        try:
            card["details"].config(text=details_text, bg=card_bg, fg=style.get("details_fg", palette.get("muted", "#c7c7c7")))
        except Exception:
            pass
        self._set_pack_visibility(
            card.get("details"),
            bool(details_text),
            anchor=tk.W,
            fill=tk.X,
            pady=(6, 0),
            before=card.get("action_row"),
        )

        self._render_step1_stage_curtain(card, status, style)

        stage_key = str(status.key or "").strip().upper() or "STAGE"
        row_primary_label = str(status.primary_label or "")
        row_primary_command = status.primary_command
        self._configure_wizard_stage_button(
            card.get("primary_btn"),
            row_primary_label,
            row_primary_command,
            side=tk.LEFT,
            padx=(0, 8),
            debug_id=f"{stage_key}-P1",
        )
        self._configure_wizard_stage_button(
            card.get("secondary_btn"),
            status.secondary_label,
            status.secondary_command,
            side=tk.LEFT,
            padx=(0, 0),
            debug_id=f"{stage_key}-P2",
        )
        footer_actions_visible = bool(
            str(row_primary_label or "").strip()
            or str(status.secondary_label or "").strip()
            or inline_approve
        )
        self._set_pack_visibility(
            card.get("action_row"),
            footer_actions_visible,
            fill=tk.X,
            pady=(10, 0),
        )

        body = card.get("body")
        if body is not None:
            if status.body_mode == "step1_ingest":
                try:
                    self._theme_step1_ingest_panel()
                    self._render_step1_route_actions(getattr(self, "ingest_route_body", None))
                except Exception:
                    pass
            if status.body_mode == "step3_rework":
                self._set_pack_visibility(body, False)
            elif status.body_mode == "step1_ingest":
                step1_mode = self._get_step1_presentation_mode()
                if step1_mode == "operational_summary":
                    self._set_pack_visibility(
                        body,
                        bool(status.body_visible),
                        fill=tk.X,
                        pady=(12, 0),
                        before=card.get("curtain_shell"),
                    )
                else:
                    self._set_pack_visibility(
                        body,
                        bool(status.body_visible),
                        fill=tk.X,
                        pady=(12, 0),
                        before=card.get("action_row"),
                    )
            else:
                self._set_pack_visibility(body, bool(status.body_visible), fill=tk.X, pady=(12, 0))

        self._configure_wizard_stage_badge_cta(
            card,
            visible=inline_approve,
            command=badge_action_command,
            label=badge_action_label,
        )

    def _configure_campaign_banner(self, *, bg: str):
        palette = getattr(self.app, "palette", {})
        panel_bg = str(palette.get("panel", "#252526"))

        try:
            if self.campaign_banner_shell is not None:
                self.campaign_banner_shell.config(bg=panel_bg)
        except Exception:
            pass

        try:
            if self.banner_progress_row is not None:
                self.banner_progress_row.config(bg=panel_bg)
        except Exception:
            pass

        try:
            if self.wizard_header_metro_canvas is not None:
                self.wizard_header_metro_canvas.config(bg=panel_bg)
            if self.wizard_exit_button_canvas is not None:
                self.wizard_exit_button_canvas.config(bg=panel_bg)
        except Exception:
            pass

        self.frame.after_idle(self._draw_wizard_stage_metro)
        self.frame.after_idle(lambda: self._draw_icon_button("exit_project"))

    def _show_project_loading_overlay(
        self,
        *,
        title: str = "Ładuję projekt",
        body: str = "",
        tone: str = "info",
        progress: float | None = None,
    ) -> None:
        progress_value = progress
        overlay = getattr(self, "project_loading_overlay", None)
        card = getattr(self, "project_loading_card", None)
        title_lbl = getattr(self, "project_loading_title_lbl", None)
        body_lbl = getattr(self, "project_loading_body_lbl", None)
        progress_bar = getattr(self, "project_loading_progress", None)
        host = getattr(self, "main_container", None)
        if overlay is None or card is None or title_lbl is None or body_lbl is None or progress_bar is None or host is None:
            return

        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        fg = palette.get("fg", "#f3f3f3")
        tone_key = str(tone or "info").strip().lower()
        if tone_key == "success":
            accent = palette.get("success", "#2ecc71")
        elif tone_key == "error":
            accent = palette.get("error", "#e74c3c")
        else:
            accent = palette.get("accent", "#4f8de3")

        overlay_bg = blend_hex_colors(panel_bg, "#000000", 0.24)
        card_bg = blend_hex_colors(panel_bg, accent, 0.10)
        border_color = blend_hex_colors(accent, palette.get("panel_border", palette.get("border", "#3c3c3c")), 0.48)

        try:
            overlay.configure(bg=overlay_bg, highlightbackground=overlay_bg, highlightcolor=overlay_bg)
            card.configure(bg=card_bg, highlightbackground=border_color, highlightcolor=border_color)
            title_lbl.configure(text=str(title or "").strip(), bg=card_bg, fg=accent)
            body_lbl.configure(text=str(body or "").strip(), bg=card_bg, fg=fg)
            if hasattr(self.app, "ensure_adaptive_wrap"):
                self.app.ensure_adaptive_wrap(body_lbl, container=card, padding=44, min_wrap=240)
        except Exception:
            pass

        try:
            progress_bar.stop()
            progress_bar.configure(
                mode="determinate",
                maximum=100.0,
                value=(0.0 if progress_value is None else max(0.0, min(100.0, float(progress_value)))),
            )
        except Exception:
            pass
        try:
            overlay.place(in_=host, relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
            overlay.lift()
        except Exception:
            pass
        self._project_loading_overlay_visible = True
        try:
            self.frame.update_idletasks()
        except Exception:
            pass

    def _hide_project_loading_overlay(self) -> None:
        overlay = getattr(self, "project_loading_overlay", None)
        progress = getattr(self, "project_loading_progress", None)
        try:
            if progress is not None:
                progress.stop()
        except Exception:
            pass
        try:
            if overlay is not None:
                overlay.place_forget()
        except Exception:
            pass
        self._project_loading_overlay_visible = False

    def _refresh_wizard_empty_state(self, *, projects_available: bool):
        try:
            self._set_pack_visibility(self.wizard_header_shell, True, fill=tk.X, pady=(0, 8))
            self._set_pack_visibility(self.wizard_header_title_lbl, False)
            self.wizard_header_title_lbl.config(text="")
            self.wizard_header_summary_lbl.config(text="Utworz albo otwórz projekt w panelu Projekt.")
            self._set_pack_visibility(self.wizard_header_summary_lbl, True, anchor=tk.W, fill=tk.X, pady=(2, 0))
        except Exception:
            pass
        try:
            self._hide_project_loading_overlay()
        except Exception:
            pass
        self._set_pack_visibility(self.wizard_empty_state_card.get("shell"), False)
        self._set_pack_visibility(self.wizard_stage_cards_host, False)
        self._refresh_wizard_stage_metro([])
        return

    def _build_active_project_dashboard_state(self) -> dict:
        state_started = perf_counter()
        active_proj = str(CAMPAIGN.get_active_project_name() or "").strip()
        if not active_proj:
            return {}

        curr_step = int(CAMPAIGN.get_current_step() or 1)
        step1_status = str(CAMPAIGN.get_step1_status() or "").strip().lower() or "pending"
        step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower() or "pending"
        step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower() or "pending"
        iteration_target = self._get_iteration_target()
        has_saved_step3_progress = self._has_saved_step3_progress()
        project_status = str(CAMPAIGN.get_project_status() or "active").strip().lower() or "active"
        project_paused_at = CAMPAIGN.get_project_paused_at()
        project_completed_at = CAMPAIGN.get_project_completed_at()

        step1_approved = step1_status == "approved"
        if (
            curr_step == 2
            and step1_approved
            and not iteration_target
            and step2_status == "pending"
            and step3_status == "pending"
        ):
            try:
                CAMPAIGN.reset_step1()
                CAMPAIGN.set_current_step(1)
                curr_step = 1
                step1_status = "pending"
                step1_approved = False
                logger.debug(
                    "[CampaignTab] Naprawiono półstan nowej iteracji: E1 było zatwierdzone bez toru. "
                    "Przywrócono E1 jako bieżący etap wyboru toru."
                )
            except Exception as e:
                logger.debug(f"Nie udało się naprawić półstanu E1 bez toru: {e}")

        if curr_step >= 2 and not step1_approved:
            try:
                CAMPAIGN.set_current_step(1)
            except Exception:
                pass
            curr_step = 1

        if self._should_reset_stale_char_iteration_state(
            current_step=curr_step,
            step2_status=step2_status,
            step3_status=step3_status,
            iteration_target=iteration_target,
        ):
            try:
                CAMPAIGN.reset_step3()
                CAMPAIGN.reset_step2()
                CAMPAIGN.set_current_step(2)
                CAMPAIGN.set_iteration_target("")
                logger.debug(
                    "[CampaignTab] Wykryto przestarzały stan toru znaków dla nowej iteracji. "
                    "Zresetowano E2/E3 do czystego wejścia iteracji."
                )
            except Exception as e:
                logger.debug(f"Nie udało się zresetować przestarzałego stanu toru znaków: {e}")
            curr_step = 2
            step2_status = "pending"
            step3_status = "pending"
            iteration_target = ""

        default_iteration_target = self._get_default_step2_iteration_target(
            current_step=curr_step,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
            iteration_target=iteration_target,
        )
        if default_iteration_target in {"plate", "char"} and default_iteration_target != iteration_target:
            CAMPAIGN.set_iteration_target(default_iteration_target)
            iteration_target = default_iteration_target

        if (
            curr_step == 2
            and step1_approved
            and iteration_target == "char"
            and step2_status == "pending"
            and step3_status == "pending"
        ):
            try:
                ready_source = self._get_char_route_ready_source()
            except Exception:
                ready_source = {}
            if ready_source:
                logger.debug(
                    "[CampaignTab] E2 ma gotowe źródło tablic dla toru znaków. "
                    "Nie zatwierdzam automatycznie; decyzję obsługuje wyłącznie badge E2."
                )

        if (
            curr_step <= 2
            and step2_status == "pending"
            and step3_status == "pending"
            and not iteration_target
            and has_saved_step3_progress
        ):
            try:
                CAMPAIGN.reset_step3()
                has_saved_step3_progress = False
            except Exception as e:
                logger.debug(f"Nie udało się wyczyscic przestarzalego stanu Z3 przy starcie iteracji: {e}")

        if not iteration_target and (curr_step >= 3 or step3_status != "pending" or has_saved_step3_progress):
            CAMPAIGN.set_iteration_target("char")
            iteration_target = "char"

        if iteration_target == "char" and (curr_step >= 3 or step3_status != "pending" or has_saved_step3_progress):
            if step2_status != "approved":
                try:
                    CAMPAIGN.approve_step2()
                    step2_status = "approved"
                except Exception as e:
                    logger.debug(f"Nie udało się znormalizować E2 do approved dla aktywnego E3: {e}")

        if iteration_target == "plate" and curr_step >= 4:
            if step2_status != "approved":
                try:
                    CAMPAIGN.approve_step2()
                    step2_status = "approved"
                except Exception as e:
                    logger.debug(f"Nie udało się znormalizować E2 do approved dla aktywnego E4: {e}")

        if iteration_target == "char" and curr_step < 3 and step2_status == "approved" and has_saved_step3_progress:
            if step2_status != "approved":
                CAMPAIGN.approve_step2()
                step2_status = "approved"
            CAMPAIGN.set_current_step(3)
            curr_step = 3

        if iteration_target == "plate" and curr_step == 3 and step2_status == "approved":
            CAMPAIGN.set_current_step(4)
            curr_step = 4

        if iteration_target == "char" and curr_step == 3 and step3_status in {"pending", "needs_rework"}:
            try:
                readiness = self._detect_campaign_char_ready_dataset_state()
                if bool(readiness.get("ok")) and int(readiness.get("perfect_count", 0) or 0) > 0:
                    CAMPAIGN.set_step3_ready()
                    step3_status = "ready"
            except Exception as e:
                logger.debug(f"Nie udało się zaktualizować stanu gotowosci E3 z datasetu znaków: {e}")

        self._log_perf(
            "build_active_dashboard_state",
            state_started,
            threshold_ms=20.0,
            extra=f"step={curr_step}, target={iteration_target or '-'}",
        )
        return {
            "active_project": active_proj,
            "current_step": int(curr_step),
            "step1_status": step1_status,
            "step2_status": step2_status,
            "step3_status": step3_status,
            "iteration_target": iteration_target,
            "project_status": project_status,
            "project_paused_at": project_paused_at,
            "project_completed_at": project_completed_at,
        }

    def _refresh_active_project_wizard_only(self) -> None:
        refresh_started = perf_counter()
        self._clear_dashboard_perf_cache()
        active_state = self._build_active_project_dashboard_state()
        active_project = str(active_state.get("active_project") or "").strip()
        if not active_project:
            self._refresh_dashboard()
            return

        try:
            self._ensure_wizard_stage_ui_ready()
        except Exception:
            pass

        palette = getattr(self.app, "palette", {})
        header_bg = palette.get("panel", "#252526")
        accent = palette.get("accent", "#2980b9")
        success = palette.get("success", "#27ae60")
        warning = palette.get("warning", "#d35400")
        surface_info = palette.get("surface_info", palette.get("panel_alt", "#252526"))
        surface_success = palette.get("surface_success", palette.get("panel_alt", "#1f3320"))
        surface_warning = palette.get("surface_warning", palette.get("panel_alt", "#3a2323"))

        curr_step = int(active_state.get("current_step", 1) or 1)
        step1_status = str(active_state.get("step1_status", "pending") or "pending")
        step2_status = str(active_state.get("step2_status", "pending") or "pending")
        step3_status = str(active_state.get("step3_status", "pending") or "pending")
        iteration_target = str(active_state.get("iteration_target", "") or "").strip().lower()
        project_status = str(active_state.get("project_status", "active") or "active").strip().lower()
        project_paused_at = str(active_state.get("project_paused_at", "") or "").strip()
        project_completed_at = str(active_state.get("project_completed_at", "") or "").strip()
        project_paused = project_status == "paused"
        project_completed = project_status == "completed"
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)

        project_title = self._format_project_iteration_title(active_project, iter_num)
        banner_bg = surface_success
        if project_completed:
            banner_bg = surface_warning
        elif project_paused:
            banner_bg = surface_info

        self._configure_campaign_banner(bg=banner_bg)
        self._set_icon_button_enabled("exit_project", True)
        self._refresh_wizard_active_dashboard(
            active_project=active_project,
            current_step=curr_step,
            iteration_target=iteration_target,
            project_status=project_status,
            project_paused_at=project_paused_at,
            project_completed_at=project_completed_at,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
        )
        try:
            if bool(getattr(self, "_project_loading_overlay_visible", False)):
                self._show_project_loading_overlay(
                    title="Ładuję projekt",
                    body="Kończę odświeżanie i ustawiam docelowy widok projektu.",
                    tone="success",
                    progress=100.0,
                )
                self.frame.after(90, self._hide_project_loading_overlay)
            else:
                self._hide_project_loading_overlay()
        except Exception:
            pass
        self._update_main_tabs_highlight(curr_step=curr_step, has_project=True)
        self.app.update_campaign_tab_access()
        self.frame.update_idletasks()
        try:
            self._stabilize_wizard_stage_badges()
        except Exception as e:
            logger.debug(f"Nie udało się natychmiast ustabilizować badge'y wizarda: {e}")
        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self._schedule_pending_wizard_stage_focus()
        self._log_perf(
            "refresh_active_project_wizard_only",
            refresh_started,
            threshold_ms=20.0,
            extra=f"step={curr_step}, target={iteration_target or '-'}",
        )

    def _cancel_deferred_project_open_tasks(self) -> None:
        for attr_name in (
            "_project_open_refresh_after_id",
            "_project_open_context_after_id",
            "_project_open_post_refresh_after_id",
            "_wizard_stage_badge_stabilize_after_id",
        ):
            pending = getattr(self, attr_name, None)
            if not pending:
                continue
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
            setattr(self, attr_name, None)

    def _build_project_loading_stage_statuses(
        self,
        *,
        active_project: str,
        current_step: int,
        iteration_target: str,
    ) -> list[WizardStageStatus]:
        clamped_step = min(max(int(current_step or 1), 1), 4)

        statuses = []

        stage_specs = (
            ("step1", "E1. Wejście i tor iteracji"),
            ("step2", "E2. Tablice"),
            ("step3", "E3. Znaki i gold pack"),
            ("step4", "E4. Dataset i trening"),
        )

        for idx, (key, title) in enumerate(stage_specs, start=1):
            if idx < clamped_step:
                state = "ready"
                summary = "Odtwarzam zapisany stan etapu."
            elif idx == clamped_step:
                state = "in_progress"
                summary = "Ładuję bieżący stan etapu."
            else:
                state = "locked"
                summary = "Stan etapu zostanie odczytany za chwilę."

            statuses.append(
                WizardStageStatus(
                    key=key,
                    title=title,
                    state=state,
                    summary=summary,
                    details="To chwilowy stan podczas otwierania projektu.",
                    body_mode="",
                    body_visible=False,
                    is_current=bool(idx == clamped_step),
                )
            )

        return statuses

    def _show_project_loading_dashboard(self, active_project: str) -> None:
        if not active_project:
            return

        palette = getattr(self.app, "palette", {})
        header_bg = palette.get("panel", "#252526")
        info_fg = palette.get("accent", "#2980b9")
        info_bg = palette.get("surface_info", palette.get("panel_alt", "#252526"))
        muted = palette.get("muted", "#c7c7c7")
        muted_dim = palette.get("muted_dim", "#9a9a9a")

        current_step = int(CAMPAIGN.get_current_step() or 1)
        iteration_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)

        try:
            self._refresh_projects_list()
        except Exception:
            pass

        try:
            self._show_project_loading_overlay(
                title="Ładuję projekt",
                body="Odtwarzam stan etapów, modele i kontekst roboczy projektu.",
                tone="info",
                progress=12.0,
            )
        except Exception:
            pass

        try:
            self._collapse_all_wizard_stage_curtains()
        except Exception:
            pass

        try:
            self._configure_campaign_banner(bg=info_bg)
            self._set_icon_button_enabled("exit_project", True)
        except Exception:
            pass

        for mt in ["vehicle", "plate", "char"]:
            try:
                getattr(self, f"lbl_model_{mt}").config(text="Ładowanie...", fg=muted)
            except Exception:
                pass
            try:
                lbl_meta = getattr(self, f"lbl_model_{mt}_meta", None)
                if lbl_meta is not None:
                    lbl_meta.config(text="Utworzono: -", fg=muted_dim)
            except Exception:
                pass
            try:
                btn_model = getattr(self, f"btn_model_{mt}", None)
                if btn_model is not None:
                    btn_model.config(state="disabled")
            except Exception:
                pass

        try:
            self.btn_open_proj.config(state="normal")
            self.btn_del_proj.config(state="normal")
            self.btn_exit_project.config(state="normal")
            self.btn_complete_project.config(text="Ładowanie...", state="disabled", style="TButton")
        except Exception:
            pass

        try:
            self._set_pack_visibility(self.wizard_empty_state_card.get("shell"), False)
            self._set_pack_visibility(self.wizard_stage_cards_host, True, fill=tk.X)
            self._set_pack_visibility(self.wizard_header_shell, False)
            self._set_pack_visibility(self.wizard_header_title_lbl, False)
            self._set_pack_visibility(self.wizard_header_summary_lbl, False)
            self.wizard_header_title_lbl.config(text="")
            self.wizard_header_summary_lbl.config(text="")
        except Exception:
            pass

        statuses = self._build_project_loading_stage_statuses(
            active_project=active_project,
            current_step=current_step,
            iteration_target=iteration_target,
        )
        try:
            self._refresh_wizard_stage_metro(statuses)
            for status in statuses:
                card = self.wizard_stage_cards.get(status.key)
                if card is not None:
                    self._apply_wizard_stage_status(card, status)
        except Exception:
            pass

        try:
            self._update_main_tabs_highlight(curr_step=current_step, has_project=True)
        except Exception:
            pass

        try:
            self.frame.update_idletasks()
        except Exception:
            pass

    def _refresh_wizard_active_dashboard(
        self,
        *,
        active_project: str,
        current_step: int,
        iteration_target: str,
        project_status: str,
        project_paused_at: str,
        project_completed_at: str,
        step1_status: str,
        step2_status: str,
        step3_status: str,
    ):
        self._set_pack_visibility(self.wizard_empty_state_card.get("shell"), False)
        self._set_pack_visibility(self.wizard_stage_cards_host, True, fill=tk.X)

        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        project_status_norm = str(project_status or "active").strip().lower()
        project_completed = project_status_norm == "completed"
        project_paused = project_status_norm == "paused"
        project_suspended = bool(project_completed or project_paused)

        try:
            self._set_pack_visibility(self.wizard_header_shell, False)
            self._set_pack_visibility(self.wizard_header_title_lbl, False)
            self._set_pack_visibility(self.wizard_header_summary_lbl, False)
            self.wizard_header_title_lbl.config(text="")
            self.wizard_header_summary_lbl.config(text="")
        except Exception:
            pass

        statuses = self._get_wizard_stage_statuses(
            active_project=active_project,
            current_step=current_step,
            iteration_target=iteration_target,
            project_status=project_status_norm,
            project_paused_at=project_paused_at,
            project_completed_at=project_completed_at,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
        )
        self._refresh_wizard_stage_metro(statuses)

        for status in statuses:
            card = self.wizard_stage_cards.get(status.key)
            if card is not None:
                self._apply_wizard_stage_status(card, status)
        self._schedule_wizard_stage_badge_stabilization()

    def _format_project_status_timestamp(self, raw_value: str) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return "brak daty"

        display = value.replace("T", " ").strip() or "brak daty"
        formatter = getattr(self.app, "_format_project_created_at", None)
        if callable(formatter):
            try:
                return str(formatter(value) or "").strip() or display
            except Exception:
                return display
        return display

    @staticmethod
    def _format_project_iteration_title(project_name: str, iteration_num: int | None = None) -> str:
        name = str(project_name or "").strip()
        if not name:
            return "Brak aktywnego projektu"
        try:
            iter_value = max(1, int(iteration_num or 1))
        except Exception:
            iter_value = 1
        return f"Projekt: {name} | Iteracja {iter_value}"

    def _align_step3_details_with_cta_labels(
        self,
        *,
        state: str,
        details: str,
        primary_label: str = "",
        secondary_label: str = "",
        badge_label: str = "",
    ) -> str:
        state_key = str(state or "").strip().lower()
        primary = str(primary_label or "").strip()
        secondary = str(secondary_label or "").strip()
        badge = str(badge_label or "").strip()

        if state_key == "ready":
            actions = []
            if badge:
                actions.append(f"zamknąć E3 przyciskiem „{badge}”")
            if primary:
                actions.append(f"wrócić do Z2 przez „{primary}”")
            if secondary:
                actions.append(f"pracować dalej w Z3 przez „{secondary}”")
            if actions:
                if len(actions) == 1:
                    return f"Możesz {actions[0]}."
                return f"Możesz {', '.join(actions[:-1])} albo {actions[-1]}."

        return str(details or "").strip()

    def _get_wizard_stage_statuses(
        self,
        *,
        active_project: str,
        current_step: int,
        iteration_target: str,
        project_status: str,
        project_paused_at: str,
        project_completed_at: str,
        step1_status: str,
        step2_status: str,
        step3_status: str,
    ) -> list[WizardStageStatus]:
        statuses: list[WizardStageStatus] = []
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        project_status_norm = str(project_status or "active").strip().lower()
        project_completed = project_status_norm == "completed"
        project_paused = project_status_norm == "paused"
        project_suspended = bool(project_completed or project_paused)
        target_label = self._iteration_target_label(iteration_target)
        iter_image_count = self._get_iteration_image_count()
        step1_approved = str(step1_status or "").strip().lower() == "approved"
        if not step1_approved and int(current_step or 1) != 1:
            current_step = 1
            try:
                CAMPAIGN.set_current_step(1)
            except Exception:
                pass
        master_pool = CAMPAIGN.get_master_pool_dir()
        master_pool_ready = bool(master_pool and master_pool.exists() and master_pool.is_dir())
        draft_plan = self._get_active_step1_draft_plan()
        plan_count = int(draft_plan.get("selected_total", 0) or 0)
        plate_ready_source = self._get_plate_route_ready_source() if iteration_target == "plate" else {}
        char_ready_source = self._get_char_route_ready_source() if iteration_target == "char" else {}
        char_route_source_state = self._get_char_route_source_state() if iteration_target == "char" else {}
        plate_approved_stats = self._get_plate_approved_set_stats()
        try:
            project_approved_images_current = int(plate_approved_stats.get("images", 0) or 0)
        except Exception:
            project_approved_images_current = 0
        try:
            project_approved_plates_current = int(plate_approved_stats.get("plates", 0) or 0)
        except Exception:
            project_approved_plates_current = 0
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())
        training_tab = self.app.tabs.get("training") if getattr(self.app, "tabs", None) else None
        plate_step4_gate = {
            "ok": True,
            "reason": "",
            "message": "",
            "annotated_images": 0,
            "required_images": 0,
            "required_plates": int(getattr(self, "STEP2_PLATE_MIN_PLATES", 10) or 10),
            "source_run": "",
        }
        char_step4_gate = {
            "ok": True,
            "reason": "",
            "message": "",
            "ready_dataset": "",
            "dataset_hint": "",
            "train_images": 0,
            "val_images": 0,
            "test_images": 0,
            "validation_message": "",
        }
        if iteration_target == "plate" and (current_step >= 4 or str(step2_status or "").strip().lower() == "approved"):
            try:
                if training_tab is not None and hasattr(training_tab, "get_campaign_step4_readiness"):
                    plate_step4_gate = training_tab.get_campaign_step4_readiness(iteration_target="plate")
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzic gotowosci E4 dla toru tablic: {e}")
            try:
                gate_images = int(plate_step4_gate.get("project_approved_images", 0) or 0)
            except Exception:
                gate_images = 0
            try:
                gate_plates = int(plate_step4_gate.get("project_approved_plates", 0) or 0)
            except Exception:
                gate_plates = 0
            if project_approved_images_current > gate_images:
                try:
                    gate_annotated_images = int(plate_step4_gate.get("annotated_images", 0) or 0)
                except Exception:
                    gate_annotated_images = 0
                plate_step4_gate["project_approved_images"] = project_approved_images_current
                plate_step4_gate["annotated_images"] = max(
                    gate_annotated_images,
                    project_approved_images_current,
                )
            if project_approved_plates_current > gate_plates:
                plate_step4_gate["project_approved_plates"] = project_approved_plates_current
            if project_approved_images_current > 0 and not str(plate_step4_gate.get("source_run") or "").strip():
                plate_step4_gate["source_run"] = "ApprovedSet projektu"

        helper_char_step4_gate = (
            self._detect_campaign_char_ready_dataset_state()
            if iteration_target == "char" and (current_step >= 3 or str(step3_status or "").strip().lower() in {"approved", "needs_rework", "ready"})
            else {}
        )

        if iteration_target == "char" and (current_step >= 3 or str(step3_status or "").strip().lower() in {"approved", "needs_rework", "ready"}):
            try:
                if training_tab is not None and hasattr(training_tab, "get_campaign_step4_readiness"):
                    char_step4_gate = training_tab.get_campaign_step4_readiness(iteration_target="char")
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzic gotowosci E4 dla toru znaków: {e}")
        if helper_char_step4_gate:
            if not bool(helper_char_step4_gate.get("ok")):
                char_step4_gate = dict(helper_char_step4_gate)
            elif not bool(char_step4_gate.get("ok")) or not str(char_step4_gate.get("ready_dataset") or "").strip():
                char_step4_gate = dict(helper_char_step4_gate)
            if (
                bool(helper_char_step4_gate.get("ok"))
                and int(helper_char_step4_gate.get("perfect_count", 0) or 0) > 0
                and iteration_target == "char"
                and current_step == 3
                and str(step3_status or "").strip().lower() in {"pending", "needs_rework"}
            ):
                step3_status = "ready"

        char_repair_guidance = (
            self._get_char_repair_guidance(char_route_source_state)
            if iteration_target == "char"
            else {}
        )

        plate_step4_blocked = bool(
            iteration_target == "plate"
            and (current_step >= 4 or str(step2_status or "").strip().lower() == "approved")
            and not bool(plate_step4_gate.get("ok", True))
        )
        plate_step4_reason = str(plate_step4_gate.get("reason") or "").strip().lower()
        char_step4_blocked = bool(
            iteration_target == "char"
            and (current_step >= 4 or str(step3_status or "").strip().lower() == "approved")
            and not bool(char_step4_gate.get("ok", True))
        )
        step4_gate_blocked = bool(plate_step4_blocked or char_step4_blocked)
        step4_finish_state = {}
        try:
            if training_tab is not None and hasattr(training_tab, "get_campaign_step4_finish_state"):
                step4_finish_state = training_tab.get_campaign_step4_finish_state(iteration_target=iteration_target) or {}
            else:
                step4_finish_state = CAMPAIGN.get_step4_finish_state() or {}
        except Exception:
            try:
                step4_finish_state = CAMPAIGN.get_step4_finish_state() or {}
            except Exception:
                step4_finish_state = {}
        step4_finish_ready = bool(step4_finish_state.get("ready", False))
        step4_finish_target = self._normalize_iteration_target(step4_finish_state.get("target", ""))
        step4_finish_iteration = int(step4_finish_state.get("iteration", 0) or 0)
        if not step4_finish_target:
            step4_finish_target = iteration_target
        step4_can_advance = bool(
            current_step == 4
            and not step4_gate_blocked
            and step4_finish_ready
            and step4_finish_target == iteration_target
            and step4_finish_iteration == int(iter_num or 0)
        )

        manifest = self._load_ingest_manifest_cached()
        manifest_mode = str((manifest or {}).get("selection_mode", "") or "").strip().lower() if isinstance(manifest, dict) else ""
        is_iteration_reuse = bool(iter_num > 1 and manifest_mode in {"iteration_reuse", "pool_reuse", "stage_reuse"})
        step1_context = self._get_step1_manifest_context(manifest if isinstance(manifest, dict) else None)
        project_pool_total = int(step1_context.get("project_pool_total_after", step1_context.get("project_pool_total", 0)) or 0)
        approved_images = max(
            int(step1_context.get("approved_images", 0) or 0),
            int(project_approved_images_current or 0),
        )
        approved_plates = max(
            int(step1_context.get("approved_plates", 0) or 0),
            int(project_approved_plates_current or 0),
        )
        source_total = int(step1_context.get("source_total", 0) or 0)
        new_to_project_count = int(step1_context.get("new_to_project_count", 0) or 0)
        project_overlap_count = int(step1_context.get("project_overlap_filenames", 0) or 0)
        approved_overlap_count = int(step1_context.get("skipped_duplicate_approved", 0) or 0)
        current_iteration_package = int(
            step1_context.get("current_iteration_package_count", 0)
            or iter_image_count
            or 0
        )
        try:
            current_master_pool_dir = CAMPAIGN.get_master_pool_dir()
        except Exception:
            current_master_pool_dir = None
        current_source_dir_count = (
            self._count_images_in_dir(current_master_pool_dir, recursive=True)
            if current_master_pool_dir is not None and current_master_pool_dir.exists() and current_master_pool_dir.is_dir()
            else 0
        )
        source_diverged = bool(
            current_source_dir_count > 0
            and current_iteration_package > 0
            and current_source_dir_count != current_iteration_package
        )
        source_label = str(step1_context.get("source_label", "") or "").strip()
        target_selected = bool(iteration_target in {"plate", "char"})

        project_scope_parts: list[str] = []
        if approved_images > 0 or approved_plates > 0:
            project_scope_parts.append(
                f"Pudełko tablic zatwierdzonych: {approved_images} zdjęć / {approved_plates} tablic."
            )
        if project_pool_total > 0:
            project_scope_parts.append(f"Pula projektu informacyjnie: {project_pool_total} zdjęć.")
        project_scope_text = " ".join(project_scope_parts).strip()
        step1_has_selected_image_folder = bool(current_source_dir_count > 0)
        step1_ready_for_approval = bool(
            not project_suspended
            and current_step == 1
            and target_selected
            and not step1_approved
            and step1_has_selected_image_folder
        )
        step1_body_visible = bool(
            not project_suspended
            and (
                (current_step == 1 and not step1_approved)
                or (current_step >= 2 and not target_selected)
            )
        )

        if step1_approved and not target_selected:
            step1_state = "needs_attention"
            step1_summary = "E1 ma zdjęcia, ale brakuje zapisanego toru iteracji."
            step1_details = "To najpewniej starszy zapis projektu. Wybierz tor w E1, aby E2 mogło przejść do pracy na tablicach."
        elif step1_approved and iter_image_count > 0:
            step1_state = "done"
            step1_summary = ""
            step1_details = ""
        elif iter_image_count > 0 and not target_selected:
            step1_state = "needs_attention"
            step1_summary = f"W folderze iteracji są już {iter_image_count} zdjęcia. Wybierz jeszcze tor iteracji."
            step1_details = "Tor wybierasz w panelu E1. Dopiero wtedy można zatwierdzić E1 i przejść do E2."
        elif iter_image_count > 0:
            step1_state = "needs_attention"
            step1_summary = f"W folderze iteracji są już {iter_image_count} zdjęcia, ale E1 czeka na zatwierdzenie."
            step1_details = "Zejdź do panelu E1 i zatwierdź zestaw zdjęć, aby odblokować E2."
        elif master_pool_ready or plan_count > 0 or current_step == 1:
            step1_state = "in_progress" if current_step == 1 else "ready"
            step1_summary = ""
            step1_details = ""
        else:
            step1_state = "ready"
            step1_summary = ""
            step1_details = ""

        if step1_body_visible and current_step == 1 and not step1_approved:
            step1_intro = self._get_step1_assets_intro_text()
            step1_details = (
                f"{step1_intro}\n{step1_details}"
                if str(step1_details or "").strip()
                else step1_intro
            )

        statuses.append(
            WizardStageStatus(
                key="step1",
                title="E1. Wejście i tor iteracji",
                state=step1_state,
                summary=step1_summary,
                details=step1_details,
                primary_label="",
                primary_command=None,
                badge_action_label=("Zatwierdź etap" if step1_ready_for_approval else ""),
                badge_action_command=(self._approve_step1_from_wizard if step1_ready_for_approval else None),
                body_mode="step1_ingest",
                body_visible=step1_body_visible,
                is_current=bool(not project_suspended and current_step == 1),
            )
        )

        step2_vm = self._get_annotation_step2_view_model()
        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        try:
            step2_wizard_status = (
                dict(annotation_tab.get_campaign_step2_wizard_status() or {})
                if annotation_tab is not None and hasattr(annotation_tab, "get_campaign_step2_wizard_status")
                else {}
            )
        except Exception:
            step2_wizard_status = {}
        step2_title = "E2. Tablice"
        if step2_vm is not None:
            primary_cta = getattr(step2_vm, "primary_cta", None)
            secondary_cta = getattr(step2_vm, "secondary_cta", None)
            step2_title = str(getattr(step2_vm, "title", "") or "").strip() or step2_title
            step2_state = str(getattr(step2_vm, "state", "") or "").strip() or "locked"
            step2_summary = str(getattr(step2_vm, "summary", "") or "").strip()
            step2_details = str(getattr(step2_vm, "details", "") or "").strip()
            step2_primary_label = str(getattr(primary_cta, "label", "") or "").strip()
            step2_primary_command = self._resolve_step2_wizard_action_command(
                str(getattr(primary_cta, "command_id", "") or "").strip(),
                context=dict(getattr(primary_cta, "command_context", {}) or {}),
            )
            step2_secondary_label = str(getattr(secondary_cta, "label", "") or "").strip()
            step2_secondary_command = self._resolve_step2_wizard_action_command(
                str(getattr(secondary_cta, "command_id", "") or "").strip(),
                context=dict(getattr(secondary_cta, "command_context", {}) or {}),
            )
            vm_current_step = int(getattr(step2_vm, "current_step", current_step) or current_step)
            step2_body_mode = ""
            step2_body_visible = False
        elif not iteration_target:
            step2_state = "needs_attention" if current_step >= 2 else "locked"
            step2_summary = "Brak wybranego toru iteracji."
            step2_details = (
                "Wybór toru należy teraz do E1. Wróć do E1, wybierz tor tablic albo tor znaków, "
                "a dopiero potem zatwierdź katalog zdjęć wejściowych."
            )
            step2_primary_label = ""
            step2_primary_command = None
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = ""
            step2_body_visible = False
        else:
            step2_primary_label = self._get_step2_jump_button_text(iteration_target)
            step2_primary_command = self._step_goto_auto_annotation
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = ""
            step2_body_visible = False

            if current_step == 2 and step1_approved:
                step2_state = "in_progress"
                step2_summary = "E2 jest w toku: przygotuj anotacje tablic w Z2."
                step2_details = (
                    "Przejdź do Z2, aby utworzyć albo poprawić anotacje tablic "
                    "dla wybranego katalogu zdjęć z E1."
                )
            elif current_step > 2 or str(step2_status or "").strip().lower() == "approved":
                step2_state = "done"
                step2_summary = "E2 zostało już domknięte."
                step2_details = "Dalsza praca odbywa się w kolejnych etapach wizarda."
                step2_primary_label = ""
                step2_primary_command = None
            else:
                step2_state = "locked"
                step2_summary = "E2 odblokuje się po zatwierdzeniu katalogu zdjęć wejściowych z E1."
                step2_details = "Najpierw domknij E1."

        if current_step == 2 and not iteration_target:
            step2_primary_label = ""
            step2_primary_command = None
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_summary = "Brak wybranego toru iteracji."
            step2_details = (
                "Ten stan oznacza stary albo niepełny zapis projektu. Wróć do E1, wybierz tor iteracji "
                "i zatwierdź E1 ponownie, żeby E2 mogło pracować wyłącznie jako etap tablic."
            )

        step2_already_approved = str(step2_status or "").strip().lower() == "approved"
        step2_ready_for_approval = bool(
            step1_approved
            and step2_wizard_status.get("ready_for_approval")
            and not step2_already_approved
        )
        step2_approval_action = str(step2_wizard_status.get("approval_action", "") or "").strip().lower()
        step2_approval_iteration_target = str(
            step2_wizard_status.get("approval_iteration_target", "") or ""
        ).strip().lower()
        if step2_ready_for_approval and step2_approval_iteration_target not in {"plate", "char"}:
            step2_approval_iteration_target = self._normalize_iteration_target(iteration_target)
        if (
            not step2_already_approved
            and step1_approved
            and int(current_step or 0) <= 2
            and not step2_ready_for_approval
        ):
            fallback_approval_context = {}
            try:
                if annotation_tab is not None and hasattr(annotation_tab, "_get_campaign_step2_approval_context"):
                    fallback_approval_context = dict(annotation_tab._get_campaign_step2_approval_context() or {})
            except Exception:
                fallback_approval_context = {}
            fallback_target = str(
                iteration_target or fallback_approval_context.get("iteration_target") or ""
            ).strip().lower()
            try:
                fallback_step = int(fallback_approval_context.get("current_step") or current_step or 0)
            except Exception:
                fallback_step = int(current_step or 0)
            try:
                campaign_fallback_step = int(current_step or 0)
            except Exception:
                campaign_fallback_step = fallback_step
            if (
                (campaign_fallback_step == 2 or fallback_step == 2)
                and fallback_target in {"plate", "char"}
            ):
                disk_fallback = self._get_step2_render_disk_approval_fallback(fallback_target)
                if bool(disk_fallback.get("ready")):
                    step2_ready_for_approval = True
                    if not step2_approval_action:
                        step2_approval_action = str(disk_fallback.get("action") or "approve_stage").strip()
                    if not step2_approval_iteration_target:
                        step2_approval_iteration_target = fallback_target
        if step2_ready_for_approval:
            approval_iteration_target = step2_approval_iteration_target
            next_stage_label = "E4" if approval_iteration_target == "plate" else "E3"
            last_target = self._get_last_iteration_target()
            same_route_as_previous = bool(
                approval_iteration_target in {"plate", "char"}
                and last_target == approval_iteration_target
            )
            if approval_iteration_target == "char" and step2_approval_action == "continue_characters":
                step2_state = "ready"
                step2_summary = "Źródło tablic dla wybranego katalogu zdjęć jest już gotowe."
                step2_details = (
                    "Minimalny próg wejścia do E3 jest już spełniony, więc badge po prawej może od razu zamknąć E2. "
                    "Jeśli jednak masz jeszcze chwilę, zwykle więcej daje dopisanie kolejnych poprawnych tablic w Z2 niż samo szybkie przejście dalej."
                )
                step2_primary_label = "Dodaj jeszcze tablice w Z2"
                step2_primary_command = lambda: self._step_return_to_annotation_review(mark_step3_rework=False)
            else:
                step2_state = "ready"
                step2_summary = "Etap 2 możesz już zamknąć, ale warto jeszcze rozważyć dopisanie tablic w Z2."
                step2_details = (
                    f"Minimalny próg projektu jest już spełniony, więc możesz od razu zamknąć E2 i odblokować {next_stage_label}. "
                    "Jeśli jednak zależy Ci na lepszym materiale do kolejnych iteracji modelu, zwykle bardziej opłaca się dopisać jeszcze kilka poprawnych anotacji niż kończyć etap od razu."
                )
                if same_route_as_previous:
                    step2_details += " Dotyczy to szczególnie sytuacji, gdy zostajesz w tym samym torze co poprzednio."
                else:
                    step2_details += " To dobry moment, żeby zdecydować, czy chcesz tylko przejść dalej, czy jeszcze trochę wzmocnić zbiór projektu."
                step2_primary_label = "Dodaj jeszcze tablice w Z2"
                step2_primary_command = self._step_goto_auto_annotation
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = ""
            step2_body_visible = False

        if step2_state == "done":
            step2_primary_label = ""
            step2_primary_command = None
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = ""
            step2_body_visible = False

        statuses.append(
            WizardStageStatus(
                key="step2",
                title=step2_title,
                state=step2_state,
                summary=step2_summary,
                details=step2_details,
                primary_label=step2_primary_label,
                primary_command=step2_primary_command,
                secondary_label=step2_secondary_label,
                secondary_command=step2_secondary_command,
                badge_action_label=("Zatwierdź etap" if step2_ready_for_approval else ""),
                badge_action_command=(self._approve_step2_from_wizard if step2_ready_for_approval else None),
                body_mode=step2_body_mode,
                body_visible=step2_body_visible,
                is_current=bool(
                    not project_suspended
                    and (
                        current_step == 2
                        or plate_step4_reason in {"missing_plate_annotations", "insufficient_plate_annotations"}
                    )
                ),
            )
        )

        step3_vm = self._get_campaign_step3_view_model(
            current_step=current_step,
            iteration_target=iteration_target,
            project_completed=project_suspended,
            step2_status=step2_status,
            step3_status=step3_status,
            char_ready_source=char_ready_source,
            char_repair_guidance=char_repair_guidance,
            char_step4_gate=char_step4_gate,
        )
        step3_primary_cta = getattr(step3_vm, "primary_cta", None)
        step3_secondary_cta = getattr(step3_vm, "secondary_cta", None)
        step3_state = str(getattr(step3_vm, "state", "") or "").strip() or "locked"
        step3_summary = str(getattr(step3_vm, "summary", "") or "").strip()
        step3_details = str(getattr(step3_vm, "details", "") or "").strip()
        step3_primary_label = str(getattr(step3_primary_cta, "label", "") or "").strip()
        step3_primary_command = self._resolve_step3_wizard_action_command(
            str(getattr(step3_primary_cta, "command_id", "") or "").strip(),
            context=dict(getattr(step3_primary_cta, "command_context", {}) or {}),
        )
        step3_secondary_label = str(getattr(step3_secondary_cta, "label", "") or "").strip()
        step3_secondary_command = self._resolve_step3_wizard_action_command(
            str(getattr(step3_secondary_cta, "command_id", "") or "").strip(),
            context=dict(getattr(step3_secondary_cta, "command_context", {}) or {}),
        )

        if step3_state.lower() == "ready":
            step3_summary = "Etap 3 jest gotowy do zamknięcia albo dalszej pracy."
            step3_details = (
                "Możesz zamknąć E3, oznaczyć więcej tablic w Z2 albo pracować dalej na znakach tablic w Z3."
            )
            step3_primary_label = "Oznacz więcej tablic"
            step3_primary_command = self._step_return_to_annotation_review
            step3_secondary_label = "Pracuj na znakach tablic"
            step3_secondary_command = self._step_goto_characters

        step3_badge_label = "Zatwierdź etap" if step3_state.lower() == "ready" else ""
        step3_details = self._align_step3_details_with_cta_labels(
            state=step3_state,
            details=step3_details,
            primary_label=step3_primary_label,
            secondary_label=step3_secondary_label,
            badge_label=step3_badge_label,
        )

        statuses.append(
            WizardStageStatus(
                key="step3",
                title=str(getattr(step3_vm, "title", "") or "").strip() or "E3. Znaki i gold pack",
                state=step3_state,
                summary=step3_summary,
                details=step3_details,
                primary_label=step3_primary_label,
                primary_command=step3_primary_command,
                secondary_label=step3_secondary_label,
                secondary_command=step3_secondary_command,
                badge_action_label=step3_badge_label,
                badge_action_command=(
                    self._approve_step3_from_wizard
                    if step3_state.lower() == "ready"
                    else None
                ),
                body_mode=str(getattr(step3_vm, "body_mode", "") or "").strip(),
                body_visible=bool(getattr(step3_vm, "body_visible", False)),
                is_current=bool(not project_suspended and current_step == 3 and iteration_target == "char"),
            )
        )

        step4_badge_label = ""
        step4_badge_command = None

        if project_completed:
            step4_state = "done"
            step4_summary = "Projekt został zakończony. Z4 pozostaje dostępne do przeglądu wyników i analiz."
            step4_details = "Jeśli chcesz uruchomić kolejną iterację w tym projekcie, wznów go z karty projektu."
            step4_secondary_label = "Wznów projekt"
            step4_secondary_command = self._toggle_project_completion
        elif project_paused:
            step4_state = "done"
            step4_summary = "Projekt został odłożony. Możesz wrócić do niego później bez utraty stanu iteracji."
            step4_details = "Po wznowieniu możesz wrócić do Z4 albo rozpocząć nową iterację w tym samym projekcie."
            step4_secondary_label = "Wznów projekt"
            step4_secondary_command = self._toggle_project_completion
        elif current_step >= 5:
            step4_state = "done"
            step4_summary = "Iteracja została domknięta. Możesz przejść do E1 kolejnej iteracji."
            step4_details = (
                "Z4 pozostaje dostępne do przeglądu datasetu, runów i analiz. "
                "Jeśli poprzednio zamknąłeś modal decyzji bez przejścia dalej, użyj badge'a „Przejdź do E1”."
            )
            step4_secondary_label = ""
            step4_secondary_command = None
            step4_badge_label = "Przejdź do E1"
            step4_badge_command = self._advance_iteration
        elif step4_can_advance:
            step4_state = "ready"
            step4_summary = "Trening tej iteracji jest zakończony. E4 jest gotowe do zatwierdzenia."
            step4_details = (
                "Model i run treningowy są już gotowe. Użyj badge'a „Zatwierdź etap”, "
                "aby formalnie zamknąć E4 i dopiero potem otwierać kolejną iterację projektu."
            )
            step4_secondary_label = ""
            step4_secondary_command = None
            step4_badge_label = "Zatwierdź etap"
            step4_badge_command = self._finish_step4_iteration
        elif plate_step4_blocked:
            step4_state = "needs_attention"
            if plate_step4_reason == "stale_plate_dataset":
                step4_summary = "Z4 wymaga przebudowy datasetu tablic."
                step4_details = str(plate_step4_gate.get("message") or "").strip() or (
                    "ApprovedSet projektu jest już większy niż ostatnio przygotowany dataset treningowy. "
                    "Przejdź do Z4 i przebuduj dataset w PZ1."
                )
            else:
                step4_summary = "Z4 czeka na uzupełnienie oznaczeń w Z2."
                step4_details = str(plate_step4_gate.get("message") or "").strip() or (
                    f"W torze tablic potrzebujesz co najmniej {int(getattr(self, 'STEP2_PLATE_MIN_PLATES', 10) or 10)} zatwierdzonych tablic, zanim wejdziesz do Z4."
                )
            step4_secondary_label = ""
            step4_secondary_command = None
            if not project_suspended and current_step == 4:
                step4_badge_label = "Zakończ etap bez treningu"
                step4_badge_command = self._finish_step4_without_training
        elif current_step == 4:
            step4_state = "in_progress"
            step4_summary = "Budowa datasetu i trening odbywają się w Z4."
            if iteration_target == "plate":
                approved_images = max(
                    int(plate_step4_gate.get("project_approved_images", 0) or 0),
                    int(project_approved_images_current or 0),
                )
                approved_plates = max(
                    int(plate_step4_gate.get("project_approved_plates", 0) or 0),
                    int(project_approved_plates_current or 0),
                )
                step4_details = (
                    "W torze tablic Z4 przygotuje dataset YOLO Pose i uruchomi trening modelu tablic. "
                    f"Źródłem jest zatwierdzony zbiór projektu: {approved_images} obraz(y), {approved_plates} tablic(e)."
                )
            else:
                step4_details = "W torze znaków Z4 zbuduje dataset znaków i uruchomi trening modelu YOLO Detect."
            step4_secondary_label = ""
            step4_secondary_command = None
            step4_badge_label = "Zakończ etap bez treningu"
            step4_badge_command = self._finish_step4_without_training
        else:
            step4_state = "locked"
            if iteration_target == "plate":
                step4_summary = "Z4 odblokuje się po zakończeniu Z2 w torze tablic."
            elif iteration_target == "char":
                step4_summary = "Z4 odblokuje się po zakończeniu Z3 w torze znaków."
            else:
                step4_summary = "Najpierw wybierz tor iteracji i przejdź przez wcześniejsze etapy."
            step4_details = "Wizard pokaże Z4 jako ostatni etap, ale cała praca będzie się odbywać już w zakładce treningu."
            step4_secondary_label = ""
            step4_secondary_command = None

        if char_step4_blocked and not project_suspended and current_step < 5:
            step4_state = "needs_attention"
            step4_summary = "Z4 czeka na poprawny dataset znaków z Z3."
            gate_msg = str(char_step4_gate.get("message") or "").strip()
            repair_msg = str(char_repair_guidance.get("details") or "").strip()
            if gate_msg and repair_msg:
                step4_details = gate_msg + "\n\n" + repair_msg
            else:
                step4_details = gate_msg or repair_msg or (
                    "Wróć do Z3 i przygotuj dataset znaków gotowy do treningu."
                )
            step4_secondary_label = ""
            step4_secondary_command = None
            if not project_suspended and current_step == 4:
                step4_badge_label = "Zakończ etap bez treningu"
                step4_badge_command = self._finish_step4_without_training

        step4_primary_label = ""
        step4_primary_command = None
        if project_suspended or current_step >= 5 or (current_step == 4 and not step4_gate_blocked):
            step4_primary_label = "Otwórz Z4"
            step4_primary_command = self._step_goto_training
        elif plate_step4_blocked:
            plate_step4_reason = str(plate_step4_gate.get("reason") or "").strip().lower()
            if plate_step4_reason == "stale_plate_dataset":
                step4_primary_label = "Przebuduj dataset w Z4"
                step4_primary_command = self._step_goto_training_dataset
            else:
                step4_primary_label = "Wróć do Z2"
                step4_primary_command = self._step_return_to_annotation_review
        elif char_step4_blocked:
            step4_primary_label = str(char_repair_guidance.get("primary_label") or "Wróć do Z3")
            step4_primary_command = char_repair_guidance.get("primary_command") or self._step_goto_characters

        statuses.append(
            WizardStageStatus(
                key="step4",
                title="E4. Dataset i trening",
                state=step4_state,
                summary=step4_summary,
                details=step4_details,
                primary_label=step4_primary_label,
                primary_command=step4_primary_command,
                secondary_label=step4_secondary_label,
                secondary_command=step4_secondary_command,
                badge_action_label=step4_badge_label,
                badge_action_command=step4_badge_command,
                is_current=bool(not project_suspended and current_step >= 4),
            )
        )

        return [status for status in statuses if getattr(status, "key", "") != "project"]

    @staticmethod
    def _normalize_iteration_target(target: str | None) -> str:
        value = str(target or "").strip().lower()
        if value == "plate":
            return "plate"
        if value == "char":
            return "char"
        return ""

    def _get_iteration_target(self) -> str:
        return self._normalize_iteration_target(CAMPAIGN.get_iteration_target())

    def _get_last_iteration_target(self) -> str:
        try:
            return self._normalize_iteration_target(CAMPAIGN.get_last_iteration_target())
        except Exception:
            return ""

    def _should_default_first_iteration_step2_to_plate(
        self,
        *,
        current_step: int,
        step1_status: str,
        step2_status: str,
        step3_status: str,
        iteration_target: str,
    ) -> bool:
        if self._normalize_iteration_target(iteration_target):
            return False

        try:
            current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            current_iteration = 1
        if current_iteration != 1:
            return False

        if int(current_step or 1) != 2:
            return False
        if str(step1_status or "").strip().lower() != "approved":
            return False
        if str(step2_status or "").strip().lower() != "pending":
            return False
        if str(step3_status or "").strip().lower() != "pending":
            return False

        return True

    def _get_default_step2_iteration_target(
        self,
        *,
        current_step: int,
        step1_status: str,
        step2_status: str,
        step3_status: str,
        iteration_target: str,
    ) -> str:
        normalized_target = self._normalize_iteration_target(iteration_target)
        if normalized_target in {"plate", "char"}:
            return normalized_target

        # Od teraz tor jest jawnie wybierany w E1. Nie zgadujemy go na E2,
        # bo to ukrywa stare stany projektu i miesza logikę tablic/znaków.
        return ""

    def _get_annotation_bootstrap_for_target(self, target: str) -> dict:
        target = self._normalize_iteration_target(target)
        if target not in {"plate", "char"}:
            return {}

        registry_state = self._get_annotation_step2_source_state_from_registry(target)
        if isinstance(registry_state, dict) and registry_state:
            bootstrap = registry_state.get("bootstrap")
            if isinstance(bootstrap, dict) and bootstrap:
                return dict(bootstrap)

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return {}

        try:
            bootstrap = annotation_tab._get_campaign_auto_annotation_bootstrap(target)
        except Exception as e:
            logger.debug(f"Nie udało się pobrac bootstrapu Z2 dla toru {target}: {e}")
            return {}

        return dict(bootstrap) if isinstance(bootstrap, dict) else {}

    def _get_annotation_step2_source_state_from_registry(self, target: str) -> dict:
        target = self._normalize_iteration_target(target)
        if target not in {"plate", "char"}:
            return {}

        try:
            iteration_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            iteration_num = 1
        images_dir = CAMPAIGN.get_iteration_image_source_dir(iteration_num) or CAMPAIGN.get_master_pool_dir() or CAMPAIGN.get_iteration_raw_dir(iteration_num)
        if images_dir is None:
            return {}

        bundle = dict(
            CAMPAIGN.get_iteration_artifact_bundle(
                images_dir=images_dir,
                iteration_num=iteration_num,
            ) or {}
        )
        if not bundle:
            return {}

        plate_source = dict(bundle.get("plate_source") or {})
        step2_active_run = dict(bundle.get("step2_active_run") or {})
        plate_model = dict(bundle.get("plate_model") or {})
        char_effective = dict(bundle.get("char_effective_source") or {})
        route_hints = dict(bundle.get("route_hints") or {})
        image_source = dict(bundle.get("image_source") or {})
        expected_image_set_token = str(image_source.get("image_set_token") or "").strip()
        plate_expected_token = str(plate_source.get("expected_image_set_token") or "").strip()
        plate_xml_token = str(plate_source.get("xml_image_set_token") or "").strip()
        plate_image_set_match = plate_source.get("image_set_match")
        if plate_image_set_match is None:
            plate_source_usable = bool(
                not expected_image_set_token
                or not plate_xml_token
                or expected_image_set_token == plate_xml_token
                or (plate_expected_token and plate_expected_token == plate_xml_token)
            )
        else:
            plate_source_usable = bool(plate_image_set_match)

        try:
            effective_input_dir = Path(
                str(
                    step2_active_run.get("images_dir")
                    or plate_source.get("images_dir")
                    or image_source.get("master_pool_dir")
                    or CAMPAIGN.get_iteration_image_source_dir(iteration_num)
                    or CAMPAIGN.get_iteration_raw_dir(iteration_num)
                    or ""
                ).strip()
            )
        except Exception:
            effective_input_dir = None
        if effective_input_dir is not None and (not effective_input_dir.exists() or not effective_input_dir.is_dir()):
            effective_input_dir = None

        plate_model_path = str(plate_model.get("path") or "").strip()
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())

        result = {
            "iteration_target": target,
            "ready": False,
            "has_source": False,
            "needs_more_tables": False,
            "images_with_plates": 0,
            "total_plates": 0,
            "restore_run_dir": None,
            "run_name": "",
            "bootstrap": {},
            "input_source": "",
            "manual_template": False,
            "plate_model_ready": plate_model_ready,
        }

        if target == "plate":
            active_run_dir_raw = str(step2_active_run.get("run_dir") or "").strip()
            active_xml_path_raw = str(step2_active_run.get("xml_path") or "").strip()
            try:
                active_run_dir = Path(active_run_dir_raw) if active_run_dir_raw else None
            except Exception:
                active_run_dir = None
            if active_run_dir is not None and (not active_run_dir.exists() or not active_run_dir.is_dir()):
                active_run_dir = None
            active_xml_ok = False
            if active_xml_path_raw:
                try:
                    active_xml_ok = Path(active_xml_path_raw).exists()
                except Exception:
                    active_xml_ok = False
            run_dir_raw = str(plate_source.get("run_dir") or "").strip()
            xml_path_raw = str(plate_source.get("xml_path") or "").strip()
            try:
                run_dir = Path(run_dir_raw) if run_dir_raw else None
            except Exception:
                run_dir = None
            if run_dir is not None and (not run_dir.exists() or not run_dir.is_dir()):
                run_dir = None
            xml_ok = False
            if xml_path_raw:
                try:
                    xml_ok = Path(xml_path_raw).exists()
                except Exception:
                    xml_ok = False
            restore_run_dir = run_dir if (run_dir is not None and xml_ok and plate_source_usable) else None
            if active_run_dir is not None and active_xml_ok:
                restore_run_dir = active_run_dir
            result["restore_run_dir"] = restore_run_dir
            result["run_name"] = str(getattr(restore_run_dir, "name", "") or "").strip()
            result["has_source"] = bool(restore_run_dir is not None)
            result["ready"] = bool(restore_run_dir is not None)
            result["manual_template"] = bool(not restore_run_dir and not plate_model_ready)
            result["input_source"] = (
                str(
                    (
                        step2_active_run.get("input_source")
                        if restore_run_dir is not None and active_run_dir is not None
                        else plate_source.get("input_source")
                    ) or ""
                ).strip()
                or (
                    "registry_step2_active_run"
                    if restore_run_dir is not None and active_run_dir is not None
                    else ("registry_plate_source" if restore_run_dir is not None else "registry")
                )
            )
            result["bootstrap"] = {
                "restore_run_dir": restore_run_dir,
                "input_dir": effective_input_dir,
                "input_source": result["input_source"],
                "manual_template": bool(result["manual_template"]),
                "plate_model_path": plate_model_path if plate_model_ready else "",
            }
            if restore_run_dir is not None or plate_model_ready or effective_input_dir is not None:
                return result
            return {}

        try:
            approved_stats = dict(CAMPAIGN.get_plate_approved_set_stats() or {})
            project_approved_images = int(approved_stats.get("images", 0) or 0)
            project_approved_plates = int(approved_stats.get("plates", 0) or 0)
        except Exception:
            project_approved_images = 0
            project_approved_plates = 0

        raw_char_images = max(
            int(char_effective.get("images_with_plates", 0) or 0),
            int(route_hints.get("images_with_plates", 0) or 0),
            int(project_approved_images or 0),
        )
        raw_char_plates = max(
            int(char_effective.get("total_plates", 0) or 0),
            int(route_hints.get("total_plates", 0) or 0),
            int(project_approved_plates or 0),
        )
        approved_char_images = int(
            max(
                int(char_effective.get("images_with_plates", 0) or 0),
                int(plate_source.get("approved_images", 0) or 0),
                int(project_approved_images or 0),
            )
        )
        approved_char_plates = int(
            max(
                int(char_effective.get("total_plates", 0) or 0),
                int(plate_source.get("approved_plates", 0) or 0),
                int(project_approved_plates or 0),
            )
        )
        run_dir_raw = str(char_effective.get("run_dir") or plate_source.get("run_dir") or "").strip()
        run_name = str(char_effective.get("display_name") or "").strip()
        try:
            restore_run_dir = Path(run_dir_raw) if run_dir_raw else None
        except Exception:
            restore_run_dir = None
        if restore_run_dir is not None and (not restore_run_dir.exists() or not restore_run_dir.is_dir()):
            restore_run_dir = None
        if not run_name and restore_run_dir is not None:
            run_name = str(restore_run_dir.name or "").strip()
        if not run_name and project_approved_plates > 0:
            run_name = "Zatwierdzony zbiór projektu tablic"

        has_source = bool(
            (restore_run_dir is not None and plate_source_usable)
            or raw_char_plates > 0
            or project_approved_plates > 0
            or str(route_hints.get("char_entry_mode") or "").strip().lower() in {"ready", "needs_more_tables"}
        )
        min_char_plates = int(getattr(self, "STEP3_CHAR_MIN_PLATES", 10) or 10)
        ready = bool(approved_char_plates >= min_char_plates)
        needs_more_tables = bool(has_source and not ready)
        char_source_scope = (
            "campaign_approved_set"
            if project_approved_plates > 0 and project_approved_images >= approved_char_images
            else "campaign_char_effective_source"
        )
        result.update(
            has_source=has_source,
            ready=ready,
            needs_more_tables=needs_more_tables,
            images_with_plates=approved_char_images,
            total_plates=approved_char_plates,
            project_images_with_plates=project_approved_images,
            project_total_plates=project_approved_plates,
            source_scope=char_source_scope,
            restore_run_dir=restore_run_dir,
            run_name=run_name,
            input_source=(
                "campaign_char_effective_source"
                if char_effective
                else ("registry_plate_source" if has_source else "")
            ),
            manual_template=False,
            bootstrap={
                "restore_run_dir": restore_run_dir,
                "input_dir": effective_input_dir,
                "xml_path": (
                    Path(str(char_effective.get("xml_path") or "").strip())
                    if str(char_effective.get("xml_path") or "").strip()
                    else None
                ),
                "input_source": (
                    "campaign_char_effective_source"
                    if char_effective
                    else ("registry_plate_source" if has_source else "")
                ),
                "manual_template": False,
                "plate_model_path": plate_model_path if plate_model_ready else "",
                "display_name": run_name,
                "run_name": run_name,
                "contributor_run_dir": str(char_effective.get("contributor_run_dir") or "").strip(),
                "source_scope": char_source_scope,
            },
        )
        return result if has_source or plate_model_ready else {}

    def _get_annotation_step2_source_state(self, target: str) -> dict:
        target = self._normalize_iteration_target(target)
        if target not in {"plate", "char"}:
            return {}

        cache_key = (
            str(CAMPAIGN.get_active_project_name() or "").strip(),
            int(CAMPAIGN.get_current_iteration_num() or 1),
            int(CAMPAIGN.get_current_step() or 1),
            str(CAMPAIGN.get_step2_status() or "").strip().lower(),
            str(CAMPAIGN.get_step3_status() or "").strip().lower(),
            target,
        )
        state_cache = self._get_dashboard_cache_bucket("step2_source_states")
        cached = state_cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)

        persistent_signature = self._build_step2_source_state_signature(target)
        persistent_scope = f"step2_source_state:{target}"
        persistent_cached = self._get_project_view_cache_entry(persistent_scope, persistent_signature)
        if isinstance(persistent_cached, dict) and persistent_cached:
            state_cache[cache_key] = dict(persistent_cached)
            return dict(persistent_cached)

        registry_state = self._get_annotation_step2_source_state_from_registry(target)
        if isinstance(registry_state, dict) and registry_state:
            state_cache[cache_key] = dict(registry_state)
            self._set_project_view_cache_entry(
                persistent_scope,
                persistent_signature,
                registry_state,
            )
            return dict(registry_state)

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return {}

        getter = getattr(annotation_tab, "get_campaign_step2_source_state", None)
        if not callable(getter):
            return {}

        source_started = perf_counter()
        try:
            source_state = getter(iteration_target=target)
        except Exception as e:
            logger.debug(f"Nie udało się pobrac stanu źródła E2 z Z2 dla toru {target}: {e}")
            return {}

        normalized_state = dict(source_state) if isinstance(source_state, dict) else {}
        state_cache[cache_key] = dict(normalized_state)
        if normalized_state:
            self._set_project_view_cache_entry(
                persistent_scope,
                persistent_signature,
                normalized_state,
            )
        self._log_perf(
            f"step2_source_state[{target}]",
            source_started,
            threshold_ms=20.0,
            extra=f"ready={bool(normalized_state.get('ready'))}, has_source={bool(normalized_state.get('has_source'))}",
        )
        return normalized_state

    def _get_plate_approved_set_stats(self) -> dict:
        try:
            manifest_path = CAMPAIGN.get_plate_approved_set_path()
        except Exception:
            manifest_path = None

        cache = getattr(self, "_dashboard_perf_cache", {})
        stats_cache = cache.get("approved_stats", {}) if isinstance(cache, dict) else {}
        cache_key = ("plate_approved_stats", self._build_cache_token_for_path(manifest_path))
        cached = stats_cache.get(cache_key) if isinstance(stats_cache, dict) else None
        if isinstance(cached, dict):
            return dict(cached)

        try:
            stats = CAMPAIGN.get_plate_approved_set_stats()
        except Exception as e:
            logger.debug(f"Nie udało się pobrac statystyk ApprovedSet tablic: {e}")
            return {}
        result = dict(stats) if isinstance(stats, dict) else {}
        if isinstance(stats_cache, dict):
            if len(stats_cache) > 64:
                stats_cache.clear()
                stats_cache[cache_key] = dict(result)
        return result

    def _get_step2_disk_approval_fallback(
        self,
        *,
        iteration_target: str = "",
        plate_ready_source: dict | None = None,
        char_ready_source: dict | None = None,
    ) -> dict:
        target = self._normalize_iteration_target(iteration_target)
        if target not in {"plate", "char"}:
            return {"ready": False}

        annotation_tab = self.app.tabs.get("annotation") if getattr(self.app, "tabs", None) else None
        source_state = dict(plate_ready_source or {}) if target == "plate" else dict(char_ready_source or {})
        bootstrap = dict(source_state.get("bootstrap") or {})
        candidates: list[object] = []

        for raw_candidate in (
            CAMPAIGN.get_step2_staging_run(),
            source_state.get("restore_run_dir"),
            bootstrap.get("restore_run_dir"),
        ):
            if raw_candidate:
                candidates.append(raw_candidate)

        try:
            bundle = dict(
                CAMPAIGN.get_iteration_artifact_bundle(
                    iteration_num=int(CAMPAIGN.get_current_iteration_num() or 1)
                ) or {}
            )
        except Exception:
            bundle = {}
        for entry_key in ("step2_active_run", "plate_source", "char_effective_source"):
            entry = dict(bundle.get(entry_key) or {})
            raw_candidate = entry.get("run_dir")
            if raw_candidate:
                candidates.append(raw_candidate)

        def resolve_run(raw_value) -> Path | None:
            if not raw_value:
                return None
            if annotation_tab is not None and hasattr(annotation_tab, "_resolve_safe_annotation_run_dir"):
                try:
                    resolved = annotation_tab._resolve_safe_annotation_run_dir(raw_value, require_xml=True)
                    if resolved is not None:
                        return Path(resolved)
                except Exception:
                    pass
            try:
                candidate = Path(raw_value)
            except Exception:
                return None
            try:
                if candidate.exists() and candidate.is_dir() and (candidate / "annotations.xml").exists():
                    return candidate
            except Exception:
                return None
            return None

        def count_run_approved(run_dir: Path | None) -> tuple[int, int]:
            if run_dir is None:
                return 0, 0
            if annotation_tab is not None and hasattr(annotation_tab, "_get_run_plate_approved_counts"):
                try:
                    return annotation_tab._get_run_plate_approved_counts(run_dir)
                except Exception:
                    pass
            try:
                manifest = CAMPAIGN._load_annotation_run_manifest_file(run_dir)
                approved_names = {
                    CAMPAIGN._normalize_image_set_name(name)
                    for name in list(manifest.get("approved_filenames") or [])
                    if CAMPAIGN._normalize_image_set_name(name)
                }
                counts = CAMPAIGN._load_run_plate_counts_by_image(run_dir, image_names=approved_names)
                image_count = sum(1 for value in counts.values() if int(value or 0) > 0)
                plate_count = sum(max(0, int(value or 0)) for value in counts.values())
                return int(image_count), int(plate_count)
            except Exception:
                return 0, 0

        resolved_run = None
        run_images = 0
        run_plates = 0
        min_char_plates = int(getattr(self, "STEP3_CHAR_MIN_PLATES", 10) or 10)
        min_plate_plates = int(getattr(self, "STEP2_PLATE_MIN_PLATES", 10) or 10)
        seen: set[str] = set()
        for raw_candidate in candidates:
            candidate = resolve_run(raw_candidate)
            if candidate is None:
                continue
            try:
                key = str(candidate.resolve()).lower()
            except Exception:
                key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            images, plates = count_run_approved(candidate)
            if images > run_images or plates > run_plates or resolved_run is None:
                resolved_run = candidate
                run_images = int(images or 0)
                run_plates = int(plates or 0)
            if target == "char":
                if run_plates >= min_char_plates:
                    break
            elif run_plates >= min_plate_plates:
                break

        try:
            approved_stats = dict(CAMPAIGN.get_plate_approved_set_stats() or {})
        except Exception:
            approved_stats = {}
        project_images = max(0, int(approved_stats.get("images", 0) or 0))
        project_plates = max(0, int(approved_stats.get("plates", 0) or 0))
        total_images = project_images + int(run_images or 0)
        total_plates = project_plates + int(run_plates or 0)
        if target == "char":
            ready = bool(total_plates >= min_char_plates)
        else:
            ready = bool(total_plates >= min_plate_plates)

        action = ""
        if ready:
            action = "approve_stage"
            if target == "char" and int(run_images or 0) <= 0 and source_state:
                action = "continue_characters"

        return {
            "ready": bool(ready),
            "iteration_target": target,
            "action": action,
            "run_dir": resolved_run,
            "run_approved_images": int(run_images or 0),
            "run_approved_plates": int(run_plates or 0),
            "project_approved_images": int(project_images or 0),
            "project_approved_plates": int(project_plates or 0),
            "total_images": int(total_images or 0),
            "total_plates": int(total_plates or 0),
        }

    def _get_step2_current_iteration_contribution_state(
        self,
        *,
        approval_context: dict | None = None,
        source_state: dict | None = None,
        run_approved_images: int | None = None,
        run_approved_plates: int | None = None,
    ) -> dict:
        context = dict(approval_context or {})
        source = dict(source_state or {})

        try:
            iteration_stats = dict(CAMPAIGN.get_plate_approved_set_iteration_stats() or {})
        except Exception:
            iteration_stats = {}
        try:
            approved_stats = dict(CAMPAIGN.get_plate_approved_set_stats() or {})
        except Exception:
            approved_stats = {}

        def _int_value(payload: dict, key: str) -> int:
            try:
                return max(0, int(payload.get(key, 0) or 0))
            except Exception:
                return 0

        current_images = _int_value(iteration_stats, "images")
        current_plates = _int_value(iteration_stats, "plates")

        for image_key, plate_key in (
            ("current_images_with_plates", "current_total_plates"),
            ("pending_images_with_plates", "pending_total_plates"),
        ):
            current_images = max(current_images, _int_value(source, image_key))
            current_plates = max(current_plates, _int_value(source, plate_key))

        if run_approved_images is not None or run_approved_plates is not None:
            try:
                current_images = max(current_images, int(run_approved_images or 0))
            except Exception:
                pass
            try:
                current_plates = max(current_plates, int(run_approved_plates or 0))
            except Exception:
                pass
        else:
            run_dir = context.get("run_dir")
            source_kind = str(context.get("source_kind") or "").strip().lower()
            if run_dir is not None and source_kind == "staging":
                try:
                    annotation_tab = self.app.tabs.get("annotation") if getattr(self.app, "tabs", None) else None
                    counter = getattr(annotation_tab, "_get_run_plate_approved_counts", None)
                    if callable(counter):
                        run_images, run_plates = counter(Path(run_dir))
                        current_images = max(current_images, int(run_images or 0))
                        current_plates = max(current_plates, int(run_plates or 0))
                except Exception:
                    pass

        project_images = max(
            _int_value(approved_stats, "images"),
            _int_value(source, "project_images_with_plates"),
            _int_value(source, "images_with_plates"),
        )
        project_plates = max(
            _int_value(approved_stats, "plates"),
            _int_value(source, "project_total_plates"),
            _int_value(source, "total_plates"),
        )

        try:
            iteration = int(iteration_stats.get("iteration", CAMPAIGN.get_current_iteration_num() or 1) or 1)
        except Exception:
            iteration = 1

        return {
            "iteration": int(iteration),
            "current_images": int(current_images),
            "current_plates": int(current_plates),
            "project_images": int(project_images),
            "project_plates": int(project_plates),
            "iteration_target": str(
                context.get("iteration_target")
                or source.get("iteration_target")
                or CAMPAIGN.get_iteration_target()
                or ""
            ).strip().lower(),
        }

    def _confirm_step2_without_current_iteration_contribution(
        self,
        *,
        approval_context: dict | None = None,
        source_state: dict | None = None,
        run_approved_images: int | None = None,
        run_approved_plates: int | None = None,
    ) -> bool:
        contribution = self._get_step2_current_iteration_contribution_state(
            approval_context=approval_context,
            source_state=source_state,
            run_approved_images=run_approved_images,
            run_approved_plates=run_approved_plates,
        )
        current_images = int(contribution.get("current_images", 0) or 0)
        current_plates = int(contribution.get("current_plates", 0) or 0)
        project_images = int(contribution.get("project_images", 0) or 0)
        project_plates = int(contribution.get("project_plates", 0) or 0)
        iteration = int(contribution.get("iteration", CAMPAIGN.get_current_iteration_num() or 1) or 1)
        target = str(contribution.get("iteration_target") or "").strip().lower()

        if current_images > 0 or current_plates > 0 or project_plates <= 0:
            return True

        next_step_text = (
            "E4 zostanie uruchomione na tej samej puli tablic co wcześniej."
            if target == "plate"
            else "E3/Z3 zostanie uruchomione na obecnej puli tablic projektu."
        )
        repair_hint = (
            "\n\nW torze znaków to nie zamyka drogi do dopisania tablic: w E3 możesz wrócić do Z2 "
            "w trybie naprawczym i powiększyć pulę przed finalnym zatwierdzeniem E3."
            if target == "char"
            else ""
        )
        message = (
            f"Iteracja {iteration:03d} spełnia bramkę E2 dzięki zatwierdzonej puli projektu, "
            "ale w tej iteracji nie dodano żadnych nowych zatwierdzonych obrazów z tablicami.\n\n"
            f"Aktualna pula projektu: {project_images} zdjęć / {project_plates} tablic.\n"
            "Nowy wkład tej iteracji: 0 zdjęć / 0 tablic.\n\n"
            f"Jeśli zatwierdzisz E2 mimo to, {next_step_text} To jest poprawne tylko wtedy, gdy świadomie "
            "chcesz kontynuować bez powiększania materiału wejściowego."
            f"{repair_hint}"
        )
        title = "Brak nowych tablic w tej iteracji" if target == "char" else "E2 bez nowych danych"
        confirm_label = "Kontynuuj bez nowych tablic" if target == "char" else "Zatwierdź mimo to"
        cancel_label = "Oznacz więcej tablic" if target == "char" else "Wróć do E2"
        try:
            return bool(
                self.app.themed_confirm(
                    title,
                    message,
                    parent=self.frame,
                    confirm_label=confirm_label,
                    cancel_label=cancel_label,
                    tone="warning",
                )
            )
        except Exception:
            return True

    def _resolve_step2_wizard_action_command(self, action_id: str, *, context: dict | None = None):
        normalized = str(action_id or "").strip().lower()
        if not normalized:
            return None

        if normalized == "open_z2":
            return self._step_goto_auto_annotation
        if normalized == "open_z2_step2_review":
            return self._step_open_z2_from_step2_review
        if normalized == "return_to_z2":
            return self._step_open_z2_repair_from_later_stage
        if normalized == "continue_z3":
            return lambda ctx=dict(context or {}): self._step_continue_characters_from_ready_source(ctx)
        return None

    def _approve_step2_from_wizard(self):
        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return

        try:
            ensure_context = getattr(annotation_tab, "ensure_campaign_context_ready_for_active_project", None)
            if callable(ensure_context):
                ensure_context(force=False)
        except Exception:
            pass

        try:
            wizard_status_getter = getattr(annotation_tab, "get_campaign_step2_wizard_status", None)
            wizard_status = dict(wizard_status_getter() or {}) if callable(wizard_status_getter) else {}
        except Exception:
            wizard_status = {}

        approval_action = str(wizard_status.get("approval_action", "") or "").strip().lower()
        approval_iteration_target = str(wizard_status.get("approval_iteration_target", "") or "").strip().lower()

        try:
            approval_context_getter = getattr(annotation_tab, "_get_campaign_step2_approval_context", None)
            approval_context = dict(approval_context_getter() or {}) if callable(approval_context_getter) else {}
        except Exception:
            approval_context = {}
        approval_run_dir = approval_context.get("run_dir")
        if approval_iteration_target not in {"plate", "char"}:
            approval_iteration_target = self._get_iteration_target()

        disk_fallback = {}
        try:
            disk_fallback = self._get_step2_disk_approval_fallback(
                iteration_target=approval_iteration_target,
                plate_ready_source=self._get_plate_route_ready_source() if approval_iteration_target == "plate" else {},
                char_ready_source=self._get_char_route_ready_source() if approval_iteration_target == "char" else {},
            )
        except Exception:
            disk_fallback = {}
        if bool(disk_fallback.get("ready")):
            if approval_iteration_target not in {"plate", "char"}:
                approval_iteration_target = str(disk_fallback.get("iteration_target") or "").strip().lower()
            if not approval_action:
                approval_action = str(disk_fallback.get("action") or "").strip().lower()
            if approval_run_dir is None and disk_fallback.get("run_dir") is not None:
                approval_run_dir = disk_fallback.get("run_dir")
                approval_context["run_dir"] = approval_run_dir
                approval_context["source_kind"] = "staging"

        if approval_iteration_target in {"plate", "char"}:
            try:
                CAMPAIGN.set_iteration_target(approval_iteration_target)
            except Exception:
                pass

        if approval_iteration_target == "char":
            ready_source = {}
            try:
                ready_source = self._get_char_route_ready_source() or {}
            except Exception:
                ready_source = {}
            should_continue_characters = bool(
                approval_action == "continue_characters"
                or (approval_run_dir is None and ready_source)
            )
            if should_continue_characters:
                if not self._confirm_step2_without_current_iteration_contribution(
                    approval_context=approval_context,
                    source_state=ready_source,
                ):
                    try:
                        self.app.update_status(
                            "Zatwierdzenie E2 przerwane. Dodaj nowe zatwierdzone tablice albo świadomie zatwierdź E2 bez nowego wkładu.",
                            "warning",
                        )
                    except Exception:
                        pass
                    return
                try:
                    self._finish_step2_char_and_focus_step3(ready_source)
                except Exception as e:
                    logger.error(f"Nie udało się zatwierdzić E2 z badge wizarda (char source): {e}")
                return

        if approval_iteration_target == "plate" and approval_run_dir is None:
            if not self._confirm_step2_without_current_iteration_contribution(
                approval_context=approval_context,
            ):
                try:
                    self.app.update_status(
                        "Zatwierdzenie E2 przerwane. Dodaj nowe zatwierdzone tablice albo świadomie zatwierdź E2 bez nowego wkładu.",
                        "warning",
                    )
                except Exception:
                    pass
                return
            try:
                CAMPAIGN.approve_step2()
                CAMPAIGN.set_current_step(4)
                self.request_wizard_stage_focus(step_num=4)
                self._refresh_dashboard()
                self.app.open_controlled_tab("campaign")
                self.app.update_campaign_tab_access()
                self.app.update_status(
                    "E2 zostało zatwierdzone na podstawie zatwierdzonego zbioru projektu. Etap E4 jest już odblokowany.",
                    "info",
                )
            except Exception as e:
                logger.error(f"Nie udało się zatwierdzić E2 z badge wizarda (project approved set): {e}")
            return

        if approval_run_dir is not None:
            try:
                current_run = getattr(annotation_tab, "current_annotation_run_dir", None)
                same_run_loaded = bool(
                    current_run is not None
                    and hasattr(annotation_tab, "_paths_equivalent")
                    and annotation_tab._paths_equivalent(current_run, approval_run_dir)
                )
            except Exception:
                same_run_loaded = False
            if not same_run_loaded and hasattr(annotation_tab, "_restore_preview_from_annotation_run"):
                try:
                    annotation_tab._restore_preview_from_annotation_run(Path(approval_run_dir))
                    annotation_tab._refresh_step2_action_states()
                except Exception as e:
                    logger.debug(f"Nie udało się odtworzyć runu E2 przed zatwierdzeniem z badge: {e}")

        try:
            annotation_tab._approve_annotation_stage()
        except Exception as e:
            logger.error(f"Nie udało się zatwierdzić E2 z badge wizarda: {e}")

    def _approve_step1_from_wizard(self):
        if not CAMPAIGN.get_active_project_name():
            return
        try:
            self._apply_current_ingest_plan()
        except Exception as e:
            logger.error(f"Nie udało się zatwierdzić E1 z badge wizarda: {e}")

    def _get_annotation_step2_view_model(self):
        cache_key = (
            str(CAMPAIGN.get_active_project_name() or "").strip(),
            int(CAMPAIGN.get_current_iteration_num() or 1),
            int(CAMPAIGN.get_current_step() or 1),
            str(CAMPAIGN.get_iteration_target() or "").strip().lower(),
            str(CAMPAIGN.get_step1_status() or "").strip().lower(),
            str(CAMPAIGN.get_step2_status() or "").strip().lower(),
            str(CAMPAIGN.get_step3_status() or "").strip().lower(),
        )
        vm_cache = self._get_dashboard_cache_bucket("step2_view_models")
        cached = vm_cache.get(cache_key)
        if isinstance(cached, Step2ViewModel):
            return cached

        current_step = int(CAMPAIGN.get_current_step() or 1)
        iteration_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        step1_status = str(CAMPAIGN.get_step1_status() or "").strip().lower()
        step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
        step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower()
        if step1_status != "approved":
            locked_vm = Step2ViewModel(
                stage_key="step2",
                iteration_target=iteration_target,
                current_step=current_step,
                step2_status=step2_status,
                state="locked",
                title="E2. Tablice",
                summary="E2 odblokuje się dopiero po zatwierdzeniu E1.",
                details="W E1 musi być wskazany katalog zdjęć oraz wybrany tor iteracji. Bez zatwierdzenia E1 nie można uruchomić STEP2-P1.",
                primary_cta=None,
                secondary_cta=None,
            )
            vm_cache[cache_key] = locked_vm
            return locked_vm
        if (
            current_step == 2
            and not iteration_target
            and step1_status == "approved"
            and step2_status == "pending"
            and step3_status == "pending"
        ):
            lightweight_vm = Step2ViewModel(
                stage_key="step2",
                iteration_target="",
                current_step=current_step,
                step2_status=step2_status,
                state="needs_attention",
                title="E2. Tablice",
                summary="Brak wybranego toru iteracji.",
                details="Wybór toru należy do E1. Wróć do E1 i wybierz tor, zanim uruchomisz E2.",
                primary_cta=None,
                secondary_cta=None,
            )
            vm_cache[cache_key] = lightweight_vm
            return lightweight_vm

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return None

        getter = getattr(annotation_tab, "get_campaign_step2_view_model", None)
        if not callable(getter):
            return None

        vm_started = perf_counter()
        try:
            view_model = getter()
        except Exception as e:
            logger.debug(f"Nie udało się pobrac modelu widoku E2 z Z2: {e}")
            return None

        if isinstance(view_model, Step2ViewModel):
            vm_cache[cache_key] = view_model

        self._log_perf(
            "step2_view_model",
            vm_started,
            threshold_ms=20.0,
            extra=f"target={str(getattr(view_model, 'iteration_target', '') or '').strip() or '-'}",
        )
        return view_model

    def _resolve_step3_wizard_action_command(self, action_id: str, *, context: dict | None = None):
        normalized = str(action_id or "").strip().lower()
        if not normalized:
            return None

        if normalized == "approve_step3":
            return self._approve_step3_from_wizard
        if normalized == "open_z3":
            return self._step_goto_characters
        if normalized == "open_z2_step3_repair":
            return self._step_open_z2_repair_from_later_stage
        if normalized == "continue_z3":
            return lambda ctx=dict(context or {}): self._step_continue_characters_from_ready_source(ctx)
        if normalized == "open_z3_detect":
            return lambda ctx=dict(context or {}): self._step_goto_characters_detect(ctx)
        return None

    def _get_step3_current_iteration_contribution_state(self, source_state: dict | None = None) -> dict:
        state = dict(source_state or {})
        if not state:
            try:
                state = dict(self._get_char_route_source_state() or {})
            except Exception:
                state = {}

        def _int_value(key: str) -> int:
            try:
                return max(0, int(state.get(key, 0) or 0))
            except Exception:
                return 0

        current_images = max(
            _int_value("current_images_with_plates"),
            _int_value("pending_images_with_plates"),
        )
        current_plates = max(
            _int_value("current_total_plates"),
            _int_value("pending_total_plates"),
        )

        try:
            iteration_stats = dict(CAMPAIGN.get_plate_approved_set_iteration_stats() or {})
        except Exception:
            iteration_stats = {}

        iteration_images = int(iteration_stats.get("images", 0) or 0)
        iteration_plates = int(iteration_stats.get("plates", 0) or 0)
        current_images = max(current_images, iteration_images)
        current_plates = max(current_plates, iteration_plates)

        # Backward compatible fallback for projects created before ApprovedSet stored
        # first_approved_iteration. If the current step2 run is the source of entries,
        # treat it as current work rather than warning too aggressively.
        if current_plates <= 0:
            try:
                current_run = str(CAMPAIGN.get_step2_staging_run() or "").strip()
            except Exception:
                current_run = ""
            if current_run:
                matched_images = 0
                matched_plates = 0
                try:
                    for entry in CAMPAIGN.list_plate_approved_entries():
                        if not isinstance(entry, dict):
                            continue
                        approved_from_run = str(entry.get("approved_from_run", "") or "").strip()
                        if not self._campaign_paths_equivalent(approved_from_run, current_run):
                            continue
                        valid_plate_count = 0
                        for plate_entry in list(entry.get("plates") or []):
                            if not isinstance(plate_entry, dict):
                                continue
                            polygon = list(plate_entry.get("polygon") or [])
                            if len(polygon) >= 4:
                                valid_plate_count += 1
                        if valid_plate_count <= 0:
                            valid_plate_count = int(entry.get("plate_count", 0) or 0)
                        if valid_plate_count <= 0:
                            continue
                        matched_images += 1
                        matched_plates += int(valid_plate_count)
                except Exception:
                    matched_images = 0
                    matched_plates = 0
                current_images = max(current_images, matched_images)
                current_plates = max(current_plates, matched_plates)

        try:
            approved_stats = dict(CAMPAIGN.get_plate_approved_set_stats() or {})
        except Exception:
            approved_stats = {}

        project_images = max(
            _int_value("project_images_with_plates"),
            int(approved_stats.get("images", 0) or 0),
        )
        project_plates = max(
            _int_value("project_total_plates"),
            int(approved_stats.get("plates", 0) or 0),
        )
        total_images = max(_int_value("images_with_plates"), project_images)
        total_plates = max(_int_value("total_plates"), project_plates)

        return {
            "current_images": int(current_images),
            "current_plates": int(current_plates),
            "project_images": int(project_images),
            "project_plates": int(project_plates),
            "total_images": int(total_images),
            "total_plates": int(total_plates),
            "iteration": int(iteration_stats.get("iteration", CAMPAIGN.get_current_iteration_num() or 1) or 1),
        }

    def _confirm_step3_without_current_iteration_contribution(self, contribution_state: dict | None = None) -> bool:
        contribution = dict(contribution_state or self._get_step3_current_iteration_contribution_state())
        current_plates = int(contribution.get("current_plates", 0) or 0)
        project_plates = int(contribution.get("project_plates", 0) or 0)
        total_plates = int(contribution.get("total_plates", 0) or 0)
        iteration = int(contribution.get("iteration", CAMPAIGN.get_current_iteration_num() or 1) or 1)

        if current_plates > 0 or project_plates <= 0 or total_plates <= 0:
            return True

        message = (
            f"Iteracja {iteration:03d} spełnia bramkę E3 dzięki tablicom z poprzednich iteracji, "
            "ale w tej iteracji nie dodano żadnych nowych tablic do puli znaków.\n\n"
            "Jeśli teraz zatwierdzisz E3 i przejdziesz do E4, trening znaków odbędzie się na tej samej puli danych "
            "wejściowych co poprzednio. To zwykle nie przyniesie dodatkowych korzyści jakościowych, chyba że "
            "świadomie zmieniono konfigurację treningu albo chcesz wykonać kontrolny run.\n\n"
            "Możesz kontynuować mimo to albo wrócić do E3/Z2 i dodać nowe tablice do bieżącej iteracji."
        )
        try:
            return bool(
                self.app.themed_confirm(
                    "E3 bez nowych danych",
                    message,
                    parent=self.frame,
                    confirm_label="Zatwierdź mimo to",
                    cancel_label="Wróć do E3",
                    tone="warning",
                )
            )
        except Exception:
            return True

    def _approve_step3_from_wizard(self):
        if not CAMPAIGN.get_active_project_name():
            return
        if self._get_iteration_target() != "char":
            return

        char_tab = self.app.tabs.get("characters") if getattr(self.app, "tabs", None) else None
        if char_tab is None:
            return

        readiness = {}
        try:
            getter = getattr(char_tab, "_get_campaign_step3_training_readiness", None)
            if callable(getter):
                readiness = dict(getter() or {})
        except Exception as e:
            logger.debug(f"Nie udało się sprawdzic gotowosci zatwierdzenia E3: {e}")
            readiness = {}

        has_outputs = False
        try:
            checker = getattr(char_tab, "_has_any_step3_export_outputs", None)
            if callable(checker):
                has_outputs = bool(checker())
        except Exception as e:
            logger.debug(f"Nie udało się sprawdzic artefaktow E3: {e}")
            has_outputs = False

        if not bool(readiness.get("ok")):
            try:
                fallback_readiness = dict(self._detect_campaign_char_ready_dataset_state() or {})
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzic gotowego datasetu E3 z katalogu projektu: {e}")
                fallback_readiness = {}
            if bool(fallback_readiness.get("ok")):
                readiness = fallback_readiness

        if str(readiness.get("ready_dataset") or "").strip():
            has_outputs = True

        perfect_count = int(readiness.get("perfect_count", 0) or 0)

        if not (has_outputs and bool(readiness.get("ok")) and perfect_count > 0):
            message = str(readiness.get("message") or "").strip() or (
                "E3 nie jest jeszcze gotowe do zatwierdzenia. W PZ2 przygotuj co najmniej jedną tablicę "
                "ze statusem perfect, a potem wykonaj eksport w PZ3."
            )
            try:
                self.app.update_status(message, "warning")
            except Exception:
                pass
            try:
                self.app.themed_info(
                    "E3 jeszcze niegotowe",
                    message,
                    parent=self.frame,
                    tone="warning",
                )
            except Exception:
                pass
            return

        contribution_state = self._get_step3_current_iteration_contribution_state()
        if not self._confirm_step3_without_current_iteration_contribution(contribution_state):
            try:
                self.app.update_status(
                    "Zatwierdzenie E3 przerwane. Dodaj nowe tablice albo świadomie zatwierdź E3 bez nowego wkładu.",
                    "warning",
                )
            except Exception:
                pass
            return

        CAMPAIGN.approve_step3()
        if int(CAMPAIGN.get_current_step() or 3) < 4:
            CAMPAIGN.set_current_step(4)

        try:
            self.request_wizard_stage_focus(step_num=4)
        except Exception:
            pass

        self._rebuild_wizard_stage_ui()
        self._refresh_dashboard()
        self.app.update_campaign_tab_access()

        try:
            self.app.open_controlled_tab("campaign")
        except Exception:
            pass

        try:
            self.app.update_status(
                "E3 zostało zatwierdzone. Etap 4 jest odblokowany i gotowy do uruchomienia z wizarda.",
                "success",
            )
        except Exception:
            pass

    def _get_campaign_step3_view_model(
        self,
        *,
        current_step: int,
        iteration_target: str,
        project_completed: bool,
        step2_status: str,
        step3_status: str,
        char_ready_source: dict | None = None,
        char_repair_guidance: dict | None = None,
        char_step4_gate: dict | None = None,
    ) -> Step3ViewModel:
        normalized_target = self._normalize_iteration_target(iteration_target)
        normalized_step2_status = str(step2_status or "").strip().lower()
        normalized_step3_status = str(step3_status or "").strip().lower()
        step2_approved = normalized_step2_status == "approved"
        ready_source = dict(char_ready_source or {})
        repair_guidance = dict(char_repair_guidance or {})
        step4_gate = dict(char_step4_gate or {})
        step3_training_gate = {}
        if normalized_target == "char":
            try:
                char_tab = self.app.tabs.get("characters") if getattr(self.app, "tabs", None) else None
                getter = getattr(char_tab, "_get_campaign_step3_training_readiness", None)
                if callable(getter):
                    step3_training_gate = dict(getter() or {})
            except Exception as e:
                logger.debug(f"Nie udało się pobrać bramki perfectów E3: {e}")
                step3_training_gate = {}
        step3_perfect_count = int(
            step3_training_gate.get(
                "perfect_count",
                step4_gate.get("perfect_count", 0),
            )
            or 0
        )
        has_ready_char_dataset = bool(
            normalized_target == "char"
            and step3_perfect_count > 0
            and bool(step4_gate.get("ok"))
            and (
                str(step4_gate.get("ready_dataset") or "").strip()
                or str(step4_gate.get("dataset_hint") or "").strip()
                or int(step4_gate.get("train_images", 0) or 0) > 0
                or int(step4_gate.get("val_images", 0) or 0) > 0
            )
        )
        can_approve_step3 = bool(
            normalized_target == "char"
            and has_ready_char_dataset
            and (
                normalized_step3_status == "ready"
                or (int(current_step or 0) == 3 and has_ready_char_dataset)
            )
        )
        char_step4_blocked = bool(
            normalized_target == "char"
            and (int(current_step or 0) >= 4 or normalized_step3_status == "approved")
            and not bool(step4_gate.get("ok", True))
        )

        vm = Step3ViewModel(
            stage_key="step3",
            iteration_target=normalized_target,
            current_step=int(current_step or 0),
            step3_status=normalized_step3_status or "pending",
            state="locked",
            title="E3. Znaki i gold pack",
            summary="Z3 odblokuje się po przygotowaniu i zatwierdzeniu tablic w Z2.",
            details="Najpierw domknij E2.",
            body_mode="",
            body_visible=False,
            primary_cta=None,
            secondary_cta=None,
        )

        if normalized_target == "plate":
            return Step3ViewModel(
                stage_key="step3",
                iteration_target=normalized_target,
                current_step=int(current_step or 0),
                step3_status=normalized_step3_status or "pending",
                state="skipped",
                title="E3. Znaki i gold pack",
                summary="Tor tablic pomija Z3.",
                details="Po zatwierdzeniu Z2 projekt przechodzi od razu do Z4.",
            )

        if not normalized_target:
            return Step3ViewModel(
                stage_key="step3",
                iteration_target=normalized_target,
                current_step=int(current_step or 0),
                step3_status=normalized_step3_status or "pending",
                state="locked",
                title="E3. Znaki i gold pack",
                summary="Najpierw wybierz tor iteracji w E1.",
                details="Z3 dotyczy wyłącznie toru znaków, a tor jest decyzją wejściową E1.",
            )

        primary_cta = Step2CtaViewModel(
            label="Otwórz Z3",
            command_id=("continue_z3" if ready_source else "open_z3"),
            command_context=(dict(ready_source) if ready_source else {}),
        )
        secondary_cta = None
        state = "locked"
        summary = "Z3 odblokuje się po przygotowaniu i zatwierdzeniu tablic w Z2."
        details = "Najpierw domknij E2."
        body_mode = ""
        body_visible = False

        if can_approve_step3:
            state = "ready"
            summary = "Etap 3 jest gotowy do zamknięcia albo dalszej pracy."
            details = (
                "Możesz zamknąć E3, oznaczyć więcej tablic w Z2 albo pracować dalej na znakach tablic w Z3."
            )
            primary_cta = Step2CtaViewModel(
                label="Oznacz więcej tablic",
                command_id="open_z2_step3_repair",
            )
            secondary_cta = Step2CtaViewModel(
                label="Pracuj na znakach tablic",
                command_id=("continue_z3" if ready_source else "open_z3"),
                command_context=(dict(ready_source) if ready_source else {}),
                tone="secondary",
            )
        elif normalized_step3_status == "needs_rework":
            primary_command_id = "open_z3_detect" if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair" else "open_z2_step3_repair"
            primary_context = dict(ready_source or {}) if primary_command_id == "open_z3_detect" else {}
            primary_cta = Step2CtaViewModel(
                label=str(repair_guidance.get("primary_label") or "Oznacz więcej tablic"),
                command_id=primary_command_id,
                command_context=primary_context,
            )
            secondary_label = str(repair_guidance.get("secondary_label") or "").strip()
            secondary_command_id = "open_z3_detect" if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair" else ""
            secondary_context = dict(ready_source or {})
            if secondary_label:
                if secondary_label.lower().startswith(("przygotuj więcej tablic", "oznacz więcej tablic")):
                    secondary_command_id = "open_z2_step3_repair"
                    secondary_context = {}
                secondary_cta = Step2CtaViewModel(
                    label=secondary_label,
                    command_id=secondary_command_id,
                    command_context=secondary_context,
                )
            state = "needs_attention"
            summary = "Dane znaków wymagają korekty przed treningiem."
            details = str(repair_guidance.get("details") or "Najpierw przygotuj poprawna sciezke naprawy dla toru znaków.")
            body_mode = "step3_rework"
            body_visible = not bool(project_completed)
        elif normalized_step3_status == "approved" or int(current_step or 0) > 3:
            state = "done"
            summary = "Z3 zostało zatwierdzone. Dataset znaków jest gotowy do Z4."
            details = "Możesz wrócić do Z3 albo przejść dalej do budowy datasetu i treningu."
        if (normalized_step3_status == "approved" or int(current_step or 0) > 3) and char_step4_blocked:
            primary_command_id = "open_z3_detect" if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair" else "open_z2_step3_repair"
            primary_context = dict(ready_source or {}) if primary_command_id == "open_z3_detect" else {}
            primary_cta = Step2CtaViewModel(
                label=str(repair_guidance.get("primary_label") or "Oznacz więcej tablic"),
                command_id=primary_command_id,
                command_context=primary_context,
            )
            secondary_label = str(repair_guidance.get("secondary_label") or "").strip()
            secondary_command_id = "open_z3_detect" if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair" else ""
            secondary_context = dict(ready_source or {})
            if secondary_label:
                if secondary_label.lower().startswith(("przygotuj więcej tablic", "oznacz więcej tablic")):
                    secondary_command_id = "open_z2_step3_repair"
                    secondary_context = {}
                secondary_cta = Step2CtaViewModel(
                    label=secondary_label,
                    command_id=secondary_command_id,
                    command_context=secondary_context,
                )
            state = "needs_attention"
            summary = "Z3 jest formalnie zatwierdzone, ale dataset znaków nadal wymaga poprawy."
            gate_msg = str(step4_gate.get("message") or "").strip()
            repair_msg = str(repair_guidance.get("details") or "").strip()
            if gate_msg and repair_msg:
                details = gate_msg + "\n\n" + repair_msg
            else:
                details = gate_msg or repair_msg or "Wróć do Z3 i popraw dataset znaków, zanim przejdziesz do Z4."
            body_mode = ""
            body_visible = False
        elif int(current_step or 0) == 3 and not can_approve_step3:
            if ready_source and step2_approved:
                state = "in_progress"
                summary = "Pracuj na znakach tablic w Z3."
                primary_cta = Step2CtaViewModel(
                    label="Pracuj na znakach tablic",
                    command_id="continue_z3",
                    command_context=dict(ready_source),
                )
                secondary_label = str(repair_guidance.get("secondary_label") or "").strip()
                secondary_command_id = (
                    "open_z3_detect"
                    if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair"
                    else ""
                )
                secondary_context = dict(ready_source or {})
                if secondary_label:
                    if secondary_label.lower().startswith(("przygotuj więcej tablic", "oznacz więcej tablic")):
                        secondary_command_id = "open_z2_step3_repair"
                        secondary_context = {}
                    secondary_cta = Step2CtaViewModel(
                        label=secondary_label,
                        command_id=secondary_command_id,
                        command_context=secondary_context,
                    )
                if secondary_cta is None:
                    secondary_cta = Step2CtaViewModel(
                        label="Oznacz więcej tablic",
                        command_id="open_z2_step3_repair",
                        command_context={},
                        tone="secondary",
                    )
                primary_label = str(getattr(primary_cta, "label", "") or "").strip()
                secondary_label = str(getattr(secondary_cta, "label", "") or "").strip()
                details = (
                    f"„{primary_label}” otwiera Z3 i przebudowuje dane znaków z aktualnych anotacji tablic. "
                    f"„{secondary_label}” wraca do Z2, jeśli chcesz najpierw dopisać albo poprawić tablice."
                )
            elif str(repair_guidance.get("primary_label") or "").strip():
                primary_command_id = (
                    "open_z3_detect"
                    if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair"
                    else "open_z2_step3_repair"
                )
                primary_context = dict(ready_source or {}) if primary_command_id == "open_z3_detect" else {}
                primary_cta = Step2CtaViewModel(
                    label=str(repair_guidance.get("primary_label") or "Oznacz więcej tablic"),
                    command_id=primary_command_id,
                    command_context=primary_context,
                )
                secondary_label = str(repair_guidance.get("secondary_label") or "").strip()
                secondary_command_id = (
                    "open_z3_detect"
                    if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair"
                    else ""
                )
                secondary_context = dict(ready_source or {})
                if secondary_label:
                    if secondary_label.lower().startswith(("przygotuj więcej tablic", "oznacz więcej tablic")):
                        secondary_command_id = "open_z2_step3_repair"
                        secondary_context = {}
                    secondary_cta = Step2CtaViewModel(
                        label=secondary_label,
                        command_id=secondary_command_id,
                        command_context=secondary_context,
                    )
                state = "needs_attention"
                summary = "Źródło tablic dla toru znaków nadal wymaga uwagi."
                details = str(
                    repair_guidance.get("details")
                    or "Najpierw przygotuj więcej tablic w Z2 albo wróć do Z3, jeśli źródło jest już wystarczające."
                )
            else:
                state = "in_progress"
                summary = "Pracujesz teraz w Z3: wycinanie tablic, OCR, korekty i eksport."
                details = "Wizard pokazuje tylko stan etapu. Cała praca dzieje się w zakładce Znaki."
        elif step2_approved:
            state = "ready"
            summary = "Z3 jest gotowe do uruchomienia."
            details = "Źródła tablic są już przygotowane i możesz zacząć pracę nad znakami."
            if secondary_cta is None:
                secondary_cta = Step2CtaViewModel(
                    label="Oznacz więcej tablic",
                    command_id="open_z2_step3_repair",
                    command_context={},
                    tone="secondary",
                )

        if normalized_target == "char" and state in {"in_progress", "ready"} and not can_approve_step3:
            char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
            if char_model_path and Path(char_model_path).exists():
                if state == "in_progress":
                    details = (
                        "Wizard pokazuje tylko stan etapu. Cala praca dzieje się w zakładce Znaki, "
                        "a aktywny model znaków projektu jest tam podstawiany automatycznie."
                    )
                elif state == "ready":
                    details = (
                        "Źródła tablic są już przygotowane i możesz zacząć pracę nad znakami. "
                        "Po wejsciu do Z3 model znaków projektu będzie już ustawiony automatycznie."
                    )

        if normalized_target == "char" and not step2_approved and state in {"in_progress", "ready"}:
            state = "locked"
            summary = "Z3 odblokuje się po przygotowaniu i zatwierdzeniu E2."
            details = "Gotowe źródło tablic nie wystarcza jeszcze do wejścia w E3. Najpierw formalnie zamknij E2."
            body_mode = ""
            body_visible = False
            primary_cta = None
            secondary_cta = None

        if normalized_target == "char" and int(current_step or 0) < 3 and not step2_approved:
            state = "locked"
            summary = "Z3 odblokuje się po przygotowaniu i zatwierdzeniu E2."
            details = "Najpierw przygotuj albo zatwierdź w E2 tablice dla toru znaków."
            body_mode = ""
            body_visible = False
            primary_cta = None
            secondary_cta = None

        if state == "done" and not bool(char_step4_blocked):
            primary_cta = None
            secondary_cta = None
            body_mode = ""
            body_visible = False

        if (
            normalized_target == "char"
            and not bool(char_step4_blocked)
            and (int(current_step or 0) >= 4 or normalized_step3_status == "approved")
        ):
            state = "done"
            primary_cta = None
            secondary_cta = None
            body_mode = ""
            body_visible = False

        return Step3ViewModel(
            stage_key="step3",
            iteration_target=normalized_target,
            current_step=int(current_step or 0),
            step3_status=normalized_step3_status or "pending",
            state=state,
            title="E3. Znaki i gold pack",
            summary=summary,
            details=details,
            body_mode=body_mode,
            body_visible=bool(body_visible),
            primary_cta=primary_cta,
            secondary_cta=secondary_cta,
        )

    def _get_char_route_ready_source(self) -> dict:
        source_state = self._get_char_route_source_state()
        if not bool(source_state.get("ready")):
            return {}

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        builder = getattr(annotation_tab, "_build_campaign_char_effective_source", None)
        if callable(builder):
            try:
                effective_source = dict(builder() or {})
            except Exception as e:
                logger.debug(f"Nie udało się zbudować efektywnego źródła znaków z ApprovedSet: {e}")
                effective_source = {}
            if effective_source:
                try:
                    run_dir = Path(str(effective_source.get("run_dir") or "").strip())
                except Exception:
                    run_dir = None
                try:
                    images_dir = Path(str(effective_source.get("images_dir") or "").strip())
                except Exception:
                    images_dir = None
                try:
                    xml_path = Path(str(effective_source.get("xml_path") or "").strip())
                except Exception:
                    xml_path = None
                if (
                    run_dir is not None
                    and images_dir is not None
                    and xml_path is not None
                    and run_dir.exists()
                    and images_dir.exists()
                    and xml_path.exists()
                ):
                    return {
                        "restore_run_dir": run_dir,
                        "input_dir": images_dir,
                        "xml_path": xml_path,
                        "input_source": "campaign_char_effective_source",
                        "manual_template": False,
                        "plate_model_path": str(CAMPAIGN.get_global_model("plate") or "").strip(),
                        "display_name": str(
                            effective_source.get("display_name")
                            or "Zatwierdzony zbiór projektu tablic"
                        ).strip(),
                        "run_name": str(
                            effective_source.get("display_name")
                            or getattr(run_dir, "name", "")
                            or ""
                        ).strip(),
                        "contributor_run_dir": str(effective_source.get("contributor_run_dir") or "").strip(),
                    }

        bootstrap = source_state.get("bootstrap")
        return dict(bootstrap) if isinstance(bootstrap, dict) else {}

    def _get_char_training_split_preview(self, total_plates: int) -> dict:
        total = max(0, int(total_plates or 0))
        train_pct = 80.0
        val_pct = 10.0
        test_pct = 10.0

        try:
            char_tab = self.app.tabs.get("characters") if getattr(self.app, "tabs", None) else None
            if char_tab is not None and hasattr(char_tab, "_get_gold_export_split_percentages"):
                train_pct, val_pct, test_pct = char_tab._get_gold_export_split_percentages()
        except Exception:
            train_pct, val_pct, test_pct = 80.0, 10.0, 10.0

        train_count = int(total * (float(train_pct) / 100.0))
        val_count = int(total * (float(val_pct) / 100.0))
        test_count = max(0, total - train_count - val_count)

        return {
            "total_plates": total,
            "train_pct": float(train_pct),
            "val_pct": float(val_pct),
            "test_pct": float(test_pct),
            "train": int(train_count),
            "val": int(val_count),
            "test": int(test_count),
            "ok": bool(total > 0 and train_count > 0 and val_count > 0),
        }

    def _looks_like_campaign_char_dataset_dir(self, dataset_dir: Path | None) -> bool:
        if dataset_dir is None:
            return False
        try:
            dataset_dir = Path(dataset_dir)
            data_yaml = dataset_dir / "data.yaml"
            if not data_yaml.exists():
                return False
            text = data_yaml.read_text(encoding="utf-8", errors="ignore")
            compact = "".join(text.lower().split())
            if "kpt_shape" in text.lower():
                return False
            return "nc:36" in compact
        except Exception:
            return False

    def _detect_campaign_char_ready_dataset_state(self) -> dict:
        result = {
            "ok": False,
            "reason": "missing_char_dataset",
            "message": "",
            "ready_dataset": "",
            "dataset_hint": "",
            "train_images": 0,
            "val_images": 0,
            "test_images": 0,
            "perfect_count": 0,
            "validation_message": "",
        }

        try:
            char_tab = self.app.tabs.get("characters") if getattr(self.app, "tabs", None) else None
            getter = getattr(char_tab, "_get_campaign_step3_training_readiness", None)
            if callable(getter):
                readiness = dict(getter() or {})
                ready_dataset = str(readiness.get("ready_dataset") or "").strip()
                if readiness and (
                    bool(readiness.get("ok"))
                    or (ready_dataset and self._looks_like_campaign_char_dataset_dir(Path(ready_dataset)))
                ):
                    return readiness
        except Exception as e:
            logger.debug(f"Nie udało się pobrać gotowości E3 z Z3: {e}")

        try:
            datasets_dir = CAMPAIGN.get_dir("datasets")
        except Exception:
            datasets_dir = None
        if datasets_dir is None or not Path(datasets_dir).exists():
            return result

        try:
            candidates = sorted(
                [
                    path.parent for path in Path(datasets_dir).rglob("data.yaml")
                    if path.is_file() and self._looks_like_campaign_char_dataset_dir(path.parent)
                ],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return result

        for dataset_dir in candidates:
            counts = {"train": 0, "val": 0, "test": 0}
            labels_ok = True
            label_object_count = 0
            for split_name in ("train", "val", "test"):
                images_dir = dataset_dir / "images" / split_name
                labels_dir = dataset_dir / "labels" / split_name
                if split_name in {"train", "val"} and not labels_dir.exists():
                    labels_ok = False
                if not images_dir.exists() or not images_dir.is_dir():
                    continue
                try:
                    counts[split_name] = sum(
                        1 for path in images_dir.iterdir()
                        if path.is_file() and path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
                    )
                except Exception:
                    counts[split_name] = 0
                try:
                    if labels_dir.exists() and labels_dir.is_dir():
                        for label_path in labels_dir.glob("*.txt"):
                            if not label_path.is_file():
                                continue
                            lines = [
                                line.strip()
                                for line in label_path.read_text(encoding="utf-8").splitlines()
                                if line.strip() and not line.strip().startswith("#")
                            ]
                            label_object_count += len(lines)
                except Exception:
                    pass

            if sum(int(counts.get(name, 0) or 0) for name in ("train", "val", "test")) <= 0:
                flat_images_dir = dataset_dir / "images"
                flat_labels_dir = dataset_dir / "labels"
                flat_image_count = 0
                flat_label_object_count = 0
                if flat_images_dir.exists() and flat_images_dir.is_dir() and flat_labels_dir.exists() and flat_labels_dir.is_dir():
                    try:
                        flat_image_count = sum(
                            1 for path in flat_images_dir.iterdir()
                            if path.is_file() and path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
                        )
                    except Exception:
                        flat_image_count = 0
                    try:
                        for label_path in flat_labels_dir.glob("*.txt"):
                            if not label_path.is_file():
                                continue
                            lines = [
                                line.strip()
                                for line in label_path.read_text(encoding="utf-8").splitlines()
                                if line.strip() and not line.strip().startswith("#")
                            ]
                            flat_label_object_count += len(lines)
                    except Exception:
                        flat_label_object_count = 0

                if flat_image_count > 0 and flat_label_object_count > 0:
                    dataset_str = str(dataset_dir)
                    result.update(
                        ok=True,
                        reason="source_dataset_ready_for_split",
                        ready_dataset=dataset_str,
                        dataset_hint=dataset_str,
                        train_images=0,
                        val_images=0,
                        test_images=0,
                        exportable_char_count=int(flat_label_object_count),
                        validation_message=(
                            "Źródło YOLO Detect jest gotowe do przygotowania wariantu train/val/test w Z4/PZ1."
                        ),
                    )
                    return result

            if labels_ok and counts["train"] > 0 and counts["val"] > 0 and label_object_count > 0:
                dataset_str = str(dataset_dir)
                result.update(
                    ok=True,
                    reason="",
                    ready_dataset=dataset_str,
                    dataset_hint=dataset_str,
                    train_images=int(counts["train"]),
                    val_images=int(counts["val"]),
                    test_images=int(counts["test"]),
                    exportable_char_count=int(label_object_count),
                )
                return result

        if candidates:
            result.update(
                reason="missing_char_boxes",
                message=(
                    "Znaleziono techniczny dataset znaków, ale nie zawiera on żadnych etykiet z boxami znaków. "
                    "Wróć do Z3/PZ2, oznacz boxy znaków i wykonaj eksport w PZ3."
                ),
            )
        return result

    def _get_char_repair_guidance(self, source_state: dict | None = None) -> dict:
        state = dict(source_state or self._get_char_route_source_state() or {})
        images_with_plates = int(state.get("images_with_plates", 0) or 0)
        total_plates = int(state.get("total_plates", 0) or 0)
        run_name = str(state.get("run_name", "") or "").strip()
        source_scope = str(state.get("source_scope", "") or "").strip().lower()
        split_preview = self._get_char_training_split_preview(total_plates)
        source_context = dict(state.get("bootstrap") or {})

        result = {
            "mode": "z2_more_tables",
            "primary_label": "Oznacz więcej tablic",
            "primary_command": self._step_open_z2_repair_from_later_stage,
            "secondary_label": "",
            "secondary_command": None,
            "details": "",
            "split_preview": split_preview,
            "images_with_plates": images_with_plates,
            "total_plates": total_plates,
        }

        if source_scope == "step3_pending_union":
            source_intro = (
                f"Aktywny zbiór Z3/PZ2 wraz z nowymi [OK] z Z2 ({run_name})"
                if run_name
                else "Aktywny zbiór Z3/PZ2 wraz z nowymi [OK] z Z2"
            )
        elif source_scope == "campaign_approved_set":
            source_intro = "Zatwierdzony zbiór tablic projektu"
        elif source_scope == "step3_preview":
            source_intro = (
                f"Aktywny zbiór Z3/PZ2 ({run_name})"
                if run_name
                else "Aktywny zbiór Z3/PZ2"
            )
        else:
            source_intro = (
                f"Źródło {run_name}"
                if run_name
                else "Biezace źródło"
            )

        if split_preview.get("ok"):
            result.update(
                mode="z3_pz2_repair",
                primary_label="Popraw anotacje znaków w Z3/PZ2",
                primary_command=(lambda ctx=dict(source_context): self._step_goto_characters_detect(ctx)),
                secondary_label="Oznacz więcej tablic",
                secondary_command=self._step_open_z2_repair_from_later_stage,
            )
            result["details"] = (
                f"{source_intro} zawiera {total_plates} tablic na {images_with_plates} oznaczonych obrazach. "
                f"To wystarczy, aby po poprawie znaków w Z3/PZ2 przygotować około "
                f"train={split_preview['train']}, val={split_preview['val']}, test={split_preview['test']}."
            )
            return result

        result["details"] = (
            f"{source_intro} zawiera tylko {total_plates} tablic na {images_with_plates} oznaczonych obrazach. "
            f"Przy rozkladzie {split_preview['train_pct']:.0f}/{split_preview['val_pct']:.0f}/{split_preview['test_pct']:.0f} "
            f"dostaniesz tylko train={split_preview['train']}, val={split_preview['val']}, test={split_preview['test']}. "
            "To znaczy, ze sama poprawa znaków w Z3/PZ2 nie wystarczy i najpierw trzeba przygotować więcej tablic w Z2."
        )
        return result

    def _get_active_step3_preview_source_state(self) -> dict:
        try:
            if self._get_iteration_target() != "char":
                return {}
        except Exception:
            return {}

        try:
            current_step = int(CAMPAIGN.get_current_step() or 0)
        except Exception:
            current_step = 0
        if current_step < 3:
            return {}

        preview_dir = None
        tab_char = getattr(self.app, "tabs", {}).get("characters")
        if tab_char is not None and hasattr(tab_char, "preview_dir_var"):
            try:
                preview_dir_raw = str(tab_char.preview_dir_var.get() or "").strip()
            except Exception:
                preview_dir_raw = ""
            if preview_dir_raw:
                try:
                    candidate = Path(preview_dir_raw)
                    if (
                        candidate.exists()
                        and candidate.is_dir()
                        and (candidate / "metadata.json").exists()
                        and (candidate / "images").exists()
                    ):
                        preview_dir = candidate
                except Exception:
                    preview_dir = None

        if preview_dir is None:
            try:
                bundle = dict(
                    CAMPAIGN.get_iteration_artifact_bundle(
                        images_dir=CAMPAIGN.get_iteration_image_source_dir() or CAMPAIGN.get_master_pool_dir() or CAMPAIGN.get_iteration_raw_dir(),
                        iteration_num=int(CAMPAIGN.get_current_iteration_num() or 1),
                    ) or {}
                )
            except Exception:
                bundle = {}
            preview_entry = dict(bundle.get("step3_preview_source") or {})
            preview_dir_raw = str(preview_entry.get("preview_dir") or "").strip()
            if preview_dir_raw:
                try:
                    candidate = Path(preview_dir_raw)
                    if (
                        candidate.exists()
                        and candidate.is_dir()
                        and (candidate / "metadata.json").exists()
                        and (candidate / "images").exists()
                    ):
                        preview_dir = candidate
                except Exception:
                    preview_dir = None

        if preview_dir is None:
            try:
                saved_preview_dir = str(CAMPAIGN.get_step3_preview_dir() or "").strip()
            except Exception:
                saved_preview_dir = ""
            if saved_preview_dir:
                try:
                    candidate = Path(saved_preview_dir)
                    if (
                        candidate.exists()
                        and candidate.is_dir()
                        and (candidate / "metadata.json").exists()
                        and (candidate / "images").exists()
                    ):
                        preview_dir = candidate
                except Exception:
                    preview_dir = None

        if preview_dir is None:
            try:
                chars_dir = CAMPAIGN.get_dir("chars")
            except Exception:
                chars_dir = None
            if chars_dir is not None:
                try:
                    chars_root = Path(chars_dir)
                except Exception:
                    chars_root = None
                if chars_root is not None and chars_root.exists() and chars_root.is_dir():
                    candidates: list[Path] = []
                    try:
                        for candidate in chars_root.rglob("*"):
                            if not candidate.is_dir():
                                continue
                            if (candidate / "metadata.json").exists() and (candidate / "images").exists():
                                candidates.append(candidate)
                    except Exception:
                        candidates = []
                    if candidates:
                        try:
                            candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
                        except Exception:
                            pass
                        preview_dir = candidates[0]

        if preview_dir is None:
            return {}

        try:
            loaded = json.loads((preview_dir / "metadata.json").read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(loaded, dict) or not loaded:
            return {}

        total_plates = 0
        unique_sources: set[str] = set()
        for pid, payload in loaded.items():
            pid_text = str(pid or "").strip()
            if not pid_text:
                continue
            total_plates += 1
            source_key = ""
            if isinstance(payload, dict):
                source_info = payload.get("source_info") or {}
                if not isinstance(source_info, dict):
                    source_info = {}
                source_key = str(
                    payload.get("source_image")
                    or payload.get("source_name")
                    or source_info.get("image_name")
                    or pid_text
                ).strip()
            if not source_key:
                source_key = pid_text
            unique_sources.add(source_key)

        images_with_plates = int(len(unique_sources) or total_plates or 0)
        total_plates = int(total_plates or 0)
        if total_plates <= 0:
            return {}

        return {
            "source_scope": "step3_preview",
            "run_dir": preview_dir,
            "run_name": str(preview_dir.name or "").strip(),
            "images_with_plates": images_with_plates,
            "total_plates": total_plates,
            "source_names": set(unique_sources),
        }

    def _get_pending_step3_char_union_state(self) -> dict:
        try:
            return dict(CAMPAIGN.get_step3_char_source_state() or {})
        except Exception:
            return {}

    def _get_char_route_source_state(self) -> dict:
        result = {
            "ready": False,
            "has_source": False,
            "needs_more_tables": False,
            "images_with_plates": 0,
            "total_plates": 0,
            "restore_run_dir": None,
            "run_name": "",
            "bootstrap": {},
        }
        source_state = self._get_annotation_step2_source_state("char")
        if not source_state:
            source_state = {}
        result.update(source_state)

        pending_union_state = self._get_pending_step3_char_union_state()
        if pending_union_state:
            result["has_source"] = True
            result["source_scope"] = str(pending_union_state.get("source_scope") or "step3_pending_union").strip()
            result["images_with_plates"] = int(pending_union_state.get("images_with_plates", 0) or 0)
            result["total_plates"] = int(pending_union_state.get("total_plates", 0) or 0)
            result["run_name"] = str(pending_union_state.get("run_name") or result.get("run_name") or "").strip()
            result["project_images_with_plates"] = int(pending_union_state.get("project_images_with_plates", 0) or 0)
            result["project_total_plates"] = int(pending_union_state.get("project_total_plates", 0) or 0)
            result["current_images_with_plates"] = int(pending_union_state.get("current_images_with_plates", 0) or 0)
            result["current_total_plates"] = int(pending_union_state.get("current_total_plates", 0) or 0)
            result["preview_images_with_plates"] = int(pending_union_state.get("preview_images_with_plates", 0) or 0)
            result["preview_total_plates"] = int(pending_union_state.get("preview_total_plates", 0) or 0)
            result["pending_images_with_plates"] = int(pending_union_state.get("pending_images_with_plates", 0) or 0)
            result["pending_total_plates"] = int(pending_union_state.get("pending_total_plates", 0) or 0)
            min_char_plates = int(getattr(self, "STEP3_CHAR_MIN_PLATES", 10) or 10)
            result["ready"] = bool(
                int(result.get("total_plates", 0) or 0) >= min_char_plates
            )
            result["needs_more_tables"] = bool(
                result["has_source"] and not result["ready"]
            )
        return result

    def _get_plate_route_ready_source(self) -> dict:
        if CAMPAIGN.get_step2_status() == "generated":
            return {}
        source_state = self._get_annotation_step2_source_state("plate")
        bootstrap = source_state.get("bootstrap")
        return dict(bootstrap) if isinstance(bootstrap, dict) else {}

    def _get_step2_staging_run_dir(self) -> Path | None:
        run_dir = str(CAMPAIGN.get_step2_staging_run() or "").strip()
        if not run_dir:
            return None

        try:
            candidate = Path(run_dir)
        except Exception:
            return None

        if not candidate.exists() or not candidate.is_dir():
            return None
        if not (candidate / "annotations.xml").exists():
            return None
        return candidate

    @staticmethod
    def _count_step2_images_in_dir(directory: Path | None) -> int:
        if directory is None:
            return 0
        try:
            return sum(
                1
                for image_path in Path(directory).iterdir()
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            )
        except Exception:
            return 0

    def _get_latest_project_dataset_hint(self) -> Path | None:
        datasets_dir = CAMPAIGN.get_dir("datasets")
        if datasets_dir is None:
            return None

        datasets_dir = Path(datasets_dir)
        if not datasets_dir.exists() or not datasets_dir.is_dir():
            return None

        candidates = []
        try:
            for child in datasets_dir.iterdir():
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    try:
                        has_content = any(child.iterdir())
                    except Exception:
                        has_content = False
                    if not has_content:
                        continue
                elif not child.is_file():
                    continue
                candidates.append(child)
        except Exception:
            return None

        if not candidates:
            return None

        try:
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        except Exception:
            candidates.sort(key=lambda path: path.name.lower(), reverse=True)
        return candidates[0]

    @staticmethod
    def _describe_step2_bootstrap_source(source_key: str | None = None) -> str:
        key = str(source_key or "").strip().lower()
        labels = {
            "manual_source_run": "ręczne tablice dla tego katalogu zdjęć",
            "reused_manual_source_run": "ręczne tablice z poprzedniej iteracji",
            "reused_training_source_run": "run wykorzystany w poprzednim treningu",
            "reused_iteration_run": "run odzyskany z poprzedniej iteracji",
            "latest_approved_run": "ostatni zatwierdzony run projektu",
            "project_imported_manual_source": "run zaimportowany na starcie projektu",
            "project_imported_images": "obrazy wskazane przy starcie projektu",
            "stage_current_iteration": "stage tej iteracji",
            "stage_previous_iteration": "stage poprzedniej iteracji",
            "raw": "surowe obrazy z E1",
        }
        return labels.get(key, "zasob wykryty automatycznie")

    def _collect_step2_asset_rows(self, *, current_target: str = "") -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add_row(label: str, value: str) -> None:
            clean_label = str(label or "").strip()
            clean_value = str(value or "").strip()
            if not clean_label or not clean_value:
                return
            key = (clean_label, clean_value)
            if key in seen:
                return
            seen.add(key)
            rows.append(key)

        current_target = self._normalize_iteration_target(current_target)
        try:
            iter_dir = CAMPAIGN.get_iteration_image_source_dir()
        except Exception:
            iter_dir = CAMPAIGN.get_iteration_raw_dir()
        try:
            image_count = int(CAMPAIGN.get_iteration_image_count() or 0)
        except Exception:
            image_count = self._count_step2_images_in_dir(iter_dir)
        if iter_dir is not None:
            iter_name = Path(iter_dir).name
            add_row("E1", f"{iter_name} | {image_count} obrazów" if image_count else f"{iter_name} | brak obrazów")

        staging_run = self._get_step2_staging_run_dir()
        if staging_run is not None:
            add_row("Aktywny Z2", staging_run.name)

        if current_target in {"", "plate"}:
            plate_ready_source = self._get_plate_route_ready_source()
            if plate_ready_source:
                run_dir = plate_ready_source.get("restore_run_dir")
                if run_dir is not None:
                    add_row(
                        "Tor A",
                        f"{Path(run_dir).name} | {self._describe_step2_bootstrap_source(plate_ready_source.get('input_source'))}",
                    )

        if current_target in {"", "char"}:
            char_ready_source = self._get_char_route_ready_source()
            if char_ready_source:
                run_dir = char_ready_source.get("restore_run_dir")
                if run_dir is not None:
                    add_row("Tor B", f"{Path(run_dir).name} | gotowe ręczne tablice")

        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        if plate_model_path and Path(plate_model_path).exists():
            plate_identity = self._get_model_identity_label(plate_model_path)
            plate_text = Path(plate_model_path).name
            if plate_identity:
                plate_text += f" | {plate_identity}"
            add_row("Model tablic", plate_text)

        dataset_hint = self._get_latest_project_dataset_hint()
        if dataset_hint is not None:
            add_row("Dataset", dataset_hint.name)

        return rows

    def _render_step2_asset_summary(self, frame, *, current_target: str = ""):
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
        rows = self._collect_step2_asset_rows(current_target=current_target)
        if not rows:
            return

        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        panel_bg = blend_hex_colors(card_bg, palette.get("panel_alt", "#2d2d30"), 0.35)
        shell = tk.Frame(
            frame,
            bg=panel_bg,
            bd=0,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
        )
        shell.pack(fill=tk.X, pady=(8, 0))

        inner = tk.Frame(shell, bg=panel_bg)
        inner.pack(fill=tk.X, padx=12, pady=10)

        tk.Label(
            inner,
            text="Kontekst tej iteracji",
            fg=palette.get("fg", "#f3f3f3"),
            bg=panel_bg,
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W, fill=tk.X)

        grid = tk.Frame(inner, bg=panel_bg)
        grid.pack(fill=tk.X, pady=(6, 0))
        grid.grid_columnconfigure(0, minsize=110)
        grid.grid_columnconfigure(1, weight=1)

        for row_idx, (label, value) in enumerate(rows):
            tk.Label(
                grid,
                text=f"{label}:",
                fg=palette.get("muted", "#c7c7c7"),
                bg=panel_bg,
                anchor="nw",
                justify=tk.LEFT,
                font=("Segoe UI", 9, "bold"),
            ).grid(row=row_idx, column=0, sticky="nw", padx=(0, 8), pady=(0, 4))
            tk.Label(
                grid,
                text=value,
                fg=palette.get("fg", "#f3f3f3"),
                bg=panel_bg,
                anchor="nw",
                justify=tk.LEFT,
                wraplength=400,
            ).grid(row=row_idx, column=1, sticky="nw", pady=(0, 4))


    def _get_step2_jump_button_text(self, target: str) -> str:
        target = self._normalize_iteration_target(target)

        if target == "plate":
            if CAMPAIGN.get_step2_status() == "generated":
                return "Sprawdź tablice w Z2"
            plate_bootstrap = self._get_annotation_bootstrap_for_target("plate")
            if not bool(plate_bootstrap.get("manual_template", True)):
                return "Przygotuj tablice na modelu projektu (Z2)"
            return "Przejdź do anotacji tablic"

        if target == "char":
            if CAMPAIGN.get_step2_status() == "generated":
                return "Sprawdź tablice w Z2"
            char_source_state = self._get_char_route_source_state()
            preflight = self._get_step1_char_route_preflight_state()
            plate_source_state = self._get_annotation_step2_source_state("plate")
            plate_model_ready = bool(plate_source_state.get("plate_model_ready"))
            if bool(char_source_state.get("ready")) and bool(preflight.get("material_ready")):
                return "Pracuj na znakach tablic"
            if bool(char_source_state.get("has_source")):
                return "Uzupełnij tablice w Z2"
            if plate_model_ready:
                return "Przygotuj tablice na modelu projektu (Z2)"
            return "Przejdź do anotacji tablic"

        return "Najpierw wybierz tor"

    @staticmethod
    def _iteration_target_label(target: str) -> str:
        if target == "plate":
            return "tor tablic"
        if target == "char":
            return "tor znaków"
        return "nie wybrano toru"

    def _iteration_target_button_label(self, route: str, *, current_target: str = "", last_target: str = "") -> str:
        route = self._normalize_iteration_target(route)
        current_target = self._normalize_iteration_target(current_target)
        last_target = self._normalize_iteration_target(last_target)

        if route == "plate":
            if not current_target and last_target == "plate":
                return "Tor tablic (kontynuuj)"
            return "Tor tablic"

        if route == "char":
            if not current_target and last_target == "char":
                return "Tor znaków (kontynuuj)"
            return "Tor znaków"

        return ""

    def _get_iteration_target_lock_reason(self) -> str:
        current_target = self._get_iteration_target()
        if current_target not in {"plate", "char"}:
            return ""

        active_route_label = self._iteration_target_button_label(current_target)
        if not active_route_label:
            active_route_label = (
                "Tor tablic"
                if current_target == "plate"
                else "Tor znaków"
            )

        current_step = int(CAMPAIGN.get_current_step() or 1)
        step1_status = str(CAMPAIGN.get_step1_status() or "").strip().lower()
        step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()

        if step1_status == "approved":
            return (
                f"Tor tej iteracji: „{active_route_label}”. "
                "Drugi tor wybierzesz dopiero w kolejnej iteracji."
            )

        if current_step > 2:
            return (
                f"Ta iteracja trwa już w „{active_route_label}”. "
                "Drugi tor będzie dostępny dopiero w nowej iteracji."
            )

        if step2_status in {"approved"}:
            return (
                f"Ta iteracja trwa już w „{active_route_label}”. "
                "Drugi tor będzie dostępny dopiero w nowej iteracji."
            )

        return ""

    def _get_step1_char_preflight_image_count(self) -> int:
        try:
            plan = dict(self.current_ingest_plan or {})
        except Exception:
            plan = {}

        if plan:
            try:
                selected_total = int(plan.get("selected_total", 0) or 0)
            except Exception:
                selected_total = 0
            if selected_total > 0:
                return selected_total
            try:
                selected_items = list(plan.get("selected") or [])
                if selected_items:
                    return int(len(selected_items))
            except Exception:
                pass

        try:
            image_source = dict(self._get_project_start_effective_images_source() or {})
        except Exception:
            image_source = {}

        counts = []
        for key in ("iteration_count", "effective_count", "master_count"):
            try:
                counts.append(int(image_source.get(key, 0) or 0))
            except Exception:
                counts.append(0)
        return max(counts) if counts else 0

    @staticmethod
    def _count_plate_annotations_in_xml(xml_path: Path | str | None) -> int:
        try:
            path = Path(xml_path) if xml_path is not None else None
        except Exception:
            path = None
        if path is None or not path.exists() or not path.is_file():
            return 0

        try:
            root = ET.parse(path).getroot()
        except Exception:
            return 0

        negative_label_parts = ("vehicle", "car", "pojazd")
        positive_label_parts = ("plate", "tablic")
        count = 0
        for image_node in root.findall(".//image"):
            for det_node in list(image_node):
                tag_name = str(getattr(det_node, "tag", "") or "").strip().lower()
                if tag_name not in {"polygon", "box"}:
                    continue
                label = str(det_node.get("label", "") or "").strip().lower()
                if label and any(part in label for part in negative_label_parts):
                    continue
                if not label or any(part in label for part in positive_label_parts):
                    count += 1
        return int(count)

    def _count_step1_imported_plate_annotations(self) -> int:
        try:
            plate_source_info = dict(self._get_project_start_plate_source_info() or {})
        except Exception:
            plate_source_info = {}

        candidates: list[Path] = []
        xml_path = str(plate_source_info.get("xml_path") or "").strip()
        run_path = str(plate_source_info.get("run_path") or "").strip()
        if xml_path:
            try:
                candidates.append(Path(xml_path))
            except Exception:
                pass
        if run_path:
            try:
                candidates.append(Path(run_path) / "annotations.xml")
            except Exception:
                pass

        for candidate in candidates:
            count = self._count_plate_annotations_in_xml(candidate)
            if count > 0:
                return count
        return 0

    def _get_step1_char_route_preflight_state(self) -> dict:
        min_images = int(getattr(self, "STEP1_CHAR_MIN_IMAGES", 10) or 10)
        min_plates = int(getattr(self, "STEP3_CHAR_MIN_PLATES", 10) or 10)
        image_count = self._get_step1_char_preflight_image_count()

        try:
            approved_stats = dict(self._get_plate_approved_set_stats() or {})
        except Exception:
            approved_stats = {}
        approved_plate_count = int(approved_stats.get("plates", 0) or 0)
        approved_image_count = int(approved_stats.get("images", 0) or 0)

        try:
            char_source_state = dict(self._get_char_route_source_state() or {})
        except Exception:
            char_source_state = {}
        source_plate_count = max(
            int(char_source_state.get("total_plates", 0) or 0),
            int(char_source_state.get("project_total_plates", 0) or 0),
            int(char_source_state.get("current_total_plates", 0) or 0),
            int(char_source_state.get("pending_total_plates", 0) or 0),
            approved_plate_count,
        )
        source_image_count = max(
            int(char_source_state.get("images_with_plates", 0) or 0),
            int(char_source_state.get("project_images_with_plates", 0) or 0),
            int(char_source_state.get("current_images_with_plates", 0) or 0),
            int(char_source_state.get("pending_images_with_plates", 0) or 0),
            approved_image_count,
        )

        imported_plate_count = self._count_step1_imported_plate_annotations()
        plate_material_count = max(source_plate_count, approved_plate_count, imported_plate_count)
        material_ready = bool(plate_material_count >= min_plates)
        image_potential = bool(image_count >= min_images)
        allow_route = bool(material_ready or image_potential)

        if material_ready:
            mode = "material_ready"
        elif image_potential:
            mode = "image_potential"
        else:
            mode = "blocked"

        if allow_route:
            block_reason = ""
        elif image_count <= 0 and plate_material_count <= 0:
            block_reason = (
                "Najpierw wybierz katalog zdjęć w E1 albo dodaj zgodne anotacje tablic. "
                f"Tor znaków potrzebuje co najmniej {min_images} obrazów na start lub "
                f"{min_plates} gotowych tablic z wcześniejszych albo importowanych anotacji."
            )
        else:
            block_reason = (
                f"Tor znaków nie ma jeszcze bezpiecznego minimum wejściowego: E1 widzi {image_count} obrazów "
                f"oraz {plate_material_count} gotowych tablic. Wybierz co najmniej {min_images} obrazów "
                f"albo dostarcz {min_plates} gotowych tablic."
            )

        return {
            "mode": mode,
            "allow_route": allow_route,
            "block_reason": block_reason,
            "image_count": int(image_count),
            "min_images": int(min_images),
            "plate_material_count": int(plate_material_count),
            "source_plate_count": int(source_plate_count),
            "source_image_count": int(source_image_count),
            "approved_plate_count": int(approved_plate_count),
            "approved_image_count": int(approved_image_count),
            "imported_plate_count": int(imported_plate_count),
            "min_plates": int(min_plates),
            "material_ready": material_ready,
            "image_potential": image_potential,
        }

    def _get_step1_char_preflight_signature(self, state: dict | None = None) -> tuple:
        state = dict(state or self._get_step1_char_route_preflight_state() or {})
        try:
            iteration_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            iteration_num = 1
        return (
            str(CAMPAIGN.get_active_project_name() or "").strip(),
            int(iteration_num),
            int(state.get("image_count", 0) or 0),
            int(state.get("plate_material_count", 0) or 0),
            int(state.get("imported_plate_count", 0) or 0),
        )

    def _confirm_step1_char_preflight_warning(self, state: dict | None = None) -> bool:
        state = dict(state or self._get_step1_char_route_preflight_state() or {})
        if str(state.get("mode") or "").strip() != "image_potential":
            return True

        signature = self._get_step1_char_preflight_signature(state)
        if getattr(self, "_step1_char_preflight_ack_signature", None) == signature:
            return True

        image_count = int(state.get("image_count", 0) or 0)
        min_plates = int(state.get("min_plates", self.STEP3_CHAR_MIN_PLATES) or self.STEP3_CHAR_MIN_PLATES)
        message = (
            f"E1 widzi {image_count} obrazów, ale nie ma jeszcze {min_plates} gotowych tablic do pracy w E3.\n\n"
            "Możesz wybrać tor znaków, ale E2/Z2 będzie wtedy etapem przygotowania tablic. "
            "Dopiero po oznaczeniu i zatwierdzeniu odpowiedniej liczby obrazów program będzie miał realny materiał "
            "do wycinania tablic i dalszej pracy nad znakami.\n\n"
            "Jeśli okaże się, że wybrany katalog zdjęć nie pozwala uzyskać minimum, wrócisz do E1 po większy katalog "
            "albo do E2/Z2, żeby przygotować więcej tablic."
        )
        try:
            confirmed = self.app.themed_confirm(
                "Tor znaków: preflight E1",
                message,
                parent=self.frame,
                confirm_label="Wybierz tor znaków",
                cancel_label="Zostań w E1",
                tone="warning",
            )
        except Exception:
            confirmed = messagebox.askyesno("Tor znaków: preflight E1", message, parent=self.frame)
        if confirmed:
            self._step1_char_preflight_ack_signature = signature
        return bool(confirmed)

    def _validate_step1_char_preflight_for_approval(self) -> bool:
        if self._get_iteration_target() != "char":
            return True

        state = self._get_step1_char_route_preflight_state()
        if not bool(state.get("allow_route")):
            message = str(state.get("block_reason") or "").strip()
            if not message:
                message = (
                    "Tor znaków wymaga wybranego katalogu zdjęć albo gotowych anotacji tablic. "
                    "Uzupełnij E1 przed zatwierdzeniem."
                )
            try:
                self.app.themed_info(
                    "E1 nie jest gotowe dla toru znaków",
                    message,
                    parent=self.frame,
                    tone="warning",
                )
            except Exception:
                messagebox.showwarning("E1 nie jest gotowe dla toru znaków", message, parent=self.frame)
            return False

        return self._confirm_step1_char_preflight_warning(state)

    def _format_step1_char_route_card_body(self, state: dict | None = None, block_reason: str = "") -> str:
        state = dict(state or self._get_step1_char_route_preflight_state() or {})
        if block_reason:
            return block_reason

        min_plates = int(state.get("min_plates", self.STEP3_CHAR_MIN_PLATES) or self.STEP3_CHAR_MIN_PLATES)
        if bool(state.get("material_ready")):
            return (
                f"E1 widzi {int(state.get('plate_material_count', 0) or 0)} gotowych tablic. "
                "Po zatwierdzeniu E1 możesz przejść do E3/Z3 i pracować na znakach tablic."
            )
        if bool(state.get("image_potential")):
            return (
                f"E1 widzi {int(state.get('image_count', 0) or 0)} obrazów. "
                f"To bezpieczny start, ale minimum pracy w E3 to {min_plates} tablic przygotowanych w E2/Z2."
            )
        return str(state.get("block_reason") or "")

    def _get_step1_char_route_block_reason(self) -> str:
        try:
            if (
                str(CAMPAIGN.get_step1_status() or "").strip().lower() == "approved"
                or int(CAMPAIGN.get_current_step() or 1) > 1
            ):
                return ""
        except Exception:
            return ""

        state = self._get_step1_char_route_preflight_state()
        return "" if bool(state.get("allow_route")) else str(state.get("block_reason") or "")

    def _has_saved_step3_progress(self) -> bool:
        try:
            saved_substep = int(CAMPAIGN.get_step3_substep() or 1)
        except Exception:
            saved_substep = 1

        try:
            stage1_done = bool(CAMPAIGN.is_step3_stage1_done())
        except Exception:
            stage1_done = False

        try:
            stage2_done = bool(CAMPAIGN.is_step3_stage2_done())
        except Exception:
            stage2_done = False

        try:
            extract_state = CAMPAIGN.get_step3_extract_state() or {}
        except Exception:
            extract_state = {}

        entry_mode = str(extract_state.get("entry_mode", "") or "").strip()
        workflow_step = str(extract_state.get("workflow_step", "entry") or "entry").strip().lower()
        annotation_run_dir = str(extract_state.get("annotation_run_dir", "") or "").strip()
        xml_path = str(extract_state.get("xml_path", "") or "").strip()
        images_dir = str(extract_state.get("images_dir", "") or "").strip()

        return bool(
            saved_substep > 1
            or stage1_done
            or stage2_done
            or entry_mode
            or workflow_step != "entry"
            or annotation_run_dir
            or xml_path
            or images_dir
        )

    @staticmethod
    def _campaign_paths_equivalent(path_a, path_b) -> bool:
        text_a = str(path_a or "").strip()
        text_b = str(path_b or "").strip()
        if not text_a or not text_b:
            return False
        try:
            return Path(text_a).resolve() == Path(text_b).resolve()
        except Exception:
            return text_a == text_b

    def _should_reset_stale_char_iteration_state(
        self,
        *,
        current_step: int,
        step2_status: str,
        step3_status: str,
        iteration_target: str,
    ) -> bool:
        try:
            suppress_until = float(getattr(self, "_suppress_stale_char_iteration_reset_until", 0.0) or 0.0)
        except Exception:
            suppress_until = 0.0
        if suppress_until > 0.0 and perf_counter() < suppress_until:
            return False

        if self._normalize_iteration_target(iteration_target) != "char":
            return False

        try:
            current_char_source_state = dict(
                self._get_annotation_step2_source_state_from_registry("char") or {}
            )
        except Exception:
            current_char_source_state = {}
        if bool(current_char_source_state.get("has_source")):
            return False

        normalized_step2_status = str(step2_status or "").strip().lower()
        normalized_step3_status = str(step3_status or "").strip().lower()
        if (
            int(current_step or 0) < 3
            and normalized_step2_status not in {"approved", "generated"}
            and normalized_step3_status == "pending"
        ):
            return False

        try:
            if str(CAMPAIGN.get_step2_staging_run() or "").strip():
                return False
        except Exception:
            pass

        try:
            current_iter_dir = CAMPAIGN.get_iteration_image_source_dir() or CAMPAIGN.get_iteration_raw_dir()
        except Exception:
            current_iter_dir = None
        if current_iter_dir is None:
            return False

        try:
            stored_manual_source = CAMPAIGN.get_last_plate_manual_source() or {}
        except Exception:
            stored_manual_source = {}

        source_input = str((stored_manual_source or {}).get("source_input_path") or "").strip()
        if not source_input:
            return False

        return not self._campaign_paths_equivalent(current_iter_dir, source_input)

    def _get_campaign_step_title(self, step_num: int, target: str) -> str:
        if step_num == 2:
            if target == "plate":
                return "E2. Tablice Z2"
            if target == "char":
                return "E2. Tablice jako źródło dla Z3"
            return "E2. Tablice"

        if step_num == 3:
            if target == "plate":
                return "E3. Tor znaków (pominięty)"
            return "E3. Tor znaków"

        if step_num == 4:
            if target == "plate":
                return "E4. Tor tablic: dataset + trening Pose"
            if target == "char":
                return "E4. Tor znaków: dataset + trening YOLO"
            return "E4. Trening wybranego toru"

        return ""

    def _choose_step1_iteration_target(self, target: str):
        switch_started = perf_counter()
        target = self._normalize_iteration_target(target)
        if target not in {"plate", "char"}:
            return
        if target == "char":
            preflight_state = self._get_step1_char_route_preflight_state()
            block_reason = self._get_step1_char_route_block_reason()
            if block_reason:
                try:
                    messagebox.showinfo("Tor znaków jest zablokowany", block_reason, parent=self.frame)
                except Exception:
                    pass
                return
            if not self._confirm_step1_char_preflight_warning(preflight_state):
                return

        previous_target = self._normalize_iteration_target(CAMPAIGN.get_iteration_target())
        if previous_target == target:
            try:
                self._wizard_step2_target_var.set(target)
            except Exception:
                pass
            return

        if previous_target in {"plate", "char"} and previous_target != target:
            lock_reason = self._get_iteration_target_lock_reason()
            if lock_reason:
                try:
                    self.app.update_status(lock_reason, "info")
                except Exception:
                    pass
                return

        plate_model_ready = False
        if target == "char":
            try:
                plate_source_state = self._get_annotation_step2_source_state("plate")
            except Exception:
                plate_source_state = {}
            plate_model_ready = bool(plate_source_state.get("plate_model_ready"))

        last_target = self._get_last_iteration_target()
        route_changed = previous_target in {"plate", "char"} and previous_target != target
        continuing_previous_iteration_route = bool(last_target and last_target == target and not route_changed)
        lightweight_route_reset = bool(
            route_changed
            and int(CAMPAIGN.get_current_step() or 0) <= 2
            and str(CAMPAIGN.get_step2_status() or "").strip().lower() in {"", "pending"}
            and str(CAMPAIGN.get_step3_status() or "").strip().lower() in {"", "pending"}
            and not str(CAMPAIGN.get_step2_staging_run() or "").strip()
        )

        CAMPAIGN.set_iteration_target(target)
        try:
            if str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved":
                CAMPAIGN.set_current_step(1)
        except Exception:
            pass
        try:
            self._wizard_step2_target_var.set(target)
        except Exception:
            pass

        pending_after = getattr(self, "_iteration_target_change_after_id", None)
        if pending_after is not None:
            try:
                self.frame.after_cancel(pending_after)
            except Exception:
                pass
            self._iteration_target_change_after_id = None

        def _finish_target_switch():
            finish_started = perf_counter()
            self._iteration_target_change_after_id = None
            if route_changed:
                cleanup_started = perf_counter()
                try:
                    annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
                    if annotation_tab is not None:
                        annotation_tab.reset_campaign_iteration_route_state(
                            new_target=target,
                            remove_persisted_runs=not lightweight_route_reset,
                        )
                except Exception as e:
                    logger.debug(f"Nie udało się wyczyscic stanu Z2 po zmianie toru iteracji: {e}")

                if str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved":
                    CAMPAIGN.set_current_step(1)
                elif int(CAMPAIGN.get_current_step() or 0) >= 2:
                    CAMPAIGN.set_current_step(2)
                CAMPAIGN.reset_step2()
                CAMPAIGN.reset_step3()
                self._log_perf(
                    "iteration_target_cleanup",
                    cleanup_started,
                    threshold_ms=20.0,
                    extra=(
                        f"from={previous_target or '-'} to={target} "
                        f"lightweight={1 if lightweight_route_reset else 0}"
                    ),
                )

            self._refresh_active_project_wizard_only()
            self.app.update_campaign_tab_access()
            jump_label = self._get_step2_jump_button_text(target)
            try:
                step1_pending = str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved"
                if target == "plate":
                    if step1_pending:
                        status_text = "Wybrano tor tablic w E1. Zatwierdź E1, aby odblokować E2/Z2."
                    elif continuing_previous_iteration_route:
                        status_text = f"Wybrano tor tablic. Kontynuujesz tor z poprzedniej iteracji; użyj przycisku '{jump_label}', gdy chcesz przejść dalej."
                    elif not route_changed:
                        status_text = f"Wybrano tor tablic. Użyj przycisku '{jump_label}', gdy chcesz przejść dalej."
                    else:
                        status_text = f"Wybrano tor tablic. Poprzedni stan Z2 tej iteracji został zresetowany; przejdź dalej przyciskiem '{jump_label}'."
                    self.app.update_status(status_text, "info")
                else:
                    if step1_pending:
                        status_text = "Wybrano tor znaków w E1. Zatwierdź E1, aby odblokować E2 jako etap przygotowania tablic."
                    elif continuing_previous_iteration_route:
                        status_text = f"Wybrano tor znaków. Kontynuujesz tor z poprzedniej iteracji; użyj przycisku '{jump_label}', gdy chcesz przejść dalej."
                    elif not route_changed:
                        status_text = (
                            f"Wybrano tor znaków. Model tablic projektu jest już dostępny i nie trzeba go dodawać ponownie w E1; użyj przycisku '{jump_label}', aby przygotować tablice."
                            if plate_model_ready and not self._get_char_route_ready_source()
                            else f"Wybrano tor znaków. Użyj przycisku '{jump_label}', gdy chcesz przejść dalej."
                        )
                    else:
                        status_text = f"Wybrano tor znaków. Poprzedni stan Z2 tej iteracji został zresetowany; przejdź dalej przyciskiem '{jump_label}'."
                    self.app.update_status(status_text, "info")
            except Exception:
                pass
            self._log_perf(
                "iteration_target_switch",
                finish_started,
                threshold_ms=20.0,
                extra=f"route_changed={route_changed}, target={target}",
            )
            self._log_perf(
                "iteration_target_switch_total",
                switch_started,
                threshold_ms=20.0,
                extra=f"from={previous_target or '-'} to={target}",
            )

        try:
            self._iteration_target_change_after_id = self.frame.after_idle(_finish_target_switch)
        except Exception:
            _finish_target_switch()

    def _render_step1_route_actions(self, frame):
        if frame is None:
            return

        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
        panel_alt = palette.get("panel_alt", "#2d2d30")
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        muted_dim = palette.get("muted_dim", "#9a9a9a")
        success = palette.get("success", "#27ae60")
        warning = palette.get("warning", "#f39c12")
        accent = blend_hex_colors(palette.get("accent", "#2980b9"), card_bg, 0.42)
        selected_border = blend_hex_colors(success, card_bg, 0.18)
        disabled_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        for widget in frame.winfo_children():
            widget.destroy()
        frame.configure(bg=card_bg)

        current_target = self._get_iteration_target()
        lock_reason = self._get_iteration_target_lock_reason()
        target_locked = bool(lock_reason)
        last_target = self._get_last_iteration_target()

        try:
            current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            current_iteration = 1
        try:
            current_step = int(CAMPAIGN.get_current_step() or 1)
        except Exception:
            current_step = 1

        try:
            self._wizard_step2_target_var.set(current_target if current_target in {"plate", "char"} else "")
        except Exception:
            pass

        char_preflight_state = self._get_step1_char_route_preflight_state()
        char_block_reason = self._get_step1_char_route_block_reason()
        char_route_body = self._format_step1_char_route_card_body(char_preflight_state, char_block_reason)
        if current_target == "char" and char_block_reason:
            try:
                CAMPAIGN.set_iteration_target("")
            except Exception:
                pass
            current_target = ""
            try:
                self._wizard_step2_target_var.set("")
            except Exception:
                pass

        title_row = tk.Frame(frame, bg=card_bg)
        title_row.pack(fill=tk.X)
        tk.Label(
            title_row,
            text="Tor iteracji",
            fg=fg,
            bg=card_bg,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT, anchor=tk.W)
        tk.Label(
            title_row,
            text="decyzja E1",
            fg=success if current_target in {"plate", "char"} else warning,
            bg=card_bg,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT, padx=(8, 0), anchor=tk.W)

        hint_text = (
            "Wybierz kierunek iteracji przed zatwierdzeniem E1. "
            "E2 zawsze oznacza pracę na tablicach; dopiero wybrany tor decyduje, czy po E2 idziemy do treningu tablic, czy do E3/Z3 ze znakami."
        )
        tk.Label(
            frame,
            text=hint_text,
            fg=muted,
            bg=card_bg,
            justify=tk.LEFT,
            anchor="w",
            wraplength=620,
        ).pack(fill=tk.X, pady=(4, 8))

        route_row = tk.Frame(frame, bg=card_bg)
        route_row.pack(fill=tk.X)

        route_cards = [
            {
                "target": "plate",
                "title": "Tor tablic",
                "body": "E2: anotacja tablic w Z2. Po zatwierdzeniu etap Z3 jest pomijany, a projekt przechodzi do E4/Z4.",
                "enabled": bool(not target_locked and current_target != "plate"),
            },
            {
                "target": "char",
                "title": "Tor znaków",
                "body": char_route_body,
                "enabled": bool(not target_locked and current_target != "char" and not char_block_reason),
            },
        ]

        for idx, route in enumerate(route_cards):
            route_target = route["target"]
            selected = bool(current_target == route_target)
            enabled = bool(route["enabled"])
            card_border = selected_border if selected else (accent if enabled else disabled_border)
            card = tk.Frame(
                route_row,
                bg=card_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=card_border,
                highlightcolor=card_border,
                padx=10,
                pady=8,
                cursor=("hand2" if enabled else ""),
            )
            card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8) if idx == 0 else (0, 0))

            badge_text = "WYBRANE" if selected else ("DOSTĘPNE" if enabled else "NIEDOSTĘPNE")
            badge_bg = (
                blend_hex_colors(success, card_bg, 0.18)
                if selected
                else (blend_hex_colors(accent, card_bg, 0.22) if enabled else blend_hex_colors(panel_alt, card_bg, 0.28))
            )
            badge_fg = self._pick_readable_text_color(badge_bg)

            header = tk.Frame(card, bg=card_bg, cursor=("hand2" if enabled else ""))
            header.pack(fill=tk.X)
            tk.Label(
                header,
                text=route["title"],
                fg=(fg if enabled or selected else muted_dim),
                bg=card_bg,
                font=("Segoe UI", 10, "bold"),
                anchor="w",
                cursor=("hand2" if enabled else ""),
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(
                header,
                text=badge_text,
                fg=badge_fg,
                bg=badge_bg,
                font=("Segoe UI", 7, "bold"),
                padx=7,
                pady=2,
                cursor=("hand2" if enabled else ""),
            ).pack(side=tk.RIGHT, padx=(8, 0))

            body_lbl = tk.Label(
                card,
                text=route["body"],
                fg=(muted if enabled or selected else muted_dim),
                bg=card_bg,
                justify=tk.LEFT,
                anchor="w",
                wraplength=270,
                cursor=("hand2" if enabled else ""),
            )
            body_lbl.pack(fill=tk.X, pady=(6, 0))

            if enabled:
                command = lambda selected_target=route_target: self._choose_step1_iteration_target(selected_target)
                for widget in (card, header, body_lbl):
                    try:
                        widget.bind("<Button-1>", lambda _event, cmd=command: cmd(), add="+")
                    except Exception:
                        pass
                for child in header.winfo_children():
                    try:
                        child.bind("<Button-1>", lambda _event, cmd=command: cmd(), add="+")
                    except Exception:
                        pass

        if lock_reason:
            tk.Label(
                frame,
                text=lock_reason,
                fg=muted,
                bg=card_bg,
                justify=tk.LEFT,
                anchor="w",
                wraplength=620,
            ).pack(fill=tk.X, pady=(8, 0))

        HELP.bind_help(frame, "camp_step1")
        HELP.bind_help(route_row, "camp_step1")

    def _render_step3_rework_actions(self, frame):
        """Renderuje dodatkowe akcje naprawcze dla kroku 3."""
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
        source_state = self._get_char_route_source_state()
        guidance = self._get_char_repair_guidance(source_state)
        primary_label = str(guidance.get("primary_label") or "").strip()
        primary_command = guidance.get("primary_command")
        secondary_label = str(guidance.get("secondary_label") or "").strip()
        secondary_command = guidance.get("secondary_command")
        guidance_text = str(guidance.get("details") or "").strip()

        for w in frame.winfo_children():
            w.destroy()

        frame.configure(bg=card_bg)
        frame.pack(fill=tk.X, pady=(6, 0))

        tk.Label(
            frame,
            text="Dostępne ścieżki naprawcze:",
            fg=palette.get("warning", "#d35400"),
            bg=card_bg,
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 3))

        if guidance_text:
            tk.Label(
                frame,
                text=guidance_text,
                fg=palette.get("fg", "#f3f3f3"),
                bg=card_bg,
                justify=tk.LEFT,
                wraplength=820,
                font=("Segoe UI", 9),
            ).pack(anchor=tk.W, pady=(0, 6))

        btn_row = tk.Frame(frame, bg=card_bg)
        btn_row.pack(anchor=tk.W)

        btn_primary = None
        btn_secondary = None

        if primary_label and primary_command is not None:
            btn_primary = ttk.Button(
                btn_row,
                text=f"{primary_label} (STEP3-B1)",
                command=primary_command,
                style="Accent.TButton"
            )
            btn_primary.pack(side=tk.LEFT, padx=(0, 8))

        if secondary_label and secondary_command is not None:
            btn_secondary = ttk.Button(
                btn_row,
                text=f"{secondary_label} (STEP3-B2)",
                command=secondary_command
            )
            btn_secondary.pack(side=tk.LEFT)

        HELP.bind_help(frame, "camp_step3")
        HELP.bind_help(btn_row, "camp_step3")
        if btn_primary is not None:
            HELP.bind_help(btn_primary, "camp_step3")
        if btn_secondary is not None:
            HELP.bind_help(btn_secondary, "camp_step3")
        return

    # ======================================================
    # DASHBOARD REFRESH
    # ======================================================

    def _refresh_dashboard(self):
        refresh_started = perf_counter()
        try:
            if bool(getattr(self, "_project_loading_overlay_visible", False)):
                self._show_project_loading_overlay(
                    title="Ładuję projekt",
                    body="Odczytuję stan projektu i przygotowuję widok aktywnej iteracji.",
                    tone="info",
                    progress=52.0,
                )
        except Exception:
            pass
        self._clear_dashboard_perf_cache()
        try:
            self._collapse_all_wizard_stage_curtains()
        except Exception:
            pass

        self._refresh_projects_list()

        palette = getattr(self.app, "palette", {})
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        muted_dim = palette.get("muted_dim", "#9a9a9a")
        accent = palette.get("accent", "#2980b9")
        success = palette.get("success", "#27ae60")
        warning = palette.get("warning", "#d35400")
        surface_info = palette.get("surface_info", palette.get("panel_alt", "#252526"))
        surface_success = palette.get("surface_success", palette.get("panel_alt", "#1f3320"))
        surface_warning = palette.get("surface_warning", palette.get("panel_alt", "#3a2323"))
        header_bg = palette.get("panel", "#252526")

        active_proj = CAMPAIGN.get_active_project_name()
        has_project = bool(active_proj)
        projects_available = bool(CAMPAIGN.get_all_projects())

        # ======================================================
        # TRYB SWOBODNY / BRAK AKTYWNEGO PROJEKTU
        # ======================================================
        if not has_project:
            self.app.campaign_free_mode = True
            self.app.set_campaign_mode(False)
            self._wizard_focus_stage_request = ""
            self._cancel_pending_wizard_stage_focus()

            self._configure_campaign_banner(bg=header_bg)
            self._set_icon_button_enabled("exit_project", False)

            # Lewy panel wygaszony
            for mt in ["vehicle", "plate", "char"]:
                getattr(self, f"lbl_model_{mt}").config(text="Zablokowane", fg=muted_dim)
                lbl_meta = getattr(self, f"lbl_model_{mt}_meta", None)
                if lbl_meta is not None:
                    lbl_meta.config(text="Utworzono: -", fg=muted_dim)
                btn_model = getattr(self, f"btn_model_{mt}", None)
                if btn_model is not None:
                    btn_model.config(state="disabled")

            # Przyciski nagłówka
            self.btn_open_proj.config(state="normal" if projects_available else "disabled")
            self.btn_del_proj.config(state="normal" if projects_available else "disabled")
            self.btn_exit_project.config(state="disabled")

            # Awans nieaktywny
            self.btn_advance.config(text="Utwórz projekt ↗", state="disabled", style="TButton")
            self.btn_complete_project.config(text="Zakończ projekt", state="disabled", style="TButton")
            self._set_grid_visibility(self.left_footer, False)
            self._set_pack_visibility(self.btn_advance, False)
            self._set_pack_visibility(self.btn_complete_project, False)

            self.step1_panel_expanded = False
            self.current_ingest_plan = {}
            self._refresh_ingest_panel()
            self._refresh_wizard_empty_state(projects_available=projects_available)
            self.app.update_campaign_tab_access()
            self.frame.update_idletasks()
            self.frame.after_idle(self._sync_right_panel_scrollregion)
            self._log_perf("refresh_dashboard_free_mode", refresh_started, threshold_ms=20.0)
            return

        # ======================================================
        # TRYB AKTYWNEGO PROJEKTU
        # ======================================================
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)

        active_state = self._build_active_project_dashboard_state()
        try:
            if bool(getattr(self, "_project_loading_overlay_visible", False)):
                self._show_project_loading_overlay(
                    title="Ładuję projekt",
                    body="Buduję karty etapów i podsumowanie bieżącej iteracji.",
                    tone="info",
                    progress=78.0,
                )
        except Exception:
            pass
        curr_step = int(active_state.get("current_step", CAMPAIGN.get_current_step()) or CAMPAIGN.get_current_step() or 1)
        step1_status = str(active_state.get("step1_status", CAMPAIGN.get_step1_status()) or CAMPAIGN.get_step1_status() or "pending")
        step2_status = str(active_state.get("step2_status", CAMPAIGN.get_step2_status()) or CAMPAIGN.get_step2_status() or "pending")
        step3_status = str(active_state.get("step3_status", CAMPAIGN.get_step3_status()) or CAMPAIGN.get_step3_status() or "pending")
        iteration_target = str(active_state.get("iteration_target", self._get_iteration_target()) or self._get_iteration_target() or "").strip().lower()
        project_status = str(active_state.get("project_status", CAMPAIGN.get_project_status()) or CAMPAIGN.get_project_status() or "active").strip().lower()
        project_paused = project_status == "paused"
        project_completed = project_status == "completed"
        project_paused_at = str(active_state.get("project_paused_at", CAMPAIGN.get_project_paused_at()) or CAMPAIGN.get_project_paused_at() or "").strip()
        project_completed_at = str(active_state.get("project_completed_at", CAMPAIGN.get_project_completed_at()) or CAMPAIGN.get_project_completed_at() or "").strip()

        logger.debug(
            f"[CampaignTab] active_proj={active_proj}, curr_step={curr_step}, "
            f"step2_status={step2_status}, step3_status={step3_status}"
        )
        iter_num = CAMPAIGN.get_current_iteration_num()

        banner_bg = surface_success

        if project_completed:
            banner_bg = surface_warning
        elif project_paused:
            banner_bg = surface_info

        self._configure_campaign_banner(bg=banner_bg)
        self._set_icon_button_enabled("exit_project", True)

        self._refresh_ingest_panel()
        master_pool_path = CAMPAIGN.get_master_pool_dir()
        master_pool_ready = bool(master_pool_path and master_pool_path.exists() and master_pool_path.is_dir())
        plan_ready = bool(self.current_ingest_plan.get("selected_total", 0))
        if curr_step != 1:
            self.step1_panel_expanded = False

        # Przyciski nagłówka
        self.btn_open_proj.config(state="normal")
        self.btn_del_proj.config(state="normal")
        self.btn_exit_project.config(state="normal")

        # Status aktywnych modeli projektu pozostaje tylko informacyjny.
        for mt in ["vehicle", "plate", "char"]:
            btn_model = getattr(self, f"btn_model_{mt}", None)
            if btn_model is not None:
                btn_model.config(state="normal")

        def fmt_model(p):
            return Path(p).name if p and Path(p).exists() else "Domyślny/Brak"

        vehicle_model = CAMPAIGN.get_global_model("vehicle")
        plate_model = CAMPAIGN.get_global_model("plate")
        char_model = CAMPAIGN.get_global_model("char")

        self.lbl_model_vehicle.config(text=fmt_model(vehicle_model), fg=accent)
        self.lbl_model_plate.config(text=fmt_model(plate_model), fg=accent)
        self.lbl_model_char.config(text=fmt_model(char_model), fg=accent)

        self.lbl_model_vehicle_meta.config(text=self._format_model_meta_label(vehicle_model))
        self.lbl_model_plate_meta.config(text=self._format_model_meta_label(plate_model))
        self.lbl_model_char_meta.config(text=self._format_model_meta_label(char_model))

        self._set_grid_visibility(self.left_footer, True)
        # Globalny przycisk awansu został wycofany z głównego okna wizarda.
        # Jedynym miejscem do rozpoczęcia nowej iteracji zostaje panel E4.
        self._set_pack_visibility(self.btn_advance, False)
        self._set_pack_visibility(self.btn_complete_project, True, fill=tk.X, pady=(8, 0))

        # Awans iteracji
        if project_completed or project_paused:
            self.btn_advance.config(
                text=("Projekt zakończony" if project_completed else "Projekt odłożony"),
                state="disabled",
                style="TButton"
            )
            self.btn_complete_project.config(
                text="Wznów projekt",
                state="normal",
                style="Accent.TButton"
            )
        elif curr_step >= 5:
            self.btn_complete_project.config(
                text="Opuść projekt",
                state="normal",
                style="TButton"
            )
        else:
            self.btn_advance.config(
                text=f"Awans zablokowany (Krok {curr_step})",
                state="disabled",
                style="TButton"
            )
            self.btn_complete_project.config(
                text="Zakończenie dostępne po Z4",
                state="disabled",
                style="TButton"
            )

        self._refresh_wizard_active_dashboard(
            active_project=active_proj,
            current_step=curr_step,
            iteration_target=iteration_target,
            project_status=project_status,
            project_paused_at=project_paused_at,
            project_completed_at=project_completed_at,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
        )
        try:
            if bool(getattr(self, "_project_loading_overlay_visible", False)):
                self._show_project_loading_overlay(
                    title="Ładuję projekt",
                    body="Kończę odświeżanie i ustawiam docelowy widok projektu.",
                    tone="success",
                    progress=100.0,
                )
            self.frame.after(90, self._hide_project_loading_overlay)
        except Exception:
            pass
        self._update_main_tabs_highlight(curr_step=curr_step, has_project=True)
        self.app.update_campaign_tab_access()
        self.frame.update_idletasks()
        try:
            self._stabilize_wizard_stage_badges()
        except Exception as e:
            logger.debug(f"Nie udało się natychmiast ustabilizować badge'y wizarda po refresh_dashboard: {e}")
        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self._schedule_pending_wizard_stage_focus()
        self._log_perf(
            "refresh_dashboard_active",
            refresh_started,
            threshold_ms=20.0,
            extra=f"step={curr_step}, target={iteration_target or '-'}",
        )
        return

    def _update_main_tabs_highlight(self, curr_step=None, has_project=True):
        active_tab_key = None
        if has_project:
            step_to_tab = {
                1: "campaign",
                2: "annotation",
                3: "characters",
                4: "training",
            }
            active_tab_key = step_to_tab.get(curr_step, "campaign")

        try:
            self.app.refresh_main_tab_labels(active_tab_key=active_tab_key)
        except Exception:
            pass

    # ======================================================
    # PROJECT CRUD
    # ======================================================

    def _ensure_project_context_is_switchable(
        self,
        *,
        next_project: str = "",
        dialog_title: str = "Najpierw zakończ aktywną operację",
    ) -> bool:
        if bool(getattr(self, "_project_switch_in_progress", False)):
            try:
                self.app.update_status(
                    "Trwa już przełączanie projektu. Poczekaj na zakończenie poprzedniego ładowania.",
                    "info",
                )
            except Exception:
                pass
            return False

        active_before = str(CAMPAIGN.get_active_project_name() or "").strip()
        if not active_before:
            return True

        blocker_message = self._get_project_switch_blocker_message(
            current_project=active_before,
            next_project=str(next_project or "").strip(),
        )
        if not blocker_message:
            return True

        self.app.themed_info(
            dialog_title,
            blocker_message,
            parent=self.frame,
            tone="warning",
        )
        return False

    def _add_new_project(self):
        new_name = self.app.themed_ask_string(
            "Nowy projekt",
            "Podaj unikalną nazwę projektu.",
            parent=self.frame,
            action_label="Utwórz"
        )
        if not new_name:
            return

        if not self._ensure_project_context_is_switchable(
            next_project=str(new_name or "").strip(),
            dialog_title="Najpierw zakończ aktywny projekt",
        ):
            return

        active_before = str(CAMPAIGN.get_active_project_name() or "").strip()

        try:
            annotation_tab = self.app.tabs.get("annotation")
            if annotation_tab is not None and hasattr(annotation_tab, "capture_free_mode_snapshot_for_project_return"):
                annotation_tab.capture_free_mode_snapshot_for_project_return()
        except Exception as e:
            logger.debug(f"Nie udało się zapisać migawki free mode przed utworzeniem projektu: {e}")

        self._project_switch_in_progress = True
        try:
            if active_before:
                try:
                    self._release_active_project_resources_before_switch(active_before)
                except Exception as e:
                    logger.debug(f"Nie udało się zwolnić zasobów projektu '{active_before}' przed utworzeniem nowego: {e}")

            if CAMPAIGN.create_project(new_name):
                self.app.campaign_free_mode = False
                self.app.set_campaign_mode(True)
                try:
                    CAMPAIGN.set_project_start_mode("fresh")
                except Exception:
                    pass
                self._rebuild_wizard_stage_ui()
                self._refresh_dashboard()
                self.app.update_campaign_tab_access()
                self.app.themed_info(
                    "Projekt utworzony",
                    (
                        f"Projekt '{new_name}' został utworzony.\n\n"
                        "W lewym dolnym rogu aplikacji znajduje się globalny asystent AS. "
                        "Po kliknięciu ikony AS możesz rozwinąć krótkie podpowiedzi dotyczące aktualnej zakładki, "
                        "etapu i celu pracy."
                    ),
                    parent=self.frame,
                    tone="success",
                )
            else:
                self.app.themed_error(
                    "Błąd",
                    "Projekt o takiej nazwie już istnieje lub nazwa jest nieprawidłowa.",
                    parent=self.frame
                )
        finally:
            self._project_switch_in_progress = False

    def _get_selected_projects_from_list(self) -> list[str]:
        if self.project_listbox is None:
            return []

        try:
            selected = []
            for raw_idx in self.project_listbox.curselection():
                idx = int(raw_idx)
                if 0 <= idx < len(self._project_name_by_index):
                    project_name = str(self._project_name_by_index[idx]).strip()
                    if project_name and project_name not in selected:
                        selected.append(project_name)
            return selected
        except Exception:
            return []

    def _get_selected_project_from_list(self) -> str:
        selected = self._get_selected_projects_from_list()
        return selected[0] if selected else ""

    def _select_project_in_list(self, project_name: str):
        if self.project_listbox is None or not project_name:
            return

        try:
            idx = self._project_name_by_index.index(project_name)
            self.project_listbox.selection_clear(0, tk.END)
            self.project_listbox.selection_set(idx)
            self.project_listbox.activate(idx)
            self.project_listbox.see(idx)
            self.project_listbox.focus_set()
        except Exception:
            pass

    def _show_project_context_menu(self, event):
        if self.project_listbox is None or not getattr(self, "project_context_menu", None):
            return "break"

        try:
            idx = int(self.project_listbox.nearest(event.y))
        except Exception:
            return "break"

        if idx < 0 or idx >= len(getattr(self, "_project_name_by_index", [])):
            return "break"

        try:
            selected_now = set(int(value) for value in self.project_listbox.curselection())
            if idx not in selected_now:
                self.project_listbox.selection_clear(0, tk.END)
                self.project_listbox.selection_set(idx)
            self.project_listbox.activate(idx)
            self.project_listbox.see(idx)
            self.project_listbox.focus_set()
            self._on_project_changed()
            selected_projects = self._get_selected_projects_from_list()
            try:
                self.project_context_menu.entryconfig(
                    0,
                    label="Otwórz projekt" if len(selected_projects) <= 1 else "Otwórz pierwszy projekt"
                )
                self.project_context_menu.entryconfig(
                    2,
                    label="Usuń zaznaczony projekt" if len(selected_projects) <= 1 else "Usuń zaznaczone projekty"
                )
            except Exception:
                pass
            self.project_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.project_context_menu.grab_release()
            except Exception:
                pass
        return "break"

    def _set_project_list_status(self, selected: str = "", project_count: int = 0):
        if self.project_list_status_lbl is None:
            return

        def compact(value: str, width: int = 54) -> str:
            text = str(value or "").replace("\n", " ").strip()
            if not text:
                return ""
            return shorten(text, width=width, placeholder="...")

        def apply_lines(*lines: str):
            labels = list(getattr(self, "project_list_status_labels", []))
            if not labels:
                return
            normalized = [compact(line) for line in lines[:3]]
            while len(normalized) < len(labels):
                normalized.append("")
            for lbl, line in zip(labels, normalized):
                lbl.config(text=line)

        selected_projects = self._get_selected_projects_from_list()
        if len(selected_projects) > 1:
            apply_lines(
                f"Zaznaczone projekty: {len(selected_projects)}",
                f"Pierwszy na liście: {selected_projects[0]}",
                "Dwuklik otwiera pierwszy projekt. PPM usuwa całe zaznaczenie."
            )
            return

        if not selected:
            if project_count > 0:
                apply_lines(
                    f"Zapisane projekty: {project_count}",
                    "Wybierz projekt z listy.",
                    "Dwuklik otwiera zaznaczony projekt."
                )
            else:
                apply_lines(
                    "Brak zapisanych projektów.",
                    "Utwórz pierwszy projekt.",
                    "Lista pojawi się po dodaniu projektu."
                )
            return

        created_at = ""
        try:
            created_raw = CAMPAIGN.get_project_created_at(selected)
            if created_raw:
                formatter = getattr(self.app, "_format_project_created_at", None)
                created_at = formatter(created_raw) if callable(formatter) else str(created_raw).replace("T", " ")
        except Exception:
            created_at = ""

        created_line = f"Utworzono: {created_at}" if created_at else "Utworzono: brak danych"

        if selected == CAMPAIGN.get_active_project_name():
            action_line = "Projekt jest już aktywny."
        else:
            action_line = "Dwuklik otwiera zaznaczony projekt."

        apply_lines(
            f"Projekt: {selected}",
            created_line,
            action_line
        )

    def _refresh_projects_list(self):
        if self.project_listbox is None:
            return

        projects = CAMPAIGN.get_all_projects()
        active_project = CAMPAIGN.get_active_project_name()
        previous_selection = self._get_selected_project_from_list()

        self._project_list_refreshing = True
        try:
            self.project_listbox.delete(0, tk.END)
            self._project_name_by_index = []

            if not projects:
                self._set_project_list_status("", 0)
                self.project_listbox.insert(tk.END, "(brak zapisanych projektów)")
                self.project_listbox.itemconfig(0, foreground="#888888")
                self.frame.after_idle(self._sync_left_panel_scrollregion)
                return

            for project_name in projects:
                display_name = f"* {project_name}" if project_name == active_project else project_name
                self.project_listbox.insert(tk.END, display_name)
                idx = len(self._project_name_by_index)
                self._project_name_by_index.append(project_name)
                if project_name == active_project:
                    self.project_listbox.itemconfig(idx, foreground="#27ae60")

            target_name = active_project or previous_selection or projects[0]
            self._select_project_in_list(target_name)
        finally:
            self._project_list_refreshing = False

        self._set_project_list_status(self._get_selected_project_from_list(), len(projects))
        self.frame.after_idle(self._sync_left_panel_scrollregion)

    def _on_project_changed(self, event=None):
        if self._project_list_refreshing:
            return

        selected_projects = self._get_selected_projects_from_list()
        if not selected_projects or self.project_list_status_lbl is None:
            return

        try:
            self._set_project_list_status(selected_projects[0], len(self._project_name_by_index))
            self.frame.after_idle(self._sync_left_panel_scrollregion)
        except Exception:
            pass

    def _open_selected_project(self):
        selected_projects = self._get_selected_projects_from_list()
        selected = selected_projects[0] if selected_projects else ""
        if not selected:
            selected = self._ask_project_from_list(
                title="Otwórz projekt",
                action_label="Otwórz"
            )
        if not selected:
            return

        if not self._ensure_project_context_is_switchable(
            next_project=str(selected or "").strip(),
            dialog_title="Najpierw zakończ aktywną operację",
        ):
            return

        active_before = str(CAMPAIGN.get_active_project_name() or "").strip()

        open_started = perf_counter()

        try:
            annotation_tab = self.app.tabs.get("annotation")
            if annotation_tab is not None and hasattr(annotation_tab, "capture_free_mode_snapshot_for_project_return"):
                annotation_tab.capture_free_mode_snapshot_for_project_return()
        except Exception as e:
            logger.debug(f"Nie udało się zapisać migawki free mode przed otwarciem projektu: {e}")

        self._project_switch_in_progress = True
        self._cancel_deferred_project_open_tasks()
        if active_before and active_before != str(selected or "").strip():
            try:
                self._release_active_project_resources_before_switch(active_before)
            except Exception as e:
                logger.debug(f"Nie udało się zwolnić zasobów projektu '{active_before}' przed przełączeniem: {e}")
        CAMPAIGN.set_active_project(selected)
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)
        self._clear_dashboard_perf_cache()
        self._ensure_wizard_stage_ui_ready()
        try:
            self._hide_project_loading_overlay()
        except Exception:
            pass
        self.app.update_campaign_tab_access()

        def _finish_project_open_refresh():
            self._project_open_refresh_after_id = None
            try:
                if str(CAMPAIGN.get_active_project_name() or "").strip() != str(selected or "").strip():
                    return
                try:
                    self._refresh_dashboard()
                except Exception as e:
                    logger.debug(f"Nie udało się odświeżyć dashboardu po otwarciu projektu: {e}")
                try:
                    self._schedule_project_open_post_refresh(str(selected or "").strip())
                except Exception as e:
                    logger.debug(f"Nie udało się zaplanować drugiego odświeżenia po otwarciu projektu: {e}")
                self._log_perf(
                    "open_selected_project_refresh",
                    open_started,
                    threshold_ms=20.0,
                    extra=f"project={selected}",
                )
            finally:
                self._project_switch_in_progress = False

        try:
            self._project_open_refresh_after_id = self.frame.after(15, _finish_project_open_refresh)
        except Exception:
            try:
                _finish_project_open_refresh()
            finally:
                self._project_switch_in_progress = False

        try:
            self.app.update_status(
                f"Aktywowano projekt: {selected}. Trwa ładowanie kontekstu kampanii.",
                "info"
            )
        except Exception:
            pass

    def _schedule_project_open_post_refresh(self, expected_project: str) -> None:
        try:
            pending = getattr(self, "_project_open_post_refresh_after_id", None)
            if pending:
                self.frame.after_cancel(pending)
        except Exception:
            pass

        def _run():
            self._project_open_post_refresh_after_id = None
            if str(CAMPAIGN.get_active_project_name() or "").strip() != str(expected_project or "").strip():
                return
            try:
                self._refresh_active_project_wizard_only()
            except Exception as e:
                logger.debug(f"Nie udało się wykonać drugiego odświeżenia wizarda po otwarciu projektu: {e}")
            try:
                self._stabilize_wizard_stage_badges()
            except Exception as e:
                logger.debug(f"Nie udało się ustabilizować badge'y po otwarciu projektu: {e}")

            def _late_badge_stabilize() -> None:
                if str(CAMPAIGN.get_active_project_name() or "").strip() != str(expected_project or "").strip():
                    return
                try:
                    self._stabilize_wizard_stage_badges()
                except Exception as exc:
                    logger.debug(f"Nie udało się wykonać późnej stabilizacji badge'y wizarda: {exc}")

            try:
                self.frame.after(420, _late_badge_stabilize)
            except Exception:
                pass

        try:
            self._project_open_post_refresh_after_id = self.frame.after(90, _run)
        except Exception:
            self._project_open_post_refresh_after_id = None

    def _get_project_switch_blocker_message(self, *, current_project: str = "", next_project: str = "") -> str:
        issues: list[str] = []

        try:
            annotation_tab = self.app.tabs.get("annotation")
        except Exception:
            annotation_tab = None
        if annotation_tab is not None:
            if bool(getattr(annotation_tab, "is_processing", False)):
                issues.append("Z2 nadal wykonuje operację autoanotacji albo przygotowania runu.")
            elif bool(getattr(annotation_tab, "_campaign_project_restore_in_progress", False)):
                issues.append("Z2 nadal odtwarza kontekst projektu.")
            elif bool(getattr(annotation_tab, "_campaign_deferred_run_restore_in_progress", False)):
                issues.append("Z2 nadal doczytuje run kampanii.")
            elif bool(getattr(annotation_tab, "_campaign_step2_transition_in_progress", False)):
                issues.append("Z2 nadal kończy przejście kampanijne.")

        try:
            char_tab = self.app.tabs.get("characters")
        except Exception:
            char_tab = None
        if char_tab is not None:
            if bool(getattr(char_tab, "is_processing", False)):
                issues.append("Z3 nadal wykonuje operację znaków.")
            elif bool(getattr(char_tab, "fast_test_running", False)):
                issues.append("Z3 nadal wykonuje szybki test OCR.")

        try:
            train_tab = self.app.tabs.get("training")
        except Exception:
            train_tab = None
        if train_tab is not None:
            try:
                if bool(train_tab._step4_has_active_operation()):
                    op_label = str(train_tab._get_active_step4_operation_label() or "operacja Z4").strip()
                    issues.append(f"Z4 nadal wykonuje: {op_label}.")
            except Exception:
                if bool(getattr(train_tab, "is_processing", False)):
                    issues.append("Z4 nadal wykonuje operację treningową.")

        if not issues:
            return ""

        current_label = str(current_project or "bieżący projekt").strip()
        next_label = str(next_project or "nowy projekt").strip()
        intro = (
            f"Nie mogę jeszcze przełączyć projektu z '{current_label}' na '{next_label}', "
            "bo poprzedni projekt nadal ma aktywne zadania:"
        )
        return intro + "\n\n- " + "\n- ".join(issues) + "\n\nZatrzymaj albo dokończ te działania i spróbuj ponownie."

    def _release_active_project_resources_before_switch(self, current_project: str = "") -> None:
        current_label = str(current_project or "").strip()
        if current_label:
            logger.debug(f"Zwalniam zasoby aktywnego projektu przed przełączeniem: {current_label}")

        try:
            self._hide_project_loading_overlay()
        except Exception:
            pass

        self._clear_project_contexts()

        try:
            self.frame.update_idletasks()
        except Exception:
            pass

    def _delete_project(self):
        selected_projects = self._get_selected_projects_from_list()
        if not selected_projects:
            selected = self._ask_project_from_list(
                title="Usuń projekt",
                action_label="Usuń"
            )
            selected_projects = [selected] if selected else []
        if not selected_projects:
            return

        if len(selected_projects) == 1:
            confirm_title = "Usuwanie projektu"
            confirm_message = (
                f"Usunąć projekt '{selected_projects[0]}' wraz z całym katalogiem projektu?"
            )
        else:
            confirm_title = "Usuwanie projektów"
            preview = ", ".join(selected_projects[:4])
            if len(selected_projects) > 4:
                preview += f" +{len(selected_projects) - 4} więcej"
            confirm_message = (
                f"Usunąć {len(selected_projects)} zaznaczone projekty wraz z ich katalogami?\n\n"
                f"{preview}"
            )

        if self.app.themed_confirm(
            confirm_title,
            confirm_message,
            parent=self.frame,
            confirm_label="Usuń",
            tone="warning"
        ):
            active_project = CAMPAIGN.get_active_project_name()
            if active_project and active_project in selected_projects:
                if not self._ensure_project_context_is_switchable(
                    next_project="usunięcia aktywnego projektu",
                    dialog_title="Najpierw zakończ aktywną operację",
                ):
                    return
            removed = []
            for project_name in selected_projects:
                if CAMPAIGN.delete_project(project_name):
                    removed.append(project_name)

            if not removed:
                return

            if active_project in removed:
                self._clear_project_contexts()
                self.app.campaign_free_mode = True
                self.app.set_campaign_mode(False)

            self._rebuild_wizard_stage_ui()
            self._refresh_dashboard()
            self.app.update_campaign_tab_access()

            if len(removed) == 1:
                message = f"Projekt '{removed[0]}' został usunięty."
            else:
                message = f"Usunięto {len(removed)} projektów."
            self.app.themed_info(
                "Usunięto",
                message,
                parent=self.frame,
                tone="success"
            )

    def _clear_project_contexts(self):
        try:
            self._hide_project_loading_overlay()
        except Exception:
            pass
        tab_labels = {
            "annotation": "Autoanotacji",
            "characters": "Zakładki Znaków",
            "training": "Treningu",
        }

        for tab_key, label in tab_labels.items():
            try:
                if tab_key in self.app.tabs:
                    self.app.tabs[tab_key].clear_campaign_context()
            except Exception as e:
                logger.debug(f"Nie udało się wyczyścić kontekstu {label}: {e}")

    def _exit_project_mode(self):
        active = CAMPAIGN.get_active_project_name()
        if not active:
            return

        if not self._ensure_project_context_is_switchable(
            next_project="trybu swobodnego",
            dialog_title="Najpierw zakończ aktywną operację",
        ):
            return

        if self.app.themed_confirm(
            "Wyjście z projektu",
            f"Czy na pewno chcesz opuścić projekt '{active}' i przejść do trybu swobodnego?\n\n"
            "Projekt nie zostanie usunięty.",
            parent=self.frame,
            confirm_label="Wyjdź",
            tone="warning"
        ):

            # użytkownik ręcznie wymusza tryb swobodny
            self.app.campaign_free_mode = True

            # czyścimy aktywny projekt
            CAMPAIGN.clear_active_project()

            # wyłączamy tryb kampanii
            self.app.set_campaign_mode(False)

            # odświeżamy dashboard
            self._rebuild_wizard_stage_ui()
            self._refresh_dashboard()

            # finalna synchronizacja dostępności zakładek
            self.app.update_campaign_tab_access()

            try:
                self.app.open_controlled_tab("campaign")
                self.app.root.update_idletasks()
            except Exception as e:
                logger.debug(f"Nie udało się przełączyć na główne okno po wyjściu z projektu: {e}")

            # czyścimy projektowy kontekst innych zakładek dopiero po przejściu do Z1,
            # żeby użytkownik nie widział chwilowego odtwarzania kafli workflow Z2.
            self._clear_project_contexts()

            try:
                self.app.update_status(
                    "Opuściłeś aktywny projekt. Aplikacja działa teraz w trybie swobodnym.",
                    "info"
                )
            except Exception:
                pass
    # ======================================================
    # STEPS
    # ======================================================

    def _step_create_raw_folder(self):
        if not CAMPAIGN.get_active_project_name():
            return

        if not self._choose_master_pool_dir():
            return
        try:
            self._refresh_ingest_panel()
            self._refresh_active_project_wizard_only()
        except Exception:
            try:
                self._refresh_dashboard()
            except Exception:
                pass

    def _step_open_z2_from_step2_review(self):
        self._step_return_to_annotation_review(mark_step3_rework=False)

    def _step_open_z2_repair_from_later_stage(self):
        self._step_return_to_annotation_review(mark_step3_rework=True)

    def _step_return_to_annotation_review(self, mark_step3_rework: bool = True):
        try:
            self.app.update_status(
                "Otwieram sprawdzanie tablic (Z2).",
                "info",
            )
        except Exception:
            pass

        iteration_target = self._get_iteration_target()
        if iteration_target in {"plate", "char"}:
            try:
                if iteration_target == "char" and bool(mark_step3_rework) and CAMPAIGN.get_active_project_name():
                    CAMPAIGN.set_current_step(3)
                    CAMPAIGN.set_step3_needs_rework()
            except Exception as e:
                logger.debug(f"Nie udało się ustawić trybu naprawczego E3 przed powrotem do Z2: {e}")
            if iteration_target == "char":
                def _open_char_annotation_return():
                    try:
                        self._step_goto_auto_annotation(
                            force_annotation_tab=True,
                            open_existing_run=True,
                        )
                    except Exception as e:
                        logger.error(f"Nie udało się otworzyc kampanijnego Z2 z odroczonym startem: {e}")

                try:
                    self.app.update_status(
                        "Przygotowuję kontekst naprawczy Z2 dla tego katalogu zdjęć.",
                        "info",
                    )
                except Exception:
                    pass
                try:
                    self.frame.after_idle(_open_char_annotation_return)
                except Exception:
                    _open_char_annotation_return()
                return
            try:
                self._step_goto_auto_annotation(
                    force_annotation_tab=True,
                    open_existing_run=True,
                )
                return
            except Exception as e:
                logger.error(f"Nie udało się otworzyc kampanijnego Z2 z kontekstem: {e}")

        def _open_annotation_tab():
            try:
                annotation_tab = self.app.tabs.get("annotation")
                if annotation_tab is None:
                    return
                tab_widget = str(annotation_tab.frame)
                self.app.notebook.tab(tab_widget, state="normal")
                self.app.notebook.select(tab_widget)
            except Exception as e:
                logger.error(f"Nie udało się przelaczyc na Z2: {e}")

        try:
            self.frame.after_idle(_open_annotation_tab)
        except Exception:
            _open_annotation_tab()

    def _step_goto_auto_annotation(
        self,
        force_annotation_tab: bool = False,
        entry_strategy: str | None = None,
        open_existing_run: bool = True,
    ):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 2:
            return
        if str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved":
            try:
                self.step1_panel_expanded = True
                self.request_wizard_stage_focus(step_num=1)
                self._refresh_active_project_wizard_only()
            except Exception:
                pass
            try:
                self.app.update_status(
                    "Najpierw zatwierdź E1: wskaż katalog zdjęć i wybierz tor iteracji. Dopiero wtedy STEP2-P1 będzie aktywne.",
                    "warning",
                )
            except Exception:
                pass
            return

        iteration_target = self._get_iteration_target()
        if iteration_target not in {"plate", "char"}:
            try:
                self.app.update_status(
                    "Najpierw wybierz w E1 tor iteracji: tablice albo znaki.",
                    "warning"
                )
            except Exception:
                pass
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_out = CAMPAIGN.get_staging_dir("auto_ann")
        if auto_out is not None:
            Path(auto_out).mkdir(parents=True, exist_ok=True)

        if raw_dir is None or auto_out is None:
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        try:
            input_dir = CAMPAIGN.get_iteration_image_source_dir(iter_num) or Path(raw_dir)
        except Exception:
            folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
            input_dir = folder if folder.exists() else raw_dir
        v_mod = CAMPAIGN.get_global_model("vehicle")
        p_mod = CAMPAIGN.get_global_model("plate")
        plate_source_state = self._get_annotation_step2_source_state("plate")
        plate_model_ready = bool(plate_source_state.get("plate_model_ready"))
        if plate_model_ready and (not p_mod or not Path(p_mod).exists()):
            try:
                p_mod = str((plate_source_state.get("bootstrap") or {}).get("plate_model_path") or p_mod or "").strip()
            except Exception:
                p_mod = str(p_mod or "").strip()
        char_source_state = {}
        char_has_existing_source = False
        if iteration_target == "char":
            char_source_state = self._get_char_route_source_state()
            char_has_existing_source = bool(char_source_state.get("has_source"))

        if iteration_target == "char" and not force_annotation_tab:
            ready_source = self._get_char_route_ready_source()
            if ready_source:
                self._step_continue_characters_from_ready_source(ready_source)
                return

        tab_ann = self.app.tabs.get("annotation")
        if not tab_ann:
            return

        defer_preview_load = bool(force_annotation_tab or iteration_target == "plate")
        splash_token = 0

        try:
            self.app.campaign_free_mode = False
            self.app.set_campaign_mode(True)
        except Exception:
            pass

        def _finish_open() -> None:
            try:
                result = tab_ann.open_campaign_step2_entry(
                    iteration_target=iteration_target,
                    entry_strategy=entry_strategy,
                    restore_preview=bool(not force_annotation_tab and not char_has_existing_source),
                    open_existing_run=open_existing_run,
                    defer_preview_load=defer_preview_load,
                )
            except Exception as e:
                logger.error(f"Nie udało się otworzyc punktu startowego Z2: {e}")
                try:
                    tab_ann._hide_campaign_step2_splash(token=splash_token)
                except Exception:
                    pass
                return

            if not result.get("ok"):
                try:
                    tab_ann._hide_campaign_step2_splash(token=splash_token)
                except Exception:
                    pass
                try:
                    reason = str(result.get("reason") or "nieznany powód").strip()
                    self.app.update_status(
                        f"Nie udało się otworzyć Z2 z STEP2-P1: {reason}.",
                        "warning",
                    )
                except Exception:
                    pass
                return

            try:
                tab_ann.frame.update_idletasks()
            except Exception:
                pass

            try:
                self.app.open_controlled_tab("annotation")
                try:
                    self.app.root.update_idletasks()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Nie udało się przelaczyc na Z2 po przygotowaniu wejscia: {e}")
                return

            try:
                input_dir_local = Path(result.get("input_dir") or ".")
                auto_out_local = Path(result.get("auto_out") or ".")
            except Exception:
                input_dir_local = Path(".")
                auto_out_local = Path(".")
            manual_template = bool(result.get("manual_template"))
            plate_bootstrap_model = str(result.get("plate_model_path") or "").strip()
            input_source = str(result.get("input_source") or "raw").strip()
            opened_existing_run = bool(result.get("opened_existing_run"))

            try:
                if iteration_target == "plate":
                    if opened_existing_run:
                        run_name = ""
                        try:
                            run_name = Path(result.get("restore_run_dir") or "").name
                        except Exception:
                            run_name = ""
                        self.app.update_status(
                            (
                                f"Otworzono Z2 bezposrednio w korekcie runu {run_name}."
                                if run_name
                                else "Otworzono Z2 bezposrednio w aktywnej korekcie wykrytego runu."
                            ),
                            "info"
                        )
                        try:
                            if not bool(result.get("deferred_existing_run_restore")):
                                tab_ann._hide_campaign_step2_splash(token=splash_token)
                        except Exception:
                            pass
                        return
                    extra_hint = ""
                    if not manual_template and plate_bootstrap_model:
                        extra_hint += " Aktywny model tablic projektu został podstawiony automatycznie."
                    if input_source == "stage_previous_iteration":
                        extra_hint += " Jako wejście ustawiono stage z poprzedniej iteracji."
                    elif input_source == "manual_source_run":
                        extra_hint += " Przywrócono ostatnie ręczne anotacje tablic dla tego zestawu zdjęć."
                    elif input_source == "reused_manual_source_run":
                        extra_hint += " Przywrócono ręczne anotacje z poprzedniej iteracji dla tego samego katalogu zdjęć."
                    elif input_source == "latest_approved_run":
                        extra_hint += " Przywrócono też ostatni zatwierdzony run anotacji tablic projektu."
                    elif input_source == "reused_training_source_run":
                        extra_hint += " Przywrócono ręczne anotacje z runu anotacji Z2, który zasilił trening w poprzedniej iteracji."
                    elif input_source == "reused_iteration_run":
                        extra_hint += " Przywrócono zatwierdzony run anotacji Z2 z poprzedniej iteracji dla tego samego katalogu zdjęć."
                    if input_source == "project_imported_manual_source":
                        extra_hint += " Wykorzystano run tablic podpiety na starcie projektu."
                    elif input_source == "project_imported_images":
                        extra_hint += " Jako wejście ustawiono obrazy wskazane przy starcie projektu."
                    self.app.update_status(
                        f"Auto-ustawiono Z2 dla toru tablic: IN={Path(input_dir_local).name} | OUT={Path(auto_out_local).name}. "
                        + (
                            "Tryb ręczny utworzy annotations.xml, a nowe polygony zapisza się z etykieta 'plate'."
                            if manual_template
                            else "Możesz uruchomic autoanotacje tablic aktywnym modelem projektu i ręcznie poprawiać wynik."
                        )
                        + extra_hint,
                        "info"
                    )
                else:
                    if opened_existing_run:
                        run_name = ""
                        try:
                            run_name = Path(result.get("restore_run_dir") or "").name
                        except Exception:
                            run_name = ""
                        self.app.update_status(
                            (
                                f"Otworzono Z2 bezposrednio w korekcie runu {run_name} dla toru znaków."
                                if run_name
                                else "Otworzono Z2 bezposrednio w korekcie istniejących tablic dla toru znaków."
                            ),
                            "info"
                        )
                    else:
                        if manual_template:
                            message = (
                                f"Auto-ustawiono Z2 dla toru znaków: IN={Path(input_dir_local).name} | OUT={Path(auto_out_local).name}. "
                                "Projekt nie ma jeszcze modelu tablic, więc startujesz ręcznie: utwórz XML, oznacz tablice i zatwierdź poprawne zdjęcia."
                            )
                        elif plate_bootstrap_model:
                            message = (
                                f"Auto-ustawiono Z2 dla toru znaków: IN={Path(input_dir_local).name} | OUT={Path(auto_out_local).name}. "
                                "Model tablic aktywnego projektu został podstawiony automatycznie. Przygotuj tablice w Z2, a po zatwierdzeniu przejdziesz do Z3."
                            )
                        else:
                            message = (
                                f"Auto-ustawiono Z2 dla toru znaków: IN={Path(input_dir_local).name} | OUT={Path(auto_out_local).name}. "
                                "Przygotuj źródło tablic w Z2 ręcznie albo wskaż model dopiero przy starcie autoanotacji."
                            )
                        self.app.update_status(message, "info")
            except Exception:
                pass
            if bool(result.get("deferred_existing_run_restore")):
                try:
                    tab_ann._schedule_deferred_campaign_run_restore(
                        Path(str(result.get("restore_run_dir") or "").strip()),
                        status_message="Otworzono Z2. Wczytuję aktywny run i listę obrazów tego katalogu...",
                        splash_token=splash_token,
                    )
                except Exception as e:
                    logger.debug(f"Nie udało się odroczyć przywrócenia runu Z2 po otwarciu zakładki: {e}")
                    try:
                        tab_ann._hide_campaign_step2_splash(token=splash_token)
                    except Exception:
                        pass
            if bool(result.get("deferred_preview_load")):
                try:
                    deferred_input_dir = Path(str(result.get("deferred_preview_input_dir") or "").strip())
                except Exception:
                    deferred_input_dir = None
                if deferred_input_dir is not None:
                    try:
                        tab_ann._schedule_deferred_campaign_source_preview_load(
                            deferred_input_dir,
                            status_message="Otworzono Z2. Wczytuje liste obrazow tego katalogu...",
                            splash_token=splash_token,
                        )
                    except Exception as e:
                        logger.debug(f"Nie udało się odroczyć wczytania obrazów Z2 po otwarciu zakładki: {e}")
                        try:
                            tab_ann._hide_campaign_step2_splash(token=splash_token)
                        except Exception:
                            pass
                else:
                    try:
                        if not bool(result.get("deferred_existing_run_restore")):
                            pass
                    except Exception:
                        pass
            elif not bool(result.get("deferred_existing_run_restore")):
                try:
                    pass
                except Exception:
                    pass

        try:
            self.frame.after(25, _finish_open)
        except Exception:
            _finish_open()

    def _return_to_step1_for_char_source_rework(self, *, clear_target: bool = False) -> None:
        try:
            CAMPAIGN.reset_step3()
            CAMPAIGN.reset_step2()
            CAMPAIGN.reset_step1()
            CAMPAIGN.set_current_step(1)
            if clear_target:
                CAMPAIGN.set_iteration_target("")
        except Exception as e:
            logger.debug(f"Nie udało się cofnąć kampanii do E1 po braku minimum tablic: {e}")

        self.current_ingest_plan = {}
        self.step1_panel_expanded = True
        try:
            self.request_wizard_stage_focus(step_num=1)
        except Exception:
            pass
        try:
            self._refresh_dashboard()
        except Exception:
            pass
        try:
            self.app.open_controlled_tab("campaign")
        except Exception:
            pass
        try:
            if clear_target:
                self.app.update_status(
                    "Wrócono do E1. Wybierz tor iteracji i katalog zdjęć przed ponownym zatwierdzeniem.",
                    "warning",
                )
            else:
                self.app.update_status(
                    "Wrócono do E1. Wybierz większy katalog zdjęć albo ponownie zatwierdź E1 po uzupełnieniu źródła.",
                    "warning",
                )
        except Exception:
            pass

    def _show_step2_char_minimum_not_met_dialog(
        self,
        *,
        source_images: int,
        source_plates: int,
        min_plates: int,
        run_name: str = "",
    ) -> str:
        source_images = max(0, int(source_images or 0))
        source_plates = max(0, int(source_plates or 0))
        min_plates = max(1, int(min_plates or self.STEP3_CHAR_MIN_PLATES))
        missing_plates = max(0, min_plates - source_plates)
        run_line = f"Źródło: {run_name}\n" if str(run_name or "").strip() else ""
        message = (
            f"{run_line}"
            "E2 nie ma jeszcze minimum do przejścia w tor znaków.\n\n"
            f"Zatwierdzone obrazy z tablicami: {source_images}\n"
            f"Gotowe tablice: {source_plates}\n"
            f"Minimum dla E3: {min_plates} tablic\n"
            f"Brakuje: {missing_plates} tablic\n\n"
            "Możesz dalej oznaczać tablice w Z2, wrócić do E1 po większy katalog zdjęć "
            "albo wrócić do E1 i zmienić tor iteracji."
        )
        buttons = ["Zmień tor", "Wróć do E1", "Oznacz dalej w Z2"]
        try:
            choice = self.app.themed_message_dialog(
                "Za mało tablic dla toru znaków",
                message,
                parent=self.frame,
                buttons=buttons,
                default_button="Oznacz dalej w Z2",
                tone="warning",
                wraplength=560,
            )
        except Exception:
            try:
                messagebox.showwarning("Za mało tablic dla toru znaków", message, parent=self.frame)
            except Exception:
                pass
            choice = "Oznacz dalej w Z2"
        return str(choice or "Oznacz dalej w Z2").strip()

    def _finish_step2_char_and_focus_step3(
        self,
        preferred_source_context: dict | None = None,
    ) -> bool:
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 2:
            return False

        source_state = self._get_char_route_source_state()
        if source_state.get("needs_more_tables"):
            source_images = int(source_state.get("images_with_plates", 0) or 0)
            source_plates = int(source_state.get("total_plates", 0) or 0)
            min_plates = int(getattr(self, "STEP3_CHAR_MIN_PLATES", 10) or 10)
            missing_plates = max(0, min_plates - source_plates)
            run_name = str(source_state.get("run_name", "") or "").strip()
            try:
                self.app.update_status(
                    (
                        f"Run {run_name}: zatwierdzonych obrazów {source_images}, zapisanych tablic {source_plates}. "
                        f"Minimum do wejścia do znaków: {min_plates} tablic; brakuje {missing_plates}. "
                        "Najpierw przygotuj więcej tablic w Z2, a dopiero potem przejdź do znaków."
                    )
                    if run_name
                    else (
                        f"Zatwierdzonych obrazów: {source_images}. Zapisanych tablic: {source_plates}. "
                        f"Minimum do wejścia do znaków: {min_plates} tablic; brakuje {missing_plates}. "
                        "Najpierw przygotuj więcej tablic w Z2, a dopiero potem przejdź do znaków."
                    ),
                    "warning",
                )
            except Exception:
                pass
            choice = self._show_step2_char_minimum_not_met_dialog(
                source_images=source_images,
                source_plates=source_plates,
                min_plates=min_plates,
                run_name=run_name,
            )
            if choice == "Wróć do E1":
                self._return_to_step1_for_char_source_rework(clear_target=False)
            elif choice == "Zmień tor":
                self._return_to_step1_for_char_source_rework(clear_target=True)
            else:
                self._step_return_to_annotation_review(mark_step3_rework=False)
            return False

        source_context = preferred_source_context if isinstance(preferred_source_context, dict) else {}
        if not source_context:
            source_context = self._get_char_route_ready_source()
        if not source_context:
            try:
                self.app.update_status(
                    "Nie znaleziono gotowych tablic dla tego katalogu zdjęć. Najpierw przygotuj tablice, potem przejdź do pracy nad znakami.",
                    "warning",
                )
            except Exception:
                pass
            return False

        ready_run_dir = source_context.get("restore_run_dir")
        ready_run_name = str(
            source_context.get("display_name")
            or source_context.get("run_name")
            or ""
        ).strip()
        try:
            if not ready_run_name and ready_run_dir is not None:
                ready_run_name = Path(ready_run_dir).name
        except Exception:
            ready_run_name = ""

        try:
            self._suppress_stale_char_iteration_reset_until = perf_counter() + 2.5
        except Exception:
            pass

        CAMPAIGN.approve_step2()
        if CAMPAIGN.get_current_step() < 3:
            CAMPAIGN.set_current_step(3)

        try:
            self.request_wizard_stage_focus(step_num=3)
        except Exception:
            pass
        self._refresh_dashboard()
        try:
            self.app.open_controlled_tab("campaign")
        except Exception:
            pass
        self.app.update_campaign_tab_access()

        try:
            run_hint = f" Korzystam z runu anotacji {ready_run_name}." if ready_run_name else ""
            self.app.update_status(
                "Znaleziono gotowe ręczne tablice dla tego katalogu zdjęć. "
                "E2 zostało zatwierdzone. Przechodzę do E3 w wizardzie."
                + run_hint,
                "info"
            )
        except Exception:
            pass

        return True

    def _step_continue_characters_from_ready_source(self, preferred_source_context: dict | None = None):
        if not self._finish_step2_char_and_focus_step3(preferred_source_context):
            return

        source_context = preferred_source_context if isinstance(preferred_source_context, dict) else {}
        if not source_context:
            source_context = self._get_char_route_ready_source()
        self._step_goto_characters(preferred_source_context=source_context)

    def _step_goto_characters_detect(self, preferred_source_context: dict | None = None):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3:
            return

        self._step_goto_characters(preferred_source_context=preferred_source_context)

    def _step_goto_characters(self, preferred_source_context: dict | None = None):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3:
            return

        tab_char = self.app.tabs.get("characters")
        if not tab_char:
            return

        source_context = preferred_source_context if isinstance(preferred_source_context, dict) else {}
        if not source_context and self._get_iteration_target() == "char":
            source_context = self._get_char_route_ready_source()

        try:
            result = tab_char.open_campaign_step3_entry(preferred_source_context=source_context)
        except Exception as e:
            logger.error(f"Nie udało się otworzyc punktu startowego Z3: {e}")
            return

        if not result.get("ok"):
            return

        latest_xml = str(result.get("latest_xml") or "").strip()
        images_dir = str(result.get("images_dir") or "").strip()
        using_preferred_source = bool(result.get("using_preferred_source"))
        preferred_run_dir_raw = str(result.get("preferred_run_dir") or "").strip()
        preferred_run_dir = Path(preferred_run_dir_raw) if preferred_run_dir_raw else None
        preferred_source_name = str(
            source_context.get("display_name")
            or source_context.get("run_name")
            or ""
        ).strip()

        try:
            folder_name = Path(images_dir).name if images_dir else ""
        except Exception:
            folder_name = ""

        try:
            if latest_xml:
                if using_preferred_source and preferred_run_dir is not None:
                    source_label = preferred_source_name or preferred_run_dir.name
                    self.app.update_status(
                        f"Ustawiono Z3 na gotowe źródło tablic: {source_label}. XML={preferred_run_dir.name}/annotations.xml | IMG={folder_name}.",
                        "info"
                    )
                else:
                    self.app.update_status(
                        f"Ustawiono świeże źródła dla Zakładki Znaków: XML={Path(latest_xml).parent.name}/annotations.xml | IMG={folder_name}.",
                        "info"
                    )
            else:
                self.app.update_status(
                    "Nie znaleziono nowego pliku annotations.xml. Upewnij się, ze Autoanotacja zakończyła się sukcesem i etap został zatwierdzony.",
                    "warning"
                )
        except Exception:
            pass

        self.app.open_controlled_tab("characters")

    def _step_goto_training(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 4:
            return

        try:
            iteration_target = self._get_iteration_target()
            if iteration_target not in {"plate", "char"}:
                iteration_target = "char"

            tab_train = self.app.tabs.get("training")
            if not tab_train:
                logger.error("Nie znaleziono zakładki TrainingTab w app.tabs.")
                return

            preferred_subtab = None
            readiness = None
            try:
                if hasattr(tab_train, "get_campaign_step4_readiness"):
                    readiness = tab_train.get_campaign_step4_readiness(iteration_target=iteration_target)
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzic gotowosci wejscia do Z4: {e}")
                readiness = None

            if isinstance(readiness, dict) and not readiness.get("ok", False):
                reason = str(readiness.get("reason") or "").strip().lower()
                if reason == "stale_plate_dataset":
                    preferred_subtab = "dataset"
                    warn_msg = str(readiness.get("message") or "").strip()
                    try:
                        if warn_msg:
                            self.app.update_status(warn_msg, "warning")
                    except Exception:
                        pass
                else:
                    can_open_char_dataset_stage = False
                    if iteration_target == "char" and reason in {"invalid_char_dataset", "missing_char_dataset"}:
                        try:
                            datasets_dir = CAMPAIGN.get_dir("datasets")
                            if datasets_dir is not None and hasattr(tab_train, "_find_dataset_source_candidates"):
                                for path in tab_train._find_dataset_source_candidates(Path(datasets_dir)):
                                    try:
                                        inferred = tab_train._infer_dataset_target(str(path))
                                    except Exception:
                                        inferred = "char"
                                    if inferred == "char":
                                        can_open_char_dataset_stage = True
                                        break
                        except Exception:
                            can_open_char_dataset_stage = False

                    if can_open_char_dataset_stage:
                        preferred_subtab = "dataset"
                    else:
                        warn_msg = str(readiness.get("message") or "").strip() or "Z4 nie jest jeszcze gotowe do otwarcia."
                        try:
                            self.app.update_status(warn_msg, "warning")
                        except Exception:
                            pass
                        try:
                            messagebox.showwarning("Z4 jeszcze zablokowane", warn_msg, parent=self.frame)
                        except Exception:
                            pass
                        return

                if not readiness.get("ok", False) and preferred_subtab != "dataset":
                    warn_msg = str(readiness.get("message") or "").strip() or "Z4 nie jest jeszcze gotowe do otwarcia."
                    try:
                        self.app.update_status(warn_msg, "warning")
                    except Exception:
                        pass
                    try:
                        messagebox.showwarning("Z4 jeszcze zablokowane", warn_msg, parent=self.frame)
                    except Exception:
                        pass
                    return
            elif isinstance(readiness, dict):
                reason = str(readiness.get("reason") or "").strip().lower()
                if iteration_target == "char" and reason == "source_dataset_ready_for_split":
                    preferred_subtab = "dataset"

            target_label = "tablic" if iteration_target == "plate" else "znaków"
            try:
                self._show_project_loading_overlay(
                    title="Przygotowuję Z4",
                    body=(
                        f"Odtwarzam kontekst E4 dla toru {target_label}, sprawdzam dataset "
                        "i przygotowuję zakładkę treningu."
                    ),
                    tone="info",
                    progress=18.0,
                )
            except Exception:
                pass
            try:
                self.app.update_status("Przygotowuję Z4 i odtwarzam kontekst treningu.", "info")
            except Exception:
                pass

            try:
                result = tab_train.open_campaign_step4_entry(
                    iteration_target=iteration_target,
                    preferred_subtab=preferred_subtab,
                )
            except Exception as e:
                try:
                    self._hide_project_loading_overlay()
                except Exception:
                    pass
                logger.error(f"Błąd otwierania punktu startowego Z4: {e}")
                return

            if not result.get("ok"):
                try:
                    self._hide_project_loading_overlay()
                except Exception:
                    pass
                warn_msg = str(result.get("message") or "").strip()
                if warn_msg:
                    try:
                        self.app.update_status(warn_msg, "warning")
                    except Exception:
                        pass
                return

            latest_source_raw = str(result.get("latest_source") or "").strip()
            latest_source = Path(latest_source_raw) if latest_source_raw else None
            dataset_hint = str(result.get("dataset_hint") or "").strip()

            try:
                if iteration_target == "plate":
                    if dataset_hint:
                        self.app.update_status(
                            f"Ustawiono tor treningu tablic: gotowy dataset = {Path(dataset_hint).name}, źródła XML z Z2 i model Pose.",
                            "info"
                        )
                    else:
                        self.app.update_status(
                            "Przelaczono do Treningu w torze tablic. Zbuduj dataset z XML CVAT i uruchom trening modelu Pose.",
                            "info"
                        )
                elif latest_source is not None:
                    self.app.update_status(
                        f"Ustawiono automatycznie Trening: źródło splittera = {latest_source.name}, wynik splitu w katalogu projektu oraz model DETECT dla znaków.",
                        "info"
                    )
                else:
                    self.app.update_status(
                        "Przelaczono do Treningu w kontekscie projektu, ale nie znaleziono jeszcze datasetu źródłowego w 4_training_datasets.",
                        "warning"
                    )
            except Exception:
                pass

            try:
                self._show_project_loading_overlay(
                    title="Przygotowuję Z4",
                    body="Kontekst E4 jest gotowy. Przełączam widok na zakładkę treningu.",
                    tone="success",
                    progress=86.0,
                )
            except Exception:
                pass
            self.app.open_controlled_tab("training")
            try:
                self.frame.after(180, self._hide_project_loading_overlay)
            except Exception:
                pass
            return
        except Exception as e:
            try:
                self._hide_project_loading_overlay()
            except Exception:
                pass
            logger.error(f"Błąd nawigacji (Krok 4): {e}")

    def _step_goto_training_dataset(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 4:
            return

        try:
            iteration_target = self._get_iteration_target()
            if iteration_target not in {"plate", "char"}:
                iteration_target = "char"

            tab_train = self.app.tabs.get("training")
            if not tab_train:
                logger.error("Nie znaleziono zakładki TrainingTab w app.tabs.")
                return

            target_label = "tablic" if iteration_target == "plate" else "znaków"
            try:
                self._show_project_loading_overlay(
                    title="Przygotowuję Z4/PZ1",
                    body=(
                        f"Odtwarzam kontekst E4 dla toru {target_label} "
                        "i przygotowuję panel datasetu."
                    ),
                    tone="info",
                    progress=18.0,
                )
            except Exception:
                pass
            try:
                self.app.update_status("Przygotowuję Z4/PZ1 i odtwarzam kontekst datasetu.", "info")
            except Exception:
                pass

            result = tab_train.open_campaign_step4_entry(
                iteration_target=iteration_target,
                preferred_subtab="dataset",
            )
        except Exception as e:
            try:
                self._hide_project_loading_overlay()
            except Exception:
                pass
            logger.error(f"Błąd otwierania PZ1 dla Z4: {e}")
            return

        if not result.get("ok"):
            try:
                self._hide_project_loading_overlay()
            except Exception:
                pass
            warn_msg = str(result.get("message") or "").strip()
            if warn_msg:
                try:
                    self.app.update_status(warn_msg, "warning")
                except Exception:
                    pass
                try:
                    messagebox.showwarning("Z4/PZ1 jeszcze zablokowane", warn_msg, parent=self.frame)
                except Exception:
                    pass
            return

        try:
            self.app.update_status(
                "Przejście do Z4 otworzyło PZ1, aby przebudować albo sprawdzić dataset tej iteracji.",
                "info",
            )
        except Exception:
            pass

        try:
            self._show_project_loading_overlay(
                title="Przygotowuję Z4/PZ1",
                body="Panel datasetu jest gotowy. Przełączam widok na zakładkę treningu.",
                tone="success",
                progress=86.0,
            )
        except Exception:
            pass
        self.app.open_controlled_tab("training")
        try:
            self.frame.after(180, self._hide_project_loading_overlay)
        except Exception:
            pass
        return

    def _advance_iteration(self):
        self._show_step4_completion_next_action_modal(completed_with_training=True)

    def _show_step4_completion_next_action_modal(self, *, completed_with_training: bool = True) -> bool:
        mode = self._ask_iteration_advance_mode(completed_with_training=completed_with_training)
        if str(mode or "").strip().lower() not in {"reuse_input", "new_input"}:
            try:
                self.app.update_status(
                    "Pozostajesz w E4. Iteracja nie została przeniesiona do kolejnego cyklu.",
                    "info",
                )
            except Exception:
                pass
            try:
                self.request_wizard_stage_focus(step_num=4)
                self._refresh_active_project_wizard_only()
            except Exception:
                pass
            return False
        self._start_iteration_advance(mode)
        return True

    def _start_iteration_advance(self, mode: str | None) -> None:
        mode = str(mode or "").strip().lower()
        if mode not in {"reuse_input", "new_input"}:
            return

        existing_worker = getattr(self, "_iteration_advance_thread", None)
        if existing_worker is not None:
            try:
                if existing_worker.is_alive():
                    try:
                        self.app.update_status(
                            "Trwa już przygotowywanie nowej iteracji. Zaczekaj na zakończenie bieżącej operacji.",
                            "info",
                        )
                    except Exception:
                        pass
                    return
            except Exception:
                pass
            # Bezpiecznik na stary, już zakończony worker, który mógł zostać
            # w stanie UI po wcześniejszym przejściu dashboardu.
            self._iteration_advance_thread = None
            self._iteration_advance_result = None
            self._iteration_advance_mode = ""
            try:
                pending_poll = getattr(self, "_iteration_advance_poll_after_id", None)
                if pending_poll:
                    self.frame.after_cancel(pending_poll)
            except Exception:
                pass
            self._iteration_advance_poll_after_id = None
            self._set_iteration_advance_busy(False)

        try:
            if mode == "reuse_input":
                self.app.update_status(
                    "Przygotowuję nową iterację z tej samej puli zdjęć. To może chwilę potrwać przy dużym katalogu zdjęć.",
                    "info",
                )
            else:
                self.app.update_status(
                    "Rozpoczynam nową iterację projektu.",
                    "info",
                )
        except Exception:
            pass
        try:
            self.frame.update_idletasks()
        except Exception:
            pass

        self._iteration_advance_mode = mode
        self._iteration_advance_result = None
        self._set_iteration_advance_busy(True)

        worker = threading.Thread(
            target=self._run_iteration_advance_worker,
            args=(self._iteration_advance_mode,),
            daemon=True,
        )
        self._iteration_advance_thread = worker
        worker.start()
        self._schedule_iteration_advance_poll()

    def _finish_step4_iteration(self):
        if not CAMPAIGN.get_active_project_name():
            return

        training_tab = self.app.tabs.get("training") if getattr(self.app, "tabs", None) else None
        try:
            if training_tab is not None and hasattr(training_tab, "_step4_has_active_operation"):
                if bool(training_tab._step4_has_active_operation()):
                    self.app.themed_info(
                        "Poczekaj na zakończenie operacji Z4",
                        "W Z4 nadal trwa aktywna operacja. Zaczekaj na jej zakończenie, a potem domknij iterację.",
                        parent=self.frame,
                        tone="warning",
                    )
                    return
        except Exception:
            pass

        try:
            if training_tab is not None and hasattr(training_tab, "_finish_campaign_step4"):
                handled_by_training = bool(training_tab._finish_campaign_step4())
                try:
                    step_after_training = int(CAMPAIGN.get_current_step() or 0)
                except Exception:
                    step_after_training = 0
                if handled_by_training or step_after_training >= 5:
                    return
        except Exception as e:
            logger.debug(f"Nie udało się domknąć E4 przez Z4, przechodzę na fallback: {e}")

        mode = self._ask_iteration_advance_mode(completed_with_training=True)
        if str(mode or "").strip().lower() not in {"reuse_input", "new_input"}:
            try:
                self.app.update_status(
                    "Pozostajesz w E4. Iteracja nie została domknięta, więc badge zatwierdzający pozostaje dostępny.",
                    "info",
                )
            except Exception:
                pass
            try:
                self.request_wizard_stage_focus(step_num=4)
                self._refresh_active_project_wizard_only()
            except Exception:
                pass
            return

        try:
            CAMPAIGN.set_current_step(5)
            CAMPAIGN.set_step4_finish_state(False)
        except Exception as e:
            logger.error(f"Nie udało się domknąć iteracji w E4: {e}")
            return

        try:
            self.app.update_status("Iteracja została domknięta. Przygotowuję przejście do E1.", "info")
        except Exception:
            pass
        try:
            self._refresh_active_project_wizard_only()
        except Exception:
            try:
                self._refresh_dashboard()
            except Exception:
                pass
        try:
            self.request_wizard_stage_focus(step_num=4)
        except Exception:
            pass
        self._start_iteration_advance(mode)

    def _finish_step4_without_training(self):
        if not CAMPAIGN.get_active_project_name():
            return

        training_tab = self.app.tabs.get("training") if getattr(self.app, "tabs", None) else None
        try:
            if training_tab is not None and hasattr(training_tab, "_step4_has_active_operation"):
                if bool(training_tab._step4_has_active_operation()):
                    self.app.themed_info(
                        "Poczekaj na zakończenie operacji Z4",
                        "W Z4 nadal trwa aktywna operacja. Zaczekaj na jej zakończenie, a potem zdecyduj, czy chcesz pominąć trening.",
                        parent=self.frame,
                        tone="warning",
                    )
                    return
        except Exception:
            pass

        should_finish = self.app.themed_confirm(
            "Zamknąć iterację bez treningu?",
            "Ta iteracja zostanie formalnie domknięta bez uruchamiania treningu.\n\n"
            "Wyniki przygotowania datasetu i adnotacji pozostaną w projekcie, ale dopiero kolejna iteracja "
            "będzie mogła wystartować z poziomu E1.\n\n"
            "Czy chcesz zamknąć iterację bez treningu?",
            parent=self.frame,
            confirm_label="Zamknij iterację",
            tone="warning",
        )
        if not should_finish:
            return

        mode = self._ask_iteration_advance_mode(completed_with_training=False)
        if str(mode or "").strip().lower() not in {"reuse_input", "new_input"}:
            try:
                self.app.update_status(
                    "Pozostajesz w E4. Iteracja bez treningu nie została domknięta.",
                    "info",
                )
            except Exception:
                pass
            try:
                self.request_wizard_stage_focus(step_num=4)
                self._refresh_active_project_wizard_only()
            except Exception:
                pass
            return

        try:
            CAMPAIGN.set_current_step(5)
            CAMPAIGN.set_step4_finish_state(False)
        except Exception as e:
            logger.error(f"Nie udało się domknąć iteracji bez treningu: {e}")
            return

        try:
            self.app.update_status("Iteracja została domknięta bez treningu. Przygotowuję przejście do E1.", "info")
        except Exception:
            pass
        try:
            self._refresh_active_project_wizard_only()
        except Exception:
            try:
                self._refresh_dashboard()
            except Exception:
                pass
        try:
            self.request_wizard_stage_focus(step_num=4)
        except Exception:
            pass
        self._start_iteration_advance(mode)

    def _set_iteration_advance_busy(self, busy: bool) -> None:
        state_cache = getattr(self, "_iteration_advance_ui_cache", None)
        if busy and not isinstance(state_cache, dict):
            state_cache = {}
            try:
                state_cache["btn_complete_project"] = {
                    "text": self.btn_complete_project.cget("text"),
                    "state": self.btn_complete_project.cget("state"),
                }
            except Exception:
                pass
            for attr_name in ("btn_open_proj", "btn_del_proj", "btn_exit_project"):
                widget = getattr(self, attr_name, None)
                if widget is None:
                    continue
                try:
                    state_cache[attr_name] = {"state": widget.cget("state")}
                except Exception:
                    pass
            self._iteration_advance_ui_cache = state_cache

        try:
            if busy:
                self.btn_complete_project.config(
                    text="Przygotowywanie iteracji...",
                    state="disabled",
                )
            elif isinstance(state_cache, dict) and "btn_complete_project" in state_cache:
                self.btn_complete_project.config(**dict(state_cache["btn_complete_project"]))
        except Exception:
            pass

        for attr_name in ("btn_open_proj", "btn_del_proj", "btn_exit_project"):
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            try:
                if busy:
                    widget.config(state="disabled")
                elif isinstance(state_cache, dict) and attr_name in state_cache:
                    widget.config(**dict(state_cache[attr_name]))
            except Exception:
                pass

        try:
            self.frame.configure(cursor=("watch" if busy else ""))
        except Exception:
            pass
        try:
            self.app.root.configure(cursor=("watch" if busy else ""))
        except Exception:
            pass
        if not busy:
            self._iteration_advance_ui_cache = None

    def _run_iteration_advance_worker(self, mode: str) -> None:
        try:
            result = CAMPAIGN.advance_to_next_iteration(start_mode=mode)
        except Exception as exc:
            logger.exception("Błąd podczas tworzenia nowej iteracji")
            result = {
                "ok": False,
                "reason": "exception",
                "error": str(exc),
            }
        self._iteration_advance_result = dict(result or {})

    def _schedule_iteration_advance_poll(self) -> None:
        pending = getattr(self, "_iteration_advance_poll_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
        self._iteration_advance_poll_after_id = self.frame.after(80, self._poll_iteration_advance_worker)

    def _poll_iteration_advance_worker(self) -> None:
        self._iteration_advance_poll_after_id = None
        worker = getattr(self, "_iteration_advance_thread", None)
        if worker is not None and worker.is_alive():
            self._schedule_iteration_advance_poll()
            return

        mode = str(getattr(self, "_iteration_advance_mode", "") or "").strip().lower()
        result = dict(getattr(self, "_iteration_advance_result", {}) or {})
        self._iteration_advance_thread = None
        self._iteration_advance_result = None
        self._iteration_advance_mode = ""
        self._set_iteration_advance_busy(False)
        self._finish_iteration_advance(mode, result)

    def _finish_iteration_advance(self, mode: str, result: dict) -> None:
        if not result.get("ok"):
            reason = str(result.get("reason") or "").strip().lower()
            if reason == "step4_not_finished":
                self.app.themed_info(
                    "Najpierw domknij E4",
                    (
                        "Nie możesz rozpocząć kolejnej iteracji, dopóki etap E4 tej iteracji "
                        "nie zostanie zakończony.\n\n"
                        "Najpierw wróć do Z4, uruchom trening albo domknij etap tylko wtedy, "
                        "gdy kampania oznaczy trening jako gotowy."
                    ),
                    parent=self.frame,
                    tone="warning",
                )
            elif reason == "project_not_active":
                self.app.themed_info(
                    "Projekt nie jest aktywny",
                    "Wznów projekt, zanim rozpoczniesz kolejną iterację.",
                    parent=self.frame,
                    tone="warning",
                )
            elif reason == "missing_remaining_images":
                self.app.themed_info(
                    "Brak kolejnego zestawu zdjęć",
                    (
                        "Nie ma już kolejnych zdjęć do pobrania z tej samej puli projektu.\n"
                        "System pomija tu obrazy już zatwierdzone w projekcie.\n\n"
                        "Aby kontynuować, rozpocznij kolejną iterację od nowego zestawu zdjęć "
                        "albo zakończ projekt."
                    ),
                    parent=self.frame,
                    tone="warning",
                )
            elif reason in {"copy_failed", "manifest_save_failed"}:
                self.app.themed_info(
                    "Nie udało się przygotować iteracji",
                    (
                        "Nie udało się zapisać manifestu kolejnego katalogu zdjęć.\n\n"
                        "Spróbuj ponownie albo rozpocznij iterację od innego katalogu zdjęć."
                    ),
                    parent=self.frame,
                    tone="warning",
                )
            else:
                self.app.themed_info(
                    "Nie udało się rozpocząć iteracji",
                    "Nowa iteracja nie została utworzona. Sprawdź stan projektu i spróbuj ponownie.",
                    parent=self.frame,
                    tone="warning",
                )
            return

        try:
            annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
            try:
                next_input_dir = CAMPAIGN.get_iteration_image_source_dir()
            except Exception:
                next_input_dir = CAMPAIGN.get_iteration_raw_dir()
            if annotation_tab is not None and hasattr(annotation_tab, "prepare_campaign_iteration_transition"):
                annotation_tab.prepare_campaign_iteration_transition(
                    input_dir=(Path(next_input_dir) if next_input_dir else None)
                )
        except Exception as e:
            logger.debug(f"Nie udało się przygotować Z2 do nowej iteracji: {e}")

        self._rebuild_wizard_stage_ui()
        self._refresh_dashboard()
        self.app.update_campaign_tab_access()

        iter_num = int(result.get("next_iteration", CAMPAIGN.get_current_iteration_num()) or CAMPAIGN.get_current_iteration_num())
        effective_mode = str(result.get("effective_mode", "new_input") or "new_input").strip().lower()

        try:
            if mode == "reuse_input" and effective_mode != "reuse_input":
                self.app.update_status(
                    (
                        f"Rozpoczęto iterację {iter_num:03d}, ale nie udało się przenieść "
                        "poprzedniego zestawu zdjęć. Iteracja startuje od E1."
                    ),
                    "warning"
                )
            elif effective_mode == "reuse_input":
                manifest_images = int(result.get("manifest_images", result.get("copied_images", 0)) or 0)
                source_kind = str(result.get("source_kind") or "").strip().lower()
                if source_kind == "stage":
                    self.app.update_status(
                        (
                            f"Rozpoczęto iterację {iter_num:03d}. E1 korzysta z manifestu {manifest_images} zdjęć "
                            "ze źródła zatwierdzonych tablic. Wybierz tor iteracji i zatwierdź etap. "
                            "Aktywne modele projektu pozostały zachowane."
                        ),
                        "info"
                    )
                else:
                    self.app.update_status(
                        (
                            f"Rozpoczęto iterację {iter_num:03d} na manifeście kolejnych zdjęć z tej samej puli "
                            f"({manifest_images} obrazów). Zdjęcia nie są kopiowane między iteracjami. "
                            "Wybierz tor iteracji i zatwierdź etap. "
                            "Aktywne modele projektu pozostały zachowane."
                        ),
                        "info"
                    )
            else:
                restored_dir = str(result.get("restored_master_pool_dir") or result.get("previous_image_source") or "").strip()
                if restored_dir:
                    restored_name = Path(restored_dir).name or restored_dir
                    self.app.update_status(
                        (
                            f"Rozpoczęto iterację {iter_num:03d}. W E1 odtworzono poprzedni katalog zdjęć "
                            f"({restored_name}); możesz go zatwierdzić, zmienić albo wyczyścić. "
                            "Aktywne modele projektu pozostały zachowane."
                        ),
                        "info"
                    )
                else:
                    self.app.update_status(
                        f"Rozpoczęto iterację {iter_num:03d}. Wskaż nowy zestaw zdjęć w E1. Aktywne modele projektu pozostały zachowane.",
                        "info"
                    )
        except Exception:
            pass

        try:
            self.step1_panel_expanded = True
            self.request_wizard_stage_focus(step_num=1)
        except Exception:
            pass

        try:
            self.app.open_controlled_tab("campaign")
        except Exception:
            pass

        if bool(result.get("needs_new_image_source")):
            message = (
                "Nie udało się odtworzyć katalogu zdjęć z poprzedniej iteracji.\n\n"
                "W E1 wskaż katalog zdjęć wejściowych, wybierz tor iteracji i dopiero wtedy "
                "zatwierdź etap. Jeśli poprzedni katalog nadal istnieje, możesz wskazać go ponownie."
            )
            try:
                self.app.themed_info(
                    "Wybierz nowy katalog zdjęć",
                    message,
                    parent=self.frame,
                    tone="warning",
                )
            except Exception:
                try:
                    messagebox.showwarning("Wybierz nowy katalog zdjęć", message, parent=self.frame)
                except Exception:
                    pass

    def _toggle_project_completion(self):
        active_project = CAMPAIGN.get_active_project_name()
        if not active_project:
            return

        project_status = CAMPAIGN.get_project_status()
        if project_status in {"completed", "paused"}:
            status_label = "odłożony" if project_status == "paused" else "zakończony"
            if self.app.themed_confirm(
                "Wznowienie projektu",
                f"Czy wznowić {status_label} projekt '{active_project}'?\n\n"
                "Po wznowieniu znowu będzie można rozpocząć nową iterację.",
                parent=self.frame,
                confirm_label="Wznów",
                tone="info"
            ):
                CAMPAIGN.reopen_project()
                self._refresh_dashboard()
                self.app.update_campaign_tab_access()
                try:
                    self.app.update_status(
                        f"Projekt '{active_project}' został wznowiony. Możesz wrócić do workflow albo rozpocząć kolejną iterację.",
                        "info"
                    )
                except Exception:
                    pass
            return

        if CAMPAIGN.get_current_step() < 5:
            return

        if self.app.themed_confirm(
            "Opuszczenie projektu",
            f"Czy opuścić aktywny projekt '{active_project}'?\n\n"
            "Projekt pozostanie zapisany i będzie można wrócić do niego później.",
            parent=self.frame,
            confirm_label="Opuść projekt",
            tone="info"
        ):
            CAMPAIGN.pause_project()
            self._refresh_dashboard()
            self.app.update_campaign_tab_access()
            try:
                self.app.update_status(
                    f"Projekt '{active_project}' został odłożony. Możesz wrócić do niego później.",
                    "info"
                )
            except Exception:
                pass
