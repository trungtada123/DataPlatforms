import type { QueryResponse } from "./types";

export type PipelineStepId =
  | "classify"
  | "router"
  | "agents_parallel"
  | "market_agent"
  | "news_agent"
  | "financial_agent"
  | "merge"
  | "synthesize";

export type PipelineStepStatus = "pending" | "active" | "done" | "error" | "skipped";

export type PipelineStep = {
  id: PipelineStepId;
  label: string;
  status: PipelineStepStatus;
  detail?: string;
};

const AGENT_IDS: PipelineStepId[] = ["market_agent", "news_agent", "financial_agent"];

const STEP_LABELS: Record<string, string> = {
  classify: "Phân loại ý định",
  classifier: "Phân loại ý định",
  router: "Định tuyến công cụ",
  agents_parallel: "Agent (chạy song song)",
  market_agent: "Agent thị trường (market)",
  news_agent: "Agent tin tức (news)",
  financial_agent: "Agent báo cáo tài chính",
  financial_reports_agent: "Agent báo cáo tài chính",
  execute_tools: "Agent (chạy song song)",
  merger: "Gộp kết quả",
  merge: "Gộp kết quả",
  synthesizer: "Tổng hợp câu trả lời",
  synthesize: "Tổng hợp câu trả lời",
};

const SHORT_DETAILS: Partial<Record<PipelineStepId, string>> = {
  classify: "Đã phân loại ý định và chọn công cụ.",
  router: "Đã chọn công cụ cần chạy.",
  market_agent: "Agent market hoàn tất.",
  news_agent: "Agent news hoàn tất.",
  financial_agent: "Agent báo cáo tài chính hoàn tất.",
  merge: "Đã gộp kết quả từ các agent.",
  synthesize: "Đã tạo câu trả lời cuối.",
};

/** Thứ tự khi đang chờ — agent gom một bước song song. */
export const LOADING_PIPELINE_ORDER: PipelineStepId[] = [
  "classify",
  "router",
  "agents_parallel",
  "merge",
  "synthesize",
];

export function labelForStep(step: string): string {
  return STEP_LABELS[step] ?? step.replace(/_/g, " ");
}

export function isAgentStep(id: PipelineStepId): boolean {
  return AGENT_IDS.includes(id);
}

export function buildLoadingPipeline(activeIndex: number): PipelineStep[] {
  return LOADING_PIPELINE_ORDER.map((id, index) => {
    let status: PipelineStepStatus = "pending";
    if (index < activeIndex) status = "done";
    else if (index === activeIndex) status = "active";

    let detail: string | undefined;
    if (id === "agents_parallel") {
      if (status === "active") {
        detail = "Các agent được chọn đang chạy độc lập, song song…";
      } else if (status === "done") {
        detail = "Đã hoàn tất các agent.";
      }
    }

    return {
      id,
      label: labelForStep(id),
      status,
      detail,
    };
  });
}

export function loadingProgressPercent(activeIndex: number): number {
  const total = LOADING_PIPELINE_ORDER.length;
  const capped = Math.min(activeIndex + 1, total);
  return Math.round((capped / total) * 100);
}

function normalizeEventStep(step: string): PipelineStepId | null {
  const raw = step.trim().toLowerCase();
  if (raw === "classifier") return "classify";
  if (raw === "merger") return "merge";
  if (raw === "synthesizer") return "synthesize";
  if (raw === "execute_tools") return "agents_parallel";
  if (raw in STEP_LABELS || LOADING_PIPELINE_ORDER.includes(raw as PipelineStepId)) {
    return raw as PipelineStepId;
  }
  if (raw.endsWith("_agent")) {
    if (raw.startsWith("financial")) return "financial_agent";
    if (raw.startsWith("market")) return "market_agent";
    if (raw.startsWith("news")) return "news_agent";
  }
  return null;
}

function eventStatusToPipeline(status: string | undefined): PipelineStepStatus {
  const value = (status ?? "ok").toLowerCase();
  if (value === "error") return "error";
  if (value === "warning" || value === "skipped") return "skipped";
  return "done";
}

type TraceEventLike = {
  step?: string;
  detail?: string | null;
  metadata?: Record<string, unknown>;
};

function formatToolsList(tools: unknown): string | null {
  if (!Array.isArray(tools) || tools.length === 0) return null;
  const labels = tools.map((tool) => String(tool).trim()).filter(Boolean);
  return labels.length ? labels.join(", ") : null;
}

function resolveStepDetail(
  id: PipelineStepId,
  event: TraceEventLike | undefined,
  data: QueryResponse,
): string | undefined {
  if (id === "router") {
    const detail = event?.detail?.trim();
    if (detail && detail.includes("chọn công cụ")) return detail;
    const fromMeta = formatToolsList(event?.metadata?.selected_tools);
    const fromPlan = formatToolsList(data.intent_plan?.tools_to_use);
    const fromTools = formatToolsList(data.tools_used);
    const label = fromMeta ?? fromPlan ?? fromTools;
    if (label) return `Công cụ được chọn: ${label}.`;
  }

  if (id === "classify") {
    const fromPlan = formatToolsList(data.intent_plan?.tools_to_use);
    if (fromPlan) return `Dự kiến dùng: ${fromPlan}.`;
  }

  const detail = event?.detail?.trim();
  if (!detail) return SHORT_DETAILS[id];
  if (id === "router" || id === "classify") return detail;
  if (detail.length > 120 || /[A-Za-z]{14,}/.test(detail)) {
    return SHORT_DETAILS[id] ?? "Hoàn tất.";
  }
  return detail;
}

function toolsToAgentSteps(tools: string[]): PipelineStepId[] {
  const normalized = new Set(tools.map((t) => t.toLowerCase()));
  const steps: PipelineStepId[] = [];
  if (normalized.has("market")) steps.push("market_agent");
  if (normalized.has("news")) steps.push("news_agent");
  if (normalized.has("financial") || normalized.has("financial_reports")) {
    steps.push("financial_agent");
  }
  return steps;
}

export function buildCompletedPipeline(data: QueryResponse): PipelineStep[] {
  const events = data.debug_trace?.events ?? [];
  const byId = new Map<PipelineStepId, PipelineStep>();

  for (const event of events) {
    const id = normalizeEventStep(event.step ?? "");
    if (!id || id === "agents_parallel") continue;
    byId.set(id, {
      id,
      label: labelForStep(event.step ?? id),
      status: eventStatusToPipeline(event.status),
      detail: resolveStepDetail(id, event, data),
    });
  }

  const agentSteps = toolsToAgentSteps(data.tools_used ?? []);

  const ordered: PipelineStepId[] = ["classify", "router", ...agentSteps, "merge", "synthesize"];

  return ordered.map((id) => {
    if (byId.has(id)) return byId.get(id)!;
    return {
      id,
      label: labelForStep(id),
      status: "done",
      detail: resolveStepDetail(id, undefined, data) ?? SHORT_DETAILS[id],
    };
  });
}

export function splitPipelineSteps(steps: PipelineStep[]): {
  pre: PipelineStep[];
  agents: PipelineStep[];
  post: PipelineStep[];
} {
  const agents = steps.filter((step) => isAgentStep(step.id));
  const pre = steps.filter((step) => !isAgentStep(step.id) && (step.id === "classify" || step.id === "router"));
  const post = steps.filter((step) => step.id === "merge" || step.id === "synthesize");
  return { pre, agents, post };
}

export function hasPipelineTrace(data: QueryResponse): boolean {
  return Boolean(
    (data.debug_trace?.events && data.debug_trace.events.length > 0) ||
      (data.tools_used && data.tools_used.length > 0),
  );
}
