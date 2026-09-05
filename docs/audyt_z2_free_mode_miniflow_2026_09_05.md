# Z2: wydajnosc wejscia i miniflow trybu swobodnego

Data: 2026-09-05. Dokument obejmuje diagnoze i pozniejsze wdrozenie.
Zachowano zastane modyfikacje w drzewie roboczym.

## Wdrozenie po akceptacji

Pomiar po poprawkach, bez eksperymentalnego podmieniania funkcji aplikacji:

| Operacja | Przed | Po wdrozeniu, lokalne proby |
| --- | ---: | ---: |
| Pierwsze otwarcie Z2 | 29,710 s | 0,72-0,92 s |
| Wybor pracy recznej | 26,677 s | 0,13-0,18 s |
| Przejscie Nowy -> wybor obrazow | 0,702 s | 0,13-0,18 s |
| Ponowne Wstecz/Dalej | nieustalone | 0,14-0,17 s |
| Otwarcie testowego runu do edycji | nieustalone | 0,65-0,81 s |

Test obejmowal katalog 1000 wlasnych obrazow 640x320, podglad manualny i auto,
a nastepnie run z 20 obrazami, ramkami manualnymi i jednym zatwierdzonym [OK].
Sortowanie moglo zmienic pozycje obrazu, ale nazwa, geometria i znacznik
`[M|OK]` pozostaly zgodne. Sprawdzono otwarcie z historii, otwarcie z kontekstem
importu oraz wymuszone wznowienie bez zmiany manual -> auto. Brak wyjatkow Tk.
Czasy faz `*_idle` zawieraja celowe oczekiwanie testu i nie sa czasem obliczen.

Zakres zmian:

- Tryb swobodny odczytuje tylko jawnie wybrany/aktywny run. Zwykle wejscie,
  opis, motyw ani pusty panel eksportu nie wybieraja ostatniego runu z dysku.
  Wznowienie nie zamienia wybranego runu na nowszy znaleziony w historii.
- Historia jest odczytywana dla kontynuacji, nie dla opisow nowej pracy/auto.
- Cache XML miesci wiele runow (maksymalnie 256 i 200000 nazw obrazow),
  sprawdza mtime/rozmiar, nie zapamietuje bledow i odrzuca zmiane pliku w trakcie
  odczytu. Pusty zbior wejsciowy nie powoduje parsowania XML.
- Odtworzenie sesji konczy sie jednym odswiezeniem CTA i miniflow.
  Zmiana katalogu nie wykonuje drugi raz tych samych odswiezen.
- Zawijanie tekstu z dedykowanym kontenerem ma jednego wlasciciela; identyczne
  szerokosci nie wywoluja kolejnych zmian geometrii. Przewiniecie do sekcji
  jest scalane i wykonywane po geometrii zamiast wymuszac zagniezdzone update.
  Rysowanie paska splasha nie uruchamia ponownie kolejki zdarzen.
- Zasady i kolejnosc CTA kampanii pozostaly bez zmian. Guard trybu swobodnego
  nie pozwala tez pobierac modelu/kroku z projektu pozostalego w CAMPAIGN.

Weryfikacja: `python -m pytest tests -q` -> 291 passed, 37 subtests passed;
`tests/test_z2_free_entry_runtime.py` zawiera 54 nowe przypadki.
Testy obejmuja jawne zasoby i zachowanie wyszukiwania kampanii dla T02-T06
w pierwszej i kolejnej iteracji, cache, wznowienie i geometrie.
Nie jest to pelny test przejscia przez wszystkie bramki rzeczywistego projektu.
Nie uruchamiano modeli, kopiowania zewnetrznego importu ani produkcji nowego XML.
Zapis sesji i danych projektowych byl zablokowany; probki XML nalezaly do testu.
Artefakty: `output/z2_miniflow_audit_fixed_1000/summary.json`.

Kolejnosc decyzji uzytkownika nie zostala przebudowana. Polaczenie tworzenia XML
z automatycznym przejsciem do korekty pozostaje osobnym etapem UX.

## Najwazniejszy wynik

Z2 wykonuje przy samym otwarciu kosztowne wyszukiwanie poprzednich runow,
mimo ze ekran ma dopiero przedstawic wybor pracy automatycznej lub recznej.
Koszt powraca przy odswiezaniu opisow, przyciskow, motywu i wyborze drogi.
Dominujacym problemem nie jest ladowanie YOLO ani same kontrolki Tk.

| Operacja | Stan obecny, bez cProfile | Eksperyment bez niejawnego wyszukiwania |
| --- | ---: | ---: |
| Pierwsze otwarcie Z2 | 29,710 s | 2,794 s |
| Wybor pracy recznej | 26,677 s | 1,090 s |
| Dalej: sposob pracy -> wybor obrazow | 0,702 s | 0,597 s |
| Dalej: obrazy -> przygotowanie pracy recznej | 0,910 s, bez dalszych callbackow | nie mierzono |

