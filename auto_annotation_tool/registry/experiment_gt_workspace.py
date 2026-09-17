"""Stały roboczy XML toru MT, otwierany bez wyboru nowy/istniejący."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from PIL import Image

from .experiment_workspace import experiment_workspace_for_track, activate_z2_experiment_context
from .gt_preannotation import load_json, save_json_atomic


def working_gt_path(service, track_id):
    track = service.get_track(track_id)
    paths = experiment_workspace_for_track(service.workspace, track)
    return paths.annotation_runs / "ground_truth" / "annotations.xml"


def prepare_gt_workspace(service, track_id, *, mode="manual", progress=None):
    from .track_service import EvaluationTrackError
    from .participant_pool_audit import ParticipantPoolAuditService
    from ..data_models import ImageAnnotation
    from ..exporters import CVATExporter

    if mode not in {"manual", "preannotation"}:
        raise EvaluationTrackError("Nieobsługiwany sposób przygotowania GT.")
    track = service.get_track(track_id)
    if track["status"] != "DRAFT" or track["target"] != "plate":
        raise EvaluationTrackError("Edytor Z2 obsługuje robocze GT dla MT / tablic.")
    from .final_sample_policy import assert_final_sample_ready_for_gt
    assert_final_sample_ready_for_gt(service, track_id, track=track)
    audit = ParticipantPoolAuditService(service.workspace, repository=service.repository)
    audit.assert_track_audit_ready(track_id)
    members = service.list_members(track_id)
    if not members:
        raise EvaluationTrackError("Najpierw dodaj obrazy do toru.")
    if progress:
        progress("Przygotowanie źródeł GT", 0, len(members))
    service._sync_experiment_sources_from_members(track_id)
    paths = experiment_workspace_for_track(service.workspace, track)
    context = {"source_dir": str(paths.source_images), "annotation_dir": str(paths.annotation_runs)}
    xml = working_gt_path(service, track_id)
    xml.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = xml.parent / "run_manifest.json"
    manifest = load_json(manifest_path)
    current_shas = {row["original_name"]: row["sha256"] for row in members}
    previous_shas = manifest.get("experiment_member_sha256") or {}
    original_gt = str(track.get("gt_relative_path") or "")
    if not xml.exists() and original_gt:
        source = service.workspace / original_gt
        if not source.is_file() or service._sha256(source) != track.get("gt_sha256"):
            raise EvaluationTrackError("Zapisany GT zniknął lub zmienił zawartość.")
        shutil.copy2(source, xml)

    existing = xml.is_file()
    if existing:
        tree = ET.parse(xml)
        root = tree.getroot()
        nodes = {Path(node.get("name", "")).name: node for node in root.findall("image")}
        if len(nodes) != len(root.findall("image")):
            raise EvaluationTrackError("Roboczy XML zawiera powtórzone nazwy obrazów.")
    else:
        annotations = []
        for i, member in enumerate(members):
            with Image.open(Path(context["source_dir"]) / member["original_name"]) as image:
                width, height = image.size
            annotations.append(ImageAnnotation(member["original_name"], width, height))
            if progress and (i % 100 == 0 or i + 1 == len(members)):
                progress("Tworzenie roboczego XML", i + 1, len(members))
        temporary = xml.with_suffix(".xml.tmp")
        if not CVATExporter().export(annotations, temporary, only_successful=False):
            raise EvaluationTrackError("Nie udało się utworzyć roboczego XML.")
        temporary.replace(xml)
        tree = ET.parse(xml)
        root = tree.getroot()
        nodes = {Path(node.get("name", "")).name: node for node in root.findall("image")}

    changed = False
    for name, node in tuple(nodes.items()):
        if name not in current_shas or (name in previous_shas and previous_shas[name] != current_shas[name]):
            root.remove(node)
            del nodes[name]
            changed = True
    for i, member in enumerate(members):
        name = member["original_name"]
        if name not in nodes:
            with Image.open(Path(context["source_dir"]) / name) as image:
                width, height = image.size
            ET.SubElement(root, "image", id=str(i), name=name, width=str(width), height=str(height))
            changed = True
    if changed:
        for i, node in enumerate(root.findall("image")):
            node.set("id", str(i))
        temporary = xml.with_suffix(".xml.tmp")
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        temporary.replace(xml)

    now = datetime.now(timezone.utc).isoformat()
    manifest.update(
        annotation_run_type=manifest.get("annotation_run_type", "manual_template"),
        run_status="completed", transaction_state="committed",
        generated_at=manifest.get("generated_at", now),
        source_input_dir=context["source_dir"], input_dir=context["source_dir"],
        experiment_bound=True, evaluation_track_id=track_id,
        training_dataset_export_allowed=False,
        experiment_member_sha256=current_shas,
    )
    save_json_atomic(manifest_path, manifest)
    context = activate_z2_experiment_context(service.workspace, track)
    return {
        **context, "source": "pz3", "purpose": "ground_truth",
        "experiment_purpose": track["purpose"], "gt_mode": mode,
        "annotation_path": str(xml), "annotation_run_dir": str(xml.parent),
        "gt_existing": existing or bool(original_gt),
    }


def merge_preannotation_working_copy(service, track_id, prediction_xml):
    """Zachowaj cały roboczy GT i podmień tylko obrazy objęte wynikiem AUTO."""
    from copy import deepcopy
    from .track_service import EvaluationTrackError

    track = service.get_track(track_id)
    if track["status"] != "DRAFT":
        raise EvaluationTrackError("Wynik AUTO można zastosować wyłącznie do roboczego GT.")
    target = working_gt_path(service, track_id)
    source = Path(prediction_xml)
    if source.resolve() == target.resolve():
        return target
    paths = experiment_workspace_for_track(service.workspace, track)
    if not service._is_within(source, paths.annotation_runs):
        raise EvaluationTrackError("Wynik AUTO nie należy do tego eksperymentu.")
    manifest_path = target.parent / "run_manifest.json"
    manifest = load_json(manifest_path)
    current_shas = {row["original_name"]: row["sha256"] for row in service.list_members(track_id)}
    if manifest.get("experiment_member_sha256") != current_shas:
        raise EvaluationTrackError("Pula zmieniła się podczas AUTO. Otwórz GT ponownie z PZ3.")
    tree = ET.parse(target)
    root = tree.getroot()
    existing = {Path(node.get("name", "")).name: node for node in root.findall("image")}
    predicted = ET.parse(source).getroot().findall("image")
    names = [Path(node.get("name", "")).name for node in predicted]
    if len(names) != len(set(names)) or set(names) - set(existing):
        raise EvaluationTrackError("Wynik AUTO zawiera obrazy spoza przygotowanego GT lub duplikaty.")
    for name, node in zip(names, predicted):
        previous = existing[name]
        index = list(root).index(previous)
        replacement = deepcopy(node)
        replacement.set("id", previous.get("id", "0"))
        root.remove(previous)
        root.insert(index, replacement)
    temporary = target.with_suffix(".xml.tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(target)
    manifest.update(annotation_run_type="auto_annotation", manual_xml_template=False,
                    last_preannotation_run=str(source.parent))
    save_json_atomic(manifest_path, manifest)
    return target


def publish_working_gt(service, track_id, xml_path):
    from .track_service import EvaluationTrackError
    from .participant_pool_audit import ParticipantPoolAuditService

    track = service.get_track(track_id)
    if track["status"] != "DRAFT":
        raise EvaluationTrackError("GT można zapisać tylko w DRAFT.")
    ParticipantPoolAuditService(service.workspace, repository=service.repository).assert_track_audit_ready(track_id)
    xml = Path(xml_path)
    paths = experiment_workspace_for_track(service.workspace, track)
    if not service._is_within(xml, paths.annotation_runs):
        raise EvaluationTrackError("XML nie należy do obszaru GT tego eksperymentu.")
    names = {Path(node.get("name", "")).name for node in ET.parse(xml).getroot().findall("image")}
    members = service.list_members(track_id)
    working_manifest = load_json(working_gt_path(service, track_id).parent / "run_manifest.json")
    prepared_shas = working_manifest.get("experiment_member_sha256") or {}
    current_shas = {row["original_name"]: row["sha256"] for row in members}
    if prepared_shas and prepared_shas != current_shas:
        raise EvaluationTrackError(
            "Skład puli zmienił się od otwarcia GT. Otwórz przygotowanie GT ponownie z PZ3."
        )
    if names != {row["original_name"] for row in members}:
        raise EvaluationTrackError("Roboczy XML nie odpowiada bieżącej puli obrazów.")
    canonical = working_gt_path(service, track_id)
    if xml.resolve() != canonical.resolve():
        canonical.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(xml, canonical)
    return service.set_ground_truth(track_id, canonical)
