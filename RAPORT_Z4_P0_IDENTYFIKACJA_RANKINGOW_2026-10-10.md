# Z4 P0 — identyfikacja modeli i torów

Wdrożono poprawę istniejących okien „Uczestnicy rankingu modeli” oraz „Wybór toru testowego rankingu”. Nie uruchomiono treningu, rankingu ani inferencji.

## Zmiany

- **Tory:** rzeczywisty katalog, ID Z2, typ, projekt/globalny zakres, data z podaniem źródła w szczegółach, gotowość, liczba obrazów źródłowych i osobno liczebności historycznych ocen. Panel szczegółów zawiera ścieżkę, `annotations.xml`, metadane i konkretne rekordy `model_ranking.json`. Wyszukiwanie obejmuje również metadane i daty. Dodano kopiowanie ścieżki oraz poziomy pasek przewijania.
- **Modele:** ID uczestnika i treningu, architektura i rozmiar z metadanych, pełna nazwa checkpointu, data treningu, ukończone/planowane epoki i zakres. Szczegóły pokazują pliki metadanych/historii oraz rzeczywisty SHA-256 obliczany z checkpointu w tle. Brak dowodu oznacza „nieustalone”; nazwa pliku nie zastępuje informacji o architekturze lub treningu.
- **Wybór:** Start TAK/NIE pozostaje zmieniany kliknięciem jego komórki lub spacją. Filtr, sortowanie i odświeżanie nie zmieniają Start ani toru. Zmiana splitu jest robocza do „Zastosuj”. Podwójne kliknięcie nagłówka sortowania nie zatwierdza toru.
- **Windows:** usunięto `transient` z tych dwóch okien, zachowano skalowanie i wyłączono automatyczne odzyskiwanie ich widoczności przez rodzica. Działają minimalizacja, maksymalizacja, przywrócenie i zamknięcie; bez trybu pełnoekranowego. Tabele i szczegóły rosną, przyciski pozostają na dole.
- **Bezpieczeństwo odczytu:** katalog nie uruchamia uzgadniania historii. Surowe historyczne rekordy są zachowane także z dodatkowymi polami eksperymentu, które starszy `ModelRankingEntry.from_dict()` pomija przy deserializacji.

## Odbiór

**46 testów regresyjnych PASS**, w tym 14 testów nowego zakresu, powtórzonych po ostatnich poprawkach. Sprawdzono też dotychczasowe wyniki/eksport EVAL396 i panel pomiarów MT.

Uruchomiono pełną `AutoAnnotationApp` z rzeczywistą `TrainingTab` oraz lokalnymi katalogami modeli i torów. Test integracyjny miał blokadę zapisu danych roboczych, odczyt historii bez uzgadniania i osobną kopię sesji QA. To test pełnej aplikacji, a nie atrap list modeli. Połączenie computer-use z Windows było niedostępne; kontrolę wykonano przez instrumentację Tk w procesie testowym aplikacji.

W obu oknach potwierdzono natywne style Windows, minimalizację/przywrócenie/maksymalizację, wzrost tabel, widoczność dolnych przycisków, wyszukiwanie, sortowanie i kopiowanie ścieżki. Start oraz wybrany tor pozostały bez zmian. Odczytano 23 uczestników i 156 torów; brak błędów callbacków i prób zapisu chronionych plików.

- [Zmaksymalizowani uczestnicy](Workspace/_qa/z4_ranking_identity_20261010/participants_maximized.png)
- [Zmaksymalizowany wybór toru — odnaleziony eksperyment](Workspace/_qa/z4_ranking_identity_20261010/tracks_maximized.png)
- [Pełna lista torów](Workspace/_qa/z4_ranking_identity_20261010/tracks_all_maximized.png)
- [Dowód testu pełnej aplikacji](Workspace/_qa/z4_ranking_identity_20261010/full_application_verification.json)
- [Regresja](Workspace/_qa/z4_ranking_identity_20261010/tests_final.xml), [ostatnie testy nowego zakresu](Workspace/_qa/z4_ranking_identity_20261010/tests_last.xml)

**33 862 chronione pliki zachowały SHA-256**: Z2, checkpointy i metadane, historyczne rankingi/raporty, tory eksperymentalne oraz wcześniejszy zakres EVAL396/GT/datasetów. [Kontrola integralności](Workspace/_qa/z4_ranking_identity_20261010/protected_after.json).

