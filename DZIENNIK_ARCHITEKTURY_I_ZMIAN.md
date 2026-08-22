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

## 2026-05-20

### Diagnoza krytyczna - przeciek trybu `(F)` do kampanii `(C)`

Zidentyfikowano wazna przyczyne powracajacych rozjazdow copy i paneli `Z2`: o wyborze kontekstu decydowala flaga `app.campaign_free_mode`, nawet wtedy, gdy `CAMPAIGN` mial aktywny projekt. W praktyce oznaczalo to, ze stary albo niezsynchronizowany stan trybu swobodnego mogl wymusic buildery i payloady `(F)` w ekranie kampanii `(C)`.

Decyzja architektoniczna:

- aktywny projekt `CAMPAIGN.get_active_project_name()` jest nadrzednym zrodlem prawdy dla kontekstu kampanii;
- jezeli istnieje aktywny projekt, `campaign_free_mode` nie moze wybierac buildera `(F)`;
- w takim przypadku flaga `campaign_free_mode` ma byc defensywnie czyszczona;
- brak aktywnego projektu oznacza tryb swobodny `(F)`;
- `Z2` ma miec dodatkowy bezpiecznik przy budowie `Z2WorkflowBaseContext`, aby aktywny projekt wymuszal `campaign_context=True` przed wyborem payloadu copy i runtime.

Zmiany wdrozone jako invariant:

- `auto_annotation_tool/gui/app.py` - metoda `_is_free_mode_session_context()` oraz bramki nawigacji glownej respektuja aktywny projekt jako kontekst `(C)`;
- `auto_annotation_tool/gui/tab_annotation.py` - metoda `_is_free_mode_session_context()` nie pozwala juz, aby stale `campaign_free_mode=True` wprowadzilo `(F)` do aktywnego projektu;
- `auto_annotation_tool/gui/z2_shared_ui.py` - `build_z2_workflow_base_context()` ma drugi bezpiecznik na wypadek przyszlej regresji flagi.

Wniosek stabilizacyjny: przy kazdej kolejnej zmianie workflow `(C)/(F)` nie poprawiamy najpierw copy, tylko najpierw sprawdzamy router kontekstu. Jezeli panel freemode pojawia sie w kampanii, to jest to blad separacji kontekstu, a nie blad tekstu.

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

## 2026-05-21

### Decyzja architektoniczna - preflight toru znakow w E1 i bramka E3

Ustalono, ze `E1` nie zna i nie powinien udawac, ze zna stan bramki `E3`. W `E1` uzytkownik wybiera tor pracy i ewentualnie moze zostac skierowany do `E3`, ale `E1` wykonuje tylko preflight toru znakow, czyli ocene, czy start toru znakow ma sens przy dostepnych danych.

Wlasciwa bramka `E3` pozostaje domena kampanii i etapow `Z3/PZ2/PZ3`. Otwiera sie dopiero wtedy, gdy istnieje realny material do eksportu datasetu znakow.

#### Trzy filary preflightu toru znakow w E1

1. Obrazy wejsciowe biezacej iteracji.

   W pierwszej iteracji albo wtedy, gdy nie ma jeszcze anotacji, `E1` zna zasadniczo tylko liczbe obrazow w wybranym katalogu. To jest jedynie potencjal, a nie gwarancja liczby tablic.

   Bezpieczny prog startowy: minimum `10 obrazow`.

   Komunikat powinien mowic wprost: program widzi liczbe zdjec, ale nie wie jeszcze, ile tablic uda sie z nich przygotowac.

2. Zatwierdzone anotacje tablic z poprzednich iteracji.

   W kolejnych iteracjach `E1` moze korzystac z historii projektu. Jezeli istnieje pula zatwierdzonych anotacji tablic, to program zna liczbe tablic mozliwych do wyciecia.

   Jezeli liczba takich tablic jest wystarczajaca, tor znakow moze prowadzic do `E3/PZ1` albo `E3/PZ2`, zaleznie od tego, czy tablice sa juz wyciete.

3. Anotacje zaimportowane w biezacej iteracji.

   Jezeli uzytkownik importuje zgodne anotacje dla aktualnego katalogu zdjec, `E1` moze potraktowac je jako biezacy material tablicowy. Program powinien walidowac zgodnosc importu z obrazami i dopiero po potwierdzeniu dolaczac je do projektu.

#### Decyzje E1

- Jezeli `anotacje z poprzednich iteracji + import biezacej iteracji >= 10 tablic`, tor znakow ma realny material wejsciowy.
- Jezeli material tablicowy jest mniejszy niz `10`, ale katalog obrazow ma co najmniej `10 obrazow`, tor znakow jest dopuszczalny z ostrzezeniem. Uzytkownik musi przejsc przez `E2/Z2`, aby przygotowac tablice.
- Jezeli katalog obrazow ma mniej niz `10 obrazow` i nie ma wystarczajacych anotacji, tor znakow powinien byc blokowany albo bardzo mocno ostrzegany.

#### E2/Z2 - przygotowanie tablic

`E2/Z2` odpowiada za uzyskanie zatwierdzonych anotacji tablic. Dla toru znakow celem jest przygotowanie minimum `10` tablic, ktore bedzie mozna wyciac w `E3/PZ1`.

Jezeli uzytkownik nie osiaga minimum, powinien dostac modal z jasnymi wyjsciami:

- oznaczaj dalej w `Z2`;
- wroc do `E1` po wiekszy katalog zdjec;
- zmien tor pracy.

#### E3/PZ1 - wycinanie tablic

`PZ1` sprawdza, czy istnieje material do wyciecia:

- zatwierdzone anotacje z `E2`;
- zatwierdzone anotacje z poprzednich iteracji;
- importowane anotacje biezacej iteracji.

Po wycieciu tablic:

- jezeli powstalo co najmniej `10` cropow tablic, przejscie do `PZ2` ma sens;
- jezeli powstalo mniej niz `10`, uzytkownik powinien dostac modal awaryjny.

#### E3/PZ2/PZ3 - wlasciwa bramka E3

Bramka `E3` nie sprawdza juz potencjalu, tylko realna gotowosc datasetu znakow.

Warunek otwarcia bramki `E3`:

- minimum `10` tablic `perfect`;
- kazda liczona tablica ma poprawne boxy znakow;
- boxy maja etykiety znakow;
- tablice przechodza przez aktywny zakres `gold packa`;
- `PZ3` moze fizycznie zbudowac z nich zrodlowy dataset YOLO znakow.

Szuflada `PZ2(C)` powinna pokazywac:

- `Bramka E3`: `OTWARTA` albo `ZAMKNIETA`;
- `Warunek PZ3`: `OK` albo `BRAK`;
- `Jakosc zbioru`: `SLABY`, `PRZECIETNY`, `DOBRY`;
- `JEST`: liczba tablic spelniajacych warunek;
- `BRAKUJE`: ile brakuje do minimum `10`.

#### Scenariusz awaryjny

Mozliwy jest scenariusz, w ktorym `E1` przepuszcza tor znakow, bo katalog ma minimum `10 obrazow`, ale pozniej okazuje sie, ze z tych obrazow nie da sie uzyskac minimum tablic do otwarcia bramki `E3`.

Wtedy nie przechodzimy automatycznie przez `E4`, bo brak materialu nie jest zakonczeniem treningu. To jest problem zrodel.

Modal awaryjny powinien dac uzytkownikowi trzy wyjscia:

- `Wroc do E1 po wiekszy katalog`;
- `Oznacz wiecej tablic w E2/Z2`;
- `Zostan w E3 i poprawiaj recznie`.

`E4 bez treningu` pozostaje swiadomym wyborem uzytkownika, a nie automatyczna droga awaryjna.

#### Zasada stabilizacyjna

`E1` sprawdza potencjal startu toru znakow.

`E3` sprawdza realna gotowosc datasetu znakow.

Nie mieszamy tych dwoch rzeczy w copy, w szufladzie, w modalach ani w statusach kampanii.

#### Implementacja - pierwszy krok

W `Z1/E1` dodano preflight toru znakow:

- prog startowy `10 obrazow` dla scenariusza, w ktorym nie ma jeszcze istniejacego zrodla tablic;
- prog `10 tablic w istniejacym zrodle` dla scenariusza przejscia na podstawie materialu z poprzednich iteracji albo importu;
- ostrzegawczy modal przy wyborze toru znakow, gdy E1 widzi tylko potencjal obrazowy, ale nie widzi jeszcze materialu tablicowego;
- blokade automatycznego przeskoku z E1 do E3, jesli projekt ma tylko obrazy, a nie ma realnego zrodla tablic;
- karte toru znakow w E1 opisujaca aktualny stan preflightu prostym jezykiem.

Drugi krok stabilizacji ujednolica znaczenie `ready` dla toru znakow:

- stare kryterium `2 obrazy + dowolna liczba tablic` zostalo zastapione progiem `10 tablic`;
- `needs_more_tables` oznacza teraz realnie: sa jakies tablice, ale brakuje do minimum wejscia w prace nad znakami;
- badge i fallback E2 nie powinny juz otwierac E3 tylko dlatego, ze projekt ma pojedyncze zatwierdzone tablice.

Trzeci krok stabilizacji dodaje modal awaryjny dla `E2` w torze znakow:

- jezeli `E2/Z2` ma mniej niz `10` tablic, program nie przechodzi cicho do `E3`;
- uzytkownik dostaje licznik: obrazy z tablicami, tablice w zrodle, minimum i brakujace tablice;
- dostepne sa trzy decyzje: oznaczaj dalej w `Z2`, wroc do `E1` po wiekszy katalog zdjec albo wroc do `E1` i zmien tor;
- powrot do `Z2` z tego miejsca nie ustawia juz trybu naprawczego `E3`, bo problem nadal nalezy do domkniecia `E2`.

Czwarty krok stabilizacji domyka `E3/PZ1`:

- gotowy preview wycietych tablic nie odblokowuje `PZ2`, jezeli zawiera mniej niz `10` tablic;
- przy probie pracy na zbyt malym preview uzytkownik dostaje modal awaryjny z trzema decyzjami: wroc do `E1`, oznacz wiecej w `Z2` albo zostan w `PZ1`;
- powtorne wejscie do `PZ1` nie przepuszcza juz historycznego preview z poprzedniego, zbyt malego wyciecia;
- po wycieciu mniej niz `10` tablic program pokazuje ostrzezenie i nie skacze automatycznie do `PZ2`;
- warunek dotyczy tylko kontekstu kampanii `E3` w torze znakow, dlatego tryb swobodny nie powinien zostac zmieniony.

Piaty krok stabilizacji poprawia wejscie `E2/Z2` w torze znakow:

- brak modelu tablic `YOLO Pose` nie blokuje wejscia do `Z2`;
- model tablic jest traktowany jako przyspieszenie autoanotacji, a nie jako warunek startu;
- jezeli tor znakow nie ma jeszcze gotowego zrodla tablic ani modelu tablic, `Z2` startuje w trybie recznym: uzytkownik tworzy XML, oznacza tablice i zatwierdza poprawne zdjecia;
- status po otwarciu `Z2` nie komunikuje juz, ze model projektu zostal podstawiony, jezeli projekt takiego modelu nie ma.

Szosty krok stabilizacji rozpoczyna odejscie od fizycznego kopiowania zdjec miedzy iteracjami:

- `E1` i kolejne iteracje opieraja sie na manifeście wyboru zdjec, a nie na kopiowaniu calego katalogu do `1_raw_images/Iteracja_XXX`;
- `CampaignManager` dostal centralny kontrakt odczytu: liczba zdjec iteracji, katalog zrodla iteracji oraz realne sciezki plikow z manifestu;
- tryby `pool_reuse`, `stage_reuse` i `iteration_reuse` zapisuja manifest logicznego zrodla, nie przenosza zdjec do nowego katalogu iteracji;
- `Z2` korzysta z listy plikow manifestu, dzieki czemu nie powinno przypadkiem wczytywac calej duzej puli, jezeli iteracja ma pracowac tylko na podzbiorze;
- `Z3` i `Z4` zaczynaja korzystac z efektywnego zrodla obrazow iteracji zamiast zakladac, ze prawda lezy zawsze w fizycznym katalogu `Iteracja_XXX`;
- stare katalogi fizyczne pozostaja obslugiwane jako fallback dla projektow utworzonych przed ta zmiana.

Doprecyzowanie szostego kroku:

- walidacja importu anotacji w `E1` korzysta z nazw zdjec wybranych w manifeście, a nie z calego katalogu zrodlowego;
- autoanotacja `Z2(C)` traktuje manifest jako twardy zakres pracy. Jezeli manifest wskazuje 299 zdjec z katalogu 3000+, program nie moze sam rozszerzyc pracy na caly katalog;
- bundle artefaktow kampanii jest teraz odczytywany najpierw przez efektywne zrodlo iteracji, dopiero pozniej przez katalog glowny i stare `Iteracja_XXX`;
- w podsumowaniach `E2` liczba obrazow ma pochodzic z kontraktu `CampaignManager.get_iteration_image_count()`, zeby UI nie liczyl pustego katalogu fizycznego jako prawdy.
- cleanup stage dostal bezpiecznik: jezeli manifest iteracji wskazuje na pliki lezace w stage, katalog stage nie jest usuwany przez porzadkowanie po zmianie toru.
- `artifact_registry` dostal centralny token zestawu obrazow iteracji. Z2, Z3 i Z4 powinny dopisywac artefakty do jednego pakietu iteracji, zamiast tworzyc osobne pakiety dla katalogow roboczych albo tymczasowych subsetow.
- tymczasowy zakres autoanotacji w Z2 probuje teraz tworzyc linki twarde do obrazow zamiast pelnych kopii. Jezeli system plikow na to nie pozwoli, program wraca do bezpiecznego kopiowania pojedynczych plikow.
- synchronizacja stage po eksporcie datasetu tablic korzysta z listy obrazow manifestu, jezeli manifest istnieje. Dzięki temu stage kolejnej iteracji nie powinien zbierac calego katalogu zrodlowego, tylko faktyczny zestaw obrazow bieżącej iteracji.

