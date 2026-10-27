import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, Status } from "../api";
import { Async, Badge, Card, ErrorBox, fmtDate, Pre, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";

interface Kind { kind: string; label: string; needs_ai: boolean }
interface OutputRow { id: number; kind: string; kind_label: string; title: string; lang: string; status: string; error: string | null; params: Record<string, unknown>; generated_by: string; resources: number; created_at: string }
interface OutputFull { id: number; kind: string; title: string; status: string; error: string | null; content: string | null; params: Record<string, unknown>; resource_ids: number[] | null; generated_by: string; formats: string[] }

export default function Outputs() {
  const { id } = useParams();
  const { t, v } = useI18n();
  const kinds = useAsync(() => api.get<Kind[]>("/api/output-kinds"), []);
  const list = useAsync(() => api.get<OutputRow[]>("/api/outputs"), [], 15000);
  const status = useAsync(() => api.get<Status>("/api/status"), []);
  const kindMap = Object.fromEntries((kinds.data || []).map((k) => [k.kind, k]));

  return (
    <div className="page">
      <div className="page-head"><h1>{t("outputs_title")}</h1></div>
      {id ? <OutputView id={id} /> : null}
      <CreateOutput kinds={kinds.data || []} aiReady={!!status.data?.ai.configured} onCreated={list.reload} />
      <Card title={t("outputs_title")} actions={<button type="button" className="btn btn-small" onClick={list.reload}>{t("refresh")}</button>}>
        <ErrorBox error={kinds.error} />
        <Async state={list}>
          {(rows) => rows.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
            <TableWrap>
              <table>
                <thead><tr><th>#</th><th>{t("title")}</th><th>{t("output_kind")}</th><th>{t("language")}</th><th>{t("status")}</th><th>{t("resources_n")}</th><th>{t("created")}</th></tr></thead>
                <tbody>
                  {rows.map((o) => (
                    <tr key={o.id} className={String(o.id) === id ? "row-active" : ""}>
                      <td>{o.id}</td>
                      <td><Link to={`/outputs/${o.id}`} dir="auto">{o.title}</Link></td>
                      <td>{o.kind_label} {kindMap[o.kind]?.needs_ai ? <Badge tone="info">{t("needs_ai")}</Badge> : null}</td>
                      <td>{o.lang}</td>
                      <td><Badge value={o.status} />{o.error ? <div className="err-text small" dir="auto">{o.error}</div> : null}</td>
                      <td>{o.resources}</td>
                      <td className="nowrap">{fmtDate(o.created_at)} <span className="muted small">{v(o.generated_by)}</span></td>
                    </tr>
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

function OutputView({ id }: { id: string }) {
  const { t } = useI18n();
  const state = useAsync(() => api.get<OutputFull>(`/api/outputs/${id}`), [id], 15000);
  return (
    <Async state={state}>
      {(o) => (
        <Card title={<span dir="auto">#{o.id} {o.title}</span>} actions={<Badge value={o.status} />}>
          <ErrorBox error={o.error} />
          {o.formats.length ? (
            <p className="toolbar">
              <strong>{t("downloads")}:</strong>
              {o.formats.map((f) => (
                <a key={f} className="btn btn-small" href={`/api/outputs/${o.id}/download?fmt=${encodeURIComponent(f)}`} target="_blank" rel="noopener noreferrer" download>
                  {f.toUpperCase()}
                </a>
              ))}
            </p>
          ) : null}
          {o.params && Object.keys(o.params).length ? <p className="small muted"><code>{JSON.stringify(o.params)}</code></p> : null}
          {o.content ? <Pre>{o.content}</Pre> : <p className="muted">{t("no_content")}</p>}
        </Card>
      )}
    </Async>
  );
}

function CreateOutput({ kinds, aiReady, onCreated }: { kinds: Kind[]; aiReady: boolean; onCreated: () => void }) {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const [kind, setKind] = useState("");
  const [title, setTitle] = useState("");
  const [olang, setOlang] = useState<string>(lang);
  const [pillar, setPillar] = useState("");
  const [query, setQuery] = useState("");
  const [qid, setQid] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const k = kinds.find((x) => x.kind === (kind || kinds[0]?.kind));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!k) return;
    setErr(null);
    setBusy(true);
    const params: Record<string, unknown> = {};
    if (pillar) params.pillar = pillar;
    if (query.trim()) params.query = query.trim();
    if (qid.trim()) params.question_id = Number(qid);
    try {
      const r = await api.post<{ id: number; job_id: number }>("/api/outputs", { kind: k.kind, title: title.trim() || null, lang: olang, params });
      onCreated();
      nav(`/outputs/${r.id}`);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={t("create_output")}>
      <form className="form-stack" onSubmit={submit}>
        <div className="form-grid">
          <label className="field">
            <span>{t("output_kind")}</span>
            <select value={k?.kind || ""} onChange={(e) => setKind(e.target.value)}>
              {kinds.map((x) => <option key={x.kind} value={x.kind}>{x.label}{x.needs_ai ? ` (${t("needs_ai")})` : ""}</option>)}
            </select>
          </label>
          <label className="field"><span>{t("title")}</span><input dir="auto" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={k?.label} /></label>
          <label className="field">
            <span>{t("output_language")}</span>
            <select value={olang} onChange={(e) => setOlang(e.target.value)}>
              <option value="en">{t("lang_en")}</option>
              <option value="ar">{t("lang_ar")}</option>
            </select>
          </label>
          <label className="field">
            <span>{t("pillar")}</span>
            <select value={pillar} onChange={(e) => setPillar(e.target.value)}>
              <option value="">{t("all")}</option>
              {["children", "parents", "murabbi"].map((p) => <option key={p} value={p}>{t(`pillar_${p}` as "pillar_children")}</option>)}
            </select>
          </label>
          <label className="field"><span>{t("query_optional")}</span><input dir="auto" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
          <label className="field"><span>{t("question_id_optional")}</span><input type="number" min={1} value={qid} onChange={(e) => setQid(e.target.value)} /></label>
        </div>
        {k?.needs_ai && !aiReady ? <div className="alert alert-warn">{t("ai_not_configured_warn")}</div> : null}
        <ErrorBox error={err} />
        <div><button type="submit" className="btn btn-primary" disabled={busy || !k}>{t("create")}</button></div>
      </form>
    </Card>
  );
}
