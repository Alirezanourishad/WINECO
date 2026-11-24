# Deployment notes

These notes describe how to configure and run the WINECO digital twin locally. Runtime startup has not yet been independently tested.

## Prerequisites

- Docker Engine or Docker Desktop with Docker Compose v2.
- This repository cloned locally.
- Fresh local credentials and a reviewed environment configuration.
- An isolated development network.

WINECO uses four Compose services: `inside-broker`, `inside-rasp`, `outside-rasp`, and `cloud-rasp`.

## Startup sequence

Copy `cloud_rasp/.env.example` to `cloud_rasp/.env` and set unique nonempty values for the InfluxDB token and both passwords. Keep the same configuration across restarts. Then:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```

The current configuration requires the following Python processes to be started manually, in separate terminal sessions as appropriate:

| Service | Scripts |
| --- | --- |
| inside-rasp | inside_handling.py, automat_logic.py, Decision_algorithm.py |
| outside-rasp | outside_handling.py |
| cloud-rasp | Unified_cloud.py |

For example, from the repository root: `docker compose exec inside-rasp python inside_handling.py`.

## Local service endpoints

| Service | Host port |
| --- | --- |
| MQTT | 1884 |
| InfluxDB | 8086 |
| Grafana | 3000 |
| Flask bridge | 5000 |
| Actuator status | 5050 |

The portfolio Compose file binds exposed ports to 127.0.0.1. MQTT is anonymous within the isolated simulation and the Flask bridge does not implement authentication. Do not deploy this configuration publicly or use it to control real hardware without further safety and security engineering.

## Security checklist

- Rotate any previously exposed tokens, credentials and remote-access setup keys.
- Keep real environment files and runtime databases out of version control.
- Use unique credentials and avoid anonymous broker access outside isolated testing.
- Review all source files, dashboards, logs and Git history before publishing.
- Never commit credentials or authentication tokens.

## Reproducibility and limitations

The current Docker stack has not been tested end to end. Hardware-dependent tests require the physical prototype. The repository includes CI configuration for Python syntax, lint, shell syntax and Compose validation; runtime tests and further hardening remain future work.
