import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, qs, Question } from "../api";
import { Async, Badge, Card, ErrorBox, fmtDate, fmtNum, PillarBadges, useAsync } from "../components";
import { useI18n } from "../i18n";
import { PillarChecks } from "./Research";

export const QUESTION_STATUSES = ["open", "investigating", "answered", "unresolved", "deferred", "duplicate", "not_relevant"];
export const QUESTION_KINDS = ["planner", "gap", "coverage", "entity", "entity_followup", "citation_followup", "terminology"];

export default function Questions() {
  const { t, v } = useI18n();
  const [sp, setSp] = useSearchParams();
  const status = sp.get("status") || "";
  const pillar = sp.get("pillar") || "";
  const kind = sp.get("kind") || "";
  const q = sp.get("q") || "";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);
  const state = useAsync(
    () => api.get<{ total: number; counts: Record<string, number>; questions: Question[] }>(`/api/questions${qs({ status, pillar, kind, q, limit: 200 })}`),
    [status, pillar, kind, q],
  );
  const set = (k: string, val: string) => {
    const n = new URLSearchParams(sp);
    if (val) n.set(k, val);
    else n.delete(k);
    setSp(n);
  };
  const counts = state.data?.counts || {};
  const allCount = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="page">
      <div className="page-head"><h1>{t("questions_title")}</h1></div>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={!status} className={`tab ${!status ? "active" : ""}`} onClick={() => set("status", "")}>
          {t("all")} <span className="tab-count">{allCount}</span>
        </button>
        {QUESTION_STATUSES.map((s) => (
          <button type="button" role="tab" aria-selected={status === s} key={s} className={`tab ${status === s ? "active" : ""}`} onClick={() => set("status", s)}>
            {v(s)} <span className="tab-count">{counts[s] || 0}</span>
          </button>
        ))}
      </div>
      <Card>
        <form className="filter-row" onSubmit={(e) => { e.preventDefault(); set("q", draft.trim()); }}>
          <input type="search" dir="auto" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("filter_text")} aria-label={t("filter_text")} />
          <select value={pillar} onChange={(e) => set("pillar", e.target.value)} aria-label={t("pillar")}>
            <option value="">{t("pillar")}: {t("all")}</option>
            {["children", "parents", "murabbi"].map((p) => <option key={p} value={p}>{t(`pillar_${p}` as "pillar_children")}</option>)}
          </select>
          <select value={kind} onChange={(e) => set("kind", e.target.value)} aria-label={t("kind")}>
            <option value="">{t("kind")}: {t("all")}</option>
            {QUESTION_KINDS.map((k) => <option key={k} value={k}>{v(k)}</option>)}
          </select>
          <button type="submit" className="btn">{t("search")}</button>
        </form>
      </Card>

      <Async state={state}>
        {(d) => (
          <Card title={`${fmtNum(d.total)} ${t("questions_by_status")}`}>
            {d.questions.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
              <div className="q-list">
                {d.questions.map((x) => <QuestionCard key={x.id} q={x} />)}
              </div>
            )}
          </Card>
        )}
      </Async>
      <AddQuestion onAdded={state.reload} />
    </div>
  );
}

export function QuestionCard({ q }: { q: Question }) {
  const { t, v } = useI18n();
  return (
    <div className="q-card">
      <div className="q-head">
        <Link to={`/questions/${q.id}`} dir="auto" className="q-text content-text">{q.text}</Link>
      </div>
      {q.text_alt ? <div className="muted" dir="auto">{q.text_alt}</div> : null}
      <div className="res-meta">
        <Badge value={q.status} />
        <Badge value={q.kind} tone="neutral" />
        <PillarBadges pillars={q.pillars} />
        <span className="small">{t("priority")}: <strong>{fmtNum(q.priority, 2)}</strong></span>
        <span className="small">{t("created_by")}: {v(q.created_by)}</span>
        <span className="muted small">{fmtDate(q.created_at)}</span>
      </div>
      {q.rationale ? <p className="small rationale" dir="auto">{q.rationale}</p> : null}
    </div>
  );
}

function AddQuestion({ onAdded }: { onAdded: () => void }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const [text, setText] = useState("");
  const [alt, setAlt] = useState("");
  const [pillars, setPillars] = useState<string[]>([]);
  const [now, setNow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [added, setAdded] = useState<number | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setAdded(null);
    try {
      const r = await api.post<{ id: number }>("/api/questions", { text: text.trim(), text_alt: alt.trim() || null, pillars, investigate_now: now });
      setAdded(r.id);
      setText("");
      setAlt("");
      onAdded();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={t("add_question")}>
      <form onSubmit={submit} className="form-stack">
        <label className="field"><span>{t("question_text")} *</span><textarea dir="auto" required rows={2} value={text} onChange={(e) => setText(e.target.value)} /></label>
        <label className="field"><span>{t("question_text_alt")}</span><textarea dir="auto" rows={2} value={alt} onChange={(e) => setAlt(e.target.value)} /></label>
        <PillarChecks value={pillars} onChange={setPillars} />
        <label className="check"><input type="checkbox" checked={now} onChange={(e) => setNow(e.target.checked)} />{t("investigate_now")}</label>
        <div><button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>{busy ? "…" : ""}{t("add")}</button></div>
        <ErrorBox error={err} />
        {added ? (
          <div className="alert alert-ok" role="status">
            {t("question_added")}{added} — <button type="button" className="linklike" onClick={() => nav(`/questions/${added}`)}>{t("view")}</button>
          </div>
        ) : null}
      </form>
    </Card>
  );
}
