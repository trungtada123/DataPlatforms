"""Scheduled Airflow DAGs for intraday refresh and end-of-day finalization."""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.decorators import dag, task


LOCAL_TZ = pendulum.timezone("Asia/Ho_Chi_Minh")


def build_intraday_dag(dag_id: str, schedule: str) -> None:
    """Factory that builds a small scheduled DAG for the intraday refresh job."""

    @dag(
        dag_id=dag_id,
        schedule=schedule,
        start_date=pendulum.datetime(2026, 4, 14, tz=LOCAL_TZ),
        catchup=False,
        max_active_runs=1,
        default_args={
            "retries": 2,
            "retry_delay": timedelta(minutes=2),
            "execution_timeout": timedelta(minutes=20),
        },
        tags=["ssi", "intraday"],
    )
    def _dag() -> None:
        @task
        def run_refresh() -> dict:
            from ingestion.market_data import refresh_intraday

            return refresh_intraday()

        run_refresh()

    _dag()


@dag(
    dag_id="ssi_intraday_session_close",
    schedule="10 15 * * 1-5",
    start_date=pendulum.datetime(2026, 4, 14, tz=LOCAL_TZ),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "execution_timeout": timedelta(minutes=45),
    },
    tags=["ssi", "intraday", "eod"],
)
def ssi_intraday_session_close() -> None:
    """Finalize daily raw rows and recompute features after the trading session ends."""

    @task
    def run_finalize() -> dict:
        from ingestion.market_data import finalize_eod

        return finalize_eod()

    run_finalize()


build_intraday_dag("ssi_intraday_session_main", "*/2 9-14 * * 1-5")
ssi_intraday_session_close()
