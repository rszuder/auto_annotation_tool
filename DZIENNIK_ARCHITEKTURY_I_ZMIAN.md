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
