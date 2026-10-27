import { Link, useNavigate, useParams } from "react-router-dom";
import { api, qs, ResourceBrief, Status } from "../api";
import { ActionButton, Async, Badge, Bars, Card, CountList, fmtDate, fmtNum, PillarBadges, ResourceItem, Stat, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";

interface Stats {
  day: string;
  discoveries: {
    total: number;
    by_type: Record<string, number>;
    by_language: Record<string, number>;
    by_source: Record<string, number>;
    by_access: Record<string, number>;
    paid_catalogued: number;
    entities: Record<string, number>;
    institutions: { id: number; name: string }[];
    experts: { id: number; name: string }[];
    items: ResourceBrief[];
  };
  pillars: Record<string, number>;
  research: {
    questions_created: number;
    questions_investigated: number;
    questions_answered: number;
    open_questions: number;
    findings: number;
    findings_with_verified_evidence: number;
    claims_extracted: number;
    claims_with_verified_quotes: number;
    findings_list: { id: number; question_id: number | null; statement: string; type: string; confidence: string; qa: string }[];
  };
  activity: {
    searches: { source: string; searches: number; new: number }[];
    sources_visited: number;
    downloaded: number;
    processed: number;
    jobs: Record<string, Record<string, number>>;
    failed_jobs: { id: number; type: string; error: string }[];
    pending_jobs: number;
    http_requests: number;
    ai_calls: number;
    ai_cost_usd: number;
  };
  gaps: {
    emerging_topics: { topic: string; topic_ar: string; today: number; prev_daily_avg: number }[];
    new_questions: { id: number; text: string; text_alt: string | null; kind: string; priority: number; rationale: string | null }[];
    gap_findings: { id: number; statement: string; question_id: number | null }[];
  };
}

interface Plan {
  prioritized_questions?: { id: number; text: string; text_alt: string | null; priority: number; kind: string; pillars: string[] }[];
  sources_to_revisit?: { id: number; name: string; next_run_at: string | null }[];
  pending_documents?: { id: number; title: string; acquisition: string; processing: string }[];
  queued_jobs?: Record<string, number>;
  deferred_questions?: number;
}

interface DashboardData {
  day: string;
  live: boolean;
  stats: Stats;
  plan: Plan | null;
  previous: { day: string; summary: string | null; stats: Stats | null; plan: Plan | null; finalized: boolean } | null;
  status: Status;
}

export function localISODate(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function shiftDay(day: string, delta: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return localISODate(new Date(y, m - 1, d + delta));
}

export default function Dashboard() {
  const params = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const today = localISODate();
  const day = params.day && /^\d{4}-\d{2}-\d{2}$/.test(params.day) ? params.day : today;
  const isToday = day === today;
  const state = useAsync(() => api.get<DashboardData>(`/api/dashboard${qs({ day })}`), [day], isToday ? 15000 : undefined);
  const go = (d: string) => navigate(d === today ? "/" : `/day/${d}`);

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("dash_title")}</h1>
        <div className="toolbar">
          <button type="button" className="btn" onClick={() => go(shiftDay(day, -1))}>
            <span className="flip" aria-hidden="true">‹</span> {t("prev_day")}
          </button>
          <label className="inline-field">
            <span className="sr-only">{t("day")}</span>
            <input type="date" value={day} max={today} onChange={(e) => e.target.value && go(e.target.value)} aria-label={t("day")} />
          </label>
          <button type="button" className="btn" onClick={() => go(shiftDay(day, 1))} disabled={isToday}>
            {t("next_day")} <span className="flip" aria-hidden="true">›</span>
          </button>
          {!isToday ? (
            <button type="button" className="btn btn-ghost" onClick={() => go(today)}>
              {t("today")}
            </button>
          ) : null}
          {state.data ? (
            state.data.live ? (
              <Badge tone="good">● {t("live")}</Badge>
            ) : (
              <Badge tone="neutral">{t("stored")}</Badge>
            )
          ) : null}
          {isToday ? <span className="muted small">{t("auto_refresh")}</span> : null}
        </div>
      </div>
      <Async state={state}>{(d) => <DashboardBody d={d} reload={state.reload} />}</Async>
    </div>
  );
}

