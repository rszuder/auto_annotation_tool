# Zatwierdzony kontrakt nowego rozliczenia MT F4

**Polityka:** `f4_mt_final_bbox_iou50_greedy_v1`. **Zatwierdzona przez operatora 26.10.2026.**

Źródło zatwierdzenia: bezpośrednia odpowiedź użytkownika **„Zatwierdzam opisany kontrakt dla F4”** na pytanie o kompletny dokument `output/Z4_P0_P1_20261026_190657/matching_policy_candidate.md`. SHA-256 zatwierdzonego dokumentu: `8f0e33be0854efbedf5525d00413bfae93b1f547b075a055f59c1ec6b9e1999a`.

Zatwierdzenie obejmuje cały ten kontrakt, w szczególności:

- Jednostka: zakończone, zidentyfikowane wywołanie MT + źródłowa klatka/ROI. Alias nie tworzy kolejnej jednostki, odrębne wywołania pozostają osobne. Nie łączyć automatycznie sesji, wariantów, scenariuszy i powtórzeń.
- Tylko źródłowo dowiedzione FINAL z telefonu. RAW suppressed jest diagnostyczne. Nie powtarzać NMS i nie filtrować ponownie confidence.
- Fizyczne GT pochodzą z zapisanych, jawnych decyzji operatora, ze stabilnymi ID i rzeczywistą referencją geometrii. Bez automatycznego tworzenia lub łączenia GT na podstawie nakładania/OCR. Historyczne oceny czytać bez migracji i ponownej ręcznej weryfikacji.
- Ciągłe BBOX IoU **≥ 0,50**, bez `+1px` i bez naprawiania nieprawidłowego BBOX. Wiarygodny BBOX MT w źródle i obwiednia rzeczywistego GT. Detekcja BBOX jest niezależna od dostępności narożników Pose i OCR.
- Greedy **1:1**: malejący confidence, remis po unikalnym indeksie MT; wybór najwyższego IoU wolnej GT, remis po GT ID. Brak confidence, źródła, indeksu lub geometrii daje N/A. Nie zastępować greedy maksymalnym matching.
- PPM „poza tablicą” daje FP i nie zajmuje GT. Inne FINAL mogą zostać dopasowane geometrycznie. Spacja nie jest samodzielnym TP i nie potwierdza poprawności narożników GT.
- GT całkowicie poza ROI wyłączyć z mianownika tego wywołania; nieustalona granica/kompletność GT daje N/A. MT NOT_RUN/CANCELLED/ERROR, nierozstrzygnięte FINAL i niezgodne źródło nie tworzą sztucznych zer/FN.
- Dla kompletnej jednostki: `TP=liczba par`, `FP=FINAL−TP`, `FN=GT−TP`; bez object-level TN. GT asystowane pozostaje **ASSISTED**.
- Sumować liczniki kwalifikowanych jednostek przed dzieleniem. Precision=`TP/(TP+FP)`, Recall=`TP/(TP+FN)`, F1=`2TP/(2TP+FP+FN)`. Zerowy mianownik daje N/A; częściowy zakres ma jawne n/N.
- Rozliczenie tylko do odczytu, bez zmiany GT, decyzji, rewizji, READY i wcześniejszych eksportów. Nowe wyniki i manifesty są wersjonowane. P1 jest jednym kompaktowym wierszem istniejących wyników sesji; gesty i główny layout bez zmian.

Baza algorytmu: `ranking/mt_eval_metrics.py` oraz `RAPORT_FAZA3_AUDYT_NATYWNEGO_E2E_Z4.md:175`. Zastosowanie do F4 ustanawia powyższa bezpośrednia decyzja operatora; nie przypisujemy go retrospektywnie do dawnych eksportów ani do niezależnej oceny F6.
