from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

import pytest

from auto_annotation_tool.gui import z4_mobile_export_locations as locations


@pytest.fixture(scope="module")
def root():
    window = tk.Tk()
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def panel(root):
    widget = locations.MobileExportSourceLocations(
        root, bg="#252526", fg="#f3f3f3", muted="#c7c7c7", accent="#4f8de3",
    )
    yield widget
    widget.destroy()


def make_candidate(tmp_path, name):
    project = tmp_path / name
    model = project / "train" / "weights" / "best.pt"
    dataset = project / "dataset" / "data.yaml"
    model.parent.mkdir(parents=True)
    dataset.parent.mkdir(parents=True)
    model.write_bytes(b"test checkpoint")
    dataset.write_text("names: [plate]\n", encoding="utf-8")
    return {"best_weights": model, "dataset_path": str(dataset)}


def test_sources_use_selected_checkpoint_and_dataset_not_base_or_copy(tmp_path):
    candidate = make_candidate(tmp_path, "przeniesiony projekt")
    candidate.update(base_model="yolo26n.pt", alternate_paths=[str(tmp_path / "copy.pt")],
                     run=SimpleNamespace(dataset_path=str(tmp_path / "old_dataset")))
    assert locations.candidate_source_paths(candidate) == {
        "model": candidate["best_weights"], "dataset": Path(candidate["dataset_path"]),
    }


@pytest.mark.parametrize("run", [{"dataset_path": "Workspace/dataset/data.yaml"},
                                 SimpleNamespace(dataset_path="Workspace/dataset/data.yaml")])
def test_run_fallback_and_relative_paths_follow_export_working_directory(tmp_path, monkeypatch, run):
    monkeypatch.chdir(tmp_path)
    paths = locations.candidate_source_paths({"best_weights": "weights/best.pt", "run": run})
    assert paths["model"] == tmp_path / "weights/best.pt"
    assert paths["dataset"] == tmp_path / "Workspace/dataset/data.yaml"
    assert locations.candidate_source_paths(None) == {"model": None, "dataset": None}


def test_selection_replaces_visible_paths_and_both_open_actions(panel, tmp_path):
    first = make_candidate(tmp_path, "pierwszy")
    second = make_candidate(tmp_path, "drugi & zażółć")
    panel.set_candidate(first)
    panel.set_candidate(second)
    with patch.object(locations, "reveal_source_path") as reveal:
        for key, field in (("model", "best_weights"), ("dataset", "dataset_path")):
            assert panel.path_labels[key]["text"] == str(second[field])
            panel.open_buttons[key].invoke()
            reveal.assert_called_with(Path(second[field]))
            panel.copy_buttons[key].invoke()
            assert panel.clipboard_get() == str(second[field])


def test_unknown_and_missing_sources_do_not_keep_previous_actions(panel, tmp_path):
    panel.set_candidate(make_candidate(tmp_path, "known"))
    missing = tmp_path / "deleted" / "best.pt"
    panel.set_candidate({"best_weights": missing})
    assert panel.path_labels["model"]["text"] == str(missing)
    assert panel.open_buttons["model"]["text"] == "Brak na dysku"
    assert panel.path_labels["dataset"]["text"] == "Brak ścieżki w metadanych"
    assert panel.copy_buttons["dataset"].instate(["disabled"])
    with patch.object(locations, "reveal_source_path") as reveal:
        panel.open_buttons["model"].invoke()
        panel.open_buttons["dataset"].invoke()
        reveal.assert_not_called()
    panel.set_candidate(None)
    assert all(button.instate(["disabled"]) for button in panel.open_buttons.values())


def test_dataset_directory_can_be_opened(panel, tmp_path):
    panel.set_candidate({"dataset_path": tmp_path})
    assert panel.open_buttons["dataset"]["text"] == "Otwórz folder"
    assert not panel.open_buttons["dataset"].instate(["disabled"])


@pytest.mark.parametrize("filename", ["best & zażółć.pt", "data.yaml"])
def test_windows_reveals_exact_file_without_running_it(tmp_path, filename):
    path = tmp_path / filename
    path.touch()
    with patch.object(locations.sys, "platform", "win32"), \
         patch.object(locations.subprocess, "Popen") as popen, \
         patch.object(locations.os, "startfile", create=True) as startfile:
        locations.reveal_source_path(path)
    popen.assert_called_once_with(["explorer.exe", "/select,", str(path)])
    startfile.assert_not_called()


def test_windows_opens_dataset_directory(tmp_path):
    with patch.object(locations.sys, "platform", "win32"), \
         patch.object(locations.os, "startfile", create=True) as startfile:
        locations.reveal_source_path(tmp_path)
    startfile.assert_called_once_with(str(tmp_path))


def test_deleted_source_reports_error_in_own_dialog(panel, tmp_path):
    candidate = make_candidate(tmp_path, "deleted")
    panel.set_candidate(candidate)
    candidate["best_weights"].unlink()
    with patch.object(locations.messagebox, "showerror") as error, \
         patch.object(locations.subprocess, "Popen") as popen:
        panel.open_buttons["model"].invoke()
    popen.assert_not_called()
    assert str(candidate["best_weights"]) in error.call_args.args[1]
    assert error.call_args.kwargs["parent"] == panel.winfo_toplevel()
    assert panel.open_buttons["model"].instate(["disabled"])


def test_export_dialog_selection_updates_pinned_locations(root, tmp_path):
    from auto_annotation_tool.gui import z4_model_export as export

    candidates = [make_candidate(tmp_path, name) for name in ("first", "second")]
    for index, candidate in enumerate(candidates):
        candidate.update(model_label=f"model_{index}", role="plate", target="plate", task="pose",
                         model_version="YOLO26n-pose", training_provenance={"provenance_version": 1})
    host = SimpleNamespace(
        app=SimpleNamespace(root=root, palette={}), frame=root,
        _build_mobile_model_export_path=lambda *_args: tmp_path / "export.alprmodel",
    )
    callback_errors = []
    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)

    with patch.object(export, "_collect_mobile_export_candidates", return_value=candidates), \
         patch.object(root, "report_callback_exception", side_effect=lambda *exc: callback_errors.append(exc)):
        dialog = export._open_mobile_model_export_center(host)
        try:
            root.update()
            widgets = list(walk(dialog))
            panel = next(widget for widget in widgets if isinstance(widget, locations.MobileExportSourceLocations))
            tree = next(widget for widget in widgets if isinstance(widget, ttk.Treeview)
                        and widget.exists("mobile_export_candidate_1"))
            tree.selection_set("mobile_export_candidate_1")
            root.update()
            assert panel.paths == locations.candidate_source_paths(candidates[1])
            assert panel.winfo_viewable()
            # Locations have a fixed row above the scrolling metadata table.
            assert int(panel.grid_info()["row"]) == 1
            with patch.object(locations, "reveal_source_path") as reveal:
                panel.open_buttons["model"].invoke()
                reveal.assert_called_once_with(candidates[1]["best_weights"])
            assert callback_errors == []
        finally:
            dialog.destroy()
