"""Resolve explicit drawing targets; occupied source areas focus existing GT."""
import copy
from . import mobile_canvas_clean_view as clean

def resolve(editor):
    if not editor.selected:return None
    row=clean.selected(editor)
    if not row:raise ValueError('Nie ustalono wybranej referencji. Anuluj zaznaczenie i wybierz obiekt ponownie.')
    if row['conflict']:raise ValueError('Konflikt referencji GT — zachowano zapisane dane.')
    if row['fp'] or row['role'] not in ('GT','FINAL'):return None
    s=editor._read();v=clean.source(editor);p=row['plate'];c=row['candidate']
    from ..ranking.mobile_manual_frame_guard import reservation_records
    references=reservation_records(s,session=editor.h.session,gid=editor.h.current_invocation)
    saved={r['plate_id'] for r in references}
    if p and p['gt_quad']:
        reference=next((r for r in references if r['plate_id']==row['pid']),None)
        if reference:return dict(kind='focus',reference=reference)
        raise ValueError('Nie potwierdzono aktywnej GTR. Wybierz istniejącą referencję ponownie; nie rozpoczęto nowej ramki.')
    if c and row['pid'] not in saved:
        from .mobile_canvas_reservation import for_source
        reserved=for_source(editor,c['object_id'])
        if reserved:return dict(kind='focus',reference=reserved)
    if c and not p:
        location=clean.source_location(editor,row)
        if not location:raise ValueError('Brak wiarygodnej lokalizacji wybranego MT.')
        return dict(kind='create',gid=editor.h.current_invocation,plate_id=None,oid=c['object_id'],number=None,
                    revision=editor.h.session.review.review_revision,binding=copy.deepcopy(s['source_binding']))
    location=clean.source_location(editor,row) if c else None
    if c and not location:raise ValueError('Brak wiarygodnej lokalizacji wybranego MT.')
    if not p:return None
    target=dict(kind='complete',gid=editor.h.current_invocation,
        plate_id=row['pid'],oid=row['reference_id'],number=row['n'],quad=copy.deepcopy(p['gt_quad']),
        revision=editor.h.session.review.review_revision,binding=copy.deepcopy(s['source_binding']))
    if target['kind']=='complete':
        if not c or c['role']!='FINAL' or not location or location['kind']!='BBOX':
            raise ValueError('Nie ustalono jednoznacznej referencji do uzupełnienia.')
        target['oid']=c['object_id']
    if target['plate_id'] not in v['active_plate_ids']:raise ValueError('Wybrana GTR nie jest aktywna.')
    return target
