"""Przekazanie zapieczętowanego toru i jego uczestników do istniejącego rankingu."""
from pathlib import Path


def comparison_context(host):
    context = getattr(host, "_pz3_comparison_context", None)
    # Aktywny eksperyment nie znika po zmianie pola ścieżki.
    # Niezgodność jest błędem sprawdzanym przed uruchomieniem.
    return context if isinstance(context, dict) and context else None


def clear_pz3_comparison_context(host) -> None:
    """Jawny powrót do zwykłego rankingu; pieczęć i wyniki pozostają zapisane."""
    from ..registry import EvaluationTrackError

    if comparison_context(host) is None:
        return
    if getattr(host, "rank_is_running", False) or getattr(host, "rank_cancel_requested", False) is True:
        raise EvaluationTrackError(
            "Nie można wyjść podczas porównania. Poczekaj na jego zakończenie "
            "lub na zakończenie anulowania."
        )
    host._pz3_comparison_context = None
    # Nowy wybór toru zapobiega przypadkowemu ponowieniu starego eksperymentu.
    host.rank_data_dir.set("")
    host._refresh_ranking_reference_ui()
    host._refresh_ranking_start_state()
    host._load_ranking()


def validate_comparison_context(host, *, model_paths=None):
    """Odrzuć zmianę toru lub uczestników, także po ominięciu selektorów GUI."""
    from ..registry import EvaluationTrackError

    context = comparison_context(host)
    if context is None:
        return None
    variable = getattr(host, "rank_data_dir", None)
    selected = str(variable.get() or "").strip() if variable is not None else ""
    reference = str(context.get("reference_path") or "").strip()
    expected_models = context.get("model_paths")
    if not context.get("track_id") or not reference or not expected_models:
        raise EvaluationTrackError("Niekompletny kontekst eksperymentu PZ3. Otwórz porównanie ponownie z toru.")
    if not selected or Path(selected).resolve() != Path(reference).resolve():
        raise EvaluationTrackError(
            "Naruszony kontekst eksperymentu: zmieniono zapieczętowany tor. "
            f"Porównanie wymaga toru {context['track_id']}: {reference}."
        )
    if not isinstance(expected_models, (list, tuple)) or any(
        not isinstance(path, (str, Path)) or not str(path).strip() for path in expected_models
    ):
        raise EvaluationTrackError("Nieprawidłowa lista modeli w kontekście eksperymentu PZ3.")
    if model_paths is not None:
        expected = [Path(path).resolve() for path in expected_models]
        actual = [Path(path).resolve() for path in model_paths]
        if len(actual) != len(expected) or len(set(actual)) != len(actual) or set(actual) != set(expected):
            raise EvaluationTrackError(
                "Naruszony kontekst eksperymentu: lista modeli różni się od zamrożonych uczestników."
            )
    return context


def _resolve_model_paths(service, model_ids):
    from ..registry import EvaluationTrackError

    model_paths = []
    for model_id in model_ids:
        model = service.repository.get_model(str(model_id))
        if model is None:
            raise EvaluationTrackError(f"Nie znaleziono modelu: {model_id}")
        expected_sha = str(model["sha256"] or "").strip().lower()
        found = None
        for row in service.repository.list_model_locations(str(model_id)):
            row = dict(row)
            candidates = []
            if row.get("relative_path"):
                candidates.append(service.workspace / row["relative_path"])
            if row.get("external_path"):
                candidates.append(Path(row["external_path"]))
            for path in candidates:
                if path.is_file() and service._sha256(path) == expected_sha:
                    found = path
                    break
            if found is not None:
                break
        if found is None:
            raise EvaluationTrackError(
                f"Nie znaleziono checkpointu zgodnego z rejestrem: {model_id}."
            )
        model_paths.append(str(found))
    return model_paths


