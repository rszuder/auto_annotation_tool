# HANDOFF — Desktop: uporządkowanie kontraktu „model mobilny” vs „pakiet ALPR”

## Repozytorium i punkt odniesienia

Repozytorium: `rszuder/auto_annotation_tool`

Punkt odniesienia:
- commit: `301a1ef79d949f937707ab7afd5c513ea930cde0`
- message: `Napraw kompas PZ2, zmiane motywu i pokaz lokalizacje eksportu`

Nie cofaj zmian dotyczących provenance, dataset identity, lineage, eksportu NCNN, walidacji runtime/output, rankingów modeli ani eksportu research.

---

## 1. Problem

W aplikacji i dokumentacji mieszają się dwa różne pojęcia:

```text
pojedynczy model mobilny
```

oraz:

```text
kompletny pakiet ALPR
```

Dlatego zdanie „minimalny pakiet eksportu to MT+MZ” wydaje się sprzeczne z faktem, że Desktop poprawnie pozwala wyeksportować sam `MT`, sam `MZ`, a także sam `MP`.

Funkcjonalność eksportu pojedynczych modeli jest potrzebna i należy ją zachować. Nieścisłość jest przede wszystkim terminologiczna.

---

## 2. Docelowy kontrakt pojęciowy

### 2.1. Pojedynczy model mobilny

Schemat:

```text
alpr.model.v1
```

Dozwolone role:

```text
MP
MT
MZ
```

czyli:

```text
vehicle
plate
character
```

Każdy z nich może być eksportowany samodzielnie.

Przykłady:

```text
MT(n)
MZ
MP
```

To są poprawne samodzielne pliki modelu mobilnego. Nie nazywaj ich „kompletnym pakietem ALPR”.

### 2.2. Kompletny pakiet ALPR

Schemat:

```text
alpr.package.v1
```

Minimalna poprawna zawartość:

```text
MT + MZ
```

Rozszerzona poprawna zawartość:

```text
MP + MT + MZ
```

Pakiet `alpr.package.v1` oznacza kompletny zestaw zdolny do realizacji pełnego rozpoznania tablicy.

Niepoprawne jako `alpr.package.v1`:

```text
MP
MT
MZ
MP + MT
MP + MZ
```

Jeżeli użytkownik chce wyeksportować tylko jeden model, ma użyć `alpr.model.v1`.

---

## 3. Dlaczego pojedynczy eksport jest potrzebny

Zachować scenariusz:

```text
telefon:
MP + MT(s) + MZ
```

Desktop eksportuje tylko:

```text
MT(n)
```

Android podmienia wyłącznie MT i uzyskuje:

```text
MP z konfiguracji bazowej
MT(n) z pojedynczego alpr.model.v1
MZ z konfiguracji bazowej
```

To jest poprawne i bardzo przydatne badawczo. Pozwala zmieniać jeden czynnik eksperymentalny bez ponownego eksportu modeli, które się nie zmieniły.

Analogicznie ma działać osobna podmiana `MZ` albo `MP`.

---

## 4. Zmiany w UI Desktop

### 4.1. Eksport pojedynczego modelu

W miejscach, gdzie eksportowany jest jeden model, używać nazwy:

```text
Eksportuj model mobilny (.alprmodel)
```

Nie:

```text
Eksportuj pakiet mobilny
```

Jeżeli UI zna rolę, można doprecyzować:

```text
Eksportuj model MT
Eksportuj model MZ
Eksportuj model MP
```

### 4.2. Eksport kompletnego zestawu

Dla eksportu `MT+MZ` lub `MP+MT+MZ` używać:

```text
Eksportuj pakiet ALPR (.alprmodel)
```

albo:

```text
Eksportuj kompletny pakiet ALPR
```

### 4.3. Centrum eksportu

Jeżeli centrum eksportu pozwala wybierać kombinacje modeli, pokaż użytkownikowi jednoznacznie:

```text
1 model wybrany
→ zostanie utworzony model mobilny alpr.model.v1
```

```text
MT + MZ
→ zostanie utworzony kompletny pakiet ALPR alpr.package.v1
```

```text
MP + MT + MZ
→ zostanie utworzony kompletny pakiet ALPR alpr.package.v1
```

Nie sugeruj, że `MP+MT` lub `MP+MZ` są kompletnym pakietem.

---

## 5. Zmiany w pomocy i dokumentacji

Znajdź i popraw wszystkie teksty sugerujące, że:

```text
alpr.package.v1 może zawierać jeden model
```

Docelowy opis:

```text
alpr.model.v1
- pojedynczy model logiczny:
  MP, MT albo MZ

alpr.package.v1
- kompletny pakiet ALPR:
  MT+MZ
  albo MP+MT+MZ
```

