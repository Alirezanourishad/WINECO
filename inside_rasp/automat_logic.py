# ──────────────────────────────────────────────────────────────
# automat_logic.py — DIGITAL TWIN VERSION
#   Identical to the physical version except BROKER is the Docker
#   service name. There is no hardware in this script, so the
#   simulation behaves exactly like the real Pi.
# ──────────────────────────────────────────────────────────────
import paho.mqtt.client as mqtt
import json

# --- CONFIGURATION ---
BROKER = "inside-broker"   # Docker DNS name (was "localhost" on the real Pi)
PORT = 1883

# Subscribing to wildcards ensures we grab everything regardless of roots (e.g., building/sensor/lux_zone1)
INPUT_TOPICS = [
    "kpi/thermal", "kpi/iaq", "kpi/visual",
    "sensor/inside_co2", "sensor/lux_zone1", "sensor/lux_zone2",
    "sensor/inside_temp", "sensor/outside_temp"
]

ACTUATOR_TOPICS = {
    "piston": "aut_logic/piston",
    "shading": "aut_logic/shading",
    "led1": "aut_logic/led1",
    "led2": "aut_logic/led2",
    "fan": "aut_logic/fan"
}

# Adjusted defaults to realistic "operating" numbers so logic isn't instantly zeroed
current_data = {
    "thermal_kpi": 50.0,
    "iaq_kpi": 50.0,
    "visual_kpi": 50.0,
    "co2": 1300.0,         # Set above 1200 to test fan response instantly
    "lux1": 300.0,         # Set below 400 to test LED response instantly
    "lux2": 300.0,
    "t_in": 25.0,          # Set above 25 to test piston response instantly
    "t_out": 23.0
}

# --- CONTROL LOGIC CLASSES ---

class FanController:
    def get_command(self, co2, t_in):
        # Temperature emergency rule takes absolute priority
        if t_in > 29.0:
            return 100.0

        # Original CO2 logic runs if temperature is safe
        if co2 <= 1200: return 0.0
        elif co2 <= 1700: return 50.0
        elif co2 <= 2000: return 85.0
        else: return 100.0

class PistonController:
    def __init__(self):
        self.co2_override = False

    def get_command(self, co2, t_in, t_out):
        if co2 > 2000:
            self.co2_override = True
        elif co2 < 1500:
            self.co2_override = False

        if self.co2_override:
            return 100.0

        if t_in > 25.0 and (t_in - t_out) > 3.0:
            return 100.0

        return 0.0


class LightingController:
    def __init__(self):
        self.target = 400     # Adjusted target to 400 lux as requested
        self.shade_pos = 50.0 # 0.0 = fully closed (dark), 100.0 = fully open (bright)
        self.deadband = 20    # Prevents jittering/oscillating right at 400 lux

    def get_commands(self, l1, l2, t_in):
        # --- 1. TEMPERATURE EMERGENCY OVERRIDE (First Priority) ---
        # If inside temperature goes over 40°C, slam shades closed to stop greenhouse heat gain
        if t_in > 28.0:
            self.shade_pos = 0.0

        # --- 2. REGULAR LIGHTING LOGIC (Runs only if temperature is safe) ---
        else:
            # --- AUTOMATIC SHADING CONTROL ---
            # If light drops below 380 lux, open the shades to let natural light in
            if l1 < (self.target - self.deadband):
                self.shade_pos = min(100, self.shade_pos + 10) # Smooth 10% steps

            # If light exceeds 420 lux, close the shades to block excess light
            elif l1 > (self.target + self.deadband):
                self.shade_pos = max(0, self.shade_pos - 10)

            # Note: If light is between 380 and 420 lux, shade_pos remains unchanged.

        # --- 3. LED DIMMING CONTROL (0-100%) ---
        # Safeguarded math: explicitly forces 0 if light matches or exceeds target,
        # protecting the division logic from processing negative/excessive inputs.
        led1 = max(0, min(100, ((self.target - l1) / self.target) * 100)) if l1 < self.target else 0
        led2 = max(0, min(100, ((self.target - l2) / self.target) * 100)) if l2 < self.target else 0

        # --- 4. HIGH LUX SHADING OVERRIDE (Only active when temp is safe) ---
        if t_in <= 28.0:
            avg_lux = (l1 + l2) / 2
            if led1 == 0 and led2 == 0:
                if avg_lux > 450:
                    # If it's already at 50% or lower but light is still > 450, drop to 0%
                    if self.shade_pos <= 50:
                        self.shade_pos = 0.0
                    else:
                        self.shade_pos = 50.0

        return self.shade_pos, led1, led2


fan_ctrl = FanController()
piston_ctrl = PistonController()
light_ctrl = LightingController()

# --- MQTT CALLBACKS ---

def on_message(client, userdata, msg):
    
    try:
        # Robust payload parsing (Handles raw floats OR json strings like {"val": 23})
        payload_str = msg.payload.decode().strip()
        try:
            val = float(payload_str)
        except ValueError:
            data_dict = json.loads(payload_str)
            val = float(data_dict.get("value", data_dict.get("val", 0)))

        topic = msg.topic
        matched = True

        # Stricter string matches to safeguard variable routing
        if "thermal" in topic: current_data["thermal_kpi"] = val
        elif "iaq" in topic: current_data["iaq_kpi"] = val
        elif "co2" in topic: current_data["co2"] = val
        elif "lux_zone1" in topic or "lux1" in topic: current_data["lux1"] = val
        elif "lux_zone2" in topic or "lux2" in topic: current_data["lux2"] = val
        elif "inside_temp" in topic or "t_in" in topic: current_data["t_in"] = val
        elif "outside_temp" in topic or "t_out" in topic: current_data["t_out"] = val
        elif "visual" in topic: current_data["visual_kpi"] = val
        else:
            matched = False
            print(f"⚠️ Warning: Unhandled topic received: {topic}")

        if matched:
            # RECALCULATE
            fan = fan_ctrl.get_command(current_data["co2"], current_data["t_in"])
            piston = piston_ctrl.get_command(
                current_data["co2"], current_data["t_in"], current_data["t_out"]
            )
            # FIXED: Exchanged current_data["t_out"] for current_data["t_in"]
            shading, led1, led2 = light_ctrl.get_commands(
                current_data["lux1"], current_data["lux2"], current_data["t_in"]
            )

            results = {"fan": fan, "piston": piston, "shading": shading, "led1": led1, "led2": led2}

            print(f"\n--- 🤖 Logic Update (Triggered by: {topic} -> Value: {val}) ---")

            # Publish and Print
            for key, topic_name in ACTUATOR_TOPICS.items():
                val_out = max(0, min(100, round(results[key], 1)))
                client.publish(topic_name, val_out)
                print(f"📤 Published to {topic_name} -> {val_out}%")

    except Exception as e:
        print(f"Logic Error processing message on topic {msg.topic}: {e}")

# Connection and Loop
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT Broker successfully.")
        for t in INPUT_TOPICS:
            client.subscribe(t)
            print(f"📥 Subscribed to: {t}")
    else:
        print(f"❌ Connection failed with code {rc}")

client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER, PORT)
client.loop_forever()
