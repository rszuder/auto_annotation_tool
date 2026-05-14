from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Z4CampaignRuntimeState:
    in_campaign: bool = False
    dataset_mode: str = "char"
    route_selected: bool = False
    route_locked: bool = False
    train_unlocked: bool = False
    finish_ready: bool = False
    dataset_tab_visible: bool = False


@dataclass(frozen=True)
class Z4FreeModeRuntimeState:
    in_campaign: bool = False
    dataset_mode: str = "char"
    route_selected: bool = False
    hover_mode: str = ""


@dataclass(frozen=True)
class Z4LayoutState:
    show_route_panel: bool = True
    show_waiting_panel: bool = False
    show_creator_section: bool = False
    show_split_section: bool = False
    show_dataset_section: bool = True
    show_session_name: bool = True


@dataclass(frozen=True)
class Z4CtaState:
    next_enabled: bool = True
    next_label: str = "Dalej do treningu"
    show_dataset_back: bool = True
    dataset_back_label: str = "Wstecz"
    show_train_nav: bool = False
    show_train_back: bool = True
    train_back_label: str = "Wstecz do toru"
    finish_enabled: bool = False


@dataclass(frozen=True)
class TrainingInputContext:
    source: str = ""
    target: str = "char"
    dataset_path: str = ""
    ready: bool = False
