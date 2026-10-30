"""Source-bound, reversible per-frame operator decisions, separate from OCR GT.

Reading never writes or migrates a legacy review. Only explicit Canvas actions
enable this contract. A model prediction alone is never a positive decision.
"""
from __future__ import annotations

import copy

KEY = 'operator_frame_decisions_v1'
SCHEMA = 'alpr.mobile.operator_frame_decisions.v1'
PLATE, NOT_PLATE, UNRESOLVED = 'PLATE', 'NOT_PLATE', 'UNRESOLVED'
VALUES = {PLATE, NOT_PLATE, UNRESOLVED}


def _objects(scene):
    rows = (scene.get('_stack_legacy') or {}).get('objects', [])
    return {o['object_id']: o for o in [*rows, *scene['objects']]}


def _initial(scene, state, roles):
    objects = _objects(scene)
    decisions = {}
    for oid, role in roles.items():
        if role != 'FINAL':
            continue
        link = state['links'].get(oid, {})
        accepted = (scene['checked'] or link.get('identity_decision') or
                    link.get('provenance') in {'operator_accept_unchanged_final_reference',
                                              'operator_canvas_association'})
        decisions[oid] = (NOT_PLATE if link.get('status') == 'UNASSOCIATED_NO_PLATE' else
                          PLATE if accepted and link.get('plate_id') else UNRESOLVED)
    return dict(schema=SCHEMA, source_binding=scene['source_binding'], source_roles=roles,
                decisions=decisions, previous_decisions={},
                empty_confirmed=bool(scene['checked'] and scene.get('roi_presence') == 'NO_PLATES'))


def enable(session, gid, scene, state=None):
    from . import mobile_candidate_stacks as stacks
    if KEY not in scene:
        state = state if state is not None else scene.get(stacks.KEY) or stacks._legacy(scene)
        by_attempt = stacks.roles(session, gid, scene)
        roles = {o['object_id']: by_attempt[o['attempt_id']] for o in _objects(scene).values()
                 if o.get('parent_id')}
        scene[KEY] = _initial(scene, state, roles)
    return scene[KEY]


def sync_gtr_review(session,gid,scene,old,action,oid):
    """A changed physical GT needs explicit approval; presence stays separate."""
    from . import mobile_candidate_stacks as stacks
    from .mobile_canvas_operator_view import saved_reference_ids
    state=scene.get(stacks.KEY) or stacks._legacy(scene)
    previous=old.get(stacks.KEY) or stacks._legacy(old)
    saved=saved_reference_ids(scene,state)
    def quad(value):return tuple(tuple(float(v) for v in p) for p in value) if value else None
    changed={pid for pid in saved if quad(state['plates'][pid]['gt_quad'])!=quad(previous['plates'].get(pid,{}).get('gt_quad'))}
    # Supplying GTZ may establish a reference with untouched source corners;
    # that text-only action has not drawn or modified any geometry.
    objects=_objects(old)
    for pid in list(changed):
        plate=state['plates'][pid];obj=objects.get(plate['origin_object_id'],{})
        if (pid not in previous['plates'] and plate['geometry_state']=='unconfirmed'
                and obj.get('parent_id') and quad(plate['gt_quad'])==quad(obj.get('quad'))):
            changed.discard(pid)
    pending=set((old.get(KEY) or {}).get('pending_gtr_ids',())) | set((scene.get(KEY) or {}).get('pending_gtr_ids',()))
    # A first explicit Space/acceptance of unchanged MT is already approval.
    if action in {'operator_toggle_frame_presence','operator_accept_shared_gt_reference'}:
        pid=state['links'].get(oid,{}).get('plate_id')
        if pid not in previous['plates']:changed.discard(pid)
    pending=(pending|changed)&saved
    if action in {'operator_confirm_gtr_geometry','operator_confirm_associated_frames'}:pending.discard(oid)
    if not pending and KEY not in scene:return
    if KEY not in scene:
        seed=copy.deepcopy(scene);seed['checked']=old['checked']
        scene[KEY]=enable(session,gid,seed,state)
    if pending or 'pending_gtr_ids' in scene[KEY] or changed:
        scene[KEY]['pending_gtr_ids']=sorted(pending)


