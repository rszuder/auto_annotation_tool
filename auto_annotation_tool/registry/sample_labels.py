"""Optional operator metadata, independent of audit, GT and ranking inputs."""
from collections import Counter
import json
from pathlib import Path
import uuid

LABELS_FILE = "sample_labels.json"
LABELS_SCHEMA = "alpr.experiment_sample_labels.v1"
MAX_LABEL_LENGTH = 60


class SampleLabels:
    """One label per selected SHA, with incremental counts and reverse lookup.

    ``selected`` is the existing sample membership set, shared with the GUI.
    Label operations never add or remove membership.
    """

    def __init__(self, selected, payload=None, *, track_id=None):
        self.selected = selected
        self.labels = {}
        self.assignments = {}
        self.counts = Counter()
        self.members_by_label = {}
        self.active_id = ""
        if payload is not None:
            if (not isinstance(payload, dict) or payload.get("schema") != LABELS_SCHEMA
                    or (track_id is not None and payload.get("track_id") != track_id)):
                raise ValueError("Nieprawidłowy plik etykiet próbki lub identyfikator toru.")
            rows, assignments = payload.get("labels"), payload.get("assignments")
            if not isinstance(rows, list) or not isinstance(assignments, dict):
                raise ValueError("Nieprawidłowa lista etykiet lub przypisań próbki.")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Nieprawidłowy wpis etykiety próbki.")
                label_id = row.get("id")
                if not isinstance(label_id, str) or not label_id.strip() or label_id in self.labels:
                    raise ValueError("Nieprawidłowy lub powtórzony identyfikator etykiety.")
                name = self.validate_name(row.get("name"))
                self.labels[label_id] = name
                self.members_by_label[label_id] = set()
            for sha, label_id in assignments.items():
                if sha in selected and isinstance(label_id, str) and label_id in self.labels:
                    self._assign(sha, label_id)

    def validate_name(self, name, *, except_id=""):
        if not isinstance(name, str):
            raise ValueError("Podaj nazwę etykiety.")
        name = name.strip()
        if not name:
            raise ValueError("Podaj nazwę etykiety.")
        if len(name) > MAX_LABEL_LENGTH:
            raise ValueError(f"Nazwa etykiety może mieć najwyżej {MAX_LABEL_LENGTH} znaków.")
        if any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ValueError("Nazwa etykiety musi mieścić się w jednym wierszu.")
        if any(existing.casefold() == name.casefold() and label_id != except_id
               for label_id, existing in self.labels.items()):
            raise ValueError("Etykieta o tej nazwie już istnieje.")
        return name

    def add(self, name):
        name = self.validate_name(name)
        label_id = "L-" + uuid.uuid4().hex
        self.labels[label_id] = name
        self.members_by_label[label_id] = set()
        return label_id

    def rename(self, label_id, name):
        if label_id not in self.labels:
            raise ValueError("Etykieta już nie istnieje.")
        self.labels[label_id] = self.validate_name(name, except_id=label_id)
        return set(self.members_by_label[label_id])

    def delete(self, label_id):
        changed = set(self.members_by_label.get(label_id, ()))
        for sha in changed:
            self._assign(sha, "")
        self.labels.pop(label_id, None)
        self.members_by_label.pop(label_id, None)
        self.counts.pop(label_id, None)
        if self.active_id == label_id:
            self.active_id = ""
        return changed

    def activate(self, label_id):
        if label_id and label_id not in self.labels:
            raise ValueError("Etykieta już nie istnieje.")
        self.active_id = label_id

    def _assign(self, sha, label_id):
        previous = self.assignments.get(sha, "")
        if previous == label_id:
            return False
        if previous:
            self.members_by_label[previous].discard(sha)
            self.counts[previous] -= 1
            del self.assignments[sha]
        if label_id:
            self.assignments[sha] = label_id
            self.members_by_label[label_id].add(sha)
            self.counts[label_id] += 1
        return True

    def assign(self, shas, label_id):
        if label_id and label_id not in self.labels:
            raise ValueError("Etykieta już nie istnieje.")
        return {sha for sha in shas if sha in self.selected and self._assign(sha, label_id)}

    def set_membership(self, shas, selected):
        changed = set()
        for sha in shas:
            if selected:
                if sha not in self.selected:
                    self.selected.add(sha)
                    changed.add(sha)
                if self.active_id and self._assign(sha, self.active_id):
                    changed.add(sha)
            else:
                if sha in self.selected:
                    self.selected.discard(sha)
                    changed.add(sha)
                self._assign(sha, "")
        return changed

    def label_for(self, sha):
        return self.labels.get(self.assignments.get(sha), "")

    @property
    def unlabeled_count(self):
        return len(self.selected) - len(self.assignments)

    def payload(self, track_id, *, retained=None):
        retained = self.selected if retained is None else retained
        return {"schema": LABELS_SCHEMA, "track_id": track_id,
                "labels": [{"id": key, "name": value} for key, value in self.labels.items()],
                "assignments": {sha: label_id for sha, label_id in self.assignments.items()
                                if sha in retained}}



