import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ActionButton, Async, Card, ErrorBox, fmtNum, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";

interface Summary {
  active: number;
  unclassified: number;
  unscored: number;
  low_relevance: number;
  below: number;
  archived: number;
  archived_auto: number;
  deleted: number;
  buckets: { from: number; to: number; count: number }[];
  sources: { key: string | null; source_id: number | null; name: string; enabled: boolean | null; items: number;
             avg_relevance: number | null; relevant_pct: number; archived: number }[];
  focus_terms: string[];
  exclude_terms: string[];
  auto_archive_below: number;
  ai_triage: boolean;
  research_trusted_only: boolean;
  ai_screened: number;
  ai_available: boolean;
  job_running: { id: number; checkpoint: Record<string, number> } | null;
}

const lines = (s: string) => s.split(/\r?\n|,|،/).map((x) => x.trim()).filter(Boolean);

export default function Clean() {
  const { t } = useI18n();
  const [below, setBelow] = useState(20);
  const state = useAsync<Summary>(() => api.get<Summary>(`/api/curation?below=${below}`), [below]);
  const running = !!state.data?.job_running;
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => state.reload(), 4000);
    return () => window.clearInterval(id);
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("nav_clean")}</h1>
      </div>
      <p className="muted">{t("clean_intro")}</p>
      <Async state={state}>
        {(d) => (
          <>
            <Overview d={d} />
            <SortStep d={d} reload={state.reload} />
            <ArchiveStep sources={d.sources} below={below} setBelow={setBelow} reload={state.reload} />
            <QualityStep d={d} reload={state.reload} />
            <TeachStep d={d} reload={state.reload} />
            <SourcesStep d={d} reload={state.reload} />
          </>
        )}
      </Async>
    </div>
  );
}

function Stat({ n, label, to }: { n: number; label: string; to?: string }) {
  const body = (
    <div className="stat">
      <div className="stat-value">{fmtNum(n)}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
  return to ? <Link to={to} className="stat-link">{body}</Link> : body;
}

function Overview({ d }: { d: Summary }) {
  const { t } = useI18n();
  const max = Math.max(1, ...d.buckets.map((b) => b.count));
  return (
    <Card title={t("clean_overview")}>
      <div className="stats-row">
        <Stat n={d.active} label={t("active_items")} to="/library" />
        <Stat n={d.unclassified} label={t("unclassified_np")} to="/library?pillar=none" />
        <Stat n={d.low_relevance} label={t("low_relevance_n").replace("{n}", String(d.below))}
          to={`/library?max_relevance=${d.below - 1}&sort=relevance_low`} />
        <Stat n={d.archived} label={`${t("archived_items")} (${d.archived_auto} ${t("archived_auto_n")})`} to="/library?view=archived" />
        {d.unscored ? <Stat n={d.unscored} label={t("not_scored")} /> : null}
      </div>
      <h3 className="small">{t("relevance_spread")}</h3>
      <div className="bars" role="img" aria-label={t("relevance_spread")}>
        {d.buckets.map((b) => (
          <Link key={b.from} className="bar-row" to={`/library?min_relevance=${b.from}&max_relevance=${b.to}`}>
            <span className="bar-label">{b.from}–{b.to}</span>
            <span className="bar-track"><span className={`bar-fill ${b.from >= 40 ? "good" : b.from >= 20 ? "warn" : "bad"}`}
              style={{ inlineSize: `${(100 * b.count) / max}%` }} /></span>
            <span className="bar-num">{fmtNum(b.count)}</span>
          </Link>
        ))}
      </div>
    </Card>
  );
}

function SortStep({ d, reload }: { d: Summary; reload: () => void }) {
  const { t } = useI18n();
  const [ai, setAi] = useState(true);
  const run = (scope: string) => async () => {
    const r = await api.post("/api/curation/rescore", { scope, ai: ai && d.ai_available });
    reload();
    return r;
  };
  const cp = d.job_running?.checkpoint || {};
  return (
    <Card title={t("step1")}>
      <p className="small">{t("step1_text")}</p>
      {d.ai_available ? (
        <label className="check"><input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} />{t("use_ai_too")}</label>
      ) : null}
      <div className="toolbar spaced">
        <ActionButton className="btn btn-primary" onRun={run("unclassified")}>{t("sort_unclassified")} ({fmtNum(d.unclassified)})</ActionButton>
        <ActionButton onRun={run("all")}>{t("rescore_all")}</ActionButton>
        <Link className="btn btn-ghost" to="/library?pillar=none">{t("open_in_library")}</Link>
      </div>
      {d.job_running ? (
        <p className="small" role="status">{t("sorting_running")} {cp.done ? `${fmtNum(cp.done)} ✓ · +${fmtNum(cp.sorted || 0)}` : ""}</p>
      ) : null}
    </Card>
  );
}

