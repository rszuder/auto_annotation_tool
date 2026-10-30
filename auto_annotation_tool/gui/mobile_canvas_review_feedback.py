"""Explain review work and source-bound matching; never persist decisions."""
from __future__ import annotations
import tkinter as tk

def operator_inventory(scene,state):
    """Saved IDs, proven FINALs and explicit links; no IoU or TP/FP/FN here."""
    from ..ranking.mobile_canvas_operator_view import physical_plate_ids,reference_numbers
    from ..ranking import mobile_canvas_partial_review as partial
    empty=dict(counts=dict.fromkeys(('gt','mt','rejected','unlinked')),rejected=[],unlinked=[])
    if not scene or not state:return empty
    progress=partial.progress(scene)
    if progress['source_unknown'] or scene.get('exclusion_reason'):return empty
    saved=physical_plate_ids(scene,state)
    finals=[c for c in state['candidates'] if c['role']=='FINAL']
    linked={link['plate_id'] for c in finals for link in [state['links'].get(c['object_id'],{})]
            if link.get('status')=='ASSOCIATED_FOR_GEOMETRY' and link.get('plate_id') in saved}
    rejected=[dict(oid=c['object_id'],label=f"MT {c['mt_detection_index']+1}",kind='BBOX') for c in finals
              if progress['object_decisions'].get(c['object_id'])==partial.NOT_PLATE]
    numbers=reference_numbers(state)
    unlinked=[dict(gt_id=pid,oid=p['origin_object_id'],label=f"GTR {numbers[pid]}" if pid in numbers else 'GT bez obrysu',kind='GTR')
              for pid,p in state['plates'].items() if pid in saved-linked]
    return dict(counts=dict(gt=len(saved),mt=len(finals),rejected=len(rejected),unlinked=len(unlinked)),
                rejected=rejected,unlinked=unlinked)

def operator_view(ed):
    from .mobile_canvas_clean_view import source,records
    value=operator_inventory(ed._read(),source(ed));rows=records(ed)
    # Use the visible reference alias without changing its physical identity.
    for item in value['unlinked']:
        row=next((r for r in rows if r['pid']==item['gt_id'] and r['gt']),None)
        if row:item['oid']=row['oid']
    return value

def reference_comparison(ed,row,result=None):
    from ..ranking.mobile_mt_geometry_layers import source_bbox
    from ..ranking.mobile_mt_detection_evaluation import evaluate_unit,box_iou,POLICY
    result=result or evaluate_unit(ed.h.session,ed.h.current_invocation)
    c=row.get('candidate');p=row.get('plate')
    if (result['status']!='MEASURED' or not c or not p or not row['gt']
            or c['role']!='FINAL' or c['association_status']!='ASSOCIATED_FOR_GEOMETRY'):
        return None
    bbox=source_bbox(ed.h.session,ed._read(),c)
    if not bbox:return None
    q=row['gt'];gt_bbox=[min(v[0] for v in q),min(v[1] for v in q),max(v[0] for v in q),max(v[1] for v in q)]
    return dict(attempt_id=c['attempt_id'],gt_id=row['pid'],number=row['n'],bbox=list(bbox),gt_bbox=gt_bbox,
                iou=box_iou(bbox,gt_bbox),threshold=POLICY['match_iou'])

