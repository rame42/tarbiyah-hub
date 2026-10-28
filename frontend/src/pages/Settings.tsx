import { FormEvent, ReactNode, useEffect, useState } from "react";
import { api, Status } from "../api";
import { ActionButton, Async, BoolBadge, Card, ErrorBox, KV, TableWrap, useAsync } from "../components";
import { TKey, useI18n } from "../i18n";

type Values = Record<string, unknown>;
interface SettingsResponse { values: Values; defaults: Values; model: string; data_dir: string }

const SELECTS: Record<string, string[]> = {
  ocr_provider: ["auto", "tesseract", "claude", "none"],
  ai_summary_language: ["source", "en", "ar"],
  ai_effort: ["low", "medium", "high"],
  ui_language: ["en", "ar"],
};

const SECTIONS: [TKey, string[]][] = [
  ["sec_automation", ["automation_enabled", "paused", "operating_hours", "paused_collectors", "worker_concurrency", "job_timeout_seconds", "lease_seconds"]],
  ["sec_research", ["research_cycle_minutes", "max_questions_per_cycle", "max_open_questions", "max_new_questions_per_run", "max_question_depth", "search_repeat_days", "max_results_per_search"]],
  ["sec_budgets", ["daily_http_request_limit", "daily_download_limit", "daily_download_mb_limit", "daily_ai_call_limit", "daily_ai_budget_usd"]],
  ["sec_storage", ["storage_limit_gb", "max_file_mb", "min_free_disk_gb", "download_free_to_read"]],
  ["sec_ai", ["ai_enabled", "ai_effort", "ai_summary_language", "ocr_provider", "ocr_languages"]],
  ["sec_crawler", ["crawler_default_max_pages", "crawler_default_max_depth", "respect_robots_txt"]],
];

// Python floats such as 2.0 arrive as JSON integers, so float settings are listed explicitly.
const FLOAT_KEYS = new Set(["storage_limit_gb", "min_free_disk_gb", "daily_ai_budget_usd"]);

function label(key: string): string {
  return key.replace(/_/g, " ");
}

