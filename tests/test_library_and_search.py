"""Import, duplicate detection, licensing decisions, bilingual keyword search."""
from pathlib import Path

from tarbiyah.db import session_scope
from tarbiyah.ingest.licensing import decide
from tarbiyah.ingest.pipeline import import_local_file, process
from tarbiyah.ingest.registry import ResourceIn, canonical_url, register
from tarbiyah.models import Resource
from tarbiyah.search.fts import SearchFilters, search, search_chunks

FILES = ["ar_tarbiyah.pdf", "en_parenting.pdf", "framework.docx", "children_rights.epub", "ar_article.html",
         "en_article.html", "scanned.pdf"]


def _import_all(fixtures_dir: Path) -> dict[str, int]:
    ids = {}
    with session_scope() as s:
        for f in FILES:
            r, created = import_local_file(s, fixtures_dir / f)
            assert created
            process(s, r)
            ids[f] = r.id
    return ids


def test_import_preserves_metadata_and_provenance(env, fixtures_dir):
    ids = _import_all(fixtures_dir)
    with session_scope() as s:
        r = s.get(Resource, ids["ar_tarbiyah.pdf"])
        assert r.title == "تربية الأطفال في ضوء المنهج الإسلامي"  # title from the document, not the file name
        assert r.language == "ar" and r.page_count == 2 and r.checksum_sha256 and len(r.checksum_sha256) == 64
        assert r.access_status == "user_provided" and r.download_permitted
        assert r.extra["original_filename"] == "ar_tarbiyah.pdf"
        assert (env / r.local_path).exists() and (env / r.text_path).exists()
        assert {p.pillar for p in r.pillars} >= {"children"}
        scanned = s.get(Resource, ids["scanned.pdf"])
        assert scanned.processing_status == "needs_ocr" and "Tesseract" in scanned.last_error


def test_duplicate_detection(env, fixtures_dir):
    _import_all(fixtures_dir)
    with session_scope() as s:
        r, created = import_local_file(s, fixtures_dir / "ar_tarbiyah.pdf")  # same bytes -> checksum match
        assert not created
        a, c1 = register(s, ResourceIn(title="Islamic Parenting", doi="https://doi.org/10.1234/ABC", source_key="crossref"))
        b, c2 = register(s, ResourceIn(title="Islamic parenting (2nd)", doi="10.1234/abc", source_key="openalex"))
        assert c1 and not c2 and a.id == b.id
        assert "Islamic parenting (2nd)" in a.alt_titles  # alternate title merged, not a second record
        u1, _ = register(s, ResourceIn(title="Page", url="https://www.Example.org/a/?utm_source=x&id=2#top", resource_type="web_page"))
        u2, n2 = register(s, ResourceIn(title="Page again", url="http://example.org/a?id=2", resource_type="web_page"))
        assert u1.id == u2.id and not n2
        t1, _ = register(s, ResourceIn(title="تربية الأطفال في الإسلام", authors=["عبد الله ناصح علوان"], year=1976, resource_type="book"))
        t2, n3 = register(s, ResourceIn(title="تَرْبِيَةُ الأَطْفَالِ فِي الإِسْلَامِ", authors=["عبدالله ناصح علوان"], year=1977, resource_type="book"))
        assert t1.id == t2.id and not n3
        t3, n4 = register(s, ResourceIn(title="تربية الأطفال في الإسلام", authors=["Another Author"], year=2015, resource_type="book"))
        assert n4  # same title but different author and year: a different work
    assert canonical_url("https://youtu.be/abc?si=x") == "https://youtube.com/abc"


def test_licensing_is_conservative():
    assert decide("CC BY 4.0").download_permitted
    assert decide("https://creativecommons.org/publicdomain/zero/1.0/").download_permitted
    assert decide(None, public_domain=True).download_permitted
    assert not decide(None).download_permitted  # unknown -> link only
    assert not decide("All rights reserved").download_permitted
    assert not decide(None, open_access=True, oa_status="green").download_permitted  # free to read != licence
    assert decide(None, open_access=True, oa_status="green", allow_free_to_read=True).download_permitted
    assert decide(None, paid=True).access_status == "paid"
    assert decide(None, lending_only=True).access_status == "lending_only"


def test_bilingual_keyword_search(env, fixtures_dir):
    ids = _import_all(fixtures_dir)
    with session_scope() as s:
        ar = search(s, "تربية الأطفال")
        found = [x["resource"]["id"] for x in ar["results"]]
        assert found[0] == ids["ar_tarbiyah.pdf"]
        assert ids["children_rights.epub"] in found  # English resource found by an Arabic query
        assert "child" in ar["expansions"]
        assert ar["results"][0]["passage"]["page"] == 1
        assert "تربية الأطفال" in ar["results"][0]["passage"]["text"]  # snippet is ORIGINAL text, not normalized

        en = search(s, "teacher training")
        ids_en = [x["resource"]["id"] for x in en["results"]]
        assert ids["en_parenting.pdf"] in ids_en
        assert ids["ar_tarbiyah.pdf"] in ids_en  # Arabic resource found by an English query (تدريب / المربي)

        dialogue = [x["resource"]["id"] for x in search(s, "dialogue")["results"]]
        assert ids["ar_article.html"] in dialogue

        # diacritics and hamza variants in the query
        assert search(s, "الغَزَالِي")["results"][0]["resource"]["id"] == ids["ar_tarbiyah.pdf"]

        only_en = search(s, "تربية الأطفال", SearchFilters(language="en"))
        assert all(x["resource"]["language"] == "en" for x in only_en["results"])
        strict = search(s, "تربية الأطفال", cross_language=False)
        assert all(x["resource"]["language"] in ("ar", "mixed") for x in strict["results"])
        murabbi = search(s, "competencies", SearchFilters(pillar="murabbi"))
        assert ids["framework.docx"] in [x["resource"]["id"] for x in murabbi["results"]]


def test_passage_retrieval_for_questions(env, fixtures_dir):
    ids = _import_all(fixtures_dir)
    with session_scope() as s:
        hits = search_chunks(s, "كيف أحاور أبنائي؟", limit=5)
        assert ids["ar_article.html"] in [h["resource_id"] for h in hits]
        hits = search_chunks(s, "What did al-Ghazali say about children?", limit=5)
        assert hits and hits[0]["resource_id"] in (ids["ar_tarbiyah.pdf"], ids["children_rights.epub"])
