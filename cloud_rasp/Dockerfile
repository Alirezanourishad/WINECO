# ──────────────────────────────────────────────────────────────
# Cloud Rasp image — HARDENED VERSION
#   - Python 3.11 (for Unified_cloud.py + status_dashboard.py)
#   - InfluxDB 2.x  (data storage, auto-starts, auto-initializes)
#   - Grafana       (dashboards, auto-starts, auto-provisioned)
# ──────────────────────────────────────────────────────────────
FROM python:3.11-bullseye

# --- System utilities needed to add the apt repos + curl for health checks ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg ca-certificates curl apt-transport-https \
        adduser libfontconfig1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /etc/apt/keyrings

# --- Install InfluxDB 2.x from the official repo ---
# NOTE: uses the NEW signing key (influxdata-archive.key, not _compat)
# rotated by InfluxData in Jan 2026. signed-by scopes the key to this repo.
RUN wget -qO- https://repos.influxdata.com/influxdata-archive.key \
        | gpg --dearmor -o /etc/apt/keyrings/influxdata-archive.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main" \
        > /etc/apt/sources.list.d/influxdata.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends influxdb2 influxdb2-cli \
    && rm -rf /var/lib/apt/lists/*

# --- Install Grafana from the official repo ---
RUN wget -qO- https://apt.grafana.com/gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
        > /etc/apt/sources.list.d/grafana.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends grafana \
    && rm -rf /var/lib/apt/lists/*

# --- Python deps for Unified_cloud.py AND status_dashboard.py ---
RUN pip install --no-cache-dir \
        paho-mqtt \
        requests \
        influxdb-client \
        flask \
        flask-cors

# --- Startup script that launches InfluxDB + Grafana + status dashboard ---
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

# 8086 = InfluxDB UI/API | 3000 = Grafana UI | 5000 = Flask bridge | 5050 = status dashboard
EXPOSE 8086 3000 5000 5050

WORKDIR /app
CMD ["/usr/local/bin/start.sh"]
