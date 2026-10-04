import pyautogui
import time

x, y = 500, 500  # pixel to check

while True:
    colour = pyautogui.pixel(x, y)
    print(f"Pixel colour: {colour}")
    time.sleep(1)   