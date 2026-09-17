"""Visual selection from audited raw images, before the Ground Truth lifecycle."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from .experiment_workspace import experiment_workspace_for_track, active_z2_context_path
from .gt_preannotation import load_json
from .participant_pool_audit import ParticipantPoolAuditService
from .track_service import EvaluationTrackError
from .sample_labels import LABELS_FILE, SampleLabels, load_sample_labels
from .final_sample_policy import has_selected_sample

SELECTION_FILE = "sample_selection.json"
SELECTION_SCHEMA = "alpr.experiment_sample_selection.v1"

SAMPLE_REVIEW_DRAFT_SCHEMA = "alpr.experiment_sample_review_draft.v1"
SAMPLE_REVIEW_DRAFT_DIR = "sample_review_drafts"


def _sample_review_draft_path(service, track_id):
    track = service.get_track(track_id)
    paths = experiment_workspace_for_track(service.workspace, track)
    path = paths.state_root / SAMPLE_REVIEW_DRAFT_DIR / f"{track_id}.json"
    workspace = service.workspace.resolve()
    if not path.resolve().is_relative_to(workspace):
        raise EvaluationTrackError("Stan roboczy próby wychodzi poza Workspace.")
    return path


def load_sample_review_draft(service, track_id, members):
    path = _sample_review_draft_path(service, track_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        current = {
            str(row["sha256"]).strip().lower()
            for row in members
            if str(row.get("sha256") or "").strip()
        }
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != SAMPLE_REVIEW_DRAFT_SCHEMA
            or payload.get("track_id") != track_id
            or not isinstance(payload.get("member_sha256"), list)
            or set(payload["member_sha256"]) != current
        ):
            return None
        raw_selected = payload.get("selected_member_sha256")
        if not isinstance(raw_selected, list):
            return None
        selected = {
            str(value).strip().lower()
            for value in raw_selected
            if isinstance(value, str) and str(value).strip()
        }
        if not selected.issubset(current):
            return None
        state = SampleLabels(selected, payload.get("sample_labels"), track_id=track_id)
        active = str(payload.get("active_label") or "")
        if active not in state.labels:
            active = ""
        return {
            "selected_member_sha256": sorted(selected),
            "sample_labels": state.payload(track_id),
            "active_label": active,
        }
    except Exception:
        return None


def save_sample_review_draft(
    service,
    track_id,
    *,
    selected_sha256,
    sample_labels,
    active_label,
    expected_member_sha256,
):
    track = service.get_track(track_id)
    if track["status"] != "DRAFT" or track["target"] != "plate":
        raise EvaluationTrackError("Stan roboczy próby można zapisać tylko dla DRAFT tablic.")
    members = service.list_members(track_id)
    current_map = {
        str(row["original_name"]): str(row["sha256"]).strip().lower()
        for row in members
    }
    expected = {
        str(name): str(sha).strip().lower()
        for name, sha in dict(expected_member_sha256).items()
    }
    if current_map != expected:
        raise EvaluationTrackError("Skład puli zmienił się. Otwórz próbę ponownie z PZ3.")
    current = set(current_map.values())
    selected = {
        str(value).strip().lower()
        for value in selected_sha256
        if str(value or "").strip()
    }
    if not selected.issubset(current):
        raise EvaluationTrackError("Stan roboczy zawiera obraz spoza bieżącej puli.")
    state = SampleLabels(selected, sample_labels, track_id=track_id)
    active = str(active_label or "")
    if active not in state.labels:
        active = ""
    payload = {
        "schema": SAMPLE_REVIEW_DRAFT_SCHEMA,
        "track_id": track_id,
        "member_sha256": sorted(current),
        "selected_member_sha256": sorted(selected),
        "sample_labels": state.payload(track_id),
        "active_label": active,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _sample_review_draft_path(service, track_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    service._atomic_json(path, payload)
    return payload


def clear_sample_review_draft(service, track_id):
    _sample_review_draft_path(service, track_id).unlink(missing_ok=True)



def prepare_sample_selection(service, track_id, *, progress=None):
    track = service.get_track(track_id)
    if track["status"] != "DRAFT" or track["target"] != "plate":
        raise EvaluationTrackError("Wybór próby jest dostępny tylko dla DRAFT tablic.")
    if track.get("gt_relative_path"):
        raise EvaluationTrackError("Tor ma już opublikowane GT. Wybór próby musi poprzedzać GT.")
    audit = ParticipantPoolAuditService(service.workspace, repository=service.repository)
    state = audit.get_track_audit_state(track_id)
    members = service.list_members(track_id)
    if not members or state.get("status") != "CURRENT" or not audit.load_participants(track_id):
        raise EvaluationTrackError("Najpierw zakończ audyt szerokiej puli względem uczestników.")
    track_root = service._track_root(track)
    current_sha = {row["sha256"] for row in members}
    previous = load_json(track_root / SELECTION_FILE)
    previous_selected = previous.get("selected_member_sha256", [])
    initial_selected = (current_sha.intersection(value for value in previous_selected if isinstance(value, str))
                        if previous.get("schema") == SELECTION_SCHEMA and previous.get("track_id") == track_id
                        and isinstance(previous_selected, list) else set())
    draft_review = load_sample_review_draft(service, track_id, members)
    if draft_review is not None:
        initial_selected = set(draft_review["selected_member_sha256"])
    final_labels = load_sample_labels(track_root, track_id, current_sha)
    review_labels = draft_review["sample_labels"] if draft_review is not None else final_labels
    review_active_label = draft_review["active_label"] if draft_review is not None else ""
    if progress:
        progress("Przygotowanie listy kandydatów", len(members), len(members))
    return {
        "source": "pz3", "purpose": "sample_selection",
        "workspace": str(service.workspace), "track_id": track_id, "name": track["name"],
        "candidate_count": len(members), "source_dir": str(track_root / "images"),
        "sample_member_sha256": {row["original_name"]: row["sha256"] for row in members},
        "sample_image_paths": {row["original_name"]: str(track_root / row["track_relative_path"])
                               for row in members},
        "sample_audit_id": state.get("audit_id"),
        "sample_labels": review_labels,
        "sample_active_label": review_active_label,
        "sample_initial_selected_sha256": sorted(initial_selected),
        "sample_committed_sha256": ([row["sha256"] for row in members]
                                    if has_selected_sample(service.workspace, track, members) else []),
    }


def commit_sample_selection(service, track_id, *, keep_sha256, expected_member_sha256,
                            expected_audit_id, criteria_note="", progress=None, sample_labels=None):
    """Retain selected raw images without creating or publishing Ground Truth."""
    track = service.get_track(track_id)
    audit = ParticipantPoolAuditService(service.workspace, repository=service.repository)
    audit.assert_track_audit_ready(track_id)
    if audit.get_track_audit_state(track_id).get("audit_id") != expected_audit_id:
        raise EvaluationTrackError("Audyt zmienił się od otwarcia wyboru próby.")
    keep = {str(value).strip().lower() for value in keep_sha256}
    if not keep or not keep.issubset(set(expected_member_sha256.values())):
        raise EvaluationTrackError("Wybierz co najmniej jeden obraz z bieżącej puli.")
    paths = experiment_workspace_for_track(service.workspace, track)
    track_root = service._track_root(track)
    manifest_path = track_root / "track_manifest.json"
    original_manifest = service._read_json(manifest_path)
    if sample_labels is None:
        sample_labels = load_sample_labels(track_root, track_id, set(expected_member_sha256.values()))
    labels = SampleLabels(keep, sample_labels, track_id=track_id)
    selection = {
        "schema": SELECTION_SCHEMA, "track_id": track_id,
        "method": "manual_visual_curation",
        "candidate_count_before": len(expected_member_sha256),
        "selected_count": len(keep), "selected_member_sha256": sorted(keep),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "criteria_note": str(criteria_note).strip(), "source_audit_id": expected_audit_id,
    }
    stage = paths.state_root / "sample_commits" / uuid.uuid4().hex
    workspace_root = service.workspace.resolve()
    if not stage.resolve().is_relative_to(workspace_root):
        raise EvaluationTrackError("Staging próby wychodzi poza Workspace.")
    moved, replaced = [], []

    def stage_file(path, category):
        resolved = path.resolve()
        if resolved == workspace_root or not resolved.is_relative_to(workspace_root):
            raise EvaluationTrackError("Ścieżka próby wychodzi poza Workspace.")
        if not path.is_file():
            return
        backup = stage / category / str(len(moved))
        backup.parent.mkdir(parents=True, exist_ok=True)
        path.rename(backup)
        moved.append((path, backup))

    def replace_bytes(path, content):
        stage_file(path, "replaced")
        path.parent.mkdir(parents=True, exist_ok=True)
        replaced.append(path)
        temporary = path.with_name("." + path.name + ".sample.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def json_bytes(payload):
        return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    def prepare_files(track_row, retained, all_rows):
        rejected = [row for row in all_rows if row["sha256"] not in keep]
        if progress:
            progress("Zapis wybranej próby", 0, len(rejected))
        for index, row in enumerate(rejected):
            image = track_root / row["track_relative_path"]
            if not service._is_within(image, track_root / "images"):
                raise EvaluationTrackError("Kopia obrazu wychodzi poza katalog toru.")
            stage_file(image, "track_images")
            source_copy = paths.source_images / row["original_name"]
            if not service._is_within(source_copy, paths.source_images):
                raise EvaluationTrackError("Nazwa obrazu wychodzi poza pulę eksperymentu.")
            stage_file(source_copy, "source_copies")
            if progress and (index % 100 == 0 or index + 1 == len(rejected)):
                progress("Zapis wybranej próby", index + 1, len(rejected))
        selection_bytes = json_bytes(selection)
        replace_bytes(track_root / SELECTION_FILE, selection_bytes)
        stage_file(_sample_review_draft_path(service, track_id), "review_draft")
        manifest = deepcopy(original_manifest)
        manifest.update(
            members=[{key: row[key] for key in (
                "member_index", "source_image_id", "source_artifact_id", "track_artifact_id",
                "original_name", "track_relative_path", "sha256")} for row in retained],
            member_count=len(retained), object_count=0, verified_at=None, verification={},
            sample_selection={"path": SELECTION_FILE,
                              "sha256": hashlib.sha256(selection_bytes).hexdigest()},
        )
        # Use the same rollback boundary as membership and sample_selection.json.
        labels_path = track_root / LABELS_FILE
        if labels.labels:
            labels_bytes = json_bytes(labels.payload(track_id))
            replace_bytes(labels_path, labels_bytes)
            manifest["sample_labels"] = {"path": LABELS_FILE,
                                         "sha256": hashlib.sha256(labels_bytes).hexdigest()}
        else:
            stage_file(labels_path, "removed_labels")
            manifest.pop("sample_labels", None)
        replace_bytes(manifest_path, json_bytes(manifest))
        active = active_z2_context_path(service.workspace)
        if load_json(active).get("track_id") == track_id:
            stage_file(active, "active_context")

    try:
        result = service.repository.commit_evaluation_sample_selection(
            track_id, keep_sha256=keep, expected_member_sha256=expected_member_sha256,
            expected_audit_id=expected_audit_id, prepare_files=prepare_files,
        )
    except Exception:
        for path in reversed(replaced):
            path.unlink(missing_ok=True)
        for original, backup in reversed(moved):
            original.parent.mkdir(parents=True, exist_ok=True)
            backup.rename(original)
        if stage.exists():
            shutil.rmtree(stage)
        raise
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    if progress:
        progress("Próba zapisana. Ponownie audytuj pulę przed GT.", len(keep), len(keep))
    return result
