"""Bilingual full-text search on SQLite FTS5.

Two FTS5 tables hold *normalized* copies of text (see migrations):
  resource_fts(rowid = resources.id; title, people, description, keywords, stems)
  chunk_fts(rowid = chunks.id; body, stems)
Original text stays in `resources` / `chunks`; snippets are cut from the original.

Cross-language retrieval: query concepts found in the glossary are expanded into the
other language, so an Arabic query also matches English text and vice versa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import Chunk, GlossaryTerm, Resource, ResourcePillar, ResourceTopic
from ..text.arabic import content_tokens, has_arabic, light_stem, normalize_for_search, stems_text, tokens

_FTS_SAFE = re.compile(r'["*^:(){}\[\]]')


def _q(term: str) -> str:
    term = _FTS_SAFE.sub(" ", term).strip()
    return f'"{term}"' if term else ""


# ---------------------------------------------------------------- indexing

def index_resource(session: Session, r: Resource) -> None:
    conn = session.connection()
    conn.execute(text("DELETE FROM resource_fts WHERE rowid = :id"), {"id": r.id})
    people = r.authors_text or ""
    titles = " ".join([r.title or "", *(r.alt_titles or []), *[str(v) for k, v in (r.title_translations or {}).items() if not k.endswith("_status")]])
    kw = " ".join(r.keywords or [])
    desc = r.description or ""
    conn.execute(
        text(
            "INSERT INTO resource_fts(rowid, title, people, description, keywords, stems) "
            "VALUES (:id, :t, :p, :d, :k, :s)"
        ),
        {
            "id": r.id,
            "t": normalize_for_search(titles),
            "p": normalize_for_search(people),
            "d": normalize_for_search(desc),
            "k": normalize_for_search(kw),
            "s": stems_text(" ".join([titles, desc, kw])),
        },
    )


def index_chunks(session: Session, chunks: Iterable[Chunk]) -> int:
    conn = session.connection()
    n = 0
    for c in chunks:
        conn.execute(text("DELETE FROM chunk_fts WHERE rowid = :id"), {"id": c.id})
        conn.execute(
            text("INSERT INTO chunk_fts(rowid, body, stems) VALUES (:id, :b, :s)"),
            {"id": c.id, "b": normalize_for_search(c.text), "s": stems_text(c.text)},
        )
        n += 1
    return n


def remove_resource(session: Session, resource_id: int) -> None:
    conn = session.connection()
    conn.execute(text("DELETE FROM resource_fts WHERE rowid = :id"), {"id": resource_id})
    ids = [row[0] for row in conn.execute(text("SELECT id FROM chunks WHERE resource_id=:r"), {"r": resource_id})]
    for cid in ids:
        conn.execute(text("DELETE FROM chunk_fts WHERE rowid = :id"), {"id": cid})


# ---------------------------------------------------------------- query building

@dataclass
class ParsedQuery:
    original: str
    match: str  # FTS5 MATCH expression
    concepts: list[str] = field(default_factory=list)
    expansions: dict[str, list[str]] = field(default_factory=dict)


def _token_expr(tok: str) -> str:
    if has_arabic(tok):
        st = light_stem(tok)
        parts = {_q(tok)}
        if st and st != tok:
            parts.add(_q(st))
        return "(" + " OR ".join(sorted(parts)) + ")" if len(parts) > 1 else _q(tok)
    return _q(tok)


def _phrase_expr(phrase: str) -> str:
    toks = tokens(phrase)
    if not toks:
        return ""
    if len(toks) == 1:
        return _token_expr(toks[0])
    return _q(" ".join(toks))


def _load_glossary(session: Session) -> list[tuple[str, list[str], list[str]]]:
    rows = session.execute(select(GlossaryTerm)).scalars().all()
    out = []
    for g in rows:
        en = [normalize_for_search(t) for t in (g.terms_en or []) + (g.transliterations or [])]
        ar = [normalize_for_search(t) for t in (g.terms_ar or [])]
        out.append((g.concept_key, en, ar))
    return out


def build_query(session: Session, query: str, cross_language: bool = True,
                extra_terms: list[str] | None = None, match_any: bool = False) -> ParsedQuery:
    """match_any=False: every word must match (library search).
    match_any=True: any content word may match, ranked by BM25 (passage retrieval for questions)."""
    norm = normalize_for_search(query)
    qtoks = content_tokens(query) if match_any else tokens(query)
    if not qtoks:
        qtoks = tokens(query)
    if not qtoks:
        return ParsedQuery(query, "")
    base = (" OR " if match_any else " AND ").join(e for e in (_token_expr(t) for t in qtoks) if e)
    clauses = [f"({base})"]
    concepts: list[str] = []
    expansions: dict[str, list[str]] = {}
    if cross_language:
        covered: set[str] = set()
        # concepts that cover the same query words are alternatives (OR); different words are AND-ed
        groups_by_cover: dict[frozenset[str], set[str]] = {}
        padded = f" {norm} "
        qstems = {light_stem(t) for t in qtoks if has_arabic(t)}
        for key, en, ar in _load_glossary(session):
            hit = None
            for term in en + ar:
                if term and f" {term} " in padded:
                    hit = term
                    break
            if hit is None:
                # match on Arabic light stems too (e.g. "للأطفال" vs "الأطفال")
                for term in ar:
                    tt = tokens(term)
                    if tt and all(light_stem(t) in qstems for t in tt):
                        hit = term
                        break
            if hit is None:
                continue
            hit_stems = {light_stem(x) for x in tokens(hit)}
            cover = frozenset(t for t in qtoks if t in tokens(hit) or (has_arabic(t) and light_stem(t) in hit_stems))
            if not cover:
                continue
            concepts.append(key)
            covered.update(cover)
            terms = sorted(set(en + ar))
            expansions[key] = terms
            groups_by_cover.setdefault(cover, set()).update(terms)
        if groups_by_cover:
            # merge overlapping covers into one OR-group
            merged: list[tuple[set[str], set[str]]] = []
            for cover, terms in groups_by_cover.items():
                for mc, mt in merged:
                    if mc & cover:
                        mc |= cover
                        mt |= terms
                        break
                else:
                    merged.append((set(cover), set(terms)))
            uncovered = [t for t in qtoks if t not in covered]
            groups = ["(" + " OR ".join(e for e in (_phrase_expr(t) for t in sorted(terms)) if e) + ")"
                      for _, terms in merged]
            groups += [_token_expr(t) for t in uncovered]
            clauses.append("(" + (" OR " if match_any else " AND ").join(groups) + ")")
    for t in extra_terms or []:
        e = _phrase_expr(t)
        if e:
            clauses.append(e)
    return ParsedQuery(query, " OR ".join(clauses), concepts, expansions)


# ---------------------------------------------------------------- searching

@dataclass
class SearchFilters:
    language: str | None = None
    pillar: str | None = None
    resource_type: str | None = None
    access_status: str | None = None
    source_key: str | None = None
    topic_id: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    discovered_from: str | None = None  # ISO date
    discovered_to: str | None = None


def _filter_ids(session: Session, ids: list[int], f: SearchFilters) -> list[int]:
    if not ids:
        return ids
    stmt = select(Resource.id).where(Resource.id.in_(ids), Resource.duplicate_of_id.is_(None))
    if f.language:
        stmt = stmt.where(Resource.language == f.language)
    if f.resource_type:
        stmt = stmt.where(Resource.resource_type == f.resource_type)
    if f.access_status:
        stmt = stmt.where(Resource.access_status == f.access_status)
    if f.source_key:
        stmt = stmt.where(Resource.source_key == f.source_key)
    if f.year_from:
        stmt = stmt.where(Resource.year >= f.year_from)
    if f.year_to:
        stmt = stmt.where(Resource.year <= f.year_to)
    if f.discovered_from:
        stmt = stmt.where(Resource.discovered_at >= f.discovered_from)
    if f.discovered_to:
        stmt = stmt.where(Resource.discovered_at < f.discovered_to + "T23:59:59.999")
    if f.pillar:
        stmt = stmt.where(Resource.id.in_(select(ResourcePillar.resource_id).where(ResourcePillar.pillar == f.pillar)))
    if f.topic_id:
        stmt = stmt.where(Resource.id.in_(select(ResourceTopic.resource_id).where(ResourceTopic.topic_id == f.topic_id)))
    allowed = set(session.execute(stmt).scalars().all())
    return [i for i in ids if i in allowed]


def snippet(original: str, query_terms: list[str], width: int = 260) -> str:
    """Cut a window of the ORIGINAL text around the first normalized term hit."""
    if not original:
        return ""
    norm_chars: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(original):
        n = normalize_for_search(ch) if not ch.isspace() else " "
        for c in n:
            norm_chars.append(c)
            index_map.append(i)
    norm = "".join(norm_chars)
    pos = -1
    for term in query_terms:
        t = normalize_for_search(term)
        if t:
            pos = norm.find(t)
            if pos >= 0:
                break
    if pos < 0:
        return original[:width].strip() + ("…" if len(original) > width else "")
    o = index_map[pos]
    start = max(0, o - width // 3)
    end = min(len(original), start + width)
    return ("…" if start > 0 else "") + original[start:end].strip() + ("…" if end < len(original) else "")


def search(session: Session, query: str, filters: SearchFilters | None = None, limit: int = 20,
           offset: int = 0, cross_language: bool = True, extra_terms: list[str] | None = None) -> dict[str, Any]:
    filters = filters or SearchFilters()
    pq = build_query(session, query, cross_language, extra_terms)
    if not pq.match:
        return {"query": query, "total": 0, "results": [], "expansions": {}}
    conn = session.connection()
    scores: dict[int, float] = {}
    best_chunk: dict[int, tuple[float, int]] = {}
    # bm25: lower is better -> negate. Metadata matches weigh more than body matches.
    rows = conn.execute(
        text("SELECT rowid, bm25(resource_fts, 6.0, 3.0, 1.5, 2.0, 1.0) FROM resource_fts "
             "WHERE resource_fts MATCH :m ORDER BY 2 LIMIT 500"),
        {"m": pq.match},
    ).all()
    for rid, s in rows:
        scores[rid] = scores.get(rid, 0.0) + (-s) * 2.0
    rows = conn.execute(
        text("SELECT c.id, c.resource_id, bm25(chunk_fts) FROM chunk_fts JOIN chunks c ON c.id = chunk_fts.rowid "
             "WHERE chunk_fts MATCH :m ORDER BY 3 LIMIT 2000"),
        {"m": pq.match},
    ).all()
    for cid, rid, s in rows:
        sc = -s
        scores[rid] = scores.get(rid, 0.0) + sc
        if rid not in best_chunk or sc > best_chunk[rid][0]:
            best_chunk[rid] = (sc, cid)
    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
    ranked = _filter_ids(session, ranked, filters)
    total = len(ranked)
    page = ranked[offset: offset + limit]
    terms = tokens(query) + [t for ts in pq.expansions.values() for t in ts]
    results = []
    for rid in page:
        r = session.get(Resource, rid)
        if r is None:
            continue
        hit = None
        if rid in best_chunk:
            c = session.get(Chunk, best_chunk[rid][1])
            if c is not None:
                hit = {"chunk_id": c.id, "page": c.page_start, "text": snippet(c.text, terms), "lang": c.lang}
        results.append({
            "resource": resource_brief(r),
            "score": round(scores[rid], 3),
            "passage": hit,
            "description_snippet": snippet(r.description or "", terms, 200) if r.description else None,
        })
    return {"query": query, "fts": pq.match, "total": total, "results": results,
            "expansions": pq.expansions, "concepts": pq.concepts}


def search_chunks(session: Session, query: str, limit: int = 12, resource_ids: list[int] | None = None,
                  extra_terms: list[str] | None = None) -> list[dict[str, Any]]:
    """Passage-level retrieval used by the assistant and synthesis agents.
    Keyword (bilingual, any-word) ranking, fused with semantic ranking when embeddings are enabled."""
    from . import semantic

    pq = build_query(session, query, True, extra_terms, match_any=True)
    ranked: list[int] = []
    scores: dict[int, float] = {}
    if pq.match:
        rows = session.connection().execute(
            text("SELECT c.id, bm25(chunk_fts) FROM chunk_fts JOIN chunks c ON c.id = chunk_fts.rowid "
                 "JOIN resources r ON r.id = c.resource_id "
                 "WHERE chunk_fts MATCH :m AND r.duplicate_of_id IS NULL ORDER BY 2 LIMIT :lim"),
            {"m": pq.match, "lim": limit * 4},
        ).all()
        ranked = [cid for cid, _ in rows]
        scores = {cid: -s for cid, s in rows}
    if semantic.available():
        try:
            sem = semantic.semantic_chunks(session, query, k=limit * 4)
        except Exception:  # noqa: BLE001 - semantic search is optional; keyword results still returned
            sem = []
        if sem:
            ranked = semantic.fuse(ranked, [cid for cid, _ in sem])
            for cid, sc in sem:
                scores.setdefault(cid, sc)
    out = []
    per_resource: dict[int, int] = {}
    for cid in ranked:
        c = session.get(Chunk, cid)
        if c is None:
            continue
        r = session.get(Resource, c.resource_id)
        if r is None or r.duplicate_of_id is not None:
            continue
        if resource_ids and c.resource_id not in resource_ids:
            continue
        if per_resource.get(c.resource_id, 0) >= 3:  # diversity across sources
            continue
        per_resource[c.resource_id] = per_resource.get(c.resource_id, 0) + 1
        out.append({"chunk_id": c.id, "resource_id": c.resource_id, "page": c.page_start,
                    "text": c.text, "lang": c.lang, "score": scores.get(cid, 0.0)})
        if len(out) >= limit:
            break
    return out


def resource_brief(r: Resource) -> dict[str, Any]:
    return {
        "id": r.id,
        "title": r.title,
        "title_translations": r.title_translations or {},
        "authors": r.authors_text,
        "type": r.resource_type,
        "language": r.language,
        "year": r.year,
        "url": r.url,
        "source_key": r.source_key,
        "access_status": r.access_status,
        "acquisition_status": r.acquisition_status,
        "processing_status": r.processing_status,
        "pillars": [{"pillar": p.pillar, "score": round(p.score, 2)} for p in r.pillars],
        "discovered_at": r.discovered_at.isoformat() if r.discovered_at else None,
        "has_file": bool(r.local_path),
    }
