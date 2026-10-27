"""Knowledge model.

Status vocabularies (kept as plain strings so the schema stays portable):

Resource.acquisition_status: pending | downloaded | text_collected | metadata_only | failed | duplicate | skipped_limit
Resource.access_status:      public_domain | open_license | open_access | free_to_read | restricted |
                             paid | lending_only | unknown
Resource.processing_status:  pending | extracted | needs_ocr | low_quality | failed | metadata_only
Resource.ai_status:          pending | done | skipped_no_ai | failed | not_applicable
Job.status:                  queued | running | succeeded | failed | dead | cancelled
ResearchQuestion.status:     open | investigating | answered | unresolved | duplicate |
                             not_relevant | deferred
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow

PILLARS = ("children", "parents", "murabbi")


class Source(Base):
    """A configured collector instance (adapter + its configuration)."""

    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True)
    adapter: Mapped[str] = mapped_column(String(60), index=True)
    name: Mapped[str] = mapped_column(String(300))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schedule_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=20)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    health: Mapped[str] = mapped_column(String(40), default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text)
    items_collected: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # cursors persisted across runs
    last_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Resource(Base):
    __tablename__ = "resources"
    # one record per canonical URL / DOI, enforced by the database even under concurrent collectors
    __table_args__ = (
        Index("uq_resources_canonical_url", "canonical_url", unique=True,
              sqlite_where=text("canonical_url IS NOT NULL"), postgresql_where=text("canonical_url IS NOT NULL")),
        Index("uq_resources_doi", "doi", unique=True,
              sqlite_where=text("doi IS NOT NULL"), postgresql_where=text("doi IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(40), index=True, default="other")
    title: Mapped[str] = mapped_column(Text)
    alt_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    title_translations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    authors_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(12), index=True)
    published_date: Mapped[str | None] = mapped_column(String(32))
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    publisher: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    download_url: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), index=True)
    source_key: Mapped[str | None] = mapped_column(String(120), index=True)
    external_id: Mapped[str | None] = mapped_column(String(300), index=True)
    doi: Mapped[str | None] = mapped_column(String(200))
    isbn: Mapped[str | None] = mapped_column(String(40), index=True)
    collection_method: Mapped[str | None] = mapped_column(String(40))
    # licensing / access
    license: Mapped[str | None] = mapped_column(String(200))
    license_url: Mapped[str | None] = mapped_column(Text)
    access_status: Mapped[str] = mapped_column(String(30), default="unknown", index=True)
    download_permitted: Mapped[bool] = mapped_column(Boolean, default=False)
    permission_basis: Mapped[str | None] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(String(60))
    currency: Mapped[str | None] = mapped_column(String(10))
    purchase_url: Mapped[str | None] = mapped_column(Text)
    # local file
    local_path: Mapped[str | None] = mapped_column(Text)
    file_mime: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    title_key: Mapped[str | None] = mapped_column(String(300), index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id"))
    # statuses
    acquisition_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    processing_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    index_status: Mapped[str] = mapped_column(String(30), default="pending")
    ai_status: Mapped[str] = mapped_column(String(30), default="pending")
    extraction_method: Mapped[str | None] = mapped_column(String(60))
    extraction_quality: Mapped[float | None] = mapped_column(Float)
    page_count: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int | None] = mapped_column(Integer)
    text_path: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)  # AI-generated, never mixed with source text
    summary_lang: Mapped[str | None] = mapped_column(String(12))
    evidence_category: Mapped[str | None] = mapped_column(String(40))
    quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    discovered_by_question_id: Mapped[int | None] = mapped_column(Integer)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    pillars: Mapped[list["ResourcePillar"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan", order_by="Chunk.seq"
    )


class ResourcePillar(Base):
    __tablename__ = "resource_pillars"
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    pillar: Mapped[str] = mapped_column(String(20), primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(20), default="rules")
    resource: Mapped[Resource] = relationship(back_populates="pillars")


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name_en: Mapped[str] = mapped_column(String(200))
    name_ar: Mapped[str] = mapped_column(String(200))
    pillar: Mapped[str | None] = mapped_column(String(20))
    keywords_en: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords_ar: Mapped[list[str]] = mapped_column(JSON, default=list)


class ResourceTopic(Base):
    __tablename__ = "resource_topics"
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(20), default="rules")


class GlossaryTerm(Base):
    """Arabic <-> English terminology mapping used for bilingual query expansion."""

    __tablename__ = "glossary"
    id: Mapped[int] = mapped_column(primary_key=True)
    concept_key: Mapped[str] = mapped_column(String(120), unique=True)
    terms_en: Mapped[list[str]] = mapped_column(JSON, default=list)
    terms_ar: Mapped[list[str]] = mapped_column(JSON, default=list)
    transliterations: Mapped[list[str]] = mapped_column(JSON, default=list)
    pillar: Mapped[str | None] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(20), default="seed")  # seed | user | ai


class Chunk(Base):
    """A passage of extracted source text (original language, never translated)."""

    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String(12))
    timestamp_start: Mapped[float | None] = mapped_column(Float)  # transcripts
    resource: Mapped[Resource] = relationship(back_populates="chunks")


class Embedding(Base):
    __tablename__ = "embeddings"
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id"), primary_key=True)
    model: Mapped[str] = mapped_column(String(80), primary_key=True)
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)


class Entity(Base):
    """People, organizations, programs, courses, concepts, events, channels."""

    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("entity_type", "norm_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(Text)
    name_ar: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    norm_key: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    pillars: Mapped[list[str]] = mapped_column(JSON, default=list)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(20), default="metadata")  # metadata | ai | user
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ResourceEntity(Base):
    __tablename__ = "resource_entities"
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(30), primary_key=True)  # author|publisher|mentions|channel|subject


class Relation(Base):
    """Generic knowledge-graph edge between any two records."""

    __tablename__ = "relations"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_kind: Mapped[str] = mapped_column(String(20))
    from_id: Mapped[int] = mapped_column(Integer)
    rel_type: Mapped[str] = mapped_column(String(40))
    to_kind: Mapped[str] = mapped_column(String(20))
    to_id: Mapped[int] = mapped_column(Integer)
    evidence_chunk_id: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(20), default="rules")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (
        Index("ix_rel_from", "from_kind", "from_id"),
        Index("ix_rel_to", "to_kind", "to_id"),
    )


class Claim(Base):
    """A statement extracted from a source. `quote` is verbatim source text; `statement`
    is the system's paraphrase and is always marked as generated."""

    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id"))
    claim_type: Mapped[str] = mapped_column(String(30))
    statement: Mapped[str] = mapped_column(Text)
    statement_lang: Mapped[str | None] = mapped_column(String(12))
    quote: Mapped[str | None] = mapped_column(Text)
    quote_lang: Mapped[str | None] = mapped_column(String(12))
    page: Mapped[int | None] = mapped_column(Integer)
    evidence_type: Mapped[str | None] = mapped_column(String(30))
    age_group: Mapped[str | None] = mapped_column(String(60))
    pillars: Mapped[list[str]] = mapped_column(JSON, default=list)
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    qa_status: Mapped[str] = mapped_column(String(20), default="pending")
    generated_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Citation(Base):
    __tablename__ = "citations"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    raw: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(200), index=True)
    external_id: Mapped[str | None] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer)
    cited_resource_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id"))
    status: Mapped[str] = mapped_column(String(20), default="uncollected")


