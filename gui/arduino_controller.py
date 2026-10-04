import serial
import threading
import time

#Handles serial communication with the Arduino.
class ArduinoController:

    # port: e.g. 'COM3' (Windows) or '/dev/ttyUSB0' (Linux/Mac)
    def __init__(self, port, baudrate=9600, timeout=1, on_position_change=None, on_message=None, simulate=False):
    
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.on_message = on_message
        self.simulate = simulate

        self.on_position_change = on_position_change

        self.serial_conn = None
        self._reader_thread = None
        self._running = False

        self.position = 0

    
    # Connection management ==========================
    def connect(self):
        #Open the serial connection and start listening for messages
        if self.simulate:
            from mock_serial import MockSerial
            self.serial_conn = MockSerial(self.port, self.baudrate, timeout=self.timeout)
        else:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            time.sleep(2)  # Arduino resets on connect, give it time to boot

        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def disconnect(self):
        #Stop listening and close the serial connection
        self._running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

    def is_connected(self):
        return self.serial_conn is not None and self.serial_conn.is_open

    # Position ==========================
    def _set_position(self, value):
        self.position = value
        if self.on_position_change:
            self.on_position_change(self.position)

    # Reading ==========================
    def _read_loop(self):
        while self._running:
            if self.serial_conn and self.serial_conn.in_waiting:
                line = self.serial_conn.readline().decode(errors='ignore').strip()
                if line == "LIMIT_BOTTOM":
                    self._set_position(0)
                if line and self.on_message:
                    self.on_message(line)

    # Sending commands  ==========================
    def _send(self, command):
        if not self.is_connected():
            raise ConnectionError("Arduino is not connected.")
        self.serial_conn.write((command + '\n').encode())

    def move_up(self, steps):
        self._send(f"UP {steps}")
        self._set_position(self.position + steps)
        print(f"Moved up by {steps}, position = {self.position}")

    def move_down(self, steps):
        self._send(f"DOWN {steps}")
        self._set_position(max(0, self.position - steps))
        print(f"Moved down by {steps}, position = {self.position}")

    def switch_screen(self):
        self._send("SWITCH")

    def home(self):
        self._send("HOME")