#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lekkie modele widoku dla E2/E3/Z2.

To warstwa pośrednia między domeną workflow a rendererami kampanii / free mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Step2CtaViewModel:
    label: str = ""
    command_id: str = ""
    command_context: dict = field(default_factory=dict)
    enabled: bool = True
    tone: str = "primary"


@dataclass(frozen=True)
class Step2RouteChoiceViewModel:
    id: str = ""
    label: str = ""
    visible: bool = True
    enabled: bool = True
    selected: bool = False
    command_id: str = ""
    command_context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Step2ViewModel:
    stage_key: str = "step2"
    iteration_target: str = ""
    current_step: int = 0
    step2_status: str = "pending"
    state: str = "locked"
    title: str = "E2"
    summary: str = ""
    details: str = ""
    route_hint: str = ""
    route_lock_reason: str = ""
    route_choices: list[Step2RouteChoiceViewModel] = field(default_factory=list)
    primary_cta: Step2CtaViewModel | None = None
    secondary_cta: Step2CtaViewModel | None = None


@dataclass(frozen=True)
class Step3ViewModel:
    stage_key: str = "step3"
    iteration_target: str = ""
    current_step: int = 0
    step3_status: str = "pending"
    state: str = "locked"
    title: str = "E3"
    summary: str = ""
    details: str = ""
    body_mode: str = ""
    body_visible: bool = False
    primary_cta: Step2CtaViewModel | None = None
    secondary_cta: Step2CtaViewModel | None = None


@dataclass(frozen=True)
class Step3EntryFlowViewModel:
    mode: str = ""
    message: str = ""
    target_substep: int = 0
    should_start_extraction: bool = False
    should_show_splash: bool = False
    should_hide_splash: bool = False
    splash_title: str = ""
    splash_body: str = ""
    splash_tone: str = "info"
    splash_show_progress: bool = False
    splash_show_return: bool = False


@dataclass(frozen=True)
class Step3CampaignNavigationViewModel:
    in_campaign: bool = False
    splash_visible: bool = False
    show_detect_back_to_extract: bool = True
    show_detect_to_dataset: bool = True
    show_dataset_back_to_detect: bool = True


@dataclass(frozen=True)
class Step3FinishActionViewModel:
    visible: bool = False
    label: str = ""
    command_id: str = ""
    enabled: bool = False
    emphasize: bool = False
    hint: str = ""
    hint_tone: str = "muted"
    back_to_wizard_enabled: bool = False


@dataclass(frozen=True)
class Step3Pz3PathSelectionViewModel:
    selected_path: str = ""
    show_dataset_section: bool = False
    show_cvat_section: bool = False
    show_status_section: bool = False
    dataset_card_selected: bool = False
    cvat_card_selected: bool = False
    dataset_badge_text: str = "DATASET"
    dataset_title_text: str = "Budowa datasetu"
    dataset_desc_text: str = "Perfecty, importy manualne, split i eksport datasetu treningowego."
    cvat_badge_text: str = "CVAT"
    cvat_title_text: str = "Eksport do CVAT"
    cvat_desc_text: str = "Eksport review packa do ręcznej korekty."


@dataclass(frozen=True)
class Step3Pz3DatasetModeViewModel:
    in_campaign: bool = False
    mode: str = "perfect"
    dataset_source_title: str = " Źródło pracy w PZ3 "
    dataset_source_intro: str = ""
    show_dataset_source_cards: bool = True
    perfect_selected: bool = True
    existing_selected: bool = False
    perfect_badge_text: str = "PZ2 | DOMYSLNIE"
    perfect_title_text: str = "Perfecty z aktywnego runu"
    perfect_desc_text: str = "Buduj nowy dataset bezposrednio z wyniku PZ2 i aktualnych perfectow."
    existing_badge_text: str = "DATASET | WZNOWIENIE"
    existing_title_text: str = "Gotowy dataset YOLO"
    existing_desc_text: str = "Wskaż już zapisany dataset znaków, aby wykonac nowy split albo wznowic prace po restarcie."
    show_existing_dataset_panel: bool = False
    cvat_option2_title: str = ""
    cvat_option2_tone: str = "muted"
    cvat_option2_desc: str = ""
    show_gold_filters: bool = True
    split_title: str = " Split train / val / test "
    split_label: str = "Po eksporcie podziel dane na train / val / test"
    primary_export_label: str = ""
    primary_export_command_id: str = ""
    primary_export_enabled: bool = True
    primary_export_columnspan: int = 1
    show_classifier_export: bool = True
    classifier_export_enabled: bool = True
    action_hint: str = ""
    action_hint_tone: str = "muted"
    existing_dataset_status: str = ""
    existing_dataset_status_tone: str = "muted"


