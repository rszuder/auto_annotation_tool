"""Read-only canvas inventory for live status/navigation, separate from metrics.

Unopened eligible frames are included in progress. Metric denominators still
come exclusively from mobile_canvas_review.summary and confirmed/evaluable data.
"""
from __future__ import annotations

from . import mobile_canvas_review as core


def build_inventory(session):
    result = dict(total=0, editable=0, inspected=0, assessed=0, excluded=0,
                  remaining=0, incomplete=0, unavailable=0, groups={})
    if session is None:
        return result
    for gid, group in session.mt_invocations.items():
        if not group.executed or group.cancelled or group.execution_failed:
            continue
        result["total"] += 1
        item = dict(gid=gid, scene=None, status="UNAVAILABLE", cells=("○", "—", "—", "—", "○"),
                    issues=[], persisted=core.has_scene(session, gid),
                    subject_keys=tuple(group.subject_keys))
        try:
            scene = core.scene(session, gid)
        except (ValueError, TypeError, KeyError) as exc:
            item["issues"] = [str(exc)]
            result["unavailable"] += 1
        else:
            result["editable"] += 1
            item["scene"] = scene
            item["cells"] = core.scene_review_cells(scene)
            excluded = scene["checked"] and bool(scene.get("exclusion_reason"))
            issues = [] if excluded else core._content_issues(scene)
            if not scene["checked"]:
                issues.insert(0, "Obraz nie został oznaczony jako sprawdzony")
            item["issues"] = issues
            if scene["checked"]:
                result["inspected"] += 1
            if excluded:
                result["excluded"] += 1
                item["status"] = "EXCLUDED"
            elif not issues:
                result["assessed"] += 1
                item["status"] = "READY"
            elif scene["checked"]:
                result["incomplete"] += 1
                item["status"] = "INCOMPLETE"
            else:
                item["status"] = "PENDING"
        result["groups"][gid] = item
    result["remaining"] = result["total"] - result["inspected"]
    return result


def subject_groups(session, subject_key):
    ids = {session.invocation_by_attempt.get(aid)
           for aid in session.subjects.get(subject_key, {}).get("attempts", ())}
    return [gid for gid in session.mt_invocations if gid in ids]


def percent(value):
    return "—" if value is None else f"{value:.2f}%".replace(".", ",")


