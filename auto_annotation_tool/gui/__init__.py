#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moduł GUI aplikacji.
"""

from .app import AutoAnnotationApp
from .tab_annotation import AnnotationTab
from .tab_character_annotation import CharacterAnnotationTab
from .tab_training import TrainingTab
from .tab_help import HelpTab
from .tab_rectification import RectificationTab

__all__ = [
    'AutoAnnotationApp',
    'AnnotationTab',
    'CharacterAnnotationTab',
    'TrainingTab',
    'RectificationTab',
    'HelpTab'
]