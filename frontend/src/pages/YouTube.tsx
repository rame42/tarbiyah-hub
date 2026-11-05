import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ActionButton, Async, Card, fmtDate, fmtNum, useAsync } from "../components";
import { useI18n } from "../i18n";

interface Suggestion { id: string; title: string; description: string; thumbnail: string | null; subscribers: number;
  videos: number; sample_titles: string[]; url: string; score: number; pillars: string[]; reason: string; found_with: string }
interface MyChannel { id: number; name: string; enabled: boolean; health: string; items: number; channel_ids: string[];
  playlist_ids: string[]; only_playlists: boolean; min_minutes: number | null; strict: boolean }
interface Overview { key_set: boolean; suggestions: Suggestion[]; updated_at: string | null; running: boolean; dismissed: number;
  quota_used_today: number; quota_limit: number; default_min_minutes: number; channels: MyChannel[]; learned: string[] }
const PILLARS = ["children", "parents", "murabbi"];

export default function YouTube() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<Overview>("/api/youtube"), []);
  const running = !!state.data?.running;
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => state.reload(), 5000);
    return () => window.clearInterval(id);
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="page">
      <div className="page-head"><h1>{t("nav_youtube")}</h1></div>
      <p className="muted">{t("yt_intro")}</p>
      <Async state={state}>
        {(d) => (
          <>
            {!d.key_set ? <div className="alert alert-warn">{t("yt_need_key")} <Link to="/settings">{t("nav_settings")}</Link></div> : null}
            <FindChannels d={d} reload={state.reload} />
            <Card title={`${t("yt_suggested")} (${d.suggestions.length})`}>
              {!d.suggestions.length ? <p className="small muted">{t("yt_no_suggestions")}</p> : null}
              <div className="res-list">{d.suggestions.map((x) => <SuggestionRow key={x.id} x={x} reload={state.reload} />)}</div>
            </Card>
            <Card title={`${t("yt_my_channels")} (${d.channels.length})`}>
              <p className="small muted">{t("yt_my_channels_help")}</p>
              {d.channels.map((c) => <ChannelRow key={c.id} c={c} defMin={d.default_min_minutes} />)}
            </Card>
          </>
        )}
      </Async>
    </div>
  );
}

function FindChannels({ d, reload }: { d: Overview; reload: () => void }) {
  const { t } = useI18n();
  const [pillars, setPillars] = useState<string[]>(["children"]);
  const [n, setN] = useState(6);
  return (
    <Card title={t("yt_find_title")}>
      <p className="small">{t("yt_find_text")}</p>
      <div className="toolbar spaced">
        {PILLARS.map((p) => <label key={p} className="check"><input type="checkbox" checked={pillars.includes(p)}
          onChange={() => setPillars((c) => (c.includes(p) ? c.filter((x) => x !== p) : [...c, p]))} />{t(`pillar_${p}` as never)}</label>)}
        <label className="field inline-field"><span>{t("yt_searches")}</span>
          <input type="number" min={1} max={20} value={n} onChange={(e) => setN(Number(e.target.value) || 1)} /></label>
        <ActionButton className="btn btn-primary" disabled={!d.key_set || d.running || !pillars.length}
          onRun={async () => { const r = await api.post("/api/youtube/discover", { pillars, max_queries: n }); reload(); return r; }}>
          {d.running ? t("yt_searching") : t("yt_find_btn")}
        </ActionButton>
      </div>
      <p className="small muted">{t("yt_quota")}: {fmtNum(d.quota_used_today)} / {fmtNum(d.quota_limit)} · {t("yt_cost").replace("{n}", String(n * 100))}
        {d.updated_at ? ` · ${t("updated")}: ${fmtDate(d.updated_at)}` : ""} · {t("yt_dismissed")}: {d.dismissed}</p>
      {d.learned.length ? <p className="small muted" dir="auto">{t("yt_learned")}: {d.learned.join(" · ")}</p> : null}
    </Card>
  );
}

