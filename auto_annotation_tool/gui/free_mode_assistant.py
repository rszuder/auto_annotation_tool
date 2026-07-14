from __future__ import annotations

from dataclasses import dataclass
import re
import tkinter as tk

from .web_slim_scrollbar import blend_hex_colors


FREE_MODE_ASSISTANT_GLOSSARY: dict[str, str] = {
    "akcje": "pole bramki grafu kampanii; otwiera operacje prowadz\u0105ce do kart roboczych, np. Z2, Z3 albo Z4.",
    "bramka": "interaktywny panel przy kraw\u0119dzi grafu kampanii; pokazuje status przej\u015bcia, zasoby, akcje i zatwierdzenie.",
    "elektroda": "prze\u0142\u0105cznik wyboru bramki na grafie; po jej w\u0142\u0105czeniu dana \u015bcie\u017cka staje si\u0119 aktywna.",
    "graf": "mapa przej\u015b\u0107 kampanii pokazuj\u0105ca etapy jako w\u0119z\u0142y oraz decyzje jako kraw\u0119dzie z bramkami.",
    "kraw\u0119d\u017a": "po\u0142\u0105czenie mi\u0119dzy etapami grafu kampanii; reprezentuje jedno mo\u017cliwe przej\u015bcie.",
    "w\u0119ze\u0142": "g\u0142\u00f3wny punkt grafu, np. etap E1, E2, E3, E4T albo E4Z.",
    "zasoby": "dane wymagane przez wybran\u0105 bramk\u0119, np. katalog zdj\u0119\u0107, model albo anotacje.",
    "zatwierd\u017a": "pole bramki zamykaj\u0105ce wybrane przej\u015bcie po spe\u0142nieniu jego warunk\u00f3w.",
    "anotacja": "opis obiektów na obrazie, np. położenie tablicy, znaku, boxu albo poligonu.",
    "artefakt": "plik lub katalog wytworzony przez krok aplikacji, np. XML, cropy, dataset albo model.",
    "autoanotacja": "automatyczne tworzenie wstępnych ramek przez model; użytkownik później sprawdza i poprawia wynik.",
    "box": "prostokątna ramka opisująca położenie obiektu na obrazie, np. tablicy albo znaku.",
    "batch": "liczba obrazów przetwarzanych jednocześnie podczas treningu; większy batch szybciej zużywa pamięć GPU.",
    "checkpoint": "zapisany plik modelu, zwykle .pt, od którego można zacząć inferencję, walidację albo dalszy trening.",
    "confidence": "próg pewności detekcji; niższy próg daje więcej propozycji, wyższy odrzuca słabsze trafienia.",
    "crop": "wycięty fragment obrazu, np. sama tablica wycięta z pełnego zdjęcia pojazdu.",
    "CVAT": "zewnętrzne narzędzie do ręcznego poprawiania anotacji obrazów.",
    "data.yaml": "plik konfiguracyjny YOLO wskazujący klasy oraz foldery train, val i test.",
    "dataset": "uporządkowany zestaw danych treningowych: obrazy oraz odpowiadające im etykiety/anotacje.",
    "epoka": "jedno pełne przejście treningu po danych treningowych.",
    "eksport": "zapisanie gotowych danych do formatu używanego dalej, np. XML, YOLO albo zestawu CVAT.",
    "fit": "dopasowanie ramek do obrazu lub obszaru pracy, aby wynik był spójny z podglądem.",
    "gold pack": "wybrany, zaufany zestaw przykładów, z którego buduje się lepszy dataset znaków.",
    "GPU": "karta graficzna używana do szybszej inferencji lub treningu modeli.",
    "inferencja": "uruchomienie gotowego modelu na danych, aby uzyskać predykcje, np. boxy albo odczyt znaków.",
    "iteracja": "jeden pełny cykl pracy projektu: przygotowanie danych, anotacja, ewentualnie znaki, dataset i trening.",
    "kampania": "projekt prowadzony etapami przez wizard, z pamięcią iteracji, modeli i zatwierdzonych artefaktów.",
    "katalog": "folder na dysku zawierający dane danego kroku, np. obrazy, run albo gotowy dataset.",
    "korekta": "ręczne sprawdzenie i poprawienie anotacji po automatycznym albo wcześniejszym etapie pracy.",
    "klasa": "nazwa typu obiektu, którego uczy się model, np. konkretnego znaku albo tablicy.",
    "modal": "okno dialogowe wymagające decyzji użytkownika przed kontynuacją danego działania.",
    "model": "plik wag lub konfiguracja sieci neuronowej używana do detekcji, OCR albo treningu.",
    "obraz": "pojedynczy plik graficzny używany jako wejście do anotacji, datasetu albo treningu.",
    "OCR": "rozpoznawanie znaków z obrazu, np. odczyt liter i cyfr z wyciętej tablicy.",
    "overlay": "nakładka na obszar roboczy pokazująca stan procesu, postęp albo krótkie sterowanie bez przechodzenia do innej karty.",
    "perfect": "status oznaczający, że przykład jest sprawdzony i nadaje się do datasetu.",
    "poligon": "wielopunktowy obrys obiektu; dokładniejszy niż zwykły prostokątny box.",
    "preview run": "roboczy zestaw podglądowy, zwykle używany do sprawdzenia cropów przed dalszym etapem.",
    "PT": "plik wag modelu PyTorch/YOLO, zwykle z rozszerzeniem .pt.",
    "ranking": "porównanie wyników modeli lub treningów, pomagające wybrać najlepszy wariant.",
    "review pack": "zestaw przykładów przygotowany do ręcznego sprawdzenia, często poza aplikacją.",
    "run": "katalog konkretnego przebiegu pracy, zawierający pliki i artefakty danego kroku.",
    "split": "podział datasetu na części: train do uczenia, val do kontroli jakości i test do końcowej oceny.",
    "tablica": "tablica rejestracyjna widoczna na zdjęciu lub wycięta jako crop do dalszej pracy.",
    "test": "część datasetu odkładana do końcowej oceny modelu po treningu.",
    "tor": "wybrana ścieżka pracy, np. tablice, znaki, anotacja ręczna albo autoanotacja.",
    "train": "część datasetu używana bezpośrednio do uczenia modelu.",
    "trening": "proces uczenia modelu na przygotowanym datasecie.",
    "val": "część walidacyjna datasetu, używana do sprawdzania jakości podczas treningu.",
    "walidacja": "sprawdzenie jakości modelu na danych, których nie używa bezpośrednio do uczenia.",
    "wariant": "konkretna wersja datasetu lub konfiguracji, którą można porównać z innymi.",
    "VRAM": "pamięć karty graficznej; jej brak zwykle wymaga mniejszego batcha albo niższej rozdzielczości.",
    "wizard": "prowadzenie projektowe w Z1, które pilnuje kolejności etapów kampanii.",
    "znak": "pojedynczy znak z tablicy, np. litera albo cyfra rozpoznawana w Z3.",
    "XML": "plik anotacji zawierający informacje o obiektach i ich położeniu na obrazach.",
    "YOLO": "rodzina modeli do detekcji obiektów; w aplikacji służy m.in. do tablic, znaków i datasetów YOLO.",
    "YOLO Detect": "tryb YOLO wykrywający prostokątne boxy obiektów.",
    "YOLO Pose": "tryb YOLO uczący punkty/kształt obiektu, np. narożniki albo poligony.",
    "Z1": "zakładka wizarda kampanii i kontroli etapów projektu.",
    "Z2": "zakładka pracy nad tablicami rejestracyjnymi.",
    "Z3": "zakładka pracy nad znakami wyciętymi z tablic.",
    "Z4": "zakładka przygotowania datasetu i treningu modeli.",
    "Z5": "zakładka instrukcji, dziennika architektury i opisów programu.",
    "PZ1": "pierwsza podzakładka bieżącego etapu; jej sens zależy od tego, czy jesteś w Z2, Z3 czy Z4.",
    "PZ2": "druga podzakładka bieżącego etapu; zwykle kolejny krok pracy po PZ1.",
    "PZ3": "trzecia podzakładka bieżącego etapu, najczęściej związana z eksportem albo pracą dodatkową.",
    "źródło": "dane wejściowe potrzebne do danego kroku, np. XML z pasującym katalogiem obrazów albo gotowy dataset.",
    "źródło bez splitu": "dataset YOLO zapisany jako katalog images/labels, jeszcze bez podziału train/val/test. PZ1 tworzy z niego wariant treningowy.",
    "źródło Z2": "zgodna para danych z Z2: XML anotacji tablic oraz katalog obrazów, z których ten XML powstał.",
}

