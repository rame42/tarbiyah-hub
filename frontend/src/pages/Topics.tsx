import { useState } from "react";
import { api } from "../api";
import { Async, Card, fmtDate, fmtNum, useAsync } from "../components";
import { useI18n } from "../i18n";

interface Topic {
  id: number; pillar: string; name_en: string; name_ar: string; phrases_en: string[]; phrases_ar: string[];
  enabled: boolean; origin: string; last_swept_at: string | null;
  stats: { searches: number; returned: number; kept: number; new: number; yield_pct: number | null; weak: boolean };
}
const PILLARS = ["children", "parents", "murabbi"];
const lines = (s: string) => s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);

export default function Topics() {
  const { t } = useI18n();
  const [pillar, setPillar] = useState("children");
  const state = useAsync(() => api.get<{ topics: Topic[] }>("/api/topics"), []);
  return (
    <div className="page">
      <div className="page-head"><h1>{t("nav_topics")}</h1></div>
      <p className="muted">{t("topics_intro")}</p>
      <div className="toolbar spaced">
        {PILLARS.map((p) => (
          <button key={p} type="button" className={`btn ${pillar === p ? "btn-primary" : ""}`} onClick={() => setPillar(p)}>
            {t(`pillar_${p}` as never)}{state.data ? ` (${state.data.topics.filter((x) => x.pillar === p).length})` : ""}
          </button>
        ))}
      </div>
      <Async state={state}>
        {(d) => (
          <>
            <AddTopic pillar={pillar} reload={state.reload} />
            {d.topics.filter((x) => x.pillar === pillar).map((x) => <TopicRow key={x.id} tp={x} reload={state.reload} />)}
          </>
        )}
      </Async>
    </div>
  );
}

function TopicRow({ tp, reload }: { tp: Topic; reload: () => void }) {
  const { t } = useI18n();
  const [en, setEn] = useState(tp.phrases_en.join("\n"));
  const [ar, setAr] = useState(tp.phrases_ar.join("\n"));
  const [nameEn, setNameEn] = useState(tp.name_en);
  const [nameAr, setNameAr] = useState(tp.name_ar);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const st = tp.stats;
  const save = async (extra: Record<string, unknown> = {}) => {
    setMsg(null);
    try {
      await api.patch(`/api/topics/${tp.id}`, { name_en: nameEn, name_ar: nameAr, phrases_en: lines(en), phrases_ar: lines(ar), ...extra });
      setMsg({ ok: true, text: t("keys_saved") });
      reload();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  const remove = async () => {
    if (!window.confirm(t("topic_delete_confirm"))) return;
    await api.del(`/api/topics/${tp.id}`);
    reload();
  };
  return (
    <Card title={<span dir="auto">{tp.name_en} · {tp.name_ar}</span>}
      actions={<span className="res-meta">
        {!tp.enabled ? <span className="badge badge-muted">{t("off")}</span> : null}
        {st.weak ? <span className="badge badge-bad" title={t("topic_weak_help")}>{t("topic_weak")}</span> : null}
        {st.yield_pct !== null ? <span className={`badge badge-${st.yield_pct >= 40 ? "good" : st.yield_pct >= 15 ? "warn" : "bad"}`}>{t("sp_yield")} {st.yield_pct}%</span> : null}
        <span className="small muted">{fmtNum(st.searches)} {t("sp_searches").toLowerCase()} · {fmtNum(st.kept)} {t("topic_kept")}{tp.last_swept_at ? ` · ${fmtDate(tp.last_swept_at)}` : ""}</span>
      </span>}>
      <div className="form-grid">
        <label>{t("topic_name_en")}<input value={nameEn} onChange={(e) => setNameEn(e.target.value)} /></label>
        <label>{t("topic_name_ar")}<input dir="rtl" value={nameAr} onChange={(e) => setNameAr(e.target.value)} /></label>
        <label>{t("topic_phrases_en")}<textarea rows={3} value={en} onChange={(e) => setEn(e.target.value)} /></label>
        <label>{t("topic_phrases_ar")}<textarea dir="rtl" rows={3} value={ar} onChange={(e) => setAr(e.target.value)} /></label>
      </div>
      <div className="toolbar spaced">
        <button type="button" className="btn btn-primary btn-small" onClick={() => save()}>{t("save")}</button>
        <button type="button" className="btn btn-small" onClick={() => save({ enabled: !tp.enabled })}>{tp.enabled ? t("turn_off") : t("turn_on")}</button>
        <button type="button" className="btn btn-small btn-ghost" onClick={remove}>{t("delete_item")}</button>
        {msg ? <span className={`small ${msg.ok ? "" : "text-error"}`} role="status">{msg.text}</span> : null}
      </div>
    </Card>
  );
}

function AddTopic({ pillar, reload }: { pillar: string; reload: () => void }) {
  const { t } = useI18n();
  const [en, setEn] = useState("");
  const [ar, setAr] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const add = async () => {
    setErr(null);
    try {
      await api.post("/api/topics", { pillar, phrases_en: lines(en), phrases_ar: lines(ar), name_en: lines(en)[0] || "", name_ar: lines(ar)[0] || "" });
      setEn(""); setAr("");
      reload();
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Card title={t("topic_add")}>
      <details>
        <summary className="small">{t("topic_add_open")}</summary>
        <div className="form-grid">
          <label>{t("topic_phrases_en")}<textarea rows={2} value={en} onChange={(e) => setEn(e.target.value)} placeholder="teaching wudu to children" /></label>
          <label>{t("topic_phrases_ar")}<textarea dir="rtl" rows={2} value={ar} onChange={(e) => setAr(e.target.value)} placeholder="تعليم الأطفال الوضوء" /></label>
        </div>
        <div className="toolbar spaced">
          <button type="button" className="btn btn-primary btn-small" disabled={!lines(en).length && !lines(ar).length} onClick={add}>{t("add")}</button>
          {err ? <span className="small text-error">{err}</span> : null}
        </div>
      </details>
    </Card>
  );
}
