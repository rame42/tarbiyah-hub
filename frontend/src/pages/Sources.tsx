import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ActionButton, Async, Badge, Card, ErrorBox, fmtDate, fmtNum, KV, Pre, useAsync } from "../components";
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
              <Card title={`${t("monitored_sources")} (${monitor.length})`}>
                <p className="muted small">{t("monitored_sources_help")}</p>
                {monitor.length === 0 ? <p className="muted">{t("none")}</p> : (
                  <div className="src-grid">{monitor.map((s) => <SourceCard key={s.id} s={s} onUpdate={update} onDeleted={state.reload} />)}</div>
                )}
              </Card>
              <Card title={`${t("search_sources")} (${search.length})`}>
                <p className="muted small">{t("search_sources_help")}</p>
                <div className="src-grid">{search.map((s) => <SourceCard key={s.id} s={s} onUpdate={update} onDeleted={state.reload} />)}</div>
              </Card>
            </>
          );
        }}
      </Async>
      <AddSource onAdded={state.reload} />
    </div>
  );
}

function SourceCard({ s, onUpdate, onDeleted }: { s: SourceRow; onUpdate: (s: SourceRow) => void; onDeleted: () => void }) {
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
    <div className={`src-card ${s.enabled ? "" : "src-disabled"}`}>
      <div className="src-head">
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
        {isMonitor ? (
          <ActionButton className="btn btn-small btn-danger" confirm={`${t("confirm_delete")} ${t("delete_note")}`} onRun={async () => { const r = await api.del(`/api/sources/${s.id}`); onDeleted(); return r; }} title={t("delete_note")}>
            {t("delete")}
          </ActionButton>
        ) : null}
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
