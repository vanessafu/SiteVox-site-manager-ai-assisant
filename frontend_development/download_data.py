# ============================================================================
#  Makathon data downloader  -  run: python download_data.py
#  Downloads a SMALL sample (default 10 clips per language) of clean speech
#  and construction-like noise, plus a few pre-mixed noisy examples.
#  Everything lands in the folder "makathon_data" next to this file.
#  Needs Python 3.9-3.12 installed (python.org, tick "Add to PATH").
# ============================================================================
import csv, io, json, os, subprocess, sys, time, traceback, urllib.request, zipfile
from pathlib import Path

N_PER_LANG = 10          # clips per language
N_PER_NOISE_CLASS = 5    # short noise clips per UrbanSound8K class
SR = 16000

HERE = Path(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__)).parent
OUT = HERE / "makathon_data"
SPEECH, NOISE, MIXED = OUT / "speech", OUT / "noise", OUT / "speech_noisy"
RESULTS = []  # (task, status, detail)


def say(msg):
    print(msg, flush=True)


def ensure_packages():
    need = []
    for mod, pip_name in [("datasets", "datasets>=2.18,<4"), ("soundfile", "soundfile"),
                          ("librosa", "librosa"), ("huggingface_hub", "huggingface_hub")]:
        try:
            __import__(mod)
            if mod == "datasets":
                import datasets
                if int(datasets.__version__.split(".")[0]) >= 4:
                    need.append(pip_name)  # v4 dropped loading scripts (FLEURS needs them)
        except ImportError:
            need.append(pip_name)
    if need:
        say(f"Installing Python packages: {' '.join(need)} (one-time, a few minutes) ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *need])


def task(name):
    def deco(fn):
        def run(*a, **k):
            say(f"\n=== {name} ===")
            t = time.time()
            try:
                detail = fn(*a, **k) or "ok"
                RESULTS.append((name, "OK", f"{detail} ({time.time() - t:.0f}s)"))
                say(f"  -> OK: {detail}")
            except Exception as e:
                RESULTS.append((name, "FAILED", f"{type(e).__name__}: {e}"[:300]))
                say(f"  -> FAILED, skipping: {type(e).__name__}: {e}")
                traceback.print_exc(limit=1)
        return run
    return deco


def to16k(array, sr):
    import librosa
    import numpy as np
    y = np.asarray(array, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    return librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y


def text_of(ex):
    for k in ("raw_transcription", "transcription", "sentence", "transcript", "text"):
        if isinstance(ex.get(k), str) and ex[k].strip():
            return ex[k].strip()
    return ""


def save_speech(rows, folder, source, lang, examples, license_):
    import soundfile as sf
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for ex in examples:
        a = ex["audio"]
        y = to16k(a["array"], a["sampling_rate"])
        name = f"{lang}_{source}_{n:02d}.wav"
        sf.write(folder / name, y, SR)
        rows.append({"file": f"speech/{lang}/{name}", "language": lang, "source": source,
                     "text": text_of(ex), "seconds": round(len(y) / SR, 1), "license": license_})
        n += 1
        if n >= N_PER_LANG:
            break
    if n == 0:
        raise RuntimeError("no examples returned")
    return n


def stream(repo, config, split, **kw):
    from datasets import load_dataset
    return load_dataset(repo, config, split=split, streaming=True, **kw)


# ----------------------------------------------------------------- speech
FLEURS = {  # our language tag -> FLEURS config
    "pl": "pl_pl", "ro": "ro_ro", "cs": "cs_cz", "sk": "sk_sk", "hu": "hu_hu", "bg": "bg_bg",
    "hr": "hr_hr", "sr": "sr_rs", "uk": "uk_ua", "ru": "ru_ru", "tr": "tr_tr", "ar": "ar_eg",
    "fa": "fa_ir", "ckb": "ckb_iq", "de": "de_de", "zh": "cmn_hans_cn",
}


def speech_fleurs(rows, lang, cfg):
    @task(f"Speech FLEURS {lang} ({cfg})")
    def _():
        ds = stream("google/fleurs", cfg, "test", trust_remote_code=True)
        n = save_speech(rows, SPEECH / lang, "fleurs", lang, ds, "CC BY 4.0")
        return f"{n} clips"
    _()


def speech_mediaspeech(rows, lang):
    @task(f"Speech MediaSpeech {lang}")
    def _():
        ds = stream("ymoslem/MediaSpeech", lang, "train")
        n = save_speech(rows, SPEECH / lang, "mediaspeech", lang, ds, "CC BY 4.0")
        return f"{n} clips"
    _()


def speech_mls(rows, lang, cfg):
    @task(f"Speech Multilingual LibriSpeech {lang} ({cfg})")
    def _():
        ds = stream("facebook/multilingual_librispeech", cfg, "test")
        n = save_speech(rows, SPEECH / lang, "mls", lang, ds, "CC BY 4.0")
        return f"{n} clips"
    _()


# ----------------------------------------------------------------- noise
@task("Noise open-noise: roadwork (3 x 10 min)")
def noise_roadwork():
    from huggingface_hub import hf_hub_download
    import shutil
    dst = NOISE / "roadwork_open-noise"
    dst.mkdir(parents=True, exist_ok=True)
    got = 0
    for v in ("a_steady", "b_eventful", "c_dynamic"):
        p = hf_hub_download("routsourav1729/open-noise", f"noise/roadwork/roadwork__{v}.wav", repo_type="dataset")
        shutil.copy(p, dst / f"roadwork__{v}.wav")
        got += 1
    return f"{got} files (license: non-commercial, share-alike)"


@task("Noise DEMAND: street traffic (STRAFFIC, 16 kHz, ~119 MB)")
def noise_demand():
    url = "https://zenodo.org/records/1227121/files/STRAFFIC_16k.zip?download=1"
    dst = NOISE / "street_traffic_DEMAND"
    dst.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_STRAFFIC_16k.zip"
    if not tmp.exists():
        say("  downloading ~119 MB ...")
        urllib.request.urlretrieve(url, tmp)
    with zipfile.ZipFile(tmp) as z:
        wavs = [n for n in z.namelist() if n.lower().endswith(".wav")]
        pick = [n for n in wavs if n.lower().endswith("ch01.wav")] or wavs[:1]
        for n in pick:  # one channel is enough
            (dst / Path(n).name).write_bytes(z.read(n))
    tmp.unlink()
    return f"{len(pick)} file(s) (CC BY)"


@task("Noise UrbanSound8K: jackhammer / drilling / engine idling")
def noise_urbansound():
    import soundfile as sf
    want = {"jackhammer": 0, "drilling": 0, "engine_idling": 0}
    ds = stream("danavery/urbansound8K", None, "train")
    for ex in ds:
        c = ex.get("class")
        if c in want and want[c] < N_PER_NOISE_CLASS:
            d = NOISE / f"urbansound8k_{c}"
            d.mkdir(parents=True, exist_ok=True)
            sf.write(d / f"{c}_{want[c]:02d}.wav", to16k(ex["audio"]["array"], ex["audio"]["sampling_rate"]), SR)
            want[c] += 1
        if all(v >= N_PER_NOISE_CLASS for v in want.values()):
            break
    return ", ".join(f"{k}: {v}" for k, v in want.items()) + " (CC BY-NC)"


# ----------------------------------------------------------------- mixing
@task("Pre-mix examples: 2 clips per language x roadwork noise at 10 / 5 / 0 dB")
def premix(rows):
    import numpy as np
    import soundfile as sf
    noise_files = sorted((NOISE / "roadwork_open-noise").glob("*.wav")) or sorted(NOISE.rglob("*.wav"))
    if not noise_files:
        raise RuntimeError("no noise downloaded")
    noise, nsr = sf.read(noise_files[0], dtype="float32")
    noise = to16k(noise, nsr)
    MIXED.mkdir(parents=True, exist_ok=True)
    rms = lambda x: float(np.sqrt(np.mean(x ** 2) + 1e-12))
    rng = np.random.default_rng(0)
    out, per_lang = [], {}
    for r in rows:
        lang = r["language"]
        if per_lang.get(lang, 0) >= 2:
            continue
        per_lang[lang] = per_lang.get(lang, 0) + 1
        y, _ = sf.read(OUT / r["file"], dtype="float32")
        for snr in (10, 5, 0):
            s = int(rng.integers(0, max(1, len(noise) - len(y))))
            n = np.resize(noise[s:], len(y))
            mix = y + n * rms(y) / (rms(n) * 10 ** (snr / 20))
            mix = mix / max(1.0, float(np.max(np.abs(mix))) / 0.95)
            name = f"{Path(r['file']).stem}__roadwork__snr{snr}dB.wav"
            sf.write(MIXED / name, mix, SR)
            out.append({"file": f"speech_noisy/{name}", "clean_file": r["file"], "language": lang,
                        "snr_db": snr, "text": r["text"]})
    with open(MIXED / "noisy_index.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    return f"{len(out)} noisy files"


# ----------------------------------------------------------------- docs
MANUAL = """
## Not downloaded automatically (download by hand if needed)

| What | Where | Note |
|---|---|---|
| Mozilla Common Voice (all languages, CC-0) | https://datacollective.mozillafoundation.org | whole language packs, several GB |
| Golos (Russian, 1240 h) | https://github.com/sberdevices/golos / https://openslr.org/114 | 18 GB |
| BIGOS (Polish ASR benchmark) | https://huggingface.co/datasets/amu-cai/pl-asr-bigos-v2 | needs HF login + accept terms |
| STT4SG-350 (Swiss German) | https://swissnlp.org/datasets/ | request access |
| SDS-200 (Swiss German) | https://github.com/stt4sg/dialektsammlung-public | |
| Betthupferl (Bavarian, Franconian, Swabian) | https://github.com/mainlp/betthupferl | text only; audio via Bayerischer Rundfunk on request |
| MUSAN (noise, CC BY 4.0) | https://openslr.org/17 | 11 GB |
| Freesound construction site (concrete pour) | https://freesound.org/s/400865 | free account, credit "klankbeeld / freesound.org" |
| BigSoundBank urban works (CC0) | https://bigsoundbank.com/urban-works-1-s3526.html | no account needed |
| ZapSplat construction site | https://www.zapsplat.com/sound-effect-category/construction-site/ | free account |
"""


def write_docs(rows):
    if rows:
        with open(OUT / "transcripts.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    lines = ["# makathon_data - what is in here\n",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')} by download_data.py\n",
             "## Download log\n", "| Task | Status | Detail |", "|---|---|---|"]
    lines += [f"| {t} | {s} | {d.replace('|', '/')} |" for t, s, d in RESULTS]
    lines += ["\n## Licenses of downloaded data\n",
              "- FLEURS, MediaSpeech, Multilingual LibriSpeech: CC BY 4.0 (credit the authors)",
              "- open-noise (roadwork): non-commercial, share-alike (research/evaluation only)",
              "- DEMAND: CC BY", "- UrbanSound8K: CC BY-NC (non-commercial only)",
              "\nAll audio is 16 kHz mono WAV. Reference texts are in transcripts.csv.", MANUAL]
    (OUT / "README_SOURCES.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    say(__doc__ or "")
    say(f"Target folder: {OUT}")
    OUT.mkdir(exist_ok=True)
    ensure_packages()
    rows = []
    for lang, cfg in FLEURS.items():
        speech_fleurs(rows, lang, cfg)
    speech_mediaspeech(rows, "tr")
    speech_mediaspeech(rows, "ar")
    speech_mls(rows, "de", "german")
    speech_mls(rows, "pl", "polish")
    noise_roadwork()
    noise_demand()
    noise_urbansound()
    if rows:
        premix(rows)
    write_docs(rows)
    ok = sum(1 for r in RESULTS if r[1] == "OK")
    say("\n" + "=" * 70)
    say(f"Done: {ok}/{len(RESULTS)} tasks OK, {len(rows)} clean speech clips.")
    for t, s, d in RESULTS:
        if s != "OK":
            say(f"  FAILED  {t}: {d}")
    say(f"See {OUT / 'README_SOURCES.md'} for details and manual download links.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        say("\nSomething went wrong before the downloads finished (see above).")
    sys.exit(0)  # always 0, so the .bat does not start a second run
