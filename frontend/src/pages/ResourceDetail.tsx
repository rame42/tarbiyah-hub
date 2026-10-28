import { ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, qs } from "../api";
import {
  ActionButton, Async, Badge, RelevanceBadge, BoolBadge, Card, ErrorBox, fmtDate, fmtNum, fmtTimestamp, KV, Loading, PillarBadge, Pre, TableWrap, useAsync, videoUrlAt, WatchButton
} from "../components";
import { useI18n } from "../i18n";
import { ACCESS_VALUES, RESOURCE_TYPES } from "./Library";

interface ResourceFull {
  id: number;
  resource_type: string;
  title: string;
  alt_titles: string[] | null;
  title_translations: Record<string, unknown> | null;
  authors_text: string | null;
  description: string | null;
  language: string | null;
  published_date: string | null;
  year: number | null;
  publisher: string | null;
  url: string | null;
  canonical_url: string | null;
  download_url: string | null;
  source_key: string | null;
  external_id: string | null;
  doi: string | null;
  isbn: string | null;
  collection_method: string | null;
  license: string | null;
  license_url: string | null;
  access_status: string;
  download_permitted: boolean;
  permission_basis: string | null;
  price: string | null;
  currency: string | null;
  purchase_url: string | null;
  local_path: string | null;
  file_mime: string | null;
  file_size: number | null;
  checksum_sha256: string | null;
  duplicate_of_id: number | null;
  acquisition_status: string;
  processing_status: string;
  index_status: string;
  ai_status: string;
  extraction_method: string | null;
  extraction_quality: number | null;
  page_count: number | null;
  word_count: number | null;
  last_error: string | null;
  summary: string | null;
  summary_lang: string | null;
  evidence_category: string | null;
  quality: Record<string, unknown> | null;
  keywords: string[] | null;
  discovered_at: string | null;
  collected_at: string | null;
  processed_at: string | null;
  updated_at: string | null;
  pillars: { pillar: string; score: number; method: string }[];
  labels?: string[] | null;
  deleted?: boolean;
  archived?: boolean;
  relevance?: number | null;
  extra?: Record<string, unknown> | null;
  topics: { id: number; name_en: string; name_ar: string; score: number; method: string }[];
  entities: { id: number; type: string; name: string; role: string | null }[];
  claims: { id: number; type: string; statement: string; quote: string | null; page: number | null; evidence_type: string | null; verified: boolean | null; qa: string; generated_by: string; chunk_id: number | null }[];
  citations: { id: number; title: string | null; raw: string | null; status: string; doi: string | null; cited_resource_id: number | null }[];
  history: { at: string; agent: string; action: string; status: string; detail: string | null }[];
  jobs: { id: number; type: string; status: string; attempts: number; error: string | null; finished_at: string | null }[];
  chunk_count: number;
  source: { id: number; name: string; adapter: string } | null;
  has_file: boolean;
}

function translationText(v: unknown): { text: string; method?: string } {
  if (typeof v === "string") return { text: v };
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    const text = String(o.text ?? o.title ?? JSON.stringify(o));
    const method = o.method ?? o.by ?? o.generated_by;
    return { text, method: method ? String(method) : undefined };
  }
  return { text: String(v) };
}

export default function ResourceDetail() {
  const { id } = useParams();
  const { t } = useI18n();
  const state = useAsync(() => api.get<ResourceFull>(`/api/resources/${id}`), [id]);
  return (
    <div className="page">
      <p><Link to="/library"><span className="flip" aria-hidden="true">‹</span> {t("nav_library")}</Link></p>
      <Async state={state}>{(r) => <Body r={r} reload={state.reload} />}</Async>
    </div>
  );
}