def resolve_benchmark_reuse(
    service,
    benchmark_id_or_track_id,
    *,
    model_ids,
    selected_sha256=None,
    label_ids=None,
    include_unlabeled=False,
):
    """Jawne ponowne użycie GT/benchmarku z nowymi uczestnikami."""
    from ..registry import EvaluationTrackError
    from ..registry.evaluation_benchmark import (
        ensure_benchmark_for_track,
        load_benchmark,
        materialize_benchmark_subset,
        verify_benchmark,
    )

    raw = str(benchmark_id_or_track_id or "").strip()
    if raw.startswith("BENCH-") or Path(raw).is_file():
        benchmark = load_benchmark(service.workspace, raw)
    else:
        benchmark = ensure_benchmark_for_track(service, raw)
    benchmark = verify_benchmark(service, benchmark)

    clean_models = list(dict.fromkeys(
        str(value or "").strip()
        for value in model_ids
        if str(value or "").strip()
    ))
    if len(clean_models) < 2:
        raise EvaluationTrackError(
            "Ponowne użycie benchmarku wymaga co najmniej dwóch modeli."
        )

    subset = materialize_benchmark_subset(
        service,
        benchmark,
        selected_sha256=selected_sha256,
        label_ids=label_ids,
        include_unlabeled=include_unlabeled,
    )
    model_paths = _resolve_model_paths(service, clean_models)
    return {
        "track_id": str(benchmark["source_track_id"]),
        "name": f"{benchmark.get('name') or benchmark['benchmark_id']} · reuse",
        "target": benchmark["target"],
        "reference_path": subset["reference_path"],
        "model_paths": model_paths,
        "model_ids": clean_models,
        "benchmark": benchmark,
        "benchmark_id": benchmark["benchmark_id"],
        "benchmark_fingerprint": benchmark["fingerprint"],
        "benchmark_subset_fingerprint": subset["subset_fingerprint"],
        "benchmark_selected_sha256": subset["selected_sha256"],
        "benchmark_source_track_id": str(benchmark["source_track_id"]),
        "benchmark_reuse": True,
    }


def resolve_comparison(service, track_id):
    from ..registry import EvaluationTrackError
    from ..registry.evaluation_benchmark import (
        ensure_benchmark_for_track,
        resolve_benchmark_subset,
    )
    from ..registry.participant_pool_audit import ParticipantPoolAuditService

    track = service.get_track(track_id)
    if track["status"] != "SEALED":
        raise EvaluationTrackError("Najpierw zapieczętuj eksperyment.")
    integrity = service.verify_integrity(track_id)
    if not integrity.ok:
        raise EvaluationTrackError("Naruszona pieczęć toru: " + "; ".join(integrity.issues))

    benchmark = ensure_benchmark_for_track(service, track_id)
    subset = resolve_benchmark_subset(benchmark)

    participants = ParticipantPoolAuditService(
        service.workspace, repository=service.repository
    ).load_participants(track_id)
    if not participants:
        raise EvaluationTrackError("Tor nie zawiera zamrożonych uczestników porównania.")

    model_paths = _resolve_model_paths(
        service,
        [item.model_id for item in participants],
    )
    return {
        "track_id": track_id,
        "name": track["name"],
        "target": track["target"],
        "reference_path": str(service.workspace / track["relative_path"]),
        "model_paths": model_paths,
        "model_ids": [item.model_id for item in participants],
        "benchmark": benchmark,
        "benchmark_id": benchmark["benchmark_id"],
        "benchmark_fingerprint": benchmark["fingerprint"],
        "benchmark_subset_fingerprint": subset["subset_fingerprint"],
        "benchmark_selected_sha256": subset["selected_sha256"],
        "benchmark_source_track_id": track_id,
        "benchmark_reuse": False,
    }



def open_comparison(panel):
    from . import z4_analysis_ranking

    track_id = panel._require_current_track()
    if not track_id:
        return
    try:
        if (
            getattr(panel.host, "rank_is_running", False)
            or getattr(panel.host, "rank_cancel_requested", False) is True
        ):
            raise RuntimeError("Poczekaj na zakończenie bieżącego porównania lub anulowania.")
        context = resolve_comparison(panel.service, track_id)
        host = panel.host
        host._ensure_step4_train_tab_built()
        host._pz3_comparison_context = context
        host.rank_scope_var.set("Globalne")
        host.rank_data_dir.set(context["reference_path"])
        host._ensure_plate_ranking_engine()
        host._refresh_ranking_reference_ui()
        host._refresh_ranking_start_state()
        close = getattr(host, "_ranking_results_modal_close", None)
        if callable(close) and getattr(host, "_ranking_results_modal", None) is not None:
            close()
        z4_analysis_ranking._open_ranking_results_modal(host)
        panel._set_status(
            f"Porównanie: {context['name']} · uczestników: {len(context['model_ids'])}. "
            "Użyj „Uruchom porównanie”."
        )
    except Exception as exc:
        panel._show_error("Nie udało się przygotować porównania", exc)
