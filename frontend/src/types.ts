export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

/** Thời gian chờ tối đa phía trình duyệt khi gọi POST /query. */
export const QUERY_CLIENT_TIMEOUT_MS = 300_000;

export function clientTimeoutSeconds(): number {
  return Math.round(QUERY_CLIENT_TIMEOUT_MS / 1000);
}

export type RequestState<T> = {
  loading: boolean;
  data: T | null;
  error: string | null;
};

export type ToolExecutionResult = {
  tool_name?: string;
  status?: string;
  query_used?: string;
  summary?: string;
  structured_data?: {
    sql?: string;
    row_count?: number;
    rows?: Record<string, unknown>[];
    reasoning?: string;
    /** news */
    article_summaries?: Record<string, unknown>[];
    selected_article_summaries?: Record<string, unknown>[];
    article_count?: number;
    /** financial_reports */
    filters?: Record<string, unknown>;
    top_hits?: Record<string, unknown>[];
    selected_contexts?: Record<string, unknown>[];
    retrieval_queries?: string[];
  };
  evidence?: Array<{ kind?: string; value?: unknown }>;
  raw_response?: { sql?: string; reasoning?: string };
  error_message?: string | null;
  limitations?: string[];
};

export type IntentPlan = {
  original_query?: string;
  normalized_query?: string;
  tools_to_use?: string[];
  tool_queries?: Record<string, string>;
  entities?: Record<string, unknown>;
  time_constraints?: Record<string, unknown>;
  analysis_requirements?: Record<string, unknown>;
  reasoning_brief?: string;
  primary_intent?: string;
  classifier_mode?: string;
  confidence?: number;
};

export type DebugTrace = {
  trace_id?: string;
  requested_tools?: string[];
  chosen_tools?: string[];
  unsupported_tools?: string[];
  fallback_reason?: string | null;
  generated_sql?: string | null;
  latency_ms?: number | null;
  events?: Array<{
    step?: string;
    status?: string;
    detail?: string | null;
    duration_ms?: number | null;
    metadata?: Record<string, unknown>;
  }>;
  metadata?: Record<string, unknown>;
};

export type MergedContext = {
  user_query?: string;
  normalized_query?: string;
  intent_plan?: Record<string, unknown>;
  normalized_entities?: Record<string, unknown>;
  tool_summaries?: Record<string, unknown>[];
  key_evidence?: Record<string, unknown>[];
  limitations?: string[];
  answer_style?: string;
};

export type QueryResponse = {
  trace_id?: string;
  status?: string;
  original_query?: string;
  normalized_query?: string;
  answer?: string;
  tools_used?: string[];
  limitations?: string[];
  merged_context?: MergedContext | null;
  debug_trace?: DebugTrace | null;
  intent_plan?: IntentPlan;
  results?: ToolExecutionResult[];
};

export type SqlSnippet = {
  source: string;
  sql: string;
  rowCount?: number;
  reasoning?: string;
};

export function makeInitialState<T>(): RequestState<T> {
  return { loading: false, data: null, error: null };
}

export function formatFetchError(error: unknown): string {
  if (error instanceof DOMException && error.name === "AbortError") {
    return `Hết thời gian chờ phản hồi (quá ${clientTimeoutSeconds()} giây). Thử lại hoặc bật ít công cụ hơn.`;
  }
  if (error instanceof TypeError && /fetch/i.test(error.message)) {
    const hint =
      API_BASE_URL === "/api" || API_BASE_URL.endsWith("/api")
        ? "Kiểm tra container backend và proxy nginx /api (http://localhost:5173/api/health)."
        : `Kiểm tra backend tại ${API_BASE_URL} và CORS (nên dùng VITE_API_BASE_URL=/api).`;
    return `Không kết nối được API (${API_BASE_URL}). ${hint}`;
  }
  return error instanceof Error ? error.message : String(error);
}

export async function readJsonResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail ?? response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload as T;
}

export function extractSqlSnippets(data: QueryResponse): SqlSnippet[] {
  const seen = new Set<string>();
  const snippets: SqlSnippet[] = [];

  const push = (source: string, sql: unknown, extras?: Partial<SqlSnippet>) => {
    if (typeof sql !== "string") return;
    const normalized = sql.trim();
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    snippets.push({ source, sql: normalized, ...extras });
  };

  push("debug_trace.generated_sql", data.debug_trace?.generated_sql);

  for (const result of data.results ?? []) {
    const tool = result.tool_name ?? "tool";
    push(`${tool} · structured_data`, result.structured_data?.sql, {
      rowCount: result.structured_data?.row_count,
      reasoning: result.structured_data?.reasoning,
    });
    push(`${tool} · raw_response`, result.raw_response?.sql, {
      reasoning: result.raw_response?.reasoning,
    });
    for (const item of result.evidence ?? []) {
      if (item.kind === "sql") {
        push(`${tool} · evidence`, item.value);
      }
    }
  }

  return snippets;
}

export function formatStatusLabel(status: string | undefined): string {
  if (!status) return "Không rõ";
  const map: Record<string, string> = {
    success: "Thành công",
    partial_success: "Thành công một phần",
    no_data: "Không có dữ liệu",
    no_route: "Không định tuyến",
    error: "Lỗi",
    not_supported_yet: "Chưa hỗ trợ",
    partial_no_data: "Thiếu dữ liệu một phần",
  };
  return map[status] ?? status;
}

export function statusTone(status: string | undefined): "success" | "error" | "neutral" {
  if (!status) return "neutral";
  if (status === "success") return "success";
  if (status === "error" || status === "no_route") return "error";
  if (status.includes("success")) return "success";
  if (status.includes("error") || status.includes("no_data")) return "neutral";
  return "neutral";
}
