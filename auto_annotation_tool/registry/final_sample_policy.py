"""Gate new plate experiment GT on a committed sample and its current audit."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def requires_final_sample_before_gt(track):
    track = dict(track or {})
    return (
        str(track.get("status") or "").upper() == "DRAFT"
        and str(track.get("target") or "").lower() in {"plate", "char"}
        and str(track.get("purpose") or "").lower() in {"ranking", "final_test"}
    )


def has_selected_sample(workspace, track, members):
    """A retained subset is valid; new images require selecting the sample again."""
    try:
        data = json.loads((Path(workspace) / track["relative_path"] /
                           "sample_selection.json").read_text(encoding="utf-8"))
        selected = set(data["selected_member_sha256"])
        current = {row["sha256"] for row in members}
        return (data.get("track_id") == track["track_id"]
                and data.get("schema") == "alpr.experiment_sample_selection.v1"
                and bool(current) and current.issubset(selected))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _valid_existing_gt(workspace, track, members):
    """Legacy GT is usable only for exactly the current image membership."""
    relative = str(track.get("gt_relative_path") or "")
    expected = str(track.get("gt_sha256") or "").lower()
    if not relative or not expected or str(track.get("gt_format") or "").lower() != "cvat_xml":
        return False
    try:
        content = (Path(workspace) / relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            return False
        root = ET.fromstring(content)
        if root.tag != "annotations":
            return False
        names = [Path(node.get("name", "")).name for node in root.findall("image")]
        current = [str(member["original_name"]) for member in members]
        return (
            bool(current)
            and all(names)
            and len(names) == len(set(names)) == len(current)
            and set(names) == set(current)
        )
    except (OSError, ET.ParseError, ValueError, LookupError, TypeError):
        return False


def final_sample_gt_issue(workspace, track, members, audit_state):
    track = dict(track or {})
    if not requires_final_sample_before_gt(track) or _valid_existing_gt(workspace, track, members):
        return ""
    if not has_selected_sample(workspace, track, members):
        return (
            "Najpierw wybierz i sfinalizuj finalną próbę z zaudytowanej puli. "
            "Roboczy wybór i etykiety nie są jeszcze finalnym zestawem Ground Truth."
        )
    if (audit_state or {}).get("status") != "CURRENT":
        return (
            "Audyt niezależności puli nie jest aktualny. "
            "W finalnej próbce nie wykonuje się osobnego drugiego audytu."
        )
    return ""

def final_sample_ready_for_gt(workspace, track, members, audit_state):
    return not final_sample_gt_issue(workspace, track, members, audit_state)


def assert_final_sample_ready_for_gt(service, track_id, *, track=None):
    from .participant_pool_audit import ParticipantPoolAuditService
    from .track_service import EvaluationTrackError

    track = dict(track if track is not None else service.get_track(track_id))
    if not requires_final_sample_before_gt(track):
        return
    members = service.list_members(track_id)
    audit = ParticipantPoolAuditService(service.workspace, repository=service.repository)
    issue = final_sample_gt_issue(service.workspace, track, members, audit.get_track_audit_state(track_id))
    if issue:
        raise EvaluationTrackError(issue)
