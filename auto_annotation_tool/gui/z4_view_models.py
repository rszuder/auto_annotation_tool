#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lekkie modele widoku dla E4/Z4.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    split_action_label: str = "Przygotuj dataset treningowy"
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
