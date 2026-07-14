#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z4 tab shell and assistant-context helpers extracted from tab_training.py."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import datetime
import time
import webbrowser
import csv
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..campaign_manager import CAMPAIGN
from ..config import (
    CONFIG,
    YOLO_AVAILABLE,
    AVAILABLE_POSE_MODELS,
    AVAILABLE_DETECT_MODELS,
    PIL_AVAILABLE,
    get_torch_module,
    get_yolo_class,
    is_cuda_available,
    logger,
)
from ..icons import IconManager
from ..validators import validate_model_file, format_yolo_model_identity
from ..training import YOLOPoseTrainer, TrainingHistory, TrainingStatus, DatasetCreator, DatasetSplitter
from ..ranking import ModelRanking
from ..utils import cleanup_gpu_memory, safe_load_yaml, get_image_files
from .help_manager import HELP
from .inertial_scroll import InertialScrollController
from .section_header_label import SectionHeaderLabel
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors
from .zoomable_canvas import ZoomableCanvas
from .z4_campaign_flow import (
    build_step4_campaign_navigation_view_model,
    build_step4_dataset_workflow_view_model,
    build_step4_training_inputs_view_model,
    clear_campaign_context,
    complete_campaign_project,
    finish_campaign_step4,
    get_campaign_training_target,
    open_campaign_step4_entry,
    poll_training_completion,
    restore_step4_campaign_project_state,
    set_campaign_context,
    set_campaign_training_target,
)
from .z4_flow_models import (
    CharYoloDatasetSourceAdapter,
    PlateXmlImagesSourceAdapter,
    TrainingSource,
    TrainingSourceStats,
)
from .z4_free_mode_flow import (
    refresh_free_training_route_cards,
    refresh_free_training_route_ui,
    update_step4_notebook_mode,
)
from .z4_shared_ui import (
    accept_training_input_context,
    clear_step4_guidance,
    guide_step4_builder_action,
    guide_step4_finish_action,
    guide_step4_next_action,
    guide_step4_route_selection,
    mark_step4_dataset_ready,
    open_step4_dataset_stage,
    refresh_step4_campaign_builder_inputs_ui,
    refresh_step4_analysis_tab_visibility,
    refresh_step4_campaign_navigation_ui,
    refresh_step4_dataset_mode_ui,
    refresh_step4_training_inputs_mode_ui,
    set_step4_dataset_mode,
    sync_step4_analysis_nav_buttons,
    step4_dataset_go_back,
    step4_dataset_go_next,
    step4_train_go_back,
)
from . import z4_dataset_sources
from . import z4_training_metrics
from . import z4_dataset_builder
from . import z4_analysis_ranking
from . import z4_training_runtime
from . import z4_campaign_state
from . import z4_dataset_validation
from . import z4_layout_runtime
from . import z4_device_runtime
from . import z4_model_export
from . import z4_training_progress
from . import z4_ui_runtime
from . import z4_theme_runtime
from .z4_view_models import (
    Step4CampaignNavigationViewModel,
    Step4DatasetWorkflowViewModel,
    Step4TrainingInputsViewModel,
)

NAV_BUTTON_WIDTH = 18

if PIL_AVAILABLE:
    from PIL import Image, ImageDraw, ImageFont

YOLO = None


def _build_ui(self):


    # Główny notatnik powyżej paska pomocy
    self.main_nb = ttk.Notebook(self.frame)
    self.main_nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0, 4))

    self.tab_dataset = ttk.Frame(self.main_nb)
    self.tab_train = ttk.Frame(self.main_nb)
    self.tab_val = None
    self.tab_ranking = None

    self.main_nb.add(self.tab_dataset, text="[PZ1] Budowa datasetu")
    self.main_nb.add(self.tab_train, text="[PZ2] Trening i wyniki")
    self.main_nb.bind("<<NotebookTabChanged>>", self._on_main_nb_tab_changed, add="+")
    self._step4_dataset_tab_visible = True

    self._build_dataset_tab()
    self._build_train_tab_placeholder()
    self._update_step4_notebook_mode()

def _build_train_tab_placeholder(self):
    for child in self.tab_train.winfo_children():
        try:
            child.destroy()
        except Exception:
            pass
    placeholder = ttk.Frame(self.tab_train, padding=18)
    placeholder.pack(fill=tk.BOTH, expand=True)
    ttk.Label(
        placeholder,
        text="PZ2 wybiera wariant splitu przygotowany w PZ1 i uruchamia na nim trening modelu.",
        style="PanelMuted.TLabel",
        justify=tk.LEFT,
        wraplength=520,
    ).pack(anchor=tk.W)

