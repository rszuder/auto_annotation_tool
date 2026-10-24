"""Read-only bridge from the AKT89E export gate to the main results panel."""
from dataclasses import asdict, replace
from pathlib import Path

from .mobile_compare_review_gate import imported_verification, inspect_canvas, _live_review_state


def results_root_for_source(source):
    for parent in Path(str(source or "")).parents:
        if parent.name.lower() == "02_sesje":
            candidate = parent.parent / "03_wyniki"
            return candidate if candidate.is_dir() else None
    return None


def export_stamp(results_root, session_id):
    if results_root is None:
        return ()
    try:
        return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size)
                     for p in sorted((Path(results_root) / session_id).glob("*/export_manifest.json")))
    except OSError as error:
        return (type(error).__name__, str(error))


def selected_canvas_export(session_id, source_sha, results_root, review_root):
    """Same revision selection and fail-closed rules as the import checkboxes."""
    from .mobile_comparison_core import load_session_export
    gate = imported_verification(session_id, source_sha, results_root, review_root)
    if not gate.ready:
        return gate, None
    # Retain manifest verification when fetching the selected payload. Never
    # read a guessed export, or render a previous READY after a concurrent edit.
    try:
        item = load_session_export(gate.export_dir, verify=True)
    except (OSError, ValueError, TypeError, KeyError) as error:
        return replace(gate, state="UNREADABLE" if isinstance(error, OSError) else "INVALID",
                       label="Brak odczytu" if isinstance(error, OSError) else "Wymaga kontroli",
                       reason=str(error)), None
    live = _live_review_state(review_root, source_sha, session_id)
    canvas_sid = (item.canvas or {}).get("session_id", session_id)
    if (item.session_id != session_id or item.source_sha256 != source_sha or
            item.review_revision != gate.revision or canvas_sid != session_id or
            not item.canvas_ready or live not in (None, (item.review_revision, "COMPLETED"))):
        return replace(gate, state="STALE", label="Eksport nieaktualny",
                       reason="Tożsamość lub rewizja zmieniła się podczas odczytu."), None
    return gate, item


def load_canvas_snapshot(session_id, source_sha, results_root, review_root):
    gate, item = selected_canvas_export(session_id, source_sha, results_root, review_root)
    result = dict(verification=asdict(gate), session_id=session_id, source_sha256=source_sha,
                  summary=None, identity=None)
    if item is not None:
        result.update(summary=item.canvas, identity=item.model_identity,
                      manifest_sha256=item.manifest_sha256, review_revision=item.review_revision)
    return result


def canvas_overview(snapshot, *, session_id="", source_sha="", progress=None, loading=False):
    snapshot = snapshot or {}
    gate = snapshot.get("verification") or {}
    state = gate.get("state", "NONE")
    c = snapshot.get("summary") or {}
    bound = (state == "READY" and snapshot.get("session_id") == session_id
             and snapshot.get("source_sha256") == source_sha
             and c.get("source_archive_sha256") == source_sha
             and c.get("review_revision") == gate.get("revision")
             and c.get("session_id", session_id) == session_id
             and inspect_canvas(c, "COMPLETED")[0])
    titles = ("MT — wykrycie tablic", "MT — dopasowanie obrysu",
              "MZ — pełne zgodne odczyty", "MZ — błędy znaków")
    cards = [dict(title=t, value="—", note="Brak zatwierdzonej oceny Canvas.") for t in titles]
    status = {"READY":"WYMAGA KONTROLI", "NONE":"BRAK · Do weryfikacji",
        "IN_PROGRESS":"W TOKU", "STALE":"EKSPORT NIEAKTUALNY", "NEEDS_EXPORT":"EKSPORT NIEAKTUALNY",
        "UNREADABLE":"BRAK ODCZYTU", "INVALID":"WYMAGA KONTROLI", "INCOMPLETE":"W TOKU"}.get(state, "BRAK")
    counter, detail, ratio = "Postęp Canvas: brak potwierdzonych danych", gate.get("reason", ""), None
    p = progress or {}
    if p.get("session_id") == session_id and p.get("source_sha256") == source_sha:
        counter = f"Sprawdzone obrazy: {p['inspected']}/{p['total']} · pozostało: {p['remaining']}"
        ratio = p['inspected']/p['total'] if p['total'] else None
    def pct(value):
        return f"{value:.2f}%".replace(".", ",") if isinstance(value, (int, float)) else "—"
    if bound:
        status = "ZATWIERDZONA"
        counter = f"Sprawdzone obrazy: {c['checked_scenes']}/{c['scene_count']} · rewizja {gate['revision']}"
        ratio = (c['checked_scenes'] + c['excluded_scenes'])/c['scene_count']
        detail = f"Ocena asystowana · poza oceną: {c['excluded_scenes']} · SHA {source_sha[:12]}…"
        cards[0].update(value=f"{c['linked_plates']}/{c['expected_plates']}",
                        note=f"Powiązane detekcje / tablice referencyjne · FN: {c['missed_plates']} · FP: {c['false_positive_mt']}")
        cards[1].update(value=f"IoU {pct(c.get('polygon_iou_mean_pct'))}",
                        note=f"NMCE {pct(c.get('nmce_mean_pct'))} · n={c['geometry_n']} par obrysów. FN poza geometrią.")
        cards[2].update(value=f"{c['exact_reads']}/{c['evaluated_reads']}",
                        note="Pełne zgodne numery / ocenione odczyty MZ. MZ NOT_RUN poza mianownikiem.")
        chars, errors = c['gt_characters'], c['text_errors']
        cards[3].update(value=pct(errors/chars*100) if chars else "Nie oceniano",
                        note=f"Micro-CER: {errors}/{chars} · błędy edycji / znaki GT.")
    elif loading:
        status = "Wczytywanie oceny Canvas…"
    return dict(status=status, cards=cards, progress=counter, progress_subtitle=detail,
                progress_ratio=ratio, ready=bound,
                methodology="Canvas ASSISTED: ocena z widoczną predykcją. E2E Exact Match: nie oceniano osobno.")
