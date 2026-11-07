# F4: eligibility from saved frame decisions, 2026-11-02

This retrospective eligibility/reporting contract is `f4_frame_decisions_assisted_v1`.
Its authoritative constants and SHA are in `ranking/mobile_frame_review_state.py`.
The F4-EVAL-2.0 matching policy, source population, 1:1 pairing, geometry math,
conditional OCR scoring, source timings and BBOX-v1 algorithm are unchanged.

`AUTO_FROM_FRAME_DECISIONS` means every proven FINAL has a saved PLATE/NOT_PLATE
decision and the active operator references have finished, valid geometry.
Space, PPM and completed D/corner editing are the operator's decisions. There
is no second image checkbox, link, keyboard shortcut or navigation approval.
Historical `checked`/`empty_confirmed` and events remain readable. Reads and
exports do not write/migrate sidecars; edits record their completion basis in
the same normal atomic review transaction.

GT remains ASSISTED, with `gt_scope=operator_reference_scope` and FN limited to
`saved_physical_GT_only`. Completion is not an independent exhaustive census
of all plates in the photograph. 0 FINAL/0 GT is NO_REFERENCE_EVIDENCE and N/A,
not a new TN, inferred FN=0 or full recall. Technical source/ROI/execution gaps
remain N/A. A previously accepted BBOX identity without optional GTR geometry
does not require rechecking; the unavailable object/geometry measure remains
explicitly N/A until sufficient reference evidence exists. Missing GTZ limits
OCR only, and does not revoke operational MT completion.

New exports contain the eligibility contract/SHA/date, source archive SHA,
review revision, exact source-review SHA, snapshot digest and per-measure n/N.
Old exports are immutable and replay using their original unit inputs. Legacy
checked-based inputs and new eligibility inputs must not be silently combined
as a single evaluation cohort. The scoped handoff contains the per-invocation
before/after eligibility audit for the actual 12 F4 sessions.
