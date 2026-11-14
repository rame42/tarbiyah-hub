import { FormEvent, Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ActionButton, Async, Badge, Card, ErrorBox, fmtDate, fmtNum, KV, Pre, TableWrap, useAsync, DeleteSourceButton } from "../components";
import { useI18n } from "../i18n";

interface AdapterInfo {
  name: string;
  label: string;
  kind: string;
  description: string;
  capabilities: string[];
  resource_types: string[];
  credentials: string[];
  missing_credentials: string[];
  optional_credentials: string[];
  optional_missing: string[];
  paid: boolean;
  access_notes: string;
  configured: boolean;
  config_fields: Record<string, string>;
  default_config: Record<string, unknown>;
  default_schedule_minutes: number;
}
interface SourceRow {
  id: number;
  key: string;
  adapter: string;
  name: string;
  enabled: boolean;
  role: string;
  config: Record<string, unknown>;
  schedule_minutes: number | null;
  rate_limit_per_min: number | null;
  last_run_at: string | null;
  last_success_at: string | null;
  next_run_at: string | null;
  health: string;
  last_error: string | null;
  items_collected: number;
  last_result: Record<string, unknown> | null;
  active_jobs: number;
  paused: boolean;
  adapter_info: AdapterInfo | null;
}

export function parseConfig(text: string, t: (k: "invalid_json" | "must_be_object") => string): Record<string, unknown> {
  let v: unknown;
  try {
    v = JSON.parse(text || "{}");
  } catch (e) {
    throw new Error(`${t("invalid_json")} ${(e as Error).message}`);
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error(t("must_be_object"));
  return v as Record<string, unknown>;
}

export default function Sources() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<SourceRow[]>("/api/sources"), []);
  // merge single-source updates without refetching everything
  const [overrides, setOverrides] = useState<Record<number, SourceRow>>({});
  useEffect(() => setOverrides({}), [state.data]);
  const update = (s: SourceRow) => setOverrides((o) => ({ ...o, [s.id]: s }));

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("sources_title")}</h1>
        <button type="button" className="btn" onClick={state.reload}>{t("refresh")}</button>
      </div>
      <Async state={state}>
        {(rows) => {
          const list = rows.map((r) => overrides[r.id] || r).filter((r) => r.health !== "deleted");
          const search = list.filter((r) => r.role === "search");
          const monitor = list.filter((r) => r.role !== "search");
          return (
            <>
              <Card title={<>{t("monitored_sources")} <span className="muted count">{monitor.length}</span></>}>
                <p className="muted small">{t("monitored_sources_help")}</p>
                {monitor.length === 0 ? <p className="empty">{t("none")}</p> : <SourceTable rows={monitor} onUpdate={update} onDeleted={state.reload} />}
              </Card>
              <Card title={<>{t("search_sources")} <span className="muted count">{search.length}</span></>}>
                <p className="muted small">{t("search_sources_help")}</p>
                <SourceTable rows={search} onUpdate={update} onDeleted={state.reload} />
              </Card>
            </>
          );
        }}
      </Async>
      <DeletedSources key={state.data ? state.data.length : 0} onRestored={state.reload} />
      <AddSource onAdded={state.reload} />
    </div>
  );
}

type SortKey = "name" | "health" | "last_run_at" | "items_collected";
const PROBLEM = new Set(["error", "needs_credentials", "waiting"]);

