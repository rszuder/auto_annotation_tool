#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safe train-only YOLO dataset augmentation.

This module intentionally avoids crops, flips and strong perspective warps.
It only creates additional training images from the train split and transforms
YOLO labels together with the image.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import importlib
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable

from ..config import CONFIG, CV2_AVAILABLE, YAML_AVAILABLE, cv2, logger, np, yaml
from ..utils import safe_load_yaml


MAX_DIRT_FLOW_POINTS = 2000
MAX_RAIN_DROPS = 60000
MAX_RAIN_LENS_PIXELS = 1_600_000
MAX_RAIN_EDGE_PIXELS = 2_000_000
MAX_AUGMENTATION_PREVIEW_PIXELS = 1_400_000


@dataclass(frozen=True)
class AugmentationProfile:
    """User-facing augmentation settings for one dataset build."""

    enabled: bool = False
    sample_size: int = 32
    extra_count: int = 0
    rotation_limit: float = 0.0
    translate_limit: float = 0.0
    scale_limit: float = 0.0
    brightness_limit: float = 0.0
    contrast_limit: float = 0.0
    saturation_limit: float = 1.0
    noise_strength: float = 0.0
    noise_grain_size: int = 1
    rain_strength: float = 0.0
    rain_drop_size: float = 0.07
    rain_drop_size_min: float = 0.01
    rain_drop_size_max: float = 0.13
    rain_vector_field_strength: float = 0.0
    rain_vortex_strength: float = 0.0
    rain_alpha: float = 0.22
    rain_lens_strength: float = 0.0
    rain_edge_mist_strength: float = 0.0
    rain_edge_mist_radius: float = 0.45
    tyndall_strength: float = 0.55
    wet_reflection_strength: float = 0.0
    vehicle_speed: float = 0.0
    night_strength: float = 0.0
    night_luma_min: float = 0.56
    night_luma_max: float = 0.92
    night_light_strength: float = 0.0
    night_bloom_strength: float = 0.0
    night_iso_noise_strength: float = 0.0
    night_light_warmth: float = 0.35
    traffic_headlight_strength: float = 0.0
    traffic_headlight_count: int = 3
    traffic_headlight_source_x: float = -1.0
    traffic_headlight_source_y: float = -1.0
    traffic_headlight_target_x: float = -1.0
    traffic_headlight_target_y: float = -1.0
    traffic_headlight_1_warmth: float = -1.0
    traffic_headlight_1_r: float = -1.0
    traffic_headlight_1_g: float = -1.0
    traffic_headlight_1_b: float = -1.0
    traffic_headlight_1_cone: float = 0.45
    traffic_headlight_1_source_radius: float = 0.08
    traffic_headlight_2_strength: float = 0.0
    traffic_headlight_2_warmth: float = 0.35
    traffic_headlight_2_r: float = -1.0
    traffic_headlight_2_g: float = -1.0
    traffic_headlight_2_b: float = -1.0
    traffic_headlight_2_cone: float = 0.45
    traffic_headlight_2_source_radius: float = 0.08
    traffic_headlight_2_source_x: float = -1.0
    traffic_headlight_2_source_y: float = -1.0
    traffic_headlight_2_target_x: float = -1.0
    traffic_headlight_2_target_y: float = -1.0
    traffic_headlight_3_strength: float = 0.0
    traffic_headlight_3_warmth: float = 0.35
    traffic_headlight_3_r: float = -1.0
    traffic_headlight_3_g: float = -1.0
    traffic_headlight_3_b: float = -1.0
    traffic_headlight_3_cone: float = 0.45
    traffic_headlight_3_source_radius: float = 0.08
    traffic_headlight_3_source_x: float = -1.0
    traffic_headlight_3_source_y: float = -1.0
    traffic_headlight_3_target_x: float = -1.0
    traffic_headlight_3_target_y: float = -1.0
    wet_mud_gloss_strength: float = 0.0
    flare_strength: float = 0.0
    overexposure_strength: float = 0.0
    dirt_streak_strength: float = 0.0
    dirt_flow_strength: float = 0.0
    dirt_flow_points: int = 0
    dirt_flow_mass_min: float = 0.18
    dirt_flow_mass_max: float = 1.0
    dirt_flow_splash_scale: float = 0.45
    dirt_flow_trail_length: float = 0.55
    dirt_flow_humidity: float = 0.45
    dirt_flow_stickiness: float = 0.45
    dirt_flow_stickiness_min: float = 0.30
    dirt_flow_stickiness_max: float = 0.70
    dirt_flow_air_angle: float = 0.0
    dirt_flow_wind_strength: float = 0.45
    dirt_flow_gravity_angle: float = 90.0
    dirt_flow_gravity_strength: float = 1.0
    dirt_flow_opacity_min: float = 0.25
    dirt_flow_opacity_max: float = 0.80
    dirt_flow_stop_on_dark_contour: bool = False
    dark_relief_strength: float = 0.0
    dark_relief_light_angle: float = 135.0
    light_normal_strength: float = 0.0
    overhang_shadow_strength: float = 0.0
    overhang_shadow_depth: float = 0.60
    overhang_shadow_skew: float = 0.0
    plate_reflect_gradient_strength: float = 0.0
    plate_reflect_glare_strength: float = 0.0
    plate_reflect_curve_strength: float = 0.0
    blur_strength: float = 0.0
    blur_enabled: bool = False
    seed: int = 42
    class_name: str = ""

    def normalized(self) -> "AugmentationProfile":
        dirt_flow_opacity_min = max(0.0, min(1.0, float(self.dirt_flow_opacity_min or 0.0)))
        dirt_flow_opacity_max = max(0.0, min(1.0, float(self.dirt_flow_opacity_max or 0.0)))
        if dirt_flow_opacity_min > dirt_flow_opacity_max:
            dirt_flow_opacity_min, dirt_flow_opacity_max = dirt_flow_opacity_max, dirt_flow_opacity_min
        dirt_flow_mass_min = max(0.05, min(2.8, float(getattr(self, "dirt_flow_mass_min", 0.18) or 0.18)))
        dirt_flow_mass_max = max(0.05, min(2.8, float(getattr(self, "dirt_flow_mass_max", 1.0) or 1.0)))
        if dirt_flow_mass_min > dirt_flow_mass_max:
            dirt_flow_mass_min, dirt_flow_mass_max = dirt_flow_mass_max, dirt_flow_mass_min
        legacy_stickiness = max(0.0, min(1.0, float(getattr(self, "dirt_flow_stickiness", 0.45) if getattr(self, "dirt_flow_stickiness", None) is not None else 0.45)))
        dirt_flow_stickiness_min = max(0.0, min(1.0, float(getattr(self, "dirt_flow_stickiness_min", legacy_stickiness) if getattr(self, "dirt_flow_stickiness_min", None) is not None else legacy_stickiness)))
        dirt_flow_stickiness_max = max(0.0, min(1.0, float(getattr(self, "dirt_flow_stickiness_max", legacy_stickiness) if getattr(self, "dirt_flow_stickiness_max", None) is not None else legacy_stickiness)))
        if dirt_flow_stickiness_min > dirt_flow_stickiness_max:
            dirt_flow_stickiness_min, dirt_flow_stickiness_max = dirt_flow_stickiness_max, dirt_flow_stickiness_min
        dirt_flow_stickiness = (dirt_flow_stickiness_min + dirt_flow_stickiness_max) / 2.0
        legacy_drop_size = max(0.0, min(1.0, float(self.rain_drop_size if self.rain_drop_size is not None else 0.35)))
        rain_drop_size_min = max(0.0, min(1.0, float(getattr(self, "rain_drop_size_min", legacy_drop_size) if getattr(self, "rain_drop_size_min", None) is not None else legacy_drop_size)))
        rain_drop_size_max = max(0.0, min(1.0, float(getattr(self, "rain_drop_size_max", legacy_drop_size) if getattr(self, "rain_drop_size_max", None) is not None else legacy_drop_size)))
        if rain_drop_size_min > rain_drop_size_max:
            rain_drop_size_min, rain_drop_size_max = rain_drop_size_max, rain_drop_size_min
        rain_drop_size = (rain_drop_size_min + rain_drop_size_max) / 2.0
        blur_strength = max(0.0, min(1.0, float(getattr(self, "blur_strength", 0.0) or 0.0)))
        if blur_strength <= 0.001 and bool(getattr(self, "blur_enabled", False)):
            blur_strength = 0.18
        return AugmentationProfile(
            enabled=bool(self.enabled),
            sample_size=max(1, int(self.sample_size or 1)),
            extra_count=max(0, int(self.extra_count or 0)),
            rotation_limit=max(-15.0, min(15.0, float(self.rotation_limit or 0.0))),
            translate_limit=max(0.0, min(0.03, float(self.translate_limit or 0.0))),
            scale_limit=max(0.0, min(0.08, float(self.scale_limit or 0.0))),
            brightness_limit=max(0.0, min(0.25, float(self.brightness_limit or 0.0))),
            contrast_limit=max(0.0, min(0.25, float(self.contrast_limit or 0.0))),
            saturation_limit=max(0.0, min(3.0, float(getattr(self, "saturation_limit", 1.0) if getattr(self, "saturation_limit", None) is not None else 1.0))),
            noise_strength=max(0.0, min(0.08, float(self.noise_strength or 0.0))),
            noise_grain_size=max(1, min(12, int(float(self.noise_grain_size or 1)))),
            rain_strength=max(0.0, min(1.0, float(self.rain_strength or 0.0))),
            rain_drop_size=rain_drop_size,
            rain_drop_size_min=rain_drop_size_min,
            rain_drop_size_max=rain_drop_size_max,
            rain_vector_field_strength=max(0.0, min(1.0, float(getattr(self, "rain_vector_field_strength", 0.0) or 0.0))),
            rain_vortex_strength=max(0.0, min(1.0, float(getattr(self, "rain_vortex_strength", 0.0) or 0.0))),
            rain_alpha=max(0.0, min(1.0, float(getattr(self, "rain_alpha", 0.22) if getattr(self, "rain_alpha", None) is not None else 0.22))),
            rain_lens_strength=max(0.0, min(1.0, float(getattr(self, "rain_lens_strength", 0.0) or 0.0))),
            rain_edge_mist_strength=max(0.0, min(1.0, float(getattr(self, "rain_edge_mist_strength", 0.0) or 0.0))),
            rain_edge_mist_radius=max(0.0, min(1.0, float(getattr(self, "rain_edge_mist_radius", 0.45) if getattr(self, "rain_edge_mist_radius", None) is not None else 0.45))),
            tyndall_strength=max(0.0, min(1.0, float(getattr(self, "tyndall_strength", 0.55) if getattr(self, "tyndall_strength", None) is not None else 0.55))),
            wet_reflection_strength=max(0.0, min(1.0, float(self.wet_reflection_strength if self.wet_reflection_strength is not None else 0.0))),
            vehicle_speed=max(0.0, min(1.0, float(self.vehicle_speed if self.vehicle_speed is not None else 0.0))),
            night_strength=max(0.0, min(1.0, float(self.night_strength or 0.0))),
            night_luma_min=0.56,
            night_luma_max=0.92,
            night_light_strength=max(0.0, min(1.0, float(getattr(self, "night_light_strength", 0.0) or 0.0))),
            night_bloom_strength=max(0.0, min(1.0, float(getattr(self, "night_bloom_strength", 0.0) or 0.0))),
            night_iso_noise_strength=max(0.0, min(1.0, float(getattr(self, "night_iso_noise_strength", 0.0) or 0.0))),
            night_light_warmth=max(0.0, min(1.0, float(getattr(self, "night_light_warmth", 0.35) if getattr(self, "night_light_warmth", None) is not None else 0.35))),
            traffic_headlight_strength=max(0.0, min(1.0, float(getattr(self, "traffic_headlight_strength", 0.0) or 0.0))),
            traffic_headlight_count=max(0, min(6, int(float(getattr(self, "traffic_headlight_count", 3) if getattr(self, "traffic_headlight_count", None) is not None else 3)))),
            traffic_headlight_source_x=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_source_x", -1.0) if getattr(self, "traffic_headlight_source_x", None) is not None else -1.0))),
            traffic_headlight_source_y=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_source_y", -1.0) if getattr(self, "traffic_headlight_source_y", None) is not None else -1.0))),
            traffic_headlight_target_x=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_target_x", -1.0) if getattr(self, "traffic_headlight_target_x", None) is not None else -1.0))),
            traffic_headlight_target_y=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_target_y", -1.0) if getattr(self, "traffic_headlight_target_y", None) is not None else -1.0))),
            traffic_headlight_1_warmth=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_1_warmth", -1.0) if getattr(self, "traffic_headlight_1_warmth", None) is not None else -1.0))),
            traffic_headlight_1_r=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_1_r", -1.0) if getattr(self, "traffic_headlight_1_r", None) is not None else -1.0))),
            traffic_headlight_1_g=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_1_g", -1.0) if getattr(self, "traffic_headlight_1_g", None) is not None else -1.0))),
            traffic_headlight_1_b=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_1_b", -1.0) if getattr(self, "traffic_headlight_1_b", None) is not None else -1.0))),
            traffic_headlight_1_cone=max(0.02, min(2.5, float(getattr(self, "traffic_headlight_1_cone", 0.45) if getattr(self, "traffic_headlight_1_cone", None) is not None else 0.45))),
            traffic_headlight_1_source_radius=max(0.0, min(2.5, float(getattr(self, "traffic_headlight_1_source_radius", 0.08) if getattr(self, "traffic_headlight_1_source_radius", None) is not None else 0.08))),
            traffic_headlight_2_strength=max(0.0, min(1.0, float(getattr(self, "traffic_headlight_2_strength", 0.0) or 0.0))),
            traffic_headlight_2_warmth=max(0.0, min(1.0, float(getattr(self, "traffic_headlight_2_warmth", 0.35) if getattr(self, "traffic_headlight_2_warmth", None) is not None else 0.35))),
            traffic_headlight_2_r=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_2_r", -1.0) if getattr(self, "traffic_headlight_2_r", None) is not None else -1.0))),
            traffic_headlight_2_g=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_2_g", -1.0) if getattr(self, "traffic_headlight_2_g", None) is not None else -1.0))),
            traffic_headlight_2_b=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_2_b", -1.0) if getattr(self, "traffic_headlight_2_b", None) is not None else -1.0))),
            traffic_headlight_2_cone=max(0.02, min(2.5, float(getattr(self, "traffic_headlight_2_cone", 0.45) if getattr(self, "traffic_headlight_2_cone", None) is not None else 0.45))),
            traffic_headlight_2_source_radius=max(0.0, min(2.5, float(getattr(self, "traffic_headlight_2_source_radius", 0.08) if getattr(self, "traffic_headlight_2_source_radius", None) is not None else 0.08))),
            traffic_headlight_2_source_x=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_2_source_x", -1.0) if getattr(self, "traffic_headlight_2_source_x", None) is not None else -1.0))),
            traffic_headlight_2_source_y=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_2_source_y", -1.0) if getattr(self, "traffic_headlight_2_source_y", None) is not None else -1.0))),
            traffic_headlight_2_target_x=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_2_target_x", -1.0) if getattr(self, "traffic_headlight_2_target_x", None) is not None else -1.0))),
            traffic_headlight_2_target_y=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_2_target_y", -1.0) if getattr(self, "traffic_headlight_2_target_y", None) is not None else -1.0))),
            traffic_headlight_3_strength=max(0.0, min(1.0, float(getattr(self, "traffic_headlight_3_strength", 0.0) or 0.0))),
            traffic_headlight_3_warmth=max(0.0, min(1.0, float(getattr(self, "traffic_headlight_3_warmth", 0.35) if getattr(self, "traffic_headlight_3_warmth", None) is not None else 0.35))),
            traffic_headlight_3_r=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_3_r", -1.0) if getattr(self, "traffic_headlight_3_r", None) is not None else -1.0))),
            traffic_headlight_3_g=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_3_g", -1.0) if getattr(self, "traffic_headlight_3_g", None) is not None else -1.0))),
            traffic_headlight_3_b=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_3_b", -1.0) if getattr(self, "traffic_headlight_3_b", None) is not None else -1.0))),
            traffic_headlight_3_cone=max(0.02, min(2.5, float(getattr(self, "traffic_headlight_3_cone", 0.45) if getattr(self, "traffic_headlight_3_cone", None) is not None else 0.45))),
            traffic_headlight_3_source_radius=max(0.0, min(2.5, float(getattr(self, "traffic_headlight_3_source_radius", 0.08) if getattr(self, "traffic_headlight_3_source_radius", None) is not None else 0.08))),
            traffic_headlight_3_source_x=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_3_source_x", -1.0) if getattr(self, "traffic_headlight_3_source_x", None) is not None else -1.0))),
            traffic_headlight_3_source_y=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_3_source_y", -1.0) if getattr(self, "traffic_headlight_3_source_y", None) is not None else -1.0))),
            traffic_headlight_3_target_x=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_3_target_x", -1.0) if getattr(self, "traffic_headlight_3_target_x", None) is not None else -1.0))),
            traffic_headlight_3_target_y=max(-1.0, min(1.0, float(getattr(self, "traffic_headlight_3_target_y", -1.0) if getattr(self, "traffic_headlight_3_target_y", None) is not None else -1.0))),
            wet_mud_gloss_strength=max(0.0, min(1.0, float(getattr(self, "wet_mud_gloss_strength", 0.0) or 0.0))),
            flare_strength=max(0.0, min(1.0, float(self.flare_strength or 0.0))),
            overexposure_strength=max(0.0, min(1.0, float(self.overexposure_strength or 0.0))),
            dirt_streak_strength=max(0.0, min(1.0, float(self.dirt_streak_strength or 0.0))),
            dirt_flow_strength=max(0.0, min(1.0, float(self.dirt_flow_strength or 0.0))),
            dirt_flow_points=max(0, min(MAX_DIRT_FLOW_POINTS, int(float(self.dirt_flow_points or 0)))),
            dirt_flow_mass_min=dirt_flow_mass_min,
            dirt_flow_mass_max=dirt_flow_mass_max,
            dirt_flow_splash_scale=max(0.0, min(1.0, float(self.dirt_flow_splash_scale if self.dirt_flow_splash_scale is not None else 0.45))),
            dirt_flow_trail_length=max(0.0, min(1.0, float(self.dirt_flow_trail_length if self.dirt_flow_trail_length is not None else 0.55))),
            dirt_flow_humidity=max(0.0, min(1.0, float(self.dirt_flow_humidity if self.dirt_flow_humidity is not None else 0.45))),
            dirt_flow_stickiness=dirt_flow_stickiness,
            dirt_flow_stickiness_min=dirt_flow_stickiness_min,
            dirt_flow_stickiness_max=dirt_flow_stickiness_max,
            dirt_flow_air_angle=max(-75.0, min(75.0, float(self.dirt_flow_air_angle or 0.0))),
            dirt_flow_wind_strength=max(0.0, min(1.0, float(self.dirt_flow_wind_strength if self.dirt_flow_wind_strength is not None else 0.45))),
            dirt_flow_gravity_angle=float(self.dirt_flow_gravity_angle if self.dirt_flow_gravity_angle is not None else 90.0) % 360.0,
            dirt_flow_gravity_strength=max(0.0, min(1.0, float(self.dirt_flow_gravity_strength if self.dirt_flow_gravity_strength is not None else 1.0))),
            dirt_flow_opacity_min=dirt_flow_opacity_min,
            dirt_flow_opacity_max=dirt_flow_opacity_max,
            dirt_flow_stop_on_dark_contour=bool(getattr(self, "dirt_flow_stop_on_dark_contour", False)),
            dark_relief_strength=max(0.0, min(3.0, float(self.dark_relief_strength or 0.0))),
            dark_relief_light_angle=float(self.dark_relief_light_angle or 0.0) % 360.0,
            light_normal_strength=max(0.0, min(1.0, float(self.light_normal_strength if self.light_normal_strength is not None else 0.0))),
            overhang_shadow_strength=max(0.0, min(1.0, float(getattr(self, "overhang_shadow_strength", 0.0) or 0.0))),
            overhang_shadow_depth=max(0.0, min(0.60, float(getattr(self, "overhang_shadow_depth", 0.60) if getattr(self, "overhang_shadow_depth", None) is not None else 0.60))),
            overhang_shadow_skew=max(-1.0, min(1.0, float(getattr(self, "overhang_shadow_skew", 0.0) or 0.0))),
            plate_reflect_gradient_strength=max(0.0, min(2.0, float(getattr(self, "plate_reflect_gradient_strength", 0.0) or 0.0))),
            plate_reflect_glare_strength=max(0.0, min(2.0, float(getattr(self, "plate_reflect_glare_strength", 0.0) or 0.0))),
            plate_reflect_curve_strength=max(0.0, min(2.0, float(getattr(self, "plate_reflect_curve_strength", 0.0) or 0.0))),
            blur_strength=blur_strength,
            blur_enabled=bool(self.blur_enabled) or blur_strength > 0.001,
            seed=int(self.seed or 42),
            class_name=str(self.class_name or "").strip(),
        )


@dataclass
class YoloObject:
    class_id: int
    bbox: list[float]
    keypoints: list[tuple[float, float, float | None]]


def is_albumentations_available() -> bool:
    return importlib.util.find_spec("albumentations") is not None


def get_albumentations_status() -> dict:
    if not is_albumentations_available():
        return {
            "available": False,
            "message": "Biblioteka Albumentations nie jest zainstalowana.",
        }
    return {
        "available": True,
        "message": "Albumentations jest dostępne.",
    }


def build_albumentations_install_command() -> list[str]:
    return [sys.executable, "-m", "pip", "install", "albumentations"]