Kolejne doprecyzowanie szostego kroku:

- wyciagniete buildery `Z2`, `Z3` i `Z4` nie powinny juz samodzielnie skladac glownego zrodla przez `1_raw_images/Iteracja_XXX`. Najpierw pytaja `CampaignManager` o efektywne zrodlo iteracji, a dopiero potem uzywaja starego katalogu jako fallbacku;
- fallback zatwierdzania `E1` po restarcie programu korzysta z manifestu iteracji, jezeli taki manifest istnieje. Dzieki temu pusty fizyczny katalog `Iteracja_XXX` nie powinien juz powodowac falszywego komunikatu o braku zdjec;
- manifest iteracji niesie jawne pola `manifest_only` oraz `image_set_token`, co ulatwia trzymanie artefaktow `Z2/Z3/Z4` przy tym samym logicznym zestawie zdjec.
- przeniesienie wejscia do kolejnej iteracji nie liczy juz calego katalogu zrodlowego, jezeli poprzednia iteracja byla manifestowym podzbiorem. Najpierw wykorzystywana jest lista plikow z manifestu poprzedniej iteracji;
- starszy tryb manifestu `planned` jest traktowany jak tryb manifestowy tak samo jak `planned_manifest`, zeby starsze projekty nie wracaly do pustego albo zbyt szerokiego fizycznego katalogu iteracji.
- roboczy merge katalogu wejscia `Z2` takze probuje uzywac linkow twardych przed pelnym kopiowaniem plikow. To ogranicza koszt czasowy i pamieciowy w sytuacjach, w ktorych Z2 musi zlozyc tymczasowy zakres pracy.
- reczne dodawanie obrazow do stage datasetu korzysta z tego samego wzorca: link twardy, a dopiero potem bezpieczny fallback do kopii.

Backlog stabilizacyjny po tej zmianie:

- przejrzec wszystkie miejsca, ktore nadal wyswietlaja uzytkownikowi pojecie `paczka`, i zamienic je na precyzyjne `katalog zdjec`, `manifest iteracji` albo `zestaw zdjec iteracji`;
- dodac w UI E1 czytelna informacje, czy iteracja korzysta z manifestu czy ze starego fizycznego katalogu;
- po testach GUI usunac ostatnie nieuzywane sciezki awaryjne oparte o reczne tworzenie katalogu `Iteracja_XXX`, jezeli nie beda juz potrzebne do zgodnosci wstecznej.

Kolejny krok porzadkowania slownika UI - 2026-05-21:

- aktywne komunikaty GUI nie uzywaja juz pojecia `paczka` dla katalogu zdjec, manifestowego wyboru obrazow ani zestawu roboczego Z2;
- w `Z2` nazewnictwo zakresu autoanotacji zostalo ujednolicone do `zestawu zdjec`, zeby modal i statusy nie sugerowaly fizycznego kopiowania katalogu;
- w `Z3/PZ1/PZ2` dawna `paczka tablic` zostala nazwana `zestawem wycietych tablic`, co lepiej opisuje wynik procesu wycinania i ogranicza pomieszanie z katalogiem zdjec z `E1`;
- globalny AS, help i opisy treningu rozrozniaja teraz `dataset`, `preview run`, `review pack` i `zestaw`, zamiast wrzucac wszystko do jednego potocznego pojecia;
- pozostawiono tylko wewnetrzne komentarze techniczne oraz nazwy domenowe typu `review pack`/`gold pack`, gdzie jest to swiadome pojecie funkcjonalne.

E1 jako panel kontrolny zrodla iteracji:

### Backlog - import boxow tablic i wielonumerowe nazwy obrazow - 2026-05-22

Do dalszej stabilizacji importu anotacji i przyszlego importu boxow tablic dopisujemy ryzyko kolizji semantycznej nazw plikow.

Przyklad:

- `1111_2222_3333_4444_001.jpg`;
- `1111_2222_8888_001.jpg`.

Problem polega na tym, ze dwa rozne obrazy moga miec czesciowo wspolne numery tablic w nazwie. Jezeli jakikolwiek mechanizm zaczalby dopasowywac ramki po pojedynczym tokenie, np. `1111`, zamiast po pelnej nazwie obrazu albo stabilnym kluczu z manifestu, mogloby dojsc do przypisania boxa z niewlasciwego obrazu.

Aktualna diagnoza:

- import anotacji w `E1` porownuje obrazy po pelnej znormalizowanej nazwie pliku, a nie po pojedynczym numerze tablicy;
- `Z3/PZ1` wycina tablice z konkretnego `source_image`, wiec same cropy nie sa tworzone przez dopasowanie po tokenie `1111`;
- do metadanych cropow PZ1 dodano `source_plate_index`, `source_plate_count`, `source_expected_text` oraz `source_expected_texts`;
- konkretny `source_expected_text` jest nadawany tylko wtedy, gdy liczba numerow odczytanych z nazwy pliku zgadza sie z liczba polygonow tablic w obrazie;
- jezeli przypadek jest niejednoznaczny, program nie powinien udawac, ze zna przypisanie konkretnego cropa do konkretnego numeru tablicy.

Wymaganie dla przyszlego importu boxow tablic:

- podstawowym kluczem dopasowania musi byc pelna nazwa obrazu, relatywna sciezka z manifestu albo stabilny `source key`, nigdy sam pojedynczy numer tablicy;
- nazwy wielonumerowe nalezy traktowac jako uporzadkowany zestaw oczekiwanych tablic, a nie jako niezalezne globalne identyfikatory;
- jezeli liczba boxow w imporcie nie zgadza sie z liczba numerow w nazwie, uzytkownik powinien dostac modal o niejednoznacznym dopasowaniu;
- dla duplikatow tej samej nazwy pliku w roznych folderach nie wystarczy basename. Trzeba uzyc relatywnej sciezki, manifestu albo tokenu zestawu zdjec;
- przy adopcji boxow warto dodatkowo zapisywac `source_bbox`, `source_polygon`, `source_plate_index` i ewentualnie wynik dopasowania po geometrii, zeby pozniejszy import mogl walidowac zgodnosc.

Ocena: to nie jest tylko detal importu. To zasada tozsamosci danych w calym przeplywie `E1 -> Z2 -> Z3/PZ1 -> PZ2`. Po stabilizacji warto wrocic do tego przed pelnoprawnym importem boxow tablic.

### Stabilizacja - wielorejestracyjne obrazy i status `perfect` w PZ2 - 2026-07-25

Nowy problem odkryty na projekcie `pisto`: jeden obraz moze zawierac kilka tablic, a nazwa pliku niesie kilka prawidlowych rejestracji, np.:

- `2TT0978_WI905PW_001.jpg`;
- przypadek z rejestracjami `365` oraz `WF3799Y`.

Proces `Z3/PZ1` poprawnie wycina z takiego obrazu kilka cropow tablic. Problem pojawia sie pozniej w `Z3/PZ2`, przy ocenie statusu tablicy jako `perfect` albo `do korekty`.

Dotychczasowe zalozenie bylo zbyt mocne:

- skoro mamy kilka rejestracji w nazwie pliku i kilka cropow, to mozna przypisac cropowi konkretny `source_expected_text` po kolejnosci;
- z tego pojedynczego tekstu mozna wyprowadzic oczekiwana liczbe znakow/boxow dla danego cropa.

To zalozenie rozsypuje sie, gdy kolejnosc cropow nie odpowiada kolejnosci rejestracji w nazwie albo gdy geometria wycinania zmieni kolejnosc. Wtedy np. crop tablicy `365` moze dostac oczekiwana liczbe znakow z `WF3799Y`, a crop `WF3799Y` liczbe z `365`. Program moze wtedy nieslusznie uznac prawidlowy odczyt za blad.

Ustalenie projektowe:

- zrodlem prawdy dla obrazu wielorejestracyjnego jest lista tokenow z nazwy pliku: `source_expected_texts`;
- pojedynczy `source_expected_text` moze byc tylko podpowiedzia wynikajaca z aktualnej kolejnosci, ale nie moze byc twardym warunkiem `perfect`;
- crop tablicy jest `perfect`, jezeli jego odczyt pasuje do dowolnego tokenu z `source_expected_texts` i wszystkie boxy sa eksportowalne;
- oczekiwana liczba boxow dla cropa powinna wynikac z dopasowanego odczytu, np. odczyt `365` oznacza oczekiwanie `3`, a odczyt `WF3799Y` oznacza oczekiwanie `7`;
- jezeli odczyt nie pozwala jednoznacznie dopasowac cropa do tokenu z nazwy, UI nie powinien udawac, ze zna liczbe znakow. Powinien pokazac stan nierozstrzygniety albo zakres mozliwych dlugosci, np. `3 lub 7`.

Koncept docelowego rozwiazania:

- dodac jeden helper kontraktu odczytu cropa, np. `resolve_expected_text_for_crop(data, chars)`;
- helper powinien zwracac dopasowany token, zrodlo dopasowania i status pewnosci;
- walidacja `perfect`, licznik oczekiwanych ramek, overlay statusu i `detector.expected_character_count` powinny korzystac z tego helpera, zamiast z indeksu cropa albo pojedynczego `source_expected_text`;
- `source_expected_texts` ma byc czytane przed `source_expected_text`;
- `source_expected_text` zostaje jako informacja pomocnicza, przydatna do diagnostyki i ewentualnego tie-breaku, ale nie jako nadrzedne ground truth;
- w przypadkach wieloznacznych program ma byc bezpieczny: nie nadawac falszywego `bad/needs_fix` tylko dlatego, ze przypisanie po kolejnosci cropow bylo nietrafione.

Wniosek:

Ground truth w torze znakow nie moze byc modelem `crop -> pojedynczy tekst po indeksie`. Musi byc modelem `source image -> zestaw dopuszczalnych rejestracji`, a przypisanie konkretnego cropa do konkretnej rejestracji powinno wynikac z faktycznego odczytu i geometrii, nie z samej kolejnosci wycinania.

Ujednolicenie progow bramek tablic - 2026-05-21:

- prog `2 oznaczone obrazy` zostal uznany za zbyt liberalny i historyczny;
- centralne progi kampanii sa teraz zapisane w `CONFIG`:
  - `CAMPAIGN_MIN_CHAR_IMAGES = 10`,
  - `CAMPAIGN_MIN_PLATE_ANNOTATIONS = 10`,
  - `CAMPAIGN_MIN_CHAR_PLATES = 10`;
- `E2/Z2`, overlay bramki, modal wyjscia do wizarda, panel E2 i blokada E4 w torze tablic licza minimum po zatwierdzonych tablicach, a nie po samej liczbie obrazow;
- tor znakow zachowuje ten sam prog `10 tablic`, zeby wejscie do `E3/Z3` nie bylo otwierane na zbyt malym materiale.

- w podsumowaniu E1 dodano wiersz `Tryb wejscia`, ktory pokazuje, czy iteracja korzysta z manifestowego zestawu zdjec, czy ze starego fizycznego katalogu iteracji;
- dodano wiersz `Sposob wyboru`, ktory przeklada techniczny `selection_mode` na jezyk uzytkownika;
- to jest celowo element stabilizacyjny: podczas testow widac od razu, czy Z2/Z3 powinny pracowac na manifeście, stage, ponownym uzyciu poprzedniego zestawu czy legacy katalogu.

### Stabilizacja Z4/PZ1/PZ2(F): wspolny wzorzec zrodla treningowego - 2026-05-23

Problem do uporzadkowania:

- w trybie swobodnym `Z4/PZ1` pokazuje rozne techniczne formaty wejscia zalezne od toru: dla tablic `XML + obrazy`, dla znakow gotowy dataset YOLO z `data.yaml`;
- technicznie jest to poprawne, ale dla uzytkownika tworzy wrazenie dwoch roznych filozofii pracy;
- UI nie powinno zmuszac uzytkownika do myslenia w kategoriach `XML` kontra `YAML`, tylko w kategoriach: `zrodlo datasetu`, `walidacja`, `split treningowy`, `wariant treningu`;
- porzadkowanie musi zaczac sie od `(F)`, bez ruszania kampanii `(C)`, zeby nie rozlac bramek, manifestow i logiki etapow.

Decyzja stabilizacyjna:

- zachowujemy fakt, ze rozne tory moga miec rozne formaty fizyczne;
- wprowadzamy wspolny kontrakt logiczny zrodla treningowego, ktory ukrywa roznice techniczne przed reszta UI;
- `PZ1(F)` ma sluzyc do wyboru albo utworzenia zrodla splitu, a `PZ2(F)` ma trenowac na wybranym wariancie, bez ponownego recznego skladania sciezek;
- statusy typu `Gotowy do PZ2` nie moga pojawiac sie bez aktywnie wybranego albo utworzonego zrodla.

Planowany kontrakt roboczy:

