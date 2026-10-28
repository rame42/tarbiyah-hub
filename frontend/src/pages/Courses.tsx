import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, ResourceBrief } from "../api";
import { ActionButton, Async, Card, ErrorBox, fmtNum, PillarBadges, RelevanceBadge, useAsync } from "../components";
import { useI18n } from "../i18n";

interface Course extends ResourceBrief { provider: string | null; price: string | null; currency: string | null;
  purchase_url: string | null; description: string | null }
interface CoursesResponse { total: number; page: number; page_size: number; counts: { all: number; free: number; paid: number }; items: Course[] }

const PAGE = 30;
const FREE = ["free_to_read", "open_access", "open_license", "public_domain"];

export default function Courses() {
  const { t } = useI18n();
  const [price, setPrice] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const key = JSON.stringify([price, q, page]);
  const state = useAsync(() => api.get<CoursesResponse>(`/api/courses?${new URLSearchParams({ price, q, page: String(page), page_size: String(PAGE) })}`), [key]);

  return (
    <div className="page">
      <div className="page-head"><h1>{t("nav_courses")}</h1></div>
      <p className="muted">{t("courses_intro")}</p>
      <div className="grid-2">
        <AddCourse onAdded={state.reload} />
        <FindCourses />
      </div>
      <Card>
        <div className="toolbar spaced">
          {(["all", "free", "paid"] as const).map((p) => (
            <button key={p} type="button" className={`btn ${price === p ? "btn-primary" : ""}`} onClick={() => { setPrice(p); setPage(1); }}>
              {t(`courses_${p}` as never)}{state.data ? ` (${fmtNum(state.data.counts[p])})` : ""}
            </button>
          ))}
          <input type="search" dir="auto" placeholder={t("search")} value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        </div>
        <Async state={state}>
          {(d) => (
            <>
              {!d.items.length ? <p className="muted">{t("courses_empty")}</p> : null}
              <div className="res-list">
                {d.items.map((c) => (
                  <div key={c.id} className="res-result">
                    <div className="res-title" dir="auto"><Link to={`/resources/${c.id}`}>{c.title}</Link></div>
                    <div className="res-meta">
                      {FREE.includes(c.access_status) ? <span className="badge badge-good">{t("course_free")}</span>
                        : c.access_status === "paid" ? <span className="badge badge-warn">{t("course_paid")}{c.price ? `: ${c.price} ${c.currency || ""}` : ""}</span>
                        : <span className="badge badge-muted">{t("course_price_unknown")}</span>}
                      {c.provider ? <span dir="auto">{c.provider}</span> : null}
                      {c.language ? <span className="badge badge-neutral">{c.language}</span> : null}
                      <PillarBadges pillars={c.pillars} />
                      <RelevanceBadge value={c.relevance} />
                      {c.url ? <a className="btn btn-small" href={c.purchase_url || c.url} target="_blank" rel="noopener noreferrer">{t("open_course")} ↗</a> : null}
                    </div>
                    {c.description ? <p className="snippet-desc" dir="auto">{c.description}</p> : null}
                  </div>
                ))}
              </div>
              <div className="pager">
                <button type="button" className="btn btn-small" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("prev")}</button>
                <span className="small">{page} / {Math.max(1, Math.ceil(d.total / PAGE))}</span>
                <button type="button" className="btn btn-small" disabled={page * PAGE >= d.total} onClick={() => setPage(page + 1)}>{t("next")}</button>
              </div>
            </>
          )}
        </Async>
      </Card>
    </div>
  );
}

function AddCourse({ onAdded }: { onAdded: () => void }) {
  const { t } = useI18n();
  const [f, setF] = useState({ url: "", title: "", provider: "", price: "", currency: "USD", free: "auto" });
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setMsg(null); setErr(null);
    try {
      const r = await api.post<{ created: boolean }>("/api/courses", {
        url: f.url.trim(), title: f.title, provider: f.provider || null,
        free: f.free === "auto" ? null : f.free === "free", price: f.free === "paid" ? f.price || null : null,
        currency: f.free === "paid" ? f.currency : null,
      });
      setMsg(r.created ? t("course_added") : t("course_exists"));
      setF({ ...f, url: "", title: "", provider: "", price: "" });
      onAdded();
    } catch (e2) { setErr((e2 as Error).message); }
  };
  return (
    <Card title={t("add_course")}>
      <form className="form-grid" onSubmit={submit}>
        <label>{t("course_link")} *<input type="url" required dir="ltr" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://" /></label>
        <label>{t("title")}<input dir="auto" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder={t("course_title_auto")} /></label>
        <label>{t("course_provider")}<input dir="auto" value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })} /></label>
        <label>{t("course_price")}
          <select value={f.free} onChange={(e) => setF({ ...f, free: e.target.value })}>
            <option value="auto">{t("course_price_from_page")}</option>
            <option value="free">{t("course_free")}</option>
            <option value="paid">{t("course_paid")}</option>
          </select></label>
        {f.free === "paid" ? <>
          <label>{t("price")}<input value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></label>
          <label>{t("currency")}<input value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })} /></label>
        </> : null}
        <div><button type="submit" className="btn btn-primary">{t("add")}</button></div>
      </form>
      {msg ? <p className="small" role="status">{msg}</p> : null}
      <ErrorBox error={err} />
    </Card>
  );
}

function FindCourses() {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  return (
    <Card title={t("find_courses")}>
      <p className="small">{t("find_courses_text")}</p>
      <div className="toolbar spaced">
        <input dir="auto" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("find_courses_placeholder")} />
        <ActionButton className="btn btn-primary" onRun={() => api.post("/api/courses/find", { query: q || null })}>{t("find_courses_btn")}</ActionButton>
      </div>
      <p className="small muted">{t("course_sites_hint")}</p>
    </Card>
  );
}
