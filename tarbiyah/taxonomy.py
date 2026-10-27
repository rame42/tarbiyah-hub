"""Seed taxonomy (pillars, topics) and Arabic<->English glossary.

Everything here is editable data: it is copied into the database on first run, and
users can extend it from the dashboard. Keywords are matched against *normalized*
text, so Arabic entries may be written with or without diacritics / hamza forms.
"""
from __future__ import annotations

PILLAR_LABELS = {
    "children": {"en": "Children's Tarbiyah", "ar": "تربية الأطفال"},
    "parents": {"en": "Parents & Family", "ar": "الوالدان والأسرة"},
    "murabbi": {"en": "Murabbi Development", "ar": "إعداد المربين"},
}

# Pillar-level signal words (bilingual). Each hit adds weight; topics add more.
PILLAR_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "children": {
        "en": ["child", "children", "childhood", "kid", "kids", "infant", "toddler", "preschool",
               "early childhood", "adolescent", "adolescence", "youth", "teen", "pupil", "student",
               "kindergarten", "primary school", "boys", "girls", "upbringing"],
        "ar": ["طفل", "الطفل", "أطفال", "الأطفال", "الطفولة", "الصغار", "الناشئة", "النشء",
               "المراهق", "المراهقة", "المراهقين", "الشباب", "التلاميذ", "التلميذ", "الروضة",
               "رياض الأطفال", "الصبيان", "البنات", "تنشئة"],
    },
    "parents": {
        "en": ["parent", "parents", "parenting", "family", "families", "mother", "father",
               "mothers", "fathers", "home", "household", "marriage", "spouse", "siblings",
               "parent-child", "caregiver"],
        "ar": ["الوالدين", "الوالدان", "الآباء", "الأمهات", "الأم", "الأب", "الأسرة", "أسرة",
               "الأسري", "الأسرية", "البيت", "المنزل", "الزواج", "الزوجين", "الأبوة", "الأمومة",
               "بر الوالدين", "الإخوة"],
    },
    "murabbi": {
        "en": ["murabbi", "teacher", "teachers", "educator", "educators", "mentor", "mentoring",
               "trainer", "training", "coach", "coaching", "facilitator", "instructor",
               "professional development", "teacher training", "pedagogy", "competency",
               "competencies", "train-the-trainer", "training of trainers", "leadership",
               "halaqa", "halaqah"],
        "ar": ["المربي", "المربين", "مربي", "المربية", "المعلم", "المعلمين", "المعلمة", "المدرس",
               "الموجه", "التوجيه", "المدرب", "التدريب", "تدريب المدربين", "إعداد المعلم",
               "إعداد المربي", "الكفايات", "الكفاءات", "التنمية المهنية", "الحلقة", "الحلقات",
               "الشيخ", "المرشد", "القيادة"],
    },
}

