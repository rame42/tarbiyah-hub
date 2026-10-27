import { FormEvent, useState } from "react";
import { api } from "../api";
import { Async, Card, ErrorBox, PillarBadge, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";

interface Term { id: number; concept: string; terms_en: string[]; terms_ar: string[]; transliterations: string[]; pillar: string | null; origin: string }

const split = (s: string) => s.split(/[,،]/).map((x) => x.trim()).filter(Boolean);

export default function Glossary() {
  const { t, v } = useI18n();
  const state = useAsync(() => api.get<Term[]>("/api/glossary"), []);
  const [filter, setFilter] = useState("");
  const [f, setF] = useState({ concept: "", en: "", ar: "", tr: "", pillar: "" });
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const edit = (g: Term) => {
    setF({ concept: g.concept, en: g.terms_en.join(", "), ar: g.terms_ar.join("، "), tr: g.transliterations.join(", "), pillar: g.pillar || "" });
    document.getElementById("glossary-form")?.scrollIntoView({ behavior: "smooth" });
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setOk(null);
    try {
      await api.post("/api/glossary", { concept: f.concept.trim(), terms_en: split(f.en), terms_ar: split(f.ar), transliterations: split(f.tr), pillar: f.pillar || null });
      setOk(f.concept.trim());
      setF({ concept: "", en: "", ar: "", tr: "", pillar: "" });
      state.reload();
    } catch (x) {
      setErr((x as Error).message);
    }
  };

  const fl = filter.trim().toLowerCase();
  return (
    <div className="page">
      <div className="page-head"><h1>{t("glossary_title")}</h1></div>
      <Card>
        <input type="search" dir="auto" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("filter_text")} aria-label={t("filter_text")} className="search-input" />
      </Card>
      <Async state={state}>
        {(rows) => {
          const list = fl ? rows.filter((g) => [g.concept, ...g.terms_en, ...g.terms_ar, ...g.transliterations].some((x) => x.toLowerCase().includes(fl))) : rows;
          return (
            <Card title={`${list.length}`}>
              <TableWrap>
                <table>
                  <thead><tr><th>{t("concept")}</th><th>{t("terms_en")}</th><th>{t("terms_ar")}</th><th>{t("transliterations")}</th><th>{t("pillar")}</th><th>{t("origin")}</th><th></th></tr></thead>
                  <tbody>
                    {list.map((g) => (
                      <tr key={g.id}>
                        <td><code>{g.concept}</code></td>
                        <td dir="ltr" className="wide-cell">{g.terms_en.join(", ")}</td>
                        <td dir="rtl" lang="ar" className="wide-cell content-text">{g.terms_ar.join("، ")}</td>
                        <td dir="ltr">{g.transliterations.join(", ")}</td>
                        <td>{g.pillar ? <PillarBadge pillar={g.pillar} /> : "—"}</td>
                        <td>{v(g.origin)}</td>
                        <td><button type="button" className="btn btn-small" onClick={() => edit(g)}>{t("edit")}</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </Card>
          );
        }}
      </Async>
      <Card title={t("add_term")}>
        <form id="glossary-form" className="form-stack" onSubmit={submit}>
          <div className="form-grid">
            <label className="field"><span>{t("concept")} *</span><input dir="ltr" required value={f.concept} onChange={(e) => setF({ ...f, concept: e.target.value })} /></label>
            <label className="field">
              <span>{t("pillar")}</span>
              <select value={f.pillar} onChange={(e) => setF({ ...f, pillar: e.target.value })}>
                <option value="">—</option>
                {["children", "parents", "murabbi"].map((p) => <option key={p} value={p}>{t(`pillar_${p}` as "pillar_children")}</option>)}
              </select>
            </label>
          </div>
          <label className="field"><span>{t("terms_en")} ({t("comma_sep")})</span><input dir="ltr" value={f.en} onChange={(e) => setF({ ...f, en: e.target.value })} /></label>
          <label className="field"><span>{t("terms_ar")} ({t("comma_sep")})</span><input dir="rtl" lang="ar" value={f.ar} onChange={(e) => setF({ ...f, ar: e.target.value })} /></label>
          <label className="field"><span>{t("transliterations")} ({t("comma_sep")})</span><input dir="ltr" value={f.tr} onChange={(e) => setF({ ...f, tr: e.target.value })} /></label>
          <ErrorBox error={err} />
          {ok ? <div className="alert alert-ok" role="status">{t("saved")} <code>{ok}</code></div> : null}
          <div><button type="submit" className="btn btn-primary" disabled={!f.concept.trim()}>{t("save")}</button></div>
        </form>
      </Card>
    </div>
  );
}