function Body({ r, reload }: { r: ResourceFull; reload: () => void }) {
  const { t, v, lang } = useI18n();
  const [showText, setShowText] = useState(false);
  const act = (a: string) => async () => {
    const res = await api.post(`/api/resources/${r.id}/${a}`);
    reload();
    return res;
  };
  const translations = Object.entries(r.title_translations || {});

  return (
    <>
      <div className="page-head">
        <h1 dir="auto" className="content-text">{r.title}</h1>
      </div>
      <div className="res-meta">
        <Badge value={r.resource_type} tone="neutral" />
        {r.language ? <span className="badge badge-neutral">{r.language}</span> : null}
        <Badge value={r.access_status} />
        {r.pillars.map((p) => <PillarBadge key={p.pillar} pillar={p.pillar} />)}
        <RelevanceBadge value={r.relevance} />
        {r.duplicate_of_id ? <Link to={`/resources/${r.duplicate_of_id}`}><Badge tone="muted">{v("duplicate")} → #{r.duplicate_of_id}</Badge></Link> : null}
      </div>

      {(r.labels || []).length ? (
        <div className="res-meta">{(r.labels || []).map((lb) => <span key={lb} className="badge badge-label">🏷 {lb}</span>)}</div>
      ) : null}

      {r.deleted ? (
        <div className="alert alert-warn bulk-bar" role="status">
          <span>{t("deleted_banner")}</span>
          <ActionButton onRun={act("restore")}>{t("restore")}</ActionButton>
        </div>
      ) : null}

      {(r.extra || {}).relevance_reason ? (
        <p className="small muted" dir="auto"><strong>{t("relevance_reason")}:</strong> {String((r.extra || {}).relevance_reason)}</p>
      ) : null}

      {r.archived && !r.deleted ? (
        <div className="alert alert-info bulk-bar" role="status">
          <span>{t("archived_banner")}{(r.extra || {}).archived_reason ? ` ${t("archived_reason")}: ${String((r.extra || {}).archived_reason)}.` : ""}</span>
          <ActionButton onRun={act("unarchive")}>{t("unarchive_item")}</ActionButton>
        </div>
      ) : null}

      <div className="toolbar spaced">
        {!r.archived && !r.deleted ? <ActionButton onRun={act("archive")}>{t("archive_item")}</ActionButton> : null}
        <ActionButton onRun={act("reprocess")}>{t("reprocess")}</ActionButton>
        <ActionButton onRun={act("reanalyze")}>{t("reanalyze")}</ActionButton>
        <ActionButton onRun={act("acquire")}>{t("acquire")}</ActionButton>
        {r.has_file ? (
          <a className="btn" href={`/api/resources/${r.id}/file`} target="_blank" rel="noopener noreferrer">{t("open_file")}</a>
        ) : null}
        <button type="button" className="btn" onClick={() => setShowText((x) => !x)}>
          {showText ? t("hide_full_text") : t("full_text")}
        </button>
        <WatchButton url={r.url} type={r.resource_type} />
        {r.url && !(r.resource_type === "video" || /youtube\.com|youtu\.be|tiktok\.com/i.test(r.url)) ? (
          <a className="btn btn-ghost" href={r.url} target="_blank" rel="noopener noreferrer">{t("external_link")} ↗</a>
        ) : null}
      </div>

      {showText ? <FullText id={r.id} /> : null}

      {!r.deleted ? <EditCard r={r} reload={reload} /> : null}

      <div className="grid-2">
        <Card title={t("metadata")}>
          <KV rows={[
            [t("authors"), r.authors_text ? <span dir="auto">{r.authors_text}</span> : null],
            [t("year"), r.year ?? r.published_date],
            [t("publisher"), r.publisher ? <span dir="auto">{r.publisher}</span> : null],
            [t("doi"), r.doi],
            [t("isbn"), r.isbn],
            [t("keywords"), r.keywords?.length ? <span dir="auto">{r.keywords.join(", ")}</span> : null],
            [t("evidence_category"), r.evidence_category ? v(r.evidence_category) : null],
            [t("description"), r.description ? <span dir="auto" className="pre-line">{r.description}</span> : null],
          ]} />
          {r.alt_titles && r.alt_titles.length ? (
            <ul className="plain-list">{r.alt_titles.map((a) => <li key={a} dir="auto">{a}</li>)}</ul>
          ) : null}
          <h3>{t("title_translations")}</h3>
          {translations.length === 0 ? <p className="muted">{t("none")}</p> : (
            <ul className="plain-list">
              {translations.map(([l, val]) => {
                const x = translationText(val);
                return (
                  <li key={l}>
                    <span className="badge badge-neutral">{l}</span> <span dir="auto">{x.text}</span>{" "}
                    <Badge tone="warn">{t("machine_translation")}{x.method ? ` · ${x.method}` : ""}</Badge>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title={t("provenance")}>
          <KV rows={[
            [t("source"), r.source ? <Link to="/sources">{r.source.name} ({r.source.adapter})</Link> : r.source_key],
            [t("url"), r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer" className="break" dir="ltr">{r.url}</a> : null],
            [t("download_url"), r.download_url ? <a href={r.download_url} target="_blank" rel="noopener noreferrer" className="break" dir="ltr">{r.download_url}</a> : null],
            [t("collection_method"), r.collection_method ? v(r.collection_method) : null],
            [t("discovered_at"), fmtDate(r.discovered_at)],
            [t("collected_at"), fmtDate(r.collected_at)],
            [t("license"), r.license ? (r.license_url ? <a href={r.license_url} target="_blank" rel="noopener noreferrer">{r.license}</a> : r.license) : null],
            [t("access_status"), <Badge value={r.access_status} />],
            [t("download_permitted"), <BoolBadge value={r.download_permitted} />],
            [t("permission_basis"), r.permission_basis ? <span dir="auto">{r.permission_basis}</span> : null],
            [t("checksum"), r.checksum_sha256 ? <code className="break">{r.checksum_sha256}</code> : null],
            [t("file_size"), r.file_size ? `${fmtNum(r.file_size / 1024, 1)} KB ${r.file_mime || ""}` : null],
            ...(r.price || r.purchase_url
              ? ([[t("price"), `${r.price || ""} ${r.currency || ""}`.trim() || null],
                  [t("buy"), r.purchase_url ? <a href={r.purchase_url} target="_blank" rel="noopener noreferrer" className="break">{r.purchase_url}</a> : null]] as [string, ReactNode][])
              : []),
          ]} />
        </Card>
      </div>

      <div className="grid-2">
        <Card title={t("statuses")}>
          <KV rows={[
            [t("acquisition"), <Badge value={r.acquisition_status} />],
            [t("processing"), <Badge value={r.processing_status} />],
            [t("index"), <Badge value={r.index_status} />],
            [t("ai_status"), <Badge value={r.ai_status} />],
            [t("processed_at"), fmtDate(r.processed_at)],
            [t("updated"), fmtDate(r.updated_at)],
          ]} />
          <h3>{t("extraction")}</h3>
          <KV rows={[
            [t("extraction_method"), r.extraction_method],
            [t("extraction_quality"), r.extraction_quality !== null ? fmtNum(r.extraction_quality, 2) : null],
            [t("pages_count"), r.page_count],
            [t("words"), r.word_count !== null ? fmtNum(r.word_count) : null],
            [t("passages_count"), fmtNum(r.chunk_count)],
          ]} />
          {r.quality && Object.keys(r.quality).length ? <Pre>{JSON.stringify(r.quality, null, 2)}</Pre> : null}
          {r.last_error ? <ErrorBox error={`${t("last_error")}: ${r.last_error}`} /> : null}
        </Card>

        <Card title={t("ai_summary")} className="card-ai">
          <p className="muted small">{t("ai_summary_note")}</p>
          {r.summary ? <p dir="auto" className="pre-line content-text">{r.summary}</p> : <p className="muted">{t("none")}</p>}
          <h3>{t("pillars")}</h3>
          {r.pillars.length === 0 ? <p className="muted">{t("unclassified")}</p> : (
            <ul className="plain-list">
              {r.pillars.map((p) => (
                <li key={p.pillar}>
                  <PillarBadge pillar={p.pillar} /> {t("score")}: {fmtNum(p.score, 2)} · {t("method")}: <Badge value={p.method} tone="neutral" />
                </li>
              ))}
            </ul>
          )}
          <h3>{t("topics")}</h3>
          {r.topics.length === 0 ? <p className="muted">{t("none")}</p> : (
            <span className="chips">
              {r.topics.map((x) => (
                <Link className="chip" key={x.id} to={`/library?topic=${x.id}`}>
                  {lang === "ar" ? x.name_ar : x.name_en} <span className="muted small">{fmtNum(x.score, 2)} · {v(x.method)}</span>
                </Link>
              ))}
            </span>
          )}
          <h3>{t("entities")}</h3>
          {r.entities.length === 0 ? <p className="muted">{t("none")}</p> : (
            <span className="chips">
              {r.entities.map((e) => (
                <Link className="chip" key={`${e.id}-${e.role}`} to={`/entities/${e.id}`}>
                  <span dir="auto">{e.name}</span> <span className="muted small">{v(e.type)}{e.role ? ` · ${e.role}` : ""}</span>
                </Link>
              ))}
            </span>
          )}
        </Card>
      </div>

      <Card title={`${t("claims")} (${r.claims.length})`}>
        {r.claims.length === 0 ? <p className="muted">{t("none")}</p> : (
          <TableWrap>
            <table>
              <thead>
                <tr>
                  <th>{t("claim_statement")}</th>
                  <th>{t("claim_quote")}</th>
                  <th>{t("verified")}</th>
                  <th>{t("page")}</th>
                  <th>{t("type")}</th>
                  <th>{t("qa_status")}</th>
                </tr>
              </thead>
              <tbody>
                {r.claims.map((c) => (
                  <tr key={c.id}>
                    <td className="wide-cell" dir="auto">{c.statement}</td>
                    <td className="wide-cell">{c.quote ? <q dir="auto" className="quote">{c.quote}</q> : "—"}</td>
                    <td><BoolBadge value={!!c.verified} yes={t("verified")} no={t("unverified")} /></td>
                    <td>{c.page ?? "—"}</td>
                    <td>{v(c.type)}{c.evidence_type ? ` · ${v(c.evidence_type)}` : ""}</td>
                    <td><Badge value={c.qa} /> <span className="muted small">{c.generated_by}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <Card title={`${t("citations")} (${r.citations.length})`}>
        {r.citations.length === 0 ? <p className="muted">{t("none")}</p> : (
          <ul className="plain-list">
            {r.citations.map((c) => (
              <li key={c.id}>
                <Badge value={c.status} />{" "}
                {c.cited_resource_id ? <Link to={`/resources/${c.cited_resource_id}`} dir="auto">{c.title || c.raw}</Link> : <span dir="auto">{c.title || c.raw}</span>}
                {c.doi ? <span className="muted small"> · DOI {c.doi}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Passages id={r.id} total={r.chunk_count} url={r.url} />

      <div className="grid-2">
        <Card title={t("history")}>
          {r.history.length === 0 ? <p className="muted">{t("none")}</p> : (
            <TableWrap>
              <table>
                <thead><tr><th>{t("at")}</th><th>{t("agent")}</th><th>{t("action")}</th><th>{t("status")}</th><th>{t("details")}</th></tr></thead>
                <tbody>
                  {r.history.map((h, i) => (
                    <tr key={i}><td className="nowrap">{fmtDate(h.at)}</td><td>{h.agent}</td><td>{h.action}</td><td><Badge value={h.status} /></td><td dir="auto" className="wide-cell">{h.detail}</td></tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Card>
        <Card title={t("jobs")}>
          {r.jobs.length === 0 ? <p className="muted">{t("none")}</p> : (
            <TableWrap>
              <table>
                <thead><tr><th>#</th><th>{t("type")}</th><th>{t("status")}</th><th>{t("attempts")}</th><th>{t("finished")}</th><th>{t("error_col")}</th></tr></thead>
                <tbody>
                  {r.jobs.map((j) => (
                    <tr key={j.id}><td>{j.id}</td><td>{j.type}</td><td><Badge value={j.status} /></td><td>{j.attempts}</td><td className="nowrap">{fmtDate(j.finished_at)}</td><td className="err-text wide-cell" dir="auto">{j.error}</td></tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Card>
      </div>
    </>
  );
}

function FullText({ id }: { id: number }) {
  const { t } = useI18n();
  const state = useAsync(() => api.get<string>(`/api/resources/${id}/text`), [id]);
  return (
    <Card title={t("full_text")}>
      <Async state={state}>{(txt) => <Pre>{txt}</Pre>}</Async>
    </Card>
  );
}

interface Passage { id: number; seq: number; page: number | null; heading: string | null; lang: string | null; timestamp: number | null; text: string }

function Passages({ id, total, url }: { id: number; total: number; url?: string | null }) {
  const { t } = useI18n();
  const [offset, setOffset] = useState(0);
  const limit = 10;
  const state = useAsync(() => api.get<{ total: number; passages: Passage[] }>(`/api/resources/${id}/passages${qs({ offset, limit })}`), [id, offset]);
  const n = state.data?.total ?? total;
  return (
    <Card title={`${t("passages")} (${fmtNum(n)})`}>
      <ErrorBox error={state.error} />
      {state.loading && !state.data ? <Loading /> : null}
      {state.data && state.data.passages.length === 0 ? <p className="muted">{t("none")}</p> : null}
      {state.data?.passages.map((p) => (
        <div key={p.id} className="passage" id={`passage-${p.id}`}>
          <div className="passage-meta">
            <span className="badge badge-neutral">#{p.seq + 1}</span>
            {p.page !== null ? <span>{t("page_short")} {p.page}</span> : null}
            {p.timestamp !== null ? (url ? (
              <a href={videoUrlAt(url, p.timestamp)} target="_blank" rel="noopener noreferrer" title={t("play_from_here")}>⏱ {fmtTimestamp(p.timestamp)} ▶</a>
            ) : <span>⏱ {fmtTimestamp(p.timestamp)}</span>) : null}
            {p.lang ? <span className="muted">{p.lang}</span> : null}
            {p.heading ? <strong dir="auto">{p.heading}</strong> : null}
          </div>
          <p dir="auto" className="pre-line content-text">{p.text}</p>
        </div>
      ))}
      {n > limit ? (
        <div className="pager">
          <button type="button" className="btn btn-small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>{t("prev")}</button>
          <span>{offset + 1}–{Math.min(offset + limit, n)} {t("of")} {n}</span>
          <button type="button" className="btn btn-small" disabled={offset + limit >= n} onClick={() => setOffset(offset + limit)}>{t("next")}</button>
        </div>
      ) : null}
    </Card>
  );
}

const PILLAR_KEYS = ["children", "parents", "murabbi"];

function EditCard({ r, reload }: { r: ResourceFull; reload: () => void }) {
  const { t, v } = useI18n();
  const nav = useNavigate();
  const [title, setTitle] = useState(r.title);
  const [type, setType] = useState(r.resource_type);
  const [access, setAccess] = useState(r.access_status);
  const [pillars, setPillars] = useState<string[]>(r.pillars.map((p) => p.pillar));
  const [labels, setLabels] = useState((r.labels || []).join(", "));
  const [notes, setNotes] = useState(String((r.extra || {}).user_notes || ""));
  const userRel = (r.extra || {}).relevance_user;
  const [relevance, setRelevance] = useState(userRel === undefined || userRel === null ? "" : String(userRel));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const types = Array.from(new Set([...RESOURCE_TYPES, r.resource_type]));

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.patch(`/api/resources/${r.id}`, {
        title, resource_type: type, access_status: access, pillars, notes, relevance: relevance === "" ? null : Number(relevance),
        labels: labels.split(/[,،]/).map((x) => x.trim()).filter(Boolean),
      });
      setMsg({ ok: true, text: t("ok_done") });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!armed) { setArmed(true); return; }
    setBusy(true);
    try {
      await api.del(`/api/resources/${r.id}`);
      nav("/library");
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
      setBusy(false);
    }
  };

  return (
    <Card title={t("edit_item")}>
      <div className="form-grid">
        <label>{t("title")}<input type="text" dir="auto" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <label>{t("resource_type")}
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {types.map((x) => <option key={x} value={x}>{v(x)}</option>)}
          </select>
        </label>
        <label>{t("access_status")}
          <select value={access} onChange={(e) => setAccess(e.target.value)}>
            {ACCESS_VALUES.map((x) => <option key={x} value={x}>{v(x)}</option>)}
          </select>
        </label>
        <fieldset className="check-row">
          <legend>{t("pillar")}</legend>
          {PILLAR_KEYS.map((p) => (
            <label key={p} className="check">
              <input type="checkbox" checked={pillars.includes(p)}
                onChange={(e) => setPillars((cur) => e.target.checked ? [...cur, p] : cur.filter((x) => x !== p))} />
              {t(`pillar_${p}` as never)}
            </label>
          ))}
        </fieldset>
        <label>{t("labels")}
          <input type="text" dir="auto" value={labels} placeholder={t("labels_hint")} onChange={(e) => setLabels(e.target.value)} />
        </label>
        <label title={t("relevance_help")}>{t("relevance")} (0-100)
          <input type="number" min={0} max={100} value={relevance} placeholder={r.relevance === null || r.relevance === undefined ? "" : String(r.relevance)}
            onChange={(e) => setRelevance(e.target.value)} />
        </label>
        <label>{t("notes")}<textarea dir="auto" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      </div>
      <div className="toolbar spaced">
        <button type="button" className="btn btn-primary" disabled={busy} onClick={save}>{t("save")}</button>
        <button type="button" className="btn btn-danger" disabled={busy} onClick={remove}>
          {armed ? t("confirm_delete_n") : t("delete_item")}
        </button>
        {msg ? <span className={msg.ok ? "small" : "small text-error"} role="status">{msg.text}</span> : null}
      </div>
      <p className="small muted">{t("delete_explain")}</p>
    </Card>
  );
}
