# Dziennik architektury i zmian

Plik roboczy do prowadzenia:
- ustaleń architektonicznych,
- zmian semantycznych w workflow,
- pomysłów użytkownika,
- decyzji wdrożeniowych wymagających ciągłości między sesjami.

## 2026-05-07

### Cel nadrzędny
Przejście z rozproszonych heurystyk i „ostatnio znanych wskaźników” na centralny rejestr artefaktów iteracji, który staje się głównym źródłem prawdy dla wejść do etapów `E1/E2/E3/E4` oraz zakładek `Z2/Z3/Z4`.

### Diagnoza stanu wyjściowego
- System posiadał fragmenty architektury rozrzucone po kilku miejscach:
  - `project_start_mode`,
  - `last_plate_manual_source_*`,
  - manifesty runów `Z2`,
  - `plate_approved_set.json`,
  - tymczasowe źródło znaków `char_effective_source`,
  - heurystyki bootstrapu `Z2/Z3`.
- Logika wejść do torów była częściowo poprawna, ale niedeterministyczna.
- Brakowało jednego modelu relacji:
  - `paczka iteracji -> obrazy -> run/xml tablic -> źródło znaków -> gotowość torów`.

### Decyzja architektoniczna
Wprowadzamy centralny rejestr artefaktów iteracji:
- plik: `_campaign_state/artifact_registry.json`
- właściciel: `CampaignManager`
- model: `write-through registry`

To znaczy:
- przy tworzeniu lub podpinaniu artefaktu od razu dopisujemy wpis do rejestru,
- etapy i zakładki czytają najpierw z rejestru,
- stare skanowanie katalogów zostaje tylko jako fallback bezpieczeństwa.

### Minimalny model rejestru
Rejestr przechowuje wpisy per paczka iteracji (`package_id`) oraz indeks iteracji.

Kluczowe grupy danych:
- `image_source`
  - katalog obrazów iteracji,
  - token zmian ścieżki,
  - manifest ingestu,
  - tryb wyboru paczki,
  - liczność wejścia.
- `plate_source`
  - run tablic,
  - `annotations.xml`,
  - katalog obrazów zgodnych z runem,
  - liczba obrazów z tablicami,
  - liczba tablic,
  - zakres / pochodzenie.
- `plate_model`
  - ścieżka,
  - token,
  - scope,
  - identity.
- `char_model`
  - ścieżka,
  - token,
  - scope,
  - identity.
- `char_effective_source`
  - wynikowe źródło tablic dla toru znaków,
  - `run_dir`,
  - `images_dir`,
  - `xml_path`,
  - liczniki tablic.
- `step3_extract_source`
  - stan wejścia / ekstrakcji `Z3`,
  - `annotation_run_dir`,
  - `xml_path`,
  - `images_dir`,
  - `entry_mode`,
  - `workflow_step`.
- `route_hints`
  - `plate_entry_mode`,
  - `char_entry_mode`,
  - `char_ready`,
  - `char_has_source`,
  - `needs_more_tables`,
  - liczniki pomocnicze.

### Główne reguły semantyczne
- Jeśli w `E1` dodano model tablic:
  - tor `A` ma domyślnie startować w autoanotacji tablic,
  - a nie w ręcznym tworzeniu XML.
- Jeśli w `E1` dodano gotowy zasób anotacji tablic:
  - oznacza to, że tablice są już gotowe jako źródło,
  - tor `B` może być odblokowany już w pierwszej iteracji,
  - nawet jeśli później system stwierdzi, że trzeba dołożyć więcej tablic do sensownego splitu.
- Sam model znaków:
  - nie odblokowuje toru `B`,
  - ale powinien być podstawiany automatycznie w `Z3`.

### Miejsca zapisu do rejestru
#### `E1 / CampaignTab`
- wybór katalogu obrazów iteracji,
- import gotowego runu tablic,
- wybór modelu tablic,
- wybór modelu znaków,
- odświeżenie panelu startowego `E1`.

#### `Z2 / AnnotationTab`
- zapamiętanie źródła ręcznych tablic,
- zapis modelu tablic w bieżącym runie,
- domknięcie i zatwierdzenie `E2`,
- budowa wynikowego źródła znaków z ApprovedSet i bieżących `[OK]`.

#### `Z3 / CharacterAnnotationTab`
- ustawienie wejścia `step3_extract_state`,
- zapis źródła ekstrakcji do rejestru.

### Miejsca odczytu z rejestru
#### `CampaignTab`
- stan źródeł `E2`,
- bootstrap wejścia dla torów,
- blokady / gotowość przejść.

#### `AnnotationTab`
- bootstrap kampanijnego `Z2`,
- odczyt modelu tablic i runu źródłowego,
- fallback tylko przy niekompletnym wpisie.

### Zmiany już wdrożone
- dodano `artifact_registry.json` w `CampaignManager`,
- dodano `package_id` budowany na podstawie paczki iteracji,
- wdrożono operacje:
  - `load_artifact_registry`,
  - `save_artifact_registry`,
  - `upsert_iteration_artifact_bundle`,
  - `get_iteration_artifact_bundle`.
- `E1`, `Z2` i `Z3` zaczęły zapisywać do rejestru,
- `CampaignTab` zaczął czytać stan torów z rejestru,
- cache widoków `E2` uwzględnia już token rejestru.

### Świadome kompromisy na dziś
- Stara logika heurystyczna nie została jeszcze całkowicie wycięta.
- Rejestr jest już używany jako źródło pierwszego wyboru, ale fallback pozostaje:
  - dla bezpieczeństwa,
  - dla zgodności ze starymi projektami,
  - na czas testów przepływów.

### Testy przepływów do wykonania
1. `E1 + model tablic`
   - oczekiwane:
     - tor `A` startuje od autoanotacji,
     - nie od ręcznego XML.
2. `E1 + gotowy run tablic`
   - oczekiwane:
     - tor `B` odblokowuje się już w pierwszej iteracji,
     - nawet jeśli później może prowadzić do komunikatu „przygotuj więcej tablic”.
3. `Z2 -> zatwierdzenie E2 -> Z3`
   - oczekiwane:
     - `Z3` bierze źródło z rejestru,
     - a nie tylko z heurystycznego skanowania katalogów.

