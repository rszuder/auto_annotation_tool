"""Model-relative audit of candidate evaluation images.

A common ranking track is audited only against the selected participant models.
The service also keeps a persistent SHA/pHash cache to make repeated checks of
large folders fast.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid
from typing import Any, Callable, Iterable, Mapping, Sequence

import cv2
import numpy as np

from ..config import CONFIG
from .repository import RegistryRepository
from .track_service import EvaluationTrackError, STATUS_DRAFT

STATUS_DEPENDENT = "DEPENDENT"
STATUS_SUSPECT = "SUSPECT_DERIVATIVE"
STATUS_CLEAN = "NO_DETECTED_DEPENDENCE"
STATUS_UNKNOWN = "UNKNOWN"

PARTICIPANT_SCHEMA = "alpr.evaluation_track_participants.v1"
AUDIT_SCHEMA = "alpr.participant_pool_audit.v1"
CACHE_SCHEMA = "alpr.participant_pool_file_cache.v1"


@dataclass(frozen=True)
class ParticipantModel:
    model_id: str
    sha256: str
    run_id: str
    target: str
    family: str
    scale: str
    provenance_status: str


@dataclass(frozen=True)
class ModelCandidateVerdict:
    model_id: str
    model_sha256: str
    status: str
    reason: str = ""
    training_run_id: str = ""
    training_dataset_id: str = ""
    training_split: str = ""
    reference_path: str = ""
    phash_distance: int | None = None
    phash_reference_coverage: float = 0.0
    reference_image_path: str = ""


@dataclass(frozen=True)
class CandidateVerdict:
    path: str
    filename: str
    sha256: str
    phash64: str
    common_status: str
    per_model: tuple[ModelCandidateVerdict, ...]


@dataclass(frozen=True)
class ParticipantPoolAuditReport:
    schema: str
    track_id: str
    participant_fingerprint: str
    participants: tuple[ParticipantModel, ...]
    candidates: tuple[CandidateVerdict, ...]
    dependent_count: int
    suspect_count: int
    clean_count: int
    unknown_count: int
    audited_at: str
    cache_hits_sha: int = 0
    cache_hits_phash: int = 0
    cache_misses_sha: int = 0
    cache_misses_phash: int = 0
    reference_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "track_id": self.track_id,
            "participant_fingerprint": self.participant_fingerprint,
            "participants": [asdict(item) for item in self.participants],
            "candidates": [
                {
                    "path": item.path,
                    "filename": item.filename,
                    "sha256": item.sha256,
                    "phash64": item.phash64,
                    "common_status": item.common_status,
                    "per_model": [asdict(value) for value in item.per_model],
                }
                for item in self.candidates
            ],
            "dependent_count": self.dependent_count,
            "suspect_count": self.suspect_count,
            "clean_count": self.clean_count,
            "unknown_count": self.unknown_count,
            "audited_at": self.audited_at,
            "cache_hits_sha": self.cache_hits_sha,
            "cache_hits_phash": self.cache_hits_phash,
            "cache_misses_sha": self.cache_misses_sha,
            "cache_misses_phash": self.cache_misses_phash,
            "reference_rows": self.reference_rows,
        }


def common_status(statuses: Iterable[str]) -> str:
    values = tuple(str(item or "").strip().upper() for item in statuses)
    if any(value == STATUS_DEPENDENT for value in values):
        return STATUS_DEPENDENT
    if any(value == STATUS_SUSPECT for value in values):
        return STATUS_SUSPECT
    if not values or any(value != STATUS_CLEAN for value in values):
        return STATUS_UNKNOWN
    return STATUS_CLEAN


def participant_fingerprint(participants: Sequence[ParticipantModel]) -> str:
    payload = "\n".join(
        f"{item.model_id}|{item.sha256}|{item.run_id}|{item.provenance_status}"
        for item in sorted(participants, key=lambda row: row.model_id)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().lower()


class _PersistentFingerprintCache:
    def __init__(self, workspace: Path) -> None:
        self.path = workspace / "_registry" / "participant_pool_file_cache.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": CACHE_SCHEMA, "files": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            files = value.get("files") if isinstance(value, Mapping) else {}
            return {
                "schema": CACHE_SCHEMA,
                "files": dict(files) if isinstance(files, Mapping) else {},
            }
        except Exception:
            return {"schema": CACHE_SCHEMA, "files": {}}

    @staticmethod
    def _key(path: Path) -> str:
        try:
            return str(path.resolve()).casefold()
        except Exception:
            return str(path.absolute()).casefold()

    def get(self, path: Path) -> dict[str, Any] | None:
        try:
            stat = path.stat()
        except Exception:
            return None
        with self._lock:
            row = self._data["files"].get(self._key(path))
            if not isinstance(row, Mapping):
                return None
            if (
                int(row.get("size") or -1) != int(stat.st_size)
                or int(row.get("mtime_ns") or -1) != int(stat.st_mtime_ns)
                or int(row.get("ctime_ns") or -1) != int(stat.st_ctime_ns)
            ):
                return None
            return dict(row)

    def put(
        self,
        path: Path,
        *,
        sha256: str | None = None,
        phash64: str | None = None,
    ) -> None:
        stat = path.stat()
        key = self._key(path)
        with self._lock:
            old = self._data["files"].get(key)
            unchanged = isinstance(old, Mapping) and (
                int(old.get("size") or -1) == stat.st_size
                and int(old.get("mtime_ns") or -1) == stat.st_mtime_ns
                and int(old.get("ctime_ns") or -1) == stat.st_ctime_ns
            )
            row = dict(old) if unchanged else {}
            row.update(
                {
                    "path": str(path),
                    "size": int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns),
                    "ctime_ns": int(stat.st_ctime_ns),
                }
            )
            if sha256:
                row["sha256"] = str(sha256).lower()
            if phash64:
                row["phash64"] = str(phash64).lower()
            self._data["files"][key] = row

    def save(self) -> None:
        temp = self.path.with_suffix(".json.tmp")
        with self._lock:
            payload = json.dumps(
                self._data,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        temp.write_text(payload + "\n", encoding="utf-8")
        temp.replace(self.path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _phash64_file(path: Path) -> str:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Nie można odczytać obrazu do pHash: {path}")
    image = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(image))
    values = dct[:8, :8].flatten()
    median = float(np.median(values[1:])) if len(values) > 1 else float(values[0])
    number = 0
    for bit in values > median:
        number = (number << 1) | int(bool(bit))
    return f"{number:016x}"


class ParticipantPoolAuditService:
    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        *,
        repository: RegistryRepository | None = None,
    ) -> None:
        self.workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
        self.repository = repository or RegistryRepository.for_workspace(self.workspace)
        self.repository.initialize()
        self.cache = _PersistentFingerprintCache(self.workspace)

    def _track_row(self, track_id: str) -> Mapping[str, Any]:
        row = self.repository.get_evaluation_track(str(track_id or "").strip())
        if row is None:
            raise EvaluationTrackError(f"Nie znaleziono toru: {track_id}")
        return row

    def _track_root(self, track_id: str) -> Path:
        row = self._track_row(track_id)
        rel = str(row["relative_path"] or "").strip()
        if not rel:
            raise EvaluationTrackError("Tor nie ma relative_path.")
        return self.workspace / rel

    def participants_path(self, track_id: str) -> Path:
        return self._track_root(track_id) / "participants.json"

    def audit_state_path(self, track_id: str) -> Path:
        return self._track_root(track_id) / "participant_pool_audit_state.json"

    def list_eligible_models(self, target: str) -> list[ParticipantModel]:
        return [
            ParticipantModel(
                model_id=str(row["model_id"] or ""),
                sha256=str(row["sha256"] or "").lower(),
                run_id=str(row["run_id"] or ""),
                target=str(row["target"] or ""),
                family=str(row["yolo_family"] or ""),
                scale=str(row["yolo_scale"] or "unknown"),
                provenance_status=str(row["provenance_status"] or ""),
            )
            for row in self.repository.list_models_for_target(
                str(target or "").strip().lower()
            )
        ]

    def load_participants(self, track_id: str) -> tuple[ParticipantModel, ...]:
        path = self.participants_path(track_id)
        track = self._track_row(track_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if str(track["status"]) in {"SEALED", "RETIRED"}:
                manifest = json.loads((self._track_root(track_id) / "track_manifest.json").read_text(encoding="utf-8"))
                contract = manifest.get("experiment_contract")
                if isinstance(contract, Mapping):
                    payload = contract
            rows = payload.get("participants") if isinstance(payload, Mapping) else []
        except Exception:
            return ()
        result = []
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            model_id = str(row.get("model_id") or "")
            if not model_id:
                continue
            result.append(
                ParticipantModel(
                    model_id=model_id,
                    sha256=str(row.get("sha256") or "").lower(),
                    run_id=str(row.get("run_id") or ""),
                    target=str(row.get("target") or ""),
                    family=str(row.get("family") or ""),
                    scale=str(row.get("scale") or "unknown"),
                    provenance_status=str(row.get("provenance_status") or ""),
                )
            )
        return tuple(result)

    def _assert_registered_participants(self, track_id, participants):
        track = self._track_row(track_id)
        available = {
            item.model_id: item
            for item in self.list_eligible_models(str(track["target"] or ""))
        }
        current = [available[item.model_id] for item in participants
                   if item.model_id in available]
        if participant_fingerprint(current) != participant_fingerprint(participants):
            raise EvaluationTrackError(
                "Historia lub checkpoint uczestnika zmieniły się w rejestrze. "
                "Wybierz ponownie modele uczestniczące i ponów audyt."
            )

    def save_participants(
        self,
        track_id: str,
        model_ids: Sequence[str],
    ) -> tuple[ParticipantModel, ...]:
        track = self._track_row(track_id)
        if str(track["status"] or "").upper() != STATUS_DRAFT:
            raise EvaluationTrackError(
                "Uczestników można zmieniać wyłącznie dla toru DRAFT."
            )
        available = {
            item.model_id: item
            for item in self.list_eligible_models(str(track["target"] or ""))
        }
        selected = []
        for model_id in dict.fromkeys(str(value or "").strip() for value in model_ids):
            if model_id:
                item = available.get(model_id)
                if item is None:
                    raise EvaluationTrackError(
                        f"Model {model_id} nie pasuje do targetu toru."
                    )
                selected.append(item)
        if not selected:
            raise EvaluationTrackError("Wybierz co najmniej jeden model uczestniczący.")

        payload = {
            "schema": PARTICIPANT_SCHEMA,
            "track_id": str(track_id),
            "participant_fingerprint": participant_fingerprint(selected),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "participants": [asdict(item) for item in selected],
        }
        path = self.participants_path(track_id)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
        self.invalidate_track_audit(track_id, reason="participants_changed")
        return tuple(selected)

    def invalidate_track_audit(self, track_id: str, *, reason: str) -> None:
        state = self._read_track_audit_state(track_id)
        state.update(
            schema=AUDIT_SCHEMA, track_id=str(track_id), status="STALE",
            reason=str(reason or ""), invalidated_at=datetime.now(timezone.utc).isoformat(),
        )
        self.repository.save_evaluation_track_audit_state(track_id, state)


    def _read_track_audit_state(self, track_id: str) -> dict[str, Any]:
        state = self.repository.get_evaluation_track_audit_state(track_id)
        if state is not None:
            return state
        # One-way compatibility import. Once present, SQLite is authoritative.
        path = self.audit_state_path(track_id)
        if not path.exists():
            return {}
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError):
            state = {}
        state.update(track_id=str(track_id), legacy_imported=True)
        if state.get("status") not in {"CURRENT", "STALE"}:
            state.update(status="STALE", reason="legacy_audit_unreadable")
        self.repository.save_evaluation_track_audit_state(track_id, state)
        return state

    def _assert_audit_state_matches(self, track_id, state):
        if state.get("status") != "CURRENT":
            raise EvaluationTrackError("Audyt puli jest nieaktualny.")
        participants = self.load_participants(track_id)
        if not participants:
            raise EvaluationTrackError("Tor nie ma wybranych modeli uczestniczących.")
        self._assert_registered_participants(track_id, participants)
        if state.get("participant_fingerprint") != participant_fingerprint(participants):
            raise EvaluationTrackError("Zestaw modeli zmienił się po audycie puli.")
        current = {
            str(row["sha256"] or "").lower()
            for row in self.repository.list_evaluation_track_members(track_id)
        }
        if current != set(state.get("audited_member_sha256") or []):
            raise EvaluationTrackError("Skład obrazów zmienił się po audycie puli.")

    def get_track_audit_state(self, track_id: str) -> dict[str, Any]:
        state = self._read_track_audit_state(track_id)
        if state.get("status") == "CURRENT":
            try:
                self._assert_audit_state_matches(track_id, state)
            except EvaluationTrackError as exc:
                self.invalidate_track_audit(track_id, reason=str(exc))
                state = self._read_track_audit_state(track_id)
        result = dict(state)
        result.setdefault("status", "MISSING")
        result["current_member_count"] = len(self.repository.list_evaluation_track_members(track_id))
        result["current_participant_count"] = len(self.load_participants(track_id))
        return result

    def validate_resolution_target(self, track_id, resolution, expected_member_shas) -> None:
        resolution.validate()
        report = resolution.report
        participants = self.load_participants(track_id)
        self._assert_registered_participants(track_id, participants)
        if (report.track_id != track_id or not participants
                or report.participant_fingerprint != participant_fingerprint(participants)):
            raise EvaluationTrackError("Uczestnicy zmienili się podczas audytu. Uruchom go ponownie.")
        current = {
            str(row["sha256"] or "").lower()
            for row in self.repository.list_evaluation_track_members(track_id)
        }
        if current != set(expected_member_shas):
            raise EvaluationTrackError("Skład toru zmienił się podczas audytu. Uruchom go ponownie.")

    def record_resolution(self, track_id, resolution, *, mode, previous_state=None) -> dict:
        from .audit_resolution import audit_path_key
        resolution.validate()
        if mode not in {"ingest", "pool"}:
            raise ValueError("Nieprawidłowy tryb audytu.")
        report = resolution.report
        participants = self.load_participants(track_id)
        self._assert_registered_participants(track_id, participants)
        if (report.track_id != track_id or not participants
                or report.participant_fingerprint != participant_fingerprint(participants)):
            raise EvaluationTrackError("Raport nie dotyczy aktualnych uczestników toru.")

        members = self.repository.list_evaluation_track_members(track_id)
        current = {str(row["sha256"]).lower() for row in members}
        by_path = {audit_path_key(item.path): item for item in report.candidates}
        accepted = {by_path[audit_path_key(path)].sha256.lower()
                    for path in resolution.accepted_paths}
        rejected = {by_path[audit_path_key(path)].sha256.lower()
                    for path in resolution.rejected_paths}
        if not accepted.issubset(current) or rejected & current:
            raise EvaluationTrackError("Skład zapisanej puli nie odpowiada decyzjom audytu.")

        previous = previous_state or {}
        prior_shas, prior_manual = set(), set()
        if (mode == "ingest" and previous.get("status") == "CURRENT"
                and previous.get("participant_fingerprint") == report.participant_fingerprint):
            prior_shas = set(previous.get("audited_member_sha256") or [])
            prior_manual = set(previous.get("accepted_suspect_sha256") or [])
        covered = accepted | prior_shas
        ready = bool(current) and current == covered
        manual = (prior_manual | {
            by_path[audit_path_key(path)].sha256.lower()
            for path in resolution.accepted_suspects
        }) & current

        # Verified batch copies reuse their source fingerprints on subsequent audits.
        by_sha = {item.sha256.lower(): item for item in report.candidates}
        root = self._track_root(track_id)
        for member in members:
            sha = str(member["sha256"]).lower()
            if sha in accepted:
                item = by_sha[sha]
                path = root / str(member["track_relative_path"])
                if path.is_file():
                    self.cache.put(path, sha256=sha, phash64=item.phash64 or None)
        self.cache.save()

        now = datetime.now(timezone.utc).isoformat()
        audit_id = "AUDIT-" + uuid.uuid4().hex
        member_fp = hashlib.sha256("\n".join(sorted(current)).encode()).hexdigest()
        state = {
            "schema": AUDIT_SCHEMA, "track_id": track_id, "audit_id": audit_id,
            "status": "CURRENT" if ready else "STALE",
            "reason": "" if ready else "previous_pool_requires_audit" if current else "empty_pool",
            "participant_fingerprint": report.participant_fingerprint,
            "member_fingerprint": member_fp,
            "audited_member_sha256": sorted(covered),
            "accepted_suspect_sha256": sorted(manual),
            "audited_at": report.audited_at, "recorded_at": now,
            "participant_count": len(participants), "member_count": len(current),
            "dependent_count": 0, "unknown_count": 0,
            "manual_verified_count": len(manual),
            "resolution_counts": {
                "accepted_clean": len(resolution.accepted_clean),
                "accepted_suspects": len(resolution.accepted_suspects),
                "rejected_dependent": len(resolution.rejected_dependent),
                "rejected_unknown": len(resolution.rejected_unknown),
                "rejected_suspects": len(resolution.rejected_suspects),
            },
        }
        # A rejected-only preflight does not change the audit of the existing pool.
        state_to_write = None if mode == "ingest" and not accepted else state
        self.repository.record_evaluation_track_audit(
            {
                "audit_id": audit_id, "track_id": track_id, "mode": mode,
                "participant_fingerprint": report.participant_fingerprint,
                "member_fingerprint": member_fp, "audited_at": report.audited_at,
                "applied_at": now, "report": report.to_dict(),
            },
            resolution.decision_rows(), state=state_to_write, expected_member_shas=current,
        )
        return state if state_to_write is not None else self.get_track_audit_state(track_id)

    @staticmethod
    def _progress(callback, stage: str, current: int, total: int) -> None:
        if callback is not None:
            try:
                callback(stage, int(current), int(total))
            except Exception:
                pass

    def _ensure_sha(self, paths, progress=None):
        result, missing, hits = {}, [], 0
        for path in paths:
            row = self.cache.get(path)
            value = str((row or {}).get("sha256") or "").lower()
            if value:
                result[path] = value
                hits += 1
            else:
                missing.append(path)
        done, total = hits, len(paths)
        self._progress(progress, "SHA-256", done, total)
        with ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 2))) as pool:
            jobs = {pool.submit(_sha256_file, path): path for path in missing}
            for future in as_completed(jobs):
                path = jobs[future]
                value = future.result()
                result[path] = value
                self.cache.put(path, sha256=value)
                done += 1
                if done == total or done % 25 == 0:
                    self._progress(progress, "SHA-256", done, total)
        return result, hits, len(missing)

    def _ensure_phash(self, paths, progress=None, stage="pHash"):
        unique = list(dict.fromkeys(path for path in paths if path.exists()))
        result, missing, hits = {}, [], 0
        for path in unique:
            row = self.cache.get(path)
            value = str((row or {}).get("phash64") or "").lower()
            if value:
                result[path] = value
                hits += 1
            else:
                missing.append(path)
        done, total = hits, len(unique)
        self._progress(progress, stage, done, total)
        with ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 2))) as pool:
            jobs = {pool.submit(_phash64_file, path): path for path in missing}
            for future in as_completed(jobs):
                path = jobs[future]
                try:
                    value = future.result()
                except Exception:
                    value = ""
                if value:
                    result[path] = value
                    self.cache.put(path, phash64=value)
                done += 1
                if done == total or done % 25 == 0:
                    self._progress(progress, stage, done, total)
        return result, hits, len(missing)

    def fingerprint_paths(self, paths, *, progress=None) -> dict[Path, str]:
        normalized = [
            Path(value)
            for value in paths
            if Path(value).exists() and Path(value).is_file()
        ]
        result, _hits, _misses = self._ensure_sha(normalized, progress=progress)
        self.cache.save()
        return result

    def _resolve_reference_path(self, row: Mapping[str, Any]) -> Path | None:
        candidates = []
        external = str(row.get("artifact_external_path") or "").strip()
        if external:
            candidates.append(Path(external))
        artifact_rel = str(row.get("artifact_relative_path") or "").strip()
        if artifact_rel:
            p = Path(artifact_rel)
            candidates.append(p if p.is_absolute() else self.workspace / p)
        dataset_rel = str(row.get("dataset_relative_path") or "").strip()
        member_rel = str(row.get("member_relative_path") or "").strip()
        if dataset_rel and member_rel:
            root = Path(dataset_rel)
            if not root.is_absolute():
                root = self.workspace / root
            candidates.append(root / member_rel)
        for path in candidates:
            if path.exists() and path.is_file():
                return path
        return None

    def audit_paths(
        self,
        track_id: str,
        paths: Sequence[Path | str],
        *,
        phash_threshold: int = 8,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> ParticipantPoolAuditReport:
        participants = self.load_participants(track_id)
        if not participants:
            raise EvaluationTrackError(
                "Najpierw wybierz modele uczestniczące w rankingu."
            )
        self._assert_registered_participants(track_id, participants)
        fp = participant_fingerprint(participants)
        candidates = list(dict.fromkeys(Path(value) for value in paths))
        missing = {path for path in candidates if not path.is_file()}
        self._progress(progress, "Skan", len(candidates), len(candidates))
        candidate_sha, sha_hits, sha_misses = self._ensure_sha(
            [path for path in candidates if path not in missing], progress=progress
        )
        if missing:
            root = self._track_root(track_id)
            stored = {
                root / row["track_relative_path"]: str(row["sha256"])
                for row in self.repository.list_evaluation_track_members(track_id)
            }
            candidate_sha.update({path: stored.get(path, "") for path in missing})

        self._progress(progress, "Lineage modeli", 0, 1)
        refs = [
            dict(row)
            for row in self.repository.list_participant_training_members(
                [item.model_id for item in participants],
                splits=("train", "val"),
            )
        ]
        self._progress(progress, "Lineage modeli", 1, 1)

        by_model_sha = {item.model_id: {} for item in participants}
        by_model_refs = {item.model_id: [] for item in participants}
        history_complete = {
            item.model_id: item.provenance_status in {"complete", "known"}
            for item in participants
        }
        for row in refs:
            model_id = str(row.get("model_id") or "")
            if model_id not in by_model_refs:
                continue
            if (
                row.get("run_provenance_status") not in {"complete", "known"}
                or row.get("dataset_provenance_status") not in {"complete", "known"}
                or not row.get("source_image_id")
                or (int(row.get("ancestor_depth") or 0) >= 128 and row.get("parent_run_id"))
            ):
                history_complete[model_id] = False
            if not row.get("source_image_id"):
                continue
            by_model_refs[model_id].append(row)
            sha = str(row.get("file_sha256") or row.get("artifact_sha256") or "").lower()
            if sha:
                by_model_sha[model_id].setdefault(sha, row)

        exact = {}
        need_candidate_phash = []
        for path in candidates:
            model_hits = {}
            sha = candidate_sha.get(path, "")
            for participant in participants:
                row = by_model_sha[participant.model_id].get(sha)
                if row is not None:
                    model_hits[participant.model_id] = row
            exact[path] = model_hits
            if len(model_hits) != len(participants):
                need_candidate_phash.append(path)

        candidate_phash, ph_hits, ph_misses = self._ensure_phash(
            need_candidate_phash,
            progress=progress,
            stage="pHash kandydatów",
        )

        ref_paths = {item.model_id: {} for item in participants}
        all_ref_paths = []
        for participant in participants:
            for row in by_model_refs[participant.model_id]:
                path = self._resolve_reference_path(row)
                if path is not None:
                    ref_paths[participant.model_id].setdefault(path, row)
                    all_ref_paths.append(path)

        ref_phash, ref_hits, ref_misses = self._ensure_phash(
            list(dict.fromkeys(all_ref_paths)),
            progress=progress,
            stage="pHash train/val",
        )
        ph_hits += ref_hits
        ph_misses += ref_misses

        model_hashes = {}
        coverage = {}
        for participant in participants:
            pairs = []
            for path, row in ref_paths[participant.model_id].items():
                value = ref_phash.get(path)
                if value:
                    pairs.append((int(value, 16), row))
            model_hashes[participant.model_id] = pairs
            total_refs = len(by_model_refs[participant.model_id])
            # The same train/val file can appear in several ancestor runs.
            # Count covered rows, not unique paths, to avoid false gaps.
            covered_refs = sum(
                self._resolve_reference_path(row) in ref_phash
                for row in by_model_refs[participant.model_id]
            )
            coverage[participant.model_id] = (
                covered_refs / total_refs if total_refs else 0.0
            )

        verdicts = []
        total = len(candidates)
        for index, path in enumerate(candidates, 1):
            sha = candidate_sha.get(path, "")
            phash = candidate_phash.get(path, "")
            per_model = []
            for participant in participants:
                if path in missing:
                    per_model.append(ModelCandidateVerdict(
                        participant.model_id, participant.sha256, STATUS_UNKNOWN,
                        "Brak pliku obrazu. Nie można sprawdzić jego zawartości.",
                    ))
                    continue
                hit = exact[path].get(participant.model_id)
                cov = coverage[participant.model_id]
                if hit is not None:
                    per_model.append(
                        ModelCandidateVerdict(
                            participant.model_id,
                            participant.sha256,
                            STATUS_DEPENDENT,
                            "exact SHA-256 w train/val modelu",
                            str(hit.get("run_id") or ""),
                            str(hit.get("dataset_id") or ""),
                            str(hit.get("split") or ""),
                            str(hit.get("member_relative_path") or ""),
                            None,
                            cov,
                            reference_image_path=str(self._resolve_reference_path(hit) or ""),
                        )
                    )
                    continue

                pairs = model_hashes[participant.model_id]
                if not by_model_refs[participant.model_id]:
                    per_model.append(
                        ModelCandidateVerdict(
                            participant.model_id,
                            participant.sha256,
                            STATUS_UNKNOWN,
                            "brak zarejestrowanego train/val w lineage modelu",
                            phash_reference_coverage=0.0,
                        )
                    )
                    continue
                if not phash or not pairs:
                    per_model.append(
                        ModelCandidateVerdict(
                            participant.model_id,
                            participant.sha256,
                            STATUS_UNKNOWN,
                            ("Nie można odczytać obrazu do porównania wyglądu."
                             if not phash else "Brak obrazów referencyjnych treningu/walidacji do porównania."),
                            phash_reference_coverage=cov,
                        )
                    )
                    continue

                candidate_int = int(phash, 16)
                best_distance, best_row = None, None
                for reference_int, row in pairs:
                    distance = (candidate_int ^ reference_int).bit_count()
                    if best_distance is None or distance < best_distance:
                        best_distance, best_row = distance, row
                        if distance == 0:
                            break
                if best_distance is not None and best_distance <= int(phash_threshold):
                    row = best_row or {}
                    per_model.append(
                        ModelCandidateVerdict(
                            participant.model_id,
                            participant.sha256,
                            STATUS_SUSPECT,
                            f"pHash distance={best_distance} ≤ {int(phash_threshold)}",
                            str(row.get("run_id") or ""),
                            str(row.get("dataset_id") or ""),
                            str(row.get("split") or ""),
                            str(row.get("member_relative_path") or ""),
                            int(best_distance),
                            cov,
                            reference_image_path=str(self._resolve_reference_path(row) or ""),
                        )
                    )
                else:
                    per_model.append(
                        ModelCandidateVerdict(
                            participant.model_id,
                            participant.sha256,
                            (STATUS_CLEAN if cov == 1.0 and history_complete[participant.model_id]
                             else STATUS_UNKNOWN),
                            ("brak wykrytej zależności od train/val tego modelu"
                             if cov == 1.0 and history_complete[participant.model_id]
                             else "niepełna historia modelu lub pokrycie train/val"),
                            phash_distance=(
                                int(best_distance)
                                if best_distance is not None else None
                            ),
                            phash_reference_coverage=cov,
                        )
                    )

            verdicts.append(
                CandidateVerdict(
                    str(path),
                    path.name,
                    sha,
                    phash,
                    common_status(item.status for item in per_model),
                    tuple(per_model),
                )
            )
            if index == total or index % 25 == 0:
                self._progress(progress, "Klasyfikacja", index, total)

        self.cache.save()
        report = ParticipantPoolAuditReport(
            AUDIT_SCHEMA,
            str(track_id),
            fp,
            participants,
            tuple(verdicts),
            sum(v.common_status == STATUS_DEPENDENT for v in verdicts),
            sum(v.common_status == STATUS_SUSPECT for v in verdicts),
            sum(v.common_status == STATUS_CLEAN for v in verdicts),
            sum(v.common_status == STATUS_UNKNOWN for v in verdicts),
            datetime.now(timezone.utc).isoformat(),
            sha_hits,
            ph_hits,
            sha_misses,
            ph_misses,
            len(refs),
        )
        audit_dir = self._track_root(track_id) / "audits"
        audit_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        (audit_dir / f"participant_pool_audit_{stamp}.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return report

    def record_ingested_report(self, track_id, report, accepted_paths) -> None:
        participants = self.load_participants(track_id)
        members = self.repository.list_evaluation_track_members(track_id)
        by_path = {str(Path(item.path).resolve()).casefold(): item
                   for item in report.candidates}
        by_sha = {item.sha256.lower(): item for item in report.candidates}
        try:
            self._assert_registered_participants(track_id, participants)
            if (not participants or report.track_id != track_id
                    or report.participant_fingerprint != participant_fingerprint(participants)):
                raise EvaluationTrackError("Raport nie dotyczy aktualnych uczestników tego toru.")
            for path in accepted_paths:
                item = by_path.get(str(Path(path).resolve()).casefold())
                if item is None or item.common_status not in {STATUS_CLEAN, STATUS_SUSPECT}:
                    raise EvaluationTrackError("Wybrany obraz nie ma dopuszczającego wyniku audytu.")
            for row in members:
                item = by_sha.get(str(row["sha256"] or "").lower())
                if item is None or item.common_status not in {STATUS_CLEAN, STATUS_SUSPECT}:
                    raise EvaluationTrackError(
                        "Raport nie potwierdza niezależności wszystkich obrazów toru. Ponów audyt."
                    )
        except Exception:
            self.invalidate_track_audit(track_id, reason="report_does_not_cover_current_pool")
            raise
        # Batch ingest verifies copy SHA against the audited SHA before commit.
        # Seed the cache for those new paths so the next audit can reuse pHash.
        track_root = self._track_root(track_id)
        for row in members:
            item = by_sha[str(row["sha256"]).lower()]
            member_path = track_root / str(row["track_relative_path"])
            if member_path.is_file():
                self.cache.put(member_path, sha256=item.sha256, phash64=item.phash64 or None)
        self.cache.save()
        payload = {
            "schema": AUDIT_SCHEMA,
            "track_id": str(track_id),
            "status": "CURRENT",
            "participant_fingerprint": report.participant_fingerprint,
            "audited_at": report.audited_at,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "accepted_suspect_sha256": sorted(
                str(row["sha256"]).lower() for row in members
                if by_sha[str(row["sha256"]).lower()].common_status == STATUS_SUSPECT
            ),
            "audited_member_sha256": sorted(
                str(row["sha256"] or "").strip().lower()
                for row in members
                if str(row["sha256"] or "").strip()
            ),
        }
        self.repository.save_evaluation_track_audit_state(track_id, payload)

    def assert_track_audit_ready(self, track_id: str) -> None:
        track = self._track_row(track_id)
        if str(track["purpose"] or "").strip().lower() not in {"ranking", "final_test"}:
            return
        self._assert_audit_state_matches(track_id, self._read_track_audit_state(track_id))
