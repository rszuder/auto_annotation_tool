# Import Akwizycji Androida

Implementacja desktopowa rozdziału 15 dokumentu
`ALPR_architektura_wymiany_Android_Desktop_2026-09-09.md`.

W Z3, na ekranie wyboru źródła, przycisk **Akwizycja Androida** otwiera
galerię paczek ze schematem `alpr_crop_session_v1` w `session.json`.
Nie wymaga zmiany rozszerzenia ZIP ani konwersji na `.alprsession`.

## Galeria i ocena

- Grupowanie ignoruje wielkość liter (`uppercase.v1`), zachowuje spacje
  i pozostałe znaki. `AAA` i `aaa` tworzą jedną grupę, `AA A` pozostaje osobno.
- Pierwszy crop w kolejności manifestu jest obrazem bazowym grupy.
  Oryginalne cropy, teksty i ich obserwacje pozostają zachowane.
- Galeria pokazuje bazowy obraz i ramki MZ, liczbę obserwacji oraz pełne
  metadane, w tym encje, kontekst sceny, czas, źródło, modele i telemetrię.
- Pole GT jest początkowo puste. Operator zapisuje szkic, potwierdza GT
  dla obrazu bazowego lub odrzuca grupę. Zmiana GT cofa potwierdzenie do szkicu.
- Review ma osobny schemat `alpr.mobile_crop_review.v1`. Plik jest zapisywany
  atomowo w `acquisition_reviews/<sha256>.json` pod katalogiem pracy Z3.
  Powiązanie obejmuje hash źródła, session ID i politykę grupowania.

## Przekazanie do Z3

Akcja **Zatwierdzone do anotacji** tworzy nowy katalog `mobile_crops_*`:

```text
mobile_crops_*/
  source.zip                 # niezmieniona kopia całej paczki Androida
  acquisition_review.json    # decyzje użyte przy imporcie
  acquisition_import.json    # pochodzenie i ograniczenia materiału
  metadata.json              # rekordy edytora Z3
  images/plate_000001.jpg     # bajty bazowego JPEG bez ponownej kompresji
```

Do edytora trafiają wyłącznie grupy z potwierdzonym GT. Ramki znaków są
przeliczane z zakresu 0–1 na piksele rzeczywistego obrazu. Źródłowe ramki
i etykiety są zachowane w `mobile_acquisition.crops`; robocze etykiety
mają wielkie litery. Predykcja nie jest automatycznie uznawana za GT.
Potwierdzenie numeru nie zatwierdza poprawności geometrii: Z3 nadal ocenia
ramki i zgodność odczytu z GT, a operator może je poprawiać.

Importer nie odgaduje GT z nazw plików ani nie dopisuje prób MT, detekcji
negatywnych, wywołań modelu lub wyników benchmarku. Czytnik raportów
badawczych odrzuca tę paczkę również po zmianie rozszerzenia i kieruje do Z3.
Selekcja niepustych MZ uniemożliwia ocenę jakości całego pipeline'u.
Czas źródłowy jest zachowany, także gdy pochodzi z odtworzonego cache RAM.

Eksporty datasetu YOLO i klasyfikacji przenoszą pochodzenie Akwizycji.
Przy podziale wykonywanym w Z3 rekordy z tym samym session ID pozostają
w jednym zbiorze. Proporcje są przybliżone; pojedyncza sesja może dać pusty
zbiór walidacyjny i testowy. Późniejszy niezależny podział w innym narzędziu
musi również respektować pole `dataset_group`.

## Walidacja

Czytnik sprawdza schemat, bezpieczne i jednoznaczne nazwy ZIP, obecność
obrazów, ich format JPEG i wymiary, ramki 0–1 oraz spójność obserwacji.
Limity: 50 000 wpisów, 2 GiB po rozpakowaniu, 32 MiB manifestu,
20 MiB i 25 milionów pikseli na obraz. Nie wykonuje ogólnego `extractall`.
Hash źródła wiąże review z konkretną paczką; nie stanowi podpisu producenta.
Brak `entry_sha256` w kontrakcie Androida nie jest uzupełniany fikcyjnymi danymi.

Testy: `tests/test_mobile_acquisition.py` oraz natywny probe GUI
`tests/gui_mobile_acquisition_probe.py`. Fixture odzwierciedla lokalny
`CropSessionStore.java`, a geometrię zweryfikowano względem `PlateCharacter.java`.
Nie jest to test eksportu uruchomionego na fizycznym telefonie.
