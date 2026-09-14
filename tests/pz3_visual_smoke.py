import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_pz3_ingest_integration import PZ3IngestIntegrationTests
from auto_annotation_tool.gui.source_filename_review_dialog import _SourceFilenameReviewDialog
from auto_annotation_tool.gui.pz3_participant_audit import ParticipantSelectionDialog
from pz3_gui_capture import capture_window

case = PZ3IngestIntegrationTests("test_mixed_folder_adds_clean_and_updates_actual_table")
case.setUp()
try:
    case.root.geometry("1200x850+30+30")
    case.root.deiconify()
    case.root.update()
    case.ingest(case.f.mixed())
    case.root.update()
    capture_window(case.root, "output/pz3_smoke_panel.png")

    directory = Path(case.temp.name) / "review"
    directory.mkdir()
    original = next(Path("Workspace/1_raw_images/sample_1000").glob("*.jpg"))
    first = directory / "bad1.jpg"
    second = directory / "bad2.jpg"
    shutil.copy2(original, first)
    shutil.copy2(original, second)
    dialog = _SourceFilenameReviewDialog(case.root, directory, recursive=False, title="Podgląd i korekta nazw — PZ3")
    dialog.window.update()
    dialog.tree.selection_set(str(first))
    dialog.tree.focus(str(first))
    dialog._begin_inline_edit()
    dialog._edit_entry.delete(0, "end")
    dialog._edit_entry.insert(0, "IMG_004.jpg")
    dialog._commit_inline_edit()
    dialog.window.update()
    capture_window(dialog.window, "output/pz3_smoke_names.png")
    dialog._cancel()

    selector = ParticipantSelectionDialog(
        case.root, models=case.panel.participant_audit.list_eligible_models("plate"),
        selected_ids={"M1", "M2"}, track_name="PZ3 integration",
        on_refresh=lambda: case.panel._refresh_participant_model_registry("plate"))
    selector.window.update()
    capture_window(selector.window, "output/pz3_smoke_models.png")
    selector._cancel()
    case.root.update()
    assert not case.callback_errors, case.callback_errors
    print(json.dumps({"smoke": "passed", "screenshots": [
        "output/pz3_smoke_panel.png", "output/pz3_smoke_names.png", "output/pz3_smoke_models.png"
    ]}))
finally:
    case.doCleanups()