def confirm_gtr(session,gid,plate_id):
    """Approve the current stored geometry of one explicit physical GTR."""
    from . import mobile_canvas_review as core,mobile_candidate_stacks as stacks
    from .mobile_canvas_operator_view import saved_reference_ids
    scene=core._legacy_scene(session,gid,include_history=False);state=stacks._state(scene)
    if plate_id not in saved_reference_ids(scene,state):raise ValueError('Wybierz istniejącą GTR do zatwierdzenia.')
    data=scene.get(KEY)
    if not data or plate_id not in data.get('pending_gtr_ids',[]):return False
    data['pending_gtr_ids']=[pid for pid in data['pending_gtr_ids'] if pid!=plate_id]
    stacks._write(session,gid,scene,state,'operator_confirm_gtr_geometry',plate_id)
    return True


def validate(session, gid, scene):
    if KEY not in scene:
        return
    from . import mobile_candidate_stacks as stacks
    data = scene[KEY]
    roles = stacks.roles(session, gid, scene)
    expected = {o['object_id']: roles[o['attempt_id']] for o in _objects(scene).values()
                if o.get('parent_id')}
    if (not isinstance(data, dict) or data.get('schema') != SCHEMA
            or data.get('source_binding') != scene['source_binding']
            or data.get('source_roles') != expected or type(data.get('empty_confirmed')) is not bool):
        raise ValueError('Decyzje ramek nie odpowiadają źródłowemu obrazowi i wynikom MT.')
    final = {oid for oid, role in expected.items() if role == 'FINAL'}
    decisions = data.get('decisions')
    previous = data.get('previous_decisions')
    if (not isinstance(decisions, dict) or set(decisions) != final
            or any(value not in VALUES for value in decisions.values())
            or not isinstance(previous, dict) or not set(previous).issubset(final)
            or any(value not in VALUES for value in previous.values())):
        raise ValueError('Nieprawidłowe częściowe decyzje operatora.')
    state = scene.get(stacks.KEY) or stacks._legacy(scene)
    from .mobile_canvas_operator_view import saved_reference_ids
    pending=data.get('pending_gtr_ids',[])
    if (not isinstance(pending,list) or any(not isinstance(pid,str) for pid in pending)
            or len(set(pending))!=len(pending) or not set(pending)<=saved_reference_ids(scene,state)):
        raise ValueError('Nieprawidłowe oczekujące zatwierdzenia GTR.')
    for oid, decision in decisions.items():
        link = state['links'].get(oid, {})
        if decision == PLATE and (link.get('status') != 'ASSOCIATED_FOR_GEOMETRY'
                                  or link.get('plate_id') not in state['plates']):
            raise ValueError('Poprawna ramka nie ma zapisanej tożsamości tablicy.')
        if decision == NOT_PLATE and link.get('status') != 'UNASSOCIATED_NO_PLATE':
            raise ValueError('Błędna ramka nie odpowiada zapisanej decyzji FP.')


def _state(scene):
    from . import mobile_candidate_stacks as stacks
    state = scene.get(stacks.KEY) or stacks._legacy(scene)
    if KEY in scene:
        return state, scene[KEY]
    roles = {o['object_id']: ('SUPPRESSED' if o.get('post_nms_suppressed') else
                             'UNKNOWN' if scene.get('_post_nms_unknown') or scene.get('_post_nms_pending')
                             else 'FINAL') for o in _objects(scene).values() if o.get('parent_id')}
    return state, _initial(scene, state, roles)


def manual_plate_ids(scene, state=None):
    if state is None:
        state, _ = _state(scene)
    objects = _objects(scene)
    return {pid for pid, plate in state['plates'].items()
            if plate['origin_object_id'] in objects
            and not objects[plate['origin_object_id']].get('parent_id')
            and not objects[plate['origin_object_id']]['error']
            and plate['origin_object_id'] not in state.get('removed_manual_ids', [])}