### Wyniki testów logicznych z 2026-05-07
Wykonano lekkie testy na poziomie logiki wejść i priorytetów źródeł, bez pełnego klikania GUI:

1. `E1 + model tablic -> tor A auto`
   - wynik:
     - `plate_model_ready=True`
     - `manual_template=False`
     - `bootstrap_model_path` wskazuje model z rejestru
   - wniosek:
     - tor `A` bierze model tablic z rejestru i nie wraca do ręcznego XML.

2. `E1 + gotowy run tablic -> tor B odblokowany`
   - wynik:
     - stan rejestrowy toru `B`:
       - `has_source=True`
       - `ready=False`
       - `needs_more_tables=True`
       - `input_source='registry_plate_source'`
     - wybór torów w `E2`:
       - `plate.enabled=True`
       - `char.enabled=True`
   - wniosek:
     - gotowy zasób tablic odblokowuje tor `B` już w pierwszej iteracji,
     - nawet jeśli później system może wymagać dołożenia tablic do sensownego splitu.

3. `char_effective_source -> tor B gotowy z rejestru`
   - wynik:
     - `has_source=True`
     - `ready=True`
     - `needs_more_tables=False`
     - `input_source='campaign_char_effective_source'`
     - licznik: `images_with_plates=3`, `total_plates=12`
   - wniosek:
     - jeśli rejestr ma już wynikowe źródło znaków, tor `B` bierze je z rejestru jako źródło pierwszego wyboru.

4. `tor B bez modelu tablic, ale z gotowym źródłem tablic`
   - wynik:
     - wybór toru `B` pozostaje aktywny,
     - CTA w `E2` zmienia się na:
       - `Uzupełnij tablice w Z2`
   - wniosek:
     - gotowe źródło tablic z rejestru ma pierwszeństwo nad wymaganiem modelu tablic,
     - model tablic jest wymagany tylko wtedy, gdy tor `B` nie ma jeszcze żadnego źródła wejściowego.

### Domknięcie semantyki rejestru w kolejnych krokach
W drugiej części prac dopięto jeszcze trzy istotne miejsca, które wcześniej nadal potrafiły wracać do starej heurystyki:

1. `Z2` i nieaktualny wskaźnik modelu
   - jeśli globalny wskaźnik modelu tablic istnieje, ale prowadzi do nieistniejącej ścieżki,
   - bootstrap `Z2` bierze teraz poprawną ścieżkę modelu z rejestru,
   - zamiast blokować tor lub wracać do ręcznego XML.

2. CTA i wybór toru w `E2`
   - teksty przycisków i blokady wejścia dla toru `B`
   - nie opierają się już wyłącznie na `get_global_model("plate")`,
   - tylko na stanie `plate_model_ready` wyliczonym z rejestru / bootstrapu.

3. `Z3` i preferowane źródło wejściowe
   - jeśli `Z3` nie dostanie jawnego `preferred_source_context`,
   - najpierw szuka źródła w rejestrze:
     - `step3_extract_source`,
     - potem `char_effective_source`,
     - potem `plate_source`,
   - a dopiero później schodzi do starszych wskaźników pomocniczych.

### Dodatkowe testy logiczne po domknięciu rejestru
5. `Z2` przy martwym globalnym modelu, ale poprawnym modelu w rejestrze
   - wynik:
     - `bootstrap_plate_model_path` wskazuje model z rejestru
     - `manual_template=False`
   - wniosek:
     - centralny rejestr potrafi już uratować wejście do `Z2`, gdy stary globalny wskaźnik modelu jest nieaktualny.

6. CTA toru `B` z `plate_model_ready` z rejestru
   - wynik:
     - CTA: `Przygotuj tablice na modelu projektu (Z2)`
   - wniosek:
     - decyzja tekstowa w `E2` bierze teraz pod uwagę stan modelu z rejestru, a nie tylko surowy wpis globalny.

7. Preferowane źródło `Z3` z rejestru
   - wynik:
     - helper źródła `Z3` wskazał run z rejestru,
     - ten sam wpis jest też pierwszym kandydatem dla ręcznego „użyj źródła z Z2”.
   - wniosek:
     - `Z3` nie musi już polegać wyłącznie na ostatnim znalezionym `annotations.xml` w katalogach.

### Ograniczenie testów na dziś
- Potwierdzona jest logika rejestru i reguły wejść.
- Nie wykonano jeszcze pełnego testu GUI end-to-end z realnym klikiem przez cały flow:
  - `E1 -> E2 -> Z2 -> approve -> Z3`
- Stara heurystyka nadal istnieje jako fallback bezpieczeństwa.

### Ustalenia UX / semantyki z dzisiejszej sesji
- `E1` ma być tabelą zasobów startowych iteracji.
- Obrazy iteracji są wymagane.
- Pozostałe zasoby są opcjonalne.
- Źródła `Projekt / Freemode` są przełączane per wiersz.
- W tabeli pokazujemy ścieżki względne, ale pełną ścieżkę można skopiować z menu kontekstowego.
- `E1` nie powinno dublować opisów już zawartych w samej tabeli.
- Dla `E1`:
  - obrazy iteracji wybieramy jako katalog,
  - anotacje tablic wskazujemy jako konkretny plik `annotations.xml`,
  - modele wskazujemy jako pliki `.pt`.

### Pomysły do dalszego wdrożenia
- pełne przepięcie wszystkich wejść `E2/Z2/Z3/Z4` na rejestr,
- tryb „napraw / odbuduj rejestr” dla projektów ręcznie modyfikowanych na dysku,
- śledzenie powiązań:
  - paczka zdjęć,
  - run,
  - `annotations.xml`,
  - źródło znaków,
  - dataset treningowy,
  - model wynikowy,
- rezygnacja z części skanów workspace przy przejściach między etapami.

### Rozszerzenie rejestru: tokeny zgodnoĹ›ci paczki i XML
Kolejny krok architektury:
- `E1` zapisuje teraz do manifestu i rejestru token zestawu obrazĂłw paczki:
  - `image_set_token`
- `plate_source` zapisuje:
  - `xml_image_set_token`
  - `expected_image_set_token`
  - `image_set_match`

