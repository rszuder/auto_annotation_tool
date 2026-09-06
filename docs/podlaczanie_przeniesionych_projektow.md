# Podłączanie przeniesionego projektu

W panelu projektów Z1 jest przycisk **Podłącz istniejący projekt…**.
Wykrywa katalogi umieszczone bezpośrednio w `Workspace/9_projects`, których
nie ma jeszcze w `campaigns_registry.json`.

1. Wybierz katalog z listy lub przez wybór folderu.
2. Użyj **Sprawdź**. Analiza działa w tle; okno pozostaje dostępne.
3. Sprawdź nazwę, odtworzony etap, dostępne zasoby i brakujące odwołania.
4. Użyj **Podłącz projekt**. Projekt pojawi się na liście i można otworzyć go
   zwykłym dwuklikiem. Samo podłączenie nie zmienia aktywnego projektu.

## Rozpoznawanie i przenośny opis

Nowe zapisy stanu utrwalają także `_campaign_state/project.json`
(`alpr.project.v1`) wewnątrz folderu projektu. Przy kolejnym przeniesieniu
folderu ten opis pozwala zachować stan kampanii oraz wybrane modele.

Starsze katalogi bez opisu są rozpoznawane po rejestrze artefaktów lub historii
treningów. Stan jest odtwarzany z historii projektu i danych bieżącej iteracji.
Nie jest to pełna kopia utraconego rejestru poprzedniej instancji: np. wyboru
aktywnego modelu nie odgaduje się wyłącznie z istnienia zakończonego treningu.
Okno pokazuje, kiedy użyto takiego odtwarzania.

## Ścieżki, źródła i zapis

- Nazwa folderu i identyfikatory artefaktów pozostają zachowane.
- Ścieżki wewnątrz projektu są dostosowywane w metadanych JSON/JSONL,
  YAML i XML. Pliki checkpointów, obrazy i metryki treningu nie są edytowane.
- Odwołania do zasobów wspólnego workspace mogą wskazywać lokalną kopię tylko
  wtedy, gdy istnieje pod dokładnie odpowiadającą ścieżką. Brakujące zasoby
  zewnętrzne pozostają jawnie wymienione; katalog nie jest z tego powodu
  zastępowany przypadkowym zbiorem obrazów.
- Obrazy zatwierdzonych anotacji zachowane wyłącznie w roboczym
  `char_effective_source/images` są zabezpieczane w
  `1_raw_images/attached_approved_sources`. Powiązanie wymaga zgodności cache
  z ApprovedSet, nazwy, rozmiarów i geometrii anotacji. Na NTFS używane są
  dodatkowe dowiązania twarde, z kopią pliku jako wariantem awaryjnym.
  Usunięcie kopii roboczej przy przebudowie źródła nie usuwa zabezpieczonego obrazu.
- Oryginały zmienianych opisów i rejestru są zachowane w
  `_campaign_state/attachments/<data_id>/`. Raport `attachment.json` zawiera
  ścieżki, SHA-256 przed/po, listę zabezpieczonych obrazów i nierozwiązane zasoby.
- Rejestr jest aktualizowany na końcu operacji, atomowym zastąpieniem pliku.
  Błąd zapisu powoduje odtworzenie zmienionych opisów i usunięcie nowo
  utworzonych kopii obrazów. Zmiana danych od momentu analizy wymaga ponownego
  sprawdzenia; kolizje nazw i ponowne podłączenie tego samego folderu są odrzucane.
- Zwykły zapis rejestru zachowuje nowe projekty podłączone przez inną instancję,
  których zapisująca instancja nie znała przy wczytywaniu danych.

## Weryfikacja przykładu — 2026-09-06

Podłączono `train_yolo26n_pose_258740` jako **train_yolo26n_pose**:

- odtworzono iterację 2, etap Z3/PZ2 i ścieżkę `char_from_ready_plates`;
- zachowano 1245 tablic podglądu oraz dwa zakończone treningi;
- zabezpieczono 1000 obrazów zatwierdzonych anotacji;
- oba pliki `best.pt`, YAML datasetu i geometria znaków zachowały zawartość;
- aktywny projekt i wszystkie wcześniejsze wpisy rejestru pozostały zachowane;
- świeży `CampaignManager` i rzeczywista lista w GUI widzą podłączony projekt.

Pełna pula `SAMPLE_10K` i niektóre modele spoza folderu projektu nie zostały
przeniesione. Ich odwołania znajdują się w raporcie. Dostępne lokalnie treningi,
dataset, wyodrębnione tablice i zabezpieczone źródła pozostają w projekcie.

Kopia bezpieczeństwa tej operacji:
`Workspace/9_projects/train_yolo26n_pose_258740/_campaign_state/attachments/20260906_224356_e0d60c`.

Próba GUI: `output/project_attachment_ui_probe.py`; wynik i zrzuty:
`output/project_attachment_audit/`. Zarejestrowano 233 wykonania kontrolnego
timera podczas analizy — odczyt nie blokował głównego wątku Tk.

Regresje: `tests/test_project_attachment.py` (17 przypadków), testy przeglądarki
projektów oraz odczytu zasobów historycznych. Końcowy pełny przebieg:
**481 testów i 44 podtesty, bez pominięć** (`python -m pytest tests -q
--tb=short --basetemp=output/pytest_attachment_final_all`).
