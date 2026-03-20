#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Rozkład Jazdy (Dashboard Kampanii MLOps).
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
import os

from ..config import CONFIG, logger
from ..campaign_manager import CAMPAIGN
from ..icons import IconManager
from .help_manager import HELP


class CampaignTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        self.frame = ttk.Frame(parent)

        # UI state
        self.roadmap_ui_elements = []
        self.right_panel = None

        self._build_ui()
        self._refresh_dashboard()

    # ======================================================
    # UI BUILD
    # ======================================================

    def _build_ui(self):
        header_f = ttk.Frame(self.frame, padding=15)
        header_f.pack(fill=tk.X)

        # Uwaga: nie używamy trophy z IconManager, bo fallback daje [Ranking]
        self.lbl_title = tk.Label(
            header_f,
            text="MENADŻER KAMPANII (PROJEKTY)",
            font=("Segoe UI", 16, "bold"),
            fg="#2c3e50"
        )
        self.lbl_title.pack(side=tk.LEFT)

        proj_frame = ttk.Frame(header_f)
        proj_frame.pack(side=tk.LEFT, padx=(10, 0))

        self.proj_combo_var = tk.StringVar()
        self.proj_combo = ttk.Combobox(
            proj_frame, textvariable=self.proj_combo_var,
            state="readonly", width=25
        )
        self.proj_combo.pack(side=tk.LEFT, padx=5)
        self.proj_combo.bind("<<ComboboxSelected>>", self._on_project_changed)

        self.btn_add_proj = ttk.Button(proj_frame, text="Nowy Projekt", command=self._add_new_project)
        self.btn_add_proj.pack(side=tk.LEFT, padx=5)

        self.btn_del_proj = ttk.Button(proj_frame, text="Usuń", command=self._delete_project)
        self.btn_del_proj.pack(side=tk.LEFT, padx=5)

        self.lbl_iter = tk.Label(
            header_f,
            text="Iteracja: -",
            font=("Segoe UI", 14, "bold"),
            fg="#e74c3c",
            bg="#fadbd8",
            padx=10,
            pady=5
        )
        self.lbl_iter.pack(side=tk.RIGHT)

        ttk.Separator(self.frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15)

        main_container = ttk.Frame(self.frame, padding=15)
        main_container.pack(fill=tk.BOTH, expand=True)

        # LEFT PANEL
        left_panel = ttk.LabelFrame(main_container, text=" Wiedza Algorytmów (Aktywny Projekt) ", padding=15)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        tk.Label(
            left_panel,
            text="Mózg projektu (aktualizuje się automatycznie po treningu).\n"
                 "Przycisk 'Zmień' to override/serwis.",
            justify=tk.LEFT, fg="gray"
        ).pack(anchor=tk.W, pady=(0, 15))

        self._build_model_status(left_panel, "Model Pojazdów (Detect):", "vehicle", Path(CONFIG.DIR_6_MODELS))
        self._build_model_status(left_panel, "Model Tablic (Pose):", "plate", Path(CONFIG.DIR_6_MODELS))
        self._build_model_status(left_panel, "Model Znaków (OCR/YOLO):", "char", Path(CONFIG.DIR_6_MODELS))

        self.btn_advance = ttk.Button(
            left_panel,
            text="Awansuj do Nowej Iteracji",
            command=self._advance_iteration,
            style="Accent.TButton"
        )
        self.btn_advance.pack(side=tk.BOTTOM, fill=tk.X, pady=10)

        HELP.bind_help(left_panel, "camp_models")
        HELP.bind_help(self.btn_advance, "camp_advance")

        # RIGHT PANEL
        self.right_panel = ttk.LabelFrame(main_container, text=" Rozkład Jazdy (Cykl Active Learningu) ", padding=15)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._rebuild_roadmap_ui()

    def _build_model_status(self, parent, title, model_type, initial_dir: Path):
        f = ttk.Frame(parent)
        f.pack(fill=tk.X, pady=10)

        tk.Label(f, text=title, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)

        row = ttk.Frame(f)
        row.pack(fill=tk.X)

        lbl_val = tk.Label(row, text="Domyślny/Brak", fg="#2980b9", font=("Consolas", 10))
        lbl_val.pack(side=tk.LEFT, expand=True, anchor=tk.W)

        btn = ttk.Button(row, text="Zmień", command=lambda: self._set_model(model_type, initial_dir))
        btn.pack(side=tk.RIGHT)

        setattr(self, f"lbl_model_{model_type}", lbl_val)
        setattr(self, f"btn_model_{model_type}", btn)

    def _set_model(self, model_type, initial_dir: Path):
        p = filedialog.askopenfilename(
            initialdir=str(initial_dir),
            filetypes=[("YOLO Model", "*.pt")]
        )
        if p:
            CAMPAIGN.set_global_model(model_type, p)
            self._refresh_dashboard()

    # ======================================================
    # ROADMAP UI (rebuild to avoid ttk ghosting)
    # ======================================================

    def _build_roadmap_step(self, parent, step_num, title, desc, btn_text, command):
        f = ttk.Frame(parent)
        f.pack(fill=tk.X, pady=10)

        text_f = ttk.Frame(f)
        text_f.pack(side=tk.LEFT, fill=tk.X, expand=True)

        lbl_title = tk.Label(text_f, text=title, font=("Segoe UI", 12, "bold"))
        lbl_title.pack(anchor=tk.W)

        lbl_desc = tk.Label(text_f, text=desc, fg="#7f8c8d")
        lbl_desc.pack(anchor=tk.W)

        btn = ttk.Button(f, text=btn_text, command=command, width=25)
        btn.pack(side=tk.RIGHT, padx=10)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        self.roadmap_ui_elements.append({
            "step_num": step_num,
            "original_title": title,
            "orig_btn_text": btn_text,
            "lbl_title": lbl_title,
            "lbl_desc": lbl_desc,
            "btn": btn
        })

    def _rebuild_roadmap_ui(self):
        for widget in self.right_panel.winfo_children():
            widget.destroy()
        self.roadmap_ui_elements = []

        self._build_roadmap_step(
            self.right_panel, 1,
            "1. Ingestia Danych",
            "Utwórz katalog iteracji i zatwierdź, że znajdują się w nim obrazy.",
            "Utwórz / Zatwierdź", self._step_create_raw_folder
        )
        self._build_roadmap_step(
            self.right_panel, 2,
            "2. Detekcja kaskadowa (Autoanotacja)",
            "Ustawia automatycznie ścieżki IN/OUT i przenosi do Autoanotacji.",
            "Skocz: Autoanotacja", self._step_goto_auto_annotation
        )
        self._build_roadmap_step(
            self.right_panel, 3,
            "3. Wycinanie tablic + Złota paczka",
            "Ustawia XML + folder obrazów (z projektu) i przenosi do Zakładki Znaków.",
            "Skocz: Znaki", self._step_goto_characters
        )
        self._build_roadmap_step(
            self.right_panel, 4,
            "4. Trening i analiza",
            "Przenosi do Zakładki Trening. (Krok odblokuje się po zbudowaniu datasetu).",
            "Skocz: Trening", self._step_goto_training
        )

        # Help bindings for steps (fresh widgets)
        steps_frames = [f for f in self.right_panel.winfo_children() if isinstance(f, ttk.Frame)]
        if len(steps_frames) >= 4:
            HELP.bind_help(steps_frames[0], "camp_step1")
            HELP.bind_help(steps_frames[1], "camp_step2")
            HELP.bind_help(steps_frames[2], "camp_step3")
            HELP.bind_help(steps_frames[3], "camp_step4")

    # ======================================================
    # DASHBOARD REFRESH
    # ======================================================

    def _refresh_dashboard(self):
        self._refresh_projects_list()

        active_proj = CAMPAIGN.get_active_project_name()
        all_projs = CAMPAIGN.get_all_projects()
        has_project = bool(active_proj) and (active_proj in all_projs)

        # ====== NO PROJECT => LOCK EVERYTHING ======
        if not has_project:
            self.lbl_iter.config(text="Iteracja: -")

            # Left panel lock
            for mt in ["vehicle", "plate", "char"]:
                getattr(self, f"lbl_model_{mt}").config(text="Zablokowane", fg="gray")
                getattr(self, f"btn_model_{mt}").config(state="disabled")

            self.btn_del_proj.config(state="disabled")
            self.btn_advance.config(text="Utwórz projekt ↗", state="disabled", style="TButton")

            # Right panel lock
            for item in self.roadmap_ui_elements:
                item["lbl_title"].config(text=f"🔒 {item['original_title']}", fg="#bdc3c7")
                item["lbl_desc"].config(fg="#bdc3c7")
                item["btn"].config(text="Zablokowane", style="TButton", state="disabled")

            self._update_main_tabs_highlight(curr_step=1, has_project=False)
            self.frame.update_idletasks()
            return

        # ====== ACTIVE PROJECT ======
        self.btn_del_proj.config(state="normal")

        curr_step = CAMPAIGN.get_current_step()
        iter_num = CAMPAIGN.get_current_iteration_num()
        self.lbl_iter.config(text=f"Iteracja: {iter_num}")

        # Advance iteration locked until step >=5 (jeśli masz taki model)
        if curr_step >= 5:
            self.btn_advance.config(text="🎉 Cykl zakończony → Nowa Iteracja", state="normal", style="Accent.TButton")
        else:
            self.btn_advance.config(text=f"Awans zablokowany (Krok {curr_step})", state="disabled", style="TButton")

        # Models UI
        for mt in ["vehicle", "plate", "char"]:
            getattr(self, f"btn_model_{mt}").config(state="normal")

        def fmt_model(p):
            return Path(p).name if p and Path(p).exists() else "Domyślny/Brak"

        self.lbl_model_vehicle.config(text=fmt_model(CAMPAIGN.get_global_model("vehicle")), fg="#2980b9")
        self.lbl_model_plate.config(text=fmt_model(CAMPAIGN.get_global_model("plate")), fg="#2980b9")
        self.lbl_model_char.config(text=fmt_model(CAMPAIGN.get_global_model("char")), fg="#2980b9")

        # Step 1 folder existence (project-aware)
        raw_dir = CAMPAIGN.get_dir("raw")
        step1_folder_exists = False
        if raw_dir:
            step1_folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
            step1_folder_exists = step1_folder.exists()

        # Wizard-style painting
        for item in self.roadmap_ui_elements:
            s = item["step_num"]
            title = item["original_title"]
            orig_btn_txt = item["orig_btn_text"]
            btn = item["btn"]

            if s < curr_step:
                item["lbl_title"].config(text=f"✅ {title}", fg="#27ae60")
                item["lbl_desc"].config(fg="#7f8c8d")
                btn.config(text="Wykonano (skocz)", style="TButton", state="normal")

            elif s == curr_step:
                item["lbl_title"].config(text=f"🔵 {title}", fg="#2980b9")
                item["lbl_desc"].config(fg="#2c3e50")

                if s == 1:
                    btn.config(
                        text="Zatwierdź pliki" if step1_folder_exists else "Utwórz folder",
                        style="Accent.TButton",
                        state="normal"
                    )
                else:
                    btn.config(text=orig_btn_txt, style="Accent.TButton", state="normal")

            else:
                item["lbl_title"].config(text=f"⚪ {title}", fg="#bdc3c7")
                item["lbl_desc"].config(fg="#bdc3c7")
                btn.config(text=orig_btn_txt, style="TButton", state="disabled")

        self._update_main_tabs_highlight(curr_step=curr_step, has_project=True)
        self.frame.update_idletasks()

    def _update_main_tabs_highlight(self, curr_step, has_project):
        nb = self.app.notebook
        try:
            tabs_count = nb.index("end")
        except Exception:
            return

        # clear
        for i in range(tabs_count):
            txt = nb.tab(i, "text")
            clean_txt = txt.replace("⭐ ", "").replace(" ⭐", "")
            nb.tab(i, text=clean_txt)

        if not has_project:
            return

        # indices assumed: 0 campaign, 1 annotation, 2 characters, 3 training
        target_idx = 0
        if curr_step == 2:
            target_idx = 1
        elif curr_step == 3:
            target_idx = 2
        elif curr_step >= 4:
            target_idx = 3

        if target_idx < tabs_count:
            txt = nb.tab(target_idx, "text")
            nb.tab(target_idx, text=f"⭐ {txt} ⭐")

    # ======================================================
    # PROJECT CRUD
    # ======================================================

    def _refresh_projects_list(self):
        projects = CAMPAIGN.get_all_projects()
        self.proj_combo["values"] = projects
        active = CAMPAIGN.get_active_project_name()
        if active in projects:
            self.proj_combo_var.set(active)
        elif projects:
            # fallback to first
            self.proj_combo_var.set(projects[0])
            CAMPAIGN.set_active_project(projects[0])
        else:
            self.proj_combo_var.set("")

    def _on_project_changed(self, event=None):
        selected = self.proj_combo_var.get()
        if selected:
            CAMPAIGN.set_active_project(selected)
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()

    def _add_new_project(self):
        new_name = simpledialog.askstring("Nowy Projekt", "Podaj unikalną nazwę projektu:", parent=self.frame)
        if not new_name:
            return
        if CAMPAIGN.create_project(new_name):
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()
            messagebox.showinfo("Sukces", f"Projekt '{new_name}' utworzony.")
        else:
            messagebox.showerror("Błąd", "Projekt o takiej nazwie już istnieje lub nazwa jest nieprawidłowa.")

    def _delete_project(self):
        active = CAMPAIGN.get_active_project_name()
        if not active:
            return
        if not messagebox.askyesno("OSTRZEŻENIE", f"Usunąć projekt '{active}' (cały katalog projektu)?"):
            return

        if CAMPAIGN.delete_project(active):
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()
            messagebox.showinfo("Usunięto", "Projekt został usunięty.")

    # ======================================================
    # STEPS
    # ======================================================

    def _step_create_raw_folder(self):
        if not CAMPAIGN.get_active_project_name():
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        if raw_dir is None:
            logger.error("Brak raw_dir dla projektu.")
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"

        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            messagebox.showinfo(
                "Folder utworzony",
                f"Katalog iteracji:\n{folder}\n\nSkopiuj zdjęcia i kliknij ponownie, aby zatwierdzić."
            )
            try:
                os.startfile(folder)
            except Exception:
                pass
            self._refresh_dashboard()
            return

        images = [f for f in folder.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
        if images:
            CAMPAIGN.set_current_step(2)
            self._refresh_dashboard()
            try:
                self.app.update_status(f"✅ Zatwierdzono {len(images)} obrazów w {folder.name}. Odblokowano Krok 2.", "info")
            except Exception:
                pass
        else:
            messagebox.showwarning("Brak plików", "Folder jest pusty. Dodaj obrazy i spróbuj ponownie.")
            try:
                os.startfile(folder)
            except Exception:
                pass

    def _step_goto_auto_annotation(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 2:
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_out = CAMPAIGN.get_dir("auto_ann")
        if raw_dir is None or auto_out is None:
            logger.error("Brak katalogów projektu (raw/auto_ann).")
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"

        tab_ann = self.app.tabs.get("annotation")
        if tab_ann:
            if folder.exists():
                tab_ann.input_dir_var.set(str(folder))

            # output autoanotacji kierujemy do projektu
            tab_ann.output_dir_var.set(str(auto_out))

            v_mod = CAMPAIGN.get_global_model("vehicle")
            p_mod = CAMPAIGN.get_global_model("plate")

            if v_mod and Path(v_mod).exists():
                tab_ann.vehicle_model_var.set("Custom")
                tab_ann.vehicle_custom_var.set(v_mod)
            if p_mod and Path(p_mod).exists():
                tab_ann.plate_model_var.set("Custom")
                tab_ann.plate_custom_var.set(p_mod)

            tab_ann.mode_var.set("C: Pojazdy + tablice")
            tab_ann._on_mode_change()

        try:
            self.app.update_status(
                f"Auto-ustawiono: IN={folder} | OUT={auto_out}. Kliknij START w Autoanotacji.",
                "info"
            )
        except Exception:
            pass

        self.app.notebook.select(1)

    def _step_goto_characters(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3:
            return  # ✅ ZMIANA: cicha blokada

        try:
            raw_dir = CAMPAIGN.get_dir("raw")          # projekt/1_raw_images
            auto_dir = CAMPAIGN.get_dir("auto_ann")    # projekt/2_auto_annotations
            chars_dir = CAMPAIGN.get_dir("chars")      # projekt/3_cropped_characters
            datasets_dir = CAMPAIGN.get_dir("datasets")# projekt/4_training_datasets

            if not raw_dir or not auto_dir:
                logger.error("Brak katalogów projektu (raw/auto_ann).")
                return

            iter_num = CAMPAIGN.get_current_iteration_num()
            images_folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"

            # ✅ ZMIANA: szukamy NAJNOWSZEGO annotations.xml tylko w obrębie projektu
            xml_candidates = list(Path(auto_dir).rglob("annotations.xml"))
            latest_xml = None
            if xml_candidates:
                latest_xml = max(xml_candidates, key=lambda p: p.stat().st_mtime)

            if latest_xml is None or not latest_xml.exists():
                messagebox.showerror(
                    "Brak XML",
                    "Nie znaleziono annotations.xml w katalogu projektu.\n\n"
                    "Upewnij się, że Krok 2 (Autoanotacja) zakończył się sukcesem."
                )
                return

            tab_char = self.app.tabs.get("characters")
            if tab_char:
                # ✅ ZMIANA: ustawiamy ścieżki wejściowe
                tab_char.images_dir_var.set(str(images_folder))
                tab_char.xml_path_var.set(str(latest_xml))

                # ✅ ZMIANA: override’y (żeby wycinanie i żniwa pisały do projektu)
                if chars_dir:
                    tab_char._campaign_chars_dir = str(chars_dir)
                if datasets_dir:
                    tab_char._campaign_datasets_dir = str(datasets_dir)

            # ✅ ZMIANA: “krzycząca” informacja (ale bez spamowania messagebox)
            try:
                self.app.update_status(
                    f"Ustawiono automatycznie dla Zakładki Znaków: XML={latest_xml.parent.name}/annotations.xml | IMG={images_folder.name}",
                    "info"
                )
            except Exception:
                pass

            self.app.notebook.select(2)

        except Exception as e:
            logger.error(f"Błąd nawigacji (Krok 3): {e}")

    def _step_goto_training(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 4:
            return
        self.app.notebook.select(3)

    def _advance_iteration(self):
        if messagebox.askyesno("Nowa Iteracja", "Zamknąć obecną iterację i rozpocząć nową?"):
            CAMPAIGN.advance_to_next_iteration()
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()