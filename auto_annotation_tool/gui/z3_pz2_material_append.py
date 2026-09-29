#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AZ009D — wejście UI appendu materiału do aktywnego PZ2."""

from __future__ import annotations

import json
from pathlib import Path
from tkinter import filedialog, messagebox

from ..campaign_manager import CAMPAIGN
from ..config import CONFIG
from ..registry.az_package_transport import (
    analyze_az_package,
    append_az_package,
    load_az_package,
)
from ..registry.az_registry import (
    AZRegistry,
    ensure_campaign_project,
)
from ..registry.pz2_append_materializer import (
    materialize_az_append_to_preview,
)


def open_pz2_add_material(host) -> bool:
    context = _resolve_active_project_context(host)
    if context is None:
        return False

    parent = _parent(host)
    preview_dir = context["preview_dir"]

    selected = filedialog.askdirectory(
        parent=parent,
        initialdir=str(preview_dir),
        title="Wybierz pakiet gotowych tablic + AZ",
    )
    if not selected:
        return False

    try:
        package = load_az_package(selected)
    except Exception as exc:
        _show_error(
            host,
            "Dodawanie materiału do zbioru",
            f"Wybrany katalog nie jest poprawnym pakietem cropów + AZ.\n\n{exc}",
        )
        return False

    registry = context["registry"]
    project_id = context["project_id"]
    iteration_num = context["iteration_num"]
    metadata_path = preview_dir / "metadata.json"
    images_dir = preview_dir / "images"

    try:
        _flush_preview_metadata(host)
        plan = analyze_az_package(
            registry,
            package,
            target_project_id=project_id,
        )
    except Exception as exc:
        _show_error(
            host,
            "Dodawanie materiału do zbioru",
            f"Nie udało się wykonać preflightu pakietu.\n\n{exc}",
        )
        return False

    if plan.new_count <= 0:
        if plan.already_present_count > 0:
            question = (
                "Pakiet nie zawiera nowych logical cropów do przypięcia, ale część materiału "
                "jest już zarejestrowana w tym projekcie.\n\n"
                f"Już przypięte: {plan.already_present_count}\n"
                f"Konflikty: {plan.conflict_count}\n"
                f"Nieprawidłowe: {plan.invalid_count}\n\n"
                "Sprawdzić, czy poprzedni append wymaga dokończenia w aktywnym PZ2?"
            )
            if not messagebox.askyesno(
                "Dokończ append materiału",
                question,
                parent=parent,
            ):
                return False
            try:
                result = materialize_az_append_to_preview(
                    registry,
                    package,
                    preview_dir=preview_dir,
                    target_project_id=project_id,
                    iteration_num=iteration_num,
                    append_result=None,
                )
                _refresh_after_append(host, metadata_path, result, package.package_id)
            except Exception as exc:
                _show_error(
                    host,
                    "Dokończenie appendu",
                    f"Nie udało się dokończyć appendu w PZ2.\n\n{exc}",
                )
                return False

            if result.added <= 0:
                _show_info(
                    host,
                    "Materiał już w zbiorze",
                    (
                        "Pakiet jest już w pełni obecny w aktywnym zbiorze PZ2.\n\n"
                        f"Obecnych rekordów: {result.after_count}\n"
                        f"Rozpoznanych rekordów pakietu: {result.candidates}"
                    ),
                )
            else:
                _show_success(host, result, plan)
            return True

        _show_info(
            host,
            "Brak nowego materiału",
            (
                "Pakiet nie zawiera cropów, które można dopiąć do bieżącego projektu.\n\n"
                f"Konflikty: {plan.conflict_count}\n"
                f"Nieprawidłowe: {plan.invalid_count}"
            ),
        )
        return False

    current_count = _current_metadata_count(host, metadata_path)
    projected_count = current_count + int(plan.new_count)
    confirmation = (
        "Ta operacja ROZSZERZY istniejący zbiór aktywnego projektu. "
        "Nie zastąpi bieżącego runu PZ2 i nie nadpisze lokalnej pracy.\n\n"
        f"Obecny zbiór: {current_count}\n"
        f"Nowe cropy do dopięcia: {plan.new_count}\n"
        f"Już obecne / bez duplikacji: {plan.already_present_count}\n"
        f"Konflikty pomijane: {plan.conflict_count}\n"
        f"Nieprawidłowe pomijane: {plan.invalid_count}\n"
        f"Z AZ w poprawnych rekordach: {plan.with_az_count}\n"
        f"Bez AZ w poprawnych rekordach: {plan.without_az_count}\n"
        f"Po operacji: {projected_count}\n\n"
        "Nowe AZ zostaną oznaczone jako wymagające lokalnej kontroli w tym projekcie."
    )
    if not messagebox.askyesno(
        "Dodaj materiał do zbioru",
        confirmation,
        parent=parent,
    ):
        return False

    try:
        append_result = append_az_package(
            registry,
            package,
            target_project_id=project_id,
            iteration_num=iteration_num,
            target_artifact_dir=images_dir,
        )
        result = materialize_az_append_to_preview(
            registry,
            package,
            preview_dir=preview_dir,
            target_project_id=project_id,
            iteration_num=iteration_num,
            append_result=append_result,
        )
        _refresh_after_append(host, metadata_path, result, package.package_id)
    except Exception as exc:
        _show_error(
            host,
            "Dodawanie materiału do zbioru",
            (
                "Append nie został poprawnie domknięty.\n\n"
                f"{exc}\n\n"
                "Istniejąca praca PZ2 nie została zastąpiona."
            ),
        )
        return False

    _show_success(host, result, plan)
    return True