- `target`: `plates` albo `chars`;
- `kind`: `annotation_xml_images` albo `yolo_dataset`;
- `annotation_file`: plik anotacji, jezeli zrodlem jest XML;
- `images_dir`: katalog obrazow zgodnych z anotacjami, jezeli jest wymagany;
- `dataset_dir`: katalog datasetu, jezeli zrodlem jest gotowy dataset YOLO;
- `yaml_path`: plik `data.yaml`, jezeli dataset juz go ma albo program go wygenerowal;
- `validated`: wynik walidacji zrodla;
- `stats`: liczba obrazow, etykiet, klas, elementow train/val/test i ewentualne ostrzezenia;
- `provenance`: informacja, skad zrodlo pochodzi, np. `Z2`, `Z3/PZ2`, import albo reczny wybor.

Adaptery docelowe:

- `PlateXmlImagesSourceAdapter` waliduje zgodnosc XML z katalogiem obrazow i przygotowuje wariant YOLO Pose;
- `CharYoloDatasetSourceAdapter` waliduje `images/labels/data.yaml`, potrafi zaproponowac utworzenie brakujacego `data.yaml` i przygotowuje wariant splitu;
- oba adaptery zwracaja ten sam typ podsumowania, dzieki czemu tabele, modale i walidatory moga korzystac ze wspolnego wzorca.

Etapy wdrozenia:

- Etap 1: uporzadkowac jezyk UI `Z4/PZ1/PZ2(F)`, usunac zbedne radiobuttony zrodel i nie pokazywac technicznych formatow jako glownej decyzji uzytkownika;
- Etap 2: dodac lekki model `TrainingSource` bez przepinania calej logiki naraz;
- Etap 3: nauczyc `PZ1(F)` produkowac `TrainingSource`, a `PZ2(F)` czytac go jako jedyne zrodlo prawdy;
- Etap 4: przeniesc walidacje, tabele i modale na `TrainingSource.stats`;
- Etap 5: dopiero po stabilizacji `(F)` ocenic, czy kampania `(C)` potrzebuje mostu do tego samego kontraktu.

Kryteria akceptacji:

- uzytkownik widzi jedno pojecie `dataset treningowy` niezaleznie od toru;
- `XML`, `obrazy`, `data.yaml` i `labels` sa szczegolami technicznymi walidacji, a nie glownymi wyborami w UI;
- `PZ1(F)` nie pokazuje falszywej gotowosci bez aktywnego zrodla;
- `PZ2(F)` nie pozwala trenowac na niejawnie odziedziczonym albo starym wariancie;
- zmiany w `(F)` nie zmieniaja zachowania bramek, manifestow i etapow w `(C)`.

Ocena: to jest ruch stabilizacyjny, a nie funkcja kosmetyczna. Celem jest zmniejszenie liczby miejsc, w ktorych UI, walidacja i trening samodzielnie interpretuja zrodla danych.

Pierwszy krok wdrozenia:

- dodano lekki kontrakt `TrainingSource` oraz `TrainingSourceStats` w modelach przeplywu Z4;
- `PZ1(F)` zaczyna cache'owac ostatnie aktywne zrodlo treningowe jako jeden obiekt, zamiast rozrzucac interpretacje po samych zmiennych sciezek;
- tabela `Podsumowanie splitu` korzysta juz z tego kontraktu, ale stare pola `dataset_var` i `TrainingInputContext` pozostaja jako fallback;
- to jest celowo maly krok: najpierw stabilizujemy sposob reprezentacji zrodla, a dopiero pozniej przenosimy walidacje i modale na adaptery.

Drugi krok wdrozenia:

- walidacja wejscia `PZ1(F)` tworzy juz roboczy `TrainingSource` dla obu sciezek:
  - `annotation_xml_images` dla tablic,
  - `yolo_dataset` dla znakow;
- po poprawnym utworzeniu wariantu splitu `PZ1(F)` zapisuje gotowy dataset jako `TrainingSource` z licznikami `train/val/test/total`;
- dzieki temu `PZ2(F)` bedzie moglo docelowo czytac gotowy wariant z jednego kontraktu, zamiast z samych pol tekstowych i historycznego kontekstu.

Trzeci krok wdrozenia:

- start treningu w `PZ2(F)` zaczyna rozwiazywac aktywny dataset przez `TrainingSource`;
- pole tekstowe datasetu pozostaje kompatybilnym fallbackiem, ale nie jest juz jedynym zrodlem prawdy;
- to przygotowuje kolejny etap: przeniesienie walidacji treningu i komunikatow modali na wspolny kontrakt zrodla.

Czwarty krok wdrozenia:

- centralne rozpoznawanie `data.yaml` treningu korzysta teraz najpierw z `TrainingSource`, a dopiero pozniej z pola tekstowego;
- podsumowanie uruchamianego treningu pokazuje pochodzenie aktywnego datasetu;
- wskazowki zakresu treningu w `PZ2(F)` takze czytaja aktywne zrodlo przez kontrakt, co ogranicza ryzyko pracy na starym albo niejawnie odziedziczonym wariancie.

Domkniecie fundamentu:

- dodano adapter `PlateXmlImagesSourceAdapter`, ktory waliduje wejscie `XML + katalog obrazow` i zwraca `TrainingSource` typu `annotation_xml_images`;
- dodano adapter `CharYoloDatasetSourceAdapter`, ktory korzysta z istniejacej walidacji datasetu znakow i zwraca `TrainingSource` typu `yolo_dataset`;
- `PZ1(F)` nie sklada juz roboczego zrodla treningowego przez lokalne slowniki w `tab_training.py`, tylko przez adaptery;
- usunieto lokalny helper budujacy wejściowy `TrainingSource`, bo po dodaniu adapterow stal sie martwa warstwa posrednia;
- na tym etapie kampania `(C)` pozostaje odseparowana. Nowy kontrakt jest gotowy do stopniowego wykorzystania w `(C)`, ale nie zmienia jej bramek ani manifestow.

Dwa kolejne kroki domykajace:

- `PZ2(F)` ma teraz jedna brame walidacji aktywnego zrodla treningowego. Stan przycisku treningu i sam start treningu korzystaja z tego samego sprawdzenia `TrainingSource -> data.yaml -> validate_dataset`;
- dodano cache walidacji aktywnego datasetu PZ2, oparty o sciezke datasetu, tor i czasy modyfikacji `data.yaml` oraz katalogow `images/train`, `images/val`, `images/test`. Dzieki temu odswiezanie UI nie musi za kazdym razem skanowac katalogow splitu.

Backlog po stabilizacji - schemat klas datasetu - 2026-05-24:

Pomysl: dodac mozliwosc swobodnego nadawania etykiet klasom datasetow, ale nie przez reczna edycje `data.yaml`.

Diagnoza:

- w YOLO pliki labeli przechowuja numery klas, a `data.yaml` tlumaczy te numery na nazwy;
- sama zmiana nazwy w `data.yaml` moze byc bezpieczna dla treningu, ale nie musi byc bezpieczna dla aplikacji, OCR, importu, inferencji i dalszego mapowania wynikow;
- szczegolnie w torze znakow nazwa klasy nie jest tylko opisem. Program musi wiedziec, ze dana klasa oznacza konkretny znak, np. `A`, a nie dowolna etykiete wyswietlana uzytkownikowi.

Proponowany kierunek:

- wprowadzic obok `data.yaml` dodatkowy plik `dataset_classes.json`;
- rozdzielic stabilne `id` klasy, techniczne znaczenie `canonical`, nazwe treningowa `train_name` i nazwe wyswietlana `display_name`;
- dla znakow przechowywac dodatkowo `symbol`, zeby aplikacja zawsze mogla odtworszyc semantyke klasy po inferencji;
- generowac `data.yaml` z tego schematu, zamiast traktowac YAML jako jedyne zrodlo prawdy.

Przykladowy kontrakt:

- `id`: stabilny numer klasy z labeli YOLO;
- `canonical`: techniczne znaczenie, np. `plate` albo `char:A`;
- `train_name`: nazwa zapisywana do `data.yaml`;
- `display_name`: nazwa widoczna w GUI;
- `aliases`: opcjonalne zgodne nazwy importowe;
- `symbol`: opcjonalny znak dla toru znakow.

Etapy wdrozenia po stabilizacji:

- dodac maly modul `dataset_class_schema.py`, ktory czyta, waliduje i zapisuje schemat klas;
- nauczyc eksport datasetu tablic i znakow tworzyc `dataset_classes.json` razem z `data.yaml`;
- dodac w UI mala tabele klas z kolumnami `ID`, `znaczenie`, `etykieta treningowa`, `etykieta w programie`;
- przy treningu i imporcie traktowac `dataset_classes.json` jako preferowane zrodlo semantyki, a `data.yaml` jako format kompatybilnosci z YOLO;
- zachowac fallback dla starych datasetow, ktore maja tylko `data.yaml`.

Ocena: to jest pomysl stabilizacyjno-architektoniczny, nie kosmetyka. Pozwoli nazwac klasy po ludzku bez utraty jednoznacznosci danych i bez ryzyka, ze zmiana etykiety w GUI rozbije pozniejsza inferencje albo import.

## Stabilizacja finalna: ciecie, testy, zamrozenie - 2026-05-26

Cel: przejsc z etapu szerokiej przebudowy architektury do etapu kontrolowanej stabilizacji. Od tego punktu nowe zmiany maja byc oceniane przede wszystkim pod katem ryzyka regresji w `(C)` i `(F)`.

### Krok 1: odgruzowanie architektury

- `app.py` zostal odciazony przez przeniesienie motywow, stylowania widgetow i dialogow do `app_theme_runtime.py`.
- `tab_character_annotation.py` zostal odciazony przez przeniesienie delegatow workflow ekstrakcji Z3 do `z3_character_extract_delegates.py`.
- `z2_main_widgets.py` zostal odciazony przez przeniesienie poznych bindow help/event do `z2_main_widget_bindings.py` oraz prawego panelu Z2 do `z2_right_panel_widgets.py`.
- Ciecia dotycza fasad i builderow UI. Nie zmieniaja kontraktow `(C)/(F)`, bramek etapow ani manifestow.

### Krok 2: test automatyczny po cieciach

Wykonano:

- pelna kompilacja `python -B -m compileall -q auto_annotation_tool`;
- import smoke dla `AutoAnnotationApp`, `AnnotationTab`, `CharacterAnnotationTab`, `CampaignManager`;
- `git diff --check` dla dotknietych modulow.

Wynik: testy techniczne przeszly. Pozostaje standardowe ostrzezenie CRLF/LF dla `campaign_manager.py`, bez bledow whitespace.

### Krok 3: zamrozenie funkcjonalne przed testami GUI

Do czasu przejscia trzech scenariuszy testowych nie dokladamy nowych duzych mechanik:

- tor tablic: od E1 przez Z2, Z4/PZ1, Z4/PZ2 i E4;
- tor znakow: od E1 przez E2/Z2, Z3/PZ1, Z3/PZ2, Z3/PZ3, Z4 i E4;
- tryb mieszany: zmiana toru miedzy iteracjami oraz ponowne wejscie do etapow po restarcie projektu.

Dozwolone sa tylko poprawki:

- regresji blokujacych flow;
- blednych licznikow, bramek i statusow;
- oczywistych problemow copy/kodowania;
- bezpiecznych optymalizacji, ktore nie zmieniaja kontraktu danych.

Zasada: jezeli poprawka wymaga nowego kontraktu danych albo przebudowy przeplywu, trafia do backlogu po stabilizacji, chyba ze blokuje przejscie jednego z trzech glownych scenariuszy.

## Kampania jako graf i maszyna stanow - 2026-06-03

Cel: odejsc od rozproszonych decyzji ukrytych w panelach etapow i przejsc do jawnego modelu grafowego. Kampania `(C)` ma byc opisana jako maszyna stanow, w ktorej wezly glowne reprezentuja etapy `E1`, `E2`, `E3`, `E4`, a krawedzie reprezentuja pojedyncze przejscia z wlasnymi wymaganiami, zasobami, akcjami i zatwierdzeniem.

Diagnoza:

- dotychczasowy wizard laczyl stan etapu, decyzje uzytkownika, zasoby i akcje w wielu miejscach UI;
- przez to copy, statusy bramek i dostepnosc CTA mogly sie rozjezdzac po kolejnych refaktorach;
- wybor toru `tablice/znaki` nie powinien byc osobnym magicznym stanem, tylko wynikiem wyboru konkretnej krawedzi grafu;
- badge krawedzi ma byc oknem na pojedyncze przejscie, a nie ogolnym panelem etapu.

Docelowy model:

- graf glowny pokazuje cykl `E1 -> E2 -> E3 -> E4 -> E1`;
- krawedzie standardowe sa ciagle, a skoki warunkowe, np. `E1 -> E3`, sa przerywane;
- kazda krawedz ma badge/bramke z czterema polami: `Bramka`, `Zasoby`, `Akcje`, `Zatwierdz`;
- klikniecie w `Zasoby` pokazuje modal zasobow wymaganych przez dana krawedz;
- klikniecie w `Akcje` pokazuje tylko akcje przypisane do tej konkretnej krawedzi, bez mieszania akcji z innych przejsc;
- klikniecie w `Zatwierdz` wykonuje zatwierdzenie przejscia, jezeli bramka jest otwarta;
- aktywna krawedz definiuje aktualny zestaw wymagan i mozliwych akcji.

Aktualna macierz przejsc kampanii po rozdzieleniu `E4T/E4Z` i scaleniu dawnych `T01/T02`:

| ID | Przejscie | Cel | Minimum | Opcjonalne zasoby | Efekt |
|---|---|---|---|---|---|
| `T01` | `E1 -> E2` | Przygotowanie anotacji tablic dla obrazow z zasobow | `O` | `MT`, `MZ`, `AT`, `AZ` | Otwiera E2/Z2; w pracy bramki wybieramy, czy powstale `AT` zasila model tablic, czy tor znakow |
| `T03` | `E1 -> E3` | Praca nad znakami na istniejacym zbiorze wyodrebnionych tablic | `AT` albo zatwierdzone/wyodrebnione tablice z projektu | `MZ`, `AZ` | Pomija E2 i otwiera E3/Z3 bez ponownego oznaczania tablic |
| `T04` | `E2 -> E3` | Przekazanie zatwierdzonych tablic do pracy nad znakami | zatwierdzone obrazy z anotacjami tablic | `MT` | Wyodrebnia tablice i otwiera E3/Z3 |
| `T05` | `E2 -> E4T` | Dataset i trening modelu tablic | zatwierdzone anotacje tablic | `MT` jako baza | Otwiera Z4 dla modelu tablic |
| `T06` | `E3 -> E4Z` | Przygotowanie datasetu znakow do treningu | dataset YOLO znakow | `MZ` jako baza | Otwiera Z4 dla modelu znakow |
| `T07` | `E4T/E4Z -> E1` | Zamkniecie iteracji | trening zakonczony albo jawnie pominiety | nowy `MT` albo `MZ` z treningu | Wraca do E1 kolejnej iteracji |

Slownik zasobow wejsciowych:

- `O` - katalog obrazow;
- `MT` - model tablic;
- `MZ` - model znakow;
- `AT` - anotacje tablic;
- `AZ` - anotacje znakow.

Zasoby `O`, `AT` i `AZ` powinny miec liczniki. Licznik `O` informuje o liczbie obrazow, licznik `AT` o liczbie zgodnych obrazow i tablic, a licznik `AZ` o liczbie zgodnych tablic/znakow. Dzieki temu graf moze pokazac nie tylko, czy zasob istnieje, ale tez czy ma sensowna skale dla dalszego etapu.

Macierz zasobow E1/IT1:

| Zasoby | Sens | Domyslna sciezka |
|---|---|---|
| `O` | Tylko obrazy, brak wiedzy o tablicach | `E1 -> E2` |
| `O + MT` | Obrazy i model tablic | `E1 -> E2`, autoanotacja tablic mozliwa w Z2 |
| `O + AT` | Obrazy i gotowe anotacje tablic | `E1 -> E3` albo `E1 -> E2` jako korekta |
| `O + MT + AT` | Anotacje tablic i model tablic | `E1 -> E3`, E2 jako uzupelnienie |
| `O + MZ` | Model znakow bez tablic | `E1 -> E2`, bo brakuje tablic |
| `O + AT + MZ` | Gotowe tablice i model znakow | `E1 -> E3` |
| `O + AT + AZ` | Tablice i anotacje znakow | mozliwy skok blizej `E4` po walidacji |
| `O + MT + MZ` | Modele sa, ale brak anotacji tablic | `E1 -> E2` |
| `O + MT + AT + MZ` | Pelny start do znakow | `E1 -> E3` |
| `O + MT + AT + MZ + AZ` | Najbogatszy import | walidacja i mozliwy skok do `E4` |
| dataset YOLO bez `O` | Trening bez kampanijnej puli obrazow | `E1 -> E4` jako sciezka specjalna |

Wniosek architektoniczny:

- copy powinno wynikac z zasobow i krawedzi, a nie byc wpisywane recznie w wielu miejscach;
- import `AT` w E1 i ewentualna adopcja `AT` w Z2 powinny korzystac z tego samego kontraktu walidacji;
- jezeli model `MT` mozna wskazac jako wsparcie autoanotacji, to `AT` rowniez powinno miec logiczna droge adopcji do biezacej pracy Z2;
- przyszly AS powinien korzystac z tej samej macierzy, zeby tlumaczyc uzytkownikowi aktualny cel, brakujace zasoby i sens najblizszego przejscia.

Plan wdrozenia:

- wydzielic lekki katalog zasobow kampanii, ktory opisuje `O`, `MT`, `MZ`, `AT`, `AZ`, ich zrodla i liczniki;
- przypisac do kazdej krawedzi grafu wymagania minimalne, zasoby opcjonalne i akcje;
- podpiac modal `Zasoby` badge do tego katalogu, zamiast do rozproszonych fragmentow paneli;
- generowac status bramki i copy z jednej funkcji, ktora zna aktywna krawedz i stan zasobow;
- dopiero pozniej dodac adopcje `AT` w Z2 jako konsekwencje tego modelu, a nie jako kolejny wyjatek UI.

Ocena: to jest ruch stabilizacyjny. Graf nie powinien byc tylko nowa warstwa wizualna nad starym wizardem. Docelowo ma byc mapa decyzyjna kampanii i jedno zrodlo prawdy dla przejsc, zasobow, bramek i copy.

## Stabilizacja po wdrozeniu grafu i maszyny stanow - 2026-06-12

Cel: doprowadzic graf kampanii z poziomu prototypu wizualnego do realnego systemu sterowania przeplywem oraz ograniczyc liczbe miejsc, w ktorych stary wizard, Z2, Z3 i Z4 wzajemnie dubluja logike.

### 1. Graf kampanii jako aktywna mapa przejsc

Od poprzedniego wpisu graf przestal byc tylko wizualizacja. Zaczal przejmowac role glownego centrum decyzji kampanii:

- dodano osobne moduly opisujace graf, przejscia i zasoby:
  - `campaign_transition_specs.py`,
  - `campaign_transition_graph.py`,
  - `campaign_transition_evaluator.py`,
  - `campaign_transition_copy.py`,
  - `campaign_transition_resource_report.py`,
  - `campaign_resource_catalog.py`,
  - `campaign_resource_state.py`,
  - `campaign_stage_state.py`;
- bramka grafu jest traktowana jako okno na jedno konkretne przejscie, a nie jako ogolny panel etapu;
- wybor bramki przez elektrode okresla aktywna sciezke, a pozostale bramki sa wygaszane albo ograniczane;
- akcje bramki sa filtrowane przez aktywne przejscie, zeby modal akcji nie mieszal decyzji z innych krawedzi;
- zaczeto rozroznienie zachowania bramek w zaleznosci od iteracji, szczegolnie dla pierwszej iteracji, ktora ma inne wymagania niz iteracje kolejne;
- dodano animacje prowadzenia uwagi po grafie, wezle i bramkach, jako jednorazowy sygnal dla uzytkownika;
- poprawiano zachowanie zoomu, przesuwania wezlow, przesuwania badge oraz przeliczania lacznikow podczas dragu.

Wniosek: graf staje sie docelowym modelem decyzyjnym kampanii, a stary wizard ma byc stopniowo odcinany, a nie utrzymywany jako rownolegly system prawdy.

### 2. Porzadkowanie UI kampanii

W obrebie kampanii wydzielono i uporzadkowano kolejne warstwy:

- `campaign_shell_ui.py` przejmuje szkielet ekranu kampanii;
- `campaign_dashboard_ui.py` odpowiada za rysowanie i interakcje grafu;
- `campaign_graph_actions.py` obsluguje modale zasobow, akcji i zatwierdzen;
- `campaign_navigation.py` odpowiada za przejscia z grafu do zakladek roboczych;
- `campaign_project_browser.py` i `campaign_project_history.py` porzadkuja prace z projektami i historia;
- `campaign_assistant.py` zostal odchudzony, aby AS nie byl kolejnym miejscem z wlasna logika przeplywu;
- usunieto dawny `campaign_step1_panel_ui.py`, bo byl dinozaurem starego modelu E1 i zaczynal wchodzic w parade maszynie stanow.

Zasada po tych zmianach:

- graf mowi, dokad i po co idziemy;
- zakladki robocze wykonuja prace;
- manager kampanii i katalog zasobow sa zrodlem stanu;
- panele UI nie powinny same zgadywac semantyki przejsc.

### 3. Katalog zasobow i historia projektu

Dodano fundament pod lekkie sledzenie zasobow i historii:

- `campaign_project_history.py` - historia projektu i zdarzen;
- `campaign_project_registry.py` - rejestr projektow;
- `campaign_iteration_paths.py` - sciezki iteracji;
- `campaign_plate_annotation_contract.py` - kontrakt anotacji tablic w kampanii.

Ustalony kierunek:

- historia ma byc lekka, ale uzyteczna;
- powinna pokazywac, co zostalo wyprodukowane w iteracji;
- powinna wskazywac, ktore przejscia grafu doprowadzily do obecnego stanu;
- docelowo poradnik wyboru sciezki powinien korzystac nie tylko z aktualnego stanu zasobow, ale tez z historii projektu.

### 4. Odchudzenie aplikacji glownej

`app.py` zostal rozbity na mniejsze moduly:

- `app_startup.py`,
- `app_shutdown.py`,
- `app_delegates.py`,
- `app_menu_dropdown.py`,
- `app_global_terminal.py`,
- `app_project_history.py`,
- `app_style_setup.py`,
- `app_theme_definitions.py`,
- `app_theme_runtime.py`,
- `app_tooltips.py`,
- `app_window_recovery.py`.

Cel tej zmiany:

- ograniczyc rozmiar glownej fasady aplikacji;
- oddzielic startup, shutdown, menu, motywy, terminal i historie;
- ulatwic dalsze ciecie bez ryzyka, ze poprawka w menu lub motywie dotknie logiki kampanii.

### 5. Z2: stabilizacja wejscia, autoanotacji i duzych projektow

Najwiecej pracy stabilizacyjnej dotyczylo Z2, szczegolnie projektu NEON i wejsc z bramek T04/T06.

Wydzielono kolejne moduly:

- `z2_campaign_flow.py`,
- `z2_campaign_runtime.py`,
- `z2_context_runtime.py`,
- `z2_session_runtime.py`,
- `z2_restore_workflow.py`,
- `z2_run_io_runtime.py`,
- `z2_run_lifecycle.py`,
- `z2_manifest_runtime.py`,
- `z2_preview_state.py`,
- `z2_preview_workflow.py`,
- `z2_preview_editor.py`,
- `z2_canvas_interaction.py`,
- `z2_canvas_overlays.py`,
- `z2_canvas_metrics_ui.py`,
- `z2_right_panel_widgets.py`,
- `z2_layout_ui_runtime.py`,
- `z2_auto_scope_modal.py`,
- `z2_model_dialogs.py`,
- `z2_model_runtime.py`,
- `z2_model_quality_ui.py`,
- `z2_panel_workflow.py`,
- `z2_workflow_methods.py`.

Wykonane stabilizacje:

- wejscie do Z2 z grafu nie powinno juz pokazywac przebitki trybu swobodnego;
- prawy panel Z2 w kampanii zostal przywrocony po regresji, w ktorej zostawalo samo CTA powrotu do grafu;
- stan "laduje" prawego panelu zostal oddzielony od docelowego podsumowania;
- dodano brakujacy delegat `_get_current_preview_plate_count_state`, ktory blokowal finalizacje UI po autoanotacji;
- podczas autoanotacji powrot do grafu ma byc blokowany, a zamiast tego potrzebna jest jawna akcja zatrzymania procesu;
- modal autoanotacji zaczal lepiej odrozniac liczbe obrazow od liczby tablic;
- ograniczono niekontrolowane zaznaczanie listy przy otwartym modalu, gdy uzytkownik nie wlaczyl trybu recznego wyboru;
- przyspieszono duze runy przez cache i lzejsze odtwarzanie listy;
- zoptymalizowano przypadek duzego runu z prawie kompletnym XML, aby nie skanowac bez potrzeby tysiacy obrazow przy szukaniu kilku brakow;
- logi NEON pokazaly zejscie z wejsc rzedu kilkudziesieciu sekund do kilku sekund dla samego otwarcia zakladki, chociaz pelne odtworzenie tysięcy anotacji nadal wymaga dalszej pracy.

### 6. Z2 canvas, fullscreen i superkorekta

W obrebie edytora tablic w Z2 poprawiano glownie responsywnosc:

- ograniczono hit-testy kursora przy aktywnej korekcie narożnikow;
- usunieto dodatkowy redraw przy przejeciu narożnika do dragu;
- zmniejszono koszt historii undo podczas ciaglej serii korekt narożnikow;
- odchudzono wyjscie z fullscreen:
  - nie wykonujemy wielu kolejnych `fit_to_view` podczas stabilizacji rozmiaru,
  - overlay, dock i bramka nie sa odswiezane trzykrotnie pod rzad,
  - toolbar i status edytora odswiezaja sie asynchronicznie,
  - prawy panel nie jest przywracany podwojnie.

Diagnoza architektoniczna:

- obecne fullscreen/non-fullscreen nadal przepina widgety i PanedWindow;
- to jest stabilizowane punktowo, ale docelowo lepszy bylby model warstwowy opisany w backlogu.

### 7. Z3/PZ2: rozbicie, pipeline i metadane modeli

Z3 zostalo mocno rozbite na wyspecjalizowane moduly:

- `z3_detection_runtime.py`,
- `z3_detection_pipeline_ui.py`,
- `z3_detection_controls_ui.py`,
- `z3_detection_model_ui.py`,
- `z3_detection_guard_dialog.py`,
- `z3_preview_ui.py`,
- `z3_preview_badges.py`,
- `z3_preview_events.py`,
- `z3_preview_overlay_runtime.py`,
- `z3_preview_typing_runtime.py`,
- `z3_plate_layout_runtime.py`,
- `z3_preview_compass_ui.py`,
- `z3_preview_status_ui.py`,
- `z3_preview_records.py`,
- `z3_preview_metadata_runtime.py`,
- `z3_navigation_runtime.py`,
- `z3_export_summary.py`.

