export function quickInsightView(insight = {}, actions = []) {
  const overview = insight.job_overview || {};
  return {
    type: insight.type || "summary",
    title: insight.title || "Quick Insight",
    summaryHtml: insight.summary_html || "",
    score: Number.isInteger(insight.score) ? insight.score : null,
    recommendation: insight.recommendation || "",
    reason: insight.reason || "",
    overview: {
      industryBusiness: overview.industry_business || "",
      roleFocus: overview.role_focus || "",
      summary: overview.summary || "",
    },
    topStrength: insight.top_strength || "",
    topGap: insight.top_gap || "",
    actions: actions.filter((action) => action.enabled !== false),
  };
}
