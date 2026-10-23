"""Evidence-backed distinction between raw MT boxes and post-dedup detections.

No human GT is inferred from IoU or OCR. Full-source telemetry must prove that
Android accepted one detector box and suppressed the other *in the same call*.
The operator still decides how many physical plates the source image contains.
Never edit original .alprsession, individual MT outputs or stored review GT.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import json
import math
import zipfile

DETECTION_STATUSES = frozenset({"VALID_QUAD", "DETECTION_INVALID_QUAD"})


def bbox_iou(a, b):
    keys = ("plate_left", "plate_top", "plate_right", "plate_bottom")
    try:
        u, v = tuple(float(a[k]) for k in keys), tuple(float(b[k]) for k in keys)
    except (KeyError, TypeError, ValueError, OverflowError):
        return 0.0
    if not all(math.isfinite(x) for x in u+v) or u[2]<=u[0] or u[3]<=u[1] or v[2]<=v[0] or v[3]<=v[1]:
        return 0.0
    area_a=(u[2]-u[0])*(u[3]-u[1]); area_b=(v[2]-v[0])*(v[3]-v[1])
    inter=max(0, min(u[2],v[2])-max(u[0],v[0]))*max(0,min(u[3],v[3])-max(u[1],v[1]))
    union=area_a+area_b-inter
    return inter/union if union>0 else 0.0


def _source_integer(value):
    # Full Android attempts.csv is read as strings; JSON telemetry stores ints.
    if type(value) is int and value >= 0:
        return value
    if isinstance(value,str) and value.isascii() and value.isdecimal():
        return int(value)
    return None


def _positive_integer(obj, name):
    return _source_integer(obj.get(name))


@lru_cache(maxsize=20)
def _trace_index(path, source_sha, size, mtime_ns):
    """Only already SHA-validated session ZIP; no extraction and 20 MiB cap."""
    found={}
    if not path or not source_sha:
        return found
    try:
        file=Path(path)
        stat=file.stat()
        if stat.st_size != size or stat.st_mtime_ns != mtime_ns:
            return found
        with zipfile.ZipFile(file) as archive:
            info=archive.getinfo("telemetry/traces.jsonl")
            if info.file_size > 20*1024*1024:
                return found
            with archive.open(info) as stream:
                for line in stream:
                    if len(line) > 50_000:
                        continue
                    try:
                        row=json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not isinstance(row,dict):
                        continue
                    key=(row.get("source_sequence"),row.get("source_timestamp_ns"),row.get("scene_generation"))
                    if any(v is None for v in key):
                        continue
                    # A repeated key is ambiguous, so no automatic attribution.
                    found.setdefault(key,[]).append(row)
    except (OSError,zipfile.BadZipFile,KeyError):
        return {}
    return found


def post_nms_proof(session, invocation_id):
    """Return exact traced suppression (primary, extra, counters) or None.

    Narrow-by-design: a 2->1 static invocation with one final MZ inference.
    This is the *one* documented F4 case, not a general-purpose box classifier.
    """
    group=session.mt_invocations.get(invocation_id)
    if not group or not group.executed or group.cancelled or group.execution_failed:
        return None
    if group.detection_count != 2 or len(group.records) != 2:
        return None
    rows=sorted(group.records,key=lambda r:int(r.get("mt_detection_index") or -1))
    if [_source_integer(r.get("mt_detection_index")) for r in rows]!=[0,1]:
        return None
    if any(str(r.get("mt_status") or "").upper() not in DETECTION_STATUSES for r in rows):
        return None
    if bbox_iou(*rows) < .90:
        return None
    left,right=rows
    if (str(left.get("mz_status") or "").upper() != "READ" or
            str(right.get("mz_status") or "").upper() != "NOT_RUN" or
            session.sample_ids_by_attempt.get(str(right.get("id") or ""))):
        return None
    try:
        if float(left.get("plate_confidence")) < float(right.get("plate_confidence")):
            return None
    except (TypeError,ValueError):
        return None
    # Same source/identity for both child records, not merely visual overlap.
    fields=("source_sequence","source_timestamp_nanos","scene_generation","mt_invocation_id")
    if any(left.get(k) is None or left.get(k) != right.get(k) for k in fields):
        return None
    path=getattr(session,"path",None)
    bundle=getattr(session,"bundle",None)
    source_sha=getattr(bundle,"source_archive_sha256","")
    if path is None or not source_sha:
        return None
    try:
        stat=Path(path).stat()
    except OSError:
        return None
    index=_trace_index(str(path),source_sha,stat.st_size,stat.st_mtime_ns)
    key=(_source_integer(left["source_sequence"]),_source_integer(left["source_timestamp_nanos"]),
         _source_integer(left["scene_generation"]))
    if any(v is None for v in key):
        return None
    matches=index.get(key,[])
    if len(matches) != 1:
        return None
    trace=matches[0]
    counters=trace.get("counters") or {}
    expected={"plate_detections_raw":2,"plate_detections_after_dedup":1,
              "plate_detections_suppressed":1,"mt_runs_this_frame":1,"mz_runs":1}
    if not isinstance(counters,dict) or any(_positive_integer(counters,k)!=v for k,v in expected.items()):
        return None
    # Trace itself is a provenance record for the *whole invocation*.
    return {"primary_id":str(left["id"]),"suppressed_id":str(right["id"]),
            "mt_invocation_id":invocation_id,"trace_frame_id":trace.get("frame_id"),
            "source_sequence":key[0],"bbox_iou":bbox_iou(left,right),
            "raw":2,"after_dedup":1,"suppressed":1}


def eligible_suppressed_id(session, invocation_id):
    """One physical plate still requires an explicit operator cardinality decision."""
    evidence=post_nms_proof(session,invocation_id)
    if not evidence:
        return ""
    decision=session.invocation_annotation(invocation_id)
    # Canvas inventory has its own independently reviewed physical plates;
    # the diagnostic legacy-subject path MUST NOT modify canvas scoring.
    if isinstance(decision.get("canvas_review_v1"), dict):
        return ""
    if decision.get("visible_plate_count") != "one" or decision.get("evaluable") is False:
        return ""
    # Operator's single-plate count + exact post-NMS telemetry may co-exist
    # with any previous GT sidecar values; no writes or auto-migration.
    return evidence["suppressed_id"]


def suppressed_subject(session, subject):
    """A raw-only record contributes no separate physical-plate denominator."""
    ids=subject.get("attempts",())
    if not ids or subject.get("samples"):
        return False
    for aid in ids:
        gid=session.invocation_by_attempt.get(aid,"")
        if not gid or eligible_suppressed_id(session,gid) != aid:
            return False
    return True
