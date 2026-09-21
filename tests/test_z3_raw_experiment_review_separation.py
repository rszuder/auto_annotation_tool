from pathlib import Path


def _source(path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / path).read_text(encoding="utf-8-sig")


def _function_source(text: str, name: str) -> str:
    marker = f"def {name}("
    start = text.index(marker)
    next_def = text.find("\ndef ", start + len(marker))
    return text[start:] if next_def < 0 else text[start:next_def]


def test_main_z3_detection_action_is_raw_experiment_in_free_and_campaign():
    runtime = _source("auto_annotation_tool/gui/z3_detection_runtime.py")
    stage = _function_source(runtime, "run_detection_stage")

    assert "_prompt_pz2_detection_guard_options" not in stage
    assert '"raw_only": True' in stage
    assert '"process_scope": "all"' in stage
    assert '"campaign"' in stage
    assert '"free"' in stage


def test_raw_experiment_exits_before_review_gold_mutation():
    runtime = _source("auto_annotation_tool/gui/z3_detection_runtime.py")
    body = _function_source(runtime, "run_fast_ocr_test")

    raw_store = body.index('local_meta[pid]["raw_detection"] = raw_detection')
    raw_branch = body.index("if raw_only:", raw_store)
    raw_continue = body.index("continue", raw_branch)
    review_write = body.index('local_meta[pid]["characters"] = final_chars')

    assert raw_store < raw_branch < raw_continue < review_write
    assert "REVIEW/GOLD remains" not in body  # Polish source is authoritative.
    assert "REVIEW/GOLD pozostaje bez zmian" in body


def test_raw_mode_does_not_unlock_dataset_or_use_review_scope():
    runtime = _source("auto_annotation_tool/gui/z3_detection_runtime.py")
    body = _function_source(runtime, "run_fast_ocr_test")

    assert 'process_scope = (' in body
    assert '"all"' in body
    assert "if not raw_only:" in body
    assert "self.unlock_dataset_subtab()" in body
    assert '"execution_mode": (' in body
    assert '"raw_experiment"' in body
    assert '"workflow_context": workflow_context' in body


def test_z3_main_button_is_named_run_raw():
    ui = _source("auto_annotation_tool/gui/z3_detection_tab_ui.py")
    assert 'text="Uruchom RAW"' in ui
