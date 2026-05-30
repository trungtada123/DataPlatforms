import type { IntentPlan } from "./types";

const TOOL_LABELS: Record<string, string> = {
  market: "Thị trường",
  news: "Tin tức",
  financial_reports: "Báo cáo tài chính",
};

const INTENT_LABELS: Record<string, string> = {
  market: "Thị trường",
  news: "Tin tức",
  financial_reports: "Báo cáo tài chính",
  unknown: "Chưa xác định",
};

const ANALYSIS_LABELS: Record<string, string> = {
  intraday: "Phiên / giá hiện tại",
  historical: "Dữ liệu lịch sử",
  technical_analysis: "Chỉ báo kỹ thuật",
  comparison: "So sánh",
  news: "Tin tức",
  financial_reports: "BCTC",
  health_debug: "Health / debug",
};

const CLASSIFIER_MODE_LABELS: Record<string, string> = {
  gemini: "LLM (Gemini)",
  rule_based: "Rule-based",
  fallback_rule_based: "Fallback rule-based",
};

export type IntentKeywordGroup = {
  id: string;
  title: string;
  items: Array<{ key: string; label: string; value?: string }>;
};

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter(Boolean);
}

function formatToolName(tool: string): string {
  return TOOL_LABELS[tool] ?? tool;
}

function formatIntent(intent: string | undefined): string {
  if (!intent) return "—";
  return INTENT_LABELS[intent] ?? intent;
}

function formatClassifierMode(mode: string | undefined): string {
  if (!mode) return "—";
  return CLASSIFIER_MODE_LABELS[mode] ?? mode;
}

/** Gom nhãn keyword từ IntentPlan để hiển thị trên UI. */
export function buildIntentClassifierView(plan: IntentPlan) {
  const tools = plan.tools_to_use ?? [];
  const toolQueries = plan.tool_queries ?? {};
  const entities = plan.entities ?? {};
  const timeConstraints = plan.time_constraints ?? {};
  const analysis = plan.analysis_requirements ?? {};

  const toolQueryItems = (tools.length > 0 ? tools : Object.keys(toolQueries)).map((tool) => {
    const key = String(tool);
    const query = toolQueries[key]?.trim();
    return {
      key,
      label: formatToolName(key),
      value: query || "—",
    };
  });

  const entityItems: IntentKeywordGroup["items"] = [];
  const tickers = asStringList(entities.tickers);
  if (tickers.length > 0) {
    entityItems.push({ key: "tickers", label: "Mã CK", value: tickers.join(", ") });
  }
  const companies = asStringList(entities.company_names);
  if (companies.length > 0) {
    entityItems.push({ key: "company_names", label: "Công ty", value: companies.join(", ") });
  }
  const newsSites = asStringList(entities.news_sites);
  if (newsSites.length > 0) {
    entityItems.push({ key: "news_sites", label: "Nguồn tin", value: newsSites.join(", ") });
  }

  const timeItems: IntentKeywordGroup["items"] = [];
  const explicitDates = asStringList(timeConstraints.explicit_dates);
  if (explicitDates.length > 0) {
    timeItems.push({ key: "explicit_dates", label: "Ngày cụ thể", value: explicitDates.join(", ") });
  }
  const dateRange = asStringList(timeConstraints.date_range);
  if (dateRange.length > 0) {
    timeItems.push({ key: "date_range", label: "Khoảng ngày", value: dateRange.join(" → ") });
  }
  const relativePeriods = asStringList(timeConstraints.relative_periods);
  if (relativePeriods.length > 0) {
    timeItems.push({ key: "relative_periods", label: "Kỳ tương đối", value: relativePeriods.join(", ") });
  }

  const analysisTags = Object.entries(analysis)
    .filter(([, enabled]) => Boolean(enabled))
    .map(([key]) => ({
      key,
      label: ANALYSIS_LABELS[key] ?? key,
    }));

  const groups: IntentKeywordGroup[] = [];
  if (toolQueryItems.length > 0) {
    groups.push({ id: "tool_queries", title: "Truy vấn gửi từng nhánh", items: toolQueryItems });
  }
  if (entityItems.length > 0) {
    groups.push({ id: "entities", title: "Thực thể (entities)", items: entityItems });
  }
  if (timeItems.length > 0) {
    groups.push({ id: "time", title: "Ràng buộc thời gian", items: timeItems });
  }

  return {
    primaryIntent: formatIntent(plan.primary_intent),
    classifierMode: formatClassifierMode(plan.classifier_mode),
    normalizedQuery: plan.normalized_query?.trim() || "—",
    reasoningBrief: plan.reasoning_brief?.trim() || "",
    tools: tools.map((t) => ({ key: String(t), label: formatToolName(String(t)) })),
    toolQueryItems,
    analysisTags,
    groups,
  };
}
