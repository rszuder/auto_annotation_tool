# Profil modeli uczestniczących w PZ3

Katalog uczestników pokazuje sześć kolumn: W eksperymencie, Model, Architektura,
Pochodzenie (Run i Dataset), Jakość (mAP50–95), Historia.
Kliknięcie wiersza otwiera profil; pole W eksperymencie, spacja oraz Dodaj/Usuń zmieniają udział.
Aktualna hierarchia akcji i prowadzenie PZ3: [PZ3 — prowadzenie](pz3_guided_workflow.md).

Profil zawiera pełne Run/Dataset, datę zakończenia treningu, osobne mAP Pose/BBox,
status pochodzenia, rodzaj checkpointu oraz skrócony SHA z kopiowaniem pełnej wartości.
Daty mają format DD.MM.YYYY · HH:MM, a metryki trzy miejsca po przecinku.
Kolory semantyczne dotyczą pochodzenia; mAP pozostaje neutralny.

## Źródła i wydajność

- Run, Dataset, zakończenie treningu oraz checkpoint pochodzą z pojedynczego zapytania registry.
- Metryki: zapisana historia przypisanego runu, następnie jego train/results.csv lub results.csv.
- Historia jest wyszukiwana wyłącznie w zarejestrowanym katalogu wyjściowym i trzech najbliższych
  katalogach nadrzędnych. Wpis musi odpowiadać namespaced registry run_id oraz zapisanej ścieżce wyjściowej.
- Każdy artefakt jest parsowany ponownie tylko po zmianie rozmiaru lub czasu pliku.
  Modele dzielące run korzystają z tego samego przygotowanego profilu.
- Brak skanowania Workspace, hashowania checkpointów i inferencji.
- Zmiana zaznaczenia i sortowanie korzystają wyłącznie z przygotowanych danych.
- Audyt korzysta z lekkiej listy eligible, bez odczytywania artefaktów metryk.

Starsze best_map50/best_map50_95 bez oznaczenia rodzaju są pokazywane jako metryki
historii. Nie są nazywane Pose ani BBox. Jeśli nie zapisano metryki Pose, tabela pokazuje
„Pose —”. Opcjonalne, nieobecne metryki ogólne nie zajmują dodatkowych wierszy profilu.

## Integralność

Fingerprint nadal obejmuje wyłącznie model_id, SHA, run_id, dataset_id i provenance.
Data, checkpoint_kind, task_type oraz metryki są informacyjne.
Ich aktualizacja nie unieważnia audytu. Brak daty lub mAP nie blokuje uczestnika.

Niespójne complete/known pozostają widoczne diagnostycznie, ze statusem „Niespójna”,
ale nie można dodać ich do eksperymentu. Backend nadal odrzuca brak runu/datasetu.

Wspólny run jest jawnie widoczny. Przy complete i różnych SHA oraz skalach
profil ostrzega o potencjalnym błędnym przypisaniu. Samo ostrzeżenie nie zmienia udziału.

Zapis uczestników może zachować informacyjny profil. Odczyt zapisanych uczestników,
zwłaszcza SEALED/RETIRED, nie wzbogaca historii bieżącymi metrykami.

## Granice

W tym zadaniu nie zmieniano RAW selection, GT lifecycle, mechaniki audytu train/val,
SEAL, controlled reference, rankingu, bridge ani logiki porównania modeli.
Nie dodano migracji schematu registry.

Testy: test_participant_background.py, test_pz3_participant_profile.py oraz wcześniejsze
testy lineage, sortowania i interakcji dialogu.

## Wyniki weryfikacji — 2026-09-16

- Testy profilu, lineage i dialogu: 50 PASS, 8 subtests.
- Pełne unittest discover: 710 testów OK.
- Dodatkowe testy funkcji Z2: 64 PASS.
- pz3_final_hardening_smoke.py: PASS.
- pz3_sample_review_smoke.py: PASS.
- GUI: jasny i ciemny motyw, 1140×780 i 1000×700, szczegóły, wspólny run,
  blokada niespójnego modelu.
- Kontrola hashy plików chronionych względem stanu sprzed tego zadania: bez zmian.
  Stan odniesienia zapisano lokalnie w output/pz3_profile_baseline.json.

Wyniki smoke są testem przepływu na izolowanych danych; nie stanowią pomiaru
jakości MT-n vs MT-s w rzeczywistym eksperymencie.
