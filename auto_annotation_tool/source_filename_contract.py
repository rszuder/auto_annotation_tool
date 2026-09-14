"""Centralny kontrakt nazewnictwa zasobu O i cropów tablic."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Iterable, Mapping

from .config import CONFIG

SOURCE_IMAGE_KIND = "source_image"
PLATE_CROP_KIND = "plate_crop"

SOURCE_SEQUENCE_RE = re.compile(r"^[0-9]{3,6}$")
SOURCE_PLATE_TOKEN_RE = re.compile(r"^[A-Z0-9]{3,12}$")
PLATE_CROP_STEM_RE = re.compile(r"^plate_[0-9]{6}$")



@dataclass(frozen=True)
class FilenameContractItem:
    path: str
    filename: str
    kind: str
    valid: bool
    plate_tokens: tuple[str, ...] = ()
    sequence_id: str = ""
    resource_id: str = ""
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "filename": self.filename,
            "kind": self.kind,
            "valid": self.valid,
            "plate_tokens": list(self.plate_tokens),
            "sequence_id": self.sequence_id,
            "resource_id": self.resource_id,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class FilenameContractReport:
    kind: str
    items: tuple[FilenameContractItem, ...]
    root: str = ""
    metadata_path: str = ""
    metadata_error: str = ""

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def valid_count(self) -> int:
        return sum(1 for item in self.items if item.valid)

    @property
    def invalid_count(self) -> int:
        return self.total_count - self.valid_count

    @property
    def valid(self) -> bool:
        return (
            self.total_count > 0
            and self.invalid_count == 0
            and not self.metadata_error
        )

    @property
    def invalid_items(self) -> tuple[FilenameContractItem, ...]:
        return tuple(item for item in self.items if not item.valid)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "root": self.root,
            "metadata_path": self.metadata_path,
            "metadata_error": self.metadata_error,
            "total_count": self.total_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "valid": self.valid,
            "items": [item.to_dict() for item in self.items],
        }


def _allowed_extensions() -> set[str]:
    return {
        str(ext or "").strip().lower()
        for ext in CONFIG.IMAGE_EXTENSIONS
        if str(ext or "").strip()
    }


def parse_source_image_filename(
    filename: str | Path,
) -> FilenameContractItem:
    """Waliduj wyłącznie strukturę nazwy zasobu O.

    Kontrakt:
        rejA[_rejB_..._rejN]_identyfikator.ext

    `rejA..rejN` są tokenami nazwy i mogą składać się wyłącznie z A-Z/0-9.
    Nie wymagamy cyfry w tokenie i nie utrzymujemy listy słów zastrzeżonych:
    np. IMG_004.jpg jest poprawną nazwą.
    """
    raw_path = Path(filename)
    name = raw_path.name
    errors: list[str] = []

    if not name:
        errors.append("Pusta nazwa pliku.")
        return FilenameContractItem(
            path=str(filename),
            filename=name,
            kind=SOURCE_IMAGE_KIND,
            valid=False,
            errors=tuple(errors),
        )

    if raw_path.suffix.lower() not in _allowed_extensions():
        errors.append("Nieobsługiwane rozszerzenie obrazu.")

    stem = raw_path.stem
    if not stem:
        errors.append("Brak nazwy przed rozszerzeniem.")
        return FilenameContractItem(
            path=str(filename),
            filename=name,
            kind=SOURCE_IMAGE_KIND,
            valid=False,
            errors=tuple(errors),
        )

    if stem != stem.strip() or any(ch.isspace() for ch in stem):
        errors.append("Nazwa nie może zawierać spacji.")

    if "__" in stem:
        errors.append("Nazwa zawiera pusty segment „__”.")

    parts = stem.split("_")
    if len(parts) < 2:
        errors.append(
            "Wymagany wzorzec: rejA[_rejB_..._rejN]_identyfikator."
        )
        return FilenameContractItem(
            path=str(filename),
            filename=name,
            kind=SOURCE_IMAGE_KIND,
            valid=False,
            errors=tuple(dict.fromkeys(errors)),
        )

    sequence = str(parts[-1] or "")
    if not SOURCE_SEQUENCE_RE.fullmatch(sequence):
        errors.append(
            "Końcowy identyfikator musi mieć 3–6 cyfr."
        )

    plate_tokens: list[str] = []
    for raw_token in parts[:-1]:
        token = str(raw_token or "").strip().upper()
        if not token:
            errors.append("Pusty token rej.")
            continue
        if not SOURCE_PLATE_TOKEN_RE.fullmatch(token):
            errors.append(
                f"Token „{raw_token}” musi mieć 3–12 znaków A–Z/0–9."
            )
            continue
        plate_tokens.append(token)

    if not plate_tokens:
        errors.append("Nazwa nie zawiera prawidłowego tokenu rej.")

    return FilenameContractItem(
        path=str(filename),
        filename=name,
        kind=SOURCE_IMAGE_KIND,
        valid=not errors,
        plate_tokens=tuple(plate_tokens),
        sequence_id=(
            sequence
            if SOURCE_SEQUENCE_RE.fullmatch(sequence)
            else ""
        ),
        resource_id=stem,
        errors=tuple(dict.fromkeys(errors)),
    )

def extract_plate_tokens_from_source_filename(filename: str | Path) -> list[str]:
    item = parse_source_image_filename(filename)
    return list(item.plate_tokens) if item.valid else []


def parse_plate_crop_filename(filename: str | Path) -> FilenameContractItem:
    raw_path = Path(filename)
    errors: list[str] = []
    if raw_path.suffix.lower() not in _allowed_extensions():
        errors.append("Nieobsługiwane rozszerzenie obrazu.")
    stem = raw_path.stem
    if not PLATE_CROP_STEM_RE.fullmatch(stem):
        errors.append(
            "Crop tablicy musi mieć nazwę plate_XXXXXX "
            "(dokładnie 6 cyfr)."
        )
    return FilenameContractItem(
        path=str(filename),
        filename=raw_path.name,
        kind=PLATE_CROP_KIND,
        valid=not errors,
        resource_id=stem if not errors else "",
        errors=tuple(errors),
    )


def validate_source_image_paths(
    paths: Iterable[str | Path],
) -> FilenameContractReport:
    items = tuple(parse_source_image_filename(Path(path)) for path in paths)
    return FilenameContractReport(kind=SOURCE_IMAGE_KIND, items=items)


def _iter_images(root: Path, *, recursive: bool) -> list[Path]:
    try:
        iterator = root.rglob("*") if recursive else root.iterdir()
        return sorted(
            (
                path
                for path in iterator
                if path.is_file()
                and path.suffix.lower() in _allowed_extensions()
            ),
            key=lambda item: item.as_posix().casefold(),
        )
    except Exception:
        return []


def validate_source_image_directory(
    root: str | Path,
    *,
    recursive: bool = True,
) -> FilenameContractReport:
    base = Path(root)
    if not base.exists() or not base.is_dir():
        return FilenameContractReport(
            kind=SOURCE_IMAGE_KIND,
            items=(),
            root=str(base),
            metadata_error="Katalog nie istnieje.",
        )
    paths = _iter_images(base, recursive=recursive)
    report = validate_source_image_paths(paths)
    return FilenameContractReport(
        kind=report.kind,
        items=report.items,
        root=str(base),
        metadata_error=(
            "" if paths else "Katalog nie zawiera obsługiwanych obrazów."
        ),
    )


def _resolve_crop_run_and_images_dir(root: Path) -> tuple[Path, Path]:
    if root.name.lower() == "images":
        return root.parent, root
    images = root / "images"
    if images.is_dir():
        return root, images
    return root.parent, root


def validate_plate_crop_directory(root: str | Path) -> FilenameContractReport:
    input_root = Path(root)
    run_dir, images_dir = _resolve_crop_run_and_images_dir(input_root)
    paths = _iter_images(images_dir, recursive=False)
    metadata_path = run_dir / "metadata.json"
    metadata_error = ""
    metadata: Mapping[str, object] = {}

    if not metadata_path.is_file():
        metadata_error = "Brak metadata.json obok katalogu images."
    else:
        try:
            payload = json.loads(
                metadata_path.read_text(encoding="utf-8-sig")
            )
            if isinstance(payload, Mapping):
                metadata = payload
            else:
                metadata_error = "metadata.json nie jest obiektem JSON."
        except Exception as exc:
            metadata_error = "Nie można odczytać metadata.json: " + str(exc)

    items: list[FilenameContractItem] = []
    for path in paths:
        base_item = parse_plate_crop_filename(path)
        errors = list(base_item.errors)
        stem = path.stem
        if base_item.valid and not metadata_error:
            record = metadata.get(stem)
            if not isinstance(record, Mapping):
                errors.append(f"Brak rekordu metadata.json dla {stem}.")
            else:
                source_image = str(record.get("source_image") or "").strip()
                source_name = str(record.get("source_image_name") or "").strip()
                if not source_image and not source_name:
                    errors.append(
                        f"Rekord {stem} nie wskazuje source_image."
                    )
        items.append(
            FilenameContractItem(
                path=str(path),
                filename=path.name,
                kind=PLATE_CROP_KIND,
                valid=not errors,
                resource_id=stem if not errors else "",
                errors=tuple(dict.fromkeys(errors)),
            )
        )

    if not paths and not metadata_error:
        metadata_error = "Katalog images nie zawiera cropów tablic."

    return FilenameContractReport(
        kind=PLATE_CROP_KIND,
        items=tuple(items),
        root=str(input_root),
        metadata_path=str(metadata_path),
        metadata_error=metadata_error,
    )


def format_filename_contract_report(
    report: FilenameContractReport,
    *,
    max_examples: int = 12,
) -> str:
    lines = [
        f"Sprawdzono obrazów: {report.total_count}",
        f"Poprawne: {report.valid_count}",
        f"Niepoprawne: {report.invalid_count}",
    ]
    if report.metadata_error:
        lines.extend(["", f"Problem zasobu: {report.metadata_error}"])

    invalid = list(report.invalid_items)[: max(0, int(max_examples))]
    if invalid:
        lines.extend(["", "Przykłady błędów:"])
        for item in invalid:
            reason = "; ".join(item.errors) or "Nieznany błąd"
            lines.append(f"- {item.filename}: {reason}")
        if report.invalid_count > len(invalid):
            lines.append(
                f"- ... i {report.invalid_count - len(invalid)} kolejnych"
            )

    if report.kind == SOURCE_IMAGE_KIND:
        lines.extend(
            [
                "",
                "Wzorzec: TABLICA[_TABLICA...]_ID.ext",
                "np. AS93_001.jpg, 365_001.jpg, "
                "2TT0978_WI905PW_001.jpg",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Wzorzec cropa: plate_XXXXXX.ext + metadata.json",
            ]
        )
    return "\n".join(lines)
