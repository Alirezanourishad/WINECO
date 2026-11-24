# ══════════════════════════════════════════════════════════════════
# status_dashboard.py — WINECO Actuator Live Status
#
# Updates in this version:
#   1. Subscribes to "disaster/active" — no more inferring DISASTER
#      from value patterns. Source detection is now race-free.
#   2. Manual lock COUNTDOWN TIMER shown on each actuator card.
#   3. Events deduplicated (only logged on state change), so manual
#      and disaster events never get pushed off by auto repetition.
#   4. Timestamps sent as Unix epoch, formatted in browser local time.
#   5. Disaster injection toggle (POST → MQTT override/disaster).
# ══════════════════════════════════════════════════════════════════

import os
import json
import time
import threading
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request, render_template_string

# ─── CONFIG ────────────────────────────────────────────────────────
BROKER  = os.environ.get("MQTT_BROKER", "inside-broker")
PORT    = int(os.environ.get("MQTT_PORT", "1883"))
HTTP_PORT = 5050

ACTUATORS = ["fan", "piston", "shading", "led1", "led2"]
PROTECTED = ("piston", "shading")
MANUAL_LOCK_SECONDS = 300

# ─── STATE ─────────────────────────────────────────────────────────
state_lock = threading.Lock()

actuator_state = {
    name: {
        "value": None,
        "source": "—",
        "updated_at_epoch": None,
        "manual_lock_until": 0,    # Unix epoch
    } for name in ACTUATORS
}

effective_disaster_active = False   # mirrors Decision_algorithm's disaster/active topic
disaster_override_on = False        # mirrors the dashboard toggle (UI-side)
events = deque(maxlen=100)

mqtt_client = None


def log_event_if_changed(actuator, value, source):
    """Only append to events deque if the actuator's state actually changed
    from its most recent event. Drastically reduces noise from auto_logic
    republishing the same value every cycle."""
    # Find the most recent event for this actuator
    prev = next((e for e in events if e["actuator"] == actuator), None)
    if prev and prev["value"] == value and prev["source"] == source:
        return  # no change → don't log
    events.appendleft({
        "time_epoch": time.time(),
        "actuator": actuator,
        "value": value,
        "source": source,
    })


# ─── MQTT ──────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ status_dashboard connected to MQTT broker")
        client.subscribe("gui/manual_control")
        client.subscribe("aut_logic/+")
        client.subscribe("disaster/active")          # NEW
        for act in ACTUATORS:
            client.subscribe(f"{act}_final_command")
    else:
        print(f"❌ MQTT connection failed: {rc}")


def on_message(client, userdata, msg):
    global effective_disaster_active
    topic = msg.topic
    try:
        payload = msg.payload.decode().strip()
    except Exception:
        return

    now = time.time()

    with state_lock:
        # ── 1) DISASTER STATE (authoritative — from Decision_algorithm) ──
        if topic == "disaster/active":
            new_state = payload.lower() in ("1", "true", "on")
            if new_state != effective_disaster_active:
                effective_disaster_active = new_state
                print(f"📡 effective disaster state = {new_state}")
                # When disaster starts, immediately mark protected
                # actuators as DISASTER source (they'll get value=0 next).
                if new_state:
                    for act in PROTECTED:
                        st = actuator_state[act]
                        st["source"] = "DISASTER"
                        st["updated_at_epoch"] = now
                        st["manual_lock_until"] = 0   # match Decision_algorithm:
                                                       # disaster cancels the manual lock
            return

        # ── 2) Manual control panel ──
        if topic == "gui/manual_control":
            try:
                data = json.loads(payload)
                for key in data:
                    act = key.replace("_val", "")
                    if act not in actuator_state:
                        continue
                    # Don't set lock if disaster is active for protected actuator
                    # (Decision_algorithm will reject the command anyway)
                    if effective_disaster_active and act in PROTECTED:
                        continue
                    actuator_state[act]["manual_lock_until"] = now + MANUAL_LOCK_SECONDS
            except Exception as e:
                print(f"⚠️ bad manual payload: {e}")
            return

        # ── 3) Auto-logic suggestion (ignored for source detection, but logged) ──
        if topic.startswith("aut_logic/"):
            # We only care about FINAL commands for the LEDs and events.
            # aut_logic is just informational — skip it here.
            return

        # ── 4) Final command — what actually drives the actuator ──
        if topic.endswith("_final_command"):
            act = topic[: -len("_final_command")]
            if act not in actuator_state:
                return
            try:
                value = float(payload)
            except ValueError:
                return

            st = actuator_state[act]

            # Source determination — explicit, no inference
            if effective_disaster_active and act in PROTECTED:
                source = "DISASTER"
            elif now < st["manual_lock_until"]:
                source = "MANUAL"
            else:
                source = "AUTO LOGIC"

            st["value"] = value
            st["source"] = source
            st["updated_at_epoch"] = now

            log_event_if_changed(act, value, source)
            print(f"📍 {act} = {value}%  ({source})")


