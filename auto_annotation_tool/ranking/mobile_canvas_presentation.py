"""Read-only canvas inventory for live status/navigation, separate from metrics.

Unopened eligible frames are included in progress. Metric denominators still
come exclusively from mobile_canvas_review.summary and confirmed/evaluable data.
"""
from __future__ import annotations

from . import mobile_canvas_review as core


def build_inventory(session):
    result = dict(total=0, editable=0, inspected=0, assessed=0, excluded=0,
                  remaining=0, incomplete=0, unavailable=0, groups={})
    if session is None:
        return result
    for gid, group in session.mt_invocations.items():
        if not group.executed or group.cancelled or group.execution_failed:
            continue
        result["total"] += 1
        item = dict(gid=gid, scene=None, status="UNAVAILABLE", cells=("○", "—", "—", "—", "○"),
                    issues=[], persisted=core.has_scene(session, gid),
                    subject_keys=tuple(group.subject_keys))
        try:
            scene = core.scene(session, gid)
        except (ValueError, TypeError, KeyError) as exc:
            item["issues"] = [str(exc)]
            result["unavailable"] += 1
        else:
            result["editable"] += 1
            item["scene"] = scene
            item["cells"] = core.scene_review_cells(scene)
            excluded = scene["checked"] and bool(scene.get("exclusion_reason"))
            issues = [] if excluded else core._content_issues(scene)
            if not scene["checked"]:
                issues.insert(0, "Obraz nie został oznaczony jako sprawdzony")
            item["issues"] = issues
            if scene["checked"]:
                result["inspected"] += 1
            if excluded:
                result["excluded"] += 1
                item["status"] = "EXCLUDED"
            elif not issues:
                result["assessed"] += 1
                item["status"] = "READY"
            elif scene["checked"]:
                result["incomplete"] += 1
                item["status"] = "INCOMPLETE"
            else:
                item["status"] = "PENDING"
        result["groups"][gid] = item
    result["remaining"] = result["total"] - result["inspected"]
    return result


def subject_groups(session, subject_key):
    ids = {session.invocation_by_attempt.get(aid)
           for aid in session.subjects.get(subject_key, {}).get("attempts", ())}
    return [gid for gid in session.mt_invocations if gid in ids]