def _ensure_step4_train_tab_built(self) -> bool:
    if bool(getattr(self, "_step4_train_tab_built", False)):
        return True

    for child in self.tab_train.winfo_children():
        try:
            child.destroy()
        except Exception:
            pass

    self._step4_train_tab_built = True
    try:
        self._build_train_tab()
    except Exception as e:
        self._step4_train_tab_built = False
        logger.exception(f"Nie udało się leniwie zbudować PZ2 treningu: {e}")
        self._build_train_tab_placeholder()
        return False

    self._schedule_initial_step4_refresh()
    return True

def _on_main_nb_tab_changed(self, event=None):
    if event is not None and getattr(event, "widget", None) is not self.main_nb:
        return
    try:
        if str(self.main_nb.select()) == str(getattr(self, "tab_train", "")):
            self._ensure_step4_train_tab_built()
    except Exception:
        pass
    try:
        notify = getattr(self.app, "notify_free_mode_assistant_context_changed", None)
        if callable(notify):
            notify()
    except Exception:
        pass

def get_free_mode_assistant_context(self) -> dict:
    try:
        selected_tab = str(self.main_nb.select())
    except Exception:
        selected_tab = ""

    if selected_tab == str(getattr(self, "tab_dataset", "")):
        return {
            "location": "[Z4] Trening i analiza / [PZ1] Budowa datasetu",
            "goal": (
                "PZ1 zamienia źródło danych w gotowy wariant treningowy YOLO: układa train / val / test "
                "i zapisuje data.yaml. Ten wariant wybierzesz później w PZ2."
            ),
            "workflow": (
                "Wybierz typ datasetu: tablice albo znaki.",
                "Dla tablic wskaż gotowy dataset albo parę: XML anotacji + zgodny katalog zdjęć.",
                "Po wskazaniu XML system spróbuje znaleźć pasujący katalog zdjęć i poprosi o potwierdzenie.",
                "Dla znaków wskaż dataset wyprodukowany wcześniej w Z3/PZ2.",
                "Opcjonalnie ustaw syntetyczne zwiększanie tylko części train.",
                "Kliknij „Utwórz split treningowy”; po sukcesie możesz pozostać w PZ1 albo przejść do PZ2.",
            ),
            "glossary": (
                "źródło = dane wejściowe, z których PZ1 buduje dataset",
                "źródło bez splitu = katalog images/labels, który PZ1 dopiero podzieli na train / val / test",
                "wariant treningowy = konkretny folder datasetu z images, labels i data.yaml",
                "split = podział na train / val / test",
                "augmentacja = dopisanie syntetycznych obrazów tylko do train",
                "data.yaml = opis datasetu YOLO",
            ),
            "caution": (
                "XML i katalog zdjęć muszą opisywać te same pliki. Augmentacja nie zmienia val/test, "
                "tylko powiększa train."
            ),
        }
    if selected_tab == str(getattr(self, "tab_train", "")):
        return {
            "location": "[Z4] Trening i analiza / [PZ2] Trening i wyniki",
            "goal": "PZ2 korzysta z wariantu splitu przygotowanego w PZ1, wybiera model bazowy i uruchamia trening.",
            "workflow": (
                "Wybierz wariant splitu z listy.",
                "Wybierz model bazowy zgodny z typem datasetu.",
                "Ustaw parametry startowe: epoki, batch, rozdzielczość, learning rate i urządzenie.",
                "Uruchom trening i obserwuj postęp oraz terminal procesu.",
                "Po treningu sprawdź historię runów, wykonaj walidację lub porównaj wyniki w rankingu.",
            ),
            "glossary": (
                "epoka = pełne przejście po danych",
                "val = walidacja jakości",
                "ranking = porównanie modeli",
            ),
            "caution": "Jeśli trening ma używać innego splitu, wróć do PZ1 i wybierz albo utwórz inny wariant.",
        }
    return {
        "location": "[Z4] Trening i analiza",
        "goal": "Z4 prowadzi prostym przepływem: PZ1 przygotowuje wariant splitu, PZ2 trenuje model na wybranym wariancie.",
        "workflow": (
            "PZ1 buduje wariant splitu zgodny z typem datasetu.",
            "PZ2 używa wybranego wariantu do treningu, walidacji i porównania modeli.",
            "Jeśli chcesz testować inny split, wróć do PZ1 i utwórz kolejny wariant.",
        ),
        "glossary": ("PZ1 = budowa datasetu", "PZ2 = trening i wyniki", "ranking = porównanie modeli"),
        "caution": "PZ2 trenuje na splicie wybranym z listy. Nowe splity przygotowuje PZ1.",
    }
