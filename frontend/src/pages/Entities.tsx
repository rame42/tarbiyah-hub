import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, qs } from "../api";
import { Async, Badge, Card, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";

interface EntityRow { id: number; type: string; name: string; name_ar: string | null; name_en: string | null; origin: string | null; resources: number }

const TYPES: [string, "entity_person" | "entity_organization" | "entity_program" | "entity_concept" | "entity_channel"][] = [
  ["person", "entity_person"], ["organization", "entity_organization"], ["program", "entity_program"], ["concept", "entity_concept"], ["channel", "entity_channel"],
];

export default function Entities() {
  const { t, v } = useI18n();
  const [sp, setSp] = useSearchParams();
  const type = sp.get("type") || "";
  const q = sp.get("q") || "";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);
  const state = useAsync(() => api.get<EntityRow[]>(`/api/entities${qs({ type, q, limit: 300 })}`), [type, q]);
  const set = (k: string, val: string) => {
    const n = new URLSearchParams(sp);
    if (val) n.set(k, val);
    else n.delete(k);
    setSp(n);
  };
  return (
    <div className="page">
      <div className="page-head"><h1>{t("entities_title")}</h1></div>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={!type} className={`tab ${!type ? "active" : ""}`} onClick={() => set("type", "")}>{t("all")}</button>
        {TYPES.map(([k, label]) => (
          <button type="button" role="tab" aria-selected={type === k} key={k} className={`tab ${type === k ? "active" : ""}`} onClick={() => set("type", k)}>{t(label)}</button>
        ))}
      </div>
      <Card>
        <form className="filter-row" onSubmit={(e) => { e.preventDefault(); set("q", draft.trim()); }}>
          <input type="search" dir="auto" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("filter_text")} aria-label={t("search")} />
          <button type="submit" className="btn">{t("search")}</button>
        </form>
      </Card>
      <Async state={state}>
        {(rows) => (
          <Card>
            {rows.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
              <TableWrap>
                <table>
                  <thead><tr><th>{t("name")}</th><th>{t("type")}</th><th>{t("name_ar")}</th><th>{t("name_en")}</th><th>{t("origin")}</th><th>{t("resources_n")}</th></tr></thead>
                  <tbody>
                    {rows.map((e) => (
                      <tr key={e.id}>
                        <td><Link to={`/entities/${e.id}`} dir="auto">{e.name}</Link></td>
                        <td><Badge value={e.type} tone="neutral" /></td>
                        <td dir="auto">{e.name_ar || "—"}</td>
                        <td dir="auto">{e.name_en || "—"}</td>
                        <td>{v(e.origin)}</td>
                        <td>{e.resources}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
          </Card>
        )}
      </Async>
    </div>
  );
}
