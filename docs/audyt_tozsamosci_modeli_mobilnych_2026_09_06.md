# Spójność kandydatów i manifestów eksportu mobilnego

W kopii programu z Windows 11 odtworzono 7 kandydatów i 4 słupki histogramu.
Lista zawierała 5 różnych plików wag według SHA-256: dwa wytrenowane modele
MT, dwa bazowe modele MT oraz bazowy model MP. Dwa dodatkowe wpisy były
kopiami wytrenowanych wag. Histogram uwzględniał cztery wpisy z metrykami,
w tym te kopie; nie stanowił licznika odrębnych modeli.

| Model | Epoka w profilu historii przed poprawką | Epoka w profilu kopii | Epoka zapisanego best.pt | Wykonane epoki |
|---|---:|---:|---:|---:|
| YOLO26n Pose, run 20260905_223437 | 149 | 150 | 135 | 150 |
| YOLO26s Pose, run 20260906_103421 | 144 | 150 | 139 | 150 |

Profil historii wybierał wiersz według najlepszego mAP50-95 ramki, niezależnie
od wyboru checkpointu przez trening POSE. Profil kopii mógł użyć
`current_epoch`. Pochodzenie treningowe odczytywało jeszcze inne źródło.
Ponadto deduplikacja rozróżniała ścieżki `best.pt` i gotowej kopii modelu.

## Poprawka

- Tożsamość kopii wynika z SHA-256 zawartości. Historia jest preferowanym
  źródłem danych treningowych; kopia uzupełnia metadane modelu i lokalizacje.
- Różne checkpointy tego samego wariantu YOLO pozostają odrębnymi kandydatami.
  Odrębne zapisane etapy treningu nie tracą swojego rodowodu nawet przy
  identycznych wagach.
- Powiązanie gotowego pliku z historią wymaga zgodnych wag. Sama data/nazwa
  pliku nie uprawnia do przypisania treningu innego modelu.
- Najlepsza epoka jest potwierdzana z checkpointu. Dla sfinalizowanych wag
  `epoch=-1` używane jest jednoznaczne dopasowanie `train_metrics` do
  `train_results`. Zamrożony snapshot jest fallbackiem; ostatnia epoka nie
  zastępuje najlepszej. Metryki profilu dotyczą wybranego checkpointu.
- Lista, profil, `training`, `metrics` i `candidate` manifestu korzystają
  z tych samych danych. Profil pokazuje rodzinę i projekt w obu ścieżkach.
- Sygnatury buforów obejmują historię, zagnieżdżone wagi i pliki metadanych.
  Otwarcie pliku z innej maszyny uwzględnia wagi przy lokalnej historii.
- Eksporter sprawdza zgodność deklarowanych SHA i najlepszych epok przed
  konwersją oraz podczas tworzenia końcowego manifestu. Sprzeczne metadane
  powodują błąd zamiast utworzenia niewiarygodnej paczki.
- Trening MZ z jawnym `training_target=char` nie znika z listy tylko dlatego,
  że nazwa checkpointu lub treningu nie zawiera słowa `char`.

## Weryfikacja

Pełny zestaw: 396 testów i 44 podprzypadki. Regresje obejmują MT i MZ,
kopie pod innymi nazwami, brakujące metadane, błędne epoki, odświeżenie
historii i plików, podmianę wag oraz zachowanie odrębnych etapów treningu.
Testy budują manifesty tą samą metodą, której używa eksporter produkcyjny.

Wykonano również rzeczywisty eksport obu dostępnych modeli MT do ONNX FP32
w rozdzielczości 512. Po ponownym otwarciu utworzonych `.alprmodel`
sprawdzono zgodność wszystkich sekcji manifestów i źródłowych SHA-256:

- YOLO26n: `982daa589e67b5db801444fb6c525c8a052a55a9c1890a971ee2ab026b3a11c9`, epoka 135.
- YOLO26s: `44a0545ee042913bf110b294d081197709fcdc8be62b9f8a6807d252fc4ea0bf`, epoka 139.

Nie trenowano ponownie modeli użytkownika. Pliki wag i historia użytkownika
nie były edytowane w celu usunięcia duplikatów. Po poprawce ta sama kopia
danych daje 5 kandydatów, z czego dwa mają metryki ukończonego treningu.
Nie wykonywano rzeczywistego eksportu modelu MZ użytkownika, ponieważ taki
trening nie był dostępny; MZ jest objęty regresjami wspólnej ścieżki eksportu.