def active_plate_ids(scene, state=None):
    state = state if state is not None else _state(scene)[0]
    if KEY not in scene:
        return set(state['plates'])
    decisions = scene[KEY]['decisions']
    return manual_plate_ids(scene, state) | {
        link['plate_id'] for oid, link in state['links'].items()
        if link.get('plate_id') and decisions.get(oid) == PLATE}


def progress(scene):
    state, data = _state(scene)
    pending = [oid for oid, decision in data['decisions'].items() if decision == UNRESOLVED]
    unknown = [oid for oid, role in data['source_roles'].items() if role == 'UNKNOWN']
    from .mobile_canvas_review import manual_bad_objects
    blocked = bool(state.get('conflicts') or scene.get('_post_nms_unknown')
                   or scene.get('_post_nms_pending') or scene.get('migration_warnings') or manual_bad_objects(scene))
    manual = manual_plate_ids(scene, state)
    active = manual | {link['plate_id'] for oid, link in state['links'].items()
                       if link.get('plate_id') and data['decisions'].get(oid) == PLATE}
    empty = not data['decisions'] and not manual and not unknown and not blocked
    negative_pending = empty and not data['empty_confirmed']
    from .mobile_canvas_operator_view import saved_reference_ids
    missing_gtr={pid for pid,p in state['plates'].items() if p['geometry_state']=='operator_removed' and p['gt_quad'] is None}
    pending_gtr=sorted((set(data.get('pending_gtr_ids',())) & saved_reference_ids(scene,state))|missing_gtr)
    # One Space verifies a physical stack, even when both MT and GTR await it.
    # Explicit links establish identity; overlap/text never joins review units.
    units={('GTR',pid) for pid in pending_gtr}
    for oid in pending:
        link=state['links'].get(oid,{})
        pid=link.get('plate_id') if link.get('status')=='ASSOCIATED_FOR_GEOMETRY' else None
        units.add(('GTR',pid) if pid in state['plates'] else ('MT',oid))
    decisions = len(units) + len(unknown) + int(blocked and not unknown) + int(negative_pending)
    complete = not decisions
    return dict(complete=complete, decisions=decisions, pending_ids=pending,pending_gtr_ids=pending_gtr,
                resolved=sum(d != UNRESOLVED for d in data['decisions'].values()),
                total=len(data['decisions']), correct=sum(d == PLATE for d in data['decisions'].values()),
                false_positive=sum(d == NOT_PLATE for d in data['decisions'].values()),
                manual_added=len(manual), plate_count=len(active), empty_eligible=empty,
                empty_confirmed=data['empty_confirmed'], source_unknown=bool(unknown or blocked),
                object_decisions=dict(data['decisions']))


def sync_write(session, gid, scene, action, oid):
    """Derived inspection flag is updated in the SAME durable/audited write."""
    if KEY not in scene:
        return
    from . import mobile_candidate_stacks as stacks
    data = scene[KEY]
    state = scene[stacks.KEY]
    if action == 'operator_candidate_no_plate' and oid in data['decisions']:
        link = state['links'][oid]
        if link['status'] == 'UNASSOCIATED_NO_PLATE':
            data['previous_decisions'][oid] = data['decisions'][oid]
            data['decisions'][oid] = NOT_PLATE
        else:
            data['decisions'][oid] = data['previous_decisions'].pop(oid, UNRESOLVED)
    elif action in {'operator_associate_candidate_shared_gt', 'operator_accept_shared_gt_reference',
                    'operator_link_manual_to_mt'} and oid in data['decisions']:
        data['decisions'][oid] = PLATE
    validate(session, gid, scene)
    # Each physical reference keeps its identity/text/history even when all its
    # MT candidates become unresolved/FP; only its active projection changes.
    for pid, plate in state['plates'].items():
        positives = [key for key, link in state['links'].items()
                     if link.get('plate_id') == pid and data['decisions'].get(key) == PLATE]
        if positives and plate.get('primary_object_id') not in positives:
            plate['primary_object_id'] = positives[0]
    if data['decisions'] or manual_plate_ids(scene, state):
        data['empty_confirmed'] = False
    current = progress(scene)
    if not scene.get('exclusion_reason'):
        scene['checked'] = current['complete']
        if current['complete'] and not current['plate_count']:
            from . import mobile_canvas_review as core
            scene.update(roi_presence='NO_PLATES', decision_contract=core.DECISION_CONTRACT)
        else:
            scene.pop('roi_presence', None)