def plate_review_state(scene, obj, execution=None):
    """Read-only per-object edit policy and current/audit geometry provenance.

    The editable child is compared to its immutable, identity-bound MT parent.
    A checked image or a historical geometry_state is not proof of correction.
    """
    import math

    result = dict(gt_editable=False, gt_reason="Nie można potwierdzić końcowej detekcji MT tej tablicy.",
                  gt_note="", frame_state="UNKNOWN", frame="Brak ramki / nie można ustalić pochodzenia",
                  canvas_frame="Pochodzenie nieustalone", correction_history="Historia korekty: nieustalona")
    if not scene or not obj:
        return result
    oid = obj.get("object_id")
    if len([o for o in scene.get("objects", ()) if o.get("object_id") == oid]) != 1:
        return result
    parents = [p for p in scene.get("parents", ()) if obj.get("parent_id")
               and p.get("parent_id") == obj["parent_id"]]
    siblings = [o for o in scene.get("objects", ()) if obj.get("parent_id")
                and o.get("parent_id") == obj["parent_id"]]
    parent = (parents[0] if len(parents) == len(siblings) == 1
              and obj.get("attempt_id") == parents[0].get("attempt_id") else None)
    raw = (obj.get("post_nms_suppressed", False) or bool(obj.get("attempt_id")
           and obj["attempt_id"] == scene.get("_post_nms_pending")))
    executed = bool(execution and execution.get("state") == "MT_EXECUTED"
                    and execution.get("mt_invocation_id") == scene.get("mt_invocation_id")
                    and execution.get("image_entry") == scene.get("image_entry"))
    manual = obj.get("parent_id") is None and not obj.get("attempt_id") and obj.get("kind") == "manual"
    result["gt_editable"] = bool(executed and parent and not raw and not obj.get("error"))
    if raw:
        result.update(frame_state="RAW_SUPPRESSED", frame="RAW odrzucony przez NMS · poza końcowymi detekcjami",
                      canvas_frame="RAW · poza oceną", gt_reason="RAW odrzucony przez NMS nie jest końcową detekcją MT.")
    elif manual:
        result["gt_reason"] = ("MT nie wykrył tej tablicy. MZ nie uruchomiono — numer GT nie jest tutaj wymagany "
                               "do oceny. Potwierdź obecność tablicy, aby rozliczyć pominięcie MT."
                               if executed else "Brak zakończonego wywołania i powiązanej detekcji MT. "
                               "Historyczny numer GT pozostaje tylko do odczytu; bez FN modelu MT.")
    elif obj.get("error"):
        result["gt_reason"] = "Ramka oznaczona jako błędna. Cofnij oznaczenie błędu przed edycją GT."
    elif not executed:
        result["gt_reason"] = "Nie potwierdzono zakończonego wywołania MT tej klatki. Numer GT pozostaje tylko do odczytu."
    else:
        result["gt_reason"] = "" if result["gt_editable"] else result["gt_reason"]
    if not result["gt_editable"]:
        result["gt_note"] = ("Zapis historyczny · tylko do odczytu" if obj.get("gt_text") else "Edycja GT niedostępna")

    if not raw:
        try:
            quad = core.validate_mt_quad(obj.get("quad"), *scene["image_size"])
            if manual:
                result.update(frame_state="MANUAL", canvas_frame="Ręczna · brak MT",
                    frame="Ramka referencyjna · dodana ręcznie" + (" (MT nie wykrył tablicy)" if executed else " · brak powiązanej detekcji MT"),
                    correction_history="")
            elif parent and executed:
                original = core.validate_mt_quad(parent.get("quad"), *scene["image_size"])
                same = all(math.isclose(a, b, abs_tol=1e-6, rel_tol=0)
                           for p, q in zip(quad, original) for a, b in zip(p, q))
                result.update(frame_state="MT_ORIGINAL" if same else "MT_CORRECTED",
                    frame="Ramka MT · bez korekty operatora" if same else "Ramka MT · skorygowana przez operatora",
                    canvas_frame="MT · oryginalna" if same else "MT · po korekcie")
                if any(e.get("object_id") == oid and e.get("action") == "correct_child_geometry"
                       for e in scene.get("events", ()) if isinstance(e, dict)):
                    result["correction_history"] = "Historia: zapisano operację korekty" + (" · obecnie oryginał MT" if same else "")
        except (ValueError, TypeError, KeyError, OverflowError):
            pass
    return result


def image_frame_status(scene, execution):
    """Current visible outlines, separate from quality metric denominators."""
    if not scene:
        return "Obrysy: nieustalone (brak zweryfikowanej sceny)"
    counts = dict(MT_ORIGINAL=0, MT_CORRECTED=0, MANUAL=0, UNKNOWN=0)
    for obj in (scene or {}).get("objects", ()):
        state = plate_review_state(scene, obj, execution)["frame_state"]
        if state in counts:
            counts[state] += 1
    titles = dict(MT_ORIGINAL="MT bez korekty", MT_CORRECTED="MT po korekcie", MANUAL="ręczna", UNKNOWN="nieustalone")
    return "Obrysy: " + (" · ".join(f"{n} {titles[k]}" for k, n in counts.items() if n) or "brak")


