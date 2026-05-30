"""Scheduled Airflow DAGs for SSI market intraday refresh and EOD finalization."""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.exceptions import AirflowSkipException
from airflow.decorators import dag, task

from src.ingestion.market_data.scheduler_config import eod_schedule, intraday_schedule

LOCAL_TZ = pendulum.timezone("Asia/Ho_Chi_Minh")


def build_intraday_dag(dag_id: str, schedule: str | None) -> None:
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
        def check_market_schema() -> dict:
            from src.ingestion.market_data.scheduler_config import ensure_market_schema_job

            return ensure_market_schema_job()

        @task
        def refresh_intraday_data() -> dict:
            from src.ingestion.market_data.scheduler_config import refresh_intraday_job, within_intraday_window

            if not within_intraday_window():
                raise AirflowSkipException("Outside configured SSI intraday market window.")
            return refresh_intraday_job()

        @task
        def update_market_views() -> dict:
            from src.ingestion.market_data.scheduler_config import ensure_market_schema_job

            return ensure_market_schema_job()

        @task
        def validate_latest_data() -> dict:
            from src.ingestion.market_data.scheduler_config import validate_latest_market_data_job

            return validate_latest_market_data_job("HPG")

        check_market_schema() >> refresh_intraday_data() >> update_market_views() >> validate_latest_data()

    _dag()


@dag(
    dag_id="ssi_intraday_session_close",
    schedule=eod_schedule(),
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
    def check_market_schema() -> dict:
        from src.ingestion.market_data.scheduler_config import ensure_market_schema_job

        return ensure_market_schema_job()

    @task
    def finalize_eod_data() -> dict:
        from src.ingestion.market_data.scheduler_config import finalize_eod_job

        return finalize_eod_job()

    @task
    def update_market_views() -> dict:
        from src.ingestion.market_data.scheduler_config import ensure_market_schema_job

        return ensure_market_schema_job()

    @task
    def validate_latest_data() -> dict:
        from src.ingestion.market_data.scheduler_config import validate_latest_market_data_job

        return validate_latest_market_data_job("HPG")

    check_market_schema() >> finalize_eod_data() >> update_market_views() >> validate_latest_data()


build_intraday_dag("ssi_intraday_session_main", intraday_schedule())
ssi_intraday_session_close()