Eksperyment zmienial funkcje tylko w pamieci osobnego procesu. Nie jest gotowa
poprawka: celowo pomijal automatyczne odkrywanie runu przy braku jawnego wyboru,
wiec wymaga osobnego dopracowania sciezek historii, importu i wznowienia.
Czasy sa lokalnymi obserwacjami diagnostycznymi, nie formalnym benchmarkiem.
Nie obejmuja importu wszystkich modulow podczas uruchamiania calej aplikacji.

## Dowod z profilera

W osobnej probie cProfile pierwsze otwarcie trwalo 61,489 s. Narzut profilera
jest znaczny; tego wyniku nie nalezy porownywac bezposrednio z czasami powyzej.

- `_get_preferred_annotation_run_dir`: 38 wywolan, 56,007 s lacznie wewnatrz nich.
- `_find_latest_annotation_run_for_input`: 12 wywolan, 52,729 s.
- Sprawdzanie zgodnosci runu z wejsciem: 1692 wywolania, czyli 12 x 141 runow.
- `_get_cached_run_xml_image_names`: 43,377 s lacznie.
- `_apply_free_mode_session_snapshot`: 52,089 s mimo `restore_preview=False`.
- Odroczone `apply_theme`: 5,245 s, z czego 4,698 s to odswiezenie kart drogi
  pracy, ponownie budujace kontekst i wyszukujace run.

Te czasy sa zagniezdzone i nie wolno ich sumowac.

`_get_cached_run_xml_image_names` po kazdym odczycie robi `cache.clear()`.
Przechowuje zatem tylko ostatni XML. Przejscie przez 141 runow usuwa wynik
poprzedniego odczytu, a nastepna runda znowu parsuje wszystkie XML.

Pliki:

- `auto_annotation_tool/gui/tab_annotation.py`: konstruktor i zastosowanie sesji.
- `auto_annotation_tool/gui/z2_miniflow_runtime.py`: `_get_preferred_annotation_run_dir`,
  `_should_skip_annotation_run_lookup_for_current_input`, `_set_workflow_step`.
- `auto_annotation_tool/gui/z2_run_lifecycle.py`: `_find_latest_annotation_run_for_input`.
- `auto_annotation_tool/gui/z2_run_io_runtime.py`: `_get_cached_run_xml_image_names`.
- `auto_annotation_tool/gui/z2_restore_workflow.py`: `_apply_free_mode_session_snapshot`.
- `auto_annotation_tool/gui/z2_panel_workflow.py`: odswiezanie miniflow i motywu.

## Miniflow: co aktualnie robi

| Sciezka | Przejscia do edytora | Zbedne lub ryzykowne operacje |
| --- | --- | --- |
| Reczna, nowa praca | Recznie -> Nowy run -> obrazy -> przygotowanie XML -> Dalej -> korekta | Historia odczytywana juz przy wyborze nowej pracy; dane podgladu budowane przed XML, potem ponownie odtwarzane z XML; dodatkowy modal i klikniecie po utworzeniu szablonu |
| Reczna, kontynuacja | Recznie -> Kontynuuj -> historia -> wybor runu -> korekta | Budowa historii nie jest ograniczona do wejscia w jej ekran; otwarcie runu najpierw rysuje widok, potem zmienia stan miniflow i odswieza go ponownie |
| Reczna, import | Recznie -> Import -> wskazanie/import XML -> korekta | Te same wspolne odswiezenia; walidacja zgodnosci XML z obrazami pozostaje konieczna |
| Automatyczna | Automatycznie -> obrazy -> podglad zakresu -> modal ustawien/modeli -> jawny start -> wynik/korekta | Powtarzana budowa stanu CTA i opisow; przygotowanie podgladu jest tylko odroczone przez `after(1)`, nie przeniesione poza watek GUI |

Przy przejsciu `_set_workflow_step` wywolywane sa osobno odswiezenia opisow,
stanu CTA, calego miniflow i przewijania do sekcji. Te funkcje ponownie
pytaja o run i dane, zamiast korzystac z jednego wyniku dla danego przejscia.
`_get_preferred_annotation_run_dir` po nieudanym dopasowaniu potrafi jeszcze
zwrocic ostatni run w ogole. To zagrozenie mieszania kontekstow, nie tylko koszt.

## Drugi problem: geometria i splash

Na 100 testowych obrazach 640x320 przygotowanie podgladu recznego nie
zakonczylo obslugi odlozonych zdarzen przez ponad 80 s. Probe przerwano.
Probkowanie stosu wielokrotnie wskazywalo:

`_draw_campaign_step2_splash_bar -> update_idletasks ->`
`_scroll_left_panel_to_widget -> update_idletasks -> Configure/zmiana wraplength`.

