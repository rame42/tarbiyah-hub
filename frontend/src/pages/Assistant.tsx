import { FormEvent, ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, BoolBadge, Card, ErrorBox, fmtTimestamp, videoUrlAt, WatchButton } from "../components";
import { useI18n } from "../i18n";

interface EvidenceItem {
  passage_id: number;
  resource_id: number;
  title: string;
  authors: string | null;
  year: number | null;
  page: number | null;
  timestamp: number | null;
  url: string | null;
  lang: string | null;
  text: string;
  access_status: string;
}
interface AssistantAnswer {
  question: string;
  mode: "ai" | "passages_only" | "no_evidence";
  answer: string;
  sufficiency?: string;
  citations: { passage_id: number; quote: string; verified: boolean; known_passage: boolean }[];
  evidence_vs_interpretation?: string;
  note?: string;
  evidence: EvidenceItem[];
  expanded_terms?: string[];
  expansions?: Record<string, string[]>;
}

// ---------------------------------------------------------------- tiny markdown-ish renderer

function inline(text: string, onCite: (id: number) => void, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\[P(\d+)\]|\*\*(.+?)\*\*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) {
      const id = Number(m[1]);
      out.push(
        <button type="button" key={`${keyBase}-${i++}`} className="cite" onClick={() => onCite(id)} title={`P${id}`}>
          P{id}
        </button>,
      );
    } else {
      out.push(<strong key={`${keyBase}-${i++}`}>{m[2]}</strong>);
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function RichText({ text, onCite }: { text: string; onCite: (id: number) => void }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="rich" dir="auto">
      {blocks.map((b, bi) => {
        const lines = b.split("\n");
        if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
          const ordered = /^\s*\d/.test(lines[0]);
          const items = lines.map((l, li) => <li key={li}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""), onCite, `${bi}-${li}`)}</li>);
          return ordered ? <ol key={bi} dir="auto">{items}</ol> : <ul key={bi} dir="auto">{items}</ul>;
        }
        const h = /^(#{1,4})\s+(.*)$/.exec(lines[0]);
        if (h && lines.length === 1) {
          return <h3 key={bi} dir="auto">{inline(h[2], onCite, `${bi}`)}</h3>;
        }
        return (
          <p key={bi} dir="auto">
            {lines.map((l, li) => (
              <span key={li}>
                {li > 0 ? <br /> : null}
                {inline(l.replace(/^#{1,4}\s+/, ""), onCite, `${bi}-${li}`)}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}

export default function Assistant() {
  const { t, v, lang } = useI18n();
  const [question, setQuestion] = useState("");
  const [answerLang, setAnswerLang] = useState<string>(lang);
  const [pillar, setPillar] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<AssistantAnswer | null>(null);
  const [highlight, setHighlight] = useState<number | null>(null);

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      setRes(await api.post<AssistantAnswer>("/api/assistant", { question: question.trim(), lang: answerLang, pillar: pillar || null }));
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cite = (id: number) => {
    setHighlight(id);
    const el = document.getElementById(`ev-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.focus({ preventScroll: true });
    }
  };

  const modeKey = res ? (`mode_${res.mode}` as "mode_ai") : null;
  const terms = res ? Array.from(new Set([...(res.expanded_terms || []), ...Object.values(res.expansions || {}).flat()])) : [];

  return (
    <div className="page">
      <div className="page-head"><h1>{t("assistant_title")}</h1></div>
      <Card>
        <form onSubmit={ask} className="form-stack">
          <textarea dir="auto" rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={t("ask_placeholder")} aria-label={t("question")} />
          <div className="toolbar">
            <label className="inline-field">
              <span>{t("answer_language")}</span>
              <select value={answerLang} onChange={(e) => setAnswerLang(e.target.value)}>
                <option value="en">{t("lang_en")}</option>
                <option value="ar">{t("lang_ar")}</option>
              </select>
            </label>
            <label className="inline-field">
              <span>{t("pillar")}</span>
              <select value={pillar} onChange={(e) => setPillar(e.target.value)}>
                <option value="">{t("all")}</option>
                {["children", "parents", "murabbi"].map((p) => <option key={p} value={p}>{t(`pillar_${p}` as "pillar_children")}</option>)}
              </select>
            </label>
            <button type="submit" className="btn btn-primary" disabled={busy || !question.trim()}>{busy ? "…" : ""}{t("ask")}</button>
          </div>
        </form>
        {busy ? <div className="alert alert-info" role="status"><span className="spinner" aria-hidden="true" /> {t("thinking")}</div> : null}
        <ErrorBox error={err} />
      </Card>

      {res ? (
        <>
          <Card title={t("answer")} actions={<Badge tone={res.mode === "ai" ? "info" : res.mode === "passages_only" ? "warn" : "muted"}>{t("mode")}: {v(res.mode === "ai" ? "ai_mode" : res.mode)}</Badge>}>
            {modeKey ? <p className="muted small">{t(modeKey)}</p> : null}
            <RichText text={res.answer || ""} onCite={cite} />
            {res.sufficiency ? <p className="small">{t("sufficiency")}: <Badge value={res.sufficiency} /></p> : null}
            {res.evidence_vs_interpretation ? (
              <div className="callout">
                <strong>{t("evidence_vs_interpretation")}</strong>
                <RichText text={res.evidence_vs_interpretation} onCite={cite} />
              </div>
            ) : null}
            {res.note ? <p className="alert alert-warn small" dir="auto">{t("note")}: {res.note}</p> : null}
            {terms.length ? (
              <p className="small">{t("expanded_terms")}: {terms.map((x) => <span key={x} className="chip" dir="auto">{x}</span>)}</p>
            ) : null}
          </Card>

          {res.citations.length ? (
            <Card title={`${t("citations")} (${res.citations.length})`}>
              <ul className="plain-list">
                {res.citations.map((c, i) => (
                  <li key={i}>
                    <button type="button" className="cite" onClick={() => cite(c.passage_id)}>P{c.passage_id}</button>{" "}
                    <BoolBadge value={c.verified} yes={t("verified")} no={t("unverified")} />{" "}
                    {!c.known_passage ? <Badge tone="bad">{t("unknown_passage")}</Badge> : null}
                    <blockquote dir="auto" className="quote">{c.quote}</blockquote>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          <Card title={`${t("evidence_passages")} (${res.evidence.length})`}>
            {res.evidence.length === 0 ? <p className="muted">{t("none")}</p> : res.evidence.map((e) => (
              <div key={e.passage_id} id={`ev-${e.passage_id}`} tabIndex={-1} className={`passage ${highlight === e.passage_id ? "passage-hl" : ""}`}>
                <div className="passage-meta">
                  <span className="badge badge-info">P{e.passage_id}</span>
                  <Link to={`/resources/${e.resource_id}`} dir="auto"><strong>{e.title}</strong></Link>
                  {e.authors ? <span dir="auto" className="small">{e.authors}</span> : null}
                  {e.year ? <span className="small">{e.year}</span> : null}
                  {e.page !== null ? <span className="small">{t("page_short")} {e.page}</span> : null}
                  {e.timestamp !== null ? (e.url ? (
                    <a className="small" href={videoUrlAt(e.url, e.timestamp)} target="_blank" rel="noopener noreferrer">⏱ {fmtTimestamp(e.timestamp)} ▶</a>
                  ) : <span className="small">⏱ {fmtTimestamp(e.timestamp)}</span>) : null}
                  <Badge value={e.access_status} />
                  {e.url && /youtube\.com|youtu\.be|tiktok\.com/i.test(e.url) ? <WatchButton url={e.url} small /> :
                    e.url ? <a href={e.url} target="_blank" rel="noopener noreferrer" className="small">{t("open_link")} ↗</a> : null}
                </div>
                <p dir="auto" className="pre-line content-text">{e.text}</p>
              </div>
            ))}
          </Card>
        </>
      ) : null}
    </div>
  );
}
