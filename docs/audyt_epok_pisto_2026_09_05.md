# Audyt epok modeli pisto w eksporcie mobilnym

Data: 2026-09-05. Audyt odczytowy, bez zmian wag, historii treningow ani danych projektu.

## Wynik

Wysokie metryki modelu po jednej dodatkowej epoce sa zapisane takze w jego
checkpointcie. Nie jest to model wytrenowany od zera przez jedna epoke.
Problem dotyczy odtwarzania i prezentacji historii treningu.

| Run projektu pisto | Typ | Ostatni trening, wykonano | Wczesniejszy trening | Razem po korekcie |
| --- | --- | ---: | ---: | ---: |
| `20260802_160305` | MZ | 1 | 130, `20260722_151706` | 131 |
| `20260721_194742` | MZ | 56, przy planie 100 | 50, `20260714_223004` | 106 |
| `20260719_192455` | MT, przerwany | 1 | 10, `20260718_200612` | 11 |

Ostatni wiersz jest kontrola rodowodu przerwanego runu, nie nowym kandydatem
do eksportu. Nie zmieniono filtrowania dostepnosci modeli.

Pozostale zakonczone runy pisto zachowaly liczby wykonanych epok:
`20260713_204401`: 2; `20260714_223004`: 50; `20260718_200612`: 10;
`20260721_154327`: 100; `20260721_155258`: 300; `20260722_151706`: 130.

## Dowody

Zrodla znajduja sie w
`Workspace/9_projects/pisto_21600B/5_training_runs/`:

- `training_history.json`: oba wymienione zakonczone MZ maja `lineage_mode=new`
  i pusty `parent_run_id`, ale `base_model` zawiera dokladna sciezke
  `train/weights/best.pt` odpowiedniego rodzica.
- `20260802_160305/train/args.yaml`: model wejsciowy to checkpoint
  `20260722_151706`, plan ostatniego treningu to 1 epoka.
- `20260802_160305/train/results.csv`: 1 wiersz, mAP50 = 0.98079,
  mAP50-95 = 0.86755. `best.pt.train_metrics` potwierdza te liczby;
  `train_results.epoch` zawiera `[1]`.
- Historia GUI tego runu podaje 0.9809110163 i 0.8677799244. Roznica wobec
  CSV/checkpointu jest niewielka; obydwa zrodla potwierdzaja wysoki wynik.
  Audyt nie przepisuje tych metryk.
- `20260722_151706/train/results.csv` i `best.pt.train_results` maja
  130 epok. Checkpoint podaje start z `yolo26n.pt`.
- `20260721_194742/train/results.csv`, `metrics_history` i
  `best.pt.train_results` koncza sie na epoce 56, mimo
  `current_epoch=100` i `epochs=100` w historii. Sam `best.pt` ma
  usuniety licznik `epoch=-1`, dlatego nie jest on dowodem zera epok.

Inspekcja checkpointow odbyla sie lokalnie na CPU, bez inferencji ani treningu.
Podczas kontrolnego odczytu listy kandydatow wylaczono zapis uzgodnien
`TrainingHistory._save`, aby samo badanie nie zmienialo stanu projektu.

## Przyczyny i poprawka

1. Odczyt rodowodu przechodzil do rodzica tylko dla jawnego `fine_tune`.
   Starsze runy z `base_model=.../best.pt` trafialy do niepelnej historii,
   mimo ze lokalna historia zawierala ich rodzica. Odtwarzanie teraz uznaje
   jednoznaczne dopasowanie pelnej sciezki checkpointu do historii.
   Sam identyfikator w nazwie pliku nie wystarcza. Sprzeczne zamrozone hashe,
   niejednoznaczne dopasowania i wznowienie tego samego runu nie sa sumowane.
2. Tabela zamieniala znane minimum epok na zwykla liczbe. Teraz niepelna
   historia ma zapis `>= N` (w GUI znak matematyczny) i wyjasnienie w chmurce.
   Profil rozdziela sume i ostatni trening.
3. Historyczny `current_epoch` mogl zawierac plan zamiast wykonania.
   Dla zakonczonych starszych runow bez snapshotu wyniku pierwszenstwo maja
   rzeczywiste epoki w CSV i historii metryk. Nie zmieniono logiki treningu
   ani licznika zamrozonego przez nowe runy.

`total_epochs` nadal oznacza naklad wykonanych treningow w rodowodzie,
bez wstepnego treningu bazowego YOLO. Nie jest to suma epok tylko do
wybranego `best.pt`, ani dowod, ze wszystkie te epoki poprawily wynik.
To rozroznienie jest zgodne z kontraktem provenance v2.

Wysokie mAP nie oznaczaja automatycznie porownywalnosci modeli trenowanych
i walidowanych na roznych zbiorach. Do takiego porownania sluzy wspolny
zbior rankingowy; tego audyt nie zmienia.

## Testy

- Legacy 130 + 1 oraz lancuch trzech treningow, bez zapisu do historii.
- Brak rodzica, podobne nazwy plikow, niejednoznaczna sciezka, sprzeczne hashe.
- Early stopping 56/100 i nieaktualny licznik w obie strony.
- Zachowanie obslugi wznowienia, cykli, snapshotow i brakujacych rodzicow.
- Etykieta znanego minimum, opis 131/1 i spojnosc manifestu kandydata.