Znaczenie:
- `image_set_token` opisuje paczkÄ™ zdjÄ™Ä‡ iteracji jako znormalizowany zbiĂłr nazw plikĂłw,
- `xml_image_set_token` opisuje zbiĂłr obrazĂłw wymienionych w `annotations.xml`,
- `image_set_match=True` oznacza, ĹĽe XML odpowiada tej samej paczce co aktywne `E1`.

Wniosek architektoniczny:
- sam katalog obrazĂłw nie wystarcza jako identyfikator paczki,
- dlatego `package_id` moĹĽe teraz uwzglÄ™dniaÄ‡ takĹĽe `image_set_token`,
- co zmniejsza ryzyko kolizji przy kolejnych iteracjach budowanych z tej samej puli katalogowej.

Skutek praktyczny:
- `E2/Z2/Z3` nie powinny ufaÄ‡ samemu istnieniu runu tablic,
- tylko temu, czy run jest zgodny z bieĹĽÄ…cÄ… paczkÄ… iteracji.

### Zasada robocza na kolejne sesje
Jeżeli pojawia się nowy artefakt lub nowe przejście etapu:
- najpierw sprawdzić, czy powinno zostać zapisane w centralnym rejestrze,
- dopiero potem dopisywać lokalne wskaźniki pomocnicze.

## 2026-05-10

### Stan wdrozenia RC na dzis
Ocena robocza: okolo `70%`.

To znaczy:
- fundament RC juz dziala,
- kluczowe etapy i bootstrapy juz czytaja z rejestru,
- ale nadal nie wszystkie odczyty i wszystkie zapisy ida jednym kanalem.

Najwiekszy problem nie polega juz na samym "czy rejestr istnieje", tylko na hybrydzie:
- czesc stanu siedzi w `campaigns_registry.json`,
- czesc w `artifact_registry.json`,
- czesc dalej w lokalnych snapshotach / cache GUI,
- a czesc byla jeszcze wyciagana heurystycznie z "najnowszego folderu".

### Co juz jest realnie w RC

#### 1. `campaigns_registry.json`
To jest glowny stan workflow projektu:
- aktywny projekt,
- numer iteracji,
- aktywny etap,
- `step1/step2/step3/step4 status`,
- `iteration_target`,
- stan postepu `E3`,
- aktywne wejscie `step3_extract_state`,
- nowo dopiety: `step3_preview_dir` jako aktywna paczka `Z3/PZ2`.

#### 2. `artifact_registry.json`
To jest rejestr artefaktow paczki / iteracji:
- `image_source`,
- `plate_source`,
- `plate_model`,
- `char_model`,
- `char_effective_source`,
- `step3_extract_source`,
- `route_hints`,
- czesc stanu treningowego `E4/Z4`.

#### 3. Co to nam juz daje
- `E1/E2` potrafia startowac z rejestru,
- `Z2` potrafi bootstrapowac model i run tablic z rejestru,
- `Z3` ma juz rejestrowe wejscie dla ekstrakcji,
- `Z4` ma iteracyjny zapis treningu zamiast przypadkowych pobocznych wskaznikow.

### Co jeszcze jest hybryda

#### 1. `Z2`
Poza RC nadal zyje lokalny stan UI:
- `annotation_ui_state.json`,
- `current_annotations`,
- `_preview_approved_filenames`,
- restore snapshoty,
- cache podgladu i selekcji.

To jeszcze nie jest samo w sobie bledem, ale nie moze decydowac o semantyce etapu bez synchronizacji z RC.

#### 2. `Z3/PZ2`
To byl dzis najczulszy punkt.

Problem:
- preview tablic bylo czasem brane z "najnowszego runu",
- a nie z aktywnej paczki tej iteracji.

Dlatego dopieto:
- `step3_preview_dir` w `campaigns_registry.json`,
- preferowanie aktywnej paczki preview nad heurystyka `mtime`,
- wykorzystanie tej paczki przy liczeniu `E3` i budowie `char_effective_source`.

#### 3. Heurystyki, ktore nadal trzeba ograniczac
- "wez najnowszy katalog `3_cropped_characters`",
- "wez ostatni run po mtime",
- "wez ostatni zapisany snapshot UI",
- fallbacki katalogowe tam, gdzie powinna byc decyzja z RC.

### Najwazniejsze ustalenie semantyczne z dzisiejszej sesji

#### `Z2 -> E3 -> Z3` dla toru znakow nie moze byc ani:
- czystym resetem,
- ani czystym live-merge wszystkiego.

Docelowa semantyka:
- paczka wycietych tablic w `PZ2` jest aktywnym stanem roboczym `E3`,
- nowe `[OK]` z `Z2` maja dzialac jak "dopompowanie" do tego stanu,
- czyli:
  - zachowujemy juz wyciete tablice,
  - dopisujemy nowe obrazy gotowe do kolejnego wycinania,
  - nie cofamy sie do starego preview,
  - nie liczymy samego stage projektu,
  - nie budujemy zrodla tylko z samych swiezych `[OK]`.

Krotko:
- `E3` potrzebuje logiki "zaworu w jedna strone".

### Co zostalo dzis domkniete
- `E3` nie ma juz liczyc tylko z "zywego" `char_effective_source`.
- Aktywna paczka `PZ2` zostala dopieta jako jawny stan projektu.
- `char_effective_source` musi uwzgledniac:
  - stage projektu,
  - aktywna paczke `PZ2`,
  - nowe `[OK]` z `Z2`.
- Powrot `E3 -> Z2` ma ukrywac obrazy juz obecne w aktywnej paczce `PZ2`.
- `PZ3` dostalo lokalna cofke do `PZ2`, bez wymuszania powrotu przez wizard.

### Co nadal zostalo do domkniecia

#### Priorytet 1. Pelna eliminacja heurystyki "najnowszy preview"
W krytycznych sciezkach `Z3` aktywna paczka ma byc brana:
1. z `step3_preview_dir`,
2. potem ewentualnie z jawnego `preferred_source_context`,
3. a dopiero na samym koncu z fallbacku katalogowego.

#### Priorytet 2. Odciecie semantyki workflow od snapshotow UI
`annotation_ui_state.json` moze zostac, ale tylko dla:
- scrolla,
- pozycji,
- wyboru widoku,
- kosmetyki.

