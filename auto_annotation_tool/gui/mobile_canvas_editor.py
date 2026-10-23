"""P2B2 canvas-first review controller; Z2-style drawing and inline GT.

The existing review window remains responsible for image loading, worker tasks,
zoom, session identity and exports. This controller owns interaction on the
verified source Bitmap only. Geometry persists in source pixels, never in Tk.
"""
from __future__ import annotations

import copy
import math
import sys
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

from ..ranking import mobile_canvas_review as core
from ..ranking.mobile_source_frame_roi import quad_contains_point
from ..ranking.mobile_pose_metrics import validate_mt_quad
from ..ranking.mobile_canvas_presentation import build_inventory, subject_groups
from .mobile_canvas_ui import palette, label as ui_label, MetricCard, Disclosure
from .mobile_canvas_results_panel import CanvasResultsPanel

TAG = "p2b2_canvas_overlay"


def reconciliation_story(scene, tally):
    """Human-facing explanation; does not infer physical plate count from NMS.

    The trace describes the *phone's* post-filter output. Counting all physical
    plates in the ROI remains an independent operator task.
    """
    raw = int(tally.get("mt", 0))
    suppressed = int(tally.get("raw_suppressed", 0))
    # Pending historical scenes still store both objects as active: counts()
    # cannot report the post-filter total until the explicit migration.
    pending = bool(scene.get("_post_nms_pending"))
    final = raw - (1 if pending else suppressed)
    if pending:
        return {
            "title": "DLACZEGO PROGRAM PROSI O POPRAWIENIE OCENY?",
            "body": (
                f"1. TELEFON: na jednej klatce wskazał {raw} możliwe obszary "
                f"tablicy. Po usunięciu nakładających się wskazań "
                f"przekazał {final} wynik do rozpoznawania.\n\n"
                "2. WCZEŚNIEJSZA OCENA: powstała zanim uwzględniono ten "
                "końcowy wynik. Oba wskazania policzono jako dwie tablice. "
                "Stąd niezgodność w liczniku.\n\n"
                "3. PROPONOWANA ZMIANA: liczyć tylko wynik, którego użył "
                "telefon. Drugie wskazanie, jego GT i poprawki zostaną "
                "zachowane w historii — nie uznamy go za fałszywy alarm.\n\n"
                "4. TWOJE ZADANIE PO ZMIANIE: obejrzeć cały zaznaczony "
                "obszar i samodzielnie policzyć rzeczywiste tablice. "
                "Dodatkową tablicę, której telefon nie wykrył, dodaj "
                "klawiszem D. Sprawdź ramkę i numer GT; dopiero potem "
                "potwierdź sprawdzenie obrazu."
            ),
            "action": "Popraw wcześniejszą ocenę: 2 → 1 wynik",
            "state": "pending",
        }
    if suppressed:
        return {
            "title": "WYNIK TELEFONU UWZGLĘDNIONY — CO DALEJ?",
            "body": (
                f"Telefon zapisał {raw} wstępne wskazania, ale do "
                f"rozpoznawania przekazał {final}. "
                f"Pozostałe {suppressed} zachowano w historii i nie "
                "liczymy ich jako osobnych tablic ani fałszywych alarmów.\n\n"
                "TERAZ TWOJA DECYZJA: obejrzyj cały analizowany obszar. "
                "Czy wszystkie rzeczywiste tablice są oznaczone? "
                "Jeśli brakuje tablicy, dodaj ją (D). Sprawdź narożniki "
                "i numer GT. Dopiero potem zaznacz sprawdzenie obrazu. "
                "Sam filtr telefonu nie ustala liczby tablic w rzeczywistości."
            ),
            "action": None,
            "state": "resolved",
        }
    return None


def linked_measurement_rows(session, subject_ids, available_group_ids):
    """Return rows that merely repeat the *same executed MT invocation*.

    A subject becomes an informational child only when it has exactly one
    inspectable invocation, and that invocation already belongs to the first
    subject in the ordered observation register. Never group by text, GT,
    spatial proximity, detection count, or approximate timestamps.

    The return value maps existing Treeview subject iids to (owner_iid, gid).
    It does NOT alter subjects, invocation IDs, source images or review states.
    """
    subjects = list(subject_ids.items())
    inspected = {
        key: [gid for gid in subject_groups(session, key) if gid in available_group_ids]
        for _, key in subjects
    }
    linked = {}
    for iid, key in subjects:
        gids = inspected[key]
        if len(gids) != 1:
            continue  # Multiple regions or missing evidence require own row.
        gid = gids[0]
        group = session.mt_invocations.get(gid)
        if group is None or key not in group.subject_keys:
            continue  # Inconsistent links must remain visible for manual review.
        owner = next((owner_iid for owner_iid, owner_key in subjects
                      if owner_key in group.subject_keys and gid in inspected[owner_key]), None)
        if owner is not None and iid != owner:
            linked[iid] = (owner, gid)
    return linked