def execution_state(session, gid, *, image_entry=None, image_size=None):
    """Read execution evidence for this invocation AND source frame, never GT."""
    from .mobile_source_frame_roi import source_invocation_context, source_frame_entry
    from .mobile_mt_postdedup import post_nms_proof

    result = dict(state="MT_UNKNOWN", title="MT: nie potwierdzono wykonania",
                  detail="Ocena MT: nieustalona (bez FN)", detections=None,
                  mt_invocation_id=gid, image_entry=None)
    group = session.mt_invocations.get(gid) if session else None
    if not group or group.mt_invocation_id != gid or group.session_id != session.session_id:
        return result
    ctx = source_invocation_context(group.records, gid, session.entry_names, image_size)
    # Strict NOT_RUN records have no invocation id: their attempt id binds the
    # historical image. Do not manufacture an invocation or borrow a neighbour.
    historical = (not group.executed and group.legacy_identity and bool(group.records)
        and all(str(r.get("id")) == gid and not r.get("mt_invocation_id")
                and str(r.get("mt_status")).upper() == "NOT_RUN"
                and str(r.get("mt_executed")).lower() == "false"
                for r in group.records))
    if ctx:
        if (ctx["source_sequence"] != str(group.source_sequence or "")
                or ctx["source_timestamp_nanos"] != str(group.source_timestamp_nanos or "")):
            return result
        entry = ctx["entry"]
    elif historical:
        entries = {source_frame_entry(r, session.entry_names) for r in group.records}
        if len(entries) != 1 or None in entries:
            return result
        entry = next(iter(entries))
    else:
        return result
    if image_entry is not None and image_entry != entry:
        return result
    result["image_entry"] = entry
    if group.cancelled:
        result.update(state="MT_CANCELLED", title="MT: anulowano",
                      detail="Poza oceną skuteczności MT (nie FN)")
    elif group.execution_failed:
        result.update(state="MT_EXECUTION_FAILED", title="MT: awaria wykonania",
                      detail="Awaria wykonania, poza oceną jakości MT (nie FN)")
    elif not group.executed:
        if not all(str(r.get("mt_status")).upper() == "NOT_RUN" for r in group.records):
            return result
        result.update(state="MT_NOT_RUN", title="MT: nie uruchomiono",
                      detail="Obraz historyczny · poza metrykami MT (nie FN)")
    else:
        # Validate completeness of detections, including invalid source quads.
        if any(str(r.get("mt_status") or "").upper() not in core.DETECTION_STATUSES | {"NO_DETECTION"}
               or str(r.get("mt_executed")).lower() == "false" for r in group.records):
            return result
        try:
            parents = core._parents(session, ctx)
        except (ValueError, TypeError, KeyError):
            return result
        proof = post_nms_proof(session, gid)
        suppressed = int(bool(proof and proof.get("suppressed_id") in
                              {p["attempt_id"] for p in parents}))
        n = len(parents) - suppressed
        result.update(state="MT_EXECUTED", detections=n,
                      title=f"MT: uruchomiono · detekcje: {n}",
                      detail=(f"RAW MT: {len(parents)} · po NMS: {n}" if suppressed else
                              "Zakończone wywołanie tej klatki / ROI"))
    if result["state"] in {"MT_NOT_RUN", "MT_CANCELLED", "MT_EXECUTION_FAILED"}:
        saved = session.invocation_annotation(gid).get(core.KEY, {})
        if (isinstance(saved, dict) and saved.get("source_archive_sha256") == session.review.source_archive_sha256
                and saved.get("mt_invocation_id") == gid and saved.get("image_entry") == entry):
            # Historical GT is evidence only. Never restore this as an editable
            # scene or pass it to any metric when execution is unavailable.
            result["historical_gt"] = [str(o["gt_text"]) for o in saved.get("objects", ())
                if o.get("text_confirmed") and o.get("gt_text") and not o.get("error")
                and not o.get("post_nms_suppressed")]
        statuses = {str(r.get("mz_status") or "").upper() for r in group.records}
        result["mz_not_run"] = statuses == {"NOT_RUN"}
    return result


