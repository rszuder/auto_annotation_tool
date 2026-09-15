"""Smoke for explicit PZ3 exit, repeated comparison and entry to another sealed track."""
import copy
import json
from pathlib import Path
import time
from unittest.mock import patch
import xml.etree.ElementTree as ET

from pz3_gui_capture import capture_window
from auto_annotation_tool.gui import z4_analysis_ranking as ranking
from auto_annotation_tool.gui.pz3_comparison import comparison_context
from auto_annotation_tool.registry.experiment_gt_workspace import prepare_gt_workspace, publish_working_gt


def _widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _widgets(child)


def _button(dialog, label):
    return next(widget for widget in _widgets(dialog)
                if "text" in widget.keys() and str(widget.cget("text")) == label)


def _has_advanced(dialog):
    return any("text" in widget.keys() and str(widget.cget("text")) == "Zaawansowane"
               and widget.winfo_ismapped() for widget in _widgets(dialog))


def _exit_button(dialog):
    return next(widget for widget in _widgets(dialog)
                if "text" in widget.keys() and str(widget.cget("text")) == "Wróć do zwykłego rankingu")


def _result_count(fixture, track):
    with fixture.repo.database.read_connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM experiment_results r JOIN experiments e "
            "ON e.experiment_id=r.experiment_id WHERE e.track_id=?", (track,)
        ).fetchone()[0]


