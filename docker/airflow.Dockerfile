FROM apache/airflow:2.10.4-python3.11

ENV PYTHONPATH=/opt/airflow/backend:/opt/airflow/backend/src:/opt/airflow/src

USER airflow
COPY docker/airflow-requirements.txt /tmp/airflow-requirements.txt
RUN pip install --no-cache-dir -r /tmp/airflow-requirements.txt

USER airflow
