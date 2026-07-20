"""Celonis AI Gateway chat client for enrichment tasks.

The gateway (``https://ai.celonis.dev``) is an OpenAI-compatible proxy that
serves chat models only (no embeddings). We use it to enrich documents:
re-extract clean bibliographic metadata (title/authors/year/venue) and to pull
keywords/concepts from a paper's opening text — the heuristic parser leaves many
docs with garbage titles ("Unknown - main.dvi.pdf").

Auth: a virtual key from ``celai get api-key`` (or ``CELONIS_AI_GATEWAY_API_KEY``).
LLM enrichment is always optional — callers must degrade gracefully when the
gateway is unreachable (offline, no VPN, no token).
"""

from __future__ import annotations

import json
import re
import subprocess
import time

from . import config


class GatewayError(RuntimeError):
    pass


def _get_token() -> str:
    if config.GATEWAY_API_KEY:
        return config.GATEWAY_API_KEY
    try:
        out = subprocess.run(
            ["celai", "get", "api-key"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise GatewayError(f"could not run 'celai get api-key': {exc}") from exc
    token = (out.stdout or "").strip().splitlines()[-1].strip() if out.stdout else ""
    if not token:
        raise GatewayError(f"'celai get api-key' returned no token (stderr: {out.stderr.strip()})")
    return token


class ChatClient:
    def __init__(self, model: str | None = None, base_url: str | None = None):
        import requests

        self._requests = requests
        self.base_url = (base_url or config.CHAT_BASE_URL).rstrip("/")
        self.model = model or config.CHAT_MODEL
        self._token: str | None = None

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = _get_token()
        return self._token

    def chat(self, messages: list[dict], temperature: float = 0.0,
             max_tokens: int = 1024) -> str:
        url = self.base_url + config.CHAT_PATH
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        last_err = None
        for attempt in range(4):
            try:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                }
                resp = self._requests.post(url, json=payload, headers=headers, timeout=120)
                if resp.status_code in (401, 403):  # token may have expired
                    self._token = None
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(min(2 ** attempt, 20))
        raise GatewayError(f"chat request failed after retries: {last_err}")

    def json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        """Chat and parse a JSON object from the reply (tolerant of code fences)."""
        content = self.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        return _parse_json(content)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)  # first {...} block
        if not m:
            raise
        obj = json.loads(m.group(0))
    return obj if isinstance(obj, dict) else {}


def available() -> bool:
    """Cheap check: can we obtain a token at all?"""
    try:
        _get_token()
        return True
    except GatewayError:
        return False
