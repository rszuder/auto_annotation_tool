"""Zgodność starych wyników rankingu z rejestrem eksperymentów SQLite."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..registry.repository import RegistryRepository
from .model_ranking import ModelRankingEntry

RANKING_RESULT_SCHEMA = "alpr.ranking_experiment_result.v1"

EVIDENCE_CONTROLLED = "CONTROLLED_REGISTERED"
EVIDENCE_CONTROLLED_LEGACY = "CONTROLLED_LEGACY_PROTOCOL"
EVIDENCE_WORKING = "WORKING_REGISTERED"
EVIDENCE_REGISTERED_INCOMPLETE = "REGISTERED_INCOMPLETE"
EVIDENCE_LEGACY = "LEGACY_UNREGISTERED"
EVIDENCE_ORPHANED = "ORPHANED_EXPERIMENT"
EVIDENCE_MISMATCH = "REGISTRY_MISMATCH"


def ranking_evidence_label(status: str | None) -> str:
    value = str(status or "").strip().upper()
    return {
        EVIDENCE_CONTROLLED: "CONTROLLED",
        EVIDENCE_CONTROLLED_LEGACY: "REGISTERED LEGACY",
        EVIDENCE_WORKING: "WORKING",
        EVIDENCE_REGISTERED_INCOMPLETE: "NIEKOMPLETNY",
        EVIDENCE_LEGACY: "LEGACY",
        EVIDENCE_ORPHANED: "OSIEROCONY",
        EVIDENCE_MISMATCH: "NIEZGODNY",
    }.get(value, value or "NIEZNANY")


@dataclass(frozen=True)
class RankingRegistryReconciliation:
    entries: tuple[ModelRankingEntry, ...]
    legacy_entries: int = 0
    registered_entries: int = 0
    recovered_entries: int = 0
    mismatched_entries: int = 0
    orphaned_entries: int = 0


class RankingRegistryCompatibility:
    """Łączy JSON rankingu z wynikiem eksperymentu bez fałszowania historii.

    Zasady:
    - wpis bez ``experiment_id`` pozostaje LEGACY_UNREGISTERED;
    - nigdy nie zgadujemy powiązania legacy na podstawie podobnych metryk;
    - wynik z SQLite może odtworzyć brakujący wpis JSON;
    - metadane istniejącego wpisu mogą być uzupełnione tylko wtedy, gdy
      nie przeczą zamrożonym identyfikatorom w SQLite;
    - stary eksperyment ``controlled`` sprzed obowiązku ręcznej kompletności
      GT otrzymuje status CONTROLLED_LEGACY_PROTOCOL, a nie pełny CONTROLLED.
    """

    def __init__(
        self,
        repository: RegistryRepository,
    ) -> None:
        self.repository = repository
        self.repository.initialize()

    def reconcile(
        self,
        entries: Sequence[ModelRankingEntry],
        *,
        target: str | None = None,
    ) -> RankingRegistryReconciliation:
        bundles = self.repository.list_experiment_result_bundles(
            target=str(target or "").strip().lower() or None
        )
        bundle_by_key = {
            (
                str(row["experiment_id"] or ""),
                str(row["model_id"] or ""),
            ): row
            for row in bundles
        }
        bundles_by_experiment: dict[str, list[Any]] = {}
        for row in bundles:
            bundles_by_experiment.setdefault(
                str(row["experiment_id"] or ""),
                [],
            ).append(row)

        result: list[ModelRankingEntry] = []
        represented_keys: set[tuple[str, str]] = set()
        legacy_count = 0
        registered_count = 0
        mismatch_count = 0
        orphan_count = 0

        for entry in list(entries or ()):
            experiment_id = str(
                getattr(entry, "experiment_id", "") or ""
            ).strip()
            if not experiment_id:
                self._mark(
                    entry,
                    EVIDENCE_LEGACY,
                    (
                        "Wynik pochodzi z pliku rankingu sprzed rejestru "
                        "eksperymentów albo z trybu legacy. Nie stanowi "
                        "dowodu eksperymentu controlled."
                    ),
                    registry_status="",
                )
                legacy_count += 1
                result.append(entry)
                continue

            experiment = self.repository.get_experiment(
                experiment_id
            )
            if experiment is None:
                self._mark(
                    entry,
                    EVIDENCE_ORPHANED,
                    (
                        "Wpis zawiera experiment_id, którego nie ma "
                        "w lokalnym rejestrze SQLite."
                    ),
                    registry_status="",
                )
                orphan_count += 1
                result.append(entry)
                continue

            candidate = self._find_bundle_for_entry(
                entry,
                bundles_by_experiment.get(
                    experiment_id,
                    [],
                ),
            )
            if candidate is None:
                self._mark(
                    entry,
                    EVIDENCE_REGISTERED_INCOMPLETE,
                    (
                        "Eksperyment istnieje w SQLite, ale nie ma "
                        "odpowiadającego zapisanego wyniku uczestnika."
                    ),
                    registry_status=str(
                        experiment["status"] or ""
                    ),
                )
                registered_count += 1
                result.append(entry)
                continue

            represented_keys.add(
                (
                    str(candidate["experiment_id"] or ""),
                    str(candidate["model_id"] or ""),
                )
            )
            mismatch = self._metadata_mismatch(
                entry,
                candidate,
            )
            if mismatch:
                self._mark(
                    entry,
                    EVIDENCE_MISMATCH,
                    mismatch,
                    registry_status=str(
                        candidate["experiment_status"] or ""
                    ),
                )
                mismatch_count += 1
                result.append(entry)
                continue

            self._hydrate_from_bundle(entry, candidate)
            status, note = self._classify_bundle(candidate)
            self._mark(
                entry,
                status,
                note,
                registry_status=str(
                    candidate["experiment_status"] or ""
                ),
            )
            registered_count += 1
            result.append(entry)

        recovered = 0
        for row in bundles:
            key = (
                str(row["experiment_id"] or ""),
                str(row["model_id"] or ""),
            )
            if key in represented_keys:
                continue
            recovered_entry = self._entry_from_bundle(row)
            if recovered_entry is None:
                continue
            status, note = self._classify_bundle(row)
            self._mark(
                recovered_entry,
                status,
                note,
                registry_status=str(
                    row["experiment_status"] or ""
                ),
            )
            result.append(recovered_entry)
            represented_keys.add(key)
            registered_count += 1
            recovered += 1

        return RankingRegistryReconciliation(
            entries=tuple(result),
            legacy_entries=legacy_count,
            registered_entries=registered_count,
            recovered_entries=recovered,
            mismatched_entries=mismatch_count,
            orphaned_entries=orphan_count,
        )

    @staticmethod
    def _find_bundle_for_entry(
        entry: ModelRankingEntry,
        rows: Sequence[Any],
    ):
        model_id = str(
            getattr(entry, "model_id", "") or ""
        ).strip()
        sha = str(
            getattr(entry, "model_sha256", "") or ""
        ).strip().lower()

        if model_id:
            for row in rows:
                if str(row["model_id"] or "") == model_id:
                    return row

        if sha:
            matches = [
                row
                for row in rows
                if str(
                    row["model_sha256"] or ""
                ).strip().lower()
                == sha
            ]
            if len(matches) == 1:
                return matches[0]

        if not model_id and not sha and len(rows) == 1:
            return rows[0]
        return None

    @staticmethod
    def _metadata_mismatch(
        entry: ModelRankingEntry,
        row,
    ) -> str:
        comparisons = (
            (
                "model_id",
                str(getattr(entry, "model_id", "") or "").strip(),
                str(row["model_id"] or "").strip(),
            ),
            (
                "model_sha256",
                str(
                    getattr(entry, "model_sha256", "") or ""
                ).strip().lower(),
                str(row["model_sha256"] or "").strip().lower(),
            ),
            (
                "protocol_sha256",
                str(
                    getattr(entry, "protocol_sha256", "") or ""
                ).strip().lower(),
                str(row["protocol_sha256"] or "").strip().lower(),
            ),
            (
                "track_id",
                str(getattr(entry, "track_id", "") or "").strip(),
                str(row["track_id"] or "").strip(),
            ),
            (
                "track_manifest_sha256",
                str(
                    getattr(
                        entry,
                        "track_manifest_sha256",
                        "",
                    )
                    or ""
                ).strip().lower(),
                str(
                    row["track_manifest_sha256"] or ""
                ).strip().lower(),
            ),
        )
        for field, stored, frozen in comparisons:
            if stored and frozen and stored != frozen:
                return (
                    f"Wpis JSON i SQLite różnią się w polu {field}; "
                    "wynik nie może być traktowany jako wiarygodnie "
                    "powiązany z eksperymentem."
                )
        return ""

    @staticmethod
    def _hydrate_from_bundle(
        entry: ModelRankingEntry,
        row,
    ) -> None:
        values = {
            "experiment_id": str(
                row["experiment_id"] or ""
            ),
            "experiment_mode": str(
                row["experiment_mode"] or ""
            ),
            "model_id": str(row["model_id"] or ""),
            "model_sha256": str(
                row["model_sha256"] or ""
            ).lower(),
            "track_id": str(row["track_id"] or ""),
            "protocol_sha256": str(
                row["protocol_sha256"] or ""
            ).lower(),
            "track_manifest_sha256": str(
                row["track_manifest_sha256"] or ""
            ).lower(),
            "independence_status": str(
                row["independence_status"] or ""
            ).upper(),
        }
        for field, value in values.items():
            if not str(
                getattr(entry, field, "") or ""
            ).strip():
                setattr(entry, field, value)

    def _entry_from_bundle(
        self,
        row,
    ) -> ModelRankingEntry | None:
        payload = self._ranking_payload(row)
        if payload is None:
            return None

        try:
            entry = ModelRankingEntry.from_dict(payload)
        except Exception:
            return None

        if not str(entry.date_evaluated or "").strip():
            entry.date_evaluated = str(
                row["result_created_at"] or ""
            ).strip()
        self._hydrate_from_bundle(entry, row)
        return entry

    @staticmethod
    def _ranking_payload(row) -> dict[str, Any] | None:
        raw = str(row["metrics_json"] or "").strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except Exception:
            return None
        if not isinstance(payload, Mapping):
            return None
        if str(payload.get("schema") or "") != RANKING_RESULT_SCHEMA:
            return None
        ranking_entry = payload.get("ranking_entry")
        if not isinstance(ranking_entry, Mapping):
            return None
        return dict(ranking_entry)

    def _classify_bundle(
        self,
        row,
    ) -> tuple[str, str]:
        status = str(
            row["experiment_status"] or ""
        ).strip().upper()
        mode = str(
            row["experiment_mode"] or ""
        ).strip().lower()
        independence = str(
            row["independence_status"] or ""
        ).strip().upper()

        if status != "COMPLETED":
            return (
                EVIDENCE_REGISTERED_INCOMPLETE,
                (
                    "Wynik jest zapisany w SQLite, ale eksperyment "
                    f"ma status {status or 'UNKNOWN'} zamiast COMPLETED."
                ),
            )

        if mode == "controlled":
            if independence != "PASS":
                return (
                    EVIDENCE_MISMATCH,
                    (
                        "Eksperyment controlled jest COMPLETED, ale "
                        f"uczestnik ma independence={independence or 'UNKNOWN'}."
                    ),
                )
            protocol = self._protocol(row)
            if self._has_final_controlled_gt_contract(protocol):
                return (
                    EVIDENCE_CONTROLLED,
                    (
                        "Wynik pochodzi z zakończonego eksperymentu "
                        "controlled, ma zamrożony protokół, PASS "
                        "niezależności i ręczne potwierdzenie kompletności GT."
                    ),
                )
            return (
                EVIDENCE_CONTROLLED_LEGACY,
                (
                    "Wynik pochodzi z zarejestrowanego eksperymentu "
                    "controlled utworzonego przed końcowym kontraktem "
                    "ręcznego potwierdzenia kompletności GT. Zachowujemy "
                    "go historycznie, ale nie traktujemy jako finalnego "
                    "dowodu controlled."
                ),
            )

        if mode == "working":
            return (
                EVIDENCE_WORKING,
                (
                    "Wynik pochodzi z zakończonego eksperymentu working; "
                    "może służyć do analiz roboczych, nie do wniosku "
                    "controlled."
                ),
            )

        return (
            EVIDENCE_REGISTERED_INCOMPLETE,
            (
                f"Rejestr zawiera nieobsługiwany tryb eksperymentu: "
                f"{mode or 'UNKNOWN'}."
            ),
        )

    @staticmethod
    def _protocol(row) -> dict[str, Any]:
        try:
            payload = json.loads(
                str(row["protocol_json"] or "")
            )
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _has_final_controlled_gt_contract(
        protocol: Mapping[str, Any],
    ) -> bool:
        options = (
            protocol.get("options")
            if isinstance(protocol.get("options"), Mapping)
            else {}
        )
        track = (
            protocol.get("track")
            if isinstance(protocol.get("track"), Mapping)
            else {}
        )
        return bool(
            options.get("require_manual_gt_complete")
            and track.get("manual_gt_complete")
            and str(
                track.get(
                    "manual_gt_attestation_schema"
                )
                or ""
            ).strip()
            == "alpr.gt_completeness_attestation.v1"
            and str(
                track.get(
                    "manual_gt_attestation_statement"
                )
                or ""
            ).strip()
            and str(
                track.get("manual_gt_attested_at")
                or ""
            ).strip()
        )

    @staticmethod
    def _mark(
        entry: ModelRankingEntry,
        status: str,
        note: str,
        *,
        registry_status: str,
    ) -> None:
        entry.evidence_status = str(status or "").strip()
        entry.evidence_note = str(note or "").strip()
        entry.registry_experiment_status = str(
            registry_status or ""
        ).strip().upper()
