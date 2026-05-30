import type { QueryResponse, ToolExecutionResult } from "./types";

export type TableColumn = {
  key: string;
  label: string;
  kind?: "text" | "link";
};

export type ToolDataTable = {
  id: string;
  toolName: string;
  toolLabel: string;
  title: string;
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  hint?: string;
};

const TOOL_LABELS: Record<string, string> = {
  market: "Thị trường (SSI / SQL)",
  news: "Tin tức",
  financial_reports: "Báo cáo tài chính (BCTC)",
  financial: "Báo cáo tài chính (BCTC)",
};

function toolLabel(toolName: string | undefined): string {
  if (!toolName) return "Công cụ";
  return TOOL_LABELS[toolName] ?? toolName;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asRecordList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asRecord(item)).filter((item): item is Record<string, unknown> => item !== null);
}

function truncate(value: unknown, max = 140): string {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function pickColumns(rows: Record<string, unknown>[], preferred: string[]): TableColumn[] {
  const keys = new Set<string>();
  for (const key of preferred) keys.add(key);
  for (const row of rows) {
    for (const key of Object.keys(row)) keys.add(key);
  }
  const labels: Record<string, string> = {
    ticker: "Mã CK",
    symbol: "Mã CK",
    trade_date: "Phiên",
    date: "Ngày",
    close_price: "Giá đóng cửa",
    last_price: "Giá",
    price: "Giá",
    open_price: "Giá mở cửa",
    high_price: "Giá cao",
    low_price: "Giá thấp",
    volume: "Khối lượng",
    value: "Giá trị",
    change_pct: "% thay đổi",
    title: "Tiêu đề",
    site: "Nguồn",
    url: "Link",
    published_at: "Ngày đăng",
    summary: "Tóm tắt",
    article_id: "ID bài",
    retrieval_id: "Retrieval ID",
    page: "Trang",
    chunk_type: "Loại chunk",
    qdrant_score: "Điểm Qdrant",
    rerank_score: "Điểm rerank",
    section_title: "Mục",
    preview: "Nội dung rút gọn",
    why: "Lý do chọn",
  };
  const ordered = [...preferred.filter((k) => keys.has(k)), ...[...keys].filter((k) => !preferred.includes(k))];
  return ordered.map((key) => ({
    key,
    label: labels[key] ?? key,
    kind: key === "url" ? "link" : "text",
  }));
}

function marketTable(result: ToolExecutionResult): ToolDataTable | null {
  const rows = asRecordList(result.structured_data?.rows);
  if (!rows.length) return null;
  const preferred = [
    "ticker",
    "symbol",
    "trade_date",
    "date",
    "close_price",
    "last_price",
    "price",
    "open_price",
    "high_price",
    "low_price",
    "volume",
    "change_pct",
  ];
  return {
    id: `${result.tool_name}-rows`,
    toolName: result.tool_name ?? "market",
    toolLabel: toolLabel(result.tool_name),
    title: "Kết quả truy vấn SQL (bảng)",
    columns: pickColumns(rows, preferred),
    rows,
    hint: result.structured_data?.row_count
      ? `Tổng ${result.structured_data.row_count} dòng (hiển thị tối đa ${rows.length}).`
      : undefined,
  };
}

function newsTable(result: ToolExecutionResult): ToolDataTable | null {
  const structured = result.structured_data ?? {};
  const summaries = asRecordList(
    structured.article_summaries ?? structured.selected_article_summaries,
  );
  if (!summaries.length) {
    const fromEvidence = (result.evidence ?? [])
      .filter((item) => item.kind === "article" || item.kind === "news_articles_preview")
      .flatMap((item) => (Array.isArray(item.value) ? item.value : [item.value]));
    const articles = asRecordList(fromEvidence);
    if (!articles.length) return null;
    const rows = articles.map((article, index) => ({
      stt: index + 1,
      title: article.title,
      site: article.site,
      published_at: article.published_at ?? article.published_date,
      summary: truncate(article.summary ?? article.article_summary, 200),
      url: article.url,
    }));
    return {
      id: `${result.tool_name}-articles`,
      toolName: result.tool_name ?? "news",
      toolLabel: toolLabel(result.tool_name),
      title: "Danh sách tin đã crawl",
      columns: pickColumns(rows, ["stt", "title", "site", "published_at", "summary", "url"]),
      rows,
    };
  }

  const rows = summaries.map((article, index) => ({
    stt: index + 1,
    title: article.title,
    site: article.site,
    published_at: article.published_at ?? article.published_date,
    summary: truncate(article.summary, 200),
    url: article.url,
  }));

  return {
    id: `${result.tool_name}-summaries`,
    toolName: result.tool_name ?? "news",
    toolLabel: toolLabel(result.tool_name),
    title: "Danh sách tin tức",
    columns: pickColumns(rows, ["stt", "title", "site", "published_at", "summary", "url"]),
    rows,
    hint:
      typeof structured.article_count === "number"
        ? `Tổng ${structured.article_count} bài trong pipeline.`
        : undefined,
  };
}

function keyValueTable(
  id: string,
  toolName: string,
  title: string,
  payload: Record<string, unknown> | null,
): ToolDataTable | null {
  if (!payload || !Object.keys(payload).length) return null;
  const rows = Object.entries(payload).map(([key, value]) => ({
    field: key,
    value: Array.isArray(value) ? value.join(", ") : String(value ?? "—"),
  }));
  return {
    id,
    toolName,
    toolLabel: toolLabel(toolName),
    title,
    columns: [
      { key: "field", label: "Trường" },
      { key: "value", label: "Giá trị" },
    ],
    rows,
  };
}

function financialTables(result: ToolExecutionResult): ToolDataTable[] {
  const structured = result.structured_data ?? {};
  const tables: ToolDataTable[] = [];

  const filters = asRecord(structured.filters);
  const filterTable = keyValueTable(
    `${result.tool_name}-filters`,
    result.tool_name ?? "financial_reports",
    "Bộ lọc truy vấn BCTC",
    filters,
  );
  if (filterTable) tables.push(filterTable);

  const hits = asRecordList(structured.top_hits);
  if (hits.length) {
    const rows = hits.map((hit, index) => ({
      stt: index + 1,
      retrieval_id: hit.retrieval_id,
      page: hit.page,
      chunk_type: hit.chunk_type,
      section_title: hit.section_title,
      qdrant_score: hit.qdrant_score,
      rerank_score: hit.rerank_score,
      why: Array.isArray(hit.why) ? (hit.why as string[]).slice(0, 2).join(" · ") : hit.why,
      preview: truncate(hit.preview, 160),
    }));
    tables.push({
      id: `${result.tool_name}-hits`,
      toolName: result.tool_name ?? "financial_reports",
      toolLabel: toolLabel(result.tool_name),
      title: "Top hits retrieval (Qdrant)",
      columns: pickColumns(rows, [
        "stt",
        "retrieval_id",
        "page",
        "chunk_type",
        "section_title",
        "rerank_score",
        "qdrant_score",
        "preview",
      ]),
      rows,
    });
  }

  const contexts = asRecordList(structured.selected_contexts);
  if (contexts.length) {
    const rows = contexts.map((ctx, index) => ({
      stt: index + 1,
      retrieval_id: ctx.retrieval_id,
      page: ctx.page,
      chunk_type: ctx.chunk_type,
      section_title: ctx.section_title ?? ctx.section_subtitle,
      preview: truncate(ctx.preview, 180),
    }));
    tables.push({
      id: `${result.tool_name}-contexts`,
      toolName: result.tool_name ?? "financial_reports",
      toolLabel: toolLabel(result.tool_name),
      title: "Context đã chọn cho câu trả lời",
      columns: pickColumns(rows, ["stt", "retrieval_id", "page", "chunk_type", "section_title", "preview"]),
      rows,
    });
  }

  const queries = structured.retrieval_queries;
  if (Array.isArray(queries) && queries.length) {
    const rows = queries.map((query, index) => ({ stt: index + 1, query: String(query) }));
    tables.push({
      id: `${result.tool_name}-queries`,
      toolName: result.tool_name ?? "financial_reports",
      toolLabel: toolLabel(result.tool_name),
      title: "Truy vấn retrieval",
      columns: [
        { key: "stt", label: "STT" },
        { key: "query", label: "Câu truy vấn" },
      ],
      rows,
    });
  }

  return tables;
}

function tablesForResult(result: ToolExecutionResult): ToolDataTable[] {
  const name = (result.tool_name ?? "").toLowerCase();
  if (name === "market") {
    const table = marketTable(result);
    return table ? [table] : [];
  }
  if (name === "news") {
    const table = newsTable(result);
    return table ? [table] : [];
  }
  if (name === "financial_reports" || name === "financial") {
    return financialTables(result);
  }
  return [];
}

export function extractToolDataTables(data: QueryResponse): ToolDataTable[] {
  const tables: ToolDataTable[] = [];
  for (const result of data.results ?? []) {
    tables.push(...tablesForResult(result));
  }
  return tables;
}
