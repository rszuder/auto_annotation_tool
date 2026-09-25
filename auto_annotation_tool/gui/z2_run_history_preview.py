#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lekki podgląd próbek AT z historii runów Z2."""

from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageDraw, ImageOps, ImageTk


def select_evenly_spaced(items, limit=6):
    source = list(items or [])
    limit = max(1, int(limit or 6))
    if len(source) <= limit:
        return source
    if limit == 1:
        return [source[len(source) // 2]]
    last = len(source) - 1
    indices = []
    for slot in range(limit):
        idx = int(round(slot * last / (limit - 1)))
        if idx not in indices:
            indices.append(idx)
    return [source[idx] for idx in indices]


def collect_run_history_preview_items(host, run_dir, limit=6):
    safe_run = host._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
    if safe_run is None:
        return {"ok": False, "reason": "invalid_run", "items": []}

    safe_run = Path(safe_run)
    try:
        annotations = list(
            host._parse_cvat_preview_annotations(safe_run / "annotations.xml") or []
        )
    except Exception as exc:
        return {"ok": False, "reason": "xml_read_failed", "error": str(exc), "items": []}

    annotated = []
    for ann in annotations:
        try:
            plates = list(host._get_plate_detections(ann) or [])
        except Exception:
            plates = []
        if plates:
            annotated.append((ann, plates))

    try:
        manifest = dict(host._load_annotation_run_manifest(safe_run) or {})
    except Exception:
        manifest = {}

    try:
        image_dir = host._resolve_run_image_dir_for_annotations(
            annotations, manifest, safe_run
        )
    except Exception:
        image_dir = None

    try:
        images_with_plates, total_plates = host._get_run_plate_annotation_counts(safe_run)
    except Exception:
        images_with_plates = len(annotated)
        total_plates = sum(len(plates) for _, plates in annotated)

    items = []
    for ann, plates in select_evenly_spaced(annotated, limit):
        filename = str(getattr(ann, "filename", "") or "").strip()
        items.append(
            {
                "filename": filename,
                "plates": plates,
                "image_path": _resolve_image_path(safe_run, image_dir, filename),
            }
        )

    return {
        "ok": True,
        "reason": "",
        "run_dir": safe_run,
        "items": items,
        "images_with_plates": int(images_with_plates or 0),
        "total_plates": int(total_plates or 0),
    }


def open_run_history_preview(host, run_dir, limit=6):
    summary = collect_run_history_preview_items(host, run_dir, limit)
    parent = getattr(host, "frame", None)
    parent = parent.winfo_toplevel() if parent is not None else None

    if not summary.get("ok"):
        messagebox.showwarning(
            "Podgląd anotacji",
            "Nie udało się odczytać wybranego runu Z2.",
            parent=parent,
        )
        return False

    items = list(summary.get("items") or [])
    if not items:
        messagebox.showinfo(
            "Podgląd anotacji",
            "Wybrany run nie zawiera anotacji tablic do pokazania.",
            parent=parent,
        )
        return False

    palette = getattr(getattr(host, "app", None), "palette", {}) or {}
    panel = palette.get("panel", "#252526")
    field = palette.get("field", "#1a1a1a")
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    accent = palette.get("accent", "#4f8de3")
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

    dialog = tk.Toplevel(parent)
    try:
        host.app.style_dialog_window(
            dialog,
            title="Podgląd anotacji z historii Z2",
            geometry="1080x780",
            parent=parent,
        )
    except Exception:
        dialog.title("Podgląd anotacji z historii Z2")
        dialog.geometry("1080x780")

    body = tk.Frame(dialog, bg=panel)
    body.pack(fill=tk.BOTH, expand=True)

    run_dir_obj = Path(summary["run_dir"])
    tk.Label(
        body,
        text=(
            f"{run_dir_obj.name}  •  AT: {summary['total_plates']}  •  "
            f"obrazy z AT: {summary['images_with_plates']}"
        ),
        bg=panel,
        fg=fg,
        font=("Segoe UI", 12, "bold"),
        anchor="w",
    ).pack(fill=tk.X, padx=16, pady=(14, 2))
    tk.Label(
        body,
        text=(
            f"Próbka {len(items)} obrazów rozłożonych po całym runie. "
            "Podgląd jest tylko do odczytu."
        ),
        bg=panel,
        fg=muted,
        anchor="w",
    ).pack(fill=tk.X, padx=16, pady=(0, 10))

    grid = tk.Frame(body, bg=panel)
    grid.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
    for col in range(2):
        grid.grid_columnconfigure(col, weight=1, uniform="preview")
    for row in range(3):
        grid.grid_rowconfigure(row, weight=1, uniform="preview")

    refs = []
    for index, item in enumerate(items):
        card = tk.Frame(
            grid,
            bg=field,
            highlightthickness=1,
            highlightbackground=border,
        )
        card.grid(
            row=index // 2,
            column=index % 2,
            sticky="nsew",
            padx=5,
            pady=5,
        )

        photo = None
        error = ""
        image_path = item.get("image_path")
        if image_path is not None:
            try:
                rendered = _render_preview(
                    Path(image_path),
                    item.get("plates") or [],
                    outline=accent,
                    max_size=(490, 185),
                )
                photo = ImageTk.PhotoImage(rendered)
                refs.append(photo)
            except Exception as exc:
                error = str(exc)
        else:
            error = "Nie odnaleziono obrazu źródłowego."

        if photo is not None:
            tk.Label(card, image=photo, bg=field, bd=0).pack(
                fill=tk.BOTH, expand=True, padx=5, pady=(5, 2)
            )
        else:
            tk.Label(
                card,
                text="Brak podglądu obrazu",
                bg=field,
                fg=muted,
            ).pack(fill=tk.BOTH, expand=True, padx=5, pady=(10, 2))

        caption = (
            f"{item.get('filename') or '(bez nazwy)'}  •  "
            f"AT: {len(item.get('plates') or [])}"
        )
        if error:
            caption += f"\n{error}"
        tk.Label(
            card,
            text=caption,
            bg=field,
            fg=fg if not error else muted,
            anchor="w",
            justify=tk.LEFT,
            wraplength=470,
        ).pack(fill=tk.X, padx=7, pady=(2, 6))

    footer = ttk.Frame(body, style="Panel.TFrame")
    footer.pack(fill=tk.X, padx=16, pady=(0, 12))
    ttk.Button(footer, text="Zamknij", command=dialog.destroy).pack(side=tk.RIGHT)

    dialog._z2_history_preview_photo_refs = refs
    try:
        dialog.transient(parent)
        dialog.grab_set()
        dialog.focus_set()
    except Exception:
        pass
    return True


def _resolve_image_path(run_dir, image_dir, filename):
    if not filename:
        return None
    candidates = []
    if image_dir is not None:
        candidates.append(Path(image_dir) / Path(filename))
    candidates.extend(
        [
            Path(run_dir) / "images" / Path(filename),
            Path(run_dir) / Path(filename),
        ]
    )
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except Exception:
            pass
    return None


def _render_preview(image_path, plates, outline, max_size):
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")

    draw = ImageDraw.Draw(image)
    stroke = max(2, int(round(max(image.size) / 500.0)))

    for idx, detection in enumerate(plates, 1):
        polygon = list(getattr(detection, "polygon", None) or [])
        if len(polygon) >= 3:
            points = [(float(x), float(y)) for x, y in polygon]
            draw.line(points + [points[0]], fill=outline, width=stroke)
            x1 = min(x for x, _ in points)
            y1 = min(y for _, y in points)
        else:
            bbox = list(getattr(detection, "bbox", None) or [])
            if len(bbox) < 4:
                continue
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
            draw.rectangle((x1, y1, x2, y2), outline=outline, width=stroke)

        draw.text(
            (max(0, int(x1) + 3), max(0, int(y1) + 3)),
            f"AT {idx}",
            fill=outline,
        )

    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    return image
