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

class CampaignTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        self.frame = ttk.Frame(parent)
        
        # ✅ ZMIANA: Inicjalizacja listy PRZED budową UI
        self.roadmap_ui_elements = [] 
        
        self._build_ui()
        self._refresh_dashboard()
        self.roadmap_ui_elements = [] # Będzie przechowywać referencje do kroków

    def _build_ui(self):
        # Nagłówek - Menedżer Projektów
        header_f = ttk.Frame(self.frame, padding=15)
        header_f.pack(fill=tk.X)
        
        self.lbl_title = tk.Label(header_f, text=f"{self.icon_manager.get('trophy')} MENADŻER KAMPANII:", font=("Segoe UI", 16, "bold"), fg="#2c3e50")
        self.lbl_title.pack(side=tk.LEFT)
        
        # ✅ ZMIANA: Combobox projektów i przyciski zarządzania (CRUD)
        proj_frame = ttk.Frame(header_f)
        proj_frame.pack(side=tk.LEFT, padx=(10, 0))
        
        self.proj_combo_var = tk.StringVar()
        self.proj_combo = ttk.Combobox(proj_frame, textvariable=self.proj_combo_var, state="readonly", width=25)
        self.proj_combo.pack(side=tk.LEFT, padx=5)
        self.proj_combo.bind("<<ComboboxSelected>>", self._on_project_changed)
        
        # ✅ ZMIANA: Usunięcie sztywnej szerokości i emojis, by przyciski wyglądały naturalnie
        btn_add_proj = ttk.Button(proj_frame, text="Nowy Projekt", command=self._add_new_project)
        btn_add_proj.pack(side=tk.LEFT, padx=5)
        
        self.btn_del_proj = ttk.Button(proj_frame, text="Usuń", command=self._delete_project)
        self.btn_del_proj.pack(side=tk.LEFT, padx=5)
        
        self.lbl_iter = tk.Label(header_f, text="Iteracja: 1", font=("Segoe UI", 14, "bold"), fg="#e74c3c", bg="#fadbd8", padx=10, pady=5)
        self.lbl_iter.pack(side=tk.RIGHT)

        ttk.Separator(self.frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15)

        main_container = ttk.Frame(self.frame, padding=15)
        main_container.pack(fill=tk.BOTH, expand=True)

        # LEWY PANEL - Modele (Knowledge Base)
        left_panel = ttk.LabelFrame(main_container, text=" Wiedza Algorytmów (Dla Aktywnego Projektu) ", padding=15)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        tk.Label(left_panel, text="Mózg Projektu (Aktualizuje się automatycznie!).\nSystem sam podmieni te modele po każdym udanym treningu.", justify=tk.LEFT, fg="gray").pack(anchor=tk.W, pady=(0, 15))

        self._build_model_status(left_panel, "Model Pojazdów (Detect):", "vehicle", CONFIG.DIR_6_MODELS_BASE)
        self._build_model_status(left_panel, "Model Tablic (Pose):", "plate", CONFIG.DIR_6_MODELS_PLATES)
        self._build_model_status(left_panel, "Model Znaków (OCR/YOLO):", "char", CONFIG.DIR_6_MODELS_CHARS)

        self.btn_advance = ttk.Button(left_panel, text="Awansuj do Nowej Iteracji", command=self._advance_iteration, style="Accent.TButton")
        self.btn_advance.pack(side=tk.BOTTOM, fill=tk.X, pady=10)

        # PRAWY PANEL - Rozkład Jazdy (The Flywheel)
        self.right_panel = ttk.LabelFrame(main_container, text=" Rozkład Jazdy (Cykl Active Learningu) ", padding=15)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        # Generujemy kroki po raz pierwszy
        self._rebuild_roadmap_ui()


        # ========================================================
        # ✅ ZMIANA: Podpięcie systemu pomocy (Hover Help)
        # ========================================================
        from .help_manager import HELP
        
        # Aby podpiąć przyciski "Rozkładu Jazdy", pobieramy je dynamicznie z right_panel
        # Struktura _build_roadmap_step to: Frame -> [Frame(z tekstem), Button, Separator]
        steps_frames = [f for f in self.right_panel.winfo_children() if isinstance(f, ttk.Frame)]
        
        if len(steps_frames) >= 4:
            HELP.bind_help(steps_frames[0], "camp_step1")
            HELP.bind_help(steps_frames[1], "camp_step2")
            HELP.bind_help(steps_frames[2], "camp_step3")
            HELP.bind_help(steps_frames[3], "camp_step4")
            
        # Podpinamy lewy panel (Wiedza Algorytmów)
        HELP.bind_help(left_panel, "camp_models")
        
        # Podpinamy przycisk "Awansuj do Nowej Iteracji"
        # Znajduje się on na końcu left_panel
        for child in left_panel.winfo_children():
            if isinstance(child, ttk.Button):
                HELP.bind_help(child, "camp_advance")

    def _build_model_status(self, parent, title, model_type, default_dir):
        f = ttk.Frame(parent)
        f.pack(fill=tk.X, pady=10)
        tk.Label(f, text=title, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        
        row = ttk.Frame(f)
        row.pack(fill=tk.X)
        lbl_val = tk.Label(row, text="Domyślny/Brak", fg="#2980b9", font=("Consolas", 10))
        lbl_val.pack(side=tk.LEFT, expand=True, anchor=tk.W)
        
        # TUTAJ TWORZYMY btn:
        btn = ttk.Button(row, text="Zmień", command=lambda: self._set_model(model_type, default_dir))
        btn.pack(side=tk.RIGHT)
        
        setattr(self, f"lbl_model_{model_type}", lbl_val)
        setattr(self, f"btn_model_{model_type}", btn)

    def _set_model(self, model_type, default_dir):
        p = filedialog.askopenfilename(initialdir=str(Path(default_dir).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p:
            CAMPAIGN.set_global_model(model_type, p)
            self._refresh_dashboard()

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
            "orig_btn_text": btn_text, # ✅ ZMIANA: Zapisujemy oryginalny tekst przycisku
            "lbl_title": lbl_title,
            "lbl_desc": lbl_desc,      # ✅ ZMIANA: Pamiętamy też opis do wyszarzania
            "btn": btn
        })

    def _rebuild_roadmap_ui(self):
        """Utylizuje stary prawy panel i rysuje go CAŁKOWICIE od nowa"""
        # Niszczymy wszystko wewnątrz prawego panelu
        for widget in self.right_panel.winfo_children():
            widget.destroy()
            
        self.roadmap_ui_elements = [] # Czyścimy starą pamięć odniesień
        
        # Odbudowujemy 4 klocki za pomocą istniejącej funkcji!
        self._build_roadmap_step(self.right_panel, 1, "1. Ingestia Danych", "Utwórz folder na nowe...", "Utwórz i otwórz folder", self._step_create_raw_folder)
        self._build_roadmap_step(self.right_panel, 2, "2. Detekcja Kaskadowa", "Wykryj pojazdy i...", "Skocz: Autoanotacja", self._step_goto_auto_annotation)
        self._build_roadmap_step(self.right_panel, 3, "3. Złota Paczka i CVAT", "Wytnij tablice, przetestuj...", "Skocz: Analiza Znaków", self._step_goto_characters)
        self._build_roadmap_step(self.right_panel, 4, "4. Mega-Dataset i Trening", "Zbuduj zbiór z odzyskanych...", "Skocz: Trening", self._step_goto_training)

        # Ponowne podpięcie systemu pomocy pod świeżo urodzone klocki
        from .help_manager import HELP
        steps_frames = [f for f in self.right_panel.winfo_children() if isinstance(f, ttk.Frame)]
        if len(steps_frames) >= 4:
            HELP.bind_help(steps_frames[0], "camp_step1")
            HELP.bind_help(steps_frames[1], "camp_step2")
            HELP.bind_help(steps_frames[2], "camp_step3")
            HELP.bind_help(steps_frames[3], "camp_step4")

    def _step_create_raw_folder(self):
        if not CAMPAIGN.get_active_project_name(): return
        
        proj_folder = CAMPAIGN.get_safe_project_folder_name()
        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(CONFIG.DIR_1_RAW) / str(proj_folder) / f"Iteracja_{iter_num:03d}"
        
        if not folder.exists():
            # Pierwsze kliknięcie - Tworzenie
            folder.mkdir(parents=True, exist_ok=True)
            messagebox.showinfo("Folder Utworzony", f"Katalog przygotowany:\n{folder}\n\nSkopiuj do niego zdjęcia, a następnie kliknij 'Zatwierdź'.")
            try: os.startfile(folder)
            except: pass
            self._refresh_dashboard()
        else:
            # Kolejne kliknięcie - Weryfikacja (Zatwierdzanie)
            images = [f for f in folder.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
            if len(images) > 0:
                CAMPAIGN.set_current_step(2)
                self._refresh_dashboard()
            else:
                messagebox.showwarning("Brak plików", "Folder jest wciąż pusty. Dodaj zdjęcia aby zatwierdzić ten etap.")
                try: os.startfile(folder)
                except: pass

    def _refresh_dashboard(self):
        try:
            self._refresh_projects_list()
            
            # Bezpieczne pobranie nazwy aktywnego projektu
            active_proj = CAMPAIGN.get_active_project_name()
            # Sprawdzamy czy projekt jest faktycznie na liscie w słowniku, a nie jest "duchem"
            all_projs = CAMPAIGN.get_all_projects()
            
            has_project = bool(active_proj) and (active_proj in all_projs)
            
            # ==========================================
            # TRYB BLOKADY (Brak projektu lub projekt usunięty)
            # ==========================================
            if not has_project:
                self.lbl_iter.config(text="Iteracja: -")
                self.proj_combo_var.set("Brak projektów. Kliknij [+] Nowy")
                
                # Lewy panel
                for mt in ["vehicle", "plate", "char"]:
                    getattr(self, f"lbl_model_{mt}").config(text="Zablokowane", fg="gray")
                    getattr(self, f"btn_model_{mt}").config(state="disabled")
                    
                self.btn_del_proj.config(state="disabled")
                self.btn_advance.config(text="Utwórz nowy projekt ↗", state="disabled", style="TButton")
                
                # Prawy panel (Wymuszenie czyszczenia i blokady)
                for item in self.roadmap_ui_elements:
                    item["lbl_title"].config(text=f"🔒 {item['original_title']}", fg="#bdc3c7")
                    item["lbl_desc"].config(fg="#bdc3c7")
                    # Twarde czyszczenie stylów z poprzedniej sesji!
                    btn = item["btn"]
                    btn.config(text="Zablokowane", style="TButton", state="disabled")
                    
                self._update_main_tabs_highlight(1, False)
                
                # Twarde wymuszenie odświeżenia widoku w Tkinter!
                self.frame.update_idletasks()
                return 

            # ==========================================
            # TRYB AKTYWNY (Projekt istnieje i jest poprawny)
            # ==========================================
            self.btn_del_proj.config(state="normal")
            
            curr_step = CAMPAIGN.get_current_step()

            if curr_step >= 5:
                self.btn_advance.config(text="🎉 Cykl zakończony. Rozpocznij Nową Iterację!", style="Accent.TButton", state="normal")
            else:
                self.btn_advance.config(text=f"Awans (Zablokowane - Ukończ Krok {curr_step})", style="TButton", state="disabled")
                
            for mt in ["vehicle", "plate", "char"]:
                getattr(self, f"btn_model_{mt}").config(state="normal")
                
            iter_num = CAMPAIGN.get_current_iteration_num()
            self.lbl_iter.config(text=f"Iteracja ALPR: {iter_num}")
            
            def fmt_model(path_str):
                if not path_str or not Path(path_str).exists(): return "Domyślny/Brak"
                return Path(path_str).name
                
            self.lbl_model_vehicle.config(text=fmt_model(CAMPAIGN.get_global_model("vehicle")), fg="#2980b9")
            self.lbl_model_plate.config(text=fmt_model(CAMPAIGN.get_global_model("plate")), fg="#2980b9")
            self.lbl_model_char.config(text=fmt_model(CAMPAIGN.get_global_model("char")), fg="#2980b9")

            # Bezpieczna analiza istnienia folderu pierwszego kroku
            proj_folder = CAMPAIGN.get_safe_project_folder_name()
            # Zabezpieczenie przed błędem jeśli 'proj_folder' to 'None' lub 'UNNAMED_PROJECT'
            if not proj_folder or proj_folder == "UNNAMED_PROJECT":
                step1_folder_exists = False
            else:
                step1_folder = Path(CONFIG.DIR_1_RAW) / str(proj_folder) / f"Iteracja_{iter_num:03d}"
                step1_folder_exists = step1_folder.exists()
            
            for item in self.roadmap_ui_elements:
                s = item["step_num"]
                title = item["original_title"]
                orig_btn_txt = item["orig_btn_text"]
                btn = item["btn"]
                
                if s < curr_step:
                    # Ukończony
                    item["lbl_title"].config(text=f"✅ {title}", fg="#27ae60")
                    item["lbl_desc"].config(fg="#7f8c8d")
                    btn.config(text="Wykonano (Skocz ponownie)", style="TButton", state="normal")
                    
                elif s == curr_step:
                    # Aktywny
                    item["lbl_title"].config(text=f"🔵 {title}", fg="#2980b9")
                    item["lbl_desc"].config(fg="#2c3e50")
                    
                    if s == 1:
                        if step1_folder_exists:
                            btn.config(text="Zatwierdź pliki", style="Accent.TButton", state="normal")
                        else:
                            btn.config(text="Utwórz folder", style="Accent.TButton", state="normal")
                    else:
                        btn.config(text=orig_btn_txt, style="Accent.TButton", state="normal")
                        
                else:
                    # Zablokowany w przyszłości
                    item["lbl_title"].config(text=f"⚪ {title}", fg="#bdc3c7")
                    item["lbl_desc"].config(fg="#bdc3c7")
                    btn.config(text=orig_btn_txt, style="TButton", state="disabled")

            self._update_main_tabs_highlight(curr_step, has_project)
            self.frame.update_idletasks() # Odśwież po pracy w trybie aktywnym
            
        except Exception as e:
            # TEN LOG ZDRADZI NAM, DLACZEGO PRAWY PANEL UMIERAŁ W POŁOWIE
            logger.error(f"KRYTYCZNY BŁĄD w _refresh_dashboard: {e}")

    def _update_main_tabs_highlight(self, curr_step, has_project):
        """Dynamicznie podświetla górne zakładki programu w zależności od kroku."""
        nb = self.app.notebook
        try:
            tabs_count = nb.index("end")
        except:
            return 
            
        # 1. Czyszczenie starych wskaźników (zdejmujemy strzałki ze wszystkich)
        for i in range(tabs_count):
            txt = nb.tab(i, "text")
            clean_txt = txt.replace("⭐ ", "").replace(" ⭐", "")
            nb.tab(i, text=clean_txt)

        if not has_project:
            return

        # =========================================================
        # ✅ ZMIANA: Precyzyjne uderzenie w indeksy zakładek (0-3)
        # =========================================================
        # Indeksy w notebooku:
        # 0: Rozkład Jazdy (Krok 1)
        # 1: Autoanotacja (Krok 2)
        # 2: Znaki na tablicach (Krok 3)
        # 3: Trening i Analiza (Krok 4)
        
        target_idx = 0  # Domyślnie Krok 1 (Rozkład Jazdy)
        
        if curr_step == 2:
            target_idx = 1
        elif curr_step == 3:
            target_idx = 2
        elif curr_step >= 4:
            target_idx = 3
            
        # 4. Nałożenie gwiazdek/wskaźników na DOCELOWĄ zakładkę
        if target_idx < tabs_count:
            txt = nb.tab(target_idx, "text")
            nb.tab(target_idx, text=f"⭐ {txt} ⭐")

    def _advance_iteration(self):
        if messagebox.askyesno("Nowa Iteracja", "Czy na pewno chcesz zamknąć obecny cykl i rozpocząć nową iterację?"):
            CAMPAIGN.advance_to_next_iteration()
            self._refresh_dashboard()

    # ======================================================
    # LOGIKA ZARZĄDZANIA PROJEKTAMI
    # ======================================================
    
    def _refresh_projects_list(self):
        """Odświeża listę projektów w Comboboxie."""
        projects = CAMPAIGN.get_all_projects()
        self.proj_combo['values'] = projects
        active = CAMPAIGN.get_active_project_name()
        if active in projects:
            self.proj_combo_var.set(active)

    def _on_project_changed(self, event=None):
        selected = self.proj_combo_var.get()
        if selected:
            CAMPAIGN.set_active_project(selected)
            self._rebuild_roadmap_ui() # ✅ ZMIANA (Kasuje bugi)
            self._refresh_dashboard()

    def _add_new_project(self):
        new_name = simpledialog.askstring("Nowy Projekt", "Podaj unikalną nazwę dla nowego projektu:", parent=self.frame)
        if not new_name: return
        success = CAMPAIGN.create_project(new_name)
        if success:
            self._refresh_projects_list()
            self._rebuild_roadmap_ui() # ✅ ZMIANA (Kasuje bugi)
            self._refresh_dashboard()
            messagebox.showinfo("Sukces", f"Projekt '{new_name}' został utworzony i aktywowany.")
        else:
            messagebox.showerror("Błąd", "Projekt o takiej nazwie już istnieje lub nazwa jest nieprawidłowa!")

    def _delete_project(self):
        active = CAMPAIGN.get_active_project_name()
        if not active: return
        if messagebox.askyesno("OSTRZEŻENIE", f"Czy na pewno chcesz bezpowrotnie usunąć projekt '{active}'?"):
            success = CAMPAIGN.delete_project(active)
            if success:
                self.proj_combo_var.set("")
                self.proj_combo.set("")
                self._refresh_projects_list()
                if not CAMPAIGN.get_all_projects():
                    self.proj_combo_var.set("Wybierz lub utwórz projekt")
                    
                self._rebuild_roadmap_ui() # ✅ ZMIANA (Kasuje bugi)
                self._refresh_dashboard()
                self.frame.update_idletasks()
                messagebox.showinfo("Usunięto", "Projekt oraz jego folder wejściowy zostały usunięte.")

    def _step_create_raw_folder(self):
        if not CAMPAIGN.get_active_project_name(): return
        
        proj_folder = CAMPAIGN.get_safe_project_folder_name()
        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(CONFIG.DIR_1_RAW) / str(proj_folder) / f"Iteracja_{iter_num:03d}"
        
        if not folder.exists():
            # Pierwsze kliknięcie - Tworzenie
            folder.mkdir(parents=True, exist_ok=True)
            messagebox.showinfo("Folder Utworzony", f"Katalog przygotowany:\n{folder}\n\nSkopiuj do niego zdjęcia, a następnie kliknij 'Zatwierdź'.")
            try: os.startfile(folder)
            except: pass
            self._refresh_dashboard()
        else:
            # Kolejne kliknięcie - Weryfikacja (Zatwierdzanie)
            images = [f for f in folder.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
            if len(images) > 0:
                CAMPAIGN.set_current_step(2)
                self._refresh_dashboard()
            else:
                messagebox.showwarning("Brak plików", "Folder jest wciąż pusty. Dodaj zdjęcia aby zatwierdzić ten etap.")
                try: os.startfile(folder)
                except: pass

    def _step_goto_auto_annotation(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 2: return # Cicha blokada
        try:
            proj_folder = CAMPAIGN.get_safe_project_folder_name()
            iter_num = CAMPAIGN.get_current_iteration_num()
            folder = Path(CONFIG.DIR_1_RAW) / str(proj_folder) / f"Iteracja_{iter_num:03d}"
            
            tab_ann = self.app.tabs.get('annotation')
            if tab_ann:
                if folder.exists(): tab_ann.input_dir_var.set(str(folder))
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
            self.app.notebook.select(1)
        except Exception as e: logger.error(f"Błąd nawigacji: {e}")


    def _step_goto_characters(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3: return # Cicha blokada
        try:
            auto_ann_dir = Path(CONFIG.DIR_2_AUTO_ANN)
            runs = sorted(list(auto_ann_dir.glob("run_*")), reverse=True)
            latest_xml = ""
            if runs:
                xml_cand = runs[0] / "annotations.xml"
                if xml_cand.exists(): latest_xml = str(xml_cand)

            proj_folder = CAMPAIGN.get_safe_project_folder_name()
            iter_num = CAMPAIGN.get_current_iteration_num()
            folder = Path(CONFIG.DIR_1_RAW) / str(proj_folder) / f"Iteracja_{iter_num:03d}"
            
            tab_char = self.app.tabs.get('characters')
            if tab_char:
                if folder.exists(): tab_char.images_dir_var.set(str(folder))
                if latest_xml: tab_char.xml_path_var.set(latest_xml)
                c_mod = CAMPAIGN.get_global_model("char")
                if c_mod and Path(c_mod).exists():
                    tab_char.detection_method_var.set("YOLO")
                    tab_char.yolo_model_path_var.set(c_mod)
            self.app.notebook.select(2)
        except Exception as e: logger.error(f"Błąd nawigacji: {e}")

    def _step_goto_training(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 4: return # Cicha blokada
        self.app.notebook.select(3)

    def _step_goto_training(self):
        if not CAMPAIGN.get_active_project_name(): return
        
        # ✅ ŻETON: Użytkownik nie może trenować, dopóki nie zbuduje Złotej Paczki YOLO
        if CAMPAIGN.get_current_step() < 4:
            messagebox.showwarning("Kolejność", "Najpierw musisz ukończyć Krok 3 (wyłuskać Złote Tablice do formatu YOLO w Zakładce 2)!")
            return
            
        self.app.notebook.select(3)