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
from .tab_annotation import AnnotationTab
from .tab_training import TrainingTab
from .tab_ranking import RankingTab
from .tab_validation import ValidationTab
from .tab_help import HelpTab
from .tab_rectification import RectificationTab


class AutoAnnotationApp:
    """Główna aplikacja z zakładkami."""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"{CONFIG.APP_NAME} v{CONFIG.VERSION}")
        
        # Ikony
        self.icon_manager = IconManager
        self.icon_manager.test_emoji_support(root)
        
        # Styl
        self.style = ttk.Style()
        self._setup_style()
        
        # Zmienne
        self.is_processing = False
        
        # Zakładki
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Twórz zakładki
        self.tabs = {}
        self._create_tabs()
        
        # Menu
        self._create_menu()
        
        # Status bar
        self.status_var = tk.StringVar(value=f"{self.icon_manager.get('info')} Gotowy")
        status_bar = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        logger.info("GUI zainicjalizowane")
    
    def _setup_style(self):
        """Konfiguruje styl."""
        try:
            self.style.theme_use('clam')
            self.style.configure('TNotebook.Tab', padding=[12, 8])
            self.style.configure('TButton', padding=6)
            self.style.configure('TLabel', padding=2)
        except Exception:
            pass
    
    def _create_tabs(self):
        """Tworzy zakładki."""
        self.tabs['annotation'] = AnnotationTab(self.notebook, self)
        self.notebook.add(self.tabs['annotation'].frame, text=f"{self.icon_manager.get('car')} Anotacja")
        
        self.tabs['training'] = TrainingTab(self.notebook, self)
        self.notebook.add(self.tabs['training'].frame, text=f"{self.icon_manager.get('training')} Trening")
        
        self.tabs['ranking'] = RankingTab(self.notebook, self)
        self.notebook.add(self.tabs['ranking'].frame, text=f"{self.icon_manager.get('trophy')} Ranking")
        
        self.tabs['validation'] = ValidationTab(self.notebook, self)
        self.notebook.add(self.tabs['validation'].frame, text=f"{self.icon_manager.get('check')} Walidacja")
        
        self.tabs['rectification'] = RectificationTab(self.notebook, self)
        self.notebook.add(self.tabs['rectification'].frame, text=f"{self.icon_manager.get('plate')} Prostowanie tablic")

        self.tabs['help'] = HelpTab(self.notebook, self)
        self.notebook.add(self.tabs['help'].frame, text=f"{self.icon_manager.get('help')} Pomoc")
        
        self.notebook.select(0)
    
    def _create_menu(self):
        """Tworzy menu."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Plik", menu=file_menu)
        file_menu.add_command(label=f"{self.icon_manager.get('save')} Zapisz konfigurację", command=self._save_config)
        file_menu.add_separator()
        file_menu.add_command(label=f"{self.icon_manager.get('stop')} Wyjście", command=self._on_closing)
        
        # Pomoc i GPU
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Opcje i Pomoc", menu=help_menu)
        help_menu.add_command(label=f"{self.icon_manager.get('gpu')} Specyfikacja GPU", command=self._show_gpu_info)
        help_menu.add_separator()
        help_menu.add_command(label=f"{self.icon_manager.get('info')} O programie", command=self._show_about)
    
    def update_status(self, message: str, icon: str = "info"):
        """Aktualizuje pasek statusu."""
        self.status_var.set(f"{self.icon_manager.get(icon)} {message}")
        self.root.update_idletasks()
    
    def set_processing(self, processing: bool):
        """Ustawia stan przetwarzania."""
        self.is_processing = processing
        if processing:
            self.root.config(cursor="wait")
        else:
            self.root.config(cursor="")
        self.root.update()
    
    def _save_config(self):
        messagebox.showinfo("Konfiguracja", "Funkcja w budowie.")
        
    def _show_gpu_info(self):
        """Wykrywa i wyświetla specyfikację kart graficznych."""
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
                info += "Wykryto wsparcie CUDA: NIE\n\n"
                info += "PyTorch używa procesora (CPU) do obliczeń.\n"
                info += "Jeżeli posiadasz kartę NVIDIA, zainstaluj PyTorch z obsługą CUDA:\n"
                info += "pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118"
        except ImportError:
            info = "Biblioteka PyTorch nie jest zainstalowana.\nNie można zweryfikować dostępności GPU."
            
        messagebox.showinfo("Specyfikacja i status GPU", info)
    
    def _show_about(self):
        """Pokazuje info o programie."""
        about_text = f"""
{CONFIG.APP_NAME} v{CONFIG.VERSION}

Narzędzie do automatycznej anotacji pojazdów i tablic rejestracyjnych
dla CVAT. Obsługuje YOLOv8, YOLOv11 oraz najnowsze YOLOv26!

Funkcje:
• Detekcja pojazdów i tablic (YOLO)
• Trening modeli Pose
• Eksport do CVAT XML
• Ranking modeli
• Walidacja datasetów

Autor: [Twoje imię]
Licencja: MIT
        """
        messagebox.showinfo("O programie", about_text)
    
    def _on_closing(self):
        """Obsługa zamykania."""
        if self.is_processing:
            if not messagebox.askokcancel("Zamknij", "Przetwarzanie w toku. Zamknąć?"):
                return
        self.root.destroy()