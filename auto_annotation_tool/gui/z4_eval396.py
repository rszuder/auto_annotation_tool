"""EVAL396 views reached from the existing Z4 track/results/report controls."""
from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import uuid

from ..ranking.eval396 import (DOMAINS, VARIANTS, EvidenceReader, load_eval396,
                              is_selection, default_selection, selection_reference)


def selected_eval396(tab):
    variable = getattr(tab, "rank_data_dir", None)
    return is_selection(variable.get()) if variable is not None else False


def track_candidate(repo_root):
    path = default_selection(repo_root)
    if not path.is_dir():
        return None
    try:
        info = selection_reference(path)
        return {"path": str(path), "id": info["reference_name"], "type": "MT / MZ",
                "split": "EVAL396", "split_count": 396, "counts": {}, "created": "2026-10-09",
                "source": "Zamrożony", "status": "do weryfikacji", "ready": True,
                "details": "396 scen • 479 tablic MT • 449 tekstów MZ"}
    except (OSError, ValueError) as exc:
        return {"path": str(path), "id": "EVAL396 — zamrożona selekcja", "ready": False,
                "status": "FAIL", "details": str(exc)}


def report_rows(report, domain=None, criterion="Exact Match"):
    rows = []
    for selected in ((domain,) if domain else DOMAINS):
        group = [{"model": label, "domain": selected, **report["summaries"][label]["per_domain"][selected]}
                 for label in VARIANTS]
        group.sort(key=lambda row: (-row["exact_match_rate"], row["model"]) if criterion == "Exact Match"
                   else (row["cer"], row["model"]))
        rows.extend(group)
    return rows