Zmiany semantyczne i stabilizacyjne:

- kontynuowano rozdzielanie jezyka bramek grafu od dawnego jezyka etapow;
- porzadkowano rzadowosc tablic, belke podzialu i status 1R/2R/AUTO;
- wykryto, ze filtr 1R/2R/2R? moze tworzyc wrazenie znikania anotacji;
- przyjeto kierunek, ze status rzędowości ma wynikac z danych i pracy uzytkownika, a nie byc sztucznym przelacznikiem;
- rozpoczęto porzadkowanie pipeline OCR/YOLO, w tym rozdzielenie informacji o YB/YS;
- dodano kierunek podgladu metadanych modelu YOLO przy wyborze modelu w dialogach pipeline, tak aby `best.pt` nie bylo jedyna informacja widoczna dla uzytkownika.

### 8. Z4, dataset i augmentacja

Z4 zostalo rozbite na osobne moduly przygotowania datasetu, walidacji, treningu, historii i augmentacji:

- `z4_dataset_builder.py`,
- `z4_dataset_sources.py`,
- `z4_dataset_validation.py`,
- `z4_dataset_panels.py`,
- `z4_dataset_preview.py`,
- `z4_augmentation_modal.py`,
- `z4_training_runtime.py`,
- `z4_training_progress.py`,
- `z4_training_metrics.py`,
- `z4_train_tab_builder.py`,
- `z4_train_progress_bar.py`,
- `z4_history_runtime.py`,
- `z4_model_export.py`,
- `z4_device_runtime.py`.

Ustalenia i zmiany:

- augmentacja ma byc osobnym modalem, a nie stalym ciezkim blokiem PZ1;
- syntetyczne zwiekszanie zbioru ma powiekszac dataset zrodlowy o dodatkowe obrazy, zachowujac nazwy i semantyke wariantow;
- obrazy augmentowane nie moga nadpisywac istniejacych plikow;
- parametry ustawione przez uzytkownika stanowia baze, a generator powinien tworzyc rozrzut wokol tej bazy;
- efekty robocze obejmuja m.in. blot, deszcz, noc, reflektory, relief, zacienienie i polysk mokrego blota;
- dodano modul `training/dataset_augmentation.py`;
- dodano metadane modeli YOLO jako lekkie pliki `.metadata.json`, aby UI moglo pokazac informacje bez ciezkiego czytania modelu `.pt`.

### 9. Autoanotacja i annotatory

Porzadkowano rowniez warstwe annotatorow:

- dodano `annotators/runtime_factory.py`;
- zmieniano `combined_annotator.py`, `plate_annotator.py`, `vehicle_annotator.py` i `base.py`;
- kierunek: tworzenie annotatorow i wybor runtime ma byc centralizowany, a nie rozrzucony po UI;
- wrocil temat deduplikacji nakladajacych sie ramek tablic po asyscie pojazdow, bo autoanotacja potrafila oznaczac te sama rejestracje podwojnie.

### 10. Otwarte ryzyka po tej fazie

- Kod jest znacznie bardziej modularny, ale wiele modulow jest nowych i wymaga testow przejsciowych.
- Czesci starego UI zostaly juz usuniete, ale moga nadal istniec martwe galezie w Z2/Z3/Z4.
- Najwieksze ryzyka regresji sa obecnie w:
  - wejsciach z grafu do Z2/Z3/Z4,
  - autoanotacji i finalizacji runu,
  - odtwarzaniu duzych projektow po restarcie,
  - przejsciach fullscreen/non-fullscreen,
  - modalach wyboru zasobow i akcji.
- Stabilizacja powinna isc teraz pojedynczymi problemami, nie szerokimi refaktorami naraz.

## Rozdzielenie wezla treningu E4 - 2026-07-10

Decyzja: dawny pojedynczy wezel `E4` byl zbyt ogolny, bo mieszal dwa rozne cele:

- trening modelu tablic;
- trening modelu znakow.

Wprowadzono rozdzielenie semantyczne:

- `E4T` - trening modelu tablic;
- `E4Z` - trening modelu znakow.

Zakres zmiany:

- graf kampanii ma teraz osobne wezly `E4T` i `E4Z`;
- `T05` prowadzi do `E4T`;
- `T06` prowadzi do `E4Z`;
- `T07` pozostaje kompatybilnym zamknieciem iteracji, ale wizualnie wychodzi z `E4T` albo `E4Z`;
- historia projektu i slad sciezki rozroznia produkty `MT` i `MZ` po docelowym wezle treningu;
- sciezki iteracji maja `edge_sequence` zgodne z realnymi kluczami krawedzi grafu.

Uwaga kompatybilnosci:

- wewnetrzny status kampanii nadal uzywa fizycznego kroku `step4` / `E4`;
- `E4T` i `E4Z` sa semantycznymi wezlami grafu, mapowanymi na dawny krok techniczny `E4`;
- alias starej krawedzi `e4_to_e1` pozostaje tylko po to, aby nie zerwac starych wpisow historii i logiki T07.

Wniosek:

Rozdzielenie poprawia czytelnosc decyzji uzytkownika. Uzytkownik nie widzi juz abstrakcyjnego "treningu", tylko konkretnie wie, czy zamyka i trenuje model tablic, czy model znakow.

## Scalenie bramek T01/T02 - 2026-07-10

Decyzja: `T01` i `T02` dublowaly ta sama prace w `E2/Z2`, czyli przygotowanie anotacji tablic na obrazach. Roznica dotyczyla dopiero dalszego uzycia tego produktu.

Nowy model:

- aktywny graf pokazuje jedna bramke `T01` na przejsciu `E1 -> E2`;
- `T01` oznacza przygotowanie anotacji tablic dla obrazow dostepnych w zasobach;
- w pracy bramki `T01` uzytkownik wybiera, czy przygotowane `AT` maja zasilic model tablic, czy tor znakow;
- po `E2` decyzje sa jawne:
  - `T05` prowadzi do treningu modelu tablic;
  - `T04` prowadzi do pracy nad znakami;
- `T03` pozostaje skrotem dla sytuacji, gdy projekt ma juz istniejace zrodlo tablic i mozna pominac ponowne oznaczanie tablic w `Z2`.

Kompatybilnosc:

- stare klucze `e1_to_e2_plate_training` i `e1_to_e2_char_from_images` zostaly aliasami do nowego `e1_to_e2`;
- stara semantyka `T02` nie jest juz aktywna w UI, ale stare historie i zapisane sciezki projektu moga nadal byc odczytane;
- `plate_training` i `char_from_images` pozostaja sciezkami iteracji, ale maja wspolny pierwszy krok `e1_to_e2`.

Wniosek:

Graf jest czytelniejszy: na wejsciu `E1` uzytkownik wybiera miedzy praca na obrazach (`T01`) a istniejacym zrodlem tablic (`T03`), zamiast rozrozniac dwa technicznie podobne wejscia do `E2`.

## Headless sanity-check grafu kampanii - 2026-07-10

Dodano lekki test kontraktu grafu:

```powershell
python -m auto_annotation_tool.campaign_graph_sanity
```

Zakres testu:

- sprawdza, ze aktywny graf ma jedna bramke `T01` na `E1 -> E2` i nie ma aktywnego `T02`;
- sprawdza aliasy starych kluczy `e1_to_e2_plate_training` i `e1_to_e2_char_from_images`;
- sprawdza kompletne sciezki `plate_training`, `char_from_images`, `char_from_ready_plates`;
- symuluje trzy iteracje kazdej sciezki i wymaga powrotu do `E1`;
- sprawdza widocznosc akcji zalezne od iteracji, np. `open_z2_first` tylko w iteracji 1 i `open_z2_later` dopiero w kolejnych;
- sprawdza bazowa gotowosc bramek `T01`, `T03`, `T04`, `T05`, `T06`, `T07`.

Cel:

- przed testami GUI szybko wykrywac regresy kontraktu grafu;
- nie polegac wylacznie na recznym klikaniu bramek;
- zamknac warstwe maszyny stanu do takiego poziomu, zeby pozniejsze testy byly glownie stabilizacja UI, licznikow i copy.

## Backlog po stabilizacji - warstwowy model UI - 2026-06-12

Pomysl: po opanowaniu obecnych lagow rozwazyc przejscie na warstwowy model interfejsu, zamiast przepinania widgetow i przebudowywania ekranu przy kazdej zmianie trybu.

Nazwy techniczne kierunku:

- `layered UI`;
- `layer manager`;
- `scene graph`;
- `compositing`;
- `retained-mode UI`;
- `overlay stack`.

Proponowany podzial:

- warstwa bazowa: canvas z obrazem albo tablica;
- warstwa anotacji: ramki, boxy, belki, badge, etykiety;
- warstwa HUD: kompas, asysta, statusy, ikony fullscreen;
- warstwa paneli: lewy i prawy panel;
- warstwa modalna: blokada interakcji i okna decyzji;
- warstwa interakcji: aktywny tryb, hit-testy, drag, skroty klawiaturowe.

Sens:

- fullscreen/non-fullscreen bylby tylko ukryciem albo pokazaniem warstw, a nie przebudowa PanedWindow;
- canvas i anotacje moglyby zachowac stan bez kosztownego odtwarzania;
- HUD i panele boczne bylyby niezalezne;
- interakcje bylyby kontrolowane przez jeden layer manager, a nie przez wiele rozproszonych wyjatkow.

Decyzja:

- nie wdrazac tego teraz;
- zapisac jako kierunek docelowy;
- najpierw doprowadzic obecny system do stabilnosci, a dopiero potem ocenic, czy Z2 powinno dostac pierwszy `LayerController`.

## Eksport modeli do klienta mobilnego ALPR - 2026-08-19

Dodano i udokumentowano osobny tor eksportu wytrenowanych modeli do pakietu mobilnego `.alprmodel`.

Cel:

- przygotowac wytrenowane modele `MZ` i `MT` do uzycia w demonstracyjnym kliencie Android;
- nie wymagac od klienta mobilnego importu surowego `best.pt`;
- przekazac telefonowi kompletny kontrakt inferencji: model, manifest, warianty wykonawcze, progi dekodera, klasy, ksztalty tensorow i sumy kontrolne.

Ustalenia architektoniczne:

- klient mobilny ALPR istnieje jako osobny projekt Android i importuje pakiety `.alprmodel`;
- `.alprmodel` jest pakietem ZIP z `manifest.json` i katalogiem `variants/`;
- zaznaczenie kilku formatow w prawym panelu eksportu nie oznacza kilku roznych modeli logicznych;
- kilka zaznaczonych formatow oznacza kilka wariantow wykonawczych tego samego checkpointu `best.pt` w jednym pakiecie;
- przyklad: `LiteRT/TFLite FP32 + ONNX FP32` tworzy jeden pakiet z wariantem `variants/tflite/model.tflite` i `variants/onnx/model.onnx`;
- telefon moze potem wybrac najlepszy wariant dla urzadzenia, np. LiteRT/GPU jako wariant glowny, ONNX jako fallback albo wariant kontrolny;
- wariant `LiteRT/TFLite INT8` wymaga kalibracji przez reprezentatywny `data.yaml`;
- kalibracja INT8 nie jest treningiem, tylko pomiarem zakresow liczbowych aktywacji na przykladowych obrazach przed kwantyzacja;
- `NCNN` pozostaje wariantem opcjonalnym/eksperymentalnym i nie powinien byc jedynym formatem pakietu.

Rekomendacja praktyczna:

- minimum wdrozeniowe: `LiteRT/TFLite FP32 + ONNX FP32`;
- wariant badawczy: dodac `LiteRT/TFLite INT8` z dobra kalibracja i porownac jakosc/szybkosc z FP32;
- przyszly wariant eksperymentalny: rozwazyc `W8A16` dla LiteRT, jezeli klient Android i eksporter beda mialy potwierdzone wsparcie.

Rozszerzenie 2026-08-19:

- eksporter rozroznia teraz pojedynczy pakiet `alpr.model.v1` i kompletny pakiet `alpr.package.v1`;
- kompletny pakiet nie jest nowym formatem modelu, tylko kontenerem badawczo-wdrozeniowym dla pary `MT+MZ`;
- wewnatrz kompletnego pakietu znajduja sie dwa zwykle `.alprmodel`, kazdy ze swoim manifestem, wariantami runtime, progami i sumami kontrolnymi;
- manifest pakietu glownego opisuje pipeline: detekcja tablic, rektyfikacja, detekcja znakow i skladanie sekwencji;
- po stronie Androida zmniejsza to ryzyko pomylenia modelu tablic z modelem znakow i daje jednoznaczny import kompletnego systemu ALPR.

Zrodla prawdy w repozytorium:

- `alpr_python_exporter_handoff.md` - kontrakt Python -> Android;
- `docs/eksport_mobilny_kwantyzacja.md` - opis formatow, kwantyzacji, kalibracji i parametrow inferencji do pracy inzynierskiej;
- `docs/specyfikacja_agenta_aplikacji_mobilnej_alpr.md` - instrukcja dla agenta Android oraz uporzadkowana dokumentacja eksportu i testow mobilnych;
- `auto_annotation_tool/gui/z4_model_export.py` - modal eksportu mobilnego;
- `auto_annotation_tool/exporters/mobile_model_exporter.py` - budowa pakietu `.alprmodel`;
- `requirements-mobile-export.txt` - zaleznosci eksportu mobilnego.