Nie powinien juz byc zrodlem prawdy dla:
- aktywnej paczki `E3`,
- aktywnego zrodla `Z2`,
- gotowosci etapu.

#### Priorytet 3. Jeden helper licznikow dla toru znakow
Nie mozemy dalej miec kilku roznych logik:
- osobno dla `Z2`,
- osobno dla prawego panelu `E3`,
- osobno dla `char_effective_source`.

Potrzebny jest jeden helper domenowy, ktory zwraca:
- ile obrazow jest juz w aktywnej paczce `PZ2`,
- ile jest nowych `[OK]` do dopompowania,
- ile finalnie daje to tablic dla kolejnego przebiegu.

#### Priorytet 4. Swiadome rozdzielenie:
- `aktywny preview PZ2`
- `effective source dla E3`
- `projektowy stage tablic`

To sa trzy rozne rzeczy i nie wolno ich dalej mieszac.

### Wniosek architektoniczny na teraz
RC nie jest juz eksperymentem. RC dziala.

To, co zostalo, to nie "czy wprowadzac rejestr", tylko:
- przepiac ostatnie hybrydowe odczyty,
- wyciac heurystyki z krytycznych sciezek,
- i zamienic rozproszone cache GUI w czyste pomocnicze runtime state.

### Zasada na kolejne kroki
Kazdy nowy fix workflow ma przejsc przez trzy pytania:
1. Czy ten stan powinien zyc w `campaigns_registry.json`?
2. Czy ten artefakt powinien byc wskazywany w `artifact_registry.json`?
3. Czy GUI tylko to wyswietla, czy nadal probuje samo zgadywac?

Jesli odpowiedz na pytanie 3 brzmi "GUI zgaduje", to to jest kandydat do kolejnego przepiecia na RC.

### Dodatkowy krok RC domkniety po tej analizie
- `Z2` dostalo jawny wpis `step2_active_run` w `artifact_registry.json`.
- Przywracanie kampanii do `Z2` zaczyna teraz preferowac:
  1. `step2_active_run` z RC,
  2. potem ogolne `plate_source`,
  3. a dopiero dalej starsze fallbacki awaryjne.
- Powrot naprawczy `E3 -> Z2` nie powinien juz semantycznie polegac na:
  - `last_preview_run_dir`
  - ani `plate_dataset_run`
  ze snapshotu `annotation_ui_state.json`,
  jesli aktywny run `Z2` jest juz zapisany w RC.
- To jest kolejny krok w kierunku zasady:
  - `annotation_ui_state.json` = stan interfejsu
  - `artifact_registry.json` = aktywne artefakty iteracji
  - `campaigns_registry.json` = stan workflow projektu

### Kolejny krok RC domkniety
- Kampanijny snapshot `annotation_ui_state.json` nie zapisuje juz:
  - `plate_dataset_run`
  - `plate_dataset_images`
  - `last_preview_run_dir`
- Te pola byly historycznie wykorzystywane do odtwarzania aktywnego runu `Z2`,
  ale po wprowadzeniu `step2_active_run` staly sie zdublowanym zrodlem prawdy.
- Nowa zasada:
  - aktywny run `Z2` i jego katalog obrazow po stronie kampanii maja pochodzic z RC,
  - snapshot UI moze przechowywac tylko pomocnicze informacje sesyjne:
    - indeks,
    - nazwe ostatniego preview,
    - lokalne `[OK]`,
    - kosmetyke interfejsu.

### Kolejny krok RC domkniety po licznikach toru znakow
- W `campaign_manager.py` pojawil sie wspolny helper `get_step3_char_source_state()`.
- Ten helper liczy jedno, jawne zrodlo stanu `E3/char` z:
  - aktywnej paczki `PZ2`,
  - nowych `[OK]` z `step2_active_run`,
  - oraz z wykluczeniem tego, co jest juz w projektowym `ApprovedSet`.
- Kampania (`tab_campaign.py`) przestala skladac ten stan lokalnie w GUI.
- Prawy panel `Z2` (`tab_annotation.py`) zaczal korzystac z tego samego helpera dla zielonej ramki i liczb toru znakow.
- To odcina kolejny rozjazd typu:
  - `E3` liczy jedno,
  - `Z2` liczy drugie,
  - a RC trzyma trzecie.

## 2026-05-12

### Checkpoint Architektury GUI - Z2 / Z3 / Z4

### Co zostalo fizycznie rozdzielone

#### Z2
- `z2_campaign_flow.py`
- `z2_free_mode_flow.py`
- `z2_shared_ui.py`
- `z2_flow_models.py`
- host: `tab_annotation.py`

#### Z3
- `z3_campaign_flow.py`
- `z3_free_mode_flow.py`
- `z3_shared_ui.py`
- `z3_preview_ui.py`
- `z3_flow_models.py`
- `z3_view_models.py`
- host: `tab_character_annotation.py`

#### Z4
- `z4_campaign_flow.py`
- `z4_free_mode_flow.py`
- `z4_shared_ui.py`
- `z4_flow_models.py`
- `z4_view_models.py`
- host: `tab_training.py`

### Co to oznacza praktycznie
- `(C)` i `(F)` nie siedza juz na jednym wspolnym state machine w `Z2`.
- `Z3` nie trzyma juz kampanijnego wejscia, preview, kompasu, `PZ3 statusu` i wiekszosci przejsc w jednym monolicie hosta.
- `Z4` nie trzyma juz w hoście glownego shell workflow:
  - wyboru toru,
  - `PZ1 -> PZ2`,
  - powrotu do kampanii,
  - finish / complete project,
  - kampanijnego entry / restore.

### Co zostalo w hostach

#### `tab_annotation.py`
- host widgetow `Z2`
- lokalne helpery UI i runtime
- nadal sa wrappery/delegaty, ale najwieksze decyzje `C/F` sa juz wyjete

#### `tab_character_annotation.py`
- host widgetow `Z3`
- preview editing / OCR lab / niskopoziomowe akcje na znakach
- nadal sa wrappery, ale glowny workflow `C/F`, `PZ2/PZ3` i preview chrome sa juz poza hostem

