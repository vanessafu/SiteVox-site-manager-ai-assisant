# SiteVox – Evaluation

Jede Pipeline-Stufe wird getrennt gemessen, dazu Ende-zu-Ende. Ausgelegt für **kleine, eigene Datensätze**:
Szenario-Cluster-Bootstrap statt Punktwerte, Kontrastpaare, Fehlerinjektion.

| Skript | Stufe | Kernmetriken |
|---|---|---|
| `eval_asr.py` | Whisper | WER/CER je Sprache × SNR × Akzent, **Fachbegriff-Recall**, **Zahlen-/Uhrzeit-Recall**, Sprach-ID, Halluzination auf reinem Lärm, Wort-Score-Kalibrierung (AUROC/ECE), RTF |
| `eval_extract.py` | Qwen3-4B + Regel-Engine | Ereignis-P/R/F1, Typ-Verwechslung, Slots, Sphäre, **verpasste vs. falsche Anzeige**, Mengen/Personal, Zitat-Verankerung, Konsistenz-Konfidenz (ECE/AURC), Cross-lingual-Konsistenz, Kontrastpaare |
| `eval_verify.py` | Faktenprüfung | Erkennungsrate je Fehlerart (Standard + schwere Fälle), Fehlalarme auf Originalen |

Ausgabe je Lauf: `items.jsonl` (pro Item, für Fehleranalyse), `summary.json`, `summary.md`.

## Daten

### Szenarien (`evaluation/data/scenarios.jsonl`)
Vorlage: `data/scenarios.example.jsonl` (Zeilen mit `//` werden ignoriert).

```jsonc
{"id": "S02-tr",                 // Variante (Sprache/Sprecher)
 "scenario_id": "S02",           // Bootstrap-Cluster: alle Varianten eines Szenarios
 "pair_id": "P01",               // optional: Kontrastpaar (gleiche Oberfläche, andere Entscheidung)
 "lang": "tr", "date": "2026-11-20", "time": "07:15", "source": "audio|note|email",
 "weather_exceptional": null,    // nur Witterung: Ergebnis der DWD-Schwellen
 "text": "<Gold-Transkript>",
 "text_asr": "<optional: ASR-Hypothese, für --text-field text_asr>",
 "gold": {
   "events": [{"type": "third_party_interference", "start_time": "07:00", "sphere": "AG",
               "document": "behinderungsanzeige", "attrs": {"predecessor_by_owner": true},
               "resources": ["Bagger|excavator|koparka|ekskavatör"]}],   // "|" = erlaubte Alternativen
   "progress": [{"activity": "Aushub BA1", "quantity": 190, "unit": "m³"}],
   "staffing": [{"crew": "Gesamt", "present": 14, "absent": null}]}}
```

Regeln für das Set:
- Jeder Ereignistyp × Sphäre mindestens 2×; **Szenarien ohne Ereignis** (reine Leistungsmeldung) nicht vergessen.
- **Kontrastpaare** gezielt bauen (Bagger defekt → AN/Bautagebuch vs. Bagger wartet auf AG-Vorunternehmer → AG/Behinderungsanzeige).
- Mehrsprachig: dasselbe `scenario_id` in de/en/tr/pl (+ Code-Switching), Übersetzungen von Muttersprachler:innen prüfen.

### ASR-Manifest (`data/asr_eval/manifest.jsonl`)
Kompatibel mit `scripts/data/audio/sythesize_noise_data.py`:
```jsonc
{"id": "S02_tr_spk2_snr5", "file": "…/S02_tr_spk2_snr5.wav", "text": "<Referenz, menschlich korrigiert>",
 "scenario_id": "S02", "lang": "tr", "speaker": "spk2", "accent": "tr-L1", "snr_db": 5, "noise": "bagger"}
```
Clips mit `"text": ""` (reiner Lärm/Stille) messen Halluzination. Die Referenz muss **menschlich** sein –
ASR-Fixtures sind nur Silber.

## Ausführen

```bash
# Verify: läuft sofort auf den Entwürfen in der DB (Demo: scripts/seed_demo.py)
python -m evaluation.eval_verify --out outputs/eval/verify

# Extraktion – Baseline (Demo-Modus = Schlüsselwort-Heuristik) vs. Qwen3-4B
SITEVOX_MODE=demo python -m evaluation.eval_extract --scenarios evaluation/data/scenarios.jsonl --out outputs/eval/extract_heuristic
SITEVOX_MODE=gpu  python -m evaluation.eval_extract --scenarios evaluation/data/scenarios.jsonl --out outputs/eval/extract_qwen3-4b
# Fehlerfortpflanzung ASR → Extraktion
SITEVOX_MODE=gpu  python -m evaluation.eval_extract --scenarios … --text-field text_asr --out outputs/eval/extract_asr

# ASR (live über Tunnel, oder --hyps mit vorhandenen Hypothesen)
SITEVOX_MODE=gpu SITEVOX_ASR_BACKEND=remote python -m evaluation.eval_asr --manifest data/asr_eval/manifest.jsonl --out outputs/eval/asr_large-v3
```

## Protokoll (wichtig bei wenig Daten)

1. **Dev/Test trennen nach `scenario_id`** (nicht nach Variante) und das Test-Set einfrieren. Prompts, Schwellen
   und Konfiguration nur auf Dev anpassen.
2. TTS-Audio nur für Dev; Test nur echte Sprecher:innen.
3. Immer KI berichten (Szenario-Bootstrap). Systemvergleiche gepaart: `metrics.mcnemar` (Entscheidung richtig ja/nein),
   gepaarter Bootstrap für WER.
4. Verpasste Anzeigen und falsche Anzeigen **getrennt** berichten – sie haben sehr unterschiedliche Kosten.
5. `items.jsonl` für die qualitative Fehleranalyse nutzen; bei n < 100 ist sie mindestens so aussagekräftig wie die Zahl.
6. `eval_verify.py`: die „schweren“ Fälle (Zahl/Name aus anderem Beleg, Verneinung) zeigen die Grenze des
   String-Abgleichs – Motivation für eine semantische Prüfung (NLI/LLM-Judge je Satz gegen zitierte Belege).

## Noch nicht automatisiert
- Entwurfsqualität (Qwen3-8B): Bewertung durch 2–3 Fachleute (Rubrik 1–5: Faktentreue, Verwendbarkeit, Ton,
  Änderungsaufwand; Krippendorff-α) und Edit-Distanz Entwurf → freigegebene Fassung.
- Vision: Attribut-Checkliste je Foto (Gerät in Betrieb/abgestellt, Personen arbeitend/wartend, Bauzustand),
  Objekt-Halluzination, Gesichts-Verpixelung-Recall.
- Ende-zu-Ende: 5–10 „Tage“ wie `data/demo/BV-RIEM`, Zeitmessung Bautagebuch mit/ohne System, SUS.