def focused_assessment(scene, selected_id, execution, *, text_edit_id=None):
    """Resolve read-only focus anew; never turn an automatic preview into selection."""
    objects = (scene or {}).get("objects", ())
    target_id = text_edit_id or selected_id
    selected = [o for o in objects if o["object_id"] == target_id
                and not o.get("post_nms_suppressed")]
    obj = selected[0] if len(selected) == 1 else None
    automatic = False
    if not obj and not target_id and scene and not scene.get("_post_nms_pending"):
        candidates = [o for o in objects if not o.get("post_nms_suppressed") and not o.get("error")]
        if len(candidates) == 1:
            candidate = candidates[0]
            parents = [p for p in scene["parents"] if p["parent_id"] == candidate["parent_id"]]
            siblings = [o for o in objects if candidate["parent_id"] and o["parent_id"] == candidate["parent_id"]]
            if ((candidate["parent_id"] is None and not candidate.get("attempt_id"))
                    or (len(parents) == 1 and len(siblings) == 1
                        and candidate["attempt_id"] == parents[0]["attempt_id"])):
                obj, automatic = candidate, True
    model = selected_assessment(scene, obj["object_id"] if obj else "", execution)
    model.update(plate_review_state(scene, obj, execution))
    model["image_frames"] = image_frame_status(scene, execution)
    if not obj:
        model.update(frame="Wskaż tablicę, aby zobaczyć pochodzenie obrysu", correction_history="")
        if execution.get("historical_gt"):
            model["gt_note"] = "Zapis historyczny · tylko do odczytu"
    model.update(focus_id=obj["object_id"] if obj else "", focus_mode="AUTO" if automatic else "TEXT_EDIT" if obj and text_edit_id else "SELECTED" if obj else "NONE",
                 focus="Wskaż tablicę na obrazie")
    if obj:
        parent = next((p for p in scene["parents"] if p["parent_id"] == obj["parent_id"]), None)
        index = next(i for i, o in enumerate(objects, 1) if o["object_id"] == obj["object_id"])
        identity = f"MT {int(parent['detection_index']) + 1}" if parent else f"Ręczna {index}"
        model["focus"] = identity + (" · podgląd bez zaznaczenia" if automatic else
                                     " · edycja numeru GT" if text_edit_id else " · zaznaczona do edycji")
    return model


