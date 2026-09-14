"""Pre-ingest audit of experimental source pools against registered train/val data.

The service is conservative:
- exact SHA-256 or known source lineage => DEPENDENT,
- perceptual near-duplicate => SUSPECT_DERIVATIVE,
- no hit => NO_DETECTED_DEPENDENCE,
- unreadable candidate => UNKNOWN.

Perceptual similarity is supporting evidence only. It never upgrades a candidate
to formal independence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import cv2
import numpy as np
from PIL import Image, ImageOps

from ..config import CONFIG
from .repository import RegistryRepository


AUDIT_SCHEMA = "alpr.source_pool_independence_audit.v1"
PHASH_CACHE_SCHEMA = "alpr.phash_cache.v1"
PHASH_ALGORITHM = "phash64_dct_v1"

STATUS_DEPENDENT = "DEPENDENT"
STATUS_SUSPECT = "SUSPECT_DERIVATIVE"
STATUS_CLEAN = "NO_DETECTED_DEPENDENCE"
STATUS_UNKNOWN = "UNKNOWN"

PROTECTED_SPLITS = ("train", "val")


@dataclass(frozen=True)
class SourcePoolReferenceMatch:
    dataset_id: str
    split: str
    dataset_relative_path: str
    source_image_id: str
    file_sha256: str
    training_run_ids: tuple[str, ...] = ()
    model_ids: tuple[str, ...] = ()
    reason: str = ""
    phash_distance: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "split": self.split,
            "dataset_relative_path": self.dataset_relative_path,
            "source_image_id": self.source_image_id,
            "file_sha256": self.file_sha256,
            "training_run_ids": list(self.training_run_ids),
            "model_ids": list(self.model_ids),
            "reason": self.reason,
            "phash_distance": self.phash_distance,
        }


@dataclass(frozen=True)
class SourcePoolAuditItem:
    source_path: str
    original_name: str
    sha256: str
    status: str
    source_image_ids: tuple[str, ...] = ()
    phash64: str = ""
    nearest_phash_distance: int | None = None
    matches: tuple[SourcePoolReferenceMatch, ...] = ()
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "original_name": self.original_name,
            "sha256": self.sha256,
            "status": self.status,
            "source_image_ids": list(self.source_image_ids),
            "phash64": self.phash64,
            "nearest_phash_distance": self.nearest_phash_distance,
            "matches": [item.to_dict() for item in self.matches],
            "note": self.note,
        }


@dataclass(frozen=True)
class SourcePoolAuditReport:
    audit_id: str
    target: str
    purpose: str
    track_id: str
    created_at: str
    reference_count: int
    similarity_reference_count: int
    similarity_threshold: int
    items: tuple[SourcePoolAuditItem, ...]
    warnings: tuple[str, ...] = ()
    algorithm: str = PHASH_ALGORITHM

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def dependent_count(self) -> int:
        return sum(1 for item in self.items if item.status == STATUS_DEPENDENT)

    @property
    def suspect_count(self) -> int:
        return sum(1 for item in self.items if item.status == STATUS_SUSPECT)

    @property
    def clean_count(self) -> int:
        return sum(1 for item in self.items if item.status == STATUS_CLEAN)

    @property
    def unknown_count(self) -> int:
        return sum(1 for item in self.items if item.status == STATUS_UNKNOWN)

    @property
    def dependency_fraction(self) -> float:
        return (
            float(self.dependent_count) / float(self.total_count)
            if self.total_count
            else 0.0
        )

    @property
    def similarity_coverage(self) -> float:
        return (
            float(self.similarity_reference_count) / float(self.reference_count)
            if self.reference_count
            else 0.0
        )

    def items_with_status(self, status: str) -> tuple[SourcePoolAuditItem, ...]:
        return tuple(item for item in self.items if item.status == status)

    def to_dict(self, *, decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {
            "schema": AUDIT_SCHEMA,
            "audit_id": self.audit_id,
            "target": self.target,
            "purpose": self.purpose,
            "track_id": self.track_id,
            "created_at": self.created_at,
            "algorithm": self.algorithm,
            "similarity_threshold": self.similarity_threshold,
            "reference_count": self.reference_count,
            "similarity_reference_count": self.similarity_reference_count,
            "similarity_coverage": self.similarity_coverage,
            "total_count": self.total_count,
            "dependent_count": self.dependent_count,
            "suspect_count": self.suspect_count,
            "clean_count": self.clean_count,
            "unknown_count": self.unknown_count,
            "dependency_fraction": self.dependency_fraction,
            "warnings": list(self.warnings),
            "items": [item.to_dict() for item in self.items],
            "decision": dict(decision or {}),
        }


class SourcePoolIndependenceAuditService:
    """Audit candidate images before they become evaluation-track members."""

    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        *,
        repository: RegistryRepository | None = None,
        suspect_hamming_threshold: int = 8,
    ) -> None:
        self.workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
        self.repository = repository or RegistryRepository.for_workspace(
            self.workspace
        )
        self.repository.initialize()
        self.suspect_hamming_threshold = max(
            0,
            min(64, int(suspect_hamming_threshold)),
        )
        self.cache_path = (
            self.workspace
            / "_registry"
            / "source_pool_phash_cache.json"
        )
        self._phash_cache = self._load_phash_cache()
        self._cache_dirty = False

    def audit(
        self,
        candidate_paths: Iterable[Path | str],
        *,
        target: str,
        purpose: str = "",
        track_id: str = "",
    ) -> SourcePoolAuditReport:
        normalized_target = CONFIG.normalize_task_target(target)
        created_at = datetime.now(timezone.utc).isoformat()
        audit_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + "-"
            + hashlib.sha256(created_at.encode("utf-8")).hexdigest()[:8]
        )

        candidates = self._normalize_candidates(candidate_paths)
        references = [
            dict(row)
            for row in self.repository.list_training_reference_members(
                normalized_target,
                splits=PROTECTED_SPLITS,
            )
        ]

        exact_sha: dict[str, list[dict[str, Any]]] = {}
        by_source: dict[str, list[dict[str, Any]]] = {}
        for row in references:
            file_sha = str(row.get("file_sha256") or "").strip().lower()
            canonical_sha = str(row.get("canonical_sha256") or "").strip().lower()
            source_id = str(row.get("source_image_id") or "").strip()
            if file_sha:
                exact_sha.setdefault(file_sha, []).append(row)
            if canonical_sha:
                exact_sha.setdefault(canonical_sha, []).append(row)
            if source_id:
                by_source.setdefault(source_id, []).append(row)

        prepared_candidates: list[dict[str, Any]] = []
        need_similarity = False
        for path in candidates:
            sha = self._sha256(path)
            if not sha:
                prepared_candidates.append(
                    {
                        "path": path,
                        "sha": "",
                        "source_ids": (),
                        "exact_rows": (),
                        "status": STATUS_UNKNOWN,
                        "note": "Nie udało się policzyć SHA-256 pliku.",
                    }
                )
                continue

            source_ids = tuple(
                self.repository.list_source_image_ids_by_sha256(sha)
            )
            matched_rows: list[dict[str, Any]] = []
            reasons: set[str] = set()

            if sha in exact_sha:
                matched_rows.extend(exact_sha[sha])
                reasons.add("artifact_sha256")

            for source_id in source_ids:
                rows = by_source.get(source_id, ())
                if rows:
                    matched_rows.extend(rows)
                    reasons.add("source_image_id")

            if matched_rows:
                prepared_candidates.append(
                    {
                        "path": path,
                        "sha": sha,
                        "source_ids": source_ids,
                        "exact_rows": tuple(self._dedupe_rows(matched_rows)),
                        "status": STATUS_DEPENDENT,
                        "reason": "+".join(sorted(reasons)),
                        "note": "",
                    }
                )
            else:
                prepared_candidates.append(
                    {
                        "path": path,
                        "sha": sha,
                        "source_ids": source_ids,
                        "exact_rows": (),
                        "status": "",
                        "reason": "",
                        "note": "",
                    }
                )
                need_similarity = True

        phash_references: list[tuple[dict[str, Any], str]] = []
        similarity_reference_count = 0
        warnings: list[str] = []

        if need_similarity and references:
            for row in references:
                phash = self._reference_phash(row)
                if not phash:
                    continue
                similarity_reference_count += 1
                phash_references.append((row, phash))

            missing = len(references) - similarity_reference_count
            if missing:
                warnings.append(
                    "Perceptual-hash nie objął wszystkich zarejestrowanych "
                    f"train/val: {similarity_reference_count}/{len(references)}; "
                    f"brakuje {missing} fizycznych obrazów lub cache."
                )
        elif not references:
            warnings.append(
                "Brak zarejestrowanych obrazów train/val dla tego targetu; "
                "nie da się wykonać audytu zależności względem historii treningu."
            )

        items: list[SourcePoolAuditItem] = []
        for prepared in prepared_candidates:
            path = Path(prepared["path"])
            sha = str(prepared.get("sha") or "")
            source_ids = tuple(prepared.get("source_ids") or ())

            if prepared["status"] == STATUS_UNKNOWN:
                items.append(
                    SourcePoolAuditItem(
                        source_path=str(path),
                        original_name=path.name,
                        sha256=sha,
                        status=STATUS_UNKNOWN,
                        source_image_ids=source_ids,
                        note=str(prepared.get("note") or ""),
                    )
                )
                continue

            if prepared["status"] == STATUS_DEPENDENT:
                reason = str(prepared.get("reason") or "registered_train_val")
                matches = tuple(
                    self._row_to_match(row, reason=reason)
                    for row in prepared["exact_rows"][:12]
                )
                items.append(
                    SourcePoolAuditItem(
                        source_path=str(path),
                        original_name=path.name,
                        sha256=sha,
                        status=STATUS_DEPENDENT,
                        source_image_ids=source_ids,
                        matches=matches,
                        note=(
                            "Plik ma twardy dowód zależności od "
                            "zarejestrowanego train/val."
                        ),
                    )
                )
                continue

            candidate_phash = self._cached_or_compute_phash(path, sha)
            if not candidate_phash:
                items.append(
                    SourcePoolAuditItem(
                        source_path=str(path),
                        original_name=path.name,
                        sha256=sha,
                        status=STATUS_UNKNOWN,
                        source_image_ids=source_ids,
                        note=(
                            "Nie udało się obliczyć perceptual-hash kandydata."
                        ),
                    )
                )
                continue

            nearest_distance: int | None = None
            nearest_rows: list[dict[str, Any]] = []
            if phash_references:
                for row, ref_phash in phash_references:
                    distance = self._hamming_distance(
                        candidate_phash,
                        ref_phash,
                    )
                    if nearest_distance is None or distance < nearest_distance:
                        nearest_distance = distance
                        nearest_rows = [row]
                    elif distance == nearest_distance:
                        nearest_rows.append(row)

            if (
                nearest_distance is not None
                and nearest_distance <= self.suspect_hamming_threshold
            ):
                matches = tuple(
                    self._row_to_match(
                        row,
                        reason="perceptual_hash",
                        phash_distance=nearest_distance,
                    )
                    for row in nearest_rows[:12]
                )
                items.append(
                    SourcePoolAuditItem(
                        source_path=str(path),
                        original_name=path.name,
                        sha256=sha,
                        status=STATUS_SUSPECT,
                        source_image_ids=source_ids,
                        phash64=candidate_phash,
                        nearest_phash_distance=nearest_distance,
                        matches=matches,
                        note=(
                            "Brak twardego overlapu, ale obraz jest bardzo "
                            "podobny perceptualnie do train/val."
                        ),
                    )
                )
            else:
                note = (
                    "Brak twardego overlapu i brak bliskiego perceptualnego "
                    "trafienia w dostępnej historii train/val."
                )
                if references and similarity_reference_count < len(references):
                    note += " Kontrola podobieństwa ma niepełne pokrycie."
                items.append(
                    SourcePoolAuditItem(
                        source_path=str(path),
                        original_name=path.name,
                        sha256=sha,
                        status=STATUS_CLEAN,
                        source_image_ids=source_ids,
                        phash64=candidate_phash,
                        nearest_phash_distance=nearest_distance,
                        note=note,
                    )
                )

        self._save_phash_cache_if_needed()

        return SourcePoolAuditReport(
            audit_id=audit_id,
            target=normalized_target,
            purpose=str(purpose or "").strip().lower(),
            track_id=str(track_id or "").strip(),
            created_at=created_at,
            reference_count=len(references),
            similarity_reference_count=similarity_reference_count,
            similarity_threshold=self.suspect_hamming_threshold,
            items=tuple(items),
            warnings=tuple(warnings),
        )

    def save_report(
        self,
        report: SourcePoolAuditReport,
        output_dir: Path | str,
        *,
        decision: Mapping[str, Any] | None = None,
    ) -> Path:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        destination = out_dir / f"source_pool_audit_{report.audit_id}.json"
        tmp = destination.with_suffix(destination.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                report.to_dict(decision=decision),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, destination)
        return destination

    def _normalize_candidates(
        self,
        values: Iterable[Path | str],
    ) -> list[Path]:
        result: list[Path] = []
        seen: set[str] = set()
        for value in values:
            path = Path(value)
            try:
                key = str(path.resolve()).casefold()
            except Exception:
                key = str(path).casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(path)
        return result

    def _reference_phash(self, row: Mapping[str, Any]) -> str:
        file_sha = str(row.get("file_sha256") or "").strip().lower()
        canonical_sha = str(row.get("canonical_sha256") or "").strip().lower()
        cache_key = file_sha or canonical_sha
        if cache_key:
            cached = str(self._phash_cache.get(cache_key) or "")
            if cached:
                return cached

        path = self._resolve_reference_path(row)
        if path is None:
            return ""

        actual_sha = self._sha256(path)
        cache_key = cache_key or actual_sha
        return self._cached_or_compute_phash(path, cache_key)

    def _resolve_reference_path(
        self,
        row: Mapping[str, Any],
    ) -> Path | None:
        direct_candidates = []

        artifact_relative = str(
            row.get("artifact_relative_path") or ""
        ).strip()
        artifact_external = str(
            row.get("artifact_external_path") or ""
        ).strip()
        if artifact_relative:
            direct_candidates.append(self.workspace / artifact_relative)
        if artifact_external:
            direct_candidates.append(Path(artifact_external))

        member_relative = str(
            row.get("dataset_relative_path") or ""
        ).strip()
        roots: list[Path] = []

        location_relative = str(
            row.get("dataset_location_relative_path") or ""
        ).strip()
        location_external = str(
            row.get("dataset_location_external_path") or ""
        ).strip()
        dataset_relative = str(
            row.get("dataset_root_relative_path") or ""
        ).strip()

        if location_relative:
            roots.append(self.workspace / location_relative)
        if location_external:
            roots.append(Path(location_external))
        if dataset_relative:
            roots.append(self.workspace / dataset_relative)

        for candidate in direct_candidates:
            try:
                if candidate.is_file():
                    return candidate
            except Exception:
                pass

        if member_relative:
            for root in roots:
                candidate = root / member_relative
                try:
                    if candidate.is_file():
                        return candidate
                except Exception:
                    pass
        return None

    def _cached_or_compute_phash(
        self,
        path: Path,
        sha256: str,
    ) -> str:
        key = str(sha256 or "").strip().lower()
        if key:
            cached = str(self._phash_cache.get(key) or "")
            if cached:
                return cached
        try:
            value = self._phash64(path)
        except Exception:
            return ""
        if key:
            self._phash_cache[key] = value
            self._cache_dirty = True
        return value

    @staticmethod
    def _phash64(path: Path | str) -> str:
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw).convert("L")
            resampling = getattr(Image, "Resampling", Image)
            contained = ImageOps.contain(
                image,
                (32, 32),
                method=resampling.LANCZOS,
            )

        canvas = Image.new("L", (32, 32), color=128)
        x = (32 - contained.width) // 2
        y = (32 - contained.height) // 2
        canvas.paste(contained, (x, y))

        matrix = np.asarray(canvas, dtype=np.float32)
        transformed = cv2.dct(matrix)
        low = transformed[:8, :8].flatten()
        median = float(np.median(low[1:]))

        value = 0
        for bit in low > median:
            value = (value << 1) | int(bool(bit))
        return f"{value:016x}"

    @staticmethod
    def _hamming_distance(left: str, right: str) -> int:
        return (
            int(str(left), 16)
            ^ int(str(right), 16)
        ).bit_count()

    @staticmethod
    def _sha256(path: Path | str) -> str:
        digest = hashlib.sha256()
        try:
            with Path(path).open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except Exception:
            return ""
        return digest.hexdigest()

    def _row_to_match(
        self,
        row: Mapping[str, Any],
        *,
        reason: str,
        phash_distance: int | None = None,
    ) -> SourcePoolReferenceMatch:
        return SourcePoolReferenceMatch(
            dataset_id=str(row.get("dataset_id") or ""),
            split=str(row.get("split") or ""),
            dataset_relative_path=str(
                row.get("dataset_relative_path") or ""
            ),
            source_image_id=str(row.get("source_image_id") or ""),
            file_sha256=str(row.get("file_sha256") or "").lower(),
            training_run_ids=self._csv_tuple(
                row.get("training_run_ids")
            ),
            model_ids=self._csv_tuple(
                row.get("model_ids")
            ),
            reason=reason,
            phash_distance=phash_distance,
        )

    @staticmethod
    def _csv_tuple(value: Any) -> tuple[str, ...]:
        return tuple(
            item.strip()
            for item in str(value or "").split(",")
            if item.strip()
        )

    @staticmethod
    def _dedupe_rows(
        rows: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in rows:
            data = dict(row)
            key = (
                str(data.get("dataset_id") or ""),
                str(data.get("split") or ""),
                str(data.get("artifact_id") or ""),
                str(data.get("source_image_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(data)
        return result

    def _load_phash_cache(self) -> dict[str, str]:
        if not self.cache_path.is_file():
            return {}
        try:
            payload = json.loads(
                self.cache_path.read_text(encoding="utf-8")
            )
        except Exception:
            return {}
        if not isinstance(payload, Mapping):
            return {}
        if str(payload.get("schema") or "") != PHASH_CACHE_SCHEMA:
            return {}
        if str(payload.get("algorithm") or "") != PHASH_ALGORITHM:
            return {}
        values = payload.get("values")
        if not isinstance(values, Mapping):
            return {}
        return {
            str(key).strip().lower(): str(value).strip().lower()
            for key, value in values.items()
            if str(key).strip() and str(value).strip()
        }

    def _save_phash_cache_if_needed(self) -> None:
        if not self._cache_dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(
            self.cache_path.suffix + ".tmp"
        )
        tmp.write_text(
            json.dumps(
                {
                    "schema": PHASH_CACHE_SCHEMA,
                    "algorithm": PHASH_ALGORITHM,
                    "values": self._phash_cache,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.cache_path)
        self._cache_dirty = False


def format_source_pool_audit_summary(
    report: SourcePoolAuditReport,
    *,
    max_examples: int = 8,
) -> str:
    total = report.total_count
    dep_pct = 100.0 * report.dependent_count / total if total else 0.0
    suspect_pct = 100.0 * report.suspect_count / total if total else 0.0
    clean_pct = 100.0 * report.clean_count / total if total else 0.0
    unknown_pct = 100.0 * report.unknown_count / total if total else 0.0
    coverage_pct = 100.0 * report.similarity_coverage

    lines = [
        f"Wybrano: {total}",
        f"ZALEŻNE: {report.dependent_count} ({dep_pct:.1f}%) — zawsze odrzucane",
        f"PODEJRZANE POCHODNE: {report.suspect_count} ({suspect_pct:.1f}%)",
        f"BRAK WYKRYTEJ ZALEŻNOŚCI: {report.clean_count} ({clean_pct:.1f}%)",
        f"NIE MOŻNA ROZSTRZYGNĄĆ: {report.unknown_count} ({unknown_pct:.1f}%) — odrzucane",
        "",
        (
            "Historia train/val: "
            f"{report.reference_count} wpisów; "
            "pokrycie perceptual-hash: "
            f"{report.similarity_reference_count}/{report.reference_count} "
            f"({coverage_pct:.1f}%)."
        ),
    ]

    examples = [
        item
        for item in report.items
        if item.status in {STATUS_DEPENDENT, STATUS_SUSPECT}
    ][: max(0, int(max_examples))]

    if examples:
        lines.extend(["", "Przykłady trafień:"])
        for item in examples:
            match = item.matches[0] if item.matches else None
            suffix = ""
            if match is not None:
                suffix = (
                    f" → {match.dataset_id}/{match.split}"
                    f" [{match.reason}]"
                )
                if match.phash_distance is not None:
                    suffix += f" d={match.phash_distance}"
            lines.append(
                f"- {item.original_name}: {item.status}{suffix}"
            )

    if report.warnings:
        lines.extend(["", "Uwagi:"])
        lines.extend(f"- {warning}" for warning in report.warnings)

    return "\n".join(lines)