#### `tab_training.py`
- host widgetow `Z4`
- niskopoziomowe helpery treningowe, walidacje, historię i analityke
- nadal zostaja lokalne funkcje stricte od treningu/modeli/GPU

### Najwazniejszy efekt architektoniczny
- mozemy teraz stabilizowac workflow bez ciaglego ryzyka, ze:
  - poprawka kampanii rozwali freemode,
  - poprawka freemode rozwali wizard,
  - a zmiana preview rozwali shell etapu.

### Co jeszcze nie jest idealne
- hosty nadal maja troche wrapperow i pomocniczych helperow domenowych
- `shared ui` w `Z3/Z4` jest juz duze i trzeba pilnowac, zeby nie zamienilo sie w nowy monolit
- `freemode` nie jest jeszcze przepiete na RC jako zrodlo prawdy

### Ocena checkpointu
- `Z2`: fundament mocny
- `Z3`: fundament bardzo mocny
- `Z4`: fundament juz sensowny i spojny z reszta, ale wymaga jeszcze testow regresji

### Rekomendacja po tym checkpointcie
Kolejny sensowny etap to juz nie dalsze ciecie w ciemno, tylko:
- checkpoint testowy `Z2/Z3/Z4`
- potem poprawki zachowania
- a dopiero na koncu ewentualne doczyszczanie ostatnich wrapperow.

### Wersja Inzynierska Architektury

```text
                                ┌───────────────────────┐
                                │ campaign_manager.py   │
                                │ RC / registry / stan  │
                                └───────────┬───────────┘
                                            │
                         kampania (C)       │       artefakty / status etapu
                                            │
        ┌───────────────────────────────────┼───────────────────────────────────┐
        │                                   │                                   │
        ▼                                   ▼                                   ▼

┌────────────────────┐             ┌────────────────────┐             ┌────────────────────┐
│ Z2 / E2            │             │ Z3 / E3            │             │ Z4 / E4            │
│ tab_annotation.py  │             │ tab_character_...  │             │ tab_training.py    │
│ host UI            │             │ host UI            │             │ host UI            │
└─────────┬──────────┘             └─────────┬──────────┘             └─────────┬──────────┘
          │                                  │                                  │
          │ delegates                        │ delegates                        │ delegates
          │                                  │                                  │
   ┌──────┼──────────────┐            ┌──────┼───────────────┐           ┌──────┼──────────────┐
   │      │              │            │      │       │       │           │      │      │       │
   ▼      ▼              ▼            ▼      ▼       ▼       ▼           ▼      ▼      ▼       ▼

[z2_campaign] [z2_free] [z2_shared]   [z3_campaign] [z3_free] [z3_shared] [z3_preview]
[z2_models]   [z2_view]               [z3_models]   [z3_view]

                                                                  [z4_campaign] [z4_free]
                                                                  [z4_shared]   [z4_models]
                                                                  [z4_view]

Legenda:
- `campaign_flow` = logika tylko dla (C)
- `free_mode_flow` = logika tylko dla (F)
- `shared_ui` = wspolny apply/render bez semantyki etapu
- `preview_ui` = canvas / fullscreen / overlay / kompas
- `flow_models` = typed kontrakty miedzy warstwami
- `view_models` = gotowe modele widoku
```

### Odczyt tej mapy
- hosty `tab_*` buduja widgety i deleguja logike dalej
- kampania korzysta z RC i artefaktow wskazanych przez RC
- freemode korzysta z lokalnego runtime / session / storage
- `Z2`, `Z3`, `Z4` zaczynaja miec ten sam, powtarzalny wzorzec modulu

### Wersja Produktowa Architektury

```text
                   UZYTKOWNIK
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
   KAMPANIA / WIZARD (C)       FREEMODE (F)
          │                         │
          │                         │
          ├──────────────┬──────────┤
          │              │          │
          ▼              ▼          ▼
        Z2/E2          Z3/E3      Z4/E4
     anotacja tablic   znaki       trening
          │              │          │
          │              │          │
          ▼              ▼          ▼
   osobny flow C/F  osobny flow C/F  osobny flow C/F

Dla (C):
- zrodlo prawdy = RC
- etapy sa prowadzone przez wizard
- artefakty iteracji sa odtwarzane z rejestru

Dla (F):
- zrodlo prawdy = lokalny runtime / session / storage
- brak prowadzenia przez wizard
- uzytkownik pracuje swobodnie po wlasnej sciezce

Cel architektury:
- poprawka w (C) nie rozwala (F)
- poprawka w (F) nie rozwala (C)
- host zakladki nie liczy juz calego workflow samodzielnie
```

### Odczyt wersji produktowej
- kampania i freemode sa rozdzielone nie tylko logicznie, ale tez modulowo
- kazdy etap `Z2 / Z3 / Z4` ma osobny przeplyw dla kampanii i dla trybu swobodnego
- RC prowadzi kampanie, a freemode pozostaje lokalnym trybem pracy

## 2026-05-13

### Z2 (F) - ostatnie zmiany miniflow autoanotacji

- Uporzadkowano semantyke toru auto w `Z2`:
  - `Tor (0) -> Wejscie (1) -> Autoanotacja (2) -> Korekta (3) -> Eksport (4)`.
- Wejscie do toru `Autoanotacja` startuje od czystego kroku wyboru obrazow.
- Sam wybor katalogu obrazow zostal odchudzony:
  - to juz tylko lekka walidacja sciezki,
  - bez ciezkiego budowania workspace na tym etapie.
- Ladowanie pelnego workspace `Z2` zostalo przypiete do przejscia `Dalej` z kroku `Wejscie`.
- Dodano guardy, ktore blokuja ponowne samoczynne odpalanie splash/workspace load:
  - po potwierdzeniu modala ustawien autoanotacji,
  - po zwyklym refreshu UI,
  - po przypadkowym restore stanu.
- Ustawienia modala autoanotacji przestaly byc przywracane jako trwaly stan sesji:
  - sciezka modelu tablic `.pt`,
  - wsparcie pojazdami,
  - model pojazdow / custom path,
  - `confidence`,
  - runtime meta modelu tablic.
