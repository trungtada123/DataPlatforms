# Known Issues

## Security Notice: Previously Tracked Runtime Environment Credentials

- Runtime environment files `.env.local` and `.env.docker` were previously tracked on branch `test`.
- Any credentials that were exposed through those files must be rotated manually (API keys, database credentials, broker/storage credentials, and related secrets).
- Removing these files from current tracking does not invalidate credentials that may have been exposed in prior commits or CI logs.

## Runtime Environment Policy

- Runtime env files must remain local-only and must not be committed:
  - `.env`
  - `.env.local`
  - `.env.docker`
- Safe placeholder templates are tracked for setup guidance:
  - `.env.example`
  - `.env.local.example`
  - `.env.docker.example`

## Monitoring Limitation: Airflow Metrics Scrape

- Prometheus scrape for `airflow-webserver` has been disabled because the prior target used `/health` JSON, which is not Prometheus text format.
- Backend metrics scraping remains enabled via `/metrics`.
- To monitor Airflow in Prometheus, configure a real metrics endpoint/exporter and then re-enable an Airflow scrape job.
