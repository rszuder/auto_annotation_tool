"""Static UX contract regression: selection center versus export modal."""
from pathlib import Path


def test_mobile_export_ui_owns_preflight_and_calibration():
    path = Path(__file__).resolve().parents[1] / "auto_annotation_tool/gui/z4_model_export.py"
    source = path.read_text(encoding="utf-8-sig")
    modal = source.split("    def open_selected_mobile_export_executor() -> None:", 1)[1].split(
        "\n    def export_package() -> None:", 1
    )[0]
    footer = source.split('    export_button = ttk.Button(\n        actions,\n        text="Eksportuj zaznaczone",', 1)[1]
    footer = footer.split("    # One action row at every supported width/DPI", 1)[0]
    assert "Kalibracja INT8 — wskazany model" not in footer
    assert "Wybierz trening ręcznie" not in footer
    assert "Sprawdź precyzję TFLite" not in footer
    assert "Raporty z telefonu" not in footer
    assert "Sprawdź precyzję TFLite" in modal
    assert "Przygotuj manifest INT8 — {marker}" in modal
    assert "Wybierz gotowy manifest" in modal
    assert "_sync_calibration_visibility" in modal
    assert 'if bool(current_state["int8"].get()) or bool(current_state["onnx_int8"].get()):' in modal
    assert 'package_exporter.export(request, progress=progress_cb)' in modal
    assert 'last_exported_package["path"] = str(package_path)' in modal
    assert 'open_mobile_report_browser(self, parent=executor_modal)' in modal


def test_int8_export_guards_remain_in_place():
    exporter = Path(__file__).resolve().parents[1] / "auto_annotation_tool/exporters/mobile_model_exporter.py"
    code = exporter.read_text(encoding="utf-8-sig")
    assert 'def _calibration_for_request(' in code
    assert 'FULL_INT8_OUTPUT_NOT_PROVEN' in code
    assert 'def _requested_variant_specs(' in code
    assert 'self.validate_package(temp_package, require_precision=True)' in code