def exercise_scope_lifecycle(host, panel, fixture, settle):
    context_a = copy.deepcopy(comparison_context(host))
    track_a = context_a["track_id"]
    seal_path = fixture.workspace / fixture.service.get_track(track_a)["relative_path"] / "seal.json"
    seal_a = seal_path.read_bytes()
    participants_a = fixture.audit.load_participants(track_a)
    before_repeat = _result_count(fixture, track_a)

    # Closing the result window and refreshing do not end a controlled session.
    host._ranking_results_modal_close()
    host._load_ranking()
    assert comparison_context(host) == context_a
    ranking._open_ranking_results_modal(host)
    settle()
    assert comparison_context(host) == context_a
    assert not _has_advanced(host._ranking_results_modal)
    capture_window(host._ranking_results_modal, "output/pz3_scope_lifecycle_controlled.png")

    host.rank_is_running = True
    try:
        with patch.object(ranking.messagebox, "showwarning") as refused:
            _exit_button(host._ranking_results_modal).invoke()
            refused.assert_called_once()
        assert comparison_context(host) == context_a
    finally:
        host.rank_is_running = False

    # The enclosing smoke supplies deterministic ranking predictions.
    host._run_ranking_v2()
    deadline = time.monotonic() + 60
    while host.rank_is_running and time.monotonic() < deadline:
        settle()
    assert not host.rank_is_running
    settle()
    assert comparison_context(host) == context_a
    after_repeat = _result_count(fixture, track_a)
    assert after_repeat == before_repeat + len(context_a["model_ids"])

    host.rank_cancel_requested = True
    try:
        with patch.object(panel, "_require_current_track", return_value="TRACK-CANCEL-PROBE"), \
             patch.object(panel, "_show_error") as refused, \
             patch("auto_annotation_tool.gui.pz3_comparison.resolve_comparison") as resolve:
            panel.btn_compare.invoke()
            refused.assert_called_once()
            resolve.assert_not_called()
        assert comparison_context(host) == context_a
        assert host.rank_data_dir.get() == context_a["reference_path"]
    finally:
        host.rank_cancel_requested = False

    _exit_button(host._ranking_results_modal).invoke()
    settle()
    assert comparison_context(host) is None
    assert not host.rank_data_dir.get()
    assert "eksperymentalne" not in host._ranking_results_modal.title()
    assert _has_advanced(host._ranking_results_modal)
    capture_window(host._ranking_results_modal, "output/pz3_scope_lifecycle_regular.png")

    # Both ordinary selectors really open again.
    for open_selector, attr in (
        (host._open_ranking_track_modal, "_ranking_track_modal"),
        (host._open_ranking_participants_modal, "_ranking_participants_modal"),
        (host._open_ranking_advanced_modal, "_rank_advanced_modal"),
    ):
        open_selector()
        settle()
        selector = getattr(host, attr)
        assert selector is not None and selector.winfo_exists()
        selector.tk.call(selector.protocol("WM_DELETE_WINDOW"))
        settle()
    assert seal_path.read_bytes() == seal_a
    assert fixture.service.verify_integrity(track_a).ok
    assert fixture.audit.load_participants(track_a) == participants_a
    assert _result_count(fixture, track_a) == after_repeat

    host._open_ranking_advanced_modal()
    stale_advanced = host._rank_advanced_modal
    settle()

    # A different sealed fixture must replace all track-specific context.
    service = fixture.service
    track_b = service.create_draft(name="Lifecycle Track B", target="plate", purpose="ranking")
    fixture.audit.save_participants(track_b, context_a["model_ids"])
    image = fixture.image("TRACK_B_001.png", seed=2900)
    report = fixture.audit.audit_paths(track_b, [image])
    service.add_member(track_b, image)
    fixture.audit.record_ingested_report(track_b, report, [image])
    gt_context = prepare_gt_workspace(service, track_b)
    xml = Path(gt_context["annotation_path"])
    tree = ET.parse(xml)
    ET.SubElement(tree.getroot().find("image"), "polygon", label="plate", points="10,10;80,10;80,40;10,40")
    tree.write(xml, encoding="utf-8", xml_declaration=True)
    publish_working_gt(service, track_b, xml)
    service.deactivate_z2_context(track_id=track_b)
    service.verify(track_b, manual_gt_complete=True)
    service.attest_independent_acquisition(track_b, source_pool="synthetic_lifecycle_smoke")
    service.seal(track_b)
    panel.refresh_tracks(select_track_id=track_b)
    with patch.object(panel, "_show_error", side_effect=lambda title, exc: (_ for _ in ()).throw(exc)):
        panel.btn_compare.invoke()
    settle()
    context_b = comparison_context(host)
    assert context_b["track_id"] == track_b
    assert context_b["reference_path"] != context_a["reference_path"]
    assert host.rank_data_dir.get() == context_b["reference_path"]
    assert "Lifecycle Track B" in host._ranking_results_modal.title()
    assert not _has_advanced(host._ranking_results_modal)
    with patch.object(ranking.messagebox, "showinfo") as refused:
        _button(stale_advanced, "[ TOR ] Zastosuj wybrany tor").invoke()
        refused.assert_called_once()
    assert host.rank_data_dir.get() == context_b["reference_path"]
    stale_advanced.tk.call(stale_advanced.protocol("WM_DELETE_WINDOW"))
    settle()
    rows = host.rank_tree.get_children()
    assert len(rows) == len(context_b["model_ids"])
    assert all("czeka na test" in host.rank_tree.item(row, "values") for row in rows)
    assert _result_count(fixture, track_b) == 0
    assert _result_count(fixture, track_a) == after_repeat
    assert service.verify_integrity(track_a).ok and service.verify_integrity(track_b).ok
    capture_window(host._ranking_results_modal, "output/pz3_scope_lifecycle_track_b.png")
    Path("output/pz3_scope_lifecycle_smoke.json").write_text(
        json.dumps(dict(track_a=track_a, track_b=track_b, results_before_repeat=before_repeat,
                        results_after_repeat=after_repeat, exit_preserved_seal=True,
                        ordinary_selectors_opened=True, reentry_passed=True,
                        advanced_locked_in_pz3=True, stale_advanced_apply_blocked=True,
                        reentry_blocked_during_cancel=True), indent=2),
        encoding="utf-8",
    )
    print("LIFECYCLE PASS: repeat and close retain PZ3, busy exit refused, explicit exit opens ordinary selectors, Track B replaces Track A", flush=True)
