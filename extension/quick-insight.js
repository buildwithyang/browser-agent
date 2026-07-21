import { workspaceOperationErrorEvent } from "./workspace-operation.js";
import { applyForCurrentOwner } from "./workspace-controller.js";

/** Normalize a typed Quick Insight response for the existing overlay renderer. */
export function quickInsightView(insight = {}, shortcuts = []) {
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
    shortcuts,
  };
}

/** Build Action error presentation data for the Quick Insight overlay. */
export function quickInsightActionErrorView(errorEvent, lang) {
  if (
    errorEvent?.type === "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED"
  ) {
    return {
      message: lang === "en"
        ? "Update Agent Bridge to continue."
        : "请更新 Agent Bridge 后继续。",
      updateUrl: typeof errorEvent.updateUrl === "string" && errorEvent.updateUrl
        ? errorEvent.updateUrl
        : null,
      updateLabel: lang === "en" ? "Update extension" : "更新扩展",
    };
  }
  return {
    message: lang === "en"
      ? "Workspace failed to open. Please retry."
      : "Workspace 打开失败，请重试。",
    updateUrl: null,
    updateLabel: "",
  };
}

/** Describe the initial Quick Insight request error without mutating auth or Workspace state. */
export function quickInsightRequestErrorView(error, lang) {
  const event = workspaceOperationErrorEvent(error);
  if (event.type === "AGENT_BRIDGE_EXTENSION_UPDATE_REQUIRED") {
    const update = quickInsightActionErrorView(event, lang);
    return {
      errorTitle: lang === "en" ? "Update required" : "需要更新",
      errorHint: update.message,
      updateUrl: update.updateUrl,
      updateLabel: update.updateLabel,
      updateTarget: "_blank",
      updateRel: "noopener noreferrer",
    };
  }
  const hint = error?.name === "AbortError"
    ? "请求超时,网关无响应。"
    : `无法连接网关 (${error?.message || "Unknown error"})。`;
  return {
    errorHint: hint,
    errorCmd: "./dev-start backend",
  };
}

/** Present one successful Quick Insight only while its request owner remains current. */
export async function presentQuickInsightForCurrentOwner(task, dependencies = {}) {
  const {
    snapshot,
    readCurrentSnapshot,
    present,
    onOwnerMismatch,
  } = dependencies;
  if (typeof present !== "function") {
    throw new TypeError("Quick Insight presenter is required");
  }
  return applyForCurrentOwner({
    snapshot,
    readCurrentSnapshot,
    onOwnerMismatch,
    apply: () => present(task),
  });
}
