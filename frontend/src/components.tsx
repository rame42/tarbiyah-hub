import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { PillarScore, ResourceBrief } from "./api";
import { useI18n } from "./i18n";

// ---------------------------------------------------------------- data hook

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Loads data with `fn` whenever deps change; optional polling interval (ms). */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], intervalMs?: number): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fnRef
      .current()
      .then((d) => {
        if (!alive) return;
        setData(d);
        setError(null);
      })
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (!intervalMs) return;
    const id = window.setInterval(() => setTick((x) => x + 1), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);

  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { data, error, loading, reload };
}

// ---------------------------------------------------------------- feedback

export function ErrorBox({ error }: { error: string | null | undefined }) {
  const { t } = useI18n();
  if (!error) return null;
  return (
    <div className="alert alert-error" role="alert">
      <strong>{t("error")}:</strong> <span dir="auto">{error}</span>
    </div>
  );
}

export function Loading() {
  const { t } = useI18n();
  return <div className="muted loading">{t("loading")}</div>;
}

/** Standard wrapper: shows loading/error, renders children when data is ready. */
export function Async<T>({ state, children }: { state: AsyncState<T>; children: (d: T) => ReactNode }) {
  return (
    <>
      <ErrorBox error={state.error} />
      {state.data === null ? state.loading ? <Loading /> : null : children(state.data)}
    </>
  );
}