### Stabilizacja zaleznosci i preflightu eksportu - 2026-08-19

Problem:

- podczas eksportu LiteRT/TFLite w logu pojawialo sie ostrzezenie `Invalid export format='litert', updating to format='tflite'`;
- Ultralytics probowal samodzielnie uruchamiac `AutoUpdate` brakujacych zaleznosci, np. `tf_keras`, `onnx_graphsurgeon`, `onnx2tf`, `onnxruntime-gpu`;
- eksport TFLite potrafil zakonczyc konwersje poprawnie, ale pakiet nadal upadal na inspekcji wariantu, bo `from tensorflow.lite import Interpreter` nie jest poprawnym importem w lokalnym TensorFlow `2.19`;
- stary przycisk instalacji mogl instalowac zbyt szeroki zestaw pakietow, niezaleznie od tego, jaki format eksportu wybral uzytkownik;
- blad eksportu mogl zostac przykryty wtornym bledem callbacku, jezeli zmienna `exc` byla odczytywana dopiero po wyjsciu z bloku `except`.

Decyzja:

- nazwa `LiteRT/TFLite` zostaje w UI jako nazwa wdrozeniowa zrozumiala dla Androida;
- do API Ultralytics przekazujemy jednak `format="tflite"`, bo to jest realna nazwa formatu eksportu obslugiwana przez lokalna wersje biblioteki;
- przed eksportem wykonujemy jawny preflight zaleznosci dla wybranych formatow, zamiast pozwalac Ultralytics na niekontrolowany `AutoUpdate`;
- podczas samego eksportu ustawiany jest kontrolowany kontekst `ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS=1`, zeby Ultralytics nie instalowal bibliotek w tle;
- preflight rozroznia zaleznosci bazowe, ONNX, LiteRT/TFLite i NCNN;
- preflight LiteRT/TFLite sprawdza nie tylko obecność TensorFlow, ale też dostępność interpretera TFLite potrzebnego do odczytu rzeczywistych tensorow eksportowanego pliku;
- inspekcja TFLite uzywa `tf.lite.Interpreter`, z fallbackiem do `tensorflow.lite.python.interpreter` oraz `tflite_runtime.interpreter`;
- instalator w modalu instaluje tylko brakujace zaleznosci aktualnego wyboru, a nie pelny `requirements-mobile-export.txt`;
- callbacki workerow eksportu przechowuja tekst bledu w osobnej zmiennej, zeby modal mogl pokazac prawdziwa przyczyne awarii.

Uzasadnienie:

- eksport mobilny jest czescia eksperymentu i musi byc powtarzalny;
- automatyczne, ukryte instalowanie pakietow przez biblioteke narzedziowa zmienia srodowisko badawcze poza kontrola aplikacji;
- jawny preflight daje uzytkownikowi liste brakow, kontekst, postep instalacji i mozliwosc ponownego sprawdzenia srodowiska;
- rozdzielenie zaleznosci wedlug formatu ogranicza ryzyko, ze wybor opcjonalnego runtime, np. `NCNN`, uszkodzi dzialajacy eksport `TFLite` albo `ONNX`;
- w pracy inzynierskiej mozna dzieki temu opisac eksporter jako deterministyczny etap przygotowania artefaktu, a nie jako czarna skrzynke, ktora w trakcie badania samoczynnie modyfikuje srodowisko.

Uzasadnienie importow zaleznosci:

- `ultralytics` jest potrzebne do wczytania checkpointu `best.pt`, inspekcji modelu i wywolania eksportu;
- `torch` jest potrzebny, bo checkpoint YOLO jest artefaktem PyTorch i bez poprawnego runtime nie da sie go wiarygodnie odczytac;
- `torchvision` jest sprawdzany razem z `torch`, poniewaz niespojnosc tych bibliotek potrafi ujawnic sie dopiero przy imporcie Ultralytics albo operacjach detekcyjnych;
- `onnx`, `onnxruntime` i `onnxslim` sa wymagane przy wariancie ONNX oraz przy inspekcji tensorow i uproszczeniu grafu;
- `tensorflow`, `tf_keras`, `onnx2tf`, `onnx_graphsurgeon`, `sng4onnx`, `ai-edge-litert`, `onnxslim`, `onnxruntime` i `protobuf` stanowia lancuch konwersji oraz walidacji wariantu LiteRT/TFLite;
- `tf.lite.Interpreter` albo `tflite_runtime.interpreter` jest potrzebny po eksporcie do odczytania realnego wejscia i wyjscia modelu `.tflite`;
- `jsonschema` waliduje manifest pakietu `.alprmodel`, zeby Android nie dostal niepelnego albo niespojnego kontraktu;
- `ncnn` i `pnnx` sa wymagane tylko dla opcjonalnego wariantu NCNN;
- `pytest` pozostaje zaleznoscia testowa dla walidacji eksportera, a nie wymogiem runtime aplikacji Android.

Stan po zmianie:

- lokalny preflight pokazuje komplet zaleznosci dla `LiteRT/TFLite` i `ONNX`;
- lokalny test interpretera TFLite zwraca `OK`, wiec wariant `.tflite` moze byc po eksporcie sprawdzony przed zbudowaniem manifestu;
- jedyne wykryte braki dotycza opcjonalnego wariantu `NCNN`: `ncnn` i `pnnx`;
- runtime `ultralytics/torch/torchvision` importuje sie poprawnie;
- sprawdzono `py_compile` oraz `git diff --check` dla zmienionych plikow eksportu.

## Siatka eksperymentow ALPR i pakietow mobilnych - 2026-08-19

Po przegladzie plikow TeX pracy dyplomowej doprecyzowano metodyke badan dla wyboru finalnego pakietu ALPR.

Najwazniejsze ustalenia:

- finalnym kandydatem do aplikacji Android nie jest pojedynczy model, tylko pakiet `MT+MZ` z manifestem i wariantami runtime;
- ranking pojedynczych modeli zostaje potrzebny, ale sluzy diagnostyce `MT` i `MZ`, a nie samodzielnemu wyborowi kompletnego systemu mobilnego;
- uczciwe porownanie wymaga wspolnego toru testowego, osobnego od treningu i osobnego od koncowego testu raportowanego w pracy;
- metryki desktopowe i mobilne musza byc laczone: `mAP`, `precision`, `recall`, `F1`, `CER`, dokladnosc calej tablicy, p50/p90/p95, RAM, rozmiar pakietu i stabilnosc runtime;
- aplikacja desktopowa jest laboratorium: tworzy datasety, trenuje, porownuje, eksportuje `.alprmodel` i scala raporty;
- aplikacja mobilna jest stanowiskiem pomiarowym: importuje pakiet, waliduje manifest, mierzy inferencje, runtime i wynik end-to-end na urzadzeniu.

Nowy dokument:

- `docs/siatka_eksperymentow_mobilnych_alpr.md` - metodyka porownywania modeli, pakietow `MT+MZ`, wariantow runtime, wykresow i odpowiedzialnosci ALPR/Android.
- `docs/podbudowa_literaturowa_metodyki_testow_alpr.md` - literaturowa podbudowa wiarygodnosci testow: podzial danych, metryki detekcji, ALPR end-to-end, testy mobilne, kwantyzacja i powtarzalnosc.

Pierwszy fundament kodowy:

- dodano `auto_annotation_tool/ranking/mobile_package_experiments.py`;
- dodano katalog roboczy `Workspace/7_rankings/mobile_packages`;
- modul opisuje kandydata `MT+MZ`, warianty runtime, raport z Androida, import raportu JSON i punktacje `quality/latency/memory/reliability`;
- obecny eksporter pojedynczego `.alprmodel` nie zostal zmieniony, zeby nie rozbic dzialajacego kontraktu modelu.

## Stabilizacja dragu okna eksportu mobilnego - 2026-08-19

Problem:

- modal eksportu mobilnego dalo sie przesuwac natywnym paskiem Windows, ale okno poruszalo sie z duzym opoznieniem;
- ruch wygladal jak "suniecie po sladzie kursora", czyli okno doganialo mysz dopiero po czasie;
- przy probach obejscia problemu pojawial sie efekt ghosta, znikanie/minimalizacja modala albo aktywowanie okien lezacych pod aplikacja, np. VS Code;
- problem byl szczegolnie widoczny w duzym, bogatym modalowym UI z tabela kandydatow, tabelami wymagan, parametrow, wykresami i dynamicznym zawijaniem tekstu.

Pierwsze hipotezy:

- natywny pasek Windows sam w sobie mogl byc zrodlem laga;
- Tkinter mogl zbyt czesto odswiezac tabele i wrapy przy kazdym zdarzeniu `<Configure>`;
- problem mogl wynikac z liczby widgetow w modalu;
- preflight eksportu albo rysowanie wykresow mogly blokowac petle zdarzen;
- opakowanie okna we wlasny pasek moglo ominac problem natywnego dragu.

Proby rozwiazania:

- dodano wlasny mechanizm przesuwania okna oraz imitacje paska natywnego;
- sprawdzono wariant bez natywnego paska;
- dodano opoznienia i debouncing dla odswiezania tabel, wykresow, scrollregionow i wrapow;
- ograniczono przebudowe tabel po wyborze kandydata;
- zmniejszono koszt ustawiania wierszy przez fingerprint danych i pomijanie przebudowy, jezeli wiersze sie nie zmienily;
- przeniesiono ciezsze odswiezanie wymagan/preflight do opoznionych kolejek;
- dodano pomiary wydajnosci zamiast dalszego zgadywania.

Co testowalismy:

- zwykle przesuwanie natywnym paskiem Windows;
- przesuwanie przez wlasny pasek/uchwyt;
- przesuwanie po wyborze kandydata i po odswiezeniu wymagan;
- zachowanie modala po minimalizacji, maksymalizacji, restore i zamknieciu;
- liczbe zdarzen podczas ruchu okna;
- przerwy w petli zdarzen Tkintera;
- koszt przebudowy tabel i odswiezania wrapow;
- zachowanie przy wielu zdarzeniach `<Configure>` pochodzacych od dzieci modala.

Dodane logowanie diagnostyczne:

- `AAT_MOBILE_EXPORT_PERF=1` wlacza pomiary modala eksportu mobilnego;
- `[MOBILE EXPORT PERF]` zbiera m.in. `table_set_rows`, `requirements_refresh`, `chart_redraw`, `label_wrap_apply`, `window_configure`, `native_move_stream`, `event_loop_gap`;
- `[MOBILE EXPORT STALL]` pokazuje dluzsze zastoje petli zdarzen razem ze stackiem watku glownego;
- `widget_tree` pozwala sprawdzic przyblizona liczbe widgetow w modalu.

Wyniki pomiarow:

- pierwotnie `table_set_rows` potrafilo kosztowac ok. 200-330 ms przy przebudowie kilkudziesieciu komorek;
- po optymalizacji ta sama operacja spadla do kilku-kilkunastu milisekund, a przy braku zmian danych byla pomijana;
- `requirements_refresh` spadl z ok. 80-110 ms do kilku milisekund;
- `native_move_stream` potwierdzil, ze podczas normalnego dragu generowana jest duza liczba zmian pozycji okna;
- `event_loop_gap` pokazal, ze odczuwalny lag nie zawsze pochodzil z jednego ciezkiego miejsca, lecz z kumulacji wielu malych odswiezen;
- stack z `[MOBILE EXPORT STALL]` przy zamykaniu pokazywal tez osobny koszt `gc.collect()` i `torch.cuda.synchronize()`, ale to byl problem zamykania aplikacji, nie zasadnicza przyczyna laga dragu.

Co finalnie bylo zle:

- bledne bylo zalozenie, ze winny jest sam natywny pasek Windows;
- glownym problemem byla nasza reakcja na zdarzenia okna: przesuniecie okna bylo traktowane podobnie jak zmiana rozmiaru;
- kazdy ruch modala mogl uruchamiac kolejki odswiezania wrapow, tabel, scrollregionow, wykresow albo preflightu;
- zdarzenia `<Configure>` z dzieci modala dodatkowo powodowaly szum i potegowaly liczbe niepotrzebnych reakcji;
- imitacja paska natywnego rozwiazywala tylko objaw, ale tworzyla gorszy UX: brak standardowych przyciskow okna, ghost/przesuwanie bez naturalnego zachowania i ryzyko aktywowania okien pod aplikacja.

Rozwiazanie docelowe:

- zostawic natywny pasek Windows;
- rozdzielic `position_changed` od `size_changed`;
- przy samym przesuwaniu okna nie przeliczac wrapow, scrollregionow, tabel, wykresow ani preflightu;
- ignorowac `<Configure>` dzieci modala tam, gdzie interesuje nas tylko rozmiar glownego kontenera;
- stosowac fingerprint danych w tabelach, aby nie przebudowywac identycznej zawartosci;
- kolejkowac redraw tylko wtedy, gdy realnie zmienila sie szerokosc/wysokosc kontenera;
- podczas ruchu okna wydluzac albo odkladac odswiezanie elementow niekrytycznych;
- traktowac Win32 move guard jako opcje diagnostyczna wlaczana flaga `AAT_MOBILE_EXPORT_WIN32_MOVE_GUARD=1`;
- domyslnie nie przechwytywac natywnego dragu okna, zeby nie ryzykowac ghosta, minimalizacji albo plynacego okna.
- domyslnie wlaczyc lekkie sledzenie ruchu okna, ktore nie przechwytuje natywnego paska, lecz pozwala odkladac redraw tabel, wykresow, wrapow i preflightu do momentu zakonczenia przesuwania.

