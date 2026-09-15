"""Manual curation and reviewed GT from an audited PZ3 candidate pool."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid
import xml.etree.ElementTree as ET

from .experiment_gt_workspace import prepare_gt_workspace, working_gt_path
from .experiment_workspace import experiment_workspace_for_track, active_z2_context_path
from .gt_preannotation import load_json
from .participant_pool_audit import ParticipantPoolAuditService
from .track_service import EvaluationTrackError

SELECTION_FILE = "sample_selection.json"
SELECTION_SCHEMA = "alpr.experiment_sample_selection.v1"


def prepare_reviewed_sample(service, track_id, *, mode="preannotation", progress=None):
    track = service.get_track(track_id)
    if track["status"] != "DRAFT" or track["target"] != "plate":
        raise EvaluationTrackError("Dobór próby i GT jest dostępny tylko dla DRAFT tablic.")
    if track.get("gt_relative_path"):
        raise EvaluationTrackError("Próba ma już zapisane GT. Użyj przygotowania GT do jego korekty.")
    audit = ParticipantPoolAuditService(service.workspace, repository=service.repository)
    state = audit.get_track_audit_state(track_id)
    if state.get("status") != "CURRENT" or not audit.load_participants(track_id):
        raise EvaluationTrackError("Najpierw zakończ audyt szerokiej puli względem uczestników.")
    context = prepare_gt_workspace(service, track_id, mode=mode, progress=progress)
    members = service.list_members(track_id)
    context.update(
        sample_selection=True, candidate_count=len(members),
        sample_member_sha256={row["original_name"]: row["sha256"] for row in members},
        sample_audit_id=state.get("audit_id"),
    )
    return context


def commit_reviewed_sample(service, track_id, *, keep_sha256, expected_member_sha256,
                          expected_audit_id, working_xml, criteria_note="", progress=None):
    """Retain reviewed images and their exact GT, with rollback on write failure."""
    track = service.get_track(track_id)
    audit = ParticipantPoolAuditService(service.workspace, repository=service.repository)
    audit.assert_track_audit_ready(track_id)
    if audit.get_track_audit_state(track_id).get("audit_id") != expected_audit_id:
        raise EvaluationTrackError("Audyt zmienił się od otwarcia przeglądu.")
    keep = {str(value).strip().lower() for value in keep_sha256}
    names_by_sha = {sha: name for name, sha in expected_member_sha256.items()}
    if not keep or not keep.issubset(names_by_sha):
        raise EvaluationTrackError("Zatwierdź co najmniej jeden obraz z bieżącej puli.")
    paths = experiment_workspace_for_track(service.workspace, track)
    xml = Path(working_xml)
    if not service._is_within(xml, paths.annotation_runs) or not xml.is_file():
        raise EvaluationTrackError("Roboczy XML nie należy do tego eksperymentu.")
    root = ET.parse(xml).getroot()
    nodes = root.findall("image")
    image_names = [node.get("name", "") for node in nodes]
    if len(image_names) != len(set(image_names)) or set(image_names) != set(expected_member_sha256):
        raise EvaluationTrackError("Roboczy GT nie odpowiada puli otwartej do przeglądu.")
    keep_names = {names_by_sha[sha] for sha in keep}
    selected_root = deepcopy(root)
    for node in list(selected_root.findall("image")):
        if node.get("name", "") not in keep_names:
            selected_root.remove(node)
    for index, node in enumerate(selected_root.findall("image")):
        node.set("id", str(index))
    selected_xml = ET.tostring(selected_root, encoding="utf-8", xml_declaration=True)
    gt_sha = hashlib.sha256(selected_xml).hexdigest()
    track_root = service._track_root(track)
    final_gt = track_root / "ground_truth" / "annotations.xml"
    manifest_path = track_root / "track_manifest.json"
    original_manifest = service._read_json(manifest_path)
    working_manifest_path = xml.parent / "run_manifest.json"
    selection = {
        "schema": SELECTION_SCHEMA, "track_id": track_id,
        "method": "manual_visual_curation",
        "candidate_count_before": len(expected_member_sha256),
        "selected_count": len(keep), "selected_member_sha256": sorted(keep),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "criteria_note": str(criteria_note).strip(),
        "source_audit_id": expected_audit_id,
    }
    stage = paths.state_root / "sample_commits" / uuid.uuid4().hex
    workspace_root = service.workspace.resolve()
    if not stage.resolve().is_relative_to(workspace_root):
        raise EvaluationTrackError("Staging próby wychodzi poza Workspace.")
    moved = []
    replaced = []
    def check_path(path):
        resolved = path.resolve()
        if resolved == workspace_root or not resolved.is_relative_to(workspace_root):
            raise EvaluationTrackError("Ścieżka próby wychodzi poza Workspace.")
    def stage_file(path, category):
        check_path(path)
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
            progress("Zapis zatwierdzonej próby i GT", 0, len(rejected))
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
                progress("Zapis zatwierdzonej próby i GT", index + 1, len(rejected))
        replace_bytes(final_gt, selected_xml)
        replace_bytes(xml, selected_xml)
        working_manifest = load_json(working_manifest_path)
        working_manifest.update(
            experiment_member_sha256={row["original_name"]: row["sha256"] for row in retained},
            approved_filenames=sorted(keep_names),
        )
        replace_bytes(working_manifest_path, json_bytes(working_manifest))
        selection_bytes = json_bytes(selection)
        replace_bytes(track_root / SELECTION_FILE, selection_bytes)
        manifest = deepcopy(original_manifest)
        manifest.update(
            members=[{key: row[key] for key in (
                "member_index", "source_image_id", "source_artifact_id", "track_artifact_id",
                "original_name", "track_relative_path", "sha256")} for row in retained],
            member_count=len(retained), object_count=0, verified_at=None, verification={},
            ground_truth={"format": "cvat_xml", "relative_path": "ground_truth/annotations.xml",
                          "sha256": gt_sha},
            sample_selection={"path": SELECTION_FILE,
                              "sha256": hashlib.sha256(selection_bytes).hexdigest()},
        )
        replace_bytes(manifest_path, json_bytes(manifest))
        active = active_z2_context_path(service.workspace)
        if load_json(active).get("track_id") == track_id:
            stage_file(active, "active_context")
    try:
        result = service.repository.commit_reviewed_evaluation_sample(
            track_id, keep_sha256=keep, expected_member_sha256=expected_member_sha256,
            expected_audit_id=expected_audit_id,
            gt_relative_path=service._workspace_relative(final_gt), gt_sha256=gt_sha,
            prepare_files=prepare_files,
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
    # Leftovers after commit are isolated outside the track and cannot be used
    # in GT or ranking. A locked temporary file must not undo a committed result.
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    try:
        from .gt_preannotation import maybe_compute_preannotation_metrics_for_track
        maybe_compute_preannotation_metrics_for_track(track_root, final_gt)
    except Exception:
        pass  # Optional AUTO metrics do not invalidate committed, reviewed GT.
    if progress:
        progress("Próba i GT zapisane. Ponownie audytuj finalną pulę.", len(keep), len(keep))
    return result
