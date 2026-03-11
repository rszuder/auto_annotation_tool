#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generowanie raportu treningu (HTML) + eksport wykresów Ultralytics do folderu runa.

Wynik:
- <run_dir>/plots/  (kopie wykresów z train/)
- <run_dir>/training_report.html (samodzielny HTML z osadzonymi obrazkami)
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
import base64
import mimetypes
import shutil


class TrainingReportGenerator:
    DEFAULT_PLOT_CANDIDATES = [
        "results.png",
        "PR_curve.png",
        "F1_curve.png",
        "P_curve.png",
        "R_curve.png",
        "confusion_matrix.png",
        "confusion_matrix_normalized.png",
        "labels.jpg",
        "labels.png",
    ]

    @staticmethod
    def _img_to_data_uri(img_path: Path) -> str:
        mime, _ = mimetypes.guess_type(str(img_path))
        if not mime:
            mime = "image/png"
        data = img_path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

    @classmethod
    def find_plots(cls, directory: Path) -> List[Path]:
        """Wyszukuje wykresy w katalogu (train/ albo plots/)."""
        if not directory.exists():
            return []

        found: List[Path] = []

        for name in cls.DEFAULT_PLOT_CANDIDATES:
            p = directory / name
            if p.exists() and p.is_file():
                found.append(p)

        already = {p.name for p in found}
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            for p in sorted(directory.glob(ext)):
                if p.is_file() and p.name not in already:
                    found.append(p)

        return found

    @classmethod
    def export_plots(cls, train_dir: Path, run_dir: Path) -> Path:
        """
        Kopiuje wykresy z train/ do run_dir/plots/.
        Zwraca ścieżkę do run_dir/plots.
        """
        plots = cls.find_plots(train_dir)
        out_dir = run_dir / "plots"
        out_dir.mkdir(parents=True, exist_ok=True)

        for p in plots:
            dst = out_dir / p.name
            try:
                shutil.copy2(p, dst)
            except Exception:
                try:
                    shutil.copy(p, dst)
                except Exception:
                    pass

        return out_dir

    @classmethod
    def generate_html(
        cls,
        run_dict: Dict,
        output_path: Path,
        plots_source_dir: Path,
        extra_info: Optional[Dict] = None,
    ) -> Path:
        """Generuje samodzielny raport HTML z wykresami (base64)."""
        plots = cls.find_plots(plots_source_dir)
        extra_info = extra_info or {}

        meta_rows = ""
        for k in [
            "id", "name", "status", "dataset_path", "base_model",
            "epochs", "batch_size", "img_size", "device",
            "current_epoch", "best_map50", "best_map50_95",
            "started_at", "finished_at", "paused_at",
            "best_weights", "last_weights", "error_message",
        ]:
            v = run_dict.get(k)
            if v not in (None, "", []):
                meta_rows += f"<tr><td>{k}</td><td>{v}</td></tr>"

        extra_rows = ""
        for k, v in extra_info.items():
            extra_rows += f"<tr><td>{k}</td><td>{v}</td></tr>"

        images_html = ""
        if plots:
            for p in plots:
                try:
                    uri = cls._img_to_data_uri(p)
                    images_html += f"""
                    <div class="card">
                      <div class="title">{p.name}</div>
                      <img src="{uri}" />
                    </div>
                    """
                except Exception as e:
                    images_html += f"<p>Nie udało się osadzić {p.name}: {e}</p>"
        else:
            images_html = "<p>Nie znaleziono wykresów. Upewnij się, że trening uruchamiasz z plots=True.</p>"

        html = f"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8"/>
  <title>Training Report - {run_dict.get('name','run')}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 16px; }}
    h1 {{ margin: 0 0 8px 0; }}
    .sub {{ color: #555; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 16px; }}
    td {{ border: 1px solid #ddd; padding: 6px 8px; vertical-align: top; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 10px; }}
    .title {{ font-weight: bold; margin-bottom: 8px; }}
    img {{ width: 100%; height: auto; border: 1px solid #eee; }}
    @media (max-width: 1000px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>Raport treningu</h1>
  <div class="sub">Wygenerowano: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>

  <h2>Metadane</h2>
  <table>
    {meta_rows}
    {extra_rows}
  </table>

  <h2>Wykresy (Ultralytics)</h2>
  <div class="grid">
    {images_html}
  </div>
</body>
</html>
"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return output_path