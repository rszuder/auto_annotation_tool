"""Gate new plate experiment GT on a committed sample and its current audit."""
import hashlib
import json
from pathlib import Path


def requires_final_sample_before_gt(track):
    track = dict(track or {})
    return (
        str(track.get("status") or "").upper() == "DRAFT"
        and str(track.get("target") or "").lower() == "plate"
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


def _valid_existing_gt(workspace, track):
    """Keep the legacy editing route only for the GT actually stored in the track."""
    relative = str(track.get("gt_relative_path") or "")
    expected = str(track.get("gt_sha256") or "").lower()
    if not relative or not expected:
        return False
    try:
        digest = hashlib.sha256()
        with (Path(workspace) / relative).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected
    except OSError:
        return False


def final_sample_gt_issue(workspace, track, members, audit_state):
    track = dict(track or {})
    if not requires_final_sample_before_gt(track) or _valid_existing_gt(workspace, track):
        return ""
    if not has_selected_sample(workspace, track, members):
        return ("Najpierw wybierz finalną próbę i zatwierdź jej skład, a następnie sprawdź ją ponownie. "
                "Dopiero wtedy możesz przygotować lub wczytać Ground Truth.")
    if (audit_state or {}).get("status") != "CURRENT":
        return ("Finalna próba wymaga ponownego sprawdzenia przed przygotowaniem "
                "lub wczytaniem Ground Truth.")
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