def _validate_raw_sample_labels(payload, track_id, members, *, allow_orphans=False):
    # Strict validation used for persistence/SEAL. Normal UI loading remains tolerant.
    if not isinstance(payload, dict) or payload.get("schema") != LABELS_SCHEMA:
        raise ValueError("Nieprawidłowy schema pliku etykiet próbki.")
    if str(payload.get("track_id") or "") != str(track_id):
        raise ValueError("Plik etykiet należy do innego toru.")

    rows = payload.get("labels")
    assignments = payload.get("assignments")
    if not isinstance(rows, list) or not isinstance(assignments, dict):
        raise ValueError("Nieprawidłowa lista etykiet lub przypisań próbki.")

    label_ids = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Nieprawidłowy wpis etykiety próbki.")
        label_id = row.get("id")
        if not isinstance(label_id, str) or not label_id.strip():
            raise ValueError("Nieprawidłowy identyfikator etykiety próbki.")
        if label_id in label_ids:
            raise ValueError("Powtórzony identyfikator etykiety próbki.")
        label_ids.append(label_id)

    label_ids = set(label_ids)
    current = {
        str(value or "").strip().lower()
        for value in members
        if str(value or "").strip()
    }
    assignment_sha = set()

    for raw_sha, label_id in assignments.items():
        if not isinstance(raw_sha, str) or not raw_sha.strip():
            raise ValueError("Nieprawidłowy SHA w przypisaniu etykiety próbki.")
        sha = raw_sha.strip().lower()
        if raw_sha != sha:
            raise ValueError("SHA w sample_labels.json musi być zapisany małymi literami.")
        if not isinstance(label_id, str) or label_id not in label_ids:
            raise ValueError("Przypisanie odwołuje się do nieistniejącej etykiety.")
        assignment_sha.add(sha)

    orphan = assignment_sha - current
    if orphan and not allow_orphans:
        preview = ", ".join(sorted(orphan)[:3])
        raise ValueError(
            "Etykiety próbki zawierają przypisania do obrazów spoza bieżącej "
            f"próby: {preview}"
        )

    state = SampleLabels(current, payload, track_id=track_id)
    return state, orphan


def validate_sample_labels_for_members(service, track_id, *, track=None):
    # Fail closed if the optional metadata artifact is inconsistent.
    track = dict(track if track is not None else service.get_track(track_id))
    root = service._track_root(track)
    path = root / LABELS_FILE
    if not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Nie można odczytać {LABELS_FILE}: {exc}") from exc

    members = {
        str(row.get("sha256") or "").strip().lower()
        for row in service.list_members(track_id)
        if str(row.get("sha256") or "").strip()
    }
    state, _ = _validate_raw_sample_labels(
        payload, track_id, members, allow_orphans=False
    )
    return state.payload(track_id)


def prune_sample_labels_to_members(service, track_id, *, track=None):
    # Drop only orphan assignments after intentional membership reduction.
    # Label definitions stay, even when their count falls to zero.
    track = dict(track if track is not None else service.get_track(track_id))
    root = service._track_root(track)
    path = root / LABELS_FILE
    if not path.is_file():
        return False

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Nie można odczytać {LABELS_FILE}: {exc}") from exc

    members = {
        str(row.get("sha256") or "").strip().lower()
        for row in service.list_members(track_id)
        if str(row.get("sha256") or "").strip()
    }
    state, orphan = _validate_raw_sample_labels(
        payload, track_id, members, allow_orphans=True
    )
    if not orphan:
        return False

    service._atomic_json(path, state.payload(track_id))
    return True

def load_sample_labels(track_root, track_id, members):
    path = Path(track_root) / LABELS_FILE
    if not path.exists():
        return None
    if not path.resolve().is_relative_to(Path(track_root).resolve()):
        raise ValueError("Plik etykiet wychodzi poza katalog toru.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SampleLabels(set(members), payload, track_id=track_id).payload(track_id)


def save_sample_labels(service, track_id, *, sample_labels, expected_member_sha256):
    """Save metadata on an already committed sample without touching its audit.

    Recheck membership/lifecycle under the write lock, and restore both files
    if either the filesystem write or the SQLite commit fails.
    """
    from .track_service import EvaluationTrackError
    from .final_sample_policy import has_selected_sample

    service.repository.initialize()
    connection = service.repository.database.connect()
    backups = {}
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM evaluation_tracks WHERE track_id=?", (track_id,)).fetchone()
        if row is None or row["status"] != "DRAFT":
            raise EvaluationTrackError("Etykiety można zmieniać tylko w roboczej próbie DRAFT.")
        track = dict(row)
        members = [dict(row) for row in connection.execute(
            "SELECT * FROM evaluation_track_members WHERE track_id=?", (track_id,))]
        current = {row["original_name"]: row["sha256"] for row in members}
        if current != expected_member_sha256:
            raise EvaluationTrackError("Skład próby zmienił się. Otwórz ją ponownie z PZ3.")
        if not has_selected_sample(service.workspace, track, members):
            raise EvaluationTrackError("Najpierw zatwierdź skład próby.")
        labels = SampleLabels(set(current.values()), sample_labels, track_id=track_id)
        root = service._track_root(track)
        label_path, manifest_path = root / LABELS_FILE, root / "track_manifest.json"
        for path in (label_path, manifest_path):
            if not path.resolve().is_relative_to(root.resolve()):
                raise EvaluationTrackError("Artefakt etykiet wychodzi poza katalog toru.")
            backups[path] = path.read_bytes() if path.exists() else None
        manifest = service._read_json(manifest_path)
        if labels.labels:
            service._atomic_json(label_path, labels.payload(track_id))
            manifest["sample_labels"] = {"path": LABELS_FILE, "sha256": service._sha256(label_path)}
        else:
            label_path.unlink(missing_ok=True)
            manifest.pop("sample_labels", None)
        service._atomic_json(manifest_path, manifest)
        connection.commit()
        return {"track_id": track_id, "selected_count": len(members),
                "candidate_count": len(members), "removed_count": 0}
    except Exception:
        connection.rollback()
        for path, content in backups.items():
            if content is None:
                path.unlink(missing_ok=True)
            elif not path.exists() or path.read_bytes() != content:
                path.write_bytes(content)
        raise
    finally:
        connection.close()
