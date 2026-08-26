#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contracts for ranking complete Android ALPR model packages.

The regular mobile exporter still builds one logical model package from one
checkpoint.  This module describes the research-level package candidate:
which optional vehicle model, which plate model, which character model, which
runtime variants and which mobile benchmark report belong to one comparable
experiment.
"""

from __future__ import annotations

import datetime as _dt
import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config import CONFIG, logger


MOBILE_PACKAGE_EXPERIMENT_SCHEMA = "alpr.mobile_package_experiment.v1"
MOBILE_BENCHMARK_REPORT_SCHEMA = "alpr.mobile_benchmark_report.v1"
MOBILE_ALPR_PACKAGE_SCHEMA = "alpr.package.v1"
MOBILE_RESEARCH_BUNDLE_SCHEMA = "alpr.mobile_research_bundle.v1"
MOBILE_THESIS_BUNDLE_SCHEMA = "alpr.mobile_thesis_bundle.v1"

MOBILE_REPORT_MAX_TEXT_BYTES = 32 * 1024 * 1024
MOBILE_REPORT_MAX_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MOBILE_REPORT_MAX_ENTRIES = 50000
MOBILE_REPORT_TRACE_PREVIEW_ROWS = 5000

DEFAULT_SCORE_WEIGHTS = {
    "quality": 0.50,
    "latency": 0.25,
    "memory": 0.15,
    "reliability": 0.10,
}

DEFAULT_SCORE_TARGETS = {
    "pipeline_p95_ms": 250.0,
    "ram_peak_mb": 512.0,
    "package_size_mb": 120.0,
}


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _safe_id(value: str, fallback: str = "pkg") -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    if not text:
        text = fallback
    if not re.match(r"^[A-Za-z0-9]", text):
        text = f"p-{text}"
    return text[:96]


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    parsed = _safe_float(value, None)
    if parsed is None:
        return default
    try:
        return int(parsed)
    except Exception:
        return default


def _clamp01(value: Any, default: float = 0.0) -> float:
    parsed = _safe_float(value, None)
    if parsed is None:
        return float(default)
    return max(0.0, min(1.0, float(parsed)))


def _metric01(value: Any, default: float = 0.0) -> float:
    parsed = _safe_float(value, None)
    if parsed is None:
        return float(default)
    if 1.0 < parsed <= 100.0:
        parsed /= 100.0
    return _clamp01(parsed, default)


def _nested_value(data: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = data
        ok = True
        for part in str(path).split("."):
            if isinstance(current, dict) and part in current:
                current = current.get(part)
            else:
                ok = False
                break
        if ok and current is not None and current != "":
            return current
    return None


def _role_marker(role: str) -> str:
    raw = str(role or "").strip().lower()
    if raw in {"plate", "plates", "pose", "tablica", "tablice", "mt"}:
        return "MT"
    if raw in {"character", "characters", "char", "chars", "znak", "znaki", "mz"}:
        return "MZ"
    if raw in {"vehicle", "vehicles", "pojazd", "pojazdy", "mp"}:
        return "MP"
    return raw.upper()[:4] or "M?"


def read_alprmodel_manifest(package_path: Path) -> dict[str, Any]:
    """Read the manifest from a single-model ``.alprmodel`` package."""
    safe_path = Path(package_path)
    if not safe_path.exists() or not safe_path.is_file():
        raise FileNotFoundError(f"Missing .alprmodel package: {safe_path}")
    with zipfile.ZipFile(safe_path, "r") as archive:
        if "manifest.json" not in set(archive.namelist()):
            raise ValueError(f"Package has no manifest.json: {safe_path}")
        return json.loads(archive.read("manifest.json").decode("utf-8"))


def read_alpr_package_manifest(package_path: Path) -> dict[str, Any]:
    """Read the manifest from a complete ``MT+MZ`` or ``MP+MT+MZ`` ALPR package."""
    manifest = read_alprmodel_manifest(package_path)
    if str(manifest.get("schema") or "") != MOBILE_ALPR_PACKAGE_SCHEMA:
        raise ValueError(f"Package is not a complete ALPR package: {package_path}")
    models = dict(manifest.get("models") or {})
    if not models.get("plate") or not models.get("character"):
        raise ValueError(f"Complete ALPR package has no required MT+MZ models: {package_path}")
    return manifest


@dataclass(frozen=True)
class ReportBundleEntry:
    """One safe, indexed entry inside a mobile report archive."""

    name: str
    file_size: int = 0
    compress_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReportBundleValidation:
    """Validation result shown before report metrics."""

    ok: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    checked_hashes: int = 0
    skipped_hashes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MobileReportBundle:
    """A safely parsed report bundle exported by the Android ALPR client."""

    path: str
    bundle_kind: str
    bundle_schema: str
    report: "MobileBenchmarkReport"
    manifest: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    report_payload: dict[str, Any] = field(default_factory=dict)
    trace_columns: tuple[str, ...] = field(default_factory=tuple)
    trace_rows: tuple[dict[str, str], ...] = field(default_factory=tuple)
    trace_total: int = 0
    sample_rows: tuple[dict[str, str], ...] = field(default_factory=tuple)
    sample_total: int = 0
    crop_count: int = 0
    annotation_count: int = 0
    log_preview: str = ""
    entries: tuple[ReportBundleEntry, ...] = field(default_factory=tuple)
    validation: ReportBundleValidation = field(
        default_factory=lambda: ReportBundleValidation(ok=True)
    )
    imported_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bundle_kind": self.bundle_kind,
            "bundle_schema": self.bundle_schema,
            "report": self.report.to_dict(),
            "manifest": dict(self.manifest or {}),
            "metadata": dict(self.metadata or {}),
            "trace_columns": list(self.trace_columns),
            "trace_rows": [dict(row) for row in self.trace_rows],
            "trace_total": self.trace_total,
            "sample_rows": [dict(row) for row in self.sample_rows],
            "sample_total": self.sample_total,
            "crop_count": self.crop_count,
            "annotation_count": self.annotation_count,
            "log_preview": self.log_preview,
            "entries": [entry.to_dict() for entry in self.entries],
            "validation": self.validation.to_dict(),
            "imported_at": self.imported_at,
        }


def _archive_name_safe(raw_name: str) -> tuple[bool, str]:
    normalized = str(raw_name or "").replace("\\", "/").strip()
    if not normalized:
        return False, normalized
    if normalized.startswith("/") or normalized.startswith("//"):
        return False, normalized
    if re.match(r"^[A-Za-z]:", normalized):
        return False, normalized
    parts = [part for part in normalized.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        return False, normalized
    return True, "/".join(parts)


def _compact_json_text(value: Any, *, limit: int = 900) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _report_payload_from_thesis_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload.setdefault("schema", MOBILE_BENCHMARK_REPORT_SCHEMA)
    payload.setdefault(
        "report_id",
        payload.get("report_id")
        or payload.get("bundle_id")
        or payload.get("session_id")
        or payload.get("package_id")
        or "thesis-report",
    )
    payload.setdefault("package_id", payload.get("package_id") or payload.get("model_package_id") or "thesis-package")
    payload.setdefault("variant_id", payload.get("variant_id") or payload.get("runtime") or "thesis")
    if "quality" not in payload and isinstance(payload.get("metrics"), dict):
        payload["quality"] = dict(payload.get("metrics") or {})
    payload.setdefault("raw_metadata_schema", metadata.get("schema", ""))
    return payload


class ReportBundleReader:
    """Open Android report bundles without unsafe extraction or full-image loading."""

    def __init__(
        self,
        *,
        max_text_bytes: int = MOBILE_REPORT_MAX_TEXT_BYTES,
        max_total_uncompressed_bytes: int = MOBILE_REPORT_MAX_TOTAL_UNCOMPRESSED_BYTES,
        max_entries: int = MOBILE_REPORT_MAX_ENTRIES,
        max_trace_rows: int = MOBILE_REPORT_TRACE_PREVIEW_ROWS,
    ):
        self.max_text_bytes = int(max_text_bytes)
        self.max_total_uncompressed_bytes = int(max_total_uncompressed_bytes)
        self.max_entries = int(max_entries)
        self.max_trace_rows = int(max_trace_rows)

    def read(self, path: Path) -> MobileReportBundle:
        safe_path = Path(path)
        if not safe_path.exists() or not safe_path.is_file():
            raise FileNotFoundError(f"Nie znaleziono raportu mobilnego: {safe_path}")
        if zipfile.is_zipfile(safe_path):
            return self._read_zip_bundle(safe_path)
        return self._read_json_report(safe_path)

    def _read_json_report(self, path: Path) -> MobileReportBundle:
        size = path.stat().st_size
        if size > self.max_text_bytes:
            raise ValueError(f"Plik raportu JSON jest za duży do bezpiecznego podglądu: {size} B")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            if not payload:
                raise ValueError("Plik JSON nie zawiera raportów.")
            payload = payload[0]
        if isinstance(payload, dict) and isinstance(payload.get("reports"), list):
            reports = list(payload.get("reports") or [])
            if not reports:
                raise ValueError("Plik JSON nie zawiera raportów.")
            payload = dict(reports[0] or {})
        if not isinstance(payload, dict):
            raise ValueError("Raport JSON musi być obiektem albo listą obiektów.")
        report = MobileBenchmarkReport.from_dict(payload)
        traces, columns, trace_total = self._trace_rows_from_json(payload.get("traces"))
        validation = ReportBundleValidation(
            ok=str(payload.get("schema") or MOBILE_BENCHMARK_REPORT_SCHEMA) == MOBILE_BENCHMARK_REPORT_SCHEMA,
            warnings=()
            if str(payload.get("schema") or MOBILE_BENCHMARK_REPORT_SCHEMA) == MOBILE_BENCHMARK_REPORT_SCHEMA
            else (f"Nieoczekiwany schemat raportu: {payload.get('schema')}",),
        )
        return MobileReportBundle(
            path=str(path),
            bundle_kind="json",
            bundle_schema=str(payload.get("schema") or MOBILE_BENCHMARK_REPORT_SCHEMA),
            report=report,
            report_payload=payload,
            trace_columns=tuple(columns),
            trace_rows=tuple(traces),
            trace_total=trace_total,
            validation=validation,
        )

    def _read_zip_bundle(self, path: Path) -> MobileReportBundle:
        errors: list[str] = []
        warnings: list[str] = []
        checked_hashes = 0
        skipped_hashes = 0
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > self.max_entries:
                errors.append(f"Archiwum ma zbyt dużo wpisów: {len(infos)}.")
            normalized_names: dict[str, zipfile.ZipInfo] = {}
            entries: list[ReportBundleEntry] = []
            total_uncompressed = 0
            for info in infos:
                ok, normalized = _archive_name_safe(info.filename)
                if not ok:
                    errors.append(f"Niebezpieczna ścieżka w archiwum: {info.filename}")
                    continue
                if normalized in normalized_names:
                    errors.append(f"Zduplikowany wpis w archiwum: {normalized}")
                    continue
                normalized_names[normalized] = info
                total_uncompressed += int(info.file_size or 0)
                entries.append(
                    ReportBundleEntry(
                        name=normalized,
                        file_size=int(info.file_size or 0),
                        compress_size=int(info.compress_size or 0),
                    )
                )
            if total_uncompressed > self.max_total_uncompressed_bytes:
                errors.append(
                    "Archiwum deklaruje zbyt duży rozmiar po rozpakowaniu: "
                    f"{total_uncompressed / (1024 * 1024):.1f} MB."
                )

            def read_text(name: str, *, optional: bool = False, limit: int | None = None) -> str:
                info = normalized_names.get(name)
                if info is None:
                    if not optional:
                        errors.append(f"Brakuje wpisu {name}.")
                    return ""
                max_bytes = int(limit or self.max_text_bytes)
                if int(info.file_size or 0) > max_bytes:
                    warnings.append(f"Pominięto zbyt duży wpis tekstowy {name}.")
                    return ""
                with archive.open(info, "r") as handle:
                    return handle.read(max_bytes + 1).decode("utf-8-sig", errors="replace")

            def read_json(name: str, *, optional: bool = False) -> dict[str, Any]:
                text = read_text(name, optional=optional)
                if not text:
                    return {}
                try:
                    value = json.loads(text)
                    if isinstance(value, dict):
                        return value
                    warnings.append(f"Wpis {name} nie jest obiektem JSON.")
                except Exception as exc:
                    errors.append(f"Nie udało się odczytać JSON {name}: {exc}")
                return {}

            manifest = read_json("manifest.json", optional=True)
            bundle_schema = str(manifest.get("schema") or "")
            metadata = read_json("metadata.json", optional=True)
            report_payload = read_json("report.json", optional=True)
            if not report_payload and metadata:
                report_payload = _report_payload_from_thesis_metadata(metadata)

            if not report_payload:
                errors.append("Archiwum nie zawiera czytelnego report.json ani metadata.json.")

            report_schema = str(report_payload.get("schema") or "")
            if report_payload and report_schema != MOBILE_BENCHMARK_REPORT_SCHEMA:
                warnings.append(f"Nieoczekiwany schemat report.json: {report_schema or 'brak'}.")

            if manifest:
                hash_errors, hash_warnings, checked_hashes, skipped_hashes = self._verify_manifest_hashes(
                    archive,
                    normalized_names,
                    manifest,
                )
                errors.extend(hash_errors)
                warnings.extend(hash_warnings)
            elif report_payload:
                warnings.append("Brak manifest.json, więc sprawdzono tylko strukturę raportu.")

            traces, trace_columns, trace_total = self._read_csv_from_zip(
                archive,
                normalized_names,
                "traces.csv" if "traces.csv" in normalized_names else "tables/trace_data.csv",
                optional=True,
            )
            if not traces and report_payload:
                traces, trace_columns, trace_total = self._trace_rows_from_json(report_payload.get("traces"))

            sample_rows, _sample_columns, sample_total = self._read_csv_from_zip(
                archive,
                normalized_names,
                "samples/index.csv",
                optional=True,
                max_rows=1000,
            )
            crop_count = sum(
                1
                for name in normalized_names
                if name.startswith("samples/crops/") and name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            )
            annotation_count = self._count_text_lines(
                archive,
                normalized_names.get("samples/annotations.jsonl"),
            )
            log_preview = read_text("application.log", optional=True, limit=512 * 1024)

            if not bundle_schema:
                if path.name.lower().endswith(".alprsession"):
                    bundle_schema = MOBILE_RESEARCH_BUNDLE_SCHEMA
                elif "tables/trace_data.csv" in normalized_names:
                    bundle_schema = MOBILE_THESIS_BUNDLE_SCHEMA
                else:
                    bundle_schema = MOBILE_BENCHMARK_REPORT_SCHEMA

            if bundle_schema == MOBILE_RESEARCH_BUNDLE_SCHEMA:
                bundle_kind = "alprsession"
            elif bundle_schema == MOBILE_THESIS_BUNDLE_SCHEMA:
                bundle_kind = "thesis"
            else:
                bundle_kind = "legacy_zip"

            report = MobileBenchmarkReport.from_dict(report_payload or {})
            validation = ReportBundleValidation(
                ok=not errors,
                errors=tuple(errors),
                warnings=tuple(warnings),
                checked_hashes=checked_hashes,
                skipped_hashes=skipped_hashes,
            )
            return MobileReportBundle(
                path=str(path),
                bundle_kind=bundle_kind,
                bundle_schema=bundle_schema,
                report=report,
                manifest=manifest,
                metadata=metadata,
                report_payload=report_payload,
                trace_columns=tuple(trace_columns),
                trace_rows=tuple(traces),
                trace_total=trace_total,
                sample_rows=tuple(sample_rows),
                sample_total=sample_total,
                crop_count=crop_count,
                annotation_count=annotation_count,
                log_preview=log_preview,
                entries=tuple(entries),
                validation=validation,
            )

    def _verify_manifest_hashes(
        self,
        archive: zipfile.ZipFile,
        normalized_names: dict[str, zipfile.ZipInfo],
        manifest: dict[str, Any],
    ) -> tuple[list[str], list[str], int, int]:
        errors: list[str] = []
        warnings: list[str] = []
        checked = 0
        skipped = 0
        raw_hashes = manifest.get("entry_sha256") or manifest.get("sha256") or {}
        if not isinstance(raw_hashes, dict):
            warnings.append("Manifest nie zawiera słownika entry_sha256.")
            return errors, warnings, checked, skipped
        for raw_name, expected in raw_hashes.items():
            ok, normalized = _archive_name_safe(str(raw_name or ""))
            if not ok or normalized == "manifest.json":
                continue
            info = normalized_names.get(normalized)
            if info is None:
                errors.append(f"Manifest wymienia brakujący wpis: {normalized}")
                continue
            expected_hash = str(expected or "").strip().lower()
            if not expected_hash:
                skipped += 1
                continue
            digest = hashlib.sha256()
            try:
                with archive.open(info, "r") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        if not chunk:
                            break
                        digest.update(chunk)
                checked += 1
                actual = digest.hexdigest().lower()
                if actual != expected_hash:
                    errors.append(f"SHA-256 nie zgadza się dla {normalized}.")
            except Exception as exc:
                errors.append(f"Nie udało się policzyć SHA-256 dla {normalized}: {exc}")
        return errors, warnings, checked, skipped

    def _read_csv_from_zip(
        self,
        archive: zipfile.ZipFile,
        normalized_names: dict[str, zipfile.ZipInfo],
        name: str,
        *,
        optional: bool = False,
        max_rows: int | None = None,
    ) -> tuple[list[dict[str, str]], list[str], int]:
        info = normalized_names.get(name)
        if info is None:
            if not optional:
                raise FileNotFoundError(name)
            return [], [], 0
        rows: list[dict[str, str]] = []
        columns: list[str] = []
        total = 0
        limit = self.max_trace_rows if max_rows is None else int(max_rows)
        with archive.open(info, "r") as binary:
            wrapper = io.TextIOWrapper(binary, encoding="utf-8-sig", errors="replace", newline="")
            reader = csv.DictReader(wrapper)
            columns = [str(item or "") for item in (reader.fieldnames or [])]
            for row in reader:
                total += 1
                if len(rows) < limit:
                    rows.append({str(key or ""): str(value or "") for key, value in dict(row or {}).items()})
        return rows, columns, total

    def _count_text_lines(self, archive: zipfile.ZipFile, info: zipfile.ZipInfo | None) -> int:
        if info is None:
            return 0
        total = 0
        with archive.open(info, "r") as handle:
            for _line in handle:
                total += 1
        return total

    def _trace_rows_from_json(self, traces_value: Any) -> tuple[list[dict[str, str]], list[str], int]:
        if not isinstance(traces_value, list):
            return [], [], 0
        rows: list[dict[str, str]] = []
        columns: list[str] = []
        seen: set[str] = set()
        for item in traces_value:
            if not isinstance(item, dict):
                continue
            row: dict[str, str] = {}
            for key in ("frame_id", "timestamp_ms", "status", "text"):
                row[key] = str(item.get(key, ""))
            for nested_name, suffix in (("stage_ms", "_ms"), ("confidence", ""), ("counters", ""), ("memory", "")):
                nested = item.get(nested_name)
                if not isinstance(nested, dict):
                    continue
                for key, value in nested.items():
                    column = str(key)
                    if suffix and not column.endswith(suffix):
                        column = f"{column}{suffix}"
                    row[column] = str(value)
            for key in row:
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
            if len(rows) < self.max_trace_rows:
                rows.append(row)
        return rows, columns, len([item for item in traces_value if isinstance(item, dict)])


def read_mobile_report_bundle(path: Path, *, max_trace_rows: int = MOBILE_REPORT_TRACE_PREVIEW_ROWS) -> MobileReportBundle:
    """Read an Android report bundle according to the mobile-report handoff."""
    return ReportBundleReader(max_trace_rows=max_trace_rows).read(path)


@dataclass(frozen=True)
class ExperimentModelRef:
    """A stable model reference used by package-level experiments."""

    model_id: str
    role: str
    checkpoint: str = ""
    package_path: str = ""
    run_id: str = ""
    run_label: str = ""
    dataset_id: str = ""
    dataset_path: str = ""
    yolo_family: str = ""
    yolo_version: str = ""
    parameter_count: int = 0
    file_size_mb: float = 0.0
    best_epoch: int = 0
    total_epochs: int = 0
    created_at: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def marker(self) -> str:
        return _role_marker(self.role)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentModelRef":
        fields = set(cls.__dataclass_fields__)
        payload = {key: value for key, value in dict(data or {}).items() if key in fields}
        return cls(
            model_id=_safe_id(str(payload.get("model_id") or payload.get("checkpoint") or "model")),
            role=str(payload.get("role") or ""),
            checkpoint=str(payload.get("checkpoint") or ""),
            package_path=str(payload.get("package_path") or ""),
            run_id=str(payload.get("run_id") or ""),
            run_label=str(payload.get("run_label") or ""),
            dataset_id=str(payload.get("dataset_id") or ""),
            dataset_path=str(payload.get("dataset_path") or ""),
            yolo_family=str(payload.get("yolo_family") or ""),
            yolo_version=str(payload.get("yolo_version") or ""),
            parameter_count=_safe_int(payload.get("parameter_count")),
            file_size_mb=float(_safe_float(payload.get("file_size_mb"), 0.0) or 0.0),
            best_epoch=_safe_int(payload.get("best_epoch")),
            total_epochs=_safe_int(payload.get("total_epochs")),
            created_at=str(payload.get("created_at") or ""),
            metrics=dict(payload.get("metrics") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )

    @classmethod
    def from_mobile_export_candidate(cls, candidate: dict[str, Any]) -> "ExperimentModelRef":
        """Build a model reference from the candidate dict used by the export UI."""
        run = candidate.get("run")
        metadata = candidate.get("model_metadata") if isinstance(candidate.get("model_metadata"), dict) else {}
        info = candidate.get("model_info") if isinstance(candidate.get("model_info"), dict) else {}
        best_weights = candidate.get("best_weights")
        checkpoint = str(best_weights or candidate.get("checkpoint") or "").strip()
        model_id = str(candidate.get("model_label") or Path(checkpoint).stem or "model")
        metrics = {
            "map50": candidate.get("best_map50"),
            "map50_95": candidate.get("best_map50_95"),
        }
        return cls(
            model_id=_safe_id(model_id, fallback="model"),
            role=str(candidate.get("role") or candidate.get("target") or ""),
            checkpoint=checkpoint,
            run_id=str(getattr(run, "id", "") or candidate.get("run_id") or ""),
            run_label=str(candidate.get("run_label") or getattr(run, "name", "") or ""),
            dataset_id=str(candidate.get("dataset_label") or ""),
            dataset_path=str(candidate.get("dataset_path") or getattr(run, "dataset_path", "") or ""),
            yolo_family=str(info.get("architecture_label") or info.get("yolo_variant") or ""),
            yolo_version=str(candidate.get("model_version") or info.get("version") or ""),
            parameter_count=_safe_int(info.get("parameter_count") or candidate.get("parameter_count")),
            file_size_mb=float(_safe_float(candidate.get("file_size_mb"), 0.0) or 0.0),
            best_epoch=_safe_int(candidate.get("best_epoch")),
            total_epochs=_safe_int(candidate.get("total_epochs") or getattr(run, "current_epoch", 0)),
            created_at=str(candidate.get("created_at") or getattr(run, "created_at", "") or ""),
            metrics=metrics,
            metadata={"source": "mobile_export_candidate", **metadata},
        )

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any], *, package_path: str = "") -> "ExperimentModelRef":
        training = dict(manifest.get("training") or {})
        source = dict(manifest.get("source") or {})
        metrics = dict(manifest.get("metrics") or {})
        model = dict(manifest.get("model") or {})
        checkpoint = str(source.get("checkpoint") or "").strip()
        return cls(
            model_id=_safe_id(str(manifest.get("model_id") or Path(checkpoint).stem or "model")),
            role=str(manifest.get("role") or ""),
            checkpoint=checkpoint,
            package_path=str(package_path or ""),
            run_id=str(training.get("run_id") or training.get("id") or ""),
            run_label=str(training.get("run_label") or training.get("name") or ""),
            dataset_id=str(training.get("dataset_id") or training.get("dataset_label") or ""),
            dataset_path=str(training.get("dataset_path") or ""),
            yolo_family=str(model.get("family") or model.get("architecture_label") or source.get("architecture_label") or ""),
            yolo_version=str(model.get("version") or source.get("model_version") or ""),
            parameter_count=_safe_int(source.get("parameter_count") or model.get("parameter_count")),
            file_size_mb=float(_safe_float(source.get("file_size_mb"), 0.0) or 0.0),
            best_epoch=_safe_int(metrics.get("best_epoch")),
            total_epochs=_safe_int(training.get("total_epochs") or training.get("current_epoch") or training.get("epochs")),
            created_at=str(source.get("exported_at") or training.get("finished_at") or training.get("created_at") or ""),
            metrics=metrics,
            metadata={"source": "manifest", "manifest_schema": manifest.get("schema", "")},
        )


@dataclass(frozen=True)
class RuntimeVariantSpec:
    id: str
    runtime: str
    precision: str = "fp32"
    image_size: int = 640
    confidence_threshold: float = 0.25
    iou_threshold: float = 0.45
    calibration_dataset_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeVariantSpec":
        return cls(
            id=_safe_id(str(data.get("id") or f"{data.get('runtime', 'runtime')}-{data.get('precision', 'fp32')}")),
            runtime=str(data.get("runtime") or ""),
            precision=str(data.get("precision") or "fp32").lower(),
            image_size=_safe_int(data.get("image_size") or data.get("imgsz"), 640),
            confidence_threshold=float(_safe_float(data.get("confidence_threshold"), 0.25) or 0.25),
            iou_threshold=float(_safe_float(data.get("iou_threshold"), 0.45) or 0.45),
            calibration_dataset_id=str(data.get("calibration_dataset_id") or ""),
        )


@dataclass(frozen=True)
class DatasetRef:
    dataset_id: str = ""
    path: str = ""
    split_name: str = ""
    image_count: int = 0
    plate_count: int = 0
    char_count: int = 0
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DatasetRef":
        payload = dict(data or {})
        return cls(
            dataset_id=str(payload.get("dataset_id") or payload.get("id") or ""),
            path=str(payload.get("path") or ""),
            split_name=str(payload.get("split_name") or payload.get("split") or ""),
            image_count=_safe_int(payload.get("image_count") or payload.get("images")),
            plate_count=_safe_int(payload.get("plate_count") or payload.get("plates")),
            char_count=_safe_int(payload.get("char_count") or payload.get("chars")),
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass(frozen=True)
class MobilePackageCandidate:
    """A complete ALPR candidate composed of MT+MZ and optional MP."""

    package_id: str
    plate_model: ExperimentModelRef
    character_model: ExperimentModelRef
    vehicle_model: ExperimentModelRef | None = None
    variants: tuple[RuntimeVariantSpec, ...] = field(default_factory=tuple)
    ranking_dataset: DatasetRef = field(default_factory=DatasetRef)
    calibration_dataset: DatasetRef = field(default_factory=DatasetRef)
    created_at: str = field(default_factory=_utc_now_iso)
    status: str = "candidate"
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def model_ids(self) -> tuple[str, ...]:
        if self.vehicle_model is not None:
            return (self.vehicle_model.model_id, self.plate_model.model_id, self.character_model.model_id)
        return (self.plate_model.model_id, self.character_model.model_id)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.plate_model.marker != "MT":
            problems.append("plate_model must have MT/plate role")
        if self.character_model.marker != "MZ":
            problems.append("character_model must have MZ/character role")
        if self.vehicle_model is not None and self.vehicle_model.marker != "MP":
            problems.append("vehicle_model must have MP/vehicle role")
        if not self.variants:
            problems.append("at least one runtime variant is required")
        if not str(self.package_id or "").strip():
            problems.append("package_id is required")
        return problems

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "package_id": self.package_id,
            "plate_model": self.plate_model.to_dict(),
            "character_model": self.character_model.to_dict(),
            "variants": [variant.to_dict() for variant in self.variants],
            "ranking_dataset": self.ranking_dataset.to_dict(),
            "calibration_dataset": self.calibration_dataset.to_dict(),
            "created_at": self.created_at,
            "status": self.status,
            "notes": self.notes,
            "metadata": dict(self.metadata or {}),
        }
        if self.vehicle_model is not None:
            payload["vehicle_model"] = self.vehicle_model.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MobilePackageCandidate":
        vehicle_payload = data.get("vehicle_model")
        return cls(
            package_id=_safe_id(str(data.get("package_id") or "package")),
            plate_model=ExperimentModelRef.from_dict(dict(data.get("plate_model") or {})),
            character_model=ExperimentModelRef.from_dict(dict(data.get("character_model") or {})),
            vehicle_model=ExperimentModelRef.from_dict(dict(vehicle_payload or {})) if vehicle_payload else None,
            variants=tuple(RuntimeVariantSpec.from_dict(item) for item in list(data.get("variants") or [])),
            ranking_dataset=DatasetRef.from_dict(data.get("ranking_dataset")),
            calibration_dataset=DatasetRef.from_dict(data.get("calibration_dataset")),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            status=str(data.get("status") or "candidate"),
            notes=str(data.get("notes") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MobileBenchmarkReport:
    """A report produced by the Android application for one package variant."""

    report_id: str
    package_id: str
    variant_id: str
    measured_at: str = field(default_factory=_utc_now_iso)
    device: dict[str, Any] = field(default_factory=dict)
    runtime: str = ""
    delegate: str = ""
    latency: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> tuple[str, str, str, str, str, str, str]:
        device_name = str(self.device.get("name") or self.device.get("device_name") or "").strip()
        return (
            self.report_id,
            self.package_id,
            self.variant_id,
            device_name,
            str(self.runtime or ""),
            str(self.delegate or ""),
            str(self.measured_at or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MOBILE_BENCHMARK_REPORT_SCHEMA,
            "report_id": self.report_id,
            "package_id": self.package_id,
            "variant_id": self.variant_id,
            "measured_at": self.measured_at,
            "device": dict(self.device or {}),
            "runtime": self.runtime,
            "delegate": self.delegate,
            "latency": dict(self.latency or {}),
            "memory": dict(self.memory or {}),
            "quality": dict(self.quality or {}),
            "errors": dict(self.errors or {}),
            "raw": dict(self.raw or {}),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MobileBenchmarkReport":
        payload = dict(data or {})
        device = dict(payload.get("device") or {})
        if not device:
            device = {
                "name": payload.get("device_name", ""),
                "android_version": payload.get("android_version", ""),
            }
        latency = dict(payload.get("latency") or payload.get("latencies") or {})
        memory = dict(payload.get("memory") or {})
        quality = dict(payload.get("quality") or payload.get("metrics") or {})
        errors = dict(payload.get("errors") or payload.get("error_counts") or {})
        package_id = _safe_id(str(payload.get("package_id") or payload.get("model_package_id") or "package"))
        variant_id = _safe_id(str(payload.get("variant_id") or payload.get("variant") or payload.get("runtime") or "variant"))
        report_seed = "|".join(
            [
                package_id,
                variant_id,
                str(device.get("name") or ""),
                str(payload.get("runtime") or ""),
                str(payload.get("delegate") or ""),
                str(payload.get("measured_at") or ""),
            ]
        )
        return cls(
            report_id=_safe_id(str(payload.get("report_id") or report_seed), fallback="report"),
            package_id=package_id,
            variant_id=variant_id,
            measured_at=str(payload.get("measured_at") or _utc_now_iso()),
            device=device,
            runtime=str(payload.get("runtime") or ""),
            delegate=str(payload.get("delegate") or ""),
            latency=latency,
            memory=memory,
            quality=quality,
            errors=errors,
            raw=payload,
        )


@dataclass(frozen=True)
class MobilePackageScore:
    package_id: str
    variant_id: str
    total: float
    quality: float
    latency: float
    memory: float
    reliability: float
    rejected: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_package_id(
    plate_model: ExperimentModelRef,
    character_model: ExperimentModelRef,
    *,
    vehicle_model: ExperimentModelRef | None = None,
    variant_suffix: str = "",
    prefix: str = "PKG",
) -> str:
    parts = [prefix]
    if vehicle_model is not None:
        parts.append(vehicle_model.model_id)
    parts.extend([plate_model.model_id, character_model.model_id, variant_suffix])
    return _safe_id("-".join(part for part in parts if str(part or "").strip()), fallback="PKG")


def default_runtime_variants(image_size: int = 640) -> tuple[RuntimeVariantSpec, ...]:
    return (
        RuntimeVariantSpec(id="tflite-fp32", runtime="tflite", precision="fp32", image_size=image_size),
        RuntimeVariantSpec(id="onnx-fp32", runtime="onnx", precision="fp32", image_size=image_size),
    )


def build_package_candidate(
    plate_model: ExperimentModelRef,
    character_model: ExperimentModelRef,
    *,
    vehicle_model: ExperimentModelRef | None = None,
    variants: tuple[RuntimeVariantSpec, ...] | None = None,
    ranking_dataset: DatasetRef | None = None,
    calibration_dataset: DatasetRef | None = None,
    package_id: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> MobilePackageCandidate:
    safe_variants = variants or default_runtime_variants()
    candidate = MobilePackageCandidate(
        package_id=_safe_id(package_id or build_package_id(plate_model, character_model, vehicle_model=vehicle_model)),
        plate_model=plate_model,
        character_model=character_model,
        vehicle_model=vehicle_model,
        variants=tuple(safe_variants),
        ranking_dataset=ranking_dataset or DatasetRef(),
        calibration_dataset=calibration_dataset or DatasetRef(),
        notes=notes,
        metadata=dict(metadata or {}),
    )
    problems = candidate.validate()
    if problems:
        raise ValueError("; ".join(problems))
    return candidate


def score_mobile_report(
    report: MobileBenchmarkReport,
    *,
    weights: dict[str, float] | None = None,
    targets: dict[str, float] | None = None,
) -> MobilePackageScore:
    safe_weights = dict(DEFAULT_SCORE_WEIGHTS)
    safe_weights.update(dict(weights or {}))
    safe_targets = dict(DEFAULT_SCORE_TARGETS)
    safe_targets.update(dict(targets or {}))

    quality_data = dict(report.quality or {})
    latency_data = dict(report.latency or {})
    memory_data = dict(report.memory or {})
    errors_data = dict(report.errors or {})

    exact_match = _metric01(
        _nested_value(
            quality_data,
            "plate_exact_match",
            "exact_match_rate",
            "plate_accuracy",
            "success_rate",
            "accuracy_plate",
            "end_to_end_accuracy",
        ),
        default=0.0,
    )
    cer = _metric01(_nested_value(quality_data, "cer", "character_error_rate"), default=0.0)
    char_f1 = _metric01(_nested_value(quality_data, "char_f1", "f1", "f1_score"), default=0.0)
    quality = max(exact_match, (1.0 - cer) * 0.65 + char_f1 * 0.35 if cer > 0 or char_f1 > 0 else 0.0)

    p95 = _safe_float(
        _nested_value(
            latency_data,
            "pipeline_ms_p95",
            "latency_pipeline_ms_p95",
            "pipeline.p95_ms",
            "p95_ms",
        ),
        None,
    )
    latency = 0.0
    if p95 and p95 > 0:
        latency = _clamp01(float(safe_targets["pipeline_p95_ms"]) / float(p95))

    ram_peak = _safe_float(
        _nested_value(memory_data, "ram_peak_mb", "peak_ram_mb", "process_peak_mb"),
        None,
    )
    package_size = _safe_float(
        _nested_value(memory_data, "package_size_mb", "model_size_mb", "variant_size_mb"),
        None,
    )
    memory_parts: list[float] = []
    if ram_peak and ram_peak > 0:
        memory_parts.append(_clamp01(float(safe_targets["ram_peak_mb"]) / float(ram_peak)))
    if package_size and package_size > 0:
        memory_parts.append(_clamp01(float(safe_targets["package_size_mb"]) / float(package_size)))
    memory = sum(memory_parts) / len(memory_parts) if memory_parts else 0.0

    crash_count = _safe_int(_nested_value(errors_data, "crash_count", "crashes"))
    measured_runs = max(1, _safe_int(_nested_value(report.raw, "measured_runs", "runs", "samples"), 1))
    crash_rate = _clamp01(crash_count / measured_runs)
    reliability = 1.0 - crash_rate

    reasons: list[str] = []
    if not p95:
        reasons.append("missing pipeline p95 latency")
    if quality <= 0:
        reasons.append("missing end-to-end quality")
    if crash_count > 0:
        reasons.append(f"runtime crashes: {crash_count}")

    total_weight = sum(max(0.0, float(value)) for value in safe_weights.values()) or 1.0
    total = (
        quality * max(0.0, float(safe_weights.get("quality", 0.0)))
        + latency * max(0.0, float(safe_weights.get("latency", 0.0)))
        + memory * max(0.0, float(safe_weights.get("memory", 0.0)))
        + reliability * max(0.0, float(safe_weights.get("reliability", 0.0)))
    ) / total_weight

    rejected = bool(crash_count > 0 or quality <= 0 or not p95)
    return MobilePackageScore(
        package_id=report.package_id,
        variant_id=report.variant_id,
        total=round(total, 4),
        quality=round(quality, 4),
        latency=round(latency, 4),
        memory=round(memory, 4),
        reliability=round(reliability, 4),
        rejected=rejected,
        reasons=tuple(reasons),
        metrics={
            "plate_exact_match": exact_match,
            "cer": cer,
            "char_f1": char_f1,
            "pipeline_p95_ms": p95,
            "ram_peak_mb": ram_peak,
            "package_size_mb": package_size,
        },
    )


class MobilePackageExperimentStore:
    """Persistent storage for package candidates and Android reports."""

    FILE_NAME = "mobile_package_experiments.json"

    def __init__(self, root_dir: Path | None = None):
        default_root = getattr(CONFIG, "DIR_7_RANKINGS_MOBILE_PACKAGES", CONFIG.DIR_7_RANKINGS / "mobile_packages")
        self.root_dir = Path(root_dir) if root_dir else Path(default_root)
        self.file_path = self.root_dir / self.FILE_NAME
        self.candidates: dict[str, MobilePackageCandidate] = {}
        self.reports: list[MobileBenchmarkReport] = []
        self._load()

    def _load(self) -> None:
        self.candidates = {}
        self.reports = []
        if not self.file_path.exists():
            return
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8-sig"))
            self.candidates = {
                candidate.package_id: candidate
                for candidate in (
                    MobilePackageCandidate.from_dict(item)
                    for item in list(data.get("candidates") or [])
                )
            }
            self.reports = [
                MobileBenchmarkReport.from_dict(item)
                for item in list(data.get("reports") or [])
            ]
        except Exception as exc:
            logger.error(f"Could not load mobile package experiments: {exc}")
            self.candidates = {}
            self.reports = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MOBILE_PACKAGE_EXPERIMENT_SCHEMA,
            "updated_at": _utc_now_iso(),
            "candidates": [candidate.to_dict() for candidate in self.candidates.values()],
            "reports": [report.to_dict() for report in self.reports],
            "scores": [score.to_dict() for score in self.score_reports()],
        }

    def save(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.file_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.file_path)

    def add_candidate(self, candidate: MobilePackageCandidate, *, save: bool = True) -> MobilePackageCandidate:
        problems = candidate.validate()
        if problems:
            raise ValueError("; ".join(problems))
        self.candidates[candidate.package_id] = candidate
        if save:
            self.save()
        return candidate

    def add_report(self, report: MobileBenchmarkReport, *, save: bool = True) -> MobileBenchmarkReport:
        identity = report.identity
        self.reports = [existing for existing in self.reports if existing.identity != identity]
        self.reports.append(report)
        if save:
            self.save()
        return report

    def import_mobile_report_file(self, report_path: Path, *, save: bool = True) -> list[MobileBenchmarkReport]:
        if zipfile.is_zipfile(Path(report_path)):
            bundle = read_mobile_report_bundle(Path(report_path))
            imported = [self.add_report(bundle.report, save=False)]
            if save:
                self.save()
            return imported

        data = json.loads(Path(report_path).read_text(encoding="utf-8-sig"))
        if isinstance(data, dict) and isinstance(data.get("reports"), list):
            raw_reports = list(data.get("reports") or [])
        elif isinstance(data, list):
            raw_reports = data
        else:
            raw_reports = [data]

        imported = [self.add_report(MobileBenchmarkReport.from_dict(item), save=False) for item in raw_reports]
        if save:
            self.save()
        return imported

    def score_reports(
        self,
        *,
        weights: dict[str, float] | None = None,
        targets: dict[str, float] | None = None,
    ) -> list[MobilePackageScore]:
        scores = [score_mobile_report(report, weights=weights, targets=targets) for report in self.reports]
        return sorted(scores, key=lambda score: (score.rejected, -score.total, score.package_id, score.variant_id))
