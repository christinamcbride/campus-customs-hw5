"""Settings for the Campus Customs agent team.

The model is fixed. This assignment runs on `gpt-6-luna` through Portkey and
nothing else, so the name is a constant here rather than a setting — there is
no environment variable that can swap it, and `build_model()` refuses any
other name outright.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
PROMPTS_DIR = BACKEND_DIR / "prompts"

#: The only model this project may use. Not configurable on purpose.
MODEL_NAME = "gpt-6-luna"


class AgentUnavailable(RuntimeError):
    """Raised when there is no API key, so no agent can run."""


class Settings(BaseSettings):
    # Later files win. All are optional; a missing file is skipped rather
    # than being an error, so the project still imports without a key.
    model_config = SettingsConfigDict(
        env_file=(
            PROJECT_ROOT / ".env",
            BACKEND_DIR / ".env",
            PROJECT_ROOT / "PORTKEY_API_KEY.env",
            BACKEND_DIR / "PORTKEY_API_KEY.env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Supplied by whoever is running the project. Graders have their own.
    portkey_api_key: str = ""

    #: The Portkey gateway. Every model call in this project goes through it.
    ai_base_url: str = "https://api.portkey.ai/v1"

    @property
    def ai_configured(self) -> bool:
        return bool(self.portkey_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def build_model(model_name: str = MODEL_NAME):
    """The one model every agent uses.

    Cached, so the five agents share a single client rather than opening five.
    """
    if model_name != MODEL_NAME:
        raise ValueError(
            f"This project runs on {MODEL_NAME} only. Refusing to build "
            f"{model_name!r}."
        )

    settings = get_settings()
    if not settings.ai_configured:
        raise AgentUnavailable(
            "PORTKEY_API_KEY is not set, so no agent can run. Put it in "
            "PORTKEY_API_KEY.env at the project root, or export it."
        )

    # Imported here so the module can be read without pydantic-ai installed.
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(
        MODEL_NAME,
        provider=OpenAIProvider(
            base_url=settings.ai_base_url,
            api_key=settings.portkey_api_key.strip(),
        ),
        # The gateway resolves this model to an Azure deployment that rejects
        # function tools on /v1/chat/completions unless reasoning is off --
        # it answers 400 with "Function tools with reasoning_effort are not
        # supported ... set reasoning_effort to 'none'". Every agent here
        # uses tools, so this is required, not a preference.
        settings=OpenAIChatModelSettings(openai_reasoning_effort="none"),
    )
