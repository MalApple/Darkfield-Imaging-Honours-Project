from pynput.mouse import Button, Controller
from screeninfo import get_monitors

#Working on windows, do not run within vinv. Later on this code will be transfered to linux 

mouse = Controller()

screen = get_monitors()[0]

x = int(screen.width * 0.5)
y = int(screen.height * 0.5)

print(x, y)

mouse.position = (x, y)
mouse.click(Button.left, 1)
