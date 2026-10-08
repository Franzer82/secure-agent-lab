# Rohdaten der Messungen

Jede Zeile einer `.jsonl`-Datei ist ein Versuch (JSON) mit allen Tool-Aufrufen,
den Antworten und der Bewertung. Alle Daten sind frei erfunden. Die Prüfsummen
stehen in `SHA256SUMS` (Prüfen mit `shasum -a 256 -c SHA256SUMS`).

- `trials_v1.jsonl`: Version 1 (Baseline, Nachträge, K4 und K5)
- `trials_v2.jsonl`: Version 2 (Vollauf), einschließlich eines aussortierten
  Versuchs mit technischem Fehler (Status `fehler`)

Das verwendete Modell steht in jedem Versuch (Feld `model`).
