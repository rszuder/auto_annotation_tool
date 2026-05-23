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

- prog startowy `10 obrazow` dla scenariusza, w ktorym nie ma jeszcze gotowych tablic;
- prog `10 gotowych tablic` dla scenariusza przejscia na podstawie materialu z poprzednich iteracji albo importu;
- ostrzegawczy modal przy wyborze toru znakow, gdy E1 widzi tylko potencjal obrazowy, ale nie widzi jeszcze materialu tablicowego;
- blokade automatycznego przeskoku z E1 do E3, jesli projekt ma tylko obrazy, a nie ma realnych gotowych tablic;
- karte toru znakow w E1 opisujaca aktualny stan preflightu prostym jezykiem.

Drugi krok stabilizacji ujednolica znaczenie `ready` dla toru znakow:

- stare kryterium `2 obrazy + dowolna liczba tablic` zostalo zastapione progiem `10 tablic`;
- `needs_more_tables` oznacza teraz realnie: sa jakies tablice, ale brakuje do minimum wejscia w prace nad znakami;
- badge i fallback E2 nie powinny juz otwierac E3 tylko dlatego, ze projekt ma pojedyncze zatwierdzone tablice.

Trzeci krok stabilizacji dodaje modal awaryjny dla `E2` w torze znakow:

- jezeli `E2/Z2` ma mniej niz `10` tablic, program nie przechodzi cicho do `E3`;
- uzytkownik dostaje licznik: obrazy z tablicami, gotowe tablice, minimum i brakujace tablice;
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