- Wyjscie z miniflow do wyboru toru czysci teraz rowniez runtime ustawien modala autoanotacji.
- Krok `Wejscie` i krok `Autoanotacja` dostaly bardziej kompaktowy uklad:
  - mniej pionowych odstepow,
  - mniej meta-opisow miedzy gradientowym naglowkiem a karta,
  - czytelniejsze zawijanie tekstu.
- To samo zostalo dopiete dla kroku `Korekta`:
  - sekcja siedzi wyzej,
  - wrap tekstow jest bardziej przewidywalny.
- W kroku `Korekta` ukryto tekstowa sciezke runu:
  - zostal tylko przycisk otwarcia folderu runu.
- Ustabilizowano etykiete CTA w torze auto:
  - po cofnieciu z `Korekty` do `Autoanotacji` przycisk nie powinien juz zmieniac nazwy na warianty zalezne od trybu pojazdow.
- Pasek postepu autoanotacji zostal przepiety tak, aby windowal pod CTA `Start / ZATRZYMAJ`, a nie wyzej w karcie.

### Autoanotacja ze wsparciem pojazdow

- Tryb `Pojazdy + tablice` zostal przebudowany z filtra post-process na faktyczny wariant `vehicle-first`:
  - najpierw wykrywane sa pojazdy,
  - potem tablice sa szukane tylko w obrebie pojazdu.
- UI i copy w `Z2` zostaly dopasowane do tej semantyki:
  - wsparcie pojazdami jest opisane jako mechanizm pomocniczy,
  - boxy pojazdow nie sa komunikowane jako finalny artefakt YOLO.

### Backlog - rzeczy do doszlifowania pozniej

- Domknac `Z2` miniflow auto jako jeszcze bardziej zwarty modul:
  - mniej semantyki w hoście `tab_annotation.py`,
  - mniej rozproszenia miedzy `z2_free_mode_flow.py` i `z2_shared_ui.py`.
- Wyciagnac `workspace loader` i `splash/progress UI` do bardziej spojnego podmodulu:
  - dzis to nadal jest obszar wrazliwy na regresje.
- Pilnowac, aby `shared_ui` nie stalo sie nowym monolitem `Z2`.
- Dalsze porzadki copy:
  - usuwanie starych fallbackow tekstowych,
  - ograniczenie dublowania narracji dla toru auto.
- Dopic ostroznie testy regresji dla:
  - `Wejscie -> Autoanotacja`,
  - `Autoanotacja -> Korekta`,
  - `Korekta -> Eksport`,
  - powrot do wyboru toru,
  - restart aplikacji i restore sesji.

## 2026-05-19

### Log zmian od ostatniego wpisu

Od wpisu `2026-05-13` aplikacja zostala przesunieta z etapu "ciecia architektury" w etap stabilizacji zachowan uzytkownika. Najwiecej zmian dotyczylo przeplywow `Z2`, `Z3/PZ2`, `Z4`, wizarda kampanii oraz wspolnych mechanizmow canvasa.

### Wizard / kampania (C)

- Przeniesiono wybor toru pracy na poziom `E1`, tak aby uzytkownik wybieral kierunek iteracji przed wejsciem w kolejne etapy.
- Ujednolicono tabele wyboru zasobow w `E1`, rowniez dla iteracji wiekszych niz pierwsza.
- Dodano warunek, ze zatwierdzenie `E1` wymaga jednoczesnie wyboru katalogu obrazow oraz wyboru toru.
- Uszczelniono przejscie `E1 -> E2/E3`:
  - tor tablic prowadzi do `E2`,
  - tor znakow moze kierowac bezposrednio do `E3`, jezeli zrodlo znakowe jest gotowe.
- Zablokowano bypass `E1`, w ktorym `E2` moglo byc gotowe mimo braku zatwierdzenia zrodel w `E1`.
- Poprawiono odtwarzanie sciezki katalogu obrazow po przejsciu `E4 -> E1`.
- Dodano logike rozrozniajaca sytuacje:
  - w stage nadal sa obrazy oczekujace,
  - stage jest pusty i trzeba wskazac nowy katalog.
- Poprawiono liczniki w modalu analizy obrazow `E1`, aby rozroznialy realnie nowe obrazy od obrazow znanych juz w projekcie.
- Uproszczono modal po zakonczeniu `E4`, bo po przebudowie architektury dalsza decyzja odbywa sie w `E1`.
- Poprawiono badge i CTA zatwierdzania etapow, w tym wyjatek `E4`, gdzie etap moze zostac zamkniety rowniez bez treningu.

### Z2 / anotacja tablic

- Rozdzielono zachowania `Z2` dla trybu kampanii `(C)` i trybu swobodnego `(F)` w kolejnych miejscach przeplywu.
- Ustabilizowano miniflow autoanotacji w `(F)`:
  - wybor katalogu obrazow jest lekki,
  - pelne `Z2` laduje sie dopiero po przejsciu dalej,
  - modal ustawien autoanotacji startuje z ustawieniami domyslnymi,
  - wyjscie z miniflow czysci kontekst roboczy.
- Przebudowano krok korekty po autoanotacji:
  - rozrozniono decyzje `Wytnij tablice` oraz `Eksport i split datasetu`,
  - usunieto mylace CTA i stare copy,
  - dopisano warunek, ze eksport i wycinanie wymagaja zatwierdzonych obrazow ze statusem `[OK]`.
- W trybie recznej anotacji `(F)` doprowadzono przeplyw do tego samego schematu decyzyjnego co po autoanotacji.
- Wprowadzono ostrzezenia i modale informujace, ze obraz bez ramki nie powinien otrzymac statusu `[OK]`.
- Poprawiono zachowanie po wyjsciu z trybu naprawczego `E3 -> Z2`:
  - obrazy `[OK]` trafiaja do katalogu zatwierdzonych,
  - po ponownym wejsciu nie powinny wracac na liste robocza,
  - prawy panel pokazuje czytelniejsze liczniki.
- Dodano do prawego panelu trybu naprawczego licznik oznaczonych tablic i doprecyzowano copy o katalogu zatwierdzonych zdjec.
- Dodano i rozwijano overlaye canvasa:
  - szuflada narzedzi,
  - kompas,
  - parametry obrazu i ramek `PX`,
  - status bramki w fullscreen dla kampanii,
  - status zatwierdzenia obrazu.
