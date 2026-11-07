# F4-EVAL-2.0 — jedno FINAL, jedna detekcja obiektu MT

Status: zatwierdzona przez zlecenie operatora z 2026-11-01 metoda
**retrospektywna, ASSISTED**, przyjęta po rejestracji 12 sesji F4.
Nie jest prerejestracją, niezależną oceną zaślepioną ani COCO mAP.

Polityka: `f4_mt_final_operator_assisted_object_v2`.
Schemat: `alpr.mobile.mt_object_evaluation.v2`.
Kanoniczny JSON i jego SHA-256 publikuje `mobile_mt_object_evaluation.POLICY`.
Każdy bieżący wynik, analiza i nowy eksport zawierają ten sam SHA polityki.
Nowa analiza ma identyfikator `ALPR-ANALYSIS-1.1`.

## Populacja i dowód

Jednostką jest źródłowo dowiedzione wywołanie MT, klatka i ROI. Stabilny
`attempt_id` oraz `mt_detection_index` identyfikują jedno FINAL. BBOX i Pose
są jego reprezentacjami geometrycznymi. RAW/SUPPRESSED pozostaje diagnostyką,
bez ponownego NMS, filtracji confidence ani zmiany predykcji.

GT to odrębne zapisane fizyczne GTR. Pozytywna decyzja wymaga potwierdzonej
relacji konkretnego FINAL do dokładnie jednej istniejącej potwierdzonej GTR.
Dowodem jest zapisany, powiązany ze źródłem kontrakt decyzji operatora
lub wcześniejsza jawna ocena z kanoniczną relacją. Automatyczna projekcja
nakładania ramek, bliskość, zgodny tekst ani diagnostyczne `operator_bad`
nie są taką decyzją. Odczyt i eksport nigdy nie zatwierdzają ani nie migrują ocen.

## Primary MT v2

Potwierdzone NOT_PLATE jest FP i nie zajmuje GT. Potwierdzone PLATE
z dowiedzioną GTR może być TP niezależnie od dokładności BBOX/Pose.
Kilka PLATE do jednej GTR parujemy deterministycznie według confidence
malejąco, indeksu rosnąco i attempt_id rosnąco. Pierwsze jest TP, pozostałe
FP `DUPLICATE_FINAL`, z zachowaniem historii każdej decyzji.

Dla kompletnej jednostki: TP = liczba par, FP = n_FINAL − TP,
FN = n_GT − TP. Pary są 1:1, TP+FP=n_FINAL, TP+FN=n_GT. Brak podstawowego TN.
Precision=TP/(TP+FP), Recall=TP/(TP+FN), F1=2TP/(2TP+FP+FN).
Wskaźniki sesji powstają z sum liczników kwalifikowanych jednostek.
Zerowy mianownik daje N/A, również dla jawnie pustej sceny.

UNRESOLVED, niepotwierdzona kompletność GT, brak relacji lub GTR,
konflikt tożsamości, nieznane FINAL, brak confidence/indeksu, brak źródła,
złe SHA albo niezweryfikowane ROI wykluczają całą jednostkę z formalnych
TP/FP/FN. Podajemy przyczynę i konkretne zadanie operatora. GT przecinające
ROI nie jest automatycznym FN. Znane odrzucenia w niepełnym obrazie można
pokazać jako FP≥k, przy niedostępnych TP/FN.

## Pomocnicza geometria i niezmienione v1

Dla par v2 osobno liczymy ciągłe BBOX IoU względem obwiedni GTR oraz
Polygon IoU i NMCE rzeczywistego źródłowego Pose względem GTR.
Zerowy BBOX daje N/A miary BBOX, bez poprawiania współrzędnych.
Brak Pose daje N/A Polygon IoU/NMCE, bez rekonstrukcji z BBOX/GTR.
Rozbieżności BBOX↔Pose i geometrie rozłączne mają jawne kody diagnostyczne.

`mobile_mt_detection_evaluation.py` i dokument z 2026-10-26 są niezmienne.
Archiwalne BBOX v1 (IoU≥0,50, greedy) zachowuje odrębny cel: dokładność
lokalizacji BBOX. Nowa analiza oznacza te wartości `bbox_v1_*` i porównuje
wszystkie jednostki, również bez poprawy v2. Stare eksporty nie są regenerowane.

## Warunkowe MZ i czas

Wykonane MZ po FP MT zachowuje surowy tekst, crop, attempt, źródłowy czas
i wykonanie jako `EXECUTED_EXCLUDED_MT_FP`; nie wchodzi do Exact/CER.
TP + dowiedzione pochodzenie crop/attempt + potwierdzony czytelny GTZ
kwalifikuje wykonany odczyt, również błędny i pusty. NOT_RUN jest poza
mianownikiem warunkowego OCR. Brak GTZ/crop daje jawne N/A, nie wygodny FP.
Rozłączny źródłowy Pose nie dowodzi, że crop zawiera powiązaną GTR.

Mianowniki MT, geometrii i OCR są niezależne, ze stanami FULL/SUBSET/N/A.
Wiersze OCR nie są liczbą wywołań MZ. Pełne ślady Androida zachowują wszystkie
rzeczywiste koszty, także po FP. Brak licznika wywołań jest N/A z liczbą
znanych wywołań i niepełnych śladów. Czas etapu MZ/ślad może sumować kilka
wywołań; nie dzielimy p95 przez liczbę wywołań.

F4 E2E pozostaje N/A bez mapy 18 plansz i reguły odczytu w oknie 10 s.
DAY/NIGHT i trzy rNN pozostają odrębnymi sesjami. Statystyki sesyjne nie są
połączonym percentylem ani 54 niezależnymi scenami. F5/F6 wymagają własnych
potwierdzonych protokołów; analiza F4 nie nadaje im wyników przez podobieństwo.

## Publikacja

Nowa rewizja eksportu zawiera atomowo publikowany namespace
`mt_object_evaluation_v2_###/`: JSON, units.csv, pairs.csv, policy.json,
snapshot oceny, kontekst OCR, report.md i manifest SHA/rozmiarów.
Zmiana źródła, rewizji lub sidecara podczas eksportu anuluje publikację.
Replay weryfikuje pliki i ponownie oblicza czysty scorer oraz kwalifikację OCR.
Żaden nowy eksport nie zmienia oryginalnych archiwów, GTZ, ocen, statusów,
rewizji i dotychczasowych raportów.