/** Sources as a scannable table: filter, sort by column, open a row for its full details and actions. */
function SourceTable({ rows, onUpdate, onDeleted }: { rows: SourceRow[]; onUpdate: (s: SourceRow) => void; onDeleted: () => void }) {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [show, setShow] = useState<"all" | "enabled" | "problems">("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "name", dir: 1 });
  const [open, setOpen] = useState<number | null>(null);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = rows.filter((r) => (show === "all" || (show === "enabled" ? r.enabled : PROBLEM.has(r.health)))
      && (!needle || `${r.name} ${r.key} ${r.adapter_info?.label || r.adapter}`.toLowerCase().includes(needle)));
    const val = (r: SourceRow) => (sort.key === "items_collected" ? r.items_collected : String(r[sort.key] ?? ""));
    return [...list].sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * sort.dir);
  }, [rows, q, show, sort]);
  const counts = { all: rows.length, enabled: rows.filter((r) => r.enabled).length, problems: rows.filter((r) => PROBLEM.has(r.health)).length };
  const th = (key: SortKey, label: string, cls = "") => (
    <th className={cls} aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className="th-sort" onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "name" ? 1 : -1 }))}>
        {label}<span className="sort-mark" aria-hidden="true">{sort.key === key ? (sort.dir === 1 ? "↑" : "↓") : ""}</span>
      </button>
    </th>
  );
  return (
    <>
      <div className="table-tools">
        <input type="search" placeholder={t("filter")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("filter")} />
        <div className="seg" role="group">
          {(["all", "enabled", "problems"] as const).map((k) => (
            <button key={k} type="button" className={show === k ? "active" : ""} aria-pressed={show === k} onClick={() => setShow(k)}>
              {k === "all" ? t("all") : k === "enabled" ? t("enabled") : t("needs_attention")} <span className="seg-n">{counts[k]}</span>
            </button>
          ))}
        </div>
      </div>
      <TableWrap>
        <table className="data-table">
          <thead>
            <tr>
              {th("name", t("source"))}
              {th("health", t("status"))}
              {th("last_run_at", t("last_run"))}
              <th>{t("next_run")}</th>
              {th("items_collected", t("items_collected"), "num")}
              <th className="num">{t("active_jobs")}</th>
              <th aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 ? <tr><td colSpan={7} className="muted">{t("none")}</td></tr> : null}
            {shown.map((s) => (
              <Fragment key={s.id}>
                <tr className={`clickable ${open === s.id ? "row-open" : ""} ${s.enabled ? "" : "row-dim"}`} onClick={() => setOpen(open === s.id ? null : s.id)}>
                  <td>
                    <button type="button" className="row-title" aria-expanded={open === s.id} onClick={(e) => { e.stopPropagation(); setOpen(open === s.id ? null : s.id); }}>
                      <span dir="auto">{s.name}</span>
                    </button>
                    <div className="muted small">{s.adapter_info?.label || s.adapter}</div>
                  </td>
                  <td className="nowrap">
                    <span className="badges">
                      <Badge value={s.health} />
                      {!s.enabled ? <Badge tone="muted">{t("disabled")}</Badge> : null}
                      {s.paused ? <Badge tone="warn">{t("paused")}</Badge> : null}
                      {s.adapter_info?.paid ? <Badge tone="warn">{t("paid_source")}</Badge> : null}
                    </span>
                  </td>
                  <td className="nowrap muted">{fmtDate(s.last_run_at)}</td>
                  <td className="nowrap muted">{fmtDate(s.next_run_at)}</td>
                  <td className="num">{fmtNum(s.items_collected)}</td>
                  <td className="num">{s.active_jobs ? fmtNum(s.active_jobs) : <span className="muted">—</span>}</td>
                  <td className="chev-cell"><span className={`chev ${open === s.id ? "open" : ""}`} aria-hidden="true" /></td>
                </tr>
                {open === s.id ? (
                  <tr className="detail-row">
                    <td colSpan={7}><SourceCard s={s} onUpdate={onUpdate} onDeleted={onDeleted} bare /></td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <p className="muted small table-note">{shown.length} / {rows.length} · {t("click_row")}</p>
    </>
  );
}

function SourceCard({ s, onUpdate, onDeleted, bare }: { s: SourceRow; onUpdate: (s: SourceRow) => void; onDeleted: () => void; bare?: boolean }) {
  const { t, v } = useI18n();
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const info = s.adapter_info;
  const patch = async (body: Record<string, unknown>) => {
    setErr(null);
    try {
      onUpdate(await api.patch<SourceRow>(`/api/sources/${s.id}`, body));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const isMonitor = s.role !== "search";

  return (
    <div className={bare ? "src-detail" : `src-card ${s.enabled ? "" : "src-disabled"}`}>
      <div className="src-head" style={bare ? { display: "none" } : undefined}>
        <strong dir="auto">{s.name}</strong>
        <Badge value={s.health} />
        {s.paused ? <Badge tone="warn">{t("paused")}</Badge> : null}
        {info?.paid ? <Badge tone="warn">{t("paid_source")}</Badge> : null}
      </div>
      <div className="muted small"><code>{s.key}</code> · {t("adapter")}: {info?.label || s.adapter}</div>
      {info?.description ? <p className="small" dir="auto">{info.description}</p> : null}

      <div className="toolbar">
        <label className="switch">
          <input type="checkbox" checked={s.enabled} onChange={(e) => patch({ enabled: e.target.checked })} />
          <span>{t("enabled")}</span>
        </label>
        <label className="switch">
          <input type="checkbox" checked={s.paused} onChange={(e) => patch({ paused: e.target.checked })} />
          <span>{t("paused")}</span>
        </label>
      </div>

      <KV rows={[
        [t("last_run"), fmtDate(s.last_run_at)],
        [t("last_success"), fmtDate(s.last_success_at)],
        [t("next_run"), fmtDate(s.next_run_at)],
        [t("schedule_minutes"), s.schedule_minutes !== null ? `${fmtNum(s.schedule_minutes)} ${t("min")}` : null],
        [t("items_collected"), fmtNum(s.items_collected)],
        [t("active_jobs"), fmtNum(s.active_jobs)],
        [t("last_result"), s.last_result && Object.keys(s.last_result).length ? <code className="small break">{JSON.stringify(s.last_result)}</code> : null],
      ]} />
      {s.last_error ? (
        s.health === "error" || s.health === "needs_credentials" ? (
          <ErrorBox error={`${t("last_error")}: ${s.last_error}`} />
        ) : (
          <p className="small muted" dir="auto"><strong>{t("last_messages")}:</strong> {s.last_error}</p>
        )
      ) : null}
      {Array.isArray((s.last_result as { messages?: unknown })?.messages) &&
      ((s.last_result as { messages: string[] }).messages.length > 0) ? (
        <p className="small muted" dir="auto"><strong>{t("last_messages")}:</strong> {(s.last_result as { messages: string[] }).messages.join("; ")}</p>
      ) : null}
      {info?.missing_credentials.length ? (
        <p className="small"><Badge tone="warn">{t("missing_credentials")}</Badge> <code>{info.missing_credentials.join(", ")}</code></p>
      ) : null}
      {info?.access_notes ? (
        <details className="small"><summary>{t("access_notes")}</summary><p dir="auto">{info.access_notes}</p></details>
      ) : null}
      <ErrorBox error={err} />

      <div className="toolbar">
        {isMonitor ? (
          <ActionButton className="btn btn-small btn-primary" onRun={() => api.post(`/api/sources/${s.id}/run`)}>{t("run_now")}</ActionButton>
        ) : null}
        <button type="button" className="btn btn-small" onClick={() => setEditing((x) => !x)} aria-expanded={editing}>{editing ? t("close") : t("edit")}</button>
        <DeleteSourceButton id={s.id} name={s.name} items={s.items_collected} onDone={onDeleted} />
      </div>
      {editing ? <SourceEditor s={s} onSaved={(x) => { onUpdate(x); setEditing(false); }} /> : null}
      {!editing && Object.keys(s.config).length ? (
        <details className="small"><summary>{t("config_json")}</summary><Pre>{JSON.stringify(s.config, null, 2)}</Pre></details>
      ) : null}
      {info?.capabilities.length ? <div className="muted small">{t("capabilities")}: {info.capabilities.map((c) => v(c)).join(", ")}</div> : null}
    </div>
  );
}

function SourceEditor({ s, onSaved }: { s: SourceRow; onSaved: (s: SourceRow) => void }) {
  const { t } = useI18n();
  const [sched, setSched] = useState(s.schedule_minutes !== null ? String(s.schedule_minutes) : "");
  const [cfg, setCfg] = useState(JSON.stringify(s.config, null, 2));
  const [err, setErr] = useState<string | null>(null);
  const fields = s.adapter_info?.config_fields || {};

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const config = parseConfig(cfg, t);
      const body: Record<string, unknown> = { config };
      if (sched !== "") body.schedule_minutes = Math.max(1, Math.round(Number(sched)));
      onSaved(await api.patch<SourceRow>(`/api/sources/${s.id}`, body));
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <form className="form-stack editor" onSubmit={save}>
      <label className="field narrow">
        <span>{t("schedule_minutes")}</span>
        <input type="number" min={1} value={sched} onChange={(e) => setSched(e.target.value)} />
      </label>
      <label className="field">
        <span>{t("config_json")}</span>
        <textarea className="mono" dir="ltr" rows={8} value={cfg} onChange={(e) => setCfg(e.target.value)} spellCheck={false} />
      </label>
      {Object.keys(fields).length ? <ConfigHelp fields={fields} /> : null}
      <ErrorBox error={err} />
      <div><button type="submit" className="btn btn-primary btn-small">{t("save")}</button></div>
    </form>
  );
}

function ConfigHelp({ fields }: { fields: Record<string, string> }) {
  const { t } = useI18n();
  return (
    <details className="small" open>
      <summary>{t("config_fields")}</summary>
      <dl className="kv">
        {Object.entries(fields).map(([k, d]) => (
          <div className="kv-row" key={k}><dt><code>{k}</code></dt><dd dir="auto">{d}</dd></div>
        ))}
      </dl>
    </details>
  );
}

function AddSource({ onAdded }: { onAdded: () => void }) {
  const { t, v } = useI18n();
  const adapters = useAsync(() => api.get<AdapterInfo[]>("/api/adapters"), []);
  const monitorable = useMemo(() => (adapters.data || []).filter((a) => a.capabilities.includes("monitor")), [adapters.data]);
  const [adapter, setAdapter] = useState("");
  const [name, setName] = useState("");
  const [sched, setSched] = useState("");
  const [cfg, setCfg] = useState("{}");
  const [enabled, setEnabled] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const a = monitorable.find((x) => x.name === adapter);

  useEffect(() => {
    if (!adapter && monitorable.length) setAdapter(monitorable[0].name);
  }, [monitorable, adapter]);
  useEffect(() => {
    if (a) {
      setCfg(JSON.stringify(a.default_config, null, 2));
      setSched(String(a.default_schedule_minutes));
    }
  }, [a]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setOk(null);
    try {
      const config = parseConfig(cfg, t);
      const r = await api.post<SourceRow>("/api/sources", {
        adapter, name: name.trim(), config, schedule_minutes: sched ? Math.max(1, Math.round(Number(sched))) : null, enabled,
      });
      setOk(`${r.name} (${r.key})`);
      setName("");
      onAdded();
    } catch (x) {
      setErr((x as Error).message);
    }
  };

  return (
    <Card title={t("add_source")}>
      <ErrorBox error={adapters.error} />
      <form className="form-stack" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>{t("adapter")}</span>
            <select value={adapter} onChange={(e) => setAdapter(e.target.value)}>
              {monitorable.map((x) => <option key={x.name} value={x.name}>{x.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>{t("name")} *</span>
            <input dir="auto" required value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field">
            <span>{t("schedule_minutes")}</span>
            <input type="number" min={1} value={sched} onChange={(e) => setSched(e.target.value)} />
          </label>
        </div>
        {a ? (
          <div className="small">
            <p dir="auto">{a.description}</p>
            {a.paid ? <Badge tone="warn">{t("paid_source")}</Badge> : null}{" "}
            {a.missing_credentials.length ? <><Badge tone="warn">{t("missing_credentials")}</Badge> <code>{a.missing_credentials.join(", ")}</code></> : null}
            {a.access_notes ? <p className="muted" dir="auto">{a.access_notes}</p> : null}
            <p className="muted">{t("capabilities")}: {a.capabilities.map((c) => v(c)).join(", ")}</p>
          </div>
        ) : null}
        <label className="field">
          <span>{t("config_json")}</span>
          <textarea className="mono" dir="ltr" rows={8} value={cfg} onChange={(e) => setCfg(e.target.value)} spellCheck={false} />
        </label>
        {a && Object.keys(a.config_fields).length ? <ConfigHelp fields={a.config_fields} /> : null}
        <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />{t("enabled")}</label>
        <ErrorBox error={err} />
        {ok ? <div className="alert alert-ok" role="status">{t("ok_done")} <span dir="auto">{ok}</span></div> : null}
        <div><button type="submit" className="btn btn-primary" disabled={!adapter || !name.trim()}>{t("add")}</button></div>
      </form>
    </Card>
  );
}

function DeletedSources({ onRestored }: { onRestored: () => void }) {
  const { t } = useI18n();
  const list = useAsync(() => api.get<{ id: number; name: string; adapter: string; deleted_at: string | null }[]>("/api/sources/deleted"), []);
  if (!list.data || list.data.length === 0) return null;
  return (
    <details className="card fold">
      <summary><h2>{t("deleted_sources")}</h2><span className="fold-meta">{list.data.length}</span></summary>
      <p className="small muted">{t("deleted_sources_help")}</p>
      <ul className="plain-list">
        {list.data.map((x) => (
          <li key={x.id} className="row-between">
            <span><span dir="auto">{x.name}</span> <span className="muted small">· {x.adapter} · {fmtDate(x.deleted_at)}</span></span>
            <ActionButton className="btn btn-small" onRun={async () => { const r = await api.post(`/api/sources/${x.id}/restore`); list.reload(); onRestored(); return r; }}>{t("restore")}</ActionButton>
          </li>
        ))}
      </ul>
    </details>
  );
}
