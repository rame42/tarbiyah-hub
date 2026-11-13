import { useEffect, useMemo, useRef, useState } from "react";
import { HashRouter, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api";
import { useAsync } from "./components";
import { I18n, I18nContext, Lang, TKey, applyDocumentLang, loadLang, storeLang, translate, translateValue, useI18n } from "./i18n";
import Dashboard from "./pages/Dashboard";
import History from "./pages/History";
import Library from "./pages/Library";
import Clean from "./pages/Clean";
import YouTube from "./pages/YouTube";
import Topics from "./pages/Topics";
import Review from "./pages/Review";
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

type NavItem = { to: string; key: TKey; short?: TKey };
const NAV_GROUPS: { key: TKey; items: NavItem[] }[] = [
  { key: "nav_group_today", items: [
    { to: "/", key: "nav_dashboard", short: "nav_dashboard_short" },
    { to: "/review", key: "nav_review" },
    { to: "/history", key: "nav_history" },
  ] },
  { key: "nav_group_library", items: [
    { to: "/library", key: "nav_library" },
    { to: "/files", key: "nav_files" },
    { to: "/courses", key: "nav_courses" },
    { to: "/kids", key: "nav_kids", short: "nav_kids_short" },
    { to: "/clean", key: "nav_clean" },
  ] },
  { key: "nav_group_collect", items: [
    { to: "/my-sources", key: "nav_my_sources" },
    { to: "/youtube", key: "nav_youtube" },
    { to: "/sources", key: "nav_sources" },
  ] },
  { key: "nav_group_research", items: [
    { to: "/research", key: "nav_research" },
    { to: "/topics", key: "nav_topics" },
    { to: "/questions", key: "nav_questions" },
    { to: "/assistant", key: "nav_assistant" },
    { to: "/outputs", key: "nav_outputs" },
    { to: "/entities", key: "nav_entities" },
    { to: "/glossary", key: "nav_glossary" },
  ] },
  { key: "nav_group_system", items: [
    { to: "/jobs", key: "nav_jobs" },
    { to: "/settings", key: "nav_settings" },
  ] },
];
const ALL_NAV = NAV_GROUPS.flatMap((g) => g.items.map((i) => ({ ...i, group: g.key })));

function currentNav(pathname: string) {
  const exact = ALL_NAV.find((n) => n.to === pathname);
  if (exact) return exact;
  const prefix: Record<string, string> = { resources: "/library", questions: "/questions", outputs: "/outputs", entities: "/entities", day: "/" };
  const seg = pathname.split("/")[1] || "";
  return ALL_NAV.find((n) => n.to === (prefix[seg] ?? "/")) ?? ALL_NAV[0];
}

// ---------------------------------------------------------------- theme

type Theme = "system" | "light" | "dark";
const THEME_KEY = "tarbiyah_ui_theme";
function loadTheme(): Theme {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage unavailable */
  }
  return "system";
}
function applyTheme(th: Theme) {
  if (th === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", th);
}

// ---------------------------------------------------------------- automation status (sidebar footer)

interface ShellStatus {
  worker?: { alive?: boolean };
  automation?: { enabled?: boolean; paused?: boolean };
}

function StatusLine() {
  const { t } = useI18n();
  const st = useAsync(() => api.get<ShellStatus>("/api/status"), [], 30000);
  const d = st.data;
  if (!d) return null;
  const [tone, label] = !d.automation?.enabled ? ["muted", t("status_off")]
    : d.automation?.paused ? ["warn", t("status_paused")]
    : !d.worker?.alive ? ["bad", t("status_stopped")]
    : ["good", t("status_running")];
  return (
    <NavLink to="/research" className="side-status" title={t("nav_research")}>
      <span className={`dot dot-${tone}`} aria-hidden="true" />
      {label}
    </NavLink>
  );
}

// ---------------------------------------------------------------- command palette (Ctrl/⌘ K)

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQ("");
      setIdx(0);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const needle = q.trim().toLowerCase();
  const pages = ALL_NAV.filter((n) => !needle || [translate("en", n.key), translate("ar", n.key), n.to]
    .some((s) => s.toLowerCase().includes(needle)));
  const items: { label: string; meta: string; go: () => void }[] = [
    ...pages.map((n) => ({ label: t(n.key), meta: t(n.group), go: () => navigate(n.to) })),
    ...(needle ? [{ label: `${t("cmd_search_library")} “${q.trim()}”`, meta: t("nav_library"),
      go: () => navigate(`/library?q=${encodeURIComponent(q.trim())}`) }] : []),
  ];
  const sel = Math.min(idx, Math.max(0, items.length - 1));

  if (!open) return null;
  const choose = (i: number) => {
    items[i]?.go();
    onClose();
  };
  return (
    <div className="cmdk-backdrop" onMouseDown={onClose}>
      <div className="cmdk" role="dialog" aria-modal="true" aria-label={t("cmd_open")} onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          autoFocus
          className="cmdk-input"
          value={q}
          placeholder={t("cmd_placeholder")}
          aria-label={t("cmd_open")}
          onChange={(e) => {
            setQ(e.target.value);
            setIdx(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(items.length - 1, i + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(0, i - 1)); }
            else if (e.key === "Enter") { e.preventDefault(); choose(sel); }
            else if (e.key === "Escape") onClose();
          }}
        />
        <ul className="cmdk-list" role="listbox">
          {items.length === 0 ? <li className="cmdk-empty">{t("cmd_none")}</li> : null}
          {items.map((it, i) => (
            <li key={i} role="option" aria-selected={i === sel} className={i === sel ? "cmdk-item active" : "cmdk-item"}
              onMouseEnter={() => setIdx(i)} onClick={() => choose(i)}>
              <span dir="auto">{it.label}</span>
              <span className="cmdk-meta">{it.meta}</span>
            </li>
          ))}
        </ul>
        <div className="cmdk-foot">{t("cmd_hint")}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- shell

function Shell() {
  const [lang, setLangState] = useState<Lang>(loadLang);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [menuOpen, setMenuOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const location = useLocation();

  useEffect(() => applyDocumentLang(lang), [lang]);
  useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((x) => !x);
      } else if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
  const here = currentNav(location.pathname);
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  return (
    <I18nContext.Provider value={i18n}>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className={`shell ${menuOpen ? "menu-open" : ""}`}>
        <aside id="sidenav" className="sidenav" aria-label={t("menu")}>
          <div className="side-brand">
            <span className="brand-mark" aria-hidden="true">ت</span>
            <span className="brand-text">
              <span className="brand-name">{t("app_name")}</span>
              <span className="brand-tag">{t("app_tagline")}</span>
            </span>
          </div>
          <button type="button" className="side-search" onClick={() => setCmdOpen(true)}>
            <span>{t("cmd_open")}</span>
            <kbd>{mac ? "⌘" : "Ctrl"} K</kbd>
          </button>
          <nav className="side-nav">
            {NAV_GROUPS.map((g) => (
              <div className="nav-group" key={g.key}>
                <div className="nav-group-label">{t(g.key)}</div>
                {g.items.map((n) => (
                  <NavLink key={n.to} to={n.to} end={n.to === "/"} title={t(n.key)}
                    className={({ isActive }) => (isActive || (here.to === n.to && n.to !== "/") ? "nav-link active" : "nav-link")}>
                    {t(n.short ?? n.key)}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="side-foot">
            <StatusLine />
            <div className="side-prefs">
              <label>
                <span className="sr-only">{t("language")}</span>
                <select value={lang} onChange={(e) => i18n.setLang(e.target.value as Lang)} aria-label={t("language")}>
                  <option value="en">English</option>
                  <option value="ar">العربية</option>
                </select>
              </label>
              <label>
                <span className="sr-only">{t("theme")}</span>
                <select value={theme} onChange={(e) => setTheme(e.target.value as Theme)} aria-label={t("theme")}>
                  <option value="system">{t("theme_system")}</option>
                  <option value="light">{t("theme_light")}</option>
                  <option value="dark">{t("theme_dark")}</option>
                </select>
              </label>
            </div>
          </div>
        </aside>
        <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />
        <div className="workspace">
          <header className="topbar">
            <button type="button" className="icon-btn menu-btn" aria-expanded={menuOpen} aria-controls="sidenav" onClick={() => setMenuOpen((x) => !x)}>
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M2 4.5h14M2 9h14M2 13.5h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
              <span className="sr-only">{t("menu")}</span>
            </button>
            <nav className="crumbs" aria-label="Breadcrumb">
              {t(here.group) !== t(here.short ?? here.key) ? (
                <>
                  <span className="crumb-group">{t(here.group)}</span>
                  <span className="crumb-sep" aria-hidden="true">/</span>
                </>
              ) : null}
              <NavLink to={here.to} end className="crumb-page">{t(here.short ?? here.key)}</NavLink>
            </nav>
            <button type="button" className="icon-btn top-search" onClick={() => setCmdOpen(true)} aria-label={t("cmd_open")}>
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.75" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
            </button>
          </header>
          <main className="main" id="main">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/day/:day" element={<Dashboard />} />
              <Route path="/history" element={<History />} />
              <Route path="/library" element={<Library />} />
              <Route path="/clean" element={<Clean />} />
              <Route path="/my-sources" element={<MySources />} />
              <Route path="/youtube" element={<YouTube />} />
              <Route path="/review" element={<Review />} />
              <Route path="/kids" element={<KidsCorner />} />
              <Route path="/files" element={<Files />} />
              <Route path="/courses" element={<Courses />} />
              <Route path="/resources/:id" element={<ResourceDetail />} />
              <Route path="/research" element={<Research />} />
              <Route path="/topics" element={<Topics />} />
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
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
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
