# Z4 — Centrum wyboru modeli oraz kontekstowy modal eksportu (UX v1)

## Zakres zmiany

Centrum eksportu mobilnego wybiera modele MP/MT/MZ, maksymalnie po jednym na rolę.
Jedyny CTA do przejścia dalej: **Eksportuj zaznaczone**. **Zamknij** kończy wybór.
Import online pojazdów nadal pozostaje w Centrum, ponieważ służy wyborowi modelu.

Po wybraniu MT+MZ otwiera się **Eksport kompletnego pakietu ALPR**. Każdy model
ma własną kartę z kolejnością: **1. Formaty i precyzja**, **2. Parametry inferencji**,
**3. Kalibracja INT8** (widoczna tylko przy zaznaczeniu Android lekki albo ONNX INT8).
W sekcji kalibracji: wybór trybu → przygotowanie manifestu train/SHA dla danej roli
lub wskazanie istniejącego manifestu → widoczna ścieżka.

Po prawej: **4. Gotowość eksportu i zależności**, a niżej
*Kontrola gotowego pakietu / wyniki z telefonu* ("Sprawdź precyzję TFLite",
"Raporty z telefonu"). Inspektor użyje ostatnio wyeksportowanego pliku,
a jeśli eksport jeszcze nie nastąpił, można wskazać istniejący plik.
W stopce **5. Następny krok** — dokładnie jeden CTA prowadzący przez
sprawdzenie gotowości, ewentualne uzupełnienie zależności i eksport.
Pauza dotyczy tylko instalacji zależności, nie przerywa dowolnej konwersji.

## INT8 dla kompletnego MT+MZ

Dla każdego modelu jawnie wybieramy Android lekki i wyłączamy Android stabilny,
jeśli chcemy wyłącznie LiteRT INT8. Dla MT i MZ osobno wybieramy manifest i tryb.
Eksporter już buduje dwa niezależne pakiety i dopiero potem scala je w
`alpr.package.v1`; zmiana UX nie modyfikuje tego kontraktu ani kolejności eksportu.
Nie ma automatycznego fallbacku INT8→FP32. Znana korekta badawcza MT TopK/Concat
nie jest gwarancją obsługi każdej architektury i MZ.

**EXPLORATORY_ONLY**, `FINAL_TEST_NOT_VERIFIED` i `ANDROID_RUNTIME_UNVERIFIED`
pozostają nierozstrzygnięte po samej kwantyzacji. Potwierdzenie grafu
INT8 nie dowodzi wykonywania integer na Galaxy A12. Żadne dane treningowe,
manifesty kalibracyjne, checkpointy, eksportowane pakiety, repo GitHub
ani testy Android nie są przez patch modyfikowane.

## Kryteria odbioru

- Centrum: wybór 1 MT + 1 MZ, brak przycisków kalibracji/precyzji/treningu ręcznego.
- Modal: dwie niezależne karty, INT8 dla obu widoczne i wybieralne.
- INT8: wyświetla się odpowiednia sekcja kalibracji przypisana do roli.
- FP32: sekcja kalibracji ukryta.
- Gotowość: nie dopuści eksportu bez manifestu w trybie INT8.
- Eksport: istniejąca logika kompletnego pakietu MT+MZ, kontrola grafów i SHA bez zmian.
- Po eksporcie: narzędzie precyzji otwiera ostatnio powstały .alprmodel.
- UX na ekranach 1100 px i typowym DPI; CTA nie obcięte ani nakładające się.
