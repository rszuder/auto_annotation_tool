"""Kreator i przegląd torów testowych w Z4/PZ3.

Warstwa GUI nie wykonuje surowego SQL. Operacje idą przez
``EvaluationTrackService`` i ``RegistryRepository``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .pz3_source_ingest_ui import (
    choose_pz3_source_candidates,
    collect_folder_candidates,
    format_candidate_preflight_summary,
    preflight_deduplicate_candidates,
    prepend_candidate_preflight_summary,
)
from .source_filename_review_dialog import (
    review_source_image_directory,
    review_source_image_paths,
)

from ..campaign_manager import CAMPAIGN
from ..config import CONFIG, logger
from ..source_filename_contract import (
    format_filename_contract_report,
    validate_source_image_paths,
    validate_plate_crop_directory,
)
from ..registry import (
    EvaluationTrackError,
    EvaluationTrackService,
    RegistryRepository,
    project_id_from_folder_name,
)
from ..registry.track_service import (
    INTEGRITY_FAIL,
    INTEGRITY_PASS,
    INTEGRITY_UNKNOWN,
    STATUS_DRAFT,
    STATUS_RETIRED,
    STATUS_SEALED,
    STATUS_VERIFIED,
)
from ..registry.source_pool_audit import (
    STATUS_CLEAN as SOURCE_AUDIT_CLEAN,
    STATUS_DEPENDENT as SOURCE_AUDIT_DEPENDENT,
    STATUS_SUSPECT as SOURCE_AUDIT_SUSPECT,
    STATUS_UNKNOWN as SOURCE_AUDIT_UNKNOWN,
    SourcePoolIndependenceAuditService,
    format_source_pool_audit_summary,
)


@dataclass(frozen=True)
class TrackActionState:
    can_add_images: bool
    can_remove_images: bool
    can_set_ground_truth: bool
    can_verify: bool
    can_seal: bool
    can_check_integrity: bool
    can_clone: bool
    can_retire: bool
    can_delete_draft: bool


def action_state_for_status(status: str | None) -> TrackActionState:
    normalized = str(status or "").strip().upper()
    return TrackActionState(
        can_add_images=normalized == STATUS_DRAFT,
        can_remove_images=normalized == STATUS_DRAFT,
        can_set_ground_truth=normalized == STATUS_DRAFT,
        can_verify=normalized == STATUS_DRAFT,
        can_seal=normalized == STATUS_VERIFIED,
        can_check_integrity=normalized in {STATUS_SEALED, STATUS_RETIRED},
        can_clone=normalized in {STATUS_SEALED, STATUS_RETIRED},
        can_retire=normalized == STATUS_SEALED,
        can_delete_draft=normalized == STATUS_DRAFT,
    )


def can_prepare_ground_truth(
    track: Mapping[str, Any] | None,
    *,
    member_count: int | None = None,
) -> bool:
    if not isinstance(track, Mapping):
        return False
    if str(track.get("status") or "").strip().upper() != STATUS_DRAFT:
        return False
    if str(track.get("target") or "").strip().lower() != "plate":
        return False
    count = (
        int(member_count)
        if member_count is not None
        else int(track.get("member_count") or 0)
    )
    return count > 0


def reservation_policy_for_purpose(purpose: str | None) -> str:
    normalized = str(purpose or "").strip().lower()
    if normalized in {"final_test", "ranking"}:
        return "reserve_from_training"
    return "none"


def purpose_label(purpose: str | None) -> str:
    normalized = str(purpose or "").strip().lower()
    return {
        "final_test": "test końcowy",
        "ranking": "ranking modeli",
        "validation": "walidacja robocza",
    }.get(normalized, normalized or "-")


def target_label(target: str | None) -> str:
    normalized = str(target or "").strip().lower()
    return {
        "plate": "MT / tablice",
        "char": "MZ / znaki",
        "vehicle": "MP / pojazdy",
    }.get(normalized, normalized or "-")


def manual_gt_attestation_prompt(
    target: str | None,
) -> str:
    normalized = str(target or "").strip().lower()
    object_text = {
        "plate": "wszystkie widoczne tablice rejestracyjne",
        "char": "wszystkie widoczne znaki docelowe",
        "vehicle": "wszystkie widoczne pojazdy docelowe",
    }.get(
        normalized,
        "wszystkie widoczne obiekty docelowe",
    )
    return (
        "Potwierdź tylko po ręcznym przejrzeniu każdego obrazu "
        "toru.\n\n"
        "Czy potwierdzasz, że Ground Truth zawiera "
        f"{object_text} i że żaden taki obiekt nie został "
        "pominięty?\n\n"
        "To oświadczenie zostanie zapisane w manifeście "
        "i po zapieczętowaniu stanie się częścią protokołu "
        "eksperymentu."
    )


def requires_independent_acquisition_attestation(
    purpose: str | None,
) -> bool:
    return str(purpose or "").strip().lower() in {
        "final_test",
        "ranking",
    }


def independent_acquisition_attested(
    verification: Mapping[str, Any] | None,
) -> bool:
    data = verification if isinstance(verification, Mapping) else {}
    return bool(
        data.get("independent_acquisition")
        and data.get("not_derived_from_training_data")
        and str(
            data.get("acquisition_source_pool") or ""
        ).strip()
        and str(
            data.get("independent_acquisition_attested_at")
            or ""
        ).strip()
    )


def independent_acquisition_attestation_prompt() -> str:
    return (
        "Potwierdź TAK wyłącznie wtedy, gdy wszystkie obrazy "
        "tego toru pochodzą z nowej, niezależnie pozyskanej "
        "puli, która nie była użyta w train ani val ocenianych "
        "modeli.\n\n"
        "Żaden obraz toru nie może być przeróbką, ponownym "
        "eksportem, cropem, zmianą rozmiaru ani inną pochodną "
        "obrazu treningowego lub walidacyjnego.\n\n"
        "Oświadczenie zostanie zapisane w manifeście przed "
        "zapieczętowaniem i stanie się częścią niezmiennego "
        "odniesienia toru używanego przez eksperyment."
    )


def status_label(status: str | None) -> str:
    normalized = str(status or "").strip().upper()
    return {
        STATUS_DRAFT: "DRAFT",
        STATUS_VERIFIED: "VERIFIED",
        STATUS_SEALED: "SEALED",
        STATUS_RETIRED: "RETIRED",
    }.get(normalized, normalized or "-")


def _short_hash(value: str | None, length: int = 12) -> str:
    raw = str(value or "").strip()
    return raw[: max(4, int(length or 12))] if raw else "-"


class EvaluationTracksPanel:
    """Lekki panel PZ3. Cała logika trwałości pozostaje w registry/track_service."""

    PURPOSES = ("final_test", "ranking", "validation")
    TARGETS = ("plate", "char", "vehicle")

    def __init__(self, parent, host) -> None:
        self.parent = parent
        self.host = host
        self.app = getattr(host, "app", None)
        self.workspace = Path(CONFIG.WORKSPACE_DIR)
        self.service = EvaluationTrackService(self.workspace)
        self.repository: RegistryRepository = self.service.repository

        self.current_track_id = ""
        self._track_rows: dict[str, dict[str, Any]] = {}

        self.name_var = tk.StringVar(master=parent, value="")
        self.target_var = tk.StringVar(master=parent, value="plate")
        self.purpose_var = tk.StringVar(master=parent, value="ranking")
        self.scope_var = tk.StringVar(master=parent, value="global")
        self.project_hint_var = tk.StringVar(master=parent, value="")
        self.reservation_var = tk.StringVar(
            master=parent,
            value=reservation_policy_for_purpose("ranking"),
        )
        self.status_var = tk.StringVar(
            master=parent,
            value="Wybierz istniejący tor albo utwórz nowy DRAFT.",
        )

        self._build()
        self._sync_scope_options()
        self.refresh_tracks()

    def _build(self) -> None:
        root = ttk.Frame(self.parent, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Eksperymenty i tory referencyjne",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=(
                "ranking = wspólny materiał do porównania modeli; "
                "final_test = materiał używany dopiero po zakończeniu wyboru. "
                "DRAFT → źródła i GT → VERIFIED → SEALED → RETIRED."
            ),
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(
            header,
            text="Odśwież",
            command=self.refresh_tracks,
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        form = ttk.LabelFrame(root, text="Nowy eksperyment / tor", padding=10)
        form.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in range(8):
            form.columnconfigure(column, weight=0)
        form.columnconfigure(1, weight=2)

        ttk.Label(form, text="Nazwa").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Entry(form, textvariable=self.name_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 12)
        )

        ttk.Label(form, text="Target").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        self.target_combo = ttk.Combobox(
            form,
            textvariable=self.target_var,
            values=self.TARGETS,
            state="readonly",
            width=11,
        )
        self.target_combo.grid(row=0, column=3, sticky="w", padx=(0, 12))

        ttk.Label(form, text="Cel").grid(
            row=0, column=4, sticky="w", padx=(0, 6)
        )
        self.purpose_combo = ttk.Combobox(
            form,
            textvariable=self.purpose_var,
            values=self.PURPOSES,
            state="readonly",
            width=14,
        )
        self.purpose_combo.grid(row=0, column=5, sticky="w", padx=(0, 12))
        self.purpose_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._sync_reservation_policy(),
            add="+",
        )

        ttk.Label(form, text="Zakres").grid(
            row=0, column=6, sticky="w", padx=(0, 6)
        )
        self.scope_combo = ttk.Combobox(
            form,
            textvariable=self.scope_var,
            values=("global",),
            state="readonly",
            width=11,
        )
        self.scope_combo.grid(row=0, column=7, sticky="w")

        ttk.Label(
            form,
            textvariable=self.project_hint_var,
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
        ).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            form,
            textvariable=self.reservation_var,
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
        ).grid(
            row=1, column=4, columnspan=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(
            form,
            text="Utwórz DRAFT",
            command=self.create_draft,
        ).grid(
            row=1,
            column=6,
            columnspan=2,
            sticky="e",
            pady=(8, 0),
        )

        body = ttk.Frame(root)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="Tory", padding=6)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        columns = ("name", "ver", "target", "purpose", "status", "members")
        self.tree = ttk.Treeview(
            left,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=15,
        )
        headings = {
            "name": "Nazwa",
            "ver": "Wersja",
            "target": "Target",
            "purpose": "Cel",
            "status": "Status",
            "members": "Obrazy",
        }
        widths = {
            "name": 180,
            "ver": 58,
            "target": 90,
            "purpose": 110,
            "status": 90,
            "members": 62,
        }
        for key in columns:
            self.tree.heading(key, text=headings[key])
            self.tree.column(
                key,
                width=widths[key],
                minwidth=45,
                stretch=(key == "name"),
                anchor=tk.W if key == "name" else tk.CENTER,
            )
        yscroll = ttk.Scrollbar(
            left,
            orient=tk.VERTICAL,
            command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind(
            "<<TreeviewSelect>>",
            self._on_track_selected,
            add="+",
        )

        right = ttk.LabelFrame(body, text="Wybrany tor", padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)

        self.detail_text = tk.Text(
            right,
            height=9,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bd=1,
            relief=tk.SOLID,
        )
        self.detail_text.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        member_frame = ttk.Frame(right)
        member_frame.grid(row=1, column=0, sticky="nsew")
        member_frame.columnconfigure(0, weight=1)
        member_frame.rowconfigure(0, weight=1)
        member_columns = ("idx", "name", "source", "sha")
        self.member_tree = ttk.Treeview(
            member_frame,
            columns=member_columns,
            show="headings",
            selectmode="extended",
            height=8,
        )
        member_headings = {
            "idx": "#",
            "name": "Plik",
            "source": "source_image_id",
            "sha": "SHA-256",
        }
        member_widths = {
            "idx": 42,
            "name": 180,
            "source": 190,
            "sha": 110,
        }
        for key in member_columns:
            self.member_tree.heading(key, text=member_headings[key])
            self.member_tree.column(
                key,
                width=member_widths[key],
                minwidth=40,
                stretch=(key in {"name", "source"}),
                anchor=tk.W if key != "idx" else tk.CENTER,
            )
        member_scroll = ttk.Scrollbar(
            member_frame,
            orient=tk.VERTICAL,
            command=self.member_tree.yview,
        )
        self.member_tree.configure(yscrollcommand=member_scroll.set)
        self.member_tree.grid(row=0, column=0, sticky="nsew")
        member_scroll.grid(row=0, column=1, sticky="ns")
        self.member_tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self._refresh_remove_images_button_state(),
            add="+",
        )

        actions = ttk.Frame(right)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 8))
        self.btn_add_images = ttk.Button(
            actions,
            text="Dodaj obrazy…",
            command=self.add_images,
        )
        self.btn_remove_images = ttk.Button(
            actions,
            text="Usuń zaznaczone",
            command=self.remove_selected_images,
        )
        self.btn_set_gt = ttk.Button(
            actions,
            text="Wybierz GT (CVAT XML)",
            command=self.set_ground_truth,
        )
        self.btn_verify = ttk.Button(
            actions,
            text="Zweryfikuj",
            command=self.verify_track,
        )
        self.btn_seal = ttk.Button(
            actions,
            text="Zapieczętuj",
            command=self.seal_track,
        )
        self.btn_integrity = ttk.Button(
            actions,
            text="Sprawdź integralność",
            command=self.check_integrity,
        )
        self.btn_clone = ttk.Button(
            actions,
            text="Nowa wersja",
            command=self.clone_track,
        )
        self.btn_retire = ttk.Button(
            actions,
            text="Wycofaj",
            command=self.retire_track,
        )
        self.btn_delete_draft = ttk.Button(
            actions,
            text="Usuń DRAFT",
            command=self.delete_draft,
        )
        self.btn_open_experiment_sources = ttk.Button(
            actions,
            text="Pokaż katalog źródeł",
            command=self.open_experiment_sources,
        )
        self.btn_prepare_z2 = ttk.Button(
            actions,
            text="Przygotuj GT w Z2",
            command=self.prepare_ground_truth_in_z2,
        )
        for index, button in enumerate(
            (
                self.btn_add_images,
                self.btn_remove_images,
                self.btn_set_gt,
                self.btn_verify,
                self.btn_seal,
                self.btn_integrity,
                self.btn_clone,
                self.btn_retire,
                self.btn_delete_draft,
                self.btn_open_experiment_sources,
                self.btn_prepare_z2,
            )
        ):
            button.grid(
                row=index // 4,
                column=index % 4,
                sticky="ew",
                padx=(0 if index % 4 == 0 else 4, 0),
                pady=(0 if index < 4 else 4, 0),
            )
            actions.columnconfigure(index % 4, weight=1)

        ttk.Label(
            right,
            textvariable=self.status_var,
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
            wraplength=640,
        ).grid(row=3, column=0, sticky="new")

        self._apply_action_state(None)

    def _sync_scope_options(self) -> None:
        try:
            active_name = str(CAMPAIGN.get_active_project_name() or "").strip()
            active_root = CAMPAIGN.get_active_project_root_dir() if active_name else None
        except Exception:
            active_name = ""
            active_root = None

        if active_name and active_root:
            self.scope_combo.configure(values=("global", "project"))
            self.project_hint_var.set(
                f"Aktywny projekt: {active_name}. Zakres „project” przypisze tor do tego projektu."
            )
        else:
            self.scope_combo.configure(values=("global",))
            if self.scope_var.get() == "project":
                self.scope_var.set("global")
            self.project_hint_var.set(
                "Brak aktywnego projektu — nowy tor będzie globalny."
            )

    def _sync_reservation_policy(self) -> None:
        policy = reservation_policy_for_purpose(self.purpose_var.get())
        self.reservation_var.set(
            f"Polityka rezerwacji: {policy}"
        )

    def _ensure_project_owner(self) -> str | None:
        if self.scope_var.get() != "project":
            return None
        try:
            project_name = str(CAMPAIGN.get_active_project_name() or "").strip()
            project_root = CAMPAIGN.get_active_project_root_dir() if project_name else None
        except Exception:
            project_name = ""
            project_root = None
        if not project_name or project_root is None:
            raise EvaluationTrackError(
                "Zakres project wymaga aktywnego projektu."
            )

        project_root = Path(project_root)
        folder_name = project_root.name
        project_id = project_id_from_folder_name(folder_name)
        self.repository.upsert_project(
            project_id=project_id,
            campaign_key=project_name,
            folder_name=folder_name,
            display_name=project_name,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        return project_id

    def create_draft(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning(
                "Tory testowe",
                "Podaj nazwę toru.",
                parent=self.parent,
            )
            return
        try:
            owner_project_id = self._ensure_project_owner()
            track_id = self.service.create_draft(
                name=name,
                target=self.target_var.get(),
                purpose=self.purpose_var.get(),
                scope=self.scope_var.get(),
                owner_project_id=owner_project_id,
                reservation_policy=reservation_policy_for_purpose(
                    self.purpose_var.get()
                ),
            )
        except Exception as exc:
            self._show_error("Nie udało się utworzyć toru", exc)
            return

        self.name_var.set("")
        self.current_track_id = track_id
        self.refresh_tracks(select_track_id=track_id)
        self._set_status(
            "Utworzono DRAFT i przestrzeń eksperymentu. "
            "1) Otwórz źródła i dodaj niezależne obrazy, "
            "2) przygotuj GT w Z2, 3) dodaj obrazy i GT do toru, "
            "4) zweryfikuj i zapieczętuj."
        )

    def refresh_tracks(self, *, select_track_id: str | None = None) -> None:
        self._sync_scope_options()
        self._sync_reservation_policy()
        desired = str(
            select_track_id
            or self.current_track_id
            or ""
        ).strip()

        try:
            rows = self.service.list_tracks(include_retired=True)
        except Exception as exc:
            self._show_error("Nie udało się odczytać torów", exc)
            return

        self._track_rows = {
            str(row.get("track_id") or ""): dict(row)
            for row in rows
            if str(row.get("track_id") or "").strip()
        }
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for row in rows:
            track_id = str(row.get("track_id") or "")
            self.tree.insert(
                "",
                tk.END,
                iid=track_id,
                values=(
                    str(row.get("name") or "-"),
                    f"v{int(row.get('version') or 0)}",
                    target_label(row.get("target")),
                    purpose_label(row.get("purpose")),
                    status_label(row.get("status")),
                    int(row.get("member_count") or 0),
                ),
            )

        if desired and self.tree.exists(desired):
            self.tree.selection_set(desired)
            self.tree.focus(desired)
            self.tree.see(desired)
            self.current_track_id = desired
            self._refresh_selected_details()
        else:
            self.current_track_id = ""
            self._clear_selected_details()

    def _on_track_selected(self, _event=None) -> None:
        selected = self.tree.selection()
        self.current_track_id = str(selected[0]) if selected else ""
        self._refresh_selected_details()

    def _refresh_selected_details(self) -> None:
        track_id = self.current_track_id
        if not track_id:
            self._clear_selected_details()
            return
        try:
            track = self.service.get_track(track_id)
            members = self.service.list_members(track_id)
            verification = self.service.get_verification(
                track_id
            )
        except Exception as exc:
            self._show_error("Nie udało się odczytać toru", exc)
            return

        integrity = INTEGRITY_UNKNOWN
        if str(track.get("status") or "") in {STATUS_SEALED, STATUS_RETIRED}:
            try:
                integrity = self.service.verify_integrity(track_id).status
            except Exception:
                integrity = INTEGRITY_FAIL

        try:
            experiment_paths = self.service.get_experiment_workspace(
                track_id,
                create=(str(track.get("status") or "") == STATUS_DRAFT),
            )
        except Exception:
            experiment_paths = {}

        lines = [
            f"Nazwa: {track.get('name') or '-'}",
            f"ID: {track_id}",
            f"Wersja: v{int(track.get('version') or 0)}",
            f"Target: {target_label(track.get('target'))}",
            f"Cel: {purpose_label(track.get('purpose'))}",
            f"Zakres: {track.get('scope') or '-'}",
            f"Status: {status_label(track.get('status'))}",
            f"Integralność: {integrity}",
            f"Obrazy: {int(track.get('member_count') or 0)}",
            f"Obiekty GT: {int(track.get('object_count') or 0)}",
            f"GT: {track.get('gt_format') or '-'}",
            f"Kompletność GT (ręczna): {'TAK' if bool(verification.get('manual_gt_complete')) else 'NIE'}",
            f"Potwierdzenie GT: {verification.get('manual_gt_attested_at') or '-'}",
            (
                "Niezależne pozyskanie: "
                + (
                    "TAK"
                    if independent_acquisition_attested(
                        verification
                    )
                    else "NIE"
                )
            ),
            f"Pula niezależna: {verification.get('acquisition_source_pool') or '-'}",
            (
                "Potwierdzenie niezależności: "
                f"{verification.get('independent_acquisition_attested_at') or '-'}"
            ),
            f"Manifest: {_short_hash(track.get('manifest_sha256'))}",
            f"Seal: {_short_hash(track.get('seal_sha256'))}",
            f"Rezerwacja: {track.get('reservation_policy') or 'none'}",
            f"Źródła eksperymentu: {experiment_paths.get('source_images') or '-'}",
            f"Runy anotacji: {experiment_paths.get('annotation_runs') or '-'}",
            f"Ścieżka toru: {track.get('relative_path') or '-'}",
        ]
        if track.get("parent_track_id"):
            lines.append(f"Poprzednia wersja: {track.get('parent_track_id')}")

        self._set_detail_text("\n".join(lines))
        for iid in self.member_tree.get_children():
            self.member_tree.delete(iid)
        for row in members:
            self.member_tree.insert(
                "",
                tk.END,
                values=(
                    int(row.get("member_index") or 0),
                    str(row.get("original_name") or "-"),
                    str(row.get("source_image_id") or "-"),
                    _short_hash(row.get("sha256"), 16),
                ),
            )

        self._apply_action_state(
            track,
            member_count=len(members),
        )
        self._set_status(
            self._status_hint_for_track(track, integrity)
        )

    def _clear_selected_details(self) -> None:
        self._set_detail_text(
            "Wybierz tor z listy. Operacje edycyjne są dostępne wyłącznie "
            "dla DRAFT."
        )
        for iid in self.member_tree.get_children():
            self.member_tree.delete(iid)
        self._apply_action_state(None)

    def open_experiment_sources(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        try:
            track = self.service.get_track(track_id)
            if str(track.get("status") or "").upper() != STATUS_DRAFT:
                raise EvaluationTrackError(
                    "Katalog źródeł jest roboczy i jest dostępny dla DRAFT."
                )
            paths = self.service.get_experiment_workspace(track_id)
            source_dir = Path(paths["source_images"])
            source_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._show_error(
                "Nie udało się otworzyć źródeł eksperymentu",
                exc,
            )
            return

        try:
            os.startfile(str(source_dir))
        except Exception:
            messagebox.showinfo(
                "Źródła eksperymentu",
                str(source_dir),
                parent=self.parent,
            )
        self._set_status(
            "Umieść tutaj wyłącznie niezależne obrazy tego eksperymentu. "
            "Nie eksportuj ich do datasetu treningowego."
        )

    def prepare_ground_truth_in_z2(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        try:
            track = self.service.get_track(track_id)
            if str(track.get("status") or "").upper() != STATUS_DRAFT:
                raise EvaluationTrackError(
                    "Ground Truth przygotowujemy przed weryfikacją, w DRAFT."
                )
            if str(track.get("target") or "").lower() != "plate":
                raise EvaluationTrackError(
                    "Automatyczne przekazanie do Z2 jest obecnie dostępne "
                    "dla MT / tablic. Dla innych targetów użyj właściwego "
                    "narzędzia anotacyjnego i wskaż gotowy GT."
                )
            members = self.service.list_members(track_id)
            if not members:
                raise EvaluationTrackError(
                    "Najpierw użyj „Dodaj obrazy”, aby ustalić "
                    "niezależną pulę eksperymentu."
                )
            context = self.service.activate_z2_context(track_id)
        except Exception as exc:
            self._show_error(
                "Nie udało się przygotować kontekstu Z2",
                exc,
            )
            return

        source_dir = Path(context["source_dir"])
        image_count = sum(
            1
            for path in source_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
        )
        messagebox.showinfo(
            "Eksperyment → Z2",
            (
                f"Aktywowano eksperyment „{track.get('name') or track_id}”.\n\n"
                f"Źródła: {context['source_dir']}\n"
                f"Runy Z2: {context['annotation_dir']}\n\n"
                "Z2 będzie pracować w trybie swobodnym, ale run otrzyma "
                "znacznik eksperymentalny. Eksport tego runu do "
                "4_training_datasets jest twardo zablokowany.\n\n"
                f"Ustalona pula zawiera {image_count} obrazów. "
                "Przejdź do Z2 i przygotuj Ground Truth; "
                "jeżeli używasz autoanotacji, wykonaj pełną ręczną korektę."
            ),
            parent=self.parent,
        )
        self._set_status(
            "Aktywny kontekst eksperymentalny Z2: "
            f"{track.get('name') or track_id}. Eksport treningowy zablokowany."
        )
        try:
            app = self.app
            annotation_tab = getattr(app, "tabs", {}).get("annotation")
            if annotation_tab is not None:
                app.notebook.select(annotation_tab.frame)
        except Exception:
            pass

    def add_images(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return

        try:
            track = self.service.get_track(track_id)
        except Exception as exc:
            self._show_error(
                "Nie udało się odczytać DRAFT-u",
                exc,
            )
            return

        selection = choose_pz3_source_candidates(self.parent)
        if selection is None:
            return

        if selection.mode == "folder":
            if not review_source_image_directory(
                self.parent,
                selection.source_dir,
                recursive=False,
                title="Podgląd i korekta nazw — PZ3",
            ):
                return
            selected_paths = collect_folder_candidates(selection.source_dir)
        else:
            review_result = review_source_image_paths(
                self.parent,
                selection.paths,
                title="Podgląd i korekta nazw — PZ3",
            )
            if not review_result.ok:
                return
            selected_paths = tuple(review_result.accepted_paths)

        if not selected_paths:
            messagebox.showinfo(
                "Dodaj obrazy",
                "Po korekcie/odrzuceniu nie pozostały żadne obrazy do dodania.",
                parent=self.parent,
            )
            return

        try:
            existing_members = self.service.list_members(track_id)
        except Exception:
            existing_members = []

        resolver = getattr(
            self.repository,
            "list_source_image_ids_by_sha256",
            None,
        )
        duplicate_preflight = preflight_deduplicate_candidates(
            selected_paths,
            existing_members,
            source_ids_for_sha=(resolver if callable(resolver) else None),
        )
        duplicate_summary = format_candidate_preflight_summary(
            duplicate_preflight
        )
        selected = tuple(str(path) for path in duplicate_preflight.candidates)

        if not selected:
            messagebox.showinfo(
                "Brak nowych kandydatów",
                duplicate_summary,
                parent=self.parent,
            )
            self._refresh_selected_details()
            return

        track_target = str(
            track.get("target") or ""
        ).strip().lower()
        if track_target == "char":
            crop_parents = {
                str(Path(raw).parent.resolve())
                for raw in selected
            }
            if len(crop_parents) != 1:
                messagebox.showerror(
                    "Nieprawidłowy zasób cropów",
                    (
                        "Cropy MZ muszą pochodzić z jednego katalogu "
                        "images powiązanego z jednym metadata.json."
                    ),
                    parent=self.parent,
                )
                return
            filename_report = validate_plate_crop_directory(
                Path(next(iter(crop_parents)))
            )
        else:
            filename_report = validate_source_image_paths(selected)

        if not filename_report.valid:
            messagebox.showerror(
                "Nieprawidłowe nazwy obrazów",
                (
                    "Audyt niezależności nie został uruchomiony, "
                    "bo wybrana pula nie spełnia kontraktu nazw.\n\n"
                    + format_filename_contract_report(
                        filename_report
                    )
                ),
                parent=self.parent,
            )
            self._set_status(
                "Nie dodano obrazów: najpierw popraw nazwy plików."
            )
            return

        self._set_status(
            "Audytuję wybraną pulę względem całej zarejestrowanej "
            "historii train/val tego targetu..."
        )
        try:
            self.parent.configure(cursor="watch")
            self.parent.update_idletasks()
        except Exception:
            pass

        try:
            auditor = SourcePoolIndependenceAuditService(
                self.workspace,
                repository=self.repository,
            )
            report = auditor.audit(
                selected,
                target=str(track.get("target") or ""),
                purpose=str(track.get("purpose") or ""),
                track_id=track_id,
            )
            experiment_paths = self.service.get_experiment_workspace(
                track_id
            )
            report_dir = Path(
                experiment_paths["experiment_results"]
            )
        except Exception as exc:
            self._show_error(
                "Audyt puli obrazów nie powiódł się",
                exc,
            )
            return
        finally:
            try:
                self.parent.configure(cursor="")
            except Exception:
                pass

        summary = prepend_candidate_preflight_summary(duplicate_summary, format_source_pool_audit_summary(report))
        purpose = str(track.get("purpose") or "").strip().lower()

        if (
            report.reference_count <= 0
            and purpose in {"ranking", "final_test"}
        ):
            report_path = auditor.save_report(
                report,
                report_dir,
                decision={
                    "status": "blocked_no_training_reference",
                    "accepted_count": 0,
                },
            )
            messagebox.showerror(
                "Audyt niezależności puli",
                (
                    summary
                    + "\n\nDla rankingu/testu końcowego brak "
                    "zarejestrowanego train/val uniemożliwia "
                    "kontrolowany preflight.\n\nRaport:\n"
                    + str(report_path)
                ),
                parent=self.parent,
            )
            self._set_status(
                "Nie dodano obrazów: brak podstawy do audytu train/val."
            )
            return

        clean_items = list(
            report.items_with_status(SOURCE_AUDIT_CLEAN)
        )
        suspect_items = list(
            report.items_with_status(SOURCE_AUDIT_SUSPECT)
        )
        dependent_items = list(
            report.items_with_status(SOURCE_AUDIT_DEPENDENT)
        )
        unknown_items = list(
            report.items_with_status(SOURCE_AUDIT_UNKNOWN)
        )

        include_suspects = False
        cancelled = False

        if suspect_items:
            choice = messagebox.askyesnocancel(
                "Audyt niezależności puli",
                (
                    summary
                    + "\n\nZALEŻNE i nierozstrzygnięte pliki "
                    "zostaną odrzucone automatycznie.\n\n"
                    "TAK — odrzuć również PODEJRZANE POCHODNE "
                    "(zalecane dla ranking/final_test).\n"
                    "NIE — dodaj podejrzane razem z plikami bez "
                    "wykrytej zależności.\n"
                    "ANULUJ — nie dodawaj nic."
                ),
                parent=self.parent,
            )
            if choice is None:
                cancelled = True
            elif choice is False:
                include_suspects = True
        else:
            proceed = messagebox.askyesno(
                "Audyt niezależności puli",
                (
                    summary
                    + "\n\nZALEŻNE i nierozstrzygnięte pliki "
                    "zostaną odrzucone automatycznie.\n\n"
                    f"Dodać {len(clean_items)} obrazów bez "
                    "wykrytej zależności?"
                ),
                parent=self.parent,
            )
            cancelled = not proceed

        if cancelled:
            report_path = auditor.save_report(
                report,
                report_dir,
                decision={
                    "status": "cancelled",
                    "accepted_count": 0,
                    "dependent_rejected": len(dependent_items),
                    "suspect_count": len(suspect_items),
                    "unknown_rejected": len(unknown_items),
                },
            )
            self._set_status(
                "Audyt zakończony; użytkownik anulował ingest. "
                f"Raport: {report_path}"
            )
            return

        accepted_items = list(clean_items)
        if include_suspects:
            accepted_items.extend(suspect_items)

        added = 0
        errors: list[str] = []
        ingested_names: list[str] = []
        for item in accepted_items:
            path = Path(item.source_path)
            try:
                self.service.ingest_member_source(
                    track_id,
                    path,
                    original_name=item.original_name,
                )
                added += 1
                ingested_names.append(item.original_name)
            except Exception as exc:
                errors.append(
                    f"{item.original_name}: {exc}"
                )

        decision = {
            "status": "accepted",
            "suspects_included": bool(include_suspects),
            "accepted_for_ingest_count": len(accepted_items),
            "ingested_count": added,
            "ingested_names": ingested_names,
            "dependent_rejected": len(dependent_items),
            "suspect_rejected": (
                0 if include_suspects else len(suspect_items)
            ),
            "unknown_rejected": len(unknown_items),
            "ingest_errors": errors,
        }
        report_path = auditor.save_report(
            report,
            report_dir,
            decision=decision,
        )

        self.refresh_tracks(
            select_track_id=track_id
        )

        if errors:
            messagebox.showwarning(
                "Eksperymenty — ingest po audycie",
                (
                    f"Dodano {added} obrazów po audycie.\n"
                    f"Pominięto dodatkowo {len(errors)} z powodu "
                    "błędów ingestu.\n\n"
                    + "\n".join(errors[:12])
                    + "\n\nRaport:\n"
                    + str(report_path)
                ),
                parent=self.parent,
            )
        else:
            messagebox.showinfo(
                "Audyt i ingest zakończone",
                (
                    summary
                    + "\n\n"
                    f"Do DRAFT-u dodano: {added}.\n"
                    f"Twardo zależne odrzucono: "
                    f"{len(dependent_items)}.\n"
                    f"Podejrzane odrzucono: "
                    f"{0 if include_suspects else len(suspect_items)}.\n"
                    f"Nierozstrzygnięte odrzucono: "
                    f"{len(unknown_items)}.\n\n"
                    f"Raport:\n{report_path}"
                ),
                parent=self.parent,
            )
            self._set_status(
                f"Audyt zakończony. Dodano {added} obrazów; "
                f"zależne={len(dependent_items)}, "
                f"podejrzane={len(suspect_items)}, "
                f"nierozstrzygnięte={len(unknown_items)}. "
                "Możesz teraz przygotować Ground Truth w Z2."
            )

    def remove_selected_images(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return

        try:
            track = self.service.get_track(track_id)
        except Exception as exc:
            self._show_error("Nie udało się odczytać toru", exc)
            return

        if str(track.get("status") or "").strip().upper() != STATUS_DRAFT:
            messagebox.showwarning(
                "Usuwanie obrazów",
                "Obrazy można usuwać wyłącznie z toru DRAFT.",
                parent=self.parent,
            )
            return

        selected_iids = tuple(self.member_tree.selection())
        if not selected_iids:
            messagebox.showinfo(
                "Usuwanie obrazów",
                "Zaznacz jeden lub kilka obrazów na liście.",
                parent=self.parent,
            )
            return

        member_indices: list[int] = []
        names: list[str] = []
        for iid in selected_iids:
            values = self.member_tree.item(iid, "values")
            if not values:
                continue
            try:
                member_indices.append(int(values[0]))
            except Exception:
                continue
            if len(values) > 1:
                names.append(str(values[1] or ""))

        if not member_indices:
            messagebox.showwarning(
                "Usuwanie obrazów",
                "Nie udało się odczytać zaznaczonych członków toru.",
                parent=self.parent,
            )
            return

        gt_note = ""
        if str(track.get("gt_relative_path") or "").strip():
            gt_note = (
                "\n\nTen DRAFT ma już przypisane Ground Truth. "
                "Zmiana składu toru unieważni GT; jego plik zostanie "
                "zachowany w archiwum _invalidated_member_change. "
                "GT trzeba będzie przygotować ponownie."
            )

        context_note = (
            "\n\nJeśli ten tor był przygotowany w Z2, aktywny kontekst "
            "Z2 zostanie unieważniony i trzeba będzie użyć "
            "„Przygotuj GT w Z2” ponownie."
        )

        preview = "\n".join(
            f"• {name}" for name in names[:10] if name
        )
        if len(names) > 10:
            preview += f"\n• … i {len(names) - 10} kolejnych"

        confirmed = messagebox.askyesno(
            "Usuń obrazy z DRAFT",
            (
                f"Usunąć {len(member_indices)} zaznaczonych obrazów "
                "z bieżącego toru DRAFT?\n\n"
                f"{preview}\n\n"
                "Oryginalne pliki użytkownika nie zostaną usunięte. "
                "Usunięte zostaną tylko wewnętrzne kopie należące "
                "do tego DRAFT."
                + gt_note
                + context_note
            ),
            parent=self.parent,
        )
        if not confirmed:
            return

        try:
            summary = self.service.remove_members(
                track_id,
                member_indices,
            )
        except Exception as exc:
            self._show_error("Nie udało się usunąć obrazów", exc)
            return

        removed_count = int(summary.get("removed_count") or 0)
        self.refresh_tracks(select_track_id=track_id)

        notes = [
            f"Usunięto z DRAFT: {removed_count} obrazów."
        ]
        if summary.get("ground_truth_invalidated"):
            notes.append(
                "Ground Truth unieważniono — przygotuj GT ponownie."
            )
        if summary.get("z2_context_invalidated"):
            notes.append(
                "Kontekst Z2 unieważniono — uruchom „Przygotuj GT w Z2” ponownie."
            )
        self._set_status(" ".join(notes))

    def set_ground_truth(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        dialog_options = {}
        try:
            experiment_paths = self.service.get_experiment_workspace(track_id)
            annotation_dir = Path(experiment_paths["annotation_runs"])
            if annotation_dir.is_dir():
                dialog_options["initialdir"] = str(annotation_dir)
        except Exception:
            pass
        path = filedialog.askopenfilename(
            title="Wybierz Ground Truth CVAT XML",
            filetypes=[
                ("CVAT XML", "*.xml"),
                ("Wszystkie pliki", "*.*"),
            ],
            parent=self.parent,
            **dialog_options,
        )
        if not path:
            return
        try:
            self.service.set_ground_truth(
                track_id,
                path,
                gt_format="cvat_xml",
            )
        except Exception as exc:
            self._show_error("Nie udało się zapisać Ground Truth", exc)
            return
        self.refresh_tracks(select_track_id=track_id)
        self._set_status(
            "Zapisano Ground Truth. Możesz uruchomić weryfikację DRAFT."
        )

    def verify_track(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return

        try:
            track = self.service.get_track(track_id)
        except Exception as exc:
            self._show_error(
                "Nie udało się odczytać toru",
                exc,
            )
            return

        if not messagebox.askyesno(
            "Ręczne potwierdzenie kompletności GT",
            manual_gt_attestation_prompt(
                track.get("target")
            ),
            parent=self.parent,
        ):
            self._set_status(
                "Weryfikacja anulowana — nie zapisano "
                "potwierdzenia kompletności Ground Truth."
            )
            return

        try:
            result = self.service.verify(
                track_id,
                manual_gt_complete=True,
            )
        except Exception as exc:
            self._show_error(
                "Weryfikacja toru nie powiodła się",
                exc,
            )
            return

        self.refresh_tracks(select_track_id=track_id)
        self._set_status(
            "Tor zweryfikowany z ręcznym potwierdzeniem "
            "kompletności GT. "
            f"Obiekty GT: "
            f"{int(result.get('object_count') or 0)}, "
            f"pose_corner_ready="
            f"{bool(result.get('pose_corner_ready'))}."
        )

    def seal_track(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return

        try:
            track = self.service.get_track(track_id)
            verification = self.service.get_verification(
                track_id
            )
        except Exception as exc:
            self._show_error(
                "Nie udało się odczytać toru",
                exc,
            )
            return

        if not bool(
            verification.get("manual_gt_complete")
        ):
            if not messagebox.askyesno(
                "Brak potwierdzenia kompletności GT",
                (
                    "Ten tor ma walidację strukturalną, ale nie "
                    "ma ręcznego potwierdzenia kompletności "
                    "Ground Truth.\n\n"
                    + manual_gt_attestation_prompt(
                        track.get("target")
                    )
                ),
                parent=self.parent,
            ):
                return
            try:
                self.service.attest_ground_truth_completeness(
                    track_id
                )
            except Exception as exc:
                self._show_error(
                    "Nie udało się zapisać "
                    "potwierdzenia kompletności GT",
                    exc,
                )
                return

        needs_independent_attestation = (
            requires_independent_acquisition_attestation(
                track.get("purpose")
            )
        )
        has_independent_attestation = (
            independent_acquisition_attested(
                verification
            )
        )

        if (
            needs_independent_attestation
            and not has_independent_attestation
        ):
            if messagebox.askyesno(
                "Niezależne pozyskanie obrazów",
                independent_acquisition_attestation_prompt(),
                parent=self.parent,
            ):
                try:
                    verification = (
                        self.service.attest_independent_acquisition(
                            track_id,
                            source_pool=(
                                "new_independent_acquisition"
                            ),
                        )
                    )
                    has_independent_attestation = (
                        independent_acquisition_attested(
                            verification
                        )
                    )
                except Exception as exc:
                    self._show_error(
                        "Nie udało się zapisać potwierdzenia "
                        "niezależnego pozyskania",
                        exc,
                    )
                    return

        seal_warning = ""
        if (
            needs_independent_attestation
            and not has_independent_attestation
        ):
            seal_warning = (
                "\n\nUWAGA: tor zostanie zapieczętowany bez "
                "potwierdzenia niezależnego pozyskania. "
                "Dla modeli, których historyczny train/val ma "
                "rodowód exact_hash_only, audyt niezależności "
                "pozostanie UNKNOWN i tryb controlled będzie "
                "zablokowany."
            )

        if not messagebox.askyesno(
            "Zapieczętować tor?",
            "Po zapieczętowaniu zawartości toru nie będzie "
            "można edytować. Zmiany wymagają utworzenia "
            "nowej wersji."
            + seal_warning,
            parent=self.parent,
        ):
            return

        try:
            result = self.service.seal(track_id)
        except Exception as exc:
            self._show_error(
                "Nie udało się zapieczętować toru",
                exc,
            )
            return

        self.refresh_tracks(select_track_id=track_id)
        self._set_status(
            "Tor zapieczętowany z ręcznym "
            "potwierdzeniem kompletności GT. "
            "Niezależne pozyskanie: "
            f"{'TAK' if has_independent_attestation else 'NIE'}. "
            f"Integralność: {result.status}."
        )

    def check_integrity(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        try:
            result = self.service.verify_integrity(track_id)
        except Exception as exc:
            self._show_error("Nie udało się sprawdzić integralności", exc)
            return

        text = (
            f"Integralność toru: {result.status}"
            + (
                "\n\n" + "\n".join(result.issues)
                if result.issues
                else ""
            )
        )
        if result.status == INTEGRITY_PASS:
            messagebox.showinfo(
                "Integralność toru",
                text,
                parent=self.parent,
            )
        else:
            messagebox.showwarning(
                "Integralność toru",
                text,
                parent=self.parent,
            )
        self._refresh_selected_details()

    def clone_track(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        try:
            clone_id = self.service.clone_new_version(track_id)
        except Exception as exc:
            self._show_error("Nie udało się utworzyć nowej wersji", exc)
            return
        self.current_track_id = clone_id
        self.refresh_tracks(select_track_id=clone_id)
        self._set_status(
            "Utworzono nową wersję DRAFT na podstawie zapieczętowanego toru."
        )


    def delete_draft(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return

        try:
            track = self.service.get_track(track_id)
        except Exception as exc:
            self._show_error(
                "Nie udało się odczytać toru",
                exc,
            )
            return

        if str(track.get("status") or "").upper() != STATUS_DRAFT:
            messagebox.showwarning(
                "Tory testowe",
                "Fizycznie usunąć można wyłącznie tor DRAFT. "
                "Tor SEALED należy wycofać do RETIRED.",
                parent=self.parent,
            )
            return

        name = str(
            track.get("name") or track_id
        ).strip()
        if not messagebox.askyesno(
            "Usunąć DRAFT?",
            (
                f"Tor „{name}” nie został zapieczętowany.\n\n"
                "Usunięty zostanie jego katalog roboczy oraz "
                "wpis z rejestru. Tożsamości źródłowych obrazów "
                "pozostaną w rejestrze do wykrywania duplikatów.\n\n"
                "Tej operacji nie można cofnąć."
            ),
            parent=self.parent,
        ):
            return

        try:
            self.service.delete_draft(track_id)
        except Exception as exc:
            self._show_error(
                "Nie udało się usunąć DRAFT",
                exc,
            )
            return

        self.current_track_id = ""
        self.refresh_tracks()
        self._set_status(
            f"Usunięto DRAFT: {name}."
        )

    def retire_track(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        if not messagebox.askyesno(
            "Wycofać tor?",
            "Tor pozostanie dostępny historycznie, ale otrzyma status RETIRED.",
            parent=self.parent,
        ):
            return
        try:
            self.service.retire(track_id)
        except Exception as exc:
            self._show_error("Nie udało się wycofać toru", exc)
            return
        self.refresh_tracks(select_track_id=track_id)
        self._set_status("Tor oznaczono jako RETIRED.")

    def _require_current_track(self) -> str:
        track_id = str(self.current_track_id or "").strip()
        if not track_id:
            messagebox.showwarning(
                "Tory testowe",
                "Najpierw wybierz tor z listy.",
                parent=self.parent,
            )
        return track_id

    def _refresh_remove_images_button_state(self) -> None:
        button = getattr(self, "btn_remove_images", None)
        tree = getattr(self, "member_tree", None)
        if button is None or tree is None:
            return
        row = self._track_rows.get(self.current_track_id, {})
        is_draft = (
            str(row.get("status") or "").strip().upper()
            == STATUS_DRAFT
        )
        try:
            has_selection = bool(tree.selection())
        except Exception:
            has_selection = False
        try:
            button.configure(
                state=(
                    tk.NORMAL
                    if is_draft and has_selection
                    else tk.DISABLED
                )
            )
        except Exception:
            pass

    def _apply_action_state(
        self,
        track: Mapping[str, Any] | None,
        *,
        member_count: int | None = None,
    ) -> None:
        state = action_state_for_status(
            track.get("status") if isinstance(track, Mapping) else ""
        )
        mapping = (
            (self.btn_add_images, state.can_add_images),
            (self.btn_remove_images, state.can_remove_images),
            (self.btn_set_gt, state.can_set_ground_truth),
            (self.btn_verify, state.can_verify),
            (self.btn_seal, state.can_seal),
            (self.btn_integrity, state.can_check_integrity),
            (self.btn_clone, state.can_clone),
            (self.btn_retire, state.can_retire),
            (self.btn_delete_draft, state.can_delete_draft),
            (self.btn_open_experiment_sources, state.can_add_images),
            (
                self.btn_prepare_z2,
                can_prepare_ground_truth(
                    track,
                    member_count=member_count,
                ),
            ),
        )
        for button, enabled in mapping:
            try:
                button.configure(
                    state=tk.NORMAL if enabled else tk.DISABLED
                )
            except Exception:
                pass
        self._refresh_remove_images_button_state()

    def _status_hint_for_track(
        self,
        track: Mapping[str, Any],
        integrity: str,
    ) -> str:
        status = str(track.get("status") or "").upper()
        if status == STATUS_DRAFT:
            try:
                member_count = len(
                    self.service.list_members(
                        str(track.get("track_id") or "")
                    )
                )
            except Exception:
                member_count = int(
                    track.get("member_count") or 0
                )
            if member_count <= 0:
                return (
                    "DRAFT — krok 1/4: użyj „Dodaj obrazy”. "
                    "Program utworzy kontrolowaną pulę źródłową eksperymentu."
                )
            if not str(track.get("gt_relative_path") or "").strip():
                return (
                    f"DRAFT — krok 2/4: pula zawiera {member_count} obrazów. "
                    "Użyj „Przygotuj GT w Z2”, a po zakończeniu wskaż "
                    "gotowy annotations.xml jako Ground Truth."
                )
            return (
                "DRAFT — krok 3/4: obrazy i Ground Truth są podłączone. "
                "Uruchom weryfikację; po niej pozostanie zapieczętowanie toru."
            )
        if status == STATUS_VERIFIED:
            return (
                "VERIFIED — krok 4/4: dane przeszły walidację. "
                "Zapieczętuj tor, aby stał się kontrolowanym odniesieniem."
            )
        if status == STATUS_SEALED:
            return (
                f"SEALED: integralność={integrity}. "
                "Zmiany wymagają utworzenia nowej wersji."
            )
        if status == STATUS_RETIRED:
            return (
                f"RETIRED: integralność={integrity}. "
                "Tor pozostaje częścią historii eksperymentów."
            )
        return "Nieznany stan toru."

    def _set_detail_text(self, text: str) -> None:
        try:
            self.detail_text.configure(state=tk.NORMAL)
            self.detail_text.delete("1.0", tk.END)
            self.detail_text.insert("1.0", text)
            self.detail_text.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _set_status(self, text: str) -> None:
        self.status_var.set(str(text or ""))
        try:
            update_status = getattr(self.app, "update_status", None)
            if callable(update_status):
                update_status(str(text or ""), "info")
        except Exception:
            pass

    def _show_error(self, title: str, exc: Exception) -> None:
        logger.error(f"{title}: {exc}")
        messagebox.showerror(
            "Tory testowe",
            f"{title}:\n\n{exc}",
            parent=self.parent,
        )
        self._set_status(f"{title}: {exc}")


def build_evaluation_tracks_tab(host, parent) -> EvaluationTracksPanel:
    panel = EvaluationTracksPanel(parent, host)
    host.evaluation_tracks_panel = panel
    return panel
