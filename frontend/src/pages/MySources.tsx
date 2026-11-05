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
  strict: StrictCfg; strict_stats: Record<string, number>; precision: number | null; judged: number;
  waiting_check: number; to_review: number;
}
interface StrictCfg {
  enabled: boolean; pillars: string[]; types: string[]; files_only: boolean; site_sections: string[];
  min_score: number; review: boolean; pause_below: number; min_judged: number;
}
interface PreviewItem { title: string; url: string; type: string; site_labels: string[]; score?: number; pillars?: string[]; reason?: string }
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
            <Catalog reload={state.reload} />
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
      {s.adapter === "web_crawler" && s.mine ? <SectionPicker s={s} reload={reload} /> : null}
      {s.mine ? <StrictPanel s={s} reload={reload} /> : null}
      {s.history_done ? <p className="small">✓ {t("history_done")}</p> : null}
      <div className="toolbar spaced">
        <ActionButton className="btn btn-primary btn-small" onRun={run(() => api.post(`/api/sources/${s.id}/run`))}>{t("run_now")}</ActionButton>
        <ActionButton className="btn btn-small" onRun={run(() => api.patch(`/api/sources/${s.id}`, { enabled: !s.enabled }))}>{s.enabled ? t("disable_source") : t("enable_source")}</ActionButton>
        {s.mine && !s.strict.enabled ? (
          <label className="check" title={t("keep_everything_help")}>
            <input type="checkbox" checked={s.collect_everything}
              onChange={async (e) => { await api.post(`/api/my-sources/${s.id}/keep-everything`, { on: e.target.checked }); reload(); }} />
            {t("keep_everything")}
          </label>
        ) : !s.mine ? <span className="small muted">{t("auto_source_filtered")}</span> : null}
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

const KINDS = ["article", "document", "book", "paper", "video", "course", "audio", "social_post"];
const PILLARS3 = ["children", "parents", "murabbi"];

