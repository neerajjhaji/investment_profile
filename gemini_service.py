"""
gemini_service.py
=================
Thin wrapper around the official Google Gemini SDK (`google-genai`).

Responsibilities
----------------
* Load and validate the GEMINI_API_KEY, failing loudly and clearly if absent.
* Enforce the ArthaLab educational system prompt on every call.
* Use `gemini-2.5-flash` with an automatic fallback to `gemini-2.5-pro`.
* Never fabricate returns; the model is instructed to frame everything as a
  user-configured hypothetical, not advice.

This module raises typed exceptions so the UI can render friendly messages
instead of stack traces.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# The SDK is imported lazily inside the client so the rest of the app (and the
# math engine / tests) can run even if `google-genai` is not installed.


PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-2.5-pro"

SYSTEM_PROMPT = (
    "You are ArthaLab AI, an educational financial knowledge engine for "
    "Indian markets. Explain financial mechanics, taxation, liquidity "
    "constraints, and sequence-of-returns risk plainly. Never guarantee "
    "market-linked returns. Always highlight statutory limits (POMIS, SCSS) "
    "and tax slab impacts. Frame all allocations as user-configured "
    "hypothetical simulations, not investment recommendations. You are not a "
    "SEBI Registered Investment Adviser; do not tell the user what to buy. "
    "When numbers are involved, explain what drives them and what could make "
    "them wrong. Close substantive answers with a short list of questions the "
    "user should put to a SEBI-registered adviser."
)


class GeminiConfigError(RuntimeError):
    """Raised when the API key or SDK is missing/misconfigured."""


class GeminiCallError(RuntimeError):
    """Raised when both primary and fallback model calls fail."""


@dataclass
class GeminiResponse:
    text: str
    model_used: str
    fell_back: bool


def _require_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiConfigError(
            "GEMINI_API_KEY is not set. Export it before launching:\n"
            "  export GEMINI_API_KEY='your-key'      # macOS/Linux\n"
            "  setx GEMINI_API_KEY \"your-key\"          # Windows (new shell)\n"
            "Get a key from https://aistudio.google.com/apikey ."
        )
    return key


class GeminiService:
    """
    Lazily-initialised Gemini client. Construct once and reuse.

    Usage
    -----
    >>> svc = GeminiService()          # raises GeminiConfigError if unusable
    >>> resp = svc.explain_scenario(scenario_summary)
    >>> print(resp.text)
    """

    def __init__(self, api_key: Optional[str] = None,
                 primary_model: str = PRIMARY_MODEL,
                 fallback_model: str = FALLBACK_MODEL):
        self._api_key = api_key or _require_api_key()
        self._primary = primary_model
        self._fallback = fallback_model
        self._client = self._make_client()

    def _make_client(self):
        try:
            from google import genai  # noqa: WPS433 (intentional lazy import)
        except ImportError as exc:  # pragma: no cover - env dependent
            raise GeminiConfigError(
                "The `google-genai` package is not installed. Run:\n"
                "  pip install google-genai"
            ) from exc
        try:
            return genai.Client(api_key=self._api_key)
        except Exception as exc:  # pragma: no cover - network/SDK dependent
            raise GeminiConfigError(
                f"Failed to initialise the Gemini client: {exc}"
            ) from exc

    # -- internal single-model call -------------------------------------

    def _generate(self, model: str, user_prompt: str,
                  temperature: float) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=temperature,
        )
        result = self._client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=config,
        )
        text = getattr(result, "text", None)
        if not text:
            raise GeminiCallError(f"Model {model} returned an empty response.")
        return text.strip()

    # -- public API ------------------------------------------------------

    def generate(self, user_prompt: str,
                 temperature: float = 0.4) -> GeminiResponse:
        """
        Call the primary model, falling back to the secondary on any error.
        Raises GeminiCallError only if both fail.
        """
        try:
            text = self._generate(self._primary, user_prompt, temperature)
            return GeminiResponse(text=text, model_used=self._primary,
                                  fell_back=False)
        except Exception as primary_exc:  # noqa: BLE001 - want broad fallback
            try:
                text = self._generate(self._fallback, user_prompt, temperature)
                return GeminiResponse(text=text, model_used=self._fallback,
                                      fell_back=True)
            except Exception as fallback_exc:  # noqa: BLE001
                raise GeminiCallError(
                    f"Both models failed. Primary ({self._primary}): "
                    f"{primary_exc}. Fallback ({self._fallback}): "
                    f"{fallback_exc}."
                ) from fallback_exc

    def explain_scenario(self, scenario_summary: str) -> GeminiResponse:
        """
        Ask the model to explain the mechanics/tax/risk of a user-built
        scenario. `scenario_summary` should be a plain-text dump of the
        numbers the math engine produced.
        """
        prompt = (
            "A user has configured the following HYPOTHETICAL scenario in an "
            "educational simulator. Do not recommend actions. Explain, in "
            "clear sections:\n"
            "1. How each instrument works and its statutory limits.\n"
            "2. The tax treatment of each cash flow at the stated slab.\n"
            "3. Why the SWP figure is not 'income' and how "
            "sequence-of-returns risk applies here.\n"
            "4. The key trade-offs between the buckets.\n"
            "5. Specific questions to ask a SEBI-registered adviser.\n\n"
            "Scenario data:\n"
            f"{scenario_summary}\n"
        )
        return self.generate(prompt)


def get_service_or_error() -> tuple[Optional[GeminiService], Optional[str]]:
    """
    Convenience for the UI: returns (service, None) on success or
    (None, error_message) if the service cannot be constructed. Never raises.
    """
    try:
        return GeminiService(), None
    except GeminiConfigError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - defensive for the UI layer
        return None, f"Unexpected error initialising Gemini: {exc}"
