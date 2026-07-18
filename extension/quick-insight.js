export function quickInsightView(insight = {}, actions = []) {
  const cards = Array.isArray(insight.cards) ? insight.cards : [];
  const decision = cards.find((card) => card.type === "score") || {};
  const details = cards.find((card) => card.id === "job_overview") || {};
  const items = Object.fromEntries(
    (details.items || []).map((item) => [item.label, item.value])
  );
  const textCard = (id) => cards.find((card) => card.id === id) || {};
  const plainText = (html = "") => html.replace(/<[^>]+>/g, "").trim();
  const summary = textCard("summary");
  return {
    type: decision.type === "score" ? "job_match" : "summary",
    title: insight.title || "Quick Insight",
    summaryHtml: summary.body_html || "",
    score: Number.isInteger(decision.score) ? decision.score : null,
    recommendation: decision.recommendation || "",
    reason: decision.reason || "",
    overview: {
      industryBusiness: items.industry_business || "",
      roleFocus: items.role_focus || "",
      summary: details.summary || "",
    },
    topStrength: plainText(textCard("top_strength").body_html),
    topGap: plainText(textCard("top_gap").body_html),
    actions,
  };
}
