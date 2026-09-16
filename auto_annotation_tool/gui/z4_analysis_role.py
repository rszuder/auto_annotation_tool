"""User-facing distinction between working analysis and a frozen PZ3 experiment."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .pz3_comparison import comparison_context


def analysis_role(host, reference_info=None) -> dict:
    context = comparison_context(host)
    if context:
        info = reference_info if isinstance(reference_info, dict) else {}
        count = info.get("image_count")
        images = str(count) if isinstance(count, int) else "—"
        return {
            "controlled": True, "mode": "controlled",
            "title": "Eksperyment kontrolowany",
            "status": "CONTROLLED / SEALED",
            "description": (
                f"{context.get('name') or context['track_id']} · {context['track_id']}\n"
                f"SEALED · {images} obrazów · {len(context.get('model_ids') or [])} uczestników. "
                "Tor, modele i Ground Truth pochodzą z pieczęci PZ3."
            ),
            "source_label": "Tor eksperymentu",
            "models_label": "Uczestnicy eksperymentu",
            "start_label": "Uruchom porównanie",
            "report_title": "Eksperyment kontrolowany PZ3",
            "track_id": context["track_id"],
            "participant_ids": list(context.get("model_ids") or []),
        }
    return {
        "controlled": False, "mode": "working",
        "title": "Analiza robocza modeli",
        "status": "Tryb roboczy — bez pieczęci PZ3",
        "description": (
            "Porównuj wyniki treningów, walidacji i historyczne metryki modeli. "
            "Wyniki w tym miejscu nie stanowią kontrolowanego eksperymentu PZ3."
        ),
        "source_label": "Źródło analizy roboczej",
        "models_label": "Modele do analizy",
        "start_label": "Uruchom analizę roboczą",
        "report_title": "Analiza robocza",
        "track_id": "",
        "participant_ids": [],
    }


def open_pz3_tracks(host):
    """Navigate inside Z4; retain the target and any existing frozen context."""
    host._ensure_step4_tracks_tab_built()
    close = getattr(host, "_ranking_results_modal_close", None)
    if getattr(host, "_ranking_results_modal", None) is not None and callable(close):
        close()
    host.main_nb.select(host.tab_tracks)


class AnalysisRoleBanner:
    def __init__(self, host, parent):
        self.host = host
        self.frame = ttk.Frame(parent, style="Panel.TFrame")
        self.frame.columnconfigure(0, weight=1)
        self.title = ttk.Label(self.frame, style="Panel.TLabel", font=("Segoe UI", 11, "bold"))
        self.title.grid(row=0, column=0, sticky="w")
        self.status = ttk.Label(self.frame, style="PanelMuted.TLabel")
        self.status.grid(row=1, column=0, sticky="w", pady=(1, 3))
        self.description = ttk.Label(self.frame, style="PanelMuted.TLabel", justify=tk.LEFT, wraplength=700)
        self.description.grid(row=2, column=0, sticky="ew")
        self.cta = ttk.LabelFrame(self.frame, text="Eksperyment kontrolowany w PZ3", padding=(8, 5))
        self.cta.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        self.cta.columnconfigure(0, weight=1)
        self.cta_description = ttk.Label(
            self.cta, text="Formalne porównanie na wspólnym, zapieczętowanym Ground Truth rozpocznij w PZ3.",
            style="PanelMuted.TLabel", justify=tk.LEFT, wraplength=420)
        self.cta_description.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.button = ttk.Button(self.cta, text="Otwórz Tory testowe PZ3", command=lambda: open_pz3_tracks(host))
        self.button.grid(row=0, column=1, sticky="e")
        self.frame.bind("<Configure>", self._fit, add="+")
        self.refresh()

    def _fit(self, event):
        self.description.configure(wraplength=max(250, event.width - 10))
        self.cta_description.configure(wraplength=max(200, event.width - self.button.winfo_reqwidth() - 40))

    def refresh(self, reference_info=None):
        role = analysis_role(self.host, reference_info)
        self.title.configure(text=role["title"])
        self.status.configure(text=role["status"])
        self.description.configure(text=role["description"])
        if role["controlled"]:
            self.cta.grid_remove()
        else:
            self.cta.grid()


def refresh_analysis_role(host, reference_info=None):
    role = analysis_role(host, reference_info)
    banner = getattr(host, "_analysis_role_banner", None)
    if isinstance(banner, AnalysisRoleBanner):
        banner.refresh(reference_info)
    for attr, text in (
        ("_analysis_config_box", "Źródło i modele"),
        ("btn_open_rank_participants", role["models_label"]),
        ("btn_open_rank_track", role["source_label"]),
    ):
        widget = getattr(host, attr, None)
        if widget is not None:
            try:
                widget.configure(text=text)
            except tk.TclError:
                pass
    return role
