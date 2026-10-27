import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs, Status } from "../api";
import { ActionButton, Async, Badge, Card, CountList, ErrorBox, fmtDate, fmtNum, PillarBadges, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";
import { StatusStrip } from "./Dashboard";

interface Objective {
  id: number;
  title: string;
  description: string | null;
  pillars: string[];
  priority: number;
  status: string;
  planned_at: string | null;
  questions: Record<string, number>;
}
interface Activity { id: number; agent: string; action: string; status: string; detail: string | null; job_id: number | null; question_id: number | null; resource_id: number | null; tokens: number; at: string }
interface FindingRow { id: number; question_id: number | null; statement: string; type: string; confidence: string; qa_status: string; evidence_count: number; verified_evidence: number; created_at: string }

const PILLARS = ["children", "parents", "murabbi"];
const AGENTS = ["acquisition", "assistant", "coordinator", "discovery", "knowledge", "planner", "processing", "qa", "questions", "social_media", "synthesis"];

export default function Research() {
  const { t } = useI18n();
  const status = useAsync(() => api.get<Status>("/api/status"), [], 15000);
  return (
    <div className="page">
      <div className="page-head"><h1>{t("research_title")}</h1></div>
      <Card title={t("current_state")}>
        <Async state={status}>
          {(s) => (
            <>
              <StatusStrip s={s} />
              <p className="small">
                {t("operating_hours")}: {s.automation.operating_hours.start}–{s.automation.operating_hours.end} · {t("jobs")}: <CountList data={s.jobs} /> · {t("open_questions")}: {fmtNum(s.counts.open_questions)}
              </p>
            </>
          )}
        </Async>
      </Card>
      <AutomationControls status={status.data} reload={status.reload} />
      <Objectives />
      <Findings />
      <ActivityLog />
    </div>
  );
}

function AutomationControls({ status, reload }: { status: Status | null; reload: () => void }) {
  const { t } = useI18n();
  const run = (a: string) => async () => {
    const r = await api.post(`/api/automation/${a}`);
    reload();
    return r;
  };
  return (
    <Card title={t("automation_controls")}>
      <div className="toolbar">
        {status?.automation.paused ? (
          <ActionButton className="btn btn-primary" onRun={run("resume")}>{t("resume")}</ActionButton>
        ) : (
          <ActionButton onRun={run("pause")}>{t("pause")}</ActionButton>
        )}
        {status?.automation.enabled ? (
          <ActionButton onRun={run("disable")}>{t("disable")}</ActionButton>
        ) : (
          <ActionButton className="btn btn-primary" onRun={run("enable")}>{t("enable")}</ActionButton>
        )}
        <ActionButton onRun={run("cycle")}>{t("run_cycle")}</ActionButton>
        <ActionButton onRun={run("maintenance")}>{t("run_maintenance")}</ActionButton>
      </div>
    </Card>
  );
}

function Objectives() {
  const { t, v } = useI18n();
  const state = useAsync(() => api.get<Objective[]>("/api/objectives"), []);
  const [form, setForm] = useState({ title: "", description: "", pillars: [] as string[], priority: 0.6 });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.post("/api/objectives", { ...form, description: form.description || null, status: "active" });
      setForm({ title: "", description: "", pillars: [], priority: 0.6 });
      state.reload();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const patch = (id: number, body: Record<string, unknown>) => async () => {
    const r = await api.patch(`/api/objectives/${id}`, body);
    state.reload();
    return r;
  };

  return (
    <Card title={t("objectives")}>
      <Async state={state}>
        {(list) =>
          list.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
            <div className="obj-list">
              {list.map((o) => (
                <div className="obj" key={o.id}>
                  <div className="obj-head">
                    <strong dir="auto" className="content-text">{o.title}</strong>
                    <Badge value={o.status} />
                    <PillarBadges pillars={o.pillars} />
                  </div>
                  {o.description ? <p dir="auto" className="small">{o.description}</p> : null}
                  <div className="small">
                    {t("planned_at")}: {fmtDate(o.planned_at)} · {t("questions_by_status")}: <CountList data={o.questions} />
                  </div>
                  <div className="toolbar">
                    <label className="inline-field">
                      <span>{t("status")}</span>
                      <select value={o.status} onChange={(e) => { api.patch(`/api/objectives/${o.id}`, { status: e.target.value }).then(state.reload, (x: Error) => setErr(x.message)); }}>
                        {["active", "paused", "done"].map((s) => <option key={s} value={s}>{v(s)}</option>)}
                      </select>
                    </label>
                    <PriorityEditor value={o.priority} onSave={(p) => patch(o.id, { priority: p })()} />
                    <ActionButton className="btn btn-small" onRun={patch(o.id, { replan: true })}>{t("replan")}</ActionButton>
                    <ActionButton className="btn btn-small" onRun={async () => { const r = await api.post(`/api/objectives/${o.id}/plan`); state.reload(); return r; }}>{t("plan_now")}</ActionButton>
                  </div>
                </div>
              ))}
            </div>
          )
        }
      </Async>
      <ErrorBox error={err} />
      <details className="sub-form">
        <summary>{t("new_objective")}</summary>
        <form onSubmit={create} className="form-stack">
          <label className="field"><span>{t("title")} *</span><input dir="auto" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <label className="field"><span>{t("description")}</span><textarea dir="auto" rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
          <PillarChecks value={form.pillars} onChange={(p) => setForm({ ...form, pillars: p })} />
          <label className="field narrow"><span>{t("priority")} (0–1)</span><input type="number" min={0} max={1} step={0.05} value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })} /></label>
          <div><button type="submit" className="btn btn-primary" disabled={busy}>{t("add")}</button></div>
        </form>
      </details>
    </Card>
  );
}

