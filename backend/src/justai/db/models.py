"""ORM models for all modules.

The schema is kept in one module so that Alembic sees one consistent metadata and
so that relations between modules are explicit. Flexible, evolving data lives in
JSONB columns (validated by pydantic models in the owning module); data that is
queried or joined on is stored in typed columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from justai_sdk.events import new_id
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from justai.db.base import Base, TimestampMixin

FACE_EMBEDDING_DIM = 128  # OpenCV SFace
VOICE_EMBEDDING_DIM = 256  # WeSpeaker ResNet34
MEMORY_EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2


def _id(prefix: str) -> Any:
    return mapped_column(String(64), primary_key=True, default=lambda: new_id(prefix))


def _jsonb(nullable: bool = False) -> Any:
    return mapped_column(JSONB, nullable=nullable, default=dict, server_default="{}")


def _jsonb_list() -> Any:
    return mapped_column(JSONB, nullable=False, default=list, server_default="[]")


def _ts(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


# ----------------------------------------------------------------- system / auth


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = _id("user")
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="resident")  # admin|resident|guest
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL"), nullable=True
    )
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = _ts()


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Secret(Base):
    __tablename__ = "secrets"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = _id("audit")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(128))  # user:<id> | assistant | system | plugin:<id>
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detail: Mapped[dict[str, Any]] = _jsonb()

    __table_args__ = (Index("ix_audit_ts", "ts"),)


class Job(Base):
    """Durable job queue (SELECT ... FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "jobs"

    id: Mapped[str] = _id("job")
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = _jsonb()
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|failed
    priority: Mapped[int] = mapped_column(Integer, default=1)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    locked_at: Mapped[datetime | None] = _ts()
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = _ts()

    __table_args__ = (
        Index("ix_jobs_pending", "status", "run_at", "priority"),
        Index(
            "uq_jobs_dedup_active",
            "dedup_key",
            unique=True,
            postgresql_where="dedup_key IS NOT NULL AND status IN ('pending','running')",
        ),
    )


# ------------------------------------------------------------ rooms / devices


class Room(TimestampMixin, Base):
    __tablename__ = "rooms"

    id: Mapped[str] = _id("room")
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    floor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    layout: Mapped[dict[str, Any]] = _jsonb()  # position on the floor-plan view
    policy: Mapped[dict[str, Any]] = _jsonb()  # e.g. shared display privacy, vision allowed


class Device(TimestampMixin, Base):
    __tablename__ = "devices"

    id: Mapped[str] = _id("dev")
    name: Mapped[str] = mapped_column(String(128))
    driver_id: Mapped[str] = mapped_column(String(128))
    room_id: Mapped[str | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = _jsonb()  # non-secret driver config
    settings: Mapped[dict[str, Any]] = _jsonb()  # vision/privacy/ptz/audio settings
    capabilities: Mapped[list[Any]] = _jsonb_list()  # last probed capabilities
    info: Mapped[dict[str, Any]] = _jsonb()
    status: Mapped[str] = mapped_column(String(16), default="unknown")
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = _ts()
    fingerprint: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)


class InteractionEndpoint(TimestampMixin, Base):
    __tablename__ = "interaction_endpoints"

    id: Mapped[str] = _id("ep")
    name: Mapped[str] = mapped_column(String(128))
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    arbitration_group: Mapped[str] = mapped_column(String(64), default="default")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    config: Mapped[dict[str, Any]] = _jsonb()  # wakeword, audio, conversation (pydantic model)


class EndpointDevice(Base):
    __tablename__ = "endpoint_devices"

    endpoint_id: Mapped[str] = mapped_column(
        ForeignKey("interaction_endpoints.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), primary_key=True)  # mic|camera|speaker|display
    priority: Mapped[int] = mapped_column(Integer, default=0)


# ------------------------------------------------------------- conversations


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = _id("sess")
    endpoint_id: Mapped[str | None] = mapped_column(
        ForeignKey("interaction_endpoints.id", ondelete="SET NULL"), nullable=True
    )
    room_id: Mapped[str | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL"), nullable=True
    )
    trigger: Mapped[str] = mapped_column(String(32))  # wakeword|automation|manual|text
    mode: Mapped[str] = mapped_column(String(16))  # realtime|pipeline
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = _ts()
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict[str, Any]] = _jsonb()
    memory_processed: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_sessions_started", "started_at"),)


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"

    id: Mapped[str] = _id("turn")
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user|assistant|tool|system
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    meta: Mapped[dict[str, Any]] = _jsonb()


# ------------------------------------------------------------------- events


class StoredEvent(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, default=1)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[dict[str, Any]] = _jsonb()
    payload: Mapped[dict[str, Any]] = _jsonb()
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hop: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    sensitivity: Mapped[str] = mapped_column(String(16), default="normal")

    __table_args__ = (
        Index("ix_events_type_ts", "type", "ts"),
        Index("ix_events_room_ts", "room_id", "ts"),
        Index("ix_events_correlation", "correlation_id"),
    )


# --------------------------------------------------------------- automations


class Automation(TimestampMixin, Base):
    __tablename__ = "automations"

    id: Mapped[str] = _id("auto")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    definition: Mapped[dict[str, Any]] = _jsonb()  # trigger, conditions, actions, options
    created_by: Mapped[str] = mapped_column(String(64), default="admin")  # admin|assistant|plugin
    owner_person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL"), nullable=True
    )
    origin: Mapped[dict[str, Any]] = _jsonb()  # e.g. session/utterance it was created from
    state: Mapped[dict[str, Any]] = _jsonb()  # run_count, last_run_at, cooldown_until
    revision: Mapped[int] = mapped_column(Integer, default=1)


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = _id("run")
    automation_id: Mapped[str] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = _ts()
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[list[Any]] = _jsonb_list()


# ------------------------------------------------------------------ identity


class Person(TimestampMixin, Base):
    __tablename__ = "people"

    id: Mapped[str] = _id("person")
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default="person")  # person|pet
    species: Mapped[str | None] = mapped_column(String(64), nullable=True)  # for pets: dog, cat
    notes: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict[str, Any]] = _jsonb()  # language, voice, preferences
    biometric_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    biometric_consent_at: Mapped[datetime | None] = _ts()
    recognition_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    merged_into: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[str] = _id("consent")
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # face|voice|memory|cloud
    granted: Mapped[bool] = mapped_column(Boolean)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    evidence: Mapped[dict[str, Any]] = _jsonb()  # session id, utterance, admin user


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id: Mapped[str] = _id("face")
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(FACE_EMBEDDING_DIM))
    quality: Mapped[dict[str, Any]] = _jsonb()
    source: Mapped[str] = mapped_column(String(32), default="enrollment")
    thumbnail: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceEmbedding(Base):
    """Voice profile sample of a person (only with consent kind "voice")."""

    __tablename__ = "voice_embeddings"

    id: Mapped[str] = _id("voice")
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(VOICE_EMBEDDING_DIM))
    seconds: Mapped[float] = mapped_column(Float, default=0.0)  # speech used for this sample
    source: Mapped[str] = mapped_column(String(32), default="enrollment")
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# -------------------------------------------------------------------- memory


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = _id("mem")
    kind: Mapped[str] = mapped_column(String(16))  # fact|episode|preference|procedure|note
    scope: Mapped[str] = mapped_column(String(16), default="private")  # private|room|shared|system
    owner_person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), nullable=True, index=True
    )
    room_id: Mapped[str | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(256), nullable=True)
    predicate: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    value: Mapped[dict[str, Any]] = _jsonb()
    provenance: Mapped[str] = mapped_column(String(16))  # confirmed|extracted|observed|inferred
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[dict[str, Any]] = _jsonb()
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(MEMORY_EMBEDDING_DIM), nullable=True
    )
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|superseded
    superseded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_until: Mapped[datetime | None] = _ts()
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_memories_subject_predicate", "subject", "predicate"),
        Index(
            "ix_memories_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


# -------------------------------------------------------------------- vision


class Sighting(Base):
    """Durable summary of a tracked object/person (not every frame)."""

    __tablename__ = "sightings"

    id: Mapped[str] = _id("sight")
    camera_device_id: Mapped[str] = mapped_column(String(64), index=True)
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(64))
    person_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    track_id: Mapped[str] = mapped_column(String(64))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    best_score: Mapped[float] = mapped_column(Float)
    identity_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta: Mapped[dict[str, Any]] = _jsonb()

    __table_args__ = (Index("ix_sightings_label_last", "label", "last_seen"),)


