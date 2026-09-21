from pathlib import Path


def test_z2_entry_has_no_gt_on_off_checkbox():
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "auto_annotation_tool/gui/z2_main_widgets.py",
        root / "auto_annotation_tool/gui/tab_annotation.py",
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in sources
    )

    assert "gt_capture_check" not in combined
    assert "gt_capture_hint_lbl" not in combined
    assert "Zapisuj GT znaków" not in combined
