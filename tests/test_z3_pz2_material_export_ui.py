from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def test_pz2_has_mirrored_add_and_export_buttons():
    source = _read("auto_annotation_tool/gui/z3_detection_tab_ui.py")
    assert 'text="Dodaj materiał do zbioru…"' in source
    assert 'text="Eksportuj cropy + AZ…"' in source
    assert "open_pz2_add_material" in source
    assert "open_pz2_export_material" in source


def test_export_ui_calls_same_portable_package_backend():
    source = _read("auto_annotation_tool/gui/z3_pz2_material_export.py")
    assert "export_pz2_az_package(" in source
    assert "Dodaj materiał do zbioru…" in source
    assert "_flush_preview_metadata(host)" in source
    assert "Aktywny PZ2 nie został zmodyfikowany." in source


def test_export_ui_has_clear_scopes():
    source = _read("auto_annotation_tool/gui/z3_pz2_material_export.py")
    assert "Wszystkie tablice" in source
    assert "Tylko zatwierdzone [OK]" in source
    assert "Zaznaczone tablice" in source
    assert "Ostatnio dodany materiał" in source


def test_export_button_is_kept_in_project_material_row():
    source = _read("auto_annotation_tool/gui/z3_preview_list_ui.py")
    assert "preview_add_material_btn" in source
    assert "preview_export_material_btn" in source
    assert "project_append_available" in source
