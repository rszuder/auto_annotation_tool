# Z3: wydajnosc wejscia i podzakladek

Data: 2026-09-05. Zakres: pierwsze otwarcie Z3, budowa PZ2/PZ3,
otwarcie wskazanego wyniku PZ1 i ponowne odwiedzanie podzakladek.

## Diagnoza

1. `z3_detection_model_ui.get_available_devices` importowal PyTorch i pytal
   sterownik CUDA podczas budowania PZ2. Istnial juz centralny, buforowany
   wykaz urzadzen aplikacji, ale Z3 go nie uzywalo.
2. Odswiezenie stanow przyciskow oraz licznikow szukalo ostatniego preview
   przy braku aktywnego wyniku. Podczas czyszczenia kontekstu swobodnego
   zostal przez to wybrany stary zestaw 307 cropow. Samo otwarcie podzakladki
   zaczynalo pracowac na danych, ktorych operator nie wybral.
3. Wyszukiwanie runow wykonywalo `rglob("*")` i `is_dir()` dla kazdego
   pliku, w tym wszystkich cropow. Profil pierwszego wejscia wykazal ponad
   13000 wywolan `stat` oraz 42 odczyty JSON.
4. Liczniki eksportu zapisywaly te sama wartosc `preview_dir_var`, uruchamiajac
   trace i nastepne odswiezenia. W profilu wejscia callback zmiany sciezki
   zostal wykonany 10 razy.

## Implementacja

- UI Z3 korzysta z `app.get_available_yolo_devices(allow_probe=False)`.
  Nie wykonuje wlasnego rozpoznawania CUDA. Brak wykonanego pomiaru sprzetu
  nie jest przedstawiany jako dowod braku GPU. Sprawdzanie przy rzeczywistej
  detekcji pozostaje; wybrany GPU z centralnego wykazu jest zachowany.
- Tryb swobodny nie wybiera najnowszego runu w ramach zwyklego odswiezenia.
  Jawny wynik PZ1 pozostaje dostepny. Wyszukiwanie cropow zgodnych ze zrodlem
  nadal dziala, ale wymaga wskazanych XML i obrazow.
- Flaga trybu swobodnego ma pierwszenstwo nad projektem pozostawionym
  w menedzerze kampanii. Nie przejmuje wtedy zapisanego preview projektu.
- Kampania zachowuje pierwszenstwo zapisanego preview, dotychczasowe
  wyszukiwanie awaryjne i sprawdzanie zgodnosci/minimum. Skan wyszukuje teraz
  `metadata.json`, bez sprawdzania typu kazdego pliku obrazu.
- Odczyt licznikow nie zapisuje ponownie tej samej sciezki preview.

Nie zmieniono kolejnosci CTA, bramek, pipeline OCR/YB/YS, geometrii ramek,
kryteriow perfect, progow detekcji ani danych rzeczywistych projektow.

## Pomiary

Osobny proces, rzeczywiste klasy AutoAnnotationApp i CharacterAnnotationTab,
Tkinter na Windows, odczyt zastanych katalogow; zapis do projektow/sesji
zablokowany. Liczby ponizej pochodza z prob bez cProfile.

| Operacja | Przed | Po, lokalne proby |
| --- | ---: | ---: |
| Pierwsze otwarcie Z3 | 3,278 s | 0,971-1,408 s |
| Pierwsza budowa PZ2 | 6,397 s | 0,881-1,024 s |
| Pierwsza budowa PZ3 | 0,721 s | 0,116-0,137 s |
| Wybor recznego zrodla w PZ1 | nie mierzono | 0,045 s |
| Walidacja XML i obrazow, 1000 pozycji | nie mierzono | 0,185 s |
| Otwarcie jawnego wyniku PZ1, 1000 cropow | nie mierzono | 0,483 s |
| Ponowne wejscie do tego samego preview | nie mierzono | 0,007 s |

Czasy otwarcia wyniku i wyboru podzakladek nie oznaczaja zakonczenia
wszystkich pozniejszych callbackow ani pelnego paintu. W probie 1000 cropow
pierwszy callback renderowania mial 0,794 s; nie jest on czasem samego odczytu.
Fazy `*_idle` zawieraja celowe oczekiwanie testu (1-2 s). Nie sa pomiarem
czasu ladowania. To lokalna diagnoza, nie formalny benchmark wielu maszyn.

Testowy zestaw zawieral 1000 cropow 320x100 z ramka manualna i wymuszonym
ukladem jednorzędowym. Przejscia PZ1 -> PZ2 -> PZ3 -> PZ2 zachowaly liczbe
rekordow; sprawdzono geometrie i pochodzenie ramki oraz override ukladu.
Nie bylo wyjatkow callbackow. Po otwarciu wszystkich pustych podzakladek
modul `torch` nadal nie byl zaimportowany.

Artefakty lokalne (katalog `output`, poza Git):

- `z3_entry_baseline/`: profile funkcji i pierwsze pomiary.
- `z3_entry_baseline_wall/results.json`: pomiar przed zmianami bez profilera.
- `z3_entry_fixed_wall/results.json`: pierwsza proba po zmianach.
- `z3_entry_fixed_fixture/results.json`: proba 1000 cropow i powrotow.
- `z3_entry_audit.py`: izolowany skrypt pomiarowy z blokada zapisu danych.

## Regresja i granice

`tests/test_z3_entry_runtime.py`: 30 przypadkow. Obejmuja izolacje zrodel,
brak niejawnego wyboru runu, korzystanie z cache urzadzen, zachowanie GPU,
odtwarzanie zasobu kampanii, zgodnosc wyszukiwanych cropow i dostep do PZ3
uzalezniony od pracy w biezacej iteracji.

Pelny zestaw: `python -m pytest tests -q -rs` -> **321 passed,
37 subtests passed**, bez pominiec w koncowej probie. Wczesniejszy przebieg
pominąl 12 testow przy bledzie inicjalizacji Tcl; powtorzenie po zamknieciu
okna diagnostycznego przeszlo w calosci. Nie uznano pominiec za sukces.
Kompilacja zmienionych modulow oraz `git diff --check`: poprawne.

Nie uruchamiano OCR/YOLO, eksportu, rzeczywistego wyodrebniania nowych
cropow ani pelnego cyklu wszystkich bramek projektu. Testy kampanii sa
regresjami kodu z kontrolowanym stanem, nie pelnym testem operatorskim.