function StrictPanel({ s, reload }: { s: MySource; reload: () => void }) {
  const { t, v } = useI18n();
  const [cfg, setCfg] = useState<StrictCfg>(s.strict);
  const [sections, setSections] = useState(s.strict.site_sections.join(", "));
  const [lock, setLock] = useState(Boolean(s.config.section_lock));
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [prev, setPrev] = useState<{ would_save: PreviewItem[]; would_reject: PreviewItem[]; error: string | null; note: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const isWeb = s.adapter === "web_crawler";
  const toggle = (k: "pillars" | "types", x: string) =>
    setCfg({ ...cfg, [k]: cfg[k].includes(x) ? cfg[k].filter((y) => y !== x) : [...cfg[k], x] });
  const body = () => ({ ...cfg, site_sections: sections.split(/[,،\n]/).map((x) => x.trim()).filter(Boolean) });
  const save = async () => {
    setErr(null); setMsg(null); setBusy(true);
    try {
      if (isWeb && lock !== Boolean(s.config.section_lock)) await api.patch(`/api/sources/${s.id}`, { config: { section_lock: lock } });
      const r = await api.put<{ changed: number }>(`/api/my-sources/${s.id}/strict`, { strict: body() });
      setMsg(`${t("keys_saved")} · ${t("strict_changed")}: ${r.changed}`);
      reload();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const preview = async () => {
    setErr(null); setPrev(null); setBusy(true);
    try {
      setPrev(await api.post(`/api/my-sources/${s.id}/preview`, { strict: body(), config: isWeb ? { section_lock: lock } : {} }));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const st = s.strict_stats || {};
  return (
    <details className="strict-panel" open={s.strict.enabled}>
      <summary>
        <strong>{t("strict_mode")}</strong>{" "}
        {s.strict.enabled ? <span className="badge badge-good">{t("on")}</span> : <span className="badge badge-muted">{t("off")}</span>}
        {s.strict.enabled ? <span className="small muted"> · {t("strict_precision")}: {s.precision ?? "—"}% ({s.judged}) · {t("strict_waiting")}: {s.waiting_check} · <Link to={`/review?source=${s.id}`}>{t("strict_to_review")}: {s.to_review}</Link> · {t("strict_skipped")}: {st.skipped_before_saving || 0}</span> : null}
      </summary>
      <div className="form-stack small">
        <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} /> <strong>{t("strict_enable")}</strong></label>
        {isWeb ? <label className="check"><input type="checkbox" checked={lock} onChange={(e) => setLock(e.target.checked)} /> {t("strict_lock")}</label> : null}
        {isWeb ? (
          <label>{t("strict_sections")}
            <input dir="auto" value={sections} onChange={(e) => setSections(e.target.value)} placeholder="تربية الأبناء, الأسرة, Parenting, Family" />
          </label>
        ) : null}
        <fieldset className="check-row"><legend>{t("strict_pillars")}</legend>
          {PILLARS3.map((p) => <label key={p} className="check"><input type="checkbox" checked={cfg.pillars.includes(p)} onChange={() => toggle("pillars", p)} />{t(`pillar_${p}` as never)}</label>)}
        </fieldset>
        <fieldset className="check-row"><legend>{t("strict_kinds")}</legend>
          {KINDS.map((k) => <label key={k} className="check"><input type="checkbox" checked={cfg.types.includes(k)} onChange={() => toggle("types", k)} />{v(k)}</label>)}
          <label className="check"><input type="checkbox" checked={cfg.files_only} onChange={(e) => setCfg({ ...cfg, files_only: e.target.checked })} /><strong>{t("strict_files_only")}</strong></label>
        </fieldset>
        <p className="muted">{t("strict_kinds_hint")}</p>
        <div className="toolbar spaced">
          <label className="field inline-field"><span>{t("strict_min_score")}</span>
            <input type="number" min={0} max={100} value={cfg.min_score} onChange={(e) => setCfg({ ...cfg, min_score: Number(e.target.value) || 0 })} /></label>
          <label className="field inline-field"><span>{t("strict_pause")}</span>
            <input type="number" min={0} max={100} value={cfg.pause_below} onChange={(e) => setCfg({ ...cfg, pause_below: Number(e.target.value) || 0 })} />%</label>
        </div>
        <label className="check"><input type="checkbox" checked={cfg.review} onChange={(e) => setCfg({ ...cfg, review: e.target.checked })} /> {t("strict_review")}</label>
        <div className="toolbar spaced">
          <button type="button" className="btn" disabled={busy || s.adapter === "apify"} onClick={preview}>{busy ? "…" : t("strict_preview")}</button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={save}>{t("save")}</button>
          {msg ? <span role="status">{msg}</span> : null}
        </div>
        {err ? <p className="text-error">{err}</p> : null}
        {prev ? (
          <div className="preview-box">
            {prev.error ? <p className="text-error">{prev.error}</p> : null}
            <p><strong>✔ {t("strict_would_save")} ({prev.would_save.length})</strong></p>
            <ul>{prev.would_save.map((x) => <li key={x.url} dir="auto"><a href={x.url} target="_blank" rel="noopener noreferrer">{x.title}</a> <span className="muted">· {v(x.type)} · {t("relevance_short")} {x.score}{x.site_labels.length ? ` · ${x.site_labels.slice(0, 3).join(" / ")}` : ""}</span></li>)}</ul>
            <p><strong>✖ {t("strict_would_reject")} ({prev.would_reject.length})</strong></p>
            <ul>{prev.would_reject.map((x) => <li key={x.url} dir="auto"><a href={x.url} target="_blank" rel="noopener noreferrer">{x.title}</a> <span className="muted">· {x.reason}</span></li>)}</ul>
            <p className="muted">{prev.note}</p>
          </div>
        ) : null}
      </div>
    </details>
  );
}

interface CatalogSite { key: string; name: string; url: string; lang: string; section: boolean; pillars: string[];
  about: string; added: boolean; source_name: string | null }

function Catalog({ reload }: { reload: () => void }) {
  const { t } = useI18n();
  const state = useAsync(() => api.get<{ sites: CatalogSite[] }>("/api/catalog"), []);
  const [msg, setMsg] = useState<string | null>(null);
  const add = async (keys: string[]) => {
    const r = await api.post<{ added: string[]; skipped: string[] }>("/api/catalog/add", { keys });
    setMsg(`${t("bulk_sites_added")}: ${r.added.length}${r.skipped.length ? ` · ${t("bulk_sites_skipped")}: ${r.skipped.length}` : ""}`);
    state.reload(); reload();
    return r;
  };
  return (
    <Card title={t("catalog_title")}>
      <details>
        <summary className="small">{t("catalog_open")}</summary>
        <p className="small">{t("catalog_intro")}</p>
        <Async state={state}>
          {(d) => (
            <>
              <div className="toolbar spaced">
                <ActionButton className="btn btn-primary btn-small" onRun={() => add(d.sites.filter((x) => !x.added).map((x) => x.key))}>
                  {t("catalog_add_all")} ({d.sites.filter((x) => !x.added).length})
                </ActionButton>
                {msg ? <span className="small" role="status">{msg}</span> : null}
              </div>
              <div className="table-wrap">
                <table className="table">
                  <tbody>
                    {d.sites.map((x) => (
                      <tr key={x.key}>
                        <td dir="auto"><strong>{x.name}</strong><br /><a className="small" href={x.url} target="_blank" rel="noopener noreferrer" dir="ltr">{decodeURI(x.url)} ↗</a>
                          <div className="small muted" dir="auto">{x.about}</div></td>
                        <td className="small">{x.pillars.map((p) => t(`pillar_${p}` as never)).join(", ")}<br />
                          <span className="muted">{x.section ? t("catalog_section") : t("catalog_home")}</span></td>
                        <td className="nowrap">{x.added ? <span className="badge badge-good">{t("catalog_added")}</span>
                          : <ActionButton className="btn btn-small" onRun={() => add([x.key])}>{t("add")}</ActionButton>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Async>
      </details>
    </Card>
  );
}

interface ExploreLink { url: string; label: string; menu: boolean; inside: number }

const isHome = (u: string) => {
  try { const p = new URL(u).pathname.replace(/\/(index\.\w+)?$/, ""); return p === ""; } catch { return false; }
};

function SectionPicker({ s, reload }: { s: MySource; reload: () => void }) {
  const { t } = useI18n();
  const current = (s.config.start_urls as string[]) || [];
  const [links, setLinks] = useState<ExploreLink[] | null>(null);
  const [chosen, setChosen] = useState<string[]>(current);
  const [extra, setExtra] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const explore = async () => {
    setErr(null); setBusy(true);
    try { setLinks((await api.post<{ links: ExploreLink[] }>(`/api/my-sources/${s.id}/explore`)).links); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const toggle = (u: string) => setChosen((c) => (c.includes(u) ? c.filter((x) => x !== u) : [...c, u]));
  const save = async () => {
    setErr(null);
    const urls = [...chosen, ...extra.split(/\s+/).filter((x) => x.startsWith("http"))];
    try {
      await api.put(`/api/my-sources/${s.id}/sections`, { urls });
      setMsg(t("sections_saved")); setExtra(""); reload();
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <details className="strict-panel">
      <summary><strong>{t("sections_title")}</strong> <span className="small muted">· {current.map((u) => decodeURI(u)).join(" · ")}</span></summary>
      <div className="form-stack small">
        <p className="muted">{t("sections_intro")}</p>
        <div className="toolbar"><button type="button" className="btn btn-small" disabled={busy} onClick={explore}>{busy ? "…" : t("sections_explore")}</button></div>
        {err ? <p className="text-error">{err}</p> : null}
        <div className="sections-list">
          <span className="muted">{t("sections_current")}</span>
          {current.map((u) => (
            <label key={u} className="check" dir="ltr">
              <input type="checkbox" checked={chosen.includes(u)} onChange={() => toggle(u)} />
              <span>{decodeURI(u)}{isHome(u) ? <strong className="text-error"> · {t("sections_home_warning")}</strong> : null}</span>
            </label>
          ))}
        </div>
        {links ? (
          <div className="sections-list">
            {links.filter((l) => !current.includes(l.url)).map((l) => (
              <label key={l.url} className="check" dir="auto">
                <input type="checkbox" checked={chosen.includes(l.url)} onChange={() => toggle(l.url)} />
                <span>{l.menu ? "☰ " : ""}<strong>{l.label}</strong> {l.inside ? <span className="muted">({l.inside} {t("sections_inside")})</span> : null}
                  {" "}<a href={l.url} target="_blank" rel="noopener noreferrer" className="muted">↗</a></span>
              </label>
            ))}
          </div>
        ) : null}
        <label>{t("sections_manual")}<input dir="ltr" value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="https://…" /></label>
        <div className="toolbar spaced">
          <button type="button" className="btn btn-primary btn-small" onClick={save}>{t("sections_use")} ({chosen.length + extra.split(/\s+/).filter((x) => x.startsWith("http")).length})</button>
          {msg ? <span role="status">{msg}</span> : null}
        </div>
      </div>
    </details>
  );
}
