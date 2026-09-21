from types import SimpleNamespace

from auto_annotation_tool.gui import z3_preview_list_ui as preview


class Host(SimpleNamespace):
    def _sort_character_records_by_x(self, records, data=None):
        def key(rec):
            if not isinstance(rec, dict):
                return 0
            bbox = rec.get("bbox", [])
            try:
                return float(bbox[0])
            except Exception:
                return 0
        return sorted(list(records or []), key=key)

    def _get_detection_method_key(self):
        return "OCR"

    def _get_preview_box_mode_key(self):
        return self.mode


def test_raw_result_preview_uses_frozen_raw_detection_not_review_characters():
    host = Host(mode="RAW_RESULT")
    data = {
        "characters": [
            {"character": "G", "bbox": [100, 0, 120, 20]},
        ],
        "raw_detection": {
            "contract": "gt_blind.v1",
            "characters": [
                {"character": "B", "bbox": [30, 0, 40, 20]},
                {"character": "A", "bbox": [10, 0, 20, 20]},
            ],
        },
    }

    variants = preview.get_preview_box_variants(host, data)
    records, source = preview.get_preview_box_records(host, data)

    assert [item["character"] for item in variants["RAW_RESULT"]] == ["A", "B"]
    assert [item["character"] for item in records] == ["A", "B"]
    assert source == "RAW_RESULT"

    # REVIEW/GOLD layer remains independent.
    assert [item["character"] for item in variants["FINAL"]] == ["G"]


def test_raw_result_preview_is_empty_when_no_raw_snapshot_exists():
    host = Host(mode="RAW_RESULT")
    data = {
        "characters": [
            {"character": "A", "bbox": [10, 0, 20, 20]},
        ],
    }

    records, source = preview.get_preview_box_records(host, data)

    assert records == []
    assert source == "RAW_RESULT"


def test_preview_mode_definitions_expose_raw_result_in_both_z3_sources():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    init = (
        root / "auto_annotation_tool/gui/z3_init_runtime.py"
    ).read_text(encoding="utf-8-sig")
    tab = (
        root / "auto_annotation_tool/gui/tab_character_annotation.py"
    ).read_text(encoding="utf-8-sig")

    for source in (init, tab):
        assert '("RAW_RESULT", "RAW wynik eksperymentu")' in source
        assert '"Wynik RAW": "RAW_RESULT"' in source
