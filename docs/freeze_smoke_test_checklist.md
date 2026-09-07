# Checklista smoke testu przed freeze ALPR desktop

Stan na dzien: 2026-08-27.

Ten smoke test jest ostatnia reczna kontrola przed zamrozeniem SHA uzywanego w kampanii badawczej. Celem nie jest pelna eksploracja programu, tylko sprawdzenie kontraktow krytycznych dla pracy inzynierskiej: dataset MZ, eksport/import mobilny, raporty Android oraz porownywalnosc wynikow.

## 1. Start aplikacji

- [ ] Uruchom aplikacje z czystego procesu.
- [ ] Zaladuj projekt testowy.
- [ ] Sprawdz, czy graf kampanii pojawia sie bez pustego okna i bez tracebackow.
- [ ] Sprawdz, czy aktywna bramka, projekt i iteracja sa widoczne w pasku okna.

## 2. Balans klas MZ

- [ ] Wejdz w tor znakow MZ.
- [ ] Wybierz aktywny wariant datasetu znakow.
- [ ] Uruchom `Analizuj rozklad klas`.
- [ ] Sprawdz, czy modal pokazuje status mapy klas `data.yaml`.
- [ ] Sprawdz, czy widoczne sa oddzielnie `Liczebnosc`, `Roznorodnosc`, `Cel` i `Deficyt`.
- [ ] Zmien parametr celu uzupelnienia i kliknij `Przelicz`.
- [ ] Zapisz raport `before` jako CSV i JSON.

## 3. Uzuplenienie train

- [ ] Jezeli analiza wskazuje deficyty, wybierz tylko material `train`.
- [ ] Nie modyfikuj `val` i `test`.
- [ ] Jezeli uzupelniasz realnymi zrodlami, zapisz pochodzenie materialu.
- [ ] Jezeli uzupelniasz augmentacja train-only, sprawdz, czy manifest zapisuje limit wariantow na jedno zrodlo.
- [ ] Po uzupelnieniu ponownie uruchom analize MZ.
- [ ] Zapisz raport `after` jako CSV i JSON.
- [ ] Porownaj liczbe plikow i hash/rozmiar `val` oraz `test` przed i po operacji.

## 4. Eksport mobilny

- [ ] Otworz `Integracje -> Eksport mobilny`.
- [ ] Zaznacz osobno MP, MT i MZ: podsumowanie wskazuje „model mobilny”, schema `alpr.model.v1`.
- [ ] Zaznacz MT+MZ i MP+MT+MZ: podsumowanie wskazuje „kompletny pakiet ALPR”, schema `alpr.package.v1`.
- [ ] Sprawdź blokadę eksportu MP+MT i MP+MZ oraz komunikat wskazujący brakującą rolę.
- [ ] Sprawdz, czy nie da sie zaznaczyc dwoch modeli tej samej roli.
- [ ] Otwórz wykonawczy modal eksportu. Tytuł, przycisk po sprawdzeniu gotowości, okno zapisu i komunikat sukcesu rozróżniają model mobilny oraz pakiet ALPR.
- [ ] Sprawdz, czy kazdy model ma wlasne `imgsz`, format, kwantyzacje i kalibracje.
- [ ] Uruchom sprawdzenie gotowosci.
- [ ] Jezeli sa braki zaleznosci, uzupelnij je z poziomu modala wykonawczego.
- [ ] Wykonaj eksport stabilnego wariantu `LiteRT/TFLite FP32`.
- [ ] Sprawdź schemat wyniku: pojedynczy model ma `alpr.model.v1` i właściwe `role`; pakiet ma `alpr.package.v1`, wymagane `models.plate` i `models.character`, opcjonalne `models.vehicle`.
- [ ] Sprawdź fingerprinty, formaty, kwantyzacje, progi, `imgsz` i źródła kalibracji.
- [ ] Podmień pojedynczy MT na telefonie z konfiguracją MP+MT+MZ: MP i MZ pozostają z konfiguracji bazowej.

## 5. Import raportow Android

- [ ] Otworz `Integracje -> Import raportow`.
- [ ] Zaimportuj pojedynczy plik `.alprsession`.
- [ ] Zaimportuj kilka plikow raportow naraz.
- [ ] Zaimportuj JSON zawierajacy wiele raportow w polu `reports`.
- [ ] Sprawdz, czy duplikat tego samego pliku nie dubluje wyniku.
- [ ] Sprawdz, czy dwie repliki tej samej konfiguracji pozostaja widoczne jako osobne raporty.

## 6. Pelne dane raportu

- [ ] Sprawdz w przegladarce raportow liczbe rekordow preview.
- [ ] Sprawdz w indeksie eksperymentu pelna liczbe rekordow zrodla.
- [ ] Dla raportu wiekszego niz preview potwierdz, ze analiza backendowa czyta pelne `traces`.
- [ ] Potwierdz pelny odczyt `thermal`, `frame_flow`, `events` i `samples`.

## 7. Porownywalnosc eksperymentow

- [ ] Wybierz serie raportow z tym samym `series_id`.
- [ ] Sprawdz `scenario_id`.
- [ ] Sprawdz, czy guard sygnalizuje roznice w urzadzeniu, Androidzie, SHA aplikacji, runtime, delegate, rozdzielczosci, profilu rozpoznawania i fingerprintach modeli.
- [ ] Jezeli brakuje ground truth, sprawdz, czy jakosc jest oznaczona jako niedostepna, a nie jako `0`.

## 8. Freeze

- [ ] Uruchom testy jednostkowe.
- [ ] Uruchom kompilacje zmienionych modulow Python.
- [ ] Sprawdz `git diff --check`.
- [ ] Wykonaj commit.
- [ ] Zapisz SHA freeze w dzienniku albo tagu.
- [ ] Od tego momentu nie zmieniaj pipeline'u, kontraktow raportu, datasetu ani algorytmow w ramach tej samej serii eksperymentow.