/** A button that runs an API call, shows a busy state and the result or error inline. */
export function ActionButton({
  onRun,
  children,
  className = "btn",
  done,
  confirm,
  disabled,
  title,
}: {
  onRun: () => Promise<unknown>;
  children: ReactNode;
  className?: string;
  done?: (result: unknown) => string | null;
  confirm?: string;
  disabled?: boolean;
  title?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { t } = useI18n();
  const run = async () => {
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await onRun();
      const text = done ? done(r) : defaultDone(r, t("done_job"), t("ok_done"));
      if (text) setMsg({ ok: true, text });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="action">
      <button type="button" className={className} onClick={run} disabled={busy || disabled} title={title}>
        {busy ? "…" : null}
        {children}
      </button>
      {msg ? (
        <span className={msg.ok ? "action-msg ok" : "action-msg err"} role={msg.ok ? "status" : "alert"} dir="auto">
          {msg.text}
        </span>
      ) : null}
    </span>
  );
}

function defaultDone(r: unknown, jobPrefix: string, ok: string): string {
  if (r && typeof r === "object" && "job_id" in r) return `${jobPrefix}${(r as { job_id: number }).job_id}`;
  return ok;
}

// ---------------------------------------------------------------- formatting

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  // backend timestamps are naive UTC
  const hasTz = /[zZ]|[+-]\d\d:?\d\d$/.test(iso);
  const d = new Date(hasTz || iso.length <= 10 ? iso : iso + "Z");
  if (isNaN(d.getTime())) return iso;
  const loc = uiLocale();
  if (!withTime) return d.toLocaleDateString(loc);
  return d.toLocaleString(loc, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Locale for dates follows the UI language (Arabic with Latin digits for readability of mixed content). */
function uiLocale(): string {
  return document.documentElement.lang === "ar" ? "ar-u-nu-latn" : "en-GB";
}

export function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function fmtTimestamp(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "";
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export function asText(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 2);
}

// ---------------------------------------------------------------- badges

const BADGE_TONE: Record<string, string> = {
  succeeded: "good", answered: "good", ok: "good", ready: "good", indexed: "good", extracted: "good", downloaded: "good",
  open_access: "good", open_license: "good", public_domain: "good", supported: "good", passed: "good", active: "good",
  done: "good", sufficient: "good", high: "good",
  failed: "bad", error: "bad", cancelled: "muted", deleted: "muted", contested: "warn", flagged: "warn",
  queued: "info", running: "info", investigating: "info", pending: "warn", retry: "warn", needs_ocr: "warn",
  needs_credentials: "warn", paid: "warn", restricted: "bad", gap: "warn", insufficient: "warn", unresolved: "warn",
  deferred: "muted", duplicate: "muted", not_relevant: "muted", unknown: "muted", metadata_only: "muted",
  open: "info", partial: "warn", medium: "warn", low: "muted", paused: "warn",
};

export function Badge({ value, tone, children }: { value?: string | null; tone?: string; children?: ReactNode }) {
  const { v } = useI18n();
  const cls = tone || (value ? BADGE_TONE[value] : undefined) || "neutral";
  return <span className={`badge badge-${cls}`}>{children ?? v(value)}</span>;
}

export function PillarBadge({ pillar, extra }: { pillar: string; extra?: ReactNode }) {
  const { t } = useI18n();
  const key = `pillar_${pillar}` as "pillar_children";
  const label = ["children", "parents", "murabbi"].includes(pillar) ? t(key) : pillar;
  return (
    <span className={`badge pillar pillar-${pillar}`}>
      {label}
      {extra ? <span className="pillar-extra"> {extra}</span> : null}
    </span>
  );
}

export function PillarBadges({ pillars }: { pillars: (PillarScore | string)[] | null | undefined }) {
  if (!pillars || pillars.length === 0) return null;
  return (
    <span className="badges">
      {pillars.map((p) => {
        const name = typeof p === "string" ? p : p.pillar;
        return <PillarBadge key={name} pillar={name} />;
      })}
    </span>
  );
}

export function BoolBadge({ value, yes, no }: { value: boolean | null | undefined; yes?: string; no?: string }) {
  const { t } = useI18n();
  return <span className={`badge badge-${value ? "good" : "muted"}`}>{value ? yes ?? t("yes") : no ?? t("no")}</span>;
}

// ---------------------------------------------------------------- layout bits

export function Card({ title, children, actions, className = "" }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {title || actions ? (
        <header className="card-head">
          {title ? <h2>{title}</h2> : <span />}
          {actions ? <div className="card-actions">{actions}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, val], i) => (
        <div className="kv-row" key={i}>
          <dt>{k}</dt>
          <dd>{val === null || val === undefined || val === "" ? "—" : val}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Stat({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub ? <div className="stat-sub">{sub}</div> : null}
    </div>
  );
}

/** Horizontal CSS bar chart for a {label: count} map. */
export function Bars({ data, labels, colorFor }: { data: Record<string, number>; labels?: (k: string) => ReactNode; colorFor?: (k: string) => string }) {
  const { t } = useI18n();
  const entries = Object.entries(data || {});
  if (entries.length === 0) return <p className="muted">{t("none")}</p>;
  const max = Math.max(1, ...entries.map(([, n]) => n));
  return (
    <div className="bars">
      {entries.map(([k, n]) => (
        <div className="bar-row" key={k}>
          <span className="bar-label" dir="auto">{labels ? labels(k) : k}</span>
          <span className="bar-track">
            <span className={`bar-fill ${colorFor ? colorFor(k) : ""}`} style={{ inlineSize: `${(n / max) * 100}%` }} />
          </span>
          <span className="bar-num">{fmtNum(n)}</span>
        </div>
      ))}
    </div>
  );
}

/** Simple label → count list using translated values for keys. */
export function CountList({ data }: { data: Record<string, number> | null | undefined }) {
  const { v, t } = useI18n();
  const entries = Object.entries(data || {});
  if (!entries.length) return <span className="muted">{t("none")}</span>;
  return (
    <span className="chips">
      {entries.map(([k, n]) => (
        <span className="chip" key={k}>
          <span dir="auto">{v(k)}</span> <strong>{fmtNum(n)}</strong>
        </span>
      ))}
    </span>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const { t } = useI18n();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pager">
      <button type="button" className="btn btn-small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {t("prev")}
      </button>
      <span>
        {t("page")} {page} {t("of")} {pages} · {fmtNum(total)} {t("results")}
      </span>
      <button type="button" className="btn btn-small" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        {t("next")}
      </button>
    </div>
  );
}

export function ResourceLink({ r }: { r: Pick<ResourceBrief, "id" | "title"> }) {
  return (
    <Link to={`/resources/${r.id}`} dir="auto" className="content-text">
      {r.title || `#${r.id}`}
    </Link>
  );
}

/** Link to the original video, optionally at a given second (YouTube supports t=). */
export function videoUrlAt(url: string, seconds?: number | null): string {
  if (seconds === null || seconds === undefined || seconds < 0) return url;
  try {
    const u = new URL(url);
    if (/(^|\.)youtube\.com$|(^|\.)youtu\.be$/.test(u.hostname)) {
      u.searchParams.set("t", `${Math.floor(seconds)}s`);
      return u.toString();
    }
  } catch {
    /* not a valid URL: return it unchanged */
  }
  return url;
}

function videoPlatform(url: string | null | undefined): "youtube" | "tiktok" | null {
  if (!url) return null;
  if (/youtube\.com|youtu\.be/i.test(url)) return "youtube";
  if (/tiktok\.com/i.test(url)) return "tiktok";
  return null;
}

/** "Watch on YouTube" button; videos are never downloaded, they open on their own site. */
export function WatchButton({ url, type, seconds, small }: { url: string | null | undefined; type?: string; seconds?: number | null; small?: boolean }) {
  const { t } = useI18n();
  const platform = videoPlatform(url);
  if (!url || (!platform && type !== "video")) return null;
  const label = platform === "youtube" ? t("watch_youtube") : platform === "tiktok" ? t("watch_tiktok") : t("watch_video");
  return (
    <a className={`btn btn-watch${small ? " btn-small" : ""}`} href={videoUrlAt(url, seconds)} target="_blank" rel="noopener noreferrer">
      ▶ {label} ↗
    </a>
  );
}

/** One-line resource summary used in lists. */
export function ResourceItem({ r }: { r: ResourceBrief }) {
  const { t } = useI18n();
  return (
    <div className="res-item">
      <div className="res-title">
        <ResourceLink r={r} />
      </div>
      <div className="res-meta">
        {r.authors ? <span dir="auto">{r.authors}</span> : null}
        <Badge value={r.type} tone="neutral" />
        {r.language ? <span className="badge badge-neutral">{r.language}</span> : null}
        {r.year ? <span>{r.year}</span> : null}
        <Badge value={r.access_status} />
        {r.has_file ? <span className="badge badge-info">{t("has_file")}</span> : null}
        <PillarBadges pillars={r.pillars} />
        <WatchButton url={r.url} type={r.type} small />
        {r.url && !videoPlatform(r.url) && r.type !== "video" && !r.has_file ? (
          <a className="small" href={r.url} target="_blank" rel="noopener noreferrer">{t("open_link")} ↗</a>
        ) : null}
      </div>
    </div>
  );
}

export function Pre({ children }: { children: ReactNode }) {
  return (
    <pre className="pre" dir="auto">
      {children}
    </pre>
  );
}

export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="table-wrap">{children}</div>;
}
