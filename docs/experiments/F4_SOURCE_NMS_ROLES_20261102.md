# Źródłowe role NMS w Desktop, 2026-11-02

Adapter `alpr.desktop.source_roles.v2` oddziela znane liczniki R/F/S/MZ od
tożsamości kandydatów. MZ nie jest licznikiem FINAL. Metodyka, matcher oraz SHA
F4-EVAL-2.0 pozostają bez zmian. Odczyt nigdy nie modyfikuje archiwum ani oceny.

Historyczne dowody pojedynczego odrzucenia (`primary_id` / `suppressed_id`,
`alpr.postdedup.executed_complement.v1`) pozostają czytane w dotychczasowej
postaci, bez migracji. Wewnętrzne integracje używają list FINAL/SUPPRESSED.

Dla wielu odrzuceń wymagany jest pełny dowód per ID. Wspierany jawny protokół
śladu `source_roles_v2` zawiera `schema=alpr.source_nms_roles.v2`, `complete=true`,
`mt_invocation_id`, `source_frame_entry`, dokładne `roi`, `final_ids` oraz
`suppressed_ids`. Wymagane są rozłączne, unikalne listy pokrywające dokładnie
pełen zbiór prób, zgodne R=F+S, indeksy, zakończone MT, jeden ślad, jedna
inferencja, epoch/transform i klatka/ROI. FINAL z błędem rektyfikacji może nie
mieć MZ. Status NOT_RUN, confidence, IoU ani kolejność nie dowodzą odrzucenia.

Ten protokół jest testowany na jawnie oznaczonych syntetycznych archiwach.
Nie jest deklaracją, że historyczny Android go eksportował. Nie zmieniono
Androida ani protokołu oryginalnych plików.

Oryginalny Obraz 06 sesji `exp-1792702907090-d3edcf48`, SHA
`9972226234c6ac08f49580d1f70a5eb79000fab1f00b7051121ca3b99f77f351`, ma
liczniki 4/2/2 i dwa MZ. Brakuje zapisu per ID oraz powiązanego z dokładnym APK
dowodu kontraktu wykonania. Zapis prób jest `decoder_output`; sam ten porządek
nie dowodzi FINAL. APK w metadanych ma SHA
`4a78a026cebb0bf18b8b579a75b332c8953f0071a18d3ee1af391a25d9bb1944`, git_dirty=true;
dostępny lokalny build ma inny SHA. Wynik: `UNPROVEN_SOURCE_NA`,
`SOURCE_FINAL_ROLE_UNPROVEN`, brak TP/FP/FN dla tego wywołania. Cztery UNKNOWN
pozostają diagnostyczne, GTR1 i historia pozostają nienaruszone. Nie powstaje
zadanie „Sprawdź źródło”, wybór FINAL ani dodatkowe potwierdzenie obrazu.

Nowe eksporty zawierają dowody i znane/brakujące liczności per wywołanie oraz
SHA adaptera. N/A jest wyraźnym zakresem wyłączonym z pomiaru. Inne obrazy
pozostają ocenialne; gotowość ramek nie deklaruje wyczerpującego spisu sceny.
