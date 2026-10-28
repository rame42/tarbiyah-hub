"""Structured outputs requested from Claude. Passage ids refer to <passage id=".."> tags in the prompt."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Pillar = Literal["children", "parents", "murabbi"]
EvidenceCategory = Literal[
    "scriptural_source", "classical_scholarship", "contemporary_scholarship", "empirical_research",
    "practical_guidance", "curriculum_or_training_material", "institutional_information",
    "opinion_or_commentary", "promotional", "news", "other",
]


class ClaimOut(BaseModel):
    claim_type: Literal["finding", "recommendation", "definition", "method", "textual_evidence", "opinion",
                        "historical", "limitation"]
    statement: str = Field(description="Faithful paraphrase of what the SOURCE says (not your opinion).")
    quote: str = Field(description="Exact verbatim excerpt from the passage supporting the statement, in the "
                                   "source language. Empty string if no short exact quote is possible.")
    passage_id: int
    evidence_type: Literal["empirical", "scriptural", "scholarly_opinion", "practice", "anecdotal", "unspecified"]
    age_group: str = Field(description="e.g. '0-2', '3-6', '7-12', '13-18', 'adults', or '' if not stated")
    pillars: list[Pillar]


class NamedThing(BaseModel):
    name: str
    name_other_language: str = Field(description="Name in the other language (Arabic/English) if known, else ''")
    kind: str = Field(description="person: author|scholar|researcher|educator|other; organization: school|university|"
                                  "research_center|ngo|mosque|publisher|program|government|other; concept: concept")
    description: str = ""
    passage_id: int = 0


class CitedWork(BaseModel):
    title: str
    author: str = ""
    year: str = ""


class RelationOut(BaseModel):
    subject: str
    relation: Literal["supports", "contradicts", "part_of", "method_for", "applies_to", "defined_as",
                      "related_to", "authored_by", "affiliated_with", "cites"]
    object: str
    passage_id: int = 0


class KnowledgeExtraction(BaseModel):
    summary: str = Field(description="3-6 sentence summary of the source, in the requested summary language.")
    title_translation: str = Field(description="Title translated into the other primary language (Arabic<->English)."
                                               " Mark nothing; this is stored as a machine translation.")
    pillars: list[Pillar]
    topics: list[str] = Field(description="Short topic labels in English")
    evidence_category: EvidenceCategory
    target_audience: str
    age_groups: list[str]
    claims: list[ClaimOut]
    concepts: list[NamedThing]
    people: list[NamedThing]
    organizations: list[NamedThing]
    programs: list[NamedThing]
    cited_works: list[CitedWork]
    relations: list[RelationOut]
    limitations: list[str]
    quality_notes: str = Field(description="Transparent notes on provenance, methodology and possible bias.")
    relevance: int = Field(-1, description="0-100: how useful this source is for research on Islamic tarbiyah of "
                                           "children, parents/family or murabbi development. 0 = unrelated (e.g. "
                                           "sports news), 30 = general parenting/education only loosely connected, "
                                           "60 = clearly about one pillar, 90+ = central, substantive source.")
    relevance_reason: str = Field("", description="One short sentence explaining the relevance score.")


class SearchQuery(BaseModel):
    query: str
    lang: Literal["ar", "en"]


class QuestionOut(BaseModel):
    text: str
    text_other_language: str
    lang: Literal["ar", "en"]
    kind: Literal["gap", "evidence", "terminology", "coverage", "citation_followup", "entity_followup",
                  "contradiction", "implementation", "cross_pillar", "planner"]
    rationale: str
    pillars: list[Pillar]
    importance: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    feasibility: float = Field(ge=0, le=1)
    search_queries: list[SearchQuery]
    next_steps: str
    related_passage_ids: list[int]


class QuestionBatch(BaseModel):
    questions: list[QuestionOut]


class GlossaryOut(BaseModel):
    concept: str
    terms_en: list[str]
    terms_ar: list[str]


class PlanOut(BaseModel):
    questions: list[QuestionOut]
    glossary: list[GlossaryOut]


class EvidenceOut(BaseModel):
    passage_id: int
    quote: str = Field(description="Exact verbatim excerpt from that passage")
    supports: Literal["supports", "contradicts", "qualifies"]


class FindingOut(BaseModel):
    statement: str
    finding_type: Literal["supported", "contested", "gap", "insufficient"]
    confidence: Literal["low", "medium", "high"]
    evidence_basis: Literal["empirical", "scriptural", "scholarly", "practice", "mixed", "none"]
    evidence: list[EvidenceOut]


class SynthesisOut(BaseModel):
    answer_summary: str
    status: Literal["answered", "partially_answered", "unresolved"]
    findings: list[FindingOut]
    disagreements: list[str]
    gaps: list[str]
    follow_up_questions: list[QuestionOut]


class Citation(BaseModel):
    passage_id: int
    quote: str


class AssistantAnswer(BaseModel):
    answer: str = Field(description="Markdown answer citing passages as [P<id>] after each supported sentence.")
    sufficiency: Literal["sufficient", "partial", "insufficient"]
    citations: list[Citation]
    evidence_vs_interpretation: str = Field(description="Which parts are directly evidenced, which are interpretation.")


class QueryTerms(BaseModel):
    terms_en: list[str]
    terms_ar: list[str]


class QAVerdict(BaseModel):
    index: int
    verdict: Literal["supported", "partially_supported", "unsupported"]
    note: str


class QAReview(BaseModel):
    verdicts: list[QAVerdict]


class TriageItem(BaseModel):
    id: int
    relevance: int = Field(description="0-100, see the scale in the instructions")
    pillars: list[Pillar]
    reason: str = Field(description="One short sentence")


class TriageBatch(BaseModel):
    items: list[TriageItem]
