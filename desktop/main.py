from machine import ADC, Pin, time_pulse_us, PWM
import time
import sys
import select

# Debugging statement to ensure this file is running in the background
print("MAIN FILE IS RUNNING!!")

# Joystick X-axis
x_axis = ADC(Pin(28))

# Ultrasonic sensor
TRIG_PIN = 3
ECHO_PIN = 22

trigger = Pin(TRIG_PIN, Pin.OUT)
echo = Pin(ECHO_PIN, Pin.IN)

# Temperature sensor
temp_adc = ADC(27)

# Red LED for game over
red_led = Pin(2, Pin.OUT)
red_led.value(0)

# Green LED for game running status
green_led = Pin(9, Pin.OUT)
green_led.value(0)

# Speaker
buzzer = PWM(Pin(1))
buzzer.duty_u16(0)

# Boot light at startup
def boot_light():
    for _ in range(3):
        green_led.value(1)
        time.sleep(0.15)
        green_led.value(0)
        time.sleep(0.15)

    green_led.value(1)  # stay on when system is running

# Read temperature
def read_temp_c():
    raw = temp_adc.read_u16()
    voltage = raw / 65535 * 3.3
    temp = -29.78 * voltage + 73.97

    return temp

# Get distance from ultrasonic sensor
def get_distance_cm():
    trigger.value(0)
    time.sleep_us(5)
    trigger.value(1)
    time.sleep_us(10)
    trigger.value(0)

    duration = time_pulse_us(echo, 1, 30000)

    if duration < 0:
        return None

    return int((duration / 2) / 29.1)

# Play sound each time an item is eaten
def play_eat():
    buzzer.freq(1000)
    buzzer.duty_u16(30000)
    time.sleep(0.05)
    buzzer.duty_u16(0)

# Sound when game ends
def play_gameover():
    for freq in [600, 400, 200]:
        buzzer.freq(freq)
        buzzer.duty_u16(30000)
        time.sleep(0.15)
        buzzer.duty_u16(0)
        time.sleep(0.05)

# Handling LED output based on game message on the screen
def handle_game_messages():
    if select.select([sys.stdin], [], [], 0)[0]:
        msg = sys.stdin.readline().strip()

        if msg == "EAT":
            play_eat()

        elif msg == "GAMEOVER":
            red_led.value(1)
            green_led.value(0)
            play_gameover()

        elif msg == "RESET":
            red_led.value(0)
            green_led.value(1)
            buzzer.duty_u16(0)
            
# Initial boot to blink green LED
boot_light()

# Board continuously runs this loop during gameplay
while True:
    # Read messages coming from the PyQt game
    handle_game_messages()

    # Joystick direction
    x = x_axis.read_u16()

    if x < 20000:
        print("DIR:L")
    elif x > 45000:
        print("DIR:R")
    else:
        print("DIR:N")

    # Ultrasonic distance
    d = get_distance_cm()

    if d is not None:
        print("DIST:{}".format(d))

    # Temperature
    temp = read_temp_c()
    print("TEMP:{:.1f}".format(temp))

    time.sleep(0.1)