def image_feedback(ed,result=None):
    from .mobile_canvas_clean_view import source,records
    from ..ranking import mobile_canvas_partial_review as partial
    from ..ranking.mobile_mt_detection_evaluation import evaluate_unit
    scene=ed._read();state=source(ed)
    if not scene or not state:return dict(status='UNAVAILABLE',fp=[],fn=[],text='')
    result=result or evaluate_unit(ed.h.session,ed.h.current_invocation)
    rows=records(ed);progress=partial.progress(scene)
    out=dict(status=result['status'],fp=[],fn=[],text='')
    if result['status']!='MEASURED':
        pending=progress['pending_ids'];gtr=progress['pending_gtr_ids']
        row=next((r for r in rows if len(pending)==len(gtr)==1 and r['oid']==pending[0] and r['pid']==gtr[0]),None)
        if row and progress['decisions']==1 and not scene.get('exclusion_reason'):
            index=row['candidate']['mt_detection_index']+1
            out['text']=f"1 tablica do weryfikacji:\nWskazanie MT {index} i obrys GTR {row['n']}.\nSpacja przełącza ich wspólną ocenę."
        return out
    candidates={c['attempt_id']:c for c in state['candidates'] if c['role']=='FINAL'}
    for value in result['final_outcomes']:
        if value['outcome']=='FP' and value['attempt_id'] in candidates:
            c=candidates[value['attempt_id']]
            out['fp'].append(dict(value,oid=c['object_id'],label=f"MT {c['mt_detection_index']+1}",kind='BBOX'))
    for pid in result.get('unmatched_gt_ids',[]):
        row=next((r for r in rows if r['pid']==pid and r['gt']),None)
        if row:out['fn'].append(dict(gt_id=pid,oid=row['oid'],label=f"GTR {row['n']}",kind='GTR'))
    messages=[]
    if out['fp']:messages.append('FP: '+', '.join(v['label'] for v in out['fp']))
    if out['fn']:messages.append('FN: '+', '.join(v['label'] for v in out['fn']))
    if messages:
        out['text']=' · '.join(messages)+'.'
        if len(out['fp'])==len(out['fn'])==1:
            fp,fn=out['fp'][0],out['fn'][0]
            row=next((r for r in rows if r['oid']==fp['oid'] and r['pid']==fn['gt_id']),None)
            comparison=reference_comparison(ed,row,result) if row else None
            if comparison and fp['reason']=='LOCALIZATION_CRITERION_NOT_MET':
                iou=f"{100*comparison['iou']:.2f}%".replace('.',',');threshold=f"{100*comparison['threshold']:g}%"
                out['text']=f"Tablica wykryta — BBOX nie spełnia kryterium lokalizacji.\n{fp['label']} ↔ {fn['label']}: IoU {iou} < {threshold}.\nFormalne FP/FN dotyczą tej samej tablicy."
        if any(v['reason']=='DUPLICATE_FINAL' for v in out['fp']):
            out['text']+='\nDodatkowe wskazanie tej samej GT: dopasowanie BBOX jest 1:1.'
        out['text']+='\nKliknij FP/FN w ocenie BBOX, aby wskazać geometrię.'
    return out

def inspect(ed,kind):
    from . import mobile_canvas_clean_view as clean,mobile_canvas_navigator as nav
    if not ed.available():return False
    if ed.entry is not None or ed.drag or ed.mode=='draw' or ed.busy or ed.h._saving:
        ed.message('Zakończ edycję przed wskazaniem ramki.');return False
    formal=kind in ('fp','fn')
    data=image_feedback(ed) if formal else operator_view(ed);items=data.get(kind,[])
    if not items:return False
    key=(id(ed.h.session.review),ed.h.current_invocation,kind)
    old=getattr(ed,'_metric_counter_cursor',None);index=(old[1]+1)%len(items) if old and old[0]==key else 0
    item=items[index]
    ed.inf_visible.set(True);ed.ref_visible.set(True);ed.show_fp_var.set(True);ed.gt_focus_id=''
    source_kind=kind in ('fp','rejected')
    if source_kind:chosen=nav.select_layer(ed,'BBOX',item['oid'])
    else:
        from . import mobile_canvas_plate_cycle as cycle
        target=next((t for t in cycle.targets(ed) if t['kind']=='GTR' and t['pid']==item['gt_id']),None)
        chosen=bool(target and cycle.select(ed,target))
    if not chosen:return False
    row=next((r for r in clean.records(ed) if r['oid']==item['oid'] and (source_kind or r['pid']==item['gt_id'])),None)
    q=None
    if source_kind:
        from .mobile_canvas_geometry_layers import model
        q=nav.quad(model(ed),'BBOX')
    elif row:q=row['gt']
    if q:
        points=list(q)+(list(row['gt']) if source_kind and row and row['gt'] else [])
        sw,sh=ed._read()['image_size'];sx,sy=ed.h._image.width/sw,ed.h._image.height/sh
        xs=[p[0]*sx for p in points];ys=[p[1]*sy for p in points]
        width,height=ed.c.winfo_width(),ed.c.winfo_height()
        scale=min(width*.65/max(1,max(xs)-min(xs)),height*.45/max(1,max(ys)-min(ys)))
        ed.h._view_zoom=max(1,min(256,scale/max(.0001,ed.h._view_fit_scale)))
        ed.h._view_center=((min(xs)+max(xs))/2,(min(ys)+max(ys))/2)
        ed.h._paint_image()
    ed._metric_counter_cursor=(key,index)
    descriptions=dict(fp='FP w ocenie BBOX: źródłowy prostokąt bez dopasowania',fn='FN w ocenie BBOX: referencja bez dopasowanego prostokąta',
                      rejected='Wskazanie odrzucone przez operatora (PPM)',unlinked='Zapisana GT bez jawnego powiązania ze wskazaniem MT')
    ed.message(item['label']+' · '+descriptions[kind])
    return True

