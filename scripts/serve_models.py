#!/usr/bin/env python3
"""Startbefehle für die Modellserver aus config/models.toml (GPU-Rechner).

  python scripts/serve_models.py            # Befehle anzeigen
  python scripts/serve_models.py --run      # Extraktor + Drafter im Hintergrund starten
  python scripts/serve_models.py --engine llama_cpp

vLLM: OpenAI-kompatible Server mit Guided Decoding (response_format=json_schema).
Vision (Qwen3-VL) wird standardmäßig lazy in-process geladen (backend="transformers") und braucht keinen Server.
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sitevox import settings  # noqa: E402


def vllm_cmd(role: str, cfg: dict, serve: dict, host: str = "127.0.0.1", api_key: str | None = None) -> list[str]:
    port = urlparse(cfg["base_url"]).port
    model = cfg["model"]
    cmd = ["vllm", "serve", model, "--served-model-name", cfg["served_name"], "--port", str(port),
           "--host", host,
           "--max-model-len", str(cfg.get("max_model_len", 16384)),
           "--gpu-memory-utilization", str(serve.get(f"gpu_memory_utilization_{role}", 0.3))]
    if role == "drafter" and cfg.get("awq_repo"):
        cmd[2] = cfg["awq_repo"]
        cmd += ["--quantization", "awq"]
    if cfg.get("lora_adapter"):
        cmd += ["--enable-lora", "--lora-modules", f"extract={cfg['lora_adapter']}"]
    if role == "vision":
        cmd += ["--limit-mm-per-prompt", '{"image": 1}']
    if api_key:
        cmd += ["--api-key", api_key]
    return cmd


def llama_cpp_cmd(role: str, cfg: dict, host: str = "127.0.0.1", api_key: str | None = None) -> list[str]:
    port = urlparse(cfg["base_url"]).port
    repo = cfg.get("gguf_repo") or cfg["model"]
    cmd = ["llama-server", "-hf", f"{repo}" + (f":{cfg['gguf_file']}" if cfg.get("gguf_file") else ""),
           "--port", str(port), "-c", str(cfg.get("max_model_len", 16384)), "-ngl", "99", "--jinja",
           "--alias", cfg["served_name"], "--host", host]
    if api_key:
        cmd += ["--api-key", api_key]
    return cmd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["vllm", "llama_cpp"])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--with-vision", action="store_true", help="Qwen3-VL zusätzlich als Server starten")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind-Adresse; auf dem Cluster 0.0.0.0, damit der SSH-Tunnel den Knoten erreicht")
    ap.add_argument("--roles", help="Kommagetrennt, z. B. extractor,drafter oder vision (Standard: laut Config)")
    ap.add_argument("--gpu-util", action="append", default=[], metavar="ROLE=FRAC",
                    help="gpu_memory_utilization überschreiben, z. B. vision=0.55 (eigene GPU)")
    ap.add_argument("--model", action="append", default=[], metavar="ROLE=PATH",
                    help="Modell (HF-Repo oder lokaler Ordner) überschreiben, z. B. drafter=$WORK/mmr/models/Qwen3-8B; "
                         "deaktiviert für diese Rolle die AWQ-Variante")
    ap.add_argument("--wait", action="store_true", help="Im Vordergrund auf die Server warten (sbatch)")
    args = ap.parse_args()
    api_key = os.environ.get("SITEVOX_LLM_API_KEY")
    if args.host not in ("127.0.0.1", "localhost") and not api_key:
        sys.exit("Fehler: --host %s ohne SITEVOX_LLM_API_KEY – Server wäre für alle Cluster-Nutzer offen." % args.host)
    m = settings.models()
    engine = args.engine or m["serve"]["engine"]
    procs: list[subprocess.Popen] = []
    roles = ["extractor", "drafter"] + (["vision"] if args.with_vision or m["llm"]["vision"]["backend"] == "openai" else [])
    if args.roles:
        roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    serve = dict(m["serve"])
    for kv in args.gpu_util:
        role, frac = kv.split("=", 1)
        serve[f"gpu_memory_utilization_{role}"] = float(frac)
    model_override = dict(kv.split("=", 1) for kv in args.model)
    for role in roles:
        cfg = dict(m["llm"][role])
        if role in model_override:
            cfg["model"] = model_override[role]
            cfg.pop("awq_repo", None)  # lokales Vollmodell statt AWQ-Repo
        cmd = (vllm_cmd(role, cfg, serve, args.host, api_key) if engine == "vllm"
               else llama_cpp_cmd(role, cfg, args.host, api_key))
        shown = [("***" if api_key and c == api_key else c) for c in cmd]
        print(f"# {role}: {cfg['model']}\n{shlex.join(shown)}\n", flush=True)
        if args.run:
            log = open(settings.ROOT / f"data/serve_{role}.log", "w")
            procs.append(subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT))
    print("# ASR (in-process):", m["asr"]["backend"], m["asr"]["model"])
    print("# Embedding/Rerank (in-process):", m["rag"]["embedding_model"], m["rag"]["reranker_model"])
    print("# Danach: SITEVOX_MODE=gpu uvicorn backend.main:app --port 8000", flush=True)
    if args.run and args.wait:
        try:
            for p in procs:
                p.wait()
        finally:
            for p in procs:
                p.terminate()


if __name__ == "__main__":
    main()