class ResearchObjective(Base):
    __tablename__ = "objectives"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    pillars: Mapped[list[str]] = mapped_column(JSON, default=list)
    priority: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="active")
    planned_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResearchQuestion(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    objective_id: Mapped[int | None] = mapped_column(ForeignKey("objectives.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"))
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(12), default="en")
    text_alt: Mapped[str | None] = mapped_column(Text)  # same question in the other language
    rationale: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="planner")
    pillars: Mapped[list[str]] = mapped_column(JSON, default=list)
    priority: Mapped[float] = mapped_column(Float, default=0.5, index=True)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    search_queries: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    related_resource_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    next_steps: Mapped[str | None] = mapped_column(Text)
    answer_summary: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(300), index=True)
    created_by: Mapped[str] = mapped_column(String(40), default="rules")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    investigated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(12), default="en")
    finding_type: Mapped[str] = mapped_column(String(30))  # supported|contested|gap|insufficient
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    qa_status: Mapped[str] = mapped_column(String(20), default="pending")
    qa_notes: Mapped[str | None] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SearchLog(Base):
    __tablename__ = "search_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    adapter: Mapped[str] = mapped_column(String(60), index=True)
    query: Mapped[str] = mapped_column(Text)
    query_key: Mapped[str] = mapped_column(String(300), index=True)
    lang: Mapped[str | None] = mapped_column(String(12))
    question_id: Mapped[int | None] = mapped_column(Integer)
    results: Mapped[int] = mapped_column(Integer, default=0)
    new_resources: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class CrawlUrl(Base):
    """Frontier + history for the web crawler (enables incremental re-crawls)."""

    __tablename__ = "crawl_urls"
    __table_args__ = (UniqueConstraint("source_id", "url_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    url_key: Mapped[str] = mapped_column(String(64))
    depth: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[int | None] = mapped_column(Integer)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)  # lower runs first
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    worker_id: Mapped[str | None] = mapped_column(String(80))
    dedupe_key: Mapped[str | None] = mapped_column(String(300), index=True)
    group: Mapped[str | None] = mapped_column(String(60), index=True)  # collector key, for pause
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class AgentRun(Base):
    """Audit log of agent actions."""

    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(80))
    job_id: Mapped[int | None] = mapped_column(Integer)
    question_id: Mapped[int | None] = mapped_column(Integer)
    resource_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    detail: Mapped[str | None] = mapped_column(Text)
    ai_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    ai_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class UsageCounter(Base):
    __tablename__ = "usage_counters"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)


class DailyReport(Base):
    __tablename__ = "daily_reports"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text)
    finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Output(Base):
    __tablename__ = "outputs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(12), default="en")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content: Mapped[str | None] = mapped_column(Text)
    resource_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    generated_by: Mapped[str] = mapped_column(String(80), default="rules")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