def history_state(ed):
    from ..ranking import mobile_candidate_stacks as stacks,mobile_canvas_review as core
    history=ed.h.session.invocation_annotation(ed.h.current_invocation).get(core.KEY,{}).get(stacks.HISTORY,{}) if ed.h.session and ed.h.current_invocation else {}
    head=history.get('head');entries=history.get('entries',[])
    can_undo=isinstance(head,int) and 0<=head<len(entries)
    action=entries[head].get('action') if can_undo else None
    can_redo=bool(history.get('redo'))
    if not history:
        can_undo=bool(ed.undo_stack.get(ed.h.current_invocation));can_redo=bool(ed.redo_stack.get(ed.h.current_invocation))
    return can_undo,can_redo,action

def sync_actions(ed):
    if not hasattr(ed,'clean_history_bar'):return
    undo,redo,action=history_state(ed);enabled=ed.available() and not ed.busy and not ed.h._saving and ed.mode!='draw' and not ed.drag
    if undo or redo:
        ed.clean_history_bar.pack(fill='x',pady=(4,0))
        ed.clean_undo_button.configure(text='Cofnij zatwierdzenie · Ctrl+Z' if action in ('operator_confirm_associated_frames','operator_confirm_gtr_geometry') else 'Cofnij zmianę · Ctrl+Z',state='normal' if enabled and undo else 'disabled')
        if redo:ed.clean_redo_button.pack(side='right',padx=(4,0));ed.clean_redo_button.configure(state='normal' if enabled else 'disabled')
        else:ed.clean_redo_button.pack_forget()
    else:ed.clean_history_bar.pack_forget()
    measured=image_feedback(ed);operational=operator_view(ed)
    for kind in ('rejected','unlinked'):
        cursor='hand2' if operational[kind] and enabled else ''
        for widget in (ed.contexts.counters[kind],ed.contexts.counter_labels[kind],ed.contexts.counters[kind].master):widget.configure(cursor=cursor)
    for kind in ('fp','fn'):
        ed.contexts.bbox_counters[kind].configure(state='normal' if measured[kind] and enabled else 'disabled')

def install(ed,options):
    ed.clean_history_bar=tk.Frame(ed.contexts.sections['object'],bg=ed.p['bg'])
    ed.clean_undo_button=tk.Button(ed.clean_history_bar,command=ed.undo,**options);ed.clean_undo_button.pack(side='left',fill='x',expand=True)
    ed.clean_redo_button=tk.Button(ed.clean_history_bar,text='Ponów',command=lambda:ed.undo(redo=True),**options)
    for kind in ('rejected','unlinked'):
        for widget in (ed.contexts.counters[kind],ed.contexts.counter_labels[kind],ed.contexts.counters[kind].master):
            widget.bind('<Button-1>',lambda event,kind=kind:inspect(ed,kind))
    for kind in ('fp','fn'):ed.contexts.bbox_counters[kind].configure(command=lambda kind=kind:inspect(ed,kind))