function PriorityEditor({ value, onSave }: { value: number; onSave: (v: number) => Promise<unknown> }) {
  const { t } = useI18n();
  const [val, setVal] = useState(String(value));
  return (
    <span className="inline-field">
      <label>
        <span>{t("priority")}</span>{" "}
        <input type="number" className="num-input" min={0} max={1} step={0.05} value={val} onChange={(e) => setVal(e.target.value)} />
      </label>
      <ActionButton className="btn btn-small" disabled={Number(val) === value || val === ""} onRun={() => onSave(Number(val))}>{t("save")}</ActionButton>
    </span>
  );
}

export function PillarChecks({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { t } = useI18n();
  return (
    <fieldset className="checks">
      <legend>{t("pillars")}</legend>
      {PILLARS.map((p) => (
        <label key={p} className="check">
          <input type="checkbox" checked={value.includes(p)} onChange={(e) => onChange(e.target.checked ? [...value, p] : value.filter((x) => x !== p))} />
          {t(`pillar_${p}` as "pillar_children")}
        </label>
      ))}
    </fieldset>
  );
}

function ActivityLog() {
  const { t } = useI18n();
  const [agent, setAgent] = useState("");
  const state = useAsync(() => api.get<Activity[]>(`/api/activity${qs({ limit: 100, agent })}`), [agent], 15000);
  const seen = Array.from(new Set([...AGENTS, ...(state.data || []).map((a) => a.agent)])).sort();
  return (
    <Card title={t("activity_log")} actions={
      <label className="inline-field">
        <span className="sr-only">{t("filter_agent")}</span>
        <select value={agent} onChange={(e) => setAgent(e.target.value)} aria-label={t("filter_agent")}>
          <option value="">{t("all")}</option>
          {seen.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </label>
    }>
      <Async state={state}>
        {(rows) => rows.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
          <TableWrap>
            <table>
              <thead><tr><th>{t("at")}</th><th>{t("agent")}</th><th>{t("action")}</th><th>{t("status")}</th><th>{t("details")}</th></tr></thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap">{fmtDate(a.at)}</td>
                    <td>{a.agent}</td>
                    <td>{a.action}</td>
                    <td><Badge value={a.status} /></td>
                    <td className="wide-cell">
                      <span dir="auto">{a.detail}</span>{" "}
                      {a.question_id ? <Link to={`/questions/${a.question_id}`}>Q#{a.question_id}</Link> : null}{" "}
                      {a.resource_id ? <Link to={`/resources/${a.resource_id}`}>R#{a.resource_id}</Link> : null}{" "}
                      {a.tokens ? <span className="muted small">{fmtNum(a.tokens)} {t("tokens")}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Async>
    </Card>
  );
}

function Findings() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<FindingRow[]>("/api/findings?limit=50"), []);
  return (
    <Card title={t("recent_findings")}>
      <Async state={state}>
        {(rows) => rows.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
          <ul className="plain-list">
            {rows.map((f) => (
              <li key={f.id}>
                <div className="badges">
                  <Badge value={f.type} /> <Badge value={f.confidence} /> <Badge value={f.qa_status} />
                  <span className="small">{t("evidence")}: {f.verified_evidence}/{f.evidence_count} {t("verified")}</span>
                </div>
                {f.question_id ? <Link to={`/questions/${f.question_id}`} dir="auto">{f.statement}</Link> : <span dir="auto">{f.statement}</span>}
                <div className="muted small">{fmtDate(f.created_at)}</div>
              </li>
            ))}
          </ul>
        )}
      </Async>
    </Card>
  );
}