def _resolve_active_project_context(host) -> dict | None:
    parent = _parent(host)
    try:
        project_name = str(CAMPAIGN.get_active_project_name() or "").strip()
        project_root = CAMPAIGN.get_active_project_root_dir()
        iteration_num = int(CAMPAIGN.get_current_iteration_num() or 0)
    except Exception:
        project_name = ""
        project_root = None
        iteration_num = 0

    if not project_name or project_root is None or iteration_num <= 0:
        messagebox.showwarning(
            "Dodaj materiał do zbioru",
            "Ta operacja wymaga aktywnego projektu kampanii.",
            parent=parent,
        )
        return None

    if not bool(getattr(host, "_step3_linear_mode", False)):
        messagebox.showwarning(
            "Dodaj materiał do zbioru",
            "Dodawanie materiału do projektu jest dostępne w projektowym PZ2.",
            parent=parent,
        )
        return None

    try:
        preview_raw = str(host.preview_dir_var.get() or "").strip()
    except Exception:
        preview_raw = ""
    if not preview_raw:
        messagebox.showwarning(
            "Dodaj materiał do zbioru",
            "PZ2 nie ma aktywnego runu. Najpierw przygotuj tablice w PZ1.",
            parent=parent,
        )
        return None

    preview_dir = Path(preview_raw)
    metadata_path = preview_dir / "metadata.json"
    images_dir = preview_dir / "images"
    if not metadata_path.is_file() or not images_dir.is_dir():
        messagebox.showwarning(
            "Dodaj materiał do zbioru",
            "Aktywny PZ2 nie ma kompletnego metadata.json + images/.",
            parent=parent,
        )
        return None

    loaded_meta_path = getattr(host, "_loaded_meta_path", None)
    if loaded_meta_path is not None:
        try:
            if Path(loaded_meta_path).resolve() != metadata_path.resolve():
                messagebox.showwarning(
                    "Dodaj materiał do zbioru",
                    "Widok PZ2 nie jest zsynchronizowany z aktywnym metadata.json. "
                    "Odśwież PZ2 przed dodaniem materiału.",
                    parent=parent,
                )
                return None
        except Exception:
            pass

    workspace = Path(CONFIG.WORKSPACE_DIR)
    registry = AZRegistry.for_workspace(workspace)
    project_root = Path(project_root)
    try:
        project_id = ensure_campaign_project(
            registry,
            project_name=project_name,
            folder_name=project_root.name,
        )
    except Exception as exc:
        _show_error(
            host,
            "Dodaj materiał do zbioru",
            f"Nie udało się ustalić project_id w AZ registry.\n\n{exc}",
        )
        return None

    return {
        "project_name": project_name,
        "project_root": project_root,
        "project_id": project_id,
        "iteration_num": iteration_num,
        "preview_dir": preview_dir,
        "registry": registry,
    }


