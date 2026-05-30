import { useState } from "react";
import type { SqlSnippet } from "../types";

type SqlBlockProps = {
  snippets: SqlSnippet[];
};

export function SqlBlock({ snippets }: SqlBlockProps) {
  if (!snippets.length) {
    return (
      <section className="sql-section">
        <h3 className="section-label">Câu lệnh SQL được tạo</h3>
        <p className="muted sql-empty">
          Không có câu SQL trong phản hồi (có thể dùng công cụ khác market hoặc không sinh SQL).
        </p>
      </section>
    );
  }

  return (
    <section className="sql-section">
      <h3 className="section-label">Câu lệnh SQL được tạo</h3>
      <p className="muted sql-hint">Sao chép sang Adminer hoặc psql để đối chiếu kết quả.</p>
      <div className="sql-list">
        {snippets.map((snippet, index) => (
          <SqlCard key={`${snippet.source}-${index}`} snippet={snippet} index={index} />
        ))}
      </div>
    </section>
  );
}

function SqlCard({ snippet, index }: { snippet: SqlSnippet; index: number }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(snippet.sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <article className="sql-card">
      <div className="sql-card-header">
        <span className="sql-card-label">
          SQL · {snippet.source}
        </span>
        <button type="button" className="btn-ghost" onClick={handleCopy}>
          {copied ? "Đã sao chép ✓" : "Sao chép"}
        </button>
      </div>
      <pre className="sql-code">{snippet.sql}</pre>
      {snippet.rowCount !== undefined ? (
        <p className="sql-meta">Dòng dữ liệu: {snippet.rowCount}</p>
      ) : null}
      {snippet.reasoning ? <p className="sql-reasoning">{snippet.reasoning}</p> : null}
    </article>
  );
}