- Poprawiono zachowanie kompasu, superkorekty i overlayow, aby ograniczyc kolizje z podgladem i lista.
- Dodano tabele metadanych modeli w modalach autoanotacji, w tym `map50-90`, epoke, typ modelu i parametry eksportu.
- Poprawiono obsluge eksportowanych modeli z kampanii do trybu swobodnego, aby ich metadane byly widoczne przy pozniejszym uzyciu.

### Z3 / wycinanie tablic i anotacja znakow

- Uproszczono `Z3/PZ1 (F)` dla kontynuacji z runu `Z2`:
  - zamiast dwoch kart miniflow pojawia sie tabela przejetego runu,
  - uzytkownik widzi nazwe runu, katalog obrazow, liczbe zdjec i liczbe anotacji do wyciecia,
  - glowne CTA wykonuje wycinanie tablic.
- Dodano zasade jednokrotnego wycinania tablic:
  - po udanym wycieciu przycisk zostaje zablokowany,
  - uzytkownik dostaje modal podsumowujacy,
  - aplikacja moze przejsc dalej do pracy na wycietych tablicach.
- Poprawiono przekazywanie aktualnego runu z `Z2` do `Z3`, aby nie wracaly stare cropy z poprzedniego runu.
- W `Z3/PZ2` rozbudowano pipeline detekcji znakow:
  - rozdzielono role `O`, `YB`, `YS`,
  - wybor modelu YOLO jest wspolny dla calego pipeline,
  - dodano ochrone manualnych ramek i tablic perfect,
  - dodano modal decyzji przed detekcja.
- Dodano rozroznianie metod na liscie tablic, np. `M`, `O`, `YB`, `YS` oraz kombinacje typu `OK|M|O|YB`.
- Poprawiono logike pipeline `OCR -> YOLO`, `YOLO -> OCR`, `OCR + YOLO` i budowniczego pipeline.
- Dodano splash postepu dla detekcji znakow.
- Uporzadkowano prawy panel `PZ2`:
  - szczegoly stanu,
  - liczniki perfectow,
  - czytelniejsze tabele,
  - mniej agresywne copy.
- Dodano asystenta operacji canvasowych w szufladzie `PZ2`.
- Poprawiono tryb wpisywania znakow `ALT+W`, aby nie wlaczal sie przypadkowo po samym nacisnieciu `W` na hoverze boxa.
- Ograniczono przypadki wypychania podgladu przez overlay asystenta operacji.
- Rozpoczeto porzadkowanie wydajnosci listy, zaznaczania grupowego i migotania boxow przy edycji.

### Z3/PZ3 / review pack, CVAT i gold pack

- Przebudowano narracje `PZ3`, aby jasno wyjasniala obieg:
  - eksport review pack do CVAT,
  - poprawki poza aplikacja,
  - import poprawek z powrotem.
- Usunieto niepotrzebny split z `PZ3`, bo warianty splitu sa domena `Z4`.
- Przeniesiono podsumowania importu/eksportu do modali.
- Uporzadkowano karty strategii i zrodel gold packa.
- Dodano dynamiczne tabele dla strategii i zakresu gold packa oraz backup zmian:
  - `backups/pz3_goldpack_tables_20260518_212803`.
- Poprawiano geometrie i szerokosci kolumn tabel, bo poprzedni uklad ucinal tresc.

### Z4 / dataset, split, trening i modele

- Uporzadkowano relacje `PZ1/PZ2`:
  - `PZ1` odpowiada za przygotowanie wariantu splitu,
  - `PZ2` sluzy do wyboru gotowego wariantu i treningu.
- Przywrocono mozliwosc pracy na roznych splitach bez ponownego eksportu z `Z2`.
- Rozdzielono semantyke datasetow znakow i tablic:
  - znaki: dataset YOLO detect z `images/labels` i `data.yaml`,
  - tablice: dataset pose oraz zgodnosc XML z obrazami.
- Dodano walidacje i komunikaty dla niegotowych zrodel datasetu.
- Dodano tworzenie brakujacego `data.yaml` dla datasetu znakow, gdy uzytkownik potwierdzi taka operacje.
- Przeniesiono stare katalogi klasyfikacyjne znakow do osobnego miejsca w drzewie workspace, aby nie mieszaly sie z datasetami YOLO.
- Dodano postep tworzenia datasetu w torze znakow.
- Poprawiono kolory paskow postepu i licznikow w `Z4`, aby byly zgodne z motywem.
- Dodano eksport wytrenowanego modelu z historii runow przez menu kontekstowe `PPM`:
  - eksport `best.pt`,
  - eksport metadanych modelu,
  - zapis do wlasciwego katalogu trybu swobodnego `char/pose`.
- Rozwijano raporty treningowe i wyniki, w tym przywracanie wykresow oraz czytelniejsza produkcje parametrow.
- Sprawdzano i poprawiano respektowanie globalnego wyboru `GPU/CPU` dla treningu oraz detekcji.

### Globalne UI, AS, help i stabilnosc

- Dodano globalnego asystenta `AS` do kolejnych zakladek i podzakladek, rowniez poza trybem swobodnym.
- Zmieniono zalozenie: `AS` ma byc dostepny w kazdym etapie, niezaleznie od `(C)` albo `(F)`.
- Rozbudowano slownik pojec asystenta, aby terminy typu `crop`, `dataset`, `YOLO`, `CVAT`, `model`, `epoka`, `trening`, `boxy` i `poligony` mialy wyjasnienia.
- Zaktualizowano globalny help i tresci `Z5`.
- Ustawiono wersje programu w pasku glownym na `4.0` oraz autora `R. Szuderski`.
- Dodano hover-chmurki dla ikon `Terminal` i `AS`.
- Poprawiono motywy:
  - scrollbary w trybie ciemnym,
  - zaznaczenia list,
  - dropdowny,
  - badge,
  - CTA i tabele.
- Poprawiano reakcje UI po zmianie motywu, aby wymuszac pelniejszy rerender.
- Wzmocniono zamykanie aplikacji krzyzykiem systemowym i sprzatanie zasobow.
- Rozbudowano `dependency_bootstrap.py`, aby komunikaty o brakach pakietow i problemach z pamiecia stronicowania byly czytelniejsze.

