#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trener modeli YOLO Pose.
"""

import gc
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, Tuple

from ..config import (
    CONFIG,
    logger,
    YOLO_AVAILABLE,
    AVAILABLE_POSE_MODELS,
    get_torch_module,
    get_yolo_class,
    is_cuda_available,
)
from ..utils import cleanup_gpu_memory, safe_load_yaml
from .training_history import TrainingHistory, TrainingRun, TrainingStatus
from .training_report import TrainingReportGenerator
from .resource_monitor import format_resource_sample_line, sample_system_memory

YOLO = None


_ULTRALYTICS_SAVE_MODEL_PATCHED = False


def _patch_ultralytics_save_model_closed_file_bug():
    global _ULTRALYTICS_SAVE_MODEL_PATCHED
    if _ULTRALYTICS_SAVE_MODEL_PATCHED or not YOLO_AVAILABLE:
        return

    try:
        from ultralytics.engine.trainer import BaseTrainer
    except Exception:
        return

    original = getattr(BaseTrainer, "save_model", None)
    if not callable(original):
        return
    if getattr(original, "_aat_closed_file_patch", False):
        _ULTRALYTICS_SAVE_MODEL_PATCHED = True
        return

    original_globals = getattr(original, "__globals__", {}) or {}
    torch_mod = original_globals.get("torch")
    deepcopy_fn = original_globals.get("deepcopy")
    unwrap_model_fn = original_globals.get("unwrap_model")
    convert_opt_state = original_globals.get("convert_optimizer_state_dict_to_fp16")
    datetime_mod = original_globals.get("datetime")
    ultralytics_version = original_globals.get("__version__", "")
    git_meta = original_globals.get("GIT")
    if not all([torch_mod, deepcopy_fn, unwrap_model_fn, convert_opt_state, datetime_mod]):
        return

    def _safe_torch_save_to_path(payload: dict, path_obj: Path):
        tmp_path = path_obj.with_suffix(path_obj.suffix + ".tmp")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        torch_mod.save(payload, str(tmp_path))
        os.replace(str(tmp_path), str(path_obj))

    def _fallback_save_model(self):
        ckpt = {
            "epoch": self.epoch,
            "best_fitness": self.best_fitness,
            "model": None,
            "ema": deepcopy_fn(unwrap_model_fn(self.ema.ema)).half(),
            "updates": self.ema.updates,
            "optimizer": convert_opt_state(deepcopy_fn(self.optimizer.state_dict())),
            "scaler": self.scaler.state_dict(),
            "train_args": vars(self.args),
            "train_metrics": {**getattr(self, "metrics", {}), **{"fitness": self.fitness}},
            "train_results": self.read_results_csv(),
            "date": datetime_mod.now().isoformat(),
            "version": ultralytics_version,
            "git": {
                "root": str(getattr(git_meta, "root", "")),
                "branch": str(getattr(git_meta, "branch", "")),
                "commit": str(getattr(git_meta, "commit", "")),
                "origin": str(getattr(git_meta, "origin", "")),
            },
            "license": "AGPL-3.0 (https://ultralytics.com/license)",
            "docs": "https://docs.ultralytics.com",
        }

        self.wdir.mkdir(parents=True, exist_ok=True)
        _safe_torch_save_to_path(ckpt, Path(self.last))
        if self.best_fitness == self.fitness:
            _safe_torch_save_to_path(ckpt, Path(self.best))
        if (self.save_period > 0) and (self.epoch % self.save_period == 0):
            _safe_torch_save_to_path(ckpt, Path(self.wdir) / f"epoch{self.epoch}.pt")

    def patched_save_model(self):
        try:
            return original(self)
        except ValueError as e:
            if "closed file" not in str(e or "").lower():
                raise
            logger.warning(
                "Ultralytics save_model() wywalił się na 'closed file'. "
                "Uruchamiam bezpieczny fallback zapisu checkpointu bez BytesIO."
            )
            return _fallback_save_model(self)

    setattr(patched_save_model, "_aat_closed_file_patch", True)
    BaseTrainer.save_model = patched_save_model
    _ULTRALYTICS_SAVE_MODEL_PATCHED = True


class YOLOPoseTrainer:
    """
    Trener modeli YOLO Pose.
    """

    def __init__(self, history: TrainingHistory = None):
        self.history = history or TrainingHistory()
        self.current_run: Optional[TrainingRun] = None
        self.model: Optional["YOLO"] = None

        self.is_training = False
        self.should_pause = False
        self.should_stop = False

        self.on_epoch_end: Optional[Callable[[int, Dict], None]] = None
        self.on_batch_progress: Optional[Callable[[int, int, int, float], None]] = None
        self.on_training_end: Optional[Callable[[bool, str], None]] = None
        self.on_progress: Optional[Callable[[float, str], None]] = None
        self.on_resource_sample: Optional[Callable[[Dict], None]] = None
        self.on_resource_report: Optional[Callable[[Dict], None]] = None
        self._training_batch_state: Optional[Dict] = None
        self._worker_process: Optional[subprocess.Popen] = None
        self._worker_monitor_thread: Optional[threading.Thread] = None
        self._worker_stdout_handle = None
        self._ipc_dir: Optional[Path] = None
        self._event_file_path: Optional[Path] = None
        self._control_file_path: Optional[Path] = None
        self._job_file_path: Optional[Path] = None
        self._stdout_log_path: Optional[Path] = None
        self._last_event_offset: int = 0
        self._worker_end_event_seen: bool = False

    def _apply_ultralytics_runtime_safety_overrides(self, *, device, is_pose: bool) -> None:
        """Ogranicza znane źródła niestabilności w workerze treningowym."""
        try:
            from ultralytics import SETTINGS as ULTRALYTICS_SETTINGS

            try:
                if bool(ULTRALYTICS_SETTINGS.get("sync", True)):
                    ULTRALYTICS_SETTINGS.update({"sync": False})
                    logger.info("Wyłączono sync/telemetrię Ultralytics w workerze treningowym.")
            except Exception:
                pass
        except Exception:
            ULTRALYTICS_SETTINGS = None

        try:
            from ultralytics.utils.events import events as ultralytics_events

            ultralytics_events.enabled = False
        except Exception:
            pass

        if str(device).strip().lower() != "cpu":
            return

        try:
            torch = get_torch_module()
            if torch is not None:
                try:
                    torch.backends.mkldnn.enabled = False
                    logger.info("CPU training: wyłączono MKLDNN dla stabilności.")
                except Exception:
                    pass

                try:
                    torch.set_num_threads(1)
                except Exception:
                    pass
                try:
                    torch.set_num_interop_threads(1)
                except Exception:
                    pass
                logger.info("CPU training: ograniczono wątki PyTorch do 1/1.")
        except Exception as e:
            logger.debug(f"Nie udało się zastosować CPU safety overrides: {e}")

    def _reset_runtime_state(self):
        """Czyści stan modelu i pamięć CUDA przed kolejną próbą treningu."""
        try:
            model_ref = getattr(self, "model", None)
            self.model = None
            if model_ref is not None:
                try:
                    trainer_ref = getattr(model_ref, "trainer", None)
                    if trainer_ref is not None:
                        setattr(trainer_ref, "stop", True)
                except Exception:
                    pass
                del model_ref
        except Exception:
            self.model = None

        gc.collect()
        cleanup_gpu_memory()

    def _resolve_runtime_epoch(self, trainer=None, *, include_running_epoch: bool = False) -> int:
        run = getattr(self, "current_run", None)
        fallback_epoch = 0
        if run is not None:
            try:
                history_run = self.history.get_run(run.id)
            except Exception:
                history_run = None
            try:
                fallback_epoch = int(getattr(history_run, "current_epoch", 0) or getattr(run, "current_epoch", 0) or 0)
            except Exception:
                fallback_epoch = 0

        batch_state = getattr(self, "_training_batch_state", None)
        if isinstance(batch_state, dict):
            try:
                fallback_epoch = max(fallback_epoch, int(batch_state.get("completed_epoch", 0) or 0))
            except Exception:
                pass

            if include_running_epoch:
                try:
                    running_epoch = int(batch_state.get("epoch", -1) or -1)
                    current_batch = int(batch_state.get("batch", 0) or 0)
                    total_batches = int(batch_state.get("total_batches", 0) or 0)
                except Exception:
                    running_epoch = -1
                    current_batch = 0
                    total_batches = 0
                if running_epoch >= 0 and total_batches > 0 and current_batch >= total_batches:
                    return max(fallback_epoch, running_epoch + 1)

        if not include_running_epoch:
            return max(0, fallback_epoch)

        trainer_ref = trainer
        if trainer_ref is None:
            try:
                trainer_ref = getattr(self.model, "trainer", None)
            except Exception:
                trainer_ref = None

        if trainer_ref is not None:
            try:
                trainer_epoch = int(getattr(trainer_ref, "epoch", -1))
            except Exception:
                trainer_epoch = -1
            if trainer_epoch >= 0:
                return max(fallback_epoch, trainer_epoch + 1)

        return max(0, fallback_epoch)

    def _is_runtime_epoch_complete(self) -> bool:
        batch_state = getattr(self, "_training_batch_state", None)
        if not isinstance(batch_state, dict):
            return False
        try:
            running_epoch = int(batch_state.get("epoch", -1) or -1)
            current_batch = int(batch_state.get("batch", 0) or 0)
            total_batches = int(batch_state.get("total_batches", 0) or 0)
        except Exception:
            return False
        return bool(running_epoch >= 0 and total_batches > 0 and current_batch >= total_batches)

    def _format_runtime_epoch_state(self) -> str:
        batch_state = getattr(self, "_training_batch_state", None)
        if not isinstance(batch_state, dict):
            return ""
        try:
            completed_epoch = int(batch_state.get("completed_epoch", 0) or 0)
            running_epoch = int(batch_state.get("epoch", -1) or -1)
            current_batch = int(batch_state.get("batch", 0) or 0)
            total_batches = int(batch_state.get("total_batches", 0) or 0)
        except Exception:
            return ""
        if running_epoch < 0 or total_batches <= 0:
            return f"Ukończone epoki: {completed_epoch}."
        return (
            f"Ukończone epoki: {completed_epoch}. "
            f"Przerwano w epoce {running_epoch + 1}, batch {current_batch}/{total_batches}; "
            "ta epoka nie została zaliczona jako ukończona."
        )

    def _resolve_completed_epoch_from_checkpoint(self, checkpoint_path: str | Path) -> Optional[int]:
        path = Path(str(checkpoint_path or "").strip())
        if not path.exists():
            return None
        torch = get_torch_module()
        if torch is None:
            return None
        checkpoint = None
        try:
            try:
                checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
            except TypeError:
                checkpoint = torch.load(str(path), map_location="cpu")
            if not isinstance(checkpoint, dict):
                return None
            raw_epoch = checkpoint.get("epoch")
            if raw_epoch is None:
                return None
            epoch_index = int(raw_epoch)
            if epoch_index < 0:
                return 0
            return epoch_index + 1
        except Exception as e:
            logger.debug(f"Nie udało się odczytać epoki z checkpointu {path}: {e}")
            return None
        finally:
            try:
                del checkpoint
            except Exception:
                pass
            gc.collect()

    @staticmethod
    def _is_training_memory_error(error: Exception) -> bool:
        text = str(error or "").strip().lower()
        if not text:
            return False
        needles = (
            "out of memory",
            "outofmemory",
            "cuda outofmemoryerror",
            "memory allocation failure",
            "unable to allocate",
            "defaultcpuallocator: not enough memory",
            "not enough memory",
            "cuda error: unknown error",
        )
        return any(needle in text for needle in needles)

    @staticmethod
    def _is_cuda_runtime_broken_error(error: Exception) -> bool:
        text = str(error or "").strip().lower()
        if not text:
            return False
        needles = (
            "cuda error: unknown error",
            "unable to find an engine to execute this computation",
            "get was unable to find an engine to execute this computation",
        )
        return any(needle in text for needle in needles)

    @staticmethod
    def _is_nonfinite_training_error(error: Exception) -> bool:
        text = str(error or "").strip().lower()
        if not text:
            return False
        needles = (
            "nan",
            "inf",
            "non-finite",
            "non finite",
            "not finite",
        )
        return any(needle in text for needle in needles)

    @staticmethod
    def _assert_finite_training_metrics(epoch: int, metrics: Dict) -> None:
        bad_fields = []
        for key, value in (metrics or {}).items():
            try:
                numeric = float(value)
            except Exception:
                continue
            if not math.isfinite(numeric):
                bad_fields.append(str(key))
        if bad_fields:
            raise FloatingPointError(
                "Trening wygenerował NaN/Inf w metrykach epoki "
                f"{int(epoch)} ({', '.join(bad_fields)}). "
                "Zatrzymuję run, żeby nie produkować kolejnych uszkodzonych checkpointów."
            )

    @staticmethod
    def _next_lower_training_imgsz(value: int) -> int:
        steps = [256, 320, 384, 416, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024, 1280]
        try:
            current = int(value or 640)
        except Exception:
            current = 640
        lower_steps = [step for step in steps if step < current]
        return int(lower_steps[-1] if lower_steps else steps[0])

    @staticmethod
    def _format_ram_state(ram_state: Dict) -> str:
        try:
            percent = float((ram_state or {}).get("ram_percent") or 0.0)
        except Exception:
            percent = 0.0
        try:
            available = float((ram_state or {}).get("ram_available_mib") or 0.0)
            total = float((ram_state or {}).get("ram_total_mib") or 0.0)
        except Exception:
            available = 0.0
            total = 0.0
        if not total:
            return "RAM: brak danych"
        return f"RAM {percent:.1f}% | wolne {available / 1024.0:.2f} GB z {total / 1024.0:.2f} GB"

    @staticmethod
    def _is_ram_pressure_high(ram_state: Dict, dataset_profile: Dict) -> bool:
        if not ram_state:
            return False
        try:
            percent = float(ram_state.get("ram_percent") or 0.0)
            available_mib = float(ram_state.get("ram_available_mib") or 0.0)
        except Exception:
            return False
        train_images = int((dataset_profile or {}).get("train_images", 0) or 0)
        is_pose = bool((dataset_profile or {}).get("is_pose"))
        if percent >= 82.0:
            return True
        if available_mib and available_mib < 2048.0:
            return True
        if train_images >= 1000 and available_mib and available_mib < 4096.0:
            return True
        if is_pose and train_images >= 1000 and percent >= 75.0:
            return True
        return False

    def _build_ram_safe_training_attempt(
        self,
        *,
        batch_size: int,
        img_size: int,
        lr0: float,
        dataset_profile: Dict,
        label: str,
    ) -> Dict:
        is_pose = bool((dataset_profile or {}).get("is_pose"))
        safe_batch = 1 if is_pose else max(1, min(int(batch_size or 1), 2))
        safe_img_size = 512 if int(img_size or 640) >= 640 else self._next_lower_training_imgsz(int(img_size or 640))
        safe_img_size = max(256, int(safe_img_size))
        safe_lr0 = round(max(0.0025, float(lr0 or 0.01) * 0.85), 4)
        return {
            "batch_size": int(safe_batch),
            "img_size": int(safe_img_size),
            "lr0": float(safe_lr0),
            "amp": False,
            "mosaic": 0.0,
            "close_mosaic": 0,
            "plots": False,
            "cache": False,
            "label": str(label),
            "ram_safe": True,
        }

    def _build_train_args(
        self,
        run: TrainingRun,
        dataset_path,
        epochs: int,
        batch_size: int,
        img_size: int,
        device,
        lr0: float,
        *,
        amp: bool = True,
        mosaic: float | None = None,
        close_mosaic: int | None = None,
        plots: bool = True,
        cache: bool = False,
    ) -> Dict:
        train_args = {
            "data": str(Path(dataset_path) / "data.yaml"),
            "epochs": int(epochs),
            "batch": int(batch_size),
            "imgsz": int(img_size),
            "device": 0 if device == "auto" and is_cuda_available() else device,
            "lr0": float(lr0),
            "project": run.output_dir,
            "name": "train",
            "exist_ok": True,
            "pretrained": True,
            "verbose": True,
            "save": True,
            "save_period": 10,
            "patience": 50,
            "plots": bool(plots),
            "workers": 0,
            # Jawne cache=False zapobiega niekontrolowanemu trzymaniu obrazów w RAM.
            "cache": bool(cache),
            "amp": bool(amp),
        }
        if mosaic is not None:
            train_args["mosaic"] = float(mosaic)
        if close_mosaic is not None:
            train_args["close_mosaic"] = int(close_mosaic)
        return train_args

    def _export_training_report_artifacts(self, run: TrainingRun) -> None:
        if run is None:
            return

        run_dir = Path(str(getattr(run, "output_dir", "") or "").strip())
        if not run_dir.exists():
            return

        train_dir = run_dir / "train"
        try:
            plots_dir = TrainingReportGenerator.export_plots(train_dir, run_dir)
            refreshed_run = self.history.get_run(run.id) or run
            report_path = TrainingReportGenerator.generate_html(
                refreshed_run.to_dict(),
                run_dir / "training_report.html",
                plots_dir,
                extra_info={
                    "plots_dir": str(plots_dir),
                    "train_dir": str(train_dir),
                },
            )
            self.history.update_run(
                run.id,
                plots_dir=str(plots_dir),
                report_html=str(report_path),
            )
            try:
                run.plots_dir = str(plots_dir)
                run.report_html = str(report_path)
            except Exception:
                pass
            logger.info(f"Raport treningu zapisany: {report_path}")
        except Exception as report_err:
            logger.warning(f"Nie udało się przygotować raportu i wykresów treningu: {report_err}")

    def _get_dataset_runtime_profile(self, dataset_path) -> Dict:
        profile = {
            "ok": False,
            "train_images": 0,
            "val_images": 0,
            "test_images": 0,
            "is_pose": False,
        }
        try:
            ok, _msg, stats = self.validate_dataset(Path(dataset_path))
            profile["ok"] = bool(ok)
            profile["train_images"] = int((stats or {}).get("train_images", 0) or 0)
            profile["val_images"] = int((stats or {}).get("val_images", 0) or 0)
            profile["test_images"] = int((stats or {}).get("test_images", 0) or 0)
            profile["is_pose"] = bool((stats or {}).get("kpt_shape"))
        except Exception:
            pass
        return profile

    def _close_worker_stdout_handle(self):
        handle = getattr(self, "_worker_stdout_handle", None)
        self._worker_stdout_handle = None
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass

    def _reset_worker_ipc_state(self):
        self._close_worker_stdout_handle()
        self._worker_process = None
        self._worker_monitor_thread = None
        self._ipc_dir = None
        self._event_file_path = None
        self._control_file_path = None
        self._job_file_path = None
        self._stdout_log_path = None
        self._last_event_offset = 0
        self._worker_end_event_seen = False

    def _prepare_worker_ipc(self, run: TrainingRun) -> Dict[str, str]:
        ipc_dir = Path(run.output_dir) / "_ipc"
        ipc_dir.mkdir(parents=True, exist_ok=True)
        event_path = ipc_dir / "events.jsonl"
        control_path = ipc_dir / "control.json"
        job_path = ipc_dir / "job.json"
        stdout_path = ipc_dir / "worker_stdout.log"

        try:
            event_path.write_text("", encoding="utf-8")
        except Exception:
            pass
        try:
            stdout_path.write_text("", encoding="utf-8")
        except Exception:
            pass
        control_path.write_text(
            json.dumps({"pause": False, "stop": False}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._ipc_dir = ipc_dir
        self._event_file_path = event_path
        self._control_file_path = control_path
        self._job_file_path = job_path
        self._stdout_log_path = stdout_path
        self._last_event_offset = 0
        self._worker_end_event_seen = False

        return {
            "ipc_dir": str(ipc_dir),
            "event_file": str(event_path),
            "control_file": str(control_path),
            "job_file": str(job_path),
            "stdout_log": str(stdout_path),
        }

    def _write_worker_control(self, *, pause: bool | None = None, stop: bool | None = None):
        control_path = getattr(self, "_control_file_path", None)
        if control_path is None:
            return

        payload = {"pause": False, "stop": False}
        try:
            if Path(control_path).exists():
                payload = json.loads(Path(control_path).read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    payload = {"pause": False, "stop": False}
        except Exception:
            payload = {"pause": False, "stop": False}

        if pause is not None:
            payload["pause"] = bool(pause)
        if stop is not None:
            payload["stop"] = bool(stop)

        try:
            Path(control_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Nie udało się zapisać sterowania workerem treningu: {e}")

    def _emit_worker_event(self, event: Dict):
        event_type = str((event or {}).get("type") or "").strip().lower()
        if not event_type:
            return

        if event_type == "batch_progress":
            if self.on_batch_progress:
                try:
                    self.on_batch_progress(
                        int(event.get("epoch", 0) or 0),
                        int(event.get("batch_idx", 0) or 0),
                        int(event.get("total_batches", 0) or 0),
                        float(event.get("batch_pct", 0.0) or 0.0),
                    )
                except Exception:
                    pass
            return

        if event_type == "epoch_end":
            if self.current_run is not None:
                try:
                    self.current_run.current_epoch = int(event.get("epoch", 0) or getattr(self.current_run, "current_epoch", 0) or 0)
                except Exception:
                    pass
            if self.on_epoch_end:
                try:
                    self.on_epoch_end(
                        int(event.get("epoch", 0) or 0),
                        dict(event.get("metrics") or {}),
                    )
                except Exception:
                    pass
            return

        if event_type == "progress":
            if self.on_progress:
                try:
                    self.on_progress(
                        float(event.get("percent", 0.0) or 0.0),
                        str(event.get("message", "") or "").strip(),
                    )
                except Exception:
                    pass
            return

        if event_type == "resource_monitor_start":
            if self.on_progress:
                try:
                    self.on_progress(0.0, "Monitoring zasobów treningu uruchomiony.")
                except Exception:
                    pass
            return

        if event_type == "resource_sample":
            sample = dict(event.get("sample") or {})
            if self.on_resource_sample:
                try:
                    self.on_resource_sample(sample)
                except Exception:
                    pass
            return

        if event_type == "resource_report":
            report = dict(event.get("report") or {})
            if self.current_run is not None:
                try:
                    self.history.update_run(
                        self.current_run.id,
                        resource_report=str(report.get("report_path") or ""),
                        resource_summary=str(report.get("summary_text") or format_resource_sample_line(report.get("last_sample") or {})),
                    )
                    refreshed = self.history.get_run(self.current_run.id)
                    if refreshed is not None:
                        self.current_run = refreshed
                except Exception:
                    pass
            if self.on_resource_report:
                try:
                    self.on_resource_report(report)
                except Exception:
                    pass
            return

        if event_type == "training_end":
            self._worker_end_event_seen = True
            if self.on_training_end:
                try:
                    self.on_training_end(
                        bool(event.get("success", False)),
                        str(event.get("message", "") or "").strip(),
                    )
                except Exception:
                    pass
            return

    def _drain_worker_events(self):
        event_path = getattr(self, "_event_file_path", None)
        if event_path is None:
            return

        path_obj = Path(event_path)
        if not path_obj.exists():
            return

        try:
            with path_obj.open("r", encoding="utf-8") as handle:
                handle.seek(int(getattr(self, "_last_event_offset", 0) or 0))
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    self._last_event_offset = handle.tell()
                    raw = str(line or "").strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(event, dict):
                        self._emit_worker_event(event)
        except Exception as e:
            logger.debug(f"Nie udało się odczytać zdarzeń workera treningu: {e}")

    def _reload_history_from_disk(self):
        try:
            refreshed = TrainingHistory(history_dir=self.history.history_dir)
        except Exception:
            return
        self.history = refreshed
        if self.current_run is not None:
            try:
                self.current_run = self.history.get_run(self.current_run.id) or self.current_run
            except Exception:
                pass

    def _finalize_worker_exit_without_end_event(self, return_code: int | None):
        run = self.current_run
        if run is None:
            return

        self._reload_history_from_disk()
        try:
            refreshed_run = self.history.get_run(run.id)
        except Exception:
            refreshed_run = None
        if refreshed_run is not None:
            run = refreshed_run
            self.current_run = refreshed_run

        status_value = str(getattr(run, "status", "") or "").strip().lower()
        if status_value == TrainingStatus.RUNNING.value:
            message = (
                "Proces treningu zakończył się nieoczekiwanie poza GUI. "
                f"Kod wyjścia workera: {return_code if return_code is not None else 'brak'}."
            )
            if return_code and int(return_code) < 0:
                message += " Worker został przerwany przez błąd natywny biblioteki treningowej."
            self.history.update_run(
                run.id,
                status=TrainingStatus.FAILED.value,
                finished_at=datetime.now().isoformat(),
                error_message=message,
            )
            try:
                self.current_run = self.history.get_run(run.id) or self.current_run
            except Exception:
                pass
            status_value = TrainingStatus.FAILED.value

        if self.on_training_end:
            final_message = str(getattr(self.current_run, "error_message", "") or "").strip()
            if status_value == TrainingStatus.COMPLETED.value:
                final_message = "Trening zakończony"
                success = True
            elif status_value == TrainingStatus.PAUSED.value:
                final_message = final_message or "Wstrzymano"
                success = False
            elif status_value == TrainingStatus.CANCELLED.value:
                final_message = final_message or "Zatrzymano"
                success = False
            else:
                final_message = final_message or "Trening zakończony błędem"
                success = False
            try:
                self.on_training_end(success, final_message)
            except Exception:
                pass

    def _monitor_worker_process(self, process: subprocess.Popen):
        try:
            while True:
                self._drain_worker_events()
                return_code = process.poll()
                if return_code is not None:
                    break
                time.sleep(0.25)

            self._drain_worker_events()
            self._reload_history_from_disk()
            if not self._worker_end_event_seen:
                self._finalize_worker_exit_without_end_event(process.returncode)
        finally:
            self.is_training = False
            self._close_worker_stdout_handle()
            self._worker_process = None
            self._worker_monitor_thread = None

    def get_available_models(self) -> Dict:
        return AVAILABLE_POSE_MODELS

    def _resolve_run_id_from_resume_checkpoint(self, resume_from: str) -> str:
        raw_path = str(resume_from or "").strip()
        if not raw_path:
            return ""

        try:
            resume_path = Path(raw_path)
        except Exception:
            return ""

        candidate_dirs = [
            resume_path.parent.parent.parent,
            resume_path.parent.parent,
            resume_path.parent,
        ]
        for candidate in candidate_dirs:
            run_id = str(getattr(candidate, "name", "") or "").strip()
            if run_id and self.history.get_run(run_id) is not None:
                return run_id

        try:
            resolved_checkpoint = str(resume_path.resolve())
        except Exception:
            resolved_checkpoint = raw_path

        for run_id, run in getattr(self.history, "runs", {}).items():
            last_weights = str(getattr(run, "last_weights", "") or "").strip()
            if not last_weights:
                continue
            try:
                resolved_last = str(Path(last_weights).resolve())
            except Exception:
                resolved_last = last_weights
            if resolved_last == resolved_checkpoint:
                return str(run_id or "").strip()

        return ""

    def get_latest_pose_model(self) -> str:
        priority = [
            "yolo26m-pose",
            "yolo26s-pose",
            "yolo26n-pose",
            "yolo11s-pose",
            "yolo11n-pose",
            "yolo11m-pose",
            "yolov8s-pose",
            "yolov8n-pose",
        ]
        for model_key in priority:
            if model_key in AVAILABLE_POSE_MODELS:
                return model_key
        return "yolov8n-pose"

    def get_recommended_model(self) -> str:
        preferred = ["yolo26m-pose", "yolo26s-pose", "yolo11s-pose", "yolov8s-pose"]
        for model_key in preferred:
            if model_key in AVAILABLE_POSE_MODELS:
                return model_key
        return self.get_latest_pose_model()

    def validate_dataset(self, dataset_path: Path) -> Tuple[bool, str, Dict]:
        stats = {"train_images": 0, "val_images": 0, "test_images": 0, "kpt_shape": None, "nc": 0}

        dataset_path = Path(dataset_path)
        yaml_file = dataset_path / "data.yaml"
        if not yaml_file.exists():
            return False, "Brak data.yaml", stats

        try:
            config = safe_load_yaml(yaml_file)

            # Dataset detekcyjny nie musi definiować kpt_shape.
            if "kpt_shape" in config:
                stats["kpt_shape"] = config["kpt_shape"]

            stats["nc"] = config.get("nc", 1)

        except Exception as e:
            return False, f"Błąd: {e}", stats

        for split in ["train", "val"]:
            img_dir = dataset_path / "images" / split
            if not img_dir.exists():
                return False, f"Brak: images/{split}", stats

            count = sum(1 for f in img_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS)
            stats[f"{split}_images"] = count
            if count == 0:
                return False, f"Brak obrazów w images/{split}", stats

        test_dir = dataset_path / "images" / "test"
        if test_dir.exists():
            stats["test_images"] = sum(
                1 for f in test_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            )

        return True, "Dataset OK", stats

    def start_training(
        self,
        name: str,
        dataset_path: str,
        base_model: str = "yolo11s-pose",
        epochs: int = 100,
        batch_size: int = 16,
        img_size: int = 640,
        device: str = "auto",
        lr0: float = 0.01,
        resume_from: str = None,
        **kwargs,
    ) -> Optional[str]:
        if not YOLO_AVAILABLE:
            logger.error("YOLO niedostępny")
            return None
        YoloClass = get_yolo_class()
        if YoloClass is None:
            logger.error("Nie udało się załadować YOLO")
            return None
        _patch_ultralytics_save_model_closed_file_bug()

        if self.is_training:
            logger.warning("Trening już trwa")
            return None

        is_valid, msg, _ = self.validate_dataset(Path(dataset_path))
        if not is_valid:
            logger.error(f"Dataset: {msg}")
            return None

        self._reset_runtime_state()
        self._reset_worker_ipc_state()

        # base_model może być: klucz (np. yolo26m-pose) albo ścieżka do .pt
        model_file = base_model
        if base_model in AVAILABLE_POSE_MODELS:
            model_file = AVAILABLE_POSE_MODELS[base_model]["file"]
        elif not str(base_model).lower().endswith(".pt"):
            model_file = f"{base_model}.pt"

        if resume_from:
            run_id = self._resolve_run_id_from_resume_checkpoint(resume_from)
            logger.info(f"Rozpoznany run do wznowienia z checkpointu: {run_id or '[BRAK]'} | checkpoint={resume_from}")
            self.current_run = self.history.get_run(run_id)
            if not self.current_run:
                logger.error(f"Nie znaleziono runu: {run_id}")
                return None

            self.history.update_run(
                run_id,
                status=TrainingStatus.RUNNING.value,
                started_at=datetime.now().isoformat(),
            )
        else:
            self.current_run = self.history.create_run(
                name=name,
                dataset_path=str(dataset_path),
                base_model=model_file,
                epochs=epochs,
                batch_size=batch_size,
                img_size=img_size,
                device=device,
                lr0=lr0,
            )

        self.is_training = True
        self.should_pause = False
        self.should_stop = False
        ipc_paths = self._prepare_worker_ipc(self.current_run)
        job_payload = {
            "history_dir": str(self.history.history_dir),
            "run_id": str(self.current_run.id),
            "model_file": str(model_file),
            "dataset_path": str(dataset_path),
            "epochs": int(epochs),
            "batch_size": int(batch_size),
            "img_size": int(img_size),
            "device": device,
            "lr0": float(lr0),
            "resume_from": str(resume_from or ""),
            "event_file": ipc_paths["event_file"],
            "control_file": ipc_paths["control_file"],
            "resource_interval_s": 2.0,
        }
        Path(ipc_paths["job_file"]).write_text(
            json.dumps(job_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        worker_module = "auto_annotation_tool.training.training_worker"
        try:
            stdout_handle = open(ipc_paths["stdout_log"], "a", encoding="utf-8", errors="replace")
            env = os.environ.copy()
            env.setdefault("PYTHONFAULTHANDLER", "1")
            process = subprocess.Popen(
                [sys.executable, "-m", worker_module, ipc_paths["job_file"]],
                cwd=str(Path(CONFIG.WORKSPACE_DIR).parent),
                stdout=stdout_handle,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except Exception:
            self.is_training = False
            self._close_worker_stdout_handle()
            self._reset_worker_ipc_state()
            raise

        self._worker_stdout_handle = stdout_handle
        self._worker_process = process
        monitor = threading.Thread(target=self._monitor_worker_process, args=(process,), daemon=True)
        self._worker_monitor_thread = monitor
        monitor.start()

        return self.current_run.id

    def _training_loop(self, model_file, dataset_path, epochs, batch_size, img_size, device, lr0, resume_from):
        run = self.current_run
        try:
            self._reset_runtime_state()
            if not YOLO_AVAILABLE:
                raise RuntimeError("YOLO niedostępny w procesie treningu.")
            YoloClass = get_yolo_class()
            if YoloClass is None:
                raise RuntimeError("Nie udało się załadować klasy YOLO w procesie treningu.")
            _patch_ultralytics_save_model_closed_file_bug()

            is_resuming = bool(resume_from and Path(resume_from).exists())
            dataset_profile = self._get_dataset_runtime_profile(dataset_path)
            disable_mosaic_from_start = bool(
                not is_resuming
                and bool(dataset_profile.get("is_pose"))
                and int(dataset_profile.get("train_images", 0) or 0) >= 1000
            )
            self._apply_ultralytics_runtime_safety_overrides(
                device=device,
                is_pose=bool(dataset_profile.get("is_pose")),
            )
            start_with_safe_pose_profile = bool(
                not is_resuming
                and bool(dataset_profile.get("is_pose"))
                and int(batch_size) <= 1
                and int(img_size) <= 448
            )
            ram_state = sample_system_memory()
            start_with_ram_safe_profile = bool(
                not is_resuming
                and self._is_ram_pressure_high(ram_state, dataset_profile)
            )
            if disable_mosaic_from_start:
                logger.info(
                    "Duży dataset POSE tablic wykryty. Startuję trening bez mosaic, "
                    "aby ograniczyć ryzyko awarii pamięci po stronie augmentacji."
                )
            elif start_with_safe_pose_profile:
                logger.info(
                    "Wykryto ostrożny profil startowy dla POSE tablic "
                    "(batch=1 i mały imgsz). Startuję od razu bez mosaic i bez AMP, "
                    "żeby nie czekać na pierwszy OOM."
                )
            if start_with_ram_safe_profile:
                ram_msg = (
                    "Wykryto presję RAM przed startem treningu. "
                    f"{self._format_ram_state(ram_state)}. "
                    "Uruchamiam profil oszczędzania pamięci: cache=off, workers=0, "
                    "mosaic=0, amp=off, plots=off oraz lżejszy batch/imgsz."
                )
                logger.warning(ram_msg)
                if self.on_progress:
                    self.on_progress(0.0, ram_msg)

            self.history.update_run(
                run.id,
                status=TrainingStatus.RUNNING.value,
                started_at=datetime.now().isoformat(),
            )

            try:
                completed_epoch = int(getattr(run, "current_epoch", 0) or 0)
            except Exception:
                completed_epoch = 0
            batch_state = {
                "epoch": -1,
                "batch": 0,
                "total_batches": 0,
                "completed_epoch": completed_epoch,
            }
            self._training_batch_state = batch_state

            def on_train_epoch_start(trainer):
                if self.should_stop:
                    raise InterruptedError("Zatrzymano")
                if self.should_pause:
                    self._save_checkpoint(trainer)
                    raise InterruptedError("Wstrzymano")
                batch_state["epoch"] = int(getattr(trainer, "epoch", -1))
                batch_state["batch"] = 0
                total_batches = max(1, int(len(getattr(trainer, "train_loader", []) or [])))
                batch_state["total_batches"] = total_batches
                if self.on_batch_progress:
                    self.on_batch_progress(batch_state["epoch"] + 1, 0, total_batches, 0.0)

            def on_train_batch_end(trainer):
                current_epoch = int(getattr(trainer, "epoch", -1))
                total_batches = max(1, int(len(getattr(trainer, "train_loader", []) or [])))
                if batch_state["epoch"] != current_epoch:
                    batch_state["epoch"] = current_epoch
                    batch_state["batch"] = 0
                batch_state["total_batches"] = total_batches
                batch_state["batch"] = min(total_batches, int(batch_state["batch"]) + 1)

                if self.on_batch_progress:
                    self.on_batch_progress(
                        current_epoch + 1,
                        int(batch_state["batch"]),
                        total_batches,
                        (float(batch_state["batch"]) / float(total_batches)) * 100.0,
                    )

                if self.should_stop:
                    raise InterruptedError("Zatrzymano")
                if self.should_pause:
                    self._save_checkpoint(trainer)
                    raise InterruptedError("Wstrzymano")

            def on_train_epoch_end(trainer):
                if self.should_stop:
                    raise InterruptedError("Zatrzymano")

                if self.should_pause:
                    self._save_checkpoint(trainer)
                    raise InterruptedError("Wstrzymano")

                epoch = trainer.epoch + 1
                raw_metrics = getattr(trainer, "metrics", {}) or {}
                metrics = {
                    "loss": float(trainer.loss.item()) if hasattr(trainer, "loss") else 0,
                    "map50": float(raw_metrics.get("metrics/mAP50(B)", 0) or 0),
                    "map50_95": float(raw_metrics.get("metrics/mAP50-95(B)", 0) or 0),
                    "precision": float(raw_metrics.get("metrics/precision(B)", 0) or 0),
                    "recall": float(raw_metrics.get("metrics/recall(B)", 0) or 0),
                    "box_map50": float(raw_metrics.get("metrics/mAP50(B)", 0) or 0),
                    "box_map50_95": float(raw_metrics.get("metrics/mAP50-95(B)", 0) or 0),
                    "box_precision": float(raw_metrics.get("metrics/precision(B)", 0) or 0),
                    "box_recall": float(raw_metrics.get("metrics/recall(B)", 0) or 0),
                    "pose_map50": float(raw_metrics.get("metrics/mAP50(P)", 0) or 0),
                    "pose_map50_95": float(raw_metrics.get("metrics/mAP50-95(P)", 0) or 0),
                    "pose_precision": float(raw_metrics.get("metrics/precision(P)", 0) or 0),
                    "pose_recall": float(raw_metrics.get("metrics/recall(P)", 0) or 0),
                }

                self._assert_finite_training_metrics(epoch, metrics)
                self.history.add_metrics(run.id, epoch, metrics)
                batch_state["completed_epoch"] = int(epoch)
                batch_state["batch"] = 0
                batch_state["total_batches"] = 0

                if self.on_epoch_end:
                    self.on_epoch_end(epoch, metrics)

                if self.on_progress:
                    self.on_progress((epoch / epochs) * 100, f"Epoka {epoch}/{epochs}")

            if start_with_ram_safe_profile:
                training_attempts = [
                    self._build_ram_safe_training_attempt(
                        batch_size=int(batch_size),
                        img_size=int(img_size),
                        lr0=float(lr0),
                        dataset_profile=dataset_profile,
                        label="ram_safe_preflight",
                    )
                ]
            else:
                training_attempts = [
                    {
                        "batch_size": int(batch_size),
                        "img_size": int(img_size),
                        "lr0": float(lr0),
                        "amp": (False if start_with_safe_pose_profile else True),
                        "mosaic": (0.0 if (disable_mosaic_from_start or start_with_safe_pose_profile) else None),
                        "close_mosaic": (0 if (disable_mosaic_from_start or start_with_safe_pose_profile) else None),
                        "plots": True,
                        "cache": False,
                        "label": "start",
                        "ram_safe": False,
                    }
                ]
            used_memory_fallback = False
            if not is_resuming and not start_with_ram_safe_profile:
                fallback_attempt = self._build_ram_safe_training_attempt(
                    batch_size=int(batch_size),
                    img_size=int(img_size),
                    lr0=float(lr0),
                    dataset_profile=dataset_profile,
                    label="oom_fallback",
                )
                if fallback_attempt != training_attempts[0]:
                    training_attempts.append(fallback_attempt)

            last_training_error = None
            for attempt_index, attempt in enumerate(training_attempts):
                if is_resuming:
                    logger.info(f"Wznawiam z: {resume_from}")
                    self.model = YoloClass(resume_from)
                else:
                    logger.info(f"Ładuję: {model_file}")
                    self.model = YoloClass(model_file)

                self.history.update_run(
                    run.id,
                    batch_size=int(attempt["batch_size"]),
                    img_size=int(attempt["img_size"]),
                    lr0=float(attempt["lr0"]),
                )
                try:
                    run.batch_size = int(attempt["batch_size"])
                    run.img_size = int(attempt["img_size"])
                    run.lr0 = float(attempt["lr0"])
                except Exception:
                    pass

                self.model.add_callback("on_train_epoch_start", on_train_epoch_start)
                self.model.add_callback("on_train_batch_end", on_train_batch_end)
                self.model.add_callback("on_train_epoch_end", on_train_epoch_end)

                if attempt_index > 0:
                    retry_msg = (
                        "Wykryto problem pamięci. Ponawiam trening na lżejszych ustawieniach: "
                        f"batch={int(attempt['batch_size'])}, imgsz={int(attempt['img_size'])}, "
                        "mosaic=0, amp=off, cache=off, plots=off."
                    )
                    logger.warning(retry_msg)
                    if self.on_progress:
                        self.on_progress(0.0, retry_msg)
                elif bool(attempt.get("ram_safe")):
                    logger.info(
                        "Start profilu RAM-safe: "
                        f"batch={int(attempt['batch_size'])}, imgsz={int(attempt['img_size'])}, "
                        "mosaic=0, amp=off, cache=off, plots=off."
                    )

                logger.info("Rozpoczynam trening...")
                try:
                    if (
                        not is_resuming
                        and attempt_index < (len(training_attempts) - 1)
                        and not bool(attempt.get("ram_safe"))
                    ):
                        ram_guard_state = sample_system_memory()
                        if self._is_ram_pressure_high(ram_guard_state, dataset_profile):
                            raise RuntimeError(
                                "not enough memory: RAM guard przed pierwszym batchem. "
                                f"{self._format_ram_state(ram_guard_state)}"
                            )
                    if is_resuming:
                        # Ultralytics oczekuje samej flagi resume=True przy wznawianiu treningu.
                        self.model.train(resume=True)
                    else:
                        train_args = self._build_train_args(
                            run,
                            dataset_path,
                            epochs,
                            int(attempt["batch_size"]),
                            int(attempt["img_size"]),
                            device,
                            float(attempt["lr0"]),
                            amp=bool(attempt["amp"]),
                            mosaic=attempt.get("mosaic"),
                            close_mosaic=attempt.get("close_mosaic"),
                            plots=bool(attempt.get("plots", True)),
                            cache=bool(attempt.get("cache", False)),
                        )
                        self.model.train(**train_args)
                    last_training_error = None
                    break
                except Exception as train_error:
                    last_training_error = train_error
                    progressed_batches = int(batch_state.get("batch", 0) or 0) > 0
                    can_retry = (
                        attempt_index < (len(training_attempts) - 1)
                        and not is_resuming
                        and not self.should_stop
                        and not self.should_pause
                        and self._is_training_memory_error(train_error)
                        and not self._is_cuda_runtime_broken_error(train_error)
                        and not progressed_batches
                    )
                    if can_retry:
                        used_memory_fallback = True
                        logger.warning(
                            "Trening przerwany przez błąd pamięci na ustawieniach: "
                            f"batch={int(attempt['batch_size'])}, imgsz={int(attempt['img_size'])}. "
                            "Czyszczę stan i próbuję ponownie."
                        )
                        self._reset_runtime_state()
                        continue
                    if progressed_batches and self._is_training_memory_error(train_error):
                        last_training_error = RuntimeError(
                            "Trening napotkał błąd pamięci (out of memory) już w trakcie realnej pracy na batchach. "
                            "Nie ponawiam próby w tym samym workerze, bo po takim OOM kolejne "
                            "starty w tym samym procesie często kończą się fałszywymi błędami "
                            "alokatora CPU/CUDA. Uruchom ponownie trening na lżejszych ustawieniach "
                            "(najlepiej w świeżym workerze)."
                        )
                        raise last_training_error
                    raise

            if last_training_error is not None:
                raise last_training_error

            runtime_epoch = self._resolve_runtime_epoch()
            if self.should_stop or self.should_pause:
                interrupted_status = TrainingStatus.PAUSED.value if self.should_pause else TrainingStatus.CANCELLED.value
                train_dir = Path(run.output_dir) / "train"
                last_weights = train_dir / "weights" / "last.pt"
                update_payload = {
                    "status": interrupted_status,
                    "current_epoch": runtime_epoch,
                    "last_weights": str(last_weights) if last_weights.exists() else "",
                }
                if self.should_pause:
                    update_payload["paused_at"] = datetime.now().isoformat()
                else:
                    update_payload["finished_at"] = datetime.now().isoformat()
                self.history.update_run(run.id, **update_payload)
                logger.info(
                    f"Trening zakończony przed czasem: status={interrupted_status}, epoka={runtime_epoch}/{epochs}"
                )
                if self.on_training_end:
                    self.on_training_end(False, "Wstrzymano" if self.should_pause else "Zatrzymano")
                return

            train_dir = Path(run.output_dir) / "train"
            best_weights = train_dir / "weights" / "best.pt"
            last_weights = train_dir / "weights" / "last.pt"

            self.history.update_run(
                run.id,
                status=TrainingStatus.COMPLETED.value,
                finished_at=datetime.now().isoformat(),
                best_weights=str(best_weights) if best_weights.exists() else "",
                last_weights=str(last_weights) if last_weights.exists() else "",
                current_epoch=max(epochs, self._resolve_runtime_epoch()),
            )
            self._export_training_report_artifacts(self.history.get_run(run.id) or run)
            # Błędy eksportu modelu nie powinny przerywać zakończonego treningu.
            try:
                if best_weights.exists():
                    import shutil
                    from ..campaign_manager import CAMPAIGN

                    final_map = float(self.history.get_run(run.id).best_map50) * 100
                    is_pose = "pose" in str(model_file).lower() or "plate" in run.name.lower()

                    # Zapisz model w katalogu modeli aktywnego projektu.
                    project_models_dir = CAMPAIGN.get_dir("models")
                    if project_models_dir is None:
                        # Fallback do globalnego katalogu modeli.
                        project_models_dir = Path(CONFIG.DIR_6_MODELS)

                    project_models_dir = Path(project_models_dir)

                    # Uporządkuj modele według typu zadania w nowym drzewie trained/<target>.
                    trained_root = project_models_dir / "trained"
                    if is_pose:
                        target_dir = trained_root / "plates"
                        task_tag = "plate"
                    else:
                        ds_path = str(run.dataset_path).lower()
                        if "char" in ds_path or "znak" in ds_path or "char" in run.name.lower():
                            target_dir = trained_root / "chars"
                            task_tag = "char"
                        else:
                            target_dir = trained_root / "vehicles"
                            task_tag = "vehicle"

                    target_dir.mkdir(parents=True, exist_ok=True)

                    safe_model_name = f"{task_tag}_{run.id}_map{int(final_map):02d}.pt"
                    target_path = (target_dir / safe_model_name).resolve()

                    logger.info("Kopiowanie najlepszego modelu:")
                    logger.info(f"   SRC: {best_weights}")
                    logger.info(f"   DST: {target_path}")

                    shutil.copy2(best_weights, target_path)
                    logger.info(f"[OK] Skopiowano najlepszy model do: {target_path.name}")

                    # =========================================================
                    # AUTO-WIRING: aktualizacja modeli aktywnego projektu
                    # =========================================================
                    active_proj = CAMPAIGN.get_active_project_name()
                    if active_proj:
                        if is_pose:
                            CAMPAIGN.set_global_model("plate", str(target_path))
                            logger.info("Menadżer Kampanii: Zaktualizowano model TABLIC.")
                        else:
                            if task_tag == "char":
                                CAMPAIGN.set_global_model("char", str(target_path))
                                logger.info("Menadżer Kampanii: Zaktualizowano model ZNAKÓW.")
                            else:
                                CAMPAIGN.set_global_model("vehicle", str(target_path))
                                logger.info("Menadżer Kampanii: Zaktualizowano model POJAZDÓW.")

                        # Sam udany trening nie domyka jeszcze iteracji kampanii.
                        # O zakończeniu etapu decyduje dopiero jawna akcja użytkownika w Z4.
                        if CAMPAIGN.get_current_step() >= 4:
                            logger.info("Menadzer Kampanii: Zapisano aktywny model projektu. Oczekiwanie na ręczne domknięcie iteracji w Z4.")

            except Exception as export_err:
                logger.warning(f"Nie udało się wyeksportować best.pt do katalogu modeli projektu: {export_err}")

            logger.info(f"Trening zakończony: {run.id}")

            if self.on_training_end:
                self.on_training_end(True, "Trening zakończony")

        except InterruptedError as e:
            status = TrainingStatus.PAUSED.value if self.should_pause else TrainingStatus.CANCELLED.value
            runtime_epoch = self._resolve_runtime_epoch()
            train_dir = Path(run.output_dir) / "train"
            last_weights = train_dir / "weights" / "last.pt"

            update_payload = {
                "status": status,
                "current_epoch": runtime_epoch,
                "last_weights": str(last_weights) if last_weights.exists() else "",
            }
            if self.should_pause:
                update_payload["paused_at"] = datetime.now().isoformat()
            else:
                update_payload["finished_at"] = datetime.now().isoformat()

            self.history.update_run(run.id, **update_payload)

            logger.info(f"Przerwano: {e}")
            if self.on_training_end:
                self.on_training_end(False, str(e))

        except Exception as e:
            if self._is_training_memory_error(e):
                logger.warning("Wykryto błąd pamięci. Czyszczę pamięć CUDA przed kolejną próbą treningu.")
                self._reset_runtime_state()

            logger.exception("Błąd treningu")
            error_text = str(e)
            if self._is_cuda_runtime_broken_error(e):
                error_text = (
                    "Bieżący proces treningu utracił sprawny stan CUDA. "
                    "Po takim błędzie kolejne próby GPU w tej samej sesji aplikacji mogą dalej się wywracać. "
                    "Zamknij i uruchom ponownie aplikację przed następną próbą na GPU.\n"
                    + error_text
                )
            if self._is_training_memory_error(e) and used_memory_fallback:
                error_text = (
                    "Trening został przerwany przez błąd pamięci mimo automatycznej próby "
                    "lżejszych ustawień (mniejszy batch, mniejszy imgsz, mosaic=0, amp=off).\n"
                    + error_text
                )
            epoch_state_text = self._format_runtime_epoch_state()
            if epoch_state_text:
                error_text = f"{error_text}\n\n{epoch_state_text}"

            runtime_epoch = self._resolve_runtime_epoch()
            train_dir = Path(run.output_dir) / "train"
            last_weights = train_dir / "weights" / "last.pt"
            last_weights_value = "" if self._is_nonfinite_training_error(e) else str(last_weights) if last_weights.exists() else ""
            self.history.update_run(
                run.id,
                status=TrainingStatus.FAILED.value,
                current_epoch=runtime_epoch,
                finished_at=datetime.now().isoformat(),
                best_weights="",
                last_weights=last_weights_value,
                error_message=error_text,
            )

            if self.on_training_end:
                self.on_training_end(False, error_text)

        finally:
            self.is_training = False
            self._training_batch_state = None
            self._reset_runtime_state()

    def _save_checkpoint(self, trainer):
        try:
            run = self.current_run
            checkpoint = Path(run.output_dir) / "train" / "weights" / "last.pt"

            try:
                save_model = getattr(trainer, "save_model", None)
                if callable(save_model) and self._is_runtime_epoch_complete():
                    save_model()
                elif callable(save_model):
                    logger.info(
                        "Pauza/zatrzymanie w trakcie niedomkniętej epoki. "
                        "Nie wymuszam zapisu checkpointu mid-epoch, aby nie oznaczyć "
                        "nieukończonej epoki jako ukończonej."
                    )
            except Exception as save_err:
                logger.warning(f"Nie udało się wymusić zapisu checkpointu pauzy: {save_err}")

            completed_epoch = self._resolve_runtime_epoch(trainer)
            last_weights_value = str(checkpoint) if checkpoint.exists() else str(getattr(run, "last_weights", "") or "")
            self.history.update_run(
                run.id,
                last_weights=last_weights_value,
                current_epoch=completed_epoch,
            )

            logger.info(f"Checkpoint: {last_weights_value or '[brak]'} | ukończone epoki: {completed_epoch}")

        except Exception as e:
            logger.error(f"Błąd checkpointu: {e}")

    def pause_training(self):
        if self.is_training:
            self.should_pause = True
            self._write_worker_control(pause=True)
            logger.info("Pauza...")

    def stop_training(self):
        if self.is_training:
            self.should_stop = True
            self._write_worker_control(stop=True)
            try:
                trainer = getattr(self.model, "trainer", None)
                if trainer is not None:
                    setattr(trainer, "stop", True)
            except Exception:
                pass
            logger.info("Stop...")

    def shutdown(self, wait_timeout: float = 0.8, terminate_timeout: float = 1.5, kill_timeout: float = 1.5):
        self.should_pause = False
        self.should_stop = True

        try:
            self._write_worker_control(pause=False, stop=True)
        except Exception:
            pass

        try:
            trainer = getattr(self.model, "trainer", None)
            if trainer is not None:
                setattr(trainer, "stop", True)
        except Exception:
            pass

        process = getattr(self, "_worker_process", None)
        if process is not None:
            try:
                if process.poll() is None:
                    try:
                        process.wait(timeout=max(0.0, float(wait_timeout or 0.0)))
                    except subprocess.TimeoutExpired:
                        logger.warning("Treningowy worker nie zamknął się po miękkim stopie. Wysyłam terminate().")
                        try:
                            process.terminate()
                        except Exception:
                            pass
                        try:
                            process.wait(timeout=max(0.0, float(terminate_timeout or 0.0)))
                        except subprocess.TimeoutExpired:
                            logger.warning("Treningowy worker nadal żyje. Wysyłam kill().")
                            try:
                                process.kill()
                            except Exception:
                                pass
                            try:
                                process.wait(timeout=max(0.0, float(kill_timeout or 0.0)))
                            except Exception:
                                pass
            except Exception as e:
                logger.debug(f"Nie udało się domknąć worker process podczas shutdownu: {e}")

        self.is_training = False
        self._reset_worker_ipc_state()
        self._reset_runtime_state()

    def resume_training(self, run_id: str) -> Optional[str]:
        run = self.history.get_run(run_id)
        if not run:
            return None

        if run.status not in [TrainingStatus.PAUSED.value, TrainingStatus.FAILED.value]:
            logger.error(f"Nie można wznowić: {run.status}")
            return None

        if self._is_nonfinite_training_error(RuntimeError(str(getattr(run, "error_message", "") or ""))):
            logger.error(
                "Nie można bezpiecznie wznowić tego runu: poprzedni trening wygenerował NaN/Inf "
                "albo checkpoint last.pt został oznaczony jako uszkodzony. Uruchom nowy trening "
                "z ostatniego poprawnego modelu bazowego albo lżejszych ustawień."
            )
            return None

        last_weights = str(run.last_weights or "").strip()
        if not last_weights or not Path(last_weights).exists():
            try:
                fallback_last = Path(str(run.output_dir or "")) / "train" / "weights" / "last.pt"
                if fallback_last.exists():
                    last_weights = str(fallback_last)
                    self.history.update_run(run.id, last_weights=last_weights)
                    run.last_weights = last_weights
            except Exception:
                pass
        if not last_weights or not Path(last_weights).exists():
            logger.error("Brak checkpointu")
            return None

        checkpoint_completed_epoch = self._resolve_completed_epoch_from_checkpoint(last_weights)
        if checkpoint_completed_epoch is not None:
            try:
                history_epoch = int(getattr(run, "current_epoch", 0) or 0)
            except Exception:
                history_epoch = 0
            if checkpoint_completed_epoch < history_epoch:
                logger.warning(
                    "Historia runu wskazywała epokę późniejszą niż checkpoint. "
                    f"Koryguję current_epoch: {history_epoch} -> {checkpoint_completed_epoch}."
                )
                self.history.update_run(run.id, current_epoch=int(checkpoint_completed_epoch))
                run.current_epoch = int(checkpoint_completed_epoch)

        target_epochs = max(
            int(getattr(run, "epochs", 0) or 0),
            int(getattr(run, "current_epoch", 0) or 0) + 1,
            1,
        )

        return self.start_training(
            name=run.name + " (wznowiony)",
            dataset_path=run.dataset_path,
            base_model=run.base_model,
            epochs=target_epochs,
            batch_size=run.batch_size,
            img_size=run.img_size,
            device=run.device,
            lr0=run.lr0,
            resume_from=last_weights,
        )
