# Deployment notes

These notes document the existing team simulation configuration for reference. This standalone portfolio does not currently distribute the team's source code or a runnable Compose stack.

## Prerequisites for an authorized local copy

- Docker Engine or Docker Desktop with Docker Compose v2.
- The original project files, obtained with permission from their authors.
- Fresh local credentials and a reviewed environment configuration.
- An isolated development network.

The team repository uses four Compose services: `inside-broker`, `inside-rasp`, `outside-rasp`, and `cloud-rasp`.

## Startup sequence

After configuring fresh secrets and reviewing network exposure in an authorized local copy:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```

The original configuration requires the following Python processes to be started manually, in separate terminal sessions as appropriate:

| Service | Scripts |
| --- | --- |
| inside-rasp | inside_handling.py, automat_logic.py, Decision_algorithm.py |
| outside-rasp | outside_handling.py |
| cloud-rasp | Unified_cloud.py |

For example, from the original project directory: `docker compose exec inside-rasp python inside_handling.py`.

## Service endpoints in the original development configuration

| Service | Host port |
| --- | --- |
| MQTT | 1884 |
| InfluxDB | 8086 |
| Grafana | 3000 |
| Flask bridge | 5000 |
| Actuator status | 5050 |

Restrict exposed ports to localhost or an appropriately protected network. Do not deploy this development configuration to the public internet.

## Security checklist

- Rotate any previously exposed tokens, credentials and remote-access setup keys.
- Keep real environment files and runtime databases out of version control.
- Use unique credentials and avoid anonymous broker access outside isolated testing.
- Review all source files, dashboards, logs and Git history before publishing.
- Never copy original credentials into this repository.

## Reproducibility and limitations

The original stack was inspected but has not been executed for this portfolio. Hardware-dependent tests require the original setup. Automated startup, pinned dependencies, CI tests and hardened container configuration are potential follow-up improvements, not completed features.