def report_markdown(report, criterion="Exact Match"):
    lines = ["# EVAL396 — ukończone pomiary MZ", "", "Status: PASS (zweryfikowany import istniejących wyników).",
             "Izolowane MZ na zatwierdzonych cropach GT. To nie jest mAP, E2E ani pomiar Androida.",
             "396 scen; 479 tablic lokalizacji; 449 zatwierdzonych tekstów; 30 unreadable poza mianownikiem OCR.",
             f"Porządek: {criterion}; bez automatycznego wyboru modelu wdrożeniowego.", "",
             "| Model | Domena | Tablice | Exact | Exact % | CER | no-read | Poprawne | Zamiany | Braki | Nadmiary |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report_rows(report, criterion=criterion):
        lines.append(f"| {row['model']} | {row['domain']} | {row['plates']} | {row['exact_matches']} | "
                     f"{row['exact_match_rate'] * 100:.2f} | {row['cer']:.4f} | {row['no_read']} | "
                     f"{row['correct_characters']} | {row['incorrect_characters']} | {row['missing_characters']} | {row['extra_characters']} |")
    lines += ["", "CER = suma odległości edycyjnych / liczba znaków GT (3052 ALL, 1522 DAY, 1530 NIGHT).", "",
              "## Pochodzenie", ""]
    for key in ("experiment_id", "selection_sha", "gt_freeze_sha", "comparison_sha", "selection_dir", "runs_dir"):
        lines.append(f"- {key}: `{report[key]}`")
    for model in report["models"]:
        lines.append(f"- {model['label']}: run `{model['run_id']}`, checkpoint SHA `{model['checkpoint_sha256']}`")
    lines += ["", "Parametry inferencji zapisanych pomiarów:", "", "```json",
              json.dumps(report["inference"], ensure_ascii=False, indent=2), "```", "", "## Ograniczenia", ""]
    lines += ["- " + text for text in report["limitations"]]
    lines += ["", "Pełne źródła i SHA plików: `provenance.json`. Import nie wykonuje inferencji ani treningu."]
    return "\n".join(lines) + "\n"


def export_report(report, output_root, criterion="Exact Match"):
    """Versioned report, never a new measurement. Verify sources again before publishing."""
    from .z4_analysis_ranking import _ranking_report_bar_svg
    output_root = Path(output_root).resolve()
    for name in ("selection_dir", "runs_dir"):
        if output_root.is_relative_to(Path(report[name]).resolve().parent.parent):
            raise ValueError("Raport musi być poza chronionym katalogiem eksperymentu.")
    reader = EvidenceReader()
    reader.receipt = dict(report["source_files"])
    reader.finish()
    output_root.mkdir(parents=True, exist_ok=True)
    name = "eval396_import_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    partial = output_root / (name + ".partial")
    partial.mkdir()
    (partial / "status.json").write_text('{"status":"PARTIAL","kind":"report_export"}', encoding="utf-8")
    rows = report_rows(report, criterion=criterion)
    columns = ("model", "domain", "plates", "exact_matches", "exact_match_rate", "cer", "no_read",
               "ground_truth_characters", "edit_distance", "correct_characters", "incorrect_characters",
               "missing_characters", "extra_characters")
    with (partial / "results.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    (partial / "report.md").write_text(report_markdown(report, criterion), encoding="utf-8")
    for metric, label, maximum, unit, precision in (("exact_match_rate", "Exact Match", 100, "%", 2),
                                                   ("cer", "CER", 1, "", 4)):
        bars = [{"label": row["model"] + " / " + row["domain"],
                 "score": row[metric] * (100 if metric == "exact_match_rate" else 1)} for row in rows]
        subtitle = "449 zatwierdzonych cropów GT; DAY 230 / NIGHT 219. " + (
            "Więcej = lepiej." if metric == "exact_match_rate" else "Mniej = lepiej; micro CER = edit distance / znaki GT.")
        svg = _ranking_report_bar_svg(bars, title="EVAL396 — MZ — " + label,
                                     maximum=maximum, unit=unit, precision=precision, subtitle=subtitle)
        (partial / (metric + ".svg")).write_text(svg, encoding="utf-8")
    (partial / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reader.finish()
    (partial / "status.json").write_text('{"status":"PASS","kind":"report_export"}', encoding="utf-8")
    target = output_root / name
    partial.rename(target)
    return target


def open_results(tab, *, export_after_load=False):
    existing = getattr(tab, "_eval396_dialog", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        if export_after_load:
            existing.export_eval_report()
        return existing
    dialog = tk.Toplevel(tab.frame)
    tab._eval396_dialog = dialog
    dialog.title("Z4 — EVAL396 — wyniki MZ i raport")
    dialog.geometry("1160x790")
    dialog.minsize(860, 640)
    dialog.transient(tab.frame.winfo_toplevel())
    shell = ttk.Frame(dialog, padding=16)
    shell.pack(fill="both", expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(5, weight=1)
    ttk.Label(shell, text="EVAL396 — zamrożona selekcja", font=("Segoe UI", 17, "bold")).grid(row=0, sticky="w")
    ttk.Label(shell, text="396 scen  •  479 tablic MT  •  449 tekstów MZ  •  30 nieczytelnych",
              font=("Segoe UI", 11)).grid(row=1, sticky="w", pady=(5, 3))
    ttk.Label(shell, text="Odczyt ukończonych MZ na cropach GT. MT: oczekuje na decyzję EXIF. Final_test: nieużyty.",
              wraplength=1040).grid(row=2, sticky="w", pady=(0, 10))
    status = tk.StringVar(value="INCOMPLETE — trwa weryfikacja SHA, rodowodu i zapisanych wyników…")
    ttk.Label(shell, textvariable=status, wraplength=1040).grid(row=3, sticky="ew", pady=(0, 10))
    controls = ttk.Frame(shell)
    controls.grid(row=4, sticky="ew", pady=(0, 10))
    domain, criterion = tk.StringVar(value="ALL"), tk.StringVar(value="Exact Match")
    for text, variable, values in (("Domena:", domain, DOMAINS), ("Porządek:", criterion, ("Exact Match", "CER"))):
        ttk.Label(controls, text=text).pack(side="left", padx=(0, 6))
        combo = ttk.Combobox(controls, textvariable=variable, values=values, state="readonly", width=14)
        combo.pack(side="left", padx=(0, 16))
        combo.bind("<<ComboboxSelected>>", lambda _event: refresh())
    ttk.Label(controls, text="Exact: więcej = lepiej  •  CER: mniej = lepiej").pack(side="left")
    columns = ("model", "plates", "exact", "cer", "no_read", "correct", "substitutions", "missing", "extra")
    table = ttk.Treeview(shell, columns=columns, show="headings", height=4)
    for name, label, width in zip(columns,
            ("Model", "Tablice", "Exact Match", "CER", "no-read", "Poprawne", "Zamiany", "Braki", "Nadmiary"),
            (125, 70, 155, 92, 72, 85, 75, 70, 75)):
        table.heading(name, text=label)
        table.column(name, width=width, minwidth=65, anchor="w" if name == "model" else "center")
    table.grid(row=5, sticky="nsew")
    canvas = tk.Canvas(shell, height=182, background="#101820", highlightthickness=0)
    canvas.grid(row=6, sticky="ew", pady=12)
    details = tk.Text(shell, height=7, wrap="word", font=("Consolas", 9))
    details.grid(row=7, sticky="ew")
    bottom = ttk.Frame(shell)
    bottom.grid(row=8, sticky="ew", pady=(12, 0))
    export = ttk.Button(bottom, text="[ RAPORT ] Eksportuj SVG / CSV / Markdown", state="disabled")
    export.pack(side="left")
    ttk.Button(bottom, text="Zamknij", command=dialog.destroy).pack(side="right")
    messages, report = queue.Queue(), None
    selection_path = Path(tab.rank_data_dir.get())
    busy = True

    def refresh():
        table.delete(*table.get_children())
        canvas.delete("all")
        if report is None:
            return
        rows = report_rows(report, domain.get(), criterion.get())
        for row in rows:
            table.insert("", "end", values=(row["model"], row["plates"],
                f"{row['exact_match_rate'] * 100:.2f}% ({row['exact_matches']}/{row['plates']})",
                f"{row['cer']:.4f}", row["no_read"], row["correct_characters"], row["incorrect_characters"],
                row["missing_characters"], row["extra_characters"]))
        exact = criterion.get() == "Exact Match"
        maximum = 100 if exact else max(.20, max(row["cer"] for row in rows))
        canvas.create_text(16, 19, anchor="w", fill="#f4f7f6", font=("Segoe UI", 11, "bold"),
                           text=f"MZ / {domain.get()} — {criterion.get()} — GT crops")
        available = max(200, canvas.winfo_width() - 260)
        for index, row in enumerate(rows):
            value = row["exact_match_rate"] * 100 if exact else row["cer"]
            y = 44 + index * 42
            canvas.create_text(16, y + 13, text=row["model"], anchor="w", fill="#f4f7f6")
            canvas.create_rectangle(150, y, 150 + available * value / maximum, y + 25,
                                    fill="#4aa3ff", outline="")
            canvas.create_text(165 + available * value / maximum, y + 13,
                               text=f"{value:.2f}%" if exact else f"{value:.4f}", anchor="w", fill="#f4f7f6")

    def request_export():
        nonlocal busy
        if report is None or busy:
            return
        busy = True
        export.configure(state="disabled")
        chosen = criterion.get()
        def worker():
            from ..config import CONFIG
            try:
                destination = export_report(report, Path(CONFIG.get_ranking_dir("char")) / "reports", chosen)
                messages.put(("exported", destination))
            except Exception as exc:
                messages.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        status.set("Ponownie sprawdzam źródła przed eksportem raportu…")

    def load_worker():
        try:
            data = load_eval396(selection_path, progress=lambda text: messages.put(("progress", text)))
            messages.put(("loaded", data))
        except Exception as exc:
            messages.put(("error", str(exc)))

    def poll():
        nonlocal report, busy
        if not dialog.winfo_exists():
            return
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == "progress":
                    status.set("INCOMPLETE — " + value)
                elif kind == "loaded":
                    report, busy = value, False
                    dialog.verified_report = value
                    status.set("PASS — SHA, 6 modeli, rodowód, 449 odczytów/model i agregacje zgodne. Źródła niezmienione.")
                    details.configure(state="normal")
                    details.delete("1.0", "end")
                    details.insert("1.0", "\n".join(f"{key}: {value[key]}" for key in
                        ("experiment_id", "selection_sha", "gt_freeze_sha", "comparison_sha", "runs_dir")) +
                        "\nOgraniczenia: near-duplicates i korpus pretrainingu nie są certyfikowane; import nie wybiera zwycięzcy.")
                    details.configure(state="disabled")
                    export.configure(state="normal")
                    refresh()
                    if export_after_load:
                        request_export()
                elif kind == "exported":
                    busy = False
                    export.configure(state="normal")
                    status.set("PASS — raport zapisany: " + str(value))
                elif kind == "error":
                    report, busy = None, False
                    dialog.verified_report = None
                    status.set("FAIL — " + str(value))
                    export.configure(state="disabled")
                    details.configure(state="normal")
                    details.delete("1.0", "end")
                    details.configure(state="disabled")
                    refresh()
        except queue.Empty:
            pass
        dialog.after(80, poll)

    dialog.export_eval_report = request_export
    dialog.result_table, dialog.status_variable = table, status
    canvas.bind("<Configure>", lambda _event: refresh())
    export.configure(command=request_export)
    threading.Thread(target=load_worker, daemon=True).start()
    dialog.after(80, poll)
    return dialog
