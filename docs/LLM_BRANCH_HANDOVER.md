# LLM Branch Handover

## Current Layout

LLM-backed functionality now lives in canonical backend modules:

- LLM pools: `backend/src/core/llm_pool.py`
- Market NL2SQL: `backend/src/agents/market_agent/nl2sql.py`
- News summarization: `backend/src/agents/news_agent/summarizer.py`
- Financial-report synthesis: `backend/src/agents/financial_agent/synthesis.py`
- Orchestration final synthesis: `backend/src/orchestration/nodes/synthesizer.py`

## Runtime Flow

```text
src.main
  -> src.api.query
  -> src.orchestration.workflow
  -> src.orchestration.nodes
  -> src.agents
```

## Verification

```powershell
$env:PYTHONPATH="backend"
python -m pytest tests
python -c "import src.orchestration.workflow; import src.agents.market_agent.nl2sql; print('ok')"
```

Docker import check:

```powershell
docker compose --env-file .env.docker exec backend python -c "import src.main as main; print(main.app is not None)"
```
