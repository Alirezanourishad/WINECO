# ──────────────────────────────────────────────────────────────
# Decision_algorithm.py — DIGITAL TWIN VERSION
#
# Additions vs. the simple version:
#   1. Subscribes to "override/disaster" — manual injection
#      from the status dashboard (0/1).
#   2. Publishes a unified "disaster/active" state topic (retained)
#      so the dashboard can know the *effective* disaster state
#      without having to infer it from piston+shading values.
#   3. Manual commands for piston/shading are also blocked while
#      disaster is active (was: only auto was blocked).
#   4. Manual locks for piston/shading are CLEARED when disaster
#      starts — they can resume auto immediately when disaster ends,
#      without waiting for a stale 5-min lock to time out.
# ──────────────────────────────────────────────────────────────
import paho.mqtt.client as mqtt
import json
import time
import requests

# --- CONFIGURATION ---
BROKER = "inside-broker"
PORT = 1883
LAT, LON = 45.0545, 7.6835

ACTUATORS = ["led1", "led2", "piston", "shading", "fan"]
PROTECTED = ["piston", "shading"]   # forced to 0 during disaster

# --- State Tracking ---
manual_locks = {act: 0 for act in ACTUATORS}    # 5-min lock timestamp
disaster_active = False                          # real wind-driven disaster
override_disaster_active = False                 # manual injection from dashboard
_last_published_effective = None                 # to avoid spamming disaster/active


def is_disaster():
    return disaster_active or override_disaster_active


def publish_effective_state(client):
    """Publish disaster/active with retain=True so any subscriber (incl. those
    that connect later) gets the current effective state. Idempotent."""
    global _last_published_effective
    current = is_disaster()
    if current != _last_published_effective:
        payload = "1" if current else "0"
        client.publish("disaster/active", payload, retain=True)
        _last_published_effective = current
        print(f"📡 published disaster/active = {payload}")


def trigger_disaster_close(client):
    """Common code path when disaster fires (from either source).
    Clears manual locks on protected actuators and closes them."""
    for act in PROTECTED:
        manual_locks[act] = 0      # clear stale manual locks
    publish_effective_state(client)   # publish FIRST so dashboard knows
    client.publish("piston_final_command", 0)
    client.publish("shading_final_command", 0)


def check_weather_api():
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current_weather=true"
        res = requests.get(url, timeout=2).json()
        return res['current_weather']['windspeed'] > 40
    except:
        return False


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ DECISION ALGORITHM ONLINE")
        client.subscribe([
            ("gui/manual_control", 0),
            ("aut_logic/+", 0),
            ("override/disaster", 0),
        ])
        publish_effective_state(client)   # publish initial state


def on_message(client, userdata, msg):
    global override_disaster_active
    topic = msg.topic
    payload = msg.payload.decode()
    current_time = time.time()

    # --- ROUTE A: MANUAL COMMANDS ---
    if topic == "gui/manual_control":
        try:
            data = json.loads(payload)
            for key, val in data.items():
                act_name = key.replace("_val", "")
                if act_name not in ACTUATORS:
                    continue
                # block manual for protected actuators during disaster
                if is_disaster() and act_name in PROTECTED:
                    print(f"🚨 DISASTER BLOCK: manual {act_name} ignored")
                    continue
                manual_locks[act_name] = current_time + 300
                final_topic = f"{act_name}_final_command"
                client.publish(final_topic, val)
                print(f"⌨️  MANUAL PRIORITY: {final_topic} -> {val}")
        except:
            pass

    # --- ROUTE B: AUTO LOGIC ---
    elif topic.startswith("aut_logic/"):
        act_name = topic.split("/")[-1]
        if act_name in ACTUATORS:
            if is_disaster() and act_name in PROTECTED:
                print(f"🚨 DISASTER BLOCK: auto {act_name} ignored")
            elif current_time < manual_locks[act_name]:
                remaining = int(manual_locks[act_name] - current_time)
                print(f"🛠️  MANUAL BLOCK: {act_name} locked for {remaining}s")
            else:
                final_topic = f"{act_name}_final_command"
                client.publish(final_topic, payload)
                print(f"🤖 AUTO EXECUTE: {final_topic} -> {payload}")

    # --- ROUTE C: DISASTER OVERRIDE (manual injection from dashboard) ---
    elif topic == "override/disaster":
        val = payload.strip().lower()
        new_state = val in ("1", "true", "on")
        if new_state != override_disaster_active:
            override_disaster_active = new_state
            if new_state:
                print("🚨 DISASTER OVERRIDE: manual injection ON — closing barriers")
                trigger_disaster_close(client)
            else:
                print("✅ DISASTER OVERRIDE: manual injection OFF")
                publish_effective_state(client)


# --- MQTT Setup ---
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_start()

try:
    while True:
        is_stormy = check_weather_api()
        if is_stormy:
            if not disaster_active:
                print("🚨 DISASTER START: real wind > 40 km/h — closing barriers")
                disaster_active = True
                trigger_disaster_close(client)
        else:
            if disaster_active:
                print("🌤️  DISASTER END: real wind back to safe range")
                disaster_active = False
                publish_effective_state(client)
        time.sleep(30)
except KeyboardInterrupt:
    client.loop_stop()