def install_albumentations(
    line_callback: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Install Albumentations on explicit user request."""
    if is_albumentations_available():
        return True, "Albumentations jest już zainstalowane."

    cmd = build_albumentations_install_command()
    if callable(line_callback):
        line_callback("> " + subprocess.list2cmdline(cmd))

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if process.stdout is not None:
            for line in process.stdout:
                if callable(line_callback):
                    line_callback(str(line or "").rstrip())
        code = process.wait()
    except Exception as exc:
        return False, f"Nie udało się uruchomić instalacji Albumentations: {exc}"

    importlib.invalidate_caches()
    if code == 0 and is_albumentations_available():
        return True, "Albumentations zostało zainstalowane i jest gotowe do augmentacji."
    if code == 0:
        return False, "Instalacja pip zakończyła się, ale moduł Albumentations nadal nie jest widoczny."
    return False, f"Instalacja Albumentations zakończyła się błędem pip (kod {code})."


def _load_albumentations():
    # Albumentations checks PyPI on import unless this flag is set. The app
    # should not touch the network while preparing a local dataset.
    os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")
    return importlib.import_module("albumentations")


def _stable_preview_seed(image_path: Path, profile: AugmentationProfile) -> int:
    normalized = (profile or AugmentationProfile()).normalized()
    # Preview geometry must stay stable while the user tweaks visual effects
    # such as noise, night mode or overexposure. Dataset knobs also must not
    # visually reshuffle the preview. The seed intentionally does not include
    # image_path: switching the preview sample should carry the already tuned
    # effect layout to the next plate/photo instead of silently rerolling it.
    payload = {
        "geometry_profile": {
            "rotation_limit": normalized.rotation_limit,
            "translate_limit": normalized.translate_limit,
            "scale_limit": normalized.scale_limit,
            "seed": normalized.seed,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)


def _seed_transform(transform, seed: int) -> None:
    random.seed(seed)
    try:
        if np is not None:
            np.random.seed(seed % (2**32 - 1))
    except Exception:
        pass
    try:
        transform.set_random_seed(seed)
    except Exception:
        pass


def _apply_preview_seed(transform, image_path: Path, profile: AugmentationProfile) -> None:
    _seed_transform(transform, _stable_preview_seed(image_path, profile))


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(maximum), float(value)))


def _jitter_float(
    value: float,
    rng: random.Random,
    *,
    minimum: float,
    maximum: float,
    sigma_abs: float = 0.0,
    sigma_ratio: float = 0.08,
    max_delta_abs: float = 0.0,
    max_delta_ratio: float = 0.20,
    zero_stays_zero: bool = True,
) -> float:
    base = _clamp_float(value, minimum, maximum)
    if zero_stays_zero and abs(base) <= 0.000001:
        return base
    sigma = max(float(sigma_abs), abs(base) * float(sigma_ratio))
    if sigma <= 0.000001:
        return base
    max_delta = max(float(max_delta_abs), abs(base) * float(max_delta_ratio), sigma * 1.5)
    sampled = rng.gauss(base, sigma)
    sampled = _clamp_float(sampled, base - max_delta, base + max_delta)
    return _clamp_float(sampled, minimum, maximum)


def _jitter_int(
    value: int,
    rng: random.Random,
    *,
    minimum: int,
    maximum: int,
    sigma_abs: float = 1.0,
    sigma_ratio: float = 0.08,
    max_delta_ratio: float = 0.18,
    zero_stays_zero: bool = True,
) -> int:
    base = max(int(minimum), min(int(maximum), int(value or 0)))
    if zero_stays_zero and base <= 0:
        return base
    sigma = max(float(sigma_abs), abs(float(base)) * float(sigma_ratio))
    max_delta = max(1.0, abs(float(base)) * float(max_delta_ratio), sigma * 1.5)
    sampled = rng.gauss(float(base), sigma)
    sampled = _clamp_float(sampled, float(base) - max_delta, float(base) + max_delta)
    return max(int(minimum), min(int(maximum), int(round(sampled))))


def _jitter_optional_unit(value: float, rng: random.Random, *, allow_negative_sentinel: bool = True) -> float:
    base = float(value if value is not None else -1.0)
    if allow_negative_sentinel and base < 0.0:
        return base
    return _jitter_float(
        base,
        rng,
        minimum=0.0,
        maximum=1.0,
        sigma_abs=0.015,
        sigma_ratio=0.06,
        max_delta_abs=0.04,
        max_delta_ratio=0.12,
        zero_stays_zero=False,
    )


def _jitter_coordinate(value: float, rng: random.Random) -> float:
    base = float(value if value is not None else -1.0)
    if base < 0.0:
        return base
    return _jitter_float(
        base,
        rng,
        minimum=0.0,
        maximum=1.0,
        sigma_abs=0.012,
        sigma_ratio=0.025,
        max_delta_abs=0.035,
        max_delta_ratio=0.06,
        zero_stays_zero=False,
    )


def _jitter_range_pair(
    min_value: float,
    max_value: float,
    rng: random.Random,
    *,
    minimum: float,
    maximum: float,
    sigma_abs: float = 0.015,
    sigma_ratio: float = 0.06,
) -> tuple[float, float]:
    lower = _clamp_float(min_value, minimum, maximum)
    upper = _clamp_float(max_value, minimum, maximum)
    if lower > upper:
        lower, upper = upper, lower
    if abs(lower) <= 0.000001 and abs(upper) <= 0.000001:
        return lower, upper

    center = (lower + upper) / 2.0
    width = max(0.0, upper - lower)
    center = _jitter_float(
        center,
        rng,
        minimum=minimum,
        maximum=maximum,
        sigma_abs=sigma_abs,
        sigma_ratio=sigma_ratio,
        max_delta_abs=sigma_abs * 2.5,
        max_delta_ratio=0.10,
        zero_stays_zero=False,
    )
    width = _jitter_float(
        width,
        rng,
        minimum=0.0,
        maximum=maximum - minimum,
        sigma_abs=sigma_abs * 0.75,
        sigma_ratio=0.05,
        max_delta_abs=sigma_abs * 2.0,
        max_delta_ratio=0.12,
        zero_stays_zero=False,
    )
    lower = _clamp_float(center - width / 2.0, minimum, maximum)
    upper = _clamp_float(center + width / 2.0, minimum, maximum)
    if lower > upper:
        lower, upper = upper, lower
    return lower, upper


def _jitter_augmentation_profile(profile: AugmentationProfile, rng: random.Random) -> AugmentationProfile:
    """Return a small per-sample variation around the user profile.

    The profile set in the modal is treated as the expected value. Dataset
    generation only nudges active effects, so the synthetic split gains natural
    diversity without drifting away from the user's intent.
    """
    base = (profile or AugmentationProfile()).normalized()
    rain_min, rain_max = _jitter_range_pair(
        base.rain_drop_size_min,
        base.rain_drop_size_max,
        rng,
        minimum=0.0,
        maximum=1.0,
        sigma_abs=0.010,
        sigma_ratio=0.05,
    )
    mass_min, mass_max = _jitter_range_pair(
        base.dirt_flow_mass_min,
        base.dirt_flow_mass_max,
        rng,
        minimum=0.05,
        maximum=2.8,
        sigma_abs=0.035,
        sigma_ratio=0.045,
    )
    opacity_min, opacity_max = _jitter_range_pair(
        base.dirt_flow_opacity_min,
        base.dirt_flow_opacity_max,
        rng,
        minimum=0.0,
        maximum=1.0,
        sigma_abs=0.018,
        sigma_ratio=0.05,
    )
    stickiness_min, stickiness_max = _jitter_range_pair(
        base.dirt_flow_stickiness_min,
        base.dirt_flow_stickiness_max,
        rng,
        minimum=0.0,
        maximum=1.0,
        sigma_abs=0.018,
        sigma_ratio=0.05,
    )

    jittered = replace(
        base,
        rotation_limit=_jitter_float(base.rotation_limit, rng, minimum=-15.0, maximum=15.0, sigma_abs=1.25, sigma_ratio=0.06, max_delta_abs=3.0, max_delta_ratio=0.16),
        translate_limit=_jitter_float(base.translate_limit, rng, minimum=0.0, maximum=0.03, sigma_abs=0.0015, sigma_ratio=0.10, max_delta_abs=0.004, max_delta_ratio=0.20),
        scale_limit=_jitter_float(base.scale_limit, rng, minimum=0.0, maximum=0.08, sigma_abs=0.003, sigma_ratio=0.10, max_delta_abs=0.010, max_delta_ratio=0.20),
        brightness_limit=_jitter_float(base.brightness_limit, rng, minimum=0.0, maximum=0.25, sigma_abs=0.010, sigma_ratio=0.08, max_delta_abs=0.025, max_delta_ratio=0.16),
        contrast_limit=_jitter_float(base.contrast_limit, rng, minimum=0.0, maximum=0.25, sigma_abs=0.010, sigma_ratio=0.08, max_delta_abs=0.025, max_delta_ratio=0.16),
        saturation_limit=(
            1.0
            if abs(float(base.saturation_limit or 0.0) - 1.0) <= 0.001
            else _jitter_float(base.saturation_limit, rng, minimum=0.0, maximum=3.0, sigma_abs=0.030, sigma_ratio=0.06, max_delta_abs=0.090, max_delta_ratio=0.12)
        ),
        noise_strength=_jitter_float(base.noise_strength, rng, minimum=0.0, maximum=0.08, sigma_abs=0.003, sigma_ratio=0.10, max_delta_abs=0.010, max_delta_ratio=0.22),
        noise_grain_size=_jitter_int(base.noise_grain_size, rng, minimum=1, maximum=12, sigma_abs=0.65, sigma_ratio=0.08, max_delta_ratio=0.22, zero_stays_zero=False),
        rain_strength=_jitter_float(base.rain_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.08, max_delta_abs=0.055, max_delta_ratio=0.16),
        rain_drop_size_min=rain_min,
        rain_drop_size_max=rain_max,
        rain_drop_size=(rain_min + rain_max) / 2.0,
        rain_vector_field_strength=_jitter_float(base.rain_vector_field_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.055, max_delta_ratio=0.16),
        rain_vortex_strength=_jitter_float(base.rain_vortex_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.055, max_delta_ratio=0.16),
        rain_alpha=_jitter_float(base.rain_alpha, rng, minimum=0.0, maximum=1.0, sigma_abs=0.015, sigma_ratio=0.05, max_delta_abs=0.045, max_delta_ratio=0.12, zero_stays_zero=False),
        rain_lens_strength=_jitter_float(base.rain_lens_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.055, max_delta_ratio=0.16),
        rain_edge_mist_strength=_jitter_float(base.rain_edge_mist_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.055, max_delta_ratio=0.16),
        rain_edge_mist_radius=_jitter_float(base.rain_edge_mist_radius, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.05, max_delta_abs=0.050, max_delta_ratio=0.12, zero_stays_zero=False),
        tyndall_strength=_jitter_float(base.tyndall_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.07, max_delta_abs=0.050, max_delta_ratio=0.14),
        wet_reflection_strength=_jitter_float(base.wet_reflection_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.08, max_delta_abs=0.050, max_delta_ratio=0.16),
        vehicle_speed=_jitter_float(base.vehicle_speed, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.07, max_delta_abs=0.050, max_delta_ratio=0.14),
        night_strength=_jitter_float(base.night_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.07, max_delta_abs=0.050, max_delta_ratio=0.14),
        night_light_strength=_jitter_float(base.night_light_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.07, max_delta_abs=0.050, max_delta_ratio=0.14),
        night_bloom_strength=_jitter_float(base.night_bloom_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.07, max_delta_abs=0.050, max_delta_ratio=0.14),
        night_iso_noise_strength=_jitter_float(base.night_iso_noise_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.08, max_delta_abs=0.050, max_delta_ratio=0.16),
        night_light_warmth=_jitter_float(base.night_light_warmth, rng, minimum=0.0, maximum=1.0, sigma_abs=0.015, sigma_ratio=0.05, max_delta_abs=0.045, max_delta_ratio=0.12, zero_stays_zero=False),
        traffic_headlight_strength=_jitter_float(base.traffic_headlight_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.060, max_delta_ratio=0.16),
        traffic_headlight_source_x=_jitter_coordinate(base.traffic_headlight_source_x, rng),
        traffic_headlight_source_y=_jitter_coordinate(base.traffic_headlight_source_y, rng),
        traffic_headlight_target_x=_jitter_coordinate(base.traffic_headlight_target_x, rng),
        traffic_headlight_target_y=_jitter_coordinate(base.traffic_headlight_target_y, rng),
        traffic_headlight_1_warmth=_jitter_optional_unit(base.traffic_headlight_1_warmth, rng),
        traffic_headlight_1_r=_jitter_optional_unit(base.traffic_headlight_1_r, rng),
        traffic_headlight_1_g=_jitter_optional_unit(base.traffic_headlight_1_g, rng),
        traffic_headlight_1_b=_jitter_optional_unit(base.traffic_headlight_1_b, rng),
        traffic_headlight_1_cone=_jitter_float(base.traffic_headlight_1_cone, rng, minimum=0.02, maximum=2.5, sigma_abs=0.026, sigma_ratio=0.05, max_delta_abs=0.080, max_delta_ratio=0.12, zero_stays_zero=False),
        traffic_headlight_1_source_radius=_jitter_float(base.traffic_headlight_1_source_radius, rng, minimum=0.0, maximum=2.5, sigma_abs=0.016, sigma_ratio=0.07, max_delta_abs=0.060, max_delta_ratio=0.16),
        traffic_headlight_2_strength=_jitter_float(base.traffic_headlight_2_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.060, max_delta_ratio=0.16),
        traffic_headlight_2_warmth=_jitter_optional_unit(base.traffic_headlight_2_warmth, rng, allow_negative_sentinel=False),
        traffic_headlight_2_r=_jitter_optional_unit(base.traffic_headlight_2_r, rng),
        traffic_headlight_2_g=_jitter_optional_unit(base.traffic_headlight_2_g, rng),
        traffic_headlight_2_b=_jitter_optional_unit(base.traffic_headlight_2_b, rng),
        traffic_headlight_2_cone=_jitter_float(base.traffic_headlight_2_cone, rng, minimum=0.02, maximum=2.5, sigma_abs=0.026, sigma_ratio=0.05, max_delta_abs=0.080, max_delta_ratio=0.12, zero_stays_zero=False),
        traffic_headlight_2_source_radius=_jitter_float(base.traffic_headlight_2_source_radius, rng, minimum=0.0, maximum=2.5, sigma_abs=0.016, sigma_ratio=0.07, max_delta_abs=0.060, max_delta_ratio=0.16),
        traffic_headlight_2_source_x=_jitter_coordinate(base.traffic_headlight_2_source_x, rng),
        traffic_headlight_2_source_y=_jitter_coordinate(base.traffic_headlight_2_source_y, rng),
        traffic_headlight_2_target_x=_jitter_coordinate(base.traffic_headlight_2_target_x, rng),
        traffic_headlight_2_target_y=_jitter_coordinate(base.traffic_headlight_2_target_y, rng),
        traffic_headlight_3_strength=_jitter_float(base.traffic_headlight_3_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.060, max_delta_ratio=0.16),
        traffic_headlight_3_warmth=_jitter_optional_unit(base.traffic_headlight_3_warmth, rng, allow_negative_sentinel=False),
        traffic_headlight_3_r=_jitter_optional_unit(base.traffic_headlight_3_r, rng),
        traffic_headlight_3_g=_jitter_optional_unit(base.traffic_headlight_3_g, rng),
        traffic_headlight_3_b=_jitter_optional_unit(base.traffic_headlight_3_b, rng),
        traffic_headlight_3_cone=_jitter_float(base.traffic_headlight_3_cone, rng, minimum=0.02, maximum=2.5, sigma_abs=0.026, sigma_ratio=0.05, max_delta_abs=0.080, max_delta_ratio=0.12, zero_stays_zero=False),
        traffic_headlight_3_source_radius=_jitter_float(base.traffic_headlight_3_source_radius, rng, minimum=0.0, maximum=2.5, sigma_abs=0.016, sigma_ratio=0.07, max_delta_abs=0.060, max_delta_ratio=0.16),
        traffic_headlight_3_source_x=_jitter_coordinate(base.traffic_headlight_3_source_x, rng),
        traffic_headlight_3_source_y=_jitter_coordinate(base.traffic_headlight_3_source_y, rng),
        traffic_headlight_3_target_x=_jitter_coordinate(base.traffic_headlight_3_target_x, rng),
        traffic_headlight_3_target_y=_jitter_coordinate(base.traffic_headlight_3_target_y, rng),
        wet_mud_gloss_strength=_jitter_float(base.wet_mud_gloss_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.060, max_delta_ratio=0.16),
        flare_strength=_jitter_float(base.flare_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.055, max_delta_ratio=0.16),
        overexposure_strength=_jitter_float(base.overexposure_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.055, max_delta_ratio=0.16),
        dirt_streak_strength=_jitter_float(base.dirt_streak_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.055, max_delta_ratio=0.16),
        dirt_flow_strength=_jitter_float(base.dirt_flow_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.060, max_delta_ratio=0.16),
        dirt_flow_points=_jitter_int(base.dirt_flow_points, rng, minimum=0, maximum=MAX_DIRT_FLOW_POINTS, sigma_abs=2.0, sigma_ratio=0.06, max_delta_ratio=0.14),
        dirt_flow_mass_min=mass_min,
        dirt_flow_mass_max=mass_max,
        dirt_flow_splash_scale=_jitter_float(base.dirt_flow_splash_scale, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.06, max_delta_abs=0.055, max_delta_ratio=0.14, zero_stays_zero=False),
        dirt_flow_trail_length=_jitter_float(base.dirt_flow_trail_length, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.06, max_delta_abs=0.055, max_delta_ratio=0.14, zero_stays_zero=False),
        dirt_flow_humidity=_jitter_float(base.dirt_flow_humidity, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.06, max_delta_abs=0.055, max_delta_ratio=0.14, zero_stays_zero=False),
        dirt_flow_stickiness_min=stickiness_min,
        dirt_flow_stickiness_max=stickiness_max,
        dirt_flow_stickiness=(stickiness_min + stickiness_max) / 2.0,
        dirt_flow_air_angle=_jitter_float(base.dirt_flow_air_angle, rng, minimum=-75.0, maximum=75.0, sigma_abs=2.0, sigma_ratio=0.04, max_delta_abs=5.0, max_delta_ratio=0.10),
        dirt_flow_wind_strength=_jitter_float(base.dirt_flow_wind_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.018, sigma_ratio=0.06, max_delta_abs=0.055, max_delta_ratio=0.14, zero_stays_zero=False),
        dirt_flow_opacity_min=opacity_min,
        dirt_flow_opacity_max=opacity_max,
        dark_relief_strength=_jitter_float(base.dark_relief_strength, rng, minimum=0.0, maximum=3.0, sigma_abs=0.040, sigma_ratio=0.08, max_delta_abs=0.140, max_delta_ratio=0.16),
        dark_relief_light_angle=(_jitter_float(base.dark_relief_light_angle, rng, minimum=0.0, maximum=360.0, sigma_abs=2.5, sigma_ratio=0.02, max_delta_abs=7.0, max_delta_ratio=0.04, zero_stays_zero=False) % 360.0),
        light_normal_strength=_jitter_float(base.light_normal_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.060, max_delta_ratio=0.16),
        overhang_shadow_strength=_jitter_float(base.overhang_shadow_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.060, max_delta_ratio=0.16),
        overhang_shadow_depth=_jitter_float(base.overhang_shadow_depth, rng, minimum=0.0, maximum=0.60, sigma_abs=0.018, sigma_ratio=0.05, max_delta_abs=0.055, max_delta_ratio=0.12, zero_stays_zero=False),
        overhang_shadow_skew=_jitter_float(base.overhang_shadow_skew, rng, minimum=-1.0, maximum=1.0, sigma_abs=0.030, sigma_ratio=0.05, max_delta_abs=0.080, max_delta_ratio=0.14),
        plate_reflect_gradient_strength=_jitter_float(base.plate_reflect_gradient_strength, rng, minimum=0.0, maximum=2.0, sigma_abs=0.035, sigma_ratio=0.07, max_delta_abs=0.110, max_delta_ratio=0.15),
        plate_reflect_glare_strength=_jitter_float(base.plate_reflect_glare_strength, rng, minimum=0.0, maximum=2.0, sigma_abs=0.035, sigma_ratio=0.07, max_delta_abs=0.110, max_delta_ratio=0.15),
        plate_reflect_curve_strength=_jitter_float(base.plate_reflect_curve_strength, rng, minimum=0.0, maximum=2.0, sigma_abs=0.035, sigma_ratio=0.07, max_delta_abs=0.110, max_delta_ratio=0.15),
        blur_strength=_jitter_float(base.blur_strength, rng, minimum=0.0, maximum=1.0, sigma_abs=0.020, sigma_ratio=0.08, max_delta_abs=0.060, max_delta_ratio=0.16),
    )
    return jittered.normalized()


def _image_extensions() -> set[str]:
    return {str(ext).lower() for ext in CONFIG.IMAGE_EXTENSIONS}


def _load_dataset_config(dataset_dir: Path) -> dict:
    yaml_path = Path(dataset_dir) / "data.yaml"
    if not yaml_path.exists():
        return {}
    return safe_load_yaml(yaml_path)


def _parse_kpt_shape(config: dict) -> tuple[int, int]:
    raw = config.get("kpt_shape")
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return int(raw[0]), int(raw[1])
        except Exception:
            return 0, 0
    if isinstance(raw, str):
        digits = []
        for chunk in raw.replace("[", " ").replace("]", " ").replace(",", " ").split():
            try:
                digits.append(int(float(chunk)))
            except Exception:
                continue
        if len(digits) >= 2:
            return digits[0], digits[1]
    return 0, 0


def _coerce_names(config: dict) -> dict[int, str]:
    names = config.get("names", {})
    result: dict[int, str] = {}
    if isinstance(names, dict):
        for key, value in names.items():
            try:
                idx = int(key)
            except Exception:
                continue
            result[idx] = str(value)
    elif isinstance(names, list):
        for idx, value in enumerate(names):
            result[idx] = str(value)
    return result


def _dump_dataset_config(dataset_dir: Path, config: dict) -> None:
    yaml_path = Path(dataset_dir) / "data.yaml"
    if YAML_AVAILABLE and yaml is not None:
        yaml_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return

    lines: list[str] = []
    for key in ("path", "train", "val", "test", "nc"):
        if key in config:
            lines.append(f"{key}: {config[key]}")
    names = _coerce_names(config)
    if names:
        lines.append("names:")
        for idx in sorted(names):
            lines.append(f"  {idx}: {names[idx]}")
    if "kpt_shape" in config:
        lines.append(f"kpt_shape: {config['kpt_shape']}")
    if "flip_idx" in config:
        lines.append(f"flip_idx: {config['flip_idx']}")
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_yolo_dataset_class_names(dataset_dir: Path, names_by_index: dict[int, str]) -> tuple[bool, str]:
    """Update data.yaml class labels without touching images or labels."""
    dataset_dir = Path(dataset_dir)
    yaml_path = dataset_dir / "data.yaml"
    if not yaml_path.exists():
        return False, "Brak data.yaml, nie można zmienić nazw klas."

    updates = {
        int(idx): str(name or "").strip()
        for idx, name in dict(names_by_index or {}).items()
        if str(name or "").strip()
    }
    if not updates:
        return True, "Nazwy klas bez zmian."

    config = _load_dataset_config(dataset_dir)
    names = _coerce_names(config)
    if not names:
        nc = int(config.get("nc", max(updates.keys()) + 1) or 1)
        names = {idx: f"class_{idx}" for idx in range(nc)}

    for idx, name in updates.items():
        names[idx] = name

    config["names"] = {idx: names[idx] for idx in sorted(names)}
    config["nc"] = max(int(config.get("nc", 0) or 0), len(config["names"]))
    _dump_dataset_config(dataset_dir, config)
    return True, "Nazwy klas w data.yaml zostały zaktualizowane."


def _discover_train_items(dataset_dir: Path) -> list[tuple[Path, Path]]:
    image_dir = Path(dataset_dir) / "images" / "train"
    label_dir = Path(dataset_dir) / "labels" / "train"
    if not image_dir.exists() or not label_dir.exists():
        return []

    items: list[tuple[Path, Path]] = []
    for image_path in sorted(image_dir.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in _image_extensions():
            continue
        label_path = label_dir / f"{image_path.stem}.txt"
        if label_path.exists() and label_path.read_text(encoding="utf-8", errors="ignore").strip():
            items.append((image_path, label_path))
    return items


def _parse_yolo_label(label_path: Path, *, kpt_count: int, kpt_dim: int) -> list[YoloObject]:
    objects: list[YoloObject] = []
    try:
        lines = label_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return objects

    for raw_line in lines:
        tokens = str(raw_line or "").strip().split()
        if len(tokens) < 5:
            continue
        try:
            class_id = int(float(tokens[0]))
            bbox = [float(value) for value in tokens[1:5]]
            rest = [float(value) for value in tokens[5:]]
        except Exception:
            continue

        keypoints: list[tuple[float, float, float | None]] = []
        if kpt_count > 0 and kpt_dim >= 2:
            expected = kpt_count * kpt_dim
            if len(rest) < expected:
                continue
            for idx in range(kpt_count):
                offset = idx * kpt_dim
                visibility = rest[offset + 2] if kpt_dim >= 3 else None
                keypoints.append((rest[offset], rest[offset + 1], visibility))

        objects.append(
            YoloObject(
                class_id=class_id,
                bbox=[_clamp01(value) for value in bbox],
                keypoints=keypoints,
            )
        )
    return objects


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _format_float(value: float) -> str:
    return f"{_clamp01(value):.6f}"


def _rng_int(rng, low: int, high: int) -> int:
    try:
        return int(rng.randint(low, high))
    except Exception:
        return random.randint(low, high)


def _rng_float(rng, low: float, high: float) -> float:
    try:
        return float(rng.uniform(low, high))
    except Exception:
        return random.uniform(low, high)


def _apply_coarse_noise(image, profile: AugmentationProfile, rng) -> object:
    if np is None or profile.noise_strength <= 0:
        return image

    try:
        height, width = image.shape[:2]
        grain = max(1, int(profile.noise_grain_size or 1))
        noise_h = max(1, int((height + grain - 1) / grain))
        noise_w = max(1, int((width + grain - 1) / grain))
        std = max(1.0, float(profile.noise_strength) * 255.0)
        try:
            seed = _rng_int(rng, 0, 2**31 - 1)
            noise_rng = np.random.default_rng(seed)
            noise = noise_rng.normal(0.0, std, size=(noise_h, noise_w, 1)).astype("float32")
        except Exception:
            noise = np.random.normal(0.0, std, size=(noise_h, noise_w, 1)).astype("float32")
        if grain > 1 and cv2 is not None:
            noise = cv2.resize(noise, (width, height), interpolation=cv2.INTER_NEAREST)
            if len(noise.shape) == 2:
                noise = noise[:, :, None]
        else:
            noise = noise[:height, :width]
        out = image.astype("float32") + noise
        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _apply_night_effect(image, profile: AugmentationProfile) -> object:
    if np is None or profile.night_strength <= 0:
        return image

    try:
        strength = max(0.0, min(1.0, float(profile.night_strength)))
        night = math.pow(strength, 0.82)
        out = image.astype("float32") / 255.0
        luma = (
            out[:, :, 0] * 0.114
            + out[:, :, 1] * 0.587
            + out[:, :, 2] * 0.299
        )
        channel_max = np.max(out, axis=2)
        channel_min = np.min(out, axis=2)
        chroma_mask = np.clip((channel_max - channel_min) / np.maximum(channel_max, 0.08), 0.0, 1.0)
        chroma_mask = chroma_mask * chroma_mask * (3.0 - 2.0 * chroma_mask)
        # Fixed camera-like response is easier to understand than exposing a
        # user-facing luminance range. Bright surfaces still react first, but
        # the user controls the effect through night, light, bloom and ISO.
        bright_mask = np.clip((luma - 0.42) / 0.46, 0.0, 1.0)
        bright_mask = bright_mask * bright_mask * (3.0 - 2.0 * bright_mask)

        light_strength = max(0.0, min(1.0, float(getattr(profile, "night_light_strength", 0.0) or 0.0)))
        bloom_strength = max(0.0, min(1.0, float(getattr(profile, "night_bloom_strength", 0.0) or 0.0)))
        iso_strength = max(0.0, min(1.0, float(getattr(profile, "night_iso_noise_strength", 0.0) or 0.0)))
        warmth = max(0.0, min(1.0, float(getattr(profile, "night_light_warmth", 0.35) if getattr(profile, "night_light_warmth", None) is not None else 0.35)))
        # Keep the base night exposure independent from R1/R2/R3 headlights.
        # Headlights are rendered later by _apply_traffic_headlight_effect, so
        # duplicating them here makes the night slider look weak and leaks
        # colored light back into the darkened scene.
        active_night_headlight = None
        manual_night_color = None
        camera_axis = max(0.0, min(1.0, float(getattr(profile, "light_normal_strength", 0.0) or 0.0)))
        iso_strength = max(iso_strength, night * 0.24)

        # Night camera response: dim the scene, crush midtones, but leave room
        # for retro-reflective highlights to bloom back into the image.
        ambient = np.array([0.020, 0.008, -0.050], dtype="float32")
        color_darken = chroma_mask * (1.0 - bright_mask * 0.35)
        darken = np.clip(0.34 * night + 0.52 * night * bright_mask + 0.30 * night * color_darken, 0.0, 0.96)
        out *= 1.0 - darken[:, :, None]
        gamma = 1.0 + 1.10 * night
        out = np.power(np.clip(out, 0.0, 1.0), gamma)
        luma_after_darken = np.clip(
            out[:, :, 0] * 0.114
            + out[:, :, 1] * 0.587
            + out[:, :, 2] * 0.299,
            0.0,
            1.0,
        )
        cool_gray = np.empty_like(out)
        cool_gray[:, :, 0] = luma_after_darken * 1.08 + 0.010 * night
        cool_gray[:, :, 1] = luma_after_darken * 0.94 + 0.004 * night
        cool_gray[:, :, 2] = luma_after_darken * 0.66
        desaturate = np.clip(0.34 * night + 0.44 * night * chroma_mask + 0.12 * night * bright_mask, 0.0, 0.88)
        out = out * (1.0 - desaturate[:, :, None]) + cool_gray * desaturate[:, :, None]
        out += ambient * (0.50 * night + 0.34 * night * (1.0 - bright_mask[:, :, None]))

        height, width = image.shape[:2]
        if light_strength > 0.001 and height > 1 and width > 1:
            yy, xx = np.mgrid[0:height, 0:width].astype("float32")
            nx = (xx / max(1.0, float(width - 1))) - 0.5
            ny = (yy / max(1.0, float(height - 1))) - 0.5
            ux = nx + 0.5
            uy = ny + 0.5
            angle = math.radians(float(getattr(profile, "dark_relief_light_angle", 135.0) or 0.0) % 360.0)
            if active_night_headlight is None:
                light_x = 0.0
                light_y = 0.0
            else:
                light_x = math.cos(angle)
                light_y = -math.sin(angle)
            linear = np.clip(0.50 + (nx * light_x + ny * light_y) * (0.72 + 0.48 * camera_axis), 0.0, 1.0)
            center_x = 0.18 * light_x * (0.35 + 0.65 * light_strength)
            center_y = 0.18 * light_y * (0.35 + 0.65 * light_strength)
            radial = np.exp(
                -(
                    ((nx - center_x) ** 2) / (0.14 + 0.20 * camera_axis)
                    + ((ny - center_y) ** 2) / (0.12 + 0.18 * camera_axis)
                )
            )
            if active_night_headlight is not None:
                source_attr_x, source_attr_y = active_night_headlight["source_attrs"]
                target_attr_x, target_attr_y = active_night_headlight["target_attrs"]
                source_x = float(getattr(profile, source_attr_x, -1.0) if getattr(profile, source_attr_x, None) is not None else -1.0)
                source_y = float(getattr(profile, source_attr_y, -1.0) if getattr(profile, source_attr_y, None) is not None else -1.0)
                target_x = float(getattr(profile, target_attr_x, -1.0) if getattr(profile, target_attr_x, None) is not None else -1.0)
                target_y = float(getattr(profile, target_attr_y, -1.0) if getattr(profile, target_attr_y, None) is not None else -1.0)
            else:
                # With no active R1/R2/R3 reflector there is no hidden
                # directional cone; night light stays neutral and centered.
                source_x = source_y = target_x = target_y = -1.0
            if not (0.0 <= source_x <= 1.0 and 0.0 <= source_y <= 1.0 and 0.0 <= target_x <= 1.0 and 0.0 <= target_y <= 1.0):
                source_x = 0.50 - light_x * (0.82 + 0.34 * light_strength)
                source_y = 0.50 - light_y * (0.82 + 0.34 * light_strength)
                target_x = 0.50
                target_y = 0.48
            source = np.array([source_x, source_y], dtype="float32")
            target = np.array([target_x, target_y], dtype="float32")
            direction = target - source
            norm = float(np.linalg.norm(direction) or 1.0)
            direction = direction / norm
            perp = np.array([-float(direction[1]), float(direction[0])], dtype="float32")
            rel_x = ux - float(source[0])
            rel_y = uy - float(source[1])
            along = rel_x * float(direction[0]) + rel_y * float(direction[1])
            side = rel_x * float(perp[0]) + rel_y * float(perp[1])
            beam_width = 0.16 + 0.22 * light_strength + 0.10 * camera_axis
            beam_length = 0.64 + 0.62 * light_strength
            cone = np.exp(-((side / max(0.035, beam_width)) ** 2 + ((along - norm * 0.72) / beam_length) ** 2)).astype("float32")
            cone *= np.clip(along / max(0.001, norm * 0.18), 0.0, 1.0)
            hotspot = np.exp(-(((ux - target_x) / (0.11 + 0.12 * light_strength)) ** 2 + ((uy - target_y) / (0.07 + 0.10 * light_strength)) ** 2)).astype("float32")
            light_field = np.clip(np.maximum(linear * 0.28 + radial * 0.62, cone * 0.95 + hotspot * 0.36), 0.0, 1.0)
            cold = np.array([1.12, 1.06, 0.96], dtype="float32")
            warm = np.array([0.78, 1.02, 1.28], dtype="float32")
            light_color = manual_night_color if manual_night_color is not None else cold * (1.0 - warmth) + warm * warmth

            retro = np.clip(bright_mask * light_field, 0.0, 1.0)
            out += light_field[:, :, None] * light_color * (0.05 + 0.22 * light_strength) * strength
            out += retro[:, :, None] * light_color * (0.14 + 0.54 * light_strength) * strength

            if cv2 is not None and bloom_strength > 0.001:
                bloom_source = np.clip(retro + (bright_mask * light_field * 0.22), 0.0, 1.0)
                sigma = max(1.2, min(width, height) * (0.010 + 0.035 * bloom_strength))
                bloom = cv2.GaussianBlur(bloom_source.astype("float32"), (0, 0), sigmaX=sigma, sigmaY=sigma)
                bloom_percentile = float(np.percentile(bloom, 99.2) or 0.0)
                if bloom_percentile > 0:
                    bloom = np.clip(bloom / bloom_percentile, 0.0, 1.0)
                out += bloom[:, :, None] * light_color * (0.10 + 0.40 * bloom_strength) * strength

        if iso_strength > 0.001:
            rng = np.random.default_rng(int(getattr(profile, "seed", 42) or 42) + 1931)
            luma_after = np.clip(out[:, :, 0] * 0.114 + out[:, :, 1] * 0.587 + out[:, :, 2] * 0.299, 0.0, 1.0)
            noise_scale = (0.010 + 0.065 * iso_strength) * (0.45 + 0.90 * (1.0 - luma_after))
            mono = rng.normal(0.0, noise_scale, size=luma_after.shape).astype("float32")
            chroma = rng.normal(0.0, noise_scale[:, :, None] * 0.45, size=out.shape).astype("float32")
            out += mono[:, :, None] + chroma

        return np.clip(out * 255.0, 0, 255).astype("uint8")
    except Exception:
        return image


def _apply_overexposure_effect(image, profile: AugmentationProfile, rng) -> object:
    if np is None or profile.overexposure_strength <= 0:
        return image

    try:
        strength = max(0.0, min(1.0, float(profile.overexposure_strength)))
        height, width = image.shape[:2]
        out = image.astype("float32")
        out += 42.0 * strength

        if cv2 is not None and height > 8 and width > 8:
            mask = np.zeros((height, width), dtype="float32")
            center_x = _rng_int(rng, int(width * 0.18), max(int(width * 0.82), int(width * 0.18) + 1))
            center_y = _rng_int(rng, int(height * 0.12), max(int(height * 0.55), int(height * 0.12) + 1))
            axis_x = max(8, int(width * (0.12 + 0.26 * strength)))
            axis_y = max(8, int(height * (0.08 + 0.18 * strength)))
            cv2.ellipse(mask, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, 1.0, -1)
            kernel = max(3, int(min(width, height) * (0.08 + 0.08 * strength)))
            if kernel % 2 == 0:
                kernel += 1
            mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)
            if float(mask.max() or 0.0) > 0:
                mask = mask / float(mask.max())
            out += mask[:, :, None] * (115.0 * strength)

        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _rain_drop_direction(profile: AugmentationProfile, average_drop_size: float) -> tuple[float, float]:
    wind_strength = max(0.0, min(1.0, float(profile.dirt_flow_wind_strength if profile.dirt_flow_wind_strength is not None else 0.0)))
    wind_angle = math.radians(max(-80.0, min(80.0, float(profile.dirt_flow_air_angle or 0.0))))
    drop_wind_sensitivity = max(0.20, 1.0 - 0.72 * average_drop_size)
    intensity_wind_sensitivity = max(0.65, 1.0 - 0.22 * max(0.0, min(1.0, float(profile.rain_strength or 0.0))))
    wind_x = math.sin(wind_angle) * wind_strength * (0.35 + 1.95 * drop_wind_sensitivity * intensity_wind_sensitivity)
    direction_norm = max(0.001, math.sqrt(wind_x * wind_x + 1.0))
    return wind_x / direction_norm, 1.0 / direction_norm


def _build_rain_edge_response(image, step_x: float, step_y: float):
    if np is None or cv2 is None:
        return None
    try:
        height, width = image.shape[:2]
        if width <= 3 or height <= 3:
            return None
        if width * height > MAX_RAIN_EDGE_PIXELS:
            scale = math.sqrt(MAX_RAIN_EDGE_PIXELS / float(width * height))
            small_w = max(4, int(round(width * scale)))
            small_h = max(4, int(round(height * scale)))
            small = cv2.resize(image, (small_w, small_h), interpolation=cv2.INTER_AREA)
            small_response = _build_rain_edge_response(small, step_x, step_y)
            if not small_response:
                return None
            gate = cv2.resize(small_response["gate"], (width, height), interpolation=cv2.INTER_LINEAR)
            reflect_x = cv2.resize(small_response["reflect_x"], (width, height), interpolation=cv2.INTER_LINEAR)
            reflect_y = cv2.resize(small_response["reflect_y"], (width, height), interpolation=cv2.INTER_LINEAR)
            reflect_norm = np.sqrt(reflect_x * reflect_x + reflect_y * reflect_y) + 1e-6
            return {
                "gate": gate,
                "reflect_x": reflect_x / reflect_norm,
                "reflect_y": reflect_y / reflect_norm,
            }
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype("float32") / 255.0
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = cv2.magnitude(grad_x, grad_y)
        normal_x = grad_x / (grad_mag + 1e-6)
        normal_y = grad_y / (grad_mag + 1e-6)
        edge_strength = np.clip((grad_mag - 0.035) / 0.26, 0.0, 1.0)
        # Edge normals parallel to the drop velocity mean the edge line is a pseudo-surface
        # positioned across the falling rain, so it is a good candidate for impact mist.
        edge_alignment = np.abs((normal_x * step_x) + (normal_y * step_y))
        edge_gate = np.clip(edge_strength * (edge_alignment ** 2.35), 0.0, 1.0)
        dot = (step_x * normal_x) + (step_y * normal_y)
        reflect_x = step_x - 2.0 * dot * normal_x
        reflect_y = step_y - 2.0 * dot * normal_y
        reflect_norm = np.sqrt(reflect_x * reflect_x + reflect_y * reflect_y) + 1e-6
        return {
            "gate": cv2.GaussianBlur(edge_gate, (0, 0), sigmaX=0.55, sigmaY=0.55),
            "reflect_x": reflect_x / reflect_norm,
            "reflect_y": reflect_y / reflect_norm,
        }
    except Exception:
        return None


def _build_rain_edge_gate(image, step_x: float, step_y: float):
    response = _build_rain_edge_response(image, step_x, step_y)
    if not response:
        return None
    return response.get("gate")


def build_rain_edge_debug_mask(image, profile: AugmentationProfile):
    """Return a preview-only pseudo-surface mask; it is never written to datasets."""
    profile = (profile or AugmentationProfile()).normalized()
    if np is None or cv2 is None or profile.rain_strength <= 0:
        return None
    legacy_drop_size = max(0.0, min(1.0, float(profile.rain_drop_size if profile.rain_drop_size is not None else 0.35)))
    drop_size_min = max(0.0, min(1.0, float(getattr(profile, "rain_drop_size_min", legacy_drop_size) if getattr(profile, "rain_drop_size_min", None) is not None else legacy_drop_size)))
    drop_size_max = max(0.0, min(1.0, float(getattr(profile, "rain_drop_size_max", legacy_drop_size) if getattr(profile, "rain_drop_size_max", None) is not None else legacy_drop_size)))
    if drop_size_min > drop_size_max:
        drop_size_min, drop_size_max = drop_size_max, drop_size_min
    step_x, step_y = _rain_drop_direction(profile, (drop_size_min + drop_size_max) / 2.0)
    return _build_rain_edge_gate(image, step_x, step_y)


def _apply_rain_lens_distortion(image, rain_mask, lens_strength: float):
    if np is None or cv2 is None or rain_mask is None or lens_strength <= 0:
        return image
    try:
        height, width = image.shape[:2]
        if width <= 3 or height <= 3:
            return image
        if width * height > MAX_RAIN_LENS_PIXELS:
            scale = math.sqrt(MAX_RAIN_LENS_PIXELS / float(width * height))
            small_w = max(4, int(round(width * scale)))
            small_h = max(4, int(round(height * scale)))
            small_image = cv2.resize(image, (small_w, small_h), interpolation=cv2.INTER_AREA)
            small_mask = cv2.resize(rain_mask, (small_w, small_h), interpolation=cv2.INTER_AREA)
            small_result = _apply_rain_lens_distortion(small_image, small_mask, lens_strength)
            return cv2.resize(small_result, (width, height), interpolation=cv2.INTER_LINEAR)
        lens = cv2.GaussianBlur(np.clip(rain_mask.astype("float32"), 0.0, 1.0), (0, 0), sigmaX=0.55, sigmaY=0.55)
        lens = np.clip(lens * (0.55 + 0.85 * lens_strength), 0.0, 1.0)
        if float(lens.max() or 0.0) <= 0.001:
            return image
        grad_x = cv2.Sobel(lens, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(lens, cv2.CV_32F, 0, 1, ksize=3)
        grid_x, grid_y = np.meshgrid(np.arange(width, dtype="float32"), np.arange(height, dtype="float32"))
        displacement = 1.2 + 6.8 * lens_strength
        map_x = grid_x + grad_x * displacement
        map_y = grid_y + grad_y * displacement
        distorted = cv2.remap(image, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT101)
        alpha = np.clip(lens * (0.18 + 0.62 * lens_strength), 0.0, 0.78)
        out = image.astype("float32") * (1.0 - alpha[:, :, None]) + distorted.astype("float32") * alpha[:, :, None]
        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _rng_gauss(rng, mean: float, sigma: float) -> float:
    try:
        return float(rng.gauss(mean, sigma))
    except Exception:
        return random.gauss(mean, sigma)


def _iter_stream_rain_anchors(
    width: int,
    height: int,
    count: int,
    margin_x: int,
    rng,
    *,
    step_x: float,
    step_y: float,
    strength: float,
    average_drop_size: float,
) -> list[tuple[int, int]]:
    """Return natural rain anchors arranged in stochastic streaks, not a grid."""
    if count <= 0 or width <= 0 or height <= 0:
        return []
    margin_x = max(0, int(margin_x or 0))
    direction_norm = max(0.001, math.sqrt(step_x * step_x + step_y * step_y))
    dir_x = float(step_x) / direction_norm
    dir_y = float(step_y) / direction_norm
    perp_x = -dir_y
    perp_y = dir_x
    center_x = (float(width) - 1.0) / 2.0
    center_y = (float(height) - 1.0) / 2.0
    span_w = float(width + 2 * margin_x)
    diagonal = max(1.0, math.hypot(span_w, float(height)))
    normal_limit = span_w * 0.49
    tangent_limit = max(float(height) * 0.62, diagonal * 0.36)
    strength = max(0.0, min(1.0, float(strength)))
    average_drop_size = max(0.0, min(1.0, float(average_drop_size)))

    stream_share = max(0.52, min(0.86, 0.66 + 0.18 * strength - 0.08 * average_drop_size))
    collision_share = max(0.03, min(0.14, 0.045 + 0.08 * strength + 0.025 * (1.0 - average_drop_size)))
    stream_drop_count = max(0, min(count, int(round(count * stream_share))))
    collision_count = max(0, min(count - stream_drop_count, int(round(count * collision_share))))
    background_count = max(0, count - stream_drop_count - collision_count)

    stream_count = max(
        3,
        min(
            max(3, stream_drop_count),
            int(round(math.sqrt(max(1.0, float(stream_drop_count))) * (0.65 + 1.15 * strength))),
        ),
    )
    streams = []
    for _stream in range(stream_count):
        streams.append(
            {
                "offset": _rng_float(rng, -normal_limit, normal_limit),
                "width": span_w * _rng_float(
                    rng,
                    0.004 + 0.006 * average_drop_size,
                    0.018 + 0.030 * (1.0 - average_drop_size),
                ),
                "phase": _rng_float(rng, 0.0, math.tau),
                "freq": _rng_float(rng, 0.65, 2.20),
                "weight": _rng_float(rng, 0.45, 1.85) ** 1.35,
            }
        )
    weight_sum = sum(float(item["weight"]) for item in streams) or 1.0
    cumulative = []
    running = 0.0
    for item in streams:
        running += float(item["weight"]) / weight_sum
        cumulative.append(running)

    def choose_stream():
        value = _rng_float(rng, 0.0, 1.0)
        for index, threshold in enumerate(cumulative):
            if value <= threshold:
                return streams[index]
        return streams[-1]

    def to_image(tangent: float, normal: float) -> tuple[int, int]:
        x = center_x + dir_x * tangent + perp_x * normal
        y = center_y + dir_y * tangent + perp_y * normal
        return int(round(x)), int(round(y))

    def clamp_anchor(x: int, y: int) -> tuple[int, int]:
        return (
            max(-margin_x, min(width - 1 + margin_x, int(x))),
            max(0, min(height - 1, int(y))),
        )

    anchors: list[tuple[int, int]] = []
    for _drop in range(stream_drop_count):
        stream = choose_stream()
        tangent = _rng_float(rng, -tangent_limit, tangent_limit)
        bend = math.sin((tangent / diagonal) * math.tau * float(stream["freq"]) + float(stream["phase"]))
        normal = (
            float(stream["offset"])
            + bend * float(stream["width"]) * _rng_float(rng, 0.10, 0.72)
            + _rng_gauss(rng, 0.0, max(0.45, float(stream["width"])))
        )
        anchors.append(clamp_anchor(*to_image(tangent, normal)))

    for _drop in range(collision_count):
        if anchors:
            base_x, base_y = anchors[_rng_int(rng, 0, len(anchors) - 1)]
        else:
            base_x = _rng_int(rng, -margin_x, max(1, width - 1 + margin_x))
            base_y = _rng_int(rng, 0, max(1, height - 1))
        radius = _rng_float(rng, 1.2, 6.5 + 8.0 * average_drop_size)
        angle = _rng_float(rng, 0.0, math.tau)
        # Collision neighbours are close enough to look like interacting drops,
        # but not so close that the mask grows into a single snowball blob.
        offset_x = math.cos(angle) * radius + dir_x * _rng_float(rng, -2.8, 2.8)
        offset_y = math.sin(angle) * radius + dir_y * _rng_float(rng, -2.8, 2.8)
        anchors.append(clamp_anchor(int(round(base_x + offset_x)), int(round(base_y + offset_y))))

    for _drop in range(background_count):
        # Background drops break the stream pattern and keep light rain from
        # looking like a set of artificial bands.
        anchors.append(
            (
                _rng_int(rng, -margin_x, max(1, width - 1 + margin_x)),
                _rng_int(rng, 0, max(1, height - 1)),
            )
        )

    if len(anchors) > count:
        anchors = anchors[:count]
    while len(anchors) < count:
        anchors.append(
            (
                _rng_int(rng, -margin_x, max(1, width - 1 + margin_x)),
                _rng_int(rng, 0, max(1, height - 1)),
            )
        )
    for index in range(len(anchors) - 1, 0, -1):
        swap_index = _rng_int(rng, 0, index)
        anchors[index], anchors[swap_index] = anchors[swap_index], anchors[index]
    return anchors


def _apply_rain_effect(image, profile: AugmentationProfile, rng, *, return_mask: bool = False) -> object:
    if np is None or cv2 is None or profile.rain_strength <= 0:
        return (image, None) if return_mask else image

    try:
        strength = max(0.0, min(1.0, float(profile.rain_strength)))
        drop_size_min = max(0.0, min(1.0, float(getattr(profile, "rain_drop_size_min", profile.rain_drop_size) if getattr(profile, "rain_drop_size_min", None) is not None else profile.rain_drop_size)))
        drop_size_max = max(0.0, min(1.0, float(getattr(profile, "rain_drop_size_max", profile.rain_drop_size) if getattr(profile, "rain_drop_size_max", None) is not None else profile.rain_drop_size)))
        if drop_size_min > drop_size_max:
            drop_size_min, drop_size_max = drop_size_max, drop_size_min
        average_drop_size = (drop_size_min + drop_size_max) / 2.0
        vector_field_strength = max(0.0, min(1.0, float(getattr(profile, "rain_vector_field_strength", 0.0) or 0.0)))
        vortex_strength = max(0.0, min(1.0, float(getattr(profile, "rain_vortex_strength", 0.0) or 0.0)))
        rain_alpha = max(0.0, min(1.0, float(getattr(profile, "rain_alpha", 0.22) if getattr(profile, "rain_alpha", None) is not None else 0.22)))
        lens_strength = max(0.0, min(1.0, float(getattr(profile, "rain_lens_strength", 0.0) or 0.0)))
        edge_mist_strength = max(0.0, min(1.0, float(getattr(profile, "rain_edge_mist_strength", 0.0) or 0.0)))
        edge_mist_radius = max(0.0, min(1.0, float(getattr(profile, "rain_edge_mist_radius", 0.45) if getattr(profile, "rain_edge_mist_radius", None) is not None else 0.45)))
        wind_strength = max(0.0, min(1.0, float(profile.dirt_flow_wind_strength if profile.dirt_flow_wind_strength is not None else 0.0)))
        height, width = image.shape[:2]
        size_density = 1.55 - 0.68 * average_drop_size
        # Keep the density slider useful across the whole range. The first
        # version hit a hard cap too early, while the next one saturated the
        # rain mask near 0.8. This keeps growth visible without turning rain
        # into a uniform translucent sheet.
        density_load = 10.0 + 220.0 * strength + 4600.0 * (strength ** 1.75)
        drops = int(max(1, (width * height / 28000.0) * density_load * size_density))
        pixel_drop_cap = int(max(5000, min(MAX_RAIN_DROPS, (width * height) / 2.5)))
        drops = min(drops, pixel_drop_cap)
        base_length = 1.2 + 4.0 * strength + 6.0 * wind_strength
        overlay = image.copy()
        color = (
            int(145 + 34 * strength + 28 * average_drop_size),
            int(150 + 36 * strength + 28 * average_drop_size),
            int(158 + 40 * strength + 28 * average_drop_size),
        )
        step_x, step_y = _rain_drop_direction(profile, average_drop_size)
        max_drop_length_base = base_length * (0.18 + 1.35 * drop_size_max) + 12.0 * drop_size_max
        max_thickness = max(1, int(round(0.55 + 5.8 * (drop_size_max ** 1.45) + 1.25 * strength)))
        max_slant = int(math.ceil(abs(step_x * max_drop_length_base * 1.28))) + max_thickness + 3
        rain_anchors = _iter_stream_rain_anchors(
            width,
            height,
            drops,
            max_slant,
            rng,
            step_x=step_x,
            step_y=step_y,
            strength=strength,
            average_drop_size=average_drop_size,
        )
        edge_response = None
        edge_gate = None
        if edge_mist_strength > 0.001:
            edge_response = _build_rain_edge_response(image, step_x, step_y)
            if edge_response:
                edge_gate = edge_response.get("gate")
        vortices = []
        if vortex_strength > 0.001 and width > 4 and height > 4:
            vortex_count = max(1, min(9, int(round(1 + 5 * vortex_strength + 2 * strength))))
            vortex_scale = max(12.0, min(float(width), float(height)) * (0.16 + 0.18 * vortex_strength))
            for _vortex_index in range(vortex_count):
                radius = vortex_scale * _rng_float(rng, 0.72, 1.55)
                spin = _rng_float(rng, 0.75, 1.85) * vortex_strength
                if _rng_float(rng, 0.0, 1.0) < 0.5:
                    spin = -spin
                vortices.append(
                    (
                        _rng_float(rng, -0.08 * width, 1.08 * width),
                        _rng_float(rng, -0.05 * height, 1.05 * height),
                        max(8.0, radius),
                        spin,
                    )
                )
        light_strength = max(0.0, min(1.0, float(profile.dark_relief_strength or 0.0)))
        light_normal = max(0.0, min(1.0, float(profile.light_normal_strength or 0.0)))
        light_angle = math.radians(float(profile.dark_relief_light_angle or 0.0) % 360.0)
        light_dir_x = math.cos(light_angle)
        light_dir_y = -math.sin(light_angle)
        gloss_strength = max(
            0.0,
            min(
                1.0,
                strength
                * (0.12 + 0.62 * light_strength + 0.34 * light_normal)
                * (0.55 + 0.45 * average_drop_size),
            ),
        )
        gloss_probability = max(0.0, min(0.68, 0.08 + 0.44 * gloss_strength + 0.16 * average_drop_size))
        needs_rain_mask = bool(return_mask or lens_strength > 0.001)
        rain_mask = np.zeros((height, width), dtype="float32") if needs_rain_mask else None
        gloss_mask = np.zeros((height, width), dtype="float32") if gloss_strength > 0.015 else None
        for anchor_x, anchor_y in rain_anchors:
            local_drop_size = _rng_float(rng, drop_size_min, drop_size_max)
            local_length_base = base_length * (0.18 + 1.35 * local_drop_size) + 12.0 * local_drop_size
            local_thickness = max(1, int(round(0.55 + 5.8 * (local_drop_size ** 1.45) + 1.25 * strength)))
            x1 = anchor_x
            y1 = anchor_y
            local_length = local_length_base * _rng_float(rng, 0.72, 1.28)
            local_step_x = step_x
            local_step_y = step_y
            if vector_field_strength > 0.001:
                nx = x1 / max(1.0, float(width))
                ny = y1 / max(1.0, float(height))
                phase_jitter = _rng_float(rng, -0.18, 0.18)
                field_a = math.sin((nx * 3.1 + ny * 1.7) * math.tau + phase_jitter)
                field_b = math.cos((nx * 1.2 - ny * 2.6) * math.tau - phase_jitter)
                curl = (field_a * 0.68 + field_b * 0.32) * vector_field_strength
                local_step_x = step_x + curl * (0.45 + 1.15 * (1.0 - local_drop_size))
                local_step_y = max(0.16, step_y + field_b * vector_field_strength * 0.12)
            if vortices:
                vortex_x = 0.0
                vortex_y = 0.0
                for center_x, center_y, radius, spin in vortices:
                    rel_x = (x1 - center_x) / radius
                    rel_y = (y1 - center_y) / radius
                    dist2 = rel_x * rel_x + rel_y * rel_y
                    if dist2 > 5.5:
                        continue
                    falloff = math.exp(-dist2 * 1.35)
                    vortex_x += -rel_y * spin * falloff
                    vortex_y += rel_x * spin * falloff * 0.42
                if abs(vortex_x) > 0.0001 or abs(vortex_y) > 0.0001:
                    small_drop_gain = 0.55 + 1.35 * (1.0 - local_drop_size)
                    local_step_x += vortex_x * small_drop_gain
                    local_step_y = max(0.10, local_step_y + vortex_y * small_drop_gain)
                    local_length *= max(0.36, 1.0 + 0.18 * vortex_x)
            if vector_field_strength > 0.001 or vortices:
                local_norm = max(0.001, math.sqrt(local_step_x * local_step_x + local_step_y * local_step_y))
                local_step_x /= local_norm
                local_step_y /= local_norm
            if vector_field_strength > 0.001:
                local_length *= max(0.38, 1.0 + vector_field_strength * 0.24 * field_a)
            x2 = int(round(x1 + local_step_x * local_length))
            y2 = int(round(y1 + local_step_y * local_length))
            cv2.line(overlay, (x1, y1), (x2, y2), color, local_thickness, lineType=cv2.LINE_AA)
            if rain_mask is not None:
                cv2.line(rain_mask, (x1, y1), (x2, y2), 1.0, max(1, local_thickness), lineType=cv2.LINE_AA)
            if local_drop_size > 0.42:
                head_t = _rng_float(rng, 0.10, 0.42)
                cx = int(round(x1 + local_step_x * local_length * head_t))
                cy = int(round(y1 + local_step_y * local_length * head_t))
                axis_major = max(local_thickness + 1, int(round(2.0 + 5.2 * local_drop_size)))
                axis_minor = max(1, int(round(0.85 + 2.4 * local_drop_size)))
                angle_deg = math.degrees(math.atan2(local_step_y, local_step_x))
                cv2.ellipse(
                    overlay,
                    (cx, cy),
                    (axis_major, axis_minor),
                    angle_deg,
                    0,
                    360,
                    color,
                    -1,
                    lineType=cv2.LINE_AA,
                )
                if rain_mask is not None:
                    cv2.ellipse(
                        rain_mask,
                        (cx, cy),
                        (axis_major, axis_minor),
                        angle_deg,
                        0,
                        360,
                        1.0,
                        -1,
                        lineType=cv2.LINE_AA,
                    )
            if gloss_mask is not None and _rng_float(rng, 0.0, 1.0) <= gloss_probability:
                highlight_t = _rng_float(rng, 0.12, 0.52)
                hx = x1 + local_step_x * local_length * highlight_t - light_dir_x * _rng_float(rng, 0.8, 2.8 + 3.0 * local_drop_size)
                hy = y1 + local_step_y * local_length * highlight_t - light_dir_y * _rng_float(rng, 0.8, 2.8 + 3.0 * local_drop_size)
                h_len = max(1.0, local_length * _rng_float(rng, 0.10, 0.26) * (0.55 + 0.75 * local_drop_size))
                h_thick = max(1, int(round(local_thickness * _rng_float(rng, 0.55, 0.95))))
                h_alpha = _rng_float(rng, 0.36, 0.94) * gloss_strength
                hp1 = (
                    int(round(hx - local_step_x * h_len * 0.5)),
                    int(round(hy - local_step_y * h_len * 0.5)),
                )
                hp2 = (
                    int(round(hx + local_step_x * h_len * 0.5)),
                    int(round(hy + local_step_y * h_len * 0.5)),
                )
                cv2.line(gloss_mask, hp1, hp2, h_alpha, h_thick, lineType=cv2.LINE_AA)
                if local_drop_size > 0.35:
                    radius = max(1, int(round(1.0 + 2.2 * local_drop_size + 0.8 * light_normal)))
                    cv2.circle(gloss_mask, (int(round(hx)), int(round(hy))), radius, h_alpha * 0.72, -1, lineType=cv2.LINE_AA)
        alpha = max(0.0, min(0.65, rain_alpha))
        if rain_mask is not None and rain_mask.size:
            rain_mask = cv2.GaussianBlur(rain_mask, (0, 0), sigmaX=0.22 + 0.35 * average_drop_size, sigmaY=0.22 + 0.35 * average_drop_size)
            rain_mask = np.clip(rain_mask * (0.48 + 0.72 * strength + 0.36 * average_drop_size), 0.0, 1.0)
        lens_base = _apply_rain_lens_distortion(image, rain_mask, lens_strength) if rain_mask is not None else image
        result = cv2.addWeighted(overlay, alpha, lens_base, 1.0 - alpha, 0)
        if gloss_mask is not None and gloss_mask.size:
            gloss_mask = cv2.GaussianBlur(
                gloss_mask,
                (0, 0),
                sigmaX=0.18 + 0.42 * average_drop_size,
                sigmaY=0.18 + 0.36 * average_drop_size,
            )
            gloss_mask = np.clip(gloss_mask * (0.72 + 0.58 * light_normal), 0.0, 1.0)
            out = result.astype("float32")
            tint = np.array([245.0, 250.0, 255.0], dtype="float32")
            screen = out + (tint - out) * gloss_mask[:, :, None]
            out = out * (1.0 - gloss_mask[:, :, None] * 0.10) + screen * (gloss_mask[:, :, None] * 0.68)
            result = np.clip(out, 0, 255).astype("uint8")
        if edge_gate is not None:
            mist_scale = 1.0
            mist_width = width
            mist_height = height
            mist_gate = edge_gate
            reflect_x = edge_response.get("reflect_x") if edge_response else None
            reflect_y = edge_response.get("reflect_y") if edge_response else None
            if width * height > MAX_RAIN_EDGE_PIXELS:
                mist_scale = math.sqrt(MAX_RAIN_EDGE_PIXELS / float(width * height))
                mist_width = max(4, int(round(width * mist_scale)))
                mist_height = max(4, int(round(height * mist_scale)))
                mist_gate = cv2.resize(edge_gate, (mist_width, mist_height), interpolation=cv2.INTER_AREA)
                if reflect_x is not None and reflect_y is not None:
                    reflect_x = cv2.resize(reflect_x, (mist_width, mist_height), interpolation=cv2.INTER_LINEAR)
                    reflect_y = cv2.resize(reflect_y, (mist_width, mist_height), interpolation=cv2.INTER_LINEAR)
                    reflect_norm = np.sqrt(reflect_x * reflect_x + reflect_y * reflect_y) + 1e-6
                    reflect_x = reflect_x / reflect_norm
                    reflect_y = reflect_y / reflect_norm
            impact_mask = np.clip(mist_gate * 0.28, 0.0, 1.0)
            upstream_steps = max(2, int(round(3 + 11 * edge_mist_radius + 5 * strength)))
            step_distance = 0.8 + 8.5 * edge_mist_radius + 2.2 * strength
            for step_index in range(1, upstream_steps + 1):
                decay = 1.0 - (step_index / float(upstream_steps + 1))
                distance = step_index * step_distance * mist_scale
                transform = np.float32(
                    [
                        [1, 0, float(-step_x) * distance],
                        [0, 1, float(-step_y) * distance],
                    ]
                )
                shifted = cv2.warpAffine(
                    mist_gate,
                    transform,
                    (mist_width, mist_height),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )
                impact_mask = np.maximum(impact_mask, np.clip(shifted * decay, 0.0, 1.0))
            if reflect_x is not None and reflect_y is not None:
                reflection_mask = np.zeros_like(impact_mask)
                direction_bins = 10
                min_match = math.cos(math.pi / float(direction_bins))
                reflect_steps = max(2, int(round(2 + 8 * edge_mist_radius + 4 * strength)))
                reflect_distance = step_distance * (0.72 + 0.46 * strength + 0.38 * edge_mist_radius)
                for bin_index in range(direction_bins):
                    angle = (math.tau * float(bin_index)) / float(direction_bins)
                    dir_x = math.cos(angle)
                    dir_y = math.sin(angle)
                    match = ((reflect_x * dir_x) + (reflect_y * dir_y) - min_match) / max(1e-6, 1.0 - min_match)
                    bin_gate = np.clip(mist_gate * np.clip(match, 0.0, 1.0), 0.0, 1.0)
                    if float(np.max(bin_gate) or 0.0) <= 0.002:
                        continue
                    for step_index in range(1, reflect_steps + 1):
                        decay = 1.0 - (step_index / float(reflect_steps + 1))
                        distance = step_index * reflect_distance * mist_scale
                        transform = np.float32(
                            [
                                [1, 0, float(dir_x) * distance],
                                [0, 1, float(dir_y) * distance],
                            ]
                        )
                        shifted = cv2.warpAffine(
                            bin_gate,
                            transform,
                            (mist_width, mist_height),
                            flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT,
                            borderValue=0,
                        )
                        reflection_mask = np.maximum(
                            reflection_mask,
                            np.clip(shifted * decay, 0.0, 1.0),
                        )
                if reflection_mask.size:
                    impact_mask = np.maximum(
                        impact_mask,
                        reflection_mask * (0.52 + 0.46 * strength + 0.28 * edge_mist_radius),
                    )
            mist_sigma = 0.9 + 10.0 * edge_mist_radius + 2.4 * strength
            mist_mask = cv2.GaussianBlur(
                impact_mask,
                (0, 0),
                sigmaX=max(0.45, mist_sigma * mist_scale),
                sigmaY=max(0.45, mist_sigma * mist_scale * 0.72),
            )
            mist_mask = np.clip(mist_mask * edge_mist_strength * (0.82 + 1.38 * strength), 0.0, 0.88)
            if mist_width != width or mist_height != height:
                mist_mask = cv2.resize(mist_mask, (width, height), interpolation=cv2.INTER_LINEAR)
            if mist_mask.size:
                if width * height > MAX_RAIN_EDGE_PIXELS:
                    mist_u8 = np.clip(mist_mask * 255.0, 0.0, 255.0).astype("uint8")
                    tint_layer = np.empty_like(result)
                    tint_layer[:, :] = (224, 235, 242)
                    blended = cv2.addWeighted(result, 0.58, tint_layer, 0.42, 0)
                    cv2.copyTo(blended, mist_u8, result)
                else:
                    out = result.astype("float32")
                    mist_tint = np.array([224.0, 235.0, 242.0], dtype="float32")
                    out = out * (1.0 - mist_mask[:, :, None] * 0.58) + mist_tint * (mist_mask[:, :, None] * 0.58)
                    result = np.clip(out, 0, 255).astype("uint8")
        return (result, rain_mask) if return_mask else result
    except Exception:
        return (image, None) if return_mask else image


def _apply_wet_reflection_effect(image, profile: AugmentationProfile, rng) -> object:
    if np is None or cv2 is None or profile.rain_strength <= 0 or profile.wet_reflection_strength <= 0:
        return image

    try:
        rain = max(0.0, min(1.0, float(profile.rain_strength or 0.0)))
        strength = max(0.0, min(1.0, float(profile.wet_reflection_strength or 0.0))) * (0.35 + 0.65 * rain)
        if strength <= 0.001:
            return image

        height, width = image.shape[:2]
        if height < 12 or width < 12:
            return image

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype("float32") / 255.0
        bright_mask = np.clip((gray - 0.34) / 0.58, 0.0, 1.0)
        bright_mask = cv2.GaussianBlur(bright_mask, (0, 0), sigmaX=1.8 + 3.2 * rain, sigmaY=1.8 + 3.2 * rain)
        noise_h = max(3, int(height / 18))
        noise_w = max(3, int(width / 18))
        film_noise = np.array(
            [[_rng_float(rng, 0.0, 1.0) for _x in range(noise_w)] for _y in range(noise_h)],
            dtype="float32",
        )
        film_noise = cv2.resize(film_noise, (width, height), interpolation=cv2.INTER_CUBIC)
        film_noise = cv2.GaussianBlur(film_noise, (0, 0), sigmaX=4.0 + 8.0 * rain, sigmaY=4.0 + 8.0 * rain)
        wet_mask = np.clip((bright_mask * (0.70 + 0.30 * rain)) + (film_noise * 0.16 * rain), 0.0, 1.0)

        angle = math.radians(float(profile.dark_relief_light_angle or 0.0) % 360.0)
        light_dir = np.array([math.cos(angle), -math.sin(angle)], dtype="float32")
        light_norm = float(np.linalg.norm(light_dir) or 1.0)
        light_dir = light_dir / light_norm
        tangent = np.array([-float(light_dir[1]), float(light_dir[0])], dtype="float32")

        gloss = np.zeros((height, width), dtype="float32")
        yy, xx = np.mgrid[0:height, 0:width].astype("float32")
        xx -= width * 0.5
        yy -= height * 0.5
        proj_t = xx * float(tangent[0]) + yy * float(tangent[1])
        proj_n = xx * float(light_dir[0]) + yy * float(light_dir[1])
        normal_extent = max(1.0, float(np.max(np.abs(proj_n)) or 1.0))
        tangent_extent = max(1.0, float(np.max(np.abs(proj_t)) or 1.0))

        band_count = max(1, int(round(1 + 4 * strength + 2 * rain)))
        for _ in range(band_count):
            center_n = _rng_float(rng, -normal_extent * 0.72, normal_extent * 0.72)
            center_t = _rng_float(rng, -tangent_extent * 0.42, tangent_extent * 0.42)
            sigma_n = _rng_float(rng, 5.0, max(6.0, min(width, height) * (0.035 + 0.075 * strength)))
            sigma_t = _rng_float(rng, max(18.0, tangent_extent * 0.34), max(24.0, tangent_extent * (0.72 + 0.22 * rain)))
            band = np.exp(-((proj_n - center_n) ** 2) / (2.0 * sigma_n * sigma_n))
            band *= np.exp(-((proj_t - center_t) ** 2) / (2.0 * sigma_t * sigma_t))
            gloss += band.astype("float32") * _rng_float(rng, 0.16, 0.50) * strength

        base_len = min(width, height) * (0.08 + 0.28 * strength)
        glint_count = max(1, int(round((width * height / 72000.0) * (1.0 + 8.0 * strength))))
        for _ in range(glint_count):
            cx = _rng_int(rng, int(width * 0.05), max(int(width * 0.95), int(width * 0.05) + 1))
            cy = _rng_int(rng, int(height * 0.08), max(int(height * 0.92), int(height * 0.08) + 1))
            local_angle = math.atan2(float(tangent[1]), float(tangent[0])) + _rng_float(rng, -0.35, 0.35)
            local_dir = np.array([math.cos(local_angle), math.sin(local_angle)], dtype="float32")
            length = base_len * _rng_float(rng, 0.35, 1.05)
            half = local_dir * (length * 0.5)
            offset = light_dir * _rng_float(rng, -5.0, 9.0)
            p1 = (
                int(round(cx - float(half[0]) + float(offset[0]))),
                int(round(cy - float(half[1]) + float(offset[1]))),
            )
            p2 = (
                int(round(cx + float(half[0]) + float(offset[0]))),
                int(round(cy + float(half[1]) + float(offset[1]))),
            )
            thickness = max(1, int(round(min(width, height) * _rng_float(rng, 0.003, 0.012) * (0.70 + strength))))
            cv2.line(gloss, p1, p2, _rng_float(rng, 0.08, 0.34) * strength, thickness=thickness, lineType=cv2.LINE_AA)

        tiny_count = max(1, int(round((width * height / 90000.0) * (1.0 + 8.0 * strength))))
        for _ in range(tiny_count):
            x = _rng_int(rng, 0, max(1, width - 1))
            y = _rng_int(rng, 0, max(1, height - 1))
            if wet_mask[y, x] < 0.18:
                continue
            radius = max(1, int(round(_rng_float(rng, 0.8, 2.2 + 2.8 * strength))))
            cv2.circle(gloss, (x, y), radius, _rng_float(rng, 0.08, 0.38) * strength, -1, lineType=cv2.LINE_AA)

        gloss = cv2.GaussianBlur(gloss, (0, 0), sigmaX=1.2 + 3.5 * strength, sigmaY=0.9 + 2.6 * strength)
        percentile = float(np.percentile(gloss, 99.4) or 0.0)
        if percentile > 0:
            gloss = gloss / percentile
        gloss = np.clip(gloss * wet_mask * (0.10 + 0.55 * strength), 0.0, 0.72)

        tint = np.array([245.0, 248.0, 255.0], dtype="float32")
        out = image.astype("float32")
        damp = wet_mask[:, :, None] * (0.015 + 0.055 * rain * strength)
        out = out * (1.0 - damp) + np.array([205.0, 210.0, 218.0], dtype="float32") * damp
        screen = out + (tint - out) * gloss[:, :, None]
        out = out * (1.0 - gloss[:, :, None] * 0.10) + screen * (gloss[:, :, None] * 0.58)
        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _apply_traffic_headlight_effect(image, profile: AugmentationProfile, rng, dirt_mask=None) -> object:
    """Approximate several car headlights illuminating the plate from traffic."""
    if np is None or cv2 is None:
        return image

    try:
        def _profile_float(name: str, default: float) -> float:
            value = getattr(profile, name, default)
            if value is None:
                value = default
            return float(value)

        def _clamp01(value: float) -> float:
            return max(0.0, min(1.0, float(value)))

        global_strength = _clamp01(_profile_float("traffic_headlight_strength", 0.0))
        count = max(0, min(6, int(float(getattr(profile, "traffic_headlight_count", 3) if getattr(profile, "traffic_headlight_count", None) is not None else 3))))
        rain_strength = _clamp01(_profile_float("rain_strength", 0.0))
        tyndall_strength = _clamp01(_profile_float("tyndall_strength", 0.55))
        wet_mud_gloss = max(0.0, min(1.0, float(getattr(profile, "wet_mud_gloss_strength", 0.0) or 0.0)))

        height, width = image.shape[:2]
        if height < 8 or width < 8:
            return image

        base_warmth = _clamp01(_profile_float("night_light_warmth", 0.35))
        first_warmth = _profile_float("traffic_headlight_1_warmth", -1.0)
        if first_warmth < 0.0:
            first_warmth = base_warmth
        def _headlight_rgb(index: int, warmth: float) -> tuple[float, float, float]:
            red = _profile_float(f"traffic_headlight_{index}_r", -1.0)
            green = _profile_float(f"traffic_headlight_{index}_g", -1.0)
            blue = _profile_float(f"traffic_headlight_{index}_b", -1.0)
            if red >= 0.0 and green >= 0.0 and blue >= 0.0:
                return (_clamp01(red), _clamp01(green), _clamp01(blue))
            cold_rgb = (0.84, 0.94, 1.0)
            warm_rgb = (1.0, 0.88, 0.54)
            return tuple(cold_rgb[i] * (1.0 - warmth) + warm_rgb[i] * warmth for i in range(3))

        light_defs = [
            {
                "strength": global_strength,
                "warmth": _clamp01(first_warmth),
                "rgb": _headlight_rgb(1, _clamp01(first_warmth)),
                "cone": max(0.02, min(2.5, _profile_float("traffic_headlight_1_cone", 0.45))),
                "source_radius": max(0.0, min(2.5, _profile_float("traffic_headlight_1_source_radius", 0.08))),
                "source": (
                    _profile_float("traffic_headlight_source_x", -1.0),
                    _profile_float("traffic_headlight_source_y", -1.0),
                ),
                "target": (
                    _profile_float("traffic_headlight_target_x", -1.0),
                    _profile_float("traffic_headlight_target_y", -1.0),
                ),
                "default_source": (0.14, 0.91),
                "default_target": (0.42, 0.44),
            },
            {
                "strength": _clamp01(_profile_float("traffic_headlight_2_strength", 0.0)),
                "warmth": _clamp01(_profile_float("traffic_headlight_2_warmth", 0.35)),
                "rgb": _headlight_rgb(2, _clamp01(_profile_float("traffic_headlight_2_warmth", 0.35))),
                "cone": max(0.02, min(2.5, _profile_float("traffic_headlight_2_cone", 0.45))),
                "source_radius": max(0.0, min(2.5, _profile_float("traffic_headlight_2_source_radius", 0.08))),
                "source": (
                    _profile_float("traffic_headlight_2_source_x", -1.0),
                    _profile_float("traffic_headlight_2_source_y", -1.0),
                ),
                "target": (
                    _profile_float("traffic_headlight_2_target_x", -1.0),
                    _profile_float("traffic_headlight_2_target_y", -1.0),
                ),
                "default_source": (0.86, 0.90),
                "default_target": (0.58, 0.48),
            },
            {
                "strength": _clamp01(_profile_float("traffic_headlight_3_strength", 0.0)),
                "warmth": _clamp01(_profile_float("traffic_headlight_3_warmth", 0.35)),
                "rgb": _headlight_rgb(3, _clamp01(_profile_float("traffic_headlight_3_warmth", 0.35))),
                "cone": max(0.02, min(2.5, _profile_float("traffic_headlight_3_cone", 0.45))),
                "source_radius": max(0.0, min(2.5, _profile_float("traffic_headlight_3_source_radius", 0.08))),
                "source": (
                    _profile_float("traffic_headlight_3_source_x", -1.0),
                    _profile_float("traffic_headlight_3_source_y", -1.0),
                ),
                "target": (
                    _profile_float("traffic_headlight_3_target_x", -1.0),
                    _profile_float("traffic_headlight_3_target_y", -1.0),
                ),
                "default_source": (0.50, 0.98),
                "default_target": (0.50, 0.36),
            },
        ]
        manual_lights = []
        for item in light_defs:
            local_strength = float(item["strength"])
            if local_strength <= 0.001:
                continue
            src_x, src_y = item["source"]
            tgt_x, tgt_y = item["target"]
            if not (0.0 <= src_x <= 1.0 and 0.0 <= src_y <= 1.0):
                src_x, src_y = item["default_source"]
            if not (0.0 <= tgt_x <= 1.0 and 0.0 <= tgt_y <= 1.0):
                tgt_x, tgt_y = item["default_target"]
            manual_lights.append(
                (
                    np.array([src_x, src_y], dtype="float32"),
                    np.array([tgt_x, tgt_y], dtype="float32"),
                    local_strength,
                    float(item["warmth"]),
                    tuple(item["rgb"]),
                    float(item["cone"]),
                    float(item["source_radius"]),
                    True,
                )
            )
        if not manual_lights and (global_strength <= 0.001 or count <= 0):
            return image

        yy, xx = np.mgrid[0:height, 0:width].astype("float32")
        nx = xx / max(1.0, float(width - 1))
        ny = yy / max(1.0, float(height - 1))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype("float32") / 255.0
        normal_strength = max(0.0, min(1.0, float(getattr(profile, "light_normal_strength", 0.0) or 0.0)))
        relief_strength = max(0.0, min(3.0, float(getattr(profile, "dark_relief_strength", 0.0) or 0.0)))

        mud = None
        mud_edge = None
        if dirt_mask is not None:
            mud = np.asarray(dirt_mask, dtype="float32")
            if mud.shape[:2] != (height, width):
                mud = cv2.resize(mud, (width, height), interpolation=cv2.INTER_LINEAR)
            mud = cv2.GaussianBlur(np.clip(mud, 0.0, 1.0), (0, 0), sigmaX=0.55, sigmaY=0.55)
            mud_grad_x = cv2.Sobel(mud, cv2.CV_32F, 1, 0, ksize=3)
            mud_grad_y = cv2.Sobel(mud, cv2.CV_32F, 0, 1, ksize=3)
            mud_edge = cv2.GaussianBlur(np.clip(np.abs(mud_grad_x) + np.abs(mud_grad_y), 0.0, 1.0), (0, 0), sigmaX=0.45, sigmaY=0.45)

        sign_height = np.clip((0.66 - gray) / 0.52, 0.0, 1.0)
        sign_height = sign_height ** 1.22
        height_map = sign_height * (0.10 + 1.18 * relief_strength)
        if mud is not None:
            height_map = np.clip(height_map + mud * (0.72 + 0.82 * wet_mud_gloss), 0.0, 1.0)
        height_map = cv2.GaussianBlur(height_map.astype("float32"), (0, 0), sigmaX=0.46, sigmaY=0.46)
        height_grad_x = cv2.Sobel(height_map, cv2.CV_32F, 1, 0, ksize=3)
        height_grad_y = cv2.Sobel(height_map, cv2.CV_32F, 0, 1, ksize=3)
        grad_abs = np.abs(height_grad_x) + np.abs(height_grad_y)
        grad_scale = float(np.percentile(grad_abs, 99.2) or 0.0)
        if grad_scale > 0.0001:
            height_grad_x = height_grad_x / grad_scale
            height_grad_y = height_grad_y / grad_scale
            grad_abs = np.clip(grad_abs / grad_scale, 0.0, 1.0)
        else:
            grad_abs = np.clip(grad_abs, 0.0, 1.0)
        symbol_gate = cv2.GaussianBlur(np.clip(sign_height, 0.0, 1.0).astype("float32"), (0, 0), sigmaX=0.32, sigmaY=0.32)
        relief_field = np.zeros((height, width), dtype="float32")
        shadow_field = np.zeros((height, width), dtype="float32")

        procedural_lights = []
        if not manual_lights:
            base_sources = [
                (-0.28, 1.18),
                (1.28, 1.14),
                (0.50, 1.36),
                (-0.18, 0.38),
                (1.18, 0.34),
                (0.50, -0.18),
            ]
            for index in range(count):
                src_x, src_y = base_sources[index % len(base_sources)]
                src = np.array([src_x + _rng_float(rng, -0.06, 0.06), src_y + _rng_float(rng, -0.05, 0.05)], dtype="float32")
                target = np.array([0.50 + _rng_float(rng, -0.08, 0.08), 0.46 + _rng_float(rng, -0.08, 0.07)], dtype="float32")
                procedural_lights.append((src, target, global_strength, base_warmth, _headlight_rgb(1, base_warmth), 0.45, 0.08, False))
        active_lights = manual_lights or procedural_lights
        strength = max((float(item[2]) for item in active_lights), default=0.0)
        if strength <= 0.001:
            return image
        light_field = np.zeros((height, width), dtype="float32")
        hotspot_field = np.zeros((height, width), dtype="float32")
        color_weight = np.zeros((height, width), dtype="float32")
        color_accum = np.zeros((height, width, 3), dtype="float32")
        cold = np.array([255.0, 240.0, 214.0], dtype="float32")
        warm = np.array([180.0, 225.0, 255.0], dtype="float32")

        for src, target_center, local_strength, local_warmth, local_rgb, local_cone, local_source_radius, stable in active_lights:
            delta = target_center - src
            norm = float(np.linalg.norm(delta) or 0.0)
            source_width = max(0.0, min(2.5, float(local_source_radius)))
            target_width = max(0.02, min(2.5, float(local_cone)))
            if not stable:
                target_width *= _rng_float(rng, 0.86, 1.18)
                source_width *= _rng_float(rng, 0.86, 1.14)
            local_color = np.array(
                [
                    float(local_rgb[2]) * 255.0,
                    float(local_rgb[1]) * 255.0,
                    float(local_rgb[0]) * 255.0,
                ],
                dtype="float32",
            )
            if norm <= 0.012:
                center = (src + target_center) * 0.5
                rel_x = nx - float(center[0])
                rel_y = ny - float(center[1])
                radial = np.sqrt(rel_x * rel_x + rel_y * rel_y)
                outer_radius = max(0.008, max(source_width, target_width))
                inner_radius = max(0.006, min(source_width, target_width))
                beam = np.exp(-((radial / outer_radius) ** 2)).astype("float32")
                core = np.exp(-((radial / inner_radius) ** 2)).astype("float32") * 0.42
                beam = np.maximum(beam, core)
                beam *= local_strength * (1.0 if stable else _rng_float(rng, 0.58, 1.18))
                light_field = np.maximum(light_field, beam)

                hot_sigma = max(0.012, outer_radius * (0.26 + 0.22 * local_strength))
                hot = np.exp(-((radial / hot_sigma) ** 2)).astype("float32")
                hot *= local_strength * (0.62 if stable else _rng_float(rng, 0.42, 1.0))
                hotspot_field = np.maximum(hotspot_field, hot)
                local_source = np.clip(beam * (0.56 + 0.70 * local_strength) + hot * (0.32 + 0.90 * local_strength), 0.0, 1.0)
                color_accum += local_source[:, :, None] * local_color
                color_weight += local_source
                continue

            direction = delta / norm
            perp = np.array([-float(direction[1]), float(direction[0])], dtype="float32")

            rel_x = nx - float(src[0])
            rel_y = ny - float(src[1])
            along = rel_x * float(direction[0]) + rel_y * float(direction[1])
            side = rel_x * float(perp[0]) + rel_y * float(perp[1])
            beam_length = max(0.16, norm * (0.72 if stable else _rng_float(rng, 0.58, 0.92)) + target_width * 1.20)
            center_along = norm * (0.50 if stable else _rng_float(rng, 0.45, 0.62))
            progress = np.clip(along / max(0.001, norm), 0.0, 1.30)
            width_progress = np.clip(progress, 0.0, 1.0)
            local_width = np.maximum(0.006, source_width * (1.0 - width_progress) + target_width * width_progress)
            beam = np.exp(-((side / local_width) ** 2 + ((along - center_along) / beam_length) ** 2)).astype("float32")
            near_fade = max(0.018, norm * 0.055)
            beam *= np.clip((along + near_fade) / near_fade, 0.0, 1.0)
            far_fade = max(0.028, target_width + norm * 0.12)
            beam *= np.clip((norm + far_fade - along) / far_fade, 0.0, 1.0)
            beam *= local_strength * (1.0 if stable else _rng_float(rng, 0.58, 1.18))
            light_field = np.maximum(light_field, beam)
            local_relief = (height_grad_x * float(direction[0])) + (height_grad_y * float(direction[1]))
            relief_field = np.maximum(relief_field, np.clip(local_relief, 0.0, 1.0) * beam)
            shadow_field = np.maximum(shadow_field, np.clip(-local_relief, 0.0, 1.0) * beam)

            hot_x = float(src[0]) + float(direction[0]) * norm * (0.78 if stable else _rng_float(rng, 0.62, 0.92))
            hot_y = float(src[1]) + float(direction[1]) * norm * (0.78 if stable else _rng_float(rng, 0.62, 0.92))
            hot_sigma_x = (0.055 if stable else _rng_float(rng, 0.035, 0.090)) * (1.0 + 0.55 * local_strength)
            hot_sigma_y = (0.036 if stable else _rng_float(rng, 0.020, 0.060)) * (1.0 + 0.40 * local_strength)
            hot = np.exp(-(((nx - hot_x) / hot_sigma_x) ** 2 + ((ny - hot_y) / hot_sigma_y) ** 2)).astype("float32")
            hot *= local_strength * (1.0 if stable else _rng_float(rng, 0.42, 1.0))
            hotspot_field = np.maximum(hotspot_field, hot)
            local_source = np.clip(beam * (0.56 + 0.70 * local_strength) + hot * (0.32 + 0.90 * local_strength), 0.0, 1.0)
            color_accum += local_source[:, :, None] * local_color
            color_weight += local_source

        light_field = cv2.GaussianBlur(np.clip(light_field, 0.0, 1.0), (0, 0), sigmaX=1.2 + 3.0 * strength, sigmaY=1.2 + 3.0 * strength)
        hotspot_field = cv2.GaussianBlur(np.clip(hotspot_field, 0.0, 1.0), (0, 0), sigmaX=0.8 + 1.6 * strength, sigmaY=0.8 + 1.6 * strength)
        color_weight = cv2.GaussianBlur(np.clip(color_weight, 0.0, 1.0), (0, 0), sigmaX=1.0 + 2.2 * strength, sigmaY=1.0 + 2.2 * strength)
        for channel in range(3):
            color_accum[:, :, channel] = cv2.GaussianBlur(color_accum[:, :, channel], (0, 0), sigmaX=1.0 + 2.2 * strength, sigmaY=1.0 + 2.2 * strength)
        field = np.clip(light_field * (0.56 + 0.70 * strength) + hotspot_field * (0.32 + 0.90 * strength), 0.0, 1.0)

        bright_mask = np.clip((gray - 0.28) / 0.62, 0.0, 1.0)
        retro_mask = cv2.GaussianBlur(bright_mask, (0, 0), sigmaX=0.7, sigmaY=0.7)
        fallback_color = cold * (1.0 - base_warmth) + warm * base_warmth
        light_color = color_accum / np.maximum(color_weight[:, :, None], 0.0001)
        light_color = np.where(color_weight[:, :, None] > 0.001, light_color, fallback_color)

        out = image.astype("float32")
        tyndall_gain = rain_strength * strength * tyndall_strength
        if tyndall_gain > 0.001:
            min_dim = float(max(1, min(width, height)))
            aerosol = np.clip(light_field * 0.72 + hotspot_field * 0.28, 0.0, 1.0)
            aerosol = cv2.GaussianBlur(
                aerosol,
                (0, 0),
                sigmaX=max(1.0, 1.6 + min_dim * (0.006 + 0.018 * rain_strength)),
                sigmaY=max(0.8, 1.1 + min_dim * (0.004 + 0.014 * rain_strength)),
            )
            noise_h = max(6, min(96, height // 28 or 6))
            noise_w = max(6, min(96, width // 28 or 6))
            noise_rng = np.random.default_rng(_rng_int(rng, 1, 2_147_483_646))
            particles = noise_rng.random((noise_h, noise_w)).astype("float32")
            particles = cv2.resize(particles, (width, height), interpolation=cv2.INTER_LINEAR)
            particles = cv2.GaussianBlur(
                particles,
                (0, 0),
                sigmaX=0.8 + 2.2 * rain_strength,
                sigmaY=0.8 + 2.2 * rain_strength,
            )
            particle_gate = np.clip(0.72 + particles * (0.24 + 0.22 * rain_strength), 0.0, 1.18)
            tyndall = np.clip(
                aerosol
                * particle_gate
                * tyndall_gain
                * (0.28 + 0.46 * rain_strength),
                0.0,
                0.48,
            )
            tyndall = cv2.GaussianBlur(
                tyndall,
                (0, 0),
                sigmaX=0.9 + 2.4 * tyndall_gain,
                sigmaY=0.7 + 1.9 * tyndall_gain,
            )
            tyndall_color = np.clip(
                light_color * 0.82 + np.array([245.0, 248.0, 255.0], dtype="float32") * 0.18,
                0.0,
                255.0,
            )
            veil = tyndall[:, :, None]
            contrast_loss = veil * (0.05 + 0.12 * tyndall_gain)
            out = out * (1.0 - contrast_loss) + np.array([186.0, 193.0, 205.0], dtype="float32") * contrast_loss
            out = out + (tyndall_color - out) * veil * (0.28 + 0.42 * tyndall_strength)
        ambient_gain = field[:, :, None] * (0.08 + 0.20 * (1.0 - retro_mask[:, :, None]))
        retro_gain = field[:, :, None] * retro_mask[:, :, None] * (0.22 + 0.66 * normal_strength)
        out = out + (light_color - out) * np.clip(ambient_gain + retro_gain, 0.0, 0.78)
        bloom = cv2.GaussianBlur(np.clip(field * retro_mask, 0.0, 1.0), (0, 0), sigmaX=2.0 + 5.5 * strength, sigmaY=1.2 + 3.5 * strength)
        out = out + (255.0 - out) * np.clip(bloom[:, :, None] * strength * 0.28, 0.0, 0.38)
        relief_gain = strength * (0.10 + 0.42 * normal_strength + 0.96 * relief_strength + 0.36 * wet_mud_gloss)
        if relief_gain > 0.001:
            relief_field = cv2.GaussianBlur(np.clip(relief_field, 0.0, 1.0), (0, 0), sigmaX=0.32 + 0.55 * relief_gain, sigmaY=0.32 + 0.55 * relief_gain)
            shadow_field = cv2.GaussianBlur(np.clip(shadow_field, 0.0, 1.0), (0, 0), sigmaX=0.55 + 0.70 * relief_gain, sigmaY=0.55 + 0.70 * relief_gain)
            edge_gate = np.clip((symbol_gate * 0.34) + (height_map * 0.26) + (grad_abs * 1.18), 0.0, 1.0)
            lit = np.clip(relief_field * edge_gate * (0.78 + 1.05 * field), 0.0, 1.0)
            shaded = np.clip(shadow_field * edge_gate * (0.64 + 0.86 * field), 0.0, 1.0)
            out = out + light_color * lit[:, :, None] * (0.14 + 0.68 * relief_gain)
            out = out - out * shaded[:, :, None] * (0.12 + 0.52 * relief_gain)

        if wet_mud_gloss > 0.001 and mud is not None and mud_edge is not None:
            wetness = max(0.0, min(1.0, float(getattr(profile, "dirt_flow_humidity", 0.45) if getattr(profile, "dirt_flow_humidity", None) is not None else 0.45)))
            gloss_source = np.clip((field * 0.72 + hotspot_field * 0.95) * mud, 0.0, 1.0)
            gloss_shape = np.clip(0.36 + 1.18 * mud_edge + 0.72 * relief_field, 0.0, 2.2)
            gloss = np.clip(
                gloss_source
                * gloss_shape
                * (0.48 + 0.82 * wetness)
                * wet_mud_gloss
                * (0.75 + 0.95 * wet_mud_gloss),
                0.0,
                1.0,
            )
            gloss = cv2.GaussianBlur(gloss, (0, 0), sigmaX=0.28 + 1.15 * wet_mud_gloss, sigmaY=0.28 + 0.82 * wet_mud_gloss)
            color_gloss = np.clip(gloss[:, :, None] * (0.86 + 0.72 * wet_mud_gloss), 0.0, 0.86)
            white_gloss = np.clip((gloss * (0.42 + 0.78 * mud_edge + 0.36 * hotspot_field))[:, :, None] * wet_mud_gloss, 0.0, 0.62)
            out = out + (light_color - out) * color_gloss
            out = out + (255.0 - out) * white_gloss

        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _has_active_traffic_headlight(profile: AugmentationProfile) -> bool:
    try:
        return any(
            max(0.0, min(1.0, float(getattr(profile, name, 0.0) or 0.0))) > 0.001
            for name in (
                "traffic_headlight_strength",
                "traffic_headlight_2_strength",
                "traffic_headlight_3_strength",
            )
        )
    except Exception:
        return False


def _apply_camera_glare_effect(image, profile: AugmentationProfile, rng) -> object:
    if np is None or cv2 is None or profile.light_normal_strength <= 0:
        return image

    try:
        normal = max(0.0, min(1.0, float(profile.light_normal_strength or 0.0)))
        light = max(0.0, min(1.0, float(profile.dark_relief_strength or 0.0)))
        rain = max(0.0, min(1.0, float(profile.rain_strength or 0.0)))
        strength = normal * (0.28 + 0.72 * light) * (0.70 + 0.30 * rain)
        if strength <= 0.002:
            return image

        height, width = image.shape[:2]
        if height < 12 or width < 12:
            return image

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype("float32") / 255.0
        bright_mask = np.clip((gray - 0.44) / 0.56, 0.0, 1.0)
        broad = cv2.GaussianBlur(
            bright_mask,
            (0, 0),
            sigmaX=max(2.0, min(width, height) * (0.035 + 0.085 * strength)),
            sigmaY=max(2.0, min(width, height) * (0.035 + 0.085 * strength)),
        )
        fine = cv2.GaussianBlur(bright_mask, (0, 0), sigmaX=1.2 + 2.5 * strength, sigmaY=1.2 + 2.5 * strength)
        glare = np.clip((broad * (0.62 + 0.28 * rain)) + (fine * 0.22), 0.0, 1.0)

        angle = math.radians(float(profile.dark_relief_light_angle or 0.0) % 360.0)
        offset_x = math.cos(angle) * width * 0.10 * normal
        offset_y = -math.sin(angle) * height * 0.10 * normal
        center_x = width * 0.5 + offset_x
        center_y = height * 0.5 + offset_y
        yy, xx = np.mgrid[0:height, 0:width].astype("float32")
        radial = ((xx - center_x) ** 2) / ((width * (0.36 + 0.24 * normal)) ** 2)
        radial += ((yy - center_y) ** 2) / ((height * (0.30 + 0.20 * normal)) ** 2)
        veil = np.exp(-radial).astype("float32") * (0.18 + 0.38 * strength)
        glare = np.clip(glare * (0.26 + 0.74 * strength) + veil, 0.0, 1.0)

        tint = np.array([238.0, 245.0, 255.0], dtype="float32")
        out = image.astype("float32")
        contrast_loss = glare[:, :, None] * (0.05 + 0.16 * strength)
        out = out * (1.0 - contrast_loss) + np.array([190.0, 198.0, 210.0], dtype="float32") * contrast_loss
        out = out + (tint - out) * glare[:, :, None] * (0.28 + 0.42 * strength)
        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _apply_dirt_streak_effect(image, profile: AugmentationProfile, rng) -> object:
    if np is None or cv2 is None or profile.dirt_streak_strength <= 0:
        return image

    try:
        strength = max(0.0, min(1.0, float(profile.dirt_streak_strength)))
        height, width = image.shape[:2]
        if height < 12 or width < 12:
            return image

        overlay = image.astype("float32")
        mask = np.zeros((height, width), dtype="float32")
        streaks = int(max(1, (width / 95.0) * (2.0 + 8.0 * strength)))
        for _ in range(streaks):
            x = _rng_int(rng, 0, max(1, width - 1))
            y = _rng_int(rng, 0, max(1, int(height * 0.55)))
            length = _rng_int(rng, int(height * (0.18 + 0.18 * strength)), int(height * (0.38 + 0.42 * strength)))
            thickness = _rng_int(rng, 1, max(2, int(2 + 5 * strength)))
            drift = _rng_int(rng, -max(2, int(width * 0.035)), max(2, int(width * 0.035)))
            mid_y = min(height - 1, y + int(length * 0.45))
            end_y = min(height - 1, y + length)
            points = np.array(
                [
                    [x, y],
                    [max(0, min(width - 1, x + int(drift * 0.35))), mid_y],
                    [max(0, min(width - 1, x + drift)), end_y],
                ],
                dtype=np.int32,
            )
            cv2.polylines(mask, [points], False, 1.0, thickness=thickness, lineType=cv2.LINE_AA)
            if _rng_int(rng, 0, 100) < int(35 + 35 * strength):
                drop_y = min(height - 1, y + _rng_int(rng, int(length * 0.08), max(int(length * 0.35), int(length * 0.08) + 1)))
                cv2.circle(mask, (x, drop_y), max(1, thickness), 0.65, -1, lineType=cv2.LINE_AA)

        kernel = max(3, int(3 + 8 * strength))
        if kernel % 2 == 0:
            kernel += 1
        mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)
        max_value = float(mask.max() or 0.0)
        if max_value > 0:
            mask = mask / max_value

        dirt_color = np.array([42.0, 55.0, 75.0], dtype="float32")  # BGR: muted brown-gray.
        alpha = mask[:, :, None] * (0.10 + 0.38 * strength)
        overlay = overlay * (1.0 - alpha) + dirt_color * alpha
        return np.clip(overlay, 0, 255).astype("uint8")
    except Exception:
        return image


def _apply_physical_dirt_flow_effect(image, profile: AugmentationProfile, rng, *, return_mask: bool = False) -> object:
    if np is None or cv2 is None:
        return (image, None) if return_mask else image

    try:
        legacy_strength = max(0.0, min(1.0, float(profile.dirt_flow_strength or 0.0)))
        points = max(0, min(MAX_DIRT_FLOW_POINTS, int(profile.dirt_flow_points or 0)))
        if points <= 0 and legacy_strength <= 0:
            return (image, None) if return_mask else image
        if points <= 0:
            points = max(1, int(round(24 * (0.20 + 0.80 * legacy_strength))))

        mass_min = max(0.05, min(2.8, float(getattr(profile, "dirt_flow_mass_min", 0.18) or 0.18)))
        mass_max = max(0.05, min(2.8, float(getattr(profile, "dirt_flow_mass_max", 1.0) or 1.0)))
        if mass_min > mass_max:
            mass_min, mass_max = mass_max, mass_min
        splash_scale = max(0.0, min(1.0, float(profile.dirt_flow_splash_scale if profile.dirt_flow_splash_scale is not None else 0.45)))
        trail_length = max(0.0, min(1.0, float(profile.dirt_flow_trail_length if profile.dirt_flow_trail_length is not None else 0.55)))
        humidity = max(0.0, min(1.0, float(profile.dirt_flow_humidity)))
        legacy_stickiness = max(0.0, min(1.0, float(getattr(profile, "dirt_flow_stickiness", 0.45) if getattr(profile, "dirt_flow_stickiness", None) is not None else 0.45)))
        stickiness_min = max(0.0, min(1.0, float(getattr(profile, "dirt_flow_stickiness_min", legacy_stickiness) if getattr(profile, "dirt_flow_stickiness_min", None) is not None else legacy_stickiness)))
        stickiness_max = max(0.0, min(1.0, float(getattr(profile, "dirt_flow_stickiness_max", legacy_stickiness) if getattr(profile, "dirt_flow_stickiness_max", None) is not None else legacy_stickiness)))
        if stickiness_min > stickiness_max:
            stickiness_min, stickiness_max = stickiness_max, stickiness_min
        angle = math.radians(max(-75.0, min(75.0, float(profile.dirt_flow_air_angle or 0.0))))
        wind_strength = max(0.0, min(1.0, float(profile.dirt_flow_wind_strength or 0.0)))
        vehicle_speed = max(0.0, min(1.0, float(profile.vehicle_speed if profile.vehicle_speed is not None else 0.0)))
        rain_strength = max(0.0, min(1.0, float(profile.rain_strength or 0.0)))
        gravity_strength = 1.0
        opacity_min = max(0.0, min(1.0, float(profile.dirt_flow_opacity_min or 0.0)))
        opacity_max = max(0.0, min(1.0, float(profile.dirt_flow_opacity_max or 0.0)))
        if opacity_min > opacity_max:
            opacity_min, opacity_max = opacity_max, opacity_min

        height, width = image.shape[:2]
        if height < 12 or width < 12:
            return (image, None) if return_mask else image

        stop_on_dark_contour = bool(getattr(profile, "dirt_flow_stop_on_dark_contour", False))
        stop_mask = None
        stop_normal_x = None
        stop_normal_y = None
        if stop_on_dark_contour:
            try:
                source_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
                source_gray = source_gray.astype("uint8", copy=False)
                blurred_gray = cv2.GaussianBlur(source_gray, (3, 3), 0)
                dark_threshold = max(20.0, min(175.0, float(np.percentile(blurred_gray, 38)) * 0.96))
                dark_region = blurred_gray <= dark_threshold
                contour_edges = cv2.Canny(blurred_gray, 35, 120)
                kernel = np.ones((3, 3), dtype="uint8")
                dark_neighborhood = cv2.dilate(dark_region.astype("uint8"), kernel, iterations=1) > 0
                contour_neighborhood = cv2.dilate((contour_edges > 0).astype("uint8"), kernel, iterations=1) > 0
                stop_mask = cv2.dilate((dark_neighborhood & contour_neighborhood).astype("uint8"), kernel, iterations=1) > 0
                grad_x = cv2.Sobel(blurred_gray.astype("float32"), cv2.CV_32F, 1, 0, ksize=3)
                grad_y = cv2.Sobel(blurred_gray.astype("float32"), cv2.CV_32F, 0, 1, ksize=3)
                grad_norm = np.sqrt(grad_x * grad_x + grad_y * grad_y) + 1e-6
                stop_normal_x = grad_x / grad_norm
                stop_normal_y = grad_y / grad_norm
            except Exception:
                stop_mask = None
                stop_normal_x = None
                stop_normal_y = None

        alpha_mask = np.zeros((height, width), dtype="float32")
        gravity = np.array([0.0, 1.0], dtype="float32") * (0.18 + 1.40 * gravity_strength)
        airflow = np.array([math.sin(angle) * (0.35 + 1.85 * wind_strength), 0.0], dtype="float32")
        initial_force = gravity * 0.35 + airflow * (0.65 + 0.45 * wind_strength)
        initial_norm = float(np.linalg.norm(initial_force) or 1.0)
        initial_force = initial_force / initial_norm
        gravity_norm = gravity / float(np.linalg.norm(gravity) or 1.0)
        flow_power = 1.0 + 0.80 * humidity + 0.85 * wind_strength

        active_points = max(1, int(points))
        base_radius = max(2.0, min(width, height) * (0.005 + 0.030 * splash_scale))
        center = np.array([width * 0.5, height * 0.52], dtype="float32")
        point_seeds = [_rng_int(rng, 1, 2_147_483_646) for _ in range(active_points)]
        for point_seed in point_seeds:
            rng = random.Random(point_seed)
            mass = _rng_float(rng, mass_min, mass_max)
            if stickiness_max > stickiness_min:
                bucket_count = 5
                raw_bucket = _rng_int(rng, 0, bucket_count - 1)
                stickiness = stickiness_min + (stickiness_max - stickiness_min) * (raw_bucket / max(1, bucket_count - 1))
            else:
                stickiness = stickiness_min
            mass_norm = max(0.0, min(1.0, (mass - 0.05) / 2.75))
            mass_common = max(0.0, min(1.0, mass))
            mass_heavy_boost = max(0.0, min(1.0, (mass - 1.0) / 1.8))
            opacity = _rng_float(rng, opacity_min, opacity_max)
            impact_energy = (vehicle_speed ** 1.35) * (0.35 + 0.65 * mass_norm) * (0.50 + 0.50 * splash_scale)
            impact_force = max(0.0, min(1.0, impact_energy * (0.72 + 0.48 * mass_heavy_boost)))
            dry_adhesion = (1.0 - humidity) * stickiness
            cohesive_slide = humidity * stickiness
            wet_runoff = humidity * (1.0 - stickiness) * (1.0 - 0.45 * mass_norm)
            dry_dust_runoff = (1.0 - humidity) * (1.0 - stickiness) * (1.0 - mass_norm)
            start_x = _rng_int(rng, 0, max(1, width - 1))
            start_y = _rng_int(rng, 0, max(1, int(height * 0.62)))
            mass_trail_factor = max(
                0.10,
                (0.24 + 0.76 * (mass_common ** 1.10)) * (1.0 + 0.55 * mass_heavy_boost),
            )
            mass_trail_factor *= 0.42 + 0.95 * cohesive_slide + 0.70 * wet_runoff + 0.32 * dry_dust_runoff
            mass_trail_factor *= 1.0 - 0.62 * dry_adhesion
            mass_trail_factor = max(0.05, mass_trail_factor)
            if trail_length <= 0.001 or humidity <= 0.001:
                length = 0
            else:
                trail_intent = 0.25 + 1.85 * trail_length
                length = int((height * (0.08 + 0.62 * humidity)) * mass_trail_factor * trail_intent * flow_power)
                min_length = int(
                    round(
                        height
                        * (0.018 + 0.090 * trail_length)
                        * (0.30 + 0.70 * mass_common)
                        * (0.55 + 0.45 * humidity)
                    )
                )
                max_length = int(
                    math.hypot(width, height)
                    * (0.18 + 0.82 * min(1.0, mass_trail_factor))
                    * (0.35 + 0.65 * trail_length)
                )
                length = max(min_length, min(max_length, length))
            thickness = max(1, int(round((1 + mass_norm * (0.75 + 4.6 * splash_scale + 2.6 * humidity + 2.4 * impact_force)) * (1.0 + 0.90 * dry_adhesion))))

            impact_mask = np.zeros((height, width), dtype="float32")
            radius_gain = 1.0 + 2.65 * impact_force + 1.35 * (vehicle_speed ** 2.0) * (0.30 + 0.70 * mass_norm)
            radius_x = max(2, int(round(base_radius * (0.45 + 2.85 * mass_norm) * (1.0 + 0.55 * dry_adhesion + 0.28 * stickiness * mass_norm) * radius_gain)))
            radius_y = max(2, int(round(radius_x * _rng_float(rng, 0.55, 1.30) * (1.0 + 0.22 * dry_adhesion + 0.55 * impact_force))))
            impact_opacity = min(1.0, opacity * (0.86 + 0.38 * dry_adhesion + 0.22 * stickiness + 0.70 * impact_force))
            vertex_count = _rng_int(rng, 9, 19)
            vertices: list[list[int]] = []
            angle_offset = _rng_float(rng, 0.0, math.tau)
            for idx in range(vertex_count):
                local_angle = angle_offset + (math.tau * idx / vertex_count) + _rng_float(rng, -0.18, 0.18)
                local_radius = _rng_float(rng, 0.52, 1.32)
                x = int(round(start_x + math.cos(local_angle) * radius_x * local_radius))
                y = int(round(start_y + math.sin(local_angle) * radius_y * local_radius))
                vertices.append([max(0, min(width - 1, x)), max(0, min(height - 1, y))])
            if len(vertices) >= 3:
                cv2.fillPoly(impact_mask, [np.array(vertices, dtype=np.int32)], impact_opacity, lineType=cv2.LINE_AA)

            lobes = max(1, int(round(1 + 10 * mass_norm * splash_scale + 8 * impact_force)))
            for _lobe in range(lobes):
                lobe_angle = _rng_float(rng, 0.0, math.tau)
                lobe_dist = _rng_float(rng, 0.05, 0.95 + 0.48 * impact_force) * max(radius_x, radius_y)
                lobe_x = int(round(start_x + math.cos(lobe_angle) * lobe_dist))
                lobe_y = int(round(start_y + math.sin(lobe_angle) * lobe_dist))
                lobe_radius = max(1, int(round(_rng_float(rng, 0.18, 0.55 + 0.35 * impact_force) * max(radius_x, radius_y))))
                cv2.circle(
                    impact_mask,
                    (max(0, min(width - 1, lobe_x)), max(0, min(height - 1, lobe_y))),
                    lobe_radius,
                    impact_opacity * _rng_float(rng, 0.35, 0.90),
                    -1,
                    lineType=cv2.LINE_AA,
                )

            holes = max(0, int(round(1 + 6 * (1.0 - humidity) * mass_norm)))
            for _hole in range(holes):
                hole_angle = _rng_float(rng, 0.0, math.tau)
                hole_dist = _rng_float(rng, 0.0, 0.75) * max(radius_x, radius_y)
                hole_x = int(round(start_x + math.cos(hole_angle) * hole_dist))
                hole_y = int(round(start_y + math.sin(hole_angle) * hole_dist))
                hole_radius = max(1, int(round(_rng_float(rng, 0.08, 0.22) * max(radius_x, radius_y))))
                cv2.circle(
                    impact_mask,
                    (max(0, min(width - 1, hole_x)), max(0, min(height - 1, hole_y))),
                    hole_radius,
                    0.0,
                    -1,
                    lineType=cv2.LINE_AA,
                )

            impact_blur = max(3, int(3 + 4 * humidity))
            if impact_blur % 2 == 0:
                impact_blur += 1
            impact_mask = cv2.GaussianBlur(impact_mask, (impact_blur, impact_blur), 0)
            alpha_mask = np.maximum(alpha_mask, np.clip(impact_mask, 0.0, 1.0))

            current_x = float(start_x)
            current_y = float(start_y)
            trail_points: list[list[int]] = [[int(current_x), int(current_y)]]

            if length > 1:
                segments = max(4, min(34, int(length / 7)))
                for step in range(1, segments + 1):
                    decay = 1.0 - (step / float(segments + 1))
                    progress = step / float(segments)
                    gravity_takeover = min(1.0, progress ** (0.72 + 0.55 * (1.0 - humidity)))
                    segment_force = initial_force * (1.0 - gravity_takeover) + gravity_norm * gravity_takeover
                    segment_norm = float(np.linalg.norm(segment_force) or 1.0)
                    segment_force = segment_force / segment_norm
                    wobble = _rng_float(rng, -1.0, 1.0) * (0.35 + 1.20 * humidity) * (0.35 + decay)
                    step_len = (length / segments) * (0.82 + 0.36 * decay)
                    next_x = current_x + float(segment_force[0]) * step_len + wobble * (1.0 - 0.45 * gravity_takeover)
                    next_y = current_y + float(segment_force[1]) * step_len
                    clamped_x = max(0, min(width - 1, int(round(next_x))))
                    clamped_y = max(0, min(height - 1, int(round(next_y))))
                    trail_points.append([clamped_x, clamped_y])
                    if stop_mask is not None and step > 1 and bool(stop_mask[clamped_y, clamped_x]):
                        should_stop = True
                        if stop_normal_x is not None and stop_normal_y is not None:
                            movement_norm = float(np.linalg.norm(segment_force) or 1.0)
                            move_x = float(segment_force[0]) / movement_norm
                            move_y = float(segment_force[1]) / movement_norm
                            edge_alignment = abs((float(stop_normal_x[clamped_y, clamped_x]) * move_x) + (float(stop_normal_y[clamped_y, clamped_x]) * move_y))
                            should_stop = edge_alignment >= 0.72
                        if should_stop:
                            break
                    if next_x < 0 or next_x >= width or next_y < 0 or next_y >= height:
                        break
                    current_x = next_x
                    current_y = next_y

            if len(trail_points) >= 2:
                trail_mask = np.zeros((height, width), dtype="float32")
                water_channel = max(0.0, min(1.0, humidity * trail_length * (0.56 + 0.44 * stickiness)))
                stream_width_scale = max(0.14, 1.0 - 0.78 * water_channel + 0.20 * dry_adhesion)
                trail_alpha = min(
                    1.0,
                    opacity
                    * (0.54 + 0.64 * humidity)
                    * (0.38 + 0.78 * mass_common)
                    * (0.72 + 0.62 * stickiness + 0.34 * wet_runoff),
                )
                for idx in range(1, len(trail_points)):
                    p0 = tuple(trail_points[idx - 1])
                    p1 = tuple(trail_points[idx])
                    fade = 1.0 - ((idx - 1) / max(1.0, len(trail_points) - 1.0))
                    segment_thickness = max(
                        1,
                        int(round(thickness * stream_width_scale * (0.34 + 0.78 * fade))),
                    )
                    cv2.line(
                        trail_mask,
                        p0,
                        p1,
                        trail_alpha * (0.18 + 0.82 * fade),
                        thickness=segment_thickness,
                        lineType=cv2.LINE_AA,
                    )
                for idx, point in enumerate(trail_points):
                    fade = 1.0 - (idx / max(1.0, len(trail_points) - 1.0))
                    radius = max(
                        1,
                        int(round(thickness * stream_width_scale * (0.28 + 0.55 * humidity) * (0.24 + fade))),
                    )
                    cv2.circle(trail_mask, tuple(point), radius, trail_alpha * (0.12 + 0.88 * fade), -1, lineType=cv2.LINE_AA)
                end_radius = max(1, int(round(thickness * stream_width_scale * (0.45 + 0.65 * humidity))))
                cv2.circle(trail_mask, tuple(trail_points[-1]), end_radius, trail_alpha * (0.22 + 0.35 * humidity), -1, lineType=cv2.LINE_AA)
                trail_blur = max(1, int(1 + 5 * (1.0 - water_channel) + 2 * (1.0 - humidity)))
                if trail_blur % 2 == 0:
                    trail_blur += 1
                trail_mask = cv2.GaussianBlur(trail_mask, (trail_blur, trail_blur), 0)
                alpha_mask = np.maximum(alpha_mask, np.clip(trail_mask, 0.0, 1.0))

            lower_runoff = max(0.0, min(1.0, (0.72 * wet_runoff + 0.38 * dry_dust_runoff) * (1.0 - 0.55 * mass_norm)))
            if lower_runoff > 0.035:
                runoff_mask = np.zeros((height, width), dtype="float32")
                runoff_len = int(height * (0.08 + 0.40 * trail_length) * lower_runoff * (0.85 + 0.35 * (1.0 - mass_norm)))
                runoff_len = max(4, min(height, runoff_len))
                drift = math.sin(angle) * wind_strength * (0.15 + 0.40 * lower_runoff)
                end_x = max(0, min(width - 1, int(round(start_x + drift * runoff_len))))
                end_y = max(0, min(height - 1, start_y + runoff_len))
                runoff_alpha = min(1.0, opacity * (0.16 + 0.42 * lower_runoff))
                runoff_thickness = max(1, int(round(thickness * (0.32 + 0.58 * lower_runoff))))
                cv2.line(
                    runoff_mask,
                    (start_x, start_y),
                    (end_x, end_y),
                    runoff_alpha,
                    thickness=runoff_thickness,
                    lineType=cv2.LINE_AA,
                )
                bottom_start = max(0, min(height - 1, int(round(height * (0.52 + 0.25 * (1.0 - lower_runoff))))))
                if bottom_start < height - 1:
                    gradient = np.linspace(0.0, 1.0, height - bottom_start, dtype="float32")[:, None]
                    x0 = max(0, start_x - int(radius_x * (1.5 + lower_runoff)))
                    x1 = min(width, start_x + int(radius_x * (1.5 + lower_runoff)) + 1)
                    runoff_mask[bottom_start:height, x0:x1] = np.maximum(
                        runoff_mask[bottom_start:height, x0:x1],
                        gradient * runoff_alpha * 0.36,
                    )
                blur = max(3, int(3 + 8 * lower_runoff))
                if blur % 2 == 0:
                    blur += 1
                runoff_mask = cv2.GaussianBlur(runoff_mask, (blur, blur), 0)
                alpha_mask = np.maximum(alpha_mask, np.clip(runoff_mask, 0.0, 1.0))

            if vehicle_speed > 0.015:
                airflow_mask = np.zeros((height, width), dtype="float32")
                impact_point = np.array([float(start_x), float(start_y)], dtype="float32")
                radial = impact_point - center
                radial_norm = float(np.linalg.norm(radial) or 0.0)
                if radial_norm < max(4.0, min(width, height) * 0.035):
                    radial = np.array([_rng_float(rng, -0.35, 0.35), -1.0], dtype="float32")
                    radial_norm = float(np.linalg.norm(radial) or 1.0)
                radial = radial / radial_norm
                wind_bias = np.array([math.sin(angle) * wind_strength, 0.0], dtype="float32")
                flow_dir = radial + wind_bias * (0.08 + 0.18 * vehicle_speed)
                flow_norm = float(np.linalg.norm(flow_dir) or 1.0)
                flow_dir = flow_dir / flow_norm
                flow_angle = math.atan2(float(flow_dir[1]), float(flow_dir[0]))
                fluid_spread = max(0.0, min(1.0, (1.0 - stickiness) * (0.45 + 0.55 * humidity)))
                speed_splash = vehicle_speed * (0.50 + 0.50 * splash_scale) * (0.62 + 0.38 * mass_norm) * (0.65 + 0.85 * fluid_spread + 0.60 * impact_force)
                speed_core_alpha = min(1.0, opacity * (0.24 + 0.88 * vehicle_speed) * (0.58 + 0.42 * mass_norm + 0.34 * impact_force))
                # High vehicle speed is interpreted as impact energy: dense mud balls flatten and can cover characters.
                occluding_blob_count = max(1, int(round(1 + 8 * impact_force + 4 * speed_splash)))
                for _blob in range(occluding_blob_count):
                    distance = _rng_float(rng, 0.0, max(2.0, max(radius_x, radius_y) * (0.35 + 1.40 * impact_force)))
                    lateral = _rng_float(rng, -max(radius_x, radius_y), max(radius_x, radius_y)) * (0.12 + 0.48 * impact_force)
                    blob_x = int(round(start_x + float(flow_dir[0]) * distance - float(flow_dir[1]) * lateral))
                    blob_y = int(round(start_y + float(flow_dir[1]) * distance + float(flow_dir[0]) * lateral))
                    if not (0 <= blob_x < width and 0 <= blob_y < height):
                        continue
                    blob_major = max(1, int(round(max(radius_x, radius_y) * _rng_float(rng, 0.20, 0.82 + 0.78 * impact_force))))
                    blob_minor = max(1, int(round(blob_major * _rng_float(rng, 0.26, 0.70) * (1.0 - 0.24 * fluid_spread))))
                    blob_angle = math.degrees(flow_angle + _rng_float(rng, -0.42, 0.42))
                    cv2.ellipse(
                        airflow_mask,
                        (blob_x, blob_y),
                        (blob_major, blob_minor),
                        blob_angle,
                        0,
                        360,
                        speed_core_alpha * _rng_float(rng, 0.42, 0.98),
                        -1,
                        lineType=cv2.LINE_AA,
                    )
                ray_count = max(1 + int(round(2 * vehicle_speed)), int(round(2 + 12 * speed_splash + 10 * impact_force)))
                spread = math.radians(7.0 + 34.0 * (1.0 - vehicle_speed) + 18.0 * splash_scale + 22.0 * fluid_spread)
                speed_alpha = opacity * (0.14 + 0.84 * vehicle_speed) * (0.58 + 0.42 * mass_norm) * (0.70 + 0.54 * fluid_spread)
                speed_alpha = max(speed_alpha, 0.06 * vehicle_speed * (0.35 + opacity), speed_core_alpha * (0.36 + 0.32 * impact_force))
                speed_length = int(min(width, height) * (0.05 + 0.50 * vehicle_speed) * (0.82 + 0.18 * trail_length) * (0.48 + 0.52 * mass_norm + 0.35 * impact_force) * (0.72 + 0.72 * fluid_spread))
                speed_length = max(int(4 + 8 * vehicle_speed), min(int(min(width, height) * 0.80), speed_length))
                for _ray in range(ray_count):
                    local_angle = flow_angle + _rng_float(rng, -spread, spread)
                    local_dir = np.array([math.cos(local_angle), math.sin(local_angle)], dtype="float32")
                    local_length = speed_length * _rng_float(rng, 0.45, 1.18)
                    end_x = int(round(start_x + float(local_dir[0]) * local_length))
                    end_y = int(round(start_y + float(local_dir[1]) * local_length))
                    end_x = max(0, min(width - 1, end_x))
                    end_y = max(0, min(height - 1, end_y))
                    ray_thickness = max(1, int(round(thickness * _rng_float(rng, 0.24, 0.78) * (1.0 - 0.35 * fluid_spread))))
                    cv2.line(
                        airflow_mask,
                        (start_x, start_y),
                        (end_x, end_y),
                        speed_alpha * _rng_float(rng, 0.32, 0.95),
                        thickness=ray_thickness,
                        lineType=cv2.LINE_AA,
                    )
                    if _rng_float(rng, 0.0, 1.0) < 0.55:
                        cv2.circle(
                            airflow_mask,
                            (end_x, end_y),
                            max(1, int(round(ray_thickness * _rng_float(rng, 0.6, 1.4)))),
                            speed_alpha * _rng_float(rng, 0.12, 0.38),
                            -1,
                            lineType=cv2.LINE_AA,
                        )
                splashlet_count = max(
                    int(round(1 + 5 * vehicle_speed)),
                    int(round(18 * speed_splash * (0.35 + splash_scale) + 20 * impact_force)),
                )
                for _splashlet in range(splashlet_count):
                    local_angle = flow_angle + _rng_float(rng, -spread * 1.35, spread * 1.35)
                    distance = _rng_float(rng, max(1.0, radius_x * 0.20), max(2.0, speed_length * (0.62 + 0.28 * impact_force)))
                    dot_x = int(round(start_x + math.cos(local_angle) * distance))
                    dot_y = int(round(start_y + math.sin(local_angle) * distance))
                    if not (0 <= dot_x < width and 0 <= dot_y < height):
                        continue
                    dot_radius = max(1, int(round(_rng_float(rng, 0.25, 1.35 + 1.10 * impact_force) * thickness * (0.55 + splash_scale + 0.65 * impact_force))))
                    cv2.circle(
                        airflow_mask,
                        (dot_x, dot_y),
                        dot_radius,
                        speed_alpha * _rng_float(rng, 0.18, 0.62 + 0.32 * impact_force),
                        -1,
                        lineType=cv2.LINE_AA,
                    )
                airflow_blur = max(3, int(1 + 5 * (1.0 - vehicle_speed + humidity * 0.45)))
                if airflow_blur % 2 == 0:
                    airflow_blur += 1
                airflow_mask = cv2.GaussianBlur(airflow_mask, (airflow_blur, airflow_blur), 0)
                alpha_mask = np.maximum(alpha_mask, np.clip(airflow_mask, 0.0, 1.0))

        wash_strength = rain_strength * vehicle_speed
        if wash_strength > 0.015:
            rain_dir = np.array([math.sin(angle) * wind_strength * (0.35 + 0.75 * (1.0 - profile.rain_drop_size)), 1.0], dtype="float32")
            rain_norm = float(np.linalg.norm(rain_dir) or 1.0)
            rain_dir = rain_dir / rain_norm
            washed = np.zeros_like(alpha_mask)
            steps = max(2, int(round(2 + 7 * wash_strength)))
            for step in range(1, steps + 1):
                decay = 1.0 - (step / float(steps + 1))
                distance = step * (2.0 + 9.0 * wash_strength)
                transform = np.float32([[1, 0, float(rain_dir[0]) * distance], [0, 1, float(rain_dir[1]) * distance]])
                shifted = cv2.warpAffine(
                    alpha_mask,
                    transform,
                    (width, height),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=0,
                )
                washed = np.maximum(washed, shifted * (0.10 + 0.55 * decay) * wash_strength)
            alpha_mask = np.clip((alpha_mask * (1.0 - 0.42 * wash_strength)) + washed, 0.0, 1.0)

        dirt_color = np.array([32.0, 45.0, 68.0], dtype="float32")
        alpha = np.clip(alpha_mask, 0.0, 1.0)[:, :, None]
        out = image.astype("float32")
        out = out * (1.0 - alpha) + dirt_color * alpha
        result = np.clip(out, 0, 255).astype("uint8")
        return (result, np.clip(alpha_mask, 0.0, 1.0)) if return_mask else result
    except Exception:
        return (image, None) if return_mask else image


def _apply_dark_relief_effect(image, profile: AugmentationProfile, extra_height_mask=None) -> object:
    if np is None or cv2 is None or profile.dark_relief_strength <= 0:
        return image

    try:
        strength = max(0.0, min(3.0, float(profile.dark_relief_strength)))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Dark text/stains become a soft height map; bright regions stay flat.
        dark_mask = 1.0 - (gray.astype("float32") / 255.0)
        dark_mask = np.clip((dark_mask - 0.18) / 0.58, 0.0, 1.0)
        soft_mask = cv2.GaussianBlur(dark_mask, (0, 0), sigmaX=1.0, sigmaY=1.0)
        mud_mask = None
        if extra_height_mask is not None:
            mud_mask = np.asarray(extra_height_mask, dtype="float32")
            if mud_mask.shape[:2] != soft_mask.shape[:2]:
                mud_mask = cv2.resize(mud_mask, (soft_mask.shape[1], soft_mask.shape[0]), interpolation=cv2.INTER_LINEAR)
            mud_mask = np.clip(mud_mask, 0.0, 1.0)
            mud_mask = cv2.GaussianBlur(mud_mask, (0, 0), sigmaX=0.55, sigmaY=0.55)
            soft_mask = np.clip((soft_mask * 0.70) + (mud_mask * 1.60), 0.0, 1.0)

        grad_x = cv2.Sobel(soft_mask, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(soft_mask, cv2.CV_32F, 0, 1, ksize=3)
        angle = math.radians(float(profile.dark_relief_light_angle or 0.0) % 360.0)
        light_x = math.cos(angle)
        light_y = -math.sin(angle)
        light = -((grad_x * light_x) + (grad_y * light_y))
        max_abs = float(np.max(np.abs(light)) or 0.0)
        if max_abs > 0:
            light = light / max_abs

        edge_mask = np.clip(np.abs(grad_x) + np.abs(grad_y), 0.0, 1.0)
        edge_mask = cv2.GaussianBlur(edge_mask, (0, 0), sigmaX=0.75, sigmaY=0.75)
        if mud_mask is not None:
            mud_grad_x = cv2.Sobel(mud_mask, cv2.CV_32F, 1, 0, ksize=3)
            mud_grad_y = cv2.Sobel(mud_mask, cv2.CV_32F, 0, 1, ksize=3)
            mud_edge = np.clip(np.abs(mud_grad_x) + np.abs(mud_grad_y), 0.0, 1.0)
            mud_edge = cv2.GaussianBlur(mud_edge, (0, 0), sigmaX=0.45, sigmaY=0.45)
            edge_mask = np.clip(edge_mask + (mud_edge * 1.75), 0.0, 1.0)
        bump_boost = 1.65 if mud_mask is not None else 1.0
        relief_mask = np.clip((soft_mask * 0.45) + (edge_mask * 1.55), 0.0, 1.0)
        front_light = np.clip(light, 0.0, 1.0)[:, :, None] * (150.0 * strength * bump_boost) * relief_mask[:, :, None]
        edge_highlight = np.clip(light, 0.0, 1.0) * edge_mask * np.clip(soft_mask + edge_mask, 0.0, 1.0)
        edge_highlight = cv2.GaussianBlur(edge_highlight, (0, 0), sigmaX=0.35 + 0.45 * strength, sigmaY=0.35 + 0.45 * strength)
        edge_highlight = edge_highlight[:, :, None] * (38.0 * strength * bump_boost)

        shadow_dx = int(round(-light_x * (1.0 + 4.0 * strength)))
        shadow_dy = int(round(-light_y * (1.0 + 4.0 * strength)))
        transform = np.float32([[1, 0, shadow_dx], [0, 1, shadow_dy]])
        cast_shadow = cv2.warpAffine(
            edge_mask,
            transform,
            (edge_mask.shape[1], edge_mask.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        cast_shadow = cv2.GaussianBlur(cast_shadow, (0, 0), sigmaX=1.2 + 1.8 * strength, sigmaY=1.2 + 1.8 * strength)
        contour_shadow = cast_shadow[:, :, None] * (110.0 * strength * bump_boost)

        out = image.astype("float32") + front_light + edge_highlight - contour_shadow
        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _apply_overhang_shadow_effect(image, profile: AugmentationProfile, rng) -> object:
    """Simulate a soft top shadow cast by a bodywork lip above the plate."""
    if np is None or cv2 is None:
        return image

    try:
        strength = max(0.0, min(1.0, float(getattr(profile, "overhang_shadow_strength", 0.0) or 0.0)))
        if strength <= 0.001:
            return image
        height, width = image.shape[:2]
        if height < 8 or width < 8:
            return image

        angle = math.radians(float(getattr(profile, "dark_relief_light_angle", 135.0) or 0.0) % 360.0)
        # In the existing light model, angle 90 deg means rays coming from the top.
        top_light = max(0.0, math.sin(angle))
        if top_light <= 0.015:
            return image

        max_depth = max(0.0, min(0.60, float(getattr(profile, "overhang_shadow_depth", 0.60) if getattr(profile, "overhang_shadow_depth", None) is not None else 0.60)))
        manual_skew = max(-1.0, min(1.0, float(getattr(profile, "overhang_shadow_skew", 0.0) or 0.0)))
        depth_ratio = max_depth * (0.18 + 0.82 * top_light)
        if depth_ratio <= 0.002:
            return image

        yy, xx = np.mgrid[0:height, 0:width].astype("float32")
        centered_x = (xx / max(1.0, float(width - 1))) - 0.5
        side_light = math.cos(angle)
        random_tilt = _rng_float(rng, -0.08, 0.08)
        tilt = (side_light * 0.12 + manual_skew * 0.42 + random_tilt) * height * depth_ratio
        wave_phase = _rng_float(rng, 0.0, math.tau)
        wave_amp = height * (0.006 + 0.026 * depth_ratio) * _rng_float(rng, 0.35, 1.0)
        boundary = (
            height * depth_ratio
            + centered_x * tilt
            + np.sin((xx / max(1.0, width)) * math.tau * _rng_float(rng, 0.55, 1.25) + wave_phase) * wave_amp
        )
        softness = max(2.0, height * (0.025 + 0.075 * (1.0 - top_light) + 0.045 * strength))
        shadow = np.clip((boundary + softness - yy) / max(1.0, softness * 2.0), 0.0, 1.0)
        shadow = shadow * shadow * (3.0 - 2.0 * shadow)
        shadow = cv2.GaussianBlur(shadow.astype("float32"), (0, 0), sigmaX=0.65 + 2.4 * strength, sigmaY=0.85 + 2.8 * strength)

        darken = shadow[:, :, None] * (0.28 + 0.68 * strength) * (0.45 + 0.55 * top_light)
        darken = np.clip(darken, 0.0, 0.86)
        cool = np.array([0.94, 0.91, 0.87], dtype="float32")
        out = image.astype("float32")
        out = out * (1.0 - darken)
        out = out * (1.0 - 0.10 * darken) + (out * cool) * (0.10 * darken)
        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _apply_plate_reflectance_effect(image, profile: AugmentationProfile, rng) -> object:
    """Approximate uneven reflectance of a slightly curved license plate."""
    if np is None or cv2 is None:
        return image

    try:
        gradient_strength = max(0.0, min(2.0, float(getattr(profile, "plate_reflect_gradient_strength", 0.0) or 0.0)))
        glare_strength = max(0.0, min(2.0, float(getattr(profile, "plate_reflect_glare_strength", 0.0) or 0.0)))
        curve_strength = max(0.0, min(2.0, float(getattr(profile, "plate_reflect_curve_strength", 0.0) or 0.0)))
        if gradient_strength <= 0.001 and glare_strength <= 0.001 and curve_strength <= 0.001:
            return image

        height, width = image.shape[:2]
        if height < 8 or width < 8:
            return image

        angle = math.radians(float(getattr(profile, "dark_relief_light_angle", 135.0) or 0.0) % 360.0)
        camera_axis = max(0.0, min(1.0, float(getattr(profile, "light_normal_strength", 0.0) or 0.0)))
        light_x = math.cos(angle)
        light_y = -math.sin(angle)

        yy, xx = np.mgrid[0:height, 0:width].astype("float32")
        nx = (xx / max(1.0, float(width - 1))) * 2.0 - 1.0
        ny = (yy / max(1.0, float(height - 1))) * 2.0 - 1.0
        axis = nx * light_x + ny * light_y
        axis_extent = float(np.max(np.abs(axis)) or 1.0)
        axis = axis / axis_extent

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype("float32") / 255.0
        bright_mask = np.clip((gray - 0.36) / 0.54, 0.0, 1.0)
        bright_mask = cv2.GaussianBlur(bright_mask, (0, 0), sigmaX=0.75, sigmaY=0.75)
        surface_mask = np.clip(0.35 + 0.65 * bright_mask, 0.0, 1.0)

        dark_side = np.clip(-axis, 0.0, 1.0)
        light_side = np.clip(axis, 0.0, 1.0)
        out = image.astype("float32")
        if gradient_strength > 0.001:
            gradient_gain = min(1.0, gradient_strength / 2.0)
            darken = dark_side[:, :, None] * surface_mask[:, :, None] * (0.12 + 0.46 * gradient_gain)
            brighten = light_side[:, :, None] * bright_mask[:, :, None] * (0.10 + 0.38 * gradient_gain) * (0.50 + 0.70 * camera_axis)
            out = out * (1.0 - darken)
            out = out + (255.0 - out) * np.clip(brighten, 0.0, 0.58)

        if curve_strength > 0.001:
            curve_gain = min(1.0, curve_strength / 2.0)
            horizontal_curve = np.clip(nx * nx, 0.0, 1.0)
            ridge_center = np.clip(light_x * 0.34 + curve_gain * 0.12 * math.sin(angle), -0.72, 0.72)
            ridge_sigma = max(0.11, 0.32 - 0.14 * curve_gain)
            curved_ridge = np.exp(-((nx - ridge_center) ** 2) / (2.0 * ridge_sigma * ridge_sigma)).astype("float32")
            edge_falloff = np.clip(horizontal_curve * surface_mask, 0.0, 1.0)
            ridge_light = np.clip(curved_ridge * bright_mask * (0.16 + 0.48 * curve_gain) * (0.45 + 0.75 * camera_axis), 0.0, 0.72)
            curve_shadow = np.clip(edge_falloff * (0.05 + 0.20 * curve_gain) * (0.55 + 0.45 * abs(light_x)), 0.0, 0.32)
            out = out * (1.0 - curve_shadow[:, :, None])
            out = out + (255.0 - out) * ridge_light[:, :, None]

        if glare_strength > 0.001:
            # A shallow camera angle turns bright plate areas into a broad reflector.
            glare_gain = min(1.0, glare_strength / 2.0)
            curve_gain = min(1.0, curve_strength / 2.0)
            acute_factor = 0.30 + 1.15 * camera_axis
            curve = curve_gain * (0.72 * (nx * nx - 0.34) + 0.24 * np.sin(nx * math.pi * 1.25 + _rng_float(rng, -0.45, 0.45)))
            skew = light_x * (0.34 + 0.18 * curve_gain)
            band_center = (-0.22 + 0.44 * math.sin(angle)) + curve + skew * nx
            sigma = 0.20 - 0.10 * camera_axis + 0.05 * (1.0 - glare_gain) + 0.05 * curve_gain
            sigma = max(0.045, sigma)
            band = np.exp(-((ny - band_center) ** 2) / (2.0 * sigma * sigma)).astype("float32")
            broad_curve = np.exp(-((ny - curve * 0.65) ** 2) / (2.0 * (sigma * 2.55) ** 2)).astype("float32")
            specular = np.clip((band * (0.92 + 1.25 * curve_gain) + broad_curve * (0.28 + 0.32 * curve_gain)) * bright_mask, 0.0, 1.0)
            specular = cv2.GaussianBlur(specular, (0, 0), sigmaX=1.0 + 3.8 * curve_gain, sigmaY=0.55 + 2.1 * curve_gain)
            specular *= (0.70 + 1.15 * glare_gain) * acute_factor
            tint = np.array([242.0, 248.0, 255.0], dtype="float32")
            out = out + (tint - out) * np.clip(specular[:, :, None] * 1.05, 0.0, 0.92)
            veil = cv2.GaussianBlur(specular, (0, 0), sigmaX=3.0 + 7.0 * glare_gain, sigmaY=1.4 + 4.2 * glare_gain)
            out = out + (255.0 - out) * np.clip(veil[:, :, None] * (0.16 + 0.38 * camera_axis), 0.0, 0.52)

        return np.clip(out, 0, 255).astype("uint8")
    except Exception:
        return image


def _apply_image_postprocess(image, profile: AugmentationProfile, rng=None, *, return_debug: bool = False) -> object:
    profile = (profile or AugmentationProfile()).normalized()
    rng = rng or random.Random(profile.seed)
    base_seed = int(rng.randint(1, 2_147_483_647))

    def effect_rng(offset: int) -> random.Random:
        return random.Random((base_seed + int(offset)) % 2_147_483_647 or 1)

    out = image
    needs_relief_mask = bool(
        float(getattr(profile, "dark_relief_strength", 0.0) or 0.0) > 0.001
        or float(getattr(profile, "light_normal_strength", 0.0) or 0.0) > 0.001
        or float(getattr(profile, "wet_mud_gloss_strength", 0.0) or 0.0) > 0.001
    )
    out = _apply_night_effect(out, profile)
    out = _apply_overexposure_effect(out, profile, effect_rng(101))
    out = _apply_dirt_streak_effect(out, profile, effect_rng(211))
    dirt_result = _apply_physical_dirt_flow_effect(out, profile, effect_rng(307), return_mask=needs_relief_mask)
    if needs_relief_mask:
        out, dirt_bump_mask = dirt_result
    else:
        out = dirt_result
        dirt_bump_mask = None
    out = _apply_coarse_noise(out, profile, effect_rng(401))
    rain_edge_debug_mask = build_rain_edge_debug_mask(out, profile) if return_debug else None
    rain_result = _apply_rain_effect(out, profile, effect_rng(503), return_mask=needs_relief_mask)
    if needs_relief_mask:
        out, rain_bump_mask = rain_result
    else:
        out = rain_result
        rain_bump_mask = None
    relief_mask = None
    if dirt_bump_mask is not None and rain_bump_mask is not None:
        relief_mask = np.clip(np.maximum(dirt_bump_mask, rain_bump_mask * 0.72), 0.0, 1.0)
    elif dirt_bump_mask is not None:
        relief_mask = dirt_bump_mask
    elif rain_bump_mask is not None:
        relief_mask = np.clip(rain_bump_mask * 0.72, 0.0, 1.0)
    # Relief is a material parameter. Directional light/shadow comes from
    # active R1/R2/R3 headlights, not from a separate global light.
    out = _apply_plate_reflectance_effect(out, profile, effect_rng(575))
    out = _apply_wet_reflection_effect(out, profile, effect_rng(601))
    out = _apply_traffic_headlight_effect(out, profile, effect_rng(625), relief_mask)
    out = _apply_overhang_shadow_effect(out, profile, effect_rng(655))
    out = _apply_camera_glare_effect(out, profile, effect_rng(709))
    if return_debug:
        return out, {"rain_edge_debug_mask": rain_edge_debug_mask}
    return out


def _apply_albumentations_image_effects(image, profile: AugmentationProfile, *, seed: int | None = None) -> object:
    try:
        A = _load_albumentations()
        transform = A.Compose(_build_image_effect_transforms(A, profile))
        if seed is not None:
            _seed_transform(transform, int(seed))
        result = transform(image=image)
        return _apply_direct_image_tuning(result.get("image", image), profile)
    except Exception:
        return image


def _apply_direct_image_tuning(image, profile: AugmentationProfile) -> object:
    """Apply deterministic scene sliders so preview changes match user input."""
    if np is None:
        return image
    try:
        brightness = max(0.0, min(0.25, float(getattr(profile, "brightness_limit", 0.0) or 0.0)))
        contrast = max(0.0, min(0.25, float(getattr(profile, "contrast_limit", 0.0) or 0.0)))
        saturation = max(0.0, min(3.0, float(getattr(profile, "saturation_limit", 1.0) if getattr(profile, "saturation_limit", None) is not None else 1.0)))
        if brightness <= 0.001 and contrast <= 0.001 and abs(saturation - 1.0) <= 0.001:
            return image

        tuned = image.astype("float32", copy=True)
        if contrast > 0.001:
            tuned = (tuned - 127.5) * (1.0 + 2.0 * contrast) + 127.5
        if brightness > 0.001:
            tuned = tuned + 255.0 * brightness
        tuned = np.clip(tuned, 0, 255).astype("uint8")

        if abs(saturation - 1.0) > 0.001 and cv2 is not None:
            if saturation < 1.0:
                gray = cv2.cvtColor(tuned, cv2.COLOR_BGR2GRAY).astype("float32")
                tuned = np.clip(
                    gray[:, :, None] * (1.0 - saturation) + tuned.astype("float32") * saturation,
                    0,
                    255,
                ).astype("uint8")
            else:
                hsv = cv2.cvtColor(tuned, cv2.COLOR_BGR2HSV).astype("float32")
                hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
                tuned = cv2.cvtColor(hsv.astype("uint8"), cv2.COLOR_HSV2BGR)
        return tuned
    except Exception:
        return image


def _build_geometry_transforms(A, profile: AugmentationProfile) -> list:
    transforms = []
    rotation_angle = float(profile.rotation_limit or 0.0)
    if abs(rotation_angle) > 0.001 or profile.translate_limit > 0 or profile.scale_limit > 0:
        try:
            transforms.append(
                A.Affine(
                    rotate=(rotation_angle, rotation_angle),
                    translate_percent=(-profile.translate_limit, profile.translate_limit),
                    scale=(1.0 - profile.scale_limit, 1.0 + profile.scale_limit),
                    shear=(0.0, 0.0),
                    p=1.0,
                )
            )
        except TypeError:
            transforms.append(
                A.ShiftScaleRotate(
                    shift_limit=profile.translate_limit,
                    scale_limit=profile.scale_limit,
                    rotate_limit=(rotation_angle, rotation_angle),
                    p=1.0,
                )
            )

    if not transforms:
        transforms.append(A.NoOp(p=1.0))
    return transforms


def _build_image_effect_transforms(A, profile: AugmentationProfile) -> list:
    transforms = []
    if profile.flare_strength > 0 and hasattr(A, "RandomSunFlare"):
        strength = max(0.0, min(1.0, float(profile.flare_strength)))
        try:
            transforms.append(
                A.RandomSunFlare(
                    flare_roi=(0.0, 0.0, 1.0, 0.65),
                    src_radius=int(70 + 260 * strength),
                    src_color=(255, 245, 215),
                    num_flare_circles_range=(2, max(3, int(3 + 5 * strength))),
                    method="overlay",
                    p=max(0.10, min(0.85, 0.18 + 0.62 * strength)),
                )
            )
        except TypeError:
            transforms.append(A.RandomSunFlare(p=max(0.10, min(0.85, 0.18 + 0.62 * strength))))

    blur_strength = max(0.0, min(1.0, float(getattr(profile, "blur_strength", 0.0) or 0.0)))
    if blur_strength <= 0.001 and bool(getattr(profile, "blur_enabled", False)):
        blur_strength = 0.18
    if blur_strength > 0.001:
        blur_limit = 3 + int(round(8.0 * blur_strength))
        if blur_limit % 2 == 0:
            blur_limit += 1
        blur_limit = max(3, min(11, blur_limit))
        sigma_limit = (0.1, max(0.2, 0.25 + 2.2 * blur_strength))
        try:
            transforms.append(A.GaussianBlur(blur_limit=(3, blur_limit), sigma_limit=sigma_limit, p=1.0))
        except Exception:
            try:
                transforms.append(A.Blur(blur_limit=(3, blur_limit), p=1.0))
            except Exception:
                transforms.append(A.Blur(blur_limit=blur_limit, p=1.0))

    if not transforms:
        transforms.append(A.NoOp(p=1.0))
    return transforms


def _build_transform(profile: AugmentationProfile, *, has_keypoints: bool):
    A = _load_albumentations()
    transforms = _build_geometry_transforms(A, profile)

    bbox_kwargs = {
        "format": "yolo",
        "label_fields": ["class_labels"],
        "min_visibility": 0.0,
    }
    try:
        bbox_params = A.BboxParams(**bbox_kwargs, clip=True, filter_invalid_bboxes=False)
    except TypeError:
        try:
            bbox_params = A.BboxParams(**bbox_kwargs, clip=True)
        except TypeError:
            bbox_params = A.BboxParams(**bbox_kwargs)

    keypoint_params = None
    if has_keypoints:
        keypoint_params = A.KeypointParams(format="xy", remove_invisible=False)

    return A.Compose(
        transforms,
        bbox_params=bbox_params,
        keypoint_params=keypoint_params,
    )


def preview_augmentation_image(image_path: Path, profile: AugmentationProfile) -> tuple[bool, str, dict]:
    """Return RGB original and augmented arrays for the modal preview."""
    if not CV2_AVAILABLE or cv2 is None:
        return False, "OpenCV jest niedostępny, więc podgląd augmentacji nie może zostać wykonany.", {}
    if not is_albumentations_available():
        return False, "Albumentations nie jest zainstalowane. Użyj przycisku doinstalowania w modalu.", {}

    image_path = Path(image_path)
    if not image_path.exists() or not image_path.is_file():
        return False, "Nie znaleziono obrazu do podglądu augmentacji.", {}

    image = cv2.imread(str(image_path))
    if image is None:
        return False, "Nie udało się odczytać obrazu do podglądu augmentacji.", {}

    profile = (profile or AugmentationProfile()).normalized()
    preview_note = ""
    try:
        height, width = image.shape[:2]
        pixel_count = int(width) * int(height)
        if pixel_count > MAX_AUGMENTATION_PREVIEW_PIXELS:
            scale = math.sqrt(MAX_AUGMENTATION_PREVIEW_PIXELS / float(pixel_count))
            resized_w = max(4, int(round(width * scale)))
            resized_h = max(4, int(round(height * scale)))
            image = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
            preview_note = f" Podgląd w skali {scale * 100.0:.0f}% chroni RAM."
    except Exception:
        preview_note = ""
    try:
        A = _load_albumentations()
        geometry_transform = A.Compose(_build_geometry_transforms(A, profile))
        geometry_seed = _stable_preview_seed(image_path, profile)
        _seed_transform(geometry_transform, geometry_seed)
        augmented = geometry_transform(image=image)
        augmented_image = augmented.get("image", image)
        augmented_image = _apply_albumentations_image_effects(
            augmented_image,
            profile,
            seed=geometry_seed,
        )
        augmented_image, debug_payload = _apply_image_postprocess(
            augmented_image,
            profile,
            random.Random(geometry_seed),
            return_debug=True,
        )
    except Exception as exc:
        return False, f"Nie udało się przygotować podglądu augmentacji: {exc}", {}

    try:
        original_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        augmented_rgb = cv2.cvtColor(augmented_image, cv2.COLOR_BGR2RGB)
    except Exception:
        original_rgb = image
        augmented_rgb = augmented_image

    return True, f"Podgląd augmentacji gotowy.{preview_note}", {
        "source": str(image_path),
        "original_rgb": original_rgb,
        "augmented_rgb": augmented_rgb,
        "rain_edge_debug_mask": debug_payload.get("rain_edge_debug_mask") if isinstance(debug_payload, dict) else None,
    }


def _objects_to_albumentations_payload(
    objects: Iterable[YoloObject],
    *,
    width: int,
    height: int,
) -> tuple[list[list[float]], list[int], list[tuple[float, float]], list[list[float | None]]]:
    bboxes: list[list[float]] = []
    class_labels: list[int] = []
    keypoints: list[tuple[float, float]] = []
    visibility_groups: list[list[float | None]] = []

    for obj in objects:
        bboxes.append([_clamp01(value) for value in obj.bbox])
        class_labels.append(int(obj.class_id))
        visibilities: list[float | None] = []
        for kp_x, kp_y, visibility in obj.keypoints:
            keypoints.append((_clamp01(kp_x) * width, _clamp01(kp_y) * height))
            visibilities.append(visibility)
        visibility_groups.append(visibilities)
    return bboxes, class_labels, keypoints, visibility_groups


def _format_augmented_labels(
    *,
    bboxes: list,
    class_labels: list,
    keypoints: list,
    visibility_groups: list[list[float | None]],
    width: int,
    height: int,
    kpt_count: int,
    kpt_dim: int,
) -> list[str]:
    lines: list[str] = []
    keypoint_index = 0
    for obj_idx, bbox in enumerate(bboxes):
        if len(bbox) < 4:
            continue
        try:
            class_id = int(class_labels[obj_idx])
        except Exception:
            class_id = 0

        values: list[str] = [str(class_id)]
        values.extend(_format_float(float(value)) for value in bbox[:4])

        if kpt_count > 0 and kpt_dim >= 2:
            visibilities = visibility_groups[obj_idx] if obj_idx < len(visibility_groups) else []
            for kp_idx in range(kpt_count):
                if keypoint_index >= len(keypoints):
                    return []
                kp_x, kp_y = keypoints[keypoint_index][:2]
                keypoint_index += 1
                values.append(_format_float(float(kp_x) / max(1, width)))
                values.append(_format_float(float(kp_y) / max(1, height)))
                if kpt_dim >= 3:
                    visibility = visibilities[kp_idx] if kp_idx < len(visibilities) else 2.0
                    try:
                        values.append(f"{float(visibility):.0f}")
                    except Exception:
                        values.append("2")

        lines.append(" ".join(values))
    return lines


def _split_variant_stem(stem: str) -> tuple[str, int, int] | None:
    """Return semantic prefix and numeric variant from names like ABC_DEF_001."""
    prefix, sep, variant = str(stem or "").rpartition("_")
    if not sep or not prefix or not variant.isdigit():
        return None
    return prefix, int(variant), len(variant)


def _collect_reserved_dataset_stems(dataset_dir: Path) -> set[str]:
    """Collect all image/label stems so generated variants never replace existing samples."""
    reserved: set[str] = set()
    dataset_dir = Path(dataset_dir)
    image_root = dataset_dir / "images"
    if image_root.exists():
        for image_path in image_root.rglob("*"):
            try:
                if image_path.is_file() and image_path.suffix.lower() in _image_extensions():
                    reserved.add(image_path.stem)
            except Exception:
                continue
    label_root = dataset_dir / "labels"
    if label_root.exists():
        for label_path in label_root.rglob("*.txt"):
            try:
                if label_path.is_file():
                    reserved.add(label_path.stem)
            except Exception:
                continue
    return reserved


def _unique_augmented_paths(
    image_path: Path,
    label_dir: Path,
    index: int,
    reserved_stems: set[str] | None = None,
) -> tuple[Path, Path]:
    image_dir = image_path.parent
    suffix = image_path.suffix or ".jpg"
    stem = image_path.stem
    reserved_stems = reserved_stems if reserved_stems is not None else set()

    def is_candidate_free(candidate_stem: str, candidate_img: Path, candidate_lbl: Path) -> bool:
        if candidate_stem in reserved_stems:
            return False
        return not candidate_img.exists() and not candidate_lbl.exists()

    def reserve(candidate_stem: str, candidate_img: Path, candidate_lbl: Path) -> tuple[Path, Path]:
        reserved_stems.add(candidate_stem)
        return candidate_img, candidate_lbl

    parsed_variant = _split_variant_stem(stem)
    if parsed_variant is not None:
        prefix, source_variant, width = parsed_variant
        counter = max(source_variant + 1, int(index))
        while True:
            candidate_stem = f"{prefix}_{counter:0{max(width, len(str(counter)))}d}"
            candidate_img = image_dir / f"{candidate_stem}{suffix}"
            candidate_lbl = label_dir / f"{candidate_stem}.txt"
            if is_candidate_free(candidate_stem, candidate_img, candidate_lbl):
                return reserve(candidate_stem, candidate_img, candidate_lbl)
            counter += 1

    counter = int(index)
    while True:
        candidate_name = f"{stem}__aug_{counter:04d}{suffix}"
        candidate_stem = Path(candidate_name).stem
        candidate_img = image_dir / candidate_name
        candidate_lbl = label_dir / f"{candidate_stem}.txt"
        if is_candidate_free(candidate_stem, candidate_img, candidate_lbl):
            return reserve(candidate_stem, candidate_img, candidate_lbl)
        counter += 1


def _write_manifest(dataset_dir: Path, payload: dict) -> None:
    manifest_path = Path(dataset_dir) / "augmentation_manifest.json"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def augment_yolo_dataset_train_split(
    dataset_dir: Path,
    profile: AugmentationProfile,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[bool, str, dict]:
    """Create additional augmented samples in images/train and labels/train."""
    dataset_dir = Path(dataset_dir)
    profile = (profile or AugmentationProfile()).normalized()
    stats = {
        "enabled": bool(profile.enabled),
        "generated": 0,
        "skipped": 0,
        "train_before": 0,
        "train_after": 0,
        "sample_pool": 0,
        "profile_jitter": "per_sample_gaussian_small",
    }

    if not profile.enabled or profile.extra_count <= 0:
        return True, "Augmentacja train pominięta.", stats

    if not CV2_AVAILABLE or cv2 is None:
        return False, "OpenCV jest niedostępny, więc augmentacja obrazów nie może zostać wykonana.", stats

    if not is_albumentations_available():
        return False, "Albumentations nie jest zainstalowane. Zainstaluj pakiet albumentations albo wyłącz augmentację.", stats

    config = _load_dataset_config(dataset_dir)
    kpt_count, kpt_dim = _parse_kpt_shape(config)
    has_keypoints = kpt_count > 0 and kpt_dim >= 2
    items = _discover_train_items(dataset_dir)
    stats["train_before"] = len(items)
    if not items:
        return False, "Brak obrazów z etykietami w train, nie ma czego augmentować.", stats

    rng = random.Random(profile.seed)
    pool = list(items)
    rng.shuffle(pool)
    pool = pool[: min(len(pool), profile.sample_size)]
    stats["sample_pool"] = len(pool)
    if not pool:
        return False, "Losowa próbka train jest pusta.", stats

    try:
        _build_transform(profile, has_keypoints=has_keypoints)
    except Exception as exc:
        return False, f"Nie udało się przygotować pipeline Albumentations: {exc}", stats

    label_dir = dataset_dir / "labels" / "train"
    generated_files: list[dict] = []
    reserved_stems = _collect_reserved_dataset_stems(dataset_dir)

    max_attempts = max(profile.extra_count * 10, profile.extra_count + len(pool) * 2)
    attempts = 0
    while stats["generated"] < profile.extra_count and attempts < max_attempts:
        attempts += 1
        if callable(progress_callback):
            progress_callback(stats["generated"], profile.extra_count, "augmentacja")

        image_path, label_path = rng.choice(pool)
        sample_seed = int(rng.randint(1, 2_147_483_647))
        sample_profile = _jitter_augmentation_profile(profile, random.Random(sample_seed))
        image = cv2.imread(str(image_path))
        if image is None:
            stats["skipped"] += 1
            continue

        height, width = image.shape[:2]
        objects = _parse_yolo_label(label_path, kpt_count=kpt_count, kpt_dim=kpt_dim)
        if not objects:
            stats["skipped"] += 1
            continue

        if has_keypoints and any(len(obj.keypoints) != kpt_count for obj in objects):
            stats["skipped"] += 1
            continue

        bboxes, class_labels, keypoints, visibility_groups = _objects_to_albumentations_payload(
            objects,
            width=width,
            height=height,
        )

        try:
            transform = _build_transform(sample_profile, has_keypoints=has_keypoints)
            _seed_transform(transform, sample_seed)
            augmented = transform(
                image=image,
                bboxes=bboxes,
                class_labels=class_labels,
                keypoints=keypoints if has_keypoints else [],
            )
        except Exception as exc:
            logger.debug(f"Augmentacja pominięta dla {image_path.name}: {exc}")
            stats["skipped"] += 1
            continue

        augmented_bboxes = list(augmented.get("bboxes") or [])
        augmented_labels = list(augmented.get("class_labels") or [])
        augmented_keypoints = list(augmented.get("keypoints") or [])
        if len(augmented_bboxes) != len(objects) or len(augmented_labels) != len(objects):
            stats["skipped"] += 1
            continue
        if has_keypoints and len(augmented_keypoints) != len(keypoints):
            stats["skipped"] += 1
            continue

        label_lines = _format_augmented_labels(
            bboxes=augmented_bboxes,
            class_labels=augmented_labels,
            keypoints=augmented_keypoints,
            visibility_groups=visibility_groups,
            width=width,
            height=height,
            kpt_count=kpt_count,
            kpt_dim=kpt_dim,
        )
        if not label_lines:
            stats["skipped"] += 1
            continue

        out_img, out_lbl = _unique_augmented_paths(image_path, label_dir, stats["generated"] + 1, reserved_stems)
        augmented_image = _apply_albumentations_image_effects(
            augmented["image"],
            sample_profile,
            seed=(sample_seed + 31337) % 2_147_483_647,
        )
        augmented_image = _apply_image_postprocess(
            augmented_image,
            sample_profile,
            random.Random((sample_seed + 7919) % 2_147_483_647 or 1),
        )
        if not cv2.imwrite(str(out_img), augmented_image):
            stats["skipped"] += 1
            continue
        out_lbl.write_text("\n".join(label_lines) + "\n", encoding="utf-8")

        stats["generated"] += 1
        generated_files.append(
            {
                "image": str(out_img.relative_to(dataset_dir)),
                "label": str(out_lbl.relative_to(dataset_dir)),
                "source_image": str(image_path.relative_to(dataset_dir)),
                "source_label": str(label_path.relative_to(dataset_dir)),
                "augmentation_seed": sample_seed,
            }
        )

    stats["train_after"] = stats["train_before"] + stats["generated"]
    _write_manifest(
        dataset_dir,
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "dataset_dir": str(dataset_dir),
            "policy": "train_only_no_crop_no_flip_no_strong_deformation",
            "profile_jitter": {
                "enabled": True,
                "mode": "per_sample_gaussian_small",
                "base_profile_is_expected_value": True,
            },
            "profile": asdict(profile),
            "stats": dict(stats),
            "generated_files": generated_files,
        },
    )

    if callable(progress_callback):
        progress_callback(stats["generated"], profile.extra_count, "augmentacja zakończona")

    if stats["generated"] <= 0:
        return (
            False,
            f"Zwiększanie syntetyczne train nie utworzyło żadnego obrazu z planowanych {profile.extra_count}.",
            stats,
        )
    if stats["generated"] < profile.extra_count:
        return (
            True,
            (
                "Zwiększanie syntetyczne train zakończone częściowo: "
                f"dodano {stats['generated']} z {profile.extra_count} obrazów, "
                f"pominięto {stats['skipped']}."
            ),
            stats,
        )
    return (
        True,
        f"Zwiększanie syntetyczne train zakończone: dodano {stats['generated']} obrazów, pominięto {stats['skipped']}.",
        stats,
    )