# slug, pillar, name_en, name_ar, keywords_en, keywords_ar
TOPICS: list[tuple[str, str | None, str, str, list[str], list[str]]] = [
    ("islamic-upbringing", "children", "Islamic upbringing", "التربية الإسلامية",
     ["islamic upbringing", "islamic education", "tarbiyah", "tarbiya", "religious upbringing", "faith development"],
     ["التربية الإسلامية", "تربية إسلامية", "التنشئة الإسلامية", "التربية الإيمانية", "التنشئة الدينية"]),
    ("character-akhlaq", None, "Character & manners (akhlaq, adab)", "الأخلاق والآداب",
     ["character", "akhlaq", "adab", "manners", "morals", "moral education", "values", "virtue", "ethics"],
     ["الأخلاق", "الآداب", "أدب", "القيم", "التربية الأخلاقية", "الفضائل", "السلوك القويم"]),
    ("child-development", "children", "Child development & developmental stages", "نمو الطفل ومراحله",
     ["child development", "developmental stage", "developmental stages", "cognitive development",
      "emotional development", "social development", "early childhood development", "milestones"],
     ["نمو الطفل", "مراحل النمو", "النمو المعرفي", "النمو الانفعالي", "النمو الاجتماعي", "مراحل الطفولة", "خصائص النمو"]),
    ("child-psychology", "children", "Child psychology & emotions", "علم نفس الطفل",
     ["child psychology", "emotions", "emotional intelligence", "self-esteem", "anxiety", "behavior problems", "wellbeing"],
     ["علم نفس الطفل", "الانفعالات", "الذكاء العاطفي", "تقدير الذات", "القلق", "المشكلات السلوكية", "الصحة النفسية"]),
    ("behavior-discipline", None, "Behavior & discipline", "السلوك والتأديب",
     ["discipline", "behavior management", "behaviour", "reward", "punishment", "positive discipline", "reinforcement"],
     ["التأديب", "تعديل السلوك", "الثواب والعقاب", "العقاب", "التعزيز", "الانضباط", "الضرب"]),
    ("quran-memorization", "children", "Qur'an learning & memorization", "تعليم القرآن وتحفيظه",
     ["quran", "qur'an", "hifz", "memorization", "memorisation", "tajweed", "recitation"],
     ["القرآن", "تحفيظ", "حفظ القرآن", "التجويد", "التلاوة", "الكتاتيب", "الكتّاب"]),
    ("arabic-learning", "children", "Arabic language learning", "تعليم اللغة العربية",
     ["arabic language", "learning arabic", "arabic literacy", "arabic for children"],
     ["اللغة العربية", "تعليم العربية", "تعليم اللغة العربية", "القراءة والكتابة"]),
    ("islamic-studies-curriculum", "children", "Islamic studies curricula", "مناهج العلوم الشرعية",
     ["curriculum", "curricula", "syllabus", "lesson plan", "islamic studies", "textbook", "scope and sequence"],
     ["المنهج", "المناهج", "منهج", "الخطة الدراسية", "المقرر", "مقررات", "الكتاب المدرسي", "التربية الدينية"]),
    ("activities-play", "children", "Activities, play & learning environments", "الأنشطة واللعب وبيئات التعلم",
     ["activity", "activities", "play", "games", "storytelling", "stories", "learning environment", "hands-on"],
     ["النشاط", "الأنشطة", "اللعب", "الألعاب", "القصة", "القصص", "بيئة التعلم", "الأنشطة التربوية"]),
    ("assessment", None, "Assessment & evaluation", "التقويم والقياس",
     ["assessment", "evaluation", "measurement", "rubric", "test", "outcomes"],
     ["التقويم", "التقييم", "القياس", "الاختبار", "المخرجات", "مؤشرات الأداء"]),
    ("parenting-approaches", "parents", "Parenting approaches", "أساليب التربية الوالدية",
     ["parenting style", "parenting styles", "authoritative", "permissive", "authoritarian", "positive parenting", "gentle parenting"],
     ["أساليب المعاملة الوالدية", "الأساليب الوالدية", "أساليب التربية", "التربية الإيجابية", "المعاملة الوالدية"]),
    ("parent-child-communication", "parents", "Parent–child communication", "التواصل بين الوالدين والأبناء",
     ["communication", "listening", "dialogue", "parent-child relationship", "attachment", "bonding"],
     ["الحوار", "التواصل", "الإصغاء", "العلاقة بين الآباء والأبناء", "التعلق", "الحوار الأسري"]),
    ("home-learning", "parents", "Home learning environment", "البيئة التعليمية في المنزل",
     ["home learning", "homeschooling", "home environment", "family learning", "home-based"],
     ["التعليم المنزلي", "البيئة المنزلية", "التعلم في البيت", "دور الأسرة في التعليم"]),
    ("family-relations", "parents", "Family relationships & challenges", "العلاقات الأسرية وتحدياتها",
     ["family relationships", "marital", "divorce", "family conflict", "siblings", "extended family", "screen time"],
     ["العلاقات الأسرية", "الخلافات الأسرية", "الطلاق", "التفكك الأسري", "الإخوة", "الشاشات", "الأجهزة الذكية"]),
    ("parent-education", "parents", "Parent education programs", "برامج تثقيف الوالدين",
     ["parent education", "parenting program", "parenting course", "parent training", "parenting workshop"],
     ["تثقيف الوالدين", "برنامج تربوي للوالدين", "دورة في التربية", "تدريب الوالدين", "التوعية الأسرية"]),
    ("murabbi-competencies", "murabbi", "Murabbi competencies", "كفايات المربي",
     ["competency framework", "teacher competencies", "educator qualities", "qualities of a teacher", "professional standards"],
     ["كفايات المربي", "صفات المربي", "صفات المعلم", "كفايات المعلم", "معايير مهنية", "أخلاقيات المهنة"]),
    ("teacher-training", "murabbi", "Educator training & professional development", "تدريب المربين والتنمية المهنية",
     ["teacher training", "teacher education", "professional development", "in-service training", "continuing education"],
     ["تدريب المعلمين", "إعداد المعلمين", "التنمية المهنية", "التدريب أثناء الخدمة", "التكوين"]),
    ("training-of-trainers", "murabbi", "Training of trainers (ToT)", "تدريب المدربين",
     ["training of trainers", "train the trainer", "tot", "trainer development", "facilitation"],
     ["تدريب المدربين", "إعداد المدربين", "صناعة المدرب", "التيسير"]),
    ("mentoring-halaqa", "murabbi", "Mentoring, halaqas & study circles", "الإرشاد والحلقات التربوية",
     ["mentoring", "mentorship", "halaqa", "halaqah", "study circle", "usra", "small group"],
     ["الإرشاد", "الحلقة التربوية", "الحلقات", "الأسرة التربوية", "المحضن التربوي", "المحاضن التربوية"]),
    ("teaching-methods", "murabbi", "Teaching methods & pedagogy", "طرق التدريس",
     ["teaching methods", "pedagogy", "instructional strategies", "active learning", "lecture", "methodology"],
     ["طرق التدريس", "أساليب التدريس", "استراتيجيات التدريس", "التعلم النشط", "الوسائل التعليمية", "منهجية"]),
    ("prophetic-methods", None, "Prophetic methods of education", "الأساليب النبوية في التربية",
     ["prophetic", "sunnah", "prophet muhammad", "sirah", "seerah", "hadith"],
     ["الأساليب النبوية", "التربية النبوية", "السنة النبوية", "الهدي النبوي", "السيرة", "الحديث"]),
    ("classical-scholarship", None, "Classical scholarship on education", "التراث التربوي الإسلامي",
     ["al-ghazali", "ghazali", "ibn khaldun", "ibn qayyim", "ibn sina", "zarnuji", "classical", "manuscript"],
     ["الغزالي", "ابن خلدون", "ابن القيم", "ابن سينا", "الزرنوجي", "تعليم المتعلم", "تحفة المودود", "التراث", "مخطوط"]),
    ("institutions-programs", None, "Institutions & programs", "المؤسسات والبرامج",
     ["institution", "organization", "school", "university", "program", "initiative", "center", "academy"],
     ["مؤسسة", "جمعية", "مدرسة", "جامعة", "برنامج", "مبادرة", "مركز", "أكاديمية"]),
]