Efekt i dalsze zalecenie:

- natywny pasek Windows zostaje kierunkiem docelowym, ale mechanizm nie moze ukrywac laga przez ghost albo wlasny pasek;
- stabilizacja dragu musi byc dalej pilnowana przy zmianach w tabelach i panelach konfiguracji, ale nie wymaga juz obchodzenia natywnego paska okna;
- wnioskiem dla pozostalych ciezkich modali jest zasada: nie wolno laczyc kazdego `<Configure>` z pelnym rerenderem UI;
- przy kolejnych modalach trzeba od poczatku mierzyc: koszt tabel, liczbe widgetow, przerwy petli zdarzen, liczbe zdarzen configure i osobno ruch okna oraz resize.

Domkniecie regresu 2026-08-21:

- po kolejnych zmianach eksportera zanikl splash budowania modala, bo zamiast lekkiego loadera pojawialo sie ukrywane/ujawniane okno glowne;
- radosny fakt diagnostyczny: lag dragu zostal namierzony i po poprawce okno eksportu mobilnego znowu przesuwa sie plynnie z natywnym paskiem Windows;
- przyczyna regresu nie lezala w samym wygladzie modala ani w liczbie widgetow, tylko w rozszczelnionym wykrywaniu stanu przesuwania okna;
- funkcje rysujace i odkladajace redraw byly juz przygotowane pod warunek `_mobile_export_window_is_moving()`, ale ten warunek zaczynal dzialac za pozno albo nie wlaczal sie domyslnie przy natywnym dragu;
- w efekcie Tk nadal wykonywal niepotrzebne aktualizacje tabel, wykresow, wrapow, scrollregionow i preflightu w czasie, gdy Windows przesuwal okno;
- przywrocono model docelowy: natywny pasek Windows, osobny splash przed skanowaniem kandydatow i domyslnie wlaczone lekkie sledzenie ruchu bez przechwytywania dragu;
- dodano lekki hook Win32 na `WM_ENTERSIZEMOVE` i `WM_EXITSIZEMOVE`, ktory tylko ustawia `native_move_state` i natychmiast informuje UI, ze okno jest przesuwane;
- hook nie zamraza dzieci okna, nie manipuluje `WM_SETREDRAW` i nie tworzy efektu ghosta;
- agresywny `AAT_MOBILE_EXPORT_WIN32_MOVE_GUARD` oraz eksperyment z alfa/DWM pozostaja opcjami diagnostycznymi, a nie domyslna sciezka pracy;
- dodatkowo zabezpieczono funkcje rysujace i callback preflightu, aby nie przebudowywaly tabel, wykresow, statusu ani podsumowan w trakcie dragu.

Wniosek po naprawie:

- jezeli lag okna eksportu wroci, najpierw sprawdzic `AAT_MOBILE_EXPORT_TRACK_WINDOW_MOVE`, `native_move_state` i hook Win32, a dopiero potem ruszac layout;
- w ciezkich oknach Tk/Ttk kluczowy jest nie tylko koszt pojedynczego widgetu, ale rytm zdarzen: redraw musi wiedziec, kiedy uzytkownik przesuwa okno, a kiedy faktycznie zmienia jego rozmiar.

## Plan rozwoju po wersji obronnej - 2026-08-19

Ten rozdzial zbiera tematy, ktore sa wazne dla dalszego rozwoju programu, ale nie powinny destabilizowac wersji przygotowywanej do pracy inzynierskiej. Wersja obronna ma dowiezc stabilny rdzen: kampanie, iteracje, kontrolowana prace na anotacjach, trening, ranking, eksport mobilny i dokumentacje metodyki. Rzeczy ponizej traktujemy jako kierunki rozwoju, a nie warunki konieczne do domkniecia pracy.

### 1. Warstwowy model UI dla ciezkich widokow

Cel:

- ograniczyc lagi i przebudowy widokow w `Z2`, `Z3/PZ2`, fullscreenie i duzych modalach;
- zastapic lokalne wyjatki jednym modelem warstw: obraz, anotacje, HUD, panele, modal, interakcje;
- sprawic, aby fullscreen byl ukryciem/pokazaniem warstw, a nie przebudowa ukladu.

Uzasadnienie:

- obecne problemy wydajnosciowe najczesciej wynikaja z pelnych rerenderow po drobnych akcjach;
- osobny `LayerController` pozwolilby pilnowac kolejnosci rysowania, aktywnego elementu, hit-testow, dragu i skrotow klawiaturowych;
- podobny wzorzec moze potem posluzyc grafowi kampanii, canvasom anotacji i overlayom AS.

### 2. Manager artefaktow projektu

Cel:

- dac uzytkownikowi jedno miejsce do przegladania i usuwania artefaktow: runow, datasetow, augmentacji, eksportow i raportow;
- pokazywac rozmiar na dysku, powiazania z iteracja, bramka, modelem i statusem zatwierdzenia;
- bezpiecznie usuwac tylko artefakty nieuzywane przez aktywny kontrakt projektu.

Uzasadnienie:

- projekt produkuje wiele plikow pomocniczych i wynikowych;
- bez managera trudno ocenic, co nadal jest potrzebne, a co tylko zajmuje miejsce;
- usuwanie musi znac zaleznosci, zeby nie zniszczyc powtarzalnosci eksperymentow.

### 3. Pelny import/eksport AZ miedzy instancjami

Cel:

- umozliwic przenoszenie anotacji znakow `AZ` pomiedzy instalacjami programu;
- eksportowac `AZ` razem z kontekstem `AT`, aby geometria cropow tablic byla weryfikowalna;
- nie dopuszczac ryzykownego importu samych znakow bez mozliwosci sprawdzenia zgodnosci z tablicami.

Uzasadnienie:

- same znaki bez skorelowanych ramek tablic moga pasowac pozornie, ale geometrycznie dotyczyc innego cropa;
- import zewnetrzny ma sens tylko wtedy, gdy system potrafi jasno pokazac, co pasuje, co wymaga kontroli, a co nalezy odrzucic;
- bezpieczna wersja powinna importowac material do kontroli, a nie od razu jako gotowy zasob projektu.

### 4. Mocniejszy model kontraktow T01/T02 i rollback decyzji iteracji

Cel:

- formalnie opisac moment, w ktorym wybor `T01` albo `T02` staje sie nieodwracalny w danej iteracji;
- zapewnic przewidywalny rollback, jesli uzytkownik porzuca jedna bramke przed zatwierdzonym przyrostem;
- konsekwentnie pokazywac, czy zasob pochodzi z biezacej iteracji, czy z poprzednich.

Uzasadnienie:

- `T01` i `T02` sa alternatywami startowymi, ale obie dotykaja zasobow tablic;
- po zatwierdzeniu przyrostu jedna sciezka powinna blokowac druga w tej samej iteracji;
- uzytkownik musi widziec, czy bramka jest gotowa dzieki obecnej pracy, czy dzieki dziedziczeniu z poprzednich iteracji.

### 5. Testy regresji przeplywow kampanii i trybu swobodnego

Cel:

- dodac zestaw scenariuszy kontrolnych dla przeplywow `T01/T02/T05/T06`, `Z2`, `Z3/PZ2`, `Z3/PZ3`, `Z4/PZ1`, `Z4/PZ2`;
- automatycznie sprawdzac, czy tryb kampanii nie przecieka do trybu swobodnego i odwrotnie;
- kontrolowac statusy bramek, zasobow, pracy przerwanej, zatwierdzen i powrotow do grafu.

Uzasadnienie:

- najgrozniejsze regresje pojawialy sie nie w pojedynczych funkcjach, tylko na styku stanow;
- potrzebujemy testow scenariuszowych, ktore symuluja realne decyzje uzytkownika;
- to naturalny krok, jesli aplikacja ma byc rozwijana po obronie jako stabilne narzedzie.

### 6. Rozbudowana metodyka porownywania pakietow mobilnych

Cel:

- porownywac nie tylko pojedyncze modele `MT` i `MZ`, ale kompletne pakiety `MT+MZ`;
- laczyc wyniki desktopowe z raportami z aplikacji Android;
- generowac wykresy i raporty gotowe do wykorzystania w pracy i dalszych eksperymentach.

Uzasadnienie:

- model znakow sam nie daje kompletnego ALPR na telefonie;
- finalnym kandydatem wdrozeniowym jest caly pipeline: detekcja tablic, rektyfikacja, detekcja/rozpoznanie znakow, dekoder i runtime mobilny;
- ranking pakietow musi uwzgledniac jakosc, opoznienie, pamiec, rozmiar i stabilnosc dzialania na urzadzeniu.

### 7. Zaawansowana augmentacja fizyczna jako osobny modul badawczy

Cel:

- odseparowac eksperymentalne efekty fizyczne od stabilnego toru generowania datasetu;
- rozwazyc osobny renderer GPU/shader dla zjawisk takich jak mokry film, krople, odblaski, cienie wypuklych znakow i oswietlenie reflektorami;
- zachowac powtarzalnosc przez presety, ziarno losowosci i raport parametrow.

Uzasadnienie:

- prosta augmentacja 2D jest wystarczajaca do wersji obronnej, jezeli jest stabilna i powtarzalna;
- realistyczna optyka kropel, filmu wodnego i odbic wymaga modelu blizszego shaderom niz zwyklemu rysowaniu na bitmapie;
- to ciekawy kierunek badawczy, ale zbyt ryzykowny, zeby byl warunkiem stabilizacji glownego workflow.

### 8. Globalny standard modalow, splashy i feedbacku dlugich operacji

Cel:

- ujednolicic wyglad i zachowanie wszystkich splashy, modalow i paskow postepu;
- rozdzielic realny postep od komunikatu "czekam na dluga operacje";
- zapewnic, ze okno nie pokazuje bialych, niedoladowanych lub postrzepionych stanow posrednich.

Uzasadnienie:

- uzytkownik musi wiedziec, czy program pracuje, czeka, laduje dane czy zakonczyl zadanie;
- pasek 100% nie moze wisiec, jesli UI nadal sie buduje;
- standard modalowy zmniejszy ryzyko kolejnych regresji UX.

### 9. Profilowanie i budzet wydajnosciowy dla akcji interaktywnych

Cel:

- zdefiniowac maksymalne czasy reakcji dla akcji takich jak select boxa, drag narożnika, `q/e`, zatwierdzenie `[OK]`, sortowanie listy, otwarcie modala;
- logowac nie tylko duze operacje, ale tez odczuwalna zwloke miedzy intencja uzytkownika a widoczna reakcja UI;
- stosowac pomiary przed kazda wieksza optymalizacja.

Uzasadnienie:

- wielokrotnie okazalo sie, ze zgadywanie przyczyny laga prowadzi do regresji;
- pomiary typu `event_loop_gap`, koszt tabel, liczba widgetow i koszt synchronizacji pomagaja szybko wskazac prawdziwe zrodlo problemu;
- taki budzet wydajnosciowy jest tez dobrym materialem do opisu inzynierskiego dojrzalosci projektu.

### 10. Dokumentacja uzytkowa i onboarding

Cel:

- rozbudowac `Z5`, AS i dokumenty `docs/` tak, aby nowy uzytkownik rozumial podstawowe pojecia bez znajomosci historii projektu;
- opisac kontrakty `O/AT/AZ`, role `MT/MZ`, bramki `T01-T06`, iteracje, statusy i eksport mobilny;
- unikac opisow historycznych typu "kiedys bylo inaczej"; dokumentacja ma opisywac aktualny model pracy.

Uzasadnienie:

- aplikacja ma duzo pojec i bez jasnej dokumentacji moze sprawiac wrazenie bardziej skomplikowanej niz jest;
- AS powinien tlumaczyc aktualny ekran, a nie tylko wyswietlac ogolne definicje;
- dobra dokumentacja obniza koszt dalszej stabilizacji i pomaga w obronie pracy.

### 11. Stabilizacja dekodera wyjścia YOLO pose w eksporcie mobilnym

Problem:

- eksport `LiteRT/TFLite` modelu tablic `MT` zakonczyl sie sukcesem, ale walidator pakietu odrzucil realny ksztalt wyjscia `[1, 300, 14]`;
- przyczyna bylo stare zalozenie, ze kazdy keypoint modelu `pose` ma trzy skladowe `(x, y, confidence)`;
- wytrenowany model zwracal cztery narozniki jako `kpt_shape=[4,2]`, czyli same wspolrzedne `(x, y)`.

Zmiana:

- inspektor wariantow ONNX/TFLite czyta i przenosi `keypoint_dimensions` do manifestu;
- walidator rozpoznaje oba poprawne warianty `pose`: `keypoint_dimensions=2` oraz `keypoint_dimensions=3`;
- dla modelu z jedna klasa i czterema naroznikami ksztalt `[1, 300, 14]` jest traktowany jako poprawny uklad `anchors_first` z `objectness`.

Uzasadnienie:

- manifest ma opisywac rzeczywisty model po eksporcie, a nie domyslna interpretacje eksportera;
- Android musi czytac `output.keypoint_dimensions`, zeby poprawnie zdekodowac `MT`;
- ta poprawka domyka zgodnosc kontraktu Python -> Android bez zmiany samych wag modelu.

### 12. Obsługa wyjścia end-to-end YOLO26 w eksporcie mobilnym

Problem:

