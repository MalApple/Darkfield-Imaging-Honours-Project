import time
import queue


class MockSerial:
    """
    Stand-in for serial.Serial() when no Arduino is connected.
    Mimics the pyserial interface.
    """

    def __init__(self, port=None, baudrate=9600, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True
        self._response_queue = queue.Queue()

    # Called by ArduinoController._send() ==========================
    def write(self, data):
        command = data.decode().strip()
        response = self._fake_response(command)
        if response:
            self._response_queue.put(response)


    # Called by ArduinoController._read_loop() ==========================
    @property
    def in_waiting(self):
        return 1 if not self._response_queue.empty() else 0

    def readline(self):
        if not self._response_queue.empty():
            line = self._response_queue.get()
            return (line + '\n').encode()
        return b''

    def close(self):
        self.is_open = False

    
    # Fake Arduino for testing ==========================
    def _fake_response(self, command):
        time.sleep(0.1)  # simulate real-world serial delay

        if command.startswith("UP"):
            steps = command.split(" ")[1] if " " in command else "?"
            return f"OK: moved up {steps}"
        elif command.startswith("DOWN"):
            steps = command.split(" ")[1] if " " in command else "?"
            return f"OK: moved down {steps}"
        elif command == "SWITCH":
            return "OK: switched"
        else:
            return "ERR: unknown command"