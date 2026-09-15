"""Wejście z PZ3 do eksperymentalnego workflow Ground Truth w Z2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Mapping

from ..config import CONFIG
from ..registry.gt_preannotation import (
    PROFILE_LABELS,
    create_preannotation_snapshot,
    get_gt_preparation_summary,
    load_json,
    save_json_atomic,
    write_gt_workflow_session,
)

PENDING_SCHEMA = "alpr.experiment_gt_entry.v1"


@dataclass(frozen=True)
class ExperimentGtEntryDecision:
    mode: str
    dataset_profile: str
    custom_profile: str = ""


def _state_dir(workspace: Path | str) -> Path:
    """Zwróć katalog stanu należący do jawnie podanego Workspace.

    DIR_10_EXPERIMENT_STATE może być użyty tylko wtedy, gdy rzeczywiście
    znajduje się wewnątrz tego samego Workspace. To ważne także dla
    tymczasowych Workspace używanych w testach i dla ewentualnej zmiany
    katalogu roboczego w przyszłości.
    """
    workspace_path = Path(workspace)
    configured = getattr(CONFIG, "DIR_10_EXPERIMENT_STATE", None)
    if configured:
        try:
            configured_path = Path(configured)
            workspace_resolved = workspace_path.resolve()
            configured_resolved = configured_path.resolve()
            configured_resolved.relative_to(workspace_resolved)
            return configured_path
        except (OSError, RuntimeError, ValueError):
            pass

    return workspace_path / "10_experiments" / "_state"


def pending_path(workspace: Path | str) -> Path:
    return _state_dir(workspace) / "pending_gt_entry.json"


def active_context_path(workspace: Path | str) -> Path:
    return _state_dir(workspace) / "active_z2_context.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return dict(value) if isinstance(value, Mapping) else {}
    except Exception:
        return {}


def save_pending_experiment_gt_entry(
    workspace: Path | str,
    track_id: str,
    decision: ExperimentGtEntryDecision,
) -> dict[str, Any]:
    session = write_gt_workflow_session(
        workspace,
        track_id,
        mode=decision.mode,
        dataset_profile=decision.dataset_profile,
        custom_profile=decision.custom_profile,
    )
    payload = {
        "schema": PENDING_SCHEMA,
        "track_id": str(track_id),
        "mode": decision.mode,
        "dataset_profile": decision.dataset_profile,
        "dataset_profile_label": str(session.get("dataset_profile_label") or ""),
        "custom_profile": decision.custom_profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "applied_to_z2": False,
        "snapshot_created": bool(session.get("preannotation_snapshot_sha256")),
    }
    save_json_atomic(pending_path(workspace), payload)
    return payload


class _ExperimentGtEntryDialog:
    DISPLAY = {
        "unspecified": "Nieokreślony",
        "natural_distribution": "Naturalny / reprezentatywny",
        "challenge_set": "Challenge set / trudne przypadki",
        "stress_test": "Stress test",
        "failure_analysis": "Failure set / analiza błędów",
        "ood_like": "OOD-like",
        "custom": "Profil własny",
    }

    def __init__(self, parent, *, workspace: Path, track: Mapping[str, Any], member_count: int):
        self.parent = parent
        self.workspace = workspace
        self.track = dict(track)
        self.member_count = int(member_count or 0)
        self.result: ExperimentGtEntryDecision | None = None

        summary = get_gt_preparation_summary(
            workspace,
            str(self.track.get("track_id") or ""),
        )
        mode = str(summary.get("mode") or "preannotation")
        profile = str(summary.get("dataset_profile") or "unspecified")
        self.mode_var = tk.StringVar(master=parent, value=mode)
        self.profile_var = tk.StringVar(
            master=parent,
            value=self.DISPLAY.get(profile, self.DISPLAY["unspecified"]),
        )
        self.custom_var = tk.StringVar(master=parent, value="")
        self.info_var = tk.StringVar(master=parent, value="")

        self.window = tk.Toplevel(parent)
        self.window.title("Przygotowanie Ground Truth w Z2")
        self.window.geometry("920x650")
        self.window.minsize(760, 560)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build(summary)
        self._refresh()
        try:
            self.window.wait_visibility()
            self.window.grab_set()
        except Exception:
            pass

    def _build(self, existing: Mapping[str, Any]) -> None:
        root = ttk.Frame(self.window, padding=16)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        ttk.Label(
            root,
            text="Przygotowanie Ground Truth",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            root,
            text=(
                f"Tor: {self.track.get('name') or '-'}\n"
                f"ID: {self.track.get('track_id') or '-'}\n"
                f"Target: {self.track.get('target') or '-'}   •   "
                f"Cel: {self.track.get('purpose') or '-'}   •   "
                f"Obrazy: {self.member_count}\n"
                "Eksport treningowy: ZABLOKOWANY."
            ),
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="ew", pady=(6, 14))

        profile = ttk.LabelFrame(root, text="Profil zbioru", padding=10)
        profile.grid(row=2, column=0, sticky="ew")
        profile.columnconfigure(1, weight=1)
        ttk.Label(profile, text="Charakter zbioru:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        combo = ttk.Combobox(
            profile,
            textvariable=self.profile_var,
            values=tuple(self.DISPLAY.values()),
            state="readonly",
        )
        combo.grid(row=0, column=1, sticky="ew")
        combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh(), add="+")
        ttk.Label(
            profile,
            text=(
                "Profil opisuje intencję doboru danych, nie ich niezależność. "
                "Niezależny zbiór może być reprezentatywny, challenge, stress-test "
                "albo celowo OOD-like."
            ),
            justify=tk.LEFT,
            wraplength=830,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        self.custom_entry = ttk.Entry(profile, textvariable=self.custom_var)
        self.custom_entry.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Label(
            root,
            text="Sposób przygotowania GT",
            font=("Segoe UI", 11, "bold"),
        ).grid(row=3, column=0, sticky="w", pady=(16, 7))

        modes = ttk.Frame(root)
        modes.grid(row=4, column=0, sticky="nsew")
        modes.columnconfigure((0, 1), weight=1)
        modes.rowconfigure(0, weight=1)

        manual = ttk.LabelFrame(modes, text="Ręczna anotacja", padding=14)
        manual.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Radiobutton(
            manual,
            text="Wybierz ręczne przygotowanie GT",
            variable=self.mode_var,
            value="manual",
            command=self._refresh,
        ).pack(anchor="w")
        ttk.Label(
            manual,
            text=(
                "Z2 otworzy ręczny workflow. Każdy obraz musi zostać przejrzany, "
                "a wszystkie obiekty docelowe oznaczone."
            ),
            justify=tk.LEFT,
            wraplength=370,
        ).pack(anchor="w", fill=tk.X, pady=(10, 0))

        auto = ttk.LabelFrame(
            modes,
            text="Preanotacja modelem + ręczna korekta",
            padding=14,
        )
        auto.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Radiobutton(
            auto,
            text="Wybierz preanotację",
            variable=self.mode_var,
            value="preannotation",
            command=self._refresh,
        ).pack(anchor="w")
        ttk.Label(
            auto,
            text=(
                "Model wybierzesz w standardowym modalu autoanotacji Z2. "
                "Może to być również model, który później będzie ewaluowany — "
                "zapiszemy jego SHA-256 w provenance."
            ),
            justify=tk.LEFT,
            wraplength=370,
        ).pack(anchor="w", fill=tk.X, pady=(10, 0))
        ttk.Label(
            auto,
            text=(
                "Po autoanotacji zapisujemy niezmienny snapshot predykcji. "
                "Po pełnej ręcznej korekcie program porówna PREANNOTATION z "
                "FINAL GT i policzy dodatkowe metryki."
            ),
            justify=tk.LEFT,
            wraplength=370,
        ).pack(anchor="w", fill=tk.X, pady=(8, 0))

        if existing.get("snapshot_exists"):
            ttk.Label(
                root,
                text=(
                    "✓ Snapshot preanotacji już istnieje i nie zostanie "
                    "nadpisany przy ponownym wejściu."
                ),
            ).grid(row=5, column=0, sticky="ew", pady=(10, 0))

        ttk.Label(
            root,
            textvariable=self.info_var,
            justify=tk.LEFT,
            wraplength=850,
        ).grid(row=6, column=0, sticky="ew", pady=(12, 8))

        footer = ttk.Frame(root)
        footer.grid(row=7, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text="Anuluj", command=self._cancel).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(footer, text="Przejdź do Z2", command=self._accept).grid(
            row=0, column=2, padx=(8, 0)
        )

    def _profile_code(self) -> str:
        display = str(self.profile_var.get() or "")
        for code, label in self.DISPLAY.items():
            if display == label:
                return code
        return "unspecified"

    def _refresh(self) -> None:
        custom = self._profile_code() == "custom"
        self.custom_entry.configure(state=tk.NORMAL if custom else tk.DISABLED)
        if self.mode_var.get() == "preannotation":
            self.info_var.set(
                "Preanotacja nie jest GT. Po jej wykonaniu snapshot zostanie "
                "zamrożony, a cały zbiór musi zostać ręcznie przejrzany."
            )
        else:
            self.info_var.set(
                "Ręczne GT również wymaga pełnego przeglądu wszystkich obrazów."
            )

    def _accept(self) -> None:
        mode = str(self.mode_var.get() or "")
        profile = self._profile_code()
        custom = str(self.custom_var.get() or "").strip()
        if mode not in {"manual", "preannotation"}:
            return
        if profile == "custom" and not custom:
            messagebox.showwarning(
                "Ground Truth",
                "Wpisz opis profilu własnego.",
                parent=self.window,
            )
            return
        self.result = ExperimentGtEntryDecision(mode, profile, custom)
        self._close()

    def _cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    def show(self):
        self.window.wait_window()
        return self.result


def show_experiment_gt_entry(
    parent,
    *,
    workspace: Path | str,
    track: Mapping[str, Any],
    member_count: int,
):
    return _ExperimentGtEntryDialog(
        parent,
        workspace=Path(workspace),
        track=track,
        member_count=member_count,
    ).show()


def apply_pending_experiment_gt_entry(host) -> bool:
    if (isinstance(getattr(host, "_experiment_gt_context", None), dict)
            and host._experiment_gt_context.get("source") == "pz3"):
        return False
    workspace = Path(CONFIG.WORKSPACE_DIR)
    pending = _read_json(pending_path(workspace))
    active = _read_json(active_context_path(workspace))
    track_id = str(pending.get("track_id") or "").strip()
    if not track_id or str(active.get("track_id") or "").strip() != track_id:
        return False
    token = (track_id, str(pending.get("mode") or ""), str(pending.get("created_at") or ""))
    if getattr(host, "_experiment_gt_entry_applied_token", None) == token:
        return False

    mode = str(pending.get("mode") or "")
    route = "auto" if mode == "preannotation" else "manual"
    try:
        host.workflow_route_var.set(route)
    except Exception:
        pass
    if route == "manual":
        for attr, value in (
            ("manual_entry_mode_var", "new"),
            ("manual_xml_template_var", True),
            ("manual_vehicle_assist_var", False),
        ):
            try:
                getattr(host, attr).set(value)
            except Exception:
                pass

    host._experiment_gt_entry_applied_token = token
    host._experiment_gt_workflow_active = True
    host._experiment_gt_track_id = track_id
    host._experiment_gt_workflow_mode = mode
    host._experiment_gt_dataset_profile = str(
        pending.get("dataset_profile") or "unspecified"
    )
    pending["applied_to_z2"] = True
    pending["applied_at"] = datetime.now(timezone.utc).isoformat()
    save_json_atomic(pending_path(workspace), pending)
    return True


def capture_experiment_gt_preannotation_snapshot(host, run_dir: Path | str):
    if not bool(getattr(host, "_experiment_gt_workflow_active", False)):
        return {}
    if str(getattr(host, "_experiment_gt_workflow_mode", "")) != "preannotation":
        return {}
    track_id = str(getattr(host, "_experiment_gt_track_id", "") or "").strip()
    if not track_id:
        return {}
    run_dir = Path(run_dir)
    xml = run_dir / "annotations.xml"
    if not xml.exists():
        return {}

    model_path = ""
    try:
        resolved_model = host._get_model_path("plate")
        model_path = str(resolved_model or "").strip()
    except Exception:
        try:
            model_path = str(host.plate_custom_var.get() or "").strip()
        except Exception:
            pass
    try:
        runtime_meta = dict(getattr(host, "_plate_model_runtime_meta", {}) or {})
    except Exception:
        runtime_meta = {}

    result = create_preannotation_snapshot(
        Path(CONFIG.WORKSPACE_DIR),
        track_id,
        xml,
        model_path=(Path(model_path) if model_path else None),
        runtime_meta=runtime_meta,
        annotation_run_dir=run_dir,
    )
    pending = _read_json(pending_path(CONFIG.WORKSPACE_DIR))
    if str(pending.get("track_id") or "") == track_id:
        pending["snapshot_created"] = True
        pending["snapshot_sha256"] = str(result.get("annotations_sha256") or "")
        pending["model_sha256"] = str(result.get("model_sha256") or "")
        save_json_atomic(pending_path(CONFIG.WORKSPACE_DIR), pending)
    return result
