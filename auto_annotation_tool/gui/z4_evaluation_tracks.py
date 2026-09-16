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

from .pz3_participant_audit import (
    BatchProgressDialog,
    ParticipantAuditMatrixDialog,
    ParticipantSelectionDialog,
    TrainingRunSelectionDialog,
)
from .pz3_audit_resolution_dialog import format_audit_state
from ..registry.audit_resolution import audit_path_key
from ..registry.participant_pool_audit import (
    ParticipantPoolAuditService,
    STATUS_CLEAN,
    STATUS_DEPENDENT,
    STATUS_SUSPECT,
    STATUS_UNKNOWN,
)
from ..registry.participant_model_registry import (
    eligible_training_runs,
    register_existing_participant_model,
    unregister_manual_participant_model,
)

from .experiment_gt_workflow import (
    save_pending_experiment_gt_entry,
    show_experiment_gt_entry,
)

from .pz3_audit_results_dialog import (
    compact_source_pool_audit_followup_text,
    show_source_pool_audit_results,
)

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
    can_select_participants: bool
    can_audit_pool: bool
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
        can_select_participants=normalized == STATUS_DRAFT,
        can_audit_pool=normalized in {STATUS_DRAFT, STATUS_VERIFIED},
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
        "Audyt puli sprawdza kolizje z train/val ocenianych modeli. "
        "Starsze obrazy w puli lub w historii treningu mogą jednak nie mieć "
        "pełnego rodowodu w rejestrze. Sam brak kolizji SHA nie potwierdza "
        "wtedy niezależnego pochodzenia.\n\n"
        "To oświadczenie uzupełnia brakujące informacje o pochodzeniu obrazów. "
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
        self.participant_audit = ParticipantPoolAuditService(
            self.workspace,
            repository=self.repository,
        )

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
        from .z4_evaluation_tracks_layout import EvaluationTracksLayout

        self._layout = EvaluationTracksLayout(self)

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
        if getattr(self, "_layout", None) is not None:
            self._layout.show_form(False)
        self.current_track_id = track_id
        self.refresh_tracks(select_track_id=track_id)

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
        if not rows and getattr(self, "_layout", None) is not None:
            self._layout.show_form(True)

    def _on_track_selected(self, _event=None) -> None:
        selected = self.tree.selection()
        track_id = str(selected[0]) if selected else ""
        if track_id == self.current_track_id:
            return  # Programmatic refresh already rebuilt the member table.
        self.current_track_id = track_id
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
            (
                "Modele uczestniczące: "
                + ", ".join(
                    item.model_id
                    for item in self.participant_audit.load_participants(track_id)
                )
                or "Modele uczestniczące: -"
            ),
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

        audit_state = self.participant_audit.get_track_audit_state(track_id)
        lines += ["", format_audit_state(audit_state)]
        self._set_detail_text("\n".join(lines))
        self._current_readiness = self.service.get_preparation_state(track_id)
        if getattr(self, "_layout", None) is not None:
            self._layout.set_track(track, member_count=len(members), audit_state=audit_state,
                                   readiness=self._current_readiness)
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
            self._current_readiness.next_step
        )

    def _clear_selected_details(self) -> None:
        if getattr(self, "_layout", None) is not None:
            self._layout.set_track()
        self.status_var.set("Wybierz istniejący tor albo utwórz nowy DRAFT.")
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

    def select_experiment_sample_in_z2(self) -> None:
        from .pz3_sample_route import enter_sample_selection
        from ..registry.sample_selection import prepare_sample_selection
        track_id = self._require_current_track()
        if not track_id:
            return
        progress = None
        try:
            loader = getattr(self.app, "_ensure_tab_loaded", None)
            annotation = loader("annotation", select=False) if callable(loader) else self.app.tabs.get("annotation")
            if annotation is None or getattr(annotation, "is_processing", False):
                raise EvaluationTrackError("Poczekaj na zakończenie bieżącej operacji Z2.")
            if getattr(annotation, "_preview_dirty_images", None) and not annotation._save_preview_edits(interactive=True):
                return
            progress = BatchProgressDialog(self.parent, title="Przygotowanie wyboru próby")
            context = progress.run(lambda update: prepare_sample_selection(self.service, track_id, progress=update))
            progress.close()
            progress = None
            self.app.notebook.select(annotation.frame)
            if enter_sample_selection(annotation, context):
                self._set_status("Otwarto surowe obrazy w Z2. Wybierz próbę spacją lub z menu listy.")
        except Exception as exc:
            self._show_error("Nie udało się otworzyć wyboru próby", exc)
        finally:
            if progress is not None:
                progress.close()

    def prepare_ground_truth_in_z2(self) -> None:
        from .pz3_gt_route import enter_experiment_gt_workspace
        from .experiment_gt_workflow import ExperimentGtEntryDecision
        from ..registry.experiment_gt_workspace import prepare_gt_workspace, working_gt_path
        from ..registry.gt_preannotation import get_gt_preparation_summary

        track_id = self._require_current_track()
        if not track_id:
            return
        progress = None
        try:
            readiness = self.service.get_preparation_state(track_id)
            if not readiness.can_prepare_gt or readiness.target != "plate":
                raise EvaluationTrackError(readiness.next_step)
            track = self.service.get_track(track_id)
            loader = getattr(self.app, "_ensure_tab_loaded", None)
            annotation_tab = (
                loader("annotation", select=False) if callable(loader)
                else getattr(self.app, "tabs", {}).get("annotation")
            )
            if annotation_tab is None:
                raise EvaluationTrackError("Edytor Z2 nie jest dostępny.")
            if getattr(annotation_tab, "is_processing", False):
                raise EvaluationTrackError("Poczekaj na zakończenie bieżącej anotacji Z2.")
            from .pz3_sample_route import sample_context
            if sample_context(annotation_tab):
                raise EvaluationTrackError("Zatwierdź albo anuluj wybór próby przed otwarciem GT.")
            if getattr(annotation_tab, "_preview_dirty_images", None):
                if not annotation_tab._save_preview_edits(interactive=True):
                    return
            existing = working_gt_path(self.service, track_id).is_file() or bool(track.get("gt_relative_path"))
            if existing:
                decision = ExperimentGtEntryDecision("manual", "unspecified")
            else:
                decision = show_experiment_gt_entry(
                    self.parent, workspace=self.workspace, track=track,
                    member_count=len(self.service.list_members(track_id)),
                )
                if decision is None:
                    return
            progress = BatchProgressDialog(self.parent, title="Przygotowanie Ground Truth")
            context = progress.run(lambda update: prepare_gt_workspace(
                self.service, track_id, mode=decision.mode, progress=update,
            ))
            progress.close()
            progress = None
            if not existing:
                save_pending_experiment_gt_entry(self.workspace, track_id, decision)
            self.app.notebook.select(annotation_tab.frame)
            if not enter_experiment_gt_workspace(annotation_tab, context):
                return
            self._set_status("Otwarto roboczy Ground Truth eksperymentu w Z2.")
        except Exception as exc:
            self._show_error("Nie udało się otworzyć Ground Truth", exc)
        finally:
            if progress is not None:
                progress.close()

    def _refresh_participant_model_registry(
        self,
        target: str,
    ):
        """Lekko przeładuj modele już obecne w centralnym rejestrze.

        Pełny bootstrap Workspace jest celowo wyłączony z tego CTA: skanuje
        również datasety treningowe i może liczyć ich fingerprinty, co jest
        nieproporcjonalnie ciężkie dla zwykłego odświeżenia listy uczestników.
        Nowe modele z treningów aplikacji są synchronizowane do rejestru przez
        runtime_service, a obce checkpointy dodajemy jawnie przez
        „Zarejestruj istniejący model…”.
        """
        models = self.participant_audit.list_eligible_models(
            str(target or "").strip().lower()
        )
        return (
            models,
            f"Odświeżono listę modeli z rejestru: {len(models)}.",
        )

    def _register_existing_participant_model(
        self,
        track: Mapping[str, Any],
    ):
        target = str(track.get("target") or "").strip().lower()
        path = filedialog.askopenfilename(
            title="Wybierz istniejący checkpoint modelu",
            filetypes=[
                ("PyTorch checkpoint", "*.pt"),
                ("Wszystkie pliki", "*.*"),
            ],
            parent=self.parent,
        )
        if not path:
            return (
                self.participant_audit.list_eligible_models(target),
                "",
                "Rejestracja anulowana.",
            )

        runs = eligible_training_runs(self.repository, target)
        if not runs:
            messagebox.showwarning(
                "Rejestracja modelu",
                (
                    "Brak runów z pełną lub ręcznie potwierdzoną historią "
                    f"i zapisanym zbiorem treningowym dla typu {target}. "
                    "Uzupełnij historię treningu w rejestrze."
                ),
                parent=self.parent,
            )
            return (
                self.participant_audit.list_eligible_models(target),
                "",
                "Brak odpowiedniego runu.",
            )

        run_id = TrainingRunSelectionDialog(
            self.parent,
            runs=runs,
            model_name=Path(path).name,
            target=target,
        ).show()
        if not run_id:
            return (
                self.participant_audit.list_eligible_models(target),
                "",
                "Rejestracja anulowana.",
            )

        if not messagebox.askyesno(
            "Potwierdzenie pochodzenia modelu",
            (
                "Potwierdź tylko wtedy, gdy wskazany checkpoint rzeczywiście "
                "powstał w wybranym runie.\n\n"
                "To powiązanie określa, względem jakiego train/val będzie "
                "sprawdzana niezależność puli eksperymentalnej. "
                "Oświadczenie zostanie zapisane w rejestrze."
            ),
            parent=self.parent,
        ):
            return (
                self.participant_audit.list_eligible_models(target),
                "",
                "Rejestracja anulowana.",
            )

        registration = register_existing_participant_model(
            self.workspace,
            path,
            run_id=run_id,
            target=target,
            repository=self.repository,
        )
        models = self.participant_audit.list_eligible_models(target)
        return (
            models,
            registration.model_id,
            f"Zarejestrowano {registration.model_id} · historia treningu: potwierdzona ręcznie.",
        )

    def _unregister_participant_model(
        self,
        model_id: str,
        target: str,
    ):
        result = unregister_manual_participant_model(
            self.workspace,
            model_id,
            repository=self.repository,
        )
        models = self.participant_audit.list_eligible_models(target)
        return (
            models,
            f"Wyrejestrowano {result.model_id}. Plik .pt pozostawiono bez zmian.",
        )

    def select_participant_models(self) -> bool:
        track_id = self._require_current_track()
        if not track_id:
            return False
        try:
            track = self.service.get_track(track_id)
            models = self.participant_audit.list_eligible_models(str(track.get("target") or ""))
            current = {item.model_id for item in self.participant_audit.load_participants(track_id)}
        except Exception as exc:
            self._show_error("Nie udało się odczytać modeli uczestniczących", exc)
            return False
        result = ParticipantSelectionDialog(
            self.parent,
            models=models,
            selected_ids=current,
            track_name=str(track.get("name") or track_id),
            on_refresh=lambda: self._refresh_participant_model_registry(
                str(track.get("target") or "")
            ),
            on_register=lambda: self._register_existing_participant_model(
                track
            ),
            on_unregister=lambda model_id: self._unregister_participant_model(
                model_id,
                str(track.get("target") or ""),
            ),
        ).show()
        if result is None:
            return False
        if not result:
            messagebox.showwarning("Modele uczestniczące", "Wybierz co najmniej jeden model.", parent=self.parent)
            return False
        try:
            participants = self.participant_audit.save_participants(track_id, result)
        except Exception as exc:
            self._show_error("Nie udało się zapisać modeli uczestniczących", exc)
            return False
        self._refresh_selected_details()
        self._set_status(
            "Zapisano modele uczestniczące: "
            + ", ".join(item.model_id for item in participants)
            + ". Audyt puli wymaga ponownego sprawdzenia."
        )
        return True

    def _track_member_paths(self, track: Mapping[str, Any]) -> list[Path]:
        track_root = self.workspace / str(track.get("relative_path") or "")
        result = []
        for row in self.service.list_members(str(track.get("track_id") or "")):
            rel = str(row.get("track_relative_path") or "").strip()
            path = track_root / rel
            if rel:
                result.append(path)
        return result


    def _run_participant_pool_audit(self, track_id: str, paths: list[Path], *, mode="pool", track=None):
        progress = BatchProgressDialog(self.parent, title="Audyt puli względem modeli")
        try:
            report = progress.run(
                lambda update: self.participant_audit.audit_paths(track_id, paths, progress=update)
            )
        finally:
            progress.close()
        track = track or self.service.get_track(track_id)
        return ParticipantAuditMatrixDialog(
            self.parent, report, mode=mode,
            can_remove=str(track.get("status") or "") == STATUS_DRAFT,
            has_ground_truth=bool(track.get("gt_relative_path")),
        ).show()

    def audit_current_pool(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return
        try:
            track = self.service.get_track(track_id)
            members = self.service.list_members(track_id)
            if not self.participant_audit.load_participants(track_id):
                messagebox.showwarning(
                    "Modele uczestniczące", "Najpierw wybierz modele uczestniczące.",
                    parent=self.parent,
                )
                return
            if not members:
                messagebox.showinfo("Audyt puli", "Tor nie zawiera jeszcze obrazów.", parent=self.parent)
                return
            audit_state = self.participant_audit.get_track_audit_state(track_id)
            self._set_status(
                "Audyt jest aktualny. Trwa ponowna kontrola puli…"
                if audit_state.get("status") == "CURRENT"
                else "Trwa audyt puli względem wybranych modeli…"
            )
            self.parent.update_idletasks()
            expected_shas = {str(row["sha256"]).lower() for row in members}
            resolution = self._run_participant_pool_audit(
                track_id, self._track_member_paths(track), mode="pool", track=track
            )
        except Exception as exc:
            self._show_error("Audyt puli nie powiódł się", exc)
            return
        if resolution.cancelled:
            self._set_status("Audyt anulowany. Wynik kontroli nie został zapisany.")
            return

        def apply(update):
            self.participant_audit.validate_resolution_target(track_id, resolution, expected_shas)
            rejected = {audit_path_key(path) for path in resolution.rejected_paths}
            root = self.workspace / str(track["relative_path"])
            indices = [
                int(row["member_index"]) for row in members
                if audit_path_key(root / row["track_relative_path"]) in rejected
            ]
            if indices:
                update("Usuwanie odrzuconych obrazów z toru", 0, len(indices))
                self.service.remove_members(track_id, indices)
            update("Zapis decyzji i audytu", 0, 1)
            try:
                self.service.ensure_audit_manifest(track_id)
                state = self.participant_audit.record_resolution(track_id, resolution, mode="pool")
            except Exception:
                self.participant_audit.invalidate_track_audit(track_id, reason="resolution_write_failed")
                raise
            return len(indices), state

        progress = BatchProgressDialog(self.parent, title="Zapis wyniku audytu")
        try:
            removed, state = progress.run(apply)
        except Exception as exc:
            progress.close()
            self.refresh_tracks(select_track_id=track_id)
            self._show_error("Nie udało się zastosować wyniku audytu", exc)
            return
        progress.close()
        self.refresh_tracks(select_track_id=track_id)
        outcome = (
            "Audyt zakończony. Pula jest aktualna."
            if state.get("status") == "CURRENT"
            else "Audyt zakończony. Pula wymaga uzupełnienia."
        )
        text = (
            outcome + "\n\n"
            f"Pozostało w torze: {len(self.service.list_members(track_id))}\n"
            f"Usunięto z toru: {removed}\n"
            f"Ręcznie zaakceptowano: {len(resolution.accepted_suspects)}\n\n"
            + format_audit_state(state, compact=True)
        )
        self._set_status(text.replace("\n", " | "))
        messagebox.showinfo("Zapisano wynik audytu", text, parent=self.parent)

    def add_images(self) -> None:
        track_id = self._require_current_track()
        if not track_id:
            return

        try:
            track = self.service.get_track(track_id)
        except Exception as exc:
            self._show_error("Nie udało się odczytać toru", exc)
            return

        purpose = str(track.get("purpose") or "").strip().lower()
        participants = self.participant_audit.load_participants(track_id)
        if purpose in {"ranking", "final_test"} and not participants:
            messagebox.showwarning(
                "Modele uczestniczące",
                (
                    "Najpierw wybierz modele uczestniczące w eksperymencie. "
                    "Niezależność puli obrazów będzie oceniana względem "
                    "train/val właśnie tych modeli."
                ),
                parent=self.parent,
            )
            self._set_status(
                "Najpierw wybierz modele uczestniczące. "
                "Dopiero potem można dodać pulę obrazów."
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
            selected_paths = list(
                collect_folder_candidates(selection.source_dir)
            )
        else:
            review_result = review_source_image_paths(
                self.parent,
                selection.paths,
                title="Podgląd i korekta nazw — PZ3",
            )
            if not review_result.ok:
                return
            selected_paths = list(review_result.accepted_paths)

        if not selected_paths:
            messagebox.showinfo(
                "Dodaj obrazy",
                "Po podglądzie nie pozostały żadne obrazy do dodania.",
                parent=self.parent,
            )
            return

        progress = BatchProgressDialog(
            self.parent,
            title="Przygotowanie puli obrazów",
        )
        try:
            fingerprints = progress.run(
                lambda update: self.participant_audit.fingerprint_paths(
                    selected_paths, progress=update
                )
            )
        except Exception as exc:
            progress.close()
            self._show_error(
                "Nie udało się policzyć fingerprintów obrazów",
                exc,
            )
            return
        progress.close()

        existing_members = self.service.list_members(track_id)
        try:
            known_sources = self.repository.find_source_ids_by_sha256_batch(
                list(fingerprints.values())
            )
            preflight = preflight_deduplicate_candidates(
                selected_paths, existing_members,
                sha256_by_path=fingerprints,
                source_ids_for_sha=lambda sha: known_sources.get(sha, ()),
            )
        except Exception as exc:
            self._show_error("Nie udało się sprawdzić duplikatów", exc)
            return
        unique_paths = list(preflight.candidates)
        skipped_track = preflight.already_in_track
        skipped_batch = preflight.batch_duplicates
        skipped_name = preflight.name_collisions

        if not unique_paths:
            messagebox.showinfo(
                "Dodaj obrazy",
                (
                    "Nie ma nowych kandydatów do dodania.\n\n"
                    f"Już w torze: {len(skipped_track)}\n"
                    f"Duplikaty w wyborze: {len(skipped_batch)}\n"
                    f"Kolizje nazw: {len(skipped_name)}\n"
                    f"Błędy odczytu: {len(preflight.hash_errors)}"
                ),
                parent=self.parent,
            )
            return


        resolution = None
        accepted_new = list(unique_paths)
        previous_state = self.participant_audit.get_track_audit_state(track_id)
        expected_shas = {str(row["sha256"]).lower() for row in existing_members}
        if participants:
            try:
                resolution = self._run_participant_pool_audit(
                    track_id, unique_paths, mode="ingest", track=track
                )
            except Exception as exc:
                self._show_error("Audyt puli nie powiódł się", exc)
                return
            if resolution.cancelled:
                return
            accepted_new = list(resolution.accepted_paths)

        sha_map = {str(path): fingerprints.get(path, "") for path in accepted_new}
        if resolution is not None:
            report_by_path = {
                audit_path_key(item.path): item for item in resolution.report.candidates
            }
            sha_map.update({
                str(path): report_by_path[audit_path_key(path)].sha256 for path in accepted_new
            })

        def ingest(update):
            if resolution is not None:
                self.participant_audit.validate_resolution_target(track_id, resolution, expected_shas)
            indices = []
            if accepted_new:
                indices = self.service.add_members_batch(
                    track_id, accepted_new, sha256_by_path=sha_map, progress=update
                )
            if resolution is not None:
                update("Zapis decyzji i audytu", 0, 1)
                try:
                    self.service.ensure_audit_manifest(track_id)
                    self.participant_audit.record_resolution(
                        track_id, resolution, mode="ingest", previous_state=previous_state
                    )
                except Exception:
                    self.participant_audit.invalidate_track_audit(track_id, reason="resolution_write_failed")
                    raise
            return indices

        progress = BatchProgressDialog(self.parent, title="Zastosowanie wyniku audytu")
        try:
            added_indices = progress.run(ingest)
        except Exception as exc:
            progress.close()
            self.refresh_tracks(select_track_id=track_id)
            self._show_error("Nie udało się zastosować wyniku dodawania", exc)
            return
        progress.close()
        self.refresh_tracks(select_track_id=track_id)
        if getattr(self, "_layout", None) is not None:
            self._layout.notebook.select(self._layout.images_page)
        self.parent.update_idletasks()
        actual_count = len(self.service.list_members(track_id))
        if (actual_count - len(existing_members) != len(added_indices)
                or len(self.member_tree.get_children()) != actual_count):
            messagebox.showerror(
                "Nie udało się potwierdzić listy obrazów",
                "Liczba zapisanych obrazów nie zgadza się z listą. Odśwież tor.",
                parent=self.parent,
            )
            return
        final_lines = [
            f"Dodano do toru: {len(added_indices)}",
            f"Już w torze: {len(skipped_track)}",
            f"Duplikaty w wyborze: {len(skipped_batch)}",
            f"Kolizje nazw: {len(skipped_name)}",
            f"Błędy odczytu: {len(preflight.hash_errors)}",
        ]
        if resolution is not None:
            final_lines += [
                f"Pominięte zależne: {len(resolution.rejected_dependent)}",
                f"Pominięte nieustalone: {len(resolution.rejected_unknown)}",
                f"Pominięte po weryfikacji: {len(resolution.rejected_suspects)}",
                f"Ręcznie zaakceptowano: {len(resolution.accepted_suspects)}",
            ]
        self._set_status(" | ".join(final_lines))
        messagebox.showinfo("Dodawanie obrazów zakończone", "\n".join(final_lines), parent=self.parent)

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

        try:
            self.participant_audit.invalidate_track_audit(
                track_id, reason="members_removed"
            )
        except Exception:
            pass

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

    def _participant_audit_seal_issue(
        self,
        track_id: str,
        track: Mapping[str, Any],
    ) -> str:
        # Zwróć tekst blokady seal albo pusty string.
        purpose = str(track.get("purpose") or "").strip().lower()
        if purpose not in {"ranking", "final_test"}:
            return ""

        participant_audit = getattr(self, "participant_audit", None)
        if participant_audit is None:
            # Izolowane testy GUI konstruują panel przez object.__new__
            # i podstawiają FakeTrackService, bez Workspace/SQLite.
            has_runtime_context = (
                hasattr(self, "workspace")
                and hasattr(self, "repository")
            )
            if has_runtime_context:
                return (
                    "Nie zainicjalizowano usługi audytu puli względem modeli. "
                    "Odśwież PZ3 lub uruchom aplikację ponownie."
                )
            return ""

        try:
            participant_audit.assert_track_audit_ready(track_id)
        except Exception as exc:
            return str(exc)
        return ""

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

        audit_issue = self._participant_audit_seal_issue(
            track_id,
            track,
        )
        if audit_issue:
            messagebox.showwarning(
                "Audyt puli względem modeli",
                audit_issue,
                parent=self.parent,
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
                "Uzupełnienie informacji o pochodzeniu obrazów",
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
                "\n\nNie zapisano oświadczenia uzupełniającego pochodzenie obrazów. "
                "Jeśli pula lub historyczny train/val ocenianych modeli nie ma pełnego "
                "rodowodu, niezależność pozostanie nierozstrzygnięta (UNKNOWN), "
                "a porównanie kontrolowane będzie zablokowane."
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

    def open_comparison(self) -> None:
        from .pz3_comparison import open_comparison
        open_comparison(self)

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

        progress = BatchProgressDialog(self.parent, title="Usuwanie DRAFT")
        try:
            progress.run(lambda update: self.service.delete_draft(track_id, progress=update))
        except Exception as exc:
            progress.close()
            # Cleanup can fail after the registry transaction has committed.
            self.refresh_tracks(select_track_id=track_id)
            self._show_error(
                "Nie udało się usunąć DRAFT",
                exc,
            )
            return
        progress.close()

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

    def _participant_entry_ready(
        self,
        track: Mapping[str, Any] | None,
    ) -> bool:
        if not isinstance(track, Mapping):
            return False

        status = str(track.get("status") or "").strip().upper()
        if status != STATUS_DRAFT:
            return True

        purpose = str(track.get("purpose") or "").strip().lower()
        if purpose not in {"ranking", "final_test"}:
            return True

        participant_audit = getattr(self, "participant_audit", None)
        if participant_audit is None:
            return False

        track_id = str(
            track.get("track_id")
            or getattr(self, "current_track_id", "")
            or ""
        ).strip()
        if not track_id:
            return False

        try:
            return bool(participant_audit.load_participants(track_id))
        except Exception:
            return False

    def _apply_action_state(
        self,
        track: Mapping[str, Any] | None,
        *,
        member_count: int | None = None,
    ) -> None:
        state = action_state_for_status(
            track.get("status") if isinstance(track, Mapping) else ""
        )
        from ..registry.track_readiness import track_readiness
        readiness = (
            self.service.get_preparation_state(str(track["track_id"]))
            if track and track.get("track_id") else track_readiness(None)
        )
        participant_entry_ready = self._participant_entry_ready(track)
        mapping = (
            (
                self.btn_add_images,
                readiness.can_add_images,
            ),
            (self.btn_participants, state.can_select_participants),
            (
                self.btn_audit_pool,
                readiness.can_audit,
            ),
            (self.btn_remove_images, state.can_remove_images),
            (self.btn_set_gt, readiness.can_prepare_gt),
            (self.btn_verify, readiness.can_verify),
            (self.btn_seal, readiness.can_seal and not self._participant_audit_seal_issue(
                str((track or {}).get("track_id") or ""), track or {}
            )),
            (self.btn_integrity, state.can_check_integrity),
            (self.btn_clone, state.can_clone),
            (self.btn_retire, state.can_retire),
            (self.btn_delete_draft, state.can_delete_draft),
            (self.btn_open_experiment_sources, state.can_add_images),
            (
                self.btn_prepare_z2,
                readiness.can_prepare_gt and readiness.target == "plate",
            ),
        )
        for button, enabled in mapping:
            try:
                button.configure(
                    state=tk.NORMAL if enabled else tk.DISABLED
                )
            except Exception:
                pass
        sample_button = getattr(self, "btn_sample_selection", None)
        if sample_button is not None:
            sample_button.configure(state=tk.NORMAL if (
                readiness.can_prepare_gt and readiness.target == "plate"
                and readiness.participants_ready and readiness.audit_current and not readiness.gt_exists
            ) else tk.DISABLED)
        compare_button = getattr(self, "btn_compare", None)
        if compare_button is not None:
            compare_button.configure(state=tk.NORMAL if readiness.sealed else tk.DISABLED)
        self._refresh_remove_images_button_state()

    def _status_hint_for_track(
        self,
        track: Mapping[str, Any],
        integrity: str,
    ) -> str:
        status = str(track.get("status") or "").upper()
        if (
            status == STATUS_DRAFT
            and str(track.get("purpose") or "").strip().lower()
            in {"ranking", "final_test"}
            and not self._participant_entry_ready(track)
        ):
            return (
                "DRAFT: najpierw wybierz modele uczestniczące. "
                "Dopiero potem dodaj obrazy; ich zależność zostanie "
                "sprawdzona względem train/val wybranych modeli."
            )
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
                    "Pula obrazów: użyj „Dodaj obrazy”. "
                    "Program utworzy kontrolowaną pulę źródłową eksperymentu."
                )
            if not str(track.get("gt_relative_path") or "").strip():
                return (
                    f"Ground Truth: pula zawiera {member_count} obrazów. "
                    "Użyj „Przygotuj GT w Z2”, a po zakończeniu wskaż "
                    "gotowy annotations.xml jako Ground Truth."
                )
            return (
                "Zatwierdzenie: obrazy i Ground Truth są podłączone. "
                "Uruchom weryfikację; po niej pozostanie zapieczętowanie toru."
            )
        if status == STATUS_VERIFIED:
            return (
                "VERIFIED: dane przeszły walidację. "
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
