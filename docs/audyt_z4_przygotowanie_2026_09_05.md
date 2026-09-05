# Z4: przygotowanie PZ1 i PZ2

Data: 2026-09-05. Zakres: otwarcie Z4, pierwsza budowa PZ2, przekazanie
wariantu z PZ1, odswiezanie sprzetu i podsumowania datasetu.

## Przyczyny opoznien

- Po pokazaniu PZ1 odroczony callback obliczal rekomendacje PZ2. Uruchamial
  PyTorch/CUDA, mimo ze podzakladka treningu nie byla jeszcze zbudowana.
  Samo dodanie `after` nie usuwalo blokady glownego watku.
- Lista wariantow sprawdzala `Path.is_file()` oddzielnie dla kazdego obrazu
  w kazdym splicie. W profilu budowy PZ2 ta sciezka miala okolo 11000
  kontroli plikow; liczniki zajely 2,72 s z 3,79 s profilowanej budowy PZ2.
- Podsumowanie materialu czytalo wszystkie etykiety w watku Tk.
  W probie 1000 obrazow toru znakow profil przypisal tej analizie 0,86 s.
- Odswiezenia ustawien oraz zmiany modelu automatycznie stosowaly zalecane
  batch/imgsz/LR. Byla to dodatkowa praca i ryzyko nadpisania ustawien.
- Powtorne przypiecie tego samego katalogu historii tworzylo nowy obiekt
  trenera, choc nie zmienial sie kontekst danych.

## Implementacja

### Sprzet i ustawienia

Z4 czyta potwierdzone profile GPU z centralnego cache aplikacji. Istniejacy
skan sprzetu zbiera dodatkowo VRAM i przekazuje profile przez kolejke.
Publikacja odbywa sie na watku UI dopiero po sukcesie. Blad lub timeout
nie nadpisuje poprzednich profili. Zwykle otwarcie Z4 nie uruchamia skanu.

Brak sprawdzenia sprzetu nie oznacza wykrycia CPU. Rekomendacja jest wtedy
niedostepna z wyjasnieniem o menu Konfiguracja. Jawny wybor CPU nadal pozwala
obliczyc rekomendacje bez sprawdzania CUDA. Pomiar VRAM i wybor GPU sa
wspolne z reszta aplikacji; nie dodano drugiego niezaleznego skanera.

PZ1 nie przygotowuje niewidocznych rekomendacji PZ2. Budowa widoku, wybor
wariantu oraz odswiezanie modelu nie stosuja zalecen automatycznie.
Uzytkownik nadal moze wybrac **Zastosuj rekomendowane**. Gdy trwa analiza
datasetu albo brak potwierdzonych danych sprzetu, ta operacja nie wpisuje
niepelnych wartosci do formularza. Epoki pozostaja ustawieniem operatora.

Ponowne uzycie tego samego katalogu runow zachowuje istniejacy trener.
Odswiezenie historii z dysku pozostaje dostepne, podobnie jak zmiana toru.

### Dataset

Liczniki splitow korzystaja z `os.scandir` i metadanych listowania katalogu,
bez osobnego `stat` dla kazdego zwyklego obrazu na Windows. Licza te same
pliki i rozszerzenia w tych samych katalogach train/val/test. Cache nadal
sprawdza zmiany katalogow; blad odczytu nie jest utrwalany jako zero.

Pelny profil materialu jest liczony w osobnym workerze. Czytnik otrzymuje
sciezke YAML i wlasny stan, bez widgetow, zmiennych Tk ani kontekstu kampanii.
Aktualizacja UI przechodzi przez istniejaca kolejke Z4, zabezpieczona przy
zamykaniu okna. Jednoczesnie pracuje najwyzej jeden czytnik profilu.

Podsumowanie ma neutralny status analizy, a nie falszywe zera lub ocene
zbyt malego zbioru. Sprawdzana jest sciezka oraz sygnatura odczytu; wynik
dla porzuconego datasetu nie trafia do aktualnego widoku. Zmiana wyboru
powoduje przygotowanie aktualnego profilu po zakonczeniu poprzedniego.
Sygnatury profilu korzystaja z mtime w nanosekundach.

