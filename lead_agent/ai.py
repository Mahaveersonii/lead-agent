"""Shared Claude API helper: one prompt in, one JSON object out (checked against a schema by the API)."""
from __future__ import annotations

import json
import os

import anthropic

_client = None


class AIUnavailable(RuntimeError):
    """The Claude API can't be used right now (no key, wrong key, no credit, or no internet)."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise AIUnavailable("ANTHROPIC_API_KEY is missing in .env")
        _client = anthropic.Anthropic(max_retries=4, timeout=120)  # the SDK retries network drops, 429 and 5xx
    return _client


def ask_json(prompt: str, schema: dict, cfg: dict) -> dict:
    """Send the prompt to Claude and return the JSON reply as a dict."""
    settings = cfg["ai"]
    try:
        response = _get_client().messages.create(
            model=settings["model"],
            max_tokens=settings["max_tokens"],
            output_config={"effort": settings["effort"],
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise AIUnavailable("the Claude API key in .env is wrong or was deleted")
    except anthropic.PermissionDeniedError:
        raise AIUnavailable("the Claude API key is not allowed to use this model")
    except anthropic.BadRequestError as error:
        if "credit" in str(error).lower():
            raise AIUnavailable("the Claude account is out of credit. Top up at platform.claude.com -> Billing")
        raise
    except anthropic.APIConnectionError:
        raise AIUnavailable("could not reach the Claude API. Check the internet connection")
    if response.stop_reason == "refusal":
        raise ValueError("Claude declined to answer for this lead")
    text = next((block.text for block in response.content if block.type == "text"), "")
    if not text:
        raise ValueError(f"empty AI reply (stop reason: {response.stop_reason})")
    return json.loads(text)


def check_access(cfg: dict) -> str:
    """Tiny test call used by the setup check and the run pre-check."""
    ask_json('Reply with JSON {"ok": true}.',
             {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False},
             cfg)
    return f"key works, model {cfg['ai']['model']}"
