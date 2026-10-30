import { useEffect, useMemo, useState } from "react";
import { HashRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { I18n, I18nContext, Lang, TKey, applyDocumentLang, loadLang, storeLang, translate, translateValue } from "./i18n";
import Dashboard from "./pages/Dashboard";
import History from "./pages/History";
import Library from "./pages/Library";
import Clean from "./pages/Clean";
import KidsCorner from "./pages/KidsCorner";
import MySources from "./pages/MySources";
import Courses from "./pages/Courses";
import Files from "./pages/Files";
import ResourceDetail from "./pages/ResourceDetail";
import Research from "./pages/Research";
import Questions from "./pages/Questions";
import QuestionDetail from "./pages/QuestionDetail";
import Assistant from "./pages/Assistant";
import Sources from "./pages/Sources";
import Jobs from "./pages/Jobs";
import Outputs from "./pages/Outputs";
import Settings from "./pages/Settings";
import Entities from "./pages/Entities";
import EntityDetail from "./pages/EntityDetail";
import Glossary from "./pages/Glossary";

const NAV: [string, TKey][] = [
  ["/", "nav_dashboard"],
  ["/history", "nav_history"],
  ["/library", "nav_library"],
  ["/my-sources", "nav_my_sources"],
  ["/kids", "nav_kids"],
  ["/clean", "nav_clean"],
  ["/files", "nav_files"],
  ["/courses", "nav_courses"],
  ["/research", "nav_research"],
  ["/questions", "nav_questions"],
  ["/assistant", "nav_assistant"],
  ["/sources", "nav_sources"],
  ["/jobs", "nav_jobs"],
  ["/outputs", "nav_outputs"],
  ["/entities", "nav_entities"],
  ["/glossary", "nav_glossary"],
  ["/settings", "nav_settings"],
];

function Shell() {
  const [lang, setLangState] = useState<Lang>(loadLang);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => applyDocumentLang(lang), [lang]);
  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);

  const i18n: I18n = useMemo(
    () => ({
      lang,
      setLang: (l: Lang) => {
        storeLang(l);
        setLangState(l);
      },
      t: (k: TKey) => translate(lang, k),
      v: (x) => translateValue(lang, x),
    }),
    [lang],
  );
  const { t } = i18n;

  return (
    <I18nContext.Provider value={i18n}>
      <div className="shell">
        <header className="topbar">
          <button type="button" className="btn btn-ghost menu-btn" aria-expanded={menuOpen} aria-controls="sidenav" onClick={() => setMenuOpen((x) => !x)}>
            ☰ <span className="sr-only">{t("menu")}</span>
          </button>
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">ت</span>
            <span>
              <span className="brand-name">{t("app_name")}</span>
              <span className="brand-tag">{t("app_tagline")}</span>
            </span>
          </div>
          <label className="lang-select">
            <span className="sr-only">{t("language")}</span>
            <select value={lang} onChange={(e) => i18n.setLang(e.target.value as Lang)} aria-label={t("language")}>
              <option value="en">English</option>
              <option value="ar">العربية</option>
            </select>
          </label>
        </header>
        <div className="body">
          <nav id="sidenav" className={`sidenav ${menuOpen ? "open" : ""}`} aria-label={t("menu")}>
            {NAV.map(([to, key]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
                {t(key)}
              </NavLink>
            ))}
          </nav>
          <main className="main">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/day/:day" element={<Dashboard />} />
              <Route path="/history" element={<History />} />
              <Route path="/library" element={<Library />} />
              <Route path="/clean" element={<Clean />} />
              <Route path="/my-sources" element={<MySources />} />
              <Route path="/kids" element={<KidsCorner />} />
              <Route path="/files" element={<Files />} />
              <Route path="/courses" element={<Courses />} />
              <Route path="/resources/:id" element={<ResourceDetail />} />
              <Route path="/research" element={<Research />} />
              <Route path="/questions" element={<Questions />} />
              <Route path="/questions/:id" element={<QuestionDetail />} />
              <Route path="/assistant" element={<Assistant />} />
              <Route path="/sources" element={<Sources />} />
              <Route path="/jobs" element={<Jobs />} />
              <Route path="/outputs" element={<Outputs />} />
              <Route path="/outputs/:id" element={<Outputs />} />
              <Route path="/entities" element={<Entities />} />
              <Route path="/entities/:id" element={<EntityDetail />} />
              <Route path="/glossary" element={<Glossary />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Dashboard />} />
            </Routes>
          </main>
        </div>
      </div>
    </I18nContext.Provider>
  );
}

export default function App() {
  return (
    <HashRouter>
      <Shell />
    </HashRouter>
  );
}
