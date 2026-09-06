# Dataset efektywnie użyty do treningu

Identyfikator w profilu kandydata i paczce mobilnej opisuje ten sam dataset
niezależnie od rozmiaru modelu. Liczy się zawartość i podział danych, nie
nazwa modelu ani katalogu.

## Kolejność zapisu

Przed startem workera powstaje snapshot wejściowy. Po utworzeniu loaderów,
które mogą naprawić JPEG-i, callback `on_pretrain_routine_end` ponownie
potwierdza fingerprint przed pierwszą epoką. Wynik staje się
`training_dataset_snapshot` używanym przez eksport, profil i kontrolę resume.
Snapshot wejściowy jest zachowany w `training_dataset_input_snapshot`.
`dataset_preparation` zapisuje identyfikatory wejścia i efektywnych danych,
czas weryfikacji oraz informację, czy zawartość zmieniła się podczas
przygotowania. Poza tym snapshoty nadal nie są przeliczane z aktualnego
katalogu przy zwykłym eksporcie zakończonego treningu.

Wznowienie wymaga zgodności z efektywnym snapshotem zapisanym wcześniej.
Jeżeli przygotowanie danych przy resume ujawni zmianę, trening jest
zatrzymywany przed kolejnymi epokami. Etykiety i odmienne obrazy nie są
uznawane za zgodne tylko z powodu identycznej nazwy datasetu.

## Potwierdzona korekta historyczna n/s

W treningu `20260905_223437` (YOLO26n) dwa pliki `AS93_001.jpg` i
`CG0898A_001.jpg` zostały naprawione przez Ultralytics przed pierwszą epoką.
Historyczny snapshot został jednak zapisany wcześniej. Trening
`20260906_103421` (YOLO26s) otrzymał już naprawione pliki.

- Snapshot wejściowy n: `DS-MT-6EDC999C5B`.
- Dataset po przygotowaniu, użyty przez n i s: `DS-MT-FC1A2BF3BD`.
- Oba mają 800/100/100 obrazów i 2000 plików obrazów oraz etykiet.
- SHA aktualnego splitu: `5e742aaaa5e69e8335419b3a015fcc826f188a3fedbe8f3973543761c9cc22aa`.
- Wirtualne przywrócenie SHA i rozmiarów tylko dwóch zachowanych oryginalnych
  JPEG-ów odtwarza poprzedni SHA: `9e9ff53b53ebe64aaccd3cd7b5ded92800354a6bfc7556b0bde996493ed1d726`.

Tak potwierdzona korekta zachowuje pierwotny snapshot i jawny dowód naprawy;
oznaczenie efektywnego snapshotu to `reconstructed_from_training_artifacts`.
Operacyjne pola datasetu w historii, profilu, metadanych i paczce wskazują
wspólny identyfikator. Pierwotny identyfikator może pozostać wyłącznie
w jednoznacznie nazwanych polach audytu/wejścia. Korekta manifestu nie wymaga
ponownej konwersji: pliki wariantów modeli zachowują swoje SHA-256.

## Weryfikacja

401 testów i 44 podprzypadki. Regresje odtwarzają naprawę JPEG funkcją
Ultralytics, wspólny identyfikator kolejnych modeli MT/MZ, trwałość śladu
wejściowego, odrzucenie zmienionych danych przy resume i rozróżnienie różnych
etykiet w tak samo nazwanym datasecie. Wykonano także rzeczywiste krótkie
treningi POSE i DETECT na odizolowanych danych z JPEG-em wymagającym naprawy.
W obu przypadkach zapis zakończonego treningu odpowiada danym po naprawie.
