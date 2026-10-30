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


def canvas_post_nms_proof(session, invocation_id):
    """Keep historical 2->1 evidence stable; additionally prove one RAW rejection.

    MZ can run only on retained post-dedup candidates in the archived static
    pipeline. If every retained candidate has its own executed MZ/crop record,
    the single remaining raw record is uniquely identified by subtraction.
    NOT_RUN or overlap alone is never sufficient. No NMS is rerun here.
    """
    old = post_nms_proof(session, invocation_id)
    if old:
        return old
    if getattr(session,'path',None) is None:return None
    group = session.mt_invocations.get(invocation_id)
    if not group or not group.executed or group.cancelled or group.execution_failed:
        return None
    from .mobile_source_frame_roi import source_invocation_context
    if not source_invocation_context(group.records, invocation_id, session.entry_names):
        return None
    rows = list(group.records)
    raw = len(rows)
    if raw < 2 or group.detection_count != raw:
        return None
    indices=[_source_integer(r.get('mt_detection_index')) for r in rows]
    if any(i is None for i in indices) or sorted(indices) != list(range(raw)):
        return None
    key = tuple(_source_integer(rows[0].get(k)) for k in ('source_sequence','source_timestamp_nanos','scene_generation'))
    if any(v is None for v in key):return None
    if any(tuple(_source_integer(r.get(k)) for k in ('source_sequence','source_timestamp_nanos','scene_generation')) != key for r in rows):
        return None
    stat = session.path.stat()
    matches = _trace_index(str(session.path),session.bundle.source_archive_sha256,stat.st_size,stat.st_mtime_ns).get(key,[])
    if len(matches) != 1:return None
    trace = matches[0]; counters = trace.get('counters',{})
    expected = dict(plate_detections_raw=raw,plate_detections_after_dedup=raw-1,
                    plate_detections_suppressed=1,mt_runs_this_frame=1,mz_runs=raw-1)
    if any(_source_integer(counters.get(k)) != v for k,v in expected.items()):return None
    if any(_source_integer(r.get(k)) != _source_integer(trace.get(k)) or _source_integer(r.get(k)) is None
           for r in rows for k in ('visual_epoch','camera_transform_generation')):return None
    kept=[];rejected=[]
    for row in rows:
        aid=str(row.get('id') or row.get('attempt_id') or '')
        if row.get('mt_status') not in DETECTION_STATUSES or str(row.get('mt_executed')).lower() != 'true':return None
        samples=[session.samples[sid] for sid in session.sample_ids_by_attempt.get(aid,()) if sid in session.samples]
        ran=str(row.get('mz_executed')).lower() == 'true'
        if (ran and row.get('rectification_status') == 'OK' and row.get('mz_status') in {'READ','NO_CHARACTERS'}
                and samples and all(str(s.get('attempt_id')) == aid and not session.cancelled(s) for s in samples)):
            kept.append(aid)
        elif not ran and row.get('mz_status') == 'NOT_RUN' and row.get('rectification_status') == 'NOT_RUN' and not samples:
            rejected.append(aid)
        else:return None
    if len(kept) != raw-1 or len(rejected) != 1:return None
    return dict(schema='alpr.postdedup.executed_complement.v1',mt_invocation_id=invocation_id,
                source_archive_sha256=session.bundle.source_archive_sha256,trace_frame_id=trace.get('frame_id'),
                source_sequence=key[0],source_timestamp_nanos=key[1],scene_generation=key[2],
                final_ids=sorted(kept),suppressed_id=rejected[0],raw=raw,after_dedup=raw-1,suppressed=1)


def unresolved_filter_reason(session,gid):
    """Known suppression without attributable IDs must not become a new READY."""
    if getattr(session,'path',None) is None:return ''
    group=session.mt_invocations[gid];row=group.records[0];stat=session.path.stat()
    key=tuple(_source_integer(row.get(k)) for k in ('source_sequence','source_timestamp_nanos','scene_generation'))
    matches=_trace_index(str(session.path),session.bundle.source_archive_sha256,stat.st_size,stat.st_mtime_ns).get(key,[])
    research='session.json' in getattr(session,'entry_names',())
    if len(matches)!=1 and research:
        return 'Brak jednoznacznego śladu końcowych wyników MT dla tej klatki.'
    if len(matches)==1:
        c=matches[0].get('counters',{});raw=_source_integer(c.get('plate_detections_raw'));final=_source_integer(c.get('plate_detections_after_dedup'))
        if research and (raw is None or final is None):
            return 'Brak liczników RAW i końcowych wskazań w śladzie klatki.'
        if raw is not None and final is not None and raw>final and not canvas_post_nms_proof(session,gid):
            return 'Źródło potwierdza odrzucone wskazania, ale nie pozwala ustalić ich identyfikatorów.'
    return ''


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