export function StatusStrip({ s }: { s: Status }) {
  const { t, v } = useI18n();
  const ai = s.ai;
  return (
    <div className="status-strip" aria-label={t("system_status")}>
      <div className="strip-item">
        <span className="strip-label">{t("worker")}</span>
        <Badge tone={s.worker.alive ? "good" : "bad"}>{s.worker.alive ? t("alive") : t("not_running")}</Badge>
        {s.worker.state ? <span className="muted small">{v(String(s.worker.state))}</span> : null}
      </div>
      <div className="strip-item">
        <span className="strip-label">{t("automation")}</span>
        <Badge tone={s.automation.enabled ? "good" : "muted"}>{s.automation.enabled ? t("enabled") : t("disabled")}</Badge>
        {s.automation.paused ? <Badge tone="warn">{t("paused")}</Badge> : null}
        {!s.automation.within_operating_hours ? <Badge tone="warn">{t("outside_hours")}</Badge> : null}
      </div>
      <div className="strip-item">
        <span className="strip-label">{t("ai")}</span>
        <Badge tone={ai.configured && ai.enabled ? "good" : "muted"}>{ai.configured ? (ai.enabled ? t("configured") : t("disabled")) : t("not_configured")}</Badge>
        <span className="small">
          {fmtNum(ai.calls_today)}/{fmtNum(ai.daily_call_limit)} · ${fmtNum(ai.cost_today_usd, 2)}/${fmtNum(ai.daily_budget_usd, 2)}
        </span>
      </div>
      <div className="strip-item">
        <span className="strip-label">{t("ocr")}</span>
        <Badge tone={s.ocr.tesseract || s.ocr.claude_ocr_available ? "good" : "muted"}>
          {s.ocr.tesseract || s.ocr.claude_ocr_available ? t("available") : t("unavailable")}
        </Badge>
        <span className="muted small">
          {s.ocr.tesseract ? `tesseract ${s.ocr.languages.join("+")}` : ""}
          {s.ocr.claude_ocr_available ? " claude" : ""}
        </span>
      </div>
      <div className="strip-item">
        <span className="strip-label">{t("storage")}</span>
        <span className="small">
          {fmtNum(s.storage.used_gb, 3)} / {fmtNum(s.storage.limit_gb, 1)} GB
        </span>
      </div>
      <div className="strip-item">
        <span className="strip-label">{t("http_requests")}</span>
        <span className="small">
          {fmtNum(s.usage_today.http_requests)} / {fmtNum(s.limits.daily_http_request_limit)}
        </span>
      </div>
    </div>
  );
}

function pillarLabelKey(k: string) {
  return (["children", "parents", "murabbi"].includes(k) ? `pillar_${k}` : "unclassified") as "pillar_children";
}

