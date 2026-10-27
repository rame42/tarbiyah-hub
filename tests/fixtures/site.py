"""A small bilingual test website served over real HTTP on localhost.

Structure (Arabic section /ar, English section /en):
  robots.txt (disallows /private/, declares sitemap)  sitemap.xml
  /ar/index.html -> page 2 (pagination) -> 3 Arabic articles (+ CC licence, PDF link)
  /en/index.html -> 2 English articles, one linking a PDF
  /feed.xml (RSS podcast with <podcast:transcript>)  /private/secret.html (must never be fetched)
  /tg/s/testchannel (Telegram-style public channel preview)
"""
from __future__ import annotations

import functools
import http.server
import shutil
import socket
import threading
from pathlib import Path

from .make_fixtures import build_all

AR_ARTICLES = {
    "ar/articles/hiwar.html": ("الحوار مع الأبناء في الأسرة المسلمة",
                               "الحوار الأسري من أهم أساليب التربية، فالإصغاء للطفل واحترام رأيه يبني الثقة ويقوي العلاقة بين الوالدين والأبناء. "
                               "وينبغي للوالدين اختيار الوقت المناسب للحديث والبعد عن كثرة الأوامر. " * 3),
    "ar/articles/qudwa.html": ("القدوة الحسنة في تربية الطفل",
                               "القدوة الحسنة أقوى وسائل التربية أثرًا، فالطفل يتعلم بالملاحظة والمحاكاة قبل أن يتعلم بالكلام. "
                               "ولذلك يحتاج المربي والمعلم إلى أن يكون نموذجًا عمليًا للأخلاق والآداب التي يدعو إليها. " * 3),
    "ar/articles/murabbi.html": ("كفايات المربي في الحلقات التربوية",
                                 "يحتاج المربي في الحلقات التربوية إلى كفايات متعددة: الإرشاد والتوجيه، وإدارة الحوار، وتدريب المدربين، "
                                 "والقدرة على متابعة نمو المتربين في مراحل المراهقة والشباب. " * 3),
}
EN_ARTICLES = {
    "en/posts/storytelling.html": ("Storytelling for Moral Education in Early Childhood",
                                   "Storytelling is an effective teaching method in early childhood. Stories of the prophets give "
                                   "children concrete models of honesty and patience, and teachers report better recall when a "
                                   "story is followed by a short activity. Parents can use the same approach at home. " * 3),
    "en/posts/teacher-training.html": ("Training of Trainers for Islamic School Teachers",
                                       "Professional development for teachers in Islamic schools works best when training of trainers "
                                       "programs model active learning, reflective mentoring and classroom observation. Competency "
                                       "frameworks help educators plan their growth. " * 3),
}


def _page(title: str, body: str, lang: str, extra: str = "", license_link: bool = False) -> str:
    d = "rtl" if lang == "ar" else "ltr"
    lic = '<link rel="license" href="https://creativecommons.org/licenses/by/4.0/">' if license_link else ""
    return (f'<!doctype html><html lang="{lang}" dir="{d}"><head><meta charset="utf-8"><title>{title}</title>'
            f'<meta name="author" content="Test Author">{lic}</head><body><nav><a href="/ar/index.html">ar</a> '
            f'<a href="/en/index.html">en</a> <a href="/private/secret.html">private</a></nav>'
            f"<article><h1>{title}</h1><p>{body}</p>{extra}</article></body></html>")


def build_site(root: Path, base: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    gen = build_all()
    (root / "docs").mkdir(exist_ok=True)
    shutil.copy(gen / "ar_tarbiyah.pdf", root / "docs" / "ar_guide.pdf")
    shutil.copy(gen / "en_parenting.pdf", root / "docs" / "en_parenting_guide.pdf")
    (root / "robots.txt").write_text(f"User-agent: *\nDisallow: /private/\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    pages = list(AR_ARTICLES) + list(EN_ARTICLES)
    urls = "".join(f"<url><loc>{base}/{p}</loc></url>" for p in pages)
    (root / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        encoding="utf-8")
    keys = list(AR_ARTICLES)
    (root / "ar").mkdir(exist_ok=True)
    (root / "ar" / "index.html").write_text(_page("مقالات تربوية", "قائمة المقالات",
        "ar", f'<a href="/{keys[0]}">1</a> <a href="/ar/page2.html" rel="next">الصفحة التالية</a>'), encoding="utf-8")
    (root / "ar" / "page2.html").write_text(_page("مقالات تربوية - 2", "قائمة المقالات",
        "ar", f'<a href="/{keys[1]}">2</a> <a href="/{keys[2]}">3</a> <a href="/docs/ar_guide.pdf">دليل PDF</a>'),
        encoding="utf-8")
    for path, (title, body) in AR_ARTICLES.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(_page(title, body, "ar", license_link=True), encoding="utf-8")
    (root / "en").mkdir(exist_ok=True)
    ek = list(EN_ARTICLES)
    (root / "en" / "index.html").write_text(_page("Blog", "Latest posts", "en",
        f'<a href="/{ek[0]}">a</a> <a href="/{ek[1]}">b</a> <a href="/docs/en_parenting_guide.pdf">guide</a>'),
        encoding="utf-8")
    for path, (title, body) in EN_ARTICLES.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(_page(title, body, "en"), encoding="utf-8")
    (root / "private").mkdir(exist_ok=True)
    (root / "private" / "secret.html").write_text(_page("Secret", "must not be crawled " * 50, "en"), encoding="utf-8")
    (root / "transcripts").mkdir(exist_ok=True)
    (root / "transcripts" / "ep1.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nWelcome to the parenting podcast.\n\n"
        "00:00:05.000 --> 00:00:12.000\nToday we discuss patience and dialogue with teenagers.\n", encoding="utf-8")
    (root / "feed.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><title>Family Tarbiyah Podcast</title>
<link>{base}/</link><description>test</description>
<item><title>Episode 1: Dialogue with teenagers</title><link>{base}/episodes/1</link><guid>{base}/episodes/1</guid>
<pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate><description>Parents and adolescents: patience and dialogue.</description>
<enclosure url="{base}/audio/ep1.mp3" type="audio/mpeg" length="1000"/>
<podcast:transcript url="{base}/transcripts/ep1.vtt" type="text/vtt"/></item>
<item><title>حلقة: تربية الأبناء على الصدق</title><link>{base}/episodes/2</link><guid>{base}/episodes/2</guid>
<pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate><description>حديث عن تربية الأطفال على الصدق والأمانة في الأسرة المسلمة وأثر القدوة الحسنة.</description>
<enclosure url="{base}/audio/ep2.mp3" type="audio/mpeg" length="1000"/></item>
</channel></rss>""", encoding="utf-8")
    (root / "tg" / "s").mkdir(parents=True, exist_ok=True)
    msgs = "".join(
        f'<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="testchannel/{i}">'
        f'<div class="tgme_widget_message_text">{t}</div>'
        f'<a class="tgme_widget_message_date"><time datetime="2026-10-0{i}T10:00:00+00:00"></time></a></div></div>'
        for i, t in [(1, "نصائح للوالدين في تربية الأطفال على الصلاة"), (2, "Course announcement: training for halaqa mentors"),
                     (3, 'كتاب جديد عن كفايات المربي <a href="https://example.org/book">رابط</a>')])
    (root / "tg" / "s" / "testchannel").write_text(f"<html><body>{msgs}</body></html>", encoding="utf-8")
    return root


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass

    def guess_type(self, path):
        if str(path).endswith("testchannel"):
            return "text/html"
        return super().guess_type(path)


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    handler = functools.partial(_Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"