# concept_key, pillar, en terms, ar terms, transliterations
GLOSSARY: list[tuple[str, str | None, list[str], list[str], list[str]]] = [
    ("tarbiyah", None, ["upbringing", "education", "nurturing", "moral education", "tarbiyah"],
     ["تربية", "التربية", "تنشئة"], ["tarbiyah", "tarbiya", "tarbiyya"]),
    ("child", "children", ["child", "children", "childhood"], ["طفل", "الطفل", "أطفال", "الأطفال", "الطفولة"], ["tifl", "atfal"]),
    ("youth", "children", ["adolescent", "adolescence", "youth", "teenager"], ["المراهقة", "المراهق", "الشباب", "النشء"], []),
    ("parents", "parents", ["parents", "parenting", "parent"], ["الوالدين", "الوالدان", "الآباء", "الأبوين"], ["walidayn"]),
    ("family", "parents", ["family", "household"], ["الأسرة", "أسرة", "العائلة"], ["usra", "usrah"]),
    ("mother", "parents", ["mother", "motherhood"], ["الأم", "الأمومة"], []),
    ("father", "parents", ["father", "fatherhood"], ["الأب", "الأبوة"], []),
    ("murabbi", "murabbi", ["educator", "mentor", "murabbi", "tutor"], ["المربي", "مربي", "المربين"], ["murabbi", "murabbiyah"]),
    ("teacher", "murabbi", ["teacher", "teachers", "instructor"], ["المعلم", "المعلمين", "المدرس"], ["muallim", "mu'allim"]),
    ("trainer", "murabbi", ["trainer", "training", "coach"], ["المدرب", "التدريب"], []),
    ("character", None, ["character", "morals", "manners", "ethics"], ["الأخلاق", "الخلق", "الآداب"], ["akhlaq", "adab", "khuluq"]),
    ("values", None, ["values"], ["القيم", "قيم"], ["qiyam"]),
    ("curriculum", None, ["curriculum", "curricula", "syllabus"], ["المنهج", "المناهج", "منهاج"], ["manhaj"]),
    ("teaching-methods", "murabbi", ["teaching methods", "pedagogy"], ["طرق التدريس", "أساليب التدريس"], []),
    ("development", "children", ["development", "growth"], ["النمو", "نمو"], []),
    ("discipline", None, ["discipline", "punishment", "reward"], ["التأديب", "العقاب", "الثواب"], ["ta'dib", "tadib"]),
    ("quran", "children", ["quran", "qur'an", "koran"], ["القرآن", "القران"], ["quran"]),
    ("memorization", "children", ["memorization", "memorisation", "hifz"], ["الحفظ", "تحفيظ", "حفظ"], ["hifz", "tahfiz", "tahfeez"]),
    ("prophetic", None, ["prophetic", "sunnah", "prophet"], ["النبوي", "النبوية", "السنة", "النبي"], ["sunnah", "nabawi"]),
    ("worship", None, ["worship", "prayer", "salah"], ["العبادة", "الصلاة"], ["ibadah", "salah", "salat"]),
    ("faith", None, ["faith", "belief", "iman"], ["الإيمان", "العقيدة"], ["iman", "aqidah"]),
    ("communication", "parents", ["communication", "dialogue", "listening", "talk with"],
     ["الحوار", "التواصل", "الإصغاء", "حوار", "أحاور", "نحاور", "تحاور", "محاورة", "أتحدث", "التحدث"], ["hiwar"]),
    ("offspring", "parents", ["sons", "offspring", "my children", "kids"],
     ["الأبناء", "أبناء", "أبنائي", "أبناءنا", "الأولاد", "أولاد", "أولادي", "ابني", "ابنتي", "الذرية"], ["abna", "awlad"]),
    ("raising", "parents", ["raising", "raise", "bringing up", "rearing"],
     ["تربية", "أربي", "نربي", "يربي", "تنشئة", "تنشئه"], []),
    ("play", "children", ["play", "games"], ["اللعب", "الألعاب"], []),
    ("story", "children", ["story", "stories", "storytelling"], ["القصة", "القصص"], ["qissa"]),
    ("competency", "murabbi", ["competency", "competencies", "competence"], ["الكفايات", "الكفاءة", "الكفاءات"], []),
    ("mentoring", "murabbi", ["mentoring", "mentorship", "guidance"], ["الإرشاد", "التوجيه"], ["irshad"]),
    ("study-circle", "murabbi", ["study circle", "halaqa"], ["الحلقة", "الحلقات"], ["halaqa", "halaqah"]),
    ("school", None, ["school", "schools"], ["المدرسة", "المدارس"], ["madrasa", "madrasah"]),
    ("early-childhood", "children", ["early childhood", "preschool", "kindergarten"], ["الطفولة المبكرة", "رياض الأطفال", "الروضة"], []),
    ("emotions", "children", ["emotions", "emotional"], ["الانفعالات", "المشاعر", "العاطفة"], []),
    ("research", None, ["research", "study", "studies"], ["بحث", "دراسة", "الدراسات"], []),
]

