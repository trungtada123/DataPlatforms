import type { MergedContext, QueryResponse } from "./types";

const TOOL_LABELS: Record<string, string> = {
  market: "Thị trường (SSI / SQL)",
  news: "Tin tức",
  financial_reports: "Báo cáo tài chính (BCTC)",
  financial: "Báo cáo tài chính (BCTC)",
};

const ANSWER_STYLE_LABELS: Record<string, string> = {
  integrated_analysis: "Phân tích tổng hợp",
  balanced_investment_view: "Góc nhìn đầu tư cân bằng",
  comparison_analysis: "So sánh",
  concise_answer: "Trả lời ngắn gọn",
};

export function toolLabel(toolName: string | undefined): string {
  if (!toolName) return "Công cụ";
  return TOOL_LABELS[toolName] ?? toolName;
}

export function answerStyleLabel(style: string | undefined): string {
  if (!style) return "—";
  return ANSWER_STYLE_LABELS[style] ?? style;
}

export function extractMergedContext(data: QueryResponse): MergedContext | null {
  const top = data.merged_context;
  if (top && typeof top === "object") {
    return top;
  }

  const fromMeta = data.debug_trace?.metadata?.merged_context;
  if (fromMeta && typeof fromMeta === "object" && !Array.isArray(fromMeta)) {
    return fromMeta as MergedContext;
  }
  if (typeof fromMeta === "string") {
    try {
      return JSON.parse(fromMeta) as MergedContext;
    } catch {
      return null;
    }
  }
  return null;
}

export function truncateText(value: unknown, max = 160): string {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

export function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item ?? "").trim()).filter(Boolean);
}

export function asRecordList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (item && typeof item === "object" && !Array.isArray(item) ? (item as Record<string, unknown>) : null))
    .filter((item): item is Record<string, unknown> => item !== null);
}