@dataclass(frozen=True)
class Step3Pz3StatusRowViewModel:
    label: str = ""
    text: str = ""
    tone: str = "muted"


@dataclass(frozen=True)
class Step3Pz3StatusPanelViewModel:
    title: str = "Podsumowanie"
    show_section: bool = False
    export_row: Step3Pz3StatusRowViewModel = field(default_factory=Step3Pz3StatusRowViewModel)
    import_row: Step3Pz3StatusRowViewModel = field(default_factory=Step3Pz3StatusRowViewModel)
    finish_action: Step3FinishActionViewModel = field(default_factory=Step3FinishActionViewModel)


@dataclass(frozen=True)
class Step3ExtractStepCardViewModel:
    key: str = ""
    state: str = "pending"
    title: str = ""
    description: str = ""


@dataclass(frozen=True)
class Step3ExtractWorkflowViewModel:
    route: str = ""
    current_step: str = "entry"
    linear_mode: bool = False
    show_entry: bool = True
    show_source: bool = False
    show_start: bool = False
    source_title: str = "Źródła wejscia"
    start_title: str = "Uruchom wyodrebnianie"
    source_intro: str = ""
    source_hint: str = ""
    run_hint: str = ""
    run_hint_tone: str = "muted"
    start_hint: str = ""
    start_hint_tone: str = "muted"
    show_step_nav: bool = False
    prev_enabled: bool = False
    next_enabled: bool = False
    next_visible: bool = True
    show_tab_nav: bool = True
    show_back_nav: bool = False
    show_detect_nav: bool = True
    clear_detect_emphasis: bool = True
    step_cards: list[Step3ExtractStepCardViewModel] = field(default_factory=list)


@dataclass(frozen=True)
class Step4DatasetWorkflowViewModel:
    mode: str = "char"
    in_campaign: bool = False
    route_selected: bool = False
    route_locked: bool = False
    show_route_panel: bool = True
    show_waiting_panel: bool = False
    title: str = ""
    description: str = ""
    show_creator_section: bool = False
    show_split_section: bool = False
    next_label: str = "Dalej do treningu"
    creator_summary: str = ""
    split_intro: str = ""
    split_summary: str = ""
    split_action_label: str = "Rozpocznij podział (split)"
    show_split_toggle: bool = False
    split_toggle_label: str = "Popraw split"
    show_split_details: bool = True
    char_ready_dataset: bool = False
    char_ready_dataset_path: str = ""
    char_ready_train: int = 0
    char_ready_val: int = 0
    char_ready_test: int = 0


@dataclass(frozen=True)
class Step4TrainingInputsViewModel:
    in_campaign: bool = False
    show_session_name: bool = True
    show_dataset_section: bool = True
    dataset_caption: str = ""
    dataset_entry_state: str = "normal"
    show_dataset_pick_button: bool = True
    show_dataset_hint: bool = True
    show_scope_hint: bool = True
    show_pose_warning: bool = True
    base_caption: str = ""
    base_combo_state: str = "readonly"
    show_custom_model: bool = True
    custom_entry_state: str = "disabled"
    show_custom_pick_button: bool = True


@dataclass(frozen=True)
class Step4CampaignNavigationViewModel:
    in_campaign: bool = False
    dataset_tab_enabled: bool = True
    train_tab_enabled: bool = True
    next_enabled: bool = True
    next_label: str = "Dalej do treningu"
    show_dataset_back: bool = True
    dataset_back_label: str = "Wstecz"
    show_train_nav: bool = False
    show_train_back: bool = True
    train_back_label: str = "Wstecz do toru"
    finish_enabled: bool = False
    show_complete_project: bool = False
    force_dataset_tab_selection: bool = False
