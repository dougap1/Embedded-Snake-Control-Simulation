import serial
import time

ser = serial.Serial("COM4", 115200, timeout=1)

time.sleep(2)  # give board time to reset

while True:
    line = ser.readline().decode(errors="ignore").strip()
    if line:
        print(line)
