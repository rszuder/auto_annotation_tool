# Z4MOBREV030 — prosty formularz numeru tablicy

Stan: patch przygotowany 19.10.2026, wymaga kontroli `--check`, testów Windows i odbioru GUI.

## Problem

Sekcja **02 · WERYFIKACJA ODCZYTU MZ** wymagała od operatora wyboru pomiędzy napisami „Numer czytelny — weryfikuj odczyt MZ” oraz „Numer nieczytelny — wyłącz OCR z weryfikacji”. Są to nazwy operacji analitycznych, a nie decyzji obserwacyjnych; operator nie powinien ręcznie sterować mianownikiem CER. Formę pokazano na ekranie weryfikacji sesji P1-R0-FP32-B z 19.10.

## Docelowy kontrakt interfejsu

- Sekcja: **02 · SPRAWDZENIE NUMERU TABLICY**.
- Widoczny, niezmienny **Numer odczytany przez aplikację** (jeśli MZ rzeczywiście działało).
- Pole **Jaki numer widzisz na zdjęciu?** — wyłącznie ręczna transkrypcja operatora; zakaz automatycznego przepisywania predykcji.
- Jedyny przełącznik: **Nie mogę odczytać numeru ze zdjęcia**. Opcjonalne uzasadnienie pojawia się tylko po zaznaczeniu.
- Bez osobnych przełączników „OCR” i „weryfikuj”; program sam wyznacza kwalifikowalność do pomiaru.
- W formularzu wielu tablic analogicznie zmieniono wyłącznie niezrozumiałe napisy, bez zmiany logiki przypisań; pełnoklatkowy edytor GT należy do odrębnego P2B.

## Trzy rozłączne stany danych

| Obserwacja operatora | `ground_truth` | `evaluable` | Konsekwencja |
|---|---|---|---|
| Numer wpisany | Niepusty | `true` | Można porównać tekst, jeśli wykonano MZ i spełnione są pozostałe kryteria |
| Nie można odczytać numeru | Pusty | `false` | Jawne pominięcie porównania tekstu; MT i Pose nadal weryfikowane osobno |
| Brak decyzji | Pusty | `null` | Formularz niekompletny, bez automatycznego wykluczenia |

Zapis pozostaje w istniejącym sidecarze; oryginalne ZIP, predykcje, pomiary, GT źródłowy i Android nietknięte. Stare sidecary `evaluable:false` odwzorowują się na zaznaczony checkbox. Przy niepustym wpisanym GT włączenie nieczytelności wymaga wcześniejszego świadomego wyczyszczenia pola (bez niejawnego usuwania GT).

Przerwane lub technicznie niewykonane próby mają formularz read-only. Dla aktywnych prób bez wykonania MZ GT można udokumentować, lecz nie wolno wyliczać błędu OCR z nieistniejącego wyniku. Weryfikacja z widoczną predykcją jest *asystowana*, nie zaślepiona.

## Testy i odbiór

1. Jedna czytelna kontrolka zamiast dwóch przycisków radiowych.
2. Puste GT bez zaznaczenia pozostaje niedokończone.
3. Czytelny GT automatycznie pozwala na porównanie MZ po zapisie.
4. Zaznaczenie nieczytelności zapisuje `evaluable=false`, nie modyfikuje MT/obrysu.
5. Odznaczenie przy pustym GT przywraca `evaluable=null`.
6. Nie da się jednym kliknięciem wykluczyć wcześniej wpisanego numeru.
7. Historyczne sidecary zachowują swoją decyzję i notatkę.
8. Przerwane/techniczne próby nie mają edytowalnych decyzji.
9. Prawy panel nie pokazuje schowanych opcji i nie zasłania obrazu.
10. Testy Tk oraz poprzednie testy cyklu życia, P2A/ROI po zastosowaniu patcha.

Odbiór wizualny w rzeczywistej aplikacji Windows jest nadal wymagany.