def run_mqtt():
    global mqtt_client
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    while True:
        try:
            mqtt_client.connect(BROKER, PORT, keepalive=60)
            mqtt_client.loop_forever()
        except Exception as e:
            print(f"⚠️ MQTT reconnect in 5s: {e}")
            time.sleep(5)


# ─── FLASK ─────────────────────────────────────────────────────────
app = Flask(__name__)

PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>WINECO — Actuator Status</title>
<style>
  :root {
    --bg: #0f1117;
    --panel: #181b24;
    --panel2: #1f2330;
    --line: #2a2f3d;
    --text: #e6e9f2;
    --muted: #8a93a6;
    --auto: #3aa6ff;
    --manual: #f0b400;
    --disaster: #ff4d57;
    --idle: #4a5060;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    background: var(--bg); color: var(--text);
    transition: background .4s;
  }
  body.disaster-on { background: #1a0f12; }
  h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: .3px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 16px; }

  /* ─── Disaster injection panel ─── */
  .injector {
    display: flex; align-items: center; gap: 12px;
    margin: 0 0 24px;
    padding: 10px 16px;
    background: rgba(255,77,87,0.05);
    border: 1px solid rgba(255,77,87,0.2);
    border-radius: 10px;
    width: fit-content;
  }
  .injector.on {
    background: rgba(255,77,87,0.18);
    border-color: var(--disaster);
    box-shadow: 0 0 18px rgba(255,77,87,0.25);
  }
  .injector-label {
    font-size: 12px; font-weight: 700;
    color: var(--disaster);
    text-transform: uppercase; letter-spacing: 1.2px;
  }
  .injector-state {
    font-size: 11px; font-weight: 600;
    color: var(--muted); letter-spacing: .6px;
  }
  .injector.on .injector-state { color: var(--disaster); }

  .switch { position: relative; display: inline-block; width: 46px; height: 24px; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider {
    position: absolute; cursor: pointer;
    top: 0; left: 0; right: 0; bottom: 0;
    background: #3a3f50; border-radius: 24px; transition: .25s;
  }
  .slider:before {
    position: absolute; content: "";
    height: 18px; width: 18px; left: 3px; bottom: 3px;
    background: white; border-radius: 50%; transition: .25s;
  }
  input:checked + .slider { background: var(--disaster); }
  input:checked + .slider:before { transform: translateX(22px); }

  /* ─── Cards grid ─── */
  .grid {
    display: grid; gap: 14px;
    grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
    margin-bottom: 28px;
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 18px;
    position: relative;
  }
  .card .name {
    font-size: 13px; text-transform: uppercase; letter-spacing: 1.2px;
    color: var(--muted); margin-bottom: 6px;
  }
  .card .val { font-size: 38px; font-weight: 600; line-height: 1.1; }
  .card .val .unit { font-size: 18px; color: var(--muted); margin-left: 4px; }
  .bar {
    height: 6px; background: var(--panel2); border-radius: 3px;
    overflow: hidden; margin: 12px 0 10px;
  }
  .bar > div { height: 100%; transition: width .3s ease; }
  .bar > div.AUTO     { background: var(--auto); }
  .bar > div.MANUAL   { background: var(--manual); }
  .bar > div.DISASTER { background: var(--disaster); }
  .bar > div.IDLE     { background: var(--idle); }

  /* ─── 3-LED row ─── */
  .leds { display: flex; gap: 5px; margin: 12px 0 10px; }
  .led {
    flex: 1;
    display: inline-flex; align-items: center; justify-content: center;
    gap: 5px;
    padding: 4px 6px;
    border-radius: 6px;
    font-size: 9px; font-weight: 700;
    letter-spacing: .6px;
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.05);
    opacity: 0.32;
    transition: opacity .25s, background .25s, border-color .25s;
  }
  .led .dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--idle); transition: background .25s, box-shadow .25s;
  }
  .led.on { opacity: 1; }
  .led-DISASTER.on { background: rgba(255,77,87,0.15); border-color: var(--disaster); color: var(--disaster); }
  .led-DISASTER.on .dot { background: var(--disaster); box-shadow: 0 0 10px var(--disaster); animation: led-pulse 1.4s infinite; }
  .led-MANUAL.on { background: rgba(240,180,0,0.15); border-color: var(--manual); color: var(--manual); }
  .led-MANUAL.on .dot { background: var(--manual); box-shadow: 0 0 10px var(--manual); animation: led-pulse 1.4s infinite; }
  .led-AUTO.on { background: rgba(58,166,255,0.15); border-color: var(--auto); color: var(--auto); }
  .led-AUTO.on .dot { background: var(--auto); box-shadow: 0 0 10px var(--auto); animation: led-pulse 1.4s infinite; }
  @keyframes led-pulse {
    0%, 100% { filter: brightness(1.0); }
    50%      { filter: brightness(1.4); }
  }

  /* ─── Manual lock countdown ─── */
  .lock-timer {
    display: none;
    align-items: center;
    gap: 6px;
    margin: 6px 0 4px;
    padding: 4px 8px;
    background: rgba(240,180,0,0.10);
    border: 1px solid rgba(240,180,0,0.30);
    border-radius: 6px;
    color: var(--manual);
    font-size: 11px;
    font-weight: 600;
    width: fit-content;
    letter-spacing: .3px;
    font-variant-numeric: tabular-nums;
  }
  .lock-timer.visible { display: inline-flex; }

  .when { color: var(--muted); font-size: 11px; margin-top: 6px; }

  /* ─── Events table ─── */
  h2 { font-size: 14px; text-transform: uppercase; color: var(--muted);
       letter-spacing: 1.4px; margin: 0 0 10px; }
  table {
    width: 100%; border-collapse: collapse;
    background: var(--panel); border-radius: 12px; overflow: hidden;
  }
  th, td { padding: 10px 14px; font-size: 13px; text-align: left; }
  th { background: var(--panel2); color: var(--muted);
       font-weight: 500; text-transform: uppercase; letter-spacing: .6px; font-size: 11px; }
  tr + tr td { border-top: 1px solid var(--line); }
  td.time { font-variant-numeric: tabular-nums; color: var(--muted); }
  .src-tag {
    display: inline-block;
    padding: 2px 8px; border-radius: 999px;
    font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .6px;
  }
  .src-tag.AUTO     { background: rgba(58,166,255,.15);  color: var(--auto); }
  .src-tag.MANUAL   { background: rgba(240,180,0,.15);   color: var(--manual); }
  .src-tag.DISASTER { background: rgba(255,77,87,.15);   color: var(--disaster); }
  .src-tag.IDLE     { background: rgba(120,128,150,.15); color: var(--muted); }

  .pulse {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: #38d977; margin-right: 8px;
    box-shadow: 0 0 0 0 rgba(56,217,119,.6);
    animation: pulse 1.4s infinite;
  }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(56,217,119,.5); }
    70%  { box-shadow: 0 0 0 8px rgba(56,217,119,0); }
    100% { box-shadow: 0 0 0 0 rgba(56,217,119,0); }
  }
