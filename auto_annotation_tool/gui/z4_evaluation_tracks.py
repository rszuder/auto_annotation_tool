"""Kreator i przegląd torów testowych w Z4/PZ3.

Warstwa GUI nie wykonuje surowego SQL. Operacje idą przez
``EvaluationTrackService`` i ``RegistryRepository``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Mapping

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..campaign_manager import CAMPAIGN
from ..config import CONFIG, logger
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


@dataclass(frozen=True)
class TrackActionState:
    can_add_images: bool
    can_set_ground_truth: bool
    can_verify: bool
    can_seal: bool
    can_check_integrity: bool
    can_clone: bool
    can_retire: bool


def action_state_for_status(status: str | None) -> TrackActionState:
    normalized = str(status or "").strip().upper()
    return TrackActionState(
        can_add_images=normalized == STATUS_DRAFT,
        can_set_ground_truth=normalized == STATUS_DRAFT,
        can_verify=normalized == STATUS_DRAFT,
        can_seal=normalized == STATUS_VERIFIED,
        can_check_integrity=normalized in {STATUS_SEALED, STATUS_RETIRED},
        can_clone=normalized in {STATUS_SEALED, STATUS_RETIRED},
        can_retire=normalized == STATUS_SEALED,
    )


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
        self.purpose_var = tk.StringVar(master=parent, value="final_test")
        self.scope_var = tk.StringVar(master=parent, value="global")
        self.project_hint_var = tk.StringVar(master=parent, value="")
        self.reservation_var = tk.StringVar(
            master=parent,
            value=reservation_policy_for_purpose("final_test"),
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
            text="Tory testowe",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=(
                "DRAFT → VERIFIED → SEALED → RETIRED. "
                "Po zapieczętowaniu zawartość toru nie jest modyfikowana."
            ),
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(
            header,
            text="Odśwież",
            command=self.refresh_tracks,
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        form = ttk.LabelFrame(root, text="Nowy tor", padding=10)
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

        actions = ttk.Frame(right)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 8))
        self.btn_add_images = ttk.Button(
            actions,
            text="Dodaj obrazy",
            command=self.add_images,
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
        for index, button in enumerate(
            (
                self.btn_add_images,
                self.btn_set_gt,
                self.btn_verify,
                self.btn_seal,
                self.btn_integrity,
                self.btn_clone,
                self.btn_retire,
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
            "Utworzono DRAFT. Dodaj obrazy i kompletne Ground Truth, "
            "a następnie uruchom weryfikację."
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
            f"Manifest: {_short_hash(track.get('manifest_sha256'))}",
            f"Seal: {_short_hash(track.get('seal_sha256'))}",
            f"Rezerwacja: {track.get('reservation_policy') or 'none'}",
            f"Ścieżka: {track.get('relative_path') or '-'}",
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

        self._apply_action_state(track)
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

    def add_images(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        extensions = " ".join(
            f"*{ext}" for ext in sorted(CONFIG.IMAGE_EXTENSIONS)
        )
        selected = filedialog.askopenfilenames(
            title="Dodaj obrazy do toru",
            filetypes=[
                ("Obrazy", extensions),
                ("Wszystkie pliki", "*.*"),
            ],
            parent=self.parent,
        )
        if not selected:
            return

        added = 0
        errors: list[str] = []
        for raw in selected:
            path = Path(raw)
            try:
                self.service.add_member(
                    track_id,
                    path,
                    original_name=path.name,
                )
                added += 1
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")

        self.refresh_tracks(select_track_id=track_id)
        if errors:
            messagebox.showwarning(
                "Tory testowe",
                f"Dodano {added} plików. Pominięto {len(errors)}:\n\n"
                + "\n".join(errors[:12]),
                parent=self.parent,
            )
        else:
            self._set_status(f"Dodano {added} obrazów do toru.")

    def set_ground_truth(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        path = filedialog.askopenfilename(
            title="Wybierz Ground Truth CVAT XML",
            filetypes=[
                ("CVAT XML", "*.xml"),
                ("Wszystkie pliki", "*.*"),
            ],
            parent=self.parent,
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

        if not messagebox.askyesno(
            "Zapieczętować tor?",
            "Po zapieczętowaniu zawartości toru nie będzie "
            "można edytować. Zmiany wymagają utworzenia "
            "nowej wersji.",
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

    def _apply_action_state(self, track: Mapping[str, Any] | None) -> None:
        state = action_state_for_status(
            track.get("status") if isinstance(track, Mapping) else ""
        )
        mapping = (
            (self.btn_add_images, state.can_add_images),
            (self.btn_set_gt, state.can_set_ground_truth),
            (self.btn_verify, state.can_verify),
            (self.btn_seal, state.can_seal),
            (self.btn_integrity, state.can_check_integrity),
            (self.btn_clone, state.can_clone),
            (self.btn_retire, state.can_retire),
        )
        for button, enabled in mapping:
            try:
                button.configure(
                    state=tk.NORMAL if enabled else tk.DISABLED
                )
            except Exception:
                pass

    def _status_hint_for_track(
        self,
        track: Mapping[str, Any],
        integrity: str,
    ) -> str:
        status = str(track.get("status") or "").upper()
        if status == STATUS_DRAFT:
            return (
                "DRAFT: dodaj obrazy oraz kompletny CVAT XML. "
                "Weryfikacja sprawdzi zgodność listy obrazów i GT."
            )
        if status == STATUS_VERIFIED:
            return (
                "VERIFIED: dane przeszły walidację. "
                "Zapieczętuj tor, aby można było używać go kontrolowanie."
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
