import { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Question, ResourceBrief } from "../api";
import { ActionButton, Async, Badge, BoolBadge, Card, fmtDate, fmtNum, KV, PillarBadges, ResourceItem, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";
import { QuestionCard } from "./Questions";

interface Evidence { chunk_id?: number; resource_id?: number; title?: string | null; page?: number | null; quote?: string; quote_verified?: boolean; relation?: string; [k: string]: unknown }
interface QuestionFull extends Question {
  parent: Question | null;
  findings: { id: number; statement: string; type: string; confidence: string; qa_status: string; qa_notes: string | null; evidence: Evidence[]; generated_by: string; created_at: string }[];
  children: Question[];
  related_resources: ResourceBrief[];
  searches: { adapter: string; query: string; results: number; new: number; status: string; error: string | null; at: string }[];
}

const SETTABLE = ["open", "answered", "unresolved", "deferred", "duplicate", "not_relevant"];

/** Renders a list-ish JSON value (list of strings or objects) readably. */
export function JsonList({ value }: { value: unknown }): ReactNode {
  const { t } = useI18n();
  if (value === null || value === undefined || (Array.isArray(value) && value.length === 0)) return <span className="muted">{t("none")}</span>;
  if (Array.isArray(value)) {
    return (
      <ul className="plain-list bullets">
        {value.map((x, i) => (
          <li key={i} dir="auto">{typeof x === "string" ? x : Object.entries(x as object).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(" · ")}</li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    return <KV rows={Object.entries(value as object).map(([k, v]) => [k, <span dir="auto">{typeof v === "string" ? v : JSON.stringify(v)}</span>])} />;
  }
  return <span dir="auto">{String(value)}</span>;
}

export default function QuestionDetail() {
  const { id } = useParams();
  const { t } = useI18n();
  const state = useAsync(() => api.get<QuestionFull>(`/api/questions/${id}`), [id]);
  return (
    <div className="page">
      <p><Link to="/questions"><span className="flip" aria-hidden="true">‹</span> {t("nav_questions")}</Link></p>
      <Async state={state}>{(q) => <Body q={q} reload={state.reload} />}</Async>
    </div>
  );
}

function Body({ q, reload }: { q: QuestionFull; reload: () => void }) {
  const { t, v } = useI18n();
  const after = (p: Promise<unknown>) => p.then((r) => { reload(); return r; });
  return (
    <>
      <div className="page-head"><h1 dir="auto" className="content-text">{q.text}</h1></div>
      {q.text_alt ? <p className="muted lead" dir="auto">{q.text_alt}</p> : null}
      <div className="res-meta">
        <Badge value={q.status} />
        <Badge value={q.kind} tone="neutral" />
        <PillarBadges pillars={q.pillars} />
        <span className="small">{t("priority")}: <strong>{fmtNum(q.priority, 2)}</strong></span>
      </div>
      <div className="toolbar spaced">
        <ActionButton className="btn btn-primary" onRun={() => after(api.post(`/api/questions/${q.id}/investigate`))}>{t("investigate_now")}</ActionButton>
        <ActionButton onRun={() => after(api.post(`/api/questions/${q.id}/synthesize`))}>{t("synthesize_now")}</ActionButton>
        <label className="inline-field">
          <span>{t("mark_as")}</span>
          <select
            value=""
            onChange={(e) => {
              const s = e.target.value;
              if (s) api.patch(`/api/questions/${q.id}`, { status: s }).then(reload, (x: Error) => window.alert(x.message));
            }}
          >
            <option value="">—</option>
            {SETTABLE.filter((s) => s !== q.status).map((s) => <option key={s} value={s}>{v(s)}</option>)}
          </select>
        </label>
      </div>

      <div className="grid-2">
        <Card title={t("details")}>
          <KV rows={[
            [t("rationale"), q.rationale ? <span dir="auto">{q.rationale}</span> : null],
            [t("created_by"), v(q.created_by)],
            [t("created"), fmtDate(q.created_at)],
            [t("investigated_at"), fmtDate(q.investigated_at)],
            [t("depth"), q.depth],
            [t("attempts"), q.attempts],
            [t("scores"), q.scores ? <span className="chips">{Object.entries(q.scores).map(([k, n]) => <span key={k} className="chip">{k} <strong>{typeof n === "number" ? fmtNum(n, 2) : String(n)}</strong></span>)}</span> : null],
            [t("nav_research"), q.objective_id ? `#${q.objective_id}` : null],
          ]} />
        </Card>
        <Card title={t("answer_summary")}>
          {q.answer_summary ? <p dir="auto" className="pre-line content-text">{q.answer_summary}</p> : <p className="muted">{t("none")}</p>}
          <h3>{t("search_queries")}</h3>
          <JsonList value={q.search_queries} />
          <h3>{t("next_steps")}</h3>
          <JsonList value={q.next_steps} />
        </Card>
      </div>

      <Card title={`${t("findings")} (${q.findings.length})`}>
        {q.findings.length === 0 ? <p className="muted">{t("none")}</p> : q.findings.map((f) => (
          <div key={f.id} className="finding">
            <div className="badges">
              <Badge value={f.type} /> <span className="small">{t("confidence")}:</span> <Badge value={f.confidence} />{" "}
              <span className="small">{t("qa_status")}:</span> <Badge value={f.qa_status} />
              <span className="muted small">{t("generated_by")}: {f.generated_by} · {fmtDate(f.created_at)}</span>
            </div>
            <p dir="auto" className="content-text"><strong>{f.statement}</strong></p>
            {f.qa_notes ? <p className="small" dir="auto">{t("qa_notes")}: {f.qa_notes}</p> : null}
            {f.evidence?.length ? (
              <ul className="plain-list evidence-list">
                {f.evidence.map((e, i) => (
                  <li key={i} className="evidence">
                    <div className="badges">
                      <BoolBadge value={!!e.quote_verified} yes={t("verified")} no={t("unverified")} />
                      {e.relation ? <Badge value={String(e.relation)} tone="neutral" /> : null}
                      {e.resource_id ? (
                        <Link to={`/resources/${e.resource_id}`} dir="auto">{e.title || `#${e.resource_id}`}</Link>
                      ) : <span dir="auto">{e.title}</span>}
                      {e.page !== null && e.page !== undefined ? <span className="small">{t("page_short")} {e.page}</span> : null}
                    </div>
                    {e.quote ? <blockquote dir="auto" className="quote">{e.quote}</blockquote> : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}
      </Card>

      <div className="grid-2">
        <Card title={t("parent_question")}>
          {q.parent ? <QuestionCard q={q.parent} /> : <p className="muted">{t("none")}</p>}
          <h3>{t("child_questions")} ({q.children.length})</h3>
          {q.children.length === 0 ? <p className="muted">{t("none")}</p> : <div className="q-list">{q.children.map((c) => <QuestionCard key={c.id} q={c} />)}</div>}
        </Card>
        <Card title={`${t("related_resources")} (${q.related_resources.length})`}>
          {q.related_resources.length === 0 ? <p className="muted">{t("none")}</p> : (
            <div className="res-list">{q.related_resources.map((r) => <ResourceItem key={r.id} r={r} />)}</div>
          )}
        </Card>
      </div>

      <Card title={t("search_log")}>
        {q.searches.length === 0 ? <p className="muted">{t("none")}</p> : (
          <TableWrap>
            <table>
              <thead><tr><th>{t("at")}</th><th>{t("source")}</th><th>{t("query")}</th><th>{t("results")}</th><th>{t("new_count")}</th><th>{t("status")}</th></tr></thead>
              <tbody>
                {q.searches.map((s, i) => (
                  <tr key={i}>
                    <td className="nowrap">{fmtDate(s.at)}</td>
                    <td>{s.adapter}</td>
                    <td dir="auto" className="wide-cell">{s.query}</td>
                    <td>{s.results}</td>
                    <td>{s.new}</td>
                    <td><Badge value={s.status} />{s.error ? <div className="err-text small" dir="auto">{s.error}</div> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>
    </>
  );
}
