import copy
from pathlib import Path

from auto_annotation_tool.gui import z3_dataset_provenance as provenance


def chars(text, **extra):
    return [
        {
            "character": ch,
            "bbox": [idx * 10, 0, idx * 10 + 8, 20],
            **extra,
        }
        for idx, ch in enumerate(text)
    ]


def raw_exact_data():
    records = chars("ABC123")
    return {
        "source_image_id": "img-sha256-a",
        "source_annotation_id": "plate-ann-a",
        "source_geometry_hash": "geom",
        "source_gt_hash": "gt",
        "ground_truth_source": "manual_z2",
        "characters": records,
        "raw_detection": {
            "contract": "gt_blind.v1",
            "prediction_text": "ABC123",
            "characters": copy.deepcopy(records),
        },
        "raw_validation": {
            "status": "perfect",
            "exact_text_match": True,
            "exact_count_match": True,
            "geometry_ok": True,
        },
    }


def category(data, source_bucket=""):
    return provenance.classify_plate_dataset_provenance(
        None,
        data,
        meta_path=Path("metadata.json"),
        source_bucket=source_bucket,
    )["category"]


def test_raw_model_exact_requires_gt_blind_exact_and_unchanged_final():
    data = raw_exact_data()
    assert category(data) == provenance.RAW_MODEL_EXACT

    data["characters"][0]["bbox"][0] += 1
    assert category(data) == provenance.LEGACY_UNTRACKED


def test_manual_has_priority_over_raw_exact():
    data = raw_exact_data()
    data["characters"][0]["sign_source"] = "manual_sign"
    data["characters"][0]["source_kind"] = "local_manual"

    assert category(data) == provenance.MANUAL


def test_gt_assist_confirmed_has_highest_review_priority():
    data = raw_exact_data()
    data["correction_source"] = "gt_assist_confirmed"
    data["source_info"] = {
        "bucket": "local_manual",
        "origin": "preview_editor",
    }

    assert category(data) == provenance.GT_ASSIST_CONFIRMED


def test_cvat_import_is_explicit():
    data = raw_exact_data()
    data["source_info"] = {
        "bucket": "cvat_manual",
        "origin": "cvat_import",
    }

    assert category(data) == provenance.CVAT_IMPORT


def test_mobile_human_review_is_preserved():
    data = {
        "characters": chars("ABC123"),
        "source_expected_text_source": "mobile_crop_human_review",
        "mobile_acquisition": {
            "session_id": "capture-1",
        },
    }

    assert category(data) == provenance.MOBILE_HUMAN_REVIEW


def test_legacy_perfect_is_not_called_raw_model_exact():
    data = {
        "status": "perfect",
        "characters": chars("ABC123"),
    }

    assert category(data) == provenance.LEGACY_UNTRACKED


def test_provenance_summary_counts_categories():
    items = [
        {"provenance": {"category": provenance.RAW_MODEL_EXACT}},
        {"provenance": {"category": provenance.RAW_MODEL_EXACT}},
        {"provenance": {"category": provenance.MANUAL}},
    ]

    assert provenance.summarize_dataset_provenance(items) == {
        provenance.RAW_MODEL_EXACT: 2,
        provenance.MANUAL: 1,
    }
