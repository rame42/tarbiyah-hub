import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ResourceBrief } from "../api";
import { ActionButton, Async, Badge, Card, ErrorBox, fmtDate, fmtNum, ResourceItem, useAsync } from "../components";
import { useI18n } from "../i18n";

interface MySource {
  id: number; key: string; adapter: string; name: string; enabled: boolean; health: string; last_error: string | null;
  last_run_at: string | null; next_run_at: string | null; config: Record<string, unknown>; mine: boolean;
  added_by: string; suggested_because?: string | null; collect_everything: boolean; items: number; archived: number;
  history_done: boolean; recent: ResourceBrief[]; adapter_info?: { label?: string } | null;
}
interface Suggestion {
  key: string; adapter: string; name: string; link: string; mentions: number; avg_relevance: number; score: number;
  from_sources: string[];
}
interface MyResponse {
  sources: MySource[]; suggestions: Suggestion[]; suggestions_updated_at: string | null;
  auto_add_sources: boolean; auto_add_min_mentions: number;
}

const KIND: Record<string, string> = { youtube: "YouTube", telegram: "Telegram", web_crawler: "Website", rss: "RSS / podcast" };

export default function MySources() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<MyResponse>("/api/my-sources"), []);
  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("nav_my_sources")}</h1>
        <Link className="btn btn-primary" to="/sources">{t("add_my_source")}</Link>
      </div>
      <p className="muted">{t("my_sources_intro")}</p>
      <Async state={state}>
        {(d) => (
          <>
            <BulkWebsites reload={state.reload} />
            <Suggestions d={d} reload={state.reload} />
            {!d.sources.length ? <Card><p className="muted">{t("my_sources_empty")}</p></Card> : null}
            {d.sources.map((s) => <SourceCard key={s.id} s={s} reload={state.reload} />)}
          </>
        )}
      </Async>
    </div>
  );
}

function SourceCard({ s, reload }: { s: MySource; reload: () => void }) {
  const { t } = useI18n();
  const run = (f: () => Promise<unknown>) => async () => { const r = await f(); reload(); return r; };
  return (
    <Card title={<span dir="auto">{s.name}</span>}
      actions={<span className="res-meta">
        <span className="badge badge-neutral">{KIND[s.adapter] || s.adapter_info?.label || s.adapter}</span>
        <Badge value={s.health} />
        {s.added_by === "auto" ? <span className="badge badge-info">{t("added_automatically")}</span> : null}
        {!s.enabled ? <span className="badge badge-muted">{t("disabled")}</span> : null}
      </span>}>
      {s.suggested_because ? <p className="small muted">{t("suggested_because")}: {s.suggested_because}</p> : null}
      <div className="stats-row">
        <Link to={`/library?source=${encodeURIComponent(s.key)}`} className="stat-link"><div className="stat"><div className="stat-value">{fmtNum(s.items)}</div><div className="stat-label">{t("my_items")}</div></div></Link>
        <Link to={`/library?source=${encodeURIComponent(s.key)}&view=archived`} className="stat-link"><div className="stat"><div className="stat-value">{fmtNum(s.archived)}</div><div className="stat-label">{t("archived_items")}</div></div></Link>
        <div className="stat"><div className="stat-value small">{fmtDate(s.last_run_at) || "—"}</div><div className="stat-label">{t("last_run")}</div></div>
        <div className="stat"><div className="stat-value small">{fmtDate(s.next_run_at) || "—"}</div><div className="stat-label">{t("next_run")}</div></div>
      </div>
      {s.last_error ? <ErrorBox error={s.last_error} /> : null}
      {s.history_done ? <p className="small">✓ {t("history_done")}</p> : null}
      <div className="toolbar spaced">
        <ActionButton className="btn btn-primary btn-small" onRun={run(() => api.post(`/api/sources/${s.id}/run`))}>{t("run_now")}</ActionButton>
        <ActionButton className="btn btn-small" onRun={run(() => api.patch(`/api/sources/${s.id}`, { enabled: !s.enabled }))}>{s.enabled ? t("disable_source") : t("enable_source")}</ActionButton>
        {s.mine ? (
          <label className="check" title={t("keep_everything_help")}>
            <input type="checkbox" checked={s.collect_everything}
              onChange={async (e) => { await api.post(`/api/my-sources/${s.id}/keep-everything`, { on: e.target.checked }); reload(); }} />
            {t("keep_everything")}
          </label>
        ) : <span className="small muted">{t("auto_source_filtered")}</span>}
        <Link className="btn btn-ghost btn-small" to="/sources">{t("edit_settings")}</Link>
      </div>
      {Array.isArray(s.config.keywords) && (s.config.keywords as unknown[]).length ? <ApplyKeywords id={s.id} reload={reload} /> : null}
      {s.recent.length ? (
        <details>
          <summary className="small">{t("latest_from_source")}</summary>
          <div className="res-list">{s.recent.map((r) => <div key={r.id} className="res-result"><ResourceItem r={r} /></div>)}</div>
        </details>
      ) : null}
    </Card>
  );
}

