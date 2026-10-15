"""AI configuration: which provider/model serves which task, with fallbacks and
privacy rules. Stored in the settings table (key ``ai``) and edited in the admin UI.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ModelRole(StrEnum):
    CONVERSATION = "conversation"  # classic pipeline answers
    REASONING = "reasoning"  # complex questions (tool may escalate)
    VISION = "vision"  # image understanding
    MEMORY = "memory"  # memory extraction / consolidation
    TOOL_GENERATION = "tool_generation"  # writing new tools
    BACKGROUND = "background"  # summaries, automation parsing ...
    REALTIME = "realtime"  # native speech-to-speech
    STT = "stt"
    TTS = "tts"
    EMBEDDING = "embedding"


class Locality(StrEnum):
    LOCAL_ONLY = "local_only"  # cloud providers are never used for this role
    PREFER_LOCAL = "prefer_local"  # cloud only as (announced) fallback
    ANY = "any"


class ModelRef(BaseModel):
    provider: str  # registered provider id, e.g. "gemini", "oai:ollama", "faster-whisper"
    model: str = ""
    options: dict[str, Any] = Field(default_factory=dict)  # temperature, voice, ...


class RoleConfig(BaseModel):
    chain: list[ModelRef] = Field(default_factory=list)  # primary first, then fallbacks
    locality: Locality = Locality.ANY
    timeout_s: float = 60.0


class PrivacyPolicy(BaseModel):
    cloud_allowed: bool = True
    camera_images_to_cloud: bool = True
    conversation_audio_to_cloud: bool = True
    personal_memories_to_cloud: bool = True
    announce_cloud_fallback: bool = True


class CostLimits(BaseModel):
    daily_usd: float | None = None
    monthly_usd: float | None = None


class ConversationMode(StrEnum):
    REALTIME = "realtime"
    PIPELINE = "pipeline"


class AISettings(BaseModel):
    assistant_name: str = "Justi"
    default_language: str = "de"
    languages: list[str] = Field(default_factory=lambda: ["de", "it", "en"])
    conversation_mode: ConversationMode = ConversationMode.PIPELINE
    system_prompt: str = ""
    roles: dict[ModelRole, RoleConfig] = Field(default_factory=dict)
    voices: dict[str, str] = Field(default_factory=dict)  # language -> TTS voice id
    privacy: PrivacyPolicy = Field(default_factory=PrivacyPolicy)
    cost_limits: CostLimits = Field(default_factory=CostLimits)

    def role(self, role: ModelRole) -> RoleConfig:
        return self.roles.get(role) or RoleConfig()


def fill_empty_roles(settings: AISettings, available: dict[str, set[str]]) -> bool:
    """Give roles without a provider chain a default from newly available providers.

    ``available`` maps provider kind (llm, realtime) to provider ids. Roles that an
    admin configured are never changed. Returns True if something was filled in.
    """
    defaults = default_ai_settings(has_google_key="gemini" in available.get("llm", set()))
    changed = False
    for role, cfg in defaults.roles.items():
        current = settings.roles.get(role)
        if current is not None and current.chain:
            continue
        usable = [ref for ref in cfg.chain
                  if ref.provider in available.get("realtime" if role == ModelRole.REALTIME else
                                                   {"stt": "stt", "tts": "tts", "embedding": "embedding"}.get(
                                                       role.value, "llm"), set())]
        if usable:
            settings.roles[role] = cfg.model_copy(update={"chain": usable})
            changed = True
            if role == ModelRole.REALTIME and settings.conversation_mode == ConversationMode.PIPELINE:
                settings.conversation_mode = ConversationMode.REALTIME
    return changed


def default_ai_settings(has_google_key: bool = False) -> AISettings:
    """Sensible defaults: everything local; Gemini realtime when a key is configured."""
    roles: dict[ModelRole, RoleConfig] = {
        ModelRole.STT: RoleConfig(chain=[ModelRef(provider="faster-whisper", model="small")],
                                  locality=Locality.PREFER_LOCAL),
        ModelRole.TTS: RoleConfig(chain=[ModelRef(provider="piper")], locality=Locality.PREFER_LOCAL),
        ModelRole.EMBEDDING: RoleConfig(
            chain=[ModelRef(provider="fastembed",
                            model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")],
            locality=Locality.LOCAL_ONLY),
    }
    if has_google_key:
        # Flash-Lite is served from a separate capacity pool: a useful fallback when
        # the primary model is overloaded (HTTP 503).
        llm = [ModelRef(provider="gemini", model="gemini-3.8-flash"),
               ModelRef(provider="gemini", model="gemini-flash-lite-latest")]
        for role in (ModelRole.CONVERSATION, ModelRole.REASONING, ModelRole.VISION,
                     ModelRole.MEMORY, ModelRole.TOOL_GENERATION, ModelRole.BACKGROUND):
            roles[role] = RoleConfig(chain=list(llm))
        roles[ModelRole.REALTIME] = RoleConfig(chain=[ModelRef(provider="gemini", model="gemini-3.8-live")])
    return AISettings(
        conversation_mode=ConversationMode.REALTIME if has_google_key else ConversationMode.PIPELINE,
        roles=roles,
        voices={"de": "de_DE-thorsten-medium", "it": "it_IT-paola-medium",
                "en": "en_US-lessac-medium"},
    )
