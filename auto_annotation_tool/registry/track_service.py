"""Wersjonowane i pieczętowane tory testowe dla kontrolowanych eksperymentów."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from ..config import CONFIG
from .repository import RegistryRepository

TRACK_SCHEMA = "alpr.evaluation_track.v1"
SEAL_SCHEMA = "alpr.evaluation_track_seal.v1"

STATUS_DRAFT = "DRAFT"
STATUS_VERIFIED = "VERIFIED"
STATUS_SEALED = "SEALED"
STATUS_RETIRED = "RETIRED"

INTEGRITY_PASS = "PASS"
INTEGRITY_FAIL = "FAIL"
INTEGRITY_UNKNOWN = "UNKNOWN"


class EvaluationTrackError(RuntimeError):
    """Błąd domenowy toru testowego."""


@dataclass(frozen=True)
class TrackIntegrityResult:
    status: str
    track_id: str
    issues: tuple[str, ...] = ()
    manifest_sha256: str = ""

    @property
    def ok(self) -> bool:
        return self.status == INTEGRITY_PASS


class EvaluationTrackService:
    """Tworzy, weryfikuje i pieczętuje samowystarczalne tory testowe."""

    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        *,
        repository: RegistryRepository | None = None,
    ) -> None:
        self.workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
        self.root = self.workspace / "10_evaluation_tracks"
        self.repository = repository or RegistryRepository.for_workspace(self.workspace)
        self.repository.initialize()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_draft(
        self,
        *,
        name: str,
        target: str,
        purpose: str,
        scope: str = "global",
        owner_project_id: str | None = None,
        reservation_policy: str = "none",
        parent_track_id: str | None = None,
        version: int = 1,
    ) -> str:
        clean_name = str(name or "").strip()
        clean_target = self._normalize_target(target)
        clean_purpose = str(purpose or "").strip().lower()
        clean_scope = str(scope or "").strip().lower() or "global"
        if not clean_name:
            raise EvaluationTrackError("Nazwa toru nie może być pusta.")
        if not clean_target:
            raise EvaluationTrackError(f"Nieobsługiwany target toru: {target!r}.")
        if not clean_purpose:
            raise EvaluationTrackError("Purpose toru nie może być pusty.")
        if int(version or 0) < 1:
            raise EvaluationTrackError("Wersja toru musi być >= 1.")

        if parent_track_id:
            parent = self.repository.get_evaluation_track(parent_track_id)
            if parent is None:
                raise EvaluationTrackError("Nie znaleziono toru nadrzędnego.")

        track_id = f"TRK-{uuid.uuid4().hex[:20].upper()}"
        slug = self._safe_slug(clean_name)
        folder = f"{slug}__v{int(version):03d}__{track_id[-8:]}"
        track_root = self.root / clean_target / folder
        images_dir = track_root / "images"
        gt_dir = track_root / "ground_truth"
        images_dir.mkdir(parents=True, exist_ok=False)
        gt_dir.mkdir(parents=True, exist_ok=True)

        relative_path = self._workspace_relative(track_root)
        created_at = self._utc_now()
        try:
            self.repository.create_evaluation_track(
                track_id=track_id,
                owner_project_id=owner_project_id,
                name=clean_name,
                target=clean_target,
                purpose=clean_purpose,
                scope=clean_scope,
                status=STATUS_DRAFT,
                version=int(version),
                parent_track_id=parent_track_id,
                relative_path=relative_path,
                reservation_policy=reservation_policy,
                created_at=created_at,
            )
            self._write_manifest(track_id)
        except Exception:
            shutil.rmtree(track_root, ignore_errors=True)
            raise
        return track_id

    def add_member(
        self,
        track_id: str,
        source_path: Path | str,
        *,
        source_image_id: str | None = None,
        source_artifact_id: str | None = None,
        original_name: str | None = None,
    ) -> int:
        track = self._require_status(track_id, STATUS_DRAFT)
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise EvaluationTrackError(f"Brak pliku źródłowego: {source}")

        name = str(original_name or source.name).strip()
        if not name or Path(name).name != name:
            raise EvaluationTrackError("Nazwa obrazu toru musi być samą nazwą pliku.")
        existing_names = {
            str(row["original_name"] or "")
            for row in self.repository.list_evaluation_track_members(track_id)
        }
        if name in existing_names:
            raise EvaluationTrackError(f"Tor zawiera już obraz o nazwie: {name}")

        sha = self._sha256(source)
        if not sha:
            raise EvaluationTrackError(f"Nie udało się policzyć SHA-256: {source}")

        resolved_source_id = self.repository.resolve_or_create_source_image(
            sha256=sha,
            source_image_id=source_image_id,
            origin_status="exact_hash_only" if not source_image_id else "known",
        )
        member_index = self.repository.next_evaluation_track_member_index(track_id)

        track_root = self._track_root(track)
        destination = track_root / "images" / name
        shutil.copy2(source, destination)
        if self._sha256(destination) != sha:
            destination.unlink(missing_ok=True)
            raise EvaluationTrackError("Kopia obrazu toru nie zgadza się z plikiem źródłowym.")

        artifact_seed = f"{track_id}|{member_index}|{sha}|{name}".encode("utf-8")
        track_artifact_id = (
            "ART-TRACK-" + hashlib.sha256(artifact_seed).hexdigest().upper()[:32]
        )
        artifact_relative = self._workspace_relative(destination)
        try:
            self.repository.add_evaluation_track_member(
                track_id=track_id,
                member_index=member_index,
                source_image_id=resolved_source_id,
                source_artifact_id=source_artifact_id,
                track_artifact_id=track_artifact_id,
                original_name=name,
                track_relative_path=f"images/{name}",
                sha256=sha,
                artifact_relative_path=artifact_relative,
                artifact_size_bytes=destination.stat().st_size,
            )
            self._write_manifest(track_id)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return member_index

    def set_ground_truth(
        self,
        track_id: str,
        source_path: Path | str,
        *,
        gt_format: str = "cvat_xml",
    ) -> Path:
        track = self._require_status(track_id, STATUS_DRAFT)
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise EvaluationTrackError(f"Brak pliku GT: {source}")

        normalized_format = str(gt_format or "").strip().lower()
        if normalized_format != "cvat_xml":
            raise EvaluationTrackError(
                "ETAP 5 obsługuje weryfikację GT w formacie cvat_xml."
            )

        track_root = self._track_root(track)
        gt_dir = track_root / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)
        destination = gt_dir / ("annotations" + (source.suffix or ".xml"))
        shutil.copy2(source, destination)
        gt_sha = self._sha256(destination)

        old_relative = str(track["gt_relative_path"] or "").strip()
        if old_relative and old_relative != self._workspace_relative(destination):
            old_path = self.workspace / old_relative
            if old_path.exists() and self._is_within(old_path, track_root):
                old_path.unlink(missing_ok=True)

        self.repository.update_evaluation_track(
            track_id,
            gt_format=normalized_format,
            gt_relative_path=self._workspace_relative(destination),
            gt_sha256=gt_sha,
        )
        self._write_manifest(track_id)
        return destination

    def verify(self, track_id: str) -> dict[str, Any]:
        track = self._require_status(track_id, STATUS_DRAFT)
        members = self.repository.list_evaluation_track_members(track_id)
        if not members:
            raise EvaluationTrackError("Nie można zweryfikować pustego toru.")

        gt_format = str(track["gt_format"] or "").strip().lower()
        gt_relative = str(track["gt_relative_path"] or "").strip()
        gt_sha = str(track["gt_sha256"] or "").strip().lower()
        if not gt_format or not gt_relative or not gt_sha:
            raise EvaluationTrackError("Tor nie ma kompletnego Ground Truth.")

        gt_path = self.workspace / gt_relative
        if not gt_path.exists() or self._sha256(gt_path) != gt_sha:
            raise EvaluationTrackError("Plik GT nie istnieje albo zmienił zawartość.")

        for member in members:
            member_path = self._track_root(track) / str(member["track_relative_path"])
            expected = str(member["sha256"] or "").strip().lower()
            if not member_path.exists() or self._sha256(member_path) != expected:
                raise EvaluationTrackError(
                    f"Obraz toru zmienił zawartość: {member['original_name']}"
                )

        if gt_format != "cvat_xml":
            raise EvaluationTrackError(f"Brak walidatora GT dla formatu: {gt_format}")

        verification = self._verify_cvat_xml(track, members, gt_path)
        verified_at = self._utc_now()
        # Najpierw przygotuj manifest VERIFIED. Jeśli zapis DB się nie powiedzie,
        # tor pozostaje DRAFT i weryfikację można bezpiecznie powtórzyć.
        self._write_manifest(
            track_id,
            verification=verification,
            status_override=STATUS_VERIFIED,
            verified_at_override=verified_at,
            object_count_override=int(verification["object_count"]),
        )
        self.repository.update_evaluation_track(
            track_id,
            status=STATUS_VERIFIED,
            member_count=len(members),
            object_count=int(verification["object_count"]),
            verified_at=verified_at,
        )
        return verification

    def seal(self, track_id: str) -> TrackIntegrityResult:
        track = self._require_status(track_id, STATUS_VERIFIED)
        preflight = self._content_integrity(track_id)
        if not preflight.ok:
            raise EvaluationTrackError(
                "Nie można zapieczętować toru: " + "; ".join(preflight.issues)
            )

        sealed_at = self._utc_now()
        # Najpierw zapisujemy finalny manifest i seal, dopiero potem lifecycle w DB.
        # W razie błędu DB tor nadal jest VERIFIED i pieczętowanie można powtórzyć.
        manifest_path = self._write_manifest(
            track_id,
            status_override=STATUS_SEALED,
            sealed_at_override=sealed_at,
        )
        manifest_sha = self._sha256(manifest_path)

        track = self._require_track(track_id)
        members = self.repository.list_evaluation_track_members(track_id)
        files = [
            {
                "path": str(row["track_relative_path"]),
                "sha256": str(row["sha256"] or "").lower(),
            }
            for row in members
        ]
        gt_relative = str(track["gt_relative_path"] or "")
        if gt_relative:
            gt_path = self.workspace / gt_relative
            files.append(
                {
                    "path": gt_path.relative_to(self._track_root(track)).as_posix(),
                    "sha256": str(track["gt_sha256"] or "").lower(),
                }
            )

        seal_payload = {
            "schema": SEAL_SCHEMA,
            "track_id": track_id,
            "version": int(track["version"]),
            "sealed_at": sealed_at,
            "manifest_sha256": manifest_sha,
            "algorithm": "sha256",
            "files": files,
        }
        self._atomic_json(self._track_root(track) / "seal.json", seal_payload)
        self.repository.update_evaluation_track(
            track_id,
            status=STATUS_SEALED,
            sealed_at=sealed_at,
            manifest_sha256=manifest_sha,
        )
        return self.verify_integrity(track_id)

    def verify_integrity(self, track_id: str) -> TrackIntegrityResult:
        track = self._require_track(track_id)
        status = str(track["status"] or "")
        if status not in {STATUS_SEALED, STATUS_RETIRED}:
            return TrackIntegrityResult(
                status=INTEGRITY_UNKNOWN,
                track_id=track_id,
                issues=("Tor nie jest zapieczętowany.",),
            )

        track_root = self._track_root(track)
        manifest_path = track_root / "track_manifest.json"
        seal_path = track_root / "seal.json"
        issues: list[str] = []

        if not manifest_path.exists():
            issues.append("Brak track_manifest.json.")
        if not seal_path.exists():
            issues.append("Brak seal.json.")
        if issues:
            return TrackIntegrityResult(
                status=INTEGRITY_FAIL,
                track_id=track_id,
                issues=tuple(issues),
            )

        try:
            seal = json.loads(seal_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return TrackIntegrityResult(
                status=INTEGRITY_FAIL,
                track_id=track_id,
                issues=(f"Nie można odczytać seal.json: {exc}",),
            )

        manifest_sha = self._sha256(manifest_path)
        expected_manifest = str(seal.get("manifest_sha256") or "").strip().lower()
        db_manifest = str(track["manifest_sha256"] or "").strip().lower()
        if manifest_sha != expected_manifest:
            issues.append("SHA-256 manifestu nie zgadza się z seal.json.")
        if db_manifest and manifest_sha != db_manifest:
            issues.append("SHA-256 manifestu nie zgadza się z rejestrem SQLite.")

        for item in seal.get("files") or []:
            if not isinstance(item, Mapping):
                issues.append("Niepoprawny wpis files w seal.json.")
                continue
            relative = str(item.get("path") or "").strip()
            expected = str(item.get("sha256") or "").strip().lower()
            candidate = track_root / relative
            if not self._is_within(candidate, track_root):
                issues.append(f"Ścieżka w seal.json wychodzi poza tor: {relative}")
                continue
            if not candidate.exists():
                issues.append(f"Brak pliku toru: {relative}")
                continue
            actual = self._sha256(candidate)
            if actual != expected:
                issues.append(f"Zmieniła się zawartość pliku: {relative}")

        return TrackIntegrityResult(
            status=INTEGRITY_FAIL if issues else INTEGRITY_PASS,
            track_id=track_id,
            issues=tuple(issues),
            manifest_sha256=manifest_sha,
        )

    def retire(self, track_id: str) -> None:
        self._require_status(track_id, STATUS_SEALED)
        integrity = self.verify_integrity(track_id)
        if not integrity.ok:
            raise EvaluationTrackError(
                "Nie można wycofać toru z uszkodzoną pieczęcią."
            )
        # Manifest i seal pozostają nietknięte: retirement jest stanem lifecycle w DB.
        self.repository.update_evaluation_track(track_id, status=STATUS_RETIRED)

    def clone_new_version(
        self,
        track_id: str,
        *,
        name: str | None = None,
    ) -> str:
        parent = self._require_track(track_id)
        if str(parent["status"] or "") not in {STATUS_SEALED, STATUS_RETIRED}:
            raise EvaluationTrackError(
                "Nową wersję można tworzyć tylko z toru SEALED/RETIRED."
            )
        integrity = self.verify_integrity(track_id)
        if not integrity.ok:
            raise EvaluationTrackError("Nie można klonować toru z uszkodzoną pieczęcią.")

        new_id = self.create_draft(
            name=str(name or parent["name"]),
            target=str(parent["target"]),
            purpose=str(parent["purpose"]),
            scope=str(parent["scope"]),
            owner_project_id=parent["owner_project_id"],
            reservation_policy=str(parent["reservation_policy"] or "none"),
            parent_track_id=track_id,
            version=int(parent["version"]) + 1,
        )

        parent_root = self._track_root(parent)
        for member in self.repository.list_evaluation_track_members(track_id):
            source_artifact_id = (
                str(member["source_artifact_id"] or "")
                or str(member["track_artifact_id"] or "")
                or None
            )
            self.add_member(
                new_id,
                parent_root / str(member["track_relative_path"]),
                source_image_id=str(member["source_image_id"]),
                source_artifact_id=source_artifact_id,
                original_name=str(member["original_name"]),
            )

        gt_relative = str(parent["gt_relative_path"] or "").strip()
        if gt_relative:
            self.set_ground_truth(
                new_id,
                self.workspace / gt_relative,
                gt_format=str(parent["gt_format"] or "cvat_xml"),
            )
        return new_id

    def get_track(self, track_id: str) -> dict[str, Any]:
        row = self._require_track(track_id)
        return dict(row)

    def list_members(self, track_id: str) -> list[dict[str, Any]]:
        self._require_track(track_id)
        return [dict(row) for row in self.repository.list_evaluation_track_members(track_id)]

    def _verify_cvat_xml(
        self,
        track: Mapping[str, Any],
        members: list[Any],
        gt_path: Path,
    ) -> dict[str, Any]:
        try:
            root = ET.parse(gt_path).getroot()
        except (OSError, ET.ParseError) as exc:
            raise EvaluationTrackError(f"Nie można odczytać CVAT XML: {exc}") from exc

        image_nodes = root.findall(".//image")
        xml_names = [Path(str(node.get("name") or "")).name for node in image_nodes]
        if len(xml_names) != len(set(xml_names)):
            raise EvaluationTrackError("CVAT XML zawiera zduplikowane nazwy obrazów.")

        member_names = [str(row["original_name"] or "") for row in members]
        missing = sorted(set(member_names) - set(xml_names))
        extra = sorted(set(xml_names) - set(member_names))
        if missing or extra:
            details = []
            if missing:
                details.append("brak w GT: " + ", ".join(missing[:10]))
            if extra:
                details.append("nadmiarowe w GT: " + ", ".join(extra[:10]))
            raise EvaluationTrackError("Zestaw obrazów GT nie odpowiada torowi (" + "; ".join(details) + ").")

        object_count = 0
        box_count = 0
        polygon_count = 0
        quad_polygon_count = 0
        invalid_polygon_count = 0
        images_without_objects = 0

        for node in image_nodes:
            boxes = node.findall("box")
            polygons = node.findall("polygon")
            box_count += len(boxes)
            polygon_count += len(polygons)
            shapes = len(boxes) + len(polygons)
            object_count += shapes
            if shapes == 0:
                images_without_objects += 1
            for polygon in polygons:
                points = str(polygon.get("points") or "").split(";")
                points = [point for point in points if point.strip()]
                if len(points) == 4:
                    quad_polygon_count += 1
                else:
                    invalid_polygon_count += 1

        if object_count <= 0:
            raise EvaluationTrackError("GT nie zawiera żadnego obiektu.")
        if invalid_polygon_count:
            raise EvaluationTrackError(
                "GT zawiera polygon(y) o liczbie narożników innej niż 4."
            )

        return {
            "format": "cvat_xml",
            "member_count": len(members),
            "object_count": object_count,
            "box_count": box_count,
            "polygon_count": polygon_count,
            "quad_polygon_count": quad_polygon_count,
            "images_without_objects": images_without_objects,
            "pose_corner_ready": bool(
                str(track["target"]) == "plate"
                and polygon_count > 0
                and box_count == 0
                and polygon_count == quad_polygon_count
            ),
        }

    def _content_integrity(self, track_id: str) -> TrackIntegrityResult:
        track = self._require_track(track_id)
        track_root = self._track_root(track)
        issues: list[str] = []
        for member in self.repository.list_evaluation_track_members(track_id):
            path = track_root / str(member["track_relative_path"])
            if not path.exists():
                issues.append(f"Brak obrazu: {member['original_name']}")
                continue
            if self._sha256(path) != str(member["sha256"] or "").lower():
                issues.append(f"Zmieniono obraz: {member['original_name']}")
        gt_relative = str(track["gt_relative_path"] or "").strip()
        gt_sha = str(track["gt_sha256"] or "").strip().lower()
        if not gt_relative or not gt_sha:
            issues.append("Brak GT.")
        else:
            gt_path = self.workspace / gt_relative
            if not gt_path.exists():
                issues.append("Brak pliku GT.")
            elif self._sha256(gt_path) != gt_sha:
                issues.append("Zmieniono plik GT.")
        return TrackIntegrityResult(
            status=INTEGRITY_FAIL if issues else INTEGRITY_PASS,
            track_id=track_id,
            issues=tuple(issues),
        )

    def _write_manifest(
        self,
        track_id: str,
        *,
        verification: Mapping[str, Any] | None = None,
        status_override: str | None = None,
        verified_at_override: str | None = None,
        sealed_at_override: str | None = None,
        object_count_override: int | None = None,
    ) -> Path:
        track = self._require_track(track_id)
        track_root = self._track_root(track)
        manifest_path = track_root / "track_manifest.json"

        preserved_verification: dict[str, Any] = {}
        if verification is None and manifest_path.exists():
            try:
                old = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(old.get("verification"), Mapping):
                    preserved_verification = dict(old["verification"])
            except Exception:
                preserved_verification = {}

        members = [
            {
                "member_index": int(row["member_index"]),
                "source_image_id": str(row["source_image_id"]),
                "source_artifact_id": row["source_artifact_id"],
                "track_artifact_id": row["track_artifact_id"],
                "original_name": str(row["original_name"] or ""),
                "track_relative_path": str(row["track_relative_path"] or ""),
                "sha256": str(row["sha256"] or "").lower(),
            }
            for row in self.repository.list_evaluation_track_members(track_id)
        ]

        gt_relative = str(track["gt_relative_path"] or "").strip()
        gt_track_relative = ""
        if gt_relative:
            gt_path = self.workspace / gt_relative
            try:
                gt_track_relative = gt_path.relative_to(track_root).as_posix()
            except Exception:
                gt_track_relative = gt_relative

        payload = {
            "schema": TRACK_SCHEMA,
            "track_id": track_id,
            "name": str(track["name"]),
            "target": str(track["target"]),
            "purpose": str(track["purpose"]),
            "scope": str(track["scope"]),
            "status": str(status_override or track["status"]),
            "version": int(track["version"]),
            "parent_track_id": track["parent_track_id"],
            "reservation_policy": track["reservation_policy"],
            "member_count": int(track["member_count"] or len(members)),
            "object_count": int(
                object_count_override
                if object_count_override is not None
                else (track["object_count"] or 0)
            ),
            "created_at": track["created_at"],
            "verified_at": (
                verified_at_override
                if verified_at_override is not None
                else track["verified_at"]
            ),
            "sealed_at": (
                sealed_at_override
                if sealed_at_override is not None
                else track["sealed_at"]
            ),
            "ground_truth": {
                "format": str(track["gt_format"] or ""),
                "relative_path": gt_track_relative,
                "sha256": str(track["gt_sha256"] or "").lower(),
            },
            "members": members,
            "verification": dict(verification or preserved_verification),
        }
        self._atomic_json(manifest_path, payload)
        return manifest_path

    def _require_track(self, track_id: str):
        row = self.repository.get_evaluation_track(str(track_id or "").strip())
        if row is None:
            raise EvaluationTrackError(f"Nie znaleziono toru: {track_id}")
        return row

    def _require_status(self, track_id: str, expected: str):
        row = self._require_track(track_id)
        actual = str(row["status"] or "")
        if actual != expected:
            raise EvaluationTrackError(
                f"Operacja wymaga statusu {expected}; aktualny status: {actual}."
            )
        return row

    def _track_root(self, track: Mapping[str, Any]) -> Path:
        relative = str(track["relative_path"] or "").strip()
        path = self.workspace / relative
        if not self._is_within(path, self.root):
            raise EvaluationTrackError("Ścieżka toru wychodzi poza 10_evaluation_tracks.")
        return path

    def _workspace_relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.workspace.resolve()).as_posix()
        except Exception as exc:
            raise EvaluationTrackError(
                f"Artefakt toru musi znajdować się w Workspace: {path}"
            ) from exc

    @staticmethod
    def _normalize_target(target: str) -> str:
        raw = str(target or "").strip().lower()
        if raw in {"plate", "plates", "pose", "mt"}:
            return "plate"
        if raw in {"char", "chars", "character", "characters", "mz"}:
            return "char"
        if raw in {"vehicle", "vehicles"}:
            return "vehicle"
        return ""

    @staticmethod
    def _safe_slug(value: str) -> str:
        chars = []
        for char in str(value or "").strip():
            if char.isalnum() or char in {"-", "_"}:
                chars.append(char)
            elif char.isspace():
                chars.append("_")
            else:
                chars.append("_")
        result = "".join(chars).strip("_-")
        return result[:80] or "track"

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except Exception:
            return ""
        return digest.hexdigest()

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    @staticmethod
    def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name("." + path.name + ".tmp")
        data = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        temp.write_bytes(data)
        temp.replace(path)
