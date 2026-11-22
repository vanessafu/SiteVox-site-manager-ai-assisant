# Mock data

All test data in SiteVox are **synthetic**. There is one fictional project, the residential building
"BV Riem, Baufeld 3" (client Wohnbau Riem GmbH & Co. KG, contractor Hofbau Rohbau GmbH, VOB/B contract
RI-2026-014). People, companies, addresses and e-mail addresses (`*.example`) are invented.

Three kinds of data exist:

| Data set | Purpose | Location |
|---|---|---|
| Project documents | Knowledge base for RAG, contract extraction, schedule | `data/demo/BV-RIEM/` |
| Gold scenarios | End-to-end evaluation of the full pipeline | `data/demo/scenario/*.json` → `data/raw/scenario_*/` |
| ASR benchmark sets | Isolated speech-recognition evaluation under noise | `data/asr_eval/noisy`, `data/asr_eval/noisy_cv` |

---

## 1. Project documents

`data/demo/BV-RIEM/` contains the documents a site manager would have:

| File | Content |
|---|---|
| `docs/Bauvertrag_RI-2026-014.pdf` (+ `.md`) | Construction contract: parties, authorised representative, contract deadlines, owner-supplied items |
| `docs/LV_Rohbau.md` | Bill of quantities (Leistungsverzeichnis) with item numbers, quantities and units |
| `docs/Planlieferliste.md` | Plan delivery list: which drawing is due when |
| `docs/Protokoll_BB07_2026-11-18.md` | Site meeting minutes with open items |
| `plan/Bauzeitenplan.xlsx` | Construction schedule (activities, durations, FS/SS links, milestones) |
| `history/leistung.csv` | Progress history before the scenario days |
| `inputs/2026-11-20/` | The demo day: voice memos, photos with EXIF, incoming e-mails (`.eml`) |

`scripts/make_demo_data.py` regenerates the derived files (schedule workbook, e-mails, placeholder media).

---

## 2. Gold scenarios

### 2.1 Design

Each scenario is one working day seen through the site manager's phone. The site manager is the only person
who enters data. A **capture** is 0–2 photos plus one or two short notes, typed or spoken, written in colloquial
site language.

```text
SCN-RIEM-0016  Mon 23.11.2026   photo day: obstructions, defects, late material
SCN-RIEM-0017  Tue 24.11.2026   axis C finished; building-services openings still open
SCN-RIEM-0018  Wed 25.11.2026   rebar inspection, site meeting no. 8, excavation finished; wall drawings late
SCN-RIEM-0019  Thu 26.11.2026   concrete pour A–B; concrete supply stalls; surface change ordered by the client
```

The four days form one continuous story: later days continue or close events of earlier days
(`continues`, `closes`), and the demo day 20.11.2026 is replayed first as history.

Every day exists in **four languages** (de, en, pl, tr). Gold annotations are identical across languages;
only the site manager's notes differ. Outgoing letters are always expected in German.

### 2.2 What a scenario file contains (schema `gold-scenario/0.5-photo-first-project-grounded`)

| Key | Content |
|---|---|
| `meta` | project, contract, date, report number, working hours |
| `persona` | the site manager entering the data |
| `registry` | all parties with `contracted_by` (decides recipient and risk sphere) |
| `plan` | activities of the day with LV item, quantity, planned and forecast finish, critical path |
| `weather_ground_truth` | temperatures, rain, gusts and the expected assessment |
| `captures[]` | the input stream with gold labels (see below) |
| `photo_triage_gold` | number of usable / unusable photos and the reason |
| `expected_report` | expected daily report: staffing, equipment hours, deliveries, output per activity, incidents, photos, expected and forbidden messages |
| `generation` | instructions for generating images, voice and text from the scenario |

One capture:

```json
{"id": "C03", "time": "11:40", "purpose": "progress",
 "audio": {"noise": "clean", "snr_db": null},
 "photos": [],
 "notes": [{"kind": "voice", "language": "en",
            "text": "Meeting's done. Wagner decided: instead of core drilling later we set 4 box-outs DN150 before pouring. With the others that's 10 pieces. Lechner sends the positions by 14:00. Pour stays tomorrow 07:00."}],
 "gold": {"report": ["6_vorkommnisse"],
          "event": {"id": "EVT-18-02", "kind": "follow_up", "continues": ["EVT-2026-11-20-004", "EVT-17-03"],
                    "type": "additional_work", "sphere": "AG", "document": null,
                    "reasoning": "DN150 falls under LV 03.050 'openings up to 20 x 20 cm'; 10 pcs ≤ 12 pcs → no extra cost",
                    "contrastive_pair": {"with": "EVT-2026-11-20-004",
                                         "differs_in": "core drilling afterwards (not in LV → extra cost) vs. box-out before pouring (in LV)"}},
          "must_not": ["Mehrkostenanzeige"],
          "source_refs": ["LV 03.050", "Protokoll BB07 TOP 5", "Bauvertrag §5"]}}
```

### 2.3 Annotation rules

- Every **event type × risk sphere** combination appears, including **routine captures without an event**
  ("excavator running, new hose holds") that must not raise an alarm (`near_miss`).
- **Contrastive pairs**: the same surface with a different decision, e.g. excavator broken (AN → diary only)
  vs. excavator waiting for the client's preceding contractor (AG → notice of obstruction).