## Odnalezione porównanie MT-n / MT-s

W `Workspace/7_rankings/plates/model_ranking.json` istnieją dwa rekordy eksperymentu **EXP-7A1394D2F8704A199B35** z **2026-09-19, 10:44:15 i 10:44:36**, po **500 obrazów**. Mają wspólne `reference_path`, `track_id` i SHA protokołu. Metadane oraz rzeczywiste SHA checkpointów potwierdzają **YOLO26n Pose** i **YOLO26s Pose**.

Tor: `Workspace/10_experiments/tracks/plate/Porownanie_modeli_MT-s_vs_n__v001__4046B8AD`, ID **TRK-A4562E0840FC4046B8AD**. Zachowano `ground_truth/annotations.xml`, manifest i pieczęć. Tor zawiera 500 elementów; `sample_selection.json` zapisuje pulę 9952 kandydatów przed selekcją. **9952 nie zostało uznane za liczebność Z2 ani ocenionego zbioru.** Powiązanie wynika z konkretnych ścieżek/ID/SHA, nie ze zgodności liczby obrazów. Ten tor jest eksperymentalny, dlatego nie wymyślono mu ID Z2.

Stara lista przeszukiwała głównie runy Z2 i bieżący projekt; nie odkrywała tego toru na podstawie `reference_path` zapisanych ocen. Obecnie można wyszukać `Porownanie_modeli_MT-s_vs_n` i odczytać oba wyniki w szczegółach. Wpis historyczny nie zmienia procedury uruchamiania nowych rankingów.

## Zachowane wykresy — bez ponownego pomiaru

Raport `Workspace/7_rankings/plates/reports/ranking_report_20260919_114308` jest zachowany. Zweryfikowano zgodność dwóch wierszy CSV z rekordami natywnymi, ścieżkami modeli, liczbą 500, metrykami P/R/accuracy i SHA zapisanymi w Markdown. Pliki SVG są poprawnym XML. [Pełny dowód odszukania i SHA](Workspace/_qa/z4_ranking_identity_20261010/recovered_history.json).

Sześć istniejących wykresów analitycznych:

1. [Precision / Recall / F1](Workspace/7_rankings/plates/reports/ranking_report_20260919_114308/ranking_metrics.svg)
2. [Koszt korekt detekcji](Workspace/7_rankings/plates/reports/ranking_report_20260919_114308/ranking_plate_diffs.svg)
3. [Statystyki błędu narożników](Workspace/7_rankings/plates/reports/ranking_report_20260919_114308/ranking_corner_metrics.svg)
4. [F1 według etykiet](Workspace/7_rankings/plates/reports/ranking_report_20260919_114308/ranking_label_f1.svg)
5. [IoU ≥ 0,8 według etykiet](Workspace/7_rankings/plates/reports/ranking_report_20260919_114308/ranking_label_accuracy.svg)
6. [P95 błędu narożników według etykiet](Workspace/7_rankings/plates/reports/ranking_report_20260919_114308/ranking_label_corner_p95.svg)

Dodatkowo istnieje siódmy, zbiorczy [ranking_score.svg](Workspace/7_rankings/plates/reports/ranking_report_20260919_114308/ranking_score.svg). Nie regenerowano ani nie zmieniano tych wykresów i raportu. Ich stare etykiety, m.in. sufiks `map00`, pozostały oryginalne; identyfikację architektury oparto na metadanych/SHA, a nie na tym sufiksie. Nie przeprowadzano ponownego audytu metodologii historycznych metryk w ramach poprawki UX.

## Pliki zmiany

- `auto_annotation_tool/gui/z4_analysis_ranking.py` — istniejące wejścia do okien kierują do wspólnego widoku katalogów; odczyty historii bez uzgadniania.
- `auto_annotation_tool/gui/z4_ranking_catalog.py` — tabele, szczegóły, wyszukiwanie, Start i okna Windows.
- `auto_annotation_tool/gui/z4_ranking_identity.py` — odczyt i jawne powiązania metadanych oraz historii.
- `tests/test_z4_ranking_identity.py`, `tests/test_z4_ranking_catalog_ui.py` — regresja.
- Niniejszy raport i dowody QA.

Wcześniejsze lokalne zmiany zachowano. Nie zmieniono wykonawcy Fazy 2B, polityki Pose478/Bbox479, checkpointów ani EVAL396/GT. Kod wymaga ponownego uruchomienia aplikacji.