**Podsumowanie prezentacyjne nie zastepuje kontroli przed treningiem.**
Nie zmieniono walidacji danych, manifestow MZ, kontraktow treningu,
provenance, checkpointow, mechanizmu resume ani zasad zatwierdzania T06.

## Pomiary lokalne

Osobny proces z rzeczywistymi AutoAnnotationApp i TrainingTab, Windows/Tk,
z zapisem ograniczonym do diagnostycznego `output/`. Siec, worker treningu
i zapisy do danych projektowych byly zablokowane. Pomiar wykonano bez
cProfile, poza wyraznie oznaczonymi profilami diagnostycznymi.

| Faza | Przed | Po |
| --- | ---: | ---: |
| Samo otwarcie Z4/PZ1 | 0,71 s | 0,80-0,90 s w koncowych probach |
| Faza po otwarciu, z zegarem ustawionym na 2 s | 3,79 s | 2,00 s |
| Pierwsza budowa pustego PZ2 | 2,29 s | 0,77 s |
| PZ2 z wybranym wariantem MT, 1000 obrazow | brak porownywalnej proby przed | 1,00 s |
| PZ2 z wybranym wariantem MZ, 1000 obrazow | brak porownywalnej proby przed | 0,81-1,34 s |
| Przyjecie wskazanego wariantu PZ1 | brak pomiaru przed | 0,08-0,12 s |
| Wybor juz zbudowanej podzakladki | okolo 0,01 s | okolo 0,01 s |

Najwazniejszym wynikiem dla PZ1 jest usuniecie blokady **po** pokazaniu karty,
nie przyspieszenie samego konstruktora. Fazy `*_idle` zawieraja celowy czas
oczekiwania testu i nie sa czystym czasem obliczen. Pomiar wyboru podzakladki
nie obejmuje wszystkich pozniejszych odswiezen/paintu. Wyniki nie stanowia
benchmarku reprezentatywnego dla wszystkich maszyn i wielkosci projektow.

W obu torach test przygotowal 1000 obrazow i 1000 anotacji: train 800,
val 100, test 100. Po przejsciach PZ1/PZ2 i powrotach sprawdzono:

- ten sam wybrany wariant i prawidlowy typ danych;
- obecnosc wariantu na liscie PZ2;
- zachowanie ustawien: epoki 123, batch 7, imgsz 416, LR 0,002;
- pelne liczniki obrazow i anotacji po analizie w tle;
- brak wyjatkow callbackow i brak importu PyTorch/Ultralytics przy otwieraniu.

Artefakty lokalne, poza Git: `output/z4_entry_audit.py`, katalogi
`z4_entry_baseline`, `z4_entry_baseline_wall`, `z4_entry_fixed_wall`,
`z4_entry_final_plate`, `z4_entry_final_char` i posrednie proby profilowane.

## Weryfikacja i granice

`python -m pytest tests -q -rs`: **353 passed, 37 subtests passed**.
Nowe testy Z4 obejmuja cache licznikow, bledy odczytu, profil w tle,
zmiane i wyczyszczenie datasetu w trakcie analizy, blad startu watku,
zachowanie parametrow oraz CPU/GPU. Rozszerzono testy centralnego skanu
o publikacje VRAM, zachowanie poprzedniego wyniku przy bledzie i watek UI.
Kompilacja zmienionych modulow i `git diff --check`: poprawne.

Nie wykonywano rzeczywistego treningu ani wznowienia checkpointu; ich
mechanizmy sprawdzono dostepnymi regresjami. Nie przeprowadzano calego
cyklu T01-T06 rzeczywistego projektu ani testow na drugiej maszynie Win11.
Nie przebudowywano calego layoutu ani rankingu. Dalsze koszty to m.in.
tworzenie kontrolek, odswiezanie historii/rankingu oraz listowanie katalogow
wariantow; nie sa one zerowe.
