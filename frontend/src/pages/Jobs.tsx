import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, qs } from "../api";
import { ActionButton, Async, Badge, Card, fmtDate, Pre, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";

interface JobRow {
  id: number;
  type: string;
  status: string;
  group: string | null;
  priority: number;
  attempts: number;
  max_attempts: number;
  payload: Record<string, unknown>;
  result: unknown;
  error: string | null;
  run_after: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}
interface JobsResponse { counts: Record<string, number>; by_type: { type: string; status: string; n: number }[]; jobs: JobRow[] }

const JOB_STATUSES = ["queued", "running", "succeeded", "failed", "cancelled"];

export default function Jobs() {
  const { t, v } = useI18n();
  const [sp, setSp] = useSearchParams();
  const status = sp.get("status") || "";
  const type = sp.get("type") || "";
  const state = useAsync(() => api.get<JobsResponse>(`/api/jobs${qs({ status, type, limit: 200 })}`), [status, type], 10000);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const set = (k: string, val: string) => {
    const n = new URLSearchParams(sp);
    if (val) n.set(k, val);
    else n.delete(k);
    setSp(n);
  };
  const counts = state.data?.counts || {};
  const types = Array.from(new Set((state.data?.by_type || []).map((x) => x.type))).sort();
  const statuses = Array.from(new Set([...JOB_STATUSES, ...Object.keys(counts)]));

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("jobs_title")}</h1>
        <div className="toolbar">
          <ActionButton
            className="btn btn-primary"
            disabled={!counts.failed}
            onRun={async () => { const r = await api.post<{ retried: number }>("/api/jobs/retry-failed"); state.reload(); return r; }}
            done={(r) => `${t("retried_n")} ${(r as { retried: number }).retried}`}
          >
            {t("retry_all_failed")}
          </ActionButton>
          <span className="muted small">{t("auto_refresh_10")}</span>
        </div>
      </div>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={!status} className={`tab ${!status ? "active" : ""}`} onClick={() => set("status", "")}>
          {t("all")} <span className="tab-count">{Object.values(counts).reduce((a, b) => a + b, 0)}</span>
        </button>
        {statuses.map((s) => (
          <button type="button" role="tab" aria-selected={status === s} key={s} className={`tab ${status === s ? "active" : ""}`} onClick={() => set("status", s)}>
            {v(s)} <span className="tab-count">{counts[s] || 0}</span>
          </button>
        ))}
      </div>
      <Card actions={
        <select value={type} onChange={(e) => set("type", e.target.value)} aria-label={t("type")}>
          <option value="">{t("type")}: {t("all")}</option>
          {types.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
      } title={t("jobs")}>
        <Async state={state}>
          {(d) => d.jobs.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    <th>#</th><th>{t("type")}</th><th>{t("status")}</th><th>{t("group")}</th><th>{t("priority")}</th>
                    <th>{t("attempts")}</th><th>{t("created")}</th><th>{t("finished")}</th><th>{t("actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.jobs.map((j) => (
                    <Fragment key={j.id}>
                      <tr>
                        <td>{j.id}</td>
                        <td>{j.type}</td>
                        <td><Badge value={j.status} /></td>
                        <td>{j.group || "—"}</td>
                        <td>{j.priority}</td>
                        <td>{j.attempts}/{j.max_attempts}</td>
                        <td className="nowrap">{fmtDate(j.created_at)}</td>
                        <td className="nowrap">{fmtDate(j.finished_at)}</td>
                        <td className="nowrap">
                          <button type="button" className={`btn btn-small ${j.error ? "btn-warn" : ""}`} onClick={() => setOpen({ ...open, [j.id]: !open[j.id] })} aria-expanded={!!open[j.id]}>
                            {j.error ? t("show_error") : t("details")}
                          </button>{" "}
                          {["failed", "cancelled"].includes(j.status) ? (
                            <ActionButton className="btn btn-small" onRun={async () => { const r = await api.post(`/api/jobs/${j.id}/retry`); state.reload(); return r; }}>{t("retry")}</ActionButton>
                          ) : null}{" "}
                          {j.status === "queued" ? (
                            <ActionButton className="btn btn-small btn-danger" onRun={async () => { const r = await api.post(`/api/jobs/${j.id}/cancel`); state.reload(); return r; }}>{t("cancel")}</ActionButton>
                          ) : null}
                        </td>
                      </tr>
                      {open[j.id] ? (
                        <tr className="detail-row">
                          <td colSpan={9}>
                            {j.error ? <Pre>{j.error}</Pre> : null}
                            <div className="small"><strong>{t("payload")}:</strong> <code className="break">{JSON.stringify(j.payload)}</code></div>
                            {j.result !== null && j.result !== undefined ? <div className="small"><strong>{t("result")}:</strong> <code className="break">{JSON.stringify(j.result)}</code></div> : null}
                            <div className="small muted">{t("started")}: {fmtDate(j.started_at)} · {t("run_after")}: {fmtDate(j.run_after)}</div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Async>
      </Card>
    </div>
  );
}
