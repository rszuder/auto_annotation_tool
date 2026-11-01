"""Figures and atomic, revalidated exports of ALPR-ANALYSIS-1.0 results."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import csv,hashlib,json,shutil,tempfile,textwrap
from .mobile_analysis import analyze,PROTOCOL_ID,IMPLEMENTATION_ID,METRICS,QUESTIONS

DEFAULT_FIGURES=('mt_p50_ms','mt_p95_ms','mz_trace_p50_ms','mz_trace_p95_ms',
    'pipeline_p50_ms','pipeline_p95_ms','mt_f1_pct','polygon_iou_pct','exact_mz_pct','micro_cer_pct')

def make_figure(cohort,metric_id,scenario):
    from matplotlib.figure import Figure
    if metric_id not in METRICS:raise ValueError('Nieznana miara.')
    sessions=[s for s in cohort.sessions if s.metadata.get('scenario')==scenario]
    if not sessions:raise ValueError('Brak sesji w tym scenariuszu.')
    title,unit,_=METRICS[metric_id]
    fig=Figure(figsize=(12,max(5.4,2.7+.7*len(sessions))));ax=fig.subplots()
    fig.subplots_adjust(left=.23,right=.96,top=.82,bottom=.25)
    values=[s.metrics[metric_id].value for s in sessions]
    maximum=max((v for v in values if v is not None),default=1)
    ax.set_xlim(0,max(1,maximum*1.42));ax.set_ylim(len(sessions)-.4,-.6)
    ax.set_yticks(list(range(len(sessions))),[f"{s.metadata.get('variant')} · {s.metadata.get('repeat')}\n{s.input.session_id[-8:]}" for s in sessions],fontsize=9)
    for i,s in enumerate(sessions):
        m=s.metrics[metric_id];n='N/A' if m.n_scored is None else str(m.n_scored)
        missing='N/A' if m.n_unscored is None else str(m.n_unscored)
        label=f'{m.status} · n={n} · braki={missing}'
        if m.value is None:
            ax.text(.02,i,label,transform=ax.get_yaxis_transform(),va='center',fontsize=9,color='#855800')
        else:
            ax.barh(i,m.value,height=.42,color='#2979a4' if m.status=='FULL' else '#ce8b22')
            ax.text(m.value+ax.get_xlim()[1]*.012,i,f'{m.value:.2f} · {label}',va='center',fontsize=8)
    question={'F4':'Jak konfiguracja FP32/INT8 wiąże się z kosztami i jakością?',
        'F5A':'Jaki jest koszt i pokrycie MP/ROI?', 'F5B':'Jaki jest koszt i efekt AutoZoom?',
        'DIAGNOSTIC':'Które miary mają wiarygodne źródło?'}[cohort.question]
    fig.suptitle(question+'\n'+PROTOCOL_ID+' · DESCRIPTIVE · '+scenario,fontsize=10,y=.98)
    ax.set_title(title,fontsize=11,pad=12);ax.set_xlabel(unit);ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True)
    note=('n i braki dotyczą jednostki wybranej miary, nie niezależnych plansz. MZ/ślad może sumować wiele wywołań. '
        'GT ASSISTED; odmienne podzbiory nie uzasadniają rankingu jakości. E2E bez mapy scen = N/A. '
        'Źródła SHA: '+', '.join(s.input.source_sha256[:12] for s in sessions)+'; pełne pochodzenie w JSON/CSV.')
    fig.text(.04,.045,'\n'.join(textwrap.wrap(note,130)),fontsize=8,va='bottom')
    fig._alpr_analysis=dict(metric_id=metric_id,scenario=scenario,protocol=PROTOCOL_ID,
        sources=[s.input.source_sha256 for s in sessions],values=values,protocol_files=cohort.protocol_files)
    return fig

def figure_plan(cohort,metrics=None):
    # Empty charts remain selectable in the UI as diagnostics, but are not
    # exported as decorative evidence of an unperformed experiment.
    for scenario in sorted({s.metadata.get('scenario','NIEOKREŚLONY') for s in cohort.sessions}):
        for key in metrics or DEFAULT_FIGURES:
            if any(s.metadata.get('scenario')==scenario and s.metrics[key].value is not None for s in cohort.sessions):
                yield scenario,key

def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _fingerprint(cohort):
    return dict(protocol_files=cohort.protocol_files,sessions={s.input.session_id:s.fingerprint for s in cohort.sessions})

def export_analysis(cohort,results_root,*,metrics=None):
    """Quality may become N/A before rendering; changes during rendering abort."""
    fresh=analyze(cohort.inputs,cohort.question)
    old={s.input.session_id:s for s in cohort.sessions}
    for s in fresh.sessions:
        if old[s.input.session_id].source_status=='VERIFIED' and s.source_status!='VERIFIED':
            raise ValueError('Oryginał zmienił się lub jest niedostępny. Odśwież analizę: '+s.input.source_path)
    root=Path(results_root)
    if not root.is_dir() or root.name.lower()!='03_wyniki':raise ValueError('Wskaż istniejący katalog 03_wyniki.')
    parent=root/'porownanie'
    if not parent.is_dir():raise ValueError('Brak istniejącego katalogu porownanie.')
    stage=Path(tempfile.mkdtemp(prefix='.alpr_analysis_stage_',dir=parent));files=[]
    try:
        payload=fresh.payload()
        data=stage/'analysis.json';data.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding='utf-8');files.append(data)
        csv_path=stage/'readiness_matrix.csv'
        with csv_path.open('w',encoding='utf-8-sig',newline='') as stream:
            columns=['analysis_protocol_id','question','interpretation','session_id','report_id','source_archive_sha256','scenario','variant','repeat',
                'source_status','quality_state','metric_id','status','unit','observation_unit','value','n_scored','n_total_eligible','n_unscored',
                'coverage','numerator','denominator','gt_origin','review_revision','missing_reasons','explanation','evidence_paths','implementation_id']
            writer=csv.DictWriter(stream,fieldnames=columns,delimiter=';');writer.writeheader()
            for s in fresh.sessions:
                for m in s.metrics.values():
                    row=m.payload();row.update(question=fresh.question,interpretation=fresh.interpretation,
                        session_id=s.input.session_id,report_id=s.input.report_id,source_archive_sha256=s.input.source_sha256,
                        source_status=s.source_status,quality_state=s.quality_state,
                        **{k:s.metadata.get(k) for k in ('scenario','variant','repeat')})
                    row['missing_reasons']=' | '.join(row['missing_reasons']);row['evidence_paths']=' | '.join(row['evidence_paths'])
                    writer.writerow({k:row.get(k) for k in columns})
        files.append(csv_path)
        import matplotlib.pyplot as plt
        for scenario,key in figure_plan(fresh,metrics):
            import re
            name=re.sub(r'[^A-Za-z0-9_-]','_',scenario)+'_'+key
            fig=make_figure(fresh,key,scenario)
            try:
                description=json.dumps(fig._alpr_analysis,ensure_ascii=False)
                for ext in ('png','svg'):
                    p=stage/(name+'.'+ext);fig.savefig(p,dpi=180 if ext=='png' else None,metadata={'Description':description});files.append(p)
            finally:plt.close(fig)
        report=stage/'analysis_report.md'
        lines=['# '+QUESTIONS[fresh.question], '',PROTOCOL_ID+' — protokół retrospektywny dla F4, ustalony 31.10.2026; nie prerejestracja.',
            '', '**DESCRIPTIVE.** Brak zatwierdzenia wniosku przyczynowego lub niezależnego F6.','',
            '| Scenariusz | Sesja | Źródło | Ocena | MT p95 [ms] / n | MZ/ślad p95 [ms] / n | BBOX F1 / jednostki |','|---|---|---|---|---|---|---|']
        for s in fresh.sessions:
            def show(key):
                m=s.metrics[key];return f'{m.value:.3f} / {m.n_scored} ({m.status})' if m.value is not None else m.status+' — '+', '.join(m.missing_reasons)
            lines.append(f"| {s.metadata.get('scenario')} | {s.metadata.get('variant')} {s.metadata.get('repeat')} · {s.input.session_id} | {s.source_status} | {s.quality_state} | {show('mt_p95_ms')} | {show('mz_trace_p95_ms')} | {show('mt_f1_pct')} |")
        lines+=['','## Czasy i nakład wywołań','',
            '| Scenariusz / wariant / rNN | Etap | n | p50 [ms] | p95 [ms] | Wywołania MZ w sesji |','|---|---|---:|---:|---:|---:|']
        for s in fresh.sessions:
            label=f"{s.metadata.get('scenario')} / {s.metadata.get('variant')} / {s.metadata.get('repeat')}"
            def number(v):return 'N/A' if v is None else f'{v:.6f}'
            for prefix,title in (('mt','MT'),('mz_trace','MZ/ślad'),('pipeline','potok ALPR')):
                a,b=s.metrics[prefix+'_p50_ms'],s.metrics[prefix+'_p95_ms']
                lines.append(f"| {label} | {title} | {a.n_scored if a.n_scored is not None else 'N/A'} | {number(a.value)} | {number(b.value)} | {number(s.metrics['mz_calls'].value)} |")
        lines+=['','## Ograniczenia','',*['- '+n for n in payload['limitations']], '',
            'Pełne liczniki, mianowniki, braki per jednostka, SHA i audyt warunków znajdują się w analysis.json i readiness_matrix.csv.']
        report.write_text('\n'.join(lines),encoding='utf-8');files.append(report)
        final=analyze(fresh.inputs,fresh.question)
        if _fingerprint(final)!=_fingerprint(fresh):raise ValueError('Dane zmieniły się podczas eksportu. Nie opublikowano częściowego wyniku.')
        manifest=dict(schema='alpr.analysis.export.v1',analysis_protocol_id=PROTOCOL_ID,implementation_id=IMPLEMENTATION_ID,
            protocol_files=fresh.protocol_files,
            chronology='RETROSPECTIVE_FOR_F4_NOT_PREREGISTERED',generated_utc=datetime.now(timezone.utc).isoformat(),
            question=fresh.question,interpretation='DESCRIPTIVE',fingerprints=_fingerprint(fresh),
            sources=[dict(session_id=s.input.session_id,report_id=s.input.report_id,source_archive_sha256=s.input.source_sha256,
                source_path=s.input.source_path,quality_state=s.quality_state,**s.metadata) for s in fresh.sessions],
            files=[dict(name=p.name,bytes=p.stat().st_size,sha256=_sha(p)) for p in files],
            algorithm_sha256={p.name:_sha(p) for p in (Path(__file__),Path(__file__).with_name('mobile_analysis.py'))})
        (stage/'analysis_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        stem='analiza_'+fresh.question+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        for i in range(1,100000):
            target=parent/f'{stem}_{i:03d}'
            if not target.exists():break
        else:raise ValueError('Brak wolnego numeru eksportu.')
        stage.rename(target)
        return target,fresh
    finally:
        if stage.exists():
            assert stage.resolve().is_relative_to(parent.resolve())
            shutil.rmtree(stage)
