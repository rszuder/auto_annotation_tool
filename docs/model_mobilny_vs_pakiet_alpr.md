# Model mobilny i kompletny pakiet ALPR — wdrożenie handoffu

Data: 2026-09-07. Punkt odniesienia: `301a1ef`.
Handoff: `handoff_desktop_model_vs_alpr_package_contract_v1.md`.

## Zachowanie eksportu

| Wybór | Wynik | Schemat |
| --- | --- | --- |
| MP | Model mobilny pojazdów | `alpr.model.v1`, `role=vehicle` |
| MT | Model mobilny tablic | `alpr.model.v1`, `role=plate` |
| MZ | Model mobilny znaków | `alpr.model.v1`, `role=character` |
| MT+MZ | Minimalny kompletny pakiet ALPR | `alpr.package.v1` |
| MP+MT+MZ | Kompletny pakiet kaskadowy ALPR | `alpr.package.v1` |
| MP+MT, MP+MZ | Eksport zablokowany, wskazana brakująca rola | Brak pliku wynikowego |

Pojedynczy eksport pozwala podmienić jedną rolę w konfiguracji telefonu,
zachowując pozostałe modele. Model mobilny służy też do pomiaru mAP, recall
i F1 w teście izolowanym. Kompletny pakiet pozwala badać exact match, CER,
błędy całego potoku i wydajność mobilną. Import rankingu pakietów wymaga MT i MZ.

## Zmiany w aplikacji

- `gui/z4_mobile_export_contract.py`: wspólny opis wyboru i nazw eksportu.
- `gui/z4_model_export.py`: centrum pokazuje typ wyniku i schemat; modal,
  przycisk po sprawdzeniu gotowości, okno zapisu i komunikat sukcesu stosują
  nazwy „model mobilny” albo „pakiet ALPR”. Poprawiono też starszy dialog.
- `gui/z4_train_tab_builder.py`, `gui/z4_training_runtime.py`: menu historii
  używa „Eksportuj model mobilny (.alprmodel)”.
- `gui/tab_help.py`, `gui/free_mode_assistant.py`, `gui/app.py`,
  `gui/z4_tab_shell.py`: pomoc i objaśnienia rozróżniają oba wyniki.
- `exporters/mobile_model_exporter.py`: brak MT lub MZ zgłasza wspólny,
  czytelny błąd z odesłaniem do eksportu pojedynczego modelu. Dotychczasowa
  walidacja wymagała obu ról już przed wdrożeniem.

Wszystkie powyższe ścieżki są względne do `auto_annotation_tool/`.
Ujednolicono także `docs/eksport_mobilny_kwantyzacja.md`,
`docs/specyfikacja_agenta_aplikacji_mobilnej_alpr.md`,
`docs/freeze_smoke_test_checklist.md`, `alpr_python_exporter_handoff.md`
i `DZIENNIK_ARCHITEKTURY_I_ZMIAN.md`.

## Przykłady manifestów

Poniższe fragmenty pokazują podział kontraktów. Pełne manifesty zawierają
również wejście i wyjście tensorów, warianty runtime, sumy SHA-256 i provenance.

Pojedynczy MT:

```json
{
  "schema": "alpr.model.v1",
  "model_id": "plate",
  "role": "plate",
  "task": "pose"
}
```

Kompletny pakiet MT+MZ:

```json
{
  "schema": "alpr.package.v1",
  "package_id": "complete",
  "kind": "complete_alpr_pipeline",
  "models": {
    "plate": {
      "schema": "alpr.model.v1",
      "role": "plate",
      "task": "pose",
      "package_file": "models/plate/model.alprmodel"
    },
    "character": {
      "schema": "alpr.model.v1",
      "role": "character",
      "task": "detect",
      "package_file": "models/character/model.alprmodel"
    }
  },
  "pipeline": [
    {"stage": "plate_detection"},
    {"stage": "plate_rectification"},
    {"stage": "character_detection"},
    {"stage": "sequence_assembly"}
  ]
}
```

## Weryfikacja

Wynik końcowy: **103 testy przeszły** w zestawie eksportu, NCNN, tożsamości
checkpointów, źródeł i lokalizacji modeli oraz raportów mobilnych. Natywny
smoke test GUI potwierdził wszystkie **7 kombinacji ról**, bez błędów callbacków.

`tests/test_mobile_model_package_contract.py` obejmuje D1–D7 oraz D9:
eksport wszystkich pojedynczych ról, składanie obu kompletów, odrzucanie
niepełnych zestawów przed zapisem, kontrolę importu rankingu i dokumentacji.
Testy wykonują rzeczywiste tworzenie ZIP, manifestów, sum SHA-256 i walidację;
konwersja sieci i sprawdzanie zależności są zastąpione danymi testowymi.
Sprawdzana jest także niezmienność bajtów zagnieżdżonych modeli i ich metadanych.

`tests/gui_mobile_model_package_contract_probe.py` realizuje D8 w natywnym Tk:
pięć poprawnych wyborów przechodzi od zaznaczenia przez gotowość i okno zapisu
do komunikatu sukcesu, a MP+MT i MP+MZ mają zablokowany przycisk. Skrypt sprawdza
również wybór właściwego eksportera. Konwersja i dialogi systemowe są zastąpione
kontrolowanymi odpowiedziami; obrazy okien i wyniki trafiają do
`output/model_package_gui/`.

Nie zmieniono budowania manifestu pojedynczego modelu, kontraktów tensorów,
runtime, kwantyzacji, NCNN, checkpoint SHA, dataset identity, lineage ani
formatu `.alprsession`. Istniejące testy NCNN, tożsamości checkpointów,
źródeł projektu, lokalizacji eksportu i raportów są częścią weryfikacji regresji.