</style>
</head>
<body>
  <h1><span class="pulse"></span>WINECO — Actuator Status</h1>
  <div class="sub">Live view of every actuator and which command source is driving it.</div>

  <div class="injector" id="injector">
    <span class="injector-label">🚨 Inject Disaster</span>
    <label class="switch">
      <input type="checkbox" id="disaster-toggle" onchange="toggleDisaster(this)">
      <span class="slider"></span>
    </label>
    <span class="injector-state" id="disaster-state">OFF</span>
  </div>

  <div class="grid" id="cards"></div>

  <h2>Recent events</h2>
  <table id="events">
    <thead>
      <tr><th>Time</th><th>Actuator</th><th>Value</th><th>Source</th></tr>
    </thead>
    <tbody></tbody>
  </table>

<script>
const PROTECTED = ['piston', 'shading'];

function sourceClass(s) {
  if (!s || s === "—") return "IDLE";
  if (s.startsWith("AUTO")) return "AUTO";
  return s;
}

function formatLocalTime(epochSec) {
  if (!epochSec) return '—';
  const d = new Date(epochSec * 1000);
  return d.toLocaleTimeString('en-GB', { hour12: false });
}

function formatCountdown(remainingSec) {
  const m = Math.floor(remainingSec / 60);
  const s = Math.floor(remainingSec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

async function toggleDisaster(input) {
  const value = input.checked ? '1' : '0';
  try {
    const r = await fetch('/api/disaster_override', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value })
    });
    if (!r.ok) throw new Error('server error');
    const data = await r.json();
    if (data.status !== 'sent') throw new Error(data.reason || 'failed');
    document.getElementById('disaster-state').textContent =
      input.checked ? 'ON — disaster injected' : 'OFF';
    document.getElementById('injector').classList.toggle('on', input.checked);
    document.body.classList.toggle('disaster-on', input.checked);
  } catch (e) {
    console.error('Failed to toggle disaster:', e);
    input.checked = !input.checked;
    alert('Could not toggle disaster — MQTT not connected?');
  }
}

