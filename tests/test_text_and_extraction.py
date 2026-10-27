"""Arabic/English text handling and document extraction on representative files."""
from tarbiyah.agents.common import verify_quote
from tarbiyah.ingest.extract import chunk_segments, extract_file, text_quality
from tarbiyah.text.arabic import light_stem, normalize_for_search, title_key
from tarbiyah.text.lang import detect_language


def test_arabic_normalization_keeps_meaning_but_unifies_variants():
    assert normalize_for_search("إِنَّ التَّرْبِيَةَ") == normalize_for_search("ان التربيه")
    assert normalize_for_search("مـــربـــي") == "مربي"  # tatweel removed
    assert normalize_for_search("أحمد إبراهيم آمنة") == "احمد ابراهيم امنه"
    assert normalize_for_search("مصطفى") == "مصطفي"
    assert normalize_for_search("١٢٣") == "123"
    assert light_stem("الأطفال".replace("أ", "ا")) == "اطفال"
    assert normalize_for_search("Tarbīyah") == "tarbiyah"


def test_language_detection():
    assert detect_language("إن تربية الأطفال من أهم واجبات الوالدين") == "ar"
    assert detect_language("The role of parents in the education of their children is central.") == "en"
    assert detect_language("La educación de los niños es una responsabilidad de los padres y la escuela.") == "other"
    mixed = "Murabbi competency framework for halaqa leaders. " * 3 + "كفايات المربي في الحلقات التربوية والإرشاد " * 3
    assert detect_language(mixed) == "mixed"


def test_title_key_matches_spelling_variants():
    assert title_key("تربية الأطفال في الإسلام") == title_key("تَرْبِيَةُ الاطفال في الاسلام")


def test_quote_verification_is_strict_but_tolerant_to_formatting():
    passage = "قال الغزالي: «الصبي أمانة عند والديه، وقلبه الطاهر جوهرة نفيسة»."
    assert verify_quote("الصبي أمانة عند والديه", passage)
    assert verify_quote("الصَّبِيُّ أَمَانَةٌ عِنْدَ وَالِدَيْهِ", passage)  # diacritics ignored
    assert not verify_quote("الطفل أمانة عند أبويه", passage)  # paraphrase is not a quote
    assert verify_quote("Parents play the central ... role", "Parents play the central role in the home")
    assert not verify_quote("", passage)


def test_pdf_arabic_extraction_with_pages(fixtures_dir):
    res = extract_file(fixtures_dir / "ar_tarbiyah.pdf")
    assert res.language == "ar"
    assert res.page_count == 2
    assert "تربية الأطفال" in res.segments[0].text  # presentation forms normalized back to letters
    assert "الغزالي" in res.segments[1].text and res.segments[1].page == 2
    assert text_quality(res.full_text) > 0.9
    chunks = chunk_segments(res.segments)
    assert {c["page"] for c in chunks} == {1, 2}


def test_pdf_english_docx_epub_html(fixtures_dir):
    en = extract_file(fixtures_dir / "en_parenting.pdf")
    assert en.language == "en" and "authoritative" in en.full_text
    dx = extract_file(fixtures_dir / "framework.docx")
    assert dx.title == "Murabbi Competency Framework (draft)"
    assert "كفايات المربي" in dx.full_text and "halaqa" in dx.full_text
    ep = extract_file(fixtures_dir / "children_rights.epub")
    assert ep.title == "Rights of Children in Islamic Tradition" and ep.license_hint == "Public domain"
    h = extract_file(fixtures_dir / "ar_article.html")
    assert h.title == "أساليب الحوار الأسري مع الأبناء" and h.language == "ar"
    assert h.license_hint == "https://creativecommons.org/licenses/by/4.0/"
    assert "الرئيسية" not in h.full_text  # navigation boilerplate removed


def test_scanned_pdf_is_flagged_for_ocr(fixtures_dir):
    res = extract_file(fixtures_dir / "scanned.pdf")
    assert res.ocr_pages == [1]