Szczególnie sprawdzić:
- `auto_annotation_tool/gui/tab_help.py`,
- `docs/specyfikacja_agenta_aplikacji_mobilnej_alpr.md`,
- `docs/eksport_mobilny_kwantyzacja.md`,
- `alpr_python_exporter_handoff.md`,
- `DZIENNIK_ARCHITEKTURY_I_ZMIAN.md`,
- `docs/freeze_smoke_test_checklist.md`.

Nie zmieniaj poprawnych fragmentów, które już stosują ten podział.

---

## 6. Walidacja eksportera

### 6.1. `MobileModelExporter`

Ma nadal akceptować dokładnie jeden model:

```text
vehicle
plate
character
```

i tworzyć:

```text
schema = alpr.model.v1
```

Nie wprowadzaj zależności `MT -> MZ` w tym eksporterze.

### 6.2. `MobileAlprPackageExporter`

Ma tworzyć wyłącznie:

```text
MT+MZ
```

albo:

```text
MP+MT+MZ
```

Dla `alpr.package.v1` wymagane są:

```text
models.plate
models.character
```

`models.vehicle` jest opcjonalne.

Jeżeli `plate` albo `character` brakuje, eksport pakietu ma się zakończyć czytelnym błędem, np.:

```text
Kompletny pakiet ALPR wymaga modeli MT i MZ.
Jeżeli chcesz wyeksportować pojedynczy model, użyj eksportu modelu mobilnego.
```

---

## 7. Nie wprowadzaj trzeciego formatu

Nie twórz:
- `partial_package`,
- `incomplete_package`,
- `model_bundle`,
- nowego schema dla `MP+MT`,
- nowego schema dla `MT` bez `MZ`.

Obecne dwa schematy wystarczają:

```text
alpr.model.v1
alpr.package.v1
```

---

## 8. Badania i ranking

Zachować rozróżnienie:

```text
pojedynczy model
→ mAP, recall, F1, test izolowany
```

```text
kompletny pakiet ALPR
→ exact match, CER, błędy pełnego potoku, wydajność mobilna
```

`mobile_package_experiments.py` powinien nadal wymagać kompletnego pakietu `MT+MZ` lub `MP+MT+MZ`.

Nie pozwalaj oceniać samego `MT` jako kompletnego pakietu ALPR.

---

## 9. Testy wymagane

### D1 — pojedynczy MT
Eksport jednego MT:
- sukces,
- `schema=alpr.model.v1`,
- `role=plate`.

### D2 — pojedynczy MZ
- sukces,
- `schema=alpr.model.v1`,
- `role=character`.

### D3 — pojedynczy MP
- sukces,
- `schema=alpr.model.v1`,
- `role=vehicle`.

### D4 — MT+MZ
- sukces,
- `schema=alpr.package.v1`,
- zawiera `plate` i `character`.

### D5 — MP+MT+MZ
- sukces,
- `schema=alpr.package.v1`,
- zawiera wszystkie trzy role.

### D6 — brak MZ
Próba utworzenia `alpr.package.v1` z `MT` albo `MP+MT` ma zostać odrzucona.

### D7 — brak MT
Próba `MZ` albo `MP+MZ` jako `alpr.package.v1` ma zostać odrzucona.

### D8 — UI terminology
Smoke test:
- jeden model -> „model mobilny”,
- MT+MZ / MP+MT+MZ -> „pakiet ALPR”.

### D9 — dokumentacja
Nie może pozostać tekst:

```text
alpr.package.v1 może zawierać jeden model
```

---

## 10. Nie zmieniać

Nie zmieniaj:
- zawartości `manifest.json` pojedynczego modelu poza niezbędnymi tekstami UI,
- kontraktów tensorów,
- runtime,
- kwantyzacji,
- NCNN,
- provenance,
- checkpoint SHA,
- dataset identity,
- lineage,
- formatu `.alprsession`,
- mechanizmu rankingu pojedynczych modeli.

---

## 11. Kryterium akceptacji

Po poprawce użytkownik ma rozumieć bez dodatkowego wyjaśnienia:

```text
sam MT
= model mobilny
= alpr.model.v1
```

```text
MT+MZ
= minimalny kompletny pakiet ALPR
= alpr.package.v1
```

```text
MP+MT+MZ
= kompletny pakiet kaskadowy ALPR
= alpr.package.v1
```

Pojedynczy eksport MT/MZ/MP pozostaje w pełni wspierany.

---

## 12. Raport końcowy agenta

Podaj:
- commit SHA,
- zmienione pliki,
- poprawione teksty UI,
- poprawione dokumenty,
- wynik testów,
- przykład manifestu pojedynczego MT,
- przykład manifestu `MT+MZ`,
- potwierdzenie, że `MP+MT` nie może powstać jako `alpr.package.v1`.