export default function Settings() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<SettingsResponse>("/api/settings"), []);
  const status = useAsync(() => api.get<Status>("/api/status"), []);
  return (
    <div className="page">
      <div className="page-head"><h1>{t("settings_title")}</h1></div>
      <Async state={state}>{(d) => <SettingsForm d={d} onSaved={state.reload} />}</Async>
      <div className="grid-2">
        <Card title={t("credentials")}>
          <p className="muted small">{t("credentials_note")}</p>
          <Async state={status}>
            {(s) => (
              <TableWrap>
                <table>
                  <tbody>
                    {Object.entries(s.credentials).map(([k, ok]) => (
                      <tr key={k}><td><code>{k.toUpperCase()}</code></td><td><BoolBadge value={ok} yes={t("configured")} no={t("not_configured")} /></td></tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
          </Async>
        </Card>
        <Updates />
        <Backups />
      </div>
    </div>
  );
}

function SettingsForm({ d, onSaved }: { d: SettingsResponse; onSaved: () => void }) {
  const { t } = useI18n();
  const [vals, setVals] = useState<Values>(d.values);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setVals(d.values), [d]);

  const known = new Set(SECTIONS.flatMap(([, ks]) => ks));
  const other = Object.keys(d.values).filter((k) => !known.has(k));
  const sections: [TKey, string[]][] = [...SECTIONS.map(([n, ks]) => [n, ks.filter((k) => k in d.values)] as [TKey, string[]]), ["sec_other", other]];

  const changed = Object.keys(vals).filter((k) => JSON.stringify(vals[k]) !== JSON.stringify(d.values[k]));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (!changed.length) {
      setMsg(t("no_changes"));
      return;
    }
    const body: Values = {};
    for (const k of changed) {
      const val = vals[k];
      if (typeof d.defaults[k] === "number" && (typeof val !== "number" || Number.isNaN(val))) {
        setErr(`${label(k)}: number required`);
        return;
      }
      body[k] = val;
    }
    setBusy(true);
    try {
      await api.patch("/api/settings", body);
      setMsg(`${t("saved")} ${t("changed_keys")} ${changed.join(", ")}`);
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const field = (k: string): ReactNode => {
    const def = d.defaults[k];
    const val = vals[k];
    const set = (nv: unknown) => setVals({ ...vals, [k]: nv });
    const isChanged = changed.includes(k);
    let input: ReactNode;
    if (k === "paused_collectors") {
      const list = (val as string[]) || [];
      input = (
        <span>
          {list.length ? list.map((x) => <code key={x} className="chip">{x}</code>) : <span className="muted">{t("none")}</span>}{" "}
          <span className="muted small">({t("read_only")})</span>
        </span>
      );
    } else if (k === "operating_hours") {
      const oh = (val as { start: string; end: string }) || { start: "00:00", end: "23:59" };
      input = (
        <span className="inline-field">
          <label>{t("start")} <input type="time" value={oh.start} onChange={(e) => set({ ...oh, start: e.target.value })} /></label>
          <label>{t("end")} <input type="time" value={oh.end} onChange={(e) => set({ ...oh, end: e.target.value })} /></label>
        </span>
      );
    } else if (SELECTS[k]) {
      input = (
        <select id={`set-${k}`} value={String(val)} onChange={(e) => set(e.target.value)}>
          {SELECTS[k].map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    } else if (typeof def === "boolean") {
      input = <input id={`set-${k}`} type="checkbox" checked={!!val} onChange={(e) => set(e.target.checked)} />;
    } else if (typeof def === "number") {
      const isInt = !FLOAT_KEYS.has(k) && Number.isInteger(def) && (typeof val !== "number" || Number.isInteger(val));
      input = (
        <input
          id={`set-${k}`}
          type="number"
          className="num-input"
          step={isInt ? 1 : "any"}
          min={0}
          value={typeof val === "number" && !Number.isNaN(val) ? val : ""}
          onChange={(e) => set(e.target.value === "" ? NaN : isInt ? Math.round(Number(e.target.value)) : Number(e.target.value))}
        />
      );
    } else if (typeof def === "string") {
      input = <input id={`set-${k}`} value={String(val ?? "")} onChange={(e) => set(e.target.value)} dir="ltr" />;
    } else {
      input = <code className="break">{JSON.stringify(val)}</code>;
    }
    return (
      <div className={`set-row ${isChanged ? "set-changed" : ""}`} key={k}>
        <label htmlFor={`set-${k}`} className="set-label">
          <code>{k}</code>
          <span className="muted small"> {t("default_value")}: {typeof def === "object" ? JSON.stringify(def) : String(def)}</span>
        </label>
        <div className="set-input">{input}</div>
      </div>
    );
  };

  return (
    <form onSubmit={save} noValidate>
      <Card title={t("settings_title")}>
        <KV rows={[[t("model"), <code dir="ltr">{d.model}</code>], [t("data_dir"), <code className="break" dir="ltr">{d.data_dir}</code>]]} />
      </Card>
      <div className="grid-2">
        {sections.filter(([, ks]) => ks.length).map(([name, ks]) => (
          <Card key={name} title={t(name)}>
            <div className="set-list">{ks.map(field)}</div>
          </Card>
        ))}
      </div>
      <div className="sticky-save">
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "…" : ""}{t("save")}{changed.length ? ` (${changed.length})` : ""}</button>
        <button type="button" className="btn" onClick={() => { setVals(d.values); setMsg(null); setErr(null); }} disabled={!changed.length}>{t("reset")}</button>
        {msg ? <span className="action-msg ok" role="status">{msg}</span> : null}
        <ErrorBox error={err} />
      </div>
    </form>
  );
}

function Backups() {
  const { t } = useI18n();
  const list = useAsync(() => api.get<{ name: string; size_mb: number }[]>("/api/backups"), []);
  return (
    <Card title={t("backup")}>
      <ActionButton
        className="btn btn-primary"
        onRun={async () => { const r = await api.post<{ path: string; size_mb: number }>("/api/backup"); list.reload(); return r; }}
        done={(r) => { const x = r as { path: string; size_mb: number }; return `${t("backup_created")} \u2066${x.path}\u2069 (${x.size_mb} MB)`; }}
      >
        {t("backup_now")}
      </ActionButton>
      <h3>{t("backups")}</h3>
      <Async state={list}>
        {(rows) => rows.length === 0 ? <p className="muted">{t("none")}</p> : (
          <ul className="plain-list">{rows.map((b) => <li key={b.name}><code dir="ltr">{b.name}</code> — {b.size_mb} MB</li>)}</ul>
        )}
      </Async>
    </Card>
  );
}

interface UpdateInfo {
  configured: boolean;
  message?: string;
  error?: string;
  update_available?: boolean;
  current?: { sha?: string; installed_at?: string; source?: string };
  latest?: { sha: string; date: string | null; message: string };
  last_log?: string;
}

function Updates() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<UpdateInfo>("/api/update"), []);
  const u = state.data;
  return (
    <Card title={t("updates")}>
      <ErrorBox error={state.error} />
      {u ? (
        <div className="form-stack small">
          {u.current?.sha ? <p>{t("installed_version")}: <code>{u.current.sha}</code> {u.current.installed_at ? `(${u.current.installed_at})` : null}</p> : null}
          {!u.configured ? <p className="muted" dir="auto">{t("updates_not_configured")}</p> : null}
          {u.error ? <div className="alert alert-warn" role="status" dir="auto">{u.error}</div> : null}
          {u.configured && u.latest ? (
            u.update_available ? (
              <div className="alert alert-ok" role="status">
                <strong>{t("update_available")}</strong> <code>{u.latest.sha}</code> — <span dir="auto">{u.latest.message}</span>
                <p>{t("update_how")}</p>
              </div>
            ) : <p>{t("up_to_date")}</p>
          ) : null}
          <p className="muted">{t("update_keeps")}</p>
          {u.last_log ? (
            <details>
              <summary>{t("last_update_log")}</summary>
              <pre className="pre">{u.last_log}</pre>
            </details>
          ) : null}
          <div><button type="button" className="btn btn-small" onClick={() => state.reload()}>{t("check_updates")}</button></div>
        </div>
      ) : null}
    </Card>
  );
}
