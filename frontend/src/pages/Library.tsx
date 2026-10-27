import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, getMeta, Meta, qs, ResourceBrief } from "../api";
import { ActionButton, Async, Card, ErrorBox, fmtTimestamp, Pager, ResourceItem, useAsync, videoUrlAt } from "../components";
import { useI18n } from "../i18n";

interface SearchResult {
  resource: ResourceBrief;
  score?: number;
  passage: { chunk_id: number; page: number | null; text: string; lang: string | null; timestamp?: number | null } | null;
  description_snippet: string | null;
}
interface SearchResponse {
  query: string;
  total: number;
  page: number;
  page_size: number;
  results: SearchResult[];
  expansions?: Record<string, string[]>;
}

export const ACCESS_VALUES = ["open_access", "open_license", "public_domain", "user_provided", "paid", "lending_only", "restricted", "unknown"];
export const PROCESSING_VALUES = ["pending", "metadata_only", "downloaded", "text_collected", "extracted", "needs_ocr", "low_quality", "failed", "skipped_limit"];
export const RESOURCE_TYPES = ["book", "article", "paper", "thesis", "report", "document", "video", "podcast_episode", "social_post", "other"];
const FILTER_KEYS = ["language", "pillar", "type", "access", "source", "topic", "date_from", "date_to", "status"] as const;
const PAGE_SIZE = 20;

