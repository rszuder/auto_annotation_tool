"""Read-only operator work units. Scientific readiness/scoring stay canonical."""
from __future__ import annotations
from ..ranking import mobile_canvas_review as core,mobile_candidate_stacks as stacks,mobile_canvas_partial_review as partial
from ..ranking.mobile_canvas_operator_view import reference_numbers
from .mobile_canvas_spatial_reference import project


def pending_review_units(scene,state,*,issues=()):
    """Pair one pending FINAL with its reference; never merge distinct FINALs.

    `reasons` retain every canonical pending record. A reference reason is
    attached once, whereas each unresolved FINAL retains its own source ID.
    Whole-image inspection, missing text and evidence are separate steps.
    """
    if not scene:return dict(units=[],count=0,steps=[dict(kind='SOURCE',text='Brak pełnego obrazu')],next_action='Brak pełnego obrazu',needs_review=False)
    if scene.get('exclusion_reason'):return dict(units=[],count=0,steps=[],next_action='Obraz poza oceną',needs_review=False)
    progress=partial.progress(scene);numbers=reference_numbers(state)
    finals={c['object_id']:c for c in state['candidates'] if c['role']=='FINAL'}
    pending_gt=set(progress['pending_gtr_ids']);used=set();units=[];steps=[]
    objects={o['object_id']:o for o in scene['objects']}
    def target(c):
        pid=c.get('plate_id');rel=c.get('spatial_relation',{});canonical=c.get('canonical_link',{})
        if not pid and canonical.get('status')=='ASSOCIATED_FOR_GEOMETRY':
            # A removed/moved outline does not erase the explicit physical ID.
            pid=canonical.get('plate_id')
        if pid not in state['plates'] or rel.get('conflict'):return None
        origin=objects.get(state['plates'][pid]['origin_object_id'],{})
        if c['object_id'] in origin.get('separate_from_mt',()):return None
        if canonical.get('plate_id') not in (None,pid):return None
        return pid
    for oid in progress['pending_ids']:
        c=finals.get(oid)
        if not c:continue
        pid=target(c);reasons=['pending_mt:'+oid]
        if pid in pending_gt and pid not in used:reasons.append('pending_gtr:'+pid);used.add(pid)
        text=f"Zweryfikuj tablicę GTR {numbers[pid]}" if pid in numbers else f"Zweryfikuj wskazanie MT {c['mt_detection_index']+1}"
        if pid in state['plates'] and not state['plates'][pid]['gt_quad']:text=f"Narysuj obrys GTR {numbers.get(pid,'—')} (D)"
        units.append(dict(id=f"{scene['mt_invocation_id']}:FINAL:{c['attempt_id']}:GT:{pid or '-'}",kind='PAIR' if pid else 'MT',physical_gt_id=pid,final_mt_id=c['attempt_id'],object_id=oid,reasons=reasons,text=text))
    for pid in sorted(pending_gt-used):
        p=state['plates'][pid]
        c=next((c for c in finals.values() if target(c)==pid),None)
        text=f"Narysuj obrys GTR {numbers.get(pid,'—')} (D)" if not p['gt_quad'] else f"Zweryfikuj tablicę GTR {numbers.get(pid,'—')}"
        units.append(dict(id=f"{scene['mt_invocation_id']}:GT:{pid}",kind='PAIR' if c else 'GTR',physical_gt_id=pid,final_mt_id=c['attempt_id'] if c else None,object_id=c['object_id'] if c else p['origin_object_id'],reasons=['pending_gtr:'+pid],text=text))
    if progress['source_unknown']:steps.append(dict(kind='SOURCE',text='Wyjaśnij brak lub sprzeczność danych źródłowych'))
    text_issues=[v for v in issues if 'GT numeru' in v or 'GTZ' in v]
    if text_issues:steps.append(dict(kind='GTZ',text='Uzupełnij GTZ przy tablicy',reasons=text_issues))
    if not scene['checked']:
        steps.append(dict(kind='SCENE',text='Potwierdź brak tablic na całym obrazie' if progress['empty_eligible'] else 'Sprawdź cały obraz'))
    # Keep all existing blockers auditable, without counting them as plates.
    other=[v for v in issues if v not in text_issues and not any(x in v for x in ('Rozstrzygnij wskazanie','Potwierdź obecność','Zatwierdź nową','nie został oznaczony jako sprawdzony'))]
    if other and not units and not progress['source_unknown'] and not progress['empty_eligible']:
        steps.append(dict(kind='DATA',text='Sprawdź brakujące dane w szczegółach',reasons=other))
    action=steps[0]['text'] if progress['source_unknown'] else units[0]['text'] if units else steps[0]['text'] if steps else 'Obraz zweryfikowany'
    return dict(units=units,count=len(units),steps=steps,next_action=action,needs_review=bool(units or steps),canonical_progress=progress,diagnostic_issues=list(issues))


def for_scene(session,gid,scene=None,*,issues=None):
    scene=scene if scene is not None else core.scene(session,gid,include_history=False)
    state=stacks.snapshot(session,gid,scene)
    return pending_review_units(scene,project(session,gid,scene,state),issues=core.approval_scene_issues(scene) if issues is None else issues)


def inventory(session,canonical):
    """Decorate GUI rows; preserve status, cells, approval gates and old totals."""
    result=dict(canonical,groups={});total=0;steps=0
    for gid,item in canonical['groups'].items():
        task=for_scene(session,gid,item['scene'],issues=item.get('approval_issues',item['issues'])) if item['scene'] else pending_review_units(None,None)
        result['groups'][gid]=dict(item,review_tasks=task)
        total+=task['count'];steps+=len(task['steps'])
    result.update(task_decisions=total,task_steps=steps)
    return result


def image_action(rows):
    if not rows:return 'Poza oceną','canvas_excluded'
    if all(r['status']=='EXCLUDED' for r in rows):return 'Poza oceną','canvas_excluded'
    if all(r['status']=='READY' for r in rows):return 'Zweryfikowany','canvas_ready'
    tasks=[r['review_tasks'] for r in rows];count=sum(t['count'] for t in tasks)
    kinds={s['kind'] for t in tasks for s in t['steps']}
    if 'SOURCE' in kinds:return 'Sprawdź źródło','canvas_pending'
    if count:return f'Decyzje: {count}','canvas_pending'
    if 'GTZ' in kinds:return 'Uzupełnij GTZ','canvas_pending'
    if 'SCENE' in kinds:return 'Sprawdź obraz','canvas_pending'
    if 'DATA' in kinds:return 'Uzupełnij dane','canvas_pending'
    return 'Zweryfikowany','canvas_ready'
