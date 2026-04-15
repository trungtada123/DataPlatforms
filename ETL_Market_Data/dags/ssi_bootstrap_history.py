"""Manual Airflow DAG for the initial SSI history load."""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task


LOCAL_TZ = pendulum.timezone("Asia/Ho_Chi_Minh")


@dag(
    dag_id="ssi_bootstrap_history",
    schedule=None,
    start_date=pendulum.datetime(2026, 4, 14, tz=LOCAL_TZ),
    catchup=False,
    tags=["ssi", "bootstrap"],
)
def ssi_bootstrap_history() -> None:
    """Bootstrap the initial historical data set into Postgres."""

    @task
    def run_bootstrap() -> dict:
        from stock_etl.pipeline import bootstrap_history

        return bootstrap_history()

    run_bootstrap()


ssi_bootstrap_history()
