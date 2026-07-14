#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modal configuration for train-only dataset augmentation."""

from __future__ import annotations

from pathlib import Path
import math
import random
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ..config import CONFIG, PIL_AVAILABLE, np
from ..training import (
    AugmentationProfile,
    get_albumentations_status,
    preview_augmentation_image,
)

if PIL_AVAILABLE:
    from PIL import Image, ImageTk

try:
    import psutil
except Exception:
    psutil = None


class Step4AugmentationModal:
    """Single modal with settings and side-by-side visual preview."""

    def __init__(
        self,
        master,
        *,
        target: str,
        profile: AugmentationProfile,
        sample_images: list[Path] | None = None,
        sample_pool_limit: int | None = None,
        install_callback=None,
    ):
        self.master = master
        self.target = CONFIG.normalize_task_target(target)
        self.initial_profile = (profile or AugmentationProfile()).normalized()
        self.sample_images = []
        seen_sample_paths: set[str] = set()
        for path in list(sample_images or []):
            candidate = Path(path)
            if not candidate.exists():
                continue
            try:
                key = str(candidate.resolve())
            except Exception:
                key = str(candidate)
            if key in seen_sample_paths:
                continue
            seen_sample_paths.add(key)
            self.sample_images.append(candidate)
        try:
            self.sample_pool_limit = max(1, int(sample_pool_limit or 0))
        except Exception:
            self.sample_pool_limit = 0
        if self.sample_pool_limit <= 0:
            self.sample_pool_limit = max(1, len(self.sample_images)) if self.sample_images else 10000
        self.install_callback = install_callback
        self.result: AugmentationProfile | None = None
        self._photo_refs: list = []
        self._current_sample: Path | None = self.sample_images[0] if self.sample_images else None
        try:
            ui_seed = random.SystemRandom().randint(1, 2_147_483_647)
        except Exception:
            ui_seed = id(self) % 2_147_483_647 or 1
        self._ui_random = random.Random(ui_seed)
        self._sample_shuffle_bag: list[Path] = []
        self._sample_shuffle_scope_key = ""
        self._process_handle = None
        self._memory_snapshot: dict = {}

        self.window = tk.Toplevel(master)
        self.window.title("Syntetyczne zwiększanie datasetu")
        self._configure_modal_window(master)
        self.window.geometry("980x720")
        self.window.minsize(860, 620)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.bind("<Escape>", self._on_escape_key, add="+")
        self.window.bind("<Tab>", self._on_tab_key, add="+")
        self.window.bind("<Return>", self._on_enter_key, add="+")
        self.window.bind("<KP_Enter>", self._on_enter_key, add="+")
        self.window.bind("<space>", self._on_space_key, add="+")
        self.window.bind("<Key-space>", self._on_space_key, add="+")

        initial_sample = max(1, int(self.initial_profile.sample_size or 32))
        initial_sample = min(initial_sample, self.sample_pool_limit)
        self.sample_var = tk.IntVar(value=initial_sample)
        self.extra_var = tk.IntVar(value=int(self.initial_profile.extra_count or 0))
        self._last_valid_sample_size = int(initial_sample)
        self._last_valid_extra_count = max(0, int(self.initial_profile.extra_count or 0))
        self.extra_count_title_var = tk.StringVar()
        self.rotation_var = tk.DoubleVar(value=float(self.initial_profile.rotation_limit or 0.0))
        self.brightness_var = tk.DoubleVar(value=float(self.initial_profile.brightness_limit or 0.0))
        self.contrast_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "contrast_limit", 0.0) or 0.0))
        initial_saturation = getattr(self.initial_profile, "saturation_limit", 1.0)
        if initial_saturation is None:
            initial_saturation = 1.0
        self.saturation_var = tk.DoubleVar(value=float(initial_saturation))
        self.noise_var = tk.DoubleVar(value=float(self.initial_profile.noise_strength or 0.0))
        self.noise_grain_var = tk.IntVar(value=int(self.initial_profile.noise_grain_size or 1))
        self.rain_var = tk.DoubleVar(value=float(self.initial_profile.rain_strength or 0.0))
        initial_drop_size = float(getattr(self.initial_profile, "rain_drop_size", 0.07) or 0.07)
        self.rain_drop_size_var = tk.DoubleVar(value=initial_drop_size)
        self.rain_drop_size_min_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "rain_drop_size_min", initial_drop_size) if getattr(self.initial_profile, "rain_drop_size_min", None) is not None else initial_drop_size))
        self.rain_drop_size_max_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "rain_drop_size_max", initial_drop_size) if getattr(self.initial_profile, "rain_drop_size_max", None) is not None else initial_drop_size))
        self.rain_vector_field_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "rain_vector_field_strength", 0.0) or 0.0))
        self.rain_vortex_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "rain_vortex_strength", 0.0) or 0.0))
        self.rain_alpha_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "rain_alpha", 0.22) if getattr(self.initial_profile, "rain_alpha", None) is not None else 0.22))
        self.rain_lens_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "rain_lens_strength", 0.0) or 0.0))
        self.rain_edge_mist_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "rain_edge_mist_strength", 0.0) or 0.0))
        self.rain_edge_mist_radius_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "rain_edge_mist_radius", 0.45) if getattr(self.initial_profile, "rain_edge_mist_radius", None) is not None else 0.45))
        self.rain_edge_debug_var = tk.BooleanVar(value=False)
        self.tyndall_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "tyndall_strength", 0.55) if getattr(self.initial_profile, "tyndall_strength", None) is not None else 0.55))
        self.wet_reflection_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "wet_reflection_strength", 0.0) or 0.0))
        self.vehicle_speed_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "vehicle_speed", 0.0) or 0.0))
        self.night_var = tk.DoubleVar(value=float(self.initial_profile.night_strength or 0.0))
        self.night_luma_min_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "night_luma_min", 0.56) if getattr(self.initial_profile, "night_luma_min", None) is not None else 0.56))
        self.night_luma_max_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "night_luma_max", 0.92) if getattr(self.initial_profile, "night_luma_max", None) is not None else 0.92))
        self.night_light_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "night_light_strength", 0.0) or 0.0))
        self.night_bloom_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "night_bloom_strength", 0.0) or 0.0))
        self.night_iso_noise_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "night_iso_noise_strength", 0.0) or 0.0))
        self.night_warmth_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "night_light_warmth", 0.35) if getattr(self.initial_profile, "night_light_warmth", None) is not None else 0.35))
        self.traffic_headlight_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_strength", 0.0) or 0.0))
        self.traffic_headlight_count_var = tk.IntVar(value=int(float(getattr(self.initial_profile, "traffic_headlight_count", 3) if getattr(self.initial_profile, "traffic_headlight_count", None) is not None else 3)))
        self.traffic_headlight_1_warmth_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_1_warmth", self.night_warmth_var.get()) if getattr(self.initial_profile, "traffic_headlight_1_warmth", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_1_warmth", -1.0)) >= 0 else self.night_warmth_var.get()))
        self.traffic_headlight_1_r_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_1_r", 1.0) if getattr(self.initial_profile, "traffic_headlight_1_r", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_1_r", -1.0)) >= 0 else 1.0))
        self.traffic_headlight_1_g_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_1_g", 0.88) if getattr(self.initial_profile, "traffic_headlight_1_g", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_1_g", -1.0)) >= 0 else 0.88))
        self.traffic_headlight_1_b_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_1_b", 0.54) if getattr(self.initial_profile, "traffic_headlight_1_b", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_1_b", -1.0)) >= 0 else 0.54))
        self.traffic_headlight_1_cone_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_1_cone", 0.45) if getattr(self.initial_profile, "traffic_headlight_1_cone", None) is not None else 0.45))
        self.traffic_headlight_1_source_radius_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_1_source_radius", 0.08) if getattr(self.initial_profile, "traffic_headlight_1_source_radius", None) is not None else 0.08))
        self.traffic_headlight_source_x_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_source_x", -1.0) if getattr(self.initial_profile, "traffic_headlight_source_x", None) is not None else -1.0))
        self.traffic_headlight_source_y_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_source_y", -1.0) if getattr(self.initial_profile, "traffic_headlight_source_y", None) is not None else -1.0))
        self.traffic_headlight_target_x_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_target_x", -1.0) if getattr(self.initial_profile, "traffic_headlight_target_x", None) is not None else -1.0))
        self.traffic_headlight_target_y_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_target_y", -1.0) if getattr(self.initial_profile, "traffic_headlight_target_y", None) is not None else -1.0))
        self.traffic_headlight_2_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_strength", 0.0) or 0.0))
        self.traffic_headlight_2_warmth_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_warmth", 0.35) if getattr(self.initial_profile, "traffic_headlight_2_warmth", None) is not None else 0.35))
        self.traffic_headlight_2_r_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_r", 1.0) if getattr(self.initial_profile, "traffic_headlight_2_r", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_2_r", -1.0)) >= 0 else 1.0))
        self.traffic_headlight_2_g_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_g", 0.88) if getattr(self.initial_profile, "traffic_headlight_2_g", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_2_g", -1.0)) >= 0 else 0.88))
        self.traffic_headlight_2_b_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_b", 0.54) if getattr(self.initial_profile, "traffic_headlight_2_b", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_2_b", -1.0)) >= 0 else 0.54))
        self.traffic_headlight_2_cone_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_cone", 0.45) if getattr(self.initial_profile, "traffic_headlight_2_cone", None) is not None else 0.45))
        self.traffic_headlight_2_source_radius_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_source_radius", 0.08) if getattr(self.initial_profile, "traffic_headlight_2_source_radius", None) is not None else 0.08))
        self.traffic_headlight_2_source_x_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_source_x", -1.0) if getattr(self.initial_profile, "traffic_headlight_2_source_x", None) is not None else -1.0))
        self.traffic_headlight_2_source_y_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_source_y", -1.0) if getattr(self.initial_profile, "traffic_headlight_2_source_y", None) is not None else -1.0))
        self.traffic_headlight_2_target_x_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_target_x", -1.0) if getattr(self.initial_profile, "traffic_headlight_2_target_x", None) is not None else -1.0))
        self.traffic_headlight_2_target_y_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_2_target_y", -1.0) if getattr(self.initial_profile, "traffic_headlight_2_target_y", None) is not None else -1.0))
        self.traffic_headlight_3_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_strength", 0.0) or 0.0))
        self.traffic_headlight_3_warmth_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_warmth", 0.35) if getattr(self.initial_profile, "traffic_headlight_3_warmth", None) is not None else 0.35))
        self.traffic_headlight_3_r_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_r", 1.0) if getattr(self.initial_profile, "traffic_headlight_3_r", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_3_r", -1.0)) >= 0 else 1.0))
        self.traffic_headlight_3_g_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_g", 0.88) if getattr(self.initial_profile, "traffic_headlight_3_g", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_3_g", -1.0)) >= 0 else 0.88))
        self.traffic_headlight_3_b_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_b", 0.54) if getattr(self.initial_profile, "traffic_headlight_3_b", None) is not None and float(getattr(self.initial_profile, "traffic_headlight_3_b", -1.0)) >= 0 else 0.54))
        self.traffic_headlight_3_cone_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_cone", 0.45) if getattr(self.initial_profile, "traffic_headlight_3_cone", None) is not None else 0.45))
        self.traffic_headlight_3_source_radius_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_source_radius", 0.08) if getattr(self.initial_profile, "traffic_headlight_3_source_radius", None) is not None else 0.08))
        self.traffic_headlight_3_source_x_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_source_x", -1.0) if getattr(self.initial_profile, "traffic_headlight_3_source_x", None) is not None else -1.0))
        self.traffic_headlight_3_source_y_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_source_y", -1.0) if getattr(self.initial_profile, "traffic_headlight_3_source_y", None) is not None else -1.0))
        self.traffic_headlight_3_target_x_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_target_x", -1.0) if getattr(self.initial_profile, "traffic_headlight_3_target_x", None) is not None else -1.0))
        self.traffic_headlight_3_target_y_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "traffic_headlight_3_target_y", -1.0) if getattr(self.initial_profile, "traffic_headlight_3_target_y", None) is not None else -1.0))
        self.traffic_headlight_1_enabled_var = tk.BooleanVar(value=float(self.traffic_headlight_var.get() or 0.0) > 0.001)
        self.traffic_headlight_2_enabled_var = tk.BooleanVar(value=float(self.traffic_headlight_2_var.get() or 0.0) > 0.001)
        self.traffic_headlight_3_enabled_var = tk.BooleanVar(value=float(self.traffic_headlight_3_var.get() or 0.0) > 0.001)
        self.wet_mud_gloss_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "wet_mud_gloss_strength", 0.0) or 0.0))
        self.flare_var = tk.DoubleVar(value=float(self.initial_profile.flare_strength or 0.0))
        self.overexposure_var = tk.DoubleVar(value=float(self.initial_profile.overexposure_strength or 0.0))
        self.dirt_streak_var = tk.DoubleVar(value=float(self.initial_profile.dirt_streak_strength or 0.0))
        legacy_flow_strength = float(self.initial_profile.dirt_flow_strength or 0.0)
        self.dirt_flow_points_var = tk.IntVar(value=int(self.initial_profile.dirt_flow_points or (24 if legacy_flow_strength > 0 else 0)))
        self.dirt_flow_mass_min_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "dirt_flow_mass_min", 0.18) or 0.18))
        self.dirt_flow_mass_max_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "dirt_flow_mass_max", 1.0) or 1.0))
        self.dirt_flow_splash_scale_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_splash_scale))
        self.dirt_flow_trail_length_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_trail_length))
        self.dirt_flow_humidity_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_humidity))
        initial_stickiness = float(getattr(self.initial_profile, "dirt_flow_stickiness", 0.45) if getattr(self.initial_profile, "dirt_flow_stickiness", None) is not None else 0.45)
        self.dirt_flow_stickiness_var = tk.DoubleVar(value=initial_stickiness)
        self.dirt_flow_stickiness_min_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "dirt_flow_stickiness_min", initial_stickiness) if getattr(self.initial_profile, "dirt_flow_stickiness_min", None) is not None else initial_stickiness))
        self.dirt_flow_stickiness_max_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "dirt_flow_stickiness_max", initial_stickiness) if getattr(self.initial_profile, "dirt_flow_stickiness_max", None) is not None else initial_stickiness))
        self.dirt_flow_air_angle_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_air_angle or 0.0))
        self.dirt_flow_wind_strength_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_wind_strength))
        self.dirt_flow_gravity_angle_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_gravity_angle))
        self.dirt_flow_gravity_strength_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_gravity_strength))
        self.dirt_flow_opacity_min_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_opacity_min))
        self.dirt_flow_opacity_max_var = tk.DoubleVar(value=float(self.initial_profile.dirt_flow_opacity_max))
        self.dirt_flow_stop_on_contour_var = tk.BooleanVar(value=bool(getattr(self.initial_profile, "dirt_flow_stop_on_dark_contour", False)))
        self.dark_relief_var = tk.DoubleVar(value=float(self.initial_profile.dark_relief_strength or 0.0))
        self.dark_relief_light_angle_var = tk.DoubleVar(value=float(self.initial_profile.dark_relief_light_angle or 135.0))
        self.light_normal_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "light_normal_strength", 0.0) or 0.0))
        self.overhang_shadow_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "overhang_shadow_strength", 0.0) or 0.0))
        self.overhang_shadow_depth_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "overhang_shadow_depth", 0.60) if getattr(self.initial_profile, "overhang_shadow_depth", None) is not None else 0.60))
        self.overhang_shadow_skew_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "overhang_shadow_skew", 0.0) or 0.0))
        self.plate_reflect_gradient_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "plate_reflect_gradient_strength", 0.0) or 0.0))
        self.plate_reflect_glare_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "plate_reflect_glare_strength", 0.0) or 0.0))
        self.plate_reflect_curve_var = tk.DoubleVar(value=float(getattr(self.initial_profile, "plate_reflect_curve_strength", 0.0) or 0.0))
        initial_blur = float(getattr(self.initial_profile, "blur_strength", 0.0) or 0.0)
        if initial_blur <= 0.001 and bool(getattr(self.initial_profile, "blur_enabled", False)):
            initial_blur = 0.18
        self.blur_strength_var = tk.DoubleVar(value=initial_blur)
        self.blur_var = tk.BooleanVar(value=initial_blur > 0.001)
        default_class = self.initial_profile.class_name or ("plate" if self.target == "plate" else "")
        self.class_var = tk.StringVar(value=default_class)
        self._preview_after_id = None
        self._raw_preview_request_id = 0
        self._raw_preview_worker_running = False
        self._raw_preview_pending = False
        self._vector_tool: str | None = None
        self._vector_drag_start: tuple[int, int] | None = None
        self._vector_drag_end: tuple[int, int] | None = None
        self._vector_positions: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {}
        self._effect_seed = int(getattr(self.initial_profile, "seed", 42) or 42)
        self._active_toolbox = "scene" if self.target == "plate" else "plate_surface"
        self._toolbox_buttons: dict[str, ttk.Button] = {}
        self._toolbox_panel_pos: tuple[int, int] | None = None
        self._toolbox_panel_drag: dict | None = None
        self._toolbox_panel_collapsed = False
        self._range_sync_guard = False
        self._canvas_overlay_regions: list[dict] = []
        self._canvas_slider_drag: dict | None = None
        self._headlight_drag: dict | None = None
        self._headlight_config_index: int | None = None
        self._headlight_panel_pos: tuple[int, int] | None = None
        self._headlight_panel_anchor_index: int | None = None
        self._headlight_panel_drag: dict | None = None
        self._active_headlight_index: int | None = None
        self._headlight_config_hover_index: int | None = None
        self._overlay_redraw_after_id = None
        self._preview_refresh_suspended = False
        self._preview_refresh_dirty = False
        self._preview_zoom = self._default_preview_zoom()
        self._preview_fullscreen = False
        self._preview_pan_x = 0.0
        self._preview_pan_y = 0.0
        self._preview_pan_drag: tuple[int, int, float, float] | None = None
        self._preview_canvas_mappings: dict[int, dict[str, float]] = {}
        self._fullscreen_show_original = False
        self._preview_fullscreen_grid_snapshot: dict[str, dict] = {}
        self._refresh_extra_count_title()

        self._bind_range_guards()
        self._build()
        self._bind_fullscreen_preview_tab_toggle()
        self._bind_realtime_preview()
        self._refresh_dependency_status()
        self._center_window_on_master()
        self._refresh_preview()

    def _configure_modal_window(self, master):
        """Keep the tab blocked while preserving a normal maximizable window."""
        windowing_system = ""
        try:
            windowing_system = str(self.window.tk.call("tk", "windowingsystem") or "")
        except Exception:
            windowing_system = ""

        # On Windows transient dialog windows often lose the normal maximize button.
        if windowing_system != "win32":
            try:
                self.window.transient(master)
            except Exception:
                pass

        try:
            self.window.resizable(True, True)
        except Exception:
            pass
        try:
            self.window.grab_set()
        except Exception:
            pass
        try:
            self.window.lift(master)
        except Exception:
            try:
                self.window.lift()
            except Exception:
                pass

    def _center_window_on_master(self):
        try:
            self.window.update_idletasks()
            width = max(1, int(self.window.winfo_width() or self.window.winfo_reqwidth() or 980))
            height = max(1, int(self.window.winfo_height() or self.window.winfo_reqheight() or 720))
            master = self.master
            master.update_idletasks()
            root_x = int(master.winfo_rootx())
            root_y = int(master.winfo_rooty())
            root_w = int(master.winfo_width() or master.winfo_screenwidth())
            root_h = int(master.winfo_height() or master.winfo_screenheight())
            if root_w <= 1 or root_h <= 1:
                raise ValueError("master geometry not ready")
            x = root_x + max(0, (root_w - width) // 2)
            y = root_y + max(0, (root_h - height) // 2)
        except Exception:
            try:
                width = max(1, int(self.window.winfo_width() or self.window.winfo_reqwidth() or 980))
                height = max(1, int(self.window.winfo_height() or self.window.winfo_reqheight() or 720))
                screen_w = int(self.window.winfo_screenwidth())
                screen_h = int(self.window.winfo_screenheight())
                x = max(0, (screen_w - width) // 2)
                y = max(0, (screen_h - height) // 2)
            except Exception:
                return
        try:
            self.window.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            pass

    def show(self) -> AugmentationProfile | None:
        self.window.wait_window()
        return self.result

    def _bind_fullscreen_preview_tab_toggle(self):
        sequences = ("<Tab>", "<ISO_Left_Tab>", "<Shift-Tab>")

        def bind_tree(widget):
            try:
                for sequence in sequences:
                    widget.bind(sequence, self._on_tab_key, add="+")
            except Exception:
                pass
            try:
                for child in widget.winfo_children():
                    bind_tree(child)
            except Exception:
                pass

        try:
            self.window.bind("<ISO_Left_Tab>", self._on_tab_key, add="+")
            self.window.bind("<Shift-Tab>", self._on_tab_key, add="+")
        except Exception:
            pass
        try:
            for child in self.window.winfo_children():
                bind_tree(child)
        except Exception:
            pass
        canvas = getattr(self, "augmented_canvas", None)
        if canvas is not None:
            try:
                canvas.configure(takefocus=True)
            except Exception:
                pass

    def _build(self):
        self._build_compact_layout()
        return

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            outer,
            text="Syntetyczne zwiększanie datasetu",
            font=("Segoe UI", 14, "bold"),
        )
        title.pack(anchor=tk.W)

        intro = ttk.Label(
            outer,
            text=(
                "Syntetyczne powiększanie zbioru bazuje na efekcie bazowym, "
                "który dostrajasz w edytorze efektów. Program zapisze dodatkowe obrazy "
                "do splitu train; val i test pozostają bez zmian, żeby ocena modelu była uczciwa. "
                "Warianty nie będą kopią 1:1 ustawień z podglądu: dla każdego nowego zdjęcia "
                "zostanie dodany kontrolowany rozrzut parametrów liczony od cech bazowych."
            ),
            justify=tk.LEFT,
            wraplength=920,
        )
        intro.pack(anchor=tk.W, pady=(4, 10))

        dep_row = ttk.Frame(outer)
        dep_row.pack(fill=tk.X, pady=(0, 10))
        self.dep_status_lbl = ttk.Label(dep_row, text="Albumentations: sprawdzam...")
        self.dep_status_lbl.pack(side=tk.LEFT)
        self.dep_install_btn = ttk.Button(dep_row, text="Doinstaluj", command=self._install_dependency)
        self.dep_install_btn.pack(side=tk.LEFT, padx=(10, 0))

        dataset_settings = ttk.LabelFrame(outer, text=" Parametry datasetu ", padding=10)
        dataset_settings.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(dataset_settings, text="Losowa próbka obrazów źródłowych").grid(row=0, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        ttk.Spinbox(dataset_settings, from_=1, to=self.sample_pool_limit, textvariable=self.sample_var, width=8).grid(row=0, column=1, sticky=tk.W, pady=3)
        ttk.Label(dataset_settings, text="Liczba dodatkowych obrazów train").grid(row=0, column=2, sticky=tk.W, padx=(18, 6), pady=3)
        ttk.Spinbox(dataset_settings, from_=0, to=100000, textvariable=self.extra_var, width=8).grid(row=0, column=3, sticky=tk.W, pady=3)
        if self.target == "plate":
            ttk.Label(dataset_settings, text="Nazwa klasy YOLO").grid(row=2, column=0, sticky=tk.W, padx=(0, 6), pady=(8, 0))
            ttk.Entry(dataset_settings, textvariable=self.class_var, width=18).grid(row=2, column=1, sticky=tk.W, pady=(8, 0))
            ttk.Label(dataset_settings, text="Np. plate albo pl.").grid(row=2, column=2, columnspan=2, sticky=tk.W, padx=(18, 0), pady=(8, 0))
        else:
            ttk.Label(
                dataset_settings,
                text="Klasy znaków pozostają zgodne z data.yaml wybranego datasetu.",
            ).grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))
        dataset_settings.columnconfigure(3, weight=1)

        image_settings = ttk.LabelFrame(outer, text=" Parametry obrazu ", padding=10)
        image_settings.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            image_settings,
            text="Te parametry zmieniają wygląd syntetycznych obrazów, ale nie liczbę pozycji w datasecie.",
            justify=tk.LEFT,
            wraplength=880,
        ).grid(row=0, column=0, columnspan=6, sticky=tk.EW, pady=(0, 8))
        ttk.Label(image_settings, text="Obrót").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        ttk.Spinbox(image_settings, from_=-15, to=15, increment=1, textvariable=self.rotation_var, width=6).grid(row=1, column=1, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Jasność").grid(row=1, column=2, sticky=tk.W, padx=(18, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=0.25, increment=0.01, textvariable=self.brightness_var, width=8).grid(row=1, column=3, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Siła szumu").grid(row=1, column=4, sticky=tk.W, padx=(18, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=0.08, increment=0.005, textvariable=self.noise_var, width=8).grid(row=1, column=5, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Kontrast").grid(row=2, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=0.25, increment=0.01, textvariable=self.contrast_var, width=8).grid(row=2, column=1, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Nasycenie").grid(row=2, column=2, sticky=tk.W, padx=(18, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=3.0, increment=0.01, textvariable=self.saturation_var, width=8).grid(row=2, column=3, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Rozmycie").grid(row=2, column=4, sticky=tk.W, padx=(18, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=1.0, increment=0.05, textvariable=self.blur_strength_var, width=8).grid(row=2, column=5, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Ziarno/deszcz").grid(row=3, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        ttk.Spinbox(image_settings, from_=1, to=12, increment=1, textvariable=self.noise_grain_var, width=6).grid(row=3, column=1, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Gęstość deszczu").grid(row=3, column=2, sticky=tk.W, padx=(18, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=1.0, increment=0.05, textvariable=self.rain_var, width=8).grid(row=3, column=3, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Efekt nocy").grid(row=3, column=4, sticky=tk.W, padx=(18, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=1.0, increment=0.05, textvariable=self.night_var, width=8).grid(row=3, column=5, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Przebłyski").grid(row=4, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=1.0, increment=0.05, textvariable=self.flare_var, width=8).grid(row=4, column=1, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Prześwietlenie").grid(row=4, column=2, sticky=tk.W, padx=(18, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=1.0, increment=0.05, textvariable=self.overexposure_var, width=8).grid(row=4, column=3, sticky=tk.W, pady=3)
        ttk.Label(image_settings, text="Brudne zacieki").grid(row=5, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        ttk.Spinbox(image_settings, from_=0.0, to=1.0, increment=0.05, textvariable=self.dirt_streak_var, width=8).grid(row=5, column=1, sticky=tk.W, pady=3)
        image_settings.columnconfigure(5, weight=1)

        preview_shell = ttk.LabelFrame(outer, text=" Podgląd ", padding=10)
        preview_shell.pack(fill=tk.BOTH, expand=True)
        preview_toolbar = ttk.Frame(preview_shell)
        preview_toolbar.pack(fill=tk.X, pady=(0, 8))
        self.preview_status_lbl = ttk.Label(preview_toolbar, text="")
        self.preview_status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(preview_toolbar, text="Losuj obraz", command=self._pick_random_sample).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(preview_toolbar, text="Odśwież podgląd", command=self._refresh_preview).pack(side=tk.RIGHT)

        canvases = ttk.Frame(preview_shell)
        canvases.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(canvases)
        right = ttk.Frame(canvases)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        ttk.Label(left, text="Oryginał").pack(anchor=tk.W)
        ttk.Label(right, text="Po augmentacji").pack(anchor=tk.W)
        self.original_canvas = tk.Canvas(left, bg="#111111", height=280, highlightthickness=0)
        self.augmented_canvas = tk.Canvas(right, bg="#111111", height=280, highlightthickness=0)
        self.original_canvas.pack(fill=tk.BOTH, expand=True)
        self.augmented_canvas.pack(fill=tk.BOTH, expand=True)
        self.original_canvas.bind("<Configure>", lambda _event: self._refresh_preview(redraw_only=True), add="+")
        self.augmented_canvas.bind("<Configure>", lambda _event: self._refresh_preview(redraw_only=True), add="+")

        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(footer, text="Anuluj", command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(footer, text="Zapisz profil i wróć", command=self._accept).pack(side=tk.RIGHT, padx=(0, 8))

    def _build_compact_layout(self):
        self.window.geometry("1160x720")
        self.window.minsize(960, 620)

        outer = ttk.Frame(self.window, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        self.header_frame = header
        header.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="Edytor efekt\u00f3w augmentacji",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky=tk.W)

        dep_row = ttk.Frame(header)
        dep_row.grid(row=0, column=1, sticky=tk.E)
        self.dep_status_lbl = ttk.Label(dep_row, text="Albumentations: sprawdzam...")
        self.dep_status_lbl.pack(side=tk.LEFT)
        self.dep_install_btn = ttk.Button(dep_row, text="Doinstaluj", command=self._install_dependency)
        self.dep_install_btn.pack(side=tk.LEFT, padx=(8, 0))

        effect_intro_label = ttk.Label(
            header,
            text="Dostrój efekt bazowy. Liczbę generowanych obrazów ustawiasz w PZ1.",
            justify=tk.LEFT,
            wraplength=980,
        )
        effect_intro_label.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))

        body = ttk.Frame(outer)
        body.grid(row=1, column=0, sticky=tk.NSEW)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        controls_host = ttk.Frame(body, width=340)
        self.controls_host = controls_host
        controls_host.grid(row=0, column=0, sticky=tk.NS, padx=(0, 10))
        controls_host.grid_propagate(False)
        controls_host.columnconfigure(0, weight=1)
        controls_host.rowconfigure(0, weight=1)

        controls_canvas = tk.Canvas(controls_host, highlightthickness=0, bd=0)
        controls_scrollbar = ttk.Scrollbar(controls_host, orient=tk.VERTICAL, command=controls_canvas.yview)
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.grid(row=0, column=0, sticky=tk.NSEW)
        controls_scrollbar.grid(row=0, column=1, sticky=tk.NS)

        controls = ttk.Frame(controls_canvas)
        controls_window = controls_canvas.create_window((0, 0), window=controls, anchor=tk.NW)
        controls.columnconfigure(0, weight=1)

        def refresh_controls_scroll(_event=None):
            try:
                controls_canvas.configure(scrollregion=controls_canvas.bbox("all"))
            except Exception:
                pass

        def resize_controls_window(event):
            try:
                controls_canvas.itemconfigure(controls_window, width=max(1, int(event.width)))
            except Exception:
                pass

        def scroll_controls(event):
            try:
                if getattr(event, "num", None) == 4:
                    units = -3
                elif getattr(event, "num", None) == 5:
                    units = 3
                else:
                    delta = int(getattr(event, "delta", 0) or 0)
                    units = -1 * int(delta / 120) if delta else 0
                if units:
                    controls_canvas.yview_scroll(units, "units")
                    return "break"
            except Exception:
                return None
            return None

        def bind_controls_scroll_tree(widget):
            try:
                for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    widget.bind(sequence, scroll_controls, add="+")
                for child in widget.winfo_children():
                    bind_controls_scroll_tree(child)
            except Exception:
                pass

        controls.bind("<Configure>", refresh_controls_scroll, add="+")
        controls_canvas.bind("<Configure>", resize_controls_window, add="+")
        self.window.after_idle(lambda: bind_controls_scroll_tree(controls))

        dataset_settings = ttk.LabelFrame(controls, text=" Parametry datasetu ", padding=8)
        dataset_settings.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        dataset_settings.columnconfigure(1, weight=1)
        ttk.Label(
            dataset_settings,
            textvariable=self.extra_count_title_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 5))
        ttk.Label(dataset_settings, text="Liczba nowych zdjęć").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Spinbox(dataset_settings, from_=0, to=100000, textvariable=self.extra_var, width=8).grid(row=1, column=1, sticky=tk.EW, pady=2)
        ttk.Label(dataset_settings, text="dopisz do train").grid(row=1, column=2, sticky=tk.W, padx=(6, 0), pady=2)
        ttk.Label(dataset_settings, text="Baza losowania").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Spinbox(dataset_settings, from_=1, to=self.sample_pool_limit, textvariable=self.sample_var, width=8).grid(row=2, column=1, sticky=tk.EW, pady=2)
        ttk.Label(dataset_settings, text=f"max {self.sample_pool_limit}").grid(row=2, column=2, sticky=tk.W, padx=(6, 0), pady=2)
        if self.target == "plate":
            ttk.Label(dataset_settings, text="Klasa YOLO").grid(row=3, column=0, sticky=tk.W, pady=(6, 0))
            ttk.Entry(dataset_settings, textvariable=self.class_var, width=14).grid(row=3, column=1, sticky=tk.EW, pady=(6, 0))
        else:
            ttk.Label(
                dataset_settings,
                text="Klasy znaków zgodne z data.yaml.",
                wraplength=260,
            ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        dataset_settings.grid_remove()

        image_settings = ttk.LabelFrame(controls, text=" Obraz i deszcz ", padding=6)
        image_settings.grid(row=1, column=0, sticky=tk.EW)
        image_settings.columnconfigure(1, weight=1)
        image_settings.columnconfigure(3, weight=1)

        def spin_cell(row, col, label, variable, from_, to, increment, width=6):
            ttk.Label(image_settings, text=label).grid(row=row, column=col, sticky=tk.W, pady=1, padx=(0, 4))
            ttk.Spinbox(
                image_settings,
                from_=from_,
                to=to,
                increment=increment,
                textvariable=variable,
                width=width,
            ).grid(row=row, column=col + 1, sticky=tk.EW, pady=1, padx=(0, 8 if col == 0 else 0))

        spin_cell(0, 0, "Obrót", self.rotation_var, -15, 15, 1)
        spin_cell(0, 2, "Jasność", self.brightness_var, 0.0, 0.25, 0.01)
        spin_cell(1, 0, "Kontrast", self.contrast_var, 0.0, 0.25, 0.01)
        spin_cell(1, 2, "Nasycenie", self.saturation_var, 0.0, 3.0, 0.01)
        spin_cell(2, 0, "Rozmycie", self.blur_strength_var, 0.0, 1.0, 0.05)
        spin_cell(2, 2, "Szum", self.noise_var, 0.0, 0.08, 0.005)
        spin_cell(3, 0, "Ziarno", self.noise_grain_var, 1, 12, 1)
        spin_cell(3, 2, "Gęstość deszczu", self.rain_var, 0.0, 1.0, 0.05)
        spin_cell(4, 0, "Kropla", self.rain_drop_size_var, 0.0, 1.0, 0.05)

        dirt_flow_settings = ttk.LabelFrame(controls, text=" Błoto i światło ", padding=6)
        dirt_flow_settings.grid(row=2, column=0, sticky=tk.EW, pady=(8, 0))
        dirt_flow_settings.columnconfigure(1, weight=1)
        dirt_flow_settings.columnconfigure(3, weight=1)

        def compact_spin(row, col, label, variable, from_, to, increment, width=6):
            ttk.Label(dirt_flow_settings, text=label).grid(row=row, column=col, sticky=tk.W, pady=1, padx=(0, 4))
            ttk.Spinbox(
                dirt_flow_settings,
                from_=from_,
                to=to,
                increment=increment,
                textvariable=variable,
                width=width,
            ).grid(row=row, column=col + 1, sticky=tk.EW, pady=1, padx=(0, 8 if col == 0 else 0))

        compact_spin(0, 0, "Grudki", self.dirt_flow_points_var, 0, 2000, 1, 6)
        compact_spin(0, 2, "Rozm. plam", self.dirt_flow_splash_scale_var, 0.0, 1.0, 0.05)
        compact_spin(1, 0, "Dł. smug", self.dirt_flow_trail_length_var, 0.0, 1.0, 0.05)
        compact_spin(1, 2, "Wilgoć", self.dirt_flow_humidity_var, 0.0, 1.0, 0.05)
        compact_spin(2, 0, "Krycie min", self.dirt_flow_opacity_min_var, 0.0, 1.0, 0.05)
        compact_spin(2, 2, "Krycie max", self.dirt_flow_opacity_max_var, 0.0, 1.0, 0.05)
        compact_spin(3, 0, "Prędkość/uderzenie", self.vehicle_speed_var, 0.0, 1.0, 0.05)
        compact_spin(3, 2, "Relief bazowy", self.dark_relief_var, 0.0, 3.0, 0.05)
        compact_spin(4, 0, "Oś kamery", self.light_normal_var, 0.0, 1.0, 0.05)

        preview_shell = ttk.LabelFrame(body, text=" Podgląd ", padding=8)
        try:
            image_settings.grid_remove()
            dirt_flow_settings.grid_remove()
        except Exception:
            pass

        domain_info = ttk.LabelFrame(controls, text=" Domena augmentacji ", padding=8)
        domain_info.grid(row=1, column=0, sticky=tk.EW, pady=(8, 0))
        domain_info.columnconfigure(0, weight=1)
        ttk.Label(
            domain_info,
            text=self._domain_info_text(),
            justify=tk.LEFT,
            wraplength=270,
        ).grid(row=0, column=0, sticky=tk.EW)
        controls_host.grid_remove()
        self._effects_controls_panel_hidden = True

        preview_shell.grid(row=0, column=0, sticky=tk.NSEW)
        preview_shell.columnconfigure(0, weight=1)
        preview_shell.rowconfigure(3, weight=1)

        preview_toolbar = ttk.Frame(preview_shell)
        self.preview_toolbar = preview_toolbar
        preview_toolbar.grid(row=0, column=0, sticky=tk.EW, pady=(0, 6))
        preview_toolbar.columnconfigure(0, weight=1)
        self.preview_status_lbl = ttk.Label(preview_toolbar, text="")
        self.preview_status_lbl.grid(row=0, column=0, sticky=tk.EW)
        ttk.Label(
            preview_shell,
            text=(
                "Enter: pełny ekran. TAB: oryginał / efekt. "
                "Ikony na podglądzie: losuj, reset, zoom."
            ),
            justify=tk.LEFT,
            wraplength=780,
        ).grid(row=1, column=0, sticky=tk.W, pady=(0, 6))

        self.toolbox_bar = ttk.Frame(preview_shell)
        self.toolbox_body = ttk.Frame(preview_shell)
        self.toolbox_body.columnconfigure(0, weight=1)
        # Settings are drawn directly on the augmented preview canvas. Keep the
        # Tk frames alive only for compatibility with older refresh paths.
        self._build_toolbox_bar()
        self._render_active_toolbox()

        canvases = ttk.Frame(preview_shell)
        self.canvases_frame = canvases
        canvases.grid(row=3, column=0, sticky=tk.NSEW)
        canvases.columnconfigure(0, weight=1)
        canvases.rowconfigure(0, weight=1)

        right = ttk.Frame(canvases)
        self.left_preview_frame = None
        self.right_preview_frame = right
        right.grid(row=0, column=0, sticky=tk.NSEW)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(right, text="Podgląd efektu").grid(row=0, column=0, sticky=tk.W)
        self.original_canvas = None
        self.augmented_canvas = tk.Canvas(right, bg="#111111", height=320, highlightthickness=0)
        self.augmented_canvas.grid(row=1, column=0, sticky=tk.NSEW)
        self.augmented_canvas.bind("<Configure>", lambda _event: self._refresh_preview(redraw_only=True), add="+")
        self._bind_preview_zoom_canvas(self.augmented_canvas)
        self._bind_vector_canvas(self.augmented_canvas)

        footer = ttk.Frame(outer)
        self.footer_frame = footer
        footer.grid(row=2, column=0, sticky=tk.EW, pady=(8, 0))
        ttk.Button(footer, text="Anuluj", command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(footer, text="Zastosuj", command=self._accept).pack(side=tk.RIGHT, padx=(0, 8))

    def _domain_intro_text(self) -> str:
        if self.target == "plate":
            return "Profil: zdjęcia pojazdu. Priorytet: scena, deszcz, światło."
        return "Profil: tablica/znaki. Priorytet: błoto, relief, lokalne światło."

    def _domain_info_text(self) -> str:
        if self.target == "plate":
            return "Całe zdjęcia pojazdu. Efekty sceny bez lokalnego błota tablicy."
        return "Wycięte tablice i znaki. Efekty lokalne bez deszczu sceny."

    def _domain_toolboxes(self) -> list[tuple[str, str]]:
        if self.target == "plate":
            return [("scene", "Scena"), ("rain", "Deszcz"), ("light", "Noc/światło")]
        return [("plate_surface", "Tablica"), ("mud", "Błoto"), ("light", "Noc/światło")]

    def _build_toolbox_bar(self):
        self._toolbox_buttons = {}
        for child in self.toolbox_bar.winfo_children():
            child.destroy()
        for index, (key, label) in enumerate(self._domain_toolboxes()):
            button = ttk.Button(
                self.toolbox_bar,
                text=("> " if key == self._active_toolbox else "") + label,
                command=lambda selected=key: self._select_toolbox(selected),
            )
            button.grid(row=0, column=index, sticky=tk.W, padx=(0, 6))
            self._toolbox_buttons[key] = button
        ttk.Label(
            self.toolbox_bar,
            text="Wektory: ikony na podglądzie.",
        ).grid(row=0, column=len(self._toolbox_buttons), sticky=tk.W, padx=(10, 0))

    def _select_toolbox(self, key: str):
        if key == self._active_toolbox:
            return
        self._active_toolbox = key
        for item, button in self._toolbox_buttons.items():
            label = next((text for value, text in self._domain_toolboxes() if value == item), item)
            button.configure(text=("> " if item == key else "") + label)
        self._render_active_toolbox()
        self._refresh_preview(redraw_only=True)

    def _render_active_toolbox(self):
        body = getattr(self, "toolbox_body", None)
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()
        shell = ttk.LabelFrame(body, text=f" {self._active_toolbox_title()} ", padding=4)
        shell.grid(row=0, column=0, sticky=tk.EW)
        for column in (1, 3, 5):
            shell.columnconfigure(column, weight=1)

        fields = self._toolbox_fields(self._active_toolbox)
        row = 0
        col = 0
        for field in fields:
            if field.get("type") == "range_slider" and col != 0:
                col = 0
                row += 1
            if field.get("type") == "check":
                ttk.Checkbutton(shell, text=str(field["label"]), variable=field["var"]).grid(
                    row=row,
                    column=col,
                    columnspan=2,
                    sticky=tk.W,
                    padx=(0, 12),
                    pady=2,
                )
            elif field.get("type") == "range":
                self._add_toolbox_range(
                    shell,
                    row,
                    col,
                    str(field["label"]),
                    field["min_var"],
                    field["max_var"],
                    field["from"],
                    field["to"],
                    field["step"],
                    field.get("width", 6),
                )
            elif field.get("type") == "range_slider":
                self._add_toolbox_range_slider(
                    shell,
                    row,
                    0,
                    str(field["label"]),
                    field["min_var"],
                    field["max_var"],
                    field["from"],
                    field["to"],
                    field["step"],
                )
                row += 1
                col = 0
                continue
            elif field.get("type") == "slider":
                self._add_toolbox_slider(
                    shell,
                    row,
                    col,
                    str(field["label"]),
                    field["var"],
                    field["from"],
                    field["to"],
                    field["step"],
                )
            else:
                self._add_toolbox_spin(
                    shell,
                    row,
                    col,
                    str(field["label"]),
                    field["var"],
                    field["from"],
                    field["to"],
                    field["step"],
                    field.get("width", 7),
                )
            col += 2
            if col >= 6:
                col = 0
                row += 1
        if fields:
            return
        ttk.Label(shell, text="Brak ustawień dla tej domeny.").grid(row=0, column=0, sticky=tk.W)

    def _active_toolbox_title(self) -> str:
        return next((label for key, label in self._domain_toolboxes() if key == self._active_toolbox), "Ustawienia")

    def _toolbox_fields(self, key: str) -> list[dict]:
        if key == "scene":
            return [
                {"label": "Obrót", "var": self.rotation_var, "from": -15, "to": 15, "step": 1},
                {"label": "Jasność", "type": "slider", "var": self.brightness_var, "from": 0.0, "to": 0.25, "step": 0.01},
                {"label": "Kontrast", "type": "slider", "var": self.contrast_var, "from": 0.0, "to": 0.25, "step": 0.01},
                {"label": "Nasycenie", "type": "slider", "var": self.saturation_var, "from": 0.0, "to": 3.0, "step": 0.01},
                {"label": "Rozmycie", "type": "slider", "var": self.blur_strength_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Szum", "type": "slider", "var": self.noise_var, "from": 0.0, "to": 0.08, "step": 0.005},
                {"label": "Ziarno", "var": self.noise_grain_var, "from": 1, "to": 12, "step": 1},
            ]
        if key == "rain":
            return [
                {"label": "Gęstość deszczu", "type": "slider", "var": self.rain_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Zakres kropli", "type": "range_slider", "min_var": self.rain_drop_size_min_var, "max_var": self.rain_drop_size_max_var, "from": 0.0, "to": 1.0, "step": 0.005},
                {"label": "Alfa kropli", "type": "slider", "var": self.rain_alpha_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Soczewka kropli", "type": "slider", "var": self.rain_lens_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Pole wektorowe", "type": "slider", "var": self.rain_vector_field_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Wiry lokalne", "type": "slider", "var": self.rain_vortex_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Intensywność mgły", "type": "slider", "var": self.rain_edge_mist_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Promień mgły", "type": "slider", "var": self.rain_edge_mist_radius_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Pokaż wykryte krawędzie", "var": self.rain_edge_debug_var, "type": "check"},
            ]
        if key == "plate_surface":
            return [
                {"label": "Obrót", "var": self.rotation_var, "from": -15, "to": 15, "step": 1},
                {"label": "Jasność", "type": "slider", "var": self.brightness_var, "from": 0.0, "to": 0.25, "step": 0.01},
                {"label": "Kontrast", "type": "slider", "var": self.contrast_var, "from": 0.0, "to": 0.25, "step": 0.01},
                {"label": "Nasycenie", "type": "slider", "var": self.saturation_var, "from": 0.0, "to": 3.0, "step": 0.01},
                {"label": "Rozmycie", "type": "slider", "var": self.blur_strength_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Szum", "type": "slider", "var": self.noise_var, "from": 0.0, "to": 0.08, "step": 0.005},
                {"label": "Ziarno", "var": self.noise_grain_var, "from": 1, "to": 12, "step": 1},
            ]
        if key == "mud":
            return [
                {"label": "Liczba grudek", "var": self.dirt_flow_points_var, "from": 0, "to": 2000, "step": 1, "width": 7},
                {"label": "Zakres masy", "type": "range", "min_var": self.dirt_flow_mass_min_var, "max_var": self.dirt_flow_mass_max_var, "from": 0.05, "to": 2.8, "step": 0.05},
                {"label": "Smugi", "var": self.dirt_flow_trail_length_var, "from": 0.0, "to": 1.0, "step": 0.05},
                {"label": "Wilgoć", "var": self.dirt_flow_humidity_var, "from": 0.0, "to": 1.0, "step": 0.05},
                {"label": "Zakres lepkości", "type": "range_slider", "min_var": self.dirt_flow_stickiness_min_var, "max_var": self.dirt_flow_stickiness_max_var, "from": 0.0, "to": 1.0, "step": 0.05},
                {"label": "Zakres krycia", "type": "range", "min_var": self.dirt_flow_opacity_min_var, "max_var": self.dirt_flow_opacity_max_var, "from": 0.0, "to": 1.0, "step": 0.05},
                {"label": "Stop na konturze znaku", "var": self.dirt_flow_stop_on_contour_var, "type": "check"},
                {"label": "Prędkość/uderzenie", "var": self.vehicle_speed_var, "from": 0.0, "to": 1.0, "step": 0.05},
            ]
        if key == "light":
            fields = [
                {"label": "Noc", "type": "slider", "var": self.night_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Reflektor", "type": "slider", "var": self.night_light_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Poświata", "type": "slider", "var": self.night_bloom_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Efekt Tyndalla", "type": "slider", "var": self.tyndall_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Szum ISO", "type": "slider", "var": self.night_iso_noise_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Barwa światła", "type": "slider", "var": self.night_warmth_var, "from": 0.0, "to": 1.0, "step": 0.01},
                {"label": "Relief bazowy", "type": "slider", "var": self.dark_relief_var, "from": 0.0, "to": 3.0, "step": 0.02},
                {"label": "Oś kamery", "type": "slider", "var": self.light_normal_var, "from": 0.0, "to": 1.0, "step": 0.01},
            ]
            if self.target != "plate":
                fields.extend(
                    [
                        {"label": "Cień daszka", "type": "slider", "var": self.overhang_shadow_var, "from": 0.0, "to": 1.0, "step": 0.01},
                        {"label": "Zasięg cienia", "type": "slider", "var": self.overhang_shadow_depth_var, "from": 0.0, "to": 0.60, "step": 0.01},
                        {"label": "Skos cienia", "type": "slider", "var": self.overhang_shadow_skew_var, "from": -1.0, "to": 1.0, "step": 0.01},
                        {"label": "Gradient odbicia", "type": "slider", "var": self.plate_reflect_gradient_var, "from": 0.0, "to": 1.0, "step": 0.01},
                        {"label": "Odblask tablicy", "type": "slider", "var": self.plate_reflect_glare_var, "from": 0.0, "to": 1.0, "step": 0.01},
                        {"label": "Łuk powierzchni", "type": "slider", "var": self.plate_reflect_curve_var, "from": 0.0, "to": 1.0, "step": 0.01},
                    ]
                )
            if self.target != "plate":
                fields.append(
                    {"label": "Połysk mokrego błota", "type": "slider", "var": self.wet_mud_gloss_var, "from": 0.0, "to": 1.0, "step": 0.01}
                )
            hidden_headlight_vars = {
                id(self.night_light_var),
                id(self.night_warmth_var),
                id(self.traffic_headlight_var),
                id(self.traffic_headlight_1_warmth_var),
                id(self.traffic_headlight_2_var),
                id(self.traffic_headlight_2_warmth_var),
                id(self.traffic_headlight_3_var),
                id(self.traffic_headlight_3_warmth_var),
            }
            unique_fields = []
            seen_vars = set()
            for field in fields:
                variable = field.get("var")
                if variable is not None:
                    key_var = id(variable)
                    if key_var in hidden_headlight_vars:
                        continue
                    if key_var in seen_vars:
                        continue
                    seen_vars.add(key_var)
                unique_fields.append(field)
            fields = unique_fields
            for field in fields:
                if field.get("var") in (
                    self.plate_reflect_gradient_var,
                    self.plate_reflect_glare_var,
                    self.plate_reflect_curve_var,
                ):
                    field["to"] = 2.0
                    field["step"] = 0.02
            return fields
        return []

    def _add_toolbox_spin(self, parent, row: int, col: int, label: str, variable, from_, to, increment, width=7):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky=tk.W, padx=(0, 4), pady=1)
        ttk.Spinbox(
            parent,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=variable,
            width=width,
        ).grid(row=row, column=col + 1, sticky=tk.EW, padx=(0, 8), pady=1)

    def _add_toolbox_range(self, parent, row: int, col: int, label: str, min_var, max_var, from_, to, increment, width=6):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky=tk.W, padx=(0, 4), pady=2)
        pair = ttk.Frame(parent)
        pair.grid(row=row, column=col + 1, sticky=tk.EW, padx=(0, 12), pady=2)
        pair.columnconfigure(0, weight=1)
        pair.columnconfigure(2, weight=1)
        ttk.Spinbox(
            pair,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=min_var,
            width=width,
        ).grid(row=0, column=0, sticky=tk.EW)
        ttk.Label(pair, text=" - ").grid(row=0, column=1, padx=2)
        ttk.Spinbox(
            pair,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=max_var,
            width=width,
        ).grid(row=0, column=2, sticky=tk.EW)

    def _format_toolbox_value(self, value, step) -> str:
        try:
            value = float(value)
            step = float(step)
        except Exception:
            return str(value)
        if step >= 1:
            return str(int(round(value)))
        if step < 0.01:
            return f"{value:.3f}"
        return f"{value:.2f}"

    def _add_toolbox_slider(self, parent, row: int, col: int, label: str, variable, from_, to, increment):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky=tk.W, padx=(0, 4), pady=1)
        box = ttk.Frame(parent)
        box.grid(row=row, column=col + 1, sticky=tk.EW, padx=(0, 8), pady=1)
        box.columnconfigure(0, weight=1)
        value_lbl = ttk.Label(box, text=self._format_toolbox_value(variable.get(), increment), width=5, anchor=tk.E)
        scale = ttk.Scale(
            box,
            from_=from_,
            to=to,
            orient=tk.HORIZONTAL,
            variable=variable,
            command=lambda value, lbl=value_lbl, step=increment: lbl.configure(text=self._format_toolbox_value(value, step)),
        )
        scale.grid(row=0, column=0, sticky=tk.EW)
        value_lbl.grid(row=0, column=1, sticky=tk.E, padx=(4, 0))

    def _add_toolbox_range_slider(self, parent, row: int, col: int, label: str, min_var, max_var, from_, to, increment):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky=tk.NW, padx=(0, 4), pady=1)
        pair = ttk.Frame(parent)
        pair.grid(row=row, column=col + 1, columnspan=5, sticky=tk.EW, padx=(0, 8), pady=1)
        pair.columnconfigure(1, weight=1)

        def add_line(line: int, text: str, variable):
            ttk.Label(pair, text=text, width=3).grid(row=line, column=0, sticky=tk.W)
            value_lbl = ttk.Label(pair, text=self._format_toolbox_value(variable.get(), increment), width=5, anchor=tk.E)
            scale = ttk.Scale(
                pair,
                from_=from_,
                to=to,
                orient=tk.HORIZONTAL,
                variable=variable,
                command=lambda value, lbl=value_lbl, step=increment: lbl.configure(text=self._format_toolbox_value(value, step)),
            )
            scale.grid(row=line, column=1, sticky=tk.EW, pady=0)
            value_lbl.grid(row=line, column=2, sticky=tk.E, padx=(4, 0))

        add_line(0, "od", min_var)
        add_line(1, "do", max_var)

    def _bind_range_guards(self):
        pairs = (
            (self.rain_drop_size_min_var, self.rain_drop_size_max_var, 0.0, 1.0),
            (self.dirt_flow_mass_min_var, self.dirt_flow_mass_max_var, 0.05, 2.8),
            (self.dirt_flow_stickiness_min_var, self.dirt_flow_stickiness_max_var, 0.0, 1.0),
            (self.dirt_flow_opacity_min_var, self.dirt_flow_opacity_max_var, 0.0, 1.0),
        )
        for min_var, max_var, lower, upper in pairs:
            min_var.trace_add(
                "write",
                lambda *_args, a=min_var, b=max_var, lo=lower, hi=upper: self._coerce_range_pair(a, b, lo, hi, "min"),
            )
            max_var.trace_add(
                "write",
                lambda *_args, a=min_var, b=max_var, lo=lower, hi=upper: self._coerce_range_pair(a, b, lo, hi, "max"),
            )

    def _coerce_range_pair(self, min_var, max_var, lower: float, upper: float, changed: str):
        if getattr(self, "_range_sync_guard", False):
            return
        try:
            min_value = float(min_var.get())
            max_value = float(max_var.get())
        except Exception:
            return
        min_value = max(lower, min(upper, min_value))
        max_value = max(lower, min(upper, max_value))
        if min_value > max_value:
            if changed == "min":
                min_value = max_value
            else:
                max_value = min_value
        self._range_sync_guard = True
        try:
            if abs(float(min_var.get()) - min_value) > 1e-9:
                min_var.set(min_value)
            if abs(float(max_var.get()) - max_value) > 1e-9:
                max_var.set(max_value)
        except Exception:
            pass
        finally:
            self._range_sync_guard = False

    def _profile_from_vars(self) -> AugmentationProfile:
        is_plate_dataset = self.target == "plate"
        sample_size = self._read_int_var(
            self.sample_var,
            default=32,
            minimum=1,
            maximum=int(getattr(self, "sample_pool_limit", 10000) or 10000),
            remember_attr="_last_valid_sample_size",
            repair=True,
        )
        extra_count = self._read_int_var(
            self.extra_var,
            default=0,
            minimum=0,
            maximum=100000,
            remember_attr="_last_valid_extra_count",
            repair=True,
        )
        rain_strength = float(self.rain_var.get() or 0.0) if is_plate_dataset else 0.0
        rain_drop_size_min = float(self.rain_drop_size_min_var.get() or 0.0) if is_plate_dataset else 0.0
        rain_drop_size_max = float(self.rain_drop_size_max_var.get() or 0.0) if is_plate_dataset else 0.0
        rain_vector_field = float(self.rain_vector_field_var.get() or 0.0) if is_plate_dataset else 0.0
        rain_vortex = float(self.rain_vortex_var.get() or 0.0) if is_plate_dataset else 0.0
        rain_alpha = float(self.rain_alpha_var.get() or 0.0) if is_plate_dataset else 0.0
        rain_lens = float(self.rain_lens_var.get() or 0.0) if is_plate_dataset else 0.0
        rain_edge_mist = float(self.rain_edge_mist_var.get() or 0.0) if is_plate_dataset else 0.0
        rain_edge_mist_radius = float(self.rain_edge_mist_radius_var.get() or 0.0) if is_plate_dataset else 0.0
        tyndall_strength = float(self.tyndall_var.get() or 0.0) if is_plate_dataset else 0.0
        if rain_drop_size_min > rain_drop_size_max:
            rain_drop_size_min, rain_drop_size_max = rain_drop_size_max, rain_drop_size_min
        rain_drop_size = (rain_drop_size_min + rain_drop_size_max) / 2.0
        light_strength = float(self.dark_relief_var.get() or 0.0)
        light_normal = float(self.light_normal_var.get() or 0.0)
        overhang_shadow = 0.0 if is_plate_dataset else float(self.overhang_shadow_var.get() or 0.0)
        overhang_shadow_depth = 0.60 if is_plate_dataset else float(self.overhang_shadow_depth_var.get() or 0.0)
        overhang_shadow_skew = 0.0 if is_plate_dataset else float(self.overhang_shadow_skew_var.get() or 0.0)
        reflect_gradient = 0.0 if is_plate_dataset else float(self.plate_reflect_gradient_var.get() or 0.0)
        reflect_glare = 0.0 if is_plate_dataset else float(self.plate_reflect_glare_var.get() or 0.0)
        reflect_curve = 0.0 if is_plate_dataset else float(self.plate_reflect_curve_var.get() or 0.0)
        night_light = float(self.night_light_var.get() or 0.0)
        night_bloom = float(self.night_bloom_var.get() or 0.0)
        night_iso_noise = float(self.night_iso_noise_var.get() or 0.0)
        night_warmth = float(self.night_warmth_var.get() or 0.0)
        traffic_headlight_raw = float(self.traffic_headlight_var.get() or 0.0)
        traffic_headlight = traffic_headlight_raw if self._headlight_effect_enabled(1) else 0.0
        traffic_headlight_1_warmth = float(self.traffic_headlight_1_warmth_var.get() or 0.0)
        traffic_headlight_1_r = float(self.traffic_headlight_1_r_var.get() or 0.0)
        traffic_headlight_1_g = float(self.traffic_headlight_1_g_var.get() or 0.0)
        traffic_headlight_1_b = float(self.traffic_headlight_1_b_var.get() or 0.0)
        traffic_headlight_1_cone = float(self.traffic_headlight_1_cone_var.get() or 0.45)
        traffic_headlight_1_source_radius = float(self.traffic_headlight_1_source_radius_var.get() or 0.0)
        traffic_headlight_2_raw = float(self.traffic_headlight_2_var.get() or 0.0)
        traffic_headlight_2 = traffic_headlight_2_raw if self._headlight_effect_enabled(2) else 0.0
        traffic_headlight_2_warmth = float(self.traffic_headlight_2_warmth_var.get() or 0.0)
        traffic_headlight_2_r = float(self.traffic_headlight_2_r_var.get() or 0.0)
        traffic_headlight_2_g = float(self.traffic_headlight_2_g_var.get() or 0.0)
        traffic_headlight_2_b = float(self.traffic_headlight_2_b_var.get() or 0.0)
        traffic_headlight_2_cone = float(self.traffic_headlight_2_cone_var.get() or 0.45)
        traffic_headlight_2_source_radius = float(self.traffic_headlight_2_source_radius_var.get() or 0.0)
        traffic_headlight_3_raw = float(self.traffic_headlight_3_var.get() or 0.0)
        traffic_headlight_3 = traffic_headlight_3_raw if self._headlight_effect_enabled(3) else 0.0
        traffic_headlight_3_warmth = float(self.traffic_headlight_3_warmth_var.get() or 0.0)
        traffic_headlight_3_r = float(self.traffic_headlight_3_r_var.get() or 0.0)
        traffic_headlight_3_g = float(self.traffic_headlight_3_g_var.get() or 0.0)
        traffic_headlight_3_b = float(self.traffic_headlight_3_b_var.get() or 0.0)
        traffic_headlight_3_cone = float(self.traffic_headlight_3_cone_var.get() or 0.45)
        traffic_headlight_3_source_radius = float(self.traffic_headlight_3_source_radius_var.get() or 0.0)
        traffic_headlight_count = sum(1 for value in (traffic_headlight, traffic_headlight_2, traffic_headlight_3) if value > 0.001)
        wet_mud_gloss = 0.0 if is_plate_dataset else float(self.wet_mud_gloss_var.get() or 0.0)
        # Legacy fields stay at defaults for old profile compatibility; they
        # no longer control the night effect.
        night_luma_min = 0.56
        night_luma_max = 0.92
        wet_reflection_strength = max(0.0, min(1.0, rain_strength * light_strength * (0.80 + 0.60 * light_normal))) if is_plate_dataset else 0.0
        flare_strength = max(0.0, min(1.0, (light_strength - 0.58) * light_normal * 0.36))
        overexposure_strength = max(0.0, min(1.0, (light_strength - 0.62) * light_normal * 0.46))
        dirt_flow_points = 0 if is_plate_dataset else int(float(self.dirt_flow_points_var.get() or 0))
        dirt_flow_mass_min = 0.18 if is_plate_dataset else float(self.dirt_flow_mass_min_var.get() or 0.18)
        dirt_flow_mass_max = 1.0 if is_plate_dataset else float(self.dirt_flow_mass_max_var.get() or 1.0)
        dirt_flow_splash_scale = 0.65 if not is_plate_dataset else 0.0
        dirt_flow_trail_length = 0.0 if is_plate_dataset else float(self.dirt_flow_trail_length_var.get() or 0.0)
        dirt_flow_humidity = 0.0 if is_plate_dataset else float(self.dirt_flow_humidity_var.get() or 0.0)
        dirt_flow_stickiness_min = 0.0 if is_plate_dataset else float(self.dirt_flow_stickiness_min_var.get() or 0.0)
        dirt_flow_stickiness_max = 0.0 if is_plate_dataset else float(self.dirt_flow_stickiness_max_var.get() or 0.0)
        if dirt_flow_stickiness_min > dirt_flow_stickiness_max:
            dirt_flow_stickiness_min, dirt_flow_stickiness_max = dirt_flow_stickiness_max, dirt_flow_stickiness_min
        dirt_flow_stickiness = (dirt_flow_stickiness_min + dirt_flow_stickiness_max) / 2.0
        dirt_flow_opacity_min = 0.0 if is_plate_dataset else float(self.dirt_flow_opacity_min_var.get() or 0.0)
        dirt_flow_opacity_max = 0.0 if is_plate_dataset else float(self.dirt_flow_opacity_max_var.get() or 0.0)
        has_visible_effect = any(
            [
                abs(float(self.rotation_var.get() or 0.0)) > 0.001,
                float(self.brightness_var.get() or 0.0) > 0.001,
                float(self.contrast_var.get() or 0.0) > 0.001,
                abs(float(self.saturation_var.get() if self.saturation_var.get() is not None else 1.0) - 1.0) > 0.001,
                float(self.blur_strength_var.get() or 0.0) > 0.001,
                float(self.noise_var.get() or 0.0) > 0.001,
                rain_strength > 0.001,
                rain_strength > 0.001 and rain_vector_field > 0.001,
                rain_strength > 0.001 and rain_vortex > 0.001,
                rain_strength > 0.001 and rain_lens > 0.001,
                rain_strength > 0.001 and rain_edge_mist > 0.001,
                rain_strength > 0.001 and tyndall_strength > 0.001 and any(
                    value > 0.001 for value in (traffic_headlight, traffic_headlight_2, traffic_headlight_3)
                ),
                float(self.night_var.get() or 0.0) > 0.001,
                night_light > 0.001,
                night_bloom > 0.001,
                night_iso_noise > 0.001,
                traffic_headlight > 0.001,
                traffic_headlight_2 > 0.001,
                traffic_headlight_3 > 0.001,
                wet_mud_gloss > 0.001,
                float(self.vehicle_speed_var.get() or 0.0) > 0.001,
                light_strength > 0.001,
                light_normal > 0.001,
                overhang_shadow > 0.001,
                reflect_gradient > 0.001,
                reflect_glare > 0.001,
                reflect_curve > 0.001,
                dirt_flow_points > 0,
                dirt_flow_trail_length > 0.001,
            ]
        )
        enabled = extra_count > 0 or has_visible_effect
        return AugmentationProfile(
            enabled=enabled,
            sample_size=sample_size,
            extra_count=extra_count,
            rotation_limit=float(self.rotation_var.get() or 0.0),
            translate_limit=0.0,
            scale_limit=0.0,
            brightness_limit=float(self.brightness_var.get() or 0.0),
            contrast_limit=float(self.contrast_var.get() or 0.0),
            saturation_limit=float(self.saturation_var.get() or 0.0),
            noise_strength=float(self.noise_var.get() or 0.0),
            noise_grain_size=int(float(self.noise_grain_var.get() or 1)),
            rain_strength=rain_strength,
            rain_drop_size=rain_drop_size,
            rain_drop_size_min=rain_drop_size_min,
            rain_drop_size_max=rain_drop_size_max,
            rain_vector_field_strength=rain_vector_field,
            rain_vortex_strength=rain_vortex,
            rain_alpha=rain_alpha,
            rain_lens_strength=rain_lens,
            rain_edge_mist_strength=rain_edge_mist,
            rain_edge_mist_radius=rain_edge_mist_radius,
            tyndall_strength=tyndall_strength,
            wet_reflection_strength=wet_reflection_strength,
            vehicle_speed=float(self.vehicle_speed_var.get() or 0.0),
            night_strength=float(self.night_var.get() or 0.0),
            night_luma_min=night_luma_min,
            night_luma_max=night_luma_max,
            night_light_strength=night_light,
            night_bloom_strength=night_bloom,
            night_iso_noise_strength=night_iso_noise,
            night_light_warmth=night_warmth,
            traffic_headlight_strength=traffic_headlight,
            traffic_headlight_count=traffic_headlight_count,
            traffic_headlight_source_x=self._read_float_var(self.traffic_headlight_source_x_var, -1.0),
            traffic_headlight_source_y=self._read_float_var(self.traffic_headlight_source_y_var, -1.0),
            traffic_headlight_target_x=self._read_float_var(self.traffic_headlight_target_x_var, -1.0),
            traffic_headlight_target_y=self._read_float_var(self.traffic_headlight_target_y_var, -1.0),
            traffic_headlight_1_warmth=traffic_headlight_1_warmth,
            traffic_headlight_1_r=traffic_headlight_1_r,
            traffic_headlight_1_g=traffic_headlight_1_g,
            traffic_headlight_1_b=traffic_headlight_1_b,
            traffic_headlight_1_cone=traffic_headlight_1_cone,
            traffic_headlight_1_source_radius=traffic_headlight_1_source_radius,
            traffic_headlight_2_strength=traffic_headlight_2,
            traffic_headlight_2_warmth=traffic_headlight_2_warmth,
            traffic_headlight_2_r=traffic_headlight_2_r,
            traffic_headlight_2_g=traffic_headlight_2_g,
            traffic_headlight_2_b=traffic_headlight_2_b,
            traffic_headlight_2_cone=traffic_headlight_2_cone,
            traffic_headlight_2_source_radius=traffic_headlight_2_source_radius,
            traffic_headlight_2_source_x=self._read_float_var(self.traffic_headlight_2_source_x_var, -1.0),
            traffic_headlight_2_source_y=self._read_float_var(self.traffic_headlight_2_source_y_var, -1.0),
            traffic_headlight_2_target_x=self._read_float_var(self.traffic_headlight_2_target_x_var, -1.0),
            traffic_headlight_2_target_y=self._read_float_var(self.traffic_headlight_2_target_y_var, -1.0),
            traffic_headlight_3_strength=traffic_headlight_3,
            traffic_headlight_3_warmth=traffic_headlight_3_warmth,
            traffic_headlight_3_r=traffic_headlight_3_r,
            traffic_headlight_3_g=traffic_headlight_3_g,
            traffic_headlight_3_b=traffic_headlight_3_b,
            traffic_headlight_3_cone=traffic_headlight_3_cone,
            traffic_headlight_3_source_radius=traffic_headlight_3_source_radius,
            traffic_headlight_3_source_x=self._read_float_var(self.traffic_headlight_3_source_x_var, -1.0),
            traffic_headlight_3_source_y=self._read_float_var(self.traffic_headlight_3_source_y_var, -1.0),
            traffic_headlight_3_target_x=self._read_float_var(self.traffic_headlight_3_target_x_var, -1.0),
            traffic_headlight_3_target_y=self._read_float_var(self.traffic_headlight_3_target_y_var, -1.0),
            wet_mud_gloss_strength=wet_mud_gloss,
            flare_strength=flare_strength,
            overexposure_strength=overexposure_strength,
            dirt_streak_strength=0.0,
            dirt_flow_strength=0.0,
            dirt_flow_points=dirt_flow_points,
            dirt_flow_mass_min=dirt_flow_mass_min,
            dirt_flow_mass_max=dirt_flow_mass_max,
            dirt_flow_splash_scale=dirt_flow_splash_scale,
            dirt_flow_trail_length=dirt_flow_trail_length,
            dirt_flow_humidity=dirt_flow_humidity,
            dirt_flow_stickiness=dirt_flow_stickiness,
            dirt_flow_stickiness_min=dirt_flow_stickiness_min,
            dirt_flow_stickiness_max=dirt_flow_stickiness_max,
            dirt_flow_air_angle=float(self.dirt_flow_air_angle_var.get() or 0.0),
            dirt_flow_wind_strength=float(self.dirt_flow_wind_strength_var.get() or 0.0),
            dirt_flow_gravity_angle=90.0,
            dirt_flow_gravity_strength=1.0,
            dirt_flow_opacity_min=dirt_flow_opacity_min,
            dirt_flow_opacity_max=dirt_flow_opacity_max,
            dirt_flow_stop_on_dark_contour=(False if is_plate_dataset else bool(self.dirt_flow_stop_on_contour_var.get())),
            dark_relief_strength=float(self.dark_relief_var.get() or 0.0),
            dark_relief_light_angle=float(self.dark_relief_light_angle_var.get() or 0.0),
            light_normal_strength=light_normal,
            overhang_shadow_strength=overhang_shadow,
            overhang_shadow_depth=overhang_shadow_depth,
            overhang_shadow_skew=overhang_shadow_skew,
            plate_reflect_gradient_strength=reflect_gradient,
            plate_reflect_glare_strength=reflect_glare,
            plate_reflect_curve_strength=reflect_curve,
            blur_strength=float(self.blur_strength_var.get() or 0.0),
            blur_enabled=float(self.blur_strength_var.get() or 0.0) > 0.001,
            seed=int(getattr(self, "_effect_seed", 42) or 42),
            class_name=str(self.class_var.get() or "").strip(),
        ).normalized()

    def _reset_all_parameters(self):
        self.sample_var.set(min(32, int(getattr(self, "sample_pool_limit", 32) or 32)))
        self.extra_var.set(0)
        self.rotation_var.set(0.0)
        self.brightness_var.set(0.0)
        self.contrast_var.set(0.0)
        self.saturation_var.set(1.0)
        self.noise_var.set(0.0)
        self.noise_grain_var.set(1)
        self.rain_var.set(0.0)
        self.rain_drop_size_var.set(0.07)
        self.rain_drop_size_min_var.set(0.01)
        self.rain_drop_size_max_var.set(0.13)
        self.rain_vector_field_var.set(0.0)
        self.rain_vortex_var.set(0.0)
        self.rain_alpha_var.set(0.22)
        self.rain_lens_var.set(0.0)
        self.rain_edge_mist_var.set(0.0)
        self.rain_edge_mist_radius_var.set(0.45)
        self.rain_edge_debug_var.set(False)
        self.tyndall_var.set(0.55)
        self.wet_reflection_var.set(0.0)
        self.vehicle_speed_var.set(0.0)
        self.night_var.set(0.0)
        self.night_luma_min_var.set(0.56)
        self.night_luma_max_var.set(0.92)
        self.night_light_var.set(0.0)
        self.night_bloom_var.set(0.0)
        self.night_iso_noise_var.set(0.0)
        self.night_warmth_var.set(0.35)
        self.traffic_headlight_var.set(0.0)
        self.traffic_headlight_count_var.set(3)
        self.traffic_headlight_1_warmth_var.set(0.35)
        self.traffic_headlight_1_r_var.set(1.0)
        self.traffic_headlight_1_g_var.set(0.88)
        self.traffic_headlight_1_b_var.set(0.54)
        self.traffic_headlight_1_cone_var.set(0.45)
        self.traffic_headlight_1_source_radius_var.set(0.08)
        self.traffic_headlight_source_x_var.set(-1.0)
        self.traffic_headlight_source_y_var.set(-1.0)
        self.traffic_headlight_target_x_var.set(-1.0)
        self.traffic_headlight_target_y_var.set(-1.0)
        self.traffic_headlight_2_var.set(0.0)
        self.traffic_headlight_2_warmth_var.set(0.35)
        self.traffic_headlight_2_r_var.set(1.0)
        self.traffic_headlight_2_g_var.set(0.88)
        self.traffic_headlight_2_b_var.set(0.54)
        self.traffic_headlight_2_cone_var.set(0.45)
        self.traffic_headlight_2_source_radius_var.set(0.08)
        self.traffic_headlight_2_source_x_var.set(-1.0)
        self.traffic_headlight_2_source_y_var.set(-1.0)
        self.traffic_headlight_2_target_x_var.set(-1.0)
        self.traffic_headlight_2_target_y_var.set(-1.0)
        self.traffic_headlight_3_var.set(0.0)
        self.traffic_headlight_3_warmth_var.set(0.35)
        self.traffic_headlight_3_r_var.set(1.0)
        self.traffic_headlight_3_g_var.set(0.88)
        self.traffic_headlight_3_b_var.set(0.54)
        self.traffic_headlight_3_cone_var.set(0.45)
        self.traffic_headlight_3_source_radius_var.set(0.08)
        self.traffic_headlight_3_source_x_var.set(-1.0)
        self.traffic_headlight_3_source_y_var.set(-1.0)
        self.traffic_headlight_3_target_x_var.set(-1.0)
        self.traffic_headlight_3_target_y_var.set(-1.0)
        self.traffic_headlight_1_enabled_var.set(False)
        self.traffic_headlight_2_enabled_var.set(False)
        self.traffic_headlight_3_enabled_var.set(False)
        self.wet_mud_gloss_var.set(0.0)
        self.flare_var.set(0.0)
        self.overexposure_var.set(0.0)
        self.dirt_streak_var.set(0.0)
        self.dirt_flow_points_var.set(0)
        self.dirt_flow_mass_min_var.set(0.18)
        self.dirt_flow_mass_max_var.set(1.0)
        self.dirt_flow_splash_scale_var.set(0.45)
        self.dirt_flow_trail_length_var.set(0.55)
        self.dirt_flow_humidity_var.set(0.45)
        self.dirt_flow_stickiness_var.set(0.45)
        self.dirt_flow_stickiness_min_var.set(0.30)
        self.dirt_flow_stickiness_max_var.set(0.70)
        self.dirt_flow_air_angle_var.set(0.0)
        self.dirt_flow_wind_strength_var.set(0.45)
        self.dirt_flow_gravity_angle_var.set(90.0)
        self.dirt_flow_gravity_strength_var.set(1.0)
        self.dirt_flow_opacity_min_var.set(0.25)
        self.dirt_flow_opacity_max_var.set(0.80)
        self.dirt_flow_stop_on_contour_var.set(False)
        self.dark_relief_var.set(0.0)
        self.dark_relief_light_angle_var.set(135.0)
        self.light_normal_var.set(0.0)
        self.overhang_shadow_var.set(0.0)
        self.overhang_shadow_depth_var.set(0.60)
        self.overhang_shadow_skew_var.set(0.0)
        self.plate_reflect_gradient_var.set(0.0)
        self.plate_reflect_glare_var.set(0.0)
        self.plate_reflect_curve_var.set(0.0)
        self.blur_strength_var.set(0.0)
        self.blur_var.set(False)
        if self.target == "plate":
            self.class_var.set("plate")
        else:
            self.class_var.set("")
        self._vector_tool = None
        self._vector_drag_start = None
        self._vector_drag_end = None
        self._headlight_drag = None
        self._headlight_config_index = None
        self._headlight_panel_pos = None
        self._headlight_panel_anchor_index = None
        self._vector_positions.clear()
        self._schedule_preview_refresh(delay_ms=40)

    def _refresh_extra_count_title(self):
        count = self._read_int_var(
            self.extra_var,
            default=0,
            minimum=0,
            maximum=100000,
            remember_attr="_last_valid_extra_count",
            repair=False,
        )
        if count == 1:
            noun = "zdjęcie"
        elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
            noun = "zdjęcia"
        else:
            noun = "zdjęć"
        try:
            self.extra_count_title_var.set(f"Generuj dodatkowe {count} {noun} do train")
        except Exception:
            pass

    def _bind_realtime_preview(self):
        watched_vars = (
            self.rotation_var,
            self.brightness_var,
            self.contrast_var,
            self.saturation_var,
            self.noise_var,
            self.noise_grain_var,
            self.rain_var,
            self.rain_drop_size_var,
            self.rain_drop_size_min_var,
            self.rain_drop_size_max_var,
            self.rain_vector_field_var,
            self.rain_vortex_var,
            self.rain_alpha_var,
            self.rain_lens_var,
            self.rain_edge_mist_var,
            self.rain_edge_mist_radius_var,
            self.tyndall_var,
            self.vehicle_speed_var,
            self.night_var,
            self.night_light_var,
            self.night_bloom_var,
            self.night_iso_noise_var,
            self.night_warmth_var,
            self.traffic_headlight_var,
            self.traffic_headlight_count_var,
            self.traffic_headlight_1_warmth_var,
            self.traffic_headlight_1_r_var,
            self.traffic_headlight_1_g_var,
            self.traffic_headlight_1_b_var,
            self.traffic_headlight_1_cone_var,
            self.traffic_headlight_1_source_radius_var,
            self.traffic_headlight_2_var,
            self.traffic_headlight_2_warmth_var,
            self.traffic_headlight_2_r_var,
            self.traffic_headlight_2_g_var,
            self.traffic_headlight_2_b_var,
            self.traffic_headlight_2_cone_var,
            self.traffic_headlight_2_source_radius_var,
            self.traffic_headlight_3_var,
            self.traffic_headlight_3_warmth_var,
            self.traffic_headlight_3_r_var,
            self.traffic_headlight_3_g_var,
            self.traffic_headlight_3_b_var,
            self.traffic_headlight_3_cone_var,
            self.traffic_headlight_3_source_radius_var,
            self.traffic_headlight_1_enabled_var,
            self.traffic_headlight_2_enabled_var,
            self.traffic_headlight_3_enabled_var,
            self.wet_mud_gloss_var,
            self.dirt_flow_points_var,
            self.dirt_flow_mass_min_var,
            self.dirt_flow_mass_max_var,
            self.dirt_flow_splash_scale_var,
            self.dirt_flow_trail_length_var,
            self.dirt_flow_humidity_var,
            self.dirt_flow_stickiness_min_var,
            self.dirt_flow_stickiness_max_var,
            self.dirt_flow_air_angle_var,
            self.dirt_flow_wind_strength_var,
            self.dirt_flow_opacity_min_var,
            self.dirt_flow_opacity_max_var,
            self.dirt_flow_stop_on_contour_var,
            self.dark_relief_var,
            self.dark_relief_light_angle_var,
            self.light_normal_var,
            self.overhang_shadow_var,
            self.overhang_shadow_depth_var,
            self.overhang_shadow_skew_var,
            self.plate_reflect_gradient_var,
            self.plate_reflect_glare_var,
            self.plate_reflect_curve_var,
            self.blur_strength_var,
        )
        for var in watched_vars:
            try:
                var.trace_add("write", lambda *_args: self._schedule_preview_refresh())
            except Exception:
                pass
        try:
            self.extra_var.trace_add("write", lambda *_args: self._refresh_extra_count_title())
        except Exception:
            pass
        try:
            self.rain_edge_debug_var.trace_add("write", lambda *_args: self._refresh_preview(redraw_only=True))
        except Exception:
            pass

    def _schedule_preview_refresh(self, delay_ms: int = 180):
        if bool(getattr(self, "_preview_refresh_suspended", False)):
            self._preview_refresh_dirty = True
            return
        if self._preview_after_id is not None:
            try:
                self.window.after_cancel(self._preview_after_id)
            except Exception:
                pass
            self._preview_after_id = None
        try:
            self._preview_after_id = self.window.after(max(40, int(delay_ms)), self._run_scheduled_preview_refresh)
        except Exception:
            self._preview_after_id = None

    def _run_scheduled_preview_refresh(self):
        self._preview_after_id = None
        self._refresh_preview()

    def _begin_canvas_live_edit(self):
        self._preview_refresh_suspended = True
        self._preview_refresh_dirty = False
        self._cancel_pending_preview()

    def _end_canvas_live_edit(self, delay_ms: int = 80):
        self._preview_refresh_suspended = False
        self._preview_refresh_dirty = False
        self._schedule_preview_refresh(delay_ms=delay_ms)

    def _refresh_dependency_status(self):
        status = get_albumentations_status()
        available = bool(status.get("available"))
        self.dep_status_lbl.configure(text="Albumentations: dostępne" if available else "Albumentations: brak")
        self.dep_install_btn.configure(state=(tk.DISABLED if available else tk.NORMAL))

    def _install_dependency(self):
        if callable(self.install_callback):
            self.install_callback()
        self.dep_install_btn.configure(state=tk.DISABLED)
        self.dep_status_lbl.configure(text="Albumentations: instalacja w toku...")
        self.window.after(1200, self._poll_dependency_after_install)

    def _poll_dependency_after_install(self):
        self._refresh_dependency_status()
        if not bool(get_albumentations_status().get("available")):
            self.window.after(1200, self._poll_dependency_after_install)

    def _preview_sample_candidates(self) -> list[Path]:
        candidates = list(getattr(self, "sample_images", []) or [])
        if not candidates:
            return []
        try:
            limit = int(self.sample_var.get() or 0)
        except Exception:
            limit = 0
        if limit > 0:
            candidates = candidates[: max(1, min(len(candidates), limit))]
        return candidates

    def _preview_candidates_scope_key(self, candidates: list[Path]) -> str:
        if not candidates:
            return ""
        try:
            limit = int(self.sample_var.get() or 0)
        except Exception:
            limit = 0
        sample = list(candidates[:3])
        if len(candidates) > 6:
            sample.extend(candidates[-3:])
        else:
            sample = list(candidates)
        return f"{len(candidates)}|{limit}|" + "|".join(str(path) for path in sample)

    def _pick_random_sample(self):
        candidates = self._preview_sample_candidates()
        if not candidates:
            self.preview_status_lbl.configure(text="Brak obrazów źródłowych do losowania.")
            return
        if len(candidates) == 1:
            self._current_sample = candidates[0]
            self.preview_status_lbl.configure(text=f"{self._current_sample.name} | To jedyna próbka dostępna w podglądzie.")
        else:
            current_sample = self._current_sample
            pool_key = self._preview_candidates_scope_key(candidates)
            if pool_key != self._sample_shuffle_scope_key:
                self._sample_shuffle_scope_key = pool_key
                self._sample_shuffle_bag = []
            self._sample_shuffle_bag = [
                path
                for path in self._sample_shuffle_bag
                if path != current_sample
            ]
            if not self._sample_shuffle_bag:
                self._sample_shuffle_bag = [
                    path
                    for path in candidates
                    if path != current_sample
                ] or list(candidates)
                self._ui_random.shuffle(self._sample_shuffle_bag)
            self._current_sample = self._sample_shuffle_bag.pop()
        if hasattr(self, "_last_preview_payload"):
            try:
                delattr(self, "_last_preview_payload")
            except Exception:
                pass
        try:
            self.preview_status_lbl.configure(text=f"{Path(self._current_sample).name} | Losuję podgląd...")
        except Exception:
            pass
        self._request_raw_sample_preview()
        self._schedule_preview_refresh(delay_ms=900)

    def _request_raw_sample_preview(self):
        self._raw_preview_request_id += 1
        request_id = int(self._raw_preview_request_id)
        self._raw_preview_pending = True
        if self._raw_preview_worker_running:
            return
        self._start_raw_sample_preview_worker(request_id)

    def _start_raw_sample_preview_worker(self, request_id: int):
        sample = getattr(self, "_current_sample", None)
        if sample is None or not PIL_AVAILABLE or np is None:
            return
        try:
            canvas = getattr(self, "augmented_canvas", None)
            canvas_w = max(320, int(canvas.winfo_width() or 640)) if canvas is not None else 640
            canvas_h = max(220, int(canvas.winfo_height() or 420)) if canvas is not None else 420
        except Exception:
            canvas_w, canvas_h = 640, 420
        self._raw_preview_worker_running = True
        self._raw_preview_pending = False
        sample_path = Path(sample)

        def _worker():
            payload = None
            try:
                image = Image.open(sample_path).convert("RGB")
                resampling = getattr(getattr(Image, "Resampling", Image), "BILINEAR", 2)
                image.thumbnail((max(1, canvas_w - 12), max(1, canvas_h - 12)), resampling)
                payload = np.array(image)
            except Exception:
                payload = None

            def _finish():
                self._finish_raw_sample_preview(request_id, sample_path, payload)

            try:
                self.window.after(0, _finish)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_raw_sample_preview(self, request_id: int, sample_path: Path, array):
        self._raw_preview_worker_running = False
        try:
            if not bool(self.window.winfo_exists()):
                return
        except Exception:
            return
        is_current = Path(getattr(self, "_current_sample", "")) == sample_path
        if request_id != int(getattr(self, "_raw_preview_request_id", 0) or 0) or not is_current:
            if bool(getattr(self, "_raw_preview_pending", False)):
                self._start_raw_sample_preview_worker(int(getattr(self, "_raw_preview_request_id", request_id) or request_id))
            return
        if array is not None:
            try:
                self.preview_status_lbl.configure(text=f"{sample_path.name} | Podgląd surowy, efekt renderuje się po chwili.")
            except Exception:
                pass
            self._draw_array(self.augmented_canvas, array)
        if bool(getattr(self, "_raw_preview_pending", False)):
            self._start_raw_sample_preview_worker(int(getattr(self, "_raw_preview_request_id", request_id) or request_id))

    def _reroll_effect_layout(self):
        self._effect_seed = self._ui_random.randint(1, 2_147_483_647)
        self._refresh_preview()

    def _capture_memory_snapshot(self, stage: str = "") -> dict:
        snapshot = {"available": False, "stage": stage}
        if psutil is None:
            self._memory_snapshot = snapshot
            return snapshot
        try:
            process = self._process_handle
            if process is None:
                process = psutil.Process()
                self._process_handle = process
            memory_info = process.memory_info()
            rss = float(memory_info.rss)
            peak_wset = float(getattr(memory_info, "peak_wset", rss) or rss)
            virtual = psutil.virtual_memory()
            snapshot = {
                "available": True,
                "stage": stage,
                "process_mb": rss / (1024.0 * 1024.0),
                "process_peak_mb": peak_wset / (1024.0 * 1024.0),
                "system_total_gb": float(virtual.total) / (1024.0 ** 3),
                "system_used_gb": float(virtual.total - virtual.available) / (1024.0 ** 3),
                "system_free_gb": float(virtual.available) / (1024.0 ** 3),
                "system_percent": float(virtual.percent),
            }
        except Exception:
            snapshot = {"available": False, "stage": stage}
        self._memory_snapshot = snapshot
        return snapshot

    def _format_memory_snapshot(self) -> str:
        snapshot = getattr(self, "_memory_snapshot", {}) or self._capture_memory_snapshot()
        stage = str(snapshot.get("stage") or "")
        prefix = f"{stage}: " if stage else ""
        if not snapshot.get("available"):
            return f"{prefix}RAM: brak danych"
        return (
            f"{prefix}RAM procesu {snapshot.get('process_mb', 0.0):.0f} MB | "
            f"peak {snapshot.get('process_peak_mb', 0.0):.0f} MB | "
            f"system {snapshot.get('system_used_gb', 0.0):.1f}/"
            f"{snapshot.get('system_total_gb', 0.0):.1f} GB "
            f"({snapshot.get('system_percent', 0.0):.0f}%) | "
            f"wolne {snapshot.get('system_free_gb', 0.0):.1f} GB"
        )

    def _refresh_preview(self, redraw_only: bool = False):
        if not redraw_only:
            self._raw_preview_request_id += 1
            self._raw_preview_pending = False
        if not redraw_only and self._preview_after_id is not None:
            try:
                self.window.after_cancel(self._preview_after_id)
            except Exception:
                pass
            self._preview_after_id = None
        if not PIL_AVAILABLE:
            self.preview_status_lbl.configure(text="Podgląd wymaga biblioteki Pillow.")
            return
        if self._current_sample is None:
            self.preview_status_lbl.configure(text="Brak obrazu źródłowego do podglądu. Wskaż źródło datasetu w PZ1.")
            original_canvas = getattr(self, "original_canvas", None)
            if original_canvas is not None:
                self._draw_canvas_message(original_canvas, "Brak obrazu")
            self._draw_canvas_message(self.augmented_canvas, "Brak obrazu")
            return

        if redraw_only and hasattr(self, "_last_preview_payload"):
            payload = getattr(self, "_last_preview_payload", {})
            self._draw_preview_images(payload)
            return

        self._capture_memory_snapshot("przed renderem")
        try:
            self._draw_vector_overlay()
            self.window.update_idletasks()
        except Exception:
            pass
        ok, msg, payload = preview_augmentation_image(self._current_sample, self._profile_from_vars())
        self._capture_memory_snapshot("po renderze")
        self.preview_status_lbl.configure(text=f"{Path(self._current_sample).name} | {msg}")
        if ok:
            self._last_preview_payload = payload
            self._draw_preview_images(payload)
        else:
            original_canvas = getattr(self, "original_canvas", None)
            if original_canvas is not None:
                self._draw_canvas_message(original_canvas, Path(self._current_sample).name)
            self._draw_canvas_message(self.augmented_canvas, msg)

    def _draw_preview_images(self, payload: dict):
        original = payload.get("original_rgb")
        augmented = payload.get("augmented_rgb")
        original_canvas = getattr(self, "original_canvas", None)
        if original_canvas is not None and original is not None:
            self._draw_array(original_canvas, original)
        if augmented is not None:
            if bool(self.rain_edge_debug_var.get()):
                augmented = self._compose_rain_edge_debug_preview(augmented, payload.get("rain_edge_debug_mask"))
            display = original if (bool(getattr(self, "_fullscreen_show_original", False)) and original is not None) else augmented
            self._draw_array(self.augmented_canvas, display)

    def _compose_rain_edge_debug_preview(self, array, mask):
        if np is None:
            return array
        try:
            if mask is None:
                return array
            edge_alpha = np.clip(mask.astype("float32") * 0.88, 0.0, 0.88)
            base = array.astype("float32")
            color = np.array([255.0, 70.0, 35.0], dtype="float32")
            glow = np.clip(edge_alpha * 0.34, 0.0, 0.34)
            out = base * (1.0 - edge_alpha[:, :, None]) + color * edge_alpha[:, :, None]
            out = out * (1.0 - glow[:, :, None]) + np.array([255.0, 210.0, 70.0], dtype="float32") * glow[:, :, None]
            return np.clip(out, 0, 255).astype("uint8")
        except Exception:
            return array

    def _draw_array(self, canvas: tk.Canvas, array):
        if canvas is None:
            return
        canvas.delete("all")
        try:
            image = Image.fromarray(array)
        except Exception:
            self._draw_canvas_message(canvas, "Nie można wyświetlić obrazu")
            return
        original_image_w = max(1, int(image.width))
        original_image_h = max(1, int(image.height))
        width = max(1, int(canvas.winfo_width() or 1))
        height = max(1, int(canvas.winfo_height() or 1))
        zoom = float(getattr(self, "_preview_zoom", self._default_preview_zoom()) or self._default_preview_zoom()) if canvas in (getattr(self, "original_canvas", None), getattr(self, "augmented_canvas", None)) else 1.0
        zoom = max(0.25, min(6.0, zoom))
        max_w = max(1, width - 12)
        max_h = max(1, height - 12)
        base_scale = min(max_w / max(1, image.width), max_h / max(1, image.height))
        scale = max(0.01, base_scale * zoom)
        resized_size = (
            max(1, int(round(image.width * scale))),
            max(1, int(round(image.height * scale))),
        )
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
        image = image.resize(resized_size, resampling)
        resized_w = max(1, int(image.width))
        resized_h = max(1, int(image.height))
        crop_left = 0
        crop_top = 0
        if image.width > max_w or image.height > max_h:
            max_pan_x = max(0.0, (image.width - max_w) / 2.0)
            max_pan_y = max(0.0, (image.height - max_h) / 2.0)
            pan_x = max(-max_pan_x, min(max_pan_x, float(getattr(self, "_preview_pan_x", 0.0) or 0.0)))
            pan_y = max(-max_pan_y, min(max_pan_y, float(getattr(self, "_preview_pan_y", 0.0) or 0.0)))
            self._preview_pan_x = pan_x
            self._preview_pan_y = pan_y
            center_x = image.width / 2.0 - pan_x
            center_y = image.height / 2.0 - pan_y
            left = max(0, int(round(center_x - max_w / 2.0)))
            top = max(0, int(round(center_y - max_h / 2.0)))
            crop_left = left
            crop_top = top
            image = image.crop((left, top, min(image.width, left + max_w), min(image.height, top + max_h)))
        display_w = max(1, int(image.width))
        display_h = max(1, int(image.height))
        display_left = (float(width) - float(display_w)) / 2.0
        display_top = (float(height) - float(display_h)) / 2.0
        self._preview_canvas_mappings[id(canvas)] = {
            "canvas_w": float(width),
            "canvas_h": float(height),
            "image_w": float(original_image_w),
            "image_h": float(original_image_h),
            "scale": float(scale),
            "resized_w": float(resized_w),
            "resized_h": float(resized_h),
            "crop_left": float(crop_left),
            "crop_top": float(crop_top),
            "display_left": float(display_left),
            "display_top": float(display_top),
            "display_w": float(display_w),
            "display_h": float(display_h),
        }
        photo = ImageTk.PhotoImage(image)
        self._photo_refs.append(photo)
        self._photo_refs = self._photo_refs[-8:]
        canvas.create_image(width / 2, height / 2, image=photo, anchor=tk.CENTER)
        if canvas is getattr(self, "augmented_canvas", None):
            self._draw_vector_overlay()

    def _register_canvas_overlay_region(self, kind: str, rect: tuple[float, float, float, float], **payload):
        payload.update({"kind": kind, "rect": tuple(rect)})
        self._canvas_overlay_regions.append(payload)

    def _format_overlay_value(self, variable, step) -> str:
        try:
            return self._format_toolbox_value(variable.get(), step)
        except Exception:
            return "0"

    def _draw_canvas_tool_icon(self, canvas: tk.Canvas, key: str, label: str, x: int, y: int):
        active = key == self._active_toolbox
        fill = "#20342f" if active else "#171b20"
        outline = "#5fd29c" if active else "#596269"
        color = "#7ff0b4" if active else "#d7dde1"
        canvas.create_rectangle(x, y, x + 42, y + 38, fill=fill, outline=outline, width=(2 if active else 1), tags=("aug_overlay",))
        cx = x + 21
        cy = y + 15
        if key in ("scene", "plate_surface"):
            canvas.create_rectangle(cx - 10, cy - 7, cx + 10, cy + 7, outline=color, width=2, tags=("aug_overlay",))
            canvas.create_line(cx - 8, cy + 7, cx + 8, cy - 7, fill=color, width=1, tags=("aug_overlay",))
        elif key == "rain":
            for offset in (-8, 0, 8):
                canvas.create_line(cx + offset, cy - 8, cx + offset - 4, cy + 7, fill=color, width=2, tags=("aug_overlay",))
        elif key == "mud":
            canvas.create_oval(cx - 10, cy - 5, cx + 4, cy + 7, fill=color, outline="", tags=("aug_overlay",))
            canvas.create_oval(cx + 2, cy - 8, cx + 11, cy + 3, fill=color, outline="", tags=("aug_overlay",))
        elif key == "light":
            canvas.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, outline=color, width=2, tags=("aug_overlay",))
            for angle in (0, 60, 120, 180, 240, 300):
                rad = math.radians(angle)
                canvas.create_line(cx + math.cos(rad) * 9, cy + math.sin(rad) * 9, cx + math.cos(rad) * 13, cy + math.sin(rad) * 13, fill=color, width=1, tags=("aug_overlay",))
        canvas.create_text(cx, y + 31, text=str(label or key)[:6], fill=color, font=("Segoe UI", 6), tags=("aug_overlay",))
        self._register_canvas_overlay_region("toolbox", (x, y, x + 42, y + 38), key=key)

    def _draw_canvas_vector_tool_icon(self, canvas: tk.Canvas, tool: str, x: int, y: int):
        specs = self._vector_specs()
        spec = specs.get(tool)
        if not spec:
            return
        active = self._vector_tool == tool
        fill = spec["active"] if active else "#171b20"
        outline = spec["color"] if active else "#596269"
        color = spec["color"] if active else "#d7dde1"
        tags = ("vector_overlay", "vector_control", f"vector_tool:{tool}")
        canvas.create_rectangle(x, y, x + 42, y + 38, fill=fill, outline=outline, width=(2 if active else 1), tags=tags)
        self._draw_vector_icon(canvas, tool, x + 21, y + 15, color, active)
        canvas.create_text(x + 21, y + 31, text="Wiatr", fill=color, font=("Segoe UI", 6), tags=tags)

    def _draw_canvas_action_icon(self, canvas: tk.Canvas, action: str, label: str, x: int, y: int):
        outline = "#69737a"
        color = "#d7dde1"
        if action == "fullscreen" and bool(getattr(self, "_preview_fullscreen", False)):
            outline = "#f3c86a"
            color = "#ffd56e"
        if action == "zoom" and abs(float(getattr(self, "_preview_zoom", self._default_preview_zoom()) or self._default_preview_zoom()) - self._default_preview_zoom()) > 0.01:
            outline = "#76d9ff"
            color = "#76d9ff"
        if action == "dice":
            outline = "#8df0b7"
            color = "#8df0b7"
        if action == "layout":
            outline = "#76d9ff"
            color = "#76d9ff"
        if action == "reset":
            outline = "#f3c86a"
            color = "#ffd56e"
        canvas.create_rectangle(x, y, x + 38, y + 38, fill="#171b20", outline=outline, width=1, tags=("aug_overlay",))
        cx = x + 19
        cy = y + 16
        if action == "zoom":
            canvas.create_oval(cx - 7, cy - 7, cx + 5, cy + 5, outline=color, width=2, tags=("aug_overlay",))
            canvas.create_line(cx + 4, cy + 4, cx + 10, cy + 10, fill=color, width=2, tags=("aug_overlay",))
            canvas.create_text(cx, y + 32, text=f"{float(getattr(self, '_preview_zoom', 1.0) or 1.0):.1f}x", fill=color, font=("Segoe UI", 6), tags=("aug_overlay",))
        elif action == "fullscreen":
            canvas.create_line(cx - 10, cy - 7, cx - 10, cy - 12, cx - 5, cy - 12, fill=color, width=2, tags=("aug_overlay",))
            canvas.create_line(cx + 10, cy - 7, cx + 10, cy - 12, cx + 5, cy - 12, fill=color, width=2, tags=("aug_overlay",))
            canvas.create_line(cx - 10, cy + 7, cx - 10, cy + 12, cx - 5, cy + 12, fill=color, width=2, tags=("aug_overlay",))
            canvas.create_line(cx + 10, cy + 7, cx + 10, cy + 12, cx + 5, cy + 12, fill=color, width=2, tags=("aug_overlay",))
            canvas.create_text(cx, y + 32, text=label, fill=color, font=("Segoe UI", 6), tags=("aug_overlay",))
        elif action == "dice":
            die_size = 16
            die_left = int(round(cx - die_size / 2))
            die_top = y + 6
            canvas.create_rectangle(
                die_left,
                die_top,
                die_left + die_size,
                die_top + die_size,
                fill="#10211a",
                outline=color,
                width=1,
                tags=("aug_overlay",),
            )
            dot_r = 1.7
            for dot_x, dot_y in ((4, 4), (12, 4), (8, 8), (4, 12), (12, 12)):
                px = die_left + dot_x
                py = die_top + dot_y
                canvas.create_oval(px - dot_r, py - dot_r, px + dot_r, py + dot_r, fill=color, outline="", tags=("aug_overlay",))
            canvas.create_text(cx, y + 32, text=label, fill=color, font=("Segoe UI", 6), tags=("aug_overlay",))
        elif action == "layout":
            points = ((cx - 9, cy - 5), (cx + 8, cy - 7), (cx - 2, cy + 8))
            canvas.create_line(points[0][0], points[0][1], points[1][0], points[1][1], fill=color, width=1, tags=("aug_overlay",))
            canvas.create_line(points[1][0], points[1][1], points[2][0], points[2][1], fill=color, width=1, tags=("aug_overlay",))
            canvas.create_line(points[2][0], points[2][1], points[0][0], points[0][1], fill=color, width=1, dash=(2, 2), tags=("aug_overlay",))
            for px, py in points:
                canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill=color, outline="", tags=("aug_overlay",))
            canvas.create_text(cx, y + 32, text=label, fill=color, font=("Segoe UI", 6), tags=("aug_overlay",))
        elif action == "reset":
            canvas.create_arc(cx - 9, cy - 9, cx + 9, cy + 9, start=35, extent=285, style=tk.ARC, outline=color, width=2, tags=("aug_overlay",))
            canvas.create_line(cx - 1, cy - 10, cx + 6, cy - 10, cx + 6, cy - 3, fill=color, width=2, tags=("aug_overlay",))
            canvas.create_text(cx, y + 32, text=label, fill=color, font=("Segoe UI", 6), tags=("aug_overlay",))
        self._register_canvas_overlay_region("action", (x, y, x + 38, y + 38), action=action)

    def _draw_canvas_slider(self, canvas: tk.Canvas, x: int, y: int, w: int, label: str, variable, from_, to, step, role: str | None = None):
        try:
            value = float(variable.get())
        except Exception:
            value = 0.0
        from_ = float(from_)
        to = float(to)
        span = max(0.000001, to - from_)
        ratio = max(0.0, min(1.0, (value - from_) / span))
        role_key = str(role or label or "").strip().casefold()
        fill_color = {
            "r": "#ff6b6b",
            "red": "#ff6b6b",
            "g": "#65d99b",
            "green": "#65d99b",
            "b": "#76d9ff",
            "blue": "#76d9ff",
        }.get(role_key, "#65d99b")
        label_color = fill_color if role_key in {"r", "red", "g", "green", "b", "blue"} else "#e4ecec"
        knob_fill = {
            "r": "#ffd6d6",
            "red": "#ffd6d6",
            "g": "#dfffe9",
            "green": "#dfffe9",
            "b": "#d9f2ff",
            "blue": "#d9f2ff",
        }.get(role_key, "#dfffe9")
        canvas.create_text(x, y, text=f"{label}: {self._format_overlay_value(variable, step)}", anchor=tk.W, fill=label_color, font=("Segoe UI", 7), tags=("aug_overlay",))
        bar_y = y + 12
        canvas.create_line(x, bar_y, x + w, bar_y, fill="#56616a", width=3, tags=("aug_overlay",))
        canvas.create_line(x, bar_y, x + w * ratio, bar_y, fill=fill_color, width=3, tags=("aug_overlay",))
        knob_x = x + w * ratio
        canvas.create_oval(knob_x - 4, bar_y - 4, knob_x + 4, bar_y + 4, fill=knob_fill, outline="#0d1f18", width=1, tags=("aug_overlay",))
        self._register_canvas_overlay_region(
            "slider",
            (x - 4, y - 2, x + w + 8, y + 20),
            variable=variable,
            from_=from_,
            to=to,
            step=step,
            bar=(x, x + w),
            role=role,
        )

    def _draw_canvas_range_slider(self, canvas: tk.Canvas, x: int, y: int, w: int, label: str, min_var, max_var, from_, to, step):
        try:
            min_value = float(min_var.get())
            max_value = float(max_var.get())
        except Exception:
            min_value = float(from_)
            max_value = float(to)
        from_ = float(from_)
        to = float(to)
        span = max(0.000001, to - from_)
        if min_value > max_value:
            min_value, max_value = max_value, min_value
        min_ratio = max(0.0, min(1.0, (min_value - from_) / span))
        max_ratio = max(0.0, min(1.0, (max_value - from_) / span))
        min_x = x + w * min_ratio
        max_x = x + w * max_ratio
        canvas.create_text(x, y, text=label, anchor=tk.W, fill="#e4ecec", font=("Segoe UI", 7), tags=("aug_overlay",))
        box_w = 42
        box_h = 14
        min_text = self._format_overlay_value(min_var, step)
        max_text = self._format_overlay_value(max_var, step)
        canvas.create_rectangle(x + w - box_w * 2 - 8, y - 7, x + w - box_w - 6, y + box_h - 7, fill="#162027", outline="#3f555e", width=1, tags=("aug_overlay",))
        canvas.create_rectangle(x + w - box_w, y - 7, x + w, y + box_h - 7, fill="#162027", outline="#3f555e", width=1, tags=("aug_overlay",))
        canvas.create_text(x + w - box_w - 7, y, text=min_text, anchor=tk.E, fill="#c8f8df", font=("Segoe UI", 6), tags=("aug_overlay",))
        canvas.create_text(x + w - 3, y, text=max_text, anchor=tk.E, fill="#c8f8df", font=("Segoe UI", 6), tags=("aug_overlay",))
        bar_y = y + 15
        canvas.create_line(x, bar_y, x + w, bar_y, fill="#56616a", width=3, tags=("aug_overlay",))
        canvas.create_line(min_x, bar_y, max_x, bar_y, fill="#65d99b", width=4, tags=("aug_overlay",))
        for knob_x, fill in ((min_x, "#dfffe9"), (max_x, "#f6ffe9")):
            canvas.create_rectangle(knob_x - 4, bar_y - 6, knob_x + 4, bar_y + 6, fill=fill, outline="#0d1f18", width=1, tags=("aug_overlay",))
        self._register_canvas_overlay_region(
            "range_slider",
            (x - 5, y - 8, x + w + 8, y + 24),
            min_var=min_var,
            max_var=max_var,
            from_=from_,
            to=to,
            step=step,
            bar=(x, x + w),
            min_x=min_x,
            max_x=max_x,
        )

    def _draw_canvas_check(self, canvas: tk.Canvas, x: int, y: int, label: str, variable):
        active = bool(variable.get())
        fill = "#61d998" if active else "#10161a"
        outline = "#61d998" if active else "#6f7a82"
        canvas.create_rectangle(x, y, x + 12, y + 12, fill=fill, outline=outline, width=1, tags=("aug_overlay",))
        if active:
            canvas.create_line(x + 3, y + 6, x + 5, y + 9, x + 10, y + 3, fill="#0b1712", width=1, tags=("aug_overlay",))
        canvas.create_text(x + 19, y + 6, text=label, anchor=tk.W, fill=("#bfffd6" if active else "#dce5e7"), font=("Segoe UI", 7), tags=("aug_overlay",))
        self._register_canvas_overlay_region("check", (x - 4, y - 4, x + 190, y + 17), variable=variable)

    def _draw_canvas_toolbox_panel(self, canvas: tk.Canvas, width: int, height: int) -> int:
        fields = self._toolbox_fields(self._active_toolbox)
        if not fields:
            return 54
        panel_w = max(260, min(330, width - 28))
        panel_pos = getattr(self, "_toolbox_panel_pos", None)
        if panel_pos is None:
            x = max(10, width - panel_w - 10)
            y = 78
        else:
            x = int(panel_pos[0])
            y = int(panel_pos[1])
        x = max(4, min(x, max(4, width - panel_w - 4)))
        y = max(64, min(y, max(64, height - 38)))
        self._toolbox_panel_pos = (x, y)
        slider_w = panel_w - 24
        rows = len(fields)
        row_step = 25
        collapsed = bool(getattr(self, "_toolbox_panel_collapsed", False))
        panel_h = 30 if collapsed else min(max(88, 36 + rows * row_step), max(108, height - y - 12))
        canvas.create_rectangle(x, y, x + panel_w, y + panel_h, fill="#10161a", outline="#3d4a50", width=1, tags=("aug_overlay",))
        self._register_canvas_overlay_region("panel", (x, y, x + panel_w, y + panel_h))
        canvas.create_text(x + 10, y + 13, text=self._active_toolbox_title(), anchor=tk.W, fill="#8df0b7", font=("Segoe UI", 9, "bold"), tags=("aug_overlay",))
        icon_y = y + 14
        reset_x = x + panel_w - 48
        toggle_x = x + panel_w - 24
        canvas.create_text(reset_x, icon_y, text="↺", anchor=tk.CENTER, fill="#d7dde1", font=("Segoe UI", 10, "bold"), tags=("aug_overlay",))
        canvas.create_text(toggle_x, icon_y, text=("+" if collapsed else "−"), anchor=tk.CENTER, fill="#d7dde1", font=("Segoe UI", 12, "bold"), tags=("aug_overlay",))
        canvas.create_line(x + panel_w - 78, y + 9, x + panel_w - 66, y + 9, fill="#71808a", width=1, tags=("aug_overlay",))
        canvas.create_line(x + panel_w - 78, y + 14, x + panel_w - 66, y + 14, fill="#71808a", width=1, tags=("aug_overlay",))
        canvas.create_line(x + panel_w - 78, y + 19, x + panel_w - 66, y + 19, fill="#71808a", width=1, tags=("aug_overlay",))
        self._register_canvas_overlay_region("panel_drag", (x, y, x + panel_w - 58, y + 28))
        self._register_canvas_overlay_region("panel_reset", (reset_x - 11, y + 3, reset_x + 11, y + 25))
        self._register_canvas_overlay_region("panel_toggle", (toggle_x - 11, y + 3, toggle_x + 11, y + 25))
        if collapsed:
            return y + panel_h
        row_y = y + 31
        bottom_limit = y + panel_h - 24
        for field in fields:
            if row_y > bottom_limit:
                canvas.create_text(x + 10, row_y, text="...", anchor=tk.W, fill="#aab3b8", font=("Segoe UI", 8), tags=("aug_overlay",))
                break
            ftype = field.get("type")
            if ftype == "check":
                self._draw_canvas_check(canvas, x + 10, row_y - 4, str(field["label"]), field["var"])
                row_y += row_step
            elif ftype in ("range", "range_slider"):
                self._draw_canvas_range_slider(canvas, x + 10, row_y, slider_w, str(field["label"]), field["min_var"], field["max_var"], field["from"], field["to"], field["step"])
                row_y += row_step
            else:
                self._draw_canvas_slider(canvas, x + 10, row_y, slider_w, str(field["label"]), field.get("var"), field["from"], field["to"], field["step"])
                row_y += row_step
        return y + panel_h

    def _bind_vector_canvas(self, canvas: tk.Canvas):
        canvas.bind("<Button-1>", self._on_vector_canvas_press, add="+")
        canvas.bind("<Double-Button-1>", self._on_vector_canvas_double_press, add="+")
        canvas.bind("<B1-Motion>", self._on_vector_canvas_drag, add="+")
        canvas.bind("<ButtonRelease-1>", self._on_vector_canvas_release, add="+")
        canvas.bind("<Motion>", self._on_vector_canvas_motion, add="+")
        canvas.bind("<Leave>", self._on_vector_canvas_leave, add="+")
        canvas.bind("<space>", self._on_space_key, add="+")
        canvas.bind("<Key-space>", self._on_space_key, add="+")

    def _bind_preview_zoom_canvas(self, canvas: tk.Canvas):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(sequence, self._on_preview_mousewheel, add="+")

    def _vector_specs(self) -> dict[str, dict[str, str]]:
        wind_label = "Wiatr/deszcz" if self.target == "plate" else "Wiatr/błoto"
        return {
            "wind": {"label": wind_label, "color": "#76d9ff", "active": "#123946"},
        }

    def _vector_value_text(self, tool: str) -> str:
        try:
            if tool == "wind":
                return f"{float(self.dirt_flow_wind_strength_var.get()):.2f}"
        except Exception:
            return "0.00"
        return "0.00"

    def _draw_memory_overlay(self, canvas: tk.Canvas, width: int, height: int):
        try:
            text = self._format_memory_snapshot()
            percent = float((getattr(self, "_memory_snapshot", {}) or {}).get("system_percent", 0.0) or 0.0)
            outline = "#58d68d"
            if percent >= 88:
                outline = "#ff6b6b"
            elif percent >= 76:
                outline = "#f3c86a"
            max_w = max(80, width - 20)
            text_w = min(max(228, int(len(text) * 5.7) + 18), max_w)
            x1 = max(10, width - text_w - 10)
            y2 = max(74, height - 10)
            y1 = max(52, y2 - 24)
            canvas.create_rectangle(
                x1,
                y1,
                x1 + text_w,
                y2,
                fill="#10161a",
                outline=outline,
                width=1,
                tags=("aug_overlay", "memory_overlay"),
            )
            canvas.create_text(
                x1 + 9,
                y1 + 12,
                text=text,
                anchor=tk.W,
                fill="#d7dde1",
                font=("Segoe UI", 7),
                tags=("aug_overlay", "memory_overlay"),
            )
        except Exception:
            pass

    def _draw_vector_overlay(self):
        canvas = getattr(self, "augmented_canvas", None)
        if canvas is None:
            return
        try:
            canvas.delete("vector_overlay")
            canvas.delete("aug_overlay")
            self._canvas_overlay_regions = []
            width = max(1, int(canvas.winfo_width() or 1))
            height = max(1, int(canvas.winfo_height() or 1))
            x = 10
            y = 10
            specs = self._vector_specs()
            for key, label in self._domain_toolboxes():
                self._draw_canvas_tool_icon(canvas, key, label, x, y)
                x += 48
            if "wind" in specs:
                self._draw_canvas_vector_tool_icon(canvas, "wind", x, y)
                x += 48
            actions = (("dice", "obraz"), ("layout", "układ"), ("reset", "zero"), ("zoom", "zoom"), ("fullscreen", "ent"))
            actions_left = max(10, width - (len(actions) * 44 - 6))
            action_x = actions_left
            for action, label in actions:
                self._draw_canvas_action_icon(canvas, action, label, action_x, 10)
                action_x += 44
            mode_text = "ORYGINAŁ" if bool(getattr(self, "_fullscreen_show_original", False)) else "EFEKT"
            pill_w = 102
            pill_x = max(10, actions_left - pill_w - 8)
            pill_y = 10
            canvas.create_rectangle(pill_x, pill_y, pill_x + pill_w, pill_y + 20, fill="#171b20", outline="#77612b", width=1, tags=("aug_overlay",))
            canvas.create_text(pill_x + pill_w / 2, pill_y + 10, text=f"TAB: {mode_text}", fill="#ffd56e", font=("Segoe UI", 7), tags=("aug_overlay",))
            self._draw_canvas_toolbox_panel(canvas, width, height)

            vector_drag_active = bool(
                self._vector_drag_start and self._vector_drag_end and self._vector_tool in specs
            )
            if self._vector_tool in specs and not vector_drag_active:
                self._draw_vector_line(self._vector_tool, width, height)
            active_headlight = getattr(self, "_active_headlight_index", None)
            config_headlight = getattr(self, "_headlight_config_index", None)
            should_draw_headlights = (
                self._active_toolbox == "light"
                or active_headlight in (1, 2, 3)
                or config_headlight in (1, 2, 3)
            )
            if should_draw_headlights:
                self._draw_headlight_handles(canvas, width, height)
                if getattr(self, "_headlight_config_index", None) in (1, 2, 3):
                    self._draw_headlight_config_toolbox(canvas, width, height)

            if vector_drag_active:
                if self._vector_tool == "wind":
                    self._draw_wind_vector_line(
                        canvas,
                        self._vector_drag_start,
                        self._vector_drag_end,
                        specs[self._vector_tool]["color"],
                        dash=(4, 3),
                    )
                else:
                    self._draw_arrow(
                        canvas,
                        self._vector_drag_start,
                        self._vector_drag_end,
                        specs[self._vector_tool]["color"],
                        dash=(4, 3),
                    )
            if not (
            self._headlight_drag is not None
            or self._canvas_slider_drag is not None
            or self._toolbox_panel_drag is not None
            or self._headlight_panel_drag is not None
            or self._vector_drag_start is not None
        ):
                self._draw_memory_overlay(canvas, width, height)
        except Exception:
            pass

    def _request_vector_overlay_redraw(self, delay_ms: int = 24):
        if self._overlay_redraw_after_id is not None:
            return

        def _run():
            self._overlay_redraw_after_id = None
            self._draw_vector_overlay()

        try:
            self._overlay_redraw_after_id = self.window.after(max(8, int(delay_ms)), _run)
        except Exception:
            self._overlay_redraw_after_id = None
            self._draw_vector_overlay()

    def _draw_vector_icon(self, canvas: tk.Canvas, tool: str, cx: float, cy: float, color: str, active: bool):
        tags = ("vector_overlay", "vector_control", f"vector_tool:{tool}")
        if tool == "wind":
            canvas.create_line(cx - 13, cy - 5, cx - 3, cy - 9, cx + 12, cy - 5, fill=color, width=2, smooth=True, tags=tags)
            canvas.create_line(cx - 10, cy + 1, cx + 9, cy + 1, fill=color, width=2, arrow=tk.LAST, arrowshape=(6, 7, 3), tags=tags)
            canvas.create_line(cx - 13, cy + 7, cx - 1, cy + 10, cx + 11, cy + 7, fill=color, width=1, smooth=True, tags=tags)
            return
        if tool == "light":
            radius = 5
            canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=color, fill=("#5a4212" if active else ""), width=2, tags=tags)
            for angle in (0, 45, 90, 135, 180, 225, 270, 315):
                rad = math.radians(angle)
                canvas.create_line(
                    cx + math.cos(rad) * 8,
                    cy + math.sin(rad) * 8,
                    cx + math.cos(rad) * 13,
                    cy + math.sin(rad) * 13,
                    fill=color,
                    width=1,
                    tags=tags,
                )
            return
        canvas.create_arc(cx - 11, cy - 9, cx + 11, cy + 13, start=20, extent=140, outline=color, width=2, style=tk.ARC, tags=tags)
        canvas.create_line(cx + 8, cy + 6, cx + 13, cy + 11, fill=color, width=2, tags=tags)

    def _draw_vector_line(self, tool: str, width: int, height: int):
        canvas = getattr(self, "augmented_canvas", None)
        specs = self._vector_specs()
        if canvas is None or tool not in specs:
            return
        if tool in self._vector_positions:
            start, end = self._vector_positions[tool]
        else:
            start, end = self._default_vector_position(tool, width, height)
        if start == end:
            return
        if tool == "wind":
            self._draw_wind_vector_line(canvas, start, end, specs[tool]["color"])
            return
        self._draw_arrow(canvas, start, end, specs[tool]["color"])
        canvas.create_text(
            end[0] + 8,
            end[1],
            text=specs[tool]["label"],
            anchor=tk.W,
            fill=specs[tool]["color"],
            font=("Segoe UI", 8),
            tags=("vector_overlay",),
        )

    def _draw_wind_vector_line(self, canvas: tk.Canvas, start: tuple[int, int], end: tuple[int, int], color: str, dash=None):
        sx, sy = float(start[0]), float(start[1])
        ex, ey = float(end[0]), float(end[1])
        min_x = min(sx, ex)
        max_x = max(sx, ex)
        min_y = min(sy, ey)
        max_y = max(sy, ey)
        label = "WIATR"
        try:
            strength = float(self.dirt_flow_wind_strength_var.get() or 0.0)
            label = f"WIATR {strength:.2f}"
        except Exception:
            pass
        canvas_w = max(1, int(canvas.winfo_width() or 1))
        canvas_h = max(1, int(canvas.winfo_height() or 1))
        if dash is None:
            canvas.create_line(
                sx,
                sy,
                ex,
                ey,
                fill="#031015",
                width=6,
                tags=("vector_overlay",),
            )
        canvas.create_line(
            sx,
            sy,
            ex,
            ey,
            fill=color,
            width=4,
            arrow=tk.LAST,
            arrowshape=(15, 18, 6),
            dash=dash,
            tags=("vector_overlay",),
        )
        for px, py, fill, outline in (
            (sx, sy, "#071218", color),
            (ex, ey, color, "#071218"),
        ):
            canvas.create_oval(px - 6, py - 6, px + 6, py + 6, fill=fill, outline=outline, width=2, tags=("vector_overlay",))
        label_w = min(116, max(70, int(len(label) * 7 + 18)))
        label_h = 18
        safe_top = 46

        def clamp(value: float, low: float, high: float) -> float:
            if high < low:
                return low
            return max(low, min(high, value))

        label_candidates = (
            (clamp(min_x, 4, canvas_w - label_w - 4), min_y - label_h - 8),
            (clamp(min_x, 4, canvas_w - label_w - 4), max_y + 8),
            (min_x - label_w - 8, clamp(sy - label_h / 2, safe_top, canvas_h - label_h - 4)),
            (max_x + 8, clamp(sy - label_h / 2, safe_top, canvas_h - label_h - 4)),
        )
        label_rect = None
        for lx, ly in label_candidates:
            if lx < 4 or ly < safe_top or lx + label_w > canvas_w - 4 or ly + label_h > canvas_h - 4:
                continue
            overlaps_vector_box = not (lx + label_w < min_x or lx > max_x or ly + label_h < min_y or ly > max_y)
            if not overlaps_vector_box:
                label_rect = (int(lx), int(ly), int(lx + label_w), int(ly + label_h))
                break
        if label_rect is not None:
            lx1, ly1, lx2, ly2 = label_rect
            canvas.create_rectangle(
                lx1,
                ly1,
                lx2,
                ly2,
                fill="#071218",
                outline="#24566a",
                width=1,
                tags=("vector_overlay",),
            )
            canvas.create_text(
                lx1 + 8,
                ly1 + label_h / 2,
                text=label,
                anchor=tk.W,
                fill="#bfefff",
                font=("Segoe UI", 7, "bold"),
                tags=("vector_overlay",),
            )
        else:
            canvas.create_text(
                sx + 10,
                sy - 12,
                text=label,
                anchor=tk.W,
                fill="#bfefff",
                font=("Segoe UI", 7, "bold"),
                tags=("vector_overlay",),
            )

    def _headlight_var_group(self, index: int):
        if index == 1:
            return (
                self.traffic_headlight_source_x_var,
                self.traffic_headlight_source_y_var,
                self.traffic_headlight_target_x_var,
                self.traffic_headlight_target_y_var,
                self.traffic_headlight_var,
                self.traffic_headlight_1_warmth_var,
            )
        if index == 2:
            return (
                self.traffic_headlight_2_source_x_var,
                self.traffic_headlight_2_source_y_var,
                self.traffic_headlight_2_target_x_var,
                self.traffic_headlight_2_target_y_var,
                self.traffic_headlight_2_var,
                self.traffic_headlight_2_warmth_var,
            )
        return (
            self.traffic_headlight_3_source_x_var,
            self.traffic_headlight_3_source_y_var,
            self.traffic_headlight_3_target_x_var,
            self.traffic_headlight_3_target_y_var,
            self.traffic_headlight_3_var,
            self.traffic_headlight_3_warmth_var,
        )

    def _headlight_control_vars(self, index: int):
        if index == 1:
            return (
                self.traffic_headlight_var,
                self.traffic_headlight_1_r_var,
                self.traffic_headlight_1_g_var,
                self.traffic_headlight_1_b_var,
                self.traffic_headlight_1_cone_var,
                self.traffic_headlight_1_source_radius_var,
            )
        if index == 2:
            return (
                self.traffic_headlight_2_var,
                self.traffic_headlight_2_r_var,
                self.traffic_headlight_2_g_var,
                self.traffic_headlight_2_b_var,
                self.traffic_headlight_2_cone_var,
                self.traffic_headlight_2_source_radius_var,
            )
        return (
            self.traffic_headlight_3_var,
            self.traffic_headlight_3_r_var,
            self.traffic_headlight_3_g_var,
            self.traffic_headlight_3_b_var,
            self.traffic_headlight_3_cone_var,
            self.traffic_headlight_3_source_radius_var,
        )

    def _headlight_enabled_var(self, index: int):
        if index == 1:
            return self.traffic_headlight_1_enabled_var
        if index == 2:
            return self.traffic_headlight_2_enabled_var
        return self.traffic_headlight_3_enabled_var

    def _headlight_effect_enabled(self, index: int) -> bool:
        try:
            return bool(self._headlight_enabled_var(index).get())
        except Exception:
            return False

    def _read_float_var(self, variable, default: float = 0.0) -> float:
        try:
            value = variable.get()
            if value is None or str(value).strip() == "":
                return float(default)
            value = float(value)
            return value if math.isfinite(value) else float(default)
        except Exception:
            return float(default)

    def _read_int_var(
        self,
        variable,
        *,
        default: int = 0,
        minimum: int | None = None,
        maximum: int | None = None,
        remember_attr: str | None = None,
        repair: bool = False,
    ) -> int:
        fallback = default
        if remember_attr:
            try:
                fallback = int(getattr(self, remember_attr, default))
            except Exception:
                fallback = default
        try:
            raw = variable.get()
            if raw is None or str(raw).strip() == "":
                raise ValueError("empty numeric field")
            value = int(float(raw))
        except Exception:
            value = int(fallback)
        if minimum is not None:
            value = max(int(minimum), value)
        if maximum is not None:
            value = min(int(maximum), value)
        if remember_attr:
            try:
                setattr(self, remember_attr, int(value))
            except Exception:
                pass
        if repair:
            try:
                raw = variable.get()
                if raw is None or str(raw).strip() == "" or int(float(raw)) != int(value):
                    variable.set(int(value))
            except Exception:
                try:
                    variable.set(int(value))
                except Exception:
                    pass
        return int(value)

    def _select_headlight(self, index: int | None):
        if index is None:
            self._active_headlight_index = None
            self._headlight_config_index = None
            self._headlight_panel_pos = None
            self._headlight_panel_anchor_index = None
            return
        index = int(index or 0)
        if index not in (1, 2, 3):
            self._active_headlight_index = None
            self._headlight_config_index = None
            self._headlight_panel_pos = None
            self._headlight_panel_anchor_index = None
            return
        self._active_headlight_index = index
        if self._headlight_config_index not in (None, index):
            self._headlight_config_index = None
            self._headlight_panel_pos = None
            self._headlight_panel_anchor_index = None

    def _toggle_headlight_effect(self, index: int):
        try:
            enabled_var = self._headlight_enabled_var(index)
            next_value = not bool(enabled_var.get())
            enabled_var.set(next_value)
            strength_var = self._headlight_control_vars(index)[0]
            if next_value and self._read_float_var(strength_var, 0.0) <= 0.001:
                strength_var.set(0.65)
        except Exception:
            pass

    def _toggle_headlight_cone_visibility(self, index: int):
        try:
            index = int(index or 0)
        except Exception:
            index = 0
        if index not in (1, 2, 3):
            self._select_headlight(None)
            return
        current = getattr(self, "_active_headlight_index", None)
        if current == index:
            self._select_headlight(None)
        else:
            self._select_headlight(index)

    def _default_headlight_norm(self, index: int) -> tuple[tuple[float, float], tuple[float, float]]:
        defaults = {
            1: ((0.14, 0.91), (0.42, 0.44)),
            2: ((0.86, 0.90), (0.58, 0.48)),
            3: ((0.50, 0.98), (0.50, 0.36)),
        }
        return defaults.get(index, defaults[1])

    def _preview_mapping_for_canvas(self, canvas: tk.Canvas | None = None) -> dict[str, float] | None:
        canvas = canvas or getattr(self, "augmented_canvas", None)
        if canvas is None:
            return None
        try:
            return (getattr(self, "_preview_canvas_mappings", {}) or {}).get(id(canvas))
        except Exception:
            return None

    def _canvas_point_from_image_norm(self, x_norm: float, y_norm: float, width: int, height: int) -> tuple[int, int]:
        x_norm = max(0.0, min(1.0, float(x_norm)))
        y_norm = max(0.0, min(1.0, float(y_norm)))
        mapping = self._preview_mapping_for_canvas(getattr(self, "augmented_canvas", None))
        if mapping:
            resized_x = x_norm * float(mapping.get("image_w", 1.0)) * float(mapping.get("scale", 1.0))
            resized_y = y_norm * float(mapping.get("image_h", 1.0)) * float(mapping.get("scale", 1.0))
            x = float(mapping.get("display_left", 0.0)) + resized_x - float(mapping.get("crop_left", 0.0))
            y = float(mapping.get("display_top", 0.0)) + resized_y - float(mapping.get("crop_top", 0.0))
            return (int(round(x)), int(round(y)))
        return (int(round(x_norm * max(1, width))), int(round(y_norm * max(1, height))))

    def _image_norm_from_canvas_point(self, x: float, y: float, width: float, height: float) -> tuple[float, float]:
        mapping = self._preview_mapping_for_canvas(getattr(self, "augmented_canvas", None))
        if mapping:
            image_w = max(1.0, float(mapping.get("image_w", 1.0)))
            image_h = max(1.0, float(mapping.get("image_h", 1.0)))
            scale = max(0.000001, float(mapping.get("scale", 1.0)))
            resized_x = float(mapping.get("crop_left", 0.0)) + float(x) - float(mapping.get("display_left", 0.0))
            resized_y = float(mapping.get("crop_top", 0.0)) + float(y) - float(mapping.get("display_top", 0.0))
            return (
                max(0.0, min(1.0, resized_x / (image_w * scale))),
                max(0.0, min(1.0, resized_y / (image_h * scale))),
            )
        return (
            max(0.0, min(1.0, float(x) / max(1.0, float(width)))),
            max(0.0, min(1.0, float(y) / max(1.0, float(height)))),
        )

    def _clamp_canvas_point_to_preview_image(self, x: float, y: float) -> tuple[float, float]:
        mapping = self._preview_mapping_for_canvas(getattr(self, "augmented_canvas", None))
        if not mapping:
            return float(x), float(y)
        left = float(mapping.get("display_left", 0.0))
        top = float(mapping.get("display_top", 0.0))
        right = left + max(1.0, float(mapping.get("display_w", 1.0)))
        bottom = top + max(1.0, float(mapping.get("display_h", 1.0)))
        return (
            max(left, min(right, float(x))),
            max(top, min(bottom, float(y))),
        )

    def _headlight_display_unit(self, width: int, height: int) -> float:
        mapping = self._preview_mapping_for_canvas(getattr(self, "augmented_canvas", None))
        if mapping:
            return max(
                1.0,
                min(float(mapping.get("image_w", 1.0)), float(mapping.get("image_h", 1.0)))
                * float(mapping.get("scale", 1.0)),
            )
        return max(1.0, float(min(width, height)))

    def _default_headlight_points(self, index: int, width: int, height: int) -> tuple[tuple[int, int], tuple[int, int]]:
        source, target = self._default_headlight_norm(index)
        return (
            self._canvas_point_from_image_norm(source[0], source[1], width, height),
            self._canvas_point_from_image_norm(target[0], target[1], width, height),
        )

    def _headlight_points(self, index: int, width: int, height: int) -> tuple[tuple[int, int], tuple[int, int]]:
        sx_var, sy_var, tx_var, ty_var, _strength_var, _warmth_var = self._headlight_var_group(index)
        default_source, default_target = self._default_headlight_points(index, width, height)
        try:
            sx = self._read_float_var(sx_var, -1.0)
            sy = self._read_float_var(sy_var, -1.0)
            tx = self._read_float_var(tx_var, -1.0)
            ty = self._read_float_var(ty_var, -1.0)
            source = default_source
            target = default_target
            if 0.0 <= sx <= 1.0 and 0.0 <= sy <= 1.0:
                source = self._canvas_point_from_image_norm(sx, sy, width, height)
            if 0.0 <= tx <= 1.0 and 0.0 <= ty <= 1.0:
                target = self._canvas_point_from_image_norm(tx, ty, width, height)
            return source, target
        except Exception:
            pass
        return default_source, default_target

    def _ensure_headlight_pair_defaults(self, index: int, width: float, height: float) -> None:
        sx_var, sy_var, tx_var, ty_var, _strength_var, _warmth_var = self._headlight_var_group(index)
        default_source, default_target = self._default_headlight_norm(index)

        def is_valid_pair(x_var, y_var) -> bool:
            try:
                x = self._read_float_var(x_var, -1.0)
                y = self._read_float_var(y_var, -1.0)
                return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
            except Exception:
                return False

        def set_normalized_if_missing(x_var, y_var, point: tuple[int, int]) -> None:
            if is_valid_pair(x_var, y_var):
                return
            try:
                x_var.set(max(0.0, min(1.0, float(point[0]))))
                y_var.set(max(0.0, min(1.0, float(point[1]))))
            except Exception:
                pass

        set_normalized_if_missing(sx_var, sy_var, default_source)
        set_normalized_if_missing(tx_var, ty_var, default_target)

    def _headlight_color(self, warmth: float, strength: float) -> str:
        warmth = max(0.0, min(1.0, float(warmth)))
        cold = (118, 217, 255)
        warm = (255, 211, 106)
        color = tuple(int(cold[i] * (1.0 - warmth) + warm[i] * warmth) for i in range(3))
        if strength <= 0.001:
            color = tuple(int(channel * 0.56) for channel in color)
        return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"

    def _headlight_color_from_vars(self, index: int, strength: float) -> str:
        try:
            _strength, red_var, green_var, blue_var, _cone, _source_radius = self._headlight_control_vars(index)
            red = max(0.0, min(1.0, float(red_var.get() or 0.0)))
            green = max(0.0, min(1.0, float(green_var.get() or 0.0)))
            blue = max(0.0, min(1.0, float(blue_var.get() or 0.0)))
            color = (int(red * 255.0), int(green * 255.0), int(blue * 255.0))
            if strength <= 0.001:
                color = tuple(int(channel * 0.72) for channel in color)
            luminance = color[0] * 0.2126 + color[1] * 0.7152 + color[2] * 0.0722
            if luminance < 118:
                # UI handles must stay readable even when the simulated light is dark.
                fallback = (255, 211, 106)
                blend = 0.68 if strength > 0.001 else 0.82
                color = tuple(int(color[i] * (1.0 - blend) + fallback[i] * blend) for i in range(3))
            return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
        except Exception:
            return self._headlight_color(0.35, strength)

    def _draw_headlight_toggle_bar(self, canvas: tk.Canvas, width: int, height: int, active_index: int):
        label_w = 72
        col_w = 42
        row_h = 20
        panel_w = label_w + col_w * 3 + 12
        panel_h = 68
        x = 10
        y = max(72, height - panel_h - 12)
        canvas.create_rectangle(
            x,
            y,
            x + panel_w,
            y + panel_h,
            fill="#0d1418",
            outline="#344149",
            width=1,
            tags=("vector_overlay", "headlight_control"),
        )
        canvas.create_text(
            x + 8,
            y + 10,
            text="Reflektory",
            anchor=tk.W,
            fill="#d7dde1",
            font=("Segoe UI", 8),
            tags=("vector_overlay", "headlight_control"),
        )
        header_y = y + 12
        for offset, index in enumerate((1, 2, 3)):
            cx = x + label_w + col_w * offset + col_w / 2
            canvas.create_text(
                cx,
                header_y,
                text=f"R{index}",
                anchor=tk.CENTER,
                fill="#fff3b0" if index == active_index else "#d7dde1",
                font=("Segoe UI", 8, "bold" if index == active_index else "normal"),
                tags=("vector_overlay", "headlight_control"),
            )

        rows = (
            ("Stożek", "headlight_cone_toggle"),
            ("Efekt", "headlight_toggle"),
        )
        for row_index, (row_label, action_kind) in enumerate(rows):
            row_y = y + 21 + row_index * row_h
            canvas.create_text(
                x + 8,
                row_y + row_h / 2,
                text=row_label,
                anchor=tk.W,
                fill="#d7dde1",
                font=("Segoe UI", 8),
                tags=("vector_overlay", "headlight_control"),
            )
            canvas.create_line(
                x + 6,
                row_y,
                x + panel_w - 6,
                row_y,
                fill="#243039",
                width=1,
                tags=("vector_overlay", "headlight_control"),
            )
            for offset, index in enumerate((1, 2, 3)):
                cell_x = x + label_w + col_w * offset + 4
                cell_y = row_y + 2
                cell_w = col_w - 8
                cell_h = row_h - 4
                enabled = self._headlight_effect_enabled(index)
                cone_visible = index == active_index
                active = cone_visible if action_kind == "headlight_cone_toggle" else enabled
                outline = "#76d9ff" if action_kind == "headlight_cone_toggle" else "#58d68d"
                fill = "#142833" if action_kind == "headlight_cone_toggle" else "#14291f"
                if not active:
                    outline = "#4b555c"
                    fill = "#151a1f"
                canvas.create_rectangle(
                    cell_x,
                    cell_y,
                    cell_x + cell_w,
                    cell_y + cell_h,
                    fill=fill,
                    outline=outline,
                    width=1,
                    tags=("vector_overlay", "headlight_control"),
                )
                if action_kind == "headlight_cone_toggle":
                    color = "#76d9ff" if active else "#819098"
                    cx = cell_x + cell_w / 2
                    cy = cell_y + cell_h / 2
                    canvas.create_polygon(
                        cx - 9,
                        cy + 5,
                        cx,
                        cy - 6,
                        cx + 9,
                        cy + 5,
                        fill="",
                        outline=color,
                        width=1,
                        tags=("vector_overlay", "headlight_control"),
                    )
                else:
                    canvas.create_text(
                        cell_x + cell_w / 2,
                        cell_y + cell_h / 2,
                        text="ON" if active else "OFF",
                        anchor=tk.CENTER,
                        fill=("#bfffd6" if active else "#9aa7ad"),
                        font=("Segoe UI", 7),
                        tags=("vector_overlay", "headlight_control"),
                    )
                self._register_canvas_overlay_region(
                    action_kind,
                    (cell_x, cell_y, cell_x + cell_w, cell_y + cell_h),
                    index=index,
                )

    def _headlight_config_lollipop_geometry(
        self,
        source: tuple[int, int],
        target: tuple[int, int],
        width: int,
        height: int,
        source_half_width: float = 0.0,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        sx = float(source[0])
        sy = float(source[1])
        tx = float(target[0])
        ty = float(target[1])
        vx = sx - tx
        vy = sy - ty
        distance = max(1.0, math.hypot(vx, vy))
        ux = vx / distance
        uy = vy / distance
        margin = 16.0
        start_dist = max(12.0, min(32.0, float(source_half_width) + 6.0))
        end_dist = max(start_dist + 18.0, min(66.0, float(source_half_width) + 28.0))
        limits = [end_dist]
        if abs(ux) > 0.001:
            limits.append(((float(width) - margin - sx) / ux) if ux > 0 else ((margin - sx) / ux))
        if abs(uy) > 0.001:
            limits.append(((float(height) - margin - sy) / uy) if uy > 0 else ((margin - sy) / uy))
        positive_limits = [value for value in limits if value > start_dist + 8.0]
        if positive_limits:
            end_dist = max(start_dist + 8.0, min(end_dist, min(positive_limits)))
        return (
            (sx + ux * start_dist, sy + uy * start_dist),
            (sx + ux * end_dist, sy + uy * end_dist),
        )

    def _draw_headlight_config_lollipop(
        self,
        canvas: tk.Canvas,
        index: int,
        source: tuple[int, int],
        target: tuple[int, int],
        width: int,
        height: int,
        *,
        color: str,
        expanded: bool,
        source_half_width: float,
    ):
        (x1, y1), (cx, cy) = self._headlight_config_lollipop_geometry(source, target, width, height, source_half_width)
        hover = getattr(self, "_headlight_config_hover_index", None) == index
        radius = 11 if hover or expanded else 9
        outline = "#fff3b0" if expanded else ("#76d9ff" if hover else "#b7c5cc")
        fill = "#111820"
        canvas.create_line(
            x1,
            y1,
            cx,
            cy,
            fill=outline,
            width=1,
            dash=(2, 3),
            tags=("vector_overlay", "headlight_control"),
        )
        canvas.create_oval(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            fill=fill,
            outline=outline,
            width=2 if hover or expanded else 1,
            tags=("vector_overlay", "headlight_control"),
        )
        dot_r = max(2.2, radius * 0.28)
        canvas.create_oval(
            cx - dot_r,
            cy - dot_r,
            cx + dot_r,
            cy + dot_r,
            fill=color,
            outline="",
            tags=("vector_overlay", "headlight_control"),
        )
        for offset in (-4, 0, 4):
            y = cy + offset
            canvas.create_line(
                cx - radius + 4,
                y,
                cx + radius - 4,
                y,
                fill=outline,
                width=1,
                tags=("vector_overlay", "headlight_control"),
            )
        hit_pad = radius + 7
        self._register_canvas_overlay_region(
            "headlight_config_toggle",
            (cx - hit_pad, cy - hit_pad, cx + hit_pad, cy + hit_pad),
            index=index,
        )

    def _draw_headlight_handles(self, canvas: tk.Canvas, width: int, height: int):
        active_index = getattr(self, "_active_headlight_index", None)
        if active_index not in (1, 2, 3):
            self._active_headlight_index = None
            self._headlight_config_index = None
            self._draw_headlight_toggle_bar(canvas, width, height, None)
            return
        self._draw_headlight_toggle_bar(canvas, width, height, active_index)

        index = active_index
        _sx_var, _sy_var, _tx_var, _ty_var, strength_var, _warmth_var = self._headlight_var_group(index)
        try:
            raw_strength = max(0.0, min(1.0, float(strength_var.get() or 0.0)))
        except Exception:
            raw_strength = 0.0
        enabled = self._headlight_effect_enabled(index)
        visible_strength = raw_strength if enabled else 0.0
        source, target = self._headlight_points(index, width, height)
        color = self._headlight_color_from_vars(index, visible_strength)
        try:
            _strength_var, _red_var, _green_var, _blue_var, cone_var, source_radius_var = self._headlight_control_vars(index)
            cone = max(0.02, min(2.5, float(cone_var.get() or 0.45)))
            source_radius = max(0.0, min(2.5, float(source_radius_var.get() or 0.0)))
        except Exception:
            cone = 0.45
            source_radius = 0.08
        line_width = 1
        dash = None if enabled and raw_strength > 0.001 else (4, 4)
        vx = float(target[0] - source[0])
        vy = float(target[1] - source[1])
        distance = max(1.0, math.hypot(vx, vy))
        ux = vx / distance
        uy = vy / distance
        px = -uy
        py = ux
        unit = self._headlight_display_unit(width, height)
        source_half_width = max(3.0, source_radius * unit)
        target_half_width = max(3.0, cone * unit)
        cone_outline = "#fff3b0" if enabled else "#8a7441"
        if target_half_width > 1.0 or source_half_width > 1.0:
            if math.hypot(vx, vy) <= max(6.0, min(source_half_width, target_half_width) * 0.30):
                # Zbieżne środki przekrojów oznaczają światło prawie prostopadłe do tablicy.
                cx = (float(source[0]) + float(target[0])) / 2.0
                cy = (float(source[1]) + float(target[1])) / 2.0
                for radius_px, dash_style in ((target_half_width, (3, 3)), (source_half_width, (2, 4))):
                    canvas.create_oval(
                        cx - radius_px,
                        cy - radius_px,
                        cx + radius_px,
                        cy + radius_px,
                        fill="",
                        outline=cone_outline,
                        width=1,
                        dash=dash_style,
                        tags=("vector_overlay", "headlight_control"),
                    )
            else:
                cone_points = (
                    source[0] + px * source_half_width,
                    source[1] + py * source_half_width,
                    target[0] + px * target_half_width,
                    target[1] + py * target_half_width,
                    target[0] - px * target_half_width,
                    target[1] - py * target_half_width,
                    source[0] - px * source_half_width,
                    source[1] - py * source_half_width,
                )
                canvas.create_polygon(
                    *cone_points,
                    fill="",
                    outline=cone_outline,
                    width=1,
                    dash=(3, 3),
                    tags=("vector_overlay", "headlight_control"),
                )
        canvas.create_line(
            source[0],
            source[1],
            target[0],
            target[1],
            fill="#fff3b0",
            width=line_width,
            dash=dash,
            tags=("vector_overlay", "headlight_control"),
        )
        canvas.create_line(
            source[0],
            source[1],
            target[0],
            target[1],
            fill=color,
            width=line_width,
            dash=dash,
            tags=("vector_overlay", "headlight_control"),
        )
        radius = 7 if enabled and raw_strength > 0.001 else 5
        canvas.create_oval(
            source[0] - source_half_width,
            source[1] - source_half_width,
            source[0] + source_half_width,
            source[1] + source_half_width,
            fill="",
            outline=color,
            width=1,
            dash=(2, 3),
            tags=("vector_overlay", "headlight_control"),
        )
        canvas.create_oval(
            target[0] - target_half_width,
            target[1] - target_half_width,
            target[0] + target_half_width,
            target[1] + target_half_width,
            fill="",
            outline=color,
            width=1,
            dash=(3, 3),
            tags=("vector_overlay", "headlight_control"),
        )
        canvas.create_oval(
            source[0] - radius,
            source[1] - radius,
            source[0] + radius,
            source[1] + radius,
            fill="#111820",
            outline=color,
            width=1,
            tags=("vector_overlay", "headlight_control"),
        )
        canvas.create_oval(
            target[0] - 10,
            target[1] - 10,
            target[0] + 10,
            target[1] + 10,
            fill="",
            outline="#fff3b0",
            width=2,
            tags=("vector_overlay", "headlight_control"),
        )
        canvas.create_oval(
            target[0] - 6,
            target[1] - 6,
            target[0] + 6,
            target[1] + 6,
            fill="#111820",
            outline=color,
            width=2,
            tags=("vector_overlay", "headlight_control"),
        )
        label_text = f"R{index}"
        label_x = source[0] + 11
        label_y = source[1] - 9
        label_w = 20
        canvas.create_rectangle(
            label_x - 3,
            label_y - 8,
            label_x + label_w,
            label_y + 8,
            fill="#10161a",
            outline="#fff3b0",
            width=1,
            tags=("vector_overlay", "headlight_control"),
        )
        canvas.create_text(
            label_x,
            label_y,
            text=label_text,
            anchor=tk.W,
            fill="#fff3b0",
            font=("Segoe UI", 8),
            tags=("vector_overlay", "headlight_control"),
        )
        hit_pad = 17
        self._register_canvas_overlay_region(
            "headlight",
            (source[0] - hit_pad, source[1] - hit_pad, source[0] + hit_pad + 6, source[1] + hit_pad + 6),
            index=index,
            handle="source",
        )
        self._register_canvas_overlay_region(
            "headlight",
            (target[0] - hit_pad, target[1] - hit_pad, target[0] + hit_pad, target[1] + hit_pad),
            index=index,
            handle="target",
        )
        self._draw_headlight_config_lollipop(
            canvas,
            index,
            source,
            target,
            width,
            height,
            color=color,
            expanded=getattr(self, "_headlight_config_index", None) == index,
            source_half_width=source_half_width,
        )

    def _set_headlight_handle(self, region: dict, x: float, y: float):
        canvas = getattr(self, "augmented_canvas", None)
        if canvas is None:
            return
        width = max(1.0, float(canvas.winfo_width() or 1))
        height = max(1.0, float(canvas.winfo_height() or 1))
        index = int(region.get("index", 1) or 1)
        handle = str(region.get("handle") or "source")
        sx_var, sy_var, tx_var, ty_var, _strength_var, _warmth_var = self._headlight_var_group(index)
        self._ensure_headlight_pair_defaults(index, width, height)
        clamped_x, clamped_y = self._clamp_canvas_point_to_preview_image(float(x), float(y))
        nx, ny = self._image_norm_from_canvas_point(clamped_x, clamped_y, width, height)
        def set_if_changed(variable, value: float) -> None:
            try:
                if abs(self._read_float_var(variable, -1.0) - float(value)) > 0.0008:
                    variable.set(value)
            except Exception:
                variable.set(value)
        try:
            if handle == "target":
                set_if_changed(tx_var, nx)
                set_if_changed(ty_var, ny)
            else:
                set_if_changed(sx_var, nx)
                set_if_changed(sy_var, ny)
        except Exception:
            pass

    def _draw_headlight_config_toolbox(self, canvas: tk.Canvas, width: int, height: int):
        index = getattr(self, "_headlight_config_index", None)
        if index not in (1, 2, 3):
            return
        panel_w = min(260, max(220, width - 24))
        panel_h = 188
        index = int(index)
        panel_pos = getattr(self, "_headlight_panel_pos", None)
        if panel_pos is None or getattr(self, "_headlight_panel_anchor_index", None) != index:
            source, target = self._headlight_points(index, width, height)
            _stem_start, anchor = self._headlight_config_lollipop_geometry(source, target, width, height)
            x = int(anchor[0] + 24)
            y = int(anchor[1] + 24)
            if x + panel_w > width - 8:
                x = int(anchor[0] - panel_w - 24)
            if y + panel_h > height - 8:
                y = int(anchor[1] - panel_h - 24)
            toggle_panel_w = 72 + 42 * 3 + 12
            toggle_panel_h = 68
            toggle_x = 10
            toggle_y = max(72, height - toggle_panel_h - 12)
            overlaps_toggle = (
                x < toggle_x + toggle_panel_w + 8
                and x + panel_w > toggle_x - 8
                and y < toggle_y + toggle_panel_h + 8
                and y + panel_h > toggle_y - 8
            )
            if overlaps_toggle:
                y = max(52, toggle_y - panel_h - 10)
            self._headlight_panel_anchor_index = index
        else:
            x = int(panel_pos[0])
            y = int(panel_pos[1])
        x = max(6, min(x, max(6, width - panel_w - 6)))
        y = max(52, min(y, max(52, height - panel_h - 10)))
        self._headlight_panel_pos = (x, y)
        strength_var, red_var, green_var, blue_var, cone_var, source_radius_var = self._headlight_control_vars(index)
        enabled = self._headlight_effect_enabled(index)
        color = self._headlight_color_from_vars(index, float(strength_var.get() or 0.0) if enabled else 0.0)
        panel_outline = "#ffd36a"
        panel_title = "#fff3b0"
        canvas.create_rectangle(x, y, x + panel_w, y + panel_h, fill="#10161a", outline=panel_outline, width=1, tags=("aug_overlay",))
        self._register_canvas_overlay_region("headlight_panel", (x, y, x + panel_w, y + panel_h), index=index)
        canvas.create_rectangle(x + 7, y + 4, x + 130, y + 24, fill="#172027", outline="#584b25", width=1, tags=("aug_overlay",))
        canvas.create_text(x + 12, y + 14, text=f"Reflektor R{index} {'ON' if enabled else 'OFF'}", anchor=tk.W, fill=panel_title, font=("Segoe UI", 9, "bold"), tags=("aug_overlay",))
        for yy in (y + 9, y + 14, y + 19):
            canvas.create_line(x + panel_w - 34, yy, x + panel_w - 14, yy, fill="#9aa7ad", width=1, tags=("aug_overlay",))
        self._register_canvas_overlay_region("headlight_panel_drag", (x, y, x + panel_w, y + 27), index=index)
        slider_x = x + 10
        slider_w = panel_w - 20
        rows = (
            ("Nat.", strength_var, 0.0, 1.0, 0.01),
            ("R", red_var, 0.0, 1.0, 0.01),
            ("G", green_var, 0.0, 1.0, 0.01),
            ("B", blue_var, 0.0, 1.0, 0.01),
            ("Prom. końca", cone_var, 0.02, 2.5, 0.01),
            ("Prom. startu", source_radius_var, 0.0, 2.5, 0.01),
        )
        row_y = y + 38
        for label, variable, from_, to, step in rows:
            role = str(label).strip().casefold() if str(label).strip().casefold() in {"r", "g", "b"} else None
            self._draw_canvas_slider(canvas, slider_x, row_y, slider_w, label, variable, from_, to, step, role=role)
            row_y += 24

    def _draw_arrow(self, canvas: tk.Canvas, start: tuple[int, int], end: tuple[int, int], color: str, dash=None):
        canvas.create_line(
            start[0],
            start[1],
            end[0],
            end[1],
            fill=color,
            width=2,
            arrow=tk.LAST,
            arrowshape=(10, 12, 4),
            dash=dash,
            tags=("vector_overlay",),
        )
        canvas.create_oval(
            start[0] - 3,
            start[1] - 3,
            start[0] + 3,
            start[1] + 3,
            fill=color,
            outline="",
            tags=("vector_overlay",),
        )

    def _default_vector_position(self, tool: str, width: int, height: int) -> tuple[tuple[int, int], tuple[int, int]]:
        value = 0.0
        angle = 0.0
        try:
            if tool == "wind":
                value = float(self.dirt_flow_wind_strength_var.get() or 0.0)
                angle_deg = float(self.dirt_flow_air_angle_var.get() or 0.0)
                if self._vector_tool == tool and abs(value) < 0.001 and abs(angle_deg) < 0.001:
                    angle_deg = 28.0
                angle = math.radians(angle_deg)
                direction = (math.sin(angle), math.cos(angle))
                mapping = {}
                try:
                    canvas = getattr(self, "augmented_canvas", None)
                    if canvas is not None:
                        mapping = self._preview_canvas_mappings.get(id(canvas), {}) or {}
                except Exception:
                    mapping = {}
                image_left = float(mapping.get("display_left", 0.0) or 0.0)
                image_top = float(mapping.get("display_top", 0.0) or 0.0)
                image_w = float(mapping.get("display_w", width) or width)
                image_h = float(mapping.get("display_h", height) or height)
                start = (
                    int(round(max(72.0, min(width - 92.0, image_left + image_w * 0.13)))),
                    int(round(max(72.0, min(height - 92.0, image_top + image_h * 0.17)))),
                )
            else:
                return (0, 0), (0, 0)
            display_value = max(value, 0.32) if self._vector_tool == tool else value
            length = self._vector_canvas_scale(width, height) * display_value
            end = (
                int(round(start[0] + direction[0] * length)),
                int(round(start[1] + direction[1] * length)),
            )
            return start, end
        except Exception:
            return (0, 0), (0, 0)

    def _vector_canvas_scale(self, width: int | None = None, height: int | None = None) -> float:
        canvas = getattr(self, "augmented_canvas", None)
        width = int(width if width is not None else (canvas.winfo_width() if canvas is not None else 320))
        height = int(height if height is not None else (canvas.winfo_height() if canvas is not None else 240))
        return max(60.0, min(180.0, min(width, height) * 0.34))

    def _canvas_overlay_hit(self, event) -> dict | None:
        x = float(getattr(event, "x", 0) or 0)
        y = float(getattr(event, "y", 0) or 0)
        hits: list[dict] = []
        for region in reversed(list(getattr(self, "_canvas_overlay_regions", []))):
            try:
                x1, y1, x2, y2 = region.get("rect", (0, 0, 0, 0))
                if x1 <= x <= x2 and y1 <= y <= y2:
                    hits.append(region)
            except Exception:
                continue
        if not hits:
            return None
        first = hits[0]
        if first.get("kind") != "headlight":
            return first
        active_index = int(getattr(self, "_active_headlight_index", 1) or 1)
        for region in hits:
            if region.get("kind") == "headlight" and int(region.get("index", 0) or 0) == active_index:
                return region
        return first

    def _set_canvas_slider_value(self, region: dict, x: float):
        variable = region.get("variable")
        if variable is None:
            return
        try:
            bar_x1, bar_x2 = region.get("bar", (0.0, 1.0))
            ratio = max(0.0, min(1.0, (float(x) - float(bar_x1)) / max(1.0, float(bar_x2) - float(bar_x1))))
            from_ = float(region.get("from_", 0.0))
            to = float(region.get("to", 1.0))
            step = float(region.get("step", 0.01) or 0.01)
            value = from_ + (to - from_) * ratio
            if step > 0:
                value = round(value / step) * step
            if step >= 1:
                value = int(round(value))
            variable.set(value)
        except Exception:
            pass

    def _set_canvas_range_slider_value(self, region: dict, x: float, handle: str | None = None):
        min_var = region.get("min_var")
        max_var = region.get("max_var")
        if min_var is None or max_var is None:
            return
        try:
            bar_x1, bar_x2 = region.get("bar", (0.0, 1.0))
            ratio = max(0.0, min(1.0, (float(x) - float(bar_x1)) / max(1.0, float(bar_x2) - float(bar_x1))))
            from_ = float(region.get("from_", 0.0))
            to = float(region.get("to", 1.0))
            step = float(region.get("step", 0.01) or 0.01)
            value = from_ + (to - from_) * ratio
            if step > 0:
                value = round(value / step) * step
            if step >= 1:
                value = int(round(value))
            if handle not in ("min", "max"):
                min_x = float(region.get("min_x", bar_x1))
                max_x = float(region.get("max_x", bar_x2))
                if abs(min_x - max_x) <= 2.0:
                    handle = "max" if float(x) >= max_x else "min"
                else:
                    handle = "min" if abs(float(x) - min_x) <= abs(float(x) - max_x) else "max"
            current_min = float(min_var.get())
            current_max = float(max_var.get())
            if abs(current_min - current_max) <= max(1e-9, step * 0.5):
                if value > current_max:
                    handle = "max"
                elif value < current_min:
                    handle = "min"
            if handle == "min":
                min_var.set(min(value, current_max))
                region["handle"] = "min"
            else:
                max_var.set(max(value, current_min))
                region["handle"] = "max"
        except Exception:
            pass

    def _default_preview_zoom(self) -> float:
        # Keep a working margin around the plate so HUD tools and headlights do
        # not cover the most important image area right after opening the modal.
        return 0.58

    def _toggle_preview_zoom(self):
        current = float(getattr(self, "_preview_zoom", self._default_preview_zoom()) or self._default_preview_zoom())
        steps = tuple(sorted({0.35, 0.5, round(self._default_preview_zoom(), 2), 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0}))
        next_value = steps[0]
        for value in steps:
            if current < value - 0.01:
                next_value = value
                break
        else:
            next_value = steps[0]
        self._preview_zoom = next_value
        if next_value <= 1.01:
            self._preview_pan_x = 0.0
            self._preview_pan_y = 0.0
        self._refresh_preview(redraw_only=True)

    def _on_preview_mousewheel(self, event):
        try:
            current = max(0.25, min(6.0, float(getattr(self, "_preview_zoom", self._default_preview_zoom()) or self._default_preview_zoom())))
            if getattr(event, "num", None) == 4:
                steps = 1.0
            elif getattr(event, "num", None) == 5:
                steps = -1.0
            else:
                steps = float(getattr(event, "delta", 0) or 0) / 120.0
            if abs(steps) <= 0.001:
                return None
            next_value = max(0.25, min(6.0, current * (1.10 ** steps)))
            if abs(next_value - current) > 0.001:
                self._preview_zoom = next_value
                if next_value <= 1.01:
                    self._preview_pan_x = 0.0
                    self._preview_pan_y = 0.0
                self._refresh_preview(redraw_only=True)
            return "break"
        except Exception:
            return None

    def _toggle_preview_fullscreen(self):
        self._preview_fullscreen = not bool(getattr(self, "_preview_fullscreen", False))
        self._apply_preview_fullscreen_layout(bool(self._preview_fullscreen))
        try:
            self.window.attributes("-fullscreen", bool(self._preview_fullscreen))
        except Exception:
            try:
                self.window.state("zoomed" if self._preview_fullscreen else "normal")
            except Exception:
                pass
        if self._preview_fullscreen:
            try:
                self.augmented_canvas.focus_set()
            except Exception:
                pass
        self._refresh_preview(redraw_only=True)

    def _apply_preview_fullscreen_layout(self, active: bool):
        try:
            if active:
                snapshot: dict[str, dict] = {}
                for widget_name in ("header_frame", "controls_host", "preview_toolbar", "footer_frame", "left_preview_frame"):
                    widget = getattr(self, widget_name, None)
                    if widget is not None:
                        try:
                            snapshot[widget_name] = dict(widget.grid_info() or {})
                        except Exception:
                            pass
                        widget.grid_remove()
                right = getattr(self, "right_preview_frame", None)
                if right is not None:
                    try:
                        snapshot["right_preview_frame"] = dict(right.grid_info() or {})
                    except Exception:
                        pass
                    right.grid_configure(row=0, column=0, columnspan=2, sticky=tk.NSEW, padx=0)
                self._preview_fullscreen_grid_snapshot = snapshot
            else:
                snapshot = dict(getattr(self, "_preview_fullscreen_grid_snapshot", {}) or {})

                def _restore_grid(widget_name: str, fallback: dict | None = None) -> None:
                    widget = getattr(self, widget_name, None)
                    if widget is None:
                        return
                    info = dict(snapshot.get(widget_name) or fallback or {})
                    try:
                        if info:
                            widget.grid(**info)
                        else:
                            widget.grid()
                    except Exception:
                        try:
                            widget.grid()
                        except Exception:
                            pass

                _restore_grid("header_frame")
                if not bool(getattr(self, "_effects_controls_panel_hidden", False)):
                    _restore_grid("controls_host")
                _restore_grid("preview_toolbar")
                _restore_grid("footer_frame")
                _restore_grid("left_preview_frame", {"row": 0, "column": 0, "sticky": tk.NSEW, "padx": (0, 5)})
                _restore_grid("right_preview_frame", {"row": 0, "column": 0, "sticky": tk.NSEW})
                self._preview_fullscreen_grid_snapshot = {}
        except Exception:
            pass

    def _on_escape_key(self, _event=None):
        if bool(getattr(self, "_preview_fullscreen", False)):
            self._preview_fullscreen = False
            self._apply_preview_fullscreen_layout(False)
            try:
                self.window.attributes("-fullscreen", False)
            except Exception:
                try:
                    self.window.state("normal")
                except Exception:
                    pass
            self._refresh_preview(redraw_only=True)
            return "break"
        return None

    def _on_tab_key(self, _event=None):
        widget = getattr(_event, "widget", None)
        try:
            widget_class = str(widget.winfo_class() or "")
            if widget_class in {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox"}:
                return None
        except Exception:
            pass
        self._fullscreen_show_original = not bool(getattr(self, "_fullscreen_show_original", False))
        try:
            self.augmented_canvas.focus_set()
        except Exception:
            pass
        self._refresh_preview(redraw_only=True)
        return "break"

    def _on_enter_key(self, event=None):
        widget = getattr(event, "widget", None)
        try:
            widget_class = str(widget.winfo_class() or "")
            if widget_class in {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox"}:
                return None
        except Exception:
            pass
        self._toggle_preview_fullscreen()
        return "break"

    def _on_space_key(self, event=None):
        widget = getattr(event, "widget", None)
        try:
            widget_class = str(widget.winfo_class() or "")
            if widget_class in {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox"}:
                return None
        except Exception:
            pass
        current = getattr(self, "_active_headlight_index", None)
        if current not in (1, 2, 3):
            next_index = 1
        elif current == 1:
            next_index = 2
        elif current == 2:
            next_index = 3
        else:
            next_index = None
        self._select_headlight(next_index)
        self._cancel_pending_preview()
        self._draw_vector_overlay()
        return "break"

    def _handle_canvas_overlay_press(self, event) -> bool:
        region = self._canvas_overlay_hit(event)
        if not region:
            return False
        kind = region.get("kind")
        if kind == "toolbox":
            self._select_toolbox(str(region.get("key") or self._active_toolbox))
            return True
        if kind == "action":
            action = str(region.get("action") or "")
            if action == "zoom":
                self._toggle_preview_zoom()
            elif action == "fullscreen":
                self._toggle_preview_fullscreen()
            elif action == "dice":
                self._pick_random_sample()
            elif action == "layout":
                self._reroll_effect_layout()
            elif action == "reset":
                self._reset_all_parameters()
            return True
        if kind == "check":
            variable = region.get("variable")
            try:
                variable.set(not bool(variable.get()))
            except Exception:
                pass
            self._refresh_preview(redraw_only=True)
            return True
        if kind == "slider":
            self._begin_canvas_live_edit()
            self._canvas_slider_drag = region
            self._set_canvas_slider_value(region, getattr(event, "x", 0))
            self._draw_vector_overlay()
            return True
        if kind == "range_slider":
            self._begin_canvas_live_edit()
            region["handle"] = None
            self._canvas_slider_drag = region
            self._set_canvas_range_slider_value(region, getattr(event, "x", 0))
            self._draw_vector_overlay()
            return True
        if kind == "panel_drag":
            self._toolbox_panel_drag = {
                "start_x": int(getattr(event, "x", 0)),
                "start_y": int(getattr(event, "y", 0)),
                "base": tuple(getattr(self, "_toolbox_panel_pos", None) or (10, 78)),
            }
            return True
        if kind == "panel_reset":
            self._toolbox_panel_pos = None
            self._toolbox_panel_collapsed = False
            self._draw_vector_overlay()
            return True
        if kind == "panel_toggle":
            self._toolbox_panel_collapsed = not bool(getattr(self, "_toolbox_panel_collapsed", False))
            self._draw_vector_overlay()
            return True
        if kind == "headlight":
            self._begin_canvas_live_edit()
            self._headlight_drag = region
            self._select_headlight(int(region.get("index", 1) or 1))
            if str(region.get("handle") or "") == "source":
                self._headlight_config_index = None
                self._headlight_panel_pos = None
                self._headlight_panel_anchor_index = None
            self._set_headlight_handle(region, getattr(event, "x", 0), getattr(event, "y", 0))
            try:
                canvas = getattr(self, "augmented_canvas", None)
                if canvas is not None:
                    canvas.grab_set()
            except Exception:
                pass
            self._draw_vector_overlay()
            return True
        if kind == "headlight_toggle":
            self._toggle_headlight_effect(int(region.get("index", 1) or 1))
            self._schedule_preview_refresh()
            self._draw_vector_overlay()
            return True
        if kind == "headlight_cone_toggle":
            self._toggle_headlight_cone_visibility(int(region.get("index", 1) or 1))
            self._draw_vector_overlay()
            return True
        if kind == "headlight_config_toggle":
            index = int(region.get("index", 1) or 1)
            if getattr(self, "_headlight_config_index", None) == index:
                self._headlight_config_index = None
                self._headlight_panel_pos = None
                self._headlight_panel_anchor_index = None
            else:
                if getattr(self, "_headlight_config_index", None) != index:
                    self._headlight_panel_pos = None
                    self._headlight_panel_anchor_index = None
                self._active_headlight_index = index
                self._headlight_config_index = index
            self._draw_vector_overlay()
            return True
        if kind == "headlight_panel_drag":
            self._headlight_panel_drag = {
                "start_x": int(getattr(event, "x", 0)),
                "start_y": int(getattr(event, "y", 0)),
                "base": tuple(getattr(self, "_headlight_panel_pos", None) or (10, 52)),
                "index": int(region.get("index", getattr(self, "_headlight_config_index", 1)) or 1),
            }
            return True
        if kind == "headlight_panel_reset":
            self._headlight_panel_pos = None
            self._headlight_panel_anchor_index = None
            self._draw_vector_overlay()
            return True
        if kind == "headlight_panel":
            return True
        return True

    def _event_vector_tool(self, event) -> str | None:
        canvas = getattr(self, "augmented_canvas", None)
        if canvas is None:
            return None
        try:
            current = canvas.find_withtag("current")
            for item in current:
                for tag in canvas.gettags(item):
                    if str(tag).startswith("vector_tool:"):
                        return str(tag).split(":", 1)[1]
        except Exception:
            return None
        return None

    def _nearest_headlight_index(self, x: float, y: float, tolerance: float = 12.0) -> int | None:
        canvas = getattr(self, "augmented_canvas", None)
        if canvas is None:
            return None
        width = max(1, int(canvas.winfo_width() or 1))
        height = max(1, int(canvas.winfo_height() or 1))
        best_index = None
        best_distance = float(tolerance)
        for index in (1, 2, 3):
            source, target = self._headlight_points(index, width, height)
            sx, sy = float(source[0]), float(source[1])
            tx, ty = float(target[0]), float(target[1])
            vx = tx - sx
            vy = ty - sy
            line_len2 = max(1.0, vx * vx + vy * vy)
            ratio = max(0.0, min(1.0, ((float(x) - sx) * vx + (float(y) - sy) * vy) / line_len2))
            px = sx + vx * ratio
            py = sy + vy * ratio
            distance = math.hypot(float(x) - px, float(y) - py)
            if distance < best_distance:
                best_distance = distance
                best_index = index
        return best_index

    def _on_vector_canvas_double_press(self, event):
        return None

    def _on_vector_canvas_press(self, event):
        if self._handle_canvas_overlay_press(event):
            return "break"
        tool = self._event_vector_tool(event)
        if tool:
            self._vector_tool = None if self._vector_tool == tool else tool
            self._vector_drag_start = None
            self._vector_drag_end = None
            self._draw_vector_overlay()
            return "break"
        if self._vector_tool:
            point = (int(event.x), int(event.y))
            self._vector_drag_start = point
            self._vector_drag_end = point
            self._draw_vector_overlay()
            return "break"
        if float(getattr(self, "_preview_zoom", 1.0) or 1.0) > 1.01:
            self._preview_pan_drag = (
                int(event.x),
                int(event.y),
                float(getattr(self, "_preview_pan_x", 0.0) or 0.0),
                float(getattr(self, "_preview_pan_y", 0.0) or 0.0),
            )
            return "break"
        return None

    def _on_vector_canvas_drag(self, event):
        if self._headlight_panel_drag is not None:
            start_x = int(self._headlight_panel_drag.get("start_x", 0) or 0)
            start_y = int(self._headlight_panel_drag.get("start_y", 0) or 0)
            base_x, base_y = self._headlight_panel_drag.get("base", (10, 52))
            self._headlight_panel_pos = (
                int(base_x) + int(getattr(event, "x", 0)) - start_x,
                int(base_y) + int(getattr(event, "y", 0)) - start_y,
            )
            try:
                self._headlight_panel_anchor_index = int(self._headlight_panel_drag.get("index", 0) or 0)
            except Exception:
                self._headlight_panel_anchor_index = getattr(self, "_headlight_config_index", None)
            self._request_vector_overlay_redraw()
            return "break"
        if self._toolbox_panel_drag is not None:
            start_x = int(self._toolbox_panel_drag.get("start_x", 0) or 0)
            start_y = int(self._toolbox_panel_drag.get("start_y", 0) or 0)
            base_x, base_y = self._toolbox_panel_drag.get("base", (10, 50))
            self._toolbox_panel_pos = (
                int(base_x) + int(getattr(event, "x", 0)) - start_x,
                int(base_y) + int(getattr(event, "y", 0)) - start_y,
            )
            self._request_vector_overlay_redraw()
            return "break"
        if self._headlight_drag is not None:
            self._set_headlight_handle(self._headlight_drag, getattr(event, "x", 0), getattr(event, "y", 0))
            self._request_vector_overlay_redraw()
            return "break"
        if self._canvas_slider_drag is not None:
            if self._canvas_slider_drag.get("kind") == "range_slider":
                self._set_canvas_range_slider_value(
                    self._canvas_slider_drag,
                    getattr(event, "x", 0),
                    str(self._canvas_slider_drag.get("handle") or ""),
                )
            else:
                self._set_canvas_slider_value(self._canvas_slider_drag, getattr(event, "x", 0))
            self._request_vector_overlay_redraw()
            return "break"
        if self._preview_pan_drag is not None:
            start_x, start_y, base_x, base_y = self._preview_pan_drag
            self._preview_pan_x = base_x + (int(event.x) - start_x)
            self._preview_pan_y = base_y + (int(event.y) - start_y)
            self._refresh_preview(redraw_only=True)
            return "break"
        if not self._vector_tool or self._vector_drag_start is None:
            return None
        self._vector_drag_end = (int(event.x), int(event.y))
        self._request_vector_overlay_redraw()
        return "break"

    def _on_vector_canvas_release(self, event):
        if self._headlight_panel_drag is not None:
            self._headlight_panel_drag = None
            return "break"
        if self._toolbox_panel_drag is not None:
            self._toolbox_panel_drag = None
            return "break"
        if self._headlight_drag is not None:
            self._set_headlight_handle(self._headlight_drag, getattr(event, "x", 0), getattr(event, "y", 0))
            self._headlight_drag = None
            try:
                canvas = getattr(self, "augmented_canvas", None)
                if canvas is not None:
                    canvas.grab_release()
            except Exception:
                pass
            self._end_canvas_live_edit(delay_ms=40)
            self._draw_vector_overlay()
            return "break"
        if self._canvas_slider_drag is not None:
            if self._canvas_slider_drag.get("kind") == "range_slider":
                self._set_canvas_range_slider_value(
                    self._canvas_slider_drag,
                    getattr(event, "x", 0),
                    str(self._canvas_slider_drag.get("handle") or ""),
                )
            else:
                self._set_canvas_slider_value(self._canvas_slider_drag, getattr(event, "x", 0))
            self._canvas_slider_drag = None
            self._end_canvas_live_edit(delay_ms=40)
            self._draw_vector_overlay()
            return "break"
        if self._preview_pan_drag is not None:
            self._preview_pan_drag = None
            return "break"
        if not self._vector_tool or self._vector_drag_start is None:
            return None
        tool = self._vector_tool
        start = self._vector_drag_start
        end = (int(event.x), int(event.y))
        self._vector_drag_start = None
        self._vector_drag_end = None
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 6:
            self._reset_vector_tool(tool)
            self._vector_tool = None
            self._draw_vector_overlay()
            return "break"
        self._vector_positions[tool] = (start, end)
        self._apply_vector_to_profile(tool, dx, dy, length)
        self._draw_vector_overlay()
        return "break"

    def _on_vector_canvas_motion(self, event):
        canvas = getattr(self, "augmented_canvas", None)
        if canvas is None:
            return None
        overlay = self._canvas_overlay_hit(event)
        hover_headlight_config = None
        if overlay and overlay.get("kind") == "headlight_config_toggle":
            try:
                hover_headlight_config = int(overlay.get("index", 0) or 0)
            except Exception:
                hover_headlight_config = None
        if getattr(self, "_headlight_config_hover_index", None) != hover_headlight_config:
            self._headlight_config_hover_index = hover_headlight_config
            self._request_vector_overlay_redraw()
        if overlay and overlay.get("kind") in ("slider", "range_slider"):
            cursor = "sb_h_double_arrow"
        elif overlay and overlay.get("kind") in ("panel_drag", "headlight_panel_drag"):
            cursor = "fleur"
        elif overlay and overlay.get("kind") in ("panel_reset", "panel_toggle", "headlight_panel_reset"):
            cursor = "hand2"
        elif overlay and overlay.get("kind") == "headlight":
            cursor = "fleur"
        elif overlay and overlay.get("kind") == "headlight_config_toggle":
            cursor = "hand2"
        elif overlay and overlay.get("kind") == "headlight_panel":
            cursor = "hand2"
        elif overlay:
            cursor = "hand2"
        else:
            cursor = "hand2" if self._event_vector_tool(event) else ("fleur" if float(getattr(self, "_preview_zoom", 1.0) or 1.0) > 1.01 else "")
        try:
            if str(canvas.cget("cursor") or "") != cursor:
                canvas.configure(cursor=cursor)
        except Exception:
            pass
        return None

    def _on_vector_canvas_leave(self, _event):
        if self._headlight_drag is not None:
            return None
        if getattr(self, "_headlight_config_hover_index", None) is not None:
            self._headlight_config_hover_index = None
            self._request_vector_overlay_redraw()
        canvas = getattr(self, "augmented_canvas", None)
        if canvas is not None:
            try:
                canvas.configure(cursor="")
            except Exception:
                pass
        return None

    def _reset_vector_tool(self, tool: str):
        try:
            self._vector_positions.pop(tool, None)
            if tool == "wind":
                self.dirt_flow_wind_strength_var.set(0.0)
                self.dirt_flow_air_angle_var.set(0.0)
        except Exception:
            pass

    def _apply_vector_to_profile(self, tool: str, dx: float, dy: float, length: float):
        canvas = getattr(self, "augmented_canvas", None)
        width = int(canvas.winfo_width() if canvas is not None else 320)
        height = int(canvas.winfo_height() if canvas is not None else 240)
        value = max(0.0, min(1.0, length / self._vector_canvas_scale(width, height)))
        try:
            if tool == "wind":
                angle = math.degrees(math.atan2(dx, max(1.0, abs(dy))))
                self.dirt_flow_air_angle_var.set(max(-75.0, min(75.0, angle)))
                self.dirt_flow_wind_strength_var.set(value)
        except Exception:
            pass

    def _draw_canvas_message(self, canvas: tk.Canvas, text: str):
        if canvas is None:
            return
        canvas.delete("all")
        width = max(1, int(canvas.winfo_width() or 1))
        height = max(1, int(canvas.winfo_height() or 1))
        canvas.create_text(
            width / 2,
            height / 2,
            text=str(text or ""),
            fill="#d0d0d0",
            width=max(120, width - 20),
            justify=tk.CENTER,
        )

    def _accept(self):
        self._cancel_pending_preview()
        profile = self._profile_from_vars()
        # Dataset production values live in PZ1; this modal only stores effect settings.
        if False and bool(profile.enabled) and int(getattr(profile, "extra_count", 0) or 0) <= 0:
            messagebox.showwarning(
                "Liczba dodatkowych zdjęć",
                "Wpisz, ile dodatkowych zdjęć program ma wygenerować do części train.\n\n"
                "Podgląd może działać bez tej liczby, ale zapis profilu augmentacji wymaga jawnej decyzji.",
                parent=self.window,
            )
            return
        self.result = profile
        self.window.destroy()

    def _cancel(self):
        self._cancel_pending_preview()
        self.result = None
        self.window.destroy()

    def _cancel_pending_preview(self):
        self._raw_preview_request_id += 1
        self._raw_preview_pending = False
        if self._preview_after_id is not None:
            try:
                self.window.after_cancel(self._preview_after_id)
            except Exception:
                pass
        self._preview_after_id = None
        if self._overlay_redraw_after_id is not None:
            try:
                self.window.after_cancel(self._overlay_redraw_after_id)
            except Exception:
                pass
        self._overlay_redraw_after_id = None


def ask_step4_augmentation_profile(
    master,
    *,
    target: str,
    profile: AugmentationProfile,
    sample_images: list[Path] | None = None,
    sample_pool_limit: int | None = None,
    install_callback=None,
) -> AugmentationProfile | None:
    return Step4AugmentationModal(
        master,
        target=target,
        profile=profile,
        sample_images=sample_images,
        sample_pool_limit=sample_pool_limit,
        install_callback=install_callback,
    ).show()
