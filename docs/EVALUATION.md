# Evaluation

All runs below ran in **GPU mode** on a single GPU with the production models:
faster-whisper large-v3 (ASR), Qwen3-VL-4B-Instruct (photos), Qwen3-4B-Instruct-2507 (extraction) and
Qwen3-8B (drafting), served with vLLM 0.32. Test data are described in [MOCK_DATA.md](MOCK_DATA.md).

Only **complete runs** are reported: every scenario day in every language finished and was scored.
Cancelled, partial and failed jobs are listed in [§ 5](#5-runs-not-reported) and excluded from all tables.

---

## 1. What was tested

| Benchmark | Script | Unit of evaluation | Runs reported |
|---|---|---|---|
| ASR under construction noise | `evaluation/eval_asr.py` | 1 098 clips (372 synthetic, 726 real speakers), 2 ASR backends | 1 benchmark job, 4 backend × set combinations |
| End-to-end scenarios | `evaluation/eval_capture_scenario.py` | 16 day-runs per version (4 days × 4 languages): 64 gold events, 80 routine captures, 64 voice notes, 24 expected letters | 3 versions × 16 day-runs = 48 day-runs |

The end-to-end benchmark feeds the generated input stream (photos, typed notes, voice notes) into the running
system exactly as the app would, one capture at a time, and scores the resulting database against `gold.json`.

### End-to-end metrics

| Metric | Definition |
|---|---|
| Events detected | Gold disruptions matched by a system event (recall) |
| Event type correct | Correct event type among detected events |
| Risk sphere correct | Correct AG / AN / neutral among detected events (rule engine output) |
| Letter type correct | Correct recommended document among detected events |
| Routine false alarms | Routine captures that wrongly produced an event |
| Routine logged correctly | Routine captures written to the site diary with the right entry kind |
| Deliveries captured | Expected deliveries present in the diary |
| Equipment captured | Expected equipment entries present in the diary |
| Daily progress | Activities with the correct reported quantity |
| Staffing | Days with the correct total headcount |
| Photos attached | Expected photos attached to the right event |
| Unusable photos attached | Blurred or irrelevant photos wrongly attached as evidence |
| Letters drafted | Expected letters to the client that were drafted |
| Wrong letters to client | Letters drafted to the client although none was expected |
| ASR WER / LID | Word error rate and language identification of the voice notes |
| Time per capture | Median wall time from upload to stored event / diary entry |

---

## 2. Speech recognition benchmark

Job of 21.11.2026, `outputs/eval/asr_20261121/`. Values in %, 95 % bootstrap confidence intervals in brackets
(clustered by scenario / speaker).

### 2.1 Backend comparison: faster-whisper vs. WhisperX (both Whisper large-v3)

| Metric | faster-whisper | WhisperX |
|---|---|---|
| WER, synthetic set, all languages (n = 372) | **28.1** [20.8, 33.7] | 30.3 [21.1, 37.9] |
| WER, real speakers, German (n = 726) | **26.8** [22.3, 32.0] | 27.6 [23.0, 32.9] |
| WER, Turkish | **43.1** | 53.5 |
| WER, English | **37.1** | 60.1 |
| Word-confidence AUROC (does the word score detect errors?) | **0.914** | 0.816 |
| Language identification, synthetic set | 97.8 | 97.8 |

faster-whisper is better or equal on every aggregate and gives **true per-word probabilities**, which feed the
confidence score. It became the production backend.

### 2.2 faster-whisper large-v3 in detail

| Metric | Result | Set |
|---|---|---|
| WER, real speakers, clean | **10.7** [7.8, 14.4] | `noisy_cv`, n = 121 |
| WER, real speakers, SNR 15 dB | **14.0** [10.3, 18.7] | `noisy_cv`, n = 121 |
| WER, German, clean | **18.1** [9.0, 26.0] | `noisy`, n = 52 |
| Construction-term error, German | **7.2** [2.8, 14.1] | 696 term occurrences |
| Construction-term error, German, SNR ≥ 10 dB | **≤ 2.6** | 116 term occurrences per condition |
| Time-of-day recall, German | **93.2** [87.5, 97.2] | 192 times |
| Language identification, German | **98.1** | n = 312 |
| Hallucination on pure noise / silence | **0 words/min**, 0 % of clips | 18 clips |
| Real-time factor | **0.070** (p95 0.100) | latency per clip p50 0.81 s |

---

## 3. End-to-end scenario benchmark

### 3.1 Versions

| Version | Job(s) | Date | What changed |
|---|---|---|---|
| **v0** – first full run | 5043190 | 22.11. 03:23 | Event / site-diary separation (`log_entries`), delivery tracking; replay of whole captures not yet like the app |
| **v1** – photo-first replay | 5043627, + 5043805 / 5043940 for SCN-0017 pl/tr | 22.11. 05:22 | Replay exactly as the app (first photo + first note, further notes as own messages), days in one database per language, extended scoring. All 16 day-runs re-scored with the final evaluator. |
| **v2** – prioritised prompt + compact JSON | 5044032 | 22.11. 08:54 | Extraction prompt with an explicit category order and per-category examples (de/en/pl/tr); staffing split into regular + additional staff; equipment states; **guided JSON without free whitespace** |

### 3.2 Results (all 16 day-runs per version)

| Metric | v0 | **v1** | v2 |
|---|---|---|---|
| Events detected | 12 % (8/64) | **84 %** (54/64) | 56 % (36/64) |
| Event type correct | 75 % | 85 % | **94 %** |
| Risk sphere correct | 62 % | 74 % | **81 %** |
| Letter type correct | 62 % | 63 % | **69 %** |
| Routine false alarms ↓ | **0 %** | 9 % (7/80) | **0 %** |
| Routine logged correctly | **90 %** | 89 % | 89 % |
| Deliveries captured | 50 % | **94 %** (15/16) | 88 % |
| Equipment captured | 28 % | **47 %** | 42 % |
| Daily progress | 36 % | **73 %** | 64 % |
| Staffing (days correct) | 0/16 | **10/16** | 5/16 |
| Photos attached to the right event | 4 % | **46 %** | 29 % |
| Unusable photos attached ↓ | **0 %** (0/68) | **0 %** (0/68) | **0 %** (0/68) |
| Letters to the client drafted | 0/24 | **12/24** | 9/24 |
| Wrong letters to the client ↓ | **0** | 3 | **0** |
| ASR WER (64 voice notes) | 11.3 % | 11.3 % | 11.3 % |
| ASR language identification | 100 % | 100 % | 100 % |
| Median time per capture ↓ | 8.4 s | 12.8 s | **5.9 s** |

### 3.3 v1 per input language

| Metric | DE | EN | PL | TR | All |
|---|---|---|---|---|---|
| Events detected | 94 % | 81 % | 88 % | 75 % | **84 %** |
| Event type correct | 80 % | 85 % | 93 % | 83 % | **85 %** |
| Risk sphere correct | 73 % | 69 % | 71 % | 83 % | **74 %** |
| Routine logged correctly | 90 % | 95 % | 80 % | 90 % | **89 %** |
| Deliveries captured | 100 % | 100 % | 75 % | 100 % | **94 %** |
| Daily progress | 82 % | 73 % | 55 % | 82 % | **73 %** |
| Median time per capture | 13.6 s | 13.3 s | 12.4 s | 13.2 s | **12.8 s** |

### 3.4 What the comparison shows

- **v0 → v1:** event recall rose from 12 % to 84 %, deliveries from 50 % to 94 %, daily progress from 36 % to
  73 %, photo attachments from 4 % to 46 %. The changes between the two runs were the replay of captures exactly
  as the app does (photo, follow-up question, answer) and one database per language across all days, so that
  later days can continue and close earlier events.
- **v1 → v2:** precision went up (type 94 %, sphere 81 %, no false alarms, no wrong letters, 2.2× faster), but
  recall dropped from 84 % to 56 %. Failure analysis of the raw outputs (`SITEVOX_LLM_DEBUG_DIR`) showed word
  loops with compact guided decoding (no free whitespace), so the drop is attributed to compact JSON rather than
  to the new prompt (both changed in v2; not separated by an ablation). Compact JSON was therefore made
  **opt-in** (`SITEVOX_JSON_COMPACT=1`, default off); the retry now raises the temperature from the second
  attempt so that T = 0 does not repeat a broken output.
- **Stable across versions:** no unusable photo was ever attached as evidence, language identification of the
  voice notes was always 100 %, and the risk sphere comes from rules, so it improves only through better upstream
  extraction.

### 3.5 Known weak points (v1)

| Metric | Result |
|---|---|
| Delivery quantity correct | 19 % (3/16) |
| Number recall in voice notes (times, quantities) | 49 % |
| Letters drafted out of the expected 24 | 50 % |

The bottleneck for letters is upstream: a letter is only drafted when the event is detected and attributed to
the client.

---

## 4. Reproduce

```bash
# ASR benchmark (both backends, both sets)
sbatch scripts/cluster/eval_asr.sbatch
# end-to-end: 4 days × de/en/pl/tr
sbatch --export=ALL scripts/cluster/scenario_e2e.sbatch
# re-score existing runs with the current evaluator (no GPU)
python -m evaluation.eval_capture_scenario --run data/scenario_runs/<run> --inputs data/raw/<scenario> \
    --scenario data/demo/scenario/<scenario>.json --out outputs/eval/rescore/<scenario>
```

Per run: `outputs/eval/scenario_<ID>_<date>_<lang>_<job>/summary.md` (human-readable) and `result.json`
(all counts). Logs: `data/e2e_slurm_<job>.log`, service logs in `data/scenario_runs/job_<job>/`.

---

## 5. Runs not reported

| Job | Reason |
|---|---|
| 5041765, 5041984 | First end-to-end runs on the earlier single-day scenario format; not comparable |
| 5043052 | Cancelled after 3 of 16 day-runs |
| 5043805, 5043940 | Partial re-runs (2 day-runs each); used only to complete v1 for SCN-0017 pl/tr |
| 5041793, 5041927 | Job failed (earlier single-day format) |
| 5044141, 5044167 | Model services did not start in time (slow NFS weight loading) |
