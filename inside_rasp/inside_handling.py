# ──────────────────────────────────────────────────────────────
# inside_handling.py  —  DIGITAL TWIN VERSION
#   Same logic, KPIs, hysteresis, and MQTT topics as the physical
#   Pi. The only differences:
#     - Sensor reads (BME680, TSL2591, CO2 I2C, Arduino serial) are
#       replaced by `random` so the script runs anywhere.
#     - Actuator writes (PWM fan, sysfs LEDs) are replaced by
#       print() so you can see what would happen on the real Pi.
#     - BROKER points at the Docker MQTT service.
# ──────────────────────────────────────────────────────────────
import paho.mqtt.client as mqtt
import time
import random
import requests

# --- CONFIGURATION ---
BROKER = "inside-broker"   # Docker DNS name (was "localhost" on the real Pi)
PORT = 1883
LAT, LON = 45.0545, 7.6835

# Kept from the physical version so logic that references these still works
CO2_DEVICE_ADDR = 0x28
FAN_PIN = 14
CHIP = "/sys/class/pwm/pwmchip0"
PWM0_PATH = CHIP + "/pwm0"
PWM1_PATH = CHIP + "/pwm1"
FREQ = 1000
PERIOD = int(1e9 / FREQ)

# --- HYSTERESIS SETTINGS ---
LUX_THRESHOLD = 50.0
CMD_THRESHOLD = 5.0

# --- STATE TRACKING ---
state = {
    "led1_pct": 0.0,
    "led2_pct": 0.0,
    "last_lux1": 0.0,
    "last_lux2": 0.0
}

# --- HARDWARE SETUP (SIMULATED — no I2C / GPIO in the container) ---
# On the real Pi this is where i2c, smbus and gpiozero are initialised.
# In the twin we just keep a virtual fan state.
fan_value = 0.0

# --- HELPERS ---
def w_sysfs(path, value):
    # On the real Pi: writes a PWM duty cycle to sysfs.
    # In the twin: just a no-op (the LED command is printed by on_message).
    pass

def setup_pwm_led(pwm_path, idx):
    # On the real Pi: exports the PWM channel and enables it.
    # In the twin: nothing to do.
    pass

def map_fan_speed(user_input):
    if user_input <= 0: return 0.0
    mapped = 96.0 + (user_input - 0) * (100.0 - 96.0) / (100.0 - 0)
    return mapped / 100.0

def get_co2_reading():
    # PHYSICAL: reads I2C registers 0x05/0x06 from the CO2 sensor.
    # TWIN: random value in a realistic indoor range.
    return random.randint(400, 2500)

def get_weather_data():
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current_weather=true&daily=temperature_2m_mean&past_days=7"
        res = requests.get(url, timeout=10).json()
        t_out = res['current_weather']['temperature']
        t_rm = sum(res['daily']['temperature_2m_mean']) / 8
        return t_out, t_rm
    except: return 15.0, 15.0

# --- UPDATED KPI CALCULATION FUNCTION (identical to physical) ---
def calculate_kpis(temp, co2, lux1, lux2, t_out, t_rm):
    # 1. Piecewise Thermal KPI Logic based on fuzzy comfort curves
    t_in = temp

    if t_in <= 20:
        thermal_kpi = 0.0
    elif 20 < t_in < 22:
        # Climbs 50% per degree from 20°C (0%) up to 22°C (100%)
        thermal_kpi = 100.0 - 50.0 * (22.0 - t_in)
    elif 22 <= t_in <= 26:
        # Your strict perfect comfort plateau
        thermal_kpi = 100.0
    elif 26 < t_in < 40:
        # Drops gently (~7.14% per degree) from 26°C (100%) down to 40°C (0%)
        thermal_kpi = 100.0 - (100.0 / 14.0) * (t_in - 26.0)
    else:  # t_in >= 40
        thermal_kpi = 0.0

    # --- NEW EXPANDED IAQ CO2 MAPPING LOGIC (400 to 3500 ppm) ---
    if co2 <= 400:
        iaq_kpi = 100.0
    elif 400 < co2 < 3500:
        # Maps smoothly from 400ppm (100%) down to 3500ppm (0%)
        iaq_kpi = 100.0 - ((co2 - 400) / 3100.0) * 100.0
    else:  # co2 >= 3500
        iaq_kpi = 0.0

    # 3. Original Visual KPI Logic
    avg_lux = (lux1 + lux2) / 2
    visual_kpi = max(0, min(100, 100 - (abs(avg_lux - 400) / 4)))

    return round(thermal_kpi, 1), round(iaq_kpi, 1), round(visual_kpi, 1)

