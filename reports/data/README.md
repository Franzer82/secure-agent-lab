# Rohdaten der Messungen

Jede Zeile einer `.jsonl`-Datei ist ein Versuch (JSON) mit allen Tool-Aufrufen,
den Antworten und der Bewertung. Alle Daten sind frei erfunden. Die Prüfsummen
stehen in `SHA256SUMS` (Prüfen mit `shasum -a 256 -c SHA256SUMS`).

- `trials_v1.jsonl`: Version 1 (Baseline, Nachträge, K4 und K5)
- `trials_v2.jsonl`: Version 2 (Vollauf), einschließlich eines aussortierten
  Versuchs mit technischem Fehler (Status `fehler`)

Das verwendete Modell steht in jedem Versuch (Feld `model`).

## Nachtrag A8s

`trials_a8s_v1.jsonl`, `trials_a8s_v2n.jsonl` und `trials_a8s_v2.jsonl` enthalten nur
die Versuche des Nachtrags A8s (siehe `docs/a8s_plan.md`). Prüfsummen in
`SHA256SUMS_a8s`. Die Dateien `trials_v1.jsonl` und `trials_v2.jsonl` blieben davon
unberührt.
