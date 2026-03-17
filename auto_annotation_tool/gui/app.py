#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Główna aplikacja GUI.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from ..config import CONFIG, logger, TK_AVAILABLE
from ..icons import IconManager

# Importy zakładek
from .tab_annotation import AnnotationTab
from .tab_character_annotation import CharacterAnnotationTab
from .tab_training import TrainingTab

# Importy opcjonalne (jeśli wciąż używasz starych zakładek)
try:
    from .tab_rectification import RectificationTab
except ImportError:
    RectificationTab = None
    
try:
    from .tab_help import HelpTab
except ImportError:
    HelpTab = None


class AutoAnnotationApp:
    """Główna aplikacja z zakładkami."""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"{CONFIG.APP_NAME} v{CONFIG.VERSION}")
        
        # Handler zamykania - kluczowe dla bezpiecznego zapisu sesji!
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # Ikony
        self.icon_manager = IconManager
        self.icon_manager.test_emoji_support(root)
        
        # Styl
        self.style = ttk.Style()
        self._setup_style()
        
        # Zmienne
        self.is_processing = False
        
        # 1. NAJPIERW tworzymy Menu
        self._create_menu()
        
        # 2. NASTĘPNIE tworzymy i przypinamy NA SAM DÓŁ pojemny panel informacyjny
        self.info_panel_frame = tk.Frame(root, bg="#f1f5f9", bd=1, relief=tk.SUNKEN)
        self.info_panel_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_text = tk.Text(
            self.info_panel_frame, height=2, wrap=tk.WORD, 
            bg="#f1f5f9", bd=0, font=("Segoe UI", 10, "italic"), fg="#2c3e50"
        )
        self.status_text.pack(fill=tk.X, padx=10, pady=6)
        self.status_text.insert(tk.END, f"{self.icon_manager.get('info')} Gotowy. Najedź myszką na element interfejsu, aby zobaczyć wskazówki.")
        self.status_text.config(state=tk.DISABLED)
        
        # 3. DOPIERO TERAZ tworzymy Notatnik, który zajmie całą resztę ekranu (nad paskiem)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
        
        # Tworzenie zakładek
        self.tabs = {}
        self._create_tabs()
        
        # 4. Podpinamy system pomocy
        from .help_manager import HELP
        HELP.status_updater = lambda msg: self.update_status(msg, "info")
        
        logger.info("GUI zainicjalizowane pomyślnie")
    
    def _setup_style(self):
        """Konfiguruje wygląd i czytelność elementów GUI."""
        try:
            self.style.theme_use('clam')
            self.style.configure('TNotebook.Tab', padding=[15, 8], font=('Segoe UI', 10, 'bold'))
            self.style.configure('TButton', padding=6)
            self.style.configure('TLabel', padding=2)
        except Exception:
            pass
    
    def _create_tabs(self):
        """Tworzy i podpina główne zakładki aplikacji w odpowiedniej kolejności."""
        try:
            # 1. ZAKŁADKA AUTOANOTACJI
            self.tabs['annotation'] = AnnotationTab(self.notebook, self)
            self.notebook.add(self.tabs['annotation'].frame, text=f"1. Autoanotacja")
            
            # 2. ZAKŁADKA WYCINANIA ZNAKÓW
            try:
                self.tabs['characters'] = CharacterAnnotationTab(self.notebook, self)
                self.notebook.add(self.tabs['characters'].frame, text=f"2. Znaki na tablicach")
            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki ZNAKI: {e}")
                messagebox.showerror("Błąd Zakładki", f"Błąd w zakładce Znaki na tablicach:\n{e}")
            
            # 3. ZAKŁADKA TRENINGU
            try:
                self.tabs['training'] = TrainingTab(self.notebook, self)
                self.notebook.add(self.tabs['training'].frame, text=f"3. Trening i Analiza")
            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki TRENING: {e}")
                messagebox.showerror("Błąd Zakładki", f"Błąd w zakładce Trening:\n{e}")
            # ZAKŁADKA POMOCY / PRZEWODNIK
            if HelpTab:
                self.tabs['help'] = HelpTab(self.notebook, self)
                self.notebook.add(self.tabs['help'].frame, text=f"4. Instrukcja & Architektura")

            self.notebook.select(0)
            self.notebook.select(0)
            
        except Exception as e:
            logger.error(f"Krytyczny błąd budowania zakładek GUI: {e}")
    
    def _create_menu(self):
        """Tworzy menu górne."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Plik", menu=file_menu)
        file_menu.add_command(label=f"{self.icon_manager.get('stop')} Wyjście", command=self._on_closing)
        
        # Pomoc i GPU
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Opcje i Pomoc", menu=help_menu)
        help_menu.add_command(label=f"{self.icon_manager.get('gpu')} Specyfikacja GPU", command=self._show_gpu_info)
        help_menu.add_separator()
        help_menu.add_command(label=f"{self.icon_manager.get('info')} O programie", command=self._show_about)
    
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
        except Exception:
            pass # Zapobiega błędom, gdy aplikacja jest w trakcie zamykania
    
    def set_processing(self, processing: bool):
        self.is_processing = processing
        if processing:
            self.root.config(cursor="wait")
        else:
            self.root.config(cursor="")
        self.root.update()
        
    def _show_gpu_info(self):
        info = ""
        try:
            import torch
            if torch.cuda.is_available():
                device_count = torch.cuda.device_count()
                info += f"Wykryto sprzętowe wsparcie CUDA: TAK\n"
                info += f"Dostępne karty graficzne (GPU): {device_count}\n"
                info += "-" * 40 + "\n\n"
                for i in range(device_count):
                    name = torch.cuda.get_device_name(i)
                    mem_bytes = torch.cuda.get_device_properties(i).total_memory
                    mem_gb = mem_bytes / (1024**3)
                    info += f"GPU {i}: {name}\n"
                    info += f"Pamięć VRAM: {mem_gb:.2f} GB\n\n"
            else:
                info += "Wykryto wsparcie CUDA: NIE\n\nPyTorch używa procesora (CPU)."
        except ImportError:
            info = "Biblioteka PyTorch nie jest zainstalowana."
            
        messagebox.showinfo("Specyfikacja i status GPU", info)
    
    def _show_about(self):
        about_text = f"""
{CONFIG.APP_NAME} v{CONFIG.VERSION}

Zintegrowana platforma MLOps do:
• Detekcji pojazdów i tablic rejestracyjnych (Autoanotacja)
• Automatycznego wycinania, prostowania i czytania OCR
• Eksportu i importu struktury z platformy CVAT
• Budowy zestawów danych (Datasetów) i treningu modeli YOLO

Autor: [Wpisz tu swoje imię i nazwisko!]
"""
        messagebox.showinfo("O programie", about_text)
    
    def _on_closing(self):
        """Obsługa zamykania. Wymusza zapisanie otwartych sesji!"""
        if self.is_processing:
            if not messagebox.askokcancel("Zamknij", "Przetwarzanie w toku. Na pewno zamknąć?"):
                return
        
        # Wyczyść handlery loggera, żeby uniknąć błędów _tkinter przy niszczeniu widgetów
        for handler in logger.handlers[:]:
            try:
                handler.close()
                logger.removeHandler(handler)
            except:
                pass
        
        # Zatrzymaj działające procesy w zakładkach
        for tab_name, tab in self.tabs.items():
            if hasattr(tab, 'annotator') and tab.annotator:
                try: tab.annotator.stop()
                except: pass
                try: tab.annotator.unload_models()
                except: pass
                
        logger.info("Aplikacja zamykana...")
        self.root.destroy()