"""
gemini_service.py
=================
Thin wrapper around the official Google Gemini SDK (`google-genai`).

Configuration is read ENTIRELY from the environment (loaded from a local
`.env` file via python-dotenv). No API key or model id is ever hard-coded in
source. See `.env.example` for every supported variable.

Responsibilities
----------------
* Load `.env` and read the GEMINI_API_KEY, failing loudly if absent.
* Enforce the ArthaLab educational system prompt on every call.
* Try an ordered chain of models (primary -> fallbacks) from the environment.
* Never fabricate returns; the model is instructed to frame everything as a
  user-configured hypothetical, not advice.

This module raises typed exceptions so the UI can render friendly messages
instead of stack traces.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Load .env into the process environment as early as possible. python-dotenv
# is optional: if it is not installed we silently fall back to whatever is
# already exported in the shell.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover - env dependent
    pass


# ---------------------------------------------------------------------------
# Environment-driven configuration
# ---------------------------------------------------------------------------

# Sensible, verified defaults. Override any of these in `.env` WITHOUT touching
# code. If your Google account exposes newer model ids (e.g. a gemini-3.x
# family), just set GEMINI_MODELS in `.env` — no code change required.
DEFAULT_PRIMARY_MODEL = "gemini-2.5-flash"
DEFAULT_FALLBACK_MODEL = "gemini-2.5-pro"
DEFAULT_TEMPERATURE = 0.4


def _model_chain() -> list[str]:
    """
    Resolve the ordered list of models to try.

    Priority:
      1. GEMINI_MODELS = comma-separated list (highest priority, full control).
      2. GEMINI_PRIMARY_MODEL + GEMINI_FALLBACK_MODEL (pair).
      3. Built-in verified defaults.
    Duplicates and blanks are removed while preserving order.
    """
    raw = os.environ.get("GEMINI_MODELS", "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
    else:
        models = [
            os.environ.get("GEMINI_PRIMARY_MODEL", DEFAULT_PRIMARY_MODEL).strip(),
            os.environ.get("GEMINI_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL).strip(),
        ]
    seen, ordered = set(), []
    for m in models:
        if m and m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered or [DEFAULT_PRIMARY_MODEL]


def _temperature() -> float:
    try:
        return float(os.environ.get("GEMINI_TEMPERATURE", DEFAULT_TEMPERATURE))
    except ValueError:
        return DEFAULT_TEMPERATURE


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
    """Raised when every model in the chain fails."""


@dataclass
class GeminiResponse:
    text: str
    model_used: str
    fell_back: bool          # True if a non-primary model produced the answer


def _require_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiConfigError(
            "GEMINI_API_KEY is not set.\n"
            "Create a `.env` file next to app.py (copy `.env.example`) with:\n"
            "  GEMINI_API_KEY=your-key-here\n"
            "…or export it in your shell. Get a key at "
            "https://aistudio.google.com/apikey ."
        )
    return key


class GeminiService:
    """
    Lazily-initialised Gemini client. Construct once and reuse.

    All configuration (key, models, temperature) is read from the environment
    at construction time. Pass overrides only for testing.

    Usage
    -----
    >>> svc = GeminiService()          # raises GeminiConfigError if unusable
    >>> resp = svc.explain_scenario(scenario_summary)
    >>> print(resp.text, "via", resp.model_used)
    """

    def __init__(self, api_key: Optional[str] = None,
                 models: Optional[list[str]] = None,
                 temperature: Optional[float] = None):
        self._api_key = api_key or _require_api_key()
        self._models = models or _model_chain()
        self._temperature = temperature if temperature is not None else _temperature()
        self._client = self._make_client()

    @property
    def models(self) -> list[str]:
        """The ordered model chain this service will try."""
        return list(self._models)

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

    def _generate_one(self, model: str, user_prompt: str,
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
                 temperature: Optional[float] = None) -> GeminiResponse:
        """
        Try each model in the chain in order; return the first success.
        Raises GeminiCallError only if every model fails.
        """
        temp = temperature if temperature is not None else self._temperature
        errors = []
        for idx, model in enumerate(self._models):
            try:
                text = self._generate_one(model, user_prompt, temp)
                return GeminiResponse(text=text, model_used=model,
                                      fell_back=(idx > 0))
            except Exception as exc:  # noqa: BLE001 - want to try the next model
                errors.append(f"{model}: {exc}")
        raise GeminiCallError(
            "All models in the chain failed. " + " | ".join(errors)
        )

    def explain_scenario(self, scenario_summary: str) -> GeminiResponse:
        """
        Ask the model to explain the mechanics/tax/risk of a user-built
        scenario. `scenario_summary` is a plain-text dump of the numbers the
        math engine produced.
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