FREE_MODE_ASSISTANT_GLOSSARY_ALIASES: dict[str, str] = {
    "akcja": "akcje",
    "akcji": "akcje",
    "bramki": "bramka",
    "bramek": "bramka",
    "elektrody": "elektroda",
    "grafu": "graf",
    "krawedz": "kraw\u0119d\u017a",
    "krawedzi": "kraw\u0119d\u017a",
    "kraw\u0119dzi": "kraw\u0119d\u017a",
    "mapa przejsc": "graf",
    "mapa przej\u015b\u0107": "graf",
    "wezel": "w\u0119ze\u0142",
    "wezly": "w\u0119ze\u0142",
    "w\u0119z\u0142y": "w\u0119ze\u0142",
    "zasob": "zasoby",
    "zasobow": "zasoby",
    "zasob\u00f3w": "zasoby",
    "zatwierdz": "zatwierd\u017a",
    "zatwierdzenie": "zatwierd\u017a",
    "adnotacje": "anotacja",
    "anotacje": "anotacja",
    "anotacji": "anotacja",
    "artefakty": "artefakt",
    "boxy": "box",
    "boxów": "box",
    "boxowanie": "box",
    "crop tablicy": "crop",
    "cropy": "crop",
    "cropów": "crop",
    "batch size": "batch",
    "checkpointy": "checkpoint",
    "checkpointów": "checkpoint",
    "datasetu": "dataset",
    "datasety": "dataset",
    "datasetów": "dataset",
    "detekcja": "YOLO Detect",
    "detekcji": "YOLO Detect",
    "epoki": "epoka",
    "etykieta": "anotacja",
    "etykiety": "anotacja",
    "folder": "katalog",
    "folderu": "katalog",
    "foldery": "katalog",
    "klasy": "klasa",
    "klas": "klasa",
    "karta graficzna": "GPU",
    "karty graficznej": "GPU",
    "model PT": "model",
    "modele": "model",
    "modeli": "model",
    "poligony": "poligon",
    "progi": "confidence",
    "próg": "confidence",
    "ramka": "box",
    "ramki": "box",
    "ramek": "box",
    "runu": "run",
    "runy": "run",
    "splity": "split",
    "splitu": "split",
    "tablica perfect": "perfect",
    "tablice": "tablica",
    "tablic": "tablica",
    "treningu": "trening",
    "walidacji": "walidacja",
    "walidować": "walidacja",
    "wariantu": "wariant",
    "warianty": "wariant",
    "yaml": "data.yaml",
    "yolo detect": "YOLO Detect",
    "yolo pose": "YOLO Pose",
    "yolo znaków": "YOLO",
    "zdjęcie": "obraz",
    "zdjęcia": "obraz",
    "zdjęć": "obraz",
    "znaki": "znak",
    "znaków": "znak",
    "źródła": "źródło",
    "źródło images labels": "źródło bez splitu",
    "źródło images/labels": "źródło bez splitu",
    "źródło niesplitowane": "źródło bez splitu",
    "źródłowy": "źródło",
    "źródłowych": "źródło",
}


