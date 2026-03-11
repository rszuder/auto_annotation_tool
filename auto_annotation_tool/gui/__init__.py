#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moduł GUI aplikacji.
"""

from .app import AutoAnnotationApp
from .tab_annotation import AnnotationTab
from .tab_training import TrainingTab
from .tab_ranking import RankingTab
from .tab_validation import ValidationTab
from .tab_help import HelpTab

__all__ = [
    'AutoAnnotationApp',
    'AnnotationTab',
    'TrainingTab',
    'RankingTab',
    'ValidationTab',
    'HelpTab'
]