import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type RequestState<T> = {
  loading: boolean;
  data: T | null;
  error: string | null;
};

type QueryResponse = {
  trace_id?: string;
  status?: string;
  original_query?: string;
  normalized_query?: string;
  answer?: string;
  tools_used?: string[];
  limitations?: string[];
  debug_trace?: unknown;
  results?: unknown;
  [key: string]: unknown;
};

function makeInitialState<T>(): RequestState<T> {
  return { loading: false, data: null, error: null };
}

async function readJsonResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail ?? response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload as T;
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

function StatusCard({
  title,
  state,
  onCheck,
}: {
  title: string;
  state: RequestState<unknown>;
  onCheck: () => void;
}) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>{title}</h2>
        <button type="button" onClick={onCheck} disabled={state.loading}>
          {state.loading ? "Checking" : "Run"}
        </button>
      </div>
      {state.error ? <p className="error">{state.error}</p> : null}
      {state.data ? <JsonBlock value={state.data} /> : <p className="muted">No response yet.</p>}
    </section>
  );
}

function App() {
  const [health, setHealth] = useState<RequestState<unknown>>(makeInitialState);
  const [ready, setReady] = useState<RequestState<unknown>>(makeInitialState);
  const [query, setQuery] = useState("Gia cua HPG gan day the nao?");
  const [debug, setDebug] = useState(true);
  const [queryState, setQueryState] = useState<RequestState<QueryResponse>>(makeInitialState);

  async function callEndpoint<T>(path: string, setState: (state: RequestState<T>) => void) {
    setState({ loading: true, data: null, error: null });
    try {
      const response = await fetch(`${API_BASE_URL}${path}`);
      const data = await readJsonResponse<T>(response);
      setState({ loading: false, data, error: null });
    } catch (error) {
      setState({ loading: false, data: null, error: error instanceof Error ? error.message : String(error) });
    }
  }

  async function submitQuery(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQueryState({ loading: true, data: null, error: null });
    try {
      const response = await fetch(`${API_BASE_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: query,
          debug,
          metadata: { source: "frontend-demo" },
        }),
      });
      const data = await readJsonResponse<QueryResponse>(response);
      setQueryState({ loading: false, data, error: null });
    } catch (error) {
      setQueryState({
        loading: false,
        data: null,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>DataPlatforms Demo</h1>
          <p>FastAPI backend: {API_BASE_URL}</p>
        </div>
      </header>

      <div className="grid">
        <StatusCard title="Health Check" state={health} onCheck={() => callEndpoint("/health", setHealth)} />
        <StatusCard title="Readiness Check" state={ready} onCheck={() => callEndpoint("/ready", setReady)} />
      </div>

      <section className="panel">
        <div className="panelHeader">
          <h2>Query</h2>
          <span className="badge">POST /query</span>
        </div>
        <form onSubmit={submitQuery} className="queryForm">
          <label htmlFor="question">Question</label>
          <textarea
            id="question"
            value={query}
            minLength={3}
            onChange={(event) => setQuery(event.target.value)}
            rows={4}
            required
          />
          <label className="checkbox">
            <input type="checkbox" checked={debug} onChange={(event) => setDebug(event.target.checked)} />
            Include debug trace
          </label>
          <button type="submit" disabled={queryState.loading}>
            {queryState.loading ? "Querying" : "Send query"}
          </button>
        </form>

        {queryState.error ? <p className="error">{queryState.error}</p> : null}
        {queryState.data ? (
          <div className="result">
            <h3>Answer</h3>
            <p className="answer">{queryState.data.answer ?? "No answer returned."}</p>

            <div className="metaGrid">
              <div>
                <span>Trace ID</span>
                <strong>{queryState.data.trace_id ?? "n/a"}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>{queryState.data.status ?? "n/a"}</strong>
              </div>
              <div>
                <span>Tools</span>
                <strong>{queryState.data.tools_used?.join(", ") || "n/a"}</strong>
              </div>
            </div>

            {queryState.data.limitations?.length ? (
              <>
                <h3>Limitations</h3>
                <ul>
                  {queryState.data.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </>
            ) : null}

            {queryState.data.debug_trace || queryState.data.results ? (
              <>
                <h3>Debug / Trace</h3>
                <JsonBlock value={{ debug_trace: queryState.data.debug_trace, results: queryState.data.results }} />
              </>
            ) : null}

            <details>
              <summary>Raw response</summary>
              <JsonBlock value={queryState.data} />
            </details>
          </div>
        ) : null}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
