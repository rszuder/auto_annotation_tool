"""Native review workflow against synthetic Android-contract bundles, isolated writes."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(errors="backslashreplace")
import ctypes
import json
import os
import threading
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab

from test_mobile_human_review import make_bundle, attempt
from auto_annotation_tool.config import CONFIG
from auto_annotation_tool.gui.app_theme_definitions import get_theme_palette, THEME_DEFINITIONS
from auto_annotation_tool.gui.app_style_setup import setup_style
from auto_annotation_tool.gui.z4_mobile_report_browser import MobileReportBrowser
from auto_annotation_tool.ranking.mobile_package_experiments import MobilePackageExperimentStore, read_mobile_report_bundle, _file_sha256

OUT = Path(__file__).resolve().parents[1] / "output/mobile_sample_review_audit"
OUT.mkdir(parents=True, exist_ok=True)


def guard(event, args):
    if event == "open":
        path, mode, flags = args
        if not isinstance(path, (str, bytes)) or not isinstance(flags, int): return
        if not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND): return
    elif event in {"os.remove", "os.rmdir", "os.mkdir"}:
        path = args[0]
        if event == "os.mkdir" and Path(path).is_dir(): return
    elif event == "os.rename":
        for path in args[:2]:
            if not Path(path).resolve().is_relative_to(OUT): raise PermissionError(str(path))
        return
    else: return
    if isinstance(path, bytes): path = path.decode()
    if not Path(path).resolve().is_relative_to(OUT): raise PermissionError(str(path))


sys.addaudithook(guard)
errors, records = [], []
root = tk.Tk()
root.withdraw()
finished = threading.Event()
def watchdog():
    if not finished.wait(150):
        print("PROBE TIMEOUT", flush=True)
        os._exit(2)
threading.Thread(target=watchdog, daemon=True).start()


def exception(*args):
    detail = "".join(traceback.format_exception(*args))
    errors.append(detail)
    print(detail, flush=True)
root.report_callback_exception = exception


def pump(ms=80):
    done = tk.BooleanVar(root, False)
    root.after(ms, lambda: done.set(True))
    root.wait_variable(done)


def wait_for(predicate):
    for _ in range(180):
        pump(60)
        if predicate(): return
    raise AssertionError("Timed out waiting for review UI")


def capture(window, name):
    window.lift()
    pump(200)
    ancestor = ctypes.windll.user32.GetAncestor
    ancestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    ancestor.restype = ctypes.c_void_p
    hwnd = ancestor(window.winfo_id(), 2)
    redraw = ctypes.windll.user32.RedrawWindow
    redraw.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    redraw(hwnd, None, None, 0x181)
    pump(180)
    ImageGrab.grab(window=hwnd).save(OUT / f"{name}.png")


def run():
    try:
        store = MobilePackageExperimentStore(OUT / "ranking")
        rows = [attempt("a1"), attempt("a2", prediction="WI12B4A"),
                attempt("a3", prediction=""), attempt("a4", status="NO_DETECTION", prediction="")]
        samples = [dict(capture_id=f"c{i}", session_id="s", subject_key="s/sg-1/entity-1", attempt_id=f"a{i}") for i in (1, 2, 3)]
        source = make_bundle(OUT / "new.alprsession", attempts=rows, samples=samples, state="PARTIAL", image_text="WI1234A")
        source_hash = _file_sha256(source)
        bundle = read_mobile_report_bundle(source)
        store.add_report(bundle.report)
        app = SimpleNamespace(root=root, palette=get_theme_palette("dark_graphite"), themes=THEME_DEFINITIONS,
                              current_theme_key="dark_graphite", style=ttk.Style(root), _ensure_horizontal_scale_style_assets=lambda: None)
        app.get_list_selection_colors = lambda: (app.palette["selection_bg"], app.palette["selection_fg"])
        app._get_scrollbar_colors = lambda **kwargs: (app.palette["scrollbar_track"], app.palette["scrollbar_thumb"], app.palette["scrollbar_thumb_hover"])
        setup_style(app, "dark_graphite")
        owner = SimpleNamespace(app=app, frame=root)
        with patch.object(CONFIG, "DIR_7_RANKINGS_MOBILE_PACKAGES", OUT / "ranking"), \
                patch("auto_annotation_tool.gui.z4_mobile_report_browser.MobilePackageExperimentStore", return_value=store):
            browser = MobileReportBrowser(owner)
            browser.bundle_by_report_id[bundle.report.report_id] = bundle
            pump(150)
            browser._show_report(bundle.report, bundle)
            assert str(browser.btn_review_samples["state"]) == "normal"
            browser.btn_review_samples.invoke()
            panel = browser._sample_review
            wait_for(lambda: panel.session is not None and bool(panel.subject_key) and panel.current_record is not None)
            assert "PARTIAL" in panel.notice_label.cget("text")
            panel.gt_var.set("WI1234A")
            # A decision clicked before the debounce must preserve the typed GT.
            panel.annotate({"plate_visibility": "visible", "is_plate": True})
            wait_for(lambda: panel.session.review.review_revision > 0 and not panel._saving)
            assert panel.session.sidecar_path.exists()
            def select_record(kind, key):
                iid = next(iid for iid, value in panel._record_ids.items() if value == (kind, key))
                panel.record_tree.selection_set(iid)
                wait_for(lambda: panel.current_record == (kind, key))
            for row in rows:
                select_record("attempt", row["attempt_id"])
                panel.annotate({"plate_visibility": "visible", "is_plate": True, "evaluable": True})
                wait_for(lambda: not panel._saving)
            select_record("sample", "c2")
            wait_for(lambda: panel._image is not None)
            assert "błędnie rozpoznane: 1" in panel.alignment_label.cget("text")
            capture(panel.window, "new_partial_review")
            assert panel.canvas.winfo_height() >= 120
            assert panel.record_tree.winfo_rooty() + panel.record_tree.winfo_height() < panel.window.winfo_rooty() + panel.window.winfo_height() - 22
            panel.complete()
            wait_for(lambda: not panel._saving)
            assert panel.session.review.review_status == "COMPLETED", panel.status_var.get()
            assert panel.stats["summary"]["exact_reads"] == 1
            assert panel.stats["summary"]["incorrect_reads"] == 1
            assert panel.stats["summary"]["no_reads"] == 1
            assert panel.stats["summary"]["mt_no_detections"] == 1
            with patch("auto_annotation_tool.gui.z4_mobile_sample_review.filedialog.askdirectory", return_value=str(OUT / "export")):
                panel.export()
            wait_for(lambda: not panel._saving)
            assert (OUT / "export/summary.csv").exists()
            revision = panel.session.review.review_revision
            panel.close()
            pump(150)
            browser.open_sample_review()
            reopened = browser._sample_review
            try:
                wait_for(lambda: reopened.session is not None)
            except AssertionError:
                print("REOPEN ERROR:", reopened.status_var.get(), flush=True)
                raise
            assert reopened.session.review.review_status == "COMPLETED"
            assert reopened.session.review.review_revision == revision
            assert _file_sha256(source) == source_hash
            records.append({"new_bundle": True, "autosave": True, "completed": True, "export": True, "reopen": True, "source_unchanged": True})
            reopened.close()
            pump(120)
            old_path = make_bundle(OUT / "old.alprsession", samples=[dict(capture_id="old", track_id=7, prediction="WI1234A")], image_text="WI1234A")
            old = read_mobile_report_bundle(old_path)
            store.add_report(old.report)
            browser.palette = get_theme_palette("light_visual_cs")
            setup_style(app, "light_visual_cs")
            browser._show_report(old.report, old)
            browser.open_sample_review()
            legacy = browser._sample_review
            wait_for(lambda: legacy.session is not None and bool(legacy.subject_key))
            assert not legacy.session.attempts_available
            assert "pełnego rejestru prób MT" in legacy.notice_label.cget("text")
            capture(legacy.window, "legacy_review")
            legacy.exclude_subject()
            wait_for(lambda: not legacy._saving)
            legacy.complete()
            wait_for(lambda: not legacy._saving)
            assert legacy.session.review.review_status == "COMPLETED"
            legacy.gt_var.set("WI1234A")
            browser._request_close()
            wait_for(lambda: legacy._closed)
            assert legacy.session.review.subjects[legacy.subject_key]["ground_truth"] == "WI1234A"
            records.append({"legacy_crop_only": True, "not_evaluable": True, "parent_close_preserves_gt_draft": True})
    except BaseException:
        exception(*sys.exc_info())
    finally:
        (OUT / "results.json").write_text(json.dumps({"records": records, "errors": errors}, indent=2), encoding="utf-8")
        finished.set()
        root.destroy()
root.after(0, run)
root.mainloop()
sys.exit(1 if errors else 0)
