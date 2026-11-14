"""Recommended tarbiyah websites. They are added switched off: the person chooses the sections to read
("Choose sections"), checks with Preview, and enables the source. `section` marks addresses confirmed to be
a tarbiyah/family section; the others start at the home page and the sections are chosen in the dashboard.

Entries may carry `config` (crawler settings: which addresses are articles, which to skip) and `strict`
(the exact title phrases, exclude words and points to be considered), so a site is narrow from the first run.
"""
from __future__ import annotations

# exact phrases (Arabic matches inside words, so "الأبناء" also matches "والأبناء"/"بالأبناء")
AR_CHILDREN_PARENTS = [
    "تربية الأبناء", "تربية الأطفال", "تربية الطفل", "تربية الأولاد", "تربية البنات", "تربية أبنائ", "تربية أولاد",
    "التربية الإيمانية", "التربية الإسلامية", "تأديب", "الأبناء", "أبنائنا", "أبناءك", "الأطفال", "أطفالنا", "الطفل",
    "طفلك", "الأولاد", "أولادنا", "الصغار", "الناشئة", "المراهق", "المراهقة", "الوالدين", "بر الوالدين", "الأسرة المسلمة",
]
AR_MURABBI = [
    "المربي", "المربين", "المربية", "المعلم", "المعلمين", "المعلمة", "المدرس", "إعداد المعلم", "الحلقات القرآنية",
    "حلقات التحفيظ", "تحفيظ القرآن", "المتعلم", "طالب العلم", "العملية التربوية", "التربوي", "التربوية", "القدوة",
]
AR_EXCLUDE = ["الانتخابات", "الاقتصاد", "البورصة", "الأسهم", "كرة القدم", "مباراة", "عاجل", "تهنئة", "إعلان",
              "مسابقة", "وظائف", "الطقس"]
POINTS_CHILDREN_PARENTS = (
    "احتفظ فقط بما موضوعه الأساسي تربية الأبناء أو توجيه الوالدين تربويًا من منظور إسلامي (القرآن والسنة): "
    "غرس العقيدة والعبادة والأخلاق، أساليب التربية والحوار والتأديب، مراحل الطفولة والمراهقة. "
    "ارفض: الأخبار، المقالات السياسية أو الاقتصادية، مشكلات الزوجين التي لا تتعلق بالأولاد، "
    "والمقالات التي تذكر الأطفال عرضًا فقط.")
POINTS_MURABBI = (
    "احتفظ فقط بما موضوعه الأساسي المربي أو المعلم المسلم: إعداده وتزكيته وصفاته، طرق التدريس والتربية، "
    "إدارة الحلقات القرآنية والفصول، العلاقة بين المربي والمتعلم. ارفض المواعظ العامة والأخبار.")
POINTS_ALL = POINTS_CHILDREN_PARENTS + " وكذلك ما يخص إعداد المربي والمعلم المسلم وطرق التربية والتعليم."


def _strict(keywords: list[str], points: str, where: str = "title", exclude: list[str] | None = None) -> dict:
    return {"keywords": keywords, "keywords_mode": "any", "keywords_in": where, "exclude": exclude or AR_EXCLUDE,
            "criteria": points, "review": True, "min_score": 40}


