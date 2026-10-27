"""Research outputs: bibliographies, reading lists, evidence tables (no AI needed) and
literature reviews, research briefs, curriculum outlines, training manuals (Claude).

Every output lists the resources it was built from. AI outputs cite passages [P<id>],
which are resolved into a reference list; unknown passage ids are flagged."""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.claude import claude
from ..config import get_config
from ..models import Chunk, Claim, Finding, Output, ResearchQuestion, Resource, ResourcePillar
from ..search.fts import SearchFilters, search, search_chunks
from .common import passage_block

KINDS = {
    "bibliography": ("Annotated bibliography", False),
    "reading_list": ("Reading list", False),
    "evidence_table": ("Evidence table", False),
    "literature_review": ("Literature review (draft)", True),
    "research_brief": ("Research brief", True),
    "curriculum_outline": ("Curriculum outline", True),
    "training_manual": ("Training manual outline", True),
}

AI_INSTRUCTIONS = {
    "literature_review": "Write a literature-review draft: scope, themes, agreements, disagreements, methodological "
                         "notes, gaps. Distinguish scriptural/classical, empirical and practical sources.",
    "research_brief": "Write a 1-2 page research brief: key question, what the evidence shows, confidence, "
                      "practical implications, open questions.",
    "curriculum_outline": "Draft a curriculum outline (units, objectives, age group, activities, assessment) grounded "
                          "in the passages; mark which elements are evidence-based vs suggested.",
    "training_manual": "Draft a training-manual outline for murabbis/educators (modules, competencies, activities, "
                       "facilitation notes) grounded in the passages; mark evidence-based vs suggested elements.",
}


def cite(r: Resource) -> str:
    parts = [r.authors_text or "", f"({r.year})" if r.year else "", f"*{r.title}*", r.publisher or ""]
    s = " ".join(p for p in parts if p).strip()
    if r.doi:
        s += f". https://doi.org/{r.doi}"
    elif r.url:
        s += f". {r.url}"
    return s


def _resources(session: Session, o: Output) -> list[Resource]:
    p = o.params or {}
    if p.get("resource_ids"):
        rows = [session.get(Resource, i) for i in p["resource_ids"]]
        return [r for r in rows if r is not None]
    if p.get("question_id"):
        q = session.get(ResearchQuestion, p["question_id"])
        ids = (q.related_resource_ids or []) if q else []
        return [r for r in (session.get(Resource, i) for i in ids[:60]) if r is not None]
    if p.get("query"):
        res = search(session, p["query"], SearchFilters(pillar=p.get("pillar"), language=p.get("language")), limit=60)
        return [session.get(Resource, x["resource"]["id"]) for x in res["results"]]
    stmt = select(Resource).where(Resource.duplicate_of_id.is_(None))
    if p.get("pillar"):
        stmt = stmt.where(Resource.id.in_(select(ResourcePillar.resource_id).where(ResourcePillar.pillar == p["pillar"])))
    return session.execute(stmt.order_by(Resource.discovered_at.desc()).limit(60)).scalars().all()


def bibliography(session: Session, o: Output, annotated: bool) -> str:
    rs = _resources(session, o)
    lines = [f"# {o.title}", "", f"{len(rs)} source(s).", ""]
    for r in sorted(rs, key=lambda r: (r.authors_text or r.title).lower()):
        lines.append(f"- {cite(r)}  ")
        lines.append(f"  Type: {r.resource_type} · Language: {r.language} · Access: {r.access_status}"
                     + (f" · Price: {r.price} {r.currency}" if r.price else ""))
        if annotated:
            note = r.summary or (r.description or "")[:400]
            if note:
                label = "AI summary" if r.summary else "Source description"
                lines.append(f"  {label}: {note}")
        lines.append("")
    o.resource_ids = [r.id for r in rs]
    return "\n".join(lines)