### Backlog - pomysl: iteracyjne dopasowanie boxow po OCR

Po testach `Z3/PZ2` widac, ze korekta polozenia boxow po OCR z uzyciem YOLO bywa zbyt malo precyzyjna. Obecny mechanizm nie bierze pierwszego losowego trafienia, ale nadal dziala jednoprzebiegowo: wybiera najlepszego kandydata z aktualnej listy detekcji YOLO i nie prowadzi aktywnego szukania lepszego wariantu.

Pomysl do dalszego rozwoju:

- dodac opcjonalny tryb `YB refine` / `precyzyjne dopasowanie boxow`;
- nie traktowac go jako domyslnej sciezki, tylko jako kosztowna opcje zaawansowana w pipeline;
- najpierw poprawic scoring kandydata:
  - confidence YOLO,
  - zgodnosc srodka z boxem OCR,
  - podobienstwo wysokosci do reszty znakow,
  - linia bazowa,
  - overlap/IoU z OCR,
  - kolejnosc znaku,
  - odleglosc od sasiadow;
- potem dodac iteracyjne przyblizenia:
  - kilka najlepszych kandydatow `top-k`,
  - lokalne przesuniecia,
  - lokalne skalowanie boxa,
  - limit iteracji,
  - limit czasu,
  - prog akceptacji ustawiany przez uzytkownika;
- zapisac metadane decyzji:
  - stary box,
  - nowy box,
  - score,
  - liczba iteracji,
  - metoda, np. `YB+R`;
- nie nadpisywac ramek manualnych;
- dla tablic `perfect` stosowac tylko wtedy, gdy uzytkownik jawnie wylaczy ochrone albo gdy dziala tryb bezpiecznej korekty geometrii bez zmiany tekstu.

Ocena: warto, ale dopiero po stabilizacji obecnego pipeline `O/YB/YS`. Najpierw nalezy dopracowac lekki scoring, a dopiero potem dodac ciezszy wariant iteracyjny.

### Backlog - problem: tablice dwurzedowe

Do dalszej analizy trzeba dodac obsluge tablic dwurzedowych. Obecny przeplyw `Z3/PZ2` i pipeline `O/YB/YS` sa projektowane glownie pod liniowy uklad znakow czytany od lewej do prawej. Dla tablic dwurzedowych moze to powodowac bledy w kolejnosci znakow, walidacji statusu `perfect`, dopasowaniu OCR do YOLO oraz eksporcie datasetu znakow.

Kierunek do rozpoznania:

- wykrywac, czy tablica ma jeden czy dwa rzedy znakow;
- sortowac znaki najpierw po rzedzie, potem po osi `X`;
- pokazac w `PZ2` jasny status ukladu tablicy: `1 rzad` / `2 rzedy` / `niepewne`;
- dopuscic reczna korekte przypisania znaku do rzedu;
- zapisac w `metadata.json` informacje o rzedzie znaku, aby eksport datasetu i walidacja perfect nie tracily tej struktury;
- sprawdzic, czy prostowanie tablic nie znieksztalca nadmiernie ukladu dwurzedowego;
- rozstrzygnac, czy tablice dwurzedowe maja byc obslugiwane pelnoprawnie, czy oznaczane jako przypadek wymagajacy recznej kontroli.

Ocena: temat wazny, ale do wdrozenia po stabilizacji bazowego pipeline znakow, bo zmienia zalozenie o liniowej kolejnosci znakow.

#### Dygresja architektoniczna - runtime odczytu tablic poza edytorem

Mechanizm `1R/2R` w edytorze `Z3/PZ2` pelni dzis przede wszystkim role bramki jakosciowej: pomaga zdecydowac, czy tablica moze otrzymac status `perfect`, a wiec czy moze wejsc do `gold packa` i posluzyc jako material treningowy.

Warto jednak odnotowac konsekwencje dla przyszlego uzycia wytrenowanego modelu poza aplikacja, np. w programie telefonicznym do identyfikacji tablic. Jesli model znakow zwraca osobne boxy znakow, aplikacja produkcyjna musi miec runtime'owy odpowiednik tej logiki:

- wykryc lub przyjac uklad tablicy `1R/2R`;
- dla `1R` ulozyc znaki od lewej do prawej;
- dla `2R` najpierw podzielic znaki na rzad gorny i dolny, a dopiero potem sortowac po osi `X`;
- zlozyc finalny tekst tablicy w poprawnej kolejnosci czytania.

Roznica polega na celu mechanizmu. W edytorze sluzy on walidacji datasetu i statusu `perfect/gold pack`. W runtime mobilnym lub produkcyjnym sluzylby juz nie walidacji, ale inferencji: zamianie wykrytych boxow znakow na poprawny numer rejestracyjny.

Alternatywa architektoniczna to trenowanie modelu/pipeline, ktory zwraca cala sekwencje znakow tablicy bez skladania z pojedynczych boxow. Przy obecnym podejsciu detekcyjnym `YOLO Detect` logika kolejnosci odczytu pozostaje jednak potrzebnym elementem aplikacji koncowej.

### Rzeczy do dalszej stabilizacji

- Oddzielic jeszcze mocniej runtime `(C)` i `(F)`, szczegolnie tam, gdzie `Z2` i `Z3` przekazuja sobie artefakty.
- Dopilnowac, aby `RC` bylo jedynym zrodlem prawdy dla kampanii.
- Ograniczyc zaleznosc widokow od starych fallbackow tekstowych i dynamicznych copy.
- Dopracowac wydajnosc:
  - przelaczanie obrazow,
  - zaznaczanie grup na listach,
  - odswiezanie badge i boxow,
  - prace po dlugim treningu i minimalizacji okna.
- Dopisac testy regresji dla:
  - `E1 -> E2/E3`,
  - `E3 -> Z2 -> E3`,
  - `Z2(F) -> Z3/PZ1 -> PZ2`,
  - pipeline `O/YB/YS`,
  - eksport modeli z `Z4` do katalogow trybu swobodnego,
  - odtwarzanie projektu po restarcie aplikacji.