class VisionWatch(TimestampMixin, Base):
    """Dynamic analysis task (e.g. 'tell me when a car appears in the driveway')."""

    __tablename__ = "vision_watches"

    id: Mapped[str] = _id("watch")
    name: Mapped[str] = mapped_column(String(200))
    camera_device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    spec: Mapped[dict[str, Any]] = _jsonb()  # labels, zone, min_score, dwell, kind
    created_by: Mapped[str] = mapped_column(String(64), default="admin")
    expires_at: Mapped[datetime | None] = _ts()
    state: Mapped[dict[str, Any]] = _jsonb()


# ------------------------------------------------------------------- plugins


class InstalledPlugin(TimestampMixin, Base):
    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16))  # builtin|uploaded|generated
    path: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = _jsonb()
    granted_permissions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    manifest: Mapped[dict[str, Any]] = _jsonb()
    status: Mapped[str] = mapped_column(String(16), default="installed")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PluginDocument(Base):
    __tablename__ = "plugin_documents"

    plugin_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------- tools


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = _id("exec")
    tool: Mapped[str] = mapped_column(String(128), index=True)
    plugin_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin: Mapped[str] = mapped_column(String(16))
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    params: Mapped[dict[str, Any]] = _jsonb()
    status: Mapped[str] = mapped_column(String(24))  # ok|error|denied|timeout|needs_confirmation
    result: Mapped[dict[str, Any]] = _jsonb()
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_tool_exec_created", "created_at"),)


