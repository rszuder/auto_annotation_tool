#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Window recovery helpers for the main Tk application."""

from ..config import logger


def close_floating_overlays_for_window_state(app):
    closer = getattr(app, "_close_menu_dropdown", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass

    hide_tooltip = getattr(app, "_hide_simple_tooltip", None)
    if callable(hide_tooltip):
        try:
            hide_tooltip()
        except Exception:
            pass


def release_window_grabs_for_recovery(app):
    seen = set()
    candidates = []
    try:
        current_grab = app.root.grab_current()
    except Exception:
        current_grab = None
    if current_grab is not None:
        candidates.append(current_grab)
    candidates.extend(
        [
            app.root,
            getattr(app, "startup_overlay_window", None),
            getattr(app, "startup_overlay_frame", None),
            getattr(app, "help_overlay_frame", None),
            getattr(app, "_global_terminal_window", None),
        ]
    )
    try:
        candidates.extend(list(app.root.winfo_children()))
    except Exception:
        pass

    for widget in candidates:
        if widget is None:
            continue
        key = str(widget)
        if key in seen:
            continue
        seen.add(key)
        try:
            widget.grab_release()
        except Exception:
            pass

    try:
        app.root.grab_release()
    except Exception:
        pass


def release_preview_fullscreens_for_recovery(app):
    for tab in list(app._iter_loaded_tabs()):
        try:
            if bool(getattr(tab, "_preview_fullscreen_active", False)):
                exit_fullscreen = getattr(tab, "_set_preview_fullscreen", None)
                if callable(exit_fullscreen):
                    exit_fullscreen(False)
        except Exception as e:
            logger.debug(f"Nie udało się zamknąć fullscreen preview podczas recovery okna: {e}")


def on_root_unmap(app, event=None):
    if getattr(event, "widget", None) is not app.root:
        return None
    try:
        root_state = str(app.root.state())
    except Exception:
        root_state = ""
    if root_state != "iconic":
        return None
    app._window_restore_pending = True
    close_floating_overlays_for_window_state(app)
    release_window_grabs_for_recovery(app)
    try:
        if bool(getattr(app, "_help_overlay_forced_visible", False)):
            app.hide_context_help_overlay()
    except Exception:
        pass
    release_preview_fullscreens_for_recovery(app)
    return None


def on_root_map(app, event=None):
    if getattr(event, "widget", None) is not app.root:
        return None
    app._window_restore_pending = True
    schedule_root_recovery(app, delay_ms=60, reset_attempts=True)
    return None


def on_root_visibility(app, event=None):
    if getattr(event, "widget", None) is not app.root:
        return None
    if not bool(getattr(app, "_window_restore_pending", False)) and int(getattr(app, "_window_restore_attempts", 0) or 0) <= 0:
        return None
    schedule_root_recovery(app, delay_ms=40)
    return None


def on_root_focus_in(app, event=None):
    if getattr(event, "widget", None) is not app.root:
        return None
    if not bool(getattr(app, "_window_restore_pending", False)) and int(getattr(app, "_window_restore_attempts", 0) or 0) <= 0:
        return None
    schedule_root_recovery(app, delay_ms=30)
    return None


def schedule_root_recovery(app, delay_ms: int = 60, *, reset_attempts: bool = False):
    if reset_attempts:
        app._window_restore_attempts = 0
    try:
        if app._window_restore_after_id is not None:
            app.root.after_cancel(app._window_restore_after_id)
    except Exception:
        pass
    try:
        app._window_restore_after_id = app.root.after(max(0, int(delay_ms)), lambda: recover_root_after_map(app))
    except Exception:
        app._window_restore_after_id = None
        recover_root_after_map(app)


def recover_root_after_map(app):
    app._window_restore_after_id = None
    try:
        root_state = str(app.root.state())
    except Exception:
        root_state = ""
    if root_state == "iconic":
        close_floating_overlays_for_window_state(app)
        app._window_restore_attempts = int(getattr(app, "_window_restore_attempts", 0) or 0) + 1
        if app._window_restore_attempts <= 24:
            delay_ms = min(900, 90 + (app._window_restore_attempts * 45))
            schedule_root_recovery(app, delay_ms=delay_ms)
        return
    app._window_restore_attempts = 0
    app._window_restore_pending = False

    release_window_grabs_for_recovery(app)
    try:
        if bool(getattr(app, "_help_overlay_forced_visible", False)):
            app.hide_context_help_overlay()
    except Exception:
        pass

    try:
        app.root.deiconify()
    except Exception:
        pass

    try:
        app.root.lift()
    except Exception:
        pass

    try:
        if str(app.root.tk.call("tk", "windowingsystem")).lower() == "win32":
            app.root.attributes("-topmost", True)
            try:
                if app._window_restore_topmost_after_id is not None:
                    app.root.after_cancel(app._window_restore_topmost_after_id)
            except Exception:
                pass
            app._window_restore_topmost_after_id = app.root.after(
                180,
                lambda: app.root.attributes("-topmost", False),
            )
    except Exception:
        pass

    try:
        app.root.focus_force()
    except Exception:
        try:
            app.root.focus_set()
        except Exception:
            pass
