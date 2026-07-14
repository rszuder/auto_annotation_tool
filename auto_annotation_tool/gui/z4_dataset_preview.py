"""Lightweight YOLO dataset preview for Z4/PZ1 variants."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from ..config import PIL_AVAILABLE
from ..utils import get_image_files, safe_load_yaml

if PIL_AVAILABLE:
    from PIL import Image, ImageDraw, ImageTk


def _resolve_dataset_root(dataset_path: str | Path | None) -> Path | None:
    raw = str(dataset_path or "").strip()
    if not raw:
        return None
    try:
        root = Path(raw)
    except Exception:
        return None
    if root.is_file():
        if root.name.lower() == "data.yaml":
            return root.parent
        return root.parent
    return root


def _load_class_names(dataset_root: Path) -> dict[int, str]:
    yaml_path = dataset_root / "data.yaml"
    try:
        payload = safe_load_yaml(yaml_path) or {}
    except Exception:
        payload = {}
    names = payload.get("names") if isinstance(payload, dict) else None
    result: dict[int, str] = {}
    if isinstance(names, list):
        for idx, name in enumerate(names):
            result[int(idx)] = str(name)
    elif isinstance(names, dict):
        for key, name in names.items():
            try:
                result[int(key)] = str(name)
            except Exception:
                pass
    return result


def _collect_dataset_items(dataset_root: Path) -> list[dict]:
    items: list[dict] = []
    for split in ("train", "val", "test"):
        images_dir = dataset_root / "images" / split
        labels_dir = dataset_root / "labels" / split
        if not images_dir.exists():
            continue
        try:
            images = get_image_files(images_dir)
        except Exception:
            images = []
        for image_path in images:
            items.append(
                {
                    "split": split,
                    "image": Path(image_path),
                    "label": labels_dir / f"{Path(image_path).stem}.txt",
                }
            )
    return items


def _read_yolo_label(label_path: Path) -> list[list[float]]:
    if not label_path.exists() or not label_path.is_file():
        return []
    rows: list[list[float]] = []
    try:
        for line in label_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                rows.append([float(part) for part in parts])
            except Exception:
                continue
    except Exception:
        return []
    return rows


def _draw_annotations(image, label_rows: list[list[float]], class_names: dict[int, str]):
    draw = ImageDraw.Draw(image)
    width, height = image.size

    for row in label_rows:
        class_id = int(row[0])
        cx, cy, bw, bh = row[1:5]
        x1 = (cx - bw / 2.0) * width
        y1 = (cy - bh / 2.0) * height
        x2 = (cx + bw / 2.0) * width
        y2 = (cy + bh / 2.0) * height
        draw.rectangle((x1, y1, x2, y2), outline="#2ecc71", width=max(2, width // 320))

        label = class_names.get(class_id, str(class_id))
        draw.rectangle((x1, max(0, y1 - 18), x1 + max(42, len(label) * 7 + 10), y1), fill="#102418")
        draw.text((x1 + 4, max(0, y1 - 16)), label, fill="#c8ffd7")

        keypoints = row[5:]
        points: list[tuple[float, float]] = []
        if len(keypoints) >= 6:
            step = 3 if len(keypoints) % 3 == 0 else 2
            for idx in range(0, len(keypoints), step):
                if idx + 1 >= len(keypoints):
                    break
                px = keypoints[idx] * width
                py = keypoints[idx + 1] * height
                visibility = keypoints[idx + 2] if step == 3 and idx + 2 < len(keypoints) else 1.0
                if visibility <= 0:
                    continue
                points.append((px, py))
        if len(points) >= 3:
            draw.line(points + [points[0]], fill="#ffd166", width=max(2, width // 360))
            radius = max(3, width // 260)
            for px, py in points:
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill="#ffd166")


def open_yolo_dataset_preview(host, dataset_path: str | Path | None):
    if not PIL_AVAILABLE:
        messagebox.showerror("Podgląd datasetu", "Pillow jest niedostępny, więc podgląd obrazów nie może zostać otwarty.")
        return None

    dataset_root = _resolve_dataset_root(dataset_path)
    if dataset_root is None or not dataset_root.exists():
        messagebox.showerror("Podgląd datasetu", "Nie znaleziono katalogu datasetu do podglądu.")
        return None

    items = _collect_dataset_items(dataset_root)
    if not items:
        messagebox.showinfo("Podgląd datasetu", "Ten dataset nie zawiera obrazów w strukturze images/train, images/val lub images/test.")
        return None

    parent = getattr(host, "frame", None)
    root = parent.winfo_toplevel() if parent is not None else None
    window = tk.Toplevel(root or parent)
    window.title(f"Podgląd datasetu: {dataset_root.name}")
    window.geometry("1120x760")
    window.minsize(860, 560)
    try:
        window.transient(root)
    except Exception:
        pass

    class_names = _load_class_names(dataset_root)
    state = {"index": 0, "photo": None}

    outer = ttk.Frame(window, padding=10)
    outer.pack(fill=tk.BOTH, expand=True)
    outer.columnconfigure(1, weight=1)
    outer.rowconfigure(1, weight=1)

    header_text = (
        f"{dataset_root}\n"
        "Podgląd pokazuje obrazy datasetu razem z labelkami YOLO z odpowiadającego folderu labels."
    )
    ttk.Label(outer, text=header_text, justify=tk.LEFT, wraplength=980).grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 8))

    list_frame = ttk.Frame(outer)
    list_frame.grid(row=1, column=0, sticky=tk.NS, padx=(0, 10))
    item_list = tk.Listbox(list_frame, width=42, activestyle="none", exportselection=False)
    item_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=item_list.yview)
    item_list.configure(yscrollcommand=item_scroll.set)
    item_list.pack(side=tk.LEFT, fill=tk.Y, expand=False)
    item_scroll.pack(side=tk.LEFT, fill=tk.Y)

    for item in items:
        label_count = len(_read_yolo_label(item["label"]))
        item_list.insert(tk.END, f"[{item['split']}] {item['image'].name}  ({label_count})")

    preview_frame = ttk.Frame(outer)
    preview_frame.grid(row=1, column=1, sticky=tk.NSEW)
    preview_frame.columnconfigure(0, weight=1)
    preview_frame.rowconfigure(0, weight=1)

    canvas = tk.Canvas(preview_frame, bg="#111111", highlightthickness=0)
    canvas.grid(row=0, column=0, sticky=tk.NSEW)

    info_var = tk.StringVar(value="")
    ttk.Label(preview_frame, textvariable=info_var, justify=tk.LEFT).grid(row=1, column=0, sticky=tk.EW, pady=(8, 0))

    def render_current():
        idx = max(0, min(int(state.get("index", 0)), len(items) - 1))
        state["index"] = idx
        item = items[idx]
        try:
            image = Image.open(item["image"]).convert("RGB")
        except Exception as exc:
            canvas.delete("all")
            canvas.create_text(20, 20, anchor=tk.NW, fill="#ff7777", text=f"Nie udało się odczytać obrazu: {exc}")
            return

        labels = _read_yolo_label(item["label"])
        _draw_annotations(image, labels, class_names)

        canvas.update_idletasks()
        cw = max(320, canvas.winfo_width())
        ch = max(240, canvas.winfo_height())
        iw, ih = image.size
        scale = min(cw / max(1, iw), ch / max(1, ih), 1.0)
        display_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
        display = image.resize(display_size)
        photo = ImageTk.PhotoImage(display)
        state["photo"] = photo

        canvas.delete("all")
        x = max(0, (cw - display_size[0]) // 2)
        y = max(0, (ch - display_size[1]) // 2)
        canvas.create_image(x, y, image=photo, anchor=tk.NW)

        info_var.set(
            f"{idx + 1}/{len(items)} | split: {item['split']} | "
            f"obraz: {item['image'].name} | anotacje: {len(labels)} | label: {item['label'].name}"
        )
        try:
            if item_list.curselection() != (idx,):
                item_list.selection_clear(0, tk.END)
                item_list.selection_set(idx)
                item_list.see(idx)
        except Exception:
            pass

    def select_index(idx: int):
        state["index"] = max(0, min(int(idx), len(items) - 1))
        render_current()

    def on_list_select(_event=None):
        selection = item_list.curselection()
        if selection:
            select_index(selection[0])

    def on_key(event=None):
        key = str(getattr(event, "keysym", "") or "").lower()
        if key in {"q", "left", "up", "prior"}:
            select_index(int(state["index"]) - 1)
            return "break"
        if key in {"e", "right", "down", "next", "space"}:
            select_index(int(state["index"]) + 1)
            return "break"
        if key == "home":
            select_index(0)
            return "break"
        if key == "end":
            select_index(len(items) - 1)
            return "break"
        if key == "escape":
            window.destroy()
            return "break"
        return None

    controls = ttk.Frame(outer)
    controls.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
    ttk.Label(
        controls,
        text="Nawigacja: Q / ← poprzedni, E / → następny, kliknięcie pozycji na liście.",
    ).pack(side=tk.LEFT)
    ttk.Button(controls, text="Poprzedni", command=lambda: select_index(int(state["index"]) - 1)).pack(side=tk.LEFT, padx=(12, 0))
    ttk.Button(controls, text="Następny", command=lambda: select_index(int(state["index"]) + 1)).pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(controls, text="Zamknij", command=window.destroy).pack(side=tk.RIGHT)

    item_list.bind("<<ListboxSelect>>", on_list_select)
    for widget in (window, canvas, item_list):
        try:
            widget.bind("<KeyPress>", on_key, add="+")
        except Exception:
            pass
    canvas.bind("<Configure>", lambda _event: render_current(), add="+")
    item_list.selection_set(0)
    render_current()
    try:
        window.focus_set()
        item_list.focus_set()
    except Exception:
        pass
    return window
