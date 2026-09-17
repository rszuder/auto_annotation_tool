# Opcjonalne etykiety różnorodności próbki

Handoff: `handoff_optional_sample_diversity_labels.md` z Pobranych.
Baza: `4fc67cc70048b5c3627de1cb4acbd39c3e37ceba`, `feature/evaluation-registry`.

W RAW sample-selection operator tworzy własne etykiety (1–60 znaków,
bez duplikatów przy porównaniu case-insensitive). Panel wyświetla najwyżej
trzy wiersze naraz, z przewijaniem pozostałych. Jeden checkbox oznacza aktywną
etykietę; można wyłączyć wszystkie. Menu `⋯` pozwala zmienić nazwę lub usunąć
etykietę. Nie ma gotowego słownika ani wymaganych liczebności.

Spacja nadal przełącza membership. Dodając obraz, nadaje aktywną etykietę,
jeśli została wskazana. Usunięcie obrazu z próby usuwa jego etykietę. Operacja
grupowa „Dodaj do próby” nadaje aktywną etykietę także już wybranym obrazom
z zaznaczenia. Menu listy „Ustaw etykietę” działa tylko na wybranych członkach
próby i nie zmienia membership. Usunięcie kategorii pozostawia jej obrazy
w próbie, bez etykiety. Etykiety nie są klasami modelu ani Ground Truth.

Lista pozostaje `tk.Listbox`, z kolumnami monospace: stan, etykieta, plik.
Długie etykiety są skracane na liście; pełne nazwy pozostają w menu i oknie
edycji. Poziome przewijanie umożliwia odczyt długich nazw plików. Przy
pojedynczej zmianie aktualizowane są tylko zmienione wiersze, bez dekodowania
obrazu. Filtry membership usuwają lub wstawiają odpowiednie wiersze bez
przebudowy Listbox. Liczniki kategorii są inkrementalne; „Bez etykiety” to
różnica liczby wybranych SHA i liczby przypisań. Pozostają trzy istniejące
filtry; filtrowanie według etykiet nie jest częścią v1.

Nazwy, przypisania i aktywna etykieta są odtwarzane razem z roboczą selekcją
po wyjściu i ponownym wejściu w tej samej sesji aplikacji, przed commit.
Nie zmienia to dotychczasowej nietrwałości niezapisanej selekcji po zamknięciu
aplikacji. Po commit etykiety są trwałe. Ponowne wejście do zatwierdzonej
próby odtwarza jej członków i etykiety; obce SHA i nieistniejące ID etykiet
są pomijane przy ładowaniu.

Artefakt `sample_labels.json` ma schemat `alpr.experiment_sample_labels.v1`,
`track_id`, listę `{id, name}` oraz `assignments` mapujące member SHA-256
na jedno ID. Przy zatwierdzeniu przypisania są ograniczane do zachowanych SHA.
Zapis etykiet, manifestu, próbki oraz membership ma wspólną granicę rollback.
Brak użycia funkcji nie tworzy artefaktu; usunięcie ostatniej kategorii usuwa
opcjonalny plik przy zapisie.

Zmieniony skład nadal wymaga normalnego commit i ponownego audytu. Zmiana
wyłącznie etykiet na już zatwierdzonej próbie korzysta z osobnego zapisu
metadanych: ponownie sprawdza status DRAFT i membership pod blokadą SQLite,
ale nie zmienia audytu, `sample_selection.json`, GT ani fingerprintów.
Błędy zapisu plików lub commit SQLite przywracają poprzednie pliki.

SEAL obejmuje istniejący plik etykiet jako opcjonalny artefakt w manifeście
i pieczęci. Późniejsze modyfikacje wykrywa dotychczasowa kontrola SHA.
Publiczna operacja zapisu etykiet odrzuca zapieczętowany tor. Brak pliku
pozostaje poprawny. Silnik rankingu, GT gate, VERIFY i schemat wyboru próby
nie wykorzystują etykiet. Nie dodano inferencji ani metryk per kategoria.

Nowe testy: `tests/test_sample_labels.py`, `tests/test_sample_labels_gui.py`.
Weryfikacja wizualna i wydajnościowa działa na tymczasowych Workspace.
Logi regresji są zapisywane w `output/sample_labels_*`.
