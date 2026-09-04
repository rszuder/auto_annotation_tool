import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_annotation_tool.gui import z4_training_runtime


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Widget:
    def __init__(self):
        self.config = {}

    def configure(self, **kwargs):
        self.config.update(kwargs)


class _Frame:
    def __init__(self):
        self.after_calls = []

    def after(self, delay_ms, callback=None, *args):
        self.after_calls.append((delay_ms, callback, args))
        return len(self.after_calls)

    def after_cancel(self, _job):
        return None


class _App:
    tabs = {}


class _SlowTrainer:
    def __init__(self, delay_s=0.35):
        self.delay_s = delay_s
        self.calls = 0
        self.done = threading.Event()

    def start_training(self, **kwargs):
        self.calls += 1
        callback = kwargs.get("progress_callback")
        if callable(callback):
            callback("Wolny testowy preflight", 45.0, "unit-test")
        time.sleep(self.delay_s)
        self.done.set()
        return "run_async_001"


class _Host:
    def __init__(self, dataset_root: Path):
        self.frame = _Frame()
        self.app = _App()
        self.trainer = _SlowTrainer()
        self.name_var = _Var("Async run")
        self.base_model_var = _Var("yolo11n")
        self.base_custom_var = _Var("")
        self.device_var = _Var("cpu")
        self.dataset_var = _Var("")
        self.btn_start_train = _Widget()
        self.btn_pause_train = _Widget()
        self.btn_stop_train = _Widget()
        self.train_progress_label = _Widget()
        self.train_resource_label = _Widget()
        self._training_completion_poll_job = None
        self._logs = []
        self._dataset_root = dataset_root

    def _ui(self, fn):
        fn()

    def _get_pinned_step4_result_state(self):
        return {}

    def _clear_step4_guidance(self):
        return None

    def _set_step4_process_console_text(self, text):
        self._logs.append(text)

    def _set_training_metric_interpretation(self, text):
        self._metric_interpretation = text

    def _set_training_widget_text(self, widget, text):
        widget.configure(text=text)

    def _set_training_resource_sample(self, _sample):
        return None

    def _validate_active_training_source_for_pz2(self):
        return {
            "ok": True,
            "yaml_path": str(self._dataset_root / "data.yaml"),
            "dataset_root": str(self._dataset_root),
            "message": "Dataset OK",
            "stats": {"train_images": 1, "val_images": 1, "test_images": 0},
        }

    def _looks_like_char_classification_dataset(self, _path):
        return False

    def _get_pose_dataset_size_warning(self, _dataset_root, _stats):
        return ""

    def _infer_dataset_target(self, _dataset_root):
        return "char"

    def _get_selected_training_target(self):
        return "char"

    def _rebind_free_mode_training_storage(self, target):
        self._target = target

    def _is_custom_base_model_key(self, _key):
        return False

    def _resolve_selected_training_base_model_display(self):
        return "YOLO test"

    def _resolve_selected_training_base_model_info(self):
        return None, {}

    def _device_to_ultralytics(self, value):
        return value

    def _validate_training_base_model_target_compatibility(self, **_kwargs):
        return True, ""

    def _is_pose_base_model(self, _base_key, _base_model):
        return False

    def _resolve_step4_fine_tune_parent_run(self):
        return None

    def _safe_training_int_value(self, name, default=0, minimum=0):
        values = {"epochs_var": 1, "batch_var": 1, "imgsz_var": 320}
        return max(int(values.get(name, default)), int(minimum))

    def _safe_training_float_value(self, _name, default=0.01, minimum=0.0):
        return max(float(default), float(minimum))

    def _normalize_training_device_choice(self, value):
        return value

    def _get_effective_training_device_profile(self, value):
        return value, None

    def _get_training_gpu_capacity_block_reason(self, **_kwargs):
        return ""

    def _append_train_log(self, message):
        self._logs.append(message)

    def _release_gpu_resources_before_training(self):
        self._logs.append("[TEST] release gpu")

    def _begin_step4_operation(self, _owner, _label):
        return True

    def _end_step4_operation(self, _owner):
        self._ended = True

    def _set_train_progress_values(self, **kwargs):
        self._progress = kwargs

    def _remember_campaign_plate_training_source(self, _dataset_root):
        return None

    def _reset_training_runtime_progress(self):
        return None

    def _set_train_live_metrics(self, _metrics):
        return None

    def _set_training_running_ui_state(self, run_id, *, status_text=None):
        self._running_state = (run_id, status_text)

    def _remember_campaign_training_run_in_registry(self, **_kwargs):
        return None

    def _refresh_step4_campaign_navigation_ui(self):
        return None

    def get_campaign_training_target(self):
        return "char"

    def _poll_training_completion(self):
        return None


class Z4AsyncTrainingPreflightTests(unittest.TestCase):
    def test_start_training_returns_immediately_and_blocks_double_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "dataset"
            dataset.mkdir(parents=True, exist_ok=True)
            (dataset / "data.yaml").write_text(
                "path: .\ntrain: images/train\nval: images/val\nnames:\n  0: char\n",
                encoding="utf-8",
            )
            host = _Host(dataset)

            with patch.object(z4_training_runtime, "YOLO_AVAILABLE", True):
                with patch.object(z4_training_runtime.CAMPAIGN, "get_active_project_name", return_value=""):
                    started_at = time.perf_counter()
                    z4_training_runtime._start_training(host)
                    elapsed = time.perf_counter() - started_at
                    z4_training_runtime._start_training(host)

            self.assertLess(elapsed, 0.15)
            self.assertTrue(getattr(host, "_training_start_in_progress", False))
            self.assertEqual(host.btn_start_train.config.get("state"), "disabled")
            self.assertTrue(host.trainer.done.wait(2.0))
            thread = getattr(host, "_training_preflight_thread", None)
            if thread is not None:
                thread.join(timeout=1.0)
            self.assertEqual(host.trainer.calls, 1)
            self.assertEqual(host.current_run_id, "run_async_001")


if __name__ == "__main__":
    unittest.main()