def _normalize_glossary_key(value: str) -> str:
    raw = str(value or "").strip().strip(" .,:;()[]{}")
    if not raw:
        return ""
    raw = raw.split("=", 1)[0].strip().strip(" .,:;()[]{}")
    folded = raw.casefold()
    for key in FREE_MODE_ASSISTANT_GLOSSARY:
        if folded == key.casefold():
            return key
    alias = FREE_MODE_ASSISTANT_GLOSSARY_ALIASES.get(folded)
    if alias:
        return alias
    return raw


def _contains_keyword(text: str, keyword: str) -> bool:
    if not text or not keyword:
        return False
    pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def get_step3_free_mode_assistant_context(host) -> dict:
    try:
        selected_tab = str(host.main_nb.select())
    except Exception:
        selected_tab = ""

    if selected_tab == str(getattr(host, "tab_extract", "")):
        return {
            "location": "[Z3] Autoanotacja znaków tablic / [PZ1] Wyodrębnianie zaanotowanych tablic",
            "goal": "Ta podzakładka bierze źródło z Z2, czyli XML i zgodny katalog obrazów, a następnie wyodrębnia tablice do dalszej pracy nad znakami.",
            "workflow": (
                "Wskaż albo potwierdź źródło Z2: annotations.xml oraz zgodny folder obrazów.",
                "Jeśli program znajdzie pasujący folder obrazów, świadomie potwierdź podpięcie w modalu.",
                "Uruchom wyodrębnianie tablic, aby utworzyć preview run z cropami tablic.",
                "Po sukcesie przejdź do PZ2, gdzie będziesz analizować znaki na wyodrębnionych tablicach.",
            ),
            "glossary": (
                "crop = wycięty obraz samej tablicy",
                "preview run = roboczy zestaw cropów",
                "źródło Z2 = XML + zgodne obrazy",
            ),
            "caution": "XML i katalog obrazów muszą pochodzić z tego samego zestawu; inaczej cropy będą niespójne.",
        }
    if selected_tab == str(getattr(host, "tab_detect", "")):
        return {
            "location": "[Z3] Autoanotacja znaków tablic / [PZ2] Wykrywanie znaków i analiza",
            "goal": (
                "PZ2 jest pierwszym krokiem pracy T05: tutaj przygotowujesz anotacje znaków na wyodrębnionych tablicach. "
                "Poprawiasz ramki, wpisujesz znaki i doprowadzasz tablice do statusu perfect. "
                "Sam zbiór przygotowany w PZ2 nie otwiera jeszcze T05; po zbudowaniu sensownego materiału trzeba przejść do PZ3 i wyeksportować źródłowy dataset znaków."
            ),
            "workflow": (
                "W PZ2 popraw ramki znaków i doprowadź możliwie dużo tablic do statusu perfect.",
                "Szuflada PZ2 pokazuje lokalny stan pracy: ile jest tablic i znaków, poziom jakości zbioru oraz braki do kolejnego poziomu.",
                "Gdy zbiór jest sensowny, użyj przycisku „Krok 2: dataset PZ3”.",
                "W PZ3 utwórz źródłowy dataset znaków AZ. Dopiero ten eksport domyka warunek bramki T05.",
            ),
            "glossary": (
                "perfect = tablica gotowa do datasetu",
                "YOLO znaków = boxy znaków",
                "OCR = odczyt znaków z boxów",
                "1R = tablica jednorzędowa",
                "2R = tablica dwurzędowa",
                "2R? = program podejrzewa układ dwurzędowy, ale nie ma pewności",
                "2R* / 1R* = układ ręcznie wymuszony przez użytkownika",
                "1.2 przy boxie = rząd 1, znak 2 w kolejności czytania",
            ),
            "caution": "Nie myl poziomu jakości w PZ2 z otwarciem T06. PZ2 przygotowuje materiał, PZ3 tworzy artefakt datasetu.",
        }
    if selected_tab == str(getattr(host, "tab_dataset", "")):
        return {
            "location": "[Z3] Autoanotacja znaków tablic / [PZ3] Integracje i dataset (YOLO)",
            "goal": "Ta podzakładka domyka pracę nad znakami: zbiera sprawdzone tablice perfect, opcjonalne poprawki CVAT i eksportuje źródłowy dataset znaków do dalszej pracy w Z4.",
            "workflow": (
                "Sprawdź, że pracujesz na perfectach z aktywnego runu PZ2.",
                "Jeśli poprawki zewnętrzne nie są potrzebne, wybierz strategie i źródła gold packa.",
                "Jeśli potrzebujesz CVAT, wyeksportuj review pack, popraw boxy znaków w CVAT i zaimportuj XML z powrotem do PZ3.",
                "Wyeksportuj źródłowy dataset YOLO znaków i przeczytaj modal z wynikiem operacji.",
                "Przejdź do Z4/PZ1, aby utworzyć wariant treningowy i split; trening uruchamiasz dopiero w Z4/PZ2.",
            ),
            "glossary": (
                "gold pack = wybrane tablice perfect używane jako zaufane źródło datasetu znaków",
                "review pack = zestaw cropów tablic wysyłany do ręcznego sprawdzenia w CVAT",
                "Poprawki CVAT = ręczne korekty boxów znaków wracające z CVAT do PZ3 i włączane do datasetu",
            ),
            "caution": "CVAT w PZ3 używa cropów tablic i boxów znaków, nie boxów tablic na pełnych zdjęciach.",
        }
    return {
        "location": "[Z3] Autoanotacja znaków tablic",
        "goal": "Ta zakładka prowadzi od tablic przygotowanych w Z2 do cropów, korekty znaków i źródłowego datasetu znaków.",
        "workflow": (
            "PZ1 wyodrębnia tablice z obrazów i XML z Z2.",
            "PZ2 rozpoznaje i poprawia znaki na cropach tablic.",
            "PZ3 zbiera perfecty, opcjonalne poprawki CVAT i eksportuje źródłowy dataset znaków.",
            "Z4 przejmuje dopiero wariant treningowy, split i trening modelu.",
        ),
        "glossary": (
            "PZ1 = wyodrębnianie zaanotowanych tablic",
            "PZ2 = wykrywanie znaków i analiza",
            "PZ3 = integracje i dataset YOLO",
        ),
        "caution": "Wariant treningowy i split końcowo przygotujesz w Z4.",
    }


