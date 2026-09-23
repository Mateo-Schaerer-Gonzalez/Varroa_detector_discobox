"""The Discobox fan and LEDs, driven by an Arduino over a serial port.

The protocol is the Discobox app's (src/controller.py): 9600 baud, one command
per packet of three bytes, [command, value, command XOR value]. What is new here
is only that no window pops up to choose the port: it is found automatically, as
the app does when there is a single Arduino, or given by name.

A run with no controller connected uses NoLights, which accepts every command and
does nothing -- as the Discobox app does when it finds no Arduino.
"""

import logging
import threading

_logger = logging.getLogger(__name__)

COMMANDS = {
    "vent": 0x00,
    "led1": 0x01,
    "led2": 0x02,
    "led1_on_off": 0x03,
    "led2_on_off": 0x04,
    "led_on_off": 0x05,
    "vent_on_off": 0x06,
    "all_off": 0x07,
}
DEVICES = ("vent", "led1", "led2")
DEVICE_NAMES = {"vent": "Fan", "led1": "LED 1", "led2": "LED 2"}
BAUD_RATE = 9600


def packet(command, value):
    """One command as the Arduino expects it."""
    return bytes([COMMANDS[command], value, COMMANDS[command] ^ value])


def serial_ports():
    """Every serial port, with whether it looks like the Discobox's Arduino (as the
    Discobox app decides: "arduino" in its manufacturer)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [
        {
            "device": port.device,
            "description": port.description or "",
            "manufacturer": port.manufacturer or "",
            "arduino": "arduino" in (port.manufacturer or "").lower(),
        }
        for port in list_ports.comports()
    ]


def choose_port(port):
    """The serial port to use: `port` itself; with "auto", the only Arduino (None
    when there is none); with None or "none", no controller."""
    if port in (None, "", "none"):
        return None
    if port != "auto":
        return port
    arduinos = [p["device"] for p in serial_ports() if p["arduino"]]
    if len(arduinos) > 1:
        raise ValueError(f"Several Arduinos are connected ({', '.join(arduinos)}); choose the Discobox's port.")
    return arduinos[0] if arduinos else None


class Lights:
    """The fan and the two LEDs. Remembers what it last told each device, so the
    page can show it. Commands may come from several threads (the test run, the
    settings page); they are sent one at a time."""

    def __init__(self, port=None, connection=None):
        """Open `port`, or use `connection`, anything with write() and flush()
        (a test's stand-in for the port)."""
        self.port = port
        self._lock = threading.Lock()
        self._reading = False
        self.on = {device: False for device in DEVICES}
        self.level = {device: 0 for device in DEVICES}
        if connection is None:
            import serial

            connection = serial.Serial(port=port, baudrate=BAUD_RATE)
            # The Discobox app keeps reading what the Arduino sends, so its buffer never fills.
            self._reading = True
            threading.Thread(target=self._drain, args=(connection,), daemon=True).start()
        self.connection = connection

    @property
    def connected(self):
        return True

    def _drain(self, connection):
        while self._reading:
            try:
                connection.read(1)
            except Exception:
                return

    def _send(self, *packets):
        with self._lock:
            for data in packets:
                self.connection.write(data)
            self.connection.flush()

    def set_level(self, device, level):
        """Set a device's intensity, 0-255, without switching it on or off."""
        level = int(level)
        if not 0 <= level <= 255:
            raise ValueError("An intensity must be between 0 and 255.")
        self._send(packet(device, level))
        self.level[device] = level

    def switch(self, device, on, level=None):
        """Switch a device on or off, and set its intensity, as the Discobox app
        does: the on/off command first, then the intensity."""
        level = self.level[device] if level is None else int(level)
        self._send(packet(f"{device}_on_off", 0x01 if on else 0x00), packet(device, level))
        self.on[device] = bool(on)
        self.level[device] = level

    def switch_off(self, device):
        self._send(packet(f"{device}_on_off", 0x00))
        self.on[device] = False

    def all_off(self):
        self._send(packet("all_off", 0x00))
        for device in DEVICES:
            self.on[device] = False

    def state(self):
        return {"connected": self.connected, "port": self.port,
                **{device: {"on": self.on[device], "level": self.level[device]} for device in DEVICES}}

    def close(self):
        try:
            self.all_off()
        finally:
            self._reading = False
            close = getattr(self.connection, "close", None)
            if close:
                close()


class NoLights(Lights):
    """No controller: every command is accepted and does nothing."""

    def __init__(self):
        class _Nowhere:
            def write(self, data):
                pass

            def flush(self):
                pass

        super().__init__(port=None, connection=_Nowhere())

    @property
    def connected(self):
        return False


def open_lights(port="auto"):
    """The fan and LEDs on `port` (see choose_port), or NoLights."""
    device = choose_port(port)
    if device is None:
        _logger.warning("No fan/LED controller: the test run goes ahead without the fan and LEDs.")
        return NoLights()
    return Lights(device)
