#!/bin/bash
# ──────────────────────────────────────────────────────────────
# Cloud Rasp entrypoint — HARDENED VERSION
#   - Auto-starts InfluxDB (port 8086)
#   - Auto-runs `influx setup` ONLY on first boot (idempotent)
#   - Auto-starts Grafana (port 3000) with admin credentials from .env
#   - Auto-starts status dashboard (port 5050)
#   - Then idles so you can `docker exec` in and run Unified_cloud.py
# ──────────────────────────────────────────────────────────────

set -eu
: "${INFLUXDB_TOKEN:?Set INFLUXDB_TOKEN in cloud_rasp/.env}"
: "${INFLUXDB_PASSWORD:?Set INFLUXDB_PASSWORD in cloud_rasp/.env}"
: "${GF_SECURITY_ADMIN_PASSWORD:?Set GF_SECURITY_ADMIN_PASSWORD in cloud_rasp/.env}"
export INFLUXDB_ORG="${INFLUXDB_ORG:-WINECO}"
export INFLUXDB_BUCKET="${INFLUXDB_BUCKET:-WINECO}"

# ─── 1. Prepare data directories with the right ownership ─────
mkdir -p /var/lib/influxdb2 /var/lib/grafana /var/log/grafana
chown -R grafana:grafana /var/lib/grafana /var/log/grafana 2>/dev/null || true

# ─── 2. Start InfluxDB in the background ──────────────────────
# Force InfluxDB to write to /var/lib/influxdb2 so the bind mount actually captures it
export INFLUXD_BOLT_PATH=/var/lib/influxdb2/influxd.bolt
export INFLUXD_ENGINE_PATH=/var/lib/influxdb2/engine
echo "🚀 Starting InfluxDB on :8086 (data → /var/lib/influxdb2) ..."
influxd > /var/log/influxdb.log 2>&1 &

# ─── 3. First-boot auto-setup of InfluxDB ─────────────────────
# Query the setup endpoint instead of checking for a database file.
setup_state=""
for i in {1..60}; do
    if setup_state=$(curl -fsS http://localhost:8086/api/v2/setup 2>/dev/null); then
        break
    fi
    sleep 1
done
if [ -z "$setup_state" ]; then
    echo "InfluxDB did not become ready" >&2
    exit 1
fi
if printf '%s' "$setup_state" | grep -Eq '"allowed"[[:space:]]*:[[:space:]]*true'; then
    influx setup \
        --username "${INFLUXDB_USER:-wineco}" \
        --password "${INFLUXDB_PASSWORD}" \
        --org "${INFLUXDB_ORG}" \
        --bucket "${INFLUXDB_BUCKET}" \
        --token "${INFLUXDB_TOKEN}" \
        --force
else
    echo "Existing InfluxDB setup preserved."
fi

# ─── 4. Start Grafana in the background ───────────────────────
echo "🚀 Starting Grafana on :3000 ..."

# Pass admin credentials via env so Grafana picks them up on first boot
export GF_SECURITY_ADMIN_USER="${GF_SECURITY_ADMIN_USER:-WINECO}"
export GF_SECURITY_ADMIN_PASSWORD

# INFLUXDB_TOKEN is referenced by the provisioned datasource YAML
export INFLUXDB_TOKEN="${INFLUXDB_TOKEN}"
export INFLUXDB_ORG="${INFLUXDB_ORG:-WINECO}"
export INFLUXDB_BUCKET="${INFLUXDB_BUCKET:-WINECO}"

# Install Business Forms plugin (needed for the manual-control sliders+submit
# buttons on the WINECO dashboard). Idempotent: only runs if not already present.
# Non-fatal if it fails (e.g. no internet) — the rest of the dashboard still works,
# only the manual control row will show "Plugin not found" until you run this
# block again with network.
mkdir -p /var/lib/grafana/plugins
if [ ! -d /var/lib/grafana/plugins/volkovlabs-form-panel ]; then
    echo "📦 Installing Business Forms (volkovlabs-form-panel) plugin..."
    grafana-cli --pluginsDir /var/lib/grafana/plugins plugins install volkovlabs-form-panel \
        && echo "✅ Business Forms plugin installed." \
        || echo "⚠️  Plugin install failed (no network?). Manual control sliders will be inactive."
    chown -R grafana:grafana /var/lib/grafana/plugins 2>/dev/null || true
else
    echo "♻️  Business Forms plugin already installed."
fi

/usr/sbin/grafana-server \
    --homepath=/usr/share/grafana \
    --config=/etc/grafana/grafana.ini \
    cfg:default.paths.data=/var/lib/grafana \
    cfg:default.paths.logs=/var/log/grafana \
    cfg:default.paths.plugins=/var/lib/grafana/plugins \
    cfg:default.paths.provisioning=/etc/grafana/provisioning \
    > /var/log/grafana.log 2>&1 &

# ─── 5. Start the actuator status dashboard ───────────────────
sleep 2
echo "🚀 Starting actuator status dashboard on :5050 ..."
python /app/status_dashboard.py > /var/log/status_dashboard.log 2>&1 &

# Give services a moment to bind their ports
sleep 4

cat <<EOF

═══════════════════════════════════════════════════════
 ☁️   CLOUD RASP READY (HARDENED)
═══════════════════════════════════════════════════════
 📊  InfluxDB UI : http://localhost:8086
 📈  Grafana UI  : http://localhost:3000
 🚦  Status page : http://localhost:5050
 🌉  Flask bridge: http://localhost:5000/publish

 Data is bind-mounted to ./data/ on the host.
 docker compose down -v will NOT erase it.

 To run the cloud-rasp universal logger + bridge:
   docker exec -it cloud_rasp_sim /bin/bash
   python Unified_cloud.py
═══════════════════════════════════════════════════════

EOF

# Stream all logs and keep the container alive (PID 1).
tail -F /var/log/influxdb.log /var/log/grafana.log /var/log/status_dashboard.log