@dataclass(frozen=True)
class FreeModeAssistantContext:
    location: str = ""
    goal: str = ""
    workflow: tuple[str, ...] = ()
    glossary: tuple[str, ...] = ()
    caution: str = ""

    @classmethod
    def from_value(cls, value) -> "FreeModeAssistantContext":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            glossary = value.get("glossary", ())
            if isinstance(glossary, str):
                glossary = (glossary,)
            workflow = value.get("workflow", value.get("steps", ()))
            if isinstance(workflow, str):
                workflow = (workflow,)
            return cls(
                location=str(value.get("location", "") or ""),
                goal=str(value.get("goal", "") or ""),
                workflow=tuple(str(item or "") for item in workflow if str(item or "").strip()),
                glossary=tuple(str(item or "") for item in glossary if str(item or "").strip()),
                caution=str(value.get("caution", "") or ""),
            )
        return cls()

    def is_empty(self) -> bool:
        return not any((self.location, self.goal, self.workflow, self.glossary, self.caution))

    def render_body(self) -> str:
        return "\n".join(self.render_body_lines())

    def render_body_lines(self) -> tuple[str, ...]:
        lines = []
        if self.location:
            lines.append(f"Jesteś tutaj: {self.location}")
        if self.goal:
            lines.append(f"Co robisz: {self.goal}")
        if self.workflow:
            lines.append("Kolejność pracy:")
            for index, item in enumerate(self.workflow, start=1):
                lines.append(f"{index}. {item}")
        if self.caution:
            lines.append(f"Uważaj: {self.caution}")
        return tuple(lines)

    def render_glossary_lines(self) -> tuple[str, ...]:
        text_parts = [self.location, self.goal, self.caution, *self.workflow, *self.glossary]
        searchable_text = " ".join(str(part or "") for part in text_parts)
        explicit_defs: dict[str, str] = {}
        ordered_keys: list[str] = []

        def add_key(key: str, definition: str = "") -> None:
            normalized = _normalize_glossary_key(key)
            if not normalized:
                return
            if definition:
                explicit_defs[normalized] = definition
            if normalized not in ordered_keys:
                ordered_keys.append(normalized)

        for entry in self.glossary:
            entry_text = str(entry or "").strip()
            if not entry_text:
                continue
            if "=" in entry_text:
                key, definition = entry_text.split("=", 1)
                add_key(key, definition.strip())
            else:
                add_key(entry_text)

        for key in FREE_MODE_ASSISTANT_GLOSSARY:
            if _contains_keyword(searchable_text, key):
                add_key(key)

        for alias, key in FREE_MODE_ASSISTANT_GLOSSARY_ALIASES.items():
            if _contains_keyword(searchable_text, alias):
                add_key(key)

        rendered: list[str] = []
        for key in ordered_keys:
            definition = explicit_defs.get(key) or FREE_MODE_ASSISTANT_GLOSSARY.get(key, "")
            if definition:
                rendered.append(f"- {key}: {definition}")
        return tuple(rendered)