def selected_assessment(scene, object_id, execution):
    """Small preview of ONE plate using the canonical alignment/pose functions.

    Draft values never contribute to aggregates. This function does not call
    summary(), persist GT, or change inference evidence.
    """
    from .mobile_human_review import align_plate_text
    from .mobile_pose_metrics import compare_mt_pose_to_gt, validate_mt_quad

    result = dict(state="NO_SELECTION", execution=execution, draft=True,
                  geometry="IoU / NMCE — wskaż tablicę", outcome=execution["detail"],
                  mz="MZ: —", gt="GT: —", text="Wybierz tablicę, aby porównać MZ z GT",
                  cer=None, edit_distance=None, gt_characters=None, exact=None,
                  polygon_iou_pct=None, nmce_pct=None)
    if not scene:
        result["geometry"] = "IoU / NMCE — brak potwierdzonej pary obrysów"
        if execution["state"] != "MT_EXECUTED":
            result.update(state=execution["state"], text="CER / Exact Match — poza oceną",
                          mz="MZ: nie uruchomiono" if execution.get("mz_not_run") else "MZ: — brak potwierdzonego odczytu")
            if execution.get("historical_gt"):
                result["gt"] = "GT zapisane (historia): " + ", ".join(execution["historical_gt"])
        return result
    if (scene.get("mt_invocation_id") != execution["mt_invocation_id"]
            or scene.get("image_entry") != execution["image_entry"]):
        result.update(state="UNBOUND", text="Brak zgodnego powiązania tablicy z klatką")
        return result
    obj = next((o for o in scene["objects"] if o["object_id"] == object_id), None)
    result["draft"] = not scene["checked"] or bool(core._content_issues(scene))
    if not obj:
        return result
    result["geometry"] = "Brak obrysu MT → IoU / NMCE nie dotyczy"
    parent = next((p for p in scene["parents"] if p["parent_id"] == obj["parent_id"]), None)
    result["gt"] = "GT: " + (obj["gt_text"] or "—")
    result["mz"] = ("MZ: nie uruchomiono" if not parent or parent["mz_status"] == "NOT_RUN" else
                    "MZ: " + (parent["mz_prediction"] or "brak odczytanych znaków") if parent["mz_ran"] else
                    "MZ: nie potwierdzono wykonania")
    if execution["state"] != "MT_EXECUTED":
        result.update(state=execution["state"], text="CER / Exact Match — poza oceną")
        return result
    reason = ("RAW odrzucony przez NMS" if obj.get("post_nms_suppressed") else
              "Błędne wskazanie MT" if obj["error"] and parent else
              "Błąd operatora" if obj["error"] else scene.get("exclusion_reason"))
    if reason:
        result.update(state="EXCLUDED", outcome=reason, text="Poza oceną — " + reason)
        return result
    try:
        validate_mt_quad(obj["quad"], *scene["image_size"])
    except (TypeError, ValueError):
        result.update(state="INVALID_GEOMETRY", outcome="Nieocenialny obrys operatora",
                      text="CER / Exact Match — poza oceną: nieocenialny obrys")
        return result
    result["outcome"] = ("Powiązana z MT (decyzja operatora)" if parent else
                         "Pominięcie MT (FN) · roboczo; do agregatu po potwierdzeniu obrazu"
                         if result["draft"] else "Pominięcie MT (FN) · obraz potwierdzony")
    if parent and parent["quad"]:
        metrics = compare_mt_pose_to_gt(parent["quad"], obj["quad"], *scene["image_size"])
        result.update(polygon_iou_pct=metrics["polygon_iou_pct"], nmce_pct=metrics["nmce_pct"])
        result["geometry"] = (f"IoU {percent(metrics['polygon_iou_pct'])} · "
                              f"NMCE {percent(metrics['nmce_pct'])}")
    elif parent:
        result["geometry"] = "IoU / NMCE — nieprawidłowy obrys źródłowy MT"
    if obj["text_exclusion_reason"]:
        result.update(state="TEXT_EXCLUDED", text="Numer wyłączony z oceny — " + obj["text_exclusion_reason"])
    elif not parent or parent["mz_status"] == "NOT_RUN":
        result.update(state="MZ_NOT_RUN", text="CER / Exact Match — nie dotyczy")
    elif not parent["mz_ran"]:
        result.update(state="MZ_UNKNOWN", text="CER / Exact Match — nieustalone wykonanie MZ")
    elif parent["mz_status"] == "AMBIGUOUS_SAMPLES":
        result.update(state="MZ_AMBIGUOUS", text="Sprzeczne odczyty MZ — poza oceną")
    elif not obj["text_confirmed"] or not obj["gt_text"]:
        result.update(state="GT_MISSING", text="Uzupełnij numer GT · CER —")
    else:
        a = align_plate_text(obj["gt_text"], parent["mz_prediction"])
        result.update(state="EXACT" if a.exact_match else "MISMATCH", cer=a.cer,
                      edit_distance=a.edit_distance, gt_characters=len(a.ground_truth), exact=a.exact_match)
        result["text"] = (f"{'Pełna zgodność' if a.exact_match else 'Numer niezgodny'} · CER {percent(a.cer * 100)}\n"
                          f"Operacje edycyjne / znaki GT: {a.edit_distance}/{len(a.ground_truth)}")
    return result


def current_summary(data, session):
    """Reject another source, session or revision, including missing identity."""
    return bool(data and session and data.get("session_id") == session.session_id
                and data.get("source_archive_sha256") == session.review.source_archive_sha256
                and data.get("review_revision") == session.review.review_revision)


def summary_caption(data, inventory):
    d = data
    cer = d["text_errors"] / d["gt_characters"] if d["gt_characters"] else None
    return (f"Sprawdzono {inventory['inspected']}/{inventory['total']}  |  "
            f"MZ zgodne {d['exact_reads']}/{d['evaluated_reads']}  |  "
            f"CER {percent(cer * 100 if cer is not None else None)} ({d['text_errors']}/{d['gt_characters']})  |  "
            f"IoU {percent(d['polygon_iou_mean_pct'])} (n={d['geometry_n']})  |  "
            f"NMCE {percent(d['nmce_mean_pct'])} (n={d['geometry_n']})")
