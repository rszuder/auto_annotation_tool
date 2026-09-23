"""Slide the existing PZ2 panels without rebuilding controls or the preview."""
from time import perf_counter
import tkinter as tk


class WorkspaceDrawers:
    duration = .18

    def __init__(self, owner, *, clock=perf_counter):
        self.owner = owner
        self.host = owner.detect_content_frame
        self.clock = clock
        self.detached = False
        self.destroyed = False
        self.mode_transition = False
        self.panels = {"left": owner.preview_list_lf, "right": owner.detect_right_panel,
                       "bottom": owner.detect_footer_nav}
        self.parents = {"left": owner.preview_vertical_split, "right": owner.detect_split,
                        "bottom": self.host}
        self.visible = dict.fromkeys(self.panels, 1.0)
        self.target = dict(self.visible)
        self.buttons = {}
        self._job = self._restore_job = self._complete = None
        for side, parent in self.parents.items():
            self.buttons[side] = tk.Button(
                parent, command=lambda key=side: self.toggle(key), takefocus=False,
                bd=0, padx=7, pady=4, cursor="hand2", bg="#233342", fg="#b8edff",
                activebackground="#344e64", activeforeground="#ffffff",
                font=("Segoe UI", 9, "bold"),
            )
            parent.bind("<Configure>", self._configure, add="+")
        self.host.bind("<Destroy>", self._destroy, add="+")

    def enter(self):
        self._cancel()
        if not self.detached:
            self.saved = {}
            for side, panel in self.panels.items():
                parent = self.parents[side]
                if side == "bottom":
                    allowed = panel.winfo_manager() == "grid"
                    options = panel.grid_info() if allowed else {}
                    extent = panel.winfo_height()
                else:
                    allowed = str(panel) in tuple(map(str, parent.panes()))
                    options = {key: value[-1] for key, value in parent.paneconfigure(panel).items()
                               if key not in {"after", "before"}} if allowed else {}
                    extent = panel.winfo_width()
                self.saved[side] = {"allowed": allowed, "options": options, "extent": max(1, extent)}
                self.visible[side] = self.target[side] = float(allowed)
                if allowed:
                    if side == "bottom":
                        panel.grid_remove()
                    else:
                        self.saved[side]["sash"] = parent.sash_coord(0)[0]
                        self.saved[side]["inset"] = parent.winfo_width() - parent.sash_coord(0)[0]
                        parent.forget(panel)
            self.detached = True
        self._paint()

    def animate_mode(self, fullscreen, complete):
        self._cancel()
        self.mode_transition = True
        self._complete = complete
        self.target = {side: float(not fullscreen and self.saved[side]["allowed"])
                       for side in self.panels}
        self._start_animation()

    def toggle(self, side):
        if not self.detached or self.mode_transition:
            return
        if not self.saved[side]["allowed"]:
            return
        self._cancel()
        self._complete = None
        self.target[side] = 0.0 if self.target[side] else 1.0
        self._start_animation()
        self.owner._focus_preview_canvas()

    def _start_animation(self):
        self._start = dict(self.visible)
        self._started = self.clock()
        self._tick()

    def _configure(self, event):
        if event.widget in self.parents.values() and self.detached:
            self._paint()

    def _paint(self):
        if self.destroyed or not self.detached:
            return
        for side, panel in self.panels.items():
            saved = self.saved[side]
            if not saved["allowed"]:
                self.buttons[side].place_forget()
                continue
            parent = self.parents[side]
            width, height = parent.winfo_width(), parent.winfo_height()
            fraction = self.visible[side]
            button = self.buttons[side]
            if side == "bottom":
                extent = min(max(saved["extent"], panel.winfo_reqheight()), max(40, height - 100))
                y = round(height - extent * fraction)
                panel.place(x=0, y=y, width=width, height=extent)
                button.configure(text="▼ Ukryj akcje" if self.target[side] else "▲ Akcje")
                button.place(relx=.5, y=min(height - 2, y - 2), anchor="s")
            else:
                extent = min(saved["extent"], max(180, width - 80))
                x = round(-extent * (1 - fraction)) if side == "left" else round(width - extent * fraction)
                panel.place(x=x, y=0, width=extent, height=height)
                if side == "left":
                    button.configure(text="‹ Tablice" if self.target[side] else "Tablice ›")
                    button.place(x=max(0, x + extent), rely=.52, anchor="w")
                else:
                    button.configure(text="Ustawienia ›" if self.target[side] else "‹ Ustawienia")
                    button.place(x=min(width, x), rely=.52, anchor="e")
            panel.lift()
            button.lift()
            if not getattr(self.owner, "_preview_fullscreen_active", False):
                button.place_forget()

    def _tick(self):
        self._job = None
        if self.destroyed:
            return
        t = min(1.0, max(0.0, (self.clock() - self._started) / self.duration))
        eased = t * t * (3 - 2 * t)
        self.visible = {side: self._start[side] + (target - self._start[side]) * eased
                        for side, target in self.target.items()}
        self._paint()
        if t < 1:
            self._job = self.host.after(16, self._tick)
        elif not getattr(self.owner, "_preview_fullscreen_active", False):
            self.attach()
        else:
            self._finish()

    def _finish(self):
        self.mode_transition = False
        complete, self._complete = self._complete, None
        if complete is not None:
            complete()

    def attach(self):
        self._cancel()
        if not self.detached:
            return
        for side, panel in self.panels.items():
            panel.place_forget()
            self.buttons[side].place_forget()
            saved = self.saved[side]
            if not saved["allowed"]:
                continue
            if side == "bottom":
                panel.grid(**saved["options"])
            else:
                options = dict(saved["options"], width=saved["extent"])
                if side == "left":
                    options["before"] = self.owner.preview_lf
                self.parents[side].add(panel, **options)
        self.detached = False

        def restore():
            self._restore_job = None
            if self.destroyed or self.detached:
                return
            for side in ("right", "left"):
                saved, parent = self.saved[side], self.parents[side]
                if saved["allowed"]:
                    x = parent.winfo_width() - saved["inset"] if side == "right" else saved["sash"]
                    parent.sash_place(0, max(0, x), 1)
            self._finish()

        def allocated():
            self._restore_job = self.host.after_idle(restore)
        self._restore_job = self.host.after_idle(allocated)

    def _cancel(self):
        for name in ("_job", "_restore_job"):
            job = getattr(self, name)
            if job is not None:
                self.host.after_cancel(job)
                setattr(self, name, None)

    def _destroy(self, event):
        if event.widget is self.host:
            self._cancel()
            self._complete = None
            self.destroyed = True


def workspace_drawers(owner):
    controller = getattr(owner, "_preview_workspace_drawers", None)
    if controller is None:
        controller = owner._preview_workspace_drawers = WorkspaceDrawers(owner)
    return controller