- eksport `LiteRT/TFLite` modelu znakow `MZ` zakonczyl konwersje powodzeniem, ale walidator odrzucil ksztalt `[1, 300, 6]`;
- model mial `36` klas, wiec stary walidator oczekiwal `40` albo `41` kanalow surowego YOLO;
- realny checkpoint `YOLO26` jest modelem end-to-end i zwraca gotowe detekcje w ukladzie `x1, y1, x2, y2, score, class_index`.

Zmiana:

- manifest rozroznia `output_format=raw_yolo` oraz `output_format=end2end_detections`;
- dla wariantu end-to-end zapisywane sa `decoder=ultralytics_detect_end2end_v1` albo `ultralytics_pose_end2end_v1`, `box_format=xyxy` i `nms_required=false`;
- inspektor TFLite dopuszcza ksztalt `[1, max_det, 6]` dla modeli `detect` oraz `[1, max_det, 6 + keypoint_dimensions * keypoint_count]` dla modeli `pose`.

Uzasadnienie:

- liczba klas nadal pozostaje w manifeście i etykietach, ale wyjscie end-to-end niesie tylko indeks wybranej klasy, a nie pelny wektor score klas;
- Android musi dekodowac taki wariant jako gotowa liste detekcji i nie wykonywac drugiego NMS;
- to pozwala eksportowac modele `YOLO26` bez sztucznego cofania ich do klasycznego ukladu raw.

### 13. Modernizacja kompletnej paczki mobilnej `MP+MT+MZ`

Problem:

- pierwotnie zakladalismy, ze model pojazdow `MP` moze byc dociagniety albo przygotowany po stronie klienta mobilnego;
- testy praktyczne pokazaly, ze pobieranie surowego YOLO i konwersja na telefonie sa zbyt ciezkie dla urzadzenia mobilnego;
- desktopowy eksporter wybieral dotad realnie tylko `MT` i `MZ`, mimo ze kontrakt Androida przewiduje tez pelna kaskade `MP+MT+MZ`.

Decyzja:

- aplikacja macierzysta ALPR ma przygotowywac gotowy model `MP` tak samo jak `MT` i `MZ`;
- kompletna paczka mobilna moze miec wariant `MT+MZ` albo `MP+MT+MZ`;
- Android importuje gotowe `.alprmodel`, wybiera wariant runtime i uruchamia inferencje, ale nie konwertuje surowego checkpointu YOLO na urzadzeniu.

Zmiana:

- `MobileAlprPackageRequest` i `MobileAlprPackageExporter` obsluguja opcjonalne `vehicle_request` / `vehicle_package`;
- manifest `alpr.package.v1` zapisuje `models.vehicle` i etap `vehicle_detection`, jezeli w paczce jest `MP`;
- centrum eksportu mobilnego pozwala zaznaczyc po jednym kandydacie `MP`, `MT`, `MZ` i pilnuje zgodnych zestawow: pojedynczy model, `MT+MZ` albo `MP+MT+MZ`;
- kandydaci `MP` sa wyszukiwani takze w katalogu bazowych modeli detect `Workspace/6_models/base/detect`, dzieki czemu standardowy model COCO moze zostac wyeksportowany na desktopie i dolaczony do paczki bez konwersji po stronie Androida;
- dokumenty handoff i metodyka badan zostaly doprecyzowane tak, aby odpowiedzialnosc za ciezka konwersje byla po stronie aplikacji desktopowej.

Uzasadnienie:

- taki podzial zmniejsza ryzyko awarii na telefonie i poprawia powtarzalnosc eksperymentu;
- kazdy model w paczce zachowuje wlasne `imgsz`, formaty, progi, kalibracje i metadane;
- finalny ranking mobilny moze porownywac duet `MT+MZ` z pelna kaskada `MP+MT+MZ`, zamiast mieszac odpowiedzialnosc aplikacji desktopowej i Androida.

### 14. Filtr klas pojazdow w eksporcie `MP`

Problem:

- standardowy detektor YOLO/COCO zwraca wiele klas, nie tylko pojazdy;
- samo `role=vehicle` nie wystarcza klientowi mobilnemu do rozstrzygniecia, ktore klasy maja wejsc do dalszej kaskady ALPR;
- bez jawnego filtra Android moglby uruchamiac detekcje tablic na obiektach niebedacych pojazdami albo inaczej interpretowac model niestandardowy.

Zmiana:

- modal wykonawczy eksportu pokazuje dla `MP` osobne pole klas pojazdow przepuszczanych do kaskady;
- request eksportu zapisuje blok `vehicle_detection` z `include_labels`, `include_class_indices`, fallbackiem COCO `[2,3,5,7]` i informacja, ze nastepnym etapem jest `plate_detection`;
- eksporter po odczytaniu faktycznych `labels` modelu przelicza indeksy klas wzgledem realnego manifestu modelu;
- manifest paczki `MP+MT+MZ` przenosi ten filtr takze do etapu `vehicle_detection`.

Uzasadnienie:

- `MP` jest etapem ROI, a nie wynikiem koncowym ALPR;
- filtr klas musi byc czescia kontraktu, bo Python i Android powinny identycznie rozumiec, ktore detekcje pojazdow uruchamiaja `MT`;
- przy modelach COCO dziala bezpieczny fallback indeksow, a przy modelach niestandardowych wazniejsze sa etykiety zapisane w `labels`.

### 15. Katalogowy import modelu `MP` YOLO detect w centrum eksportu

Problem:

- eksport pelnej paczki mobilnej moze wymagac modelu pojazdow `MP`, ktory nie powstal w biezacym projekcie;
- model z katalogu Ultralytics nie powinien byc mieszany z historia treningow, bo nie jest runem, nie ma datasetu projektu i nie ma lokalnych metryk treningowych;
- Android nie powinien pobierac ani konwertowac surowego checkpointu `.pt`, bo odpowiedzialnosc za ciezka konwersje lezy po stronie aplikacji desktopowej.

Zmiana:

- centrum eksportu mobilnego ma importer `+ model pojazdow`;
- importer pokazuje liste modeli Ultralytics `detect`, najpierw szuka pliku w katalogach programu, a dopiero gdy go nie znajdzie, pobiera checkpoint do `Workspace/6_models/base/detect/ultralytics` i zapisuje metadane sidecar;
- po walidacji technicznej model pojawia sie na liscie kandydatow jako `MP`;
- importowany model jest automatycznie zaznaczany do eksportu jako kandydat `MP`, ale ustawienia formatu, `imgsz`, progow, kwantyzacji i klas pojazdow pozostaja w oknie wykonawczym eksportu.

Uzasadnienie:

- zachowujemy jeden kontrakt eksportu `.alprmodel`: klient mobilny zawsze dostaje gotowy pakiet, a nie surowy model;
- zewnetrzny model ma jawne pochodzenie i nie udaje wyniku treningu projektu;
- walidacja roli zmniejsza ryzyko przypadkowego dolaczenia modelu `pose` jako `MP`;
- import Ultralytics w tym miejscu nie dotyczy `MT`, bo model tablic jest elementem toru projektu albo oddzielnego mechanizmu treningu/rankingu.

### 16. Kalibracja INT8 dla modelu pojazdow `MP`

Problem:

- `MP` moze byc gotowym modelem Ultralytics/COCO, a nie modelem trenowanym w naszym projekcie;
- taki model nie ma projektowego runu treningowego ani naturalnie powiazanego `data.yaml`;
- jednoczesnie statyczny `LiteRT/TFLite INT8` wymaga danych reprezentatywnych do kalibracji zakresow aktywacji;
- UI nie powinien sugerowac, ze dla `MP` konieczny jest "dataset treningowy modelu", bo to myli kalibracje z treningiem.

Ustalenie:

- `MP FP32` pozostaje najbezpieczniejszym wariantem domyslnym;
- `MP INT8 static` dopuszczamy tylko z jawna kalibracja, ale nie wymagamy, aby byl to dataset treningowy modelu;
- dla `MP` kalibracja powinna opierac sie na reprezentatywnych obrazach wejsciowych z naszego zastosowania, czyli na realnych kadrach/zbiorze `O`, na ktorych telefon bedzie uruchamial detekcje pojazdow;
- eksporter powinien proponowac wygenerowany kalibracyjny `data.yaml` dla `MP` z obrazow projektu albo katalogu wskazanego przez uzytkownika;
- fallback typu `coco8.yaml` traktujemy jako techniczny fallback biblioteki, nie jako pelnowartosciowy wariant badawczy do pracy inzynierskiej;
- dynamiczne `LiteRT w8a32` jest interesujacym kierunkiem, bo dokumentacja opisuje je jako dynamic INT8 bez danych kalibracyjnych, ale w naszej lokalnej wersji `ultralytics 8.4.19` eksporter nadal pracuje glownie na starszym `int8=True`, wiec wymaga to osobnego testu przed wlaczeniem do UI.

Uzasadnienie:

- kalibracja INT8 nie jest treningiem; sluzy do oszacowania zakresow aktywacji zmiennych tensorow podczas konwersji;
- dla modelu pojazdow reprezentatywnosc danych oznacza podobienstwo do klatek/ROI, ktore zobaczy telefon, a nie koniecznie zgodnosc z oryginalnym datasetem COCO;
- brak jawnej kalibracji moze dac technicznie dzialajacy plik, ale wynik badawczy bylby slaby metodologicznie, bo nie wiemy, czy spadek jakosci wynika z modelu, runtime, kwantyzacji czy zlej kalibracji;
- w paczce `MP+MT+MZ` kazdy model ma wlasna kalibracje, bo `MP` widzi pelna klatke/ROI pojazdu, `MT` widzi tablice/ROI, a `MZ` widzi wyprostowany crop tablicy.

Stan lokalnej biblioteki:

- sprawdzono `ultralytics 8.4.19`;
- lokalny kod Ultralytics przy `int8=True` i braku `data` ustawia domyslny dataset z `TASK2DATA`;
- dla zadania `detect` fallbackiem jest `coco8.yaml`;
- sam fallback jest wygodny technicznie, ale nie powinien byc naszym zalecanym trybem eksperymentalnym dla `MP` w ALPR.

Zrodla:

- Ultralytics, `Model Export with Ultralytics YOLO`: https://docs.ultralytics.com/modes/export;
- Ultralytics, `Export YOLO Models to LiteRT`: https://docs.ultralytics.com/integrations/litert;
- TensorFlow, `Post-training quantization`: https://www.tensorflow.org/model_optimization/guide/quantization/post_training;
- lokalna paczka `ultralytics 8.4.19`, pliki `ultralytics/engine/exporter.py` i `ultralytics/cfg/default.yaml`.

### 17. Swiadomy wybor formatow eksportu mobilnego

Problem:

- checkboxy formatow eksportu (`LiteRT/TFLite`, `ONNX`, `NCNN`, `INT8`) byly technicznie poprawne, ale zbyt malo mowily uzytkownikowi, po co wybiera dany wariant;
- eksport kilku formatow w jednej paczce moze byc bardzo sensowny badawczo, ale w finalnym wdrozeniu nie powinien byc przypadkowym mnozeniem plikow;
- uzytkownik musi rozumiec roznice miedzy formatem finalnym, fallbackiem, wariantem kontrolnym i eksperymentem wydajnosciowym.

Decyzja:

- kilka formatow w jednym `.alprmodel` traktujemy jako warianty wykonawcze tego samego checkpointu, a nie jako rozne modele logiczne;
- `LiteRT/TFLite FP32` jest domyslnym wariantem stabilnym dla Androida;
- `LiteRT/TFLite INT8` jest wariantem lekkim/wydajnosciowym, ale wymaga reprezentatywnej kalibracji i porownania z FP32;
- `ONNX FP32` jest wariantem kontrolnym/fallbackiem, szczegolnie przydatnym do diagnostyki i porownan runtime;
- `NCNN FP32` pozostaje wariantem eksperymentalnym, sensownym dopiero wtedy, gdy klient Android ma pelna obsluge runtime NCNN.

Zmiana:

- modal wykonawczy eksportu dostal krotki przewodnik przy wyborze formatow;
- kazdy format ma opisany cel: `Android stabilny`, `Android lekki`, `Kontrola`, `Eksperyment`;
- domyslnie zaznaczony jest tylko stabilny `LiteRT/TFLite FP32`; `ONNX`, `INT8` i `NCNN` uzytkownik wlacza swiadomie;
- dokument handoff doprecyzowuje, ze Android powinien wybierac runtime jawnie i raportowac, ktory wariant zostal uzyty;
- dokumentacja kwantyzacji/eksportu dostala rozszerzony opis konsekwencji wyboru kilku formatow.

Uzasadnienie:

- zgodnie z dokumentacja Ultralytics format eksportu jest zalezy od docelowego runtime i sprzetu, a nie jest cecha samego treningu;
- LiteRT/TFLite jest naturalnym kierunkiem dla Androida i inferencji on-device;
- ONNX Runtime Mobile moze byc dobra sciezka kontrolna, ale wymaga osobnego runtime w aplikacji;
- NCNN jest runtime mobilnym/embedded, lecz wymaga dedykowanej integracji po stronie klienta;
- powtarzalny eksperyment wymaga, aby roznice miedzy wariantami wynikaly z formatu/runtime/kwantyzacji, a nie z roznych checkpointow.

Zrodla:

- Ultralytics, `Model Export with Ultralytics YOLO`: https://docs.ultralytics.com/modes/export;
- Google AI Edge, `LiteRT for Android`: https://developers.google.cn/edge/litert/android;
- ONNX Runtime, `Deploy on mobile`: https://onnxruntime.ai/docs/tutorials/mobile/;
- Tencent NCNN: https://github.com/Tencent/ncnn.
