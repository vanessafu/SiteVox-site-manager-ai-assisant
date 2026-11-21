"""Sprache → Text mit Wort-Zeitstempeln und Wort-Scores (lokal, DSGVO-freundlich).

Backends (config/models.toml [asr].backend):
  whisperx       – faster-whisper + wav2vec2-Alignment, word.score = Alignment-Konfidenz
  faster_whisper – word.probability = ASR-Wortwahrscheinlichkeit
  mlx_whisper    – Apple Silicon
  remote         – WhisperX auf dem GPU-Knoten (scripts/cluster/asr_server.py), Audio über SSH-Tunnel
Sprache: "auto" erkennt pro Aufnahme unter allowed_languages (de/en/tr/pl) und wählt Prompt + Alignment-Modell.
Demo-Modus: Replay aus data/demo/<projekt>/fixtures/asr/<dateiname>.json
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .. import settings

log = logging.getLogger(__name__)


def _norm_word(w: str) -> str:
    return re.sub(r"[^\wäöüß]", "", w.lower())


# ----------------------------------------------------------------------------- language & prompts
def _asr_cfg() -> dict:
    return settings.models()["asr"]


def _prompt_for(lang: str) -> Optional[str]:
    c = _asr_cfg()
    return c.get("initial_prompts", {}).get(lang) or (c.get("initial_prompt") if lang == "de" else None)


def _pick_language(probs: list[tuple[str, float]]) -> tuple[str, Optional[float]]:
    """Wahrscheinlichste Sprache, aber nur unter allowed_languages (sonst fallback_language)."""
    c = _asr_cfg()
    allowed = set(c.get("allowed_languages") or [])
    cand = [(lang, p) for lang, p in probs if not allowed or lang in allowed]
    if not cand:
        return c.get("fallback_language", "de"), None
    lang, p = max(cand, key=lambda x: x[1])
    return lang, round(float(p), 3)


def _detect_language(fw_model, audio, pipeline=None) -> tuple[str, Optional[float]]:
    """Spracherkennung auf den ersten Sprachabschnitten (VAD, robust gegen Lärm am Anfang)."""
    try:
        _, _, probs = fw_model.detect_language(audio=audio, vad_filter=True, language_detection_segments=3)
        return _pick_language(probs)
    except Exception as e:  # noqa: BLE001 – ältere faster-whisper-Versionen
        log.warning("detect_language (faster-whisper) fehlgeschlagen: %s", e)
    if pipeline is not None:
        try:
            return _pick_language([(pipeline.detect_language(audio), 1.0)])
        except Exception as e:  # noqa: BLE001
            log.warning("detect_language (whisperx) fehlgeschlagen: %s", e)
    return _asr_cfg().get("fallback_language", "de"), None


def _with_options(options, **kw):
    if dataclasses.is_dataclass(options):
        return dataclasses.replace(options, **kw)
    return options._replace(**kw)  # NamedTuple (ältere faster-whisper)


def _hotwords() -> Optional[str]:
    return " ".join(_asr_cfg().get("hotwords", [])) or None


def _words_from_segment(seg: dict) -> list[dict]:
    """Fallback ohne Alignment-Modell: gleichmäßig verteilte Zeiten, kein Score."""
    toks = seg["text"].split()
    if not toks:
        return []
    step = (seg["end"] - seg["start"]) / len(toks)
    return [{"word": w, "start": round(seg["start"] + i * step, 2), "end": round(seg["start"] + (i + 1) * step, 2),
             "score": None} for i, w in enumerate(toks)]


# ----------------------------------------------------------------------------- backends
@lru_cache(maxsize=1)
def _whisperx_model():
    import whisperx  # type: ignore

    c = _asr_cfg()
    dev = settings.models()["runtime"]["device"]
    fixed = None if c["language"] == "auto" else c["language"]
    return whisperx.load_model(
        c["model"], dev, compute_type=c.get("compute_type", "float16"), language=fixed,
        asr_options={"beam_size": c.get("beam_size", 5), "initial_prompt": None,
                     "hotwords": " ".join(c.get("hotwords", [])) or None},
    )


@lru_cache(maxsize=4)
def _align_model(lang: str):
    import whisperx  # type: ignore

    return whisperx.load_align_model(language_code=lang, device=settings.models()["runtime"]["device"])


def _run_whisperx(path: Path, language: str) -> dict:
    import whisperx  # type: ignore

    c = _asr_cfg()
    dev = settings.models()["runtime"]["device"]
    pipe = _whisperx_model()
    audio = whisperx.load_audio(str(path))
    prob = None
    if language == "auto":
        language, prob = _detect_language(pipe.model, audio, pipeline=pipe)
    pipe.options = _with_options(pipe.options, initial_prompt=_prompt_for(language))
    res = pipe.transcribe(audio, batch_size=c.get("batch_size", 16), language=language)
    try:
        align_model, meta = _align_model(language)
        segments = whisperx.align(res["segments"], align_model, meta, audio, dev,
                                  return_char_alignments=False)["segments"]
    except Exception as e:  # noqa: BLE001 – kein Alignment-Modell für die Sprache
        log.warning("Kein Wort-Alignment für %s: %s", language, e)
        segments = [{**s, "words": _words_from_segment(s)} for s in res["segments"]]
    segs = []
    for s in segments:
        words = [{"word": w["word"], "start": w.get("start"), "end": w.get("end"), "score": w.get("score")}
                 for w in s.get("words", [])]
        segs.append({"start": s["start"], "end": s["end"], "text": s["text"].strip(), "words": words})
    return {"segments": segs, "duration": len(audio) / 16000, "language": language, "language_prob": prob}


@lru_cache(maxsize=1)
def _fw_model():
    from faster_whisper import WhisperModel  # type: ignore

    if settings.models()["runtime"]["device"] == "cuda":
        try:  # torch lädt cuBLAS/cuDNN aus den pip-Paketen in den Prozess; CTranslate2 findet sie sonst oft nicht
            import torch  # type: ignore  # noqa: F401

            torch.zeros(1, device="cuda") @ torch.zeros(1, device="cuda")
        except Exception as e:  # noqa: BLE001
            log.warning("CUDA-Bibliotheken über torch vorladen fehlgeschlagen: %s", e)
    c = _asr_cfg()
    return WhisperModel(c["model"], device=settings.models()["runtime"]["device"],
                        compute_type=c.get("compute_type", "float16"))


def _run_faster_whisper(path: Path, language: str) -> dict:
    from faster_whisper import decode_audio  # type: ignore

    c = _asr_cfg()
    model = _fw_model()
    audio = decode_audio(str(path))
    prob = None
    if language == "auto":
        language, prob = _detect_language(model, audio)
    segments, info = model.transcribe(
        audio, language=language, initial_prompt=_prompt_for(language), beam_size=c.get("beam_size", 5),
        word_timestamps=True, vad_filter=c.get("vad_filter", True),
        hotwords=" ".join(c.get("hotwords", [])) or None,
    )
    segs = []
    for s in segments:
        words = [{"word": w.word.strip(), "start": w.start, "end": w.end, "score": w.probability}
                 for w in (s.words or [])]
        segs.append({"start": s.start, "end": s.end, "text": s.text.strip(), "words": words})
    return {"segments": segs, "duration": info.duration, "language": language, "language_prob": prob}


def _run_mlx(path: Path, language: str) -> dict:
    import mlx_whisper  # type: ignore

    c = _asr_cfg()
    lang = None if language == "auto" else language  # mlx: freie Erkennung, ohne allowed_languages
    res = mlx_whisper.transcribe(str(path), path_or_hf_repo=c["mlx_repo"], language=lang,
                                 initial_prompt=_prompt_for(lang or c.get("fallback_language", "de")),
                                 word_timestamps=True)
    segs = []
    for s in res["segments"]:
        words = [{"word": w["word"].strip(), "start": w["start"], "end": w["end"], "score": w.get("probability")}
                 for w in s.get("words", [])]
        segs.append({"start": s["start"], "end": s["end"], "text": s["text"].strip(), "words": words})
    return {"segments": segs, "duration": segs[-1]["end"] if segs else 0.0, "language": res.get("language", lang),
            "language_prob": None}


def _run_remote(path: Path, language: str) -> dict:
    """WhisperX auf dem GPU-Knoten (scripts/cluster/asr_server.py) über den SSH-Tunnel."""
    import httpx

    c = _asr_cfg()
    key = os.environ.get("SITEVOX_LLM_API_KEY", "")
    with open(path, "rb") as f:
        r = httpx.post(f"{c['remote_url'].rstrip('/')}/transcribe", data={"language": language},
                       files={"file": (Path(path).name, f, "application/octet-stream")},
                       headers={"Authorization": f"Bearer {key}"}, timeout=600)
    r.raise_for_status()
    return r.json()


def _from_text(text: str) -> dict:
    words, t = [], 0.0
    for w in text.split():
        words.append({"word": w, "start": round(t, 2), "end": round(t + 0.35, 2), "score": None})
        t += 0.4
    return {"segments": [{"start": 0.0, "end": t, "text": text, "words": words}], "duration": t}


def transcribe(path: Path, project_id: Optional[str] = None, hint: Optional[str] = None,
               language: Optional[str] = None) -> dict[str, Any]:
    """Gibt {"text", "segments":[{start,end,text,words:[{word,start,end,score}]}], "backend", "language", ...} zurück.

    language: None → config (Standard "auto": Erkennung unter allowed_languages), sonst fester Code.
    hint: Im Demo-Modus ohne Fixture kann das Browser-Transkript (Web Speech API) übergeben werden.
    """
    c = _asr_cfg()
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
        runner = {"whisperx": _run_whisperx, "faster_whisper": _run_faster_whisper, "mlx_whisper": _run_mlx,
                  "remote": _run_remote}[backend]
        res = runner(Path(path), language or c["language"])
        if backend == "remote":
            res["backend"] = f"remote:{res.get('backend', '?')}"
            return res
    res["text"] = " ".join(s["text"] for s in res["segments"]).strip()
    res["backend"] = backend
    res["model"] = c["model"]
    res.setdefault("language", language if language and language != "auto" else None)
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
