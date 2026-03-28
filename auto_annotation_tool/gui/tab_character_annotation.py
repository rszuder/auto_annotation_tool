#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka ZNAKÓW.
Logicznie podzielona na:
1. Wycinanie tablic (surowe)
2. Wykrywanie znaków i Analiza (OCR/YOLO, Laboratorium Filtrów, Turniej z Cache)
3. Integracje i Dataset YOLO
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
from pathlib import Path, PurePosixPath
import threading
import xml.etree.ElementTree as ET
import json
import cv2
import requests
import os
import shutil

from ..config import CONFIG, logger
from ..campaign_manager import CAMPAIGN
from ..icons import IconManager
from ..character_recognition import PlateGenerator, CharacterDetector, DetectionMethod
from ..ocr import PlateOCR
from ..data_models import ImageAnnotation, Detection
from .help_manager import HELP

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

YOLO_REMOTE_URLS = {
    "yolo8n.pt":  "TU_WPISZ_URL",
    "yolo8s.pt":  "TU_WPISZ_URL",
    "yolo8m.pt":  "TU_WPISZ_URL",
    "yolo8l.pt":  "TU_WPISZ_URL",
    "yolo8x.pt":  "TU_WPISZ_URL",

    "yolo11n.pt": "TU_WPISZ_URL",
    "yolo11s.pt": "TU_WPISZ_URL",
    "yolo11m.pt": "TU_WPISZ_URL",
    "yolo11l.pt": "TU_WPISZ_URL",
    "yolo11x.pt": "TU_WPISZ_URL",

    "yolo26n.pt": "TU_WPISZ_URL",
    "yolo26s.pt": "TU_WPISZ_URL",
    "yolo26m.pt": "TU_WPISZ_URL",
    "yolo26l.pt": "TU_WPISZ_URL",
    "yolo26x.pt": "TU_WPISZ_URL",
}


class CharacterAnnotationTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        self.frame = ttk.Frame(parent)

        # core state
        self.is_processing = False
        self._step3_linear_mode = False

        # preview/cache state
        self.preview_metadata = {}
        self.preview_plate_ids = []
        self._listbox_pid_by_index = []
        self._current_photo = None
        self._reloading_preview = False



        # Cache kluczy dla przełączania runów i zmian plików.
        self._loaded_meta_path = None
        self._loaded_meta_mtime = None

        # Stan szybkiego testu OCR niezależny od procesu wycinania.
        self.fast_test_stop = threading.Event()
        self.fast_test_running = False
        self._project_reset_token = 0
        self._detection_log_visible = False
        self._source_binding_after_id = None
        self._source_binding_sync_in_progress = False

        # presets (global; later can be project-scoped)
        self.presets_dir = Path(CONFIG.WORKSPACE_DIR) / "8_ocr_presets"
        self.presets_dir.mkdir(parents=True, exist_ok=True)

        # local session
        self.session_file = Path.home() / ".auto_annotation_tool" / "char_tab_session.json"
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.local_session = self._load_local_session()

        def get_val(key, default):
            val = self.local_session.get(key, default)
            return val if val != "" else default

        # vars
        self.detection_method_var = tk.StringVar(value=get_val("char_det_method", "OCR"))
        self.xml_path_var = tk.StringVar(value=get_val("char_xml_path", ""))
        self.images_dir_var = tk.StringVar(value=get_val("char_images_dir", ""))
        self.yolo_model_path_var = tk.StringVar(value=get_val("char_yolo_model", ""))
        self.yolo_model_version_var = tk.StringVar(value=get_val("char_yolo_version", "11"))
        self.yolo_device_var = tk.StringVar(value=get_val("char_yolo_device", "auto"))
        self.yolo_model_size_var = tk.StringVar(value=get_val("char_yolo_size", "s"))
        self.yolo_conf_var = tk.DoubleVar(value=float(get_val("char_yolo_conf", 0.25)))
        self.yolo_iou_var = tk.DoubleVar(value=float(get_val("char_yolo_iou", 0.45)))
        self.yolo_overlap_var = tk.DoubleVar(value=float(get_val("char_yolo_overlap", 0.70)))
        self.yolo_agnostic_nms_var = tk.BooleanVar(value=bool(get_val("char_yolo_agnostic_nms", False)))
        self.preview_dir_var = tk.StringVar(value=get_val("char_preview_dir", ""))

        self.ocr_conf_var = tk.DoubleVar(value=float(get_val("char_ocr_conf", 0.25)))
        self.smart_export_var = tk.BooleanVar(value=get_val("char_smart_export", True))

        # lab params
        self.prep_angle_var = tk.DoubleVar(value=float(get_val("char_prep_angle", 0.0)))
        self.prep_height_var = tk.IntVar(value=int(get_val("char_prep_height", 80)))
        self.prep_padding_var = tk.IntVar(value=int(get_val("char_prep_padding", 20)))
        self.prep_clip_var = tk.IntVar(value=int(get_val("char_prep_clip", 255)))
        self.prep_denoise_var = tk.IntVar(value=int(get_val("char_prep_denoise", 0)))
        self.prep_clahe_var = tk.DoubleVar(value=float(get_val("char_prep_clahe", 0.0)))
        self.prep_use_bin_var = tk.BooleanVar(value=get_val("char_prep_use_bin", True))
        self.prep_block_var = tk.IntVar(value=int(get_val("char_prep_block", 15)))
        self.prep_c_var = tk.IntVar(value=int(get_val("char_prep_c", 5)))
        self.prep_erode_var = tk.IntVar(value=int(get_val("char_prep_erode", 0)))
        self.do_clahe_var = tk.BooleanVar(value=get_val("char_do_clahe", True))
        self.interpolation_var = tk.StringVar(value=get_val("char_interpolation", "lanczos4"))

        self._create_widgets()
        self._bind_source_path_watchers()
  
        self._update_step3_source_path_lock()
        self._update_preview_path_lock()
        self.reset_subtab_flow()
        self._schedule_source_binding_refresh(delay_ms=0)

        if not CAMPAIGN.get_active_project_name():
            self._clear_project_bound_session_values(clear_ui=True)
            self.reset_subtab_flow()

        self._update_yolo_visibility()
        self.app.root.bind("<Destroy>", self._on_app_close, add="+")
        if self.preview_dir_var.get().strip():
            self.frame.after(100, lambda: self._load_preview_data(quiet=True))

    # =========================================================
    # Small helpers
    # =========================================================

    def _reset_preview_cache(self):
        self.preview_metadata = {}
        self._loaded_meta_path = None
        self._loaded_meta_mtime = None

    def _char_record_to_symbol_and_x(self, rec, fallback_index: int = 0):
        symbol = ""
        x_key = float(fallback_index)

        if isinstance(rec, dict):
            symbol = str(
                rec.get("character")
                or rec.get("text")
                or rec.get("char")
                or ""
            )

            bbox = rec.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                try:
                    x_key = (float(bbox[0]) + float(bbox[2])) / 2.0
                except Exception:
                    pass

            return symbol, x_key

        if isinstance(rec, str):
            return rec, x_key

        try:
            symbol = str(getattr(rec, "character", getattr(rec, "text", "")) or "")
        except Exception:
            symbol = ""

        try:
            bbox = getattr(rec, "bbox", None)
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                x_key = (float(bbox[0]) + float(bbox[2])) / 2.0
        except Exception:
            pass

        return symbol, x_key
        
    def _find_latest_preview_run_dir(self) -> str:
        """
        Szuka najnowszej poprawnej paczki preview w katalogu chars projektu.
        Poprawna paczka to katalog zawierający:
        - metadata.json
        - images/
        """
        chars_root = getattr(self, "_campaign_chars_dir", None)
        if not chars_root:
            return ""

        root = Path(chars_root)
        if not root.exists() or not root.is_dir():
            return ""

        candidates = []
        try:
            for p in root.rglob("*"):
                if not p.is_dir():
                    continue

                meta_file = p / "metadata.json"
                images_dir = p / "images"

                if meta_file.exists() and images_dir.exists() and images_dir.is_dir():
                    candidates.append(p)
        except Exception:
            return ""

        if not candidates:
            return ""

        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])
        
    def _restore_preview_context_from_project(self):
        """
        Przywraca ostatnią paczkę preview projektu, jeśli istnieje.
        """
        preview_dir = self._find_latest_preview_run_dir()
        if not preview_dir:
            return False

        try:
            self.preview_dir_var.set(preview_dir)
            self._reset_preview_cache()
            self._load_preview_data(quiet=True)
            return True
        except Exception as e:
            logger.debug(f"Nie udało się przywrócić preview paczki projektu: {e}")
            return False
    
    def _ascii_progress_bar(self, current: int, total: int, width: int = 24) -> str:
        total = max(1, total)
        current = max(0, min(current, total))
        filled = int(round((current / total) * width))
        return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


    def _log_download_progress(self, label: str, downloaded: int, total: int):
        pct = (downloaded / total * 100.0) if total > 0 else 0.0
        bar = self._ascii_progress_bar(downloaded, total, width=24)

        try:
            self._set_test_status(f"Pobieranie modelu: {label} {pct:.1f}%", "warning")
        except Exception:
            pass

        self._log(
            self.test_log_text,
            f"[DOWNLOAD] {label} {bar} {pct:.1f}% ({downloaded}/{total} B)",
            "INFO"
        )


    def _download_file_with_progress(self, url: str, dst_path: Path, label: str):
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        self._log(self.test_log_text, f"[INFO] Rozpoczynam pobieranie modelu: {label}", "INFO")
        self._log(self.test_log_text, f"[INFO] Źródło: {url}", "INFO")

        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", "0") or "0")

            downloaded = 0
            last_logged_pct = -1

            with open(dst_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    pct = int(downloaded / total * 100) if total > 0 else -1
                    if total > 0 and pct >= last_logged_pct + 5:
                        last_logged_pct = pct
                        self.frame.after(
                            0,
                            lambda d=downloaded, t=total, lbl=label: self._log_download_progress(lbl, d, t)
                        )

        self._log(self.test_log_text, f"[SUCCESS] Pobieranie zakończone: {dst_path}", "SUCCESS")
    
    def _ascii_progress_bar(self, current: int, total: int, width: int = 24) -> str:
        total = max(1, total)
        current = max(0, min(current, total))
        filled = int(round((current / total) * width))
        return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


    def _sort_character_records_by_x(self, chars):
        if not isinstance(chars, list):
            return []

        prepared = []
        for i, rec in enumerate(chars):
            _, x_key = self._char_record_to_symbol_and_x(rec, fallback_index=i)
            prepared.append((x_key, i, rec))

        prepared.sort(key=lambda item: (item[0], item[1]))
        return [rec for _, _, rec in prepared]

    def _get_preview_box_records(self, data: dict):
        canonical_chars = self._sort_character_records_by_x(data.get("characters", []))
        yolo_raw = self._sort_character_records_by_x(data.get("yolo_detections", []))
        method_name = (self.detection_method_var.get() or "OCR").upper().strip()

        if method_name == "YOLO" and yolo_raw:
            return yolo_raw, "yolo"

        if method_name == "YOLO":
            yolo_from_canonical = [
                rec for rec in canonical_chars
                if isinstance(rec, dict) and str(rec.get("method", "")).strip().lower() == "yolo"
            ]
            if yolo_from_canonical:
                return self._sort_character_records_by_x(yolo_from_canonical), "yolo"

        return canonical_chars, "canonical"

    def _get_preview_box_palette(self, index: int):
        palettes = [
            ("#ff6b6b", "#ffc1c1", "#ffe9e9"),
            ("#4ecdc4", "#a6f4ef", "#e8fffd"),
            ("#ffd166", "#ffe29a", "#fff7db"),
            ("#6c5ce7", "#c8bfff", "#f0edff"),
            ("#00b894", "#7ee6ca", "#ebfff8"),
            ("#0984e3", "#74b9ff", "#ecf7ff"),
            ("#e17055", "#fab1a0", "#fff1ec"),
            ("#a29bfe", "#d6d1ff", "#f5f4ff"),
            ("#e84393", "#ffb0d5", "#fff0f7"),
            ("#2d98da", "#8fd0ff", "#eef8ff"),
        ]
        return palettes[index % len(palettes)]

    def _get_yolo_runtime_settings(self):
        conf = float(self.yolo_conf_var.get())
        iou = float(self.yolo_iou_var.get())
        overlap = float(self.yolo_overlap_var.get())

        if not (0.0 <= conf <= 1.0):
            raise ValueError("Próg confidence YOLO musi być w zakresie 0.00-1.00.")
        if not (0.01 <= iou <= 0.99):
            raise ValueError("Próg NMS IoU musi być w zakresie 0.01-0.99.")
        if not (0.0 <= overlap <= 1.0):
            raise ValueError("Próg nakładania boxów musi być w zakresie 0.00-1.00.")

        return {
            "conf": conf,
            "iou": iou,
            "overlap": overlap,
            "agnostic_nms": bool(self.yolo_agnostic_nms_var.get()),
        }


    def _characters_to_text(self, chars) -> str:
        if chars is None:
            return ""

        if isinstance(chars, str):
            return chars

        if not isinstance(chars, list):
            return str(chars)

        prepared = []
        for i, rec in enumerate(self._sort_character_records_by_x(chars)):
            symbol, x_key = self._char_record_to_symbol_and_x(rec, fallback_index=i)
            if symbol:
                prepared.append((x_key, symbol))

        prepared.sort(key=lambda item: item[0])
        return "".join(symbol for _, symbol in prepared)


    def _format_plate_listbox_label(self, plate_id: str, data: dict) -> str:
        status = str(data.get("status", "unknown")).strip().lower()
        chars_txt = self._characters_to_text(data.get("characters", []))

        if status == "perfect":
            icon = "🟢"
        elif status == "needs_fix":
            icon = "🔴"
        else:
            icon = "⚪"

        label = f"{icon} {plate_id}"
        if chars_txt:
            label += f" [{chars_txt}]"
        return label
    
    def _get_plate_row_foreground(self, status: str) -> str:
        status = str(status or "unknown").strip().lower()
        palette = getattr(self.app, "palette", {})

        if status == "perfect":
            return palette.get("success", "#27ae60")
        if status == "needs_fix":
            return palette.get("error", "#c0392b")
        return palette.get("muted_dim", "#444444")


    def _apply_plate_listbox_row_style(self, row_index: int, status: str):
        try:
            fg = self._get_plate_row_foreground(status)
            self.plates_listbox.itemconfig(
                row_index,
                foreground=fg,
                selectforeground="#ffffff"
            )
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stylu wiersza listy [{row_index}]: {e}")

    def _update_preview_info_label(self):
        try:
            perfect = 0
            needs_fix = 0
            unknown = 0

            for pid in self._listbox_pid_by_index:
                status = str(
                    self.preview_metadata.get(pid, {}).get("status", "unknown")
                ).strip().lower()

                if status == "perfect":
                    perfect += 1
                elif status == "needs_fix":
                    needs_fix += 1
                else:
                    unknown += 1

            self._set_preview_info(
                f"Wczytano tablic: {len(self._listbox_pid_by_index)} | {perfect} | {needs_fix} | ⚪ {unknown}",
                "info"
            )
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć preview_info_lbl: {e}")

    def _rebuild_preview_listbox(self, preserve_selection: bool = True):
        selected_pid = None

        if preserve_selection:
            try:
                sel = self.plates_listbox.curselection()
                if sel:
                    idx = sel[0]
                    if 0 <= idx < len(self._listbox_pid_by_index):
                        selected_pid = self._listbox_pid_by_index[idx]
            except Exception:
                selected_pid = None

        current_order = [pid for pid in self.preview_plate_ids if pid in self.preview_metadata]
        appended = [pid for pid in self.preview_metadata.keys() if pid not in current_order]
        self.preview_plate_ids = current_order + appended
        self._listbox_pid_by_index = list(self.preview_plate_ids)

        self._reloading_preview = True
        try:
            self.plates_listbox.delete(0, tk.END)
            for idx, pid in enumerate(self._listbox_pid_by_index):
                data = self.preview_metadata.get(pid, {})
                status = str(data.get("status", "unknown")).strip().lower()
                label = self._format_plate_listbox_label(pid, data)

                self.plates_listbox.insert(tk.END, label)
                self._apply_plate_listbox_row_style(idx, status)

            restore_idx = None
            if selected_pid and selected_pid in self._listbox_pid_by_index:
                restore_idx = self._listbox_pid_by_index.index(selected_pid)
            elif self._listbox_pid_by_index:
                restore_idx = 0

            if restore_idx is not None:
                self.plates_listbox.selection_clear(0, tk.END)
                self.plates_listbox.selection_set(restore_idx)
                self.plates_listbox.activate(restore_idx)
                self.plates_listbox.see(restore_idx)
                try:
                    self.frame.after_idle(
                        lambda: self.plates_listbox.event_generate("<<ListboxSelect>>")
                    )
                except Exception:
                    pass

            self._update_preview_info_label()

        finally:
            self._reloading_preview = False

    def _clear_project_bound_session_values(self, clear_ui: bool = False):
        """
        Usuwa z local_session ścieżki, które w trybie kampanii są sterowane przez Wizard.
        """
        project_bound_keys = (
            "char_xml_path",
            "char_images_dir",
            "char_preview_dir",
            "char_yolo_model",
        )

        for key in project_bound_keys:
            self.local_session.pop(key, None)

        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self.local_session, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

        if clear_ui:
            try:
                self.xml_path_var.set("")
            except Exception:
                pass
            try:
                self.images_dir_var.set("")
            except Exception:
                pass
            try:
                self.preview_dir_var.set("")
            except Exception:
                pass
            try:
                self.yolo_model_path_var.set("")
            except Exception:
                pass


    def _apply_preview_metadata_update(self, new_meta: dict, preserve_selection: bool = True):
        self.preview_metadata = new_meta
        self._rebuild_preview_listbox(preserve_selection=preserve_selection)

        try:
            self._on_preview_select(None)
        except Exception:
            pass


    def _refresh_plate_rows_in_place(self):
        """
        Odświeża TYLKO tekst istniejących wierszy listy tablic,
        bez przebudowy całego runu i bez resetowania selekcji.
        """
        try:
            self._reloading_preview = True

            # fallback: jeśli mapowanie indeks->pid nie istnieje, zbuduj je z preview_plate_ids
            if not getattr(self, "_listbox_pid_by_index", None):
                self._listbox_pid_by_index = list(self.preview_plate_ids)

            row_count = self.plates_listbox.size()
            pid_count = len(self._listbox_pid_by_index)
            limit = min(row_count, pid_count)

            for idx in range(limit):
                plate_id = self._listbox_pid_by_index[idx]
                data = self.preview_metadata.get(plate_id, {})
                status = str(data.get("status", "unknown")).strip().lower()
                label = self._format_plate_listbox_label(plate_id, data)

                try:
                    self.plates_listbox.delete(idx)
                    self.plates_listbox.insert(idx, label)
                    self._apply_plate_listbox_row_style(idx, status)
                except Exception:
                    pass

            # jeśli z jakiegoś powodu lista w UI była krótsza, dopełnij brakujące rekordy
            if pid_count > row_count:
                for idx in range(row_count, pid_count):
                    plate_id = self._listbox_pid_by_index[idx]
                    data = self.preview_metadata.get(plate_id, {})
                    status = str(data.get("status", "unknown")).strip().lower()
                    label = self._format_plate_listbox_label(plate_id, data)

                    try:
                        self.plates_listbox.insert(tk.END, label)
                        self._apply_plate_listbox_row_style(idx, status)
                    except Exception:
                        pass

            self._update_preview_info_label()

        finally:
            self._reloading_preview = False

    def _refresh_plates_listbox(self, preserve_selection: bool = True):
        """
        Wrapper kompatybilności.
        Kanoniczny pełny rebuild listy tablic wykonuje _rebuild_preview_listbox().
        """
        self._rebuild_preview_listbox(preserve_selection=preserve_selection)

    def _set_detection_process_log_visibility(self, visible: bool):
        self._detection_log_visible = bool(visible)

        try:
            if self._detection_log_visible:
                self.detection_log_frame.grid()
                self.btn_toggle_detection_log.config(text="Ukryj terminal")
            else:
                self.detection_log_frame.grid_remove()
                self.btn_toggle_detection_log.config(text="Pokaz terminal")
                self.btn_toggle_detection_log.config(text="Pokaż terminal")
        except Exception:
            pass

        try:
            self.btn_toggle_detection_log.config(
                text="Ukryj terminal" if self._detection_log_visible else "Pokaz terminal"
            )
        except Exception:
            pass

    def _toggle_detection_process_log(self):
        self._set_detection_process_log_visibility(
            not getattr(self, "_detection_log_visible", False)
        )



    def clear_campaign_context(self):
        """
        Czyści projektowy kontekst UI po wyjściu z projektu.
        Oprócz pól wejściowych czyści też preview, metadata, log testów
        i local_session powiązany z projektem.
        """
        self._project_reset_token += 1
        self.is_processing = False
        self._reloading_preview = False

        if hasattr(self, "_campaign_chars_dir"):
            self._campaign_chars_dir = None

        if hasattr(self, "_campaign_datasets_dir"):
            self._campaign_datasets_dir = None

        try:
            self._clear_project_bound_session_values(clear_ui=False)
        except Exception:
            pass

        try:
            self.xml_path_var.set("")
        except Exception:
            pass

        try:
            self.images_dir_var.set("")
        except Exception:
            pass

        try:
            self.preview_dir_var.set("")
        except Exception:
            pass

        try:
            self.yolo_model_path_var.set("")
        except Exception:
            pass

        self._reset_preview_cache()
        self.preview_metadata = {}
        self.preview_plate_ids = []
        self._listbox_pid_by_index = []

        try:
            self.plates_listbox.delete(0, tk.END)
        except Exception:
            pass

        try:
            self.preview_canvas.delete("all")
        except Exception:
            pass

        try:
            self._set_preview_info("Brak wczytanych danych", "muted")
        except Exception:
            pass

        try:
            self.test_log_text.configure(state=tk.NORMAL)
            self.test_log_text.delete("1.0", tk.END)
            self.test_log_text.configure(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self._set_detection_process_log_visibility(False)
        except Exception:
            pass

        try:
            self.fast_test_running = False
            self.fast_test_stop.set()
        except Exception:
            pass

        try:
            self.test_progress.config(value=0)
            self._set_test_progress_counter()
        except Exception:
            pass

        try:
            self._set_test_status("Gotowy do testów", "neutral")
        except Exception:
            pass

        try:
            self.ext_log.configure(state=tk.NORMAL)
            self.ext_log.delete("1.0", tk.END)
            self.ext_log.configure(state=tk.NORMAL)
        except Exception:
            pass

        try:
            self.ext_progress.config(value=0)
        except Exception:
            pass

        try:
            self._set_extraction_status("Gotowy", "neutral")
        except Exception:
            pass

        try:
            self.btn_extract.config(state=tk.NORMAL)
        except Exception:
            pass

        try:
            self.btn_ext_stop.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.import_cvat_xml_var.set("")
        except Exception:
            pass

        try:
            self._set_console_text(self.export_console, "Oczekuję na akcję...")
        except Exception:
            pass

        try:
            self._set_console_text(self.import_console, "Oczekuję na plik XML...")
        except Exception:
            pass

        try:
            self._set_winner_name("BRAK DANYCH Z TURNIEJU", "neutral")
        except Exception:
            pass

        try:
            self._set_winner_acc("Skuteczność detekcji OCR: 0.0%", "error")
        except Exception:
            pass

        try:
            if hasattr(self, "btn_finish_step3"):
                self.btn_finish_step3.config(
                    text="Zakończ krok 3 i wróć do Wizarda",
                    state=tk.DISABLED
                )
        except Exception:
            pass

        try:
            if hasattr(self, "btn_back_to_wizard_step3"):
                self.btn_back_to_wizard_step3.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self._set_button_emphasis("btn_finish_step3_frame", False)
        except Exception:
            pass

        try:
            self.reset_subtab_flow()
        except Exception as e:
            logger.debug(f"Nie udało się zresetować liniowego flow kroku 3: {e}")

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        console_border = palette.get("console_border", palette.get("border", "#3c3c3c"))

        for widget_name in ("ext_log", "test_log_text", "export_console", "import_console"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                self.app.style_text_widget(widget, role="console")
            except Exception:
                pass

        try:
            self.app.style_listbox_widget(self.plates_listbox, bordercolor=console_border)
            for idx, pid in enumerate(getattr(self, "_listbox_pid_by_index", [])):
                status = str(self.preview_metadata.get(pid, {}).get("status", "unknown")).strip().lower()
                self._apply_plate_listbox_row_style(idx, status)
        except Exception:
            pass

        try:
            self.app.style_canvas_widget(
                self.preview_canvas,
                background=palette.get("panel", "#1e1e1e"),
                bordercolor=console_border
            )
        except Exception:
            pass

        try:
            if hasattr(self, "detect_right_canvas"):
                self.detect_right_canvas.configure(
                    bg=palette.get("panel", "#252526"),
                    highlightbackground=console_border,
                    highlightcolor=console_border
                )
        except Exception:
            pass

        for frame_name in (
            "btn_to_detect_frame",
            "btn_run_detection_frame",
            "btn_run_detection_pulse_frame",
            "btn_to_dataset_frame",
            "btn_to_dataset_pulse_frame",
            "btn_finish_step3_frame",
            "btn_finish_step3_pulse_frame",
        ):
            frame = getattr(self, frame_name, None)
            if frame is None:
                continue
            try:
                frame.configure(bg=palette.get("bg", "#1f1f1f"))
            except Exception:
                pass

        for label_name, style_name in (
            ("cvat_option1_title_lbl", "PanelStatusError.TLabel"),
            ("cvat_option2_title_lbl", "PanelStatusSuccess.TLabel"),
            ("cvat_option1_desc_lbl", "PanelMuted.TLabel"),
            ("cvat_option2_desc_lbl", "PanelMuted.TLabel"),
            ("cvat_import_desc_lbl", "PanelMuted.TLabel"),
        ):
            label = getattr(self, label_name, None)
            if label is None or isinstance(label, tk.Label):
                continue
            try:
                label.configure(style=style_name)
            except Exception:
                pass

        inline_label_defaults = {
            "ext_status": ("neutral", True),
            "source_binding_status_lbl": ("warning", False),
            "test_status_lbl": ("neutral", True),
            "test_progress_count_lbl": ("muted", True),
            "winner_name_lbl": ("neutral", True),
            "winner_acc_lbl": ("muted", False),
            "preview_info_lbl": ("info", False),
            "footer_test_status_lbl": ("neutral", True),
            "cvat_option1_title_lbl": ("error", True),
            "cvat_option2_title_lbl": ("success", True),
            "cvat_option1_desc_lbl": ("muted", False),
            "cvat_option2_desc_lbl": ("muted", False),
            "cvat_import_title_lbl": ("default", True),
            "cvat_import_desc_lbl": ("muted", False),
        }

        for label_name, (default_tone, default_emphasis) in inline_label_defaults.items():
            label = getattr(self, label_name, None)
            if label is None or not isinstance(label, tk.Label):
                continue
            try:
                self._set_inline_status_label_state(
                    label,
                    text=label.cget("text"),
                    tone=getattr(label, "_inline_status_tone", default_tone),
                    emphasis=getattr(label, "_inline_status_emphasis", default_emphasis),
                )
            except Exception:
                pass

    def _sync_detect_right_scrollregion(self, event=None):
        if not hasattr(self, "detect_right_canvas") or self.detect_right_canvas is None:
            return

        try:
            self.detect_right_canvas.configure(scrollregion=self.detect_right_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_detect_right_canvas_width(self, event=None):
        if not hasattr(self, "detect_right_canvas") or self.detect_right_canvas is None:
            return

        try:
            width = max(50, int(self.detect_right_canvas.winfo_width()))
            self.detect_right_canvas.itemconfigure(self.detect_right_content_window, width=width)
        except Exception:
            pass

    def _widget_contains_point(self, widget, x_root: int, y_root: int) -> bool:
        if widget is None:
            return False
        try:
            wx = int(widget.winfo_rootx())
            wy = int(widget.winfo_rooty())
            return wx <= x_root < (wx + int(widget.winfo_width())) and wy <= y_root < (wy + int(widget.winfo_height()))
        except Exception:
            return False

    def _mousewheel_units(self, event) -> int:
        event_num = getattr(event, "num", None)
        if event_num == 4:
            return -1
        if event_num == 5:
            return 1

        delta = int(getattr(event, "delta", 0) or 0)
        if delta == 0:
            return 0
        if abs(delta) >= 120:
            units = -int(delta / 120)
        else:
            units = -1 if delta > 0 else 1
        return units if units != 0 else (-1 if delta > 0 else 1)

    def _detect_right_canvas_overflows(self) -> bool:
        canvas = getattr(self, "detect_right_canvas", None)
        if canvas is None:
            return False

        try:
            bbox = canvas.bbox("all")
            if not bbox:
                return False
            content_height = int(bbox[3]) - int(bbox[1])
            viewport_height = int(canvas.winfo_height())
            return content_height > viewport_height + 1
        except Exception:
            return False

    def _on_detect_right_global_mousewheel(self, event):
        canvas = getattr(self, "detect_right_canvas", None)
        if canvas is None:
            return None

        units = self._mousewheel_units(event)
        if units == 0:
            return None

        try:
            x_root = int(getattr(event, "x_root", 0) or self.frame.winfo_pointerx())
            y_root = int(getattr(event, "y_root", 0) or self.frame.winfo_pointery())
        except Exception:
            return None

        if not self._widget_contains_point(canvas, x_root, y_root):
            return None

        if not self._detect_right_canvas_overflows():
            return None

        try:
            canvas.yview_scroll(units, "units")
        except Exception:
            return "break"
        return "break"

    def _panel_style_name(self, tone: str = "neutral", emphasis: bool = False) -> str:
        tone_key = str(tone or "").strip().lower()
        if emphasis:
            return {
                "neutral": "PanelStatusNeutral.TLabel",
                "info": "PanelStatusInfo.TLabel",
                "success": "PanelStatusSuccess.TLabel",
                "warning": "PanelStatusWarning.TLabel",
                "error": "PanelStatusError.TLabel",
                "muted": "PanelStatusNeutral.TLabel",
            }.get(tone_key, "PanelStatusNeutral.TLabel")

        return {
            "neutral": "PanelMuted.TLabel",
            "muted": "PanelMuted.TLabel",
            "info": "PanelInfo.TLabel",
            "success": "PanelSuccess.TLabel",
            "warning": "PanelStatusWarning.TLabel",
            "error": "PanelError.TLabel",
        }.get(tone_key, "PanelMuted.TLabel")

    def _set_themed_label_state(self, widget, text: str | None = None, tone: str = "neutral", emphasis: bool = False):
        if widget is None:
            return

        config_kwargs = {"style": self._panel_style_name(tone=tone, emphasis=emphasis)}
        if text is not None:
            config_kwargs["text"] = text

        widget.config(**config_kwargs)

    def _set_inline_status_label_state(self, widget, text: str | None = None, tone: str = "neutral", emphasis: bool = False) -> bool:
        if widget is None or not isinstance(widget, tk.Label):
            return False

        palette = getattr(self.app, "palette", {})
        bg = palette.get("bg", "#1f1f1f")
        try:
            parent = widget.nametowidget(widget.winfo_parent())
        except Exception:
            parent = None

        for candidate in (parent, widget):
            if candidate is None:
                continue
            try:
                bg_candidate = candidate.cget("bg")
                if bg_candidate:
                    bg = bg_candidate
                    break
            except Exception:
                pass
            try:
                bg_candidate = candidate.cget("background")
                if bg_candidate:
                    bg = bg_candidate
                    break
            except Exception:
                pass
            try:
                style_name = candidate.winfo_class()
                bg_candidate = ttk.Style().lookup(style_name, "background")
                if bg_candidate:
                    bg = bg_candidate
                    break
            except Exception:
                pass

        tone_key = str(tone or "").strip().lower()
        fg = {
            "default": palette.get("fg", "#f3f3f3"),
            "neutral": palette.get("muted", "#9a9a9a"),
            "muted": palette.get("muted", "#9a9a9a"),
            "info": palette.get("info", palette.get("accent", "#4aa3ff")),
            "success": palette.get("success", "#2ecc71"),
            "warning": palette.get("warning", "#f39c12"),
            "error": palette.get("error", "#e74c3c"),
        }.get(tone_key, palette.get("muted", "#9a9a9a"))

        config_kwargs = {
            "bg": bg,
            "fg": fg,
            "font": ("Segoe UI", 10, "bold") if emphasis else ("Segoe UI", 9),
        }
        if text is not None:
            config_kwargs["text"] = text

        widget._inline_status_tone = tone_key
        widget._inline_status_emphasis = bool(emphasis)
        widget.config(**config_kwargs)
        return True

    def _set_extraction_status(self, text: str, tone: str = "neutral"):
        label = getattr(self, "ext_status", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=True):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=True)

    def _set_source_binding_status(self, text: str, tone: str = "warning"):
        label = getattr(self, "source_binding_status_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _set_test_status(self, text: str, tone: str = "neutral"):
        label = getattr(self, "test_status_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=True):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=True)

    def _set_test_progress_counter(self, current: int | None = None, total: int | None = None):
        label = getattr(self, "test_progress_count_lbl", None)
        if label is None:
            return

        if current is None or total is None or total <= 0:
            text = ""
            tone = "muted"
        else:
            current = max(0, min(int(current), int(total)))
            text = f"{current}/{int(total)}"
            tone = "info" if current < int(total) else "success"

        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=True):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=True)

    def _update_detection_progress_ui(self, current: int, total: int, session_token=None):
        if session_token is not None and session_token != self._project_reset_token:
            return

        pct = ((max(0, int(current)) / max(1, int(total))) * 100.0) if total else 0.0

        try:
            self.test_progress.config(value=pct)
        except Exception:
            pass

        self._set_test_progress_counter(current, total)
        self._set_test_status("Detekcja w toku", "warning")

    def _set_preview_info(self, text: str, tone: str = "info"):
        label = getattr(self, "preview_info_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _set_winner_name(self, text: str, tone: str = "neutral"):
        label = getattr(self, "winner_name_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=True):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=True)

    def _set_winner_acc(self, text: str, tone: str = "muted"):
        label = getattr(self, "winner_acc_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _get_campaign_char_model_path(self) -> str:
        """
        Zwraca ścieżkę do modelu znaków przypiętego do aktywnego projektu.
        """
        try:
            model_path = CAMPAIGN.get_global_model("char")
            if model_path and Path(model_path).exists():
                return str(Path(model_path))
        except Exception:
            pass
        return ""


    def _get_effective_yolo_model_path(self) -> str:
        """
        Zwraca rzeczywistą ścieżkę modelu YOLO używaną do detekcji.
        W trybie kampanii źródłem prawdy jest projekt, nie local session.
        """
        if getattr(self, "_step3_linear_mode", False):
            return self._get_campaign_char_model_path()

        raw = (self.yolo_model_path_var.get() or "").strip()
        if raw and raw != "Brak modelu znaków w projekcie" and Path(raw).exists():
            return raw
        return ""


    def _sync_yolo_model_binding(self):
        """
        Ustawia zawartość pola ścieżki modelu YOLO zgodnie z aktualnym trybem.
        """
        if getattr(self, "_step3_linear_mode", False):
            project_model = self._get_campaign_char_model_path()
            if project_model:
                self.yolo_model_path_var.set(project_model)
            else:
                self.yolo_model_path_var.set("Brak modelu znaków w projekcie")
        else:
            if (self.yolo_model_path_var.get() or "").strip() == "Brak modelu znaków w projekcie":
                self.yolo_model_path_var.set("")

    def _infer_yolo_arch_from_model_path(self, model_path: str):
        """
        Próbuje odczytać wydanie i rozmiar YOLO z nazwy pliku, np.:
        - yolo11s.pt
        - best_yolo26m.pt
        - chars_yolo8n_last.pt
        """
        raw = (model_path or "").strip().lower()
        if not raw:
            return None, None

        name = Path(raw).name.lower()

        import re
        match = re.search(r"yolo(8|11|26)([nsmlx])", name)
        if not match:
            return None, None

        version = match.group(1)
        size = match.group(2)
        return version, size
    def _on_yolo_arch_change(self, event=None):
        """
        Reaguje na zmianę wydania / rozmiaru YOLO.
        Nie nadpisuje panelu zwycięzcy turnieju OCR.
        """
        version = (self.yolo_model_version_var.get() or "").strip()
        size = (self.yolo_model_size_var.get() or "").strip().lower()

        if hasattr(self, "test_status_lbl"):
            self._set_test_status(f"Wybrana konfiguracja: YOLOv{version}{size}", "info")

    def _set_widget_state(self, widget, state: str):
        if widget is None:
            return
        try:
            widget.config(state=state)
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu widgetu: {e}")

    def _update_step3_source_path_lock(self):
        """
        W aktywnym, liniowym kroku 3 źródła wejściowe ustawia Wizard,
        więc użytkownik nie powinien ich ręcznie zmieniać.
        W trybie swobodnym pola mają być edytowalne.
        """
        locked = bool(getattr(self, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())

        entry_state = "disabled" if locked else "normal"
        button_state = "disabled" if locked else "normal"

        for attr_name in ("xml_path_entry", "images_dir_entry"):
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            try:
                widget.config(state=entry_state)
            except Exception as e:
                logger.debug(f"Nie udało się ustawić stanu {attr_name}: {e}")

        for attr_name in ("xml_path_browse_btn", "images_dir_browse_btn"):
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            try:
                widget.config(state=button_state)
            except Exception as e:
                logger.debug(f"Nie udało się ustawić stanu {attr_name}: {e}")

    def _bind_source_path_watchers(self):
        if getattr(self, "_source_binding_watchers_bound", False):
            return

        self._source_binding_watchers_bound = True
        for var in (self.xml_path_var, self.images_dir_var):
            try:
                var.trace_add("write", self._on_source_path_var_changed)
            except Exception as e:
                logger.debug(f"Nie udało się podpiąć watcherów źródeł Z3/PZ1: {e}")

    def _on_source_path_var_changed(self, *_args):
        if getattr(self, "_source_binding_sync_in_progress", False):
            return
        self._schedule_source_binding_refresh()

    def _schedule_source_binding_refresh(self, delay_ms: int = 150):
        if not hasattr(self, "frame") or self.frame is None:
            return

        pending = getattr(self, "_source_binding_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass

        self._source_binding_after_id = self.frame.after(delay_ms, self._refresh_source_binding_status)

    def _normalize_xml_image_relpath(self, raw_name: str) -> str:
        raw = str(raw_name or "").strip().replace("\\", "/")
        while raw.startswith("./"):
            raw = raw[2:]

        parts = [part for part in PurePosixPath(raw).parts if part not in ("", ".")]
        return "/".join(parts)

    def _xml_relpath_to_path(self, rel_path: str) -> Path:
        parts = [part for part in PurePosixPath(rel_path).parts if part not in ("", ".")]
        return Path(*parts) if parts else Path()

    def _read_xml_image_names(self, xml_path: Path) -> list[str]:
        tree = ET.parse(xml_path)
        names = []

        for image_el in tree.getroot().findall(".//image"):
            normalized = self._normalize_xml_image_relpath(image_el.get("name") or "")
            if normalized:
                names.append(normalized)

        return list(dict.fromkeys(names))

    def _evaluate_images_dir_for_xml(self, images_dir: Path, xml_image_names: list[str]) -> dict:
        matched = 0
        missing = []

        for rel_name in xml_image_names:
            candidate = images_dir / self._xml_relpath_to_path(rel_name)
            if candidate.exists() and candidate.is_file():
                matched += 1
            else:
                missing.append(rel_name)

        return {
            "images_dir": images_dir,
            "total": len(xml_image_names),
            "matched": matched,
            "missing_count": len(missing),
            "missing": missing,
        }

    def _summarize_missing_xml_images(self, missing: list[str], limit: int = 3) -> str:
        if not missing:
            return ""

        preview = ", ".join(missing[:limit])
        if len(missing) > limit:
            preview += ", ..."
        return f"Brakuje {len(missing)} plików z XML, np. {preview}."

    def _is_path_within(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    def _get_preferred_source_roots(self) -> list[Path]:
        roots = []

        try:
            campaign_raw = CAMPAIGN.get_dir("raw")
            if campaign_raw:
                roots.append(Path(campaign_raw))
        except Exception:
            pass

        try:
            roots.append(Path(CONFIG.DIR_1_RAW))
        except Exception:
            pass

        unique = []
        seen = set()
        for root in roots:
            try:
                resolved = str(root.resolve())
            except Exception:
                resolved = str(root)
            if resolved in seen:
                continue
            seen.add(resolved)
            if root.exists() and root.is_dir():
                unique.append(root)

        return unique

    def _is_recommended_images_dir(self, images_dir: Path) -> bool:
        for root in self._get_preferred_source_roots():
            if self._is_path_within(images_dir, root):
                return True
        return False

    def _derive_candidate_root_for_match(self, found_file: Path, xml_rel_name: str) -> Path | None:
        parts = [part for part in PurePosixPath(xml_rel_name).parts if part not in ("", ".")]
        if not parts:
            return None

        ascend_levels = len(parts) - 1
        parents = found_file.parents
        if ascend_levels >= len(parents):
            return None

        candidate_root = parents[ascend_levels]
        try:
            candidate_target = (candidate_root / self._xml_relpath_to_path(xml_rel_name)).resolve()
            if candidate_target != found_file.resolve():
                return None
        except Exception:
            return None

        return candidate_root

    def _find_matching_images_dir_for_xml(self, xml_image_names: list[str]) -> dict | None:
        if not xml_image_names:
            return None

        search_roots = self._get_preferred_source_roots()
        if not search_roots:
            return None

        sample_names = xml_image_names[: min(24, len(xml_image_names))]
        sample_by_basename = {}
        for rel_name in sample_names:
            sample_by_basename.setdefault(PurePosixPath(rel_name).name, []).append(rel_name)

        candidate_hits = {}

        for search_root in search_roots:
            try:
                for file_path in search_root.rglob("*"):
                    if not file_path.is_file():
                        continue

                    candidate_rel_names = sample_by_basename.get(file_path.name)
                    if not candidate_rel_names:
                        continue

                    for rel_name in candidate_rel_names:
                        candidate_root = self._derive_candidate_root_for_match(file_path, rel_name)
                        if candidate_root is None:
                            continue

                        try:
                            key = str(candidate_root.resolve())
                        except Exception:
                            key = str(candidate_root)

                        entry = candidate_hits.setdefault(
                            key,
                            {
                                "images_dir": candidate_root,
                                "sample_hits": set(),
                            },
                        )
                        entry["sample_hits"].add(rel_name)
            except Exception as e:
                logger.debug(f"Nie udało się przeskanować {search_root} podczas auto-odnajdywania paczki obrazów: {e}")

        if not candidate_hits:
            return None

        ranked_candidates = sorted(
            candidate_hits.values(),
            key=lambda item: (len(item["sample_hits"]), -len(str(item["images_dir"]))),
            reverse=True,
        )

        best_match = None
        best_score = None

        for candidate in ranked_candidates[:8]:
            stats = self._evaluate_images_dir_for_xml(candidate["images_dir"], xml_image_names)
            stats["sample_hits"] = len(candidate["sample_hits"])
            score = (stats["matched"], -stats["missing_count"], stats["sample_hits"])

            if best_match is None or score > best_score:
                best_match = stats
                best_score = score

        return best_match

    def _refresh_source_binding_status(self, allow_autofind: bool = True) -> dict:
        self._source_binding_after_id = None

        xml_raw = (self.xml_path_var.get() or "").strip()
        images_raw = (self.images_dir_var.get() or "").strip()
        base_note = "Plik annotations.xml i paczka obrazów są nierozerwalnie powiązane."

        result = {
            "ok": False,
            "tone": "warning",
            "message": "",
            "matched": 0,
            "total": 0,
            "missing_count": 0,
        }

        if not xml_raw:
            result["message"] = (
                f"{base_note} Wskaż annotations.xml, a system spróbuje odnaleźć właściwą paczkę w "
                "Workspace/1_raw_images/."
            )
            self._set_source_binding_status(result["message"], result["tone"])
            return result

        xml_path = Path(xml_raw)
        if not xml_path.exists():
            result["tone"] = "error"
            result["message"] = (
                f"Nie znaleziono pliku annotations.xml. {base_note} Wskaż poprawny XML wygenerowany dla tej samej paczki."
            )
            self._set_source_binding_status(result["message"], result["tone"])
            return result

        try:
            xml_image_names = self._read_xml_image_names(xml_path)
        except Exception as e:
            result["tone"] = "error"
            result["message"] = f"Nie mogę odczytać annotations.xml: {e}"
            self._set_source_binding_status(result["message"], result["tone"])
            return result

        if not xml_image_names:
            result["tone"] = "error"
            result["message"] = (
                "Ten plik XML nie zawiera listy obrazów, więc nie da się powiązać go z paczką źródłową."
            )
            self._set_source_binding_status(result["message"], result["tone"])
            return result

        current_images_dir = Path(images_raw) if images_raw else None
        current_stats = None

        if current_images_dir and current_images_dir.exists() and current_images_dir.is_dir():
            current_stats = self._evaluate_images_dir_for_xml(current_images_dir, xml_image_names)
        elif current_images_dir:
            result["tone"] = "error"
            result["message"] = (
                f"Nie znaleziono wskazanej paczki obrazów: {current_images_dir}. {base_note}"
            )

        best_candidate = None
        need_autofind = allow_autofind and (
            current_stats is None or current_stats["matched"] < current_stats["total"]
        )

        if need_autofind:
            best_candidate = self._find_matching_images_dir_for_xml(xml_image_names)
            if best_candidate and best_candidate["matched"] == best_candidate["total"]:
                candidate_dir = Path(best_candidate["images_dir"])
                same_as_current = False
                if current_images_dir:
                    try:
                        same_as_current = candidate_dir.resolve() == current_images_dir.resolve()
                    except Exception:
                        same_as_current = candidate_dir == current_images_dir

                if not same_as_current:
                    self._source_binding_sync_in_progress = True
                    try:
                        self.images_dir_var.set(str(candidate_dir))
                    finally:
                        self._source_binding_sync_in_progress = False
                    try:
                        self._force_save_all()
                    except Exception:
                        pass

                current_images_dir = candidate_dir
                current_stats = best_candidate
                result["auto_found"] = True

        if current_stats and current_stats["matched"] == current_stats["total"]:
            recommended = self._is_recommended_images_dir(Path(current_stats["images_dir"]))
            result.update(
                {
                    "ok": True,
                    "tone": "success" if recommended else "warning",
                    "matched": current_stats["matched"],
                    "total": current_stats["total"],
                    "missing_count": 0,
                }
            )

            if result.get("auto_found"):
                result["message"] = (
                    f"Powiązanie potwierdzone. Auto-odnaleziono paczkę obrazów: "
                    f"{current_stats['matched']}/{current_stats['total']} plików z XML w "
                    f"{current_stats['images_dir']}."
                )
            elif recommended:
                result["message"] = (
                    f"Powiązanie potwierdzone: {current_stats['matched']}/{current_stats['total']} plików z XML "
                    f"znaleziono w tej paczce obrazów."
                )
            else:
                result["message"] = (
                    f"Powiązanie XML-paczka jest poprawne ({current_stats['matched']}/{current_stats['total']}), "
                    f"ale źródła są poza Workspace/1_raw_images/. To działa w trybie swobodnym, lecz nie jest zalecane."
                )

            self._set_source_binding_status(result["message"], result["tone"])
            return result

        if current_stats:
            missing_hint = self._summarize_missing_xml_images(current_stats["missing"])
            result.update(
                {
                    "matched": current_stats["matched"],
                    "total": current_stats["total"],
                    "missing_count": current_stats["missing_count"],
                    "tone": "error",
                }
            )
            result["message"] = (
                f"Wybrana paczka obrazów nie pasuje do tego XML: znaleziono "
                f"{current_stats['matched']}/{current_stats['total']} wymaganych plików. {missing_hint}"
            ).strip()

            if best_candidate and best_candidate["matched"] > current_stats["matched"]:
                result["message"] += (
                    f" Najlepszy kandydat w Workspace/1_raw_images/ daje "
                    f"{best_candidate['matched']}/{best_candidate['total']} dopasowań."
                )

            self._set_source_binding_status(result["message"], result["tone"])
            return result

        if best_candidate and best_candidate["matched"] > 0:
            result.update(
                {
                    "matched": best_candidate["matched"],
                    "total": best_candidate["total"],
                    "missing_count": best_candidate["missing_count"],
                    "tone": "warning",
                    "message": (
                        f"Nie udało się jednoznacznie potwierdzić paczki obrazów. Najlepszy kandydat w "
                        f"Workspace/1_raw_images/ zawiera {best_candidate['matched']}/{best_candidate['total']} plików z XML."
                    ),
                }
            )
        elif not images_raw:
            result["message"] = (
                f"{base_note} Wskaż paczkę obrazów, na których wykonano anotacje. "
                "Jeśli leży w Workspace/1_raw_images/, system odnajdzie ją automatycznie."
            )

        self._set_source_binding_status(result["message"], result["tone"])
        return result

    def _count_preview_statuses(self):
        perfect = 0
        needs_fix = 0
        unknown = 0

        for _, data in self.preview_metadata.items():
            if not isinstance(data, dict):
                unknown += 1
                continue

            status = str(data.get("status", "unknown")).strip().lower()
            if status == "perfect":
                perfect += 1
            elif status == "needs_fix":
                needs_fix += 1
            else:
                unknown += 1

        return {
            "perfect": perfect,
            "needs_fix": needs_fix,
            "unknown": unknown,
            "total": perfect + needs_fix + unknown,
        }


    def _get_step3_summary_dir(self) -> Path:
        """
        Katalog, w którym zapisujemy podsumowanie kroku 3.
        Priorytet:
        1. aktywny run preview
        2. projektowy chars dir
        3. fallback do DIR_3_CHARS
        """
        preview_dir = Path(self.preview_dir_var.get().strip()) if self.preview_dir_var.get().strip() else None
        if preview_dir and preview_dir.exists():
            return preview_dir

        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if campaign_chars_dir:
            p = Path(campaign_chars_dir)
            p.mkdir(parents=True, exist_ok=True)
            return p

        fallback = Path(CONFIG.DIR_3_CHARS).absolute()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    
    def _is_valid_step3_training_dataset_dir(self, dataset_dir: Path | None) -> bool:
        """
        Sprawdza, czy katalog wygląda jak realny dataset treningowy znaków
        gotowy do użycia w etapie 4.
        """
        if dataset_dir is None:
            return False

        try:
            if not dataset_dir.exists() or not dataset_dir.is_dir():
                return False

            data_yaml = dataset_dir / "data.yaml"
            images_dir = dataset_dir / "images"
            labels_dir = dataset_dir / "labels"

            if not data_yaml.exists():
                return False

            if not images_dir.exists() or not images_dir.is_dir():
                return False

            if not labels_dir.exists() or not labels_dir.is_dir():
                return False

            return True
        except Exception:
            return False

    def _get_preferred_step3_training_dataset_dir(self) -> Path | None:
        """
        Zwraca najlepszy dostępny dataset znaków dla finału kroku 3.

        Priorytet:
        1. char_merged_pool
        2. najnowszy poprawny dataset z katalogu projektowych datasetów
        """
        merged_dir = self._get_char_merged_pool_dir()
        if self._is_valid_step3_training_dataset_dir(merged_dir):
            return merged_dir

        campaign_datasets_dir = getattr(self, "_campaign_datasets_dir", None)
        if not campaign_datasets_dir:
            return None

        ds_root = Path(campaign_datasets_dir)
        if not ds_root.exists() or not ds_root.is_dir():
            return None

        try:
            candidates = [
                p for p in ds_root.iterdir()
                if p.is_dir() and self._is_valid_step3_training_dataset_dir(p)
            ]
            if not candidates:
                return None

            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        except Exception:
            return None


    def _build_step3_export_summary(
        self,
        gold_dataset_path: str | None = None,
        review_pack_path: str | None = None,
        retry_pack_path: str | None = None,
        note: str = ""
    ):
        counts = self._count_preview_statuses()

        gold_exists = bool(gold_dataset_path and Path(gold_dataset_path).exists())
        review_exists = bool(review_pack_path and Path(review_pack_path).exists())
        retry_exists = bool(retry_pack_path and Path(retry_pack_path).exists())

        return {
            "gold_dataset_created": gold_exists,
            "gold_dataset_path": str(gold_dataset_path or ""),
            "review_pack_created": review_exists,
            "review_pack_path": str(review_pack_path or ""),
            "retry_pack_created": retry_exists,
            "retry_pack_path": str(retry_pack_path or ""),
            "perfect_count": counts["perfect"],
            "needs_fix_count": counts["needs_fix"],
            "unknown_count": counts["unknown"],
            "total_count": counts["total"],
            "note": note,
        }


    def _write_step3_export_summary(self, summary: dict) -> Path:
        summary_dir = self._get_step3_summary_dir()
        summary_path = summary_dir / "export_summary.json"
        self._atomic_write_json(summary_path, summary)
        return summary_path


    def _return_step3_result_to_wizard(self, summary: dict):
        """
        Jeden kontrakt zwrotny do wizarda:
        - jeśli istnieje gold dataset -> approve + krok 4
        - jeśli nie -> needs_rework
        """
        gold_ok = bool(summary.get("gold_dataset_created"))

        if gold_ok:
            CAMPAIGN.approve_step3()
            CAMPAIGN.set_current_step(4)
            status_msg = (
                "Krok 3 zakończony sukcesem. "
                "Powstał dataset treningowy i odblokowano etap 4."
            )
            status_kind = "success"
        else:
            CAMPAIGN.set_step3_needs_rework()
            status_msg = (
                "Krok 3 nie utworzył datasetu treningowego. "
                "Wracasz do wizarda w trybie poprawy."
            )
            status_kind = "warning"

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab:
                campaign_tab._rebuild_roadmap_ui()
                campaign_tab._refresh_dashboard()
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć Wizarda po kroku 3: {e}")

        try:
            self.app.select_tab("campaign")
            self.app.update_campaign_tab_access()
        except Exception as e:
            logger.debug(f"Nie udało się wrócić do Wizarda po kroku 3: {e}")

        try:
            self.app.update_status(status_msg, status_kind)
        except Exception:
            pass


    def _finalize_step3_from_existing_outputs(self):
        """
        Miękki finał kroku 3:
        - nie tworzy datasetu sam,
        - tylko ocenia to, co już istnieje po eksporcie z zakładki 3
        - zapisuje export_summary.json
        - zwraca wynik do wizarda
        """
        counts = self._count_preview_statuses()

        gold_dataset_path = ""
        review_pack_path = ""

        preferred_dataset_dir = self._get_preferred_step3_training_dataset_dir()
        if preferred_dataset_dir is not None:
            gold_dataset_path = str(preferred_dataset_dir)

        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if campaign_chars_dir:
            chars_root = Path(campaign_chars_dir)
            review_dir = chars_root / "review"
            if review_dir.exists():
                review_pack_path = str(review_dir)

        summary = self._build_step3_export_summary(
            gold_dataset_path=gold_dataset_path,
            review_pack_path=review_pack_path,
            retry_pack_path="",
            note="Finalizacja kroku 3 na podstawie najlepszego dostępnego datasetu znaków projektu (merged preferowany, fallback do istniejącego datasetu)."
        )

        self._write_step3_export_summary(summary)
        self._return_step3_result_to_wizard(summary)

    def _get_char_manual_pool_dir(self) -> Path | None:
        """
        Katalog na ręcznie poprawione paczki znaków importowane z CVAT.
        """
        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if not campaign_chars_dir:
            return None

        root = Path(campaign_chars_dir)
        root.mkdir(parents=True, exist_ok=True)

        pool_dir = root / "manual_char_pool"
        pool_dir.mkdir(parents=True, exist_ok=True)
        return pool_dir


    def _get_char_gold_pool_dir(self) -> Path | None:
        """
        Katalog na złotą paczkę znaków projektu.
        """
        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if not campaign_chars_dir:
            return None

        root = Path(campaign_chars_dir)
        root.mkdir(parents=True, exist_ok=True)

        pool_dir = root / "gold_char_pool"
        pool_dir.mkdir(parents=True, exist_ok=True)
        return pool_dir


    def _get_char_merged_pool_dir(self) -> Path | None:
        """
        Katalog na scaloną pulę znaków: gold + manual.
        """
        campaign_datasets_dir = getattr(self, "_campaign_datasets_dir", None)
        if not campaign_datasets_dir:
            return None

        root = Path(campaign_datasets_dir)
        root.mkdir(parents=True, exist_ok=True)

        pool_dir = root / "char_merged_pool"
        pool_dir.mkdir(parents=True, exist_ok=True)
        return pool_dir
    def _is_valid_step3_training_dataset_dir(self, dataset_dir: Path | None) -> bool:
        """
        Sprawdza, czy katalog wygląda jak realny dataset treningowy znaków
        gotowy do użycia w etapie 4.
        """
        if dataset_dir is None:
            return False

        try:
            if not dataset_dir.exists() or not dataset_dir.is_dir():
                return False

            data_yaml = dataset_dir / "data.yaml"
            images_dir = dataset_dir / "images"
            labels_dir = dataset_dir / "labels"

            if not data_yaml.exists():
                return False

            if not images_dir.exists() or not images_dir.is_dir():
                return False

            if not labels_dir.exists() or not labels_dir.is_dir():
                return False

            return True
        except Exception:
            return False

    def _get_preferred_step3_training_dataset_dir(self) -> Path | None:
        """
        Zwraca najlepszy dostępny dataset znaków dla finiszu kroku 3.

        Priorytet:
        1. char_merged_pool
        2. najnowszy poprawny dataset z katalogu projektowych datasetów
        """
        merged_dir = self._get_char_merged_pool_dir()
        if self._is_valid_step3_training_dataset_dir(merged_dir):
            return merged_dir

        campaign_datasets_dir = getattr(self, "_campaign_datasets_dir", None)
        if not campaign_datasets_dir:
            return None

        ds_root = Path(campaign_datasets_dir)
        if not ds_root.exists() or not ds_root.is_dir():
            return None

        try:
            candidates = [
                p for p in ds_root.iterdir()
                if p.is_dir() and self._is_valid_step3_training_dataset_dir(p)
            ]
            if not candidates:
                return None

            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        except Exception:
            return None
        
    def _get_project_review_dir(self) -> Path | None:
        """
        Projektowy katalog review dla eksportów CVAT z kroku 3.
        """
        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if not campaign_chars_dir:
            return None

        root = Path(campaign_chars_dir)
        root.mkdir(parents=True, exist_ok=True)

        review_dir = root / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        return review_dir
    def _store_current_preview_in_manual_char_pool(self, metadata: dict):
        """
        Zapisuje aktualnie poprawioną paczkę preview do manual_char_pool,
        aby mogła później zasilić trening modelu znaków.
        """
        manual_pool_dir = self._get_char_manual_pool_dir()
        if manual_pool_dir is None:
            raise RuntimeError("Brak katalogu manual_char_pool dla aktywnego projektu.")

        preview_dir = Path((self.preview_dir_var.get() or "").strip())
        if not preview_dir.exists() or not preview_dir.is_dir():
            raise RuntimeError("Brak poprawnego katalogu preview do zapisania w manual_char_pool.")

        preview_name = preview_dir.name if preview_dir.name else "manual_import"
        target_dir = manual_pool_dir / preview_name
        target_images_dir = target_dir / "images"

        target_dir.mkdir(parents=True, exist_ok=True)
        target_images_dir.mkdir(parents=True, exist_ok=True)

        # zapis metadata
        target_meta = target_dir / "metadata.json"
        self._atomic_write_json(target_meta, metadata)

        # kopiowanie obrazów źródłowych preview
        source_images_dir = preview_dir / "images"
        if source_images_dir.exists() and source_images_dir.is_dir():
            for img_file in source_images_dir.iterdir():
                if not img_file.is_file():
                    continue
                dst = target_images_dir / img_file.name
                shutil.copy2(img_file, dst)

        return target_dir
    def _has_char_manual_imports(self) -> bool:
        pool_dir = self._get_char_manual_pool_dir()
        if pool_dir is None or not pool_dir.exists():
            return False

        try:
            return any(p.exists() for p in pool_dir.iterdir())
        except Exception:
            return False


    def _has_char_gold_exports(self) -> bool:
        pool_dir = self._get_char_gold_pool_dir()
        if pool_dir is None or not pool_dir.exists():
            return False

        try:
            return any(p.exists() for p in pool_dir.iterdir())
        except Exception:
            return False
    def _has_any_step3_export_outputs(self) -> bool:
        """
        Krok 3 można zakończyć dopiero wtedy, gdy istnieje realny dataset
        treningowy znaków dla etapu 4.

        Sam review export do CVAT nie wystarcza.
        """
        try:
            return self._get_preferred_step3_training_dataset_dir() is not None
        except Exception:
            return False
    
    def _return_to_wizard_for_step3_rework(self):
        try:
            if CAMPAIGN.get_active_project_name():
                CAMPAIGN.set_current_step(3)
                CAMPAIGN.set_step3_needs_rework()
        except Exception as e:
            logger.debug(f"Nie udało się ustawić trybu poprawy kroku 3: {e}")

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab:
                campaign_tab._rebuild_roadmap_ui()
                campaign_tab._refresh_dashboard()
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć wizarda dla rework kroku 3: {e}")

        try:
            self.app.select_tab("campaign")
            self.app.update_campaign_tab_access()
            self.app.update_status(
                "Wracasz do wizarda w trybie poprawy kroku 3.",
                "warning"
            )
        except Exception as e:
            logger.debug(f"Nie udało się wrócić do wizarda dla rework kroku 3: {e}")

    def _resolve_guidance_button(self, attr_name: str):
        if not attr_name:
            return None

        candidates = [attr_name]
        if attr_name.endswith("_pulse_frame"):
            candidates.append(attr_name[:-12])
        if attr_name.endswith("_frame"):
            candidates.append(attr_name[:-6])

        for candidate in candidates:
            widget = getattr(self, candidate, None)
            if isinstance(widget, ttk.Button):
                return widget

        return None

    def _pulse_button_emphasis(self, frame_attr: str, pulses: int = 8, interval_ms: int = 260, color: str = "#f39c12"):
        btn = self._resolve_guidance_button(frame_attr)
        if btn is None:
            return

        try:
            self.app.pulse_button(btn, pulses=pulses, interval_ms=interval_ms, keep_emphasis=True)
        except Exception as e:
            logger.debug(f"Nie udało się pulsować przycisku dla {frame_attr}: {e}")

    def _update_step3_finish_button_state(self):
        btn = getattr(self, "btn_finish_step3", None)
        back_btn = getattr(self, "btn_back_to_wizard_step3", None)

        if btn is None:
            return

        enabled = self._has_any_step3_export_outputs()

        rework_return_mode = False
        try:
            rework_return_mode = bool(
                getattr(self, "_step3_linear_mode", False)
                and CAMPAIGN.get_active_project_name()
                and CAMPAIGN.get_step3_status() == "needs_rework"
                and not enabled
            )
        except Exception:
            rework_return_mode = False

        try:
            if rework_return_mode:
                btn.config(
                    text="Powrót do wizarda",
                    command=self._return_to_wizard_for_step3_rework,
                    state="normal"
                )
                self._set_button_emphasis("btn_finish_step3_frame", True)
                self._pulse_button_emphasis("btn_finish_step3_frame")

                if back_btn is not None:
                    back_btn.config(state="normal")
                return

            btn.config(
                text="Zakończ krok 3 i wróć do Wizarda",
                command=self._finalize_step3_from_existing_outputs,
                state=("normal" if enabled else "disabled")
            )

            if enabled:
                self._set_button_emphasis("btn_finish_step3_frame", True)
                self._pulse_button_emphasis("btn_finish_step3_frame")
            else:
                self._set_button_emphasis("btn_finish_step3_frame", False)

            if back_btn is not None:
                back_btn.config(state="disabled")

        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu btn_finish_step3: {e}")

    def _update_preview_path_lock(self):
        """
        W aktywnym, liniowym kroku 3 użytkownik nie powinien ręcznie
        zmieniać paczki preview ani ścieżki do niej.
        W trybie swobodnym pole ma być readonly, a przycisk aktywny.
        """
        locked = bool(getattr(self, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())

        try:
            if hasattr(self, "preview_dir_entry"):
                self.preview_dir_entry.config(state="disabled" if locked else "readonly")
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu preview_dir_entry: {e}")

        try:
            if hasattr(self, "preview_dir_browse_btn"):
                self.preview_dir_browse_btn.config(state="disabled" if locked else "normal")
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu preview_dir_browse_btn: {e}")

    def _set_button_state(self, attr_name: str, enabled: bool):
        btn = getattr(self, attr_name, None)
        if btn is None:
            return

        try:
            btn.config(state="normal" if enabled else "disabled")
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu przycisku '{attr_name}': {e}")       

    def _set_subtab_state(self, tab_widget, state: str):
        try:
            self.main_nb.tab(str(tab_widget), state=state)
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu podzakładki: {e}")

    def _get_subtab_state(self, tab_widget) -> str:
        try:
            return str(self.main_nb.tab(str(tab_widget), "state"))
        except Exception:
            return "normal"

    def _select_subtab(self, tab_widget):
        try:
            self.main_nb.select(str(tab_widget))
        except Exception as e:
            logger.debug(f"Nie udało się przełączyć podzakładki: {e}")

    # --- STEP3 NOTEBOOK PERSIST ---
    def _on_main_nb_tab_changed(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self.main_nb:
            return

        if not getattr(self, "_step3_linear_mode", False):
            return

        if not CAMPAIGN.get_active_project_name():
            return

        self._persist_step3_progress()

    def _sync_step3_nav_buttons(self):
        detect_enabled = self._get_subtab_state(self.tab_detect) == "normal"
        dataset_enabled = self._get_subtab_state(self.tab_dataset) == "normal"

        if hasattr(self, "btn_to_detect"):
            self.btn_to_detect.config(state=tk.NORMAL if detect_enabled else tk.DISABLED)

        if hasattr(self, "btn_to_dataset"):
            self.btn_to_dataset.config(state=tk.NORMAL if dataset_enabled else tk.DISABLED)

    def enter_campaign_step3_mode(self):
        """
        Start kroku 3 od początku.
        """
        CAMPAIGN.reset_step3_progress()
        self.restore_campaign_step3_mode()
        self._set_button_emphasis("btn_to_detect_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", False)
        try:
            self._sync_yolo_model_binding()
        except Exception:
            pass

    def reset_subtab_flow(self):
        """
        Stan neutralny poza liniowym workflow kampanii.
        W trybie swobodnym wszystkie podzakładki i przyciski nawigacyjne są dostępne.
        """
        self._step3_linear_mode = False

        # podzakładki
        self._set_subtab_state(self.tab_extract, "normal")
        self._set_subtab_state(self.tab_detect, "normal")
        self._set_subtab_state(self.tab_dataset, "normal")

        # nawigacja między podzakładkami ma działać w free mode
        self._set_button_state("btn_to_detect", True)
        self._set_button_state("btn_to_dataset", True)

        # akcje operacyjne też mają być aktywne
        self._set_button_state("btn_run_detection", True)
        self._set_button_state("btn_rank_presets", True)
        self._set_button_state("btn_ocr_lab", True)

        # zdejmij podświetlenia akcji
        self._set_button_emphasis("btn_to_detect_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", False)
        self._set_button_emphasis("btn_run_detection_frame", False)

        # odblokuj pola ścieżek
        try:
            self._update_preview_path_lock()
        except Exception:
            pass

        try:
            self._update_step3_source_path_lock()
        except Exception:
            pass

        try:
            self._update_yolo_visibility()
        except Exception:
            pass

        # wyczyść stan ostatniego testu
        try:
            self.test_progress.config(value=0)
            self._set_test_progress_counter()
        except Exception:
            pass

        try:
            self._set_test_status("Gotowy do testów", "neutral")
        except Exception:
            pass

        # jeśli konsola była zablokowana po teście, przywróć normalny stan logowania
        try:
            self.fast_test_running = False
            self.fast_test_stop.clear()
        except Exception:
            pass

    def unlock_detection_subtab(self):
        self._set_button_state("btn_to_detect", True)
        self._set_button_emphasis("btn_to_detect_frame", True)
        self._pulse_button_emphasis("btn_to_detect_frame")

        if self._step3_linear_mode:
            CAMPAIGN.set_step3_stage1_done(True)
            self._persist_step3_progress()
        

    def unlock_dataset_subtab(self):
        self._set_button_state("btn_to_dataset", True)
        self._set_button_emphasis("btn_run_detection_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", True)
        self._pulse_button_emphasis("btn_to_dataset_frame")

        if self._step3_linear_mode:
            CAMPAIGN.set_step3_stage2_done(True)
            self._persist_step3_progress()

    def go_to_substep_2(self):
        if self._step3_linear_mode:
            btn = getattr(self, "btn_to_detect", None)
            if btn is not None and str(btn.cget("state")) != "normal":
                return

            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "normal")
            self._set_subtab_state(self.tab_dataset, "disabled")

            CAMPAIGN.set_step3_substep(2)

        self._select_subtab(self.tab_detect)
        self._persist_step3_progress()
        self._pulse_button_emphasis("btn_run_detection_frame")

    def go_to_substep_3(self):
        if self._step3_linear_mode:
            btn = getattr(self, "btn_to_dataset", None)
            if btn is not None and str(btn.cget("state")) != "normal":
                return

            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "normal")

            CAMPAIGN.set_step3_substep(3)

        self._select_subtab(self.tab_dataset)
        self._persist_step3_progress()
        self._set_button_emphasis("btn_run_detection_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", False)

    def back_to_substep_1(self):
        """
        Cofnięcie do 1 blokuje 2 i 3 tylko w trybie kampanii.
        """
        if self._step3_linear_mode:
            self._set_subtab_state(self.tab_extract, "normal")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "disabled")
            self._set_button_state("btn_to_detect", False)
            self._set_button_state("btn_to_dataset", False)

            self._set_button_emphasis("btn_to_detect_frame", False)
            self._set_button_emphasis("btn_to_dataset_frame", False)

            CAMPAIGN.set_step3_substep(1)

        self._select_subtab(self.tab_extract)
        self._persist_step3_progress()


    def back_to_substep_2(self):
        """
        Cofnięcie do 2 blokuje 3 tylko w trybie kampanii.
        """
        if self._step3_linear_mode:
            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "normal")
            self._set_subtab_state(self.tab_dataset, "disabled")
            self._set_button_state("btn_to_dataset", False)

            self._set_button_emphasis("btn_to_dataset_frame", False)

            CAMPAIGN.set_step3_substep(2)

        self._select_subtab(self.tab_detect)
        self._persist_step3_progress()
        self._pulse_button_emphasis("btn_run_detection_frame")

    def _persist_step3_progress(self):
        if not getattr(self, "_step3_linear_mode", False):
            return

        current_substep = 1
        try:
            selected = str(self.main_nb.select())
            if selected == str(self.tab_extract):
                current_substep = 1
            elif selected == str(self.tab_detect):
                current_substep = 2
            elif selected == str(self.tab_dataset):
                current_substep = 3
        except Exception:
            current_substep = 1

        CAMPAIGN.set_step3_substep(current_substep)

        stage1_done = False
        stage2_done = False

        try:
            btn = getattr(self, "btn_to_detect", None)
            if btn is not None:
                stage1_done = str(btn.cget("state")) == "normal"
        except Exception:
            pass

        try:
            btn = getattr(self, "btn_to_dataset", None)
            if btn is not None:
                stage2_done = str(btn.cget("state")) == "normal"
        except Exception:
            pass

        CAMPAIGN.set_step3_stage1_done(stage1_done)
        CAMPAIGN.set_step3_stage2_done(stage2_done)


    def restore_campaign_step3_mode(self):
        """
        Przywraca zapisany postęp kroku 3 aktywnego projektu.
        """
        self._step3_linear_mode = True

        saved_substep = CAMPAIGN.get_step3_substep()
        stage1_done = CAMPAIGN.is_step3_stage1_done()
        stage2_done = CAMPAIGN.is_step3_stage2_done()

        if saved_substep > 1 and not (self.preview_dir_var.get() or "").strip():
            try:
                self._restore_preview_context_from_project()
            except Exception:
                pass        
        # jeśli zapisany stan nie ma pokrycia w realnych artefaktach, wracamy do substepu 1
        if not self.can_restore_step3_substep(saved_substep):
            saved_substep = 1
            stage1_done = False
            stage2_done = False

            try:
                CAMPAIGN.reset_step3_progress()
            except Exception:
                pass

        self._set_button_state("btn_to_detect", stage1_done)
        self._set_button_state("btn_to_dataset", stage2_done)

        if saved_substep <= 1:
            self._set_subtab_state(self.tab_extract, "normal")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "disabled")
            self._select_subtab(self.tab_extract)

        elif saved_substep == 2:
            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "normal")
            self._set_subtab_state(self.tab_dataset, "disabled")
            self._select_subtab(self.tab_detect)

        else:
            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "normal")
            self._select_subtab(self.tab_dataset)

        self._set_button_emphasis("btn_run_detection_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", False)

        if saved_substep == 2 and not stage2_done:
            self._set_button_emphasis("btn_run_detection_frame", True)
            self._pulse_button_emphasis("btn_run_detection_frame")
        elif saved_substep == 2 and stage2_done:
            self._set_button_emphasis("btn_to_dataset_frame", True)
            self._pulse_button_emphasis("btn_to_dataset_frame")
        elif saved_substep == 3:
            self._update_step3_finish_button_state()

        try:
            self._update_preview_path_lock()
        except Exception:
            pass

        try:
            self._update_step3_source_path_lock()
        except Exception:
            pass

        try:
            self._sync_yolo_model_binding()
        except Exception:
            pass

        try:
            self._update_yolo_visibility()
        except Exception:
            pass

        try:
            self._update_step3_finish_button_state()
        except Exception:
            pass      

    def can_restore_step3_substep(self, substep: int) -> bool:
        """
        Sprawdza, czy dla zapisanego substepu istnieją realne artefakty
        pozwalające wejść do tego miejsca workflow.
        """
        substep = int(substep)

        # substep 1 zawsze można otworzyć, jeśli mamy źródła z wizarda
        if substep <= 1:
            xml_ok = bool((self.xml_path_var.get() or "").strip())
            img_ok = bool((self.images_dir_var.get() or "").strip())
            return xml_ok and img_ok

        # substep 2 i 3 wymagają paczki preview z metadata i katalogiem images
        preview_dir_raw = (self.preview_dir_var.get() or "").strip()
        if not preview_dir_raw:
            return False

        preview_dir = Path(preview_dir_raw)
        if not preview_dir.exists() or not preview_dir.is_dir():
            return False

        meta_file = preview_dir / "metadata.json"
        images_dir = preview_dir / "images"

        if not meta_file.exists():
            return False

        if not images_dir.exists() or not images_dir.is_dir():
            return False

        # substep 3 dodatkowo wymaga, żeby etap 2 był realnie zakończony
        if substep >= 3:
            try:
                return bool(CAMPAIGN.is_step3_stage2_done())
            except Exception:
                return False

        return True

    def _atomic_write_json(self, path: Path, data: dict):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def _load_local_session(self):
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_local_setting(self, key, value):
        self.local_session[key] = value
        try:
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(self.local_session, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def _force_save_all(self):
        try:
            always_saved = [
                ("char_det_method", self.detection_method_var),
                ("char_yolo_device", self.yolo_device_var),
                ("char_yolo_size", self.yolo_model_size_var),
                ("char_yolo_version", self.yolo_model_version_var),
                ("char_yolo_conf", self.yolo_conf_var),
                ("char_yolo_iou", self.yolo_iou_var),
                ("char_yolo_overlap", self.yolo_overlap_var),
                ("char_yolo_agnostic_nms", self.yolo_agnostic_nms_var),
                ("char_ocr_conf", self.ocr_conf_var),
                ("char_smart_export", self.smart_export_var),
                ("char_prep_angle", self.prep_angle_var),
                ("char_prep_height", self.prep_height_var),
                ("char_prep_padding", self.prep_padding_var),
                ("char_prep_clip", self.prep_clip_var),
                ("char_prep_denoise", self.prep_denoise_var),
                ("char_prep_clahe", self.prep_clahe_var),
                ("char_prep_use_bin", self.prep_use_bin_var),
                ("char_prep_block", self.prep_block_var),
                ("char_prep_c", self.prep_c_var),
                ("char_prep_erode", self.prep_erode_var),
                ("char_do_clahe", self.do_clahe_var),
                ("char_interpolation", self.interpolation_var),
            ]

            for k, var in always_saved:
                self._save_local_setting(k, var.get())

            # ścieżki wejściowe zapisujemy tylko poza liniowym workflow kampanii
            if not getattr(self, "_step3_linear_mode", False):
                for k, var in [
                    ("char_xml_path", self.xml_path_var),
                    ("char_images_dir", self.images_dir_var),
                    ("char_yolo_model", self.yolo_model_path_var),
                    ("char_preview_dir", self.preview_dir_var),
                ]:
                    self._save_local_setting(k, var.get())

        except Exception:
            pass

    def _on_app_close(self, event):
        if str(event.widget) == str(self.app.root):
            self._force_save_all()

    def _on_method_change(self, event=None):
        self._update_yolo_visibility()

    def _update_yolo_visibility(self):
        if not hasattr(self, "yolo_panel"):
            return

        method = (self.detection_method_var.get() or "OCR").upper().strip()

        try:
            self._sync_yolo_model_binding()
        except Exception:
            pass

        is_ocr = method == "OCR"
        is_yolo = method == "YOLO"
        is_hybrid = method == "BOTH"

        # panel YOLO pokazujemy dla YOLO i HYBRYDY
        if is_yolo or is_hybrid:
            self.yolo_panel.pack(fill=tk.X, pady=(5, 0))
        else:
            self.yolo_panel.pack_forget()

        # comboboxy architektury YOLO aktywne tylko dla YOLO/BOTH
        if hasattr(self, "yolo_version_combo"):
            self._set_widget_state(
                self.yolo_version_combo,
                "readonly" if (is_yolo or is_hybrid) else "disabled"
            )

        if hasattr(self, "yolo_size_combo"):
            self._set_widget_state(
                self.yolo_size_combo,
                "readonly" if (is_yolo or is_hybrid) else "disabled"
            )

        for attr_name in ("yolo_conf_spin", "yolo_iou_spin", "yolo_overlap_spin"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                self._set_widget_state(
                    widget,
                    "normal" if (is_yolo or is_hybrid) else "disabled"
                )

        if hasattr(self, "yolo_agnostic_nms_chk"):
            self._set_widget_state(
                self.yolo_agnostic_nms_chk,
                "normal" if (is_yolo or is_hybrid) else "disabled"
            )

        # w trybie kampanii ścieżka modelu jest sterowana z Wizarda
        path_locked = bool(getattr(self, "_step3_linear_mode", False))

        if hasattr(self, "det_yolo_model_entry"):
            self._set_widget_state(
                self.det_yolo_model_entry,
                "disabled" if path_locked else "readonly"
            )

        if hasattr(self, "det_yolo_model_browse_btn"):
            self._set_widget_state(
                self.det_yolo_model_browse_btn,
                "disabled" if path_locked else "normal"
            )

        # Laboratorium OCR:
        # - OCR: aktywne
        # - YOLO: nieaktywne
        # - BOTH: aktywne
        if hasattr(self, "btn_ocr_lab"):
            self._set_widget_state(self.btn_ocr_lab, "disabled" if is_yolo else "normal")

        # Turniej presetów OCR:
        # - tylko dla czystego OCR
        if hasattr(self, "btn_rank_presets"):
            self._set_widget_state(self.btn_rank_presets, "normal" if is_ocr else "disabled")

        # Panel zwycięzcy rankingu dotyczy wyłącznie rankingu OCR.
        # YOLO i HYBRYDA nie mogą podszywać się pod "zwycięzcę turnieju".
        if hasattr(self, "winner_name_lbl") and hasattr(self, "winner_acc_lbl"):
            if is_ocr:
                self._update_winner_label()
            elif is_yolo:
                self._set_winner_name("Brak rankingu OCR", "neutral")
                self._set_winner_acc("Tryb YOLO nie bierze udziału w turnieju OCR", "muted")
            else:  # BOTH
                self._set_winner_name("Brak rankingu OCR", "neutral")
                self._set_winner_acc("Tryb hybrydowy nie ustala zwycięzcy turnieju OCR", "muted")

        # Status dolny ma pokazywać, co użytkownik może teraz zrobić
        if hasattr(self, "test_status_lbl"):
            if is_yolo:
                version = (self.yolo_model_version_var.get() or "").strip()
                size = (self.yolo_model_size_var.get() or "").strip().lower()
                self._set_test_status(
                    f"Tryb YOLO: wybierz konfigurację i użyj 'Uruchom detekcję' (YOLOv{version}{size})",
                    "muted"
                )
            elif is_hybrid:
                version = (self.yolo_model_version_var.get() or "").strip()
                size = (self.yolo_model_size_var.get() or "").strip().lower()
                self._set_test_status(
                    f"Tryb hybrydowy: uruchom wspólną detekcję (YOLOv{version}{size} + OCR)",
                    "info"
                )
            else:
                self._set_test_status(
                    "Tryb OCR: możesz uruchomić detekcję lub turniej presetów OCR",
                    "success"
                )

    def _auto_device_label(self) -> str:
        return "auto (prefer GPU/CUDA, fallback CPU)"

    def _get_available_devices(self):
        devices = [self._auto_device_label(), "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    name = torch.cuda.get_device_name(i)
                    devices.append(f"cuda:{i} ({name})")
        except Exception:
            pass
        return devices

    def _normalize_selected_device(self, raw_value: str | None = None, devices=None) -> str:
        available = list(devices or self._get_available_devices())
        current = str(raw_value if raw_value is not None else self.yolo_device_var.get() or "").strip()
        current_lower = current.lower()

        if not current or current_lower.startswith("auto"):
            return available[0] if available else "auto"
        if current_lower.startswith("cpu"):
            return "cpu"
        if current_lower.startswith("cuda:"):
            prefix = current.split()[0]
            for option in available:
                if option.startswith(prefix):
                    return option

        return current if current in available else (available[0] if available else "auto")

    def _refresh_device_options(self):
        devices = self._get_available_devices()
        if hasattr(self, "det_device_combo"):
            try:
                self.det_device_combo.configure(values=devices)
            except Exception:
                pass

        normalized = self._normalize_selected_device(devices=devices)
        if normalized:
            self.yolo_device_var.set(normalized)

        self._update_device_hint()

    def _device_to_ultralytics(self, s: str):
        raw = str(s or "").strip().lower()
        if not raw or raw.startswith("auto"):
            try:
                import torch
                if torch.cuda.is_available():
                    return 0
            except Exception:
                pass
            return "cpu"
        if raw.startswith("cpu"):
            return "cpu"
        if raw.startswith("cuda:"):
            try:
                return int(str(s).split(":")[1].split()[0])
            except Exception:
                return 0
        return "cpu"

    def _device_to_ocr(self, s: str) -> str:
        return "cuda" if self._device_to_ultralytics(s) != "cpu" else "cpu"

    def _update_device_hint(self, event=None):
        label = getattr(self, "det_device_hint_lbl", None)
        if label is None:
            return

        devices = self._get_available_devices()
        normalized = self._normalize_selected_device(devices=devices)
        current = str(self.yolo_device_var.get() or "").strip()
        if normalized != current:
            self.yolo_device_var.set(normalized)
            current = normalized

        gpu_devices = [item for item in devices if item.startswith("cuda:")]
        current_lower = current.lower()

        if current_lower.startswith("auto"):
            if gpu_devices:
                text = f"Auto najpierw sprobuje akceleracji na {gpu_devices[0]}. Gdy GPU/CUDA nie bedzie dostepne, system spadnie do CPU."
                tone = "info"
            else:
                text = "Auto nie wykrylo karty CUDA, wiec zostanie uzyty CPU."
                tone = "warning"
        elif current_lower.startswith("cpu"):
            text = "CPU wymusza prace bez akceleracji GPU. To wolniejsze, ale przewidywalne."
            tone = "muted"
        else:
            text = f"Wybrana karta: {current}. YOLO i OCR sprobuja uzyc tej akceleracji."
            tone = "success"

        self._set_themed_label_state(label, text=text, tone=tone)
    
    def _set_button_emphasis(self, frame_attr: str, enabled: bool, color: str = "#f39c12"):
        btn = self._resolve_guidance_button(frame_attr)
        if btn is None:
            return

        try:
            self.app.set_button_emphasis(btn, enabled)
        except Exception as e:
            logger.debug(f"Nie udało się ustawić podświetlenia przycisku dla {frame_attr}: {e}")

    def _ensure_yolo_model_available(self) -> str:
        """
        Zwraca lokalną ścieżkę do modelu YOLO.
        Jeśli model ma być pobrany z sieci, robi to jawnie z logowaniem postępu.
        """
        # 1. jeśli mamy realny lokalny model projektu / free mode, użyj go
        effective_model = self._get_effective_yolo_model_path()
        if effective_model and Path(effective_model).exists():
            self._log(self.test_log_text, f"[INFO] Używam lokalnego modelu: {effective_model}", "INFO")
            return str(Path(effective_model))

        # 2. fallback: model wbudowany wybrany z combo
        filename = self._get_selected_builtin_yolo_filename()
        if not filename:
            raise RuntimeError("Nie udało się ustalić nazwy modelu YOLO z wybranego wydania i rozmiaru.")

        url = YOLO_REMOTE_URLS.get(filename)
        if not url:
            raise RuntimeError(f"Brak skonfigurowanego URL dla modelu {filename}")

        models_dir = Path(self.session_dir) / "downloaded_models"
        dst_path = models_dir / filename

        if dst_path.exists():
            self._log(self.test_log_text, f"[INFO] Model już istnieje lokalnie: {dst_path}", "INFO")
            return str(dst_path)

        self._download_file_with_progress(url, dst_path, filename)
        return str(dst_path)

    # =========================================================
    # Resolvers
    # =========================================================

    def _get_selected_builtin_yolo_filename(self) -> str:
        version = (self.yolo_model_version_var.get() or "").strip()
        size = (self.yolo_model_size_var.get() or "").strip().lower()

        if version not in {"8", "11", "26"}:
            return ""
        if size not in {"n", "s", "m", "l", "x"}:
            return ""

        return f"yolo{version}{size}.pt"
    
    # =========================================================
    # Pickers
    # =========================================================

    def _pick_xml_file(self):
        p = filedialog.askopenfilename(
            initialdir=str(Path(CONFIG.DIR_2_AUTO_ANN).absolute()),
            title="Wybierz annotations.xml dla tej samej paczki obrazów",
            filetypes=[("XML", "*.xml")]
        )
        if p:
            self.xml_path_var.set(p)

    def _pick_images_dir(self):
        p = filedialog.askdirectory(
            initialdir=str(Path(CONFIG.DIR_1_RAW).absolute()),
            title="Wybierz paczkę obrazów powiązaną z annotations.xml"
        )
        if p:
            self.images_dir_var.set(p)

    def _pick_yolo_model(self):
        p = filedialog.askopenfilename(
            initialdir=str(Path(CONFIG.DIR_6_MODELS).absolute()),
            title="Wybierz model YOLO (.pt)",
            filetypes=[("PyTorch", "*.pt")]
        )
        if p:
            self.yolo_model_path_var.set(p)

    def _pick_and_load_preview_dir(self):
        initial = getattr(self, "_campaign_chars_dir", str(Path(CONFIG.DIR_3_CHARS).absolute()))
        p = filedialog.askdirectory(initialdir=str(initial), title="Wybierz folder wyników (zawierający metadata.json)")
        if p:
            self.preview_dir_var.set(p)
            self._force_save_all()
            self._reset_preview_cache()
            self._load_preview_data()

    # =========================================================
    # Logging helper
    # =========================================================

    def _log(self, txt_widget, msg: str, tag: str = "INFO"):
        def do_log():
            try:
                txt_widget.configure(state="normal")

                if not txt_widget.tag_names():
                    txt_widget.tag_config("SUCCESS", foreground="#27ae60", font=("Consolas", 9, "bold"))
                    txt_widget.tag_config("ERROR", foreground="#c0392b", font=("Consolas", 9, "bold"))
                    txt_widget.tag_config("WARNING", foreground="#d35400", font=("Consolas", 9, "bold"))
                    txt_widget.tag_config("INFO", foreground="#2980b9", font=("Consolas", 9))
                    txt_widget.tag_config("HEADER", foreground="#8e44ad", font=("Consolas", 10, "bold"))

                final_tag = tag
                if tag == "INFO":
                    if "✅" in msg:
                        final_tag = "SUCCESS"
                    elif "❌" in msg:
                        final_tag = "ERROR"

                txt_widget.insert(tk.END, msg + "\n", final_tag)
                txt_widget.see(tk.END)
                txt_widget.update_idletasks()

            finally:
                try:
                    txt_widget.configure(state="disabled")
                except Exception:
                    pass

        self.frame.after(0, do_log)

    def _get_true_texts_from_filename(self, filename: str) -> list:
        stem = Path(filename).stem.upper()
        import re
        parts = re.findall(r'[A-Z0-9]{4,}', stem)
        if not parts:
            return []
        if len(parts) > 1:
            return parts[:-1]
        return parts

    def _get_current_prep_params(self):
        return {
            "target_height": self.prep_height_var.get(),
            "manual_angle": self.prep_angle_var.get(),
            "clip_thresh": self.prep_clip_var.get(),
            "denoise_h": self.prep_denoise_var.get(),
            "clahe_clip": self.prep_clahe_var.get() if self.do_clahe_var.get() else 0.0,
            "use_binarization": self.prep_use_bin_var.get(),
            "thresh_block": self.prep_block_var.get(),
            "thresh_c": self.prep_c_var.get(),
            "erode_iter": self.prep_erode_var.get(),
            "interpolation": self.interpolation_var.get(),
            "padding_pct": self.prep_padding_var.get(),
        }

    def _get_best_preset(self):
        cache_file = self.presets_dir / "global_ranking.json"
        if not cache_file.exists():
            return None, 0.0
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            best_name, best_acc, best_params = None, -1.0, {}
            for preset_key, stats in data.items():
                acc = float(stats.get("acc", 0.0))
                if acc > best_acc:
                    best_acc, best_name, best_params = acc, str(stats.get("name", preset_key)), stats.get("params", {})
            if best_name:
                return {"name": best_name, "params": best_params}, best_acc
        except Exception:
            pass
        return None, 0.0

    # =========================================================
    # UI build
    # =========================================================

    def _create_widgets(self):
        self.main_nb = ttk.Notebook(self.frame)
        self.main_nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.tab_extract = ttk.Frame(self.main_nb)
        self.main_nb.add(self.tab_extract, text="[PZ1] Wycinanie tablic")
        self._build_extraction_tab(self.tab_extract)

        self.tab_detect = ttk.Frame(self.main_nb)
        self.main_nb.add(self.tab_detect, text="[PZ2] Wykrywanie znaków i analiza")
        self._build_detection_tab(self.tab_detect)

        self.tab_dataset = ttk.Frame(self.main_nb)
        self.main_nb.add(self.tab_dataset, text="[PZ3] Integracje i dataset (YOLO)")
        self._build_cvat_tab(self.tab_dataset)
        self.main_nb.bind("<<NotebookTabChanged>>", self._on_main_nb_tab_changed, add="+")

    # =========================================================
    # TAB 1: Extraction
    # =========================================================

    def _build_extraction_tab(self, parent):
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=3)

        lf_paths = ttk.LabelFrame(left, text=" Ścieżki do źródła ", padding=15)
        lf_paths.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(
            lf_paths,
            text="annotations.xml (musi pochodzić z tej samej paczki obrazów):",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))
        row_xml = ttk.Frame(lf_paths)
        row_xml.pack(fill=tk.X, pady=(0, 10))
        self.xml_path_entry = ttk.Entry(row_xml, textvariable=self.xml_path_var)
        self.xml_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.xml_path_browse_btn = ttk.Button(
            row_xml,
            text="Wybierz",
            command=self._pick_xml_file
        )
        self.xml_path_browse_btn.pack(side=tk.RIGHT, padx=(5, 0))

        ttk.Label(
            lf_paths,
            text="Paczka obrazów źródłowych powiązana z XML:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))
        row_img = ttk.Frame(lf_paths)
        row_img.pack(fill=tk.X, pady=(0, 10))

        self.images_dir_entry = ttk.Entry(row_img, textvariable=self.images_dir_var)
        self.images_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.images_dir_browse_btn = ttk.Button(
            row_img,
            text="Wybierz",
            command=self._pick_images_dir
        )
        self.images_dir_browse_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.source_binding_status_lbl = tk.Label(
            lf_paths,
            text=(
                "Plik annotations.xml i paczka obrazów są nierozerwalnie powiązane. "
                "System może automatycznie odnaleźć paczkę w Workspace/1_raw_images/."
            ),
            justify=tk.LEFT,
            anchor="w",
            wraplength=430,
            bd=0,
            highlightthickness=0,
        )
        self.source_binding_status_lbl.pack(fill=tk.X, pady=(0, 6))
        self._set_source_binding_status(
            "Plik annotations.xml i paczka obrazów są nierozerwalnie powiązane. "
            "System może automatycznie odnaleźć paczkę w Workspace/1_raw_images/.",
            "warning",
        )

        lf_run = ttk.LabelFrame(left, text=" Wycinanie Tablic ", padding=15)
        lf_run.pack(fill=tk.X)

        self.btn_extract = ttk.Button(lf_run, text="START (Wytnij tablice z paczki)", command=self._run_extraction, style="Accent.TButton")
        self.btn_extract.pack(fill=tk.X, ipady=5)

        self.btn_ext_stop = ttk.Button(lf_run, text="ZATRZYMAJ", command=lambda: setattr(self, 'is_processing', False), state=tk.DISABLED)
        self.btn_ext_stop.pack(fill=tk.X, pady=5)

        self.ext_progress = ttk.Progressbar(lf_run, maximum=100)
        self.ext_progress.pack(fill=tk.X, pady=(15, 5))
        self.ext_status = tk.Label(
            lf_run,
            text="Gotowy",
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.ext_status.pack(anchor=tk.W)
        self._set_inline_status_label_state(self.ext_status, text="Gotowy", tone="neutral", emphasis=True)

        lf_logs = ttk.LabelFrame(right, text=" Terminal procesu ", padding=10)
        lf_logs.pack(fill=tk.BOTH, expand=True)
        self.ext_log = scrolledtext.ScrolledText(lf_logs, wrap=tk.WORD, font=("Consolas", 10), bg="#161616", fg="#f3f3f3", insertbackground="#f3f3f3")
        self.ext_log.pack(fill=tk.BOTH, expand=True)

        HELP.bind_help(row_xml, "t2_xml")
        HELP.bind_help(row_img, "t2_img")
        HELP.bind_help(self.btn_extract, "t2_cut_start")
        HELP.bind_help(lf_logs, "t2_cut_logs")

        nav = ttk.Frame(parent)
        nav.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.btn_back_to_wizard_step3 = ttk.Button(
            nav,
            text="← Wstecz",
            command=self._return_to_wizard_for_step3_rework,
            state=tk.DISABLED
        )
        self.btn_back_to_wizard_step3.pack(side=tk.LEFT)

        self.btn_to_detect_frame = tk.Frame(nav, bd=0, highlightthickness=0)
        self.btn_to_detect_frame.pack(side=tk.RIGHT)

        self.btn_to_detect = ttk.Button(
            self.btn_to_detect_frame,
            text="Dalej → Wykrywanie Znaków i Analiza",
            command=self.go_to_substep_2,
            state=tk.DISABLED
        )
        self.btn_to_detect.pack()

    def _run_extraction(self):
        self._force_save_all()
        validation = self._refresh_source_binding_status(allow_autofind=True)
        if not validation.get("ok"):
            return messagebox.showerror("Niezgodne źródła Z3/PZ1", validation.get("message", "Źródła wejściowe są niepoprawne."))

        xml_path = Path(self.xml_path_var.get().strip())
        images_dir = Path(self.images_dir_var.get().strip())
        session_token = self._project_reset_token

        if not xml_path.exists() or not images_dir.exists():
            return messagebox.showerror(
                "Błąd",
                "Brak plików wejściowych. annotations.xml i paczka obrazów muszą pochodzić z tego samego zestawu."
            )

        import datetime
        base_out_dir = Path(getattr(self, "_campaign_chars_dir", str(CONFIG.DIR_3_CHARS)))
        base_out_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        counter = 1
        while True:
            run_dir = base_out_dir / f"run_{counter:03d}_{timestamp}"
            if not run_dir.exists():
                break
            counter += 1

        run_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir_var.set(str(run_dir))
        self._reset_preview_cache()
        self._force_save_all()

        try:
            tree = ET.parse(xml_path)
            xml_images = {img.get("name"): img for img in tree.getroot().findall(".//image") if img.get("name")}
        except Exception:
            return messagebox.showerror("Błąd", "Zły plik XML.")

        self.btn_extract.config(state=tk.DISABLED)
        self.btn_ext_stop.config(state=tk.NORMAL)
        self.is_processing = True
        self._set_extraction_status("Start wycinania...", "info")

        def worker():
            try:
                if session_token != self._project_reset_token:
                    return

                self._log(self.ext_log, f"\nROZPOCZĘTO WYCINANIE DO: {run_dir.name}\n", "HEADER")
                generator = PlateGenerator(run_dir)
                total = len(xml_images)
                processed = 0

                for img_name, img_el in xml_images.items():
                    if (not self.is_processing) or session_token != self._project_reset_token:
                        break
                    img_path = images_dir / img_name
                    if not img_path.exists():
                        processed += 1
                        continue

                    plates = []
                    for poly in img_el.findall(".//polygon[@label='plate']"):
                        pts = [tuple(map(float, p.split(","))) for p in poly.get("points", "").split(";")]
                        if len(pts) >= 4:
                            plates.append(
                                Detection(
                                    "plate", 1.0,
                                    (min(x for x, y in pts), min(y for x, y in pts), max(x for x, y in pts), max(y for x, y in pts)),
                                    polygon=pts
                                )
                            )

                    if plates:
                        ann = ImageAnnotation(img_name, int(img_el.get("width", 0)), int(img_el.get("height", 0)), plates)
                        generator.generate_from_annotations(
                            img_path, ann,
                            rectify=True,
                            do_deskew=False,
                            enhance_contrast=False,
                            interpolation=self.interpolation_var.get()
                        )

                    processed += 1
                    self.frame.after(
                        0,
                        lambda p=(processed / max(1, total)) * 100: (
                            self.ext_progress.config(value=p)
                            if session_token == self._project_reset_token else None
                        )
                    )
                    self.frame.after(
                        0,
                        lambda c=processed, t=total: (
                            self._set_extraction_status(f"{c}/{t} obrazów...", "info")
                            if session_token == self._project_reset_token else None
                        )
                    )

                generator.save_metadata()
                if self.is_processing and session_token == self._project_reset_token:
                    self.frame.after(0, lambda: self._set_extraction_status("Wycinanie zakończone", "success"))
                    self.frame.after(0, lambda: self._load_preview_data(quiet=True))
                    self.frame.after(0, self.unlock_detection_subtab)
                    self.frame.after(0, lambda: messagebox.showinfo(
                        "Gotowe",
                        "Wycinanie zakończone!\n\nOdblokowano etap 2: Wykrywanie Znaków i Analiza."
                    ))
            except Exception as e:
                if session_token == self._project_reset_token:
                    self.frame.after(0, lambda: self._set_extraction_status("Błąd wycinania", "error"))
                    self._log(self.ext_log, f"\n❌ BŁĄD: {e}\n", "ERROR")
            finally:
                if session_token == self._project_reset_token:
                    self.is_processing = False
                    self.frame.after(0, lambda: self.btn_extract.config(state=tk.NORMAL))
                    self.frame.after(0, lambda: self.btn_ext_stop.config(state=tk.DISABLED))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # TAB 2: Detection + Preview
    # =========================================================

    def _build_detection_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_columnconfigure(0, weight=1)

        content_frame = ttk.Frame(parent)
        content_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_rowconfigure(1, weight=0)
        content_frame.grid_rowconfigure(2, weight=0)
        content_frame.grid_columnconfigure(0, weight=1)

        split = ttk.PanedWindow(content_frame, orient=tk.HORIZONTAL)
        split.grid(row=0, column=0, sticky="nsew")

        left_panel = ttk.Frame(split)
        right_panel = ttk.Frame(split)
        split.add(left_panel, weight=3)
        split.add(right_panel, weight=2)

        left_panel.grid_rowconfigure(0, weight=4)
        left_panel.grid_rowconfigure(1, weight=2)
        left_panel.grid_columnconfigure(0, weight=1)

        preview_lf = ttk.LabelFrame(left_panel, text=" Podgląd tablicy ", padding=8)
        preview_lf.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        preview_lf.grid_rowconfigure(0, weight=1)
        preview_lf.grid_columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            preview_lf,
            bg="#1e1e1e",
            bd=3,
            relief="sunken",
            highlightthickness=0
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda e: self._on_preview_select(None))

        list_lf = ttk.LabelFrame(left_panel, text=" Lista tablic (🟢 Perfekt | 🔴 Błędy) ", padding=8)
        list_lf.grid(row=1, column=0, sticky="nsew")
        list_lf.grid_rowconfigure(0, weight=1)
        list_lf.grid_columnconfigure(0, weight=1)

        self.plates_listbox = tk.Listbox(
            list_lf,
            font=("Consolas", 10),
            selectbackground="#3498db"
        )
        self.plates_listbox.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)

        scroll = ttk.Scrollbar(list_lf, command=self.plates_listbox.yview)
        scroll.grid(row=0, column=1, sticky="ns")

        self.plates_listbox.config(yscrollcommand=scroll.set)
        self.plates_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

        right_panel.grid_rowconfigure(0, weight=1)
        right_panel.grid_columnconfigure(0, weight=1)

        palette = getattr(self.app, "palette", {})
        self.detect_right_scroll_host = ttk.Frame(right_panel)
        self.detect_right_scroll_host.grid(row=0, column=0, sticky="nsew")
        self.detect_right_scroll_host.grid_rowconfigure(0, weight=1)
        self.detect_right_scroll_host.grid_columnconfigure(0, weight=1)

        self.detect_right_canvas = tk.Canvas(
            self.detect_right_scroll_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0
        )
        self.detect_right_canvas.grid(row=0, column=0, sticky="nsew")

        self.detect_right_scrollbar = ttk.Scrollbar(
            self.detect_right_scroll_host,
            orient=tk.VERTICAL,
            command=self.detect_right_canvas.yview
        )
        self.detect_right_scrollbar.grid(row=0, column=1, sticky="ns")
        self.detect_right_canvas.configure(yscrollcommand=self.detect_right_scrollbar.set)

        self.detect_right_content = ttk.Frame(self.detect_right_canvas)
        self.detect_right_content.grid_columnconfigure(0, weight=1)
        self.detect_right_content_window = self.detect_right_canvas.create_window(
            (0, 0),
            window=self.detect_right_content,
            anchor="nw"
        )
        self.detect_right_content.bind("<Configure>", self._sync_detect_right_scrollregion, add="+")
        self.detect_right_canvas.bind("<Configure>", self._sync_detect_right_canvas_width, add="+")

        set_lf = ttk.LabelFrame(self.detect_right_content, text=" Konfiguracja Rozpoznawania ", padding=8)
        set_lf.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        row_meth = ttk.Frame(set_lf)
        row_meth.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(
            row_meth,
            text="Metoda detekcji znaków:",
            font=("Segoe UI", 9, "bold")
        ).pack(side=tk.LEFT)

        self.det_method_combo = ttk.Combobox(
            row_meth,
            textvariable=self.detection_method_var,
            values=["OCR", "YOLO", "BOTH"],
            state="readonly",
            width=12
        )
        self.det_method_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        self.det_method_combo.bind("<<ComboboxSelected>>", self._on_method_change)

        self.det_device_row = ttk.Frame(set_lf)
        self.det_device_row.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(self.det_device_row, text="Urzadzenie obliczen:").pack(side=tk.LEFT)

        self.det_device_combo = ttk.Combobox(
            self.det_device_row,
            textvariable=self.yolo_device_var,
            values=self._get_available_devices(),
            state="readonly",
            width=12
        )
        self.det_device_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        self.det_device_combo.bind("<<ComboboxSelected>>", self._update_device_hint, add="+")

        self.det_device_hint_lbl = ttk.Label(
            set_lf,
            text="",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        )
        self.det_device_hint_lbl.pack(fill=tk.X, pady=(0, 8))
        self._refresh_device_options()

        self.yolo_panel = ttk.Frame(set_lf)

        ttk.Label(
            self.yolo_panel,
            text="Wydanie YOLO:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(5, 0))

        self.yolo_version_row = ttk.Frame(self.yolo_panel)
        self.yolo_version_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            self.yolo_version_row,
            text="Wybierz rodzinę modelu:"
        ).pack(side=tk.LEFT)

        self.yolo_version_combo = ttk.Combobox(
            self.yolo_version_row,
            textvariable=self.yolo_model_version_var,
            values=["8", "11", "26"],
            state="readonly",
            width=10
        )
        self.yolo_version_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        self.yolo_version_combo.bind("<<ComboboxSelected>>", self._on_yolo_arch_change)

        ttk.Label(
            self.yolo_panel,
            text="Rozmiar modelu:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(5, 0))

        self.yolo_size_row = ttk.Frame(self.yolo_panel)
        self.yolo_size_row.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            self.yolo_size_row,
            text="Wybierz wariant modelu:"
        ).pack(side=tk.LEFT)

        self.yolo_size_combo = ttk.Combobox(
            self.yolo_size_row,
            textvariable=self.yolo_model_size_var,
            values=["n", "s", "m", "l", "x"],
            state="readonly",
            width=10
        )
        self.yolo_size_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        self.yolo_size_combo.bind("<<ComboboxSelected>>", self._on_yolo_arch_change)

        ttk.Label(
            self.yolo_panel,
            text="Model YOLO z Wizarda / iteracji:",
            style="Muted.TLabel"
        ).pack(anchor=tk.W, pady=(5, 0))

        self.yolo_model_row = ttk.Frame(self.yolo_panel)
        self.yolo_model_row.pack(fill=tk.X)

        self.det_yolo_model_entry = ttk.Entry(
            self.yolo_model_row,
            textvariable=self.yolo_model_path_var,
            state="readonly"
        )
        self.det_yolo_model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.det_yolo_model_browse_btn = ttk.Button(
            self.yolo_model_row,
            text="Wybierz",
            command=self._pick_yolo_model
        )
        self.det_yolo_model_browse_btn.pack(side=tk.RIGHT)

        self.yolo_tuning_lf = ttk.LabelFrame(self.yolo_panel, text=" Strojenie YOLO ", padding=8)
        self.yolo_tuning_lf.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Te progi pomagają odsiać słabe boxy i usuwać duplikaty na jednym znaku.",
            style="Muted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        self.yolo_conf_row = ttk.Frame(self.yolo_tuning_lf)
        self.yolo_conf_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self.yolo_conf_row, text="Confidence:").pack(side=tk.LEFT)
        self.yolo_conf_spin = ttk.Spinbox(
            self.yolo_conf_row,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.yolo_conf_var,
            width=8
        )
        self.yolo_conf_spin.pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Wyzej: mniej slabych i falszywych boxow, ale mozna zgubic trudne znaki. Nizej: wiecej trafien, ale rosnie ryzyko dubli i szumu.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        self.yolo_iou_row = ttk.Frame(self.yolo_tuning_lf)
        self.yolo_iou_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self.yolo_iou_row, text="NMS IoU:").pack(side=tk.LEFT)
        self.yolo_iou_spin = ttk.Spinbox(
            self.yolo_iou_row,
            from_=0.01,
            to=0.99,
            increment=0.05,
            textvariable=self.yolo_iou_var,
            width=8
        )
        self.yolo_iou_spin.pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Nizej: NMS agresywniej scala podobne ramki i mocniej wycina duble. Wyzej: zostawia wiecej zblizonych boxow, co pomaga przy ciasnych znakach, ale moze dublowac.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        self.yolo_overlap_row = ttk.Frame(self.yolo_tuning_lf)
        self.yolo_overlap_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self.yolo_overlap_row, text="Nakladanie boxow:").pack(side=tk.LEFT)
        self.yolo_overlap_spin = ttk.Spinbox(
            self.yolo_overlap_row,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.yolo_overlap_var,
            width=8
        )
        self.yolo_overlap_spin.pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Nizej: system szybciej uzna dwa boxy za ten sam znak i odrzuci slabszy. Wyzej: dwa boxy musza sie mocniej pokrywac, wiec wiecej dubli moze zostac.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Prog liczony jako wspolna czesc powierzchni mniejszego boxa dla dwoch detekcji.",
            style="Muted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        self.yolo_agnostic_nms_chk = ttk.Checkbutton(
            self.yolo_tuning_lf,
            text="Class-agnostic NMS",
            variable=self.yolo_agnostic_nms_var
        )
        self.yolo_agnostic_nms_chk.pack(anchor=tk.W)

        ttk.Label(
            self.yolo_tuning_lf,
            text="Wlacz, gdy ten sam znak dostaje kilka klas naraz, np. B i 8. Wylacz, gdy model zbyt mocno skleja sasiednie, podobne znaki.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(4, 0))

        self._update_yolo_visibility()

        self.actions_lf = ttk.LabelFrame(self.detect_right_content, text=" Panel OCR ", padding=8)
        self.actions_lf.grid(row=1, column=0, sticky="nsew", pady=(0, 8))

        ocr_top_row = ttk.Frame(self.actions_lf)
        ocr_top_row.pack(fill=tk.X)
        ocr_top_row.grid_columnconfigure(0, weight=3)
        ocr_top_row.grid_columnconfigure(1, weight=2)

        leader_block = ttk.Frame(ocr_top_row)
        leader_block.grid(row=0, column=0, sticky="nsew")

        actions_block = ttk.Frame(ocr_top_row)
        actions_block.grid(row=0, column=1, sticky="ne", padx=(12, 0))

        ttk.Label(
            leader_block,
            text="Lider OCR:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))

        self.winner_name_lbl = tk.Label(
            leader_block,
            text="BRAK DANYCH",
            width=30,
            anchor="w",
            justify="left",
            wraplength=340,
            bd=0,
            highlightthickness=0
        )
        self.winner_name_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_status_label_state(self.winner_name_lbl, text="BRAK DANYCH", tone="neutral", emphasis=True)

        ttk.Label(
            leader_block,
            text="Status rankingu OCR:",
            style="PanelMuted.TLabel"
        ).pack(anchor=tk.W, pady=(0, 2))

        self.winner_acc_lbl = tk.Label(
            leader_block,
            text="0.0%",
            width=30,
            anchor="w",
            justify="left",
            wraplength=340,
            bd=0,
            highlightthickness=0
        )
        self.winner_acc_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_status_label_state(self.winner_acc_lbl, text="0.0%", tone="muted", emphasis=False)

        self.btn_ocr_lab = ttk.Button(
            actions_block,
            text="Laboratorium OCR (filtry)",
            command=self._open_filter_lab,
            style="Accent.TButton"
        )
        self.btn_ocr_lab.pack(fill=tk.X, ipady=4, pady=(0, 6))

        self.btn_rank_presets = ttk.Button(
            actions_block,
            text="Turniej presetów OCR",
            command=self._run_preset_ranking
        )
        self.btn_rank_presets.pack(fill=tk.X, ipady=3, pady=(0, 6))

        self.test_status_lbl = ttk.Label(
            actions_block,
            text="Gotowy do testów",
            style="PanelStatusNeutral.TLabel",
            width=30,
            anchor="w",
            justify="left",
            wraplength=340
        )
        self.test_status_lbl.pack(anchor=tk.W, fill=tk.X)
        self._set_inline_status_label_state(self.test_status_lbl, text="Gotowy do testow", tone="neutral", emphasis=True)
        self.test_status_lbl.pack_forget()

        package_lf = ttk.LabelFrame(self.detect_right_content, text=" Paczka do analizy ", padding=8)
        package_lf.grid(row=2, column=0, sticky="ew")
        package_lf.grid_columnconfigure(0, weight=1)

        ttk.Label(
            package_lf,
            text="Folder run_XXX:",
            font=("Segoe UI", 9, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.preview_dir_entry = ttk.Entry(
            package_lf,
            textvariable=self.preview_dir_var,
            state="readonly"
        )
        self.preview_dir_entry.grid(row=1, column=0, sticky="ew")

        self.preview_dir_browse_btn = ttk.Button(
            package_lf,
            text="Otwórz inną paczkę",
            command=self._pick_and_load_preview_dir
        )
        self.preview_dir_browse_btn.grid(row=2, column=0, sticky="w", pady=(6, 4))

        self.preview_info_lbl = tk.Label(
            package_lf,
            text="Wczytano tablic: 0",
            justify="left",
            wraplength=360,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.preview_info_lbl.grid(row=3, column=0, sticky="w")
        self._set_inline_status_label_state(self.preview_info_lbl, text="Wczytano tablic: 0", tone="info", emphasis=False)

        detection_log_tools = ttk.Frame(content_frame)
        detection_log_tools.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.btn_toggle_detection_log = ttk.Button(
            detection_log_tools,
            text="Pokaż terminal",
            command=self._toggle_detection_process_log
        )
        self.btn_toggle_detection_log.pack(side=tk.LEFT)

        ttk.Label(
            detection_log_tools,
            text="Terminal procesu jest dostępny na żądanie użytkownika.",
            style="Muted.TLabel"
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.detection_log_frame = ttk.LabelFrame(content_frame, text=" Terminal procesu ", padding=10)
        self.detection_log_frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))

        self.test_log_text = scrolledtext.ScrolledText(
            self.detection_log_frame,
            height=7,
            wrap=tk.WORD,
            font=("Consolas", 9)
        )
        self.test_log_text.pack(fill=tk.BOTH, expand=True)

        try:
            self.test_log_text.insert(tk.END, "Gotowy do uruchomienia detekcji znaków.\n")
            self.test_log_text.configure(state="disabled")
        except Exception:
            pass

        self._set_detection_process_log_visibility(False)
        detection_log_tools.grid_remove()

        footer_nav = ttk.Frame(content_frame)
        footer_nav.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        footer_nav.grid_columnconfigure(0, weight=0)
        footer_nav.grid_columnconfigure(1, weight=0)
        footer_nav.grid_columnconfigure(2, weight=0)
        footer_nav.grid_columnconfigure(3, weight=1)
        footer_nav.grid_columnconfigure(4, weight=0)

        self.btn_back_to_extract = ttk.Button(
            footer_nav,
            text="← Wstecz do Wycinania Tablic",
            command=self.back_to_substep_1
        )
        self.btn_back_to_extract.grid(row=0, column=0, sticky="w")

        self.btn_run_detection_frame = tk.Frame(footer_nav, bd=0, highlightthickness=0)
        self.btn_run_detection_frame.grid(row=0, column=2, sticky="w", padx=(10, 0))

        self.btn_run_detection_pulse_frame = tk.Frame(
            self.btn_run_detection_frame,
            bd=0,
            highlightthickness=0
        )
        self.btn_run_detection_pulse_frame.pack(anchor=tk.W)

        self.btn_run_detection = ttk.Button(
            self.btn_run_detection_pulse_frame,
            text="Uruchom detekcję",
            command=self._run_detection_stage,
            style="Accent.TButton"
        )
        self.btn_run_detection.pack(fill=tk.X)

        self.detect_run_status_frame = ttk.Frame(footer_nav)
        self.detect_run_status_frame.grid(row=0, column=3, sticky="ew", padx=(12, 0))
        self.detect_run_status_frame.grid_columnconfigure(0, weight=1)
        self.detect_run_status_frame.grid_columnconfigure(1, weight=0)

        self.test_status_lbl = tk.Label(
            self.detect_run_status_frame,
            text="Gotowy do testÄ‚Ĺ‚w",
            anchor="w",
            justify="left",
            wraplength=460,
            bd=0,
            highlightthickness=0
        )
        self.test_status_lbl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self._set_inline_status_label_state(self.test_status_lbl, text="Gotowy do testow", tone="neutral", emphasis=True)

        self.test_progress = ttk.Progressbar(self.detect_run_status_frame, maximum=100, length=260)
        self.test_progress.grid(row=1, column=0, sticky="ew")

        self.test_progress_count_lbl = tk.Label(
            self.detect_run_status_frame,
            text="",
            anchor="e",
            width=9,
            bd=0,
            highlightthickness=0
        )
        self.test_progress_count_lbl.grid(row=1, column=1, sticky="e", padx=(8, 0))
        self._set_inline_status_label_state(self.test_progress_count_lbl, text="", tone="muted", emphasis=True)

        self.footer_test_status_lbl = tk.Label(
            footer_nav,
            text="Gotowy do testĂłw",
            anchor="w",
            justify="left",
            wraplength=460,
            bd=0,
            highlightthickness=0
        )
        self.footer_test_status_lbl.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=(4, 0))
        self._set_inline_status_label_state(self.footer_test_status_lbl, text="Gotowy do testow", tone="neutral", emphasis=True)
        self.footer_test_status_lbl.grid_remove()
        self._set_test_progress_counter()

        self.btn_toggle_detection_log = ttk.Button(
            footer_nav,
            text="PokaĹĽ terminal",
            command=self._toggle_detection_process_log
        )
        self.btn_toggle_detection_log.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.btn_toggle_detection_log.configure(text="Pokaz terminal")

        self.btn_to_dataset_frame = tk.Frame(footer_nav, bd=0, highlightthickness=0)
        self.btn_to_dataset_frame.grid(row=0, column=4, sticky="e", padx=(10, 0))

        self.btn_to_dataset_pulse_frame = tk.Frame(
            self.btn_to_dataset_frame,
            bd=0,
            highlightthickness=0
        )
        self.btn_to_dataset_pulse_frame.pack(anchor=tk.E)

        self.btn_to_dataset = ttk.Button(
            self.btn_to_dataset_pulse_frame,
            text="Dalej → Integracje i dataset",
            command=self.go_to_substep_3,
            state=tk.DISABLED
        )
        self.btn_to_dataset.pack()

        # =========================
        # HELP BINDS
        # =========================
        HELP.bind_help(self.btn_run_detection, "t2_fast_test")
        HELP.bind_help(self.btn_rank_presets, "t2_rank")
        HELP.bind_help(self.det_method_combo, "t2_method")
        HELP.bind_help(self.det_device_combo, "t2_device")
        HELP.bind_help(self.btn_ocr_lab, "t2_lab_btn")
        HELP.bind_help(self.yolo_model_row, "t2_yolo_model")
        HELP.bind_help(self.yolo_tuning_lf, "t2_yolo_tuning")
        HELP.bind_help(self.btn_toggle_detection_log, "t2_cut_logs")
        HELP.bind_help(self.plates_listbox, "t2_listbox")
        HELP.bind_help(self.preview_canvas, "t2_canvas")
        HELP.bind_help(self.preview_dir_entry, "t2_preview_run")
        HELP.bind_help(self.preview_dir_browse_btn, "t2_preview_run")
        HELP.bind_help(self.preview_info_lbl, "t2_preview_info")

        self.frame.after_idle(self._sync_detect_right_scrollregion)
        self.frame.after_idle(self._sync_detect_right_canvas_width)
        self.frame.bind_all("<MouseWheel>", self._on_detect_right_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_detect_right_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_detect_right_global_mousewheel, add="+")

    def _run_detection_stage(self):
        method = (self.detection_method_var.get() or "OCR").upper().strip()

        if method in ("YOLO", "BOTH"):
            version = (self.yolo_model_version_var.get() or "").strip()
            size = (self.yolo_model_size_var.get() or "").strip().lower()

            if version not in {"8", "11", "26"}:
                messagebox.showwarning(
                    "Brak wydania modelu",
                    "Wybierz wydanie YOLO: 8, 11 albo 26."
                )
                return

            if size not in {"n", "s", "m", "l", "x"}:
                messagebox.showwarning(
                    "Brak rozmiaru modelu",
                    "Wybierz rozmiar modelu YOLO: n / s / m / l / x."
                )
                return

            try:
                yolo_runtime = self._get_yolo_runtime_settings()
            except Exception as e:
                messagebox.showwarning("Bledne parametry YOLO", str(e))
                return

            try:
                resolved_model = self._ensure_yolo_model_available()
                self.yolo_model_path_var.set(resolved_model)

                self._log(
                    self.test_log_text,
                    f"[INFO] Wybrana konfiguracja: YOLOv{version}{size}",
                    "INFO"
                )
                self._log(
                    self.test_log_text,
                    f"[INFO] Model gotowy do użycia: {resolved_model}",
                    "INFO"
                )
                self._log(
                    self.test_log_text,
                    "[INFO] Urzadzenie: "
                    f"{self._normalize_selected_device()} | "
                    f"YOLO={self._device_to_ultralytics(self.yolo_device_var.get())} | "
                    f"OCR={self._device_to_ocr(self.yolo_device_var.get())}",
                    "INFO"
                )
                self._log(
                    self.test_log_text,
                    "[INFO] Parametry YOLO: "
                    f"conf={yolo_runtime['conf']:.2f}, "
                    f"nms_iou={yolo_runtime['iou']:.2f}, "
                    f"overlap={yolo_runtime['overlap']:.2f}, "
                    f"agnostic_nms={yolo_runtime['agnostic_nms']}",
                    "INFO"
                )
            except Exception as e:
                messagebox.showwarning(
                    "Błąd modelu YOLO",
                    f"Nie udało się przygotować modelu YOLO:\n{e}"
                )
                self._log(self.test_log_text, f"[ERROR] {e}", "ERROR")
                return

        self._run_fast_ocr_test()

    def _update_winner_label(self):
        best_preset_data, best_acc = self._get_best_preset()
        if best_preset_data and best_preset_data.get("name"):
            name = best_preset_data.get("name")
            self._set_winner_name(f"Lider: {name.upper()} .json", "success")
            self._set_winner_acc(f" Skuteczność najlepszego presetu: {best_acc:.1f}% ", "success")
        else:
            self._set_winner_name("BRAK DANYCH Z TURNIEJU", "neutral")
            self._set_winner_acc("Skuteczność detekcji OCR: 0.0%", "error")

    # =========================================================
    # Preview load + render
    # =========================================================
    def _load_preview_data(self, quiet=False):
        out_dir = Path(self.preview_dir_var.get().strip())
        meta_path = out_dir / "metadata.json"

        try:
            self.frame.after(0, self._update_winner_label)
        except Exception:
            pass

        if not meta_path.exists():
            if not quiet:
                messagebox.showerror("Brak pliku", f"Nie znaleziono metadata.json w folderze:\n{out_dir}")
            try:
                self._set_preview_info("Brak wczytanych danych", "error")
            except Exception:
                pass
            return

        try:
            current_mtime = meta_path.stat().st_mtime
            need_reload = (
                self._loaded_meta_path != meta_path
                or self._loaded_meta_mtime != current_mtime
            )

            if (not self.preview_metadata) or (not quiet) or need_reload:
                with open(meta_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)

                if not isinstance(loaded, dict):
                    loaded = {}

                changed = False
                for pid, d in loaded.items():
                    if not isinstance(d, dict):
                        continue
                    if "status" not in d:
                        d["status"] = "unknown"
                        changed = True
                    if "characters" not in d or not isinstance(d.get("characters"), list):
                        d["characters"] = []
                        changed = True
                    else:
                        sorted_chars = self._sort_character_records_by_x(d.get("characters", []))
                        if sorted_chars != d.get("characters", []):
                            d["characters"] = sorted_chars
                            changed = True
                    if "yolo_detections" in d:
                        if not isinstance(d.get("yolo_detections"), list):
                            d["yolo_detections"] = []
                            changed = True
                        else:
                            sorted_yolo = self._sort_character_records_by_x(d.get("yolo_detections", []))
                            if sorted_yolo != d.get("yolo_detections", []):
                                d["yolo_detections"] = sorted_yolo
                                changed = True

                if changed:
                    self._atomic_write_json(meta_path, loaded)
                    current_mtime = meta_path.stat().st_mtime

                self.preview_metadata = loaded
                self._loaded_meta_path = meta_path
                self._loaded_meta_mtime = current_mtime

            self._apply_preview_metadata_update(self.preview_metadata, preserve_selection=True)

            try:
                self.frame.after(100, self._update_winner_label)
            except Exception:
                pass

        except Exception as e:
            if not quiet:
                messagebox.showerror("Błąd odświeżania listy", str(e))
            logger.error(f"Błąd _load_preview_data: {e}")
        finally:
            self._reloading_preview = False

        try:
            if self.preview_plate_ids and self.plates_listbox.curselection():
                self.frame.after_idle(lambda: self._on_preview_select(None))
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć preview po _load_preview_data: {e}")


    def _refresh_listbox_rows_from_metadata(self):
        """Pełne odświeżenie listy i preview na podstawie aktualnego self.preview_metadata."""
        if not hasattr(self, "plates_listbox"):
            return

        try:
            self._apply_preview_metadata_update(self.preview_metadata, preserve_selection=True)
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć listy tablic: {e}")

        try:
            if self._listbox_pid_by_index and self.plates_listbox.curselection():
                self.frame.after_idle(lambda: self._on_preview_select(None))
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć preview po _refresh_listbox_rows_from_metadata: {e}")

    def _on_preview_select(self, event=None):
        """Podgląd tablicy + bboxy znaków."""
        if not PIL_AVAILABLE:
            return

        # jeśli akurat przebudowujemy listę - nie renderujemy
        if getattr(self, "_reloading_preview", False):
            return

        sel = self.plates_listbox.curselection()
        if not sel:
            return

        try:
            idx = int(sel[0])
        except Exception:
            return

        pid_map = getattr(self, "_listbox_pid_by_index", [])
        if not (0 <= idx < len(pid_map)):
            return

        pid = pid_map[idx]
        data = self.preview_metadata.get(pid, {})
        clean_chars = self._sort_character_records_by_x(data.get("characters", []))
        box_chars, box_source = self._get_preview_box_records(data)
        display_text = self._format_plate_listbox_label(pid, data)

        # Jeśli tekst listy jest nieaktualny, zsynchronizuj go z bieżącym metadata.
        try:
            row_text = self.plates_listbox.get(idx)
        except Exception:
            row_text = None

        if row_text != display_text:
            try:
                self._reloading_preview = True
                self.plates_listbox.delete(idx)
                self.plates_listbox.insert(idx, display_text)

                status = str(data.get("status", "unknown")).strip().lower()
                if hasattr(self, "_apply_plate_listbox_row_style"):
                    self._apply_plate_listbox_row_style(idx, status)
                else:
                    if status == "perfect":
                        self.plates_listbox.itemconfig(idx, foreground="#27ae60")
                    elif status == "needs_fix":
                        self.plates_listbox.itemconfig(idx, foreground="#c0392b")
                    else:
                        self.plates_listbox.itemconfig(idx, foreground="#444444")

                self.plates_listbox.selection_clear(0, tk.END)
                self.plates_listbox.selection_set(idx)
                self.plates_listbox.activate(idx)
                self.plates_listbox.see(idx)
            finally:
                self._reloading_preview = False

        img_path = Path(self.preview_dir_var.get().strip()) / "images" / f"{pid}.jpg"

        self.preview_canvas.delete("all")
        if not img_path.exists():
            return

        try:
            pil_img = Image.open(img_path)
            orig_w, orig_h = pil_img.size

            c_w = max(50, self.preview_canvas.winfo_width())
            c_h = max(50, self.preview_canvas.winfo_height())

            margin_x = max(84, int(c_w * 0.18))
            margin_y_top = max(24, int(c_h * 0.06))
            margin_y_bottom = max(96, int(c_h * 0.20))

            usable_w = max(80, min(c_w - margin_x, int(c_w * 0.78)))
            usable_h = max(60, c_h - (margin_y_top + margin_y_bottom))

            scale_w = usable_w / float(orig_w)
            scale_h = usable_h / float(orig_h)
            SCALE = max(1.0, min(min(scale_w, scale_h), 5.0))

            new_w, new_h = int(orig_w * SCALE), int(orig_h * SCALE)
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            self._current_photo = ImageTk.PhotoImage(pil_img)
            x_off = (c_w - new_w) // 2
            y_off = (c_h - new_h - margin_y_bottom + margin_y_top) // 2

            self.preview_canvas.create_image(x_off, y_off, anchor=tk.NW, image=self._current_photo)

            image_bottom_y = y_off + new_h
            if box_source == "yolo":
                self.preview_canvas.create_text(
                    x_off + 10,
                    y_off + 10,
                    text="Podglad boxow YOLO do anotacji",
                    fill="#ffb27a",
                    font=("Segoe UI", 9, "bold"),
                    anchor=tk.NW
                )

            # rysowanie bboxów + znaków
            for box_idx, c in enumerate(box_chars):
                if not isinstance(c, dict):
                    continue

                bbox = c.get("bbox", [0, 0, 0, 0])
                if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                    continue

                x1, y1, x2, y2 = bbox[:4]
                cx1, cy1 = (float(x1) * SCALE) + x_off, (float(y1) * SCALE) + y_off
                cx2, cy2 = (float(x2) * SCALE) + x_off, (float(y2) * SCALE) + y_off

                center_x = cx1 + (cx2 - cx1) / 2
                is_yolo_box = box_source == "yolo" or str(c.get("method", "")).strip().lower() == "yolo"
                box_color, guide_color, char_fill = self._get_preview_box_palette(box_idx)

                self.preview_canvas.create_rectangle(
                    cx1, cy1, cx2, cy2,
                    outline=box_color,
                    width=2
                )

                if is_yolo_box:
                    try:
                        conf_text = f"{float(c.get('confidence', 0.0)):.2f}"
                        self.preview_canvas.create_text(
                            cx1 + 3,
                            max(y_off + 4, cy1 - 4),
                            text=conf_text,
                            fill=guide_color,
                            font=("Consolas", 9, "bold"),
                            anchor=tk.SW
                        )
                    except Exception:
                        pass

                text_anchor_y = image_bottom_y + 35
                self.preview_canvas.create_line(
                    center_x, cy2,
                    center_x, text_anchor_y - 20,
                    fill=guide_color,
                    dash=(2, 2)
                )

                char_text = str(c.get("character", ""))
                self.preview_canvas.create_text(
                    center_x + 1, text_anchor_y + 1,
                    text=char_text,
                    fill="#000000",
                    font=("Segoe UI", 18, "bold"),
                    anchor=tk.CENTER
                )
                self.preview_canvas.create_text(
                    center_x, text_anchor_y,
                    text=char_text,
                    fill=char_fill,
                    font=("Segoe UI", 18, "bold"),
                    anchor=tk.CENTER
                )

        except Exception as e:
            logger.error(f"Błąd wyświetlania podglądu tablicy: {e}")

    # =========================================================
    # Fast test UI lock/unlock
    # =========================================================

    def _lock_ui_for_testing(self):
        self.is_processing = True

        # główne akcje
        for attr_name in ("btn_run_detection", "btn_rank_presets", "btn_ocr_lab"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                try:
                    widget.config(state=tk.DISABLED)
                except Exception:
                    pass

        # na czas detekcji blokujemy też nawigację workflow
        for attr_name in ("btn_to_detect", "btn_to_dataset"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                try:
                    widget.config(state=tk.DISABLED)
                except Exception:
                    pass

        # lista tablic ma być zablokowana tylko na czas testu
        try:
            self.plates_listbox.config(state=tk.DISABLED)
        except Exception:
            pass

        # zdejmij podświetlenie głównej akcji na czas pracy
        try:
            self._set_button_emphasis("btn_run_detection_frame", False)
        except Exception:
            pass

    def _unlock_ui_after_testing(self):
        # NAJWAŻNIEJSZE: kończymy stan "processing"
        self.is_processing = False
        self.fast_test_running = False

        try:
            self.fast_test_stop.clear()
        except Exception:
            pass

        # lista tablic ma znowu działać zawsze po zakończeniu testu
        try:
            self.plates_listbox.config(state=tk.NORMAL)
        except Exception:
            pass

        # przyciski operacyjne
        for attr_name in ("btn_run_detection", "btn_rank_presets", "btn_ocr_lab"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                try:
                    widget.config(state=tk.NORMAL)
                except Exception:
                    pass

        # odśwież blokady/odblokowania pól ścieżek zgodnie z aktualnym trybem
        try:
            self._update_preview_path_lock()
        except Exception:
            pass

        try:
            self._update_step3_source_path_lock()
        except Exception:
            pass

        try:
            self._update_yolo_visibility()
        except Exception:
            pass

        # różne zachowanie dla kampanii i trybu swobodnego
        in_campaign = bool(getattr(self, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())

        if not in_campaign:
            # w trybie swobodnym wszystko ma działać
            for attr_name in ("btn_to_detect", "btn_to_dataset"):
                widget = getattr(self, attr_name, None)
                if widget is not None:
                    try:
                        widget.config(state=tk.NORMAL)
                    except Exception:
                        pass

            try:
                self._set_subtab_state(self.tab_extract, "normal")
                self._set_subtab_state(self.tab_detect, "normal")
                self._set_subtab_state(self.tab_dataset, "normal")
            except Exception:
                pass
        else:
            # w kampanii zostawiamy workflow tak, jak ustawiły go wcześniejsze kroki
            pass

        try:
            self.test_progress.update_idletasks()
        except Exception:
            pass
    # =========================================================
    # FAST OCR TEST (stable)
    # =========================================================

    def _run_fast_ocr_test(self):
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj paczkę!")

        if self.fast_test_running:
            return

        self._force_save_all()
        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"
        session_token = self._project_reset_token

        self.test_log_text.delete(1.0, tk.END)
        self._lock_ui_for_testing()
        self._set_test_status("Start detekcji...", "info")
        self.test_progress.config(value=0)
        self._set_test_progress_counter(0, len(self.preview_plate_ids))

        self.fast_test_stop.clear()
        self.fast_test_running = True

        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, "START - Szybki Test Celności\n", "HEADER")

        method_str = (self.detection_method_var.get() or "OCR").strip().lower()
        try:
            method = DetectionMethod(method_str)
        except Exception:
            method = DetectionMethod.OCR

        yolo_model = None
        if method in [DetectionMethod.YOLO, DetectionMethod.BOTH] and YOLO is not None:
            try:
                effective_model_path = self._get_effective_yolo_model_path()
                if not effective_model_path:
                    raise RuntimeError("Brak aktywnej ścieżki modelu YOLO dla detekcji znaków.")
                yolo_model = YOLO(str(effective_model_path))
            except Exception as e:
                self._log(self.test_log_text, f"Błąd YOLO: {e}", "ERROR")
                yolo_model = None

        prep_params = self._get_current_prep_params()
        ocr_engine = None
        if method in [DetectionMethod.OCR, DetectionMethod.BOTH]:
            try:
                ocr_device = self._device_to_ocr(self.yolo_device_var.get())
                ocr_engine = PlateOCR(
                    device=ocr_device,
                    confidence_threshold=self.ocr_conf_var.get()
                )
                ocr_engine.custom_prep_params = prep_params
            except Exception as e:
                self._log(self.test_log_text, f"Błąd OCR Engine: {e}", "ERROR")
                ocr_engine = None

        try:
            yolo_runtime = self._get_yolo_runtime_settings()
        except Exception as e:
            self._log(self.test_log_text, f"Błąd parametrów YOLO: {e}", "ERROR")
            yolo_runtime = {
                "conf": 0.25,
                "iou": 0.45,
                "overlap": 0.70,
                "agnostic_nms": False,
            }

        detector = CharacterDetector(
            method=method,
            ocr_engine=ocr_engine,
            yolo_model=yolo_model,
            yolo_device=self._device_to_ultralytics(self.yolo_device_var.get()),
            yolo_confidence=yolo_runtime["conf"],
            yolo_iou=yolo_runtime["iou"],
            yolo_agnostic_nms=yolo_runtime["agnostic_nms"],
            yolo_overlap_threshold=yolo_runtime["overlap"],
        )

        def worker():
            local_meta = dict(self.preview_metadata) if isinstance(self.preview_metadata, dict) else {}
            total = len(self.preview_plate_ids)
            stat_perfect = 0
            yolo_raw_total = 0
            yolo_filtered_total = 0

            try:
                for idx, pid in enumerate(self.preview_plate_ids):
                    if self.fast_test_stop.is_set() or session_token != self._project_reset_token:
                        break

                    img_path = imgs_dir / f"{pid}.jpg"
                    if not img_path.exists():
                        continue

                    img = cv2.imread(str(img_path))
                    if img is None:
                        continue

                    if pid not in local_meta or not isinstance(local_meta.get(pid), dict):
                        local_meta[pid] = {}

                    source_image = local_meta[pid].get("source_image", "") or ""
                    true_texts = self._get_true_texts_from_filename(source_image)

                    chars = detector.detect(img)
                    if session_token != self._project_reset_token:
                        break

                    c_clean = [{
                        "character": str(c.character),
                        "bbox": [float(x) for x in c.bbox],
                        "confidence": float(c.confidence),
                        "method": str(c.method),
                    } for c in chars]
                    yolo_clean = [{
                        "character": str(c.character),
                        "bbox": [float(x) for x in c.bbox],
                        "confidence": float(c.confidence),
                        "method": str(c.method),
                    } for c in getattr(detector, "last_yolo_detections", [])]

                    yolo_raw_total += len(getattr(detector, "last_yolo_raw_detections", []))
                    yolo_filtered_total += len(getattr(detector, "last_yolo_detections", []))

                    # WAŻNE: sortujemy znaki po X PRZED zapisem do metadata
                    c_clean = self._sort_character_records_by_x(c_clean)
                    yolo_clean = self._sort_character_records_by_x(yolo_clean)

                    local_meta[pid]["characters"] = c_clean
                    local_meta[pid]["yolo_detections"] = yolo_clean

                    if c_clean:
                        txt = "".join(str(c.get("character", "")) for c in c_clean)
                        if txt in true_texts:
                            local_meta[pid]["status"] = "perfect"
                            stat_perfect += 1
                            self._log(self.test_log_text, f"✅ [{idx+1:03d}/{total}] {pid}: {txt}", "SUCCESS")
                        else:
                            local_meta[pid]["status"] = "needs_fix"
                            expected_str = " / ".join(true_texts) if true_texts else "Brak"
                            self._log(
                                self.test_log_text,
                                f"❌ [{idx+1:03d}/{total}] {pid}: Odczyt=[{txt}] (Oczek: [{expected_str}])",
                                "ERROR"
                            )
                    else:
                        local_meta[pid]["status"] = "needs_fix"
                        self._log(
                            self.test_log_text,
                            f"❌ [{idx+1:03d}/{total}] {pid}: NIC NIE ZNALEZIONO",
                            "ERROR"
                        )

                    self.frame.after(
                        0,
                        lambda c=idx + 1, t=total, token=session_token: self._update_detection_progress_ui(c, t, token)
                    )

                if session_token != self._project_reset_token:
                    return

                meta_file = out_dir / "metadata.json"
                self._atomic_write_json(meta_file, local_meta)

                plates_with_chars = sum(
                    1 for pid in self.preview_plate_ids
                    if isinstance(local_meta.get(pid), dict) and local_meta[pid].get("characters")
                )
                self._log(
                    self.test_log_text,
                    f"\n[DIAG] Tablice z wykrytymi znakami: {plates_with_chars}/{total}",
                    "INFO"
                )

                if method in [DetectionMethod.YOLO, DetectionMethod.BOTH]:
                    self._log(
                        self.test_log_text,
                        f"[DIAG] YOLO boxy: raw={yolo_raw_total}, po filtracji={yolo_filtered_total}",
                        "INFO"
                    )

                acc = (stat_perfect / total * 100) if total > 0 else 0
                self._log(
                    self.test_log_text,
                    f"\nSkuteczność: {acc:.1f}% ({stat_perfect}/{total} tablic)",
                    "SUCCESS" if acc >= 80 else "WARNING"
                )

            except Exception as e:
                self._log(self.test_log_text, f"\n❌ BŁĄD: {e}", "ERROR")

            finally:
                def finalize():
                    if session_token != self._project_reset_token:
                        return

                    try:
                        self.fast_test_running = False
                        self.fast_test_stop.clear()

                        # Odśwież listę i preview na podstawie aktualnego metadata.
                        self._apply_preview_metadata_update(local_meta, preserve_selection=True)
                        self._loaded_meta_path = out_dir / "metadata.json"
                        try:
                            self._loaded_meta_mtime = self._loaded_meta_path.stat().st_mtime
                        except Exception:
                            self._loaded_meta_mtime = None

                        try:
                            method_name = (self.detection_method_var.get() or "OCR").upper().strip()

                            if method_name == "OCR":
                                self._set_winner_name("Brak zwycięzcy turnieju", "neutral")
                                self._set_winner_acc("Uruchom turniej presetów OCR", "muted")
                            elif method_name == "YOLO":
                                self._set_winner_name("Brak rankingu OCR", "neutral")
                                self._set_winner_acc("Tryb YOLO nie bierze udziału w turnieju OCR", "muted")
                            else:  # BOTH
                                self._set_winner_name("Brak rankingu OCR", "neutral")
                                self._set_winner_acc("Tryb hybrydowy nie ustala zwycięzcy turnieju OCR", "muted")
                        except Exception:
                            pass

                        try:
                            summary_msg = (
                                f"Podsumowanie detekcji: perfect={stat_perfect}/{total}, "
                                f"skuteczność={acc:.1f}%"
                            )
                            self._log(self.test_log_text, summary_msg, "INFO")
                        except Exception:
                            pass

                        self.test_progress.config(value=100)
                        self._set_test_progress_counter(total, total)
                        self._set_test_status(
                            f"Zakończono detekcję — skuteczność {acc:.1f}%",
                            "success"
                        )

                        # 7. odblokuj dalszy krok
                        self.unlock_dataset_subtab()

                        # 7. odblokuj dalszy krok
                        self.unlock_dataset_subtab()

                    except Exception as e:
                        logger.error(f"Błąd finalize() po Szybkim Teście: {e}")
                        self._set_test_status("Błąd odświeżania UI", "error")

                    finally:
                        self._unlock_ui_after_testing()

                self.frame.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # TAB 3: CVAT + YOLO exports/imports
    # =========================================================

    def _build_cvat_tab(self, parent):
        palette = getattr(self.app, "palette", {})

        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        export_lf = ttk.LabelFrame(pane, text=" Eksporty (dane wyjściowe) ", padding=15)
        pane.add(export_lf, weight=1)

        cvat_f = ttk.Frame(export_lf)
        cvat_f.pack(fill=tk.X, pady=(5, 5))
        self.cvat_option1_title_lbl = tk.Label(
            cvat_f,
            text="OPCJA 1: Ręczna poprawa błędów",
            anchor="w",
            justify="left",
            bd=0,
            highlightthickness=0
        )
        self.cvat_option1_title_lbl.pack(anchor=tk.W)
        self._set_inline_status_label_state(self.cvat_option1_title_lbl, tone="error", emphasis=True)
        self.cvat_option1_desc_lbl = tk.Label(
            export_lf,
            text="Eksport do CVAT obejmuje wyłącznie tablice oznaczone jako błędne (czerwone).",
            wraplength=320,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.cvat_option1_desc_lbl.pack(anchor=tk.W, pady=(0, 8))
        self._set_inline_status_label_state(self.cvat_option1_desc_lbl, tone="muted", emphasis=False)



        btn_cvat = ttk.Button(cvat_f, text="WYGENERUJ .ZIP DLA CVAT", command=self._run_cvat_export, style="Accent.TButton")
        btn_cvat.pack(fill=tk.X, pady=(5, 0), ipady=3)

        ttk.Separator(export_lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)

        yolo_f = ttk.Frame(export_lf)
        yolo_f.pack(fill=tk.X, pady=(0, 5))
        self.cvat_option2_title_lbl = tk.Label(
            yolo_f,
            text="OPCJA 2: Budowa datasetu (active learning)",
            anchor="w",
            justify="left",
            bd=0,
            highlightthickness=0
        )
        self.cvat_option2_title_lbl.pack(anchor=tk.W)
        self._set_inline_status_label_state(self.cvat_option2_title_lbl, tone="success", emphasis=True)
        self.cvat_option2_desc_lbl = tk.Label(
            yolo_f,
            text="Zbiera perfekcyjne tablice i buduje dataset YOLO.",
            wraplength=320,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.cvat_option2_desc_lbl.pack(anchor=tk.W, pady=(2, 8))
        self._set_inline_status_label_state(self.cvat_option2_desc_lbl, tone="muted", emphasis=False)

        btn_yolo = ttk.Button(yolo_f, text="WYEKSPORTUJ PERFEKCYJNE TABLICE DO YOLO", command=self._run_yolo_gold_export, style="Accent.TButton")
        btn_yolo.pack(fill=tk.X, ipady=4)

        info_lf = ttk.LabelFrame(export_lf, text=" Status i wskazówki ", padding=5)
        info_lf.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        self.export_console = tk.Text(
            info_lf,
            height=10,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg=palette.get("console_bg", "#252526"),
            fg=palette.get("console_fg", "#f3f3f3"),
            insertbackground=palette.get("console_fg", "#f3f3f3"),
            bd=0
        )
        self.export_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.export_console.insert(tk.END, "Oczekuję na akcję...")
        self.export_console.config(state=tk.DISABLED)

        import_lf = ttk.LabelFrame(pane, text=" Import poprawek znaków z CVAT ", padding=15)
        pane.add(import_lf, weight=1)

        self.cvat_import_title_lbl = tk.Label(
            import_lf,
            text="Importuj poprawki znaków z CVAT",
            anchor="w",
            justify="left",
            bd=0,
            highlightthickness=0
        )
        self.cvat_import_title_lbl.pack(anchor=tk.W)
        self._set_inline_status_label_state(self.cvat_import_title_lbl, tone="default", emphasis=True)
        self.cvat_import_desc_lbl = tk.Label(
            import_lf,
            text=(
                "Ten import służy wyłącznie do wczytywania ręcznie poprawionych "
                "adnotacji znaków z CVAT.\n"
                "Zaimportowane dane zostaną dołączone do puli treningowej modelu znaków. "
                "Wskaż plik *.xml z poprawkami."
            ),
            wraplength=320,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.cvat_import_desc_lbl.pack(anchor=tk.W, pady=(2, 8))
        self._set_inline_status_label_state(self.cvat_import_desc_lbl, tone="muted", emphasis=False)

        row2 = ttk.Frame(import_lf)
        row2.pack(fill=tk.X, pady=5)
        self.import_cvat_xml_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.import_cvat_xml_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Wybierz XML", command=lambda: self._pick_file(self.import_cvat_xml_var)).pack(side=tk.RIGHT, padx=(5, 0))

        btn_import = ttk.Button(import_lf, text="Importuj", command=self._run_cvat_import, style="Accent.TButton")
        btn_import.pack(fill=tk.X, pady=(10, 5), ipady=3)

        import_console_lf = ttk.LabelFrame(import_lf, text=" Status importu ", padding=5)
        import_console_lf.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        self.import_console = tk.Text(
            import_console_lf,
            height=4,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg=palette.get("console_bg", "#252526"),
            fg=palette.get("console_fg", "#f3f3f3"),
            insertbackground=palette.get("console_fg", "#f3f3f3"),
            bd=0
        )
        self.import_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.import_console.insert(tk.END, "Oczekuję na plik XML...")
        self.import_console.config(state=tk.DISABLED)

        
        HELP.bind_help(btn_cvat, "btn_export_cvat")
        HELP.bind_help(btn_yolo, "btn_export_yolo")
        HELP.bind_help(btn_import, "btn_import_cvat")

        nav = ttk.Frame(parent)
        nav.pack(fill=tk.X, padx=15, pady=(0, 10))

        ttk.Button(
            nav,
            text="← Wstecz do Wykrywania i Analizy",
            command=self.back_to_substep_2
        ).pack(side=tk.LEFT)

        self.btn_finish_step3_frame = tk.Frame(nav, bd=0, highlightthickness=0)
        self.btn_finish_step3_frame.pack(side=tk.RIGHT)

        self.btn_finish_step3_pulse_frame = tk.Frame(
            self.btn_finish_step3_frame,
            bd=0,
            highlightthickness=0
        )
        self.btn_finish_step3_pulse_frame.pack(anchor=tk.E)

        self.btn_finish_step3 = ttk.Button(
            self.btn_finish_step3_pulse_frame,
            text="Zakończ krok 3 i wróć do Wizarda",
            command=self._finalize_step3_from_existing_outputs,
            style="Accent.TButton",
            state=tk.DISABLED
        )
        self.btn_finish_step3.pack()

    def _set_console_text(self, console_widget, text):
        console_widget.config(state=tk.NORMAL)
        console_widget.delete(1.0, tk.END)
        console_widget.insert(tk.END, text)
        console_widget.config(state=tk.DISABLED)
        self.frame.update()

    def _pick_file(self, var):
        initial = self.preview_dir_var.get().strip()
        if not initial or not Path(initial).exists():
            initial = str(CONFIG.WORKSPACE_DIR.absolute())
        p = filedialog.askopenfilename(initialdir=initial, filetypes=[("XML", "*.xml")])
        if p:
            var.set(p)

    def _run_cvat_export(self):
        work_dir = Path(self.preview_dir_var.get().strip())

        export_dir = work_dir

        project_review_dir = self._get_project_review_dir()
        if project_review_dir is not None:
            try:
                preview_name = work_dir.name if work_dir.name else "review_pack"
            except Exception:
                preview_name = "review_pack"

            export_dir = project_review_dir / preview_name
            export_dir.mkdir(parents=True, exist_ok=True)
        meta_path = work_dir / "metadata.json"
        out_xml = export_dir / "annotations.xml"
        out_zip = export_dir / "cvat_export.zip"

        self._set_console_text(self.export_console, "⌛ Eksportowanie do CVAT w toku...")

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if self.smart_export_var.get():
                filtered = {k: v for k, v in metadata.items() if v.get("status") != "perfect"}
                tmp_meta = work_dir / "temp_meta.json"
                with open(tmp_meta, 'w', encoding='utf-8') as f:
                    json.dump(filtered, f, indent=2, ensure_ascii=False)
                source_meta = tmp_meta
            else:
                source_meta = meta_path

            from ..cvat_tools.cvat_character_exporter import CVATCharacterExporter
            from ..cvat_tools.cvat_zip_manager import CVATZipManager

            if CVATCharacterExporter().export(source_meta, out_xml):
                CVATZipManager.create_cvat_import_zip(out_xml, work_dir / "images", out_zip)
                self._set_console_text(self.export_console, f"✅ Wygenerowano ZIP:\n{out_zip}")
                try:
                    self._log(
                        self.export_console,
                        f"[INFO] Review pack zapisano w katalogu projektu: {export_dir}",
                        "INFO"
                    )
                except Exception:
                    pass
                try:
                    self._update_step3_finish_button_state()
                except Exception:
                    pass

                if self.smart_export_var.get() and source_meta.exists():
                    source_meta.unlink()

        except Exception as e:
            self._set_console_text(self.export_console, f"❌ BŁĄD EKSPORTU CVAT:\n{e}")

    def _run_yolo_gold_export(self):
        self._set_console_text(self.export_console, "⌛ Zbieranie idealnych tablic...")

        base_chars_dir = Path(getattr(self, "_campaign_chars_dir", str(CONFIG.DIR_3_CHARS)))

        import datetime, uuid, shutil
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        base_datasets_dir = Path(getattr(self, "_campaign_datasets_dir", str(CONFIG.DIR_4_DATASETS)))
        yolo_out = base_datasets_dir / f"YOLO_MegaDataset_Chars_{timestamp}"
        img_out, lbl_out = yolo_out / "images", yolo_out / "labels"

        try:
            img_out.mkdir(parents=True, exist_ok=True)
            lbl_out.mkdir(parents=True, exist_ok=True)

            char_map = {c: i for i, c in enumerate("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
            copied, seen = 0, set()

            meta_candidates = []
            for meta in base_chars_dir.rglob("metadata.json"):
                run_dir = meta.parent
                if (run_dir / "images").exists():
                    meta_candidates.append(meta)

            meta_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            for meta in meta_candidates:
                run_dir = meta.parent
                with open(meta, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

                for pid, data in {k: v for k, v in metadata.items() if v.get("status") == "perfect"}.items():
                    uk = f"{data.get('source_image', 'u')}_{int(data.get('source_bbox', [0])[0]//10) if data.get('source_bbox') else 0}"
                    if uk in seen:
                        continue
                    seen.add(uk)

                    img_src = run_dir / "images" / f"{pid}.jpg"
                    if not img_src.exists():
                        continue

                    img = cv2.imread(str(img_src))
                    if img is None:
                        continue

                    ih, iw = img.shape[:2]
                    new_pid = f"mega_{uuid.uuid4().hex[:8]}_{pid}"
                    shutil.copy2(img_src, img_out / f"{new_pid}.jpg")

                    txt = []
                    for c in data.get("characters", []):
                        ch = str(c.get("character", "")).upper()
                        if ch not in char_map:
                            continue
                        x1, y1, x2, y2 = c.get("bbox", [0, 0, 0, 0])
                        xc = max(0.0, min(1.0, ((x1 + x2) / 2.0) / iw))
                        yc = max(0.0, min(1.0, ((y1 + y2) / 2.0) / ih))
                        w = max(0.0, min(1.0, (x2 - x1) / iw))
                        h = max(0.0, min(1.0, (y2 - y1) / ih))
                        txt.append(f"{char_map[ch]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")

                    (lbl_out / f"{new_pid}.txt").write_text("\n".join(txt), encoding="utf-8")
                    copied += 1

            if copied == 0:
                msg = (
                    "❌ NIE UDAŁO SIĘ UTWORZYĆ DATASETU YOLO.\n\n"
                    "Powód: w bieżącym projekcie nie znaleziono ani jednej tablicy ze statusem 🟢 perfect.\n\n"
                    "CO DALEJ:\n"
                    "1. Możesz wrócić do pz2 i poprawić OCR / Laboratorium.\n"
                    "2. Możesz wykonać eksport do CVAT i później zaimportować poprawki.\n"
                    "3. Możesz też wrócić do wizarda i skorzystać z trybów naprawczych."
                )
                self._set_console_text(self.export_console, msg)

                try:
                    if self._step3_linear_mode and CAMPAIGN.get_active_project_name():
                        CAMPAIGN.set_step3_needs_rework()
                except Exception:
                    pass

                try:
                    self._update_step3_finish_button_state()
                except Exception:
                    pass

                try:
                    self.app.update_status(
                        "Nie utworzono gold packa — pozostajesz w z3/pz3, aby kontynuować pracę.",
                        "warning"
                    )
                except Exception:
                    pass

                return

            yaml_content = f"path: {yolo_out.absolute().as_posix()}\ntrain: images\nval: images\nnc: 36\nnames:\n"
            for char, class_id in char_map.items():
                yaml_content += f"  {class_id}: '{char}'\n"
            (yolo_out / "data.yaml").write_text(yaml_content, encoding="utf-8")

            self._set_console_text(self.export_console, f"✅ Dataset YOLO gotowy: {yolo_out}")
            try:
                self._update_step3_finish_button_state()
                self._set_button_emphasis("btn_finish_step3_frame", True)
                self._pulse_button_emphasis("btn_finish_step3_frame")
            except Exception:
                pass

            try:
                self.app.update_status(
                    "Paczka YOLO została utworzona poprawnie. Możesz zakończyć ten krok przyciskiem finish.",
                    "info"
                )
            except Exception:
                pass
        except Exception as e:
            self._set_console_text(self.export_console, f"❌ BŁĄD EKSPORTU YOLO:\n{e}")

    def _run_cvat_import(self):
        xml_in = Path(self.import_cvat_xml_var.get().strip())
        meta_path = Path(self.preview_dir_var.get().strip()) / "metadata.json"

        if not xml_in.exists():
            self._set_console_text(self.import_console, "❌ BŁĄD: Wybrany plik XML nie istnieje.")
            return

        self._set_console_text(self.import_console, "⌛ Wczytywanie danych z XML...")

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            root = ET.parse(xml_in).getroot()
            updated = 0

            for image in root.findall('.//image'):
                pid = Path(image.get('name', '')).stem
                if pid not in metadata:
                    continue

                new_chars = []
                for box in image.findall('box'):
                    if box.get('label', '').lower() in ['character', 'char']:
                        t = next((a.text for a in box.findall('attribute') if a.get('name') == 'text'), "?")
                        new_chars.append({
                            "character": t,
                            "bbox": [
                                float(box.get('xtl', 0)),
                                float(box.get('ytl', 0)),
                                float(box.get('xbr', 0)),
                                float(box.get('ybr', 0))
                            ],
                            "confidence": 1.0,
                            "method": "cvat_manual"
                        })

                metadata[pid]["characters"] = self._sort_character_records_by_x(new_chars)
                metadata[pid]["status"] = "perfect"
                updated += 1

            self._atomic_write_json(meta_path, metadata)
            self._apply_preview_metadata_update(metadata, preserve_selection=True)
            self._loaded_meta_path = meta_path
            try:
                self._loaded_meta_mtime = meta_path.stat().st_mtime
            except Exception:
                self._loaded_meta_mtime = None

            self._set_console_text(self.import_console, f"✅ Zaktualizowano: {updated} tablic.")
            try:
                stored_dir = self._store_current_preview_in_manual_char_pool(metadata)
                self._set_console_text(
                    self.import_console,
                    f"✅ Zaktualizowano: {updated} tablic.\n\n"
                    f"📦 Poprawki zapisano do puli ręcznej:\n{stored_dir}"
                )
            except Exception as e:
                logger.debug(f"Nie udało się zapisać paczki do manual_char_pool: {e}")
            try:
                self._update_step3_finish_button_state()
            except Exception:
                pass

        except Exception as e:
            self._set_console_text(self.import_console, f"❌ BŁĄD IMPORTU:\n{e}")

    # =========================================================
    # Ranking presetów OCR
    # =========================================================

    def _run_preset_ranking(self):
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj paczkę danych do testu!")

        preset_files = list(self.presets_dir.glob("*.json"))
        preset_files = [f for f in preset_files if f.name != "global_ranking.json"]
        if not preset_files:
            return messagebox.showinfo("Brak presetów", "Brak presetów! Otwórz Laboratorium i zapisz filtry jako JSON.")

        self.test_log_text.delete(1.0, tk.END)
        self._lock_ui_for_testing()
        self._set_test_progress_counter()
        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, "ROZPOCZYNAM TURNIEJ PRESETÓW", "HEADER")

        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"
        cache_file = self.presets_dir / "global_ranking.json"
        session_token = self._project_reset_token

        def worker():
            try:
                ranking_cache = {}
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            ranking_cache = json.load(f)
                    except Exception:
                        pass

                ocr_engine = PlateOCR(device=self._device_to_ocr(self.yolo_device_var.get()))
                detector = CharacterDetector(method=DetectionMethod.OCR, ocr_engine=ocr_engine)

                results_table = []
                total_imgs = len(self.preview_plate_ids)
                total_presets = len(preset_files)

                for p_idx, p_file in enumerate(preset_files):
                    if session_token != self._project_reset_token:
                        return

                    preset_name = p_file.stem
                    try:
                        with open(p_file, 'r', encoding='utf-8') as f:
                            preset_params = json.load(f)
                    except Exception:
                        continue

                    clean_params = {k: v for k, v in preset_params.items() if not k.startswith("char_do_") and k != "char_ocr_conf"}
                    param_signature = str(sorted(clean_params.items()))

                    if preset_name in ranking_cache and ranking_cache[preset_name].get("signature") == param_signature:
                        results_table.append((ranking_cache[preset_name]["acc"], ranking_cache[preset_name]["matches"], preset_name, True))
                        self.frame.after(
                            0,
                            lambda p=((p_idx + 1) / total_presets) * 100: (
                                self.test_progress.config(value=p)
                                if session_token == self._project_reset_token else None
                            )
                        )
                        continue

                    ocr_engine.custom_prep_params = clean_params
                    if "char_ocr_conf" in preset_params:
                        ocr_engine.confidence_threshold = float(preset_params.get("char_ocr_conf", 0.25))

                    perfect_matches = 0
                    for pid in self.preview_plate_ids:
                        if session_token != self._project_reset_token:
                            return

                        img_path = imgs_dir / f"{pid}.jpg"
                        if not img_path.exists():
                            continue
                        plate_img = cv2.imread(str(img_path))
                        if plate_img is None:
                            continue

                        expected = self._get_true_texts_from_filename(self.preview_metadata.get(pid, {}).get("source_image", ""))
                        chars = detector.detect(plate_img)
                        if "".join([str(c.character) for c in chars]) in expected:
                            perfect_matches += 1

                    acc = (perfect_matches / total_imgs) * 100 if total_imgs > 0 else 0
                    ranking_cache[preset_name] = {
                        "name": preset_name,
                        "acc": acc,
                        "matches": perfect_matches,
                        "signature": param_signature,
                        "params": preset_params
                    }
                    results_table.append((acc, perfect_matches, preset_name, False))
                    self.frame.after(
                        0,
                        lambda p=((p_idx + 1) / total_presets) * 100: (
                            self.test_progress.config(value=p)
                            if session_token == self._project_reset_token else None
                        )
                    )

                if session_token != self._project_reset_token:
                    return

                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(ranking_cache, f, indent=4, ensure_ascii=False)

                results_table.sort(key=lambda x: x[0], reverse=True)

                self._log(self.test_log_text, "=" * 55, "HEADER")
                for i, (acc, matches, name, from_cache) in enumerate(results_table):
                    self._log(self.test_log_text, f"#{i+1}. {name.ljust(22)} | {acc:5.1f}%  ({matches}/{total_imgs})", "SUCCESS" if i == 0 else "INFO")

                self.frame.after(0, self._update_winner_label)

            except Exception as e:
                self._log(self.test_log_text, f"\n❌ BŁĄD RANKINGU: {e}", "ERROR")
            finally:
                def finalize():
                    if session_token != self._project_reset_token:
                        return

                    if self._step3_linear_mode and CAMPAIGN.get_active_project_name():
                        self.unlock_dataset_subtab()

                    self.test_progress.config(value=100)
                    self._set_test_status("Turniej Zakończony!", "success")
                    self._unlock_ui_after_testing()

                self.frame.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    def _open_filter_lab(self):
        out_dir = Path(self.preview_dir_var.get().strip())
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj najpierw listę tablic.")

        imgs_dir = out_dir / "images"

        def roll_images():
            import random
            s = min(3, len(self.preview_plate_ids))
            ids = random.sample(self.preview_plate_ids, s)
            res = []
            for pid in ids:
                i = cv2.imread(str(imgs_dir / f"{pid}.jpg"))
                if i is not None:
                    res.append((pid, i))
            return res

        self.lab_current_images = roll_images()
        if not self.lab_current_images:
            return

        best_preset_data, best_acc = self._get_best_preset()

        lab_win = tk.Toplevel(self.frame)
        lab_win.title("Laboratorium Filtrów OCR")
        lab_win.geometry("1100x850")

        bottom_bar = ttk.Frame(lab_win, padding=10, relief="raised")
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Lokalny pasek pomocy dla okna laboratorium.
        lab_help_text = tk.Text(
            bottom_bar, height=2, wrap=tk.WORD,
            bg="#050505", bd=0, font=("Segoe UI", 10), fg="#f3f3f3", insertbackground="#f3f3f3"
        )
        lab_help_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        lab_help_text.insert(tk.END, "💡 Najedź myszką na nazwę suwaka, aby zobaczyć podpowiedź...")
        lab_help_text.config(state=tk.DISABLED)

        def update_lab_help(msg):
            if lab_win.winfo_exists():
                lab_help_text.config(state=tk.NORMAL)
                lab_help_text.delete(1.0, tk.END)
                lab_help_text.insert(tk.END, msg)
                lab_help_text.config(state=tk.DISABLED)

        self.old_status_updater = HELP.status_updater
        HELP.status_updater = update_lab_help

        main_content = ttk.Frame(lab_win)
        main_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left_container = ttk.Frame(main_content, width=350)
        left_container.pack(side=tk.LEFT, fill=tk.Y)
        left_container.pack_propagate(False)

        canvas_sliders = tk.Canvas(left_container, highlightthickness=0)
        scroll_sliders = ttk.Scrollbar(left_container, orient="vertical", command=canvas_sliders.yview)
        scrollable_frame = ttk.Frame(canvas_sliders, padding=10)

        frame_id = canvas_sliders.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas_sliders.bind("<Configure>", lambda e: canvas_sliders.itemconfig(frame_id, width=e.width))
        scrollable_frame.bind("<Configure>", lambda e: canvas_sliders.configure(scrollregion=canvas_sliders.bbox("all")))
        canvas_sliders.configure(yscrollcommand=scroll_sliders.set)

        scroll_sliders.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_sliders.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_view_container = ttk.Frame(main_content, padding=10)
        right_view_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        view_canvas = tk.Canvas(right_view_container, bg="#2c3e50", highlightthickness=0)
        view_scroll_v = ttk.Scrollbar(right_view_container, orient=tk.VERTICAL, command=view_canvas.yview)
        view_scroll_h = ttk.Scrollbar(right_view_container, orient=tk.HORIZONTAL, command=view_canvas.xview)

        view_scroll_h.pack(side=tk.BOTTOM, fill=tk.X)
        view_scroll_v.pack(side=tk.RIGHT, fill=tk.Y)
        view_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        view_canvas.configure(yscrollcommand=view_scroll_v.set, xscrollcommand=view_scroll_h.set)

        view_frame = ttk.Frame(view_canvas, style="Card.TFrame")
        view_canvas.create_window((0, 0), window=view_frame, anchor="nw")
        view_frame.bind("<Configure>", lambda e: view_canvas.configure(scrollregion=view_canvas.bbox("all")))

        self.lab_image_labels = []
        for i in range(3):
            f = ttk.LabelFrame(view_frame, text=f" Obraz testowy {i+1} ", padding=10)
            f.pack(fill=tk.BOTH, expand=True, pady=10, padx=10)

            lbl = ttk.Label(f, font=("Consolas", 10, "bold"))
            lbl.pack(anchor=tk.W, pady=(0, 5))

            c = ttk.Frame(f)
            c.pack(fill=tk.BOTH, expand=True)

            of_frame = ttk.Frame(c)
            of_frame.pack(side=tk.LEFT, padx=10, fill=tk.BOTH)
            o_lbl = tk.Label(of_frame, bg="#2c3e50", bd=2, relief="sunken")
            o_lbl.pack(anchor=tk.NW)

            pf_frame = ttk.Frame(c)
            pf_frame.pack(side=tk.LEFT, padx=20, fill=tk.BOTH)
            p_lbl = tk.Label(pf_frame, bg="black", bd=2, relief="solid")
            p_lbl.pack(anchor=tk.NW)

            self.lab_image_labels.append({
                "lbl": lbl,
                "orig": o_lbl,
                "proc": p_lbl
            })

        self.lab_photo_refs = []
        active_traces = []

        def update_preview(*args):
            if not lab_win.winfo_exists():
                return
            try:
                th = self.prep_height_var.get()
                ma = self.prep_angle_var.get()
                ct = self.prep_clip_var.get()
                dh = self.prep_denoise_var.get()
                cc = self.prep_clahe_var.get()
                use_bin = self.prep_use_bin_var.get()
                tb = self.prep_block_var.get()
                t_c = self.prep_c_var.get()
                if tb % 2 == 0:
                    tb += 1
                ei = self.prep_erode_var.get()

                interp_str = self.interpolation_var.get()
                interp_map = {
                    "nearest": cv2.INTER_NEAREST,
                    "linear": cv2.INTER_LINEAR,
                    "cubic": cv2.INTER_CUBIC,
                    "lanczos4": cv2.INTER_LANCZOS4
                }
                cv2_interp = interp_map.get(interp_str.lower(), cv2.INTER_LANCZOS4)

                self.lab_photo_refs.clear()

                for idx, (pid, orig_img) in enumerate(self.lab_current_images):
                    if idx >= len(self.lab_image_labels):
                        break

                    if abs(ma) > 0.1:
                        h, w = orig_img.shape[:2]
                        M = cv2.getRotationMatrix2D((w // 2, h // 2), ma, 1.0)
                        rotated = cv2.warpAffine(
                            orig_img, M, (w, h),
                            flags=cv2_interp,
                            borderMode=cv2.BORDER_REPLICATE
                        )
                    else:
                        rotated = orig_img.copy()

                    gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY) if len(rotated.shape) == 3 else rotated.copy()
                    h_g, w_g = gray.shape
                    scale = float(th) / h_g if h_g > 0 else 1.0
                    gray_scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2_interp)

                    po = ImageTk.PhotoImage(Image.fromarray(gray_scaled))

                    if ct < 255:
                        gray_scaled[gray_scaled > ct] = 255

                    den = cv2.fastNlMeansDenoising(
                        gray_scaled, None,
                        h=dh, templateWindowSize=7, searchWindowSize=21
                    ) if dh > 0 else gray_scaled

                    if self.do_clahe_var.get() and cc > 0:
                        clahe = cv2.createCLAHE(clipLimit=cc, tileGridSize=(8, 8))
                        contrasted = clahe.apply(den)
                    else:
                        contrasted = den

                    blurred = cv2.GaussianBlur(contrasted, (3, 3), 0)

                    if use_bin:
                        binary = cv2.adaptiveThreshold(
                            blurred, 255,
                            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY,
                            blockSize=max(3, tb),
                            C=t_c
                        )
                        if ei > 0:
                            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                            final = cv2.erode(binary, kernel, iterations=ei)
                        else:
                            final = binary
                    else:
                        final = contrasted

                    pad_pct = self.prep_padding_var.get()
                    if pad_pct > 0:
                        py = int(final.shape[0] * (pad_pct / 100.0))
                        px = int(final.shape[1] * (pad_pct / 100.0))
                        final = cv2.copyMakeBorder(final, py, py, px, px, cv2.BORDER_CONSTANT, value=255)

                    pp = ImageTk.PhotoImage(Image.fromarray(final))
                    self.lab_photo_refs.extend([po, pp])

                    ui_row = self.lab_image_labels[idx]
                    ui_row["lbl"].config(text=f"ID: {pid}")
                    ui_row["orig"].config(image=po)
                    ui_row["proc"].config(image=pp)

            except Exception:
                pass

        def add_slider(parent, label, var, from_, to_, res, ghost_key="", help_key=""):
            f = ttk.Frame(parent)
            f.pack(fill=tk.X, pady=4)

            lbl_f = ttk.Frame(f)
            lbl_f.pack(fill=tk.X)

            main_label = ttk.Label(lbl_f, text=label)
            main_label.pack(side=tk.LEFT)

            if ghost_key and best_preset_data and isinstance(best_preset_data.get("params"), dict):
                params_dict = best_preset_data["params"]
                if ghost_key in params_dict:
                    val = params_dict[ghost_key]
                    ghost_str = f"{val:.1f}" if isinstance(val, float) else str(val)
                    ttk.Label(
                        lbl_f,
                        text=f"[Zwycięzca: {ghost_str}]",
                        foreground="#2980b9",
                        font=("Segoe UI", 9, "bold")
                    ).pack(side=tk.RIGHT)

            s = ttk.Scale(f, from_=from_, to=to_, variable=var, command=update_preview)
            s.pack(side=tk.LEFT, fill=tk.X, expand=True)

            l = ttk.Label(f, width=5)
            l.pack(side=tk.RIGHT)

            def update_lbl(*a):
                if lab_win.winfo_exists():
                    l.config(text=f"{var.get():.{res}f}")

            trace_id = var.trace_add("write", update_lbl)
            active_traces.append((var, trace_id))
            update_lbl()

            if help_key:
                HELP.bind_help(main_label, help_key)
                HELP.bind_help(s, help_key)

        if best_preset_data and best_preset_data.get("name"):
            leader_f = tk.Frame(scrollable_frame, bg="#252526", bd=1, relief="solid")
            leader_f.pack(fill=tk.X, pady=(0, 15))
            tk.Label(
                leader_f,
                text=f"Lider: {best_preset_data.get('name').upper()}",
                bg="#252526", fg="#f3f3f3",
                font=("Segoe UI", 10, "bold")
            ).pack(pady=(5, 0))
            tk.Label(
                leader_f,
                text=f"Skuteczność: {best_acc:.1f}%",
                bg="#252526", fg="#c7c7c7",
                font=("Segoe UI", 9)
            ).pack(pady=(0, 5))
        else:
            ttk.Label(scrollable_frame, text="Dostrojenie Algorytmu", font=("Segoe UI", 12, "bold")).pack(pady=(0, 10))

        geom = ttk.LabelFrame(scrollable_frame, text=" 1. Geometria ", padding=10)
        geom.pack(fill=tk.X, pady=(0, 10))

        angle_row = ttk.Frame(geom)
        angle_row.pack(fill=tk.X)
        add_slider(angle_row, "Ręczna korekta kąta [°]:", self.prep_angle_var, -30, 30, 1, "manual_angle", "lab_angle")
        ttk.Button(geom, text="Reset Kąta", command=lambda: (self.prep_angle_var.set(0.0), update_preview())).pack(anchor=tk.E, pady=(0, 5))

        add_slider(geom, "Wysokość OCR (px):", self.prep_height_var, 40, 150, 0, "target_height", "lab_height")

        filt = ttk.LabelFrame(scrollable_frame, text=" 2. Filtry bazowe ", padding=10)
        filt.pack(fill=tk.X, pady=(0, 10))
        add_slider(filt, "Odcięcie odblasków (255=Wył):", self.prep_clip_var, 100, 255, 0, "clip_thresh", "lab_clip")
        add_slider(filt, "Usuwanie ziarna (0=Wył):", self.prep_denoise_var, 0, 50, 0, "denoise_h", "lab_denoise")
        cb2 = ttk.Checkbutton(filt, text="Wzmacniaj kontrast (CLAHE)", variable=self.do_clahe_var, command=update_preview)
        cb2.pack(anchor=tk.W)
        HELP.bind_help(cb2, "lab_clahe")
        add_slider(filt, "Siła CLAHE:", self.prep_clahe_var, 0.0, 10.0, 1, "clahe_clip", "lab_clahe")

        bina = ttk.LabelFrame(scrollable_frame, text=" 3. Binaryzacja ", padding=10)
        bina.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(bina, text="Włącz pełną binaryzację", variable=self.prep_use_bin_var, command=update_preview).pack(anchor=tk.W)
        add_slider(bina, "Rozmiar bloku (nieparzyste):", self.prep_block_var, 3, 51, 0, "thresh_block", "lab_block")
        add_slider(bina, "Stała odcięcia (C):", self.prep_c_var, -20, 20, 0, "thresh_c", "lab_c")
        add_slider(bina, "Pogrubianie liter (Erozja):", self.prep_erode_var, 0, 5, 0, "erode_iter", "lab_erode")
        add_slider(bina, "Biała ramka - Padding [%]:", self.prep_padding_var, 0, 50, 0, "padding_pct", "lab_pad")

        ocr_f = ttk.LabelFrame(scrollable_frame, text=" 4. Parametry Sieci (OCR) ", padding=10)
        ocr_f.pack(fill=tk.X, pady=(0, 10))
        add_slider(ocr_f, "Wymagany próg pewności (0-1.0):", self.ocr_conf_var, 0.05, 0.95, 2, "char_ocr_conf", "lab_conf")

        def load_preset():
            p = filedialog.askopenfilename(initialdir=self.presets_dir, filetypes=[("JSON", "*.json")], parent=lab_win)
            if p:
                try:
                    with open(p, 'r') as f: data = json.load(f)
                    if "target_height" in data: self.prep_height_var.set(data["target_height"])
                    if "clip_thresh" in data: self.prep_clip_var.set(data["clip_thresh"])
                    if "thresh_block" in data: self.prep_block_var.set(data["thresh_block"])
                    if "thresh_c" in data: self.prep_c_var.set(data["thresh_c"])
                    if "erode_iter" in data: self.prep_erode_var.set(data["erode_iter"])
                    if "padding_pct" in data: self.prep_padding_var.set(data["padding_pct"])
                    if "char_ocr_conf" in data: self.ocr_conf_var.set(data["char_ocr_conf"])
                    update_preview()
                except: pass

        def save_preset():
            name = simpledialog.askstring("Preset", "Podaj nazwę dla presetu:", parent=lab_win)
            if name:
                p = self.presets_dir / f"{name}.json"
                data = self._get_current_prep_params()
                data["char_ocr_conf"] = self.ocr_conf_var.get()
                with open(p, 'w') as f: json.dump(data, f, indent=4)

        def safe_close():
            for var, tid in active_traces:
                try: var.trace_remove("write", tid)
                except: pass
            self._force_save_all()
            self.lab_photoRefs = []
            HELP.status_updater = self.old_status_updater
            lab_win.destroy()

        lab_win.protocol("WM_DELETE_WINDOW", safe_close)
        ttk.Button(bottom_bar, text="Zapisz Preset", command=save_preset).pack(side=tk.RIGHT)
        ttk.Button(bottom_bar, text="Wczytaj Preset", command=load_preset).pack(side=tk.RIGHT)
        ttk.Button(bottom_bar, text="ZAMKNIJ", command=safe_close, style="Accent.TButton").pack(side=tk.RIGHT, padx=15)

        btn_roll = ttk.Button(
            bottom_bar,
            text="🎲 Losuj inną próbkę",
            command=lambda: (setattr(self, 'lab_current_images', roll_images()), update_preview())
        )
        btn_roll.pack(side=tk.RIGHT, padx=15)

        update_preview()
