import { Link, useParams } from "react-router-dom";
import { api, ResourceBrief } from "../api";
import { Async, Badge, Card, KV, Pre, ResourceItem, useAsync } from "../components";
import { useI18n } from "../i18n";

interface EntityFull {
  id: number; type: string; name: string; name_ar: string | null; name_en: string | null; description: string | null;
  origin: string | null; extra: Record<string, unknown> | null; resources: ResourceBrief[];
}

export default function EntityDetail() {
  const { id } = useParams();
  const { t, v } = useI18n();
  const state = useAsync(() => api.get<EntityFull>(`/api/entities/${id}`), [id]);
  return (
    <div className="page">
      <p><Link to="/entities"><span className="flip" aria-hidden="true">‹</span> {t("nav_entities")}</Link></p>
      <Async state={state}>
        {(e) => (
          <>
            <div className="page-head"><h1 dir="auto" className="content-text">{e.name}</h1><Badge value={e.type} tone="neutral" /></div>
            <Card title={t("details")}>
              <KV rows={[
                [t("name_ar"), e.name_ar ? <span dir="auto">{e.name_ar}</span> : null],
                [t("name_en"), e.name_en ? <span dir="auto">{e.name_en}</span> : null],
                [t("origin"), v(e.origin)],
                [t("description"), e.description ? <span dir="auto">{e.description}</span> : null],
              ]} />
              {e.extra && Object.keys(e.extra).length ? (<><h3>{t("extra")}</h3><Pre>{JSON.stringify(e.extra, null, 2)}</Pre></>) : null}
            </Card>
            <Card title={`${t("resources_n")} (${e.resources.length})`}>
              {e.resources.length === 0 ? <p className="muted">{t("none")}</p> : (
                <div className="res-list">
                  {e.resources.map((r) => (
                    <div key={`${r.id}-${r.role}`}>
                      <ResourceItem r={r} />
                      {r.role ? <span className="muted small">{t("role")}: {r.role}</span> : null}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </>
        )}
      </Async>
    </div>
  );
}
