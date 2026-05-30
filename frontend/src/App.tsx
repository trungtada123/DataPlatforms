import { useState } from "react";
import { Header } from "./components/Header";
import { ErrorBox } from "./components/ErrorBox";
import { LoadingState } from "./components/LoadingState";
import { QueryForm } from "./components/QueryForm";
import { ResultPanel } from "./components/ResultPanel";
import {
  API_BASE_URL,
  formatFetchError,
  makeInitialState,
  QUERY_CLIENT_TIMEOUT_MS,
  readJsonResponse,
  type QueryResponse,
  type RequestState,
} from "./types";

export function App() {
  const [query, setQuery] = useState("Giá cổ phiếu HPG trong 30 ngày gần đây?");
  const [debug, setDebug] = useState(true);
  const [queryState, setQueryState] = useState<RequestState<QueryResponse>>(makeInitialState);

  async function submitQuery(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQueryState({ loading: true, data: null, error: null });
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), QUERY_CLIENT_TIMEOUT_MS);
    try {
      const response = await fetch(`${API_BASE_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
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
        error: formatFetchError(error),
      });
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  return (
    <div className="app">
      <Header />
      <main className="main">
        <div className="stack">
          <QueryForm
            query={query}
            debug={debug}
            loading={queryState.loading}
            onQueryChange={setQuery}
            onDebugChange={setDebug}
            onSubmit={submitQuery}
          />

          {queryState.loading ? <LoadingState /> : null}

          {queryState.error ? <ErrorBox message={queryState.error} /> : null}

          {queryState.data && !queryState.loading ? <ResultPanel data={queryState.data} /> : null}
        </div>
      </main>
    </div>
  );
}
