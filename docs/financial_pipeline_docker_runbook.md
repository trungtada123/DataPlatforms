# Financial Pipeline Docker Runbook (Handoff)

Mục tiêu: tài liệu ngắn để chạy phần Financial ETL/RAG bằng Docker, phục vụ demo và ghép với phần code khác.

## 1) Điều kiện trước khi chạy

- Đang đứng tại repo root:
  - `D:\AI_Stock\DataPlatforms-test`
- Có file `.env` hợp lệ (không commit secret).
- Tối thiểu cần các biến:
  - `FINANCIAL_REPORTS_QDRANT_URL=http://qdrant:6333`
  - `FINANCIAL_REPORTS_QDRANT_COLLECTION=bctc_chunks`
  - `FINANCIAL_REPORTS_EMBEDDING_MODEL=BAAI/bge-m3`
  - `MINIO_ENDPOINT=minio:9000`
  - `MINIO_ACCESS_KEY=...`
  - `MINIO_SECRET_KEY=...`
  - `POSTGRES_HOST=postgres`
  - `POSTGRES_DB=ssi_market`
  - `POSTGRES_USER=stock_user`
  - `POSTGRES_PASSWORD=stock_pass`
  - `RABBITMQ_HOST=rabbitmq`
  - `VISION_AGENT_API_KEY=...` (nếu chạy parse qua LandingAI)

## 2) Khởi động stack Docker

Chạy từ PowerShell tại repo root:

```powershell
docker compose up -d postgres rabbitmq minio qdrant backend
docker compose up -d financial-download-worker financial-parse-worker financial-chunk-worker financial-embedding-worker
docker compose --profile airflow up -d airflow-webserver airflow-scheduler
```

Kiểm tra trạng thái:

```powershell
docker compose ps
```

## 3) Các service cần thấy

- `ssi-postgres`
- `ssi-rabbitmq`
- `ssi-minio`
- `ssi-qdrant`
- `ssi-backend`
- `ssi-financial-download-worker`
- `ssi-financial-parse-worker`
- `ssi-financial-chunk-worker`
- `ssi-financial-embedding-worker`
- `ssi-airflow-webserver`
- `ssi-airflow-scheduler`

## 4) Trigger pipeline từ Airflow (MVP)

```powershell
docker exec ssi-airflow-webserver airflow dags trigger financial_ingest_publish_queue
```

Xem queue:

```powershell
docker exec ssi-rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged
```

Xem log worker:

```powershell
docker logs --tail 200 ssi-financial-download-worker
docker logs --tail 200 ssi-financial-parse-worker
docker logs --tail 200 ssi-financial-chunk-worker
docker logs --tail 200 ssi-financial-embedding-worker
```

## 5) Kiểm tra trạng thái document trong PostgreSQL

```powershell
docker exec ssi-postgres psql -U stock_user -d ssi_market -c "select doc_id,status,error_message,updated_at from financial_report_documents order by updated_at desc limit 20;"
```

Luồng kỳ vọng:

- `DISCOVERED -> DOWNLOADED -> PARSED -> CHUNKED -> EMBEDDED`

## 6) Test query nhanh để verify retrieval

```powershell
docker exec -i ssi-backend sh -lc "python - <<'PY'
from agents.financial_agent.service import FinancialReportsQueryService
svc = FinancialReportsQueryService()
queries = [
  'Lợi nhuận sau thuế quý 2/2025 của ACB là bao nhiêu?',
  'Tổng tài sản ACB tại 30/06/2025 và 31/12/2024 là bao nhiêu?',
  'ACB quý 2/2025 EBITDA là bao nhiêu? Nếu không có thì không được suy diễn.',
]
for q in queries:
    r = svc.ask(q).model_dump()
    print('\\nQ:', q)
    print('status:', r['status'])
    print('summary:', (r.get('summary') or '')[:300])
    hits = r.get('hits') or []
    print('hits:', len(hits))
    if hits:
        print('top1 chunk_type:', hits[0].get('chunk_type'))
        print('top1 preview:', (hits[0].get('preview') or '')[:220])
PY"
```

## 7) Ghi chú ghép với nhánh khác

- Nếu chuyển branch (ví dụ `test1` -> `my`), Docker containers vẫn còn trong Docker Desktop.
- Nhưng khi code/`docker-compose.yml` đổi, nên chạy lại:

```powershell
docker compose down --remove-orphans
docker compose up -d --build
```

- Nếu chỉ đổi code Python được mount vào container, thường chỉ cần restart service liên quan:

```powershell
docker compose restart backend financial-download-worker financial-parse-worker financial-chunk-worker financial-embedding-worker
```

## 8) Troubleshooting ngắn

- `status` đứng ở `CHUNKED` lâu:
  - kiểm tra `ssi-financial-embedding-worker` log.
  - kiểm tra `financial_embedding_jobs` queue có `unacknowledged` không.
- Airflow webserver bị kill/OOM:
  - giảm tải service khác hoặc tăng RAM Docker Desktop.
- Query `no_data` dù có vector:
  - kiểm tra filter ticker/year/quarter có quá chặt không.
  - kiểm tra payload chunk có `ticker/year/chunk_type/content_for_embedding`.
