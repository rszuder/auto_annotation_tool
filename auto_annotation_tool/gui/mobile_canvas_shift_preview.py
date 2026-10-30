"""Hold Shift over this Canvas: noninteractive source/reference contours."""
import tkinter as tk


class ShiftPreview:
    def __init__(self,editor):
        self.ed=editor;self.held=set();self.bindings=[]
        for key in ('Shift_L','Shift_R'):
            self.bind(editor.c,'<KeyPress-'+key+'>',self.press)
            self.bind(editor.c,'<KeyRelease-'+key+'>',self.release)
            self.bind(editor.h.window,'<KeyRelease-'+key+'>',self.release)
        self.bind(editor.c,'<FocusOut>',self.focus_out)
        self.bind(editor.h.window,'<FocusOut>',self.focus_out)
        self.notebook=None;parent=editor.c.master
        while parent is not None and parent is not editor.h.window:
            if parent.winfo_class()=='TNotebook':
                self.notebook=parent;self.bind(parent,'<<NotebookTabChanged>>',self.focus_out);break
            parent=parent.master

    def bind(self,widget,event,callback):
        self.bindings.append((widget,event,widget.bind(event,callback,add='+')))

    @property
    def active(self):
        return bool(self.held and self.ed.mode!='draw' and not self.ed.drag)

    def press(self,event):
        if self.ed._is_typing_shortcut(event.widget):return
        before=self.active;self.held.add(event.keysym)
        if self.active!=before:self.ed.request_overlay()

    def release(self,event):
        before=self.active;self.held.discard(event.keysym)
        if self.active!=before:self.ed.request_overlay()

    def clear(self):
        before=self.active;self.held.clear()
        if before:self.ed.request_overlay()

    def focus_out(self,event=None):self.clear()

    def dispose(self):
        self.clear()
        for widget,event,token in self.bindings:
            try:widget.unbind(event,token)
            except tk.TclError:pass
        self.bindings=[]

    def frames(self):
        """All proven geometry on this exact source image, independent of focus."""
        ed=self.ed;s=ed._read();session=ed.h.session;gid=ed.h.current_invocation
        if not s:return []
        key=(id(session),session.review.review_revision,gid,s['source_binding'])
        if getattr(self,'_frames_key',None)==key:return self._frames
        from ..ranking import mobile_canvas_review as core,mobile_candidate_stacks as stacks
        from ..ranking.mobile_canvas_operator_view import saved_reference_ids
        from ..ranking.mobile_mt_geometry_layers import source_bbox
        from .mobile_canvas_approval_visuals import RED,POSE,BBOX
        from ..ranking.mobile_canvas_source_hud import _context,_identity
        gids=[gid]
        try:identity=_identity(session.mt_invocations[gid],_context(session,gid))
        except (ValueError,KeyError,TypeError,OSError):identity=None
        if identity is not None:
            for other,group in session.mt_invocations.items():
                if other==gid:continue
                try:same=_identity(group,_context(session,other))==identity
                except (ValueError,KeyError,TypeError,OSError):continue
                if same:gids.append(other)
        frames=[]
        for other in gids:
            try:
                scene=s if other==gid else core.scene(session,other)
                state=stacks.snapshot(session,other,scene)
            except (ValueError,KeyError,TypeError,OSError):continue
            for c in state['candidates']:
                color=RED if c['association_status']=='UNASSOCIATED_NO_PLATE' else POSE if c['role']=='FINAL' else '#AEB8C2'
                bbox=source_bbox(session,scene,c)
                if bbox:
                    l,t,r,b=bbox;frames.append(dict(kind='BBOX',quad=[(l,t),(r,t),(r,b),(l,b)],color=RED if c['association_status']=='UNASSOCIATED_NO_PLATE' else BBOX if c['role']=='FINAL' else color,oid=c['object_id'],gid=other))
                if c['mt_quad']:
                    try:core.validate_mt_quad(c['mt_quad'],*scene['image_size'])
                    except (ValueError,TypeError):continue
                    frames.append(dict(kind='POSE',quad=c['mt_quad'],color=color,oid=c['object_id'],gid=other))
            saved=saved_reference_ids(scene,state)
            from .mobile_canvas_approval_visuals import approved_ids,GREEN,PENDING
            approved=approved_ids(scene,state)
            for pid,p in state['plates'].items():
                if pid in saved:frames.append(dict(kind='GTR',quad=p['gt_quad'],color=GREEN if pid in approved else PENDING,oid=pid,gid=other))
        self._frames_key=key;self._frames=frames
        return frames

    def paint(self):
        if not self.active:return
        from . import mobile_canvas_clean_view as clean
        from .mobile_canvas_editor import TAG
        from .mobile_canvas_approval_visuals import polygon
        ed=self.ed
        for frame in sorted(self.frames(),key=lambda frame:frame['kind']=='GTR'):
            q=frame['quad'];kind=frame['kind'];tags=(TAG,'shift_source_preview',frame['gid'],frame['oid'])
            tag={'BBOX':'shift_mt_source_bbox','POSE':'shift_mt_pose','GTR':'shift_saved_gtr'}[kind]
            polygon(ed,[v for p in q for v in ed.to_canvas(p)],color=frame['color'],width=2 if kind=='GTR' else 1.5,
                    dash=(4,3) if kind=='BBOX' else (),tags=tags+(tag,),underlay='shift_contrast_underlay')
            ed.clean_geometry_boxes.append(clean.bounds(ed,q))