# Age bands used in coverage/gap analysis
AGE_GROUPS = {
    "0-2": {"en": ["infant", "infancy", "toddler", "newborn", "0-2"], "ar": ["الرضيع", "الرضاعة", "المهد"]},
    "3-6": {"en": ["preschool", "kindergarten", "early childhood", "3-6"], "ar": ["الطفولة المبكرة", "رياض الأطفال", "الروضة", "ما قبل المدرسة"]},
    "7-12": {"en": ["primary school", "elementary", "middle childhood", "7-12"], "ar": ["المرحلة الابتدائية", "الطفولة المتأخرة", "الطفولة الوسطى"]},
    "13-18": {"en": ["adolescent", "adolescence", "teen", "teenager", "secondary school", "youth"], "ar": ["المراهقة", "المراهقين", "المرحلة الثانوية", "الشباب", "البلوغ"]},
}

DEFAULT_OBJECTIVES = [
    ("Evidence on Islamic upbringing methods for children by developmental stage",
     "Collect classical and contemporary sources, and empirical research, on how to nurture faith, character "
     "and learning in children at each developmental stage.", ["children"]),
    ("Practical, evidence-informed guidance for Muslim parents and families",
     "Collect parenting approaches, parent education programs and family-relationship guidance, distinguishing "
     "scriptural foundations, scholarly opinion and empirical findings.", ["parents"]),
    ("Murabbi competencies, training programs and training-of-trainers methods",
     "Map competency frameworks, educator-development pathways, training manuals and institutional programs "
     "for Tarbiyah educators and mentors.", ["murabbi"]),
]