function ArchiveStep({ sources, below, setBelow, reload }: { sources: Summary["sources"]; below: number; setBelow: (n: number) => void; reload: () => void }) {
  const { t } = useI18n();
  const [onlyUnc, setOnlyUnc] = useState(false);
  const [source, setSource] = useState("");
  const [preview, setPreview] = useState<{ would_archive: number; examples: { id: number; title: string; relevance: number }[] } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setPreview(null); setMsg(null); }, [below, onlyUnc, source]);
  const call = async (dry: boolean) => {
    setErr(null);
    try {
      const r = await api.post<{ would_archive?: number; archived?: number; examples?: { id: number; title: string; relevance: number }[] }>(
        "/api/curation/archive-low", { below, dry_run: dry, only_unclassified: onlyUnc, source: source || null });
      if (dry) setPreview({ would_archive: r.would_archive || 0, examples: r.examples || [] });
      else { setPreview(null); setMsg(`${t("archived_n")} ${fmtNum(r.archived || 0)}`); reload(); }
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Card title={t("step2")}>
      <p className="small">{t("step2_text")}</p>
      <div className="toolbar spaced">
        <label className="field inline-field">
          <span>{t("archive_below")}</span>
          <input type="number" min={1} max={100} value={below} onChange={(e) => setBelow(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} />
        </label>
        <label className="check"><input type="checkbox" checked={onlyUnc} onChange={(e) => setOnlyUnc(e.target.checked)} />{t("only_unclassified")}</label>
        <label className="field inline-field"><span>{t("source")}</span>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">{t("any")}</option>
            {sources.filter((s) => s.key).map((s) => <option key={s.key!} value={s.key!}>{s.name} ({fmtNum(s.items)})</option>)}
          </select></label>
        <button type="button" className="btn" onClick={() => call(true)}>{t("preview")}</button>
      </div>
      <ErrorBox error={err} />
      {preview ? (
        <div className="alert alert-warn">
          <p><strong>{fmtNum(preview.would_archive)}</strong> {t("would_archive")}</p>
          <ul className="small">
            {preview.examples.map((x) => <li key={x.id} dir="auto"><Link to={`/resources/${x.id}`}>{x.title}</Link> ({x.relevance})</li>)}
          </ul>
          {preview.would_archive ? <button type="button" className="btn btn-primary" onClick={() => call(false)}>{t("archive_now")}</button> : null}
        </div>
      ) : null}
      {msg ? <p className="small" role="status">{msg}</p> : null}
    </Card>
  );
}

function TeachStep({ d, reload }: { d: Summary; reload: () => void }) {
  const { t } = useI18n();
  const [focus, setFocus] = useState(d.focus_terms.join("\n"));
  const [exclude, setExclude] = useState(d.exclude_terms.join("\n"));
  const [auto, setAuto] = useState(String(d.auto_archive_below || 0));
  const save = async () => {
    const r = await api.patch("/api/settings", {
      focus_terms: lines(focus), exclude_terms: lines(exclude), auto_archive_below: Math.max(0, Math.min(100, Number(auto) || 0)),
    });
    reload();
    return r;
  };
  return (
    <Card title={t("step3")}>
      <p className="small">{t("step3_text")}</p>
      <div className="form-grid">
        <label>{t("focus_terms")}<textarea dir="auto" rows={6} value={focus} onChange={(e) => setFocus(e.target.value)}
          placeholder={"تربية الأبناء\nحفظ القرآن\nadolescence"} /></label>
        <label>{t("exclude_terms")}<textarea dir="auto" rows={6} value={exclude} onChange={(e) => setExclude(e.target.value)}
          placeholder={"football\nrecipe\nكرة القدم"} /></label>
        <label>{t("auto_archive_below")}<input type="number" min={0} max={100} value={auto} onChange={(e) => setAuto(e.target.value)} /></label>
      </div>
      <div className="toolbar spaced">
        <ActionButton className="btn btn-primary" onRun={save}>{t("save")}</ActionButton>
      </div>
      <p className="small muted">{t("rescore_after_save")}</p>
    </Card>
  );
}

function SourcesStep({ d, reload }: { d: Summary; reload: () => void }) {
  const { t } = useI18n();
  if (!d.sources.length) return null;
  return (
    <Card title={t("step4")}>
      <p className="small">{t("step4_text")}</p>
      <TableWrap>
        <table className="table">
          <thead>
            <tr><th>{t("source")}</th><th>{t("items")}</th><th>{t("relevant_pct")}</th><th>{t("avg_relevance")}</th><th>{t("archived_items")}</th><th /></tr>
          </thead>
          <tbody>
            {d.sources.map((s) => (
              <tr key={s.key || "?"}>
                <td><Link to={`/library?source=${encodeURIComponent(s.key || "")}&sort=relevance_low`}>{s.name}</Link></td>
                <td>{fmtNum(s.items)}</td>
                <td><span className={`badge badge-${s.relevant_pct >= 50 ? "good" : s.relevant_pct >= 20 ? "warn" : "bad"}`}>{s.relevant_pct}%</span></td>
                <td>{s.avg_relevance ?? "—"}</td>
                <td>{fmtNum(s.archived)}</td>
                <td>
                  {s.source_id && s.enabled !== null ? (
                    <ActionButton className="btn btn-small" onRun={async () => { const r = await api.patch(`/api/sources/${s.source_id}`, { enabled: !s.enabled }); reload(); return r; }}>
                      {s.enabled ? t("disable_source") : t("enable_source")}
                    </ActionButton>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Card>
  );
}

function QualityStep({ d, reload }: { d: Summary; reload: () => void }) {
  const { t } = useI18n();
  const set = (body: Record<string, unknown>) => async () => { const r = await api.patch("/api/settings", body); reload(); return r; };
  const strict = d.ai_triage && d.research_trusted_only && d.auto_archive_below >= 30;
  return (
    <Card title={t("quality_title")}>
      <p className="small">{t("quality_text")}</p>
      {!d.ai_available ? <p className="alert alert-warn small">{t("quality_no_ai")}</p> : null}
      <ul className="small quality-list">
        <li>
          <strong>{t("quality_triage")}</strong>: {d.ai_triage ? t("on") : t("off")} · {fmtNum(d.ai_screened)} {t("quality_screened")}
          {" "}<ActionButton className="btn btn-small" onRun={set({ ai_triage: !d.ai_triage })}>{d.ai_triage ? t("turn_off") : t("turn_on")}</ActionButton>
        </li>
        <li>
          <strong>{t("quality_trusted")}</strong>: {d.research_trusted_only ? t("on") : t("off")}
          {" "}<ActionButton className="btn btn-small" onRun={set({ research_trusted_only: !d.research_trusted_only })}>{d.research_trusted_only ? t("turn_off") : t("turn_on")}</ActionButton>
        </li>
        <li><strong>{t("auto_archive_below")}</strong>: {d.auto_archive_below || t("off")}</li>
      </ul>
      <div className="toolbar spaced">
        {strict ? <span className="badge badge-good">{t("quality_strict_on")}</span> : (
          <ActionButton className="btn btn-primary" onRun={set({ ai_triage: true, research_trusted_only: true, auto_archive_below: 30 })}>
            {t("quality_strict_btn")}
          </ActionButton>
        )}
        <ActionButton onRun={set({ research_trusted_only: false, auto_archive_below: 15 })}>{t("quality_balanced_btn")}</ActionButton>
      </div>
    </Card>
  );
}
