"""Reusable evaluation benchmark derived from a sealed PZ3 track.

The benchmark owns no copied image/GT payload. It stores immutable references
to a SEALED source track plus hashes. Working subsets are materialized
transiently under 10_experiments/_working/benchmark_subsets.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from .sample_labels import load_sample_labels

BENCHMARK_SCHEMA = "alpr.evaluation_benchmark.v1"
BENCHMARK_SUBSET_SCHEMA = "alpr.evaluation_benchmark_subset.v1"
BENCHMARK_ROOT_RELATIVE = Path("10_experiments") / "benchmarks"
BENCHMARK_WORKING_RELATIVE = Path("10_experiments") / "_working" / "benchmark_subsets"


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _benchmark_root(workspace: Path, benchmark_id: str) -> Path:
    return Path(workspace) / BENCHMARK_ROOT_RELATIVE / str(benchmark_id)


def _manifest_path(workspace: Path, benchmark_id: str) -> Path:
    return _benchmark_root(workspace, benchmark_id) / "benchmark.json"


def _labels_payload(service, track, members):
    current = {
        str(row.get("sha256") or "").strip().lower()
        for row in members
        if str(row.get("sha256") or "").strip()
    }
    return load_sample_labels(
        service._track_root(track),
        str(track["track_id"]),
        current,
    )


def _build_member_rows(service, track, members, labels_payload):
    assignments = dict((labels_payload or {}).get("assignments") or {})
    label_names = {
        str(row.get("id") or ""): str(row.get("name") or "")
        for row in list((labels_payload or {}).get("labels") or [])
        if isinstance(row, dict)
    }
    result = []
    for row in members:
        sha = str(row.get("sha256") or "").strip().lower()
        label_id = str(assignments.get(sha) or "")
        result.append({
            "member_index": int(row.get("member_index") or 0),
            "source_image_id": str(row.get("source_image_id") or ""),
            "original_name": str(row.get("original_name") or ""),
            "track_relative_path": str(row.get("track_relative_path") or ""),
            "sha256": sha,
            "label_id": label_id,
            "label_name": str(label_names.get(label_id) or ""),
        })
    return sorted(result, key=lambda item: (item["original_name"].lower(), item["sha256"]))


def _fingerprint_core(payload: dict) -> dict:
    return {
        "schema": BENCHMARK_SCHEMA,
        "target": payload.get("target"),
        "source_track_id": payload.get("source_track_id"),
        "source_track_version": payload.get("source_track_version"),
        "source_track_manifest_sha256": payload.get("source_track_manifest_sha256"),
        "gt_sha256": payload.get("gt_sha256"),
        "sample_labels_sha256": payload.get("sample_labels_sha256"),
        "members": [
            {
                "original_name": row["original_name"],
                "sha256": row["sha256"],
                "label_id": row.get("label_id", ""),
            }
            for row in payload.get("members", [])
        ],
        "labels": list(payload.get("labels") or []),
    }


def ensure_benchmark_for_track(service, track_id: str, *, name: str | None = None) -> dict:
    track = dict(service.get_track(track_id))
    if str(track.get("status") or "").upper() != "SEALED":
        raise ValueError("Benchmark można opublikować wyłącznie z toru SEALED.")
    target = str(track.get("target") or "").strip().lower()
    if target not in {"plate", "char"}:
        raise ValueError("Benchmark controlled obsługuje tory plate/MT oraz char/MZ.")

    integrity = service.verify_integrity(track_id)
    if not integrity.ok:
        raise ValueError("Naruszona integralność źródłowego toru: " + "; ".join(integrity.issues))

    members = [dict(row) for row in service.list_members(track_id)]
    if not members:
        raise ValueError("Nie można opublikować benchmarku bez obrazów.")

    gt_relative = str(track.get("gt_relative_path") or "").strip()
    gt_sha = str(track.get("gt_sha256") or "").strip().lower()
    gt_path = service.workspace / gt_relative
    if not gt_relative or not gt_sha or not gt_path.is_file() or _sha256_file(gt_path) != gt_sha:
        raise ValueError("Źródłowy tor nie ma poprawnego, niezmienionego GT.")

    verification = dict(service.get_verification(track_id) or {})
    if not bool(verification.get("manual_gt_complete")):
        raise ValueError("Benchmark controlled wymaga ręcznego potwierdzenia kompletności GT.")
    if target == "char" and not bool(verification.get("char_sequence_ready")):
        raise ValueError(
            "Benchmark controlled MZ wymaga zweryfikowanej sekwencji znaków GT."
        )

    track_root = service._track_root(track)
    track_manifest_path = track_root / "track_manifest.json"
    if not track_manifest_path.is_file():
        raise ValueError("Brak track_manifest.json źródłowego toru.")
    track_manifest_sha = _sha256_file(track_manifest_path)

    labels_payload = _labels_payload(service, track, members)
    labels_bytes = (
        (_canonical_json(labels_payload) + "\n").encode("utf-8")
        if labels_payload is not None
        else b""
    )
    labels_sha = _sha256_bytes(labels_bytes) if labels_bytes else ""

    member_rows = _build_member_rows(service, track, members, labels_payload)
    payload = {
        "schema": BENCHMARK_SCHEMA,
        "benchmark_id": "",
        "name": str(name or track.get("name") or track_id).strip(),
        "target": target,
        "source_track_id": str(track_id),
        "source_track_version": int(track.get("version") or 0),
        "source_track_relative_path": str(track.get("relative_path") or ""),
        "source_track_manifest_sha256": track_manifest_sha,
        "gt_relative_path": gt_relative,
        "gt_sha256": gt_sha,
        "sample_labels_relative_path": (
            str(Path(track.get("relative_path") or "") / "sample_labels.json")
            if labels_payload is not None
            else ""
        ),
        "sample_labels_sha256": labels_sha,
        "labels": list((labels_payload or {}).get("labels") or []),
        "members": member_rows,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manual_gt_complete": True,
        "pose_corner_ready": bool(verification.get("pose_corner_ready", False)),
        "char_sequence_ready": bool(verification.get("char_sequence_ready", False)),
        "char_sequence_count": int(verification.get("char_sequence_count", 0) or 0),
    }
    fingerprint = _sha256_bytes(_canonical_json(_fingerprint_core(payload)).encode("utf-8"))
    benchmark_id = "BENCH-" + fingerprint[:20].upper()
    payload["benchmark_id"] = benchmark_id
    payload["fingerprint"] = fingerprint
    payload["member_count"] = len(member_rows)

    manifest_path = _manifest_path(service.workspace, benchmark_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(existing.get("fingerprint") or "") != fingerprint:
            raise ValueError("Istniejący benchmark_id ma inny fingerprint.")
        return existing

    service._atomic_json(manifest_path, payload)
    return payload


def load_benchmark(workspace: Path | str, benchmark_id_or_path: str | Path) -> dict:
    candidate = Path(str(benchmark_id_or_path))
    if candidate.is_file():
        path = candidate
    else:
        path = _manifest_path(Path(workspace), str(benchmark_id_or_path))
    if not path.is_file():
        raise ValueError(f"Nie znaleziono benchmarku: {benchmark_id_or_path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != BENCHMARK_SCHEMA:
        raise ValueError("Nieprawidłowy benchmark.json.")
    expected = _sha256_bytes(_canonical_json(_fingerprint_core(payload)).encode("utf-8"))
    if str(payload.get("fingerprint") or "") != expected:
        raise ValueError("Fingerprint benchmarku nie odpowiada jego zawartości.")
    return payload


def verify_benchmark(service, benchmark: dict | str) -> dict:
    payload = (
        load_benchmark(service.workspace, benchmark)
        if not isinstance(benchmark, dict)
        else dict(benchmark)
    )
    track_id = str(payload.get("source_track_id") or "")
    track = dict(service.get_track(track_id))
    if str(track.get("status") or "").upper() not in {"SEALED", "RETIRED"}:
        raise ValueError("Źródłowy tor benchmarku nie jest zamrożony.")

    integrity = service.verify_integrity(track_id)
    if not integrity.ok:
        raise ValueError("Źródłowy tor benchmarku utracił integralność: " + "; ".join(integrity.issues))

    gt_path = service.workspace / str(payload.get("gt_relative_path") or "")
    if not gt_path.is_file() or _sha256_file(gt_path) != str(payload.get("gt_sha256") or ""):
        raise ValueError("GT benchmarku zmieniło zawartość albo nie istnieje.")

    track_root = service._track_root(track)
    current = {
        str(row.get("sha256") or "").strip().lower(): dict(row)
        for row in service.list_members(track_id)
    }
    expected = {str(row.get("sha256") or "") for row in payload.get("members", [])}
    if set(current) != expected:
        raise ValueError("Skład źródłowego toru nie odpowiada benchmarkowi.")
    for row in payload.get("members", []):
        sha = str(row.get("sha256") or "")
        live = current.get(sha)
        path = track_root / str(live.get("track_relative_path") or "")
        if not path.is_file() or _sha256_file(path) != sha:
            raise ValueError(f"Obraz benchmarku zmienił zawartość: {row.get('original_name')}")

    return payload


def benchmark_groups(benchmark: dict, *, selected_sha256=None) -> list[dict]:
    payload = dict(benchmark)
    members = list(payload.get("members") or [])
    allowed = None
    if selected_sha256 is not None:
        allowed = {
            str(value or "").strip().lower()
            for value in selected_sha256
            if str(value or "").strip()
        }
        members = [row for row in members if str(row.get("sha256") or "") in allowed]

    groups = [{
        "group_id": "ALL",
        "label_id": "",
        "label_name": "Wszystkie",
        "count": len(members),
        "sha256": [str(row.get("sha256") or "") for row in members],
        "image_names": [str(row.get("original_name") or "") for row in members],
    }]

    unlabeled = [row for row in members if not str(row.get("label_id") or "")]
    if unlabeled:
        groups.append({
            "group_id": "UNLABELED",
            "label_id": "",
            "label_name": "Bez etykiety",
            "count": len(unlabeled),
            "sha256": [str(row.get("sha256") or "") for row in unlabeled],
            "image_names": [str(row.get("original_name") or "") for row in unlabeled],
        })

    for label in list(payload.get("labels") or []):
        if not isinstance(label, dict):
            continue
        label_id = str(label.get("id") or "")
        label_name = str(label.get("name") or label_id)
        rows = [row for row in members if str(row.get("label_id") or "") == label_id]
        if not rows:
            continue
        groups.append({
            "group_id": "LABEL:" + label_id,
            "label_id": label_id,
            "label_name": label_name,
            "count": len(rows),
            "sha256": [str(row.get("sha256") or "") for row in rows],
            "image_names": [str(row.get("original_name") or "") for row in rows],
        })
    return groups


def resolve_benchmark_subset(
    benchmark: dict,
    *,
    selected_sha256=None,
    label_ids=None,
    include_unlabeled: bool = False,
) -> dict:
    payload = dict(benchmark)
    members = list(payload.get("members") or [])
    explicit_sha = {
        str(value or "").strip().lower()
        for value in (selected_sha256 or ())
        if str(value or "").strip()
    }
    labels = {
        str(value or "").strip()
        for value in (label_ids or ())
        if str(value or "").strip()
    }

    if explicit_sha:
        selected = [row for row in members if str(row.get("sha256") or "") in explicit_sha]
    elif labels or include_unlabeled:
        selected = [
            row for row in members
            if (
                str(row.get("label_id") or "") in labels
                or (include_unlabeled and not str(row.get("label_id") or ""))
            )
        ]
    else:
        selected = list(members)

    if not selected:
        raise ValueError("Wybrany podzbiór benchmarku jest pusty.")

    sha = sorted(str(row.get("sha256") or "") for row in selected)
    subset_core = {
        "benchmark_id": payload.get("benchmark_id"),
        "benchmark_fingerprint": payload.get("fingerprint"),
        "selected_sha256": sha,
    }
    subset_fingerprint = _sha256_bytes(_canonical_json(subset_core).encode("utf-8"))
    return {
        "benchmark_id": str(payload.get("benchmark_id") or ""),
        "benchmark_fingerprint": str(payload.get("fingerprint") or ""),
        "subset_fingerprint": subset_fingerprint,
        "selected_sha256": sha,
        "members": selected,
        "count": len(selected),
    }


def _filter_cvat_xml(source_xml: Path, destination_xml: Path, image_names: set[str]) -> None:
    root = ET.parse(source_xml).getroot()
    for parent in [root]:
        for image in list(parent.findall("image")):
            name = Path(str(image.get("name") or "")).name
            if name not in image_names:
                parent.remove(image)
    destination_xml.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(destination_xml, encoding="utf-8", xml_declaration=True)


def materialize_benchmark_subset(
    service,
    benchmark_id_or_payload,
    *,
    selected_sha256=None,
    label_ids=None,
    include_unlabeled: bool = False,
) -> dict:
    benchmark = (
        verify_benchmark(service, benchmark_id_or_payload)
        if not isinstance(benchmark_id_or_payload, dict)
        else verify_benchmark(service, benchmark_id_or_payload)
    )
    subset = resolve_benchmark_subset(
        benchmark,
        selected_sha256=selected_sha256,
        label_ids=label_ids,
        include_unlabeled=include_unlabeled,
    )

    root = (
        service.workspace
        / BENCHMARK_WORKING_RELATIVE
        / str(benchmark["benchmark_id"])
        / str(subset["subset_fingerprint"])
    )
    images_dir = root / "images"
    xml_path = root / "annotations.xml"
    subset_manifest = root / "subset.json"
    expected_manifest = {
        "schema": BENCHMARK_SUBSET_SCHEMA,
        "benchmark_id": benchmark["benchmark_id"],
        "benchmark_fingerprint": benchmark["fingerprint"],
        "subset_fingerprint": subset["subset_fingerprint"],
        "selected_sha256": subset["selected_sha256"],
    }

    if subset_manifest.is_file() and xml_path.is_file() and images_dir.is_dir():
        try:
            existing = json.loads(subset_manifest.read_text(encoding="utf-8"))
            if existing == expected_manifest:
                return {
                    **subset,
                    "reference_path": str(root),
                    "images_dir": str(images_dir),
                    "xml_path": str(xml_path),
                }
        except Exception:
            pass

    if root.exists():
        shutil.rmtree(root)
    images_dir.mkdir(parents=True, exist_ok=True)

    source_track = dict(service.get_track(str(benchmark["source_track_id"])))
    source_root = service._track_root(source_track)
    names = set()
    for row in subset["members"]:
        src = source_root / str(row.get("track_relative_path") or "")
        dst = images_dir / str(row.get("original_name") or "")
        names.add(dst.name)
        try:
            os.link(src, dst)
        except Exception:
            shutil.copy2(src, dst)

    gt_path = service.workspace / str(benchmark["gt_relative_path"])
    _filter_cvat_xml(gt_path, xml_path, names)
    service._atomic_json(subset_manifest, expected_manifest)
    return {
        **subset,
        "reference_path": str(root),
        "images_dir": str(images_dir),
        "xml_path": str(xml_path),
    }
