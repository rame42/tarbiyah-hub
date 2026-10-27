import { Link } from "react-router-dom";
import { api } from "../api";
import { ActionButton, Async, Badge, Card, PillarBadge, TableWrap, useAsync } from "../components";
import { useI18n } from "../i18n";

interface ReportRow {
  day: string;
  summary: string | null;
  finalized: boolean;
  discoveries: number;
  pillars: Record<string, number>;
  findings: number;
}

export default function History() {
  const { t } = useI18n();
  const state = useAsync(() => api.get<ReportRow[]>("/api/reports?limit=120"), []);
  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("history_title")}</h1>
        <button type="button" className="btn" onClick={state.reload}>{t("refresh")}</button>
      </div>
      <Async state={state}>
        {(rows) => (
          <Card>
            {rows.length === 0 ? <p className="muted">{t("nothing_yet")}</p> : (
              <TableWrap>
                <table>
                  <thead>
                    <tr>
                      <th>{t("day")}</th>
                      <th>{t("new_resources")}</th>
                      <th>{t("pillars")}</th>
                      <th>{t("findings")}</th>
                      <th>{t("summary")}</th>
                      <th>{t("actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.day}>
                        <td className="nowrap">
                          <Link to={`/day/${r.day}`}>{r.day}</Link>{" "}
                          <Badge tone={r.finalized ? "good" : "neutral"}>{r.finalized ? t("finalized") : t("not_finalized")}</Badge>
                        </td>
                        <td>{r.discoveries}</td>
                        <td>
                          <span className="badges">
                            {Object.entries(r.pillars || {}).map(([p, n]) =>
                              p === "unclassified" ? (
                                <span key={p} className="badge badge-muted">{t("unclassified")} {n}</span>
                              ) : (
                                <PillarBadge key={p} pillar={p} extra={n} />
                              ),
                            )}
                          </span>
                        </td>
                        <td>{r.findings}</td>
                        <td className="wide-cell" dir="auto">{r.summary}</td>
                        <td className="nowrap">
                          <Link className="btn btn-small" to={`/day/${r.day}`}>{t("open_day")}</Link>{" "}
                          <ActionButton className="btn btn-small" onRun={async () => { const x = await api.post(`/api/reports/${r.day}/rebuild`); state.reload(); return x; }}>
                            {t("rebuild")}
                          </ActionButton>
                        </td>
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
