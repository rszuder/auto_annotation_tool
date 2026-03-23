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
from pathlib import Path
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
        self._listbox_pid_by_index = []  # ✅ ZMIANA: index listbox -> pid (żeby nie rozjeżdżało się przy reloadach)
        self._current_photo = None
        self._reloading_preview = False          # ✅ ZMIANA: blokuje render w trakcie przebudowy listy



        # ✅ cache keys (run switching + file changes)
        self._loaded_meta_path = None
        self._loaded_meta_mtime = None

        # ✅ fast test state (separate from extraction)
        self.fast_test_stop = threading.Event()
        self.fast_test_running = False

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
  
        self._update_step3_source_path_lock()
        self._update_preview_path_lock()
        self.reset_subtab_flow()

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
            self.test_status_lbl.config(
                text=f"Pobieranie modelu: {label} {pct:.1f}%",
                foreground="#e67e22"
            )
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


    def _characters_to_text(self, chars) -> str:
        if chars is None:
            return ""

        if isinstance(chars, str):
            return chars

        if not isinstance(chars, list):
            return str(chars)

        prepared = []
        for i, rec in enumerate(chars):
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

            for pid in self._listbox_pid_by_index:
                data = self.preview_metadata.get(pid, {})
                label = self._format_plate_listbox_label(pid, data)
                self.plates_listbox.insert(tk.END, label)

            if selected_pid and selected_pid in self._listbox_pid_by_index:
                idx = self._listbox_pid_by_index.index(selected_pid)
                self.plates_listbox.selection_clear(0, tk.END)
                self.plates_listbox.selection_set(idx)
                self.plates_listbox.activate(idx)
                self.plates_listbox.see(idx)

            perfect = 0
            needs_fix = 0
            unknown = 0

            for pid in self._listbox_pid_by_index:
                status = str(self.preview_metadata.get(pid, {}).get("status", "unknown")).strip().lower()
                if status == "perfect":
                    perfect += 1
                elif status == "needs_fix":
                    needs_fix += 1
                else:
                    unknown += 1

            self.preview_info_lbl.config(
                text=f"Wczytano tablic: {len(self._listbox_pid_by_index)} | 🟢 {perfect} | 🔴 {needs_fix} | ⚪ {unknown}",
                foreground="#2980b9"
            )

            self.plates_listbox.update_idletasks()

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
                label = self._format_plate_listbox_label(plate_id, data)

                try:
                    self.plates_listbox.delete(idx)
                    self.plates_listbox.insert(idx, label)
                except Exception:
                    pass

            # jeśli z jakiegoś powodu lista w UI była krótsza, dopełnij brakujące rekordy
            if pid_count > row_count:
                for idx in range(row_count, pid_count):
                    plate_id = self._listbox_pid_by_index[idx]
                    data = self.preview_metadata.get(plate_id, {})
                    label = self._format_plate_listbox_label(plate_id, data)
                    try:
                        self.plates_listbox.insert(tk.END, label)
                    except Exception:
                        pass

            try:
                perfect = 0
                needs_fix = 0
                unknown = 0

                for pid in self._listbox_pid_by_index:
                    status = str(self.preview_metadata.get(pid, {}).get("status", "unknown")).strip().lower()
                    if status == "perfect":
                        perfect += 1
                    elif status == "needs_fix":
                        needs_fix += 1
                    else:
                        unknown += 1

                self.preview_info_lbl.config(
                    text=f"Wczytano tablic: {len(self._listbox_pid_by_index)} | 🟢 {perfect} | 🔴 {needs_fix} | ⚪ {unknown}",
                    foreground="#2980b9"
                )
            except Exception:
                pass

            try:
                self.plates_listbox.update_idletasks()
            except Exception:
                pass

        finally:
            self._reloading_preview = False

    def _refresh_plates_listbox(self, preserve_selection: bool = True):
        current_plate_id = None

        if preserve_selection:
            try:
                sel = self.plates_listbox.curselection()
                if sel:
                    idx = sel[0]
                    if 0 <= idx < len(self.preview_plate_ids):
                        current_plate_id = self.preview_plate_ids[idx]
            except Exception:
                current_plate_id = None

        try:
            self.plates_listbox.delete(0, tk.END)
        except Exception:
            return

        self.preview_plate_ids = []

        for plate_id, data in self.preview_metadata.items():
            if not isinstance(data, dict):
                continue

            status = str(data.get("status", "unknown")).strip().lower()
            chars = data.get("characters", []) or []
            chars_txt = "".join(str(c) for c in chars) if isinstance(chars, list) else str(chars)

            if status == "perfect":
                icon = "🟢"
            elif status == "needs_fix":
                icon = "🔴"
            else:
                icon = "⚪"

            label = f"{icon} {plate_id}"
            if chars_txt:
                label += f" [{chars_txt}]"

            self.plates_listbox.insert(tk.END, label)
            self.preview_plate_ids.append(plate_id)

        # spróbuj przywrócić zaznaczenie
        if current_plate_id and current_plate_id in self.preview_plate_ids:
            try:
                idx = self.preview_plate_ids.index(current_plate_id)
                self.plates_listbox.selection_clear(0, tk.END)
                self.plates_listbox.selection_set(idx)
                self.plates_listbox.activate(idx)
                self.plates_listbox.see(idx)
            except Exception:
                pass

        try:
            self.plates_listbox.update_idletasks()
        except Exception:
            pass

    def clear_campaign_context(self):
        """
        Czyści projektowy kontekst UI po wyjściu z projektu.
        """
        if hasattr(self, "_campaign_chars_dir"):
            self._campaign_chars_dir = None

        if hasattr(self, "_campaign_datasets_dir"):
            self._campaign_datasets_dir = None

        # wyczyść projektowe pola UI
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

        # wyczyść preview
        self._reset_preview_cache()
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
            self.preview_info_lbl.config(
                text="Brak wczytanych danych",
                foreground="#2980b9"
            )
        except Exception:
            pass

        # zresetuj stan testu
        try:
            self.fast_test_running = False
            self.fast_test_stop.clear()
        except Exception:
            pass

        try:
            self.test_progress.config(value=0)
        except Exception:
            pass

        try:
            self.test_status_lbl.config(
                text="Gotowy do testów",
                foreground="#2ecc71"
            )
        except Exception:
            pass

        # wróć do trybu swobodnego
        try:
            self.reset_subtab_flow()
        except Exception as e:
            logger.debug(f"Nie udało się zresetować liniowego flow kroku 3: {e}")
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

    # ===== START NOWEGO BLOKU =====
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
    # ===== KONIEC NOWEGO BLOKU =====


    def _on_yolo_arch_change(self, event=None):
        """
        Reaguje na zmianę wydania / rozmiaru YOLO.
        Nie nadpisuje panelu zwycięzcy turnieju OCR.
        """
        version = (self.yolo_model_version_var.get() or "").strip()
        size = (self.yolo_model_size_var.get() or "").strip().lower()

        if hasattr(self, "test_status_lbl"):
            self.test_status_lbl.config(
                text=f"Wybrana konfiguracja: YOLOv{version}{size}",
                foreground="#2980b9"
            )

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

        campaign_datasets_dir = getattr(self, "_campaign_datasets_dir", None)
        if campaign_datasets_dir:
            ds_root = Path(campaign_datasets_dir)
            if ds_root.exists():
                candidates = sorted(
                    [p for p in ds_root.iterdir() if p.is_dir()],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                if candidates:
                    gold_dataset_path = str(candidates[0])

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
            note="Finalizacja kroku 3 na podstawie istniejących artefaktów projektu."
        )

        self._write_step3_export_summary(summary)
        self._return_step3_result_to_wizard(summary)

    # ===== START NOWEGO BLOKU: katalogi puli danych znaków =====
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
    # ===== KONIEC NOWEGO BLOKU =====
        # ===== START NOWEGO BLOKU: katalog review packa projektu =====
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
    # ===== KONIEC NOWEGO BLOKU =====

    # ===== START NOWEGO BLOKU: zapis poprawionej paczki do manual_char_pool =====
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
    # ===== KONIEC NOWEGO BLOKU =====

    # ===== START NOWEGO BLOKU: stan artefaktów znakowych =====
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
    # ===== KONIEC NOWEGO BLOKU =====

    def _has_any_step3_export_outputs(self) -> bool:
        """
        Krok 3 można zakończyć dopiero, gdy istnieją artefakty związane
        z modelem znaków:
        - złota paczka znaków
        - import ręcznych poprawek znaków
        - scalona pula znaków
        - review pack do CVAT zapisany w katalogu projektu
        """
        try:
            if self._has_char_gold_exports():
                return True
        except Exception:
            pass

        try:
            if self._has_char_manual_imports():
                return True
        except Exception:
            pass

        merged_dir = self._get_char_merged_pool_dir()
        if merged_dir is not None and merged_dir.exists():
            try:
                if any(p.exists() for p in merged_dir.iterdir()):
                    return True
            except Exception:
                pass

        review_dir = self._get_project_review_dir()
        if review_dir is not None and review_dir.exists():
            try:
                if any(p.is_dir() for p in review_dir.iterdir()):
                    return True
            except Exception:
                pass

        return False
    
    # ===== START NOWEGO BLOKU =====
    def _update_step3_finish_button_state(self):
        btn = getattr(self, "btn_finish_step3", None)
        if btn is None:
            return

        enabled = self._has_any_step3_export_outputs()
        try:
            btn.config(state=("normal" if enabled else "disabled"))
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu btn_finish_step3: {e}")
    # ===== KONIEC NOWEGO BLOKU =====

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
        except Exception:
            pass

        try:
            self.test_status_lbl.config(
                text="Gotowy do testów",
                foreground="#2ecc71"
            )
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

        if self._step3_linear_mode:
            CAMPAIGN.set_step3_stage1_done(True)
            self._persist_step3_progress()
        

    def unlock_dataset_subtab(self):
        self._set_button_state("btn_to_dataset", True)
        self._set_button_emphasis("btn_run_detection_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", True)

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
            self._persist_step3_progress()

        self._select_subtab(self.tab_detect)
        self._set_button_emphasis("btn_run_detection_frame", True)
        self._set_button_emphasis("btn_to_dataset_frame", False)

    def go_to_substep_3(self):
        if self._step3_linear_mode:
            btn = getattr(self, "btn_to_dataset", None)
            if btn is not None and str(btn.cget("state")) != "normal":
                return

            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "normal")

            CAMPAIGN.set_step3_substep(3)
            self._persist_step3_progress()

        self._select_subtab(self.tab_dataset)
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
            CAMPAIGN.set_step3_stage1_done(False)
            CAMPAIGN.set_step3_stage2_done(False)
            self._persist_step3_progress()

        self._select_subtab(self.tab_extract)


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
            CAMPAIGN.set_step3_stage2_done(False)
            self._persist_step3_progress()

        self._select_subtab(self.tab_detect)
        self._set_button_emphasis("btn_run_detection_frame", True)
        self._set_button_emphasis("btn_to_dataset_frame", False)

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
        elif saved_substep == 2 and stage2_done:
            self._set_button_emphasis("btn_to_dataset_frame", True)
        elif saved_substep == 3:
            self._set_button_emphasis("btn_to_dataset_frame", False)

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
            self._sync_yolo_model_binding()
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
                self.winner_name_lbl.config(
                    text="Brak rankingu OCR",
                    foreground="gray"
                )
                self.winner_acc_lbl.config(
                    text="Tryb YOLO nie bierze udziału w turnieju OCR",
                    foreground="gray"
                )
            else:  # BOTH
                self.winner_name_lbl.config(
                    text="Brak rankingu OCR",
                    foreground="gray"
                )
                self.winner_acc_lbl.config(
                    text="Tryb hybrydowy nie ustala zwycięzcy turnieju OCR",
                    foreground="gray"
                )

        # Status dolny ma pokazywać, co użytkownik może teraz zrobić
        if hasattr(self, "test_status_lbl"):
            if is_yolo:
                version = (self.yolo_model_version_var.get() or "").strip()
                size = (self.yolo_model_size_var.get() or "").strip().lower()
                self.test_status_lbl.config(
                    text=f"Tryb YOLO: wybierz konfigurację i użyj 'Uruchom detekcję' (YOLOv{version}{size})",
                    foreground="#7f8c8d"
                )
            elif is_hybrid:
                version = (self.yolo_model_version_var.get() or "").strip()
                size = (self.yolo_model_size_var.get() or "").strip().lower()
                self.test_status_lbl.config(
                    text=f"Tryb hybrydowy: uruchom wspólną detekcję (YOLOv{version}{size} + OCR)",
                    foreground="#2980b9"
                )
            else:
                self.test_status_lbl.config(
                    text="Tryb OCR: możesz uruchomić detekcję lub turniej presetów OCR",
                    foreground="#2ecc71"
                )

    def _get_available_devices(self):
        devices = ["auto", "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    devices.append(f"cuda:{i}")
        except Exception:
            pass
        return devices

    def _device_to_ultralytics(self, s: str):
        if s == "auto":
            return "auto"
        if s == "cpu":
            return "cpu"
        if s.startswith("cuda:"):
            try:
                return int(s.split(":")[1].split()[0])
            except Exception:
                return 0
        return "auto"
    
    def _set_button_emphasis(self, frame_attr: str, enabled: bool, color: str = "#f39c12"):
        frame = getattr(self, frame_attr, None)
        if frame is None:
            return

        try:
            if enabled:
                frame.config(
                    highlightthickness=2,
                    highlightbackground=color,
                    highlightcolor=color,
                    bd=0
                )
            else:
                frame.config(
                    highlightthickness=0,
                    bd=0
                )
        except Exception as e:
            logger.debug(f"Nie udało się ustawić podświetlenia {frame_attr}: {e}")

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
            title="Wybierz annotations.xml",
            filetypes=[("XML", "*.xml")]
        )
        if p:
            self.xml_path_var.set(p)

    def _pick_images_dir(self):
        p = filedialog.askdirectory(
            initialdir=str(Path(CONFIG.DIR_1_RAW).absolute()),
            title="Wybierz folder z obrazami pojazdów"
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
        self.main_nb.add(self.tab_extract, text=f"{self.icon_manager.get('cut')} 1. Wycinanie Tablic")
        self._build_extraction_tab(self.tab_extract)

        self.tab_detect = ttk.Frame(self.main_nb)
        self.main_nb.add(self.tab_detect, text=f"{self.icon_manager.get('eye')} 2. Wykrywanie Znaków i Analiza")
        self._build_detection_tab(self.tab_detect)

        self.tab_dataset = ttk.Frame(self.main_nb)
        self.main_nb.add(self.tab_dataset, text=f"{self.icon_manager.get('save')} 3. Integracje i Dataset (YOLO)")
        self._build_cvat_tab(self.tab_dataset)

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

        ttk.Label(lf_paths, text="annotations.xml (z Zakładki Autoanotacja):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
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

        ttk.Label(lf_paths, text="Folder ze zdjęciami aut (źródło):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
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

        lf_run = ttk.LabelFrame(left, text=" Wycinanie Tablic ", padding=15)
        lf_run.pack(fill=tk.X)

        self.btn_extract = ttk.Button(lf_run, text="START (Wytnij tablice z paczki)", command=self._run_extraction, style="Accent.TButton")
        self.btn_extract.pack(fill=tk.X, ipady=5)

        self.btn_ext_stop = ttk.Button(lf_run, text="ZATRZYMAJ", command=lambda: setattr(self, 'is_processing', False), state=tk.DISABLED)
        self.btn_ext_stop.pack(fill=tk.X, pady=5)

        self.ext_progress = ttk.Progressbar(lf_run, maximum=100)
        self.ext_progress.pack(fill=tk.X, pady=(15, 5))
        self.ext_status = ttk.Label(lf_run, text="Gotowy", foreground="#2ecc71", font=("Segoe UI", 10, "bold"))
        self.ext_status.pack(anchor=tk.W)

        lf_logs = ttk.LabelFrame(right, text=" Logi z Wycinania ", padding=10)
        lf_logs.pack(fill=tk.BOTH, expand=True)
        self.ext_log = scrolledtext.ScrolledText(lf_logs, wrap=tk.WORD, font=("Consolas", 10), bg="#fdfdfd")
        self.ext_log.pack(fill=tk.BOTH, expand=True)

        HELP.bind_help(row_xml, "t2_xml")
        HELP.bind_help(row_img, "t2_img")
        HELP.bind_help(self.btn_extract, "t2_cut_start")
        HELP.bind_help(lf_logs, "t2_cut_logs")

        nav = ttk.Frame(parent)
        nav.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(
            nav,
            text="← Wstecz",
            state=tk.DISABLED
        ).pack(side=tk.LEFT)

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
        xml_path = Path(self.xml_path_var.get().strip())
        images_dir = Path(self.images_dir_var.get().strip())

        if not xml_path.exists() or not images_dir.exists():
            return messagebox.showerror("Błąd", "Brak plików wejściowych!")

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

        def worker():
            try:
                self._log(self.ext_log, f"\nROZPOCZĘTO WYCINANIE DO: {run_dir.name}\n", "HEADER")
                generator = PlateGenerator(run_dir)
                total = len(xml_images)
                processed = 0

                for img_name, img_el in xml_images.items():
                    if not self.is_processing:
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
                    self.frame.after(0, lambda p=(processed / max(1, total)) * 100: self.ext_progress.config(value=p))
                    self.frame.after(0, lambda c=processed, t=total: self.ext_status.config(text=f"{c}/{t} obrazów..."))

                generator.save_metadata()
                if self.is_processing:
                    self.frame.after(0, lambda: self._load_preview_data(quiet=True))
                    self.frame.after(0, self.unlock_detection_subtab)
                    self.frame.after(0, lambda: messagebox.showinfo(
                        "Gotowe",
                        "Wycinanie zakończone!\n\nOdblokowano etap 2: Wykrywanie Znaków i Analiza."
                    ))
            except Exception as e:
                self._log(self.ext_log, f"\n❌ BŁĄD: {e}\n", "ERROR")
            finally:
                self.is_processing = False
                self.frame.after(0, lambda: self.btn_extract.config(state=tk.NORMAL))
                self.frame.after(0, lambda: self.btn_ext_stop.config(state=tk.DISABLED))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # TAB 2: Detection + Preview
    # =========================================================

    def _build_detection_tab(self, parent):
        # =========================
        # LAYOUT ROOT
        # =========================
        parent.grid_rowconfigure(0, weight=0)  # header
        parent.grid_rowconfigure(1, weight=1)  # content
        parent.grid_rowconfigure(2, weight=0)  # footer
        parent.grid_columnconfigure(0, weight=1)

        # =========================
        # HEADER
        # =========================
        header_frame = ttk.Frame(parent)
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        header_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(
            header_frame,
            text="Paczka do analizy (folder run_XXX):",
            font=("Segoe UI", 9, "bold")
        ).grid(row=0, column=0, sticky="w")

        self.preview_dir_entry = ttk.Entry(
            header_frame,
            textvariable=self.preview_dir_var,
            state="readonly"
        )
        self.preview_dir_entry.grid(row=0, column=1, sticky="ew", padx=(5, 5))

        self.preview_dir_browse_btn = ttk.Button(
            header_frame,
            text="Otwórz inną paczkę",
            command=self._pick_and_load_preview_dir
        )
        self.preview_dir_browse_btn.grid(row=0, column=2, sticky="e", padx=(0, 5))

        self.preview_info_lbl = ttk.Label(
            header_frame,
            text="Wczytano tablic: 0",
            font=("Segoe UI", 9, "bold"),
            foreground="#2980b9"
        )
        self.preview_info_lbl.grid(row=0, column=3, sticky="e", padx=(10, 0))

        # =========================
        # CONTENT
        # =========================
        content_frame = ttk.Frame(parent)
        content_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 5))
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=1)

        main_pane = ttk.PanedWindow(content_frame, orient=tk.VERTICAL)
        main_pane.grid(row=0, column=0, sticky="nsew")

        top_split = ttk.Frame(main_pane)
        bottom_split = ttk.Frame(main_pane)

        main_pane.add(top_split, weight=5)
        main_pane.add(bottom_split, weight=3)

        # =========================
        # TOP SPLIT: lista + canvas
        # =========================
        top_split.grid_rowconfigure(0, weight=1)
        top_split.grid_columnconfigure(0, weight=1)

        viewer_pane = ttk.PanedWindow(top_split, orient=tk.HORIZONTAL)
        viewer_pane.grid(row=0, column=0, sticky="nsew")

        list_lf = ttk.LabelFrame(viewer_pane, text=" Lista tablic (🟢 Perfekt | 🔴 Błędy) ")
        preview_lf = ttk.LabelFrame(viewer_pane, text=" Podgląd OCR ")

        viewer_pane.add(list_lf, weight=2)
        viewer_pane.add(preview_lf, weight=3)

        list_lf.grid_rowconfigure(0, weight=1)
        list_lf.grid_columnconfigure(0, weight=1)

        self.plates_listbox = tk.Listbox(
            list_lf,
            font=("Consolas", 10),
            selectbackground="#3498db"
        )
        self.plates_listbox.grid(row=0, column=0, sticky="nsew", padx=(5, 0), pady=5)

        scroll = ttk.Scrollbar(list_lf, command=self.plates_listbox.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 5), pady=5)

        self.plates_listbox.config(yscrollcommand=scroll.set)
        self.plates_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

        preview_lf.grid_rowconfigure(0, weight=1)
        preview_lf.grid_columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            preview_lf,
            bg="#1e1e1e",
            bd=3,
            relief="sunken",
            highlightthickness=0
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.preview_canvas.bind("<Configure>", lambda e: self._on_preview_select(None))

        # =========================
        # BOTTOM SPLIT: 3 kolumny
        # =========================
        bottom_split.grid_rowconfigure(0, weight=1)
        bottom_split.grid_columnconfigure(0, weight=1)
        bottom_split.grid_columnconfigure(1, weight=1)
        bottom_split.grid_columnconfigure(2, weight=1)

        col_left = ttk.Frame(bottom_split)
        col_mid = ttk.Frame(bottom_split)
        col_right = ttk.Frame(bottom_split)

        col_left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        col_mid.grid(row=0, column=1, sticky="nsew", padx=5)
        col_right.grid(row=0, column=2, sticky="nsew", padx=(5, 0))

        col_left.grid_rowconfigure(0, weight=1)
        col_left.grid_columnconfigure(0, weight=1)

        col_mid.grid_rowconfigure(0, weight=1)
        col_mid.grid_columnconfigure(0, weight=1)

        col_right.grid_rowconfigure(0, weight=1)
        col_right.grid_columnconfigure(0, weight=1)

        # -------------------------
        # LEFT: konfiguracja
        # -------------------------
        set_lf = ttk.LabelFrame(col_left, text=" Konfiguracja Rozpoznawania ", padding=10)
        set_lf.grid(row=0, column=0, sticky="nsew")

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

        ttk.Label(self.det_device_row, text="Karta (Device):").pack(side=tk.LEFT)

        self.det_device_combo = ttk.Combobox(
            self.det_device_row,
            textvariable=self.yolo_device_var,
            values=self._get_available_devices(),
            state="readonly",
            width=12
        )
        self.det_device_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))

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
            foreground="gray"
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

        self._update_yolo_visibility()

        # -------------------------
        # MIDDLE: konsola
        # -------------------------
        log_lf = ttk.LabelFrame(col_mid, text=" Konsola informacji ", padding=10)
        log_lf.grid(row=0, column=0, sticky="nsew")

        self.test_log_text = scrolledtext.ScrolledText(
            log_lf,
            height=8,
            wrap=tk.WORD,
            font=("Consolas", 9)
        )
        self.test_log_text.pack(fill=tk.BOTH, expand=True)

        try:
            self.test_log_text.insert(tk.END, "Gotowy do uruchomienia detekcji znaków.\n")
            self.test_log_text.configure(state="disabled")
        except Exception:
            pass

        # -------------------------
        # RIGHT: OCR / ranking / lab
        # -------------------------
        self.actions_lf = ttk.LabelFrame(col_right, text=" Panel OCR / Ranking ", padding=10)
        self.actions_lf.grid(row=0, column=0, sticky="nsew")

        # 1. Zwycięzca turnieju
        ttk.Label(
            self.actions_lf,
            text="Wynik rankingu OCR:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))

        self.winner_name_lbl = ttk.Label(
            self.actions_lf,
            text="BRAK DANYCH",
            font=("Segoe UI", 11, "bold"),
            foreground="gray"
        )
        self.winner_name_lbl.pack(anchor=tk.W, pady=(0, 10))

        # 2. Skuteczność OCR
        ttk.Label(
            self.actions_lf,
            text="Wynik rankingu OCR:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))

        self.winner_acc_lbl = ttk.Label(
            self.actions_lf,
            text="0.0%",
            font=("Segoe UI", 10)
        )
        self.winner_acc_lbl.pack(anchor=tk.W, pady=(0, 10))

        ttk.Separator(self.actions_lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 10))

        # 3. Laboratorium OCR
        self.btn_ocr_lab = ttk.Button(
            self.actions_lf,
            text="LABORATORIUM OCR (FILTRY)",
            command=self._open_filter_lab,
            style="Accent.TButton"
        )
        self.btn_ocr_lab.pack(fill=tk.X, ipady=8, pady=(0, 10))

        # 4. Turniej
        self.btn_rank_presets = ttk.Button(
            self.actions_lf,
            text="Turniej presetów OCR",
            command=self._run_preset_ranking
        )
        self.btn_rank_presets.pack(fill=tk.X, ipady=6, pady=(0, 10))

        # Pasek postępu i status
        self.test_progress = ttk.Progressbar(self.actions_lf, maximum=100)
        self.test_progress.pack(fill=tk.X, pady=(5, 5))

        self.test_status_lbl = ttk.Label(
            self.actions_lf,
            text="Gotowy do testów",
            foreground="#2ecc71",
            font=("Segoe UI", 9, "bold")
        )
        self.test_status_lbl.pack(anchor=tk.W)

        # =========================
        # FOOTER
        # =========================
        footer_nav = ttk.Frame(parent)
        footer_nav.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        footer_nav.grid_columnconfigure(0, weight=0)
        footer_nav.grid_columnconfigure(1, weight=0)
        footer_nav.grid_columnconfigure(2, weight=1)
        footer_nav.grid_columnconfigure(3, weight=0)

        self.btn_back_to_extract = ttk.Button(
            footer_nav,
            text="← Wstecz do Wycinania Tablic",
            command=self.back_to_substep_1
        )
        self.btn_back_to_extract.grid(row=0, column=0, sticky="w")
        self.btn_run_detection_frame = tk.Frame(footer_nav, bd=0, highlightthickness=0)
        self.btn_run_detection_frame.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.btn_run_detection = ttk.Button(
            self.btn_run_detection_frame,
            text="Uruchom detekcję",
            command=self._run_detection_stage,
            style="Accent.TButton"
        )
        self.btn_run_detection.pack()
        self.btn_run_detection.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.btn_to_dataset_frame = tk.Frame(footer_nav, bd=0, highlightthickness=0)
        self.btn_to_dataset_frame.grid(row=0, column=3, sticky="e")

        self.btn_to_dataset = ttk.Button(
            self.btn_to_dataset_frame,
            text="Dalej → Integracje i Dataset",
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
        HELP.bind_help(self.btn_ocr_lab, "t2_lab_btn")
        HELP.bind_help(self.yolo_model_row, "t2_yolo_model")

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
            self.winner_name_lbl.config(text=f"Lider: {name.upper()} .json", foreground="green")
            self.winner_acc_lbl.config(text=f" Skuteczność najlepszego presetu: {best_acc:.1f}% ", foreground="green")
        else:
            self.winner_name_lbl.config(text="BRAK DANYCH Z TURNIEJU", foreground="gray")
            self.winner_acc_lbl.config(text="Skuteczność detekcji OCR: 0.0%", foreground="red")

    # =========================================================
    # Preview load + render
    # =========================================================
    def _load_preview_data(self, quiet=False):
        out_dir = Path(self.preview_dir_var.get().strip())
        meta_path = out_dir / "metadata.json"

        self.frame.after(0, self._update_winner_label)

        if not meta_path.exists():
            if not quiet:
                messagebox.showerror("Brak pliku", f"Nie znaleziono metadata.json w folderze:\n{out_dir}")
            self.preview_info_lbl.config(text="Brak wczytanych danych", foreground="red")
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

                self.preview_metadata = loaded
                self._loaded_meta_path = meta_path
                self._loaded_meta_mtime = current_mtime

                # Normalizacja schematu
                changed = False
                for pid, d in self.preview_metadata.items():
                    if not isinstance(d, dict):
                        continue
                    if "status" not in d:
                        d["status"] = "unknown"
                        changed = True
                    if "characters" not in d or not isinstance(d.get("characters"), list):
                        d["characters"] = []
                        changed = True

                if changed:
                    self._atomic_write_json(meta_path, self.preview_metadata)
                    self._loaded_meta_mtime = meta_path.stat().st_mtime

            # ==========================================================
            # ✅ START BLOKADY - Canvas nie może nic rysować w trakcie tej pętli
            # ==========================================================
            self._reloading_preview = True
            
            self.preview_plate_ids = sorted(list(self.preview_metadata.keys()))
            self.plates_listbox.delete(0, tk.END)
            self._listbox_pid_by_index = []  # Reset mapy PIDów

            for idx, pid in enumerate(self.preview_plate_ids):
                data = self.preview_metadata.get(pid, {})
                status = str(data.get("status", "unknown"))
                chars = data.get("characters", [])

                clean_chars = []
                if isinstance(chars, list):
                    for c in chars:
                        if isinstance(c, dict) and "character" in c and "bbox" in c:
                            bbox = c.get("bbox", [])
                            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                                clean_chars.append(c)

                clean_chars.sort(key=lambda x: float(x["bbox"][0]))
                text = "".join([str(c.get("character", "")).strip() for c in clean_chars])

                icon = "🟢" if status == "perfect" else "🔴" if status == "needs_fix" else "⚪"
                display_text = f"[{idx+1:03d}] {icon} Plik: {pid}  |  Odczyt: [{text}]"
                
                self.plates_listbox.insert(tk.END, display_text)
                self._listbox_pid_by_index.append(pid)  # Mapa 1:1 z wierszem

                current_idx = self.plates_listbox.size() - 1
                if status == "perfect":
                    self.plates_listbox.itemconfig(current_idx, foreground="#27ae60")
                elif status == "needs_fix":
                    self.plates_listbox.itemconfig(current_idx, foreground="#c0392b")

            self.preview_info_lbl.config(
                text=f"Wczytano tablic: {len(self.preview_plate_ids)} z folderu: {out_dir.name}",
                foreground="green"
            )

            if self.preview_plate_ids:
                self.plates_listbox.selection_set(0)
                self._on_preview_select(None)

            self.frame.after(100, self._update_winner_label)

        except Exception as e:
            if not quiet:
                messagebox.showerror("Błąd odświeżania listy", str(e))
            logger.error(f"Błąd _load_preview_data: {e}")
        finally:
            # ==========================================================
            # ✅ KONIEC BLOKADY - Zawsze zdejmij flagę, nawet jak jest błąd
            # ==========================================================
            self._reloading_preview = False

    def _refresh_listbox_rows_from_metadata(self):
        """Pełne odświeżenie tekstów i kolorów listy na podstawie aktualnego self.preview_metadata."""
        if not hasattr(self, "plates_listbox"):
            return

        self._reloading_preview = True
        try:
            current_sel = self.plates_listbox.curselection()
            selected_idx = int(current_sel[0]) if current_sel else None

            self.plates_listbox.delete(0, tk.END)
            self._listbox_pid_by_index = []

            self.preview_plate_ids = sorted(list(self.preview_metadata.keys()))

            for idx, pid in enumerate(self.preview_plate_ids):
                data = self.preview_metadata.get(pid, {})
                status = str(data.get("status", "unknown"))
                chars = data.get("characters", [])

                clean_chars = []
                if isinstance(chars, list):
                    for c in chars:
                        if isinstance(c, dict) and "character" in c and "bbox" in c:
                            bbox = c.get("bbox", [])
                            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                                clean_chars.append(c)

                clean_chars.sort(key=lambda x: float(x.get("bbox", [0])[0]))
                text = "".join([str(c.get("character", "")).strip() for c in clean_chars])

                icon = "🟢" if status == "perfect" else "🔴" if status == "needs_fix" else "⚪"
                display_text = f"[{idx+1:03d}] {icon} Plik: {pid}  |  Odczyt: [{text}]"

                self.plates_listbox.insert(tk.END, display_text)
                self._listbox_pid_by_index.append(pid)

                if status == "perfect":
                    self.plates_listbox.itemconfig(idx, foreground="#27ae60")
                elif status == "needs_fix":
                    self.plates_listbox.itemconfig(idx, foreground="#c0392b")
                else:
                    self.plates_listbox.itemconfig(idx, foreground="#444444")

            # Przywróć zaznaczenie, jeśli było
            if selected_idx is not None and 0 <= selected_idx < self.plates_listbox.size():
                self.plates_listbox.selection_set(selected_idx)
                self.plates_listbox.activate(selected_idx)

        finally:
            self._reloading_preview = False

    def _on_preview_select(self, event=None):
        """Podgląd tablicy + bboxy znaków. PID bierzemy z TEKSTU wiersza listy (zero rozjazdów)."""
        if not PIL_AVAILABLE:
            return

        # ✅ ZMIANA: jeśli akurat przebudowujemy listę - nie renderujemy
        if getattr(self, "_reloading_preview", False):
            return

        sel = self.plates_listbox.curselection()
        if not sel:
            return

        idx = int(sel[0])
        row_text = self.plates_listbox.get(idx)

        # ✅ ZMIANA: wyciągamy pid z wiersza listboxa (zawsze spójne z tym, co widzisz)
        import re
        m = re.search(r"Plik:\s*([^\s|]+)", row_text)
        if not m:
            return
        pid = m.group(1).strip()

        data = self.preview_metadata.get(pid, {})
        chars = data.get("characters", [])

        # ✅ ZMIANA: sort + tekst do podglądu (TA sama logika co lista)
        clean_chars = []
        if isinstance(chars, list):
            for c in chars:
                if isinstance(c, dict) and "character" in c and "bbox" in c:
                    bbox = c.get("bbox", [])
                    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                        clean_chars.append(c)

        clean_chars.sort(key=lambda x: float(x.get("bbox", [0])[0]))
        text_now = "".join([str(c.get("character", "")).strip() for c in clean_chars])

        status = str(data.get("status", "unknown"))
        icon = "🟢" if status == "perfect" else "🔴" if status == "needs_fix" else "⚪"
        display_text = f"[{idx+1:03d}] {icon} Plik: {pid}  |  Odczyt: [{text_now}]"

        # ✅ ZMIANA: samoleczenie listy - jeśli wiersz pokazuje stare `[...]`, nadpisz go
        if row_text != display_text:
            try:
                self._reloading_preview = True
                self.plates_listbox.delete(idx)
                self.plates_listbox.insert(idx, display_text)

                if status == "perfect":
                    self.plates_listbox.itemconfig(idx, foreground="#27ae60")
                elif status == "needs_fix":
                    self.plates_listbox.itemconfig(idx, foreground="#c0392b")
                else:
                    self.plates_listbox.itemconfig(idx, foreground="#000000")

                self.plates_listbox.selection_clear(0, tk.END)
                self.plates_listbox.selection_set(idx)
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

            margin_x, margin_y_top, margin_y_bottom = 80, 40, 140
            scale_w = (c_w - margin_x) / float(orig_w)
            scale_h = (c_h - (margin_y_top + margin_y_bottom)) / float(orig_h)
            SCALE = max(1.0, min(min(scale_w, scale_h), 6.0))

            new_w, new_h = int(orig_w * SCALE), int(orig_h * SCALE)
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            self._current_photo = ImageTk.PhotoImage(pil_img)
            x_off = (c_w - new_w) // 2
            y_off = (c_h - new_h - margin_y_bottom + margin_y_top) // 2

            self.preview_canvas.create_image(x_off, y_off, anchor=tk.NW, image=self._current_photo)
            image_bottom_y = y_off + new_h

            # rysowanie bboxów + znaków
            for c in clean_chars:
                x1, y1, x2, y2 = c.get("bbox", [0, 0, 0, 0])
                cx1, cy1 = (float(x1) * SCALE) + x_off, (float(y1) * SCALE) + y_off
                cx2, cy2 = (float(x2) * SCALE) + x_off, (float(y2) * SCALE) + y_off
                center_x = cx1 + (cx2 - cx1) / 2

                self.preview_canvas.create_rectangle(cx1, cy1, cx2, cy2, outline="#00ff00", width=2)

                text_anchor_y = image_bottom_y + 35
                self.preview_canvas.create_line(center_x, cy2, center_x, text_anchor_y - 20,
                                                fill="#2ecc71", dash=(2, 2))

                char_text = str(c.get("character", ""))
                self.preview_canvas.create_text(center_x + 1, text_anchor_y + 1, text=char_text,
                                                fill="#000000", font=("Segoe UI", 18, "bold"), anchor=tk.CENTER)
                self.preview_canvas.create_text(center_x, text_anchor_y, text=char_text,
                                                fill="#f1c40f", font=("Segoe UI", 18, "bold"), anchor=tk.CENTER)

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

        self.test_log_text.delete(1.0, tk.END)
        self._lock_ui_for_testing()
        self.test_status_lbl.config(text="Start detekcji...", foreground="#2980b9")
        self.test_progress.config(value=0)

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
                use_gpu = self.yolo_device_var.get().split()[0].lower().startswith("cuda")
                ocr_engine = PlateOCR(
                    device="cuda" if use_gpu else "cpu",
                    confidence_threshold=self.ocr_conf_var.get()
                )
                ocr_engine.custom_prep_params = prep_params
            except Exception as e:
                self._log(self.test_log_text, f"Błąd OCR Engine: {e}", "ERROR")
                ocr_engine = None

        detector = CharacterDetector(method=method, ocr_engine=ocr_engine, yolo_model=yolo_model)

        def worker():
            local_meta = dict(self.preview_metadata) if isinstance(self.preview_metadata, dict) else {}
            total = len(self.preview_plate_ids)
            stat_perfect = 0

            try:
                for idx, pid in enumerate(self.preview_plate_ids):
                    if self.fast_test_stop.is_set():
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

                    c_clean = [{
                        "character": str(c.character),
                        "bbox": [float(x) for x in c.bbox],
                        "confidence": float(c.confidence),
                        "method": str(c.method),
                    } for c in chars]

                    # WAŻNE: sortujemy znaki po X PRZED zapisem do metadata
                    c_clean.sort(
                        key=lambda x: (
                            float(x["bbox"][0]) if isinstance(x.get("bbox"), (list, tuple)) and len(x["bbox"]) >= 4 else 1e9
                        )
                    )

                    local_meta[pid]["characters"] = c_clean

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
                        lambda p=((idx + 1) / max(1, total)) * 100: self.test_progress.config(value=p)
                    )

                    self.frame.after(
                        0,
                        lambda c=idx + 1, t=total: self.test_status_lbl.config(
                            text=f"Detekcja {self._ascii_progress_bar(c, t)} {c}/{t}",
                            foreground="#e67e22"
                        )
                    )
                    

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
                    try:
                        self.fast_test_running = False
                        self.fast_test_stop.clear()

                        # 1. przejmujemy świeże metadata do pamięci
                        self.preview_metadata = local_meta

                        # 2. zachowujemy aktualne zaznaczenie po pid
                        selected_pid = None
                        try:
                            sel = self.plates_listbox.curselection()
                            if sel:
                                sel_idx = sel[0]
                                pid_map = getattr(self, "_listbox_pid_by_index", [])
                                if 0 <= sel_idx < len(pid_map):
                                    selected_pid = pid_map[sel_idx]
                        except Exception:
                            selected_pid = None

                        # 3. porządek listy: zachowaj bieżącą kolejność preview_plate_ids
                        current_order = [pid for pid in self.preview_plate_ids if pid in self.preview_metadata]
                        appended = [pid for pid in self.preview_metadata.keys() if pid not in current_order]
                        self.preview_plate_ids = current_order + appended
                        self._listbox_pid_by_index = list(self.preview_plate_ids)

                        # 4. przebuduj listbox z aktualnego metadata
                        self._reloading_preview = True
                        try:
                            self.plates_listbox.delete(0, tk.END)

                            perfect_count = 0
                            needs_fix_count = 0
                            unknown_count = 0

                            for pid in self._listbox_pid_by_index:
                                data = self.preview_metadata.get(pid, {})
                                status = str(data.get("status", "unknown")).strip().lower()
                                chars = data.get("characters", []) or []

                                if isinstance(chars, list):
                                    try:
                                        chars_sorted = sorted(
                                            chars,
                                            key=lambda rec: (
                                                float(rec["bbox"][0])
                                                if isinstance(rec, dict)
                                                and isinstance(rec.get("bbox"), (list, tuple))
                                                and len(rec["bbox"]) >= 4
                                                else 1e9
                                            )
                                        )
                                    except Exception:
                                        chars_sorted = chars

                                    chars_txt = "".join(
                                        str(
                                            rec.get("character")
                                            if isinstance(rec, dict)
                                            else rec
                                        )
                                        for rec in chars_sorted
                                    )
                                else:
                                    chars_txt = str(chars) if chars else ""

                                if status == "perfect":
                                    icon = "🟢"
                                    perfect_count += 1
                                elif status == "needs_fix":
                                    icon = "🔴"
                                    needs_fix_count += 1
                                else:
                                    icon = "⚪"
                                    unknown_count += 1

                                label = f"{icon} {pid}"
                                if chars_txt:
                                    label += f" [{chars_txt}]"

                                self.plates_listbox.insert(tk.END, label)

                            self.preview_info_lbl.config(
                                text=f"Wczytano tablic: {len(self._listbox_pid_by_index)} | 🟢 {perfect_count} | 🔴 {needs_fix_count} | ⚪ {unknown_count}",
                                foreground="#2980b9"
                            )

                            # 5. przywróć zaznaczenie albo wybierz pierwszy wpis
                            if selected_pid and selected_pid in self._listbox_pid_by_index:
                                idx = self._listbox_pid_by_index.index(selected_pid)
                                self.plates_listbox.selection_clear(0, tk.END)
                                self.plates_listbox.selection_set(idx)
                                self.plates_listbox.activate(idx)
                                self.plates_listbox.see(idx)
                            elif self.plates_listbox.size() > 0:
                                self.plates_listbox.selection_clear(0, tk.END)
                                self.plates_listbox.selection_set(0)
                                self.plates_listbox.activate(0)
                                self.plates_listbox.see(0)

                            self.plates_listbox.update_idletasks()

                        finally:
                            self._reloading_preview = False

                        
                        # 6. odśwież canvas i resztę UI na aktualnym wyborze
                        self._on_preview_select(None)

                        try:
                            method_name = (self.detection_method_var.get() or "OCR").upper().strip()

                            if method_name == "OCR":
                                self.winner_name_lbl.config(
                                    text="Brak zwycięzcy turnieju",
                                    foreground="gray"
                                )
                                self.winner_acc_lbl.config(
                                    text="Uruchom turniej presetów OCR",
                                    foreground="gray"
                                )
                            elif method_name == "YOLO":
                                self.winner_name_lbl.config(
                                    text="Brak rankingu OCR",
                                    foreground="gray"
                                )
                                self.winner_acc_lbl.config(
                                    text="Tryb YOLO nie bierze udziału w turnieju OCR",
                                    foreground="gray"
                                )
                            else:  # BOTH
                                self.winner_name_lbl.config(
                                    text="Brak rankingu OCR",
                                    foreground="gray"
                                )
                                self.winner_acc_lbl.config(
                                    text="Tryb hybrydowy nie ustala zwycięzcy turnieju OCR",
                                    foreground="gray"
                                )
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
                        self.test_status_lbl.config(
                            text=f"Zakończono detekcję — skuteczność {acc:.1f}%",
                            foreground="#2ecc71"
                        )

                        # 7. odblokuj dalszy krok
                        self.unlock_dataset_subtab()

                        # 7. odblokuj dalszy krok
                        self.unlock_dataset_subtab()

                    except Exception as e:
                        logger.error(f"Błąd finalize() po Szybkim Teście: {e}")
                        self.test_status_lbl.config(
                            text="Błąd odświeżania UI",
                            foreground="#c0392b"
                        )

                    finally:
                        self._unlock_ui_after_testing()

                self.frame.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # TAB 3: CVAT + YOLO exports/imports
    # =========================================================

    def _build_cvat_tab(self, parent):
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        export_lf = ttk.LabelFrame(pane, text=" EKSPORTY (Dane Wyjściowe) ", padding=15)
        pane.add(export_lf, weight=1)

        cvat_f = ttk.Frame(export_lf)
        cvat_f.pack(fill=tk.X, pady=(5, 5))
        ttk.Label(cvat_f, text="OPCJA 1: Ręczna poprawa błędów", font=("Segoe UI", 10, "bold"), foreground="#c0392b").pack(anchor=tk.W)
        ttk.Label(cvat_f, text="Generuje plik .ZIP dla programu CVAT. Eksportowane są tylko tablice z błędami (🔴).", foreground="gray").pack(anchor=tk.W, pady=(2, 8))

        cb_smart = ttk.Checkbutton(cvat_f, text="Tylko tablice z błędami (Czerwone)", variable=self.smart_export_var)
        cb_smart.pack(anchor=tk.W)

        btn_cvat = ttk.Button(cvat_f, text="WYGENERUJ .ZIP DLA CVAT", command=self._run_cvat_export, style="Accent.TButton")
        btn_cvat.pack(fill=tk.X, pady=(5, 0), ipady=3)

        ttk.Separator(export_lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)

        yolo_f = ttk.Frame(export_lf)
        yolo_f.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(yolo_f, text="OPCJA 2: Fabryka Datasetów (Active Learning)", font=("Segoe UI", 10, "bold"), foreground="#27ae60").pack(anchor=tk.W)
        ttk.Label(yolo_f, text="Zbiera 🟢 perfect i buduje dataset YOLO.", foreground="gray").pack(anchor=tk.W, pady=(2, 8))

        btn_yolo = ttk.Button(yolo_f, text="WYEKSPORTUJ PERFEKCYJNE TABLICE DO YOLO", command=self._run_yolo_gold_export, style="Accent.TButton")
        btn_yolo.pack(fill=tk.X, ipady=4)

        info_lf = ttk.LabelFrame(export_lf, text=" Status i Wskazówki ", padding=5)
        info_lf.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        self.export_console = tk.Text(info_lf, height=10, wrap=tk.WORD, font=("Consolas", 10), bg="#f8f9fa", bd=0)
        self.export_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.export_console.insert(tk.END, "Oczekuje na akcję...")
        self.export_console.config(state=tk.DISABLED)

        import_lf = ttk.LabelFrame(pane, text=" Import poprawek znaków z CVAT ", padding=15)
        pane.add(import_lf, weight=1)

        ttk.Label(import_lf, text="Importuj poprawki znaków z CVAT", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(import_lf,
                  text=" Ten import służy wyłącznie do wczytywania ręcznie poprawionych " \
                       " adnotacji znaków z CVAT.\n " \
                       " Zaimportowane dane zostaną dołączone do puli treningowej modelu znaków. Plik *.xml " ,
                         foreground="gray").pack(anchor=tk.W, pady=(2, 8))

        row2 = ttk.Frame(import_lf)
        row2.pack(fill=tk.X, pady=5)
        self.import_cvat_xml_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.import_cvat_xml_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Wybierz XML", command=lambda: self._pick_file(self.import_cvat_xml_var)).pack(side=tk.RIGHT, padx=(5, 0))

        btn_import = ttk.Button(import_lf, text="Importuj", command=self._run_cvat_import, style="Accent.TButton")
        btn_import.pack(fill=tk.X, pady=(10, 5), ipady=3)

        import_console_lf = ttk.LabelFrame(import_lf, text=" Status Importu ", padding=5)
        import_console_lf.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        self.import_console = tk.Text(import_console_lf, height=4, wrap=tk.WORD, font=("Consolas", 10), bg="#f8f9fa", bd=0)
        self.import_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.import_console.insert(tk.END, "Oczekuje na plik XML...")
        self.import_console.config(state=tk.DISABLED)

        HELP.bind_help(cb_smart, "cvat_smart_exp")
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

        # ===== START NOWEGO BLOKU =====
        self.btn_finish_step3 = ttk.Button(
            nav,
            text="Zakończ krok 3 i wróć do Wizarda",
            command=self._finalize_step3_from_existing_outputs,
            style="Accent.TButton",
            state=tk.DISABLED
        )
        self.btn_finish_step3.pack(side=tk.RIGHT)
        # ===== KONIEC NOWEGO BLOKU =====

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

        # ===== START NOWEGO BLOKU: wybór docelowego katalogu review =====
        export_dir = work_dir

        project_review_dir = self._get_project_review_dir()
        if project_review_dir is not None:
            try:
                preview_name = work_dir.name if work_dir.name else "review_pack"
            except Exception:
                preview_name = "review_pack"

            export_dir = project_review_dir / preview_name
            export_dir.mkdir(parents=True, exist_ok=True)
        # ===== KONIEC NOWEGO BLOKU =====
        # ===== START NOWEGO BLOKU: osobno ścieżka metadata preview =====
        meta_path = work_dir / "metadata.json"
        out_xml = export_dir / "annotations.xml"
        out_zip = export_dir / "cvat_export.zip"
        # ===== KONIEC NOWEGO BLOKU =====

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
                                # ===== START NOWEGO BLOKU: informacja o docelowym review dir =====
                try:
                    self._log(
                        self.export_console,
                        f"[INFO] Review pack zapisano w katalogu projektu: {export_dir}",
                        "INFO"
                    )
                except Exception:
                    pass
                # ===== KONIEC NOWEGO BLOKU =====
                # ===== START NOWEGO BLOKU =====
                try:
                    self._update_step3_finish_button_state()
                except Exception:
                    pass
                # ===== KONIEC NOWEGO BLOKU =====

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

            for run_dir in base_chars_dir.iterdir():
                meta = run_dir / "metadata.json"
                if not meta.exists():
                    continue
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
                    "1. Wróć do Autoanotacji i spróbuj ponownie na innych ustawieniach/modelu.\n"
                    "2. Albo pozostań w Zakładce Znaków i popraw OCR / Laboratorium.\n"
                    "3. Trening pozostaje zablokowany do czasu zbudowania poprawnej paczki YOLO."
                )
                self._set_console_text(self.export_console, msg)

                try:
                    from ..campaign_manager import CAMPAIGN
                    if CAMPAIGN.get_active_project_name():
                        CAMPAIGN.set_current_step(3)
                        CAMPAIGN.set_step3_needs_rework()

                        if 'campaign' in self.app.tabs:
                            self.app.tabs['campaign']._refresh_dashboard()

                    self.app.update_status(
                        "Krok 3 wymaga poprawy. Wracasz do Rozkładu Jazdy, aby wybrać ścieżkę naprawczą.",
                        "warning"
                    )

                    self.app.select_tab("campaign")
                    self.app.update_campaign_tab_access()

                except Exception:
                    pass

                return

            yaml_content = f"path: {yolo_out.absolute().as_posix()}\ntrain: images\nval: images\nnc: 36\nnames:\n"
            for char, class_id in char_map.items():
                yaml_content += f"  {class_id}: '{char}'\n"
            (yolo_out / "data.yaml").write_text(yaml_content, encoding="utf-8")

            self._set_console_text(self.export_console, f"✅ Dataset YOLO gotowy: {yolo_out}")
            # ===== START NOWEGO BLOKU =====
            try:
                self._update_step3_finish_button_state()
            except Exception:
                pass
            # ===== KONIEC NOWEGO BLOKU =====

            try:
                from ..campaign_manager import CAMPAIGN
                if CAMPAIGN.get_active_project_name() and CAMPAIGN.get_current_step() == 3:
                    CAMPAIGN.approve_step3()
                    CAMPAIGN.set_current_step(4)

                    if 'campaign' in self.app.tabs:
                        self.app.tabs['campaign']._refresh_dashboard()

                    # ✅ ZMIANA: po sukcesie też wracamy do Wizarda
                    self.app.update_status(
                        "Paczka YOLO została utworzona poprawnie. Odblokowano Krok 4 (Trening).",
                        "info"
                    )
                    self.app.select_tab("campaign")
                    self.app.update_campaign_tab_access()

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

                metadata[pid]["characters"] = new_chars
                metadata[pid]["status"] = "perfect"
                updated += 1

            self._atomic_write_json(meta_path, metadata)
            self._reset_preview_cache()
            self._load_preview_data(quiet=True)

            self._set_console_text(self.import_console, f"✅ Zaktualizowano: {updated} tablic.")
            # ===== START NOWEGO BLOKU: zapisz poprawki do manual_char_pool =====
            try:
                stored_dir = self._store_current_preview_in_manual_char_pool(metadata)
                self._set_console_text(
                    self.import_console,
                    f"✅ Zaktualizowano: {updated} tablic.\n\n"
                    f"📦 Poprawki zapisano do puli ręcznej:\n{stored_dir}"
                )
            except Exception as e:
                logger.debug(f"Nie udało się zapisać paczki do manual_char_pool: {e}")
            # ===== KONIEC NOWEGO BLOKU =====
            # ===== START NOWEGO BLOKU =====
            try:
                self._update_step3_finish_button_state()
            except Exception:
                pass
            # ===== KONIEC NOWEGO BLOKU =====

        except Exception as e:
            self._set_console_text(self.import_console, f"❌ BŁĄD IMPORTU:\n{e}")

    # =========================================================
    # Preset ranking (left as-is)
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
        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, "ROZPOCZYNAM TURNIEJ PRESETÓW", "HEADER")

        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"
        cache_file = self.presets_dir / "global_ranking.json"

        def worker():
            try:
                ranking_cache = {}
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            ranking_cache = json.load(f)
                    except Exception:
                        pass

                ocr_engine = PlateOCR(device='cuda' if self.yolo_device_var.get().startswith("cuda") else 'cpu')
                detector = CharacterDetector(method=DetectionMethod.OCR, ocr_engine=ocr_engine)

                results_table = []
                total_imgs = len(self.preview_plate_ids)
                total_presets = len(preset_files)

                for p_idx, p_file in enumerate(preset_files):
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
                        self.frame.after(0, lambda p=((p_idx + 1) / total_presets) * 100: self.test_progress.config(value=p))
                        continue

                    ocr_engine.custom_prep_params = clean_params
                    if "char_ocr_conf" in preset_params:
                        ocr_engine.confidence_threshold = float(preset_params.get("char_ocr_conf", 0.25))

                    perfect_matches = 0
                    for pid in self.preview_plate_ids:
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
                    self.frame.after(0, lambda p=((p_idx + 1) / total_presets) * 100: self.test_progress.config(value=p))

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
                self.frame.after(0, self._unlock_ui_after_testing)
                self.frame.after(0, lambda: self.test_progress.config(value=100))
                self.frame.after(0, lambda: self.test_status_lbl.config(text="Turniej Zakończony!", foreground="#2ecc71"))

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

        # ✅ Pasek pomocy dla okna Laboratorium
        lab_help_text = tk.Text(
            bottom_bar, height=2, wrap=tk.WORD,
            bg="#f0f0f0", bd=0, font=("Segoe UI", 10, "italic"), fg="#2980b9"
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
                        font=("Segoe UI", 9, "bold italic")
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
            leader_f = tk.Frame(scrollable_frame, bg="#fff3cd", bd=1, relief="solid")
            leader_f.pack(fill=tk.X, pady=(0, 15))
            tk.Label(
                leader_f,
                text=f"Lider: {best_preset_data.get('name').upper()}",
                bg="#fff3cd", fg="#8a6d3b",
                font=("Arial", 10, "bold")
            ).pack(pady=(5, 0))
            tk.Label(
                leader_f,
                text=f"Skuteczność: {best_acc:.1f}%",
                bg="#fff3cd", fg="#8a6d3b",
                font=("Arial", 9)
            ).pack(pady=(0, 5))
        else:
            ttk.Label(scrollable_frame, text="Dostrojenie Algorytmu", font=("Arial", 12, "bold")).pack(pady=(0, 10))

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