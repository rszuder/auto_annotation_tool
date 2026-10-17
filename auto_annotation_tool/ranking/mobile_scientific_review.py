"""Scientific reading layer over verified mobile ALPR review measurements.

No modifications to source sessions, annotations, GT or model outputs. This module
never imputes unavailable measurements or treats MT invocation yield as plate recall.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
from statistics import median

SCIENCE_SCHEMA = "alpr.mobile.scientific_summary.v1"


def _numeric(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _integer(value):
    n = _numeric(value)
    return int(n) if n is not None and n >= 0 and n.is_integer() else None


def _fraction(numerator, denominator):
    n, d = _integer(numerator), _integer(denominator)
    return n / d if n is not None and d else None


def _rate_text(n, d):
    n, d = _integer(n), _integer(d)
    return "nieobliczalne (brak mianownika)" if not d or n is None else f"{n}/{d} ({100*n/d:.2f}%)"


def _mean(values):
    vals = [n for v in values if (n := _numeric(v)) is not None]
    return sum(vals) / len(vals) if vals else None


def _id_row(session, key):
    return session.review.subjects.get(key, {})


def subject_stage(session, subject_key, geometry_rows):
    """Stage-specific *workflow* completeness; never changes native review_status.

    A missed plate can be finished for MT while OCR has not run.  This is not
    equivalent to full, source-verified ALPR ground-truth completion.
    """
    subject = session.subjects.get(subject_key, {})
    ids = [i for i in subject.get("attempts", ()) if i in session.attempts]
    groups = {session.invocation_by_attempt[i] for i in ids if i in session.invocation_by_attempt}
    live = []
    excluded = 0
    for group_id in groups:
        group = session.mt_invocations[group_id]
        if not group.executed or group.cancelled or group.execution_failed:
            excluded += 1
            continue
        decision = session.invocation_annotation(group_id)
        count = decision.get("visible_plate_count")
        if decision.get("evaluable") is False or count == "uncertain":
            excluded += 1
            continue
        if count not in {"none", "one", "multiple"}:
            live.append((group_id, "liczba tablic nieoceniona"))
            continue
        if session.invocation_completion_issues(group_id):
            live.append((group_id, "ocena detekcji nieukończona"))
            continue
        if count == "one":
            for record in group.records:
                rid = record["id"]
                status = str(record.get("mt_status") or "").upper()
                annot = session.review.attempt_annotations.get(rid, {})
                geometry = geometry_rows.get(rid, {})
                geom_status = geometry.get("metric_status")
                if status == "NO_DETECTION":
                    if not (geom_status == "missed_detection_gt_saved" or
                            annot.get("pose_gt_unavailable_reason")):
                        live.append((group_id, "brakuje GT pominiętej tablicy"))
                elif status in {"VALID_QUAD", "DETECTION_INVALID_QUAD"} and annot.get("is_plate") is True:
                    if geom_status in {"missing_manual_gt", "gt_provenance_mismatch",
                                       "invalid_manual_gt", "gt_exclusion_conflict"}:
                        live.append((group_id, "obrys GT wymaga oceny lub poprawy"))
        # "none" and "multiple" are deliberate cardinality decisions.
    active_groups = len(groups) - excluded
    mt_complete = active_groups > 0 and not live
    if not groups or active_groups == 0:
        mt_status = "Poza pomiarem MT"
    elif live:
        mt_status = "MT: do oceny"
    else:
        mt_status = "MT ocenione"

    sample_ids = subject.get("samples", ())
    mz_runs = []
    for sample_id in sample_ids:
        if sample_id not in session.samples:
            continue
        sample = session.samples[sample_id]
        attempt = session.attempts.get(sample.get("attempt_id"), {})
        mz_state = str(attempt.get("mz_status") or sample.get("mz_status") or "").upper()
        if mz_state not in {"", "NOT_RUN", "UNKNOWN"}:
            mz_runs.append(sample)
    gt = _id_row(session, subject_key)
    if not mz_runs:
        mz_status, mz_pending = "MZ nie uruchomiono", False
    elif gt.get("evaluable") is False:
        mz_status, mz_pending = "MZ wyłączone z oceny", False
    elif not str(gt.get("ground_truth") or "").strip() or gt.get("evaluable") is not True:
        mz_status, mz_pending = "MZ: brak numeru GT", True
    else:
        mz_status, mz_pending = "MZ ocenione", False
    if mt_status == "MT ocenione" and mz_status == "MZ nie uruchomiono":
        label = "MT ocenione"
    elif mt_status == "MT ocenione" and mz_status == "MZ ocenione":
        label = "Ocenione MT i MZ"
    elif mt_status == "Poza pomiarem MT":
        label = "Poza pomiarem MT"
    else:
        label = mt_status
    return {"label": label, "mt_status": mt_status, "mt_complete": mt_complete,
            "mt_pending": bool(live), "mt_excluded_groups": excluded,
            "mz_status": mz_status, "mz_pending": mz_pending}


def make_scientific_summary(session, statistics, pose_rows):
    """Grounded ratios only; preserve stage denominators, outcome provenance."""
    summary = statistics["summary"]
    pose_map = {row["attempt_id"]: row for row in pose_rows}
    subjects = {key: subject_stage(session, key, pose_map) for key in session.subjects}
    mt_rows = statistics.get("mt_invocations", ())
    active = [r for r in mt_rows if r.get("executed") and not r.get("cancelled")
              and not r.get("execution_failed")]
    rated = [r for r in active if session.invocation_annotation(r["mt_invocation_id"]).get(
                 "visible_plate_count") in {"none", "one", "multiple", "uncertain"}]
    sample_one = [r for r in rated if r.get("included")]
    n_singles = _integer(summary.get("evaluable_mt_invocations"))
    n_success = _integer(summary.get("mt_successful_invocations"))
    n_missed = _integer(summary.get("mt_no_detection_invocations"))
    pose_measured = [r for r in pose_rows if r.get("metric_status") == "measured"
                     and _numeric(r.get("nmce_pct")) is not None
                     and _numeric(r.get("polygon_iou_pct")) is not None]
    missed_gt = [r for r in pose_rows if r.get("metric_status") == "missed_detection_gt_saved"]
    eligible_pose = [r for r in pose_rows if r.get("eligible")]
    n_reads = _integer(summary.get("evaluable_reads"))
    n_exact = _integer(summary.get("exact_reads"))
    gt_char = _integer(summary.get("gt_characters"))
    errors = sum(_integer(summary.get(name)) or 0 for name in
                 ("incorrect_characters", "missing_characters", "extra_characters"))
    n_alpr = _integer(summary.get("evaluable_subjects"))
    n_alpr_exact = _integer(summary.get("subjects_with_exact_read"))
    done_mt = sum(1 for s in subjects.values() if s["mt_complete"])
    mz_not_run = sum(1 for s in subjects.values() if s["mz_status"] == "MZ nie uruchomiono")
    full = str(session.review.review_status).upper() == "COMPLETED"
    complete_sample = bool(active) and all(s["mt_complete"] or s["mt_status"] == "Poza pomiarem MT"
                                       for s in subjects.values())
    complete_for_mt = done_mt > 0 and complete_sample and len(rated) == len(active)
    mode = str(session.review.review_mode)
    caveats = []
    if len(rated) < len(active):
        caveats.append(f"Niezweryfikowane wywołania MT: {len(active)-len(rated)} z {len(active)} aktywnych.")
    if any(not s["mt_complete"] and s["mt_status"] != "Poza pomiarem MT" for s in subjects.values()):
        caveats.append("Część GT i decyzji MT/Pose pozostaje nieukończona.")
    if mode == "assisted":
        caveats.append("Ocena asystowana: operator widział predykcje; nie jest to ślepa anotacja GT.")
    if n_singles is not None and n_singles < 30:
        caveats.append("Mała liczba ocenionych wywołań z jedną tablicą: wynik MT jest opisowy, bez uogólnienia.")
    if n_singles is None or not n_singles:
        caveats.append("Brak mianownika dla skuteczności lokalizacji MT.")
    if len(pose_measured) == 0:
        caveats.append("Nie ma sparowanych predykcji Pose z ręcznym GT: IoU i NMCE nieobliczalne.")
    if not n_reads:
        caveats.append("Brak ocenionych odczytów MZ: nie podawaj Exact/CER jako 0%.")
    if n_alpr is None or not n_alpr:
        caveats.append("Brak pełnych par wynik ALPR–numer GT: nie obliczaj skuteczności całego ALPR.")
    if mz_not_run:
        caveats.append(f"W {mz_not_run} obserwacjach MZ nie został uruchomiony; nie jest to błąd OCR.")
    if not full:
        caveats.append("Weryfikacja pełnej sesji trwa; wszystkie agregaty traktuj jako wstępne.")
    payload = getattr(session.bundle, "report_payload", {}) or {}
    if not isinstance(payload, dict):
        payload = {}
    latency = payload.get("latency") or {}
    if not isinstance(latency, dict):
        latency = {}
    native_latency = {}
    for key in ("mt", "mz", "pipeline"):
        block = latency.get(key) or {}
        if not isinstance(block, dict):
            block = {}
        count = _integer(block.get("count"))
        native_latency[key] = {
            "n": count,
            "p50_ms": _numeric(block.get("median_ms", block.get("p50_ms"))) if count else None,
            "p95_ms": _numeric(block.get("p95_ms")) if count else None,
        }
    frame_flow = payload.get("frame_flow") or {}
    if not isinstance(frame_flow, dict):
        frame_flow = {}
    frames = {"received": _integer(frame_flow.get("frames_received")),
              "processed": _integer(frame_flow.get("frames_processed")),
              "skipped_frame_gate": _integer(frame_flow.get("frames_skipped_frame_gate",
                                                        frame_flow.get("frames_skipped_gate"))),
              "estimated_upstream_gaps": _integer(frame_flow.get("estimated_upstream_gaps"))}
    build_info = (session.bundle.experiment_session or {}).get("app_build") or {}
    if build_info.get("git_dirty") is True:
        caveats.append("APK zbudowano z lokalnymi zmianami (git_dirty=true); zachowaj kod/diff dla odtwarzalności.")
    return {
        "schema": SCIENCE_SCHEMA,
        "session_id": session.session_id,
        "source_archive_sha256": session.review.source_archive_sha256,
        "review_revision": session.review.review_revision,
        "review_status": session.review.review_status,
        "review_mode": mode,
        "conditions": session_conditions(session),
        "scientific_state": "FINAL_FULL_REVIEW" if full and complete_for_mt else
                            "MT_STAGE_COMPLETE_REVIEW_OPEN" if complete_for_mt else "PRELIMINARY",
        "subjects": subjects,
        "progress": {"subjects_total": len(session.subjects), "subjects_mt_done": done_mt,
                     "mt_executed_active": len(active), "mt_invocations_cardinality_reviewed": len(rated),
                     "mz_not_run_subjects": mz_not_run},
        "mt": {"unit": "jedno wykonane wywołanie MT z dokładnie jedną tablicą GT",
               "single_plate_n": n_singles, "localized_n": n_success,
               "failed_localization_n": (n_singles - n_success if n_singles is not None
                                         and n_success is not None and 0 <= n_success <= n_singles else None),
               "no_detection_n": n_missed, "success_rate": _fraction(n_success, n_singles),
               "false_detections_confirmed": _integer(summary.get("mt_false_detections")),
               "multi_plate_invocations_excluded": _integer(summary.get("mt_multi_plate_invocations")),
               "execution_error_invocations": _integer(summary.get("mt_execution_error_invocations"))},
        "pose": {"unit": "sparowana detekcja MT z ręcznym GT na tym samym wejściu MT",
                 "eligible_n": len(eligible_pose), "measured_n": len(pose_measured),
                 "gt_missed_plate_n": len(missed_gt),
                 "polygon_iou_mean_pct": _mean(r["polygon_iou_pct"] for r in pose_measured),
                 "nmce_mean_pct": _mean(r["nmce_pct"] for r in pose_measured),
                 "polygon_iou_median_pct": median(float(r["polygon_iou_pct"]) for r in pose_measured) if pose_measured else None,
                 "nmce_median_pct": median(float(r["nmce_pct"]) for r in pose_measured) if pose_measured else None},
        "mz": {"unit": "oceniony crop z numerem GT i uruchomionym MZ",
               "evaluable_reads": n_reads, "exact_n": n_exact,
               "exact_rate": _fraction(n_exact, n_reads),
               "gt_characters": gt_char, "error_characters": errors,
               "cer": _fraction(errors, gt_char)},
        "alpr": {"unit": "kwalifikująca się obserwacja z potwierdzonym numerem GT",
                 "evaluable_subjects": n_alpr, "exact_n": n_alpr_exact,
                 "exact_rate": _fraction(n_alpr_exact, n_alpr)},
        "performance": {"median_time_to_first_exact_ms": _numeric(summary.get("median_time_to_first_exact_ms")),
                        "p90_time_to_first_exact_ms": _numeric(summary.get("p90_time_to_first_exact_ms")),
                        "latency": native_latency, "frame_flow": frames,
                        "note": "Latency MT/MZ/pipeline to natywne miary czasu z telefonu. Czas do trafnego odczytu to osobna miara. Pipeline ≠ kamera→ekran."},
        "caveats": caveats,
        "methods": [
            "Lokalizacja MT = poprawne wywołania / ocenione wywołania z dokładnie 1 tablicą; nie jest to pełny recall tablic ani precision.",
            "Nieudane lokalizacje to mianownik 1-tablicowych wywołań minus prawidłowo zlokalizowane; samo NO_DETECTION jest węższą kategorią.",
            "Fałszywe detekcje MT: tylko jawnie odrzucone przez operatora; bez kompletnego mianownika nie podajemy precision.",
            "Pose IoU = pole przecięcia polygonów / pole ich sumy; średnia po sparowanych GT.",
            "NMCE = średnia odległość odpowiadających rogów / przekątna obwiedni GT × 100%; niżej = lepiej.",
            "Pominięta przez MT tablica z własnym GT należy do oceny wykrywania, nigdy do mianownika IoU/NMCE.",
            "Exact = identyczny odczyt i numer GT po regule normalizacji zapisanej w review; CER = S+D+I / znaki GT.",
            "MZ NOT_RUN nie jest mylone z błędnym odczytem ani z wartością CER=0.",
            "Wszystkie liczebności i mianowniki są z zatwierdzonego indeksu sesji i bieżącego sidecara; jednostka wywołanie ≠ klatka ≠ crop ≠ obserwacja.",
            "Powtarzające się klatki jednej sceny nie są niezależnymi próbkami; wywołań nie należy mylić z liczbą scen.",
            "MT lokalizacja: decyzja operatora i status VALID_QUAD, nie próg Polygon IoU; raport Pose podaje geometrię osobno.",
            "Wynik ALPR na obserwację może uwzględniać zgromadzony konsensus; odczyt pojedynczego cropa jest odrębnie rozliczany.",
            "Status etapu MT nie zmienia natywnego review_status ani warunków pełnego zakończenia sesji.",
        ],
    }


def session_conditions(session):
    """Short user-facing configuration; retain full raw provenance separately."""
    bundle = session.bundle
    experiment = (bundle.experiment_session or {}) if isinstance(bundle.experiment_session, dict) else {}
    execution = experiment.get("execution") or {}
    stages = execution.get("stages") or {}
    refs = bundle.model_refs or {}
    device = getattr(bundle.report, "device", {}) or {}
    if not isinstance(device, dict):
        device = {"name": str(device)}
    model = {}
    for key, role in (("MT", "plate"), ("MZ", "character")):
        info = refs.get(role) or {}
        stage = stages.get("mt" if role == "plate" else "mz") or {}
        model[key] = {
            "name": info.get("model_display_id") or info.get("model_id") or "brak danych",
            "variant": info.get("variant_id") or stage.get("variant_id") or "brak danych",
            "precision": info.get("precision") or stage.get("precision") or "brak danych",
            "runtime": info.get("runtime") or stage.get("runtime") or "brak danych",
            "delegate": stage.get("delegate") or "brak danych",
            "model_sha256": info.get("package_sha256") or "brak danych",
        }
    return {
        "session_id": session.session_id,
        "scenario": experiment.get("scenario_id") or "brak danych",
        "variant": experiment.get("variant") or "brak danych",
        "device": device.get("name") or device.get("model") or "brak danych",
        "android": device.get("android_version") or "brak danych",
        "build": (experiment.get("app_build") or {}).get("build_type") or "brak danych",
        "models": model,
        "source_archive_sha256": session.review.source_archive_sha256,
        "review_revision": session.review.review_revision,
        "review_mode": session.review.review_mode,
    }


def session_conditions_text(info):
    return (f"Scenariusz: {info['scenario']}  •  Wariant: {info['variant']}\n"
            f"Telefon: {info['device']}  •  Android: {info['android']}  •  APK: {info['build']}\n"
            f"MT: {info['models']['MT']['name']}  •  {info['models']['MT']['precision']}  •  {info['models']['MT']['delegate']}\n"
            f"MZ: {info['models']['MZ']['name']}  •  {info['models']['MZ']['precision']}  •  {info['models']['MZ']['delegate']}\n"
            f"Archiwum SHA-256: {info['source_archive_sha256']}\n"
            f"Weryfikacja: rewizja {info['review_revision']}; tryb {info['review_mode']}\n"
            "Pełne SHA modeli, ścieżki, historia treningu i pola techniczne znajdują się poniżej.")


def display_scientific_summary(report):
    """Short, human-readable paragraphs for a scrollable GUI read-only panel."""
    pr, mt, pose, mz, alpr = (report[k] for k in ("progress", "mt", "pose", "mz", "alpr"))
    mode = "asystowana (predykcje widoczne)" if report["review_mode"] == "assisted" else "zaślepiona"
    lines = [
        ("title", "WYNIKI NAUKOWE SESJI"),
        ("warning" if report["scientific_state"] != "FINAL_FULL_REVIEW" else "subtitle",
         "RAPORT WSTĘPNY • nie cytuj jako wyniku końcowego" if report["scientific_state"] != "FINAL_FULL_REVIEW"
         else "Pełna weryfikacja zakończona"),
        ("caption", f"Wywołania MT ocenione co do liczby tablic: {pr['mt_invocations_cardinality_reviewed']}/{pr['mt_executed_active']}  •  "
         f"obserwacje z ukończoną oceną MT: {pr['subjects_mt_done']}/{pr['subjects_total']}  •  ocena {mode}"),
        ("heading", "1   Wykrywanie tablic — MT"),
        ("metric", f"Trafienia MT potwierdzone przez operatora: {_rate_text(mt['localized_n'], mt['single_plate_n'])}"),
        ("normal", f"Nieudane lokalizacje: {mt['failed_localization_n'] if mt['failed_localization_n'] is not None else '—'}  •  "
         f"bez jakiejkolwiek detekcji: {mt['no_detection_n'] if mt['no_detection_n'] is not None else '—'}"),
        ("normal", f"Fałszywe wskazania potwierdzone: {mt['false_detections_confirmed'] if mt['false_detections_confirmed'] is not None else '—'}"),
        ("caption", "Jednostka: wykonane wywołanie MT z jedną widoczną tablicą. To nie jest pełne recall/precision."),
        ("heading", "2   Położenie narożników — Pose"),
        ("metric", f"Polygon IoU średnio: {pose['polygon_iou_mean_pct']:.2f}%" if pose['polygon_iou_mean_pct'] is not None
         else "Polygon IoU: — (brak porównywalnych par)"),
        ("metric", f"NMCE średnio: {pose['nmce_mean_pct']:.2f}%" if pose['nmce_mean_pct'] is not None
         else "NMCE: — (brak porównywalnych par)"),
        ("normal", f"Medianowe Polygon IoU: {pose['polygon_iou_median_pct']:.2f}%  •  NMCE: {pose['nmce_median_pct']:.2f}%"
         if pose['measured_n'] else "Medianowe IoU/NMCE: —"),
        ("caption", f"Sparowane predykcje i GT: {pose['measured_n']}  •  "
         f"GT tablic pominiętych przez MT: {pose['gt_missed_plate_n']} (bez IoU/NMCE)."),
        ("heading", "3   Rozpoznawanie znaków — MZ"),
        ("metric", f"Dokładne numery: {_rate_text(mz['exact_n'], mz['evaluable_reads'])}"),
        ("metric", f"CER: {mz['cer']*100:.2f}% ({mz['error_characters']}/{mz['gt_characters']} znaków)"
         if mz['cer'] is not None else "CER: — (brak GT i ocenionego odczytu)"),
        ("caption", "Próby bez uruchomionego MZ nie są błędnymi odczytami."),
        ("heading", "4   Cały proces ALPR"),
        ("metric", f"Poprawnie odczytane tablice GT: {_rate_text(alpr['exact_n'], alpr['evaluable_subjects'])}"),
        ("heading", "5   Wydajność telefonu — pomiary niezależne od GT"),
        ("normal", "  •  ".join(
            (f"{name.upper()}: mediana {report['performance']['latency'][name]['p50_ms']:.1f} ms, "
             f"P95 {report['performance']['latency'][name]['p95_ms']:.1f} ms "
             f"(n={report['performance']['latency'][name]['n']})"
             if report['performance']['latency'][name]['p50_ms'] is not None and
                report['performance']['latency'][name]['p95_ms'] is not None
             else f"{name.upper()}: —") for name in ("mt", "mz", "pipeline"))),
        ("normal", f"Klatki: otrzymano {report['performance']['frame_flow']['received']}  •  "
         f"przetworzono {report['performance']['frame_flow']['processed']}  •  "
         f"pominięto przez frame gate {report['performance']['frame_flow']['skipped_frame_gate']}"
         if report['performance']['frame_flow']['received'] is not None
         else "Przepływ klatek: brak liczników w raporcie sesji"),
        ("normal", f"Mediana do pierwszego trafnego odczytu: {report['performance']['median_time_to_first_exact_ms']:.1f} ms"
         if report["performance"]["median_time_to_first_exact_ms"] is not None else "Czas do pierwszego poprawnego odczytu: —"),
        ("caption", "Pipeline = metryka etapu pipeline w raporcie telefonu, nie całkowity czas kamera→ekran. "
         "P95 wyliczony na próbkach zapisanych przez Androida."),
        ("heading", "OGRANICZENIA I WARUNKI ODCZYTU"),
    ]
    lines.extend(("warning", "• " + v) for v in report["caveats"])
    lines.extend([("caption", "Pełna proweniencja, surowe dowody i eksport metryk pozostają dostępne."),
                  ("caption", "W raporcie do pracy: licznik, mianownik, jednostka, przypadki wyłączone i tryb GT.")])
    return lines


def scientific_markdown(report):
    """Methodological companion; readable as-is and keeps an audit trail."""
    p, mt, pose, mz, alpr = (report[k] for k in ("progress", "mt", "pose", "mz", "alpr"))
    f = lambda n: "—" if n is None else f"{n:.2f}%"
    lines = [
        "# Ocena naukowa sesji ALPR — raport roboczy" if report["scientific_state"] != "FINAL_FULL_REVIEW" else
        "# Ocena naukowa sesji ALPR",
        "", f"- Session ID: `{report['session_id']}`",
        f"- SHA-256 źródłowego archiwum: `{report['source_archive_sha256']}`",
        f"- Rewizja weryfikacji: `{report['review_revision']}`",
        f"- Tryb GT: `{report['review_mode']}` (asystowana ≠ zaślepiona)",
        f"- Status naukowy: `{report['scientific_state']}`; stan pełnej weryfikacji: `{report['review_status']}`",
        f"- Scenariusz: {report['conditions']['scenario']}; wariant: {report['conditions']['variant']}",
        f"- Telefon: {report['conditions']['device']}; Android: {report['conditions']['android']}",
        f"- Model MT: {report['conditions']['models']['MT']['name']} ({report['conditions']['models']['MT']['precision']})",
        f"- Model MZ: {report['conditions']['models']['MZ']['name']} ({report['conditions']['models']['MZ']['precision']})",
        f"- Ocenione wywołania MT: {p['mt_invocations_cardinality_reviewed']}/{p['mt_executed_active']}",
        f"- Obserwacje z zakończoną oceną MT: {p['subjects_mt_done']}/{p['subjects_total']}",
        "", "## Wyniki z jawnymi mianownikami", "",
        "| Moduł | Miara | Wynik | Jednostka i zakres |", "|---|---|---|---|",
        f"| MT | Potwierdzone trafienia modelu | {_rate_text(mt['localized_n'], mt['single_plate_n'])} | Wywołania z jedną tablicą GT |",
        f"| MT | Nieudana lokalizacja | {mt['failed_localization_n']} | Wywołania z 1 tablicą bez poprawnej lokalizacji |",
        f"| MT | Brak jakiejkolwiek detekcji | {mt['no_detection_n']} | Podzbiór nieudanych lokalizacji |",
        f"| MT | Fałszywe detekcje | {mt['false_detections_confirmed']} | Potwierdzone przez operatora, nie pełne FP |",
        f"| Pose | Średnie Polygon IoU | {f(pose['polygon_iou_mean_pct'])} | N={pose['measured_n']} sparowanych GT |",
        f"| Pose | Średni NMCE | {f(pose['nmce_mean_pct'])} | N={pose['measured_n']} sparowanych GT |",
        f"| Pose | Mediana IoU | {f(pose['polygon_iou_median_pct'])} | N={pose['measured_n']} sparowanych GT |",
        f"| Pose | Mediana NMCE | {f(pose['nmce_median_pct'])} | N={pose['measured_n']} sparowanych GT |",
        f"| Pose | Pominięte tablice z GT | {pose['gt_missed_plate_n']} | Bez porównania IoU/NMCE |",
        f"| MZ | Pełny poprawny numer | {_rate_text(mz['exact_n'], mz['evaluable_reads'])} | Ocenione odczyty MZ z GT |",
        f"| MZ | CER | {f(mz['cer']*100 if mz['cer'] is not None else None)} | Znaki GT: {mz['gt_characters']}; błędy S+D+I: {mz['error_characters']} |",
        f"| ALPR | Pełny poprawny odczyt | {_rate_text(alpr['exact_n'], alpr['evaluable_subjects'])} | Kwalifikujące się obserwacje z numerem GT |",
        "", "## Wydajność na urządzeniu (natywny raport telefonu)", "",
        "| Etap | n | Mediana [ms] | P95 [ms] |", "|---|---:|---:|---:|",
    ]
    for key in ("mt", "mz", "pipeline"):
        item = report["performance"]["latency"][key]
        shown = lambda v: f"{v:.2f}" if v is not None else "—"
        lines.append(f"| {key.upper()} | {item['n']} | {shown(item['p50_ms'])} | {shown(item['p95_ms'])} |")
    frames = report["performance"]["frame_flow"]
    lines.extend([
        "", f"- Klatki otrzymane: {frames['received']}; przetworzone: {frames['processed']}; "
            f"odrzucone przez frame gate: {frames['skipped_frame_gate']}.",
        "- Pipeline jest etapem raportowanym przez Androida, nie pomiarem całkowitego czasu kamera→ekran.",
        "", "## Interpretacja i definicje", "",
    ])
    lines.extend(f"- {method}" for method in report["methods"])
    lines.extend(["", "## Ograniczenia i warunki ważności", ""])
    lines.extend(f"- {issue}" for issue in report["caveats"])
    lines.extend(["", "## Zasada analizy", "",
                  "Dokument jest wyłącznie pochodną zapisanych pomiarów i decyzji operatora. "
                  "Nie modyfikuje pliku `.alprsession`, sidecara GT, wartości predykcji ani danych modeli. "
                  "Pełne tabele szczegółowe i proweniencja są dostępne w równoległych plikach eksportu.", ""])
    return "\n".join(lines)


def write_scientific_companion(report, directory):
    """Atomic new companion files, without touching existing native exports."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    generated = []
    session_key = re.sub(r"[^A-Za-z0-9_-]+", "_", str(report["session_id"]))[:60] or "sesja"
    revision = int(report["review_revision"])
    basename = f"ocena_naukowa_{session_key}_rew{revision:04d}"
    for name, content in (
        (basename + ".md", scientific_markdown(report)),
        (basename + ".json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"),
    ):
        path = directory / name
        tmp = directory / (name + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        generated.append(path)
    return generated