def _accept_positive(session,gid,scene,state,data,oid):
    from . import mobile_canvas_review as core, mobile_candidate_stacks as stacks
    from .mobile_canvas_resolution import identity_evidence, model_location
    if data['source_roles'].get(oid)!='FINAL':raise ValueError('Wybierz końcowe wskazanie MT.')
    obj=core._object(scene,oid);link=state['links'].get(oid,{})
    if link.get('status')=='UNASSOCIATED_NO_PLATE':link=copy.deepcopy(link.get('previous_link') or {})
    pid=link.get('plate_id')
    if not pid:
        if obj.get('quad'):
            from .mobile_manual_frame_guard import require_free_manual_area
            require_free_manual_area(scene,obj['quad'],session=session,gid=gid)
        pid=stacks._id(scene,oid)
        state['plates'].setdefault(pid,stacks._plate(scene,obj,pid))
    if pid not in state['plates']:raise ValueError('Brak wskazanej GTR; wybierz aktualną ramkę.')
    state['plates'][pid]['confirmed']=True
    accepted=(copy.deepcopy(link) if link.get('status')=='ASSOCIATED_FOR_GEOMETRY' and link.get('plate_id')==pid else
              dict(plate_id=pid,status='ASSOCIATED_FOR_GEOMETRY',provenance='operator_partial_frame_presence'))
    parent=next(p for p in scene['parents'] if p['parent_id']==obj['parent_id'])
    if not parent['quad']:
        accepted.update(identity_decision=identity_evidence(session,gid,scene,obj),identity_location=model_location(session,gid,scene,obj))
    state['links'][oid]=accepted;data['decisions'][oid]=PLATE;data['previous_decisions'].pop(oid,None)
    return pid


def confirm_stack(session,gid,*,oid=None,plate_id=None):
    """One explicit positive decision for this physical GT and its FINALs."""
    from . import mobile_canvas_review as core,mobile_candidate_stacks as stacks
    from .mobile_canvas_operator_view import physical_plate_ids
    if oid and plate_id:raise ValueError('Wybierz jedno wskazanie MT albo jedną GTR.')
    scene=core._legacy_scene(session,gid,include_history=False);state=stacks._state(scene);data=enable(session,gid,scene,state)
    before=copy.deepcopy((state,data))
    if plate_id is None:
        if not oid:raise ValueError('Wybierz ramkę tablicy do zatwierdzenia.')
        plate_id=_accept_positive(session,gid,scene,state,data,oid)
    if plate_id not in physical_plate_ids(scene,state):raise ValueError('Brak wskazanej GTR; wybierz aktualną ramkę.')
    for key,link in list(state['links'].items()):
        if (link.get('plate_id')==plate_id and link.get('status')=='ASSOCIATED_FOR_GEOMETRY'
                and data['source_roles'].get(key)=='FINAL'):
            _accept_positive(session,gid,scene,state,data,key)
    plate=state['plates'][plate_id]
    if plate['geometry_state']=='operator_removed' and plate['gt_quad'] is None:
        raise ValueError('Obrys operatora został usunięty. Narysuj go przez D albo przywróć Ctrl+Z; MT nie zastępuje GTR.')
    plate['confirmed']=True
    if plate['gt_quad'] and plate['geometry_state']=='unconfirmed':plate['geometry_state']='operator_confirmed_unchanged'
    if plate_id in data.get('pending_gtr_ids',[]):
        data['pending_gtr_ids']=[pid for pid in data['pending_gtr_ids'] if pid!=plate_id]
    if (state,data)==before:return False
    stacks._write(session,gid,scene,state,'operator_confirm_associated_frames',plate_id)
    return True