CATALOG: list[dict] = [
    # ---------------------------------------------------------------- the ten Arabic tarbiyah sites (precise)
    {"key": "islamway-tarbiyah", "name": "طريق الإسلام – تربية الأبناء في الإسلام", "lang": "ar",
     "url": "https://ar.islamway.net/articles/category/48/تربية-الأبناء-في-الإسلام", "section": True,
     "pillars": ["children", "parents"], "top10": True,
     "about": "A section only about raising children: articles by known scholars and educators.",
     "config": {"content_patterns": ["/article/"]},
     "strict": _strict(AR_CHILDREN_PARENTS, POINTS_CHILDREN_PARENTS, "title_description")},
    {"key": "islamonline-tarbiyah", "name": "إسلام أون لاين – تربية الأبناء في الإسلام", "lang": "ar",
     "url": "https://islamonline.net/category/الأسرة-في-الإسلام/تربية-الأبناء-في-الإسلام/", "section": True,
     "pillars": ["children", "parents"], "top10": True,
     "about": "The sub-section on raising children only (not the whole family category).",
     "config": {"exclude_patterns": ["/tag/", "/author/", "/wp-content/"]},
     "strict": _strict(AR_CHILDREN_PARENTS, POINTS_CHILDREN_PARENTS, "title_description")},
    {"key": "alukah-tarbiyah", "name": "شبكة الألوكة – مجتمع وإصلاح (التربية)", "lang": "ar",
     "url": "https://www.alukah.net/social/", "section": True, "pillars": ["children", "parents", "murabbi"], "top10": True,
     "about": "The largest Arabic tarbiyah collection (articles, sermons, PDF books). Only titles about children, "
              "parents or educators are kept.",
     "strict": _strict(AR_CHILDREN_PARENTS + AR_MURABBI, POINTS_ALL)},
    {"key": "saaid-tarbiah", "name": "صيد الفوائد – التربية", "lang": "ar", "url": "https://saaid.org/tarbiah/",
     "section": True, "pillars": ["children", "parents", "murabbi"], "top10": True,
     "about": "Saaid's tarbiyah folder (the site moved from saaid.net to saaid.org): articles and books.",
     "strict": _strict(AR_CHILDREN_PARENTS + AR_MURABBI, POINTS_ALL)},
    {"key": "islamweb-tarbiyah", "name": "إسلام ويب – مقالات واستشارات التربية", "lang": "ar",
     "url": "https://www.islamweb.net/ar/", "section": False, "pillars": ["children", "parents"], "top10": True,
     "about": "Only its articles and counselling answers (not fatwas, audio or Quran pages), and only titles about "
              "raising children.",
     "config": {"include_patterns": ["/ar/article/", "/ar/consult/", "/ar/articles/", "/ar/consults/"],
                "content_patterns": ["/ar/article/", "/ar/consult/"]},
     "strict": _strict(AR_CHILDREN_PARENTS, POINTS_CHILDREN_PARENTS)},
    {"key": "almoslim-murabbi", "name": "موقع المسلم – المربي والتربية", "lang": "ar", "url": "https://almoslim.net/",
     "section": False, "pillars": ["murabbi", "parents"], "top10": True,
     "about": "Strong on preparing the educator (عملية إنتاج المربي، كيف يبني المربي ثقافته). Only educator and "
              "upbringing titles are kept.",
     "config": {"content_patterns": ["/node/"]},
     "strict": _strict(AR_MURABBI + AR_CHILDREN_PARENTS, POINTS_MURABBI + " وكذلك تربية الأبناء.")},
    {"key": "albayan-murabbi", "name": "مجلة البيان – المربي والمعلم", "lang": "ar", "url": "https://www.albayan.co.uk/",
     "section": False, "pillars": ["murabbi"], "top10": True,
     "about": "Articles on teachers' competencies and preparing Quran teachers.",
     "config": {"content_patterns": ["article"]},
     "strict": _strict(AR_MURABBI, POINTS_MURABBI)},
    {"key": "midad-tarbiyah", "name": "مداد – مقالات التربية", "lang": "ar", "url": "https://midad.com/",
     "section": False, "pillars": ["murabbi", "parents"], "top10": True,
     "about": "Articles such as أخطاؤنا في التربية and الدور التربوي للحلقات القرآنية.",
     "config": {"content_patterns": ["/article/"]},
     "strict": _strict(AR_MURABBI + AR_CHILDREN_PARENTS, POINTS_ALL)},
    {"key": "dorar-akhlaq", "name": "الدرر السنية – موسوعة الأخلاق والسلوك", "lang": "ar",
     "url": "https://dorar.net/alakhlaq", "section": True, "pillars": ["children", "parents", "murabbi"], "top10": True,
     "about": "Islamic character traits with their evidence; only entries whose text speaks about children, "
              "upbringing or the educator are kept.",
     "strict": _strict(["الأطفال", "الأبناء", "الأولاد", "الصغار", "الطفل", "التربية", "المربي", "المعلم"],
                       "احتفظ فقط بمداخل الأخلاق التي تفيد في تربية الأطفال أو في إعداد المربي: كيف يُغرس الخلق "
                       "ووسائل اكتسابه والأمثلة التطبيقية. ارفض المداخل التي لا صلة لها بالتربية.", "text")},
    {"key": "islamqa-tarbiyah", "name": "الإسلام سؤال وجواب – تربية الأولاد", "lang": "ar",
     "url": "https://islamqa.info/ar", "section": False, "pillars": ["parents", "children"], "top10": True,
     "about": "Only answers whose title is about raising children (discipline, prayer, duties of the parents).",
     "config": {"include_patterns": ["/ar/answers/", "/ar/categories/"], "content_patterns": ["/ar/answers/"]},
     "strict": _strict(AR_CHILDREN_PARENTS, POINTS_CHILDREN_PARENTS +
                       " اقبل الأسئلة العملية للوالدين عن تربية أولادهم، وارفض الفتاوى في أحكام لا تتعلق بالتربية.")},
    # ---------------------------------------------------------------- other recommended sites
    {"key": "yaqeen-family", "name": "Yaqeen Institute – Family & Community", "lang": "en",
     "url": "https://yaqeeninstitute.org/topic/family-community", "section": True, "pillars": ["parents", "children"],
     "about": "Research papers, articles and video series on parenting, marriage and Muslim families."},
    {"key": "soundvision-parenting", "name": "SoundVision – Parenting", "lang": "en",
     "url": "https://www.soundvision.com/parenting", "section": True, "pillars": ["children", "parents"],
     "about": "Islamic parenting articles for Muslim families in the West, organised by the child's age."},
    {"key": "iiit", "name": "IIIT – International Institute of Islamic Thought", "lang": "en", "url": "https://iiit.org/",
     "section": False, "pillars": ["murabbi"],
     "about": "Books and papers on Islamic education, educational philosophy and curriculum (many free)."},
    {"key": "isla", "name": "Islamic Schools League of America", "lang": "en", "url": "https://theisla.org/",
     "section": False, "pillars": ["murabbi"], "about": "Resources for Islamic schools, teachers and school leaders."},
    {"key": "ams-uk", "name": "Association of Muslim Schools UK", "lang": "en", "url": "https://ams-uk.org/",
     "section": False, "pillars": ["murabbi"], "about": "Muslim schools' network: guidance and resources for educators."},
    {"key": "khalil-center", "name": "Khalil Center", "lang": "en", "url": "https://khalilcenter.com/", "section": False,
     "pillars": ["parents"], "about": "Islamic psychology: family, marriage and youth wellbeing articles."},
    {"key": "project-sakinah", "name": "Project Sakinah – parent resources", "lang": "en",
     "url": "https://projectsakinah.org/Resources/Parent-Resources", "section": True, "pillars": ["parents"],
     "about": "Resources for Muslim parents and healthy, safe families."},
    {"key": "shamela", "name": "المكتبة الشاملة (Shamela)", "lang": "ar", "url": "https://shamela.ws/", "section": False,
     "pillars": ["murabbi", "children"],
     "about": "Classical books: choose the adab/akhlaq/tarbiyah categories (al-Zarnuji, Ibn Sahnun, Ibn Jamaʿa, al-Ghazali)."},
]