# --- MQTT CALLBACKS ---
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ Inside Handling System Fully Operational...")
        client.subscribe("fan_final_command")
        client.subscribe("led1_final_command")
        client.subscribe("led2_final_command")

def on_message(client, userdata, msg):
    global fan_value
    try:
        val = float(msg.payload.decode())
        if msg.topic == "fan_final_command":
            # PHYSICAL: fan.value = map_fan_speed(val)
            # TWIN: just record and print
            fan_value = map_fan_speed(val)
            print(f"📥 MQTT COMMAND -> FAN: {val}%   (sim duty = {fan_value:.3f})")
        elif msg.topic == "led1_final_command":
            if abs(val - state["led1_pct"]) >= CMD_THRESHOLD:
                duty = int(PERIOD * val / 100)
                w_sysfs(PWM1_PATH + "/duty_cycle", duty)   # no-op in twin
                state["led1_pct"] = val
                print(f"📥 MQTT COMMAND -> LED1: {val}%   (sim duty = {duty})")
        elif msg.topic == "led2_final_command":
            if abs(val - state["led2_pct"]) >= CMD_THRESHOLD:
                duty = int(PERIOD * val / 100)
                w_sysfs(PWM0_PATH + "/duty_cycle", duty)   # no-op in twin
                state["led2_pct"] = val
                print(f"📥 MQTT COMMAND -> LED2: {val}%   (sim duty = {duty})")
    except Exception as e:
        print(f"❌ Error: {e}")

# --- MAIN SETUP ---
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_start()

setup_pwm_led(PWM0_PATH, 0)   # no-op in twin
setup_pwm_led(PWM1_PATH, 1)   # no-op in twin

# In the physical version: try BME680 at 0x76 then 0x77, TSL2591, Arduino serial.
# In the twin: just placeholders that "succeed".
bme = "SIM_BME680"
tsl = "SIM_TSL2591"
ser = "SIM_ARDUINO"

last_valid = {"temp": 22.0, "co2": 800, "lux1": 300.0, "lux2": 300.0}

# --- MAIN LOOP ---
try:
    while True:
        t_out, t_rm = get_weather_data()

        # 1. READ ALL SENSORS (TWIN: random in realistic ranges)
        raw_lux2 = round(random.uniform(200, 600), 1)          # TSL2591
        raw_temp = round(random.uniform(18.0, 32.0), 2)        # BME680
        raw_co2  = get_co2_reading()                           # CO2 I2C

        # Arduino serial → Lux1 (with the same parsing fallback structure)
        raw_lux1 = round(random.uniform(200, 600), 1)

        # 2. DATA SHIELDING
        lux1 = raw_lux1 if raw_lux1 is not None else last_valid["lux1"]
        lux2 = raw_lux2 if raw_lux2 is not None else last_valid["lux2"]
        temp = raw_temp if raw_temp is not None else last_valid["temp"]
        co2  = raw_co2  if raw_co2  is not None else last_valid["co2"]
        last_valid.update({"lux1": lux1, "lux2": lux2, "temp": temp, "co2": co2})

        # 3. COMPUTE KPIs
        th_kpi, iaq_kpi, vis_kpi = calculate_kpis(temp, co2, lux1, lux2, t_out, t_rm)

        # 4. PUBLISH TELEMETRY (Only if Lux changes significantly)
        if abs(lux1 - state["last_lux1"]) > LUX_THRESHOLD or abs(lux2 - state["last_lux2"]) > LUX_THRESHOLD:
            client.publish("sensor/lux_zone1", lux1)
            client.publish("sensor/lux_zone2", lux2)
            state["last_lux1"] = lux1
            state["last_lux2"] = lux2

        client.publish("sensor/inside_temp", temp)
        client.publish("sensor/inside_co2", co2)
        client.publish("kpi/thermal", th_kpi)
        client.publish("kpi/iaq", iaq_kpi)
        client.publish("kpi/visual", vis_kpi)

        # 5. PRINTING STYLE
        print("-" * 40)
        print(f"📊 DATA -> Temp: {temp:.1f}°C | CO2: {co2}ppm | Lux1: {lux1:.1f} | Lux2: {lux2:.1f}")
        print(f"🏆 KPIs -> Thermal: {th_kpi}% | IAQ: {iaq_kpi}% | Visual: {vis_kpi}%")
        print("📡 Telemetry sent. Monitoring Decision Algorithm for commands...")

        time.sleep(20)

except KeyboardInterrupt:
    # PHYSICAL: shut down fan, disable LED PWM channels.
    # TWIN: just stop the MQTT loop.
    fan_value = 0
    client.loop_stop()
