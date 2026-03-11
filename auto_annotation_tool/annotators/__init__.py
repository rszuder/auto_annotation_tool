#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moduł annotatorów.
"""

from .vehicle_annotator import VehicleAnnotator
from .plate_annotator import PlateAnnotator
from .combined_annotator import CombinedAnnotator

__all__ = [
    'VehicleAnnotator',
    'PlateAnnotator', 
    'CombinedAnnotator'
]