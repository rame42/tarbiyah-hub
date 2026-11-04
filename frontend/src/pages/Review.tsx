import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ResourceBrief } from "../api";
import { Async, Card, fmtNum, ResourceItem, useAsync } from "../components";
import { useI18n } from "../i18n";

interface ReviewItem extends ResourceBrief { source_name: string | null; description: string | null; reason: string | null }

export default function Review() {
  const { t } = useI18n();
  const [sp] = useSearchParams();
  const source = sp.get("source") || "";
  const state = useAsync(() => api.get<{ total: number; items: ReviewItem[] }>(`/api/review${source ? `?source_id=${source}` : ""}`), [source]);
  const [done, setDone] = useState<Record<number, boolean>>({});
  const act = async (id: number, keep: boolean) => {
    await api.post(`/api/review/${id}`, { keep });
    setDone((d) => ({ ...d, [id]: keep }));
  };
  return (
    <div className="page">
      <div className="page-head"><h1>{t("nav_review")}</h1></div>
      <p className="muted">{t("review_intro")}</p>
      <Async state={state}>
        {(d) => (
          <Card title={`${fmtNum(d.total)} ${t("strict_to_review")}`}>
            {!d.items.length ? <p className="muted">{t("review_empty")}</p> : null}
            <div className="res-list">
              {d.items.map((r) => (
                <div key={r.id} className={`res-result ${r.id in done ? "muted" : ""}`}>
                  <ResourceItem r={r} />
                  {r.source_name ? <p className="small muted" dir="auto">{r.source_name}{r.reason ? ` · ${r.reason}` : ""}</p> : null}
                  {r.description ? <p className="snippet-desc" dir="auto">{r.description}</p> : null}
                  {r.id in done ? <p className="small">{done[r.id] ? t("review_keep") : t("review_reject")}</p> : (
                    <div className="toolbar">
                      <button type="button" className="btn btn-primary btn-small" onClick={() => act(r.id, true)}>{t("review_keep")}</button>
                      <button type="button" className="btn btn-small" onClick={() => act(r.id, false)}>{t("review_reject")}</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}
      </Async>
    </div>
  );
}
