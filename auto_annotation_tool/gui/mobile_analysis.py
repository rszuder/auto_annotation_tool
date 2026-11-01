"""ALPR-ANALYSIS-1.0: retrospective F4 analysis, never a source-data migration."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, replace
from pathlib import Path
import copy
import csv
import hashlib
import json
import math
import re

PROTOCOL_ID = 'ALPR-ANALYSIS-1.0'
IMPLEMENTATION_ID = 'alpr.desktop.analysis.v1'
PROTOCOL_DATE = '2026-10-31'
QUESTIONS = {'F4':'F4 · FP32 / INT8', 'F5A':'F5A · MP / ROI',
             'F5B':'F5B · AutoZoom', 'DIAGNOSTIC':'Diagnostyka źródeł'}
REGISTRY = Path(__file__).parents[1]/'ranking/protocols/alpr_analysis_1_0/f4_registry.csv'
PROTOCOL_DOCUMENT = Path(__file__).parents[2]/'docs/experiments/ALPR_ANALYSIS_1_0_20261031.md'

def protocol_evidence():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (REGISTRY,PROTOCOL_DOCUMENT)}
METRICS = {
    'mt_p50_ms':('Czasy · MT — mediana (p50)','ms','mt_inference_call'),
    'mt_p95_ms':('Czasy · MT — p95','ms','mt_inference_call'),
    'mz_trace_p50_ms':('Czasy · etap MZ / ślad — mediana (p50)','ms','mz_stage_per_trace'),
    'mz_trace_p95_ms':('Czasy · etap MZ / ślad — p95','ms','mz_stage_per_trace'),
    'pipeline_p50_ms':('Czasy · potok ALPR — mediana (p50)','ms','completed_pipeline_trace'),
    'pipeline_p95_ms':('Czasy · potok ALPR — p95','ms','completed_pipeline_trace'),
    'mt_calls':('Liczba wywołań MT','wywołania','recorded_mt_call'),
    'mz_calls':('Liczba wywołań MZ','wywołania','recorded_mz_call'),
    'mz_call_p95_ms':('MZ — p95 pojedynczego wywołania','ms','mz_inference_call'),
    'mt_tp':('Wykrycie BBOX · TP','tablice','complete_mt_invocation_ROI'),
    'mt_fp':('Wykrycie BBOX · FP','wskazania FINAL','complete_mt_invocation_ROI'),
    'mt_fn':('Wykrycie BBOX · FN','tablice','complete_mt_invocation_ROI'),
    'mt_precision_pct':('Wykrycie BBOX · Precision','%','complete_mt_invocation_ROI'),
    'mt_recall_pct':('Wykrycie BBOX · Recall','%','complete_mt_invocation_ROI'),
    'mt_f1_pct':('Wykrycie BBOX · F1','%','complete_mt_invocation_ROI'),
    'pose_availability_pct':('Pose · dostępność źródłowych narożników','%','source_final_linked_to_GT'),
    'polygon_iou_pct':('Geometria MT · Polygon IoU','%','source_pose_GT_pair'),
    'nmce_pct':('Geometria MT · NMCE','%','source_pose_GT_pair'),
    'exact_mz_pct':('Jakość MZ · pełne zgodne numery','%','executed_MZ_with_readable_GTZ'),
    'micro_cer_pct':('Jakość MZ · micro-CER','%','GT_character_in_executed_MZ'),
    'scene_coverage_pct':('Pokrycie zaplanowanych scen','%','planned_scene'),
    'exact_e2e_pct':('Pełny potok · Exact E2E','%','unique_plate_in_planned_window'),
    'no_read_e2e_pct':('Pełny potok · no-read','%','unique_plate_in_planned_window'),
    'pss_peak_mib':('PSS · maksimum dostępnych próbek','MiB','OS_PSS_measurement'),
}

@dataclass(frozen=True)
class AnalysisInput:
    report: object
    session_id: str
    source_sha256: str
    report_id: str
    source_path: str
    results_root: Path | None
    review_root: Path
    review_seen: bool = False

def selection_identity(report, bundle=None):
    from .z4_mobile_report_browser_ux import report_identity
    info=report_identity(report,bundle)
    sid=info['session_id'];sha=str(getattr(report,'source_archive_sha256','')).lower()
    if not (str(getattr(report,'report_id','')).strip() and re.fullmatch(r'[A-Za-z0-9_.-]{1,160}',sid)
            and re.fullmatch(r'[a-f0-9]{64}',sha)):
        raise ValueError('Do analizy potrzebne są report_id, session_id i SHA-256 w indeksie importu.')
    return sid,sha

def make_input(report, *, source_path=None, results_root=None, review_root=None, bundle=None):
    from .mobile_report_source_recovery import stored_source
    from .mobile_report_canvas_view import results_root_for_source
    from ..config import CONFIG
    sid,sha=selection_identity(report,bundle)
    path=str(source_path or stored_source(report) or '')
    review_root=Path(review_root or CONFIG.DIR_7_RANKINGS_MOBILE_PACKAGES)
    return AnalysisInput(copy.deepcopy(report),sid,sha,str(report.report_id),path,
        Path(results_root) if results_root else results_root_for_source(path),
        review_root,(review_root/'human_reviews'/(sha+'.review.json')).is_file())

@dataclass(frozen=True)
class MetricEligibility:
    metric_id: str
    status: str = 'N/A'
    value: float | int | None = None
    n_scored: int | None = None
    n_total_eligible: int | None = None
    n_unscored: int | None = None
    missing_reasons: tuple[str,...] = ()
    numerator: float | int | None = None
    denominator: float | int | None = None
    gt_origin: str = 'NOT_APPLICABLE'
    review_revision: int | None = None
    inference_scope: str = 'UNAVAILABLE'
    evidence_paths: tuple[str,...] = ()
    explanation: str = ''
    population_basis: str = 'observed_source_units_not_planned_scenes'

    def payload(self):
        value=asdict(self)
        value.update(analysis_protocol_id=PROTOCOL_ID,implementation_id=IMPLEMENTATION_ID,
            unit=METRICS[self.metric_id][1],observation_unit=METRICS[self.metric_id][2],
            coverage=(self.n_scored/self.n_total_eligible if self.n_total_eligible and self.n_scored is not None else None),
            n_total_planned=None)
        return value

@dataclass
class SourceValidation:
    input: AnalysisInput
    source_status: str
    source_reason: str
    metadata: dict = field(default_factory=dict)
    quality_state: str = 'NONE'
    quality_reason: str = ''
    metrics: dict[str,MetricEligibility] = field(default_factory=dict)
    quality_units: list = field(default_factory=list)
    fingerprint: dict = field(default_factory=dict)
    conditions: dict = field(default_factory=dict)
    record: object = field(default=None,repr=False)
    bundle: object = field(default=None,repr=False)

    def payload(self):
        return dict(session_id=self.input.session_id,report_id=self.input.report_id,
            source_archive_sha256=self.input.source_sha256,source_path=self.input.source_path,
            source_status=self.source_status,source_reason=self.source_reason,
            quality_state=self.quality_state,quality_reason=self.quality_reason,metadata=self.metadata,
            metrics={k:m.payload() for k,m in self.metrics.items()},quality_units=self.quality_units,
            fingerprint=self.fingerprint,conditions=self.conditions)

@dataclass
class AnalysisCohort:
    inputs: tuple[AnalysisInput,...]
    sessions: list[SourceValidation]
    question: str
    duplicates: list
    interpretation: str = 'DESCRIPTIVE'
    protocol_files: dict = field(default_factory=protocol_evidence)

    def payload(self):
        return dict(analysis_protocol_id=PROTOCOL_ID,protocol_date=PROTOCOL_DATE,
            protocol_files=self.protocol_files,
            chronology='RETROSPECTIVE_FOR_F4_NOT_PREREGISTERED',implementation_id=IMPLEMENTATION_ID,
            question=self.question,interpretation=self.interpretation,duplicates=self.duplicates,
            limitations=['Brak dowodu parowania fotografii; brak kontrolowanego wniosku przyczynowego.',
                'DAY i NIGHT są osobnymi materiałami TV, nie dwoma checkpointami dziennym i nocnym.',
                'GT ASSISTED nie jest niezależnym F6; różne podzbiory jakości nie tworzą rankingu wariantów.',
                'n śladów i n wywołań nie są liczbą niezależnych plansz; MZ/ślad może sumować wywołania.'],
            sessions=[s.payload() for s in self.sessions])

def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def _missing(s, metric, reason, *, n=None, total=None, explanation=''):
    needs_gt=metric in ('mt_tp','mt_fp','mt_fn','mt_precision_pct','mt_recall_pct','mt_f1_pct',
        'pose_availability_pct','polygon_iou_pct','nmce_pct','exact_mz_pct','micro_cer_pct','exact_e2e_pct','no_read_e2e_pct')
    s.metrics[metric]=MetricEligibility(metric,n_scored=n,n_total_eligible=total,
        n_unscored=total-n if n is not None and total is not None else None,
        missing_reasons=(reason,),explanation=explanation or s.source_reason or s.quality_reason,
        evidence_paths=(s.input.source_path,),gt_origin=('ASSISTED' if s.metadata.get('review_revision') is not None else 'UNVERIFIED') if needs_gt else 'NOT_APPLICABLE',
        review_revision=s.metadata.get('review_revision') if needs_gt else None)

def _metric(s,key,value,n,total,*,reasons=(),quality=False,numerator=None,denominator=None,subset=False,explanation=''):
    status='N/A' if value is None else 'SUBSET' if subset or (total is not None and n<total) else 'FULL'
    s.metrics[key]=MetricEligibility(key,status,value,n,total,total-n if total is not None else None,
        tuple(dict.fromkeys(reasons)),numerator,denominator,'ASSISTED' if quality else 'NOT_APPLICABLE',
        s.metadata.get('review_revision') if quality else None,
        'UNAVAILABLE' if value is None else 'ASSISTED_SUBSET' if quality and status=='SUBSET' else 'ASSISTED' if quality else 'DESCRIPTIVE',
        tuple(s.metadata.get('quality_evidence',[])) if quality else (s.input.source_path,),explanation)

def _quality(s,review):
    """Consume the existing frozen scorer; never replace its matcher or GT."""
    from ..ranking.mobile_human_review import MobileReviewSession
    from ..ranking.mobile_mt_detection_evaluation import evaluate_session,POLICY_SHA256
    from .mobile_measurement_availability import limits_text
    quality_keys=[k for k in METRICS if k.startswith('mt_') and k not in ('mt_calls','mt_p50_ms','mt_p95_ms')]
    quality_keys+=['pose_availability_pct','polygon_iou_pct','nmce_pct','exact_mz_pct','micro_cer_pct']
    if review is None:
        for key in quality_keys:_missing(s,key,'EXPORT_STALE' if s.quality_state in ('STALE','NEEDS_EXPORT') else 'QUALITY_NOT_VERIFIED')
        return
    c=review.canvas or {}
    s.metadata['review_revision']=review.review_revision
    s.metadata['quality_evidence']=[str(review.directory/'export_manifest.json'),str(review.directory/'review.json')]
    try:
        read_only=MobileReviewSession.open(s.input.source_path,sidecar_path=review.directory/'review.json')
        mt=evaluate_session(read_only)
        if mt['matching_policy_sha256']!=POLICY_SHA256 or mt.get('alias_conflicts'):
            raise ValueError('Niepotwierdzony kontrakt dopasowania lub tożsamość jednostek.')
        if review.mt_evaluation is not None and _digest(mt)!=_digest(review.mt_evaluation):
            raise ValueError('Zapisane wyniki MT nie zgadzają się z kanonicznym odczytem źródła i tej rewizji GT.')
        units=mt['units'];qualified=[u for u in units if u['status']=='MEASURED']
        assert len({u['unit_id'] for u in units})==len(units)
        assert all(u['session_id']==s.input.session_id and u['source_archive_sha256']==s.input.source_sha256 for u in units)
        for u in qualified:
            assert all(type(u[k]) is int and u[k]>=0 for k in ('tp','fp','fn','n_gt','n_final_mt'))
            assert u['tp']+u['fn']==u['n_gt'] and u['tp']+u['fp']==u['n_final_mt']
            assert len(u['matched_pairs'])==u['tp'] and len(u['final_outcomes'])==u['n_final_mt']
        n=len(qualified);total=len(units)
        counts={k:sum(u[k] for u in qualified) for k in ('tp','fp','fn')}
        assert all(mt[k]==v for k,v in counts.items()) and n==mt['n_qualified'] and total==mt['n_total']
        labels={r.get('mt_invocation_id'):f'Obraz {i:02d}' for i,r in enumerate(c.get('scenes',[]),1)}
        s.quality_units=[dict(unit_id=u['unit_id'],mt_invocation_id=u['mt_invocation_id'],image=u.get('image_entry'),
            label=labels.get(u['mt_invocation_id'],u['mt_invocation_id']),status=u['status'],tp=u['tp'],fp=u['fp'],fn=u['fn'],
            missing_reasons=u['unavailable_reasons']) for u in units]
        reasons=[r for u in units if u['status']!='MEASURED' for r in u['unavailable_reasons']]
        for k in counts:_metric(s,'mt_'+k,counts[k] if n else None,n,total,reasons=reasons,quality=True)
        tp,fp,fn=(counts[k] for k in ('tp','fp','fn'))
        for key,num,den in (('mt_precision_pct',tp,tp+fp),('mt_recall_pct',tp,tp+fn),('mt_f1_pct',2*tp,2*tp+fp+fn)):
            _metric(s,key,100*num/den if n and den else None,n,total,reasons=reasons or (() if den else ('ZERO_DENOMINATOR',)),
                quality=True,numerator=num,denominator=den,explanation=f'{n}/{total} kompletnych jednostek MT/ROI; BBOX IoU ≥ 0,50, FINAL, greedy 1:1.')
    except (OSError,ValueError,KeyError,TypeError,AssertionError) as exc:
        for key in quality_keys[:6]:_missing(s,key,'MT_COUNTS_NOT_VERIFIED',explanation=str(exc))
    # Geometry/OCR retain their established complete Canvas validator. A partial
    # detector denominator is not evidence for a partial geometry/OCR denominator.
    if not review.canvas_ready:
        for key in ('pose_availability_pct','polygon_iou_pct','nmce_pct','exact_mz_pct','micro_cer_pct'):
            _missing(s,key,'CANVAS_METRIC_DENOMINATOR_NOT_VERIFIED',explanation=limits_text(c,review.mt_evaluation)
                +'\nZakres geometrii/MZ wymaga pełnej walidacji Canvas; częściowe sumy nie wystarczają do zatwierdzenia tej miary.')
        return
    linked=[r for r in c.get('rows',[]) if r.get('included') and r.get('outcome')=='LINKED_MT' and not r.get('post_nms_suppressed_raw')]
    geometry=int(c['geometry_n']);pose_known=geometry+int(c.get('pose_invalid_matches',0))
    pose_unknown=int(c.get('pose_evidence_unavailable_matches',0))
    _metric(s,'pose_availability_pct',100*geometry/pose_known if pose_known else None,pose_known,pose_known+pose_unknown,
        quality=True,numerator=geometry,denominator=pose_known,reasons=('POSE_STATUS_UNAVAILABLE',) if pose_unknown else ())
    for key,value in (('polygon_iou_pct',c.get('polygon_iou_mean_pct')),('nmce_pct',c.get('nmce_mean_pct'))):
        _metric(s,key,value if geometry else None,geometry,len(linked),quality=True,
            reasons=('POSE_INVALID_OR_UNAVAILABLE',) if geometry<len(linked) else (),explanation='Wyłącznie rzeczywiste źródłowe Pose i GTR; nie BBOX jako Pose.')
    n=c['evaluated_reads'];chars=c['gt_characters'];errors=c['text_errors']
    _metric(s,'exact_mz_pct',100*c['exact_reads']/n if n else None,n,n,quality=True,numerator=c['exact_reads'],denominator=n,
        explanation='Warunkowe wykonane odczyty z czytelnym GTZ. NOT_RUN poza mianownikiem; to nie E2E.')
    _metric(s,'micro_cer_pct',100*errors/chars if chars else None,n,n,quality=True,numerator=errors,denominator=chars,
        explanation='Suma odległości edycyjnych / suma znaków GTZ; nie średnia procentów CER.')

def _source(inp):
    from .mobile_report_source_recovery import restore_source
    from .mobile_import_comparison import record_from_import,_read_all_traces,_sha_file
    from .mobile_report_canvas_view import selected_canvas_export
    from .mobile_comparison_scope import trace_digest
    from .z4_mobile_report_browser_ux import report_identity
    info=report_identity(inp.report)
    s=SourceValidation(inp,'SOURCE_MISSING','',metadata=dict(scenario=info['scenario'] or 'NIEOKREŚLONY',
        variant=info['variant'],repeat='—',experiment='UNPROVEN'))
    restored=restore_source(inp.report,inp.source_path)
    if not restored.ok:
        s.source_status='SOURCE_MISMATCH' if restored.status in ('mismatch','no_fingerprint') else 'SOURCE_MISSING' if restored.status=='missing' else 'MANIFEST_INVALID'
        s.source_reason=restored.detail+' · '+inp.source_path
        for key in METRICS:_missing(s,key,s.source_status)
        s.fingerprint=dict(source_status=s.source_status,expected_sha=inp.source_sha256)
        return s
    s.bundle=restored.bundle
    try:
        record,rows,warnings=record_from_import(inp.report,s.bundle,include_review=False)
        if record.session_id!=inp.session_id or _sha_file(Path(inp.source_path))!=inp.source_sha256:
            raise ValueError('Sprzeczny session_id/SHA albo zmiana źródła podczas odczytu.')
        s.source_status='VERIFIED';s.source_reason='Oryginalne archiwum, manifest i tożsamość sprawdzone.';s.record=record
        _,trace_state=_read_all_traces(s.bundle)
        with REGISTRY.open(encoding='utf-8-sig',newline='') as f:registry=list(csv.DictReader(f,delimiter=';'))
        mapping=next((r for r in registry if r['archive_sha256']==inp.source_sha256),None)
        s.metadata.update(scenario=record.scenario,variant=record.precision.upper(),repeat=record.repeat_label,
            apk_sha256=record.apk_sha256,device=record.device,mt_checkpoint=record.mt_checkpoint,mz_checkpoint=record.mz_checkpoint,
            package_and_models=record.model_identity,trace_count=len(rows),trace_state=trace_state,registry_verified=bool(mapping))
        if mapping:
            if record.scenario!=mapping['scenario']:raise ValueError('Scenariusz źródła niezgodny z rejestrem SHA F4.')
            s.metadata.update(experiment='F4',variant=mapping['analysis_variant'],repeat=mapping['rNN_folder'],
                source_variant=mapping['source_variant'],source_replicate_index=mapping['source_replicate_index'],
                mapping_evidence=str(REGISTRY),mapping_sha256=_sha_file(REGISTRY))
        for stage,prefix in (('mt','mt'),('mz','mz_trace'),('pipeline','pipeline')):
            met=record.latency[stage];total=len(rows) if trace_state=='complete' else None
            for pct in ('p50','p95'):
                key=f'{prefix}_{pct}_ms'
                if trace_state!='complete':_missing(s,key,'INCOMPLETE_TRACE_SOURCE')
                else:_metric(s,key,getattr(met,pct+'_ms'),met.n,total,
                    reasons=('STAGE_NOT_RUN_OR_INVALID_TRACE',) if met.n<len(rows) else (),
                    explanation='Pełny strumień Androida; percentyl per sesja. MZ to suma etapu w śladzie, nie pojedyncze MZ.')
        valid=[r for r in rows if str(r.get('status','')).lower() not in ('scene_superseded','runtime_error','pipeline_error','cancelled','not_run')]
        for key,col in (('mt_calls','mt_runs_this_frame'),('mz_calls','mz_runs')):
            try:
                values=[int(r[col]) for r in valid];assert all(v>=0 for v in values) and trace_state=='complete'
                _metric(s,key,sum(values),len(valid),len(rows))
                if key=='mt_calls' and any(v!=1 for v in values):
                    for pct in ('p50','p95'):_missing(s,f'mt_{pct}_ms','MT_CALL_TIMING_UNPROVEN',explanation='Czas śladu może sumować wiele MT; brak pojedynczych czasów wywołań.')
            except (KeyError,ValueError,TypeError,AssertionError):_missing(s,key,'CALL_COUNT_UNAVAILABLE')
        _missing(s,'mz_call_p95_ms','PER_CALL_TIMING_UNAVAILABLE',explanation='Nie dzielimy percentyli sumy czasu przez liczbę MZ.')
        for key in ('scene_coverage_pct','exact_e2e_pct','no_read_e2e_pct'):
            _missing(s,key,'SCENE_UNMAPPED',explanation='Brak zweryfikowanej mapy plansza→GT i reguły wyboru odczytu z okna. F4 nie jest niezależnym F6.')
        pss=[]
        for r in rows:
            try:
                v=float(r.get('pss_end_kb',''));assert math.isfinite(v) and v>=0;pss.append(v/1024)
            except (ValueError,TypeError,AssertionError):pass
        if pss:_metric(s,'pss_peak_mib',max(pss),len(pss),len(rows))
        else:_missing(s,'pss_peak_mib','OS_PSS_NOT_MEASURED')
        side=inp.review_root/'human_reviews'/(inp.source_sha256+'.review.json')
        side_hash=None
        try:
            side_hash=_sha_file(side) if side.is_file() else None
            gate,review=selected_canvas_export(inp.session_id,inp.source_sha256,inp.results_root,inp.review_root)
            s.quality_state=gate.state;s.quality_reason=gate.reason
            if inp.review_seen and not side.is_file():
                s.quality_state='STALE';s.quality_reason='Bieżąca ocena zniknęła po wyborze; jakość wymaga ponownej weryfikacji źródła eksportu.';review=None
            if review is not None and side.is_file():
                live=json.loads(side.read_text(encoding='utf-8-sig'));exported=json.loads((review.directory/'review.json').read_text(encoding='utf-8-sig'))
                for doc in (live,exported):doc.pop('derived_metrics',None)
                if live!=exported:
                    s.quality_state='STALE';s.quality_reason='Treść bieżącej oceny różni się od eksportu; wymagany świeży eksport.';review=None
            _quality(s,review)
            quality_manifest=review.manifest_sha256 if review else None
        except (OSError,ValueError,TypeError,KeyError) as exc:
            s.quality_state='UNREADABLE';s.quality_reason=str(exc);quality_manifest=None;_quality(s,None)
        s.fingerprint=dict(source_status=s.source_status,source_sha=inp.source_sha256,trace_digest=trace_digest(rows),
            quality_state=s.quality_state,review_manifest_sha=quality_manifest,sidecar_sha=side_hash,
            metric_digest=_digest({k:m.payload() for k,m in s.metrics.items()}),metadata_digest=_digest(s.metadata))
        return s
    except (OSError,ValueError,TypeError,KeyError) as exc:
        s.source_status='SOURCE_MISMATCH';s.source_reason=str(exc);s.record=None
        s.metrics={}
        for key in METRICS:_missing(s,key,s.source_status)
        s.fingerprint=dict(source_status=s.source_status,expected_sha=inp.source_sha256)
        return s

def analyze(inputs, question='F4'):
    if question not in QUESTIONS:raise ValueError('F6 wymaga osobnego niezależnego raportu; nie jest porównaniem wariantów F4.')
    unique=[];duplicates=[];ids=set();shas=set()
    for inp in inputs:
        if inp.session_id in ids or inp.source_sha256 in shas:
            duplicates.append(dict(session_id=inp.session_id,source_archive_sha256=inp.source_sha256,reason='DUPLICATE_SOURCE_NOT_INDEPENDENT'));continue
        unique.append(inp);ids.add(inp.session_id);shas.add(inp.source_sha256)
    sessions=[_source(inp) for inp in unique]
    from .mobile_report_scientific_comparability import assess_cohort
    reports=[s.bundle.report for s in sessions if s.bundle is not None and s.source_status=='VERIFIED']
    for s in sessions:
        if s.source_status=='VERIFIED':s.conditions=assess_cohort(s.bundle.report,reports,bundle=s.bundle)
        if s.source_status=='VERIFIED' and question!='DIAGNOSTIC' and s.metadata.get('experiment')!=question:
            s.metrics={k:replace(m,status='NOT_COMPARABLE',value=None,missing_reasons=tuple((*m.missing_reasons,'QUESTION_SOURCE_NOT_PROVEN')),
                n_scored=None,n_total_eligible=None,n_unscored=None,numerator=None,denominator=None,review_revision=None,inference_scope='UNAVAILABLE',
                explanation='Brak udowodnionego materiału dla tego pytania. Źródło pozostaje w diagnostyce.') for k,m in s.metrics.items()}
    return AnalysisCohort(tuple(unique),sessions,question,duplicates)
