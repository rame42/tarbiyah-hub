import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ResourceBrief } from "../api";
import { Async, Card, fmtNum, PillarBadges, RelevanceBadge, useAsync } from "../components";
import { useI18n } from "../i18n";
import { RESOURCE_TYPES } from "./Library";

interface FileItem extends ResourceBrief { file_name: string; file_size: number | null; ext: string; exists: boolean }
interface FilesResponse { total: number; total_size: number; page: number; page_size: number; files_folder: string; items: FileItem[] }

const PAGE = 50;
const mb = (n: number | null | undefined) => (n ? (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`) : "—");

export default function Files() {
  const { t, v } = useI18n();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [pillar, setPillar] = useState("");
  const [view, setView] = useState("active");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = JSON.stringify([q, type, pillar, view, page]);
  const state = useAsync(() => api.get<FilesResponse>(`/api/files?${new URLSearchParams({ q, type, pillar, view, page: String(page), page_size: String(PAGE) })}`), [key]);
  useEffect(() => setSelected([]), [key]);

  const downloadZip = async () => {
    setErr(null); setBusy(true);
    try {
      const res = await fetch("/api/files/zip", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: selected }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "tarbiyah-files.zip";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 30000);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-head"><h1>{t("nav_files")}</h1></div>
      <p className="muted">{t("files_intro")}</p>
      <Card>
        <div className="form-grid">
          <label className="field"><span>{t("search")}</span><input type="search" dir="auto" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></label>
          <label className="field"><span>{t("resource_type")}</span>
            <select value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
              <option value="">{t("any")}</option>{RESOURCE_TYPES.map((x) => <option key={x} value={x}>{v(x)}</option>)}
            </select></label>
          <label className="field"><span>{t("pillar")}</span>
            <select value={pillar} onChange={(e) => { setPillar(e.target.value); setPage(1); }}>
              <option value="">{t("any")}</option>
              {["children", "parents", "murabbi"].map((p) => <option key={p} value={p}>{t(`pillar_${p}` as never)}</option>)}
              <option value="none">{t("unclassified_np")}</option>
            </select></label>
          <label className="field"><span>{t("lib_view")}</span>
            <select value={view} onChange={(e) => { setView(e.target.value); setPage(1); }}>
              <option value="active">{t("view_active")}</option><option value="archived">{t("view_archived")}</option>
            </select></label>
        </div>
      </Card>
      <Async state={state}>
        {(d) => (
          <Card>
            <p className="small">{fmtNum(d.total)} {t("files_n")} · {mb(d.total_size)} · {t("files_folder")}: <code dir="ltr" className="break">{d.files_folder}</code></p>
            <div className="bulk-bar">
              <label className="check">
                <input type="checkbox" checked={d.items.length > 0 && d.items.every((x) => selected.includes(x.id))}
                  onChange={(e) => setSelected(e.target.checked ? d.items.map((x) => x.id) : [])} />{t("select_all_page")}
              </label>
              <strong>{selected.length} {t("selected_n")}</strong>
              <button type="button" className="btn btn-primary" disabled={!selected.length || busy} onClick={downloadZip}>{busy ? "…" : t("download_zip")}</button>
              {err ? <span className="small text-error" role="status">{err}</span> : null}
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th /><th>{t("title")}</th><th>{t("file_type")}</th><th>{t("size")}</th><th /></tr></thead>
                <tbody>
                  {d.items.map((f) => (
                    <tr key={f.id}>
                      <td><input type="checkbox" aria-label={`select ${f.id}`} checked={selected.includes(f.id)}
                        onChange={() => setSelected((c) => (c.includes(f.id) ? c.filter((x) => x !== f.id) : [...c, f.id]))} /></td>
                      <td dir="auto"><Link to={`/resources/${f.id}`}>{f.title}</Link>
                        <div className="res-meta"><PillarBadges pillars={f.pillars} /><RelevanceBadge value={f.relevance} /></div></td>
                      <td><span className="badge badge-neutral">{f.ext || "?"}</span></td>
                      <td>{mb(f.file_size)}</td>
                      <td className="nowrap">
                        {f.exists ? <>
                          <a className="btn btn-small btn-primary" href={`/api/resources/${f.id}/file?download=true`}>{t("download")}</a>{" "}
                          <a className="btn btn-small" href={`/api/resources/${f.id}/file`} target="_blank" rel="noopener noreferrer">{t("open_file")}</a>
                        </> : <span className="small muted">{t("file_missing")}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <button type="button" className="btn btn-small" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("prev")}</button>
              <span className="small">{page} / {Math.max(1, Math.ceil(d.total / PAGE))}</span>
              <button type="button" className="btn btn-small" disabled={page * PAGE >= d.total} onClick={() => setPage(page + 1)}>{t("next")}</button>
            </div>
          </Card>
        )}
      </Async>
    </div>
  );
}