function SuggestionRow({ x, reload }: { x: Suggestion; reload: () => void }) {
  const { t } = useI18n();
  const [pillars, setPillars] = useState<string[]>(x.pillars.length ? x.pillars : ["children"]);
  const act = (path: string, body: object) => async () => { const r = await api.post(path, body); reload(); return r; };
  return (
    <div className="res-result yt-suggestion">
      <div className="yt-head">
        {x.thumbnail ? <img src={x.thumbnail} alt="" width={48} height={48} loading="lazy" /> : null}
        <div>
          <a href={x.url} target="_blank" rel="noopener noreferrer" dir="auto"><strong>{x.title}</strong> ↗</a>
          <div className="res-meta small">
            <span className={`badge badge-${x.score >= 60 ? "good" : x.score >= 40 ? "warn" : "muted"}`}>{t("relevance_short")} {x.score}</span>
            <span>{fmtNum(x.subscribers)} {t("yt_subscribers")} · {fmtNum(x.videos)} {t("yt_videos")}</span>
            <span className="muted" dir="auto">{t("yt_found_with")}: {x.found_with}</span>
          </div>
        </div>
      </div>
      {x.description ? <p className="snippet-desc" dir="auto">{x.description.slice(0, 260)}</p> : null}
      {x.sample_titles.length ? <ul className="small yt-samples">{x.sample_titles.slice(0, 5).map((s, i) => <li key={i} dir="auto">{s}</li>)}</ul> : null}
      {x.reason && x.reason !== "keyword rules" ? <p className="small muted" dir="auto">{t("relevance_reason")}: {x.reason}</p> : null}
      <div className="toolbar spaced">
        {PILLARS.map((p) => <label key={p} className="check small"><input type="checkbox" checked={pillars.includes(p)}
          onChange={() => setPillars((c) => (c.includes(p) ? c.filter((y) => y !== p) : [...c, p]))} />{t(`pillar_${p}` as never)}</label>)}
        <ActionButton className="btn btn-primary btn-small" disabled={!pillars.length} onRun={act("/api/youtube/add", { channel_id: x.id, pillars })}>{t("yt_add")}</ActionButton>
        <ActionButton className="btn btn-small" onRun={act("/api/youtube/dismiss", { channel_id: x.id })}>{t("dismiss")}</ActionButton>
      </div>
    </div>
  );
}

interface Playlist { id: string; title: string; count: number; url: string }

function ChannelRow({ c, defMin }: { c: MyChannel; defMin: number }) {
  const { t } = useI18n();
  const [lists, setLists] = useState<Playlist[] | null>(null);
  const [chosen, setChosen] = useState<string[]>(c.only_playlists ? c.playlist_ids : []);
  const [mins, setMins] = useState(String(c.min_minutes ?? defMin));
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = async () => {
    setErr(null);
    try { setLists((await api.get<{ playlists: Playlist[] }>(`/api/my-sources/${c.id}/youtube-playlists`)).playlists); }
    catch (e) { setErr((e as Error).message); }
  };
  const save = async (whole: boolean) => {
    setErr(null);
    try {
      await api.put(`/api/my-sources/${c.id}/youtube-playlists`, { playlist_ids: whole ? [] : chosen, whole_channel: whole, min_minutes: Number(mins) || 0 });
      setMsg(t("keys_saved"));
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <details className="strict-panel">
      <summary dir="auto"><strong>{c.name}</strong> <span className="small muted">· {fmtNum(c.items)} {t("my_items").toLowerCase()} · {c.only_playlists ? `${c.playlist_ids.length} ${t("yt_playlists_n")}` : t("yt_whole_channel")}{c.enabled ? "" : ` · ${t("disabled")}`}</span></summary>
      <div className="form-stack small">
        <div className="toolbar spaced">
          <button type="button" className="btn btn-small" onClick={load}>{t("yt_show_playlists")}</button>
          <label className="field inline-field"><span>{t("yt_min_minutes")}</span>
            <input type="number" min={0} max={300} value={mins} onChange={(e) => setMins(e.target.value)} /></label>
          <Link className="btn btn-ghost btn-small" to="/my-sources">{t("yt_rules_link")}</Link>
        </div>
        {lists ? (
          <div className="sections-list">
            {!lists.length ? <span className="muted">{t("yt_no_playlists")}</span> : null}
            {lists.map((p) => (
              <label key={p.id} className="check" dir="auto">
                <input type="checkbox" checked={chosen.includes(p.id)} onChange={() => setChosen((x) => (x.includes(p.id) ? x.filter((y) => y !== p.id) : [...x, p.id]))} />
                <span>{p.title} <span className="muted">({p.count})</span> <a href={p.url} target="_blank" rel="noopener noreferrer" className="muted">↗</a></span>
              </label>
            ))}
          </div>
        ) : null}
        <div className="toolbar spaced">
          <button type="button" className="btn btn-primary btn-small" disabled={!chosen.length} onClick={() => save(false)}>{t("yt_only_these")} ({chosen.length})</button>
          <button type="button" className="btn btn-small" onClick={() => save(true)}>{t("yt_use_whole")}</button>
          {msg ? <span role="status">{msg}</span> : null}
          {err ? <span className="text-error">{err}</span> : null}
        </div>
      </div>
    </details>
  );
}