Miedzy probkami wystepowaly `_sync_left_panel_canvas_width`,
`_schedule_main_pane_layout_refresh` i `_sync_approve_hint_wraplength`.
Zagniezone wymuszanie zdarzen wraz z kolejnymi zmianami geometrii jest osobnym
problemem do wyizolowania. Samo usuniecie skanow XML nie jest dowodem jego naprawy.
Dokladny cykl zmieniajacy wymiary wymaga dalszego pomiaru zdarzen Configure.

Nie zmierzono pelnego wykonania nowego szablonu XML, detekcji ani wejscia
do edytora po ich zakonczeniu. Ich powtorne odczyty ustalono z kodu.

## Osobna niespojnosc wznowienia

`ensure_free_mode_session_preview_ready` po udanym odtworzeniu przy juz
ustawionym `workflow_route=manual` przechodzi do galezi ustawiajacej `auto`
i `auto_summary`. Potwierdzono to proba funkcji na izolowanym stanie.
Nie jest to przyczyna pierwszego otwarcia przy pustej sesji, ale wymaga testu
regresji przed optymalizacja wznowienia. Dla kontekstu kampanii funkcja konczy
sie przed odtwarzaniem i nie zmienia stanu, co rowniez sprawdzono.

## Zalecana kolejnosc, bez przebudowy kampanii

1. Rozdzielic odczyt aktywnego runu od jego odkrywania. Ekran wyboru i nowa
   praca swobodna nie powinny szukac runu. Kontynuacja/import robia to jawnie.
   Odczyt opisu lub nalozenie motywu nie moze uruchamiac skanowania XML.
2. Naprawic ograniczony cache wielu runow, walidowany sciezka, mtime i rozmiarem.
   Nie przechowywac bezterminowo wyniku zaleznosci O-AT ani decyzji bramki.
3. Jeden odczyt stanu i jeden zestaw odswiezen na przejscie. Ukrytych tabel
   historii/eksportu nie przeliczac do chwili ich otwarcia.
4. Ustalic cykl Configure i usunac ponowne wymuszanie `update` wewnatrz jego
   obslugi. Zmieniac wymiary/wraplength tylko gdy wartosc faktycznie sie zmienia.
   Zachowac realny postep oraz osobne zakonczenie przygotowania i pierwszego paintu.
5. Dopiero potem uproscic UX: przygotowanie nowej pracy recznej zakonczone
   jednym CTA tworzacym XML i otwierajacym korekte, bez ponownego ladowania tych
   samych anotacji. Nie pomijac zapisu, kontroli [OK], zgody na siec ani jawnego
   uruchomienia detekcji. Ta zmiana wymaga osobnej decyzji.

Nie zalecam przepisywania miniflow ani ogolnego wylaczenia odtwarzania Z2.
Tryb kampanijny wymaga przywracania konkretnego runu, zasobow i miejsca powrotu.

## Warunki bezpiecznego odbioru

- Swobodny: czysty start bez runu; Nowy/Kontynuuj/Import; auto z MP i bez MP;
  anulowanie dialogow; Wstecz/Dalej; ponowne wejscie do tej samej pracy.
- Duzy katalog obrazow oraz wiele runow historycznych; zerowe powtorne
  parsowania niezmienionego XML i brak odkrywania historii na pustym ekranie.
- Manuale, [OK], wybor obrazu, lista i widok canvas pozostaja spojne.
- Kampania: pierwsza i kolejna iteracja, wejscia T02/T03/T04 oraz naprawa
  z T05/T06; powrot do wlasciwej bramki i brak zmian kryteriow jej zatwierdzenia.
- Przejscie kampania <-> tryb swobodny bez przejecia cudzych sciezek,
  licznikow, modelu ani etapu.

## Bezpieczenstwo i artefakty pomiaru

Izolowany proces Tk, rzeczywiste klasy aplikacji i Z2, 100 wlasnych obrazow.
Zapis SESSION oraz plikow poza katalogiem diagnostycznym byl zablokowany.
Detekcja nie byla uruchamiana. Proby zapisu logu Z2 rowniez zablokowano.
Testowa kampania byla nieaktywna; nie ladowano i nie zapisywano projektu.

Artefakty lokalne, celowo poza Git:
`output/z2_miniflow_audit.py`, `output/z2_miniflow_audit/` (cProfile),
`output/z2_miniflow_audit_wall/`, `output/z2_miniflow_audit_experiment/`.
W eksperymencie wylaczono tez automatyczny GC, aby probkowanie stosu w watchdogu
nie zwalnialo obiektow Tk w watku pomocniczym. Dlatego podane porownanie sluzy
potwierdzeniu dominujacego mechanizmu, nie deklaracji gwarantowanego czasu.