export default function Library() {
  const { t, v, lang } = useI18n();
  const [sp, setSp] = useSearchParams();
  const q = sp.get("q") || "";
  const page = Math.max(1, Number(sp.get("page") || 1));
  const crossLanguage = sp.get("xl") !== "0";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);

  const meta = useAsync<Meta>(() => getMeta(), []);
  const filters: Record<string, string> = {};
  FILTER_KEYS.forEach((k) => {
    const val = sp.get(k);
    if (val) filters[k] = val;
  });
  const key = sp.toString();
  const state = useAsync(
    () => api.get<SearchResponse>(`/api/resources${qs({ q, ...filters, page, page_size: PAGE_SIZE, cross_language: crossLanguage })}`),
    [key],
  );

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, val] of Object.entries(changes)) {
      if (val === null || val === "") next.delete(k);
      else next.set(k, val);
    }
    if (!("page" in changes)) next.delete("page");
    setSp(next);
  };

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    update({ q: draft.trim() || null });
  };

  const m = meta.data;
  const sel = (k: (typeof FILTER_KEYS)[number], label: string, options: [string, string][]) => (
    <label className="field">
      <span>{label}</span>
      <select value={sp.get(k) || ""} onChange={(e) => update({ [k]: e.target.value || null })}>
        <option value="">{t("any")}</option>
        {options.map(([val, lab]) => (
          <option key={val} value={val}>{lab}</option>
        ))}
      </select>
    </label>
  );

  const types = Array.from(new Set([...(m?.resource_types || []), ...RESOURCE_TYPES]));

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("library_title")}</h1>
      </div>
      <Card>
        <form className="search-form" onSubmit={onSearch} role="search">
          <input
            type="search"
            dir="auto"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("search_placeholder")}
            aria-label={t("search")}
            className="search-input"
          />
          <button type="submit" className="btn btn-primary">{t("search")}</button>
          <label className="check">
            <input type="checkbox" checked={crossLanguage} onChange={(e) => update({ xl: e.target.checked ? null : "0" })} />
            {t("cross_language")}
          </label>
        </form>
        <ErrorBox error={meta.error} />
        <details className="filters" open={Object.keys(filters).length > 0}>
          <summary>{t("filters")}{Object.keys(filters).length ? ` (${Object.keys(filters).length})` : ""}</summary>
          <div className="form-grid">
            {sel("language", t("language"), [["ar", t("lang_ar")], ["en", t("lang_en")], ["mixed", t("lang_mixed")]])}
            {sel("pillar", t("pillar"), [["children", t("pillar_children")], ["parents", t("pillar_parents")], ["murabbi", t("pillar_murabbi")]])}
            {sel("type", t("resource_type"), types.map((x) => [x, v(x)]))}
            {sel("access", t("access_status"), ACCESS_VALUES.map((x) => [x, v(x)]))}
            {sel("source", t("source"), (m?.source_keys || []).map((x) => [x, x]))}
            {sel("topic", t("topic"), (m?.topics || []).map((x) => [String(x.id), lang === "ar" ? x.name_ar : x.name_en]))}
            {sel("status", t("processing_status"), PROCESSING_VALUES.map((x) => [x, v(x)]))}
            <label className="field">
              <span>{t("date_from")}</span>
              <input type="date" value={sp.get("date_from") || ""} onChange={(e) => update({ date_from: e.target.value || null })} />
            </label>
            <label className="field">
              <span>{t("date_to")}</span>
              <input type="date" value={sp.get("date_to") || ""} onChange={(e) => update({ date_to: e.target.value || null })} />
            </label>
          </div>
          <button type="button" className="btn btn-small" onClick={() => setSp(new URLSearchParams(q ? { q } : {}))}>
            {t("clear")}
          </button>
        </details>
      </Card>

      <Async state={state}>
        {(d) => (
          <Card>
            {d.expansions && Object.keys(d.expansions).length > 0 ? (
              <p className="expansions">
                <strong>{t("also_searched")}</strong>{" "}
                {Array.from(new Set(Object.values(d.expansions).flat())).map((term) => (
                  <span className="chip" key={term} dir="auto">{term}</span>
                ))}
              </p>
            ) : null}
            {d.results.length === 0 ? <p className="muted">{t("no_results")}</p> : (
              <div className="res-list">
                {d.results.map((r) => (
                  <div key={r.resource.id} className="res-result">
                    <ResourceItem r={r.resource} />
                    {r.passage ? (
                      <blockquote className="snippet" dir="auto">
                        <span>{r.passage.text}</span>
                        {r.passage.page ? <span className="muted small"> — {t("page_short")} {r.passage.page}</span> : null}
                        {r.passage.timestamp != null && r.resource.url ? (
                          <> {" "}<a className="small" href={videoUrlAt(r.resource.url, r.passage.timestamp)} target="_blank" rel="noopener noreferrer">⏱ {fmtTimestamp(r.passage.timestamp)} ▶</a></>
                        ) : null}
                      </blockquote>
                    ) : r.description_snippet ? (
                      <p className="snippet-desc" dir="auto">{r.description_snippet}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
            <Pager page={page} pageSize={d.page_size || PAGE_SIZE} total={d.total} onPage={(p) => update({ page: String(p) })} />
          </Card>
        )}
      </Async>

      <div className="grid-2">
        <UploadForm />
        <AddByUrlForm />
      </div>
    </div>
  );
}

function UploadForm() {
  const { t, v } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [rtype, setRtype] = useState("book");
  const [title, setTitle] = useState("");
  const [authors, setAuthors] = useState("");
  const [license, setLicense] = useState("");
  const [result, setResult] = useState<{ resource_id: number; created: boolean; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("resource_type", rtype);
    fd.append("title", title);
    fd.append("authors", authors);
    fd.append("license", license);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.upload("/api/import", fd));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={t("upload_file")}>
      <form onSubmit={submit} className="form-stack">
        <label className="field">
          <span>{t("file")}</span>
          <input type="file" required onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        <label className="field">
          <span>{t("resource_type")}</span>
          <select value={rtype} onChange={(e) => setRtype(e.target.value)}>
            {RESOURCE_TYPES.map((x) => <option key={x} value={x}>{v(x)}</option>)}
          </select>
        </label>
        <label className="field">
          <span>{t("title")}</span>
          <input dir="auto" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          <span>{t("authors_semicolon")}</span>
          <input dir="auto" value={authors} onChange={(e) => setAuthors(e.target.value)} />
        </label>
        <label className="field">
          <span>{t("license")}</span>
          <input dir="auto" value={license} onChange={(e) => setLicense(e.target.value)} />
        </label>
        <div>
          <button type="submit" className="btn btn-primary" disabled={busy || !file}>{busy ? "…" : ""}{t("upload")}</button>
        </div>
        <ErrorBox error={error} />
        {result ? (
          <div className="alert alert-ok">
            <span dir="auto">{result.message}</span> <Link to={`/resources/${result.resource_id}`}>#{result.resource_id}</Link>
          </div>
        ) : null}
      </form>
    </Card>
  );
}

function AddByUrlForm() {
  const { t, v } = useI18n();
  const [f, setF] = useState({
    title: "", url: "", resource_type: "article", authors: "", description: "", language: "", year: "",
    publisher: "", price: "", currency: "", purchase_url: "", license: "", fetch_page: false,
  });
  const [result, setResult] = useState<{ resource_id: number; created: boolean } | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const opt = (s: string) => (s.trim() ? s.trim() : null);

  const run = async () => {
    setResult(null);
    const body = {
      title: f.title.trim(),
      url: opt(f.url),
      resource_type: f.resource_type,
      authors: f.authors.split(";").map((a) => a.trim()).filter(Boolean),
      description: opt(f.description),
      language: opt(f.language),
      year: f.year ? Number(f.year) : null,
      publisher: opt(f.publisher),
      price: opt(f.price),
      currency: opt(f.currency),
      purchase_url: opt(f.purchase_url),
      license: opt(f.license),
      fetch_page: f.fetch_page,
    };
    if (!body.title) throw new Error(`${t("title")}: required`);
    const r = await api.post<{ resource_id: number; created: boolean }>("/api/resources", body);
    setResult(r);
    return r;
  };

  return (
    <Card title={t("add_by_url")}>
      <form className="form-stack" onSubmit={(e) => e.preventDefault()}>
        <label className="field"><span>{t("title")} *</span><input dir="auto" required value={f.title} onChange={set("title")} /></label>
        <label className="field"><span>{t("url")}</span><input type="url" dir="ltr" value={f.url} onChange={set("url")} /></label>
        <div className="form-grid">
          <label className="field">
            <span>{t("resource_type")}</span>
            <select value={f.resource_type} onChange={set("resource_type")}>
              {RESOURCE_TYPES.map((x) => <option key={x} value={x}>{v(x)}</option>)}
            </select>
          </label>
          <label className="field">
            <span>{t("language")}</span>
            <select value={f.language} onChange={set("language")}>
              <option value="">—</option>
              <option value="ar">{t("lang_ar")}</option>
              <option value="en">{t("lang_en")}</option>
              <option value="mixed">{t("lang_mixed")}</option>
            </select>
          </label>
          <label className="field"><span>{t("year")}</span><input type="number" value={f.year} onChange={set("year")} /></label>
          <label className="field"><span>{t("publisher")}</span><input dir="auto" value={f.publisher} onChange={set("publisher")} /></label>
          <label className="field"><span>{t("price")}</span><input value={f.price} onChange={set("price")} /></label>
          <label className="field"><span>{t("currency")}</span><input value={f.currency} onChange={set("currency")} /></label>
        </div>
        <label className="field"><span>{t("authors_semicolon")}</span><input dir="auto" value={f.authors} onChange={set("authors")} /></label>
        <label className="field"><span>{t("description")}</span><textarea dir="auto" rows={3} value={f.description} onChange={set("description")} /></label>
        <label className="field"><span>{t("purchase_url")}</span><input type="url" dir="ltr" value={f.purchase_url} onChange={set("purchase_url")} /></label>
        <label className="field"><span>{t("license")}</span><input dir="auto" value={f.license} onChange={set("license")} /></label>
        <label className="check">
          <input type="checkbox" checked={f.fetch_page} onChange={(e) => setF({ ...f, fetch_page: e.target.checked })} />
          {t("fetch_page")}
        </label>
        <div>
          <ActionButton className="btn btn-primary" onRun={run} done={(r) => {
            const x = r as { resource_id: number; created: boolean };
            return `${t("added_resource")}${x.resource_id} ${x.created ? "" : t("already_exists")}`;
          }}>
            {t("add")}
          </ActionButton>
          {result ? <> <Link to={`/resources/${result.resource_id}`}>{t("view")} #{result.resource_id}</Link></> : null}
        </div>
      </form>
    </Card>
  );
}