def evidence_table(session: Session, o: Output) -> tuple[str, str]:
    rs = _resources(session, o)
    ids = [r.id for r in rs]
    claims = session.execute(select(Claim).where(Claim.resource_id.in_(ids)).order_by(Claim.resource_id)).scalars().all() if ids else []
    findings = []
    if (o.params or {}).get("question_id"):
        findings = session.execute(select(Finding).where(Finding.question_id == o.params["question_id"])).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["source", "year", "page", "claim_type", "evidence_type", "statement (system paraphrase)",
                "verbatim quote", "quote_verified", "age_group", "generated_by"])
    md = [f"# {o.title}", "", "| Source | Page | Type | Statement (paraphrase) | Verbatim quote | Verified |", "|---|---|---|---|---|---|"]
    by_id = {r.id: r for r in rs}
    for c in claims:
        r = by_id[c.resource_id]
        w.writerow([r.title, r.year, c.page, c.claim_type, c.evidence_type, c.statement, c.quote or "",
                    c.quote_verified, c.age_group or "", c.generated_by])
        md.append(f"| {r.title[:60]} | {c.page or ''} | {c.claim_type}/{c.evidence_type} | {c.statement[:200]} | "
                  f"{(c.quote or '')[:200]} | {'yes' if c.quote_verified else 'no'} |")
    if findings:
        md += ["", "## Findings for the question", ""]
        for f in findings:
            md.append(f"- **{f.finding_type}** ({f.confidence}, QA: {f.qa_status}): {f.statement}")
    if not claims:
        md.append("\n_No extracted claims yet for these sources (knowledge extraction requires Claude)._")
    o.resource_ids = ids
    return "\n".join(md), buf.getvalue()


def ai_document(session: Session, o: Output) -> str:
    p = o.params or {}
    topic = p.get("query") or p.get("topic") or o.title
    if p.get("question_id"):
        q = session.get(ResearchQuestion, p["question_id"])
        topic = q.text if q else topic
    hits = search_chunks(session, topic, limit=30)
    chunks = [(session.get(Chunk, h["chunk_id"]), session.get(Resource, h["resource_id"])) for h in hits]
    if not chunks:
        raise ValueError("No passages in the collection match this topic yet.")
    body = "\n".join(passage_block(c, r) for c, r in chunks)
    lang = "Arabic" if o.lang == "ar" else "English"
    session.commit()
    text = claude().text("output", "You write source-grounded research documents for Tarbiyah Hub. Cite passages as "
                         "[P<id>] after every sentence that relies on them. Never invent sources.",
                         f"{AI_INSTRUCTIONS[o.kind]}\nTopic: {topic}\nWrite in {lang}, Markdown.\n\n<source>\n{body}\n</source>",
                         max_tokens=24000, effort="medium")
    by_id = {c.id: (c, r) for c, r in chunks}
    used = [int(x) for x in re.findall(r"\[P(\d+)\]", text)]
    refs, unknown = [], []
    for pid in dict.fromkeys(used):
        if pid in by_id:
            c, r = by_id[pid]
            refs.append(f"- [P{pid}] {cite(r)}" + (f", p. {c.page_start}" if c.page_start else ""))
        else:
            unknown.append(pid)
    out = [f"# {o.title}", "", "> AI-generated draft (Claude). Statements are grounded in the cited passages; "
           "verify before use.", "", text, "", "## Sources cited", *refs]
    if unknown:
        out += ["", f"**Warning:** the draft referenced unknown passage ids {unknown}; treat those sentences as unsupported."]
    o.resource_ids = sorted({by_id[p][1].id for p in used if p in by_id})
    return "\n".join(out)


def generate(session: Session, o: Output) -> Output:
    title, needs_ai = KINDS[o.kind]
    if needs_ai and not claude().available():
        o.status = "failed"
        o.error = "This output type needs Claude (ANTHROPIC_API_KEY)."
        return o
    files: dict[str, str] = {}
    if o.kind in ("bibliography", "reading_list"):
        o.content = bibliography(session, o, annotated=o.kind == "bibliography")
    elif o.kind == "evidence_table":
        o.content, files["csv"] = evidence_table(session, o)
    else:
        o.content = ai_document(session, o)
        o.generated_by = claude().last_usage.model or claude().model_for("output")
    folder = get_config().outputs_dir
    base = folder / f"{o.id:05d}_{o.kind}"
    base.with_suffix(".md").write_text(o.content, encoding="utf-8")
    for ext, data in files.items():
        base.with_suffix("." + ext).write_text(data, encoding="utf-8-sig")
    base.with_suffix(".json").write_text(json.dumps({"title": o.title, "kind": o.kind, "params": o.params,
                                                     "resource_ids": o.resource_ids, "content": o.content},
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    o.status = "done"
    o.error = None
    return o


def export_files(o: Output) -> dict[str, Any]:
    base = get_config().outputs_dir / f"{o.id:05d}_{o.kind}"
    return {ext: str(base.with_suffix("." + ext)) for ext in ("md", "csv", "json") if base.with_suffix("." + ext).exists()}