class FreeModeAssistantOverlay:
    """Mały, pasywny HUD kontekstu dla trybu swobodnego."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self._visible = False
        self._context = FreeModeAssistantContext()
        self._palette = {}
        self._manual_position: tuple[int, int] | None = None
        self._drag_anchor: tuple[int, int, int, int] | None = None
        self._last_notebook: tk.Misc | None = None
        self._last_info_panel: tk.Misc | None = None
        self._glossary_expanded = False

        self.frame = tk.Frame(
            root,
            bd=0,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        self.title_lbl = tk.Label(
            self.frame,
            text="Asystent kontekstu  |  GRAB",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            font=("Segoe UI", 9, "bold"),
            cursor="fleur",
        )
        self.title_lbl.pack(fill=tk.X)

        self.body_lbl = tk.Message(
            self.frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            font=("Segoe UI", 9),
            width=330,
        )
        self.body_lbl.pack(fill=tk.X, pady=(6, 0))

        self.glossary_toggle_btn = tk.Button(
            self.frame,
            text="Słownik pojęć (0) pokaż",
            command=self._toggle_glossary,
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
            cursor="hand2",
            padx=0,
            pady=3,
            font=("Segoe UI", 8, "bold"),
        )
        self.glossary_toggle_btn.pack(fill=tk.X, pady=(8, 0))

        self.glossary_lbl = tk.Message(
            self.frame,
            text="",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            font=("Segoe UI", 8),
            width=330,
        )
        self.glossary_lbl.pack(fill=tk.X, pady=(4, 0))
        self.glossary_lbl.pack_forget()

        for widget in (self.frame, self.title_lbl):
            try:
                widget.bind("<ButtonPress-1>", self._begin_drag, add="+")
                widget.bind("<B1-Motion>", self._drag, add="+")
                widget.bind("<ButtonRelease-1>", self._end_drag, add="+")
            except Exception:
                pass

    def refresh_theme(self, palette: dict | None = None) -> None:
        self._palette = dict(palette or self._palette or {})
        palette = self._palette
        panel = palette.get("panel", "#252526")
        panel_alt = palette.get("panel_alt", "#2d2d30")
        border = blend_hex_colors(
            palette.get("success", palette.get("accent", "#4ec9b0")),
            palette.get("panel_border", palette.get("border", "#3c3c3c")),
            0.55,
        )
        bg = blend_hex_colors(panel_alt, panel, 0.44)
        title_fg = palette.get("success", palette.get("accent", "#4ec9b0"))
        body_fg = palette.get("muted", palette.get("fg", "#f3f3f3"))

        for widget in (self.frame, self.title_lbl, self.body_lbl, self.glossary_toggle_btn, self.glossary_lbl):
            try:
                widget.configure(bg=bg)
            except Exception:
                pass
        try:
            self.frame.configure(highlightbackground=border, highlightcolor=border)
            self.title_lbl.configure(fg=title_fg)
            self.body_lbl.configure(fg=body_fg)
            self.glossary_toggle_btn.configure(
                fg=title_fg,
                activeforeground=title_fg,
                activebackground=bg,
            )
            self.glossary_lbl.configure(fg=body_fg)
        except Exception:
            pass

    def update_context(self, context, *, palette: dict | None = None) -> None:
        self._context = FreeModeAssistantContext.from_value(context)
        if palette is not None:
            self.refresh_theme(palette)
        try:
            self.body_lbl.configure(text=self._context.render_body())
        except Exception:
            pass
        self._refresh_glossary_display()

    def _toggle_glossary(self) -> None:
        self._glossary_expanded = not bool(self._glossary_expanded)
        self._refresh_glossary_display()
        self.place(
            notebook=self._last_notebook,
            info_panel=self._last_info_panel,
        )

    def _refresh_glossary_display(self) -> None:
        lines = self._context.render_glossary_lines()
        count = len(lines)
        if count <= 0:
            try:
                self.glossary_toggle_btn.pack_forget()
                self.glossary_lbl.pack_forget()
            except Exception:
                pass
            return

        try:
            if not str(self.glossary_toggle_btn.winfo_manager()):
                self.glossary_toggle_btn.pack(fill=tk.X, pady=(8, 0))
            action = "ukryj" if self._glossary_expanded else "pokaż"
            self.glossary_toggle_btn.configure(text=f"Słownik pojęć ({count}) {action}")
            self.glossary_lbl.configure(text="\n".join(lines))
            if self._glossary_expanded:
                if not str(self.glossary_lbl.winfo_manager()):
                    self.glossary_lbl.pack(fill=tk.X, pady=(4, 0))
            elif str(self.glossary_lbl.winfo_manager()):
                self.glossary_lbl.pack_forget()
        except Exception:
            pass

    def show(self) -> None:
        self._visible = True
        self.place()

    def hide(self) -> None:
        self._visible = False
        try:
            self.frame.place_forget()
        except Exception:
            pass

    def _begin_drag(self, event) -> str:
        try:
            self._drag_anchor = (
                int(event.x_root),
                int(event.y_root),
                int(self.frame.winfo_x()),
                int(self.frame.winfo_y()),
            )
            self.frame.configure(cursor="fleur")
        except Exception:
            self._drag_anchor = None
        return "break"

    def _drag(self, event) -> str:
        if self._drag_anchor is None:
            return "break"
        try:
            start_x, start_y, frame_x, frame_y = self._drag_anchor
            next_x = frame_x + int(event.x_root) - start_x
            next_y = frame_y + int(event.y_root) - start_y
            self._manual_position = (next_x, next_y)
            self.place(
                notebook=self._last_notebook,
                info_panel=self._last_info_panel,
            )
        except Exception:
            pass
        return "break"

    def _end_drag(self, _event) -> str:
        self._drag_anchor = None
        try:
            self.frame.configure(cursor="")
        except Exception:
            pass
        return "break"

    def _clamp_position(
        self,
        x: int,
        y: int,
        *,
        width: int,
        height: int,
        info_panel: tk.Misc | None = None,
    ) -> tuple[int, int]:
        try:
            root_w = max(640, int(self.root.winfo_width() or 0))
        except Exception:
            root_w = 1024
        try:
            root_h = max(420, int(self.root.winfo_height() or 0))
        except Exception:
            root_h = 768

        bottom_limit = root_h - 12
        if info_panel is not None:
            try:
                bottom_limit -= int(info_panel.winfo_height() or 0)
            except Exception:
                pass

        min_x = 12
        min_y = 56
        max_x = max(min_x, root_w - width - 12)
        max_y = max(min_y, bottom_limit - height)
        return (
            max(min_x, min(int(x), max_x)),
            max(min_y, min(int(y), max_y)),
        )

    def place(self, *, notebook: tk.Misc | None = None, info_panel: tk.Misc | None = None) -> None:
        if not self._visible or self._context.is_empty():
            self.hide()
            return
        if notebook is not None:
            self._last_notebook = notebook
        if info_panel is not None:
            self._last_info_panel = info_panel

        try:
            self.root.update_idletasks()
        except Exception:
            pass

        try:
            root_w = max(640, int(self.root.winfo_width() or 0))
        except Exception:
            root_w = 1024

        width = min(390, max(320, int(root_w * 0.30)))
        wrap = max(260, width - 26)
        try:
            self.body_lbl.configure(width=wrap)
            self.glossary_lbl.configure(width=wrap)
        except Exception:
            pass

        try:
            self.frame.update_idletasks()
            height = int(self.frame.winfo_reqheight())
        except Exception:
            height = 150

        if self._manual_position is not None:
            x, y = self._manual_position
        else:
            x = max(12, root_w - width - 18)
            y = 78
            if notebook is not None:
                try:
                    y = max(56, int(notebook.winfo_y()) + 34)
                except Exception:
                    y = 78

        x, y = self._clamp_position(x, y, width=width, height=height, info_panel=info_panel)
        if self._manual_position is not None:
            self._manual_position = (x, y)

        try:
            self.frame.place(x=x, y=y, width=width)
            self.frame.lift()
        except Exception:
            pass
