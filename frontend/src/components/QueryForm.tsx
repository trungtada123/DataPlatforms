type QueryFormProps = {
  query: string;
  debug: boolean;
  loading: boolean;
  onQueryChange: (value: string) => void;
  onDebugChange: (checked: boolean) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
};

export function QueryForm({
  query,
  debug,
  loading,
  onQueryChange,
  onDebugChange,
  onSubmit,
}: QueryFormProps) {
  return (
    <section className="card query-card">
      <div className="card-header">
        <h2 className="card-title">Đặt câu hỏi</h2>
        <span className="pill pill-muted">POST /query</span>
      </div>
      <hr className="divider" />
      <form className="query-form" onSubmit={onSubmit}>
        <label className="query-label" htmlFor="question">
          Câu hỏi của bạn
        </label>
        <textarea
          id="question"
          className="query-textarea"
          value={query}
          minLength={3}
          rows={5}
          required
          disabled={loading}
          placeholder="Ví dụ: Giá cổ phiếu HPG trong 30 ngày gần đây?"
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <label className="query-checkbox">
          <input
            type="checkbox"
            checked={debug}
            disabled={loading}
            onChange={(event) => onDebugChange(event.target.checked)}
          />
          <span>Bật debug trace</span>
        </label>
        <div className="query-form-actions">
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? (
              <>
                <span className="spinner" aria-hidden="true" />
                Đang xử lý…
              </>
            ) : (
              <>Gửi câu hỏi →</>
            )}
          </button>
        </div>
      </form>
    </section>
  );
}
