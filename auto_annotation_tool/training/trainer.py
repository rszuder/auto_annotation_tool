#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trener modeli YOLO Pose.
"""

import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, Tuple

from ..config import CONFIG, logger, YOLO_AVAILABLE, CUDA_AVAILABLE, AVAILABLE_POSE_MODELS
from ..utils import cleanup_gpu_memory, safe_load_yaml
from .training_history import TrainingHistory, TrainingRun, TrainingStatus
from .training_report import TrainingReportGenerator  # <- NOWE

if YOLO_AVAILABLE:
    from ultralytics import YOLO


class YOLOPoseTrainer:
    """
    Trener modeli YOLO Pose.
    """

    def __init__(self, history: TrainingHistory = None):
        self.history = history or TrainingHistory()
        self.current_run: Optional[TrainingRun] = None
        self.model: Optional['YOLO'] = None

        self.is_training = False
        self.should_pause = False
        self.should_stop = False

        self.on_epoch_end: Optional[Callable[[int, Dict], None]] = None
        self.on_training_end: Optional[Callable[[bool, str], None]] = None
        self.on_progress: Optional[Callable[[float, str], None]] = None

    def get_available_models(self) -> Dict:
        return AVAILABLE_POSE_MODELS

    def get_latest_pose_model(self) -> str:
        priority = [
            "yolo26m-pose", "yolo26s-pose", "yolo26n-pose",
            "yolo11s-pose", "yolo11n-pose", "yolo11m-pose",
            "yolov8s-pose", "yolov8n-pose"
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
        stats = {"train_images": 0, "val_images": 0, "kpt_shape": None, "nc": 0}

        dataset_path = Path(dataset_path)
        yaml_file = dataset_path / "data.yaml"
        if not yaml_file.exists():
            return False, "Brak data.yaml", stats

        try:
            config = safe_load_yaml(yaml_file)
            
            # ✅ ZMIANA: kpt_shape jest OPCJONALNE (Zależne od tego, czy uczymy Pose czy Detect)
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
        **kwargs
    ) -> Optional[str]:
        if not YOLO_AVAILABLE:
            logger.error("YOLO niedostępny")
            return None

        if self.is_training:
            logger.warning("Trening już trwa")
            return None

        is_valid, msg, _ = self.validate_dataset(Path(dataset_path))
        if not is_valid:
            logger.error(f"Dataset: {msg}")
            return None

        # base_model może być: klucz (np. yolo26m-pose) albo ścieżka do .pt
        model_file = base_model
        if base_model in AVAILABLE_POSE_MODELS:
            model_file = AVAILABLE_POSE_MODELS[base_model]["file"]
        elif not str(base_model).lower().endswith(".pt"):
            model_file = f"{base_model}.pt"

        if resume_from:
            run_id = Path(resume_from).parent.parent.name
            self.current_run = self.history.get_run(run_id)
            if not self.current_run:
                logger.error(f"Nie znaleziono: {run_id}")
                return None

            self.history.update_run(
                run_id,
                status=TrainingStatus.RUNNING.value,
                started_at=datetime.now().isoformat()
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
                lr0=lr0  # ✅ DODANO LR
            )

        self.is_training = True
        self.should_pause = False
        self.should_stop = False

        thread = threading.Thread(
            target=self._training_loop,
            args=(model_file, dataset_path, epochs, batch_size, img_size, device, lr0, resume_from),
            daemon=True
        )
        thread.start()

        return self.current_run.id

    def _training_loop(self, model_file, dataset_path, epochs, batch_size, img_size, device, lr0, resume_from):
        run = self.current_run
        try:
            is_resuming = bool(resume_from and Path(resume_from).exists())
            
            if is_resuming:
                logger.info(f"Wznawiam z: {resume_from}")
                self.model = YOLO(resume_from)
            else:
                logger.info(f"Ładuję: {model_file}")
                self.model = YOLO(model_file)

            self.history.update_run(
                run.id,
                status=TrainingStatus.RUNNING.value,
                started_at=datetime.now().isoformat()
            )

            train_args = {
                "data": str(Path(dataset_path) / "data.yaml"),
                "epochs": epochs,
                "batch": batch_size,
                "imgsz": img_size,
                "device": 0 if device == "auto" and CUDA_AVAILABLE else device,
                "lr0": lr0,  # ✅ DODANO LR do opcji uczenia Ultralytics!
                "project": run.output_dir,
                "name": "train",
                "exist_ok": True,
                "pretrained": True,
                "verbose": True,
                "save": True,
                "save_period": 10,
                "patience": 50,
                "plots": True,   # <- to tworzy results.png, PR_curve.png itd.
                "workers": 0  # ✅ ZMIANA: Zablokowanie Multiprocessingu w Windows (BARDZO WAŻNE!)
            }

            def on_train_epoch_end(trainer):
                if self.should_stop:
                    raise InterruptedError("Zatrzymano")

                if self.should_pause:
                    self._save_checkpoint(trainer)
                    raise InterruptedError("Wstrzymano")

                epoch = trainer.epoch + 1
                metrics = {
                    "loss": float(trainer.loss.item()) if hasattr(trainer, 'loss') else 0,
                    "map50": float(trainer.metrics.get("metrics/mAP50(B)", 0)),
                    "map50_95": float(trainer.metrics.get("metrics/mAP50-95(B)", 0)),
                }

                self.history.add_metrics(run.id, epoch, metrics)

                if self.on_epoch_end:
                    self.on_epoch_end(epoch, metrics)

                if self.on_progress:
                    self.on_progress((epoch / epochs) * 100, f"Epoka {epoch}/{epochs}")

            self.model.add_callback("on_train_epoch_end", on_train_epoch_end)
            logger.info("Rozpoczynam trening...")
            # ✅ ZMIANA: Wznawianie treningu wymaga flagi resume=True bez innych parametrów
            if is_resuming:
                self.model.train(resume=True)
            else:
                self.model.train(**train_args)

            train_dir = Path(run.output_dir) / "train"
            best_weights = train_dir / "weights" / "best.pt"
            last_weights = train_dir / "weights" / "last.pt"

            self.history.update_run(
                run.id,
                status=TrainingStatus.COMPLETED.value,
                finished_at=datetime.now().isoformat(),
                best_weights=str(best_weights) if best_weights.exists() else "",
                last_weights=str(last_weights) if last_weights.exists() else "",
                current_epoch=epochs
            )
            # ✅ ZMIANA: Automatyczny eksport best.pt ORAZ aktualizacja Mózgu Kampanii!
            if best_weights.exists():
                import shutil
                from ..campaign_manager import CAMPAIGN # Pobieramy Menedżera!
                
                final_map = float(self.history.get_run(run.id).best_map50) * 100
                is_pose = "pose" in str(model_file).lower() or "plate" in run.name.lower()
                target_dir = CONFIG.DIR_6_MODELS_PLATES if is_pose else CONFIG.DIR_6_MODELS_CHARS
                
                new_model_name = f"V{epochs}ep_mAP{final_map:.0f}_{run.name}.pt"
                target_path = target_dir / new_model_name
                
                shutil.copy2(best_weights, target_path)
                logger.info(f"💾 Skopiowano najlepszy model do: {target_path.name}")
                
                # =========================================================
                # AUTO-WIRING (Automatyczna aktualizacja obecnego projektu)
                # =========================================================
                try:
                    active_proj = CAMPAIGN.get_active_project_name()
                    if active_proj:
                        if is_pose:
                            CAMPAIGN.set_global_model("plate", str(target_path))
                            logger.info("🧠 Menadżer: Zaktualizowano model TABLIC.")
                        else:
                            ds_path = str(run.dataset_path).lower()
                            if "char" in ds_path or "znak" in ds_path or "char" in run.name.lower():
                                CAMPAIGN.set_global_model("char", str(target_path))
                                logger.info("🧠 Menadżer: Zaktualizowano model ZNAKÓW.")
                            else:
                                CAMPAIGN.set_global_model("vehicle", str(target_path))
                                logger.info("🧠 Menadżer: Zaktualizowano model POJAZDÓW.")
                                
                        # ✅ ZMIANA: Zaliczenie całej Iteracji! Odblokowanie guzika "Nowa Iteracja"
                        if CAMPAIGN.get_current_step() == 4:
                            CAMPAIGN.set_current_step(5)
                            logger.info("🎉 Menadżer: Cykl zakończony. Odblokowano awans do nowej iteracji.")
                            
                except Exception as e:
                    logger.error(f"Nie udało się wpiąć modelu do Kampanii: {e}")

            logger.info(f"Trening zakończony: {run.id}")

            if self.on_training_end:
                self.on_training_end(True, "Trening zakończony")

        except InterruptedError as e:
            status = TrainingStatus.PAUSED.value if self.should_pause else TrainingStatus.CANCELLED.value

            self.history.update_run(
                run.id,
                status=status,
                paused_at=datetime.now().isoformat()
            )

            logger.info(f"Przerwano: {e}")
            if self.on_training_end:
                self.on_training_end(False, str(e))

        except Exception as e:
            logger.exception("Błąd treningu")

            self.history.update_run(
                run.id,
                status=TrainingStatus.FAILED.value,
                finished_at=datetime.now().isoformat(),
                error_message=str(e)
            )

            if self.on_training_end:
                self.on_training_end(False, str(e))

        finally:
            self.is_training = False
            self.model = None
            cleanup_gpu_memory()

    def _save_checkpoint(self, trainer):
        try:
            run = self.current_run
            checkpoint = Path(run.output_dir) / "train" / "weights" / "last.pt"

            self.history.update_run(
                run.id,
                last_weights=str(checkpoint),
                current_epoch=trainer.epoch + 1
            )

            logger.info(f"Checkpoint: {checkpoint}")

        except Exception as e:
            logger.error(f"Błąd checkpoint: {e}")

    def pause_training(self):
        if self.is_training:
            self.should_pause = True
            logger.info("Pauza...")

    def stop_training(self):
        if self.is_training:
            self.should_stop = True
            logger.info("Stop...")

    def resume_training(self, run_id: str) -> Optional[str]:
        run = self.history.get_run(run_id)
        if not run:
            return None

        if run.status not in [TrainingStatus.PAUSED.value, TrainingStatus.FAILED.value]:
            logger.error(f"Nie można wznowić: {run.status}")
            return None

        if not run.last_weights or not Path(run.last_weights).exists():
            logger.error("Brak checkpointu")
            return None

        remaining = run.epochs - run.current_epoch

        return self.start_training(
            name=run.name + " (wznowiony)",
            dataset_path=run.dataset_path,
            epochs=remaining,
            batch_size=run.batch_size,
            img_size=run.img_size,
            device=run.device,
            resume_from=run.last_weights
        )