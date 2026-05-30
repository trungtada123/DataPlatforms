"""Manual Airflow DAG for the initial SSI history load."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.operators.python import get_current_context


LOCAL_TZ = pendulum.timezone("Asia/Ho_Chi_Minh")


@dag(
    dag_id="ssi_bootstrap_history",
    schedule=None,
    start_date=pendulum.datetime(2026, 4, 14, tz=LOCAL_TZ),
    catchup=False,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "execution_timeout": timedelta(hours=2),
    },
    max_active_runs=1,
    tags=["ssi", "bootstrap"],
)
def ssi_bootstrap_history() -> None:
    """Bootstrap recent daily SSI market data into Postgres."""

    @task
    def run_bootstrap() -> dict:
        from src.ingestion.market_data import bootstrap_history
        from src.ingestion.market_data.scheduler_config import bootstrap_recent_history_job

        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = dag_run.conf if dag_run and isinstance(dag_run.conf, dict) else {}

        raw_tickers = str(conf.get("tickers") or os.getenv("SSI_MARKET_TICKERS", "")).strip()
        symbols = [item.strip().upper() for item in raw_tickers.split(",") if item.strip()] or None
        from_date = conf.get("from_date") or conf.get("start_date")
        to_date = conf.get("to_date") or conf.get("end_date")
        if from_date or to_date:
            return bootstrap_history(
                start_date=date.fromisoformat(str(from_date)) if from_date else None,
                end_date=date.fromisoformat(str(to_date)) if to_date else None,
                symbols=symbols,
            )

        days = int(conf.get("days") or os.getenv("SSI_BOOTSTRAP_DAYS", "30"))
        return bootstrap_recent_history_job(days=days, symbols=symbols)

    run_bootstrap()


ssi_bootstrap_history()
