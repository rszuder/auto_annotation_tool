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
        # ---------------- HEADER ----------------
        header_f = ttk.Frame(self.frame, padding=15)
        header_f.pack(fill=tk.X)

        self.lbl_title = tk.Label(
            header_f,
            text="🚀 MENADŻER KAMPANII (PROJEKTY)",
            font=("Segoe UI", 16, "bold"),
            fg="#2c3e50"
        )
        self.lbl_title.pack(side=tk.LEFT)

        proj_frame = ttk.Frame(header_f)
        proj_frame.pack(side=tk.LEFT, padx=(20, 0))

        self.btn_add_proj = ttk.Button(proj_frame, text="Nowy Projekt", command=self._add_new_project)
        self.btn_add_proj.pack(side=tk.LEFT, padx=5)

        self.btn_open_proj = ttk.Button(proj_frame, text="Otwórz projekt", command=self._open_selected_project)
        self.btn_open_proj.pack(side=tk.LEFT, padx=5)

        self.btn_del_proj = ttk.Button(proj_frame, text="Usuń projekt", command=self._delete_project)
        self.btn_del_proj.pack(side=tk.LEFT, padx=5)

        self.btn_exit_project = ttk.Button(proj_frame, text="Wyjdź z projektu", command=self._exit_project_mode)
        self.btn_exit_project.pack(side=tk.LEFT, padx=5)

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

        # ✅ ZMIANA: banner informujący, że użytkownik pracuje w aktywnym projekcie
        self.lbl_campaign_banner = tk.Label(
            self.frame,
            text="",
            font=("Segoe UI", 10, "bold"),
            fg="#8a4b08",
            bg="#fff3cd",
            padx=10,
            pady=6,
            anchor="w",
            justify=tk.LEFT
        )
        self.lbl_campaign_banner.pack(fill=tk.X, padx=15, pady=(0, 8))

        ttk.Separator(self.frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15)

        # ---------------- MAIN 2-COLUMN GRID ----------------
        main_container = ttk.Frame(self.frame, padding=15)
        main_container.pack(fill=tk.BOTH, expand=True)

        # ✅ stabilny układ: 2 kolumny
        main_container.columnconfigure(0, weight=1, minsize=360)   # lewy panel
        main_container.columnconfigure(1, weight=2, minsize=700)   # prawy panel
        main_container.rowconfigure(0, weight=1)

        # LEFT PANEL
        left_panel = ttk.LabelFrame(
            main_container,
            text=" Wiedza Algorytmów (Aktywny Projekt) ",
            padding=15
        )
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        tk.Label(
            left_panel,
            text="Mózg projektu (aktualizuje się automatycznie po treningu).\n"
                 "Przycisk 'Zmień' to ręczna korekta.",
            justify=tk.LEFT,
            fg="gray"
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
        self.right_panel = ttk.LabelFrame(
            main_container,
            text=" Rozkład Jazdy (Cykl Active Learningu) ",
            padding=15
        )
        self.right_panel.grid(row=0, column=1, sticky="nsew")

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

    def _ask_project_from_list(self, title="Wybierz projekt", action_label="OK"):
        """
        ✅ ZMIANA: modalne okno wyboru projektu z listy.
        Zwraca nazwę projektu albo None.
        """
        projects = CAMPAIGN.get_all_projects()
        if not projects:
            messagebox.showinfo("Brak projektów", "Nie ma żadnych zapisanych projektów.")
            return None

        dialog = tk.Toplevel(self.frame)
        dialog.title(title)
        dialog.geometry("420x140")
        dialog.transient(self.frame)
        dialog.grab_set()
        dialog.resizable(False, False)

        ttk.Label(dialog, text="Wybierz projekt z listy:", font=("Segoe UI", 10, "bold")).pack(
            anchor=tk.W, padx=15, pady=(15, 5)
        )

        chosen_var = tk.StringVar(value=projects[0])

        combo = ttk.Combobox(dialog, textvariable=chosen_var, values=projects, state="readonly", width=40)
        combo.pack(fill=tk.X, padx=15, pady=(0, 15))

        result = {"value": None}

        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill=tk.X, padx=15, pady=(0, 15))

        def accept():
            result["value"] = chosen_var.get().strip()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        ttk.Button(btn_row, text=action_label, command=accept).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Anuluj", command=cancel).pack(side=tk.RIGHT, padx=(0, 8))

        dialog.wait_window()
        return result["value"]

    def _set_model(self, model_type, initial_dir: Path):
        p = filedialog.askopenfilename(
            initialdir=str(initial_dir),
            filetypes=[("YOLO Model", "*.pt")]
        )
        if p:
            CAMPAIGN.set_global_model(model_type, p)
            self._refresh_dashboard()

    # ======================================================
    # ROADMAP UI
    # ======================================================

    def _build_roadmap_step(self, parent, step_num, title, desc, btn_text, command):
        f = ttk.Frame(parent)
        f.pack(fill=tk.X, pady=10)

        text_f = ttk.Frame(f)
        text_f.pack(side=tk.LEFT, fill=tk.X, expand=True)

        lbl_title = tk.Label(text_f, text=title, font=("Segoe UI", 12, "bold"))
        lbl_title.pack(anchor=tk.W)

        lbl_desc = tk.Label(text_f, text=desc, fg="#7f8c8d", justify=tk.LEFT, wraplength=520)
        lbl_desc.pack(anchor=tk.W)

        btn = ttk.Button(f, text=btn_text, command=command, width=25)
        btn.pack(side=tk.RIGHT, padx=10)

        # ✅ ZMIANA: kontener na dodatkowe akcje naprawcze (domyślnie pusty)
        extra_actions_frame = ttk.Frame(parent)
        extra_actions_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        self.roadmap_ui_elements.append({
            "step_num": step_num,
            "original_title": title,
            "orig_btn_text": btn_text,
            "lbl_title": lbl_title,
            "lbl_desc": lbl_desc,
            "btn": btn,
            "extra_actions_frame": extra_actions_frame
        })

    def _rebuild_roadmap_ui(self):
        for widget in self.right_panel.winfo_children():
            widget.destroy()
        self.roadmap_ui_elements = []

        self._build_roadmap_step(
            self.right_panel, 1,
            "1. Ingestia Danych",
            "Wskaż folder z NOWĄ paczką zdjęć. Wizard skopiuje obrazy do katalogu bieżącej iteracji projektu.",
            "Wybierz i skopiuj zdjęcia",
            self._step_create_raw_folder
        )

        self._build_roadmap_step(
            self.right_panel, 2,
            "2. Detekcja kaskadowa (Autoanotacja)",
            "Ustawia automatycznie ścieżki IN/OUT i przenosi do Autoanotacji.",
            "Skocz: Autoanotacja",
            self._step_goto_auto_annotation
        )

        self._build_roadmap_step(
            self.right_panel, 3,
            "3. Wycinanie tablic + Złota paczka",
            "Ustawia XML + folder obrazów (z projektu) i przenosi do Zakładki Znaków.",
            "Skocz: Znaki",
            self._step_goto_characters
        )

        self._build_roadmap_step(
            self.right_panel, 4,
            "4. Trening i analiza",
            "Przenosi do Zakładki Trening. Krok odblokowuje się po utworzeniu datasetu YOLO.",
            "Skocz: Trening",
            self._step_goto_training
        )

        steps_frames = [f for f in self.right_panel.winfo_children() if isinstance(f, ttk.Frame)]
        if len(steps_frames) >= 4:
            HELP.bind_help(steps_frames[0], "camp_step1")
            HELP.bind_help(steps_frames[1], "camp_step2")
            HELP.bind_help(steps_frames[2], "camp_step3")
            HELP.bind_help(steps_frames[3], "camp_step4")

    def _render_step3_rework_actions(self, frame):
        """✅ ZMIANA: dodatkowe przyciski naprawcze dla Kroku 3."""
        for w in frame.winfo_children():
            w.destroy()

        ttk.Label(
            frame,
            text="Dostępne ścieżki naprawcze:",
            foreground="#d35400",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 4))

        btn_row = ttk.Frame(frame)
        btn_row.pack(anchor=tk.W)

        ttk.Button(
            btn_row,
            text="↩ Autoanotacja",
            command=self._step_goto_auto_annotation
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            btn_row,
            text="🔬 Popraw OCR",
            command=self._step_goto_characters
        ).pack(side=tk.LEFT)

    # ======================================================
    # DASHBOARD REFRESH
    # ======================================================

    def _refresh_dashboard(self):
        self._refresh_projects_list()

        active_proj = CAMPAIGN.get_active_project_name()
        has_project = bool(active_proj)

        # ======================================================
        # TRYB SWOBODNY / BRAK AKTYWNEGO PROJEKTU
        # ======================================================
        if not has_project:
            self.app.campaign_free_mode = True
            self.app.set_campaign_mode(False)

            self.lbl_iter.config(text="Iteracja: -")
            self.lbl_campaign_banner.config(
                text="TRYB SWOBODNY — brak aktywnego projektu. Wybierz projekt z listy i kliknij „Otwórz projekt” albo utwórz nowy.",
                fg="#5f6b77",
                bg="#ecf0f1"
            )

            # Lewy panel wygaszony
            for mt in ["vehicle", "plate", "char"]:
                getattr(self, f"lbl_model_{mt}").config(text="Zablokowane", fg="gray")
                getattr(self, f"btn_model_{mt}").config(state="disabled")

            # Przyciski nagłówka
            self.btn_open_proj.config(state="normal")
            self.btn_del_proj.config(state="disabled")
            self.btn_exit_project.config(state="disabled")

            # Awans nieaktywny
            self.btn_advance.config(text="Utwórz projekt ↗", state="disabled", style="TButton")

            # Prawy panel wygaszony
            for item in self.roadmap_ui_elements:
                item["lbl_title"].config(text=f"🔒 {item['original_title']}", fg="#bdc3c7")
                item["lbl_desc"].config(fg="#bdc3c7")
                item["btn"].config(text="Zablokowane", style="TButton", state="disabled")

                extra_frame = item.get("extra_actions_frame")
                if extra_frame:
                    for w in extra_frame.winfo_children():
                        w.destroy()

            self.app.update_campaign_tab_access()
            self.frame.update_idletasks()
            return

        # ======================================================
        # TRYB AKTYWNEGO PROJEKTU
        # ======================================================
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)

        curr_step = CAMPAIGN.get_current_step()
        step2_status = CAMPAIGN.get_step2_status()
        step3_status = CAMPAIGN.get_step3_status()
        iter_num = CAMPAIGN.get_current_iteration_num()

        self.lbl_iter.config(text=f"Iteracja: {iter_num}")
        self.lbl_campaign_banner.config(
            text=(
                f"AKTYWNY PROJEKT: {active_proj}  |  TRYB KAMPANII WŁĄCZONY\n"
                "Masz włączone sterowanie workflow. Aby wrócić do trybu swobodnego, kliknij „Wyjdź z projektu”."
            ),
            fg="#145a32",
            bg="#d5f5e3"
        )

        # Przyciski nagłówka
        self.btn_open_proj.config(state="normal")
        self.btn_del_proj.config(state="normal")
        self.btn_exit_project.config(state="normal")

        # Przyciski modeli
        for mt in ["vehicle", "plate", "char"]:
            getattr(self, f"btn_model_{mt}").config(state="normal")

        def fmt_model(p):
            return Path(p).name if p and Path(p).exists() else "Domyślny/Brak"

        self.lbl_model_vehicle.config(text=fmt_model(CAMPAIGN.get_global_model("vehicle")), fg="#2980b9")
        self.lbl_model_plate.config(text=fmt_model(CAMPAIGN.get_global_model("plate")), fg="#2980b9")
        self.lbl_model_char.config(text=fmt_model(CAMPAIGN.get_global_model("char")), fg="#2980b9")

        # Awans iteracji
        if curr_step >= 5:
            self.btn_advance.config(
                text="🎉 Cykl zakończony → Nowa Iteracja",
                state="normal",
                style="Accent.TButton"
            )
        else:
            self.btn_advance.config(
                text=f"Awans zablokowany (Krok {curr_step})",
                state="disabled",
                style="TButton"
            )

        # Folder kroku 1
        raw_dir = CAMPAIGN.get_dir("raw")
        step1_folder_exists = False
        if raw_dir:
            step1_folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
            step1_folder_exists = step1_folder.exists()

        # Kroki
        for item in self.roadmap_ui_elements:
            s = item["step_num"]
            title = item["original_title"]
            orig_btn_txt = item["orig_btn_text"]
            btn = item["btn"]
            extra_frame = item.get("extra_actions_frame")

            if extra_frame:
                for w in extra_frame.winfo_children():
                    w.destroy()

            if s < curr_step:
                item["lbl_title"].config(text=f"✅ {title}", fg="#27ae60")
                item["lbl_desc"].config(fg="#7f8c8d")
                btn.config(text="Wykonano (skocz)", style="TButton", state="normal")

            elif s == curr_step:
                item["lbl_title"].config(text=f"🔵 {title}", fg="#2980b9")

                if s == 2 and step2_status == "generated":
                    item["lbl_desc"].config(
                        text=(
                            "Autoanotacja została wykonana, ale etap NIE został jeszcze zatwierdzony.\n"
                            "Przejdź do Zakładki Autoanotacja, sprawdź wynik i kliknij „Zatwierdź etap autoanotacji”."
                        ),
                        fg="#d35400"
                    )

                elif s == 3 and step3_status == "needs_rework":
                    item["lbl_desc"].config(
                        text=(
                            "Nie udało się zbudować paczki YOLO z tablic perfect.\n"
                            "Wróć do Autoanotacji albo popraw OCR w Zakładce Znaków.\n"
                            "Trening pozostaje zablokowany do czasu powodzenia tego etapu."
                        ),
                        fg="#d35400"
                    )
                    self._render_step3_rework_actions(extra_frame)

                else:
                    item["lbl_desc"].config(fg="#2c3e50")

                if s == 1:
                    btn.config(
                        text="Zatwierdź pliki" if step1_folder_exists else "Wybierz i skopiuj zdjęcia",
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
        self.app.update_campaign_tab_access()
        self.frame.update_idletasks()

    def _update_main_tabs_highlight(self, curr_step, has_project):
        nb = self.app.notebook
        try:
            tabs_count = nb.index("end")
        except Exception:
            return

        for i in range(tabs_count):
            txt = nb.tab(i, "text")
            clean_txt = txt.replace("⭐ ", "").replace(" ⭐", "")
            nb.tab(i, text=clean_txt)

        if not has_project:
            return

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
        """
        ✅ ZMIANA: zachowana dla spójności API, ale główny combobox został usunięty z nagłówka.
        Wybór projektu odbywa się teraz przez popup.
        """
        return

    def _on_project_changed(self, event=None):
        """
        ✅ ZMIANA: pozostawione dla kompatybilności, ale nieużywane.
        """
        return

    def _open_selected_project(self):
        """Aktywuje projekt wybrany z listy i włącza tryb kampanii."""
        selected = self._ask_project_from_list(
            title="Otwórz projekt",
            action_label="Otwórz"
        )
        if not selected:
            return

        CAMPAIGN.set_active_project(selected)
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)
        self._rebuild_roadmap_ui()
        self._refresh_dashboard()
        self.app.update_campaign_tab_access()

        try:
            self.app.update_status(
                f"Aktywowano projekt: {selected}. Aplikacja działa w trybie kampanii.",
                "info"
            )
        except Exception:
            pass
        
    def _add_new_project(self):
        new_name = simpledialog.askstring("Nowy Projekt", "Podaj unikalną nazwę projektu:", parent=self.frame)
        if not new_name:
            return

        if CAMPAIGN.create_project(new_name):
            self.app.campaign_free_mode = False  # ✅ ZMIANA
            self.app.set_campaign_mode(True)
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()
            self.app.update_campaign_tab_access()
            messagebox.showinfo("Sukces", f"Projekt '{new_name}' utworzony.")
        else:
            messagebox.showerror("Błąd", "Projekt o takiej nazwie już istnieje lub nazwa jest nieprawidłowa.")

    def _delete_project(self):
        selected = self._ask_project_from_list(
            title="Usuń projekt",
            action_label="Usuń"
        )
        if not selected:
            return

        if messagebox.askyesno(
            "OSTRZEŻENIE",
            f"Usunąć projekt '{selected}' (cały katalog projektu)?"
        ):
            was_active = (CAMPAIGN.get_active_project_name() == selected)

            if CAMPAIGN.delete_project(selected):
                # jeśli skasowaliśmy aktywny projekt, przejdź do trybu swobodnego
                if was_active:
                    self.app.campaign_free_mode = True
                    self.app.set_campaign_mode(False)

                    try:
                        if "annotation" in self.app.tabs:
                            self.app.tabs["annotation"].clear_campaign_context()
                    except Exception:
                        pass

                    try:
                        if "characters" in self.app.tabs:
                            self.app.tabs["characters"].clear_campaign_context()
                    except Exception:
                        pass

                    try:
                        if "training" in self.app.tabs:
                            self.app.tabs["training"].clear_campaign_context()
                    except Exception:
                        pass

                self._rebuild_roadmap_ui()
                self._refresh_dashboard()
                self.app.update_campaign_tab_access()

                messagebox.showinfo("Usunięto", f"Projekt '{selected}' został usunięty.")

    def _exit_project_mode(self):
        active = CAMPAIGN.get_active_project_name()
        if not active:
            return

        if messagebox.askyesno(
            "Wyjdź z projektu",
            f"Czy na pewno chcesz opuścić projekt '{active}' i przejść do trybu swobodnego?\n\n"
            "Projekt nie zostanie usunięty."
        ):

            # ✅ użytkownik ręcznie wymusza tryb swobodny
            self.app.campaign_free_mode = True

            # czyścimy aktywny projekt
            CAMPAIGN.clear_active_project()

            # wyłączamy tryb kampanii
            self.app.set_campaign_mode(False)

            # ✅ ZMIANA: czyścimy projektowy kontekst innych zakładek
            try:
                if "annotation" in self.app.tabs:
                    self.app.tabs["annotation"].clear_campaign_context()
            except Exception as e:
                logger.debug(f"Nie udało się wyczyścić kontekstu Autoanotacji: {e}")

            try:
                if "characters" in self.app.tabs:
                    self.app.tabs["characters"].clear_campaign_context()
            except Exception as e:
                logger.debug(f"Nie udało się wyczyścić kontekstu Zakładki Znaków: {e}")

            try:
                if "training" in self.app.tabs:
                    self.app.tabs["training"].clear_campaign_context()
            except Exception as e:
                logger.debug(f"Nie udało się wyczyścić kontekstu Treningu: {e}")

            # odświeżamy dashboard
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()

            # finalna synchronizacja dostępności zakładek
            self.app.update_campaign_tab_access()

            try:
                self.app.update_status(
                    "Opuściłeś aktywny projekt. Aplikacja działa teraz w trybie swobodnym.",
                    "info"
                )
            except Exception:
                pass
    # ======================================================
    # STEPS
    # ======================================================

    def _step_create_raw_folder(self):
        if not CAMPAIGN.get_active_project_name():
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        if raw_dir is None:
            logger.error("Brak katalogu raw dla aktywnego projektu.")
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        target_iter_dir = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
        target_iter_dir.mkdir(parents=True, exist_ok=True)

        # ✅ ZMIANA: jeśli folder iteracji już ma zdjęcia, traktujemy to jako etap gotowy do zatwierdzenia
        existing_images = [f for f in target_iter_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
        if existing_images:
            CAMPAIGN.set_current_step(2)
            self._refresh_dashboard()
            try:
                self.app.update_status(
                    f"✅ Iteracja {iter_num:03d} zawiera już {len(existing_images)} obrazów. Krok 1 zatwierdzony.",
                    "info"
                )
            except Exception:
                pass
            return

        # ✅ ZMIANA: użytkownik wskazuje źródłowy folder, a wizard kopiuje zdjęcia do projektu
        source_dir = filedialog.askdirectory(
            initialdir=str(Path(CONFIG.DIR_1_RAW).absolute()),
            title="Wybierz folder źródłowy z NOWĄ paczką zdjęć do tej iteracji"
        )
        if not source_dir:
            return

        source_dir = Path(source_dir)
        if not source_dir.exists():
            return messagebox.showerror("Błąd", "Wskazany folder źródłowy nie istnieje.")

        import shutil

        image_files = [f for f in source_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
        if not image_files:
            return messagebox.showwarning(
                "Brak zdjęć",
                "W wybranym folderze nie znaleziono żadnych obrazów obsługiwanych przez aplikację."
            )

        copied = 0
        for img_file in image_files:
            dst = target_iter_dir / img_file.name
            if not dst.exists():
                shutil.copy2(img_file, dst)
                copied += 1

        if copied == 0:
            return messagebox.showwarning(
                "Brak nowych plików",
                "Żadne nowe zdjęcia nie zostały skopiowane.\n\n"
                "Być może ten zestaw został już wcześniej użyty w tej iteracji."
            )

        CAMPAIGN.set_current_step(2)
        self._refresh_dashboard()

        try:
            self.app.update_status(
                f"✅ Skopiowano {copied} nowych zdjęć do Iteracji {iter_num:03d}. Odblokowano Krok 2.",
                "info"
            )
        except Exception:
            pass

        messagebox.showinfo(
            "Ingestia zakończona",
            f"Skopiowano {copied} zdjęć do:\n{target_iter_dir}\n\n"
            f"Każda iteracja pracuje tylko na swojej NOWEJ paczce wejściowej."
        )

    def _step_goto_auto_annotation(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 2:
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_out = CAMPAIGN.get_staging_dir("auto_ann")  # ✅ ZMIANA: autoanotacja idzie najpierw do stagingu
        if auto_out is not None:
            Path(auto_out).mkdir(parents=True, exist_ok=True)

        if raw_dir is None or auto_out is None:
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"

        tab_ann = self.app.tabs.get("annotation")
        if tab_ann:
            if folder.exists():
                tab_ann.input_dir_var.set(str(folder))

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
                f"Auto-ustawiono: IN={folder.name} | OUT={Path(auto_out).name}. Kliknij START.",
                "info"
            )
        except Exception:
            pass

        self.app.notebook.select(1)

    def _step_goto_characters(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3:
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_dir = CAMPAIGN.get_dir("auto_ann")
        chars_dir = CAMPAIGN.get_dir("chars")
        datasets_dir = CAMPAIGN.get_dir("datasets")

        if raw_dir is None or auto_dir is None:
            return

        # ✅ ZMIANA: najnowszy XML tylko z katalogu zatwierdzonych autoanotacji projektu
        xml_files = list(Path(auto_dir).rglob("annotations.xml"))
        latest_xml = str(max(xml_files, key=lambda p: p.stat().st_mtime)) if xml_files else ""

        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"

        tab_char = self.app.tabs.get("characters")
        if tab_char:
            # ======================================================
            # ✅ ZMIANA: twardy reset poprzedniego kontekstu Zakładki Znaków
            # ======================================================
            tab_char.preview_dir_var.set("")
            tab_char.preview_metadata = {}
            tab_char.preview_plate_ids = []
            tab_char._loaded_meta_path = None
            tab_char._loaded_meta_mtime = None

            # wyczyść listę i canvas, jeśli istnieją
            try:
                tab_char.plates_listbox.delete(0, tk.END)
            except Exception:
                pass

            try:
                tab_char.preview_canvas.delete("all")
            except Exception:
                pass

            try:
                tab_char.preview_info_lbl.config(text="Oczekuję na nową paczkę...", foreground="#2980b9")
            except Exception:
                pass

            # ======================================================
            # ✅ ZMIANA: ustaw świeże źródła z najnowszej próby
            # ======================================================
            if folder.exists():
                tab_char.images_dir_var.set(str(folder))
            if latest_xml:
                tab_char.xml_path_var.set(latest_xml)

            # projektowe katalogi wyjściowe
            tab_char._campaign_chars_dir = str(chars_dir) if chars_dir else None
            tab_char._campaign_datasets_dir = str(datasets_dir) if datasets_dir else None

            c_mod = CAMPAIGN.get_global_model("char")
            if c_mod and Path(c_mod).exists():
                tab_char.detection_method_var.set("YOLO")
                tab_char.yolo_model_path_var.set(c_mod)

        try:
            if latest_xml:
                self.app.update_status(
                    f"Ustawiono świeże źródła dla Zakładki Znaków: XML={Path(latest_xml).parent.name}/annotations.xml | IMG={folder.name}.",
                    "info"
                )
            else:
                self.app.update_status(
                    "Nie znaleziono nowego pliku annotations.xml. Upewnij się, że Autoanotacja zakończyła się sukcesem i etap został zatwierdzony.",
                    "warning"
                )
        except Exception:
            pass

        self.app.notebook.select(2)

    def _step_goto_training(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 4:
            return

        try:
            datasets_dir = CAMPAIGN.get_dir("datasets")
            runs_dir = CAMPAIGN.get_dir("runs")

            if datasets_dir is None:
                logger.error("Brak katalogu datasets dla aktywnego projektu.")
                return

            tab_train = self.app.tabs.get("training")
            if not tab_train:
                logger.error("Nie znaleziono zakładki TrainingTab w app.tabs.")
                return

            # ✅ pełne przełączenie TrainingTab na kontekst projektu
            tab_train.set_campaign_context(
                runs_dir=str(runs_dir) if runs_dir is not None else None,
                datasets_dir=str(datasets_dir)
            )

            datasets_dir = Path(datasets_dir)

            source_candidates = [
                p for p in datasets_dir.iterdir()
                if p.is_dir()
                and "_Split_" not in p.name
                and (p / "images").exists()
            ]

            latest_source = None
            if source_candidates:
                latest_source = max(source_candidates, key=lambda p: p.stat().st_mtime)

            if latest_source is not None:
                tab_train.split_src_var.set(str(latest_source))
                tab_train.split_out_var.set(
                    str(datasets_dir / f"{latest_source.name}_Split_[DATA_I_CZAS]")
                )
            else:
                tab_train.split_src_var.set("")
                tab_train.split_out_var.set(str(datasets_dir / "[BRAK_DATASETU_ZRODLOWEGO]"))

            char_model = CAMPAIGN.get_global_model("char")
            if char_model and Path(char_model).exists():
                tab_train.base_model_var.set("Custom")
                tab_train.base_custom_var.set(char_model)
            else:
                tab_train.base_model_var.set("yolo11n")
                tab_train.base_custom_var.set("")

            tab_train._on_base_model_change()

            try:
                tab_train.imgsz_var.set(256)
            except Exception:
                pass

            try:
                if latest_source is not None:
                    self.app.update_status(
                        f"Ustawiono automatycznie Trening: źródło splittera = {latest_source.name}, wynik splitu w katalogu projektu oraz model DETECT dla znaków.",
                        "info"
                    )
                else:
                    self.app.update_status(
                        "Przełączono do Treningu w kontekście projektu, ale nie znaleziono jeszcze datasetu źródłowego w 4_training_datasets.",
                        "warning"
                    )
            except Exception:
                pass

            self.app.notebook.select(3)

        except Exception as e:
            logger.error(f"Błąd nawigacji (Krok 4): {e}")

    def _advance_iteration(self):
        if messagebox.askyesno("Nowa Iteracja", "Zamknąć obecną iterację i rozpocząć nową?"):
            CAMPAIGN.advance_to_next_iteration()
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()