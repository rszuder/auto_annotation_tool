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


def resolve_comparison(service, track_id):
    from ..registry import EvaluationTrackError
    from ..registry.participant_pool_audit import ParticipantPoolAuditService

    track = service.get_track(track_id)
    if track["status"] != "SEALED":
        raise EvaluationTrackError("Najpierw zapieczętuj eksperyment.")
    integrity = service.verify_integrity(track_id)
    if not integrity.ok:
        raise EvaluationTrackError("Naruszona pieczęć toru: " + "; ".join(integrity.issues))
    participants = ParticipantPoolAuditService(
        service.workspace, repository=service.repository
    ).load_participants(track_id)
    if not participants:
        raise EvaluationTrackError("Tor nie zawiera zamrożonych uczestników porównania.")
    model_paths = []
    for participant in participants:
        found = None
        for row in service.repository.list_model_locations(participant.model_id):
            row = dict(row)
            candidates = []
            if row.get("relative_path"):
                candidates.append(service.workspace / row["relative_path"])
            if row.get("external_path"):
                candidates.append(Path(row["external_path"]))
            for path in candidates:
                if path.is_file() and service._sha256(path) == participant.sha256:
                    found = path
                    break
            if found is not None:
                break
        if found is None:
            raise EvaluationTrackError(
                f"Nie znaleziono checkpointu zgodnego z pieczęcią: {participant.model_id}."
            )
        model_paths.append(str(found))
    return {
        "track_id": track_id, "name": track["name"], "target": track["target"],
        "reference_path": str(service.workspace / track["relative_path"]),
        "model_paths": model_paths,
        "model_ids": [item.model_id for item in participants],
    }


def open_comparison(panel):
    from . import z4_analysis_ranking

    track_id = panel._require_current_track()
    if not track_id:
        return
    try:
        if getattr(panel.host, "rank_is_running", False):
            raise RuntimeError("Poczekaj na zakończenie bieżącego porównania.")
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
