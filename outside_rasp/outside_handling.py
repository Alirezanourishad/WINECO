# ──────────────────────────────────────────────────────────────
# outside_handling.py — DIGITAL TWIN VERSION
#   Same MQTT topics and timing as the physical Pi. Differences:
#     - BME680 reads → random temp in a realistic range.
#     - Stepper motor (shading) and piston GPIO calls → print()
#       so you can see the command + travel time on screen.
#     - BROKER points at the Docker MQTT service.
# ──────────────────────────────────────────────────────────────
import paho.mqtt.client as mqtt
import time
import random

# --- CONFIGURATION ---
BROKER = "inside-broker"   # Docker DNS name (was a hard-coded laptop IP on the real Pi)

# --- HARDWARE PINS (kept for reference, unused in the twin) ---
STEPPER_PINS = [17, 27, 22, 23]
PISTON_PINS = [5, 6]   # BCM 5 (Pin 29), BCM 6 (Pin 31)

# Half-step sequence for smooth rotation (kept for documentation parity)
STEP_SEQ = [
    [1,0,0,0], [1,1,0,0], [0,1,0,0], [0,1,1,0],
    [0,0,1,0], [0,0,1,1], [0,0,0,1], [1,0,0,1],
]

# --- STATE MANAGEMENT (Starting at 0%) ---
current_step_pos = 0
MAX_STEPS = 1024   # Half of the original 2048 so 100% turns half the way

current_piston_percent = 0.0
FULL_EXTENSION_TIME = 9.0   # 100% action takes exactly 9 seconds

def move_stepper_to(target_percent):
    """Twin: prints the move and updates the virtual position.
       Physical: drives 4 GPIO pins through STEP_SEQ at ~3 ms per step."""
    global current_step_pos
    try:
        val_percent = max(0, min(100, float(target_percent)))
        target_steps = int((val_percent / 100.0) * MAX_STEPS)
        steps_to_move = target_steps - current_step_pos

        # Only move if there is a functional difference
        if steps_to_move == 0:
            return

        print(f"🔄 Shading State: {int((current_step_pos/MAX_STEPS)*100)}% -> {val_percent}%")
        # In the twin we skip the per-step pin toggling; just update position.
        current_step_pos = target_steps
    except Exception as e:
        print(f"❌ Stepper Error: {e}")

def move_piston_to(target_percent):
    """Twin: prints the move and sleeps for the real travel time so the
       timing on the bus looks the same as the physical piston.
       Physical: drives an H-bridge for `duration` seconds."""
    global current_piston_percent
    try:
        target_val = max(0, min(100, float(target_percent)))
        diff = target_val - current_piston_percent

        # Avoid jittering for micro-adjustments under 1%
        if abs(diff) < 1.0:
            return

        # Time is strictly proportional to the difference from the past state
        duration = (abs(diff) / 100.0) * FULL_EXTENSION_TIME

        print(f"⚙️ Piston State: {current_piston_percent}% -> {target_val}% (Running for {duration:.2f}s)")

        # PHYSICAL: would energise PISTON_PINS to extend or retract here.
        time.sleep(duration)

        current_piston_percent = target_val
        print(f"✅ Piston movement finished at {current_piston_percent}%")

    except Exception as e:
        print(f"❌ Piston Error: {e}")

# --- BME680 SETUP (SIMULATED) ---
# Physical: i2c = busio.I2C(...); bme = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=0x77)
# Twin: just a marker so reads can pretend to succeed.
bme = "SIM_BME680"

# --- MQTT CALLBACKS ---
def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    if msg.topic == "shading_final_command":
        move_stepper_to(payload)
    elif msg.topic == "piston_final_command":
        move_piston_to(payload)

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ Connected to MQTT Broker")
        client.subscribe([("piston_final_command", 0), ("shading_final_command", 0)])

# --- MAIN EXECUTION ---
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, 1883)
client.loop_start()

last_valid_temp = 22.0

try:
    while True:
        try:
            # PHYSICAL: new_temp = round(bme.temperature, 1)
            # TWIN: random outdoor temp in a Torino-ish range
            new_temp = round(random.uniform(10.0, 30.0), 1)
            last_valid_temp = new_temp
        except:
            new_temp = last_valid_temp

        client.publish("sensor/outside_temp", new_temp)
        print(f"☀️ Outside Rasp: Published Temp {new_temp}")
        time.sleep(30)

except KeyboardInterrupt:
    print("Stopping application gracefully...")
    # PHYSICAL: GPIO.cleanup()
    client.loop_stop()
    client.disconnect()
