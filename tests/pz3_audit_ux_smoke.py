"""Exercise the 10-image handoff scenario through the real audit dialog."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_annotation_tool.gui.pz3_audit_resolution_dialog import ParticipantAuditMatrixDialog
from auto_annotation_tool.registry.participant_pool_audit import STATUS_DEPENDENT, STATUS_SUSPECT, STATUS_UNKNOWN
from test_pz3_ingest_integration import PZ3IngestIntegrationTests
from pz3_gui_capture import capture_window

real_show = ParticipantAuditMatrixDialog.show
case = PZ3IngestIntegrationTests("test_mixed_folder_adds_clean_and_updates_actual_table")
case.setUp()
failures = []
try:
    from PIL import Image
    paths = [case.f.image(f"IMG_{i+101:03d}.png", seed=1001+i) for i in range(5)]
    for number in (1, 2):
        path = case.f.sources / f"IMG_{number+200:03d}.png"
        path.write_bytes(case.f.references[f"M{number}"].read_bytes())
        paths.append(path)
    for number in (1, 2):
        path = case.f.sources / f"IMG_{number+300:03d}.bmp"
        with Image.open(case.f.references[f"M{number}"]) as picture:
            picture.save(path)
        paths.append(path)
    unknown = case.f.sources / "IMG_401.png"
    unknown.write_bytes(b"unreadable image")
    paths.append(unknown)
    case.root.geometry("1240x900+20+20")
    case.root.deiconify()
    case.root.update()

    def interactive_show(dialog):
        def interact():
            try:
                assert len(dialog.tree.get_children()) == 10
                assert dialog.report.clean_count == 5
                assert dialog.report.dependent_count == 2
                assert dialog.report.suspect_count == 2
                assert dialog.report.unknown_count == 1
                capture_window(dialog.window, "output/pz3_ux_audit_initial.png")
                for status, count in ((STATUS_DEPENDENT, 2), (STATUS_UNKNOWN, 1), (STATUS_SUSPECT, 2)):
                    dialog.filter_var.set(status)
                    dialog._populate()
                    dialog.window.update()
                    assert len(dialog.tree.get_children()) == count
                first, second = dialog.tree.get_children()
                dialog.tree.selection_set(first)
                dialog._select()
                dialog.accept_button.invoke()
                dialog.tree.selection_set(second)
                dialog._select()
                dialog.reject_button.invoke()
                assert len(dialog.resolution().accepted_paths) == 6
                assert len(dialog.resolution().rejected_paths) == 4
                assert str(dialog.apply_button["state"]) == "normal"
                dialog.filter_var.set("all")
                dialog._populate()
                dialog.window.update()
                capture_window(dialog.window, "output/pz3_ux_audit_resolved.png")
                dialog.apply_button.invoke()
            except Exception as exc:
                failures.append(repr(exc))
                dialog._cancel()
        dialog.window.after(150, interact)
        return real_show(dialog)

    with patch.object(ParticipantAuditMatrixDialog, "show", new=interactive_show):
        assert case.ingest(paths) == 6, failures
    assert not failures, failures
    case.root.update()
    assert "✓ AKTUALNY" in case.panel._layout.summary_var.get()
    assert "Ręcznie zweryfikowane: 1" in case.panel._layout.summary_var.get()
    capture_window(case.root, "output/pz3_ux_panel_current.png")
    case.errors.assert_not_called()
    for method in ("askyesno", "askyesnocancel", "askokcancel", "showwarning"):
        getattr(case.messages, method).assert_not_called()
    history = case.f.repo.list_evaluation_track_audits(case.f.track)
    assert len(history) == 1
    saved = case.f.repo.get_evaluation_track_audit(history[0]["audit_id"])
    assert len(saved["decisions"]) == 10
    assert len(case.f.service.list_members(case.f.track)) == 6
    assert not case.callback_errors, case.callback_errors
    print("SMOKE OK: 10 diagnosed, 6 added/displayed, decisions persisted in SQLite, no follow-up questions.")
finally:
    case.doCleanups()

