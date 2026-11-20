"""LLM-Client mit erzwungener strukturierter Ausgabe.

* GPU-Modus: OpenAI-kompatibler Endpunkt (vLLM / llama.cpp-server), response_format=json_schema,
  Pydantic-Validierung, bei Schemaverletzung Retry mit Fehlermeldung als Feedback.
* Demo-Modus: Replay von Fixtures (data/demo/<projekt>/fixtures/llm/<key>.json); fehlt ein Fixture,
  wird eine deterministische Heuristik verwendet. So läuft die gesamte Pipeline ohne GPU.

Fixture-Format:
  {"samples": [ {...}, {...} ]}                       – explizite Stichproben
  {"base": {...}, "variants": [ {}, {"pfad.feld": wert}, ... ]}  – Basis + Abweichungen je Stichprobe
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from . import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def _set_path(d: dict, path: str, value: Any) -> None:
    keys = path.split(".")
    cur: Any = d
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur.setdefault(k, {})
    last = keys[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def _expand_fixture(fx: dict) -> list[dict]:
    if "samples" in fx:
        return fx["samples"]
    base = fx["base"]
    out = []
    for var in fx.get("variants", [{}]):
        s = copy.deepcopy(base)
        for path, value in var.items():
            _set_path(s, path, value)
        out.append(s)
    return out


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    # Qwen3 thinking-Reste entfernen, falls enable_thinking versehentlich aktiv
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


class LLM:
    def __init__(self, role: str):
        self.role = role
        self.cfg = settings.models()["llm"][role]
        self._client = None

    # ------------------------------------------------------------------ public
    def structured(
        self,
        schema: Type[T],
        messages: list[dict],
        *,
        n: int = 1,
        temperature: Optional[float] = None,
        fixture: Optional[tuple[str, str]] = None,
        fallback: Optional[Callable[[], T]] = None,
    ) -> list[T]:
        """Liefert n validierte Stichproben. fixture = (project_id, key) für den Demo-Modus."""
        if settings.is_demo():
            return self._replay(schema, n, fixture, fallback)
        return self._call(schema, messages, n=n, temperature=temperature)

    # ------------------------------------------------------------------ demo
    def _replay(self, schema: Type[T], n: int, fixture, fallback) -> list[T]:
        if fixture:
            project_id, key = fixture
            path = settings.demo_dir(project_id) / "fixtures" / "llm" / f"{key}.json"
            if path.exists():
                samples = _expand_fixture(json.loads(path.read_text(encoding="utf-8")))
                out = [schema.model_validate(s) for s in samples]
                return (out * n)[:n] if len(out) < n else out[:n]
        if fallback is None:
            raise LLMError(f"Kein Fixture und keine Heuristik für {fixture}")
        return [fallback() for _ in range(n)]

    # ------------------------------------------------------------------ gpu
    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self.cfg["base_url"], api_key=self.cfg.get("api_key", "local"))
        return self._client

    def _call(self, schema: Type[T], messages: list[dict], *, n: int, temperature: Optional[float]) -> list[T]:
        if temperature is None:
            temperature = self.cfg.get("temperature", 0.0) if n == 1 else self.cfg.get("sample_temperature", 0.7)
        json_schema = schema.model_json_schema()
        extra_body: dict[str, Any] = {}
        if "enable_thinking" in self.cfg:
            extra_body["chat_template_kwargs"] = {"enable_thinking": bool(self.cfg["enable_thinking"])}
        results: list[T] = []
        msgs = list(messages)
        attempts = 0
        while len(results) < n and attempts <= self.cfg.get("max_retries", 3):
            attempts += 1
            want = n - len(results)
            try:
                resp = self.client.chat.completions.create(
                    model=self.cfg.get("served_name", self.cfg["model"]),
                    messages=msgs,
                    temperature=temperature,
                    max_tokens=self.cfg.get("max_tokens", 2048),
                    n=want,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": True},
                    },
                    extra_body=extra_body or None,
                )
            except Exception as e:  # noqa: BLE001 – Server ohne n>1 (llama.cpp) → einzeln
                if want > 1 and "n" in str(e):
                    for _ in range(want):
                        results.extend(self._call(schema, messages, n=1, temperature=temperature))
                    return results[:n]
                raise LLMError(str(e)) from e
            errors = []
            for ch in resp.choices:
                raw = _strip_json(ch.message.content or "")
                try:
                    results.append(schema.model_validate_json(raw))
                except ValidationError as ve:
                    errors.append(str(ve)[:800])
            if errors and len(results) < n:
                log.warning("Schema-Verletzung (%s), Retry %d", self.role, attempts)
                msgs = list(messages) + [
                    {"role": "user", "content": "Deine letzte Antwort war ungültig:\n" + errors[0]
                     + "\nAntworte erneut, ausschließlich mit gültigem JSON nach Schema."}
                ]
        if len(results) < n:
            if not results:
                raise LLMError(f"{self.role}: keine gültige Ausgabe nach {attempts} Versuchen")
            results = (results * n)[:n]
        return results


_cache: dict[str, LLM] = {}


def get(role: str) -> LLM:
    if role not in _cache:
        _cache[role] = LLM(role)
    return _cache[role]


def fixture_exists(project_id: str, key: str) -> bool:
    return (settings.demo_dir(project_id) / "fixtures" / "llm" / f"{key}.json").exists()


def fixtures_root(project_id: str) -> Path:
    return settings.demo_dir(project_id) / "fixtures"