def stack_is_verified(scene,*,oid=None,plate_id=None):
    """Read-only state of one explicit physical reference and its FINALs."""
    from .mobile_canvas_operator_view import physical_plate_ids
    state,data=_state(scene)
    if oid and plate_id:return False
    if oid:
        if data['source_roles'].get(oid)!='FINAL':return False
        link=state['links'].get(oid,{})
        if link.get('status')!='ASSOCIATED_FOR_GEOMETRY':return False
        plate_id=link.get('plate_id')
    if plate_id not in physical_plate_ids(scene,state):return False
    plate=state['plates'][plate_id]
    members=[key for key,link in state['links'].items() if link.get('plate_id')==plate_id
             and link.get('status')=='ASSOCIATED_FOR_GEOMETRY' and data['source_roles'].get(key)=='FINAL']
    return bool(plate['confirmed'] and plate['geometry_state']!='operator_removed' and (plate['gt_quad'] or members)
                and plate_id not in data.get('pending_gtr_ids',[])
                and all(data['decisions'].get(key)==PLATE for key in members))


def toggle_stack(session,gid,*,oid=None,plate_id=None):
    """Toggle approval in one audited write, retaining all reference content."""
    from . import mobile_canvas_review as core,mobile_candidate_stacks as stacks
    from .mobile_canvas_operator_view import saved_reference_ids
    if oid and plate_id:raise ValueError('Wybierz jedno wskazanie MT albo jedną GTR.')
    scene=core._legacy_scene(session,gid,include_history=False)
    if not stack_is_verified(scene,oid=oid,plate_id=plate_id):
        return confirm_stack(session,gid,oid=oid,plate_id=plate_id)
    state=stacks._state(scene);data=enable(session,gid,scene,state)
    if plate_id is None:plate_id=state['links'][oid]['plate_id']
    for key,link in state['links'].items():
        if (link.get('plate_id')==plate_id and link.get('status')=='ASSOCIATED_FOR_GEOMETRY'
                and data['source_roles'].get(key)=='FINAL'):
            data['decisions'][key]=UNRESOLVED
    if plate_id in saved_reference_ids(scene,state):
        data['pending_gtr_ids']=sorted(set(data.get('pending_gtr_ids',[]))|{plate_id})
    # This is not Undo: keep the current geometry, text, identity and links.
    stacks._write(session,gid,scene,state,'operator_unconfirm_associated_frames',plate_id)
    return True


def toggle_plate(session, gid, oid):
    from . import mobile_canvas_review as core, mobile_candidate_stacks as stacks
    scene = core._legacy_scene(session, gid, include_history=False)
    state = stacks._state(scene)
    data = enable(session, gid, scene, state)
    if data['source_roles'].get(oid) != 'FINAL':
        raise ValueError('Wybierz końcową ramkę MT. Ramka dodana ręcznie jest już poprawna.')
    if data['decisions'][oid] == PLATE:
        data['decisions'][oid] = UNRESOLVED
    else:
        _accept_positive(session,gid,scene,state,data,oid)
    stacks._write(session, gid, scene, state, 'operator_toggle_frame_presence', oid)


def confirm_empty(session, gid):
    from . import mobile_canvas_review as core, mobile_candidate_stacks as stacks
    scene = core._legacy_scene(session, gid, include_history=False)
    state = stacks._state(scene)
    data = enable(session, gid, scene, state)
    scene[stacks.KEY] = state
    if not progress(scene)['empty_eligible']:
        raise ValueError('Najpierw rozlicz ramki na obrazie.')
    data['empty_confirmed'] = not data['empty_confirmed']
    stacks._write(session, gid, scene, state, 'operator_toggle_empty_frame', '')
