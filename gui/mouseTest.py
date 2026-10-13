import sys
import time

from pynput.mouse import Button, Controller
from screeninfo import get_monitors

#Working on windows, do not run within vinv. Later on this code will be transfered to linux 

# mouse = Controller()

# screen = get_monitors()[0]

# x = int(screen.width * 0.5)
# y = int(screen.height * 0.5)

# print(x, y)

# mouse.position = (x, y)
# mouse.click(Button.left, 1)

# Make coordinates match real pixels on Windows with display scaling
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()

DELAY = 3  # seconds between each click

# Click positions as fractions of the screen (x, y), measured from a
STEPS = [
    ("Moving Screen",       321 / 1680, 367 / 1050),
    ("Move Out of Frame",   1416 / 1680, 160 / 1050),
    ("Imaging",             209 / 1680, 367 / 1050),
    ("Saving",              97 / 1680, 367 / 1050),
]

mouse = Controller()

monitors = get_monitors()
screen = next((m for m in monitors if m.is_primary), monitors[0]) #Picks primary monitor if there is more than one, otherwise picks the first monitor
print(f"Screen: {screen.width} x {screen.height} at ({screen.x}, {screen.y})")

print(f"Starting in {DELAY} seconds...")
time.sleep(DELAY)

for i, (label, fx, fy) in enumerate(STEPS):
    x = screen.x + int(screen.width * fx)
    y = screen.y + int(screen.height * fy)
    print(f"{label} -> ({x}, {y})")
    mouse.position = (x, y)
    time.sleep(0.2)  # let the cursor settle before clicking
    mouse.click(Button.left, 1)
    if i < len(STEPS) - 1:
        time.sleep(DELAY)

print("Done")