async function refresh() {
  try {
    const r = await fetch('/api/state');
    const data = await r.json();

    // Sync toggle state with server (covers reload)
    const toggle = document.getElementById('disaster-toggle');
    if (data.disaster_override_on !== undefined &&
        toggle.checked !== data.disaster_override_on) {
      toggle.checked = data.disaster_override_on;
      document.getElementById('disaster-state').textContent =
        toggle.checked ? 'ON — disaster injected' : 'OFF';
      document.getElementById('injector').classList.toggle('on', toggle.checked);
      document.body.classList.toggle('disaster-on', toggle.checked);
    }

    const nowSec = Date.now() / 1000;
    const disasterOn = !!data.effective_disaster_active;

    // CARDS
    const cards = document.getElementById('cards');
    cards.innerHTML = '';
    for (const [name, st] of Object.entries(data.actuators)) {
      const cls = sourceClass(st.source);
      const val = (st.value == null) ? '—' : Math.round(st.value);
      const width = (st.value == null) ? 0 : Math.max(0, Math.min(100, st.value));
      const updatedStr = st.updated_at_epoch
        ? 'updated ' + formatLocalTime(st.updated_at_epoch)
        : 'waiting for first command…';

      // Manual lock countdown: visible only if locked AND not disaster-overridden
      const lockUntil = st.manual_lock_until || 0;
      const remaining = lockUntil - nowSec;
      const isProtected = PROTECTED.includes(name);
      const showTimer = remaining > 0 && !(disasterOn && isProtected);
      const timerHtml = showTimer
        ? `<div class="lock-timer visible">🔒 Manual lock · ${formatCountdown(remaining)}</div>`
        : '';

      cards.insertAdjacentHTML('beforeend', `
        <div class="card">
          <div class="name">${name}</div>
          <div class="val">${val}<span class="unit">%</span></div>
          <div class="bar"><div class="${cls}" style="width:${width}%"></div></div>
          <div class="leds">
            <div class="led led-DISASTER ${cls === 'DISASTER' ? 'on' : ''}">
              <span class="dot"></span>DISASTER
            </div>
            <div class="led led-MANUAL ${cls === 'MANUAL' ? 'on' : ''}">
              <span class="dot"></span>MANUAL
            </div>
            <div class="led led-AUTO ${cls === 'AUTO' ? 'on' : ''}">
              <span class="dot"></span>AUTO
            </div>
          </div>
          ${timerHtml}
          <div class="when">${updatedStr}</div>
        </div>
      `);
    }

    // EVENTS — already deduplicated server-side, no further filtering needed
    const tbody = document.querySelector('#events tbody');
    tbody.innerHTML = '';
    for (const ev of data.events) {
      const cls = sourceClass(ev.source);
      tbody.insertAdjacentHTML('beforeend', `
        <tr>
          <td class="time">${formatLocalTime(ev.time_epoch)}</td>
          <td>${ev.actuator}</td>
          <td>${Math.round(ev.value)}%</td>
          <td><span class="src-tag ${cls}">${ev.source}</span></td>
        </tr>
      `);
    }
  } catch (e) {
    console.error(e);
  }
}
refresh();
setInterval(refresh, 1000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/api/state")
def api_state():
    with state_lock:
        public = {}
        for name, st in actuator_state.items():
            public[name] = {
                "value": st["value"],
                "source": st["source"],
                "updated_at_epoch": st["updated_at_epoch"],
                "manual_lock_until": st["manual_lock_until"],
            }
        return jsonify({
            "actuators": public,
            "events": list(events),
            "effective_disaster_active": effective_disaster_active,
            "disaster_override_on": disaster_override_on,
        })


@app.route("/api/disaster_override", methods=["POST"])
def api_disaster_override():
    """Toggle: publishes 0/1 to MQTT topic override/disaster.
    Decision_algorithm.py subscribes there and treats 1 as a real disaster."""
    global disaster_override_on
    data = request.get_json(silent=True) or {}
    value = str(data.get("value", "0"))
    if mqtt_client is None:
        return jsonify({"status": "error", "reason": "mqtt not connected"}), 503
    try:
        mqtt_client.publish("override/disaster", value)
        disaster_override_on = value in ("1", "true", "True", "on")
        print(f"🚨 dashboard published override/disaster = {value}")
        return jsonify({"status": "sent", "value": value})
    except Exception as e:
        return jsonify({"status": "error", "reason": str(e)}), 500


if __name__ == "__main__":
    threading.Thread(target=run_mqtt, daemon=True).start()
    print(f"🚦 Status dashboard listening on http://0.0.0.0:{HTTP_PORT}")
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False, use_reloader=False)
