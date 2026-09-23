"""Catch legacy AT in which automatic plate polygons repeat vehicle boxes."""
from .config import CONFIG


def plate_vehicle_conflicts(annotations) -> list[dict]:
    conflicts = []
    for annotation in annotations:
        vehicles = [det for det in annotation.detections
                    if str(det.label).strip().lower() in CONFIG.VEHICLE_LABELS]
        for index, plate in enumerate(annotation.detections):
            if str(plate.label).strip().lower() not in CONFIG.PLATE_LABELS:
                continue
            attrs = plate.attributes or {}
            if (str(getattr(plate, "_cvat_source", "")).lower() == "manual"
                    or str(attrs.get("manually_edited", "")).lower() == "true"
                    or attrs.get("manual_source") or attrs.get("ground_truth_text")):
                continue
            x1, y1, x2, y2 = plate.bbox
            area = max(0, x2 - x1) * max(0, y2 - y1)
            if not area:
                continue
            # This legacy failure turned a detector bbox into a rectangular
            # plate polygon. Do not infer semantic errors from aspect alone.
            points = plate.polygon or []
            if len(points) != 4:
                continue
            polygon_area = abs(sum(points[i][0] * points[(i + 1) % 4][1]
                                   - points[(i + 1) % 4][0] * points[i][1] for i in range(4))) / 2
            if polygon_area / area < .97:
                continue
            for vehicle in vehicles:
                vx1, vy1, vx2, vy2 = vehicle.bbox
                other_area = max(0, vx2 - vx1) * max(0, vy2 - vy1)
                intersection = max(0, min(x2, vx2) - max(x1, vx1)) * max(0, min(y2, vy2) - max(y1, vy1))
                union = area + other_area - intersection
                iou = intersection / union if union else 0
                if iou >= .9:
                    conflicts.append({"filename": annotation.filename, "detection_index": index,
                                      "plate_bbox": list(plate.bbox), "vehicle_bbox": list(vehicle.bbox),
                                      "iou": round(iou, 6)})
                    break
    return conflicts


def plate_import_error(annotations) -> str:
    conflicts = plate_vehicle_conflicts(annotations)
    if not conflicts:
        return ""
    files = list(dict.fromkeys(item["filename"] for item in conflicts))
    examples = "\n".join(files[:5])
    return (
        f"AT zawiera {len(conflicts)} automatycznych ramek tablic niemal pokrywających całe pojazdy "
        f"na {len(files)} obrazach. Etykiety tego AT są niespójne — mogły powstać przy użyciu modelu pojazdów "
        "jako modelu tablic.\n\n"
        f"Przykłady:\n{examples}\n\n"
        "Popraw AT lub wybierz inny zbiór anotacji. Możesz też dodać same obrazy "
        "i uruchomić w Z2 detekcję modelem tablic. Plik źródłowy nie został zmieniony."
    )