- Gold decisions are grounded in the project documents: LV items, contract clauses, plan delivery list.
- Photos include deliberately **unusable** shots (blurred, irrelevant) that must not be attached as evidence.

### 2.4 Size

Per language, over the four days:

| Item | Count per language | Total (4 languages) |
|---|---|---|
| Scenario days | 4 | 16 day-runs |
| Gold events (disruptions) | 16 | 64 |
| Routine captures (must not become events) | 20 | 80 |
| Voice notes | 16 | 64 |
| Expected letters to the client | 6 | 24 |

---

## 3. From scenario to input stream

`scripts/data/scenario/make_scenario_inputs.py` turns a gold scenario into what the phone would send:

```text
data/raw/scenario_<ID>_<date>_<lang>/
  audio/rec_HHMM_Cxx.wav    voice notes (16 kHz mono)
  notes/note_HHMM_Cxx.txt   typed notes, verbatim
  photos/IMG_xxxxxx.jpg     photos under RANDOM names with EXIF capture time and GPS
  inputs.json               ordered captures: time, photos, notes – the only file the pipeline reads
  gold.json                 mapping inputs → gold captures + audio metadata – used only for scoring
```

File names and order do not reveal which event a photo belongs to. With `--photo-time shuffle` the EXIF times are
also permuted, so photos can only be matched by content and caption (harder variant).

### 3.1 Photos

Each photo is generated with an image model from the English scene description `scene_en` of the scenario
(for example *"Timber edge formwork with one board visibly out of line, folding rule laid across"*). Photos marked
`usable: false` are generated with the named defect (blurred, irrelevant subject). The input generator then
writes realistic EXIF metadata (capture time, GPS of the site) and renames the files randomly.

### 3.2 Voice notes

1. **Spoken form** (`scripts/data/audio/spoken.py`): times, dates, decimals and codes are written out as a site
   manager would say them, per language (`08:15` → "acht Uhr fünfzehn" / "eight fifteen" / "ósma piętnaście" /
   "sekiz on beş"; `BA1` → "B A eins"). The reference transcript stays in written form.
2. **Speech synthesis** with XTTS-v2 (`scripts/data/audio/tts_synthesize.py`). About 60 % of the notes use a voice
   cloned from a Common Voice speaker with a different first language (English, Polish or Turkish L1), the rest a
   built-in studio voice.
3. **Quality check**: every synthesized note is transcribed with Whisper medium; up to three attempts, otherwise
   the best attempt is kept and flagged.
4. **Phone close-talk mixing** (`scripts/data/audio/sythesize_noise_data.py`, level model `phone`): speech fixed at
   −18 dBFS active level, real construction noise (excavator, vibrator, jackhammer, wind, rain, traffic) added at
   the scenario SNR + 10 dB (effective 10–20 dB; "clean" notes get street traffic at 25 dB), soft limiter,
   Opus 32 kbit/s round trip as in a browser upload.

On the cluster: `sbatch --export=ALL scripts/cluster/scenario_inputs.sbatch` (inputs only) or as step 1 of
`scenario_e2e.sbatch`.

---

## 4. ASR benchmark sets

Two sets measure speech recognition in isolation, at harder noise levels than the scenarios:

| Set | Built from | Conditions | Clips |
|---|---|---|---|
| `noisy` | Scenario sentences, XTTS-v2 (2 studio voices + accent clones), de/en/pl/tr | clean + SNR 15 / 10 / 5 / 0 / −5 dB, phone level model, Opus | 372 |
| `noisy_cv` | **Real** Common Voice recordings of German speakers with different accents, human transcripts | clean + SNR 15 / 10 / 5 / 0 / −5 dB | 726 (121 × 6) |

Additional pure-noise and silence clips (empty reference) measure hallucination.

```bash
python scripts/data/audio/download_data.py                       # Common Voice clips + noise → data/raw/
sbatch scripts/cluster/tts.sbatch                                # XTTS + noise mixing → data/asr_eval/noisy
python scripts/data/audio/sythesize_noise_data.py --speech data/raw/speech/de_cv --out data/asr_eval/noisy_cv
```

`data/raw/` is not committed (some sources are non-commercial).

---

## 5. Packaging

`scripts/data/package_hf.py` builds a local Hugging Face dataset folder (`data/hf_release/sitevox-scenarios/`)
with the project documents, scenarios, original images, input streams, a SHA-256 manifest and a dataset card.
Nothing is uploaded.

---

## 6. Licences

Released for non-commercial research (CC BY-NC-SA 4.0). Upstream sources:

| Source | Licence | Used for |
|---|---|---|
| XTTS-v2 (Coqui) | Coqui Public Model License 1.0.0 (non-commercial) | all synthetic speech |
| Common Voice | CC0 | voice-cloning references, `noisy_cv` set |
| UrbanSound8K | CC BY-NC 3.0 | engine, jackhammer, drilling noise |
| DEMAND | CC BY-SA 3.0 | street traffic background |
| Image model | generated images | all photos |

---

## 7. Limitations

- Synthetic speech and generated images; real site recordings differ (reverberation, overlapping talk, dialects).
- One project, four days, about 40 captures per language: suited for evaluation and error analysis, not for training.
- Gold labels come from a single annotator; they reflect one reasonable reading of VOB/B, not legal advice.
- Two voice notes failed the TTS quality check and were kept as the best attempt
  (`SCN-RIEM-0018 de/C03`, `SCN-RIEM-0018 tr/C06`).