function Suggestions({ d, reload }: { d: MyResponse; reload: () => void }) {
  const { t } = useI18n();
  const [min, setMin] = useState(String(d.auto_add_min_mentions));
  const act = (path: string, key: string) => async () => { const r = await api.post(path, { key }); reload(); return r; };
  return (
    <Card title={t("suggested_sources")}
      actions={<ActionButton className="btn btn-small" onRun={async () => { const r = await api.post("/api/suggestions/refresh"); reload(); return r; }}>{t("look_for_similar")}</ActionButton>}>
      <p className="small">{t("suggestions_intro")}</p>
      {!d.suggestions.length ? <p className="small muted">{t("no_suggestions")}</p> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>{t("suggested_source")}</th><th>{t("mentions")}</th><th>{t("avg_relevance")}</th><th>{t("found_in")}</th><th /></tr></thead>
            <tbody>
              {d.suggestions.map((x) => (
                <tr key={x.key}>
                  <td dir="auto"><span className="badge badge-neutral">{KIND[x.adapter] || x.adapter}</span>{" "}
                    <a href={x.link} target="_blank" rel="noopener noreferrer">{x.name} ↗</a></td>
                  <td>{fmtNum(x.mentions)}</td>
                  <td>{x.avg_relevance}</td>
                  <td className="small" dir="auto">{x.from_sources.join(", ")}</td>
                  <td className="nowrap">
                    <ActionButton className="btn btn-primary btn-small" onRun={act("/api/suggestions/add", x.key)}>{t("add")}</ActionButton>{" "}
                    <ActionButton className="btn btn-small" onRun={act("/api/suggestions/dismiss", x.key)}>{t("dismiss")}</ActionButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="toolbar spaced">
        <label className="check">
          <input type="checkbox" checked={d.auto_add_sources}
            onChange={async (e) => { await api.patch("/api/settings", { auto_add_sources: e.target.checked }); reload(); }} />
          {t("auto_add_sources")}
        </label>
        <label className="field inline-field"><span>{t("auto_add_min")}</span>
          <input type="number" min={2} max={100} value={min} onChange={(e) => setMin(e.target.value)}
            onBlur={async () => { await api.patch("/api/settings", { auto_add_min_mentions: Math.max(2, Number(min) || 5) }); reload(); }} />
        </label>
      </div>
      {d.suggestions_updated_at ? <p className="small muted">{t("updated")}: {fmtDate(d.suggestions_updated_at)}</p> : null}
    </Card>
  );
}

function ApplyKeywords({ id, reload }: { id: number; reload: () => void }) {
  const { t } = useI18n();
  const [prev, setPrev] = useState<{ would_archive: number; examples: { id: number; title: string }[] } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const call = async (dry: boolean) => {
    const r = await api.post<{ would_archive?: number; archived?: number; examples?: { id: number; title: string }[] }>(
      `/api/my-sources/${id}/apply-keywords`, { dry_run: dry });
    if (dry) setPrev({ would_archive: r.would_archive || 0, examples: r.examples || [] });
    else { setPrev(null); setMsg(`${t("archived_n")} ${fmtNum(r.archived || 0)}`); reload(); }
    return r;
  };
  return (
    <div className="small">
      <ActionButton className="btn btn-small" onRun={() => call(true)}>{t("apply_keywords")}</ActionButton>
      {prev ? (
        <div className="alert alert-warn">
          <p><strong>{fmtNum(prev.would_archive)}</strong> {t("apply_keywords_preview")}</p>
          <ul>{prev.examples.map((x) => <li key={x.id} dir="auto"><Link to={`/resources/${x.id}`}>{x.title}</Link></li>)}</ul>
          {prev.would_archive ? <ActionButton className="btn btn-primary btn-small" onRun={() => call(false)}>{t("archive_now")}</ActionButton> : null}
        </div>
      ) : null}
      {msg ? <span role="status"> {msg}</span> : null}
    </div>
  );
}

function BulkWebsites({ reload }: { reload: () => void }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [kw, setKw] = useState(true);
  const [section, setSection] = useState(false);
  const [res, setRes] = useState<{ created: string[]; skipped: string[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const urls = text.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean);
  const add = async () => {
    setErr(null);
    try {
      const r = await api.post<{ created: string[]; skipped: string[] }>("/api/my-sources/bulk-websites",
        { urls, pillar_keywords: kw, stay_in_section: section });
      setRes(r);
      if (r.created.length) { setText(""); reload(); }
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Card title={t("bulk_sites_title")}>
      <details>
        <summary className="small">{t("bulk_sites_open")}</summary>
        <p className="small">{t("bulk_sites_intro")}</p>
        <textarea dir="ltr" rows={6} className="full-width" value={text} onChange={(e) => setText(e.target.value)}
          placeholder={"https://yaqeeninstitute.org/topic/family-community\nhttps://islamonline.net/\nexample.org"} />
        <div className="toolbar spaced">
          <label className="check"><input type="checkbox" checked={kw} onChange={(e) => setKw(e.target.checked)} />{t("bulk_sites_kw")}</label>
          <label className="check" title={t("bulk_sites_section_help")}><input type="checkbox" checked={section} onChange={(e) => setSection(e.target.checked)} />{t("bulk_sites_section")}</label>
          <button type="button" className="btn btn-primary" disabled={!urls.length} onClick={add}>{t("bulk_sites_add")} ({urls.length})</button>
        </div>
        {err ? <p className="small text-error">{err}</p> : null}
        {res ? (
          <div className="small" role="status">
            {res.created.length ? <p>✓ {t("bulk_sites_added")}: {res.created.join(", ")}</p> : null}
            {res.skipped.length ? <p className="muted">{t("bulk_sites_skipped")}: {res.skipped.join(" · ")}</p> : null}
          </div>
        ) : null}
      </details>
    </Card>
  );
}