function DashboardBody({ d, reload }: { d: DashboardData; reload: () => void }) {
  const { t, lang } = useI18n();
  const st = d.stats;
  const disc = st.discoveries;
  const res = st.research;
  const act = st.activity;
  const gaps = st.gaps;
  const plan = d.plan || {};

  return (
    <>
      <StatusStrip s={d.status} />

      {d.previous ? (
        <Card title={`${t("yesterday")} — ${d.previous.day}`} className="card-muted" actions={<Badge tone={d.previous.finalized ? "good" : "neutral"}>{d.previous.finalized ? t("finalized") : t("not_finalized")}</Badge>}>
          <p dir="auto">{d.previous.summary || t("nothing_yet")}</p>
          <Link to={`/day/${d.previous.day}`}>{t("open_day")}</Link>
        </Card>
      ) : null}

      <div className="grid-2">
        <Card title={t("discoveries")}>
          <div className="stats-row">
            <Stat label={t("new_resources")} value={fmtNum(disc.total)} />
            <Stat label={t("paid_catalogued")} value={fmtNum(disc.paid_catalogued)} />
          </div>
          <div className="kv-compact">
            <div><strong>{t("by_type")}:</strong> <CountList data={disc.by_type} /></div>
            <div><strong>{t("by_language")}:</strong> <CountList data={disc.by_language} /></div>
            <div><strong>{t("by_source")}:</strong> <CountList data={disc.by_source} /></div>
            <div><strong>{t("by_access")}:</strong> <CountList data={disc.by_access} /></div>
            <div><strong>{t("entities_found")}:</strong> <CountList data={disc.entities} /></div>
          </div>
          <h3>{t("new_institutions")}</h3>
          <EntityChips list={disc.institutions} />
          <h3>{t("new_experts")}</h3>
          <EntityChips list={disc.experts} />
        </Card>

        <Card title={t("pillar_breakdown")}>
          <Bars data={st.pillars} labels={(k) => t(pillarLabelKey(k))} colorFor={(k) => `fill-${k}`} />
        </Card>
      </div>

      <Card title={`${t("new_items")} (${disc.items.length})`}>
        {disc.items.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
          <div className="res-list">
            {disc.items.map((r) => <ResourceItem key={r.id} r={r} />)}
          </div>
        )}
      </Card>

      <div className="grid-2">
        <Card title={t("research_progress")}>
          <div className="stats-grid">
            <Stat label={t("q_created")} value={fmtNum(res.questions_created)} />
            <Stat label={t("q_investigated")} value={fmtNum(res.questions_investigated)} />
            <Stat label={t("q_answered")} value={fmtNum(res.questions_answered)} />
            <Stat label={t("open_questions")} value={fmtNum(res.open_questions)} />
            <Stat label={t("findings")} value={fmtNum(res.findings)} />
            <Stat label={t("findings_verified")} value={fmtNum(res.findings_with_verified_evidence)} />
            <Stat label={t("claims_extracted")} value={fmtNum(res.claims_extracted)} />
            <Stat label={t("claims_verified")} value={fmtNum(res.claims_with_verified_quotes)} />
          </div>
          {res.findings_list.length ? (
            <ul className="plain-list">
              {res.findings_list.map((f) => (
                <li key={f.id}>
                  <Badge value={f.type} /> <Badge value={f.confidence} /> <Badge value={f.qa} />{" "}
                  {f.question_id ? <Link to={`/questions/${f.question_id}`} dir="auto">{f.statement}</Link> : <span dir="auto">{f.statement}</span>}
                </li>
              ))}
            </ul>
          ) : null}
        </Card>

        <Card title={t("collection_activity")}>
          <div className="stats-grid">
            <Stat label={t("sources_visited")} value={fmtNum(act.sources_visited)} />
            <Stat label={t("downloaded")} value={fmtNum(act.downloaded)} />
            <Stat label={t("processed")} value={fmtNum(act.processed)} />
            <Stat label={t("pending_jobs")} value={fmtNum(act.pending_jobs)} />
            <Stat label={t("http_requests")} value={fmtNum(act.http_requests)} />
            <Stat label={t("ai_calls")} value={fmtNum(act.ai_calls)} sub={`$${fmtNum(act.ai_cost_usd, 2)}`} />
          </div>
          <h3>{t("searches_per_source")}</h3>
          {act.searches.length === 0 ? <p className="muted">{t("none")}</p> : (
            <TableWrap>
              <table>
                <thead><tr><th>{t("source")}</th><th>{t("searches")}</th><th>{t("new_count")}</th></tr></thead>
                <tbody>
                  {act.searches.map((s) => <tr key={s.source}><td>{s.source}</td><td>{s.searches}</td><td>{s.new}</td></tr>)}
                </tbody>
              </table>
            </TableWrap>
          )}
          <h3>{t("jobs_by_type")}</h3>
          {Object.keys(act.jobs).length === 0 ? <p className="muted">{t("none")}</p> : (
            <TableWrap>
              <table>
                <thead><tr><th>{t("type")}</th><th>{t("status")}</th></tr></thead>
                <tbody>
                  {Object.entries(act.jobs).map(([jt, m]) => (
                    <tr key={jt}><td>{jt}</td><td><CountList data={m} /></td></tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
          <h3>{t("failed_jobs")} ({act.failed_jobs.length})</h3>
          {act.failed_jobs.length === 0 ? <p className="muted">{t("none")}</p> : (
            <ul className="plain-list">
              {act.failed_jobs.map((j) => (
                <li key={j.id}>
                  <strong>#{j.id}</strong> {j.type} <span className="err-text" dir="auto">{j.error}</span>{" "}
                  <ActionButton className="btn btn-small" onRun={async () => { const r = await api.post(`/api/jobs/${j.id}/retry`); reload(); return r; }}>
                    {t("retry")}
                  </ActionButton>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid-2">
        <Card title={t("knowledge_gaps")}>
          <h3>{t("emerging_topics")}</h3>
          {gaps.emerging_topics.length === 0 ? <p className="muted">{t("none")}</p> : (
            <ul className="plain-list">
              {gaps.emerging_topics.map((e) => (
                <li key={e.topic}>
                  <span dir="auto">{lang === "ar" ? e.topic_ar : e.topic}</span> — {t("today_n")}: <strong>{e.today}</strong>, {t("prev_avg")}: {e.prev_daily_avg}
                </li>
              ))}
            </ul>
          )}
          <h3>{t("new_questions")}</h3>
          {gaps.new_questions.length === 0 ? <p className="muted">{t("none")}</p> : (
            <ul className="plain-list">
              {gaps.new_questions.map((q) => (
                <li key={q.id}>
                  <Link to={`/questions/${q.id}`} dir="auto">{q.text}</Link>
                  {q.text_alt ? <div className="muted small" dir="auto">{q.text_alt}</div> : null}
                  <div className="small"><Badge value={q.kind} tone="neutral" /> {t("priority")}: {fmtNum(q.priority, 2)}</div>
                </li>
              ))}
            </ul>
          )}
          <h3>{t("gap_findings")}</h3>
          {gaps.gap_findings.length === 0 ? <p className="muted">{t("none")}</p> : (
            <ul className="plain-list">
              {gaps.gap_findings.map((f) => (
                <li key={f.id} dir="auto">
                  {f.question_id ? <Link to={`/questions/${f.question_id}`}>{f.statement}</Link> : f.statement}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={t("next_day_plan")}>
          {!d.plan || Object.keys(d.plan).length === 0 ? <p className="muted">{t("no_plan")}</p> : (
            <>
              <h3>{t("prioritized_questions")}</h3>
              {(plan.prioritized_questions || []).length === 0 ? <p className="muted">{t("none")}</p> : (
                <ol className="plain-list numbered">
                  {plan.prioritized_questions!.map((q) => (
                    <li key={q.id}>
                      <Link to={`/questions/${q.id}`} dir="auto">{q.text}</Link> <PillarBadges pillars={q.pillars} />{" "}
                      <span className="muted small">{fmtNum(q.priority, 2)}</span>
                    </li>
                  ))}
                </ol>
              )}
              <h3>{t("sources_to_revisit")}</h3>
              {(plan.sources_to_revisit || []).length === 0 ? <p className="muted">{t("none")}</p> : (
                <ul className="plain-list">
                  {plan.sources_to_revisit!.map((s) => (
                    <li key={s.id}><Link to="/sources" dir="auto">{s.name}</Link> <span className="muted small">{fmtDate(s.next_run_at)}</span></li>
                  ))}
                </ul>
              )}
              <h3>{t("pending_documents")}</h3>
              {(plan.pending_documents || []).length === 0 ? <p className="muted">{t("none")}</p> : (
                <ul className="plain-list">
                  {plan.pending_documents!.map((r) => (
                    <li key={r.id}><Link to={`/resources/${r.id}`} dir="auto">{r.title}</Link> <Badge value={r.acquisition} /> <Badge value={r.processing} /></li>
                  ))}
                </ul>
              )}
              <h3>{t("queued_jobs")}</h3>
              <CountList data={plan.queued_jobs} />
              {plan.deferred_questions !== undefined ? (
                <p className="small">{t("deferred_questions")}: <strong>{plan.deferred_questions}</strong></p>
              ) : null}
            </>
          )}
        </Card>
      </div>
    </>
  );
}

function EntityChips({ list }: { list: { id: number; name: string }[] }) {
  const { t } = useI18n();
  if (!list.length) return <p className="muted">{t("none")}</p>;
  return (
    <span className="chips">
      {list.map((e) => (
        <Link className="chip" key={e.id} to={`/entities/${e.id}`} dir="auto">{e.name}</Link>
      ))}
    </span>
  );
}
