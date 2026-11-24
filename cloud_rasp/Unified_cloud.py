# ──────────────────────────────────────────────────────────────
# Unified_cloud.py — DIGITAL TWIN VERSION
#
#   Same two responsibilities as the physical cloud Pi:
#     1) UNIVERSAL LOGGER — subscribes to every MQTT topic ('#')
#        and writes each message into InfluxDB.
#     2) GRAFANA → MQTT BRIDGE — exposes Flask /publish so the
#        Grafana UI (or any HTTP client) can post manual commands
#        that get re-published to MQTT.
#
#   Differences from the physical version:
#     - LAPTOP_IP -> "inside-broker" (Docker DNS, not a LAN IP).
#     - INFLUX_URL stays http://localhost:8086 because InfluxDB
#       runs inside this same cloud_rasp_sim container.
#     - os.system("mosquitto_pub …") is replaced with a native
#       paho-mqtt publish — no need to install mosquitto-clients.
#     - TOKEN/ORG/BUCKET must match what you set when you first
#       opened the InfluxDB UI. Edit them below.
# ──────────────────────────────────────────────────────────────
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import threading
import time

# --- CONFIGURATION ----------------------------------------------------
# Configuration is loaded from the environment.
TOKEN = os.environ["INFLUXDB_TOKEN"]
ORG = os.environ.get("INFLUXDB_ORG", "WINECO")
BUCKET = os.environ.get("INFLUXDB_BUCKET", "WINECO")
INFLUX_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")

BROKER_HOST = "inside-broker"   # Docker DNS name (was a laptop IP on physical)
MQTT_PORT = 1883

# --- FLASK BRIDGE SETUP -----------------------------------------------
app = Flask(__name__)
CORS(app)

# Will be set by run_mqtt() once the logger client connects
mqtt_client_ref = {"client": None}

@app.route('/publish', methods=['POST'])
def publish():
    try:
        data = request.json

        # Accept BOTH formats:
        #   A) wrapped:  {"topic": "...", "payload": {...}}
        #   B) plain:    {"fan_val": 50, "piston_val": 30, ...}  (Business Forms default)
        if isinstance(data, dict) and "topic" in data and "payload" in data:
            topic = data.get("topic", "gui/manual_control")
            payload = json.dumps(data.get("payload"))
        else:
            topic = "gui/manual_control"
            payload = json.dumps(data)

        client = mqtt_client_ref["client"]
        if client is None:
            return jsonify({"error": "MQTT client not ready yet"}), 503

        client.publish(topic, payload)
        print(f"🚀 Bridge: {topic} -> {payload}")
        return jsonify({"status": "sent"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# --- INFLUX LOGGER SETUP ----------------------------------------------
db_client = InfluxDBClient(url=INFLUX_URL, token=TOKEN, org=ORG)
write_api = db_client.write_api(write_options=SYNCHRONOUS)

def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = msg.payload.decode()
        point = Point("all_iot_data").tag("topic", topic)
        try:
            val = float(payload)
            point.field("numeric_value", val)
        except ValueError:
            point.field("string_value", payload)
        write_api.write(bucket=BUCKET, org=ORG, record=point)
    except Exception as e:
        print(f"⚠️ Logger Error: {e}")

def run_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = lambda c, u, f, rc, p=None: c.subscribe("#")
    client.on_message = on_message

    # RETRY LOOP: Prevents TimeoutError during boot
    connected = False
    while not connected:
        try:
            print(f"📡 Attempting connection to broker: {BROKER_HOST}...")
            client.connect(BROKER_HOST, MQTT_PORT, keepalive=60)
            connected = True
            print("✅ Universal Logger Connected!")
        except Exception as e:
            print(f"⚠️ Connection failed ({e}). Retrying in 10 seconds...")
            time.sleep(10)

    # Share the connected client with Flask so /publish can use it
    mqtt_client_ref["client"] = client
    client.loop_forever()

if __name__ == '__main__':
    # Start MQTT Logger in a separate background thread
    threading.Thread(target=run_mqtt, daemon=True).start()
    # Start Flask Bridge on Port 5000
    app.run(host='0.0.0.0', port=5000)
