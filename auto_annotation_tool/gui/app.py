#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Główna aplikacja GUI.
"""
print("DEBUG_LOADED_APP_PY:", __file__)

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from ..config import CONFIG, logger, TK_AVAILABLE
from ..icons import IconManager

# Importy zakładek
from .tab_annotation import AnnotationTab
from .tab_character_annotation import CharacterAnnotationTab
from .tab_training import TrainingTab
from .tab_campaign import CampaignTab
from .help_manager import HELP

try:
    from .tab_help import HelpTab
except ImportError:
    HelpTab = None


class AutoAnnotationApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{CONFIG.APP_NAME} v{CONFIG.VERSION}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        self.icon_manager = IconManager
        self.icon_manager.test_emoji_support(root)
        
        self.style = ttk.Style()
        self._setup_style()
        self.is_processing = False
        # ✅ ZMIANA: lokalna flaga aktywnego trybu kampanii
        self.campaign_mode_active = False
        self.campaign_free_mode = False  # ✅ ZMIANA: ręczne wyjście z projektu ma pierwszeństwo nad automatycznym trybem kampanii
    
        self._create_menu()
        
        # ✅ ZMIANA 1: Tworzenie Panelu Pomocy NA SAMYM DOLE (Musi być przed Notebookiem, żeby tk.BOTTOM zadziałało poprawnie)
        self.info_panel_frame = tk.Frame(root, bg="#f1f5f9", bd=1, relief=tk.SUNKEN)
        self.info_panel_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_text = tk.Text(
            self.info_panel_frame, height=2, wrap=tk.WORD, 
            bg="#f1f5f9", bd=0, font=("Segoe UI", 10, "italic"), fg="#2c3e50"
        )
        self.status_text.pack(fill=tk.X, padx=10, pady=6)
        self.status_text.insert(tk.END, f"{self.icon_manager.get('info')} Gotowy. Najedź myszką na element interfejsu, aby zobaczyć wskazówki.")
        self.status_text.config(state=tk.DISABLED)
        
        # Podpinamy globalny menedżer pomocy
        HELP.status_updater = lambda msg: self.update_status(msg, "info")
        
        # 2. Tworzenie Notatnika z zakładkami
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
        
        self.tabs = {}
        self._create_tabs()

        # główna blokada działa przez disabled tabs
        self.notebook.bind("<<NotebookTabChanged>>", self._guard_campaign_navigation)

        # początkowa synchronizacja stanów zakładek
        self.update_campaign_tab_access()

        # ✅ ZMIANA: jeśli aplikacja wstaje z aktywnym projektem, pokaż to w głównym pasku statusu
        try:
            from ..campaign_manager import CAMPAIGN
            active_proj = CAMPAIGN.get_active_project_name()
            if active_proj:
                self.update_status(
                    f"Aktywny projekt: {active_proj}. Aplikacja działa w trybie kampanii — aby wrócić do trybu swobodnego, użyj „Wyjdź z projektu” w Wizardzie.",
                    "warning"
                )
        except Exception:
            pass

        logger.info("GUI zainicjalizowane pomyślnie")
    
    def _setup_style(self):
        try:
            self.style.theme_use('clam')
            self.style.configure('TNotebook.Tab', padding=[15, 8], font=('Segoe UI', 10, 'bold'))
            self.style.configure('TButton', padding=6)
            self.style.configure('TLabel', padding=2)
        except: pass
    
    def _create_tabs(self):
        try:
            # ✅ ZMIANA: Menadżer Kampanii jako pierwsza zakładka (Index 0)
            try:
                self.tabs['campaign'] = CampaignTab(self.notebook, self)
                self.notebook.add(self.tabs['campaign'].frame, text=f"{self.icon_manager.get('trophy')} Rozkład Jazdy")

            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki Kampanii: {e}")

            self.tabs['annotation'] = AnnotationTab(self.notebook, self)
            self.notebook.add(self.tabs['annotation'].frame, text=f"{self.icon_manager.get('car')} Autoanotacja")
            
            try:
                self.tabs['characters'] = CharacterAnnotationTab(self.notebook, self)
                self.notebook.add(self.tabs['characters'].frame, text=f"{self.icon_manager.get('cut')} Znaki na tablicach")
            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki ZNAKI: {e}")
            
            try:
                self.tabs['training'] = TrainingTab(self.notebook, self)
                self.notebook.add(self.tabs['training'].frame, text=f"{self.icon_manager.get('training')} Trening i Analiza")
            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki TRENING: {e}")

            if HelpTab:
                self.tabs['help'] = HelpTab(self.notebook, self)
                self.notebook.add(self.tabs['help'].frame, text=f"📖 Instrukcja & Architektura")

            self.notebook.select(0)
            logger.warning(f"AUDYT _create_tabs: utworzone klucze tabs = {list(self.tabs.keys())}")
        except Exception as e:
            logger.error(f"Krytyczny błąd budowania zakładek GUI: {e}")
    
    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Plik", menu=file_menu)
        file_menu.add_command(label=f"{self.icon_manager.get('stop')} Wyjście", command=self._on_closing)
    
    def update_status(self, message: str, icon: str = "info"):
        """Aktualizuje główny panel wskazówek (zapobiega migotaniu)."""
        new_text = f"{self.icon_manager.get(icon)} {message}"
        try:
            current_text = self.status_text.get(1.0, tk.END).strip()
            if current_text != new_text.strip():
                self.status_text.config(state=tk.NORMAL)
                self.status_text.delete(1.0, tk.END)
                self.status_text.insert(tk.END, new_text)
                self.status_text.config(state=tk.DISABLED)
                self.root.update_idletasks()
        except Exception: pass
    
    def set_processing(self, processing: bool):
        self.is_processing = processing
        self.root.config(cursor="wait" if processing else "")
        self.root.update()

    def set_campaign_mode(self, active: bool):
        """
        Przełącza tryb kampanii.
        Uwaga: jeśli użytkownik ręcznie wszedł w tryb swobodny, nie nadpisujemy tego automatem.
        """
        self.campaign_mode_active = bool(active)
        self.update_campaign_tab_access()

    def _get_selected_tab_key(self):
        try:
            selected_widget = str(self.notebook.select())
        except Exception:
            return None

        for key, tab in self.tabs.items():
            try:
                if str(tab.frame) == selected_widget:
                    return key
            except Exception:
                pass

        return None


    def update_campaign_tab_access(self):
        """
        Steruje dostępnością głównych zakładek.

        Zasada:
        - tryb swobodny: wszystko dostępne
        - tryb aktywnego projektu: ręcznie klikalne są tylko:
        * Wizard kampanii
        * Help
        * aktualnie OTWARTA zakładka robocza (jeśli weszliśmy tam z wizarda)
        """

        from ..campaign_manager import CAMPAIGN

        active = CAMPAIGN.get_active_project_name()

        # ręczny free mode albo brak aktywnego projektu = pełna swoboda
        if self.campaign_free_mode or not active:
            self.campaign_mode_active = False

            for key, tab in self.tabs.items():
                try:
                    self.notebook.tab(str(tab.frame), state="normal")
                except Exception:
                    pass
            return

        # aktywny projekt
        self.campaign_mode_active = True

        selected_key = self._get_selected_tab_key()

        allowed = {"campaign", "help"}

        # jeżeli użytkownik jest już w zakładce roboczej, zostaw ją aktywną
        # ale nie odblokowuj innych roboczych tabów
        if selected_key in {"annotation", "characters", "training"}:
            allowed.add(selected_key)

        for key, tab in self.tabs.items():
            try:
                state = "normal" if key in allowed else "disabled"
                self.notebook.tab(str(tab.frame), state=state)
            except Exception:
                pass

    def get_tab_index(self, tab_key: str) -> int:
        if tab_key not in self.tabs:
            raise KeyError(f"Unknown tab key: {tab_key}")

        target_widget = str(self.tabs[tab_key].frame)

        for i, widget_name in enumerate(self.notebook.tabs()):
            if str(widget_name) == target_widget:
                return i

        raise KeyError(f"Tab widget not found in notebook for key: {tab_key}")


    def select_tab(self, tab_key: str):
        if tab_key not in self.tabs:
            raise KeyError(f"Unknown tab key: {tab_key}")

        self.notebook.select(str(self.tabs[tab_key].frame))

    def open_controlled_tab(self, tab_key: str):
        if tab_key not in self.tabs:
            raise KeyError(f"Unknown tab key: {tab_key}")

        tab_widget = str(self.tabs[tab_key].frame)

        # tymczasowo odblokuj tab, aby dało się go wybrać programowo
        self.notebook.tab(tab_widget, state="normal")
        self.notebook.select(tab_widget)

        # po przejściu od razu zsynchronizuj dostępność zakładek
        self.update_campaign_tab_access()

    def _guard_campaign_navigation(self, event=None):
        return


    
    def _on_closing(self):
        if self.is_processing:
            if not messagebox.askokcancel("Zamknij", "Przetwarzanie w toku. Na pewno zamknąć?"):
                return
        for handler in logger.handlers[:]:
            try: handler.close(); logger.removeHandler(handler)
            except: pass
        for tab_name, tab in self.tabs.items():
            if hasattr(tab, 'annotator') and tab.annotator:
                try: tab.annotator.stop(); tab.annotator.unload_models()
                except: pass
        self.root.destroy()