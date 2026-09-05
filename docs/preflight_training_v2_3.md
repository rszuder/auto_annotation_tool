# Przygotowanie treningu: responsywnosc i bezpieczenstwo watkow (v2.3)

Data weryfikacji: 2026-09-05.

Wytyczne: `handoff_patch_desktop_v2_3_preflight_responsiveness.md` z repozytorium
dokumentacji. Zakres wdrozenia obejmuje aplikacje desktopowa.

## Przeplyw

1. Start sprawdza wybrany wariant, istnienie i podstawowe pola `data.yaml`,
   zgodnosc toru, metadane modelu i parametry formularza.
2. Sprawdzenie formularza nie enumeruje obrazow, nie hashuje danych i nie
   wczytuje checkpointu. Liste wariantow pobiera z juz wyswietlonego wyboru.
   Zapisany stan nieudanej augmentacji nadal blokuje trening.
3. Aplikacja zajmuje istniejaca blokade `z4.training.run`, odlacza referencje
   anotatora Z2 w glownym watku i pokazuje status przygotowania treningu.
4. Watek przygotowania zwalnia odlaczone modele oraz pamiec CUDA/Python.
   Nie odwoluje sie do metod zwalniajacych zasoby zakladek GUI.
5. `trainer.start_training()` wykonuje pelna walidacje datasetu jeden raz.
   Nieznany model uzytkownika jest sprawdzany w tym watku. Dalej wykonywane sa
   istniejace kroki przygotowania pretrained, snapshotu datasetu, SHA-256,
   kontroli wznowienia, utworzenia runu i uruchomienia workera.
6. Wynik trafia przez kolejke do glownego watku. Dane pelnej walidacji moga
   odswiezyc liczniki i cache UI, ale nie zastepuja hashow provenance.

Wybor toru i wariantu nadal ustawia katalog historii. Samo klikniecie Start
nie tworzy ponownie trenera ani nie laduje calej historii.

## Ochrona interfejsu i zasobow

- Callback watku roboczego nie wywoluje Tkintera. Odbior kolejki i operacje na
  widgetach odbywaja sie w glownym watku.
- Zniszczenie hosta zamyka kolejke, usuwa oczekujace callbacki i blokuje nowe.
  Odroczone callbacki glownego watku tez sprawdzaja istnienie hosta.
- Jezeli po zniszczeniu hosta przygotowanie zdazy uruchomic trening i nie moze
  dostarczyc wyniku do UI, uruchomiony trener jest zamykany.
- Kolejka ma limit pracy na jeden obieg; podczas przygotowania jest odpytywana
  czesciej niz w bezczynnosci.
- Z2 oraz detekcja i ranking OCR Z3 korzystaja z tej samej blokady operacji co
  trening. Blokada jest utrzymywana takze po przejsciu z przygotowania do treningu.
- Blad przygotowania odblokowuje Start, jezeli konfiguracja nadal jest poprawna.
  Blad uruchomienia workera po utworzeniu runu zachowuje status `FAILED` i opis
  bledu. Uchwyt `worker_stdout.log` jest wtedy zamykany.
- Log procesu otrzymuje wpis przy zmianie etapu, a nie przy kazdej zmianie procentu.
  Kokpit w czasie przygotowania nie przelicza ponownie opisow datasetu i modelu.

## Dowody automatyczne

```powershell
python -m pytest tests/test_z4_async_training_preflight.py tests/test_model_training_provenance.py tests/test_mobile_export_project_sources.py tests/test_mobile_report_full_rows.py tests/test_app_hardware_scan.py -q
```

Wynik: **64 passed**. Srodowisko: Windows 10 Home, build 19045, Python 3.12.

Testy przygotowania obejmuja:

| Przypadek | Sprawdzenie |
| --- | --- |
| Wolny preflight | Zdarzenie `after(100, ...)` wykonuje sie przed zakonczeniem sekundowej walidacji; wykorzystano rzeczywista petle zdarzen Tcl. |
| Kolejka UI | Callback dodany w workerze nie wykonuje sie w nim; drain wykonuje go raz w glownym watku. |
| Pelna walidacja | Rzeczywisty preflight trenera wykonuje `validate_dataset` raz, poza watkiem GUI. |
| Start i wznowienie | Kolejne klikniecie nie uruchamia drugiego przygotowania. |
| Blad async | Flaga przygotowania i referencja watku sa czyszczone, blokada zwalniana, Start ponownie dostepny. |
| Blad spawn | Run pozostaje w historii jako `FAILED`, zachowuje snapshoty i opis bledu; plik stdout jest zamkniety. |
| Zamkniecie hosta | Wynik nie aktualizuje zniszczonego GUI; spozniony udany start jest zamykany. |
| Modele Z2/Z3 | Odpiecie referencji odbywa sie w glownym watku, unload w tle; wspolna blokada odrzuca konkurencyjne operacje. |
| Kontrakty danych | Nadal sprawdzany jest wybor wariantu, zgodnosc toru i stan gotowosci augmentacji. |

Testy uzywaja tymczasowych katalogow. Nie prowadza treningu ani zmian w projektach
`pisto` i `demo`. Test nieudanego spawn korzysta z rzeczywistego tworzenia runu,
snapshotow i hashow, ale celowo zastepuje uruchomienie procesu bledem.

Testowy interpreter Tcl jest utrzymywany w glownym watku przez caly zestaw,
a callbacki sa usuwane po kazdym tescie. Zapobiega to zniszczeniu kolejnych
testowych interpreterow przez garbage collector uruchomiony w obcym watku.

## Proby Windows 11: do wykonania

Testy automatyczne nie sa potwierdzeniem zakonczenia audytu na Windows 11.
Na dostepnej maszynie jest Windows 10; nie wykonano wymaganych prob rzeczywistego
treningu na malym i duzym datasecie na Windows 11.

Na docelowej maszynie wykonac oba scenariusze, po 1-2 epoki, ze swiadomie
wybranym datasetem i modelem. Podczas przygotowania przesuwac okno, zmieniac
jego rozmiar i przelaczac zakladki. Zapisac identyfikatory datasetu/modelu/runu,
wersje systemu i Pythona oraz sposob wyjscia z aplikacji.

Zachowac log z fazami `[PREFLIGHT]`, ewentualny `fatal_crash.log`,
`worker_stdout.log` i raport zasobow runu. Kryterium odbioru jest zachowanie
responsywnosci podczas przygotowania, nie arbitralny limit czasu hashowania.
Do czasu tych prob status wdrozenia: **testy automatyczne zakonczone,
weryfikacja Windows 11 oczekuje**.
