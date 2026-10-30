"""Read-only view model of the existing Canvas and approved MT results.

No matching, geometry or OCR algorithm lives here.  In particular, Canvas keeps
its existing, stricter complete-scene qualification for geometry and text.
"""
from __future__ import annotations

import copy
import math
from .mobile_mt_detection_evaluation import POLICY_ID, POLICY_SHA256, format_rate

SCHEMA = 'alpr.mobile.live_session_metrics.v1'
KEY_FIELDS = ('session_id', 'source_archive_sha256', 'review_revision', 'matching_policy_id')


def result_key(session):
    if session is None:
        return None
    return (session.session_id, session.review.source_archive_sha256,
            session.review.review_revision, POLICY_ID)


def snapshot_key(snapshot):
    return tuple((snapshot or {}).get(k) for k in KEY_FIELDS)


def current(snapshot, key):
    return bool(snapshot and key and snapshot_key(snapshot) == key
                and snapshot.get('matching_policy_sha256') == POLICY_SHA256
                and snapshot.get('status') != 'STALE_REVIEW')


def from_results(session, canvas, mt):
    """Project already-computed sources, retaining their exact denominators."""
    key = result_key(session)
    identity = dict(zip(KEY_FIELDS, key))
    coherent = (all(canvas.get(k) == identity[k] == mt.get(k) for k in KEY_FIELDS[:3])
                and mt.get('matching_policy_id') == POLICY_ID
                and mt.get('matching_policy_sha256') == POLICY_SHA256
                and mt.get('status') != 'STALE_REVIEW')
    geometry_n = canvas['geometry_n'] if coherent else 0
    reads = canvas['evaluated_reads'] if coherent else 0
    chars = canvas['gt_characters'] if coherent else 0
    # The same ratio of the same integer sums is displayed by CanvasResultsPanel.
    cer = canvas['text_errors'] / chars if chars else None
    complete = (coherent and session.review.review_status == 'COMPLETED'
                and mt.get('status') == 'COMPLETE' and not canvas.get('pending_scenes'))
    result = dict(schema=SCHEMA, **identity, matching_policy_sha256=POLICY_SHA256,
        gt_mode='ASSISTED', status='COMPLETE' if complete else 'PARTIAL' if coherent else 'STALE_REVIEW',
        sources=dict(mt='mt_detection_evaluation_v1', geometry='canvas_review', ocr='canvas_review'),
        mt={k: copy.deepcopy(mt.get(k)) if coherent else None for k in
            ('tp','fp','fn','n_gt','n_final_mt','precision','recall','f1')},
        geometry=dict(n_geometry=geometry_n,
            polygon_iou_mean_pct=canvas['polygon_iou_mean_pct'] if geometry_n else None,
            nmce_mean_pct=canvas['nmce_mean_pct'] if geometry_n else None,
            unavailable_reasons=[] if geometry_n else ['NO_CANONICAL_GEOMETRY_PAIRS']),
        ocr=dict(micro_cer=cer if reads else None, n_reads=reads, n_gt_characters=chars,
            n_text_errors=canvas['text_errors'] if coherent else 0,
            n_exact=canvas['exact_reads'] if reads and chars else None,
            unavailable_reasons=[] if reads and chars else ['NO_CANONICAL_TEXT_READS']),
        unavailable_reasons=[] if coherent else ['SOURCE_OR_REVISION_MISMATCH'])
    result['mt'].update(n_qualified=mt.get('n_qualified',0) if coherent else 0,
        n_total=mt.get('n_total',0) if coherent else 0,
        unavailable_reasons=copy.deepcopy(mt.get('unavailable_reasons',[])) if coherent else ['SOURCE_OR_REVISION_MISMATCH'])
    return result


def percent(value, places=2):
    """Percentage points, including valid CER/NMCE values above 100%."""
    if not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
        return '—'
    return f'{value:.{places}f}%'.replace('.',',')


def presentation(snapshot, key):
    """Small shared formatter; never computes metrics from widget text."""
    if not current(snapshot,key):
        return dict(values={k:'—' for k in ('precision','recall','f1','iou','nmce','cer')},
            status='Aktualizowanie zapisanych danych…', exact='Exact MZ: —/—',
            denominators='MT: — · geometria: — · MZ: —', refreshing=True)
    mt,geo,ocr=snapshot['mt'],snapshot['geometry'],snapshot['ocr']
    values={k:format_rate(mt[k]) for k in ('precision','recall','f1')}
    values.update(iou=percent(geo['polygon_iou_mean_pct'],1),nmce=percent(geo['nmce_mean_pct']),
                  cer=percent(100*ocr['micro_cer']) if ocr['micro_cer'] is not None else '—')
    exact=(f"{ocr['n_exact']}/{ocr['n_reads']}" if ocr['n_reads'] and ocr['n_gt_characters'] else '—/—')
    geometry=(f"{geo['n_geometry']} par" if geo['n_geometry'] else '0 (brak par)')
    text=(f"{ocr['n_reads']} odczytów / {ocr['n_gt_characters']} znaków GT"
          if ocr['n_reads'] and ocr['n_gt_characters'] else '0 (brak ocenionych odczytów)')
    return dict(values=values, status=('Ocenione dane · ASSISTED' if snapshot['status']=='COMPLETE'
                else 'W toku · tylko ocenione dane'), exact='Exact MZ: '+exact,
        denominators=f"MT: {mt['n_qualified']}/{mt['n_total']} · geometria: {geometry}\nMZ: {text}", refreshing=False)