def _flush_preview_metadata(host) -> None:
    flush = getattr(host, "_flush_scheduled_preview_metadata_save", None)
    if callable(flush):
        flush()


def _current_metadata_count(host, metadata_path: Path) -> int:
    live = getattr(host, "preview_metadata", None)
    if isinstance(live, dict):
        return len(live)
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        return len(payload) if isinstance(payload, dict) else 0
    except Exception:
        return 0


def _refresh_after_append(host, metadata_path: Path, result, package_id: str) -> None:
    payload = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError("Po appendzie metadata.json nie jest obiektem JSON.")

    host._apply_preview_metadata_update(
        payload,
        preserve_selection=True,
        render_selection=False,
        recalculate_statuses=False,
    )
    host._loaded_meta_path = metadata_path
    try:
        host._loaded_meta_mtime = metadata_path.stat().st_mtime
    except Exception:
        pass

    new_plate_ids = [
        str(item.plate_id)
        for item in getattr(result, "items", ())
        if str(getattr(item, "plate_id", "") or "").strip()
    ]
    if new_plate_ids:
        try:
            host._set_preview_import_focus(
                new_plate_ids,
                import_batch_id=package_id,
                activate=True,
            )
        except Exception:
            pass

    for refresh_name in (
        "_set_plates_legend_info",
        "_update_preview_repair_progress_ui",
        "_refresh_preview_source_panel",
    ):
        try:
            fn = getattr(host, refresh_name, None)
            if callable(fn):
                fn()
        except Exception:
            pass

    try:
        sync = getattr(host, "_sync_step3_access_from_preview_state", None)
        if callable(sync):
            sync(getattr(host, "preview_metadata", None))
    except Exception:
        pass


def _show_success(host, result, plan) -> None:
    _show_info(
        host,
        "Materiał dodany do zbioru",
        (
            "Rozszerzono TEN SAM aktywny zbiór PZ2.\n\n"
            f"Przed: {result.before_count}\n"
            f"Dodano do PZ2: {result.added}\n"
            f"Już obecne / bez duplikacji: {result.already_materialized}\n"
            f"AZ odzyskano: {result.with_az}\n"
            f"Bez AZ: {result.without_az}\n"
            f"Konflikty pakietu pominięte: {plan.conflict_count}\n"
            f"Nieprawidłowe pominięte: {plan.invalid_count}\n"
            f"Po: {result.after_count}\n\n"
            "Nowy materiał został ustawiony do lokalnej kontroli w PZ2."
        ),
    )


def _show_info(host, title: str, message: str) -> None:
    app = getattr(host, "app", None)
    themed = getattr(app, "themed_info", None)
    if callable(themed):
        try:
            themed(title, message, parent=_parent(host), tone="info")
            return
        except Exception:
            pass
    messagebox.showinfo(title, message, parent=_parent(host))


def _show_error(host, title: str, message: str) -> None:
    app = getattr(host, "app", None)
    themed = getattr(app, "themed_error", None)
    if callable(themed):
        try:
            themed(title, message, parent=_parent(host))
            return
        except Exception:
            pass
    messagebox.showerror(title, message, parent=_parent(host))


def _parent(host):
    frame = getattr(host, "frame", None)
    try:
        return frame.winfo_toplevel() if frame is not None else None
    except Exception:
        return frame
