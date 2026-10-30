import { useState } from "react";
import { api, ResourceBrief } from "../api";
import { ActionButton, Async, Card, fmtNum, ResourceItem, useAsync } from "../components";
import { useI18n } from "../i18n";

interface KidsItem extends ResourceBrief { subjects: string[]; description: string | null }
interface KidsResponse {
  total: number; page: number; page_size: number; scanning: boolean;
  counts: { all: number; quran: number; seerah: number; hadith: number; files: number };
  types: Record<string, number>; items: KidsItem[];
}

const PAGE = 30;
const SUBJECTS = ["all", "quran", "seerah", "hadith"] as const;

export default function KidsCorner() {
  const { t, v } = useI18n();
  const [subject, setSubject] = useState<string>("all");
  const [type, setType] = useState("");
  const [filesOnly, setFilesOnly] = useState(false);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const key = JSON.stringify([subject, type, filesOnly, q, page]);
  const state = useAsync(() => api.get<KidsResponse>(`/api/kids-corner?${new URLSearchParams({
    subject, type, q, files_only: String(filesOnly), page: String(page), page_size: String(PAGE) })}`), [key]);
  const reset = () => setPage(1);

  return (
    <div className="page">
      <div className="page-head"><h1>{t("nav_kids")}</h1></div>
      <p className="muted">{t("kids_intro")}</p>
      <Card>
        <div className="toolbar spaced">
          {SUBJECTS.map((sname) => (
            <button key={sname} type="button" className={`btn ${subject === sname ? "btn-primary" : ""}`}
              onClick={() => { setSubject(sname); reset(); }}>
              {t(`kids_${sname}` as never)}{state.data ? ` (${fmtNum(state.data.counts[sname])})` : ""}
            </button>
          ))}
        </div>
        <div className="toolbar spaced">
          <select aria-label={t("resource_type")} value={type} onChange={(e) => { setType(e.target.value); reset(); }}>
            <option value="">{t("kids_all_types")}</option>
            {Object.entries(state.data?.types || {}).map(([k, n]) => <option key={k} value={k}>{v(k)} ({n})</option>)}
          </select>
          <label className="check">
            <input type="checkbox" checked={filesOnly} onChange={(e) => { setFilesOnly(e.target.checked); reset(); }} />
            {t("kids_files_only")}{state.data ? ` (${fmtNum(state.data.counts.files)})` : ""}
          </label>
          <input type="search" dir="auto" placeholder={t("search")} value={q} onChange={(e) => { setQ(e.target.value); reset(); }} />
          <ActionButton className="btn" onRun={async () => { const r = await api.post("/api/kids-corner/find"); state.reload(); return r; }}>
            {t("kids_find_more")}
          </ActionButton>
        </div>
        {state.data?.scanning ? <p className="small" role="status">{t("kids_scanning")}</p> : null}
        <Async state={state}>
          {(d) => (
            <>
              {!d.items.length ? <p className="muted">{t("kids_empty")}</p> : null}
              <div className="res-list">
                {d.items.map((r) => (
                  <div key={r.id} className="res-result">
                    <ResourceItem r={r} />
                    <div className="res-meta">
                      {r.subjects.map((sname) => <span key={sname} className="badge badge-info">{t(`kids_${sname}` as never)}</span>)}
                      {r.has_file ? <>
                        <a className="btn btn-small btn-primary" href={`/api/resources/${r.id}/file?download=true`}>{t("download")}</a>
                        <a className="btn btn-small" href={`/api/resources/${r.id}/file`} target="_blank" rel="noopener noreferrer">{t("open_file")}</a>
                      </> : null}
                    </div>
                    {r.description ? <p className="snippet-desc" dir="auto">{r.description}</p> : null}
                  </div>
                ))}
              </div>
              <div className="pager">
                <button type="button" className="btn btn-small" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("prev")}</button>
                <span className="small">{page} / {Math.max(1, Math.ceil(d.total / PAGE))}</span>
                <button type="button" className="btn btn-small" disabled={page * PAGE >= d.total} onClick={() => setPage(page + 1)}>{t("next")}</button>
              </div>
            </>
          )}
        </Async>
      </Card>
    </div>
  );
}