class CanvasReviewEditor:
    def __init__(self, host, right, review, viewer):
        self.h = host
        self.c = host.canvas
        self.selected = ""
        self.pointer_canvas = None
        self.selection_key_down = False
        self.selection_release_after = None
        self._s_hover_hit = None  # (group_id, object_id, canvas_xy) from real Motion
        self._win_s_poll_id = None
        self._win_s_down = False
        self._win_user32 = None
        self.fit_key_down = False
        self.fit_release_after = None
        self.shortcut_tag = None
        self.shortcut_original_tags = {}
        self.pointer_canvas_at = None
        self.tree_branch = ""
        self.mode = "select"
        self.points = []
        self.pointer = None
        self.drag = None
        self._click_candidate = None  # click selects; drag pans unless a corner is grabbed
        self.show_roi_overlay = True
        self.plate_fit_saved = None
        self.plate_fit_active = False
        self.plate_fit_gid = ""
        self.plate_fit_previous = None  # (zoom, center) before A; view-only
        self.hover = ""
        self.skey = ""
        self.cached = None
        self.cache_key = None
        self.badges = {}
        self.card_positions = {}
        self.entry = None
        self.entry_var = None
        self.entry_target = None
        self.entry_original = ""
        self.entry_after = None
        self.refresh_after = None
        self.paint_scheduled = False
        self.paint_after = None
        self.in_refresh = False
        self.busy = False
        self.undo_stack = {}
        self.redo_stack = {}
        # Keep old widgets alive for report readers, but remove their form UI.
        self.old_right = list(right.winfo_children())
        for widget in self.old_right:
            widget.grid_remove()
        # Give the inspector meaningful space without stealing the whole image.
        # Use the actual screen width, not the 238 px legacy Canvas override.
        screen_width = host.window.winfo_screenwidth()
        self.sidebar_width = (398 if screen_width >= 1500 else
                              358 if screen_width >= 1250 else 318)
        # The operator's left panel lists images only. Technical records,
        # candidate boxes and source IDs belong to the audit/report view.
        self.left_width = (364 if screen_width >= 1500 else
                           338 if screen_width >= 1250 else 310)
        review.columnconfigure(0, weight=0, minsize=self.left_width)
        review.columnconfigure(1, weight=1, minsize=430 if screen_width >= 1250 else 350)
        review.columnconfigure(2, weight=0, minsize=self.sidebar_width + 12)
        host.window.minsize(min(1150, max(900, screen_width - 60)), 670)
        host.review_sidebar_scroll.configure(width=self.sidebar_width)
        self.p = palette(host.window, host.bg)
        self.tree_targets = {}
        self.linked_tree_rows = {}  # hidden aliases, used only for navigation
        self.pending_tree_target = None
        self.inventory_key = None
        self.inventory_data = None
        self.tree_refreshing = False
        self._active_tree_iid = ""
        self._build_panel(right)
        self._configure_tree()
        # The former binding pass ran BEFORE this panel existed.
        host._bind_sidebar_wheel(self.panel)
        host.review_sidebar_scroll.configure(yscrollincrement=22)
        for widget in viewer.grid_slaves(row=5):
            widget.grid_remove()
        host.target_nav.grid_remove()
        host.image_help.configure(text="Turkusowa ramka: wynik telefonu • pomarańczowo-żółta: korekta operatora • czerwone ×: błędne wskazanie • półprzezroczysty obszar: miejsce analizy")
        self.bindings()

    def label(self, text, bold=False, small=False):
        return tk.Label(self.panel, text=text, anchor="w", justify="left",
            wraplength=self.sidebar_width - 44,
            bg=self.h.bg, fg=self.h.fg, font=("Segoe UI", 9 if small else 10, "bold" if bold else "normal"))

    @staticmethod
    def make_action_button(parent, text, command, *, primary=False, compact=False, **kwargs):
        """A real button, not a flat heading; works with native Windows Tk themes.

        Applies only to review actions. No global ttk/theme override and no
        bindings or data writes. Tk Button owns hover/pressed/disabled states.
        """
        window = parent.winfo_toplevel()
        p = palette(window, window.cget("bg"))
        base = p["blue"] if primary else p["surface"]

        def luminance(color):
            channels = (value / 65535.0 for value in window.winfo_rgb(color))
            linear = [value / 12.92 if value <= .04045 else
                      ((value + .055) / 1.055) ** 2.4 for value in channels]
            return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]

        def blend(color_a, color_b, amount):
            aa = window.winfo_rgb(color_a)
            bb = window.winfo_rgb(color_b)
            values = [round((1-amount)*a/257 + amount*b/257) for a,b in zip(aa,bb)]
            return "#{:02x}{:02x}{:02x}".format(*values)

        # WCAG contrast prefers white below this background luminance.
        foreground = ("#ffffff" if luminance(base) < .179 else "#111827") if primary else p["fg"]
        if primary:
            hover = blend(base, "#ffffff" if luminance(base) < .45 else "#000000", .16)
        else:
            hover = blend(base, p["blue"], .15)
        return tk.Button(parent, text=text, command=command,
            bg=base, fg=foreground, activebackground=hover,
            activeforeground=foreground, disabledforeground=p["muted"],
            font=("Segoe UI", 9 if compact else 10, "bold"),
            padx=8 if compact else 13, pady=4 if compact else 8,
            relief="raised", overrelief="ridge", bd=2,
            highlightthickness=1, highlightbackground=p["border"],
            highlightcolor=p["blue"], cursor="hand2", takefocus=True,
            justify="center", **kwargs)

    def bindings(self):
        self.c.bind("<ButtonPress-1>", self.press)
        self.c.bind("<B1-Motion>", self.motion)
        self.c.bind("<ButtonRelease-1>", self.release)
        self.c.bind("<ButtonPress-3>", self.right_press)
        self.c.bind("<B3-Motion>", self.pan_motion)
        self.c.bind("<ButtonRelease-3>", self.pan_release)
        self.c.unbind("<Control-ButtonPress-3>")
        self.c.bind("<Motion>", self.hover_motion)
        self.c.bind("<Double-Button-1>", lambda e:"break")
        for k in ("d","D"):
            self.c.bind("<KeyPress-"+k+">", self.draw_toggle)
        # Register shortcuts on the actual review canvas and its early bindtag.
        # Z2 also registers a guarded global fallback for focusable widgets.
        # Only our own window may react; editing text remains untouched.
        self.c.configure(takefocus=1)
        self.install_canvas_shortcuts()
        for k in ("n", "N"):
            self.c.bind("<KeyPress-" + k + ">", self.cycle_hotkey)
        for k in ("t", "T"):
            self.c.bind("<KeyPress-" + k + ">", self.roi_hotkey)
        for k in ("f","F"):
            self.c.bind("<KeyPress-"+k+">", lambda e:self.fit())
        for k in ("q","Q"):
            self.c.bind("<KeyPress-"+k+">", lambda e:self.navigate(-1))
        for k in ("e","E"):
            self.c.bind("<KeyPress-"+k+">", lambda e:self.navigate(1))
        self.c.bind("<space>", self.confirm)
        self.c.bind("<Control-s>", self.confirm)
        self.c.bind("<Control-S>", self.confirm)
        self.c.bind("<Control-z>", lambda e:self.undo())
        self.c.bind("<Control-Z>", lambda e:self.undo())
        self.c.bind("<Control-y>", lambda e:self.undo(redo=True))
        self.c.bind("<Control-Y>", lambda e:self.undo(redo=True))
        for k in ("r", "R"):
            self.c.bind("<KeyPress-" + k + ">", self.remove_hotkey)
        self.c.bind("<Shift-R>", self.remove_selected)
        self.c.bind("<Shift-r>", self.remove_selected)
        self.c.bind("<Leave>", self.leave_canvas)
        # Delete/Backspace stay safe; removal requires selection mode + R.
        self.c.bind("<Delete>", self.no_delete)
        self.c.bind("<BackSpace>", self.back_point)
        self.c.bind("<Escape>", self.escape)
        self.h.window.bind("<Escape>", self.escape)
        self.c.bind("<Enter>", self.focus_canvas)
        # Windows fallback: Tk sometimes fails to deliver S to the review widget
        # while the mouse is on canvas. Poll only the S key, only while THIS
        # window is foreground, and only while the cursor is on the image.
        self._start_windows_s_watch()

    def focus_canvas(self, event=None):
        if self.entry is None:
            self.c.focus_set()

    def _start_windows_s_watch(self):
        if sys.platform != "win32" or getattr(self, "_win_s_poll_id", None) is not None:
            return
        self._win_s_poll_id = self.c.after(35, self._windows_s_watch_tick)

    def _windows_s_state(self):
        """(review_window_is_foreground, S_is_down). Never inspect other keys.

        Tk's focus and OS foreground are separate on Windows. A physical-key
        fallback must not affect a different application or a GT text field.
        """
        if sys.platform != "win32":
            return False, False
        try:
            import ctypes
            from ctypes import wintypes
            api = getattr(self, "_win_user32", None)
            if api is None:
                api = ctypes.WinDLL("user32", use_last_error=True)
                api.GetForegroundWindow.restype = wintypes.HWND
                api.GetAncestor.argtypes = (wintypes.HWND, ctypes.c_uint)
                api.GetAncestor.restype = wintypes.HWND
                api.GetAsyncKeyState.argtypes = (ctypes.c_int,)
                api.GetAsyncKeyState.restype = ctypes.c_short
                self._win_user32 = api
            active = api.GetForegroundWindow()
            parent = int(self.h.window.winfo_id())
            # GA_ROOT=2 collapses Tk's native top-level wrapper on Windows.
            same = bool(active and parent and
                        api.GetAncestor(active, 2) == api.GetAncestor(parent, 2))
            return same, bool(api.GetAsyncKeyState(0x53) & 0x8000) if same else False
        except (AttributeError, OSError, TypeError, ValueError, tk.TclError):
            return False, False

    def _windows_s_watch_tick(self, *, schedule=True):
        """Use a physical press edge if no Tk S event arrived.

        We never react outside the active review window, in GT input fields,
        or with the mouse outside the canvas. Existing Tk bindings remain the
        primary path; `selection_key_down` prevents a duplicate toggle.
        """
        self._win_s_poll_id = None
        try:
            if getattr(self.h, "_closed", False):
                return
            active, down = self._windows_s_state()
            was_down = getattr(self, "_win_s_down", False)
            if active and down and not was_down:
                try:
                    focus = self.h.window.focus_get()
                except (AttributeError, tk.TclError):
                    focus = None
                if (not self._is_typing_shortcut(focus)
                        and self._canvas_hotkey_pointer(None) is not None):
                    self.selection_key_press(SimpleNamespace(widget=self.c, state=0))
            elif not down and was_down:
                self.reset_selection_key()
            self._win_s_down = bool(active and down)
        finally:
            if schedule and not getattr(self.h, "_closed", False):
                self._win_s_poll_id = self.c.after(35, self._windows_s_watch_tick)

    def install_canvas_shortcuts(self):
        """Use an early Tk bindtag: Treeview class bindings may stop key events.

        This tag is scoped to the review Toplevel, leaves GT text fields and
        other windows alone and prevents one keypress being handled twice.
        """
        if getattr(self, "shortcut_tag", None):
            self._tag_canvas_shortcut_widgets()
            return
        tag = "ALPRCanvasKey_" + str(id(self))
        self.shortcut_tag = tag
        self.shortcut_original_tags = {}
        for key in ("s", "S"):
            self.c.bind_class(tag, "<KeyPress-" + key + ">", self.selection_key_press)
            self.c.bind_class(tag, "<KeyRelease-" + key + ">", self.selection_key_release)
        for key in ("a", "A"):
            self.c.bind_class(tag, "<KeyPress-" + key + ">", self.fit_key_press)
            self.c.bind_class(tag, "<KeyRelease-" + key + ">", self.fit_key_release)
        for key, handler in (("r", self.remove_hotkey), ("R", self.remove_hotkey),
                             ("t", self.roi_hotkey), ("T", self.roi_hotkey),
                             ("n", self.cycle_hotkey), ("N", self.cycle_hotkey)):
            self.c.bind_class(tag, "<KeyPress-" + key + ">", handler)
        self._tag_canvas_shortcut_widgets()
        # A newly created focusable widget (e.g. a button in an expanded
        # panel) gets the same tag when it first receives focus.
        self.h.window.bind("<FocusIn>", self._tag_canvas_focus_widget, add="+")
        # Fallback borrowed from working Z2: events dispatched by a nested
        # ttk widget or a later-created focus owner still reach this window.
        # The first bindtag wins when available; it returns "break", so no
        # physical key press is handled twice.
        self._install_shortcut_fallback()

    def _event_in_review_window(self, event):
        try:
            return event.widget.winfo_toplevel() is self.h.window
        except (AttributeError, tk.TclError):
            return False

    def _install_shortcut_fallback(self):
        """Bind guarded S/A fallback through Tk `all`, as used by Z2.

        Preserve existing global handlers (Z2 and other modules); dispose()
        removes only our Tcl callback scripts, never the whole sequence.
        """
        self.shortcut_global_bindings = []
        for key in ("s", "S", "a", "A"):
            press = self.selection_key_press if key.lower() == "s" else self.fit_key_press
            release = self.selection_key_release if key.lower() == "s" else self.fit_key_release
            for phase, handler in (("KeyPress", press), ("KeyRelease", release)):
                sequence = "<" + phase + "-" + key + ">"
                command_id = self.c.bind_all(sequence, handler, add="+")
                self.shortcut_global_bindings.append((sequence, command_id))

    def _remove_shortcut_fallback(self):
        # Tkinter's unbind_all would erase unrelated Z2 bindings. Remove only
        # scripts installed by this editor, identified by their callback IDs.
        for sequence, command_id in getattr(self, "shortcut_global_bindings", ()):
            try:
                script = str(self.c.tk.call("bind", "all", sequence))
                lines = script.splitlines(keepends=True)
                cleaned = "".join(line for line in lines if command_id not in line)
                if cleaned != script:
                    self.c.tk.call("bind", "all", sequence, cleaned)
                # bind_all registers Tcl callbacks on Tk's ROOT widget.
                # Remove them from its destruction registry as well, otherwise
                # Tk.destroy() attempts to delete a command twice.
                owner = self.c._root()
                owner.deletecommand(command_id)
                callbacks = getattr(owner, "_tclCommands", None)
                if callbacks is not None and command_id in callbacks:
                    callbacks.remove(command_id)
            except (AttributeError, tk.TclError):
                pass
        self.shortcut_global_bindings = []

    def _tag_canvas_focus_widget(self, event=None):
        widget = getattr(event, "widget", None)
        if widget is not None:
            self._tag_canvas_widget(widget)

    def _tag_canvas_widget(self, widget):
        tag = getattr(self, "shortcut_tag", None)
        if not tag:
            return
        try:
            if widget.winfo_toplevel() is not self.h.window:
                return
            tags = widget.bindtags()
            if tag not in tags:
                self.shortcut_original_tags[widget] = tags
                widget.bindtags((tag,) + tags)
        except (AttributeError, tk.TclError):
            return

    def _tag_canvas_shortcut_widgets(self):
        todo = [self.h.window]
        seen = set()
        while todo:
            widget = todo.pop()
            if id(widget) in seen:
                continue
            seen.add(id(widget))
            self._tag_canvas_widget(widget)
            try:
                todo.extend(widget.winfo_children())
            except (AttributeError, tk.TclError):
                pass

    def _is_typing_shortcut(self, widget):
        """Never hijack S/A while typing an operator GT or a reason."""
        return isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox,
                                   ttk.Entry, ttk.Combobox, ttk.Spinbox))

    def fit_key_press(self, event):
        if getattr(event, "widget", None) is not self.c and not self._event_in_review_window(event):
            return None
        if self._is_typing_shortcut(getattr(event, "widget", None)):
            return None
        # A also works from the image list if a frame is already selected or
        # the current scene contains exactly one evaluable plate. S remains a
        # true hover-only selection shortcut.
        scene = self._read()
        target_exists = bool(self.selected or (scene and sum(
            bool(self._current_quad(obj)) for obj in scene["objects"]
            if not obj.get("post_nms_suppressed", False)) == 1))
        if self._canvas_hotkey_pointer(event) is None and not target_exists:
            return None
        token = getattr(self, "fit_release_after", None)
        if token:
            self.c.after_cancel(token)
            self.fit_release_after = None
        if getattr(self, "fit_key_down", False):
            return "break"
        self.fit_key_down = True
        return self.fit_plate_toggle(event)

    def fit_key_release(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self.c and not self._event_in_review_window(event):
            return None
        token = getattr(self, "fit_release_after", None)
        if token:
            self.c.after_cancel(token)
        self.fit_release_after = self.c.after_idle(self.reset_fit_key)
        return "break"

    def reset_fit_key(self, event=None):
        token = getattr(self, "fit_release_after", None)
        if token:
            try:
                self.c.after_cancel(token)
            except (AttributeError, tk.TclError):
                pass
        self.fit_release_after = None
        self.fit_key_down = False

    def _canvas_action_key_allowed(self, event):
        """Canvas-only hotkeys, independent of keyboard focus within review.

        The S/A early bindtag catches keypresses even with Treeview focused.
        R/T/N share that dispatch but never steal typing in GT fields.
        Windows Mod1 (Tk state=8) is not Ctrl and must be permitted.
        """
        if event is None:
            return True
        widget = getattr(event, "widget", None)
        if widget is not self.c and not self._event_in_review_window(event):
            return False
        if self._is_typing_shortcut(widget) or getattr(event, "state", 0) & 4:
            return False
        return self._canvas_hotkey_pointer(event) is not None

    def remove_hotkey(self, event=None):
        if not self._canvas_action_key_allowed(event):
            return None
        return self.remove_selected(event)

    def roi_hotkey(self, event=None):
        if not self._canvas_action_key_allowed(event):
            return None
        return self.toggle_roi_overlay(event)

    def cycle_hotkey(self, event=None):
        if not self._canvas_action_key_allowed(event):
            return None
        return self.cycle(event)

    def no_delete(self, event=None):
        self.message("Najazd + S zaznacza. R usuwa ramkę ręczną lub cofa korektę MT. T pokazuje/ukrywa ROI. PPM jednym kliknięciem zmienia flagę błędu.")
        return "break"

    def message(self, text):
        self.h.status_var.set(text)

    def _read(self):
        h = self.h
        key = (h.current_invocation, getattr(getattr(h.session,"review",None),"review_revision",None))
        if self.cache_key != key:
            self.cache_key = key
            try:
                self.cached = core.scene(h.session, h.current_invocation) if h.session and h.current_invocation else None
                self.read_error = ""
            except (ValueError, KeyError, TypeError) as e:
                self.cached = None
                self.read_error = str(e)
        return self.cached

    def sync(self):
        h = self.h
        for widget in self.old_right:
            widget.grid_remove()
        h.target_nav.grid_remove()
        try:
            h.mt_visual_overlay.place_forget()
        except tk.TclError:
            pass
        if self.skey != h.current_invocation:
            self.skey = h.current_invocation
            self.selected = self.hover = ""
            self.pointer_canvas = None
            self.points = []
            self.drag = None
            self._click_candidate = None
            self.mode = "select"
            self.plate_fit_previous = None
            self.plate_fit_active = False
            self.plate_fit_gid = ""
        if self.pending_tree_target and self.pending_tree_target[0] == h.current_invocation:
            self.selected = self.pending_tree_target[1]
            self.mode = "edit" if self.selected else "select"
            self.pending_tree_target = None
        s = self._read()
        available = bool(s and h._image is not None and h._image_entry == s["image_entry"]
            and tuple(h._image_source_size or ()) == tuple(s["image_size"]))
        enabled = available and not h._saving and not self.busy
        # The previously reviewed 2->1 scene must first be reconciled; checking
        # the image must not imply approval of unresolved historical GT.
        self.approve.configure(state="normal" if enabled and not (s and s.get("_post_nms_pending")) else "disabled")
        self.exclude.configure(state="normal" if enabled else "disabled")
        self.reason_entry.configure(state="normal" if enabled else "disabled")
        self.crop.configure(state="disabled")
        if not s:
            self.checked_var.set(False); self.excluded_var.set(False)
            self.reconciliation_box.pack_forget()
            self.nms_action.pack_forget()
            self.reason_host.pack_forget()
            self.status.configure(text="Tylko podgląd", bg=self.p["amber_bg"], fg=self.p["amber"])
            self.tally.configure(text=getattr(self, "read_error", "") or "Wybierz obraz z pełną klatką i ROI.")
            self.selection.configure(text="Brak aktywnej ramki")
            self.selection_hint.configure(text="Edycja wymaga zgodnych współrzędnych źródłowych.")
            for card in self.tally_cards.values(): card.set("—")
            return
        self.checked_var.set(s["checked"])
        self.excluded_var.set(bool(s.get("exclusion_reason")))
        # The explanatory decision panel is synced after reading final/raw counts.
        reason = s.get("exclusion_reason", "")
        default = "Operator oznaczył obraz jako niemożliwy do oceny"
        if h.window.focus_get() is not self.reason_entry or self.reason_gid != self.skey:
            self.reason_var.set("" if reason == default else reason)
        self.reason_gid = self.skey
        if reason:
            self.reason_host.pack(fill="x", pady=(4, 0))
        else:
            self.reason_host.pack_forget()
        issues = core._content_issues(s)
        tone, title = (("purple", "SPRAWDZONY · NIE DO OCENY") if reason else
                       ("green", "SPRAWDZONY · GOTOWY") if s["checked"] and not issues else
                       ("amber", "SPRAWDZONY · BRAKI DANYCH") if s["checked"] else
                       ("blue", "DO SPRAWDZENIA"))
        if not available: title += "\nPodgląd wejścia MT"
        self.status.configure(text=title, bg=self.p[tone+"_bg"], fg=self.p[tone])
        tally = core.counts(s)
        for key, card in self.tally_cards.items(): card.set(str(tally[key]))
        self._sync_reconciliation_story(s, tally, enabled)
        notes = []
        if tally["operator_errors"]:
            notes.append(f"Błędy operatora: {tally['operator_errors']} · Po zaznaczeniu R usuwa próbne ramki.")
        if reason:
            notes.append("Sprawdzony; poza mianownikami oceny.")
        elif s["checked"] and issues:
            notes.append(f"Do uzupełnienia: {len(issues)}. Szczegóły w statusach po lewej.")
        elif not s["checked"]:
            notes.append("Liczby robocze — obraz niepotwierdzony.")
        self.tally.configure(text="\n".join(notes))
        obj = next((o for o in s["objects"] if o["object_id"] == self.selected), None)
        if self.selected and (obj is None or obj.get("post_nms_suppressed", False)):
            self.selected = self.hover = ""
            obj = None
            if self.mode == "edit": self.mode = "select"
        parent = next((p for p in s["parents"] if obj and p["parent_id"] == obj["parent_id"]), None)
        if obj:
            title = f"MT {int(parent['detection_index'])+1} · nakładka" if parent else "Ramka ręczna"
            if obj["error"]: title = "× BŁĄD · " + title
            self.selection.configure(text=title, fg=self.p["red"] if obj["error"] else self.p["fg"])
            self.selection_hint.configure(text=("R: cofnij korektę do wyniku MT; GT pozostaje." if parent else "R: usuń ręcznie dodaną ramkę.")
                                          + "\nLPM: przeciągnij narożnik. S: odznacz.")
            self.crop.configure(state="normal" if parent and parent["mz_ran"] else "disabled")
        else:
            self.selection.configure(text="Wybierz ramkę", fg=self.p["fg"])
            self.selection_hint.configure(text="Kliknij ramkę lub najedź i naciśnij S.\nNarożniki pojawią się po zaznaczeniu.")
        self.sync_tree_selection()

    def available(self):
        s = self._read()
        if self.h._saving or self.busy:
            self.message("Trwa zapis/odświeżanie wyników; bieżąca edycja pozostaje zachowana.")
            return False
        if not s or self.h._image is None or self.h._image_entry != s["image_entry"] or tuple(self.h._image_source_size or ()) != tuple(s["image_size"]):
            self.message("Rysowanie jest możliwe na zweryfikowanej pełnej klatce z ROI, nie na cropie ani innym obrazie.")
            return False
        return True

    def to_canvas(self, point):
        s = self._read()
        h = self.h
        sx = h._image.width / s["image_size"][0]
        sy = h._image.height / s["image_size"][1]
        cx,cy = h._view_center
        z = h._view_pixel_scale
        return ((point[0]*sx-cx)*z+self.c.winfo_width()/2,
                (point[1]*sy-cy)*z+self.c.winfo_height()/2)

    def to_source(self, x, y):
        s = self._read()
        h = self.h
        cx,cy = h._view_center
        z = max(h._view_pixel_scale,1e-12)
        return ((cx+(x-self.c.winfo_width()/2)/z)*s["image_size"][0]/h._image.width,
                (cy+(y-self.c.winfo_height()/2)/z)*s["image_size"][1]/h._image.height)

    def _current_quad(self, obj):
        if self.drag and self.drag["oid"] == obj["object_id"]:
            return self.drag["quad"]
        return obj.get("quad")

    def paint(self, width, height):
        s = self._read()
        if not s or self.h._image_entry != s["image_entry"]:
            # Old evidence remains visible, without legacy counting/drawing CTA.
            if self.h._is_source_frame_view():
                self.h._paint_source_frame_overlays(width,height)
            self.h.image_help.configure(text="Podgląd dowodu. Edycja wymaga potwierdzonej pełnej klatki + ROI.")
            return True
        if tuple(self.h._image_source_size or ()) != tuple(s["image_size"]):
            self.h.image_help.configure(text="Rozmiar obrazu nie odpowiada metadanym — edycja zablokowana.")
            return True
        self.overlay()
        return True

    def request_overlay(self):
        if self.paint_scheduled or self.h._closed:
            return
        self.paint_scheduled = True
        def repaint():
            self.paint_after = None
            self.paint_scheduled = False
            if not self.h._closed:
                self.overlay()
        self.paint_after = self.c.after_idle(repaint)

    def overlay(self):
        self.c.delete(TAG)
        s = self._read()
        if not s or self.h._image is None or self.h._image_entry != s["image_entry"] or self.h._view_center is None:
            return
        width,height = self.c.winfo_width(),self.c.winfo_height()
        self.badges = {}
        self.card_positions = {}

        def draw_contour(points, *, color, width, tags=()):
            # A SINGLE fine contour. The old dark halo looked like a second box.
            flat = [v for p in points for v in p]
            self.c.create_polygon(*flat, fill="", outline=color, width=width,
                                  tags=tags)

        l,t,r,b = s["roi"]
        x1,y1 = self.to_canvas((l,t)); x2,y2 = self.to_canvas((r,b))
        if self.show_roi_overlay:
            # Outline only: the old gray12 stipple put a dotted grid over the photo.
            self.c.create_rectangle(x1,y1,x2,y2, fill="", outline="#FFD16C",
                                    width=1.1, tags=(TAG,"analyzed_roi"))
        parents = {p["parent_id"]:p for p in s["parents"]}
        suppressed_parent_ids = {o["parent_id"] for o in s["objects"]
                                 if o.get("post_nms_suppressed", False)}
        # Exclude RAW candidates rejected by NMS only from the visual overlay;
        # preserve all original detections and their evidence for auditing.
        for parent in s["parents"]:
            if not parent["quad"] or parent["parent_id"] in suppressed_parent_ids:
                continue
            # During GT correction the original is hidden, not deleted.
            if self.mode == "edit" and self.selected:
                continue
            pts = [self.to_canvas(p) for p in parent["quad"]]
            draw_contour(pts, color="#00E5FF", width=1.5,
                         tags=(TAG,"mt_original","mt_accepted",parent["parent_id"]))
        placed=[]
        for index,obj in enumerate(s["objects"],1):
            if obj.get("post_nms_suppressed", False):
                continue  # RAW evidence already drawn above, never a second GT badge.
            quad = self._current_quad(obj)
            if not quad:
                continue
            pts = [self.to_canvas(p) for p in quad]
            xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
            if max(xs)<0 or min(xs)>width or max(ys)<0 or min(ys)>height:
                continue
            oid = obj["object_id"]
            if obj["error"]:
                color, contour_width = "#FF3B5C", 1.8
            elif oid == self.selected:
                color, contour_width = "#FFD400", 2.0
            else:
                color, contour_width = "#FF8A00", 1.5
            draw_contour(pts, color=color, width=contour_width,
                         tags=(TAG,"operator_quad",oid))
            if obj["error"]:
                for a,b in ((0,2),(1,3)):
                    self.c.create_line(*pts[a],*pts[b],fill="#FF3B5C",width=1.5,tags=(TAG,"error_flag",oid))
            if self.mode=="edit" and oid == self.selected:
                for j,(x,y) in enumerate(pts):
                    self.c.create_oval(x-6,y-6,x+6,y+6,fill="#FFFFFF",outline=color,width=1.4,
                        tags=(TAG,"corner_handle",oid))
            parent = parents.get(obj["parent_id"])
            pred = parent["mz_prediction"] if parent else ""
            caption = obj["gt_text"] or ("nieczytelna" if obj["text_exclusion_reason"] else "wpisz GT")
            if obj["error"]:
                caption = "× BŁĄD · " + (obj["gt_text"] or "ramka zachowana")
            cw=194; ch=48
            xx = max(4,min(width-cw-4,min(xs)))
            yy = max(4,min(height-ch-4,max(ys)+10))
            candidates=[(xx,yy),(xx,min(ys)-ch-12),(max(xs)+14,min(ys)),(min(xs)-cw-14,min(ys))]
            candidates += [(xx,yy+step*54) for step in range(1,8)]
            for px,py in candidates:
                px=max(4,min(width-cw-4,px)); py=max(4,min(height-ch-4,py))
                if not any(px<q[2]+4 and px+cw>q[0]-4 and py<q[3]+4 and py+ch>q[1]-4 for q in placed):
                    xx,yy=px,py
                    break
            placed.append((xx,yy,xx+cw,yy+ch))
            self.card_positions[oid]=(xx,yy)
            center=(sum(xs)/4,sum(ys)/4)
            tx=max(xx,min(xx+cw,center[0])); ty=max(yy,min(yy+ch,center[1]))
            self.c.create_line(tx,ty,*center,fill="#DDE7EF",width=1.0,tags=(TAG,"badge_tether",oid))
            self.c.create_rectangle(xx,yy,xx+cw,yy+23,fill="#0F2230",outline="#00E5FF",width=1.0,tags=(TAG,"mz_badge",oid))
            # Empty prediction intentionally stays empty: no OCR placeholder.
            mz_label = (f"MZ / MT {int(parent['detection_index'])+1}: " + pred
                        if parent else "Ręczna GT · MZ nie uruchomiono")
            self.c.create_text(xx+6,yy+11,anchor="w",text=mz_label,fill="#F2FBFF",font=("Segoe UI",10,"bold"),width=cw-12,tags=(TAG,"mz_badge",oid))
            self.c.create_rectangle(xx,yy+25,xx+cw,yy+48,fill="#302618",outline=color,width=1.0,tags=(TAG,"gt_badge",oid))
            self.c.create_text(xx+6,yy+36,anchor="w",text="GT: "+caption,fill=color,font=("Segoe UI",10,"bold"),width=cw-12,tags=(TAG,"gt_badge",oid))
            self.badges[oid]=(xx,yy+25,xx+cw,yy+48)
            if self.entry is not None and self.entry_target==(self.h.current_invocation,oid):
                self.entry.place(x=xx+1,y=yy+25,width=cw-2,height=23)
                self.entry.lift()
        if self.points:
            pts=[self.to_canvas(p) for p in self.points]
            if self.pointer:
                pts.append(self.to_canvas(self.pointer))
            if len(pts)>=2:
                self.c.create_line(*[v for p in pts for v in p],fill="#FFF2A8",width=2.6,tags=(TAG,"drawing_line"))
            for x,y in pts[:len(self.points)]:
                self.c.create_oval(x-5,y-5,x+5,y+5,fill="#FFD400",outline="#FFFFFF",width=1.4,tags=(TAG,"drawing_corner"))
        self._paint_live_overlap_hud(s)
        self.c.tag_raise("corner_handle")
        mode="D: wskaż róg %d/4"%(len(self.points)+1) if self.mode=="draw" else "S: odznacz/wybierz · LPM: narożnik · R: usuń/cofnij · PPM: błąd 1 klik" if self.mode=="edit" else "Najedź + S: zaznacz · D: dodaj"
        self.h.image_help.configure(text=("A: zbliż/powrót  •  R: usuń/cofnij ramkę  •  T: pokaż/ukryj ROI  •  "
               "N: następna tablica  •  Spacja: sprawdzony/nie  •  PPM: błąd jednym kliknięciem  •  "
               "turkus: MT  •  żółty: GT/korekta"))
        self.c.configure(cursor="crosshair" if self.mode=="draw" else "arrow")

    def _paint_live_overlap_hud(self, scene):
        """On-canvas badge next to corrected quad; per-drag assisted metrics.

        Compare original MT with live operator quad (not independent truth).
        Display only; never edit either polygon or persist intermediate points.
        """
        if self.mode != "edit" or not self.selected:
            return
        obj = next((o for o in scene["objects"] if o["object_id"] == self.selected
                    and not o.get("post_nms_suppressed", False)), None)
        if obj is None:
            return
        quad = self._current_quad(obj)
        if not quad:
            return
        parent = next((p for p in scene["parents"]
                       if p["parent_id"] == obj["parent_id"]), None)
        if not parent or not parent.get("quad"):
            lines = ("RAMKA RĘCZNA", "Brak oryginalnej ramki MT do porównania.")
        else:
            try:
                metric = core.compare_mt_pose_to_gt(parent["quad"], quad,
                                                    *scene["image_size"])
                overlap = float(metric["polygon_iou_pct"])
                corner_err = float(metric["nmce_pct"])
                if not (math.isfinite(overlap) and math.isfinite(corner_err)):
                    raise ValueError("Nieprawidłowy wynik")
                overlap = max(0.0, min(100.0, overlap))
                live = " · na żywo" if self.drag else ""
                lines = ("MT ↔ KOREKTA OPERATORA" + live,
                         f"Pokrycie (IoU): {overlap:.1f}% · różnica: {100.0-overlap:.1f}%",
                         f"Błąd narożników (NMCE): {corner_err:.2f}%")
            except (ValueError, TypeError, KeyError, IndexError,
                    ZeroDivisionError, OverflowError):
                lines = ("MT ↔ KOREKTA OPERATORA", "Obrys wymaga poprawnego ustawienia.")
        cw = int(self.c.winfo_width())
        ch = int(self.c.winfo_height())
        if cw < 180 or ch < 100:
            return
        pts = [self.to_canvas(p) for p in quad]
        px = sum(x for x, _ in pts) / len(pts)
        top = min(y for _, y in pts)
        badge_w = min(338, cw - 16)
        badge_h = 69 if len(lines) == 3 else 51
        left = max(8, min(cw-badge_w-8, px-badge_w/2))
        # Prefer immediately ABOVE the active frame. If the frame touches the
        # viewport top, keep the badge visible, not at a fixed upper-left HUD.
        badge_y = max(8, min(ch-badge_h-8, top-badge_h-10))
        # A small connector identifies which quad the values describe.
        if top > badge_y+badge_h+1:
            self.c.create_line(px, badge_y+badge_h, px, min(top, ch),
                               fill="#F9CE55", width=1.4,
                               tags=(TAG,"overlap_hud","overlap_hud_tether"))
        self.c.create_rectangle(left, badge_y, left+badge_w, badge_y+badge_h,
                                fill="#081925", outline="#FFD400", width=1.5,
                                tags=(TAG,"overlap_hud","overlap_hud_badge"))
        for i, line in enumerate(lines):
            self.c.create_text(left+9, badge_y+12+i*21, text=line, anchor="w",
                               font=("Segoe UI", 9, "bold" if i==0 else "normal"),
                               fill="#FFFFFF" if i==0 else "#E7F2FF",
                               tags=(TAG,"overlap_hud","overlap_hud_text"))

    def hit(self, x, y, badge=True):
        s = self._read()
        if not s or self.h._image_entry != s["image_entry"] or self.h._view_center is None:
            return None
        objects = [o for o in s["objects"] if not o.get("post_nms_suppressed", False)]
        # Only the explicitly selected child has draggable handles. Their
        # outside half and paint/hit priority are retained; hover owns no handle.
        if self.mode == "edit" and self.selected:
            obj = next((o for o in objects if o["object_id"] == self.selected), None)
            if obj:
                for i, p in enumerate(self._current_quad(obj) or ()):
                    if math.dist((x, y), self.to_canvas(p)) <= 14:
                        return obj["object_id"], "corner", i
        if badge:
            for oid, (l,t,r,b) in reversed(list(self.badges.items())):
                if l <= x <= r and t <= y <= b:
                    return oid, "badge", None
            for oid, (l, t) in reversed(list(self.card_positions.items())):
                if l <= x <= l + 194 and t <= y <= t + 23:
                    return oid, "mz_badge", None
        def near_edge(quad):
            pts = [self.to_canvas(p) for p in quad]
            for a,b in zip(pts, pts[1:]+pts[:1]):
                dx,dy=b[0]-a[0],b[1]-a[1]
                denom=dx*dx+dy*dy
                u=max(0,min(1,((x-a[0])*dx+(y-a[1])*dy)/denom)) if denom else 0
                if math.dist((x,y),(a[0]+u*dx,a[1]+u*dy)) <= 11:
                    return True
            return False
        source = self.to_source(x,y)
        for obj in reversed(objects):
            quad = self._current_quad(obj)
            if quad and (quad_contains_point(quad,*source) or near_edge(quad)):
                return obj["object_id"], "body", None
        # S over an unchanged MT original targets its one editable child.
        for parent in reversed(s["parents"]):
            if not any(o["parent_id"] == parent["parent_id"] for o in objects):
                continue
            quad=parent["quad"]
            if quad and (quad_contains_point(quad,*source) or near_edge(quad)):
                obj=next((o for o in objects if o["parent_id"]==parent["parent_id"]),None)
                if obj: return obj["object_id"], "body", None
        return None

    def _commit(self, action, description, remember=True):
        if not self.available():
            return False
        gid=self.h.current_invocation
        before=copy.deepcopy(self._read())
        self.busy=True
        try:
            value=action()
        except (ValueError, OSError, KeyError, TypeError) as e:
            self.message("Nie zapisano: "+str(e))
            return False
        finally:
            self.busy=False
        if remember:
            self.undo_stack.setdefault(gid,[]).append(before)
            self.undo_stack[gid]=self.undo_stack[gid][-30:]
            self.redo_stack[gid]=[]
        self.cache_key=None
        self.refresh_tree()
        self.sync()
        self.update_report()
        self.request_overlay()
        self.message(description+f" · zapisano rewizję {self.h.session.review.review_revision}")
        self.schedule_refresh()
        return value if value is not None else True

    def schedule_refresh(self):
        if self.refresh_after:
            self.c.after_cancel(self.refresh_after)
        self.refresh_after=self.c.after(650,self.refresh_results)

    def refresh_results(self):
        if self.refresh_after:
            self.c.after_cancel(self.refresh_after)
        self.refresh_after=None
        h=self.h
        if h._closed:
            return
        if self.entry is not None or self.points or self.drag or h._saving or self.in_refresh:
            self.refresh_after=self.c.after(650,self.refresh_results)
            return
        self.in_refresh=True
        def after():
            self.in_refresh=False
            # Statistics must not restore a selection captured before the worker.
            # The operator may have selected/deselected a frame in the meantime.
            self.sync()
            self.request_overlay()
        # Use the existing single worker for statistics/ranking; sidecar writes
        # have already succeeded. Never push hidden legacy subject GT fields.
        h._change(lambda:None, save_draft=False, after=after)

    def draw_toggle(self,event=None):
        if event is not None and getattr(event,"state",0)&4:
            return "break"
        if not self.finish_entry() or not self.available():
            return "break"
        self.mode="select" if self.mode=="draw" else "draw"
        self.selected=self.hover=""
        self.points=[]; self.pointer=None; self.drag=None
        self._click_candidate = None
        self.sync()
        self.request_overlay()
        return "break"

    def _pointer_for_selection(self, event=None):
        """Tk key-event x/y are NOT reliable canvas pointer coordinates.

        On Windows/X11 they may be (0,0) or even negative despite a mouse
        visibly hovering over the plate. Query the real screen pointer, then
        convert to canvas-local pixels. Only fall back to the last Motion event
        on lightweight non-Tk fixtures; never infer plate from text or GT.
        """
        if event is not None and getattr(event, "widget", self.c) is not self.c:
            return None

        def inside(xy):
            return (xy is not None and all(math.isfinite(v) for v in xy)
                    and 0 <= xy[0] < self.c.winfo_width()
                    and 0 <= xy[1] < self.c.winfo_height())

        try:
            xy = (float(self.c.winfo_pointerx() - self.c.winfo_rootx()),
                  float(self.c.winfo_pointery() - self.c.winfo_rooty()))
            if inside(xy):
                return xy
            # Pointer is physically outside: do not reuse stale hover data.
            return None
        except (AttributeError, tk.TclError, TypeError, ValueError, OverflowError):
            pass
        return self.pointer_canvas if inside(self.pointer_canvas) else None

    def _canvas_hotkey_pointer(self, event=None):
        """Read actual pointer *inside* this canvas, not keyboard event x/y.

        When Windows reports a 4–10px pointer offset at DPI scaling, a recent
        canvas Motion point is more accurate for hitting a narrow plate rim.
        The physical pointer MUST still be inside the canvas so a stale hover
        cannot activate shortcuts from the sidebar.
        """
        if self.entry is not None:
            return None
        widget = getattr(event, "widget", self.c) if event is not None else self.c
        if self._is_typing_shortcut(widget):
            return None
        if widget is not self.c:
            try:
                if widget.winfo_toplevel() is not self.h.window:
                    return None
            except (tk.TclError, AttributeError):
                return None
        # A Motion event already contains true canvas-local coordinates. This
        # is more accurate than OS screen coordinates under Windows DPI scaling.
        actual = self._pointer_for_selection(None)
        if actual is None:
            return None
        hover = self.pointer_canvas
        if (hover is not None and len(hover) == 2
                and 0 <= hover[0] < self.c.winfo_width()
                and 0 <= hover[1] < self.c.winfo_height()
                and math.dist(actual, hover) <= 90):
            return tuple(hover)
        return actual

    def _choose_plate(self, oid, *, toggle=False):
        """Select one operator quad without editing its saved GT or MT."""
        scene = self._read()
        if oid and not any(o["object_id"] == oid and
                           not o.get("post_nms_suppressed", False)
                           for o in (scene or {}).get("objects", ())):
            return False
        self.selected = "" if toggle and oid == self.selected else oid
        self.mode = "edit" if self.selected else "select"
        self.hover = ""
        self.h._view_drag_at = None
        if not self.selected:
            self.clear_tree_selection()
        self.sync()
        self.request_overlay()
        self.message("Ramka wybrana. Cztery białe uchwyty można przeciągać LPM. "
                     "Środek obrazu przeciągnij, aby go przesunąć."
                     if self.selected else
                     "Ramka odznaczona. Kliknij obrys lub najedź na ramkę i naciśnij S.")
        return True

    def select_mode(self, event=None):
        """S at the real pointer location toggles the editable quad."""
        # The real Windows session recorded S with Tk state=8 (Mod1).
        # S and A share this guard: reject Ctrl (bit 4) only, while
        # still requiring an eligible pointer and no active GT input.
        if event is not None and getattr(event, "state", 0) & 4:
            return "break"
        if self.drag:
            self.message("Dokończ przeciąganie narożnika przed zmianą zaznaczenia.")
            return "break"
        if self.points:
            self.message("Dokończ cztery punkty albo anuluj D/Esc.")
            return "break"
        if not self.finish_entry():
            return "break"
        scene = self._read()
        h = self.h
        if (not scene or h._image is None or h._image_entry != scene["image_entry"]
                or tuple(h._image_source_size or ()) != tuple(scene["image_size"])
                or h._view_center is None):
            self.message("S: to nie jest edytowalna pełna klatka lub nie ma geometrii obrazu.")
            return "break"
        xy = self._canvas_hotkey_pointer(event)
        if xy is None:
            self.message("S: przesuń kursor na zdjęcie, a następnie nad obrys tablicy.")
            return "break" if getattr(event, "widget", self.c) is self.c else None
        self.pointer_canvas = xy
        # Prefer the object resolved on the actual Canvas <Motion> event. This
        # avoids Windows DPI offsets turning S into a silent miss on thin quads.
        cached = getattr(self, "_s_hover_hit", None)
        target = None
        if cached is not None:
            group_id, oid, hover_xy = cached
            if (group_id == self.h.current_invocation
                    and math.dist(xy, hover_xy) <= 36
                    and any(o["object_id"] == oid and not o.get("post_nms_suppressed", False)
                            for o in scene["objects"])):
                target = (oid, "body", None)
        if target is None:
            target = self.hit(*xy, badge=True)
        if target:
            self._choose_plate(target[0], toggle=True)
        else:
            self.message("Najedź kursorem na ramkę tablicy i naciśnij S.")
        return "break"


    def selection_key_press(self, event):
        if self._canvas_hotkey_pointer(event) is None:
            # Let other panels use S normally. A pointer inside the image
            # receives a visible explanation through select_mode().
            return "break" if getattr(event, "widget", self.c) is self.c else None
        if self.selection_release_after:
            self.c.after_cancel(self.selection_release_after)
            self.selection_release_after = None
        if self.selection_key_down:
            return "break"
        self.selection_key_down = True
        return self.select_mode(event)

    def selection_key_release(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self.c and not self._event_in_review_window(event):
            return None
        # X11 repeats release/press pairs; Windows normally repeats KeyPress.
        # Idle deferral coalesces both into one toggle per physical key press.
        if self.selection_release_after:
            self.c.after_cancel(self.selection_release_after)
        self.selection_release_after = self.c.after_idle(self.reset_selection_key)
        return "break"

    def reset_selection_key(self, event=None):
        if self.selection_release_after:
            self.c.after_cancel(self.selection_release_after)
            self.selection_release_after = None
        self.selection_key_down = False

    def press(self,event):
        self._click_candidate = None
        if not self.finish_entry() or not self.available():
            return "break"
        self.c.focus_set()
        if self.mode=="draw":
            p=self.to_source(event.x,event.y)
            l,t,r,b=self._read()["roi"]
            if not (l<=p[0]<=r and t<=p[1]<=b):
                self.message("Brakujące ramki rysujemy tylko w analizowanym ROI.")
                return "break"
            if len(self.points)<4:
                self.points.append(p)
            if len(self.points)==4:
                try:
                    quad=core.ordered_quad(self.points,self._read()["image_size"],self._read()["roi"])
                except (ValueError,TypeError) as e:
                    self.points.pop()
                    self.message(str(e)+" · popraw czwarty punkt albo Esc.")
                    self.request_overlay()
                    return "break"
                oid=self._commit(lambda:core.add_plate(self.h.session,self.h.current_invocation,quad),"Dodano tablicę pominiętą przez MT")
                if oid:
                    self.selected=oid
                    self.points=[];self.pointer=None;self.mode="edit"
                    self.sync()
            self.request_overlay()
            return "break"
        self.pointer_canvas = (event.x, event.y)
        target=self.hit(event.x,event.y)
        if target:
            oid,kind,index=target
            if kind=="badge":
                # A text editor owns its target; it does not change geometry selection.
                self.start_entry(oid)
            elif kind=="corner" and self.mode=="edit" and oid==self.selected:
                obj=next(o for o in self._read()["objects"] if o["object_id"]==oid)
                self.drag=dict(oid=oid,index=index,quad=copy.deepcopy(obj["quad"]),before=copy.deepcopy(obj["quad"]))
            elif kind in ("body", "mz_badge"):
                # A short click selects; a genuine drag pans the image.
                self._click_candidate = (oid, event.x, event.y)
                self.h._view_drag_at=(event.x,event.y,self.h._view_center)
            else:
                self.h._view_drag_at=(event.x,event.y,self.h._view_center)
            self.request_overlay()
            return "break"
        # Panning is permitted also when a GT contour is selected.
        self.h._view_drag_at=(event.x,event.y,self.h._view_center)
        self.request_overlay()
        return "break"

    def motion(self,event):
        if self.drag:
            p=self.to_source(event.x,event.y)
            s=self._read(); w,h=s["image_size"]
            obj=next(o for o in s["objects"] if o["object_id"]==self.drag["oid"])
            l,t,r,b=s["roi"] if not obj["parent_id"] else (0,0,w,h)
            p=(max(l,min(r,p[0])),max(t,min(b,p[1])))
            self.drag["quad"][self.drag["index"]]=list(p)
            self.request_overlay()
            return "break"
        if self._click_candidate is not None:
            _, x0, y0 = self._click_candidate
            if math.hypot(event.x-x0, event.y-y0) > 5:
                self._click_candidate = None
        return self.pan_motion(event)

    def release(self,event=None):
        click_candidate = self._click_candidate
        self._click_candidate = None
        was_dragging_corner = self.drag is not None
        if self.drag:
            state=self.drag
            if state["quad"] != state["before"]:
                ok=self._commit(lambda:core.correct_plate(self.h.session,self.h.current_invocation,state["oid"],state["quad"]),"Zapisano korektę ramki potomnej")
                if not ok:
                    self.message("Nie zapisano nieprawidłowego obrysu. Przywrócono ostatnią poprawną ramkę.")
            self.drag=None
            self.request_overlay()
        self.h._view_drag_at=None
        # Select only after a stationary click. Moving the contour itself
        # continues to pan without changing the selected tablicę.
        if (not was_dragging_corner and click_candidate is not None
                and event is not None):
            oid, x0, y0 = click_candidate
            if math.hypot(event.x-x0, event.y-y0) <= 5:
                self._choose_plate(oid)
        return "break"

    def hover_motion(self, event):
        self.pointer_canvas = (event.x, event.y)
        s = self._read()
        if not s or self.h._image_entry != s["image_entry"] or self.h._view_center is None:
            self._s_hover_hit = None
            return
        if self.mode == "draw":
            self._s_hover_hit = None
            self.pointer = self.to_source(event.x, event.y)
            self.request_overlay()
        elif not self.drag:
            target = self.hit(event.x, event.y, badge=True)
            self._s_hover_hit = ((self.h.current_invocation, target[0],
                                  (event.x, event.y)) if target else None)
            cursor = "fleur" if target and target[1] == "corner" else "hand2" if target and target[1] in ("badge", "body", "mz_badge") else "arrow"
            if self.c.cget("cursor") != cursor:
                self.c.configure(cursor=cursor)

    def right_press(self, event):
        """One right-click on a plate toggles its error flag immediately.

        PPM does not require a previous S/LPM selection. Empty canvas still
        pans as before. Suppressed RAW is not selectable or mutable.
        """
        if not self.finish_entry():
            return "break"
        if self.mode == "draw":
            return self.escape()
        if not self.available():
            return "break"
        self.pointer_canvas = (event.x, event.y)
        target = self.hit(event.x, event.y)
        if target:
            oid = target[0]
            obj = next((o for o in self._read()["objects"]
                        if o["object_id"] == oid and not o.get("post_nms_suppressed", False)), None)
            if obj is not None:
                self._click_candidate = None
                self.h._view_drag_at = None  # PPM on a frame must not initiate pan.
                self.selected = oid
                self.mode = "edit"
                description = ("Cofnięto oznaczenie błędnej ramki" if obj["error"] else
                               "Oznaczono wskazaną ramkę jako błędną")
                self._commit(
                    lambda: core.toggle_error(self.h.session, self.h.current_invocation, oid),
                    description,
                )
                self.request_overlay()
                return "break"
        self.h._view_drag_at = (event.x, event.y, self.h._view_center)
        return "break"

    def pan_motion(self,event):
        state=self.h._view_drag_at
        if state and self.h._image is not None:
            x,y,center=state
            if center:
                z=max(self.h._view_pixel_scale,1e-12)
                self.h._view_center=(center[0]-(event.x-x)/z,center[1]-(event.y-y)/z)
                self.h._paint_image()
        return "break"

    def pan_release(self,event=None):
        self.h._view_drag_at=None
        return "break"

    def back_point(self,event=None):
        if self.mode=="draw" and self.points:
            self.points.pop();self.request_overlay()
        else:
            self.no_delete()
        return "break"

    def escape(self,event=None):
        if self.entry is not None:
            self.entry_var.set(self.entry_original)
            self.destroy_entry()
        self.points=[];self.pointer=None;self.drag=None;self.mode="select"
        self._click_candidate = None
        self.selected=self.hover=""
        self.pending_tree_target = None
        self.h._view_drag_at=None
        # Explicit cancellation clears an image/group row too. Ordinary sync
        # must still preserve parent-row navigation when no plate is selected.
        self.clear_tree_selection()
        self.sync()
        self.request_overlay()
        return "break"

    def start_entry(self,oid):
        if not self.available():
            return
        obj=next(o for o in self._read()["objects"] if o["object_id"]==oid)
        if obj["error"]:
            self.message("Ramka ma flagę błędu. Jeden klik PPM na ramce cofa tę flagę.")
            return
        self.entry_target=(self.h.current_invocation,oid)
        self.entry_original=obj["gt_text"]
        self.entry_var=tk.StringVar(value=obj["gt_text"])
        self.entry=tk.Entry(self.c,textvariable=self.entry_var,font=("Segoe UI",11,"bold"),
            bg="#302618",fg="#FFE2AE",insertbackground="#FFFFFF",relief="flat")
        # Widget+class only: ordinary text editing remains, global Z2/app
        # shortcuts cannot consume D/S/Q/E typed as a plate number.
        self.entry.bindtags((str(self.entry),self.entry.winfo_class()))
        self.entry.bind("<Return>",lambda e:self.entry_enter())
        self.entry.bind("<KP_Enter>",lambda e:self.entry_enter())
        self.entry.bind("<Escape>",self.escape)
        self.entry.bind("<FocusOut>",lambda e:self.finish_entry())
        self.entry.bind("<KeyRelease>",self.entry_typed)
        self.entry.bind("<Button-3>",lambda e:self.unreadable())
        self.request_overlay()
        x,y=self.card_positions.get(oid,(4,4))
        self.entry.place(x=x+1,y=y+25,width=192,height=23)
        self.entry.focus_set();self.entry.selection_range(0,"end")
        self.message("GT na badge: Enter lub wyjście zapisuje; Esc cofa do ostatniego zapisu. PPM w polu: nieczytelna tablica.")

    def entry_typed(self,event=None):
        if self.entry is None:
            return
        val=self.entry_var.get()
        if val != val.upper():
            pos=self.entry.index("insert")
            self.entry_var.set(val.upper());self.entry.icursor(pos)
        if self.entry_after:
            self.c.after_cancel(self.entry_after)
        self.entry_after=self.c.after(650,self.autosave_entry)

    def autosave_entry(self):
        self.entry_after=None
        if self.entry is not None:
            self.save_entry(close=False)

    def save_entry(self,close=True):
        if self.entry is None:
            return True
        gid,oid=self.entry_target
        if gid!=self.h.current_invocation:
            self.message("Nie zmieniono celu GT. Wróć do obrazu z aktywną edycją.")
            return False
        value=self.entry_var.get()
        if value!=self.entry_original:
            if not self._commit(lambda:core.set_text(self.h.session,gid,oid,value),"Zapisano GT wybranej tablicy"):
                return False
            self.entry_original=value
        if close:
            self.destroy_entry()
        return True

    def finish_entry(self):
        return self.save_entry(close=True)

    def entry_enter(self):
        if self.finish_entry():
            self.c.focus_set()
        return "break"

    def destroy_entry(self):
        if self.entry_after:
            self.c.after_cancel(self.entry_after);self.entry_after=None
        entry,self.entry=self.entry,None
        self.entry_target=None
        if entry is not None:
            entry.destroy()
        self.request_overlay()

    def unreadable(self):
        if self.entry is None:
            return "break"
        gid,oid=self.entry_target
        reason=simpledialog.askstring("Nieczytelny numer", "Przyczyna nieczytelności tej tablicy:",parent=self.h.window)
        if reason and self._commit(lambda:core.set_text(self.h.session,gid,oid,"",reason),"Zapisano przyczynę nieczytelności"):
            self.destroy_entry()
        return "break"

    def prepare_navigation(self):
        if self.in_refresh:
            return True
        if self.points:
            self.message("Dokończ ramkę (4 punkty) albo anuluj D/Esc przed zmianą obrazu. Szkic pozostaje na canvasie.")
            return False
        if self.drag:
            self.release()
        if not self.finish_entry():
            return False
        return self._flush_exclusion_reason()

    def confirm(self, event=None):
        if not self.prepare_navigation() or not self.available():
            return "break"
        self.checked_var.set(not bool(self.checked_var.get()))
        self.toggle_checked()
        return "break"

    def exclude_image(self):
        self.excluded_var.set(True)
        self.toggle_excluded()

    def cycle(self,event=None):
        if not self.prepare_navigation() or not self.available():
            return "break"
        ids=[o["object_id"] for o in self._read()["objects"] if not o.get("post_nms_suppressed", False)]
        if ids:
            self.selected=ids[(ids.index(self.selected)+1)%len(ids)] if self.selected in ids else ids[0]
            self.mode="edit"
            self.plate_fit_previous=None
            self.plate_fit_active=False
            self.plate_fit_gid=""
            self.sync();self.request_overlay()
        return "break"

    def navigate(self,direction):
        if not self.prepare_navigation() or self.h._saving:
            return "break"
        # Q/E move between actually displayed images, never via a hidden
        # duplicate source record (e.g. source entry 20 linked with image 19).
        tree = self.h.subject_tree
        ids = list(tree.get_children(""))
        if not ids:
            return "break"
        current = self.tree_branch if self.tree_branch in ids else None
        if current is None:
            current = next((i for i,k in self.h._subject_ids.items()
                            if i in ids and k == self.h.subject_key), None)
        if current is None:
            current = next((owner for alias,(owner,gid) in self.linked_tree_rows.items()
                            if self.h._subject_ids.get(alias)==self.h.subject_key and owner in ids),None)
        idx = ids.index(current) if current in ids else 0
        target = ids[max(0,min(len(ids)-1,idx+direction))]
        if target != current:
            tree.selection_set(target)
            tree.focus(target)
            tree.see(target)
            self.h._select_subject()
        return "break"

    def fit(self):
        self.plate_fit_active=False
        self.plate_fit_gid=""
        self.plate_fit_previous=None
        self.plate_fit_saved=None
        self.h.fit_image()
        return "break"

    def toggle_roi_overlay(self, event=None):
        self.show_roi_overlay = not self.show_roi_overlay
        self.request_overlay()
        self.message("Obszar analizy: widoczny" if self.show_roi_overlay
                     else "Obszar analizy: ukryty tylko na ekranie; ocena pozostaje bez zmian")
        return "break"

    def fit_plate_toggle(self, event=None):
        """A / toolbar: fit hovered or selected GT quad, then restore view.

        Same approach as Z2: bbox in original image pixels, 20% horizontal /
        25% vertical margin (at least 16 px), centering via actual renderer's
        _view_zoom / _view_center, no GT or prediction modification.
        """
        # The real Windows session recorded S with Tk state=8 (Mod1).
        # S and A share this guard: reject Ctrl (bit 4) only, while
        # still requiring an eligible pointer and no active GT input.
        if event is not None and getattr(event, "state", 0) & 4:
            return "break"
        if event is not None and self._is_typing_shortcut(getattr(event, "widget", self.c)):
            return None
        scene = self._read()
        if (not scene or self.h._image is None or self.h._view_center is None
                or self.h._image_entry != scene["image_entry"]
                or tuple(getattr(self.h,"_image_source_size", ()) or ()) != tuple(scene["image_size"])):
            self.message("A: zbliżenie wymaga pełnej klatki z prawidłową geometrią.")
            return "break"
        if self.plate_fit_active and self.plate_fit_gid == self.h.current_invocation:
            previous = self.plate_fit_previous
            self.plate_fit_active = False
            self.plate_fit_gid = ""
            self.plate_fit_previous = None
            if previous:
                self.h._view_zoom, self.h._view_center = previous
                self.h._paint_image()
            else:
                self.h.fit_image()
            self.message("Przywrócono widok sprzed zbliżenia (A).")
            return "break"
        if self.drag:
            self.message("A: najpierw zakończ przeciąganie narożnika.")
            return "break"
        xy = self._canvas_hotkey_pointer(event)
        hovered = self.hit(*xy, badge=False) if xy is not None else None
        qualified = [o for o in scene["objects"]
                     if not o.get("post_nms_suppressed", False) and self._current_quad(o)]
        oid = hovered[0] if hovered else self.selected
        obj = next((o for o in qualified if o["object_id"] == oid), None)
        if obj is None and len(qualified) == 1:
            obj = qualified[0]
        quad = self._current_quad(obj) if obj is not None else None
        if not quad:
            self.message("A: wybierz ramkę (hover + S). Na zdjęciu jest kilka tablic.")
            return "break"
        try:
            try:
                self.c.update_idletasks()
            except (AttributeError, tk.TclError):
                pass
            iw, ih = self.h._image.size
            source_w, source_h = map(float, scene["image_size"])
            if not all((iw > 0, ih > 0, source_w > 0, source_h > 0)):
                raise ValueError("Brak rozmiaru źródła")
            xs = [float(p[0]) * iw / source_w for p in quad]
            ys = [float(p[1]) * ih / source_h for p in quad]
            if not all(math.isfinite(z) for z in xs + ys):
                raise ValueError("Nieskończone współrzędne")
            bx1, bx2, by1, by2 = min(xs), max(xs), min(ys), max(ys)
            bw, bh = bx2 - bx1, by2 - by1
            if bw < 1e-4 or bh < 1e-4:
                raise ValueError("Brak wymiarów ramki")
            pad_x = max(16.0, bw * .20)
            pad_y = max(16.0, bh * .25)
            left, right = max(0.0, bx1 - pad_x), min(iw, bx2 + pad_x)
            top, bottom = max(0.0, by1 - pad_y), min(ih, by2 + pad_y)
            cw, ch = self.c.winfo_width(), self.c.winfo_height()
            if cw < 80 or ch < 80:
                raise ValueError("Za mały canvas")
            scale = min(cw / max(1., right-left), ch / max(1.,bottom-top))
            fit = max(1e-8, min((cw - 16) / iw, (ch - 16) / ih))
            zoom = max(1.0, min(256.0, scale / fit))
            center = ((left + right) * .5, (top + bottom) * .5)
        except (TypeError, ValueError, IndexError, OverflowError, ZeroDivisionError):
            self.message("A: nie można dopasować tablicy. Sprawdź współrzędne jej narożników.")
            return "break"
        self.plate_fit_previous = (self.h._view_zoom, tuple(self.h._view_center))
        self.plate_fit_active = True
        self.plate_fit_gid = self.h.current_invocation
        self.h._view_zoom = zoom
        self.h._view_center = center
        self.h._paint_image()
        self.message("Dopasowano tablicę z marginesem jak w Z2. Ponowne A przywróci widok.")
        return "break"

    def show_crop(self):
        s=self._read()
        obj=next((o for o in s["objects"] if o["object_id"]==self.selected),None) if s else None
        if obj and obj["attempt_id"]:
            self.h._source_frame_keep_on_selection=s["image_entry"]
            self.h._multi_focus_attempt(obj["attempt_id"])
            self.h._show_crop_preview()

    def undo(self,redo=False):
        if not self.prepare_navigation() or not self.available():
            return "break"
        gid=self.h.current_invocation
        src=self.redo_stack if redo else self.undo_stack
        dst=self.undo_stack if redo else self.redo_stack
        stack=src.setdefault(gid,[])
        if stack:
            prior=copy.deepcopy(stack[-1])
            now=copy.deepcopy(self._read())
            def change():
                live=core.scene(self.h.session,gid)
                if prior["parents"]!=live["parents"] or prior["source_binding"]!=live["source_binding"]:
                    raise ValueError("Historia dotyczy innego źródła")
                prior["events"]=copy.deepcopy(live["events"])
                prior.update(checked=False,exclusion_reason="")
                core._store(self.h.session,gid,prior,"redo_canvas_edit" if redo else "undo_canvas_edit")
            if self._commit(change,"Ponowiono zmianę" if redo else "Cofnięto zmianę operatora",remember=False):
                stack.pop();dst.setdefault(gid,[]).append(now)
        return "break"

    def dispose(self):
        """Stop controller callbacks before the window and its Tcl commands die."""
        for name in ("entry_after", "refresh_after", "paint_after", "selection_release_after", "fit_release_after"):
            callback = getattr(self, name, None)
            if callback:
                try:
                    self.c.after_cancel(callback)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        self.paint_scheduled = False
        token = getattr(self, "_win_s_poll_id", None)
        if token is not None:
            try:
                self.c.after_cancel(token)
            except (AttributeError, tk.TclError):
                pass
            self._win_s_poll_id = None
        self._remove_shortcut_fallback()
        tag = getattr(self, "shortcut_tag", None)
        if tag:
            for widget, original in tuple(self.shortcut_original_tags.items()):
                try:
                    if tag in widget.bindtags():
                        widget.bindtags(original)
                except (tk.TclError, AttributeError):
                    pass
            for key in ("s", "S", "a", "A"):
                for action in ("KeyPress", "KeyRelease"):
                    try:
                        self.c.unbind_class(tag, "<" + action + "-" + key + ">")
                    except (tk.TclError, AttributeError):
                        pass
            self.shortcut_original_tags.clear()
            self.shortcut_tag = None

    def build_report_tab(self, tabs):
        self.report_host=CanvasResultsPanel(tabs,p=self.p)
        tabs.tab(1,text="Analiza historyczna")
        tabs.add(self.report_host,text="Canvas · wyniki")
        tabs.insert(1,self.report_host)
        # Keep the action's raised CTA styling; only the caption changes.
        self.h.science_toggle.configure(text="Tabela techniczna")

    def update_report(self):
        if not hasattr(self,"report_host") or self.h.session is None:
            return
        inv=self.inventory()
        self.update_header(inv)
        data = self.h.stats.get("canvas_review") or {}
        current = (data.get("review_revision") == self.h.session.review.review_revision
                   and data.get("source_archive_sha256") == self.h.session.review.source_archive_sha256)
        self.report_host.render(data if current else {}, inv, refreshing=not current)

    def _build_panel(self, right):
        p = self.p
        self.panel = tk.Frame(right, bg=p["bg"], padx=1, pady=3)
        self.panel.grid(row=0, column=0, sticky="new")
        ui_label(self.panel, "OCENA OBRAZU", p=p, bg=p["bg"], bold=True, size=10).pack(fill="x", pady=(0, 8))
        self.status = ui_label(self.panel, "Wczytywanie…", p=p, bg=p["blue_bg"], fg=p["blue"],
                               bold=True, wrap=self.sidebar_width - 48)
        self.status.pack(fill="x", ipady=6)
        # Explain the causal chain *before* presenting a confirmation action.
        # Shown only if this scene contains a trace-backed 2->1 NMS result.
        self.reconciliation_box = tk.Frame(self.panel, bg=p["surface"], padx=11, pady=11,
                                           highlightbackground=p["border"], highlightthickness=1)
        self.reconciliation_title = ui_label(self.reconciliation_box, "", p=p, bg=p["surface"],
                                             fg=p["blue"], bold=True, size=10,
                                             wrap=self.sidebar_width - 70)
        self.reconciliation_title.pack(fill="x", pady=(0, 7))
        self.reconciliation_body = ui_label(self.reconciliation_box, "", p=p, bg=p["surface"],
                                            fg=p["fg"], size=9,
                                            wrap=self.sidebar_width - 70)
        self.reconciliation_body.pack(fill="x")
        controls = tk.Frame(self.panel, bg=p["bg"], pady=7)
        controls.pack(fill="x")
        self.checked_var = tk.BooleanVar(value=False)
        self.excluded_var = tk.BooleanVar(value=False)
        options = dict(bg=p["bg"], fg=p["fg"], activebackground=p["bg"], activeforeground=p["fg"],
                       selectcolor=p["surface"], font=("Segoe UI", 10), anchor="w", bd=0,
                       highlightthickness=1, highlightbackground=p["bg"], highlightcolor=p["blue"])
        self.approve = tk.Checkbutton(controls, text="Sprawdziłem tablice, ramki i numery GT", variable=self.checked_var,
                                      command=self.toggle_checked, **options)
        self.approve.pack(fill="x")
        self.exclude = tk.Checkbutton(controls, text="Nie można ocenić całego obrazu", variable=self.excluded_var,
                                      command=self.toggle_excluded, **options)
        self.exclude.pack(fill="x", pady=(2, 0))
        ui_label(controls,
                 "Ta opcja wyłącza z oceny cały obraz, nie jedno wskazanie telefonu.",
                 p=p, bg=p["bg"], fg=p["muted"], size=9,
                 wrap=self.sidebar_width - 48).pack(fill="x", pady=(1, 3))
        self.reason_host = tk.Frame(controls, bg=p["bg"])
        ui_label(self.reason_host, "Przyczyna (opcjonalnie)", p=p, bg=p["bg"], size=9, fg=p["muted"]).pack(fill="x")
        self.reason_var = tk.StringVar(value="")
        self.reason_entry = tk.Entry(self.reason_host, textvariable=self.reason_var, font=("Segoe UI", 9),
                                    bg=p["surface"], fg=p["fg"], insertbackground=p["fg"], width=22)
        self.reason_entry.pack(fill="x", pady=(2, 4))
        self.reason_entry.bind("<FocusOut>", self.save_exclusion_reason)
        self.reason_entry.bind("<Return>", self.save_exclusion_reason)
        self.reason_entry.bindtags((str(self.reason_entry), self.reason_entry.winfo_class(), str(self.h.window)))
        self.reason_gid = ""
        counts = tk.Frame(self.panel, bg=p["bg"])
        counts.pack(fill="x", pady=(0, 6))
        counts.columnconfigure(0, weight=1, uniform="count")
        counts.columnconfigure(1, weight=1, uniform="count")
        self.tally_cards = {}
        for i, (key, title, tone) in enumerate((("expected", "Tablice", "blue"), ("mt", "Wstępne wskazania", "blue"),
                    ("missed", "Pominięte tablice", "amber"), ("false_positive", "Błędne wykrycia", "red"))):
            card = MetricCard(counts, title, p=p, tone=tone, compact=True)
            card.grid(row=i//2, column=i%2, sticky="nsew", padx=2, pady=3)
            self.tally_cards[key] = card
        self.tally = ui_label(self.panel, "", p=p, bg=p["bg"], fg=p["muted"],
                              size=9, wrap=self.sidebar_width - 48)
        self.tally.pack(fill="x", pady=(0, 7))
        # Important operator action: separate from informational headings.
        # A two-line label + wraplength survives narrow laptop layouts/DPI scaling.
        self.nms_action = self.make_action_button(self.reconciliation_box,
            "Popraw wcześniejszą ocenę: 2 → 1 wynik",
            self.accept_nms, primary=True, wraplength=self.sidebar_width - 90)
        self.nms_action.configure(pady=11, padx=12, font=("Segoe UI", 10, "bold"))
        self.nms_action.pack_forget()
        self.reconciliation_box.pack_forget()
        selected = tk.Frame(self.panel, bg=p["surface"], padx=9, pady=8,
                            highlightbackground=p["border"], highlightthickness=1)
        selected.pack(fill="x")
        ui_label(selected, "ZAZNACZENIE", p=p, size=9, fg=p["muted"], bold=True).pack(fill="x")
        self.selection = ui_label(selected, "", p=p, bold=True, wrap=self.sidebar_width - 72)
        self.selection.pack(fill="x", pady=(5, 3))
        self.selection_hint = ui_label(selected, "", p=p, size=9, fg=p["muted"],
                                      wrap=self.sidebar_width - 72)
        self.selection_hint.pack(fill="x")
        self.crop = self.make_action_button(selected, "Podgląd cropu MZ  →",
                                            self.show_crop, compact=True)
        self.crop.pack(fill="x", pady=(7, 0))
        self.help_section = Disclosure(self.panel, "Skróty i obsługa", p=p)
        self.help_section.pack(fill="x", pady=(10, 6))
        for key, text in (("D", "Nowa tablica: 4 punkty"), ("Klik lub S", "Zaznacz ramkę; S również odznacza"),
                          ("LPM", "Przeciągnij zaznaczony narożnik"),
                          ("R", "Usuń ręczną ramkę / cofnij korektę MT"),
                          ("T", "Pokaż lub ukryj granicę ROI (tylko widok)"),
                          ("N", "Przejdź do następnej tablicy"),
                          ("PPM", "Jedno kliknięcie na ramce: oznacz błąd lub cofnij"),
                          ("GT", "Kliknij dolny badge"), ("A · Q/E", "Zbliż tablicę · poprzedni/następny obraz"),
                          ("Rolka · F", "Zoom · dopasuj obraz"), ("Ctrl+Z/Y", "Cofnij / ponów zmianę"),
                          ("Esc", "Anuluj bieżącą edycję")):
            ui_label(self.help_section.body, key, p=p, bold=True, size=9, fg=p["blue"]).pack(fill="x", pady=(4, 0))
            ui_label(self.help_section.body, text, p=p, size=9,
                     wrap=self.sidebar_width - 82).pack(fill="x")
        self.metrics = ui_label(self.panel,
            "Wyniki telefonu pozostają w historii. „Poza oceną” nie znaczy "
            "„błędna tablica”. Zmiany operatora są zapisywane osobno.",
                                 p=p, bg=p["bg"], size=9, fg=p["muted"],
                                 wrap=self.sidebar_width - 48)
        self.metrics.pack(fill="x", pady=(3, 9))

    def leave_canvas(self, event=None):
        self.pointer_canvas = None
        self._s_hover_hit = None
        self.hover = ""
        # Selection survives leaving the canvas; pointer motion never owns it.

    def remove_selected(self, event=None):
        # Windows sends state=8 for normal hotkeys; only Ctrl inhibits R.
        if event is not None and getattr(event, "state", 0) & 4:
            return "break"
        if self.mode != "edit" or not self.selected:
            self.message("Najedź na ramkę, naciśnij S, a następnie R. Oryginał MT nie zostanie usunięty.")
            return "break"
        if not self.prepare_navigation() or not self.available():
            return "break"
        s = self._read()
        obj = next((o for o in s["objects"] if o["object_id"] == self.selected), None)
        if obj is None:
            return "break"
        oid, parent = obj["object_id"], obj["parent_id"]
        description = ("Cofnięto korektę do oryginału MT; GT zachowano" if parent else
                       "Usunięto ręczną ramkę z widoku i oceny; Ctrl+Z przywraca")
        if self._commit(lambda: core.remove_operator_geometry(self.h.session, self.h.current_invocation, oid), description):
            if not parent:
                self.selected = self.hover = ""
            self.sync(); self.refresh_tree(); self.request_overlay()
        return "break"

    def _sync_reconciliation_story(self, scene, tally, enabled):
        story = reconciliation_story(scene, tally)
        if not story:
            self.nms_action.pack_forget()
            self.reconciliation_box.pack_forget()
            return
        self.reconciliation_title.configure(text=story["title"])
        self.reconciliation_body.configure(text=story["body"])
        # Top of the sidebar: context, reason, consequences, action — in order.
        self.reconciliation_box.pack(fill="x", pady=(8, 6), after=self.status)
        if story["action"]:
            self.nms_action.configure(text=story["action"], state="normal" if enabled else "disabled")
            self.nms_action.pack(fill="x", pady=(9, 0))
        else:
            self.nms_action.pack_forget()

    def _confirm_reconciliation(self):
        """Explain the decision with explicit cancel/confirm actions, default cancel.

        Nothing is saved until the positive button is pressed; this dialog
        does not decide how many physical plates are present on the image.
        """
        p = self.p
        parent = self.h.window
        dialog = tk.Toplevel(parent)
        dialog.title("Dlaczego trzeba poprawić wcześniejszą ocenę?")
        dialog.transient(parent)
        dialog.configure(bg=p["bg"])
        dialog.resizable(True, True)
        content = tk.Frame(dialog, bg=p["bg"], padx=19, pady=16)
        content.pack(fill="both", expand=True)
        dialog_width = min(620, max(430, dialog.winfo_screenwidth()-100))
        wrap = dialog_width - 70
        ui_label(content, "Poprawa wcześniejszej oceny — decyzja operatora",
                 p=p, bg=p["bg"], fg=p["fg"], bold=True, size=12,
                 wrap=wrap).pack(fill="x", pady=(0, 11))
        steps = (
            ("1. Co wykonał telefon?",
             "Na jednej klatce zapisał dwa wstępne wskazania, a po filtrowaniu "
             "nakładających się ramek użył tylko jednego do rozpoznawania."),
            ("2. Dlaczego program prosi o Twoją decyzję?",
             "Stara ocena na komputerze potraktowała obydwa wskazania jak "
             "oddzielne tablice. Ponieważ zawiera wcześniejsze poprawki "
             "człowieka, nie wolno nam zmienić tej oceny bez Twojej zgody."),
            ("3. Co zmieni Twoje potwierdzenie?",
             "Do oceny wyników telefonu pozostanie jedno wskazanie. Drugie oraz "
             "jego wcześniejsze GT, poprawki i zdarzenia będą nadal w historii. "
             "Nie zostanie uznane za fałszywy alarm. Status sprawdzenia obrazu "
             "zostanie cofnięty do ponownej kontroli."),
            ("4. Czego potwierdzenie NIE rozstrzyga?",
             "Nie potwierdza, że na zdjęciu jest tylko jedna prawdziwa tablica. "
             "Po zmianie obejrzyj całe ROI; jeśli widzisz dodatkową tablicę, "
             "oznacz ją ręcznie (D). Sprawdź ramki i GT, a dopiero potem "
             "zaznacz sprawdzenie obrazu."),
        )
        for heading, body in steps:
            ui_label(content, heading, p=p, bg=p["bg"], fg=p["blue"],
                     bold=True, size=10, wrap=wrap).pack(fill="x", pady=(4, 2))
            ui_label(content, body, p=p, bg=p["bg"], fg=p["fg"],
                     size=10, wrap=wrap).pack(fill="x", pady=(0, 7))
        ui_label(content, "Czy poprawić zapis wcześniejszej oceny w opisany sposób?",
                 p=p, bg=p["bg"], fg=p["fg"], bold=True,
                 wrap=wrap).pack(fill="x", pady=(8, 11))
        buttons = tk.Frame(content, bg=p["bg"])
        buttons.pack(fill="x")
        choice = [False]
        def finish(value):
            choice[0] = bool(value)
            dialog.destroy()
        cancel = self.make_action_button(buttons, "Nie — wróć bez zmian", lambda: finish(False))
        cancel.pack(side="left", fill="x", expand=True, padx=(0, 6))
        accept = self.make_action_button(buttons, "Tak — popraw wcześniejszą ocenę",
                                         lambda: finish(True), primary=True)
        accept.pack(side="left", fill="x", expand=True, padx=(6, 0))
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dialog.bind("<Escape>", lambda event: finish(False))
        dialog.update_idletasks()
        width = max(dialog_width, dialog.winfo_reqwidth())
        height = min(dialog.winfo_reqheight(), max(520, dialog.winfo_screenheight()-70))
        x = parent.winfo_rootx() + max(0, (parent.winfo_width()-width)//2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height()-height)//2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.wait_visibility()
        dialog.grab_set()
        cancel.focus_set()  # Default action is always to leave the review unchanged.
        parent.wait_window(dialog)
        return choice[0]

    def accept_nms(self):
        if not self.prepare_navigation() or not self.available():
            return
        s = self._read()
        if not s or not s.get("_post_nms_pending"):
            return
        if not self._confirm_reconciliation():
            return
        self._commit(lambda: core.accept_post_nms_raw_only(self.h.session, self.h.current_invocation),
            "Poprawiono wcześniejszą ocenę. Drugie wstępne wskazanie zachowano "
            "w historii. Teraz sprawdź wszystkie prawdziwe tablice, ramki i GT "
            "przed zaznaczeniem obrazu jako sprawdzonego.")

    def toggle_checked(self):
        checked = bool(self.checked_var.get())
        if not self.prepare_navigation() or not self.available():
            self.sync(); return
        reason = self._read().get("exclusion_reason", "") if checked and self._read() else ""
        self._commit(lambda: core.set_scene_review_state(self.h.session, self.h.current_invocation,
                      checked=checked, exclusion_reason=reason),
                     "Zapisano stan sprawdzenia obrazu" if checked else "Cofnięto sprawdzenie obrazu")
        self.sync()

    def toggle_excluded(self):
        excluded = bool(self.excluded_var.get())
        if not self.prepare_navigation() or not self.available():
            self.sync(); return
        reason = (self.reason_var.get().strip() or "Operator oznaczył obraz jako niemożliwy do oceny") if excluded else ""
        self._commit(lambda: core.set_scene_review_state(self.h.session, self.h.current_invocation,
                      checked=True, exclusion_reason=reason),
                     "Obraz sprawdzony, ale nie do oceny" if excluded else "Przywrócono ocenialność; obraz nadal sprawdzony")
        self.sync()

    def _flush_exclusion_reason(self):
        if self.reason_gid != self.h.current_invocation or not self.excluded_var.get():
            return True
        scene = self._read()
        if not scene or not scene.get("exclusion_reason"):
            return True
        reason = self.reason_var.get().strip() or "Operator oznaczył obraz jako niemożliwy do oceny"
        if scene["exclusion_reason"] == reason:
            return True
        return bool(self._commit(lambda: core.set_scene_review_state(
            self.h.session, self.h.current_invocation, checked=True, exclusion_reason=reason),
            "Zapisano przyczynę wyłączenia obrazu"))

    def save_exclusion_reason(self, event=None):
        saved = self._flush_exclusion_reason()
        if saved and event is not None and getattr(event, "keysym", "") == "Return":
            self.c.focus_set()
        return "break"

    def _configure_tree(self):
        tree = self.h.subject_tree
        style = ttk.Style(self.h.window)
        style.configure("MobileReview.Observations.Treeview", background=self.p["surface"],
                        fieldbackground=self.p["surface"], foreground=self.p["fg"],
                        rowheight=35, font=("Segoe UI", 10, "bold"))
        # A strong selection remains visible after keyboard focus moves to Canvas.
        style.map("MobileReview.Observations.Treeview",
                  background=[("selected", "!focus", "#135481"),
                              ("selected", "#135481")],
                  foreground=[("selected", "!focus", "#FFFFFF"),
                              ("selected", "#FFFFFF")])
        tree.configure(style="MobileReview.Observations.Treeview", selectmode="browse")
        # One image = one task. Do not expose model candidates, raw-NMS entries,
        # duplicated source rows or the raw matrix of status abbreviations.
        # The underlying Treeview columns/values are retained for compatibility
        # with the report presenter, but none are displayed in this operator list.
        tree.configure(show="tree headings", displaycolumns=())
        tree.heading("#0", text="Obraz  ·  Co zrobić", anchor="w")
        tree.column("#0", width=self.left_width - 36, minwidth=240, stretch=True)
        for widget in tree.master.master.winfo_children():
            if isinstance(widget, tk.Label) and "MT: liczba tablic" in str(widget.cget("text")):
                widget.configure(
                    text="Wybierz obraz, obejrzyj wszystkie widoczne tablice, "
                         "sprawdź ramki i numery, a następnie potwierdź obraz. "
                         "Dane techniczne znajdziesz w raporcie.",
                    wraplength=self.left_width - 38)
        tree.tag_configure("canvas_error", background=self.p["red_bg"], foreground=self.p["red"])
        tree.tag_configure("canvas_pending", background=self.p["surface"], foreground=self.p["fg"])
        tree.tag_configure("canvas_ready", background=self.p["green_bg"], foreground=self.p["green"])
        tree.tag_configure("canvas_excluded", background=self.p["purple_bg"], foreground=self.p["purple"])
        # Fallback for Windows ttk themes dimming selections on inactive focus.
        tree.tag_configure("canvas_active", background="#135481", foreground="#FFFFFF")

    @staticmethod
    def _image_action(rows):
        """Human task, derived only from existing persisted review states."""
        if not rows:
            return "Brak obrazu", "canvas_excluded"
        if all(row["status"] == "EXCLUDED" for row in rows):
            return "Poza oceną", "canvas_excluded"
        if all(row["status"] == "READY" for row in rows):
            return "Gotowe", "canvas_ready"
        if any(row.get("scene") and row["scene"].get("_post_nms_pending") for row in rows):
            return "Wyjaśnij rozbieżność", "canvas_error"
        if any(row.get("scene") and row["scene"].get("checked")
               and row["cells"][-1] != "✓" for row in rows):
            return "Uzupełnij dane", "canvas_pending"
        if any(row.get("scene") is None for row in rows):
            return "Brak pełnego obrazu", "canvas_excluded"
        return "Do sprawdzenia", "canvas_pending"

    def inventory(self):
        key = (id(self.h.session), getattr(getattr(self.h.session, "review", None), "review_revision", -1))
        if key != self.inventory_key:
            self.inventory_data = build_inventory(self.h.session)
            self.inventory_key = key
        return self.inventory_data

    def refresh_tree(self):
        h = self.h
        if not h.session or not hasattr(h, "_subject_ids"):
            return
        inv = self.inventory()
        tree = h.subject_tree
        # Only a proven shared executed invocation permits hiding an alias.
        # The source session, review objects, GT and evaluation counts stay intact.
        linked = linked_measurement_rows(h.session, h._subject_ids, inv["groups"])
        previously_selected = tree.selection()
        desired = set()
        display_index = 0
        self.tree_refreshing = True
        try:
            for iid, key in h._subject_ids.items():
                if iid in linked:
                    continue
                display_index += 1
                gids = [gid for gid in subject_groups(h.session, key)
                        if gid in inv["groups"]]
                rows = [inv["groups"][gid] for gid in gids]
                cells = core.merge_review_cells(row["cells"] for row in rows)
                action, tag = self._image_action(rows)
                label = f"Obraz {display_index:02d}  ·  {action}"
                values = (f"{display_index:02d}",) + cells
                desired.add(iid)
                if tree.exists(iid):
                    if tree.parent(iid):
                        tree.move(iid, "", "end")
                    tree.item(iid, text=label, values=values, tags=(tag,), open=False)
                else:
                    tree.insert("", "end", iid=iid, text=label,
                                values=values, tags=(tag,), open=False)
                # Remove stale descendants from AKT66 or older trees. A
                # descendant represents a raw candidate, not another task.
                for cid in tuple(tree.get_children(iid)):
                    tree.delete(cid)
            for iid in tuple(tree.get_children("")):
                if iid not in desired:
                    tree.delete(iid)
            # There are deliberately no object/group targets in the image list.
            # Object editing continues via Canvas S / A and the right inspector.
            self.tree_targets = {}
            self.linked_tree_rows = linked
        finally:
            self.tree_refreshing = False
        h._schedule_status_pills()
        self.update_header(inv)
        if previously_selected:
            old = previously_selected[0]
            new = linked.get(old, (old, None))[0]
            if tree.exists(new) and tree.selection() != (new,):
                tree.selection_set(new)
        self.sync_tree_selection()

    def update_header(self, inv=None):
        inv = inv or self.inventory()
        self.h.progress_label.configure(text=(
            f"Sprawdzone obszary (wspólne liczone raz): {inv['inspected']}/{inv['total']}  ·  "
            f"gotowe do oceny: {inv['assessed']}  ·  "
            f"nie do oceny: {inv['excluded']}  ·  pozostało: {inv['remaining']}"))
        if hasattr(self.h, "form_status_label"):
            extra = f"  ·  braki danych po sprawdzeniu: {inv['incomplete']}" if inv["incomplete"] else ""
            extra += f"  ·  tylko podgląd: {inv['unavailable']}" if inv["unavailable"] else ""
            status = "Weryfikacja zatwierdzona" if self.h.session and self.h.session.review.review_status == "COMPLETED" else "Weryfikacja w toku"
            self.h.form_status_label.configure(text=f"{status}{extra}  ·  GT i korekty zapisują się automatycznie")

    def clear_tree_selection(self):
        """Explicit S-off/Escape only; never deletes rows or changes review data."""
        tree = self.h.subject_tree
        current = tree.selection()
        if current:
            tree.selection_remove(*current)
        tree.focus("")

    def sync_tree_selection(self):
        """Highlight the current image, never an internal MT/GT record.

        A programmatic highlight of the current image must not undo an active
        S-selected plate. select_tree_row handles that same-image event as noop.
        """
        if self.tree_refreshing or not hasattr(self.h, "_subject_ids"):
            return
        tree = self.h.subject_tree
        key = self.h.subject_key
        roots = set(tree.get_children(""))
        iid = next((i for i, subject in self.h._subject_ids.items()
                    if subject == key and i in roots), None)
        if iid is None:
            alias = next((i for i, subject in self.h._subject_ids.items()
                          if subject == key), None)
            if alias in self.linked_tree_rows:
                iid = self.linked_tree_rows[alias][0]
        if iid is None and self.h.current_invocation:
            iid = next((i for i, subject in self.h._subject_ids.items()
                        if i in roots and self.h.current_invocation in
                        subject_groups(self.h.session, subject)), None)
        previous_active = getattr(self, "_active_tree_iid", "")
        if previous_active != iid and previous_active and tree.exists(previous_active):
            oldtags=tuple(t for t in tree.item(previous_active, "tags") if t != "canvas_active")
            tree.item(previous_active, tags=oldtags)
        if iid and tree.exists(iid):
            tags=tuple(t for t in tree.item(iid,"tags") if t != "canvas_active")
            tree.item(iid, tags=tags+("canvas_active",))
            self._active_tree_iid = iid
            self.tree_branch = iid
            if tree.selection() != (iid,):
                tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)

    def select_tree_row(self, iid):
        if self.tree_refreshing:
            return True
        if iid in self.linked_tree_rows:
            # A legacy asynchronous selection event may reference an old row.
            # Never navigate to a hidden source alias or create a new GT task.
            return True
        if iid not in self.h._subject_ids:
            return True
        self.tree_branch = iid
        key = self.h._subject_ids[iid]
        if key == self.h.subject_key:
            # Tk fires selection events for programmatic highlights too. Do
            # not erase the currently edited plate/GT on such an event.
            return True
        if not self.prepare_navigation():
            self.sync_tree_selection()
            return True
        # The host now opens the selected image. The raw source IDs are still
        # available in h._subject_ids; no session content is mutated here.
        self.selected = self.hover = ""
        self.mode = "select"
        self.plate_fit_saved = None
        return False

    def next_pending(self):
        inv = self.inventory()
        tree = self.h.subject_tree
        roots = tuple(tree.get_children(""))
        for gid, item in inv["groups"].items():
            if item["status"] in ("READY", "EXCLUDED"):
                continue
            iid = next((iid for iid in roots
                        if gid in subject_groups(self.h.session, self.h._subject_ids[iid])), None)
            if iid is None:
                continue
            tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)
            self.h._select_subject()
            if gid != self.h.current_invocation:
                group = self.h.session.mt_invocations.get(gid)
                records = group.records if group else []
                aid = str(records[0].get("id") or records[0].get("attempt_id") or "") if records else ""
                if aid:
                    self.pending_tree_target = (gid, "")
                    self.h._multi_focus_attempt(aid)
            return
        self.message("Wszystkie dostępne obrazy zostały sprawdzone lub wyłączone z oceny.")

    def route_scroll(self, event):
        """Handle a Windows wheel delivered to the focused image over a side panel."""
        try:
            x,y=self.h.window.winfo_pointerxy()
            areas=[(self.h.review_sidebar_scroll,self.h._on_sidebar_wheel),
                   (self.report_host.canvas,self.report_host.wheel)]
            if hasattr(self.h,"science_dashboard"):
                areas.append((self.h.science_dashboard.canvas,self.h.science_dashboard._wheel))
            for canvas,handler in areas:
                if (canvas.winfo_ismapped() and canvas.winfo_rootx()<=x<canvas.winfo_rootx()+canvas.winfo_width()
                        and canvas.winfo_rooty()<=y<canvas.winfo_rooty()+canvas.winfo_height()):
                    return handler(event)
        except (tk.TclError,AttributeError):
            pass
        return None