class ToolProject(TimestampMixin, Base):
    """A capability the assistant is developing (generated tool plugin)."""

    __tablename__ = "tool_projects"

    id: Mapped[str] = _id("tproj")
    plugin_id: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    active_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[dict[str, Any]] = _jsonb()


class ToolVersion(Base):
    __tablename__ = "tool_versions"

    id: Mapped[str] = _id("tver")
    project_id: Mapped[str] = mapped_column(
        ForeignKey("tool_projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict[str, Any]] = _jsonb()
    manifest: Mapped[dict[str, Any]] = _jsonb()
    code: Mapped[str] = mapped_column(Text)
    tests: Mapped[str] = mapped_column(Text)
    validation: Mapped[dict[str, Any]] = _jsonb()  # static, tests, review results
    status: Mapped[str] = mapped_column(String(24), default="draft")
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("project_id", "version"),)


# ------------------------------------------------------------------ displays


class Presentation(Base):
    __tablename__ = "presentations"

    id: Mapped[str] = _id("pres")
    display_device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document: Mapped[dict[str, Any]] = _jsonb()
    status: Mapped[str] = mapped_column(String(16), default="created")
    sensitivity: Mapped[str] = mapped_column(String(16), default="normal")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = _ts()
    displayed_at: Mapped[datetime | None] = _ts()
    updated_at: Mapped[datetime | None] = _ts()
    closed_at: Mapped[datetime | None] = _ts()
    expires_at: Mapped[datetime | None] = _ts()


# ------------------------------------------------------------------- AI usage


class AIUsage(Base):
    """Daily aggregated usage/cost per provider, model and role."""

    __tablename__ = "ai_usage"

    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    audio_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms_total: Mapped[int] = mapped_column(Integer, default=0)
