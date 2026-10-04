"""Small controlled-experiment section and asynchronous frozen validation for Z4."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..campaign_manager import CAMPAIGN
from ..training.mz_experiment_runtime import (
    MZ_VARIANTS, MZExperimentSelection, prepare_mz_experiment, read_mz_experiment_protocol,
)

_FIELDS = ("dataset_var", "dataset_variant_var", "base_model_var", "base_custom_var", "name_var",
           "epochs_var", "batch_var", "imgsz_var", "lr0_var", "device_var")


def is_active(host) -> bool:
    variable = getattr(host, "mz_mode_var", None)
    return bool(variable is not None and variable.get() and getattr(host, "_mz_protocol", None))


def _busy(host) -> bool:
    return bool(getattr(host, "_mz_validation_in_progress", False)
        or getattr(host, "_training_start_in_progress", False)
        or getattr(getattr(host, "trainer", None), "is_training", False))


def _frozen_widgets(host):
    for name in ("dataset_variant_combo", "base_combo", "base_custom_entry", "base_custom_btn",
                 "device_combo", "btn_apply_training_recommendation"):
        widget = getattr(host, name, None)
        if widget is not None:
            yield widget
    for row in getattr(host, "_train_recommendation_cells", []) or []:
        if row.get("editor") is not None:
            yield row["editor"]


def refresh_controls(host) -> None:
    active = is_active(host)
    busy = _busy(host)
    for name in ("mz_mode_check", "mz_load_button", "mz_variant_combo"):
        widget = getattr(host, name, None)
        if widget is not None:
            widget.configure(state="disabled" if busy else ("readonly" if name == "mz_variant_combo" else "normal"))
    if active:
        for widget in _frozen_widgets(host):
            widget.configure(state="disabled")


def _status(host, text):
    variable = getattr(host, "mz_status_var", None)
    if variable is not None:
        variable.set(text)


def _selection_status(selection):
    protocol = selection.protocol
    training = protocol["training"]
    return (f"STRICT • {protocol['experiment_id']} • {selection.variant}\n"
        f"Dataset: {protocol['dataset']['dataset_id']} • Model: {protocol['models'][selection.variant]['architecture']}\n"
        f"Epoki: {training['epochs']} • Batch: {training['batch']} • imgsz: {training['imgsz']}\n"
        f"Optimizer: {training['optimizer']} • Seed: {training['seed']} • Urządzenie: {training['device']}\n"
        "Protokół zweryfikowany. Pola zablokowane przez protokół.")


def validate_gui_context(host, protocol):
    if getattr(host, "_step4_fine_tune_parent_run_id", "") or host._resolve_step4_fine_tune_parent_run() is not None:
        raise ValueError("Tryb kontrolowany wymaga oficjalnych wag bazowych. Wyłącz kontekst dotrenowania przed startem.")
    if host._get_selected_training_target() != "char":
        raise ValueError("Ten eksperyment wymaga toru treningu znaków (Detect).")
    project = CAMPAIGN.get_active_project_name()
    if project and protocol.get("project") and project != protocol["project"]:
        raise ValueError("Otwórz projekt wskazany w protokole: " + protocol["project"])
    if project and protocol.get("iteration") is not None and CAMPAIGN.get_current_iteration_num() != protocol["iteration"]:
        raise ValueError("Aktywna iteracja nie odpowiada protokołowi eksperymentu.")


def _apply_selection(host, selection: MZExperimentSelection) -> None:
    if not getattr(host, "_mz_normal_values", None):
        host._mz_normal_values = {name:getattr(host, name).get() for name in _FIELDS if hasattr(host, name)}
        host._mz_normal_widget_states = [(widget, str(widget.cget("state"))) for widget in _frozen_widgets(host)]
    host._mz_protocol = deepcopy(selection.protocol)
    host._mz_active_variant = selection.variant
    host.mz_variant_var.set(selection.variant)
    host.mz_mode_var.set(True)
    request = selection.request
    host._mz_applying_protocol = True
    try:
        label = host._get_custom_base_model_label()
        host.base_custom_var.set(request["base_model"])
        host.base_model_var.set(label)
        host.dataset_var.set(request["dataset_path"])
        host.dataset_variant_var.set(selection.protocol["dataset"]["dataset_id"])
        for field, key in (("epochs_var", "epochs"), ("batch_var", "batch_size"),
                           ("imgsz_var", "img_size"), ("lr0_var", "lr0"), ("device_var", "device")):
            getattr(host, field).set(request[key])
        host.name_var.set(request["name"])
    finally:
        host._mz_applying_protocol = False
    _status(host, _selection_status(selection))
    refresh_controls(host)
    host._refresh_training_start_state()


def disable_mode(host) -> None:
    if _busy(host):
        host.mz_mode_var.set(bool(getattr(host, "_mz_protocol", None)))
        return
    host.mz_mode_var.set(False)
    host._mz_applying_protocol = True
    try:
        for name, value in (getattr(host, "_mz_normal_values", {}) or {}).items():
            getattr(host, name).set(value)
        for widget, state in getattr(host, "_mz_normal_widget_states", []) or []:
            widget.configure(state=state)
    finally:
        host._mz_applying_protocol = False
    host._mz_normal_values = None
    host._mz_normal_widget_states = []
    _status(host, "Tryb kontrolowany wyłączony. Zwykły trening.")
    host._refresh_training_start_state()


def _run_validation(host, protocol_loader, variant, on_success, *, loading=False):
    if _busy(host):
        return
    host._mz_validation_in_progress = True
    _status(host, "Sprawdzam protokół, dane, wagi i środowisko…")
    refresh_controls(host)
    host.btn_start_train.configure(state="disabled")

    def finish(selection, error):
        host._mz_validation_in_progress = False
        host._mz_validation_thread = None
        refresh_controls(host)
        if error:
            if is_active(host) and getattr(host, "_mz_active_variant", None):
                host.mz_variant_var.set(host._mz_active_variant)
            if loading and not getattr(host, "_mz_normal_values", None):
                host.mz_mode_var.set(False)
            _status(host, "Protokół nie został zaakceptowany: " + error)
            messagebox.showerror("Eksperyment kontrolowany", error)
            host._refresh_training_start_state()
            return
        try:
            validate_gui_context(host, selection.protocol)
            _status(host, _selection_status(selection))
            on_success(selection)
        except (ValueError, KeyError, OSError) as exc:
            if is_active(host) and getattr(host, "_mz_active_variant", None):
                host.mz_variant_var.set(host._mz_active_variant)
            if loading and not getattr(host, "_mz_normal_values", None):
                host.mz_mode_var.set(False)
            _status(host, "Start zablokowany: " + str(exc))
            messagebox.showerror("Eksperyment kontrolowany", str(exc))
            host._refresh_training_start_state()

    def worker():
        try:
            selection = prepare_mz_experiment(protocol_loader(), variant)
            error = ""
        except Exception as exc:
            selection, error = None, str(exc)
        host._ui(lambda result=selection, detail=error: finish(result, detail))

    thread = threading.Thread(target=worker, name="Z4MZFrozenPreflight", daemon=True)
    host._mz_validation_thread = thread
    try:
        thread.start()
    except Exception as exc:
        finish(None, str(exc))


def load_protocol(host, path=None):
    if _busy(host):
        return
    path = path or filedialog.askopenfilename(parent=host.frame, title="Wczytaj protokół eksperymentu",
        filetypes=[("Protokół JSON", "*.json")])
    if not path:
        if not getattr(host, "_mz_normal_values", None):
            host.mz_mode_var.set(False)
        return
    variant = host.mz_variant_var.get()
    _run_validation(host, lambda:read_mz_experiment_protocol(path), variant,
        lambda selection:_apply_selection(host, selection), loading=True)


def toggle_mode(host):
    if host.mz_mode_var.get():
        if getattr(host, "_mz_protocol", None):
            frozen = deepcopy(host._mz_protocol)
            _run_validation(host, lambda:frozen, host.mz_variant_var.get(),
                lambda selection:_apply_selection(host, selection), loading=True)
        else:
            load_protocol(host)
    else:
        disable_mode(host)


def select_variant(host):
    if not is_active(host):
        return
    frozen = deepcopy(host._mz_protocol)
    _run_validation(host, lambda:frozen, host.mz_variant_var.get(), lambda selection:_apply_selection(host, selection))


def verify_before_start(host, continuation):
    try:
        validate_gui_context(host, host._mz_protocol)
    except ValueError as exc:
        return messagebox.showerror("Eksperyment kontrolowany", str(exc))
    frozen = deepcopy(host._mz_protocol)
    _run_validation(host, lambda:frozen, host.mz_variant_var.get(), continuation)


def build_section(host, parent):
    host.mz_mode_var = tk.BooleanVar(master=host.frame, value=False)
    host.mz_variant_var = tk.StringVar(master=host.frame, value=MZ_VARIANTS[0])
    host.mz_status_var = tk.StringVar(master=host.frame, value="Tryb kontrolowany wyłączony. Wczytaj frozen protocol JSON.")
    section = ttk.LabelFrame(parent, text=" Eksperyment kontrolowany ", padding=9)
    section.pack(fill=tk.X, pady=(0, getattr(host, "_train_left_section_gap", 16)))
    host.mz_mode_check = ttk.Checkbutton(section, text="Tryb kontrolowany", variable=host.mz_mode_var,
        command=lambda:toggle_mode(host))
    host.mz_mode_check.pack(anchor=tk.W)
    row = ttk.Frame(section)
    row.pack(fill=tk.X, pady=(5, 5))
    host.mz_load_button = ttk.Button(row, text="Wczytaj protokół eksperymentu", command=lambda:load_protocol(host))
    host.mz_load_button.pack(side=tk.LEFT, fill=tk.X, expand=True)
    ttk.Label(row, text="Wariant:").pack(side=tk.LEFT, padx=(8, 4))
    host.mz_variant_combo = ttk.Combobox(row, values=MZ_VARIANTS, textvariable=host.mz_variant_var, state="readonly", width=6)
    host.mz_variant_combo.pack(side=tk.LEFT)
    host.mz_variant_combo.bind("<<ComboboxSelected>>", lambda event:select_variant(host))
    summary = ttk.Label(section, textvariable=host.mz_status_var, justify=tk.LEFT, wraplength=370)
    summary.pack(fill=tk.X)
    host._register_train_left_wrap_target(summary, padding=24, min_wrap=220)
    return section
