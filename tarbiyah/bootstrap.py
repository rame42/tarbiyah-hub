"""Initialize the database: run migrations and insert seed data (idempotent)."""
from __future__ import annotations

import logging

from sqlalchemy import select

from .config import get_config
from .db import session_scope
from .migrate import upgrade_db
from .models import GlossaryTerm, ResearchObjective, Topic
from .taxonomy import DEFAULT_OBJECTIVES, GLOSSARY, TOPICS

log = logging.getLogger(__name__)


def seed() -> None:
    with session_scope() as s:
        have = {t.slug for t in s.execute(select(Topic)).scalars()}
        for slug, pillar, en, ar, kw_en, kw_ar in TOPICS:
            if slug not in have:
                s.add(Topic(slug=slug, pillar=pillar, name_en=en, name_ar=ar, keywords_en=kw_en, keywords_ar=kw_ar))
        have_g = {g.concept_key for g in s.execute(select(GlossaryTerm)).scalars()}
        for key, pillar, en, ar, tr in GLOSSARY:
            if key not in have_g:
                s.add(GlossaryTerm(concept_key=key, pillar=pillar, terms_en=en, terms_ar=ar, transliterations=tr))
        if not s.execute(select(ResearchObjective)).first():
            for title, desc, pillars in DEFAULT_OBJECTIVES:
                s.add(ResearchObjective(title=title, description=desc, pillars=pillars, priority=0.7))
    try:
        from .sources.registry import seed_sources
    except ImportError:  # adapters not installed yet (partial checkouts)
        return
    seed_sources()


def init_app() -> None:
    get_config().ensure_dirs()
    upgrade_db()
    seed()
