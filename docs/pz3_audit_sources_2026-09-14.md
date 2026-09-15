# PZ3 — mapa źródeł danych przed refaktoryzacją audytu (handoff v2)

Sprawdzono lokalny branch feature/evaluation-registry, schemat, migracje,
RegistryDatabase i RegistryRepository. Układ użytkownika pozostaje punktem wyjścia.

Baza: Workspace/_registry/alpr_registry.sqlite3.
RegistryDatabase otwiera osobne połączenia, włącza foreign_keys, WAL i busy_timeout.
Migracje są wersjonowane przez PRAGMA user_version i wykonywane transakcyjnie.

| Pole / artefakt | Kanoniczne źródło przed zmianą | Writer | Reader |
| --- | --- | --- | --- |
| model_id, SHA checkpointu, target, rodzina/skala | SQLite: models | runtime_service, participant_model_registry przez RegistryRepository | selektor modeli, ParticipantPoolAuditService |
| Lokalizacje checkpointu | SQLite: model_locations | finalizacja treningu, rejestracja i bootstrap | rejestr modeli |
| Model → run → dataset → train/val | SQLite: models, training_runs, datasets, dataset_members, image_artifacts, source_images | rejestracja historii / bootstrap / runtime przez repozytorium | list_participant_training_members — rekurencyjny SQL ancestry |
| Uczestnicy konkretnego toru PZ3 | participants.json w katalogu toru, snapshot ID/SHA/run | ParticipantPoolAuditService.save_participants | load_participants, audyt, gate, blokada unregister |
| Uczestnicy zapisanego eksperymentu | SQLite: experiment_participants | usługa eksperymentów przez repozytorium | eksperymenty i blokada unregister |
| Cykl życia i identyfikator toru | SQLite: evaluation_tracks | EvaluationTrackService / RegistryRepository | panel PZ3, eksperymenty |
| Członkowie toru | SQLite: evaluation_track_members oraz image_artifacts/source_images | add_member, add_members_batch, remove_members | tabela obrazów, generowanie manifestu, audyt |
| Kopie obrazów i GT | filesystem toru | EvaluationTrackService | Z2, weryfikacja, audyt |
| Manifest członków / GT | track_manifest.json, artefakt generowany ze stanu toru | EvaluationTrackService._write_manifest | weryfikacja i integralność |
| CURRENT/STALE audytu | participant_pool_audit_state.json | invalidate_track_audit / record_ingested_report | assert_track_audit_ready; wcześniej brak trwałego widoku w panelu |
| Szczegółowa diagnoza audytu | audits/participant_pool_audit_*.json oraz raport w pamięci | audit_paths | dotychczasowy viewer; artefakt reprodukowalności |
| Decyzja operatora dla każdego obrazu | brak pełnego rejestru; zapisywano tylko zaakceptowane podejrzane SHA | record_ingested_report | stan audytu |
| Cache SHA/pHash | _registry/participant_pool_file_cache.json | _PersistentFingerprintCache | audit_paths / fingerprint_paths |

## Docelowy zapis

Migracja SQLite v4 dodaje evaluation_track_audits,
evaluation_track_audit_decisions i evaluation_track_audit_state.

- Aktualny stan i decyzje operatora są kanonicznie zapisane w SQLite.
- Dotychczasowy plik stanu jest odczytywany wyłącznie przy przenoszeniu starego
  toru, gdy w SQLite nie ma jeszcze jego stanu. Dalsze odczyty korzystają z bazy.
- Nie powstaje drugi aktualizowany rejestr stanu w JSON. Stary plik pozostaje
  historycznym artefaktem kompatybilności.
- Szczegółowy raport diagnostyczny i cache mogą pozostać artefaktami plikowymi.
  Zastosowany raport jest także snapshotem związanym z decyzjami w SQLite.
- participants.json opisuje uczestników toru. Nie jest zamieniany na
  experiment_participants: ta relacja opisuje osobny, zapisany eksperyment.
- Manifest członków nie ma pola CURRENT/STALE audytu. Aktualność sprawdzana jest
  dla jego członków przez zbiór SHA oraz fingerprint uczestników w rejestrze.

## Kolejność i awarie

1. Diagnoza i decyzje w dialogu nie zmieniają członków ani GT.
2. Anulowanie nie wykonuje insertów członków ani zapisu decyzji / CURRENT.
3. Zastosowanie sprawdza, czy uczestnicy i członkowie nadal odpowiadają snapshotowi.
4. Ingest pozostaje istniejącą transakcją paczki z kontrolą SHA kopii.
   Usunięcie istniejących obrazów korzysta z usługi DRAFT i jej stagingu;
   wpływ na GT jest widoczny przed zatwierdzeniem w oknie audytu.
5. Modyfikacja członków unieważnia audyt w SQLite.
6. Raport, decyzje i nowy stan audytu są zapisywane razem w transakcji.
   Nieudany zapis pozostawia STALE; błąd nie jest przedstawiany jako sukces.
7. Błąd manifestu po zatwierdzeniu członków zachowuje ich pliki i nie nadaje CURRENT.
8. Nowy ingest rozszerza aktualny audyt tylko o zaakceptowane nowe obrazy i tylko
   wtedy, gdy wcześniejszy audyt nadal pokrywał wszystkich dotychczasowych członków.
   Nieaktualna wcześniejsza pula wymaga pełnego „Audytuj pulę”.

FK nowych rekordów wiążą je z torem (ON DELETE CASCADE); decyzje z audytem.
Dotychczasowe blokady modeli użytych przez eksperyment (ON DELETE RESTRICT)
pozostają częścią istniejącego repozytorium.

