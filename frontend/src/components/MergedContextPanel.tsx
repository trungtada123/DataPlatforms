import {
  answerStyleLabel,
  asRecordList,
  asStringList,
  toolLabel,
  truncateText,
} from "../mergedContext";
import type { MergedContext } from "../types";
import { formatStatusLabel } from "../types";

type MergedContextPanelProps = {
  context: MergedContext;
};

export function MergedContextPanel({ context }: MergedContextPanelProps) {
  const entities = context.normalized_entities ?? {};
  const tickers = asStringList(entities.tickers);
  const companies = asStringList(entities.company_names);
  const newsSites = asStringList(entities.news_sites);
  const toolsDetected = asStringList(entities.tools_detected);
  const summaries = asRecordList(context.tool_summaries);
  const evidence = asRecordList(context.key_evidence);
  const limitations = context.limitations ?? [];

  return (
    <section className="merge-context-section" aria-label="Context merge">
      <h3 className="section-label">Context merge (gộp nhánh)</h3>
      <p className="muted merge-context-hint">
        Payload sau bước merger — dùng làm đầu vào cho synthesizer và ghi báo cáo pipeline.
      </p>

      <div className="merge-context-meta">
        <MetaItem label="Câu hỏi gốc" value={context.user_query} />
        <MetaItem label="Truy vấn chuẩn hóa" value={context.normalized_query} />
        <MetaItem label="Phong cách trả lời" value={answerStyleLabel(context.answer_style)} />
      </div>

      {(tickers.length > 0 || companies.length > 0 || newsSites.length > 0 || toolsDetected.length > 0) && (
        <div className="merge-entities-block">
          <span className="intent-kw-label">Thực thể đã chuẩn hóa</span>
          <div className="merge-entities-grid">
            {tickers.length > 0 ? <ChipGroup label="Mã CK" items={tickers} /> : null}
            {companies.length > 0 ? <ChipGroup label="Công ty" items={companies} /> : null}
            {newsSites.length > 0 ? <ChipGroup label="Nguồn tin" items={newsSites} /> : null}
            {toolsDetected.length > 0 ? (
              <ChipGroup label="Nhánh đã chạy" items={toolsDetected.map((t) => toolLabel(t))} />
            ) : null}
          </div>
        </div>
      )}

      {summaries.length > 0 ? (
        <div className="merge-summaries-block">
          <span className="intent-kw-label">Tóm tắt theo công cụ</span>
          <div className="merge-summaries-list">
            {summaries.map((summary, index) => (
              <ToolSummaryCard key={`${String(summary.tool_name)}-${index}`} summary={summary} />
            ))}
          </div>
        </div>
      ) : null}

      {evidence.length > 0 ? (
        <article className="data-table-card merge-evidence-card">
          <header className="data-table-card-header">
            <h4 className="data-table-title">Evidence chính (đã dedupe)</h4>
            <p className="data-table-hint">Tối đa 10 mục — dùng làm căn cứ trích dẫn trong báo cáo.</p>
          </header>
          <div className="data-table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>STT</th>
                  <th>Nhánh</th>
                  <th>Loại</th>
                  <th>Nhãn</th>
                  <th>Tham chiếu</th>
                </tr>
              </thead>
              <tbody>
                {evidence.map((item, index) => (
                  <tr key={`ev-${index}`}>
                    <td>{index + 1}</td>
                    <td>{toolLabel(String(item.tool_name ?? ""))}</td>
                    <td>{String(item.kind ?? "—")}</td>
                    <td>{truncateText(item.label, 120)}</td>
                    <td>{truncateText(item.source_ref, 100)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}

      {limitations.length > 0 ? (
        <div className="merge-limitations-block">
          <span className="intent-kw-label">Hạn chế từ merge</span>
          <ul className="merge-limitations-list">
            {limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function MetaItem({ label, value }: { label: string; value?: string }) {
  return (
    <div className="merge-meta-item">
      <span className="merge-meta-label">{label}</span>
      <span className="merge-meta-value">{value?.trim() || "—"}</span>
    </div>
  );
}

function ChipGroup({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="merge-chip-group">
      <span className="merge-chip-group-label">{label}</span>
      <div className="intent-tag-row">
        {items.map((item) => (
          <span key={`${label}-${item}`} className="intent-chip intent-chip-tool">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function ToolSummaryCard({ summary }: { summary: Record<string, unknown> }) {
  const toolName = String(summary.tool_name ?? "");
  const status = formatStatusLabel(String(summary.status ?? ""));
  const highlights = Array.isArray(summary.highlights)
    ? summary.highlights.map((h) => String(h ?? "").trim()).filter(Boolean)
    : [];
  const articles = asRecordList(summary.structured_articles);
  const reportContexts = asRecordList(summary.report_contexts);
  const toolLimitations = Array.isArray(summary.limitations)
    ? summary.limitations.map((l) => String(l ?? "").trim()).filter(Boolean)
    : [];

  return (
    <article className="merge-tool-card">
      <header className="merge-tool-card-head">
        <span className="merge-tool-name">{toolLabel(toolName)}</span>
        <span className="merge-tool-status">{status}</span>
      </header>
      {summary.query_used ? (
        <p className="merge-tool-query">
          <span className="intent-kw-label">Truy vấn nhánh</span>
          <span className="intent-kw-value">{String(summary.query_used)}</span>
        </p>
      ) : null}
      {summary.summary ? <p className="merge-tool-summary">{String(summary.summary)}</p> : null}
      {highlights.length > 0 ? (
        <ul className="merge-highlights">
          {highlights.map((line, index) => (
            <li key={`hl-${index}`}>{line}</li>
          ))}
        </ul>
      ) : null}
      {articles.length > 0 ? <MiniArticlesTable articles={articles} /> : null}
      {reportContexts.length > 0 ? <MiniReportContextsTable contexts={reportContexts} /> : null}
      {summary.error_message ? (
        <p className="merge-tool-error">{String(summary.error_message)}</p>
      ) : null}
      {toolLimitations.length > 0 ? (
        <ul className="merge-tool-limitations">
          {toolLimitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function MiniArticlesTable({ articles }: { articles: Record<string, unknown>[] }) {
  return (
    <div className="merge-mini-table-wrap">
      <span className="merge-mini-table-label">Tin trong merge (tối đa 5)</span>
      <div className="data-table-scroll merge-mini-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Tiêu đề</th>
              <th>Nguồn</th>
              <th>Tóm tắt</th>
            </tr>
          </thead>
          <tbody>
            {articles.map((article, index) => (
              <tr key={`art-${index}`}>
                <td>{truncateText(article.title, 80)}</td>
                <td>{String(article.site ?? "—")}</td>
                <td>{truncateText(article.summary, 140)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MiniReportContextsTable({ contexts }: { contexts: Record<string, unknown>[] }) {
  return (
    <div className="merge-mini-table-wrap">
      <span className="merge-mini-table-label">Context BCTC trong merge</span>
      <div className="data-table-scroll merge-mini-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Trang</th>
              <th>Mục</th>
              <th>Preview</th>
            </tr>
          </thead>
          <tbody>
            {contexts.map((ctx, index) => (
              <tr key={`ctx-${index}`}>
                <td>{String(ctx.retrieval_id ?? "—")}</td>
                <td>{ctx.page != null ? String(ctx.page) : "—"}</td>
                <td>{truncateText(ctx.section_title ?? ctx.section_subtitle, 60)}</td>
                <td>{truncateText(ctx.preview, 120)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
