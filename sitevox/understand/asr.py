"""Sprache → Text mit Wort-Zeitstempeln und Wort-Scores (lokal, DSGVO-freundlich).

Backends (config/models.toml [asr].backend):
  whisperx       – faster-whisper + wav2vec2-Alignment, word.score = Alignment-Konfidenz
  faster_whisper – word.probability = ASR-Wortwahrscheinlichkeit
  mlx_whisper    – Apple Silicon
Demo-Modus: Replay aus data/demo/<projekt>/fixtures/asr/<dateiname>.json
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .. import settings


def _norm_word(w: str) -> str:
    return re.sub(r"[^\wäöüß]", "", w.lower())


# ----------------------------------------------------------------------------- backends
@lru_cache(maxsize=1)
def _whisperx_model():
    import whisperx  # type: ignore

    c = settings.models()["asr"]
    dev = settings.models()["runtime"]["device"]
    model = whisperx.load_model(
        c["model"], dev, compute_type=c.get("compute_type", "float16"), language=c["language"],
        asr_options={"initial_prompt": c.get("initial_prompt"), "beam_size": c.get("beam_size", 5),
                     "hotwords": " ".join(c.get("hotwords", [])) or None},
    )
    align_model, meta = whisperx.load_align_model(language_code=c["language"], device=dev)
    return model, align_model, meta


def _run_whisperx(path: Path, language: str) -> dict:
    import whisperx  # type: ignore

    c = settings.models()["asr"]
    dev = settings.models()["runtime"]["device"]
    model, align_model, meta = _whisperx_model()
    audio = whisperx.load_audio(str(path))
    res = model.transcribe(audio, batch_size=c.get("batch_size", 16), language=language)
    if language != c["language"]:
        align_model, meta = whisperx.load_align_model(language_code=language, device=dev)
    aligned = whisperx.align(res["segments"], align_model, meta, audio, dev, return_char_alignments=False)
    segs = []
    for s in aligned["segments"]:
        words = [{"word": w["word"], "start": w.get("start"), "end": w.get("end"), "score": w.get("score")}
                 for w in s.get("words", [])]
        segs.append({"start": s["start"], "end": s["end"], "text": s["text"].strip(), "words": words})
    return {"segments": segs, "duration": len(audio) / 16000}


@lru_cache(maxsize=1)
def _fw_model():
    from faster_whisper import WhisperModel  # type: ignore

    c = settings.models()["asr"]
    return WhisperModel(c["model"], device=settings.models()["runtime"]["device"],
                        compute_type=c.get("compute_type", "float16"))


def _run_faster_whisper(path: Path, language: str) -> dict:
    c = settings.models()["asr"]
    segments, info = _fw_model().transcribe(
        str(path), language=language, initial_prompt=c.get("initial_prompt"), beam_size=c.get("beam_size", 5),
        word_timestamps=True, vad_filter=c.get("vad_filter", True),
        hotwords=" ".join(c.get("hotwords", [])) or None,
    )
    segs = []
    for s in segments:
        words = [{"word": w.word.strip(), "start": w.start, "end": w.end, "score": w.probability}
                 for w in (s.words or [])]
        segs.append({"start": s.start, "end": s.end, "text": s.text.strip(), "words": words})
    return {"segments": segs, "duration": info.duration}


def _run_mlx(path: Path, language: str) -> dict:
    import mlx_whisper  # type: ignore

    c = settings.models()["asr"]
    res = mlx_whisper.transcribe(str(path), path_or_hf_repo=c["mlx_repo"], language=language,
                                 initial_prompt=c.get("initial_prompt"), word_timestamps=True)
    segs = []
    for s in res["segments"]:
        words = [{"word": w["word"].strip(), "start": w["start"], "end": w["end"], "score": w.get("probability")}
                 for w in s.get("words", [])]
        segs.append({"start": s["start"], "end": s["end"], "text": s["text"].strip(), "words": words})
    return {"segments": segs, "duration": segs[-1]["end"] if segs else 0.0}


def _from_text(text: str) -> dict:
    words, t = [], 0.0
    for w in text.split():
        words.append({"word": w, "start": round(t, 2), "end": round(t + 0.35, 2), "score": None})
        t += 0.4
    return {"segments": [{"start": 0.0, "end": t, "text": text, "words": words}], "duration": t}


def transcribe(path: Path, project_id: Optional[str] = None, hint: Optional[str] = None,
               language: Optional[str] = None) -> dict[str, Any]:
    """Gibt {"text", "segments":[{start,end,text,words:[{word,start,end,score}]}], "backend", ...} zurück.

    hint: Im Demo-Modus ohne Fixture kann das Browser-Transkript (Web Speech API) übergeben werden.
    """
    c = settings.models()["asr"]
    if settings.is_demo():
        fx = settings.demo_dir(project_id or "BV-RIEM") / "fixtures" / "asr" / f"{Path(path).stem}.json"
        if fx.exists():
            res, backend = json.loads(fx.read_text(encoding="utf-8")), "replay"
        elif hint:
            res, backend = _from_text(hint), "browser-hint"
        else:
            raise FileNotFoundError(f"Demo-Modus: kein ASR-Fixture für {Path(path).name}; bitte Text mitsenden "
                                    f"oder SITEVOX_MODE=gpu verwenden")
    else:
        backend = c["backend"]
        res = {"whisperx": _run_whisperx, "faster_whisper": _run_faster_whisper, "mlx_whisper": _run_mlx}[backend](
            Path(path), language or c["language"])
    res["text"] = " ".join(s["text"] for s in res["segments"]).strip()
    res["backend"] = backend
    res["model"] = c["model"]
    scores = [w["score"] for s in res["segments"] for w in s["words"] if w.get("score") is not None]
    res["mean_score"] = round(sum(scores) / len(scores), 3) if scores else None
    return res


# ----------------------------------------------------------------------------- quote → audio span
def locate_quote(transcript: dict, quote: str, min_ratio: float = 0.6) -> Optional[dict]:
    """Findet ein (vom LLM geliefertes) Zitat im Transkript → Zeitbereich + mittlerer Wort-Score.

    Damit zeigt jedes Feld, das aus einer Sprachnotiz stammt, auf den exakten Audioabschnitt,
    und die ASR-Qualität fließt in die Feld-Konfidenz ein.
    """
    words = [w for s in transcript["segments"] for w in s["words"]]
    if not words or not quote.strip():
        return None
    qn = [_norm_word(w) for w in quote.split() if _norm_word(w)]
    tn = [_norm_word(w["word"]) for w in words]
    L = len(qn)
    best, best_i, best_len = 0.0, -1, L
    qs = " ".join(qn)
    for span in {max(1, L - 2), L, L + 2}:
        for i in range(0, max(1, len(tn) - span + 1)):
            r = SequenceMatcher(None, qs, " ".join(tn[i:i + span])).ratio()
            if r > best:
                best, best_i, best_len = r, i, span
    if best < min_ratio:
        return None
    seg = words[best_i:best_i + best_len]
    scores = [w["score"] for w in seg if w.get("score") is not None]
    low = [w["word"] for w in seg if w.get("score") is not None and w["score"] < 0.6]
    return {
        "t_start": seg[0].get("start"),
        "t_end": seg[-1].get("end"),
        "asr_score": round(min(1.0, sum(scores) / len(scores)), 3) if scores else None,
        "match_ratio": round(best, 3),
        "low_confidence_words": low,
        "text": " ".join(w["word"] for w in seg),
    }
