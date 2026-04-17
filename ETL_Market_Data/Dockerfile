FROM apache/airflow:2.10.4-python3.11

ENV PYTHONPATH=/opt/airflow/src
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

USER root
RUN python -m playwright install --with-deps chromium \
    && chmod -R 755 /ms-playwright

USER airflow
