# SPDX-FileCopyrightText: 2019 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT

import board
import busio
from digitalio import DigitalInOut, Direction, Pull
import os
import adafruit_requests as requests
import adafruit_esp32spi.adafruit_esp32spi_socket as socket
from adafruit_esp32spi import adafruit_esp32spi
import adafruit_esp32spi.adafruit_esp32spi_wifimanager as wifimanager
import adafruit_esp32spi.adafruit_esp32spi_wsgiserver as server
import usb_hid
from adafruit_hid.mouse import Mouse
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS as KeyboardLayout
from adafruit_hid.keycode import Keycode

import storage
import time
import supervisor

buttonPin = DigitalInOut(board.GP3)
buttonPin.switch_to_input(pull=Pull.UP)

inputMode = 0 # 0 -> literal mode, 1 -> parsed mode

buttonStatus = False

try:
    import json as json_module
except ImportError:
    import ujson as json_module

time.sleep(.5)

mouse = Mouse(usb_hid.devices)
kbd = Keyboard(usb_hid.devices)
layout = KeyboardLayout(kbd)

supervisor.runtime.autoreload = False

# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise

print("Raspberry Pi RP2040 - ESP32 SPI webclient test")

# Raspberry Pi RP2040 Pinout
esp32_cs = DigitalInOut(board.GP13)
esp32_ready = DigitalInOut(board.GP14)
esp32_reset = DigitalInOut(board.GP15)

spi = busio.SPI(board.GP10, board.GP11, board.GP12)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

socket.set_interface(esp)
requests.set_socket(socket, esp)

if esp.status == adafruit_esp32spi.WL_IDLE_STATUS:
    print("ESP32 found and in idle mode")
print("Firmware vers.", esp.firmware_version)
print("MAC addr:", [hex(i) for i in esp.MAC_address])

for ap in esp.scan_networks():
    print("\t%s\t\tRSSI: %d" % (str(ap["ssid"], "utf-8"), ap["rssi"]))

print("Connecting to AP...")
wifi = wifimanager.ESPSPI_WiFiManager(esp, secrets)

while not esp.is_connected:
    try:
        # esp.connect_AP(secrets["ssid"], secrets["password"])
        wifi.connect()
    except OSError as e:
        print("could not connect to AP, retrying: ", e)
        continue
print("Connected to", str(esp.ssid, "utf-8"), "\tRSSI:", esp.rssi)
print("My IP address is", esp.pretty_ip(esp.ip_address))

class SimpleWSGIApplication:
    """
    An example of a simple WSGI Application that supports
    basic route handling and static asset file serving for common file types
    """

    INDEX = "/index.html"
    CHUNK_SIZE = 8912  # max number of bytes to read at once when reading files

    def __init__(self, static_dir=None, debug=False):
        self._debug = debug
        self._listeners = {}
        self._start_response = None
        self._static = static_dir
        if self._static:
            self._static_files = ["/" + file for file in os.listdir(self._static)]

    def __call__(self, environ, start_response):
        """
        Called whenever the server gets a request.
        The environ dict has details about the request per wsgi specification.
        Call start_response with the response status string and headers as a list of tuples.
        Return a single item list with the item being your response data string.
        """
        if self._debug:
            self._log_environ(environ)

        self._start_response = start_response
        status = ""
        headers = []
        resp_data = []

        key = self._get_listener_key(
            environ["REQUEST_METHOD"].lower(), environ["PATH_INFO"]
        )
        if key in self._listeners:
            status, headers, resp_data = self._listeners[key](environ)
        if environ["REQUEST_METHOD"].lower() == "get" and self._static:
            path = environ["PATH_INFO"]
            if path in self._static_files:
                status, headers, resp_data = self.serve_file(
                    path, directory=self._static
                )
            elif path == "/" and self.INDEX in self._static_files:
                status, headers, resp_data = self.serve_file(
                    self.INDEX, directory=self._static
                )

        self._start_response(status, headers)
        return resp_data

    def on(self, method, path, request_handler):
        """
        Register a Request Handler for a particular HTTP method and path.
        request_handler will be called whenever a matching HTTP request is received.
        request_handler should accept the following args:
            (Dict environ)
        request_handler should return a tuple in the shape of:
            (status, header_list, data_iterable)
        :param str method: the method of the HTTP request
        :param str path: the path of the HTTP request
        :param func request_handler: the function to call
        """
        self._listeners[self._get_listener_key(method, path)] = request_handler

    def serve_file(self, file_path, directory=None):
        status = "200 OK"
        headers = [("Content-Type", self._get_content_type(file_path))]

        full_path = file_path if not directory else directory + file_path

        def resp_iter():
            with open(full_path, "rb") as file:
                while True:
                    chunk = file.read(self.CHUNK_SIZE)
                    if chunk:
                        yield chunk
                    else:
                        break

        return (status, headers, resp_iter())

    def _log_environ(self, environ):  # pylint: disable=no-self-use
        print("environ map:")
        for name, value in environ.items():
            print(name, value)

    def _get_listener_key(self, method, path):  # pylint: disable=no-self-use
        return "{0}|{1}".format(method.lower(), path)

    def _get_content_type(self, file):  # pylint: disable=no-self-use
        ext = file.split(".")[-1]
        if ext in ("html", "htm"):
            return "text/html"
        if ext == "js":
            return "application/javascript"
        if ext == "css":
            return "text/css"
        if ext in ("jpg", "jpeg"):
            return "image/jpeg"
        if ext == "png":
            return "image/png"
        return "text/plain"


static = "/static"
try:
    static_files = os.listdir(static)
    if "index.html" not in static_files:
        raise RuntimeError(
            """
            This example depends on an index.html, but it isn't present.
            Please add it to the {0} directory""".format(
                static
            )
        )
except OSError as e:
    raise RuntimeError(
        """
        This example depends on a static asset directory.
        Please create one named {0} in the root of the device filesystem.""".format(
            static
        )
    ) from e


led = DigitalInOut(board.GP2)
led.direction = Direction.OUTPUT

pressCommands = {
    'WINDOWS': Keycode.WINDOWS, 'GUI': Keycode.GUI,
    'APP': Keycode.APPLICATION, 'MENU': Keycode.APPLICATION, 'SHIFT': Keycode.SHIFT,
    'ALT': Keycode.ALT, 'CONTROL': Keycode.CONTROL, 'CTRL': Keycode.CONTROL,
    'DOWNARROW': Keycode.DOWN_ARROW, 'DOWN': Keycode.DOWN_ARROW, 'LEFTARROW': Keycode.LEFT_ARROW,
    'LEFT': Keycode.LEFT_ARROW, 'RIGHTARROW': Keycode.RIGHT_ARROW, 'RIGHT': Keycode.RIGHT_ARROW,
    'UPARROW': Keycode.UP_ARROW, 'UP': Keycode.UP_ARROW, 'BREAK': Keycode.PAUSE,
    'PAUSE': Keycode.PAUSE, 'CAPSLOCK': Keycode.CAPS_LOCK, 'CAPS': Keycode.CAPS_LOCK, 'DELETE': Keycode.DELETE,
    'END': Keycode.END, 'ESC': Keycode.ESCAPE, 'ESCAPE': Keycode.ESCAPE, 'HOME': Keycode.HOME,
    'INSERT': Keycode.INSERT, 'NUMLOCK': Keycode.KEYPAD_NUMLOCK, 'PAGEUP': Keycode.PAGE_UP,
    'PAGEDOWN': Keycode.PAGE_DOWN, 'PRINTSCREEN': Keycode.PRINT_SCREEN, 'ENTER': Keycode.ENTER,
    'SCROLLLOCK': Keycode.SCROLL_LOCK, 'SPACE': Keycode.SPACE, 'TAB': Keycode.TAB,
    'BACKSPACE': Keycode.BACKSPACE,
    'A': Keycode.A, 'B': Keycode.B, 'C': Keycode.C, 'D': Keycode.D, 'E': Keycode.E,
    'F': Keycode.F, 'G': Keycode.G, 'H': Keycode.H, 'I': Keycode.I, 'J': Keycode.J,
    'K': Keycode.K, 'L': Keycode.L, 'M': Keycode.M, 'N': Keycode.N, 'O': Keycode.O,
    'P': Keycode.P, 'Q': Keycode.Q, 'R': Keycode.R, 'S': Keycode.S, 'T': Keycode.T,
    'U': Keycode.U, 'V': Keycode.V, 'W': Keycode.W, 'X': Keycode.X, 'Y': Keycode.Y,
    'Z': Keycode.Z, 'F1': Keycode.F1, 'F2': Keycode.F2, 'F3': Keycode.F3,
    'F4': Keycode.F4, 'F5': Keycode.F5, 'F6': Keycode.F6, 'F7': Keycode.F7,
    'F8': Keycode.F8, 'F9': Keycode.F9, 'F10': Keycode.F10, 'F11': Keycode.F11,
    'F12': Keycode.F12,
}

def convertLine(line):
    newline = []
    # print(line)
    # loop on each key - the filter removes empty values
    for key in line:
        key = key.upper()
        # find the keycode for the command in the list
        command_keycode = pressCommands.get(key, None)
        if command_keycode is not None:
            # if it exists in the list, use it
            newline.append(command_keycode)
        elif hasattr(Keycode, key):
            # if it's in the Keycode module, use it (allows any valid keycode)
            newline.append(getattr(Keycode, key))
        else:
            # if it's not a known key name, show the error for diagnosis
            print(f"Unknown key: <{key}>")
    # print(newline)
    return newline

def runScriptLine(line):
    for k in line:
        kbd.press(k)
    kbd.release_all()


def serve_index(environ):
    return web_app.serve_file("static/index.html")

def switch_led(environ):
    led.value = not led.value
    return ("200 OK", [], [])

def parse_move_command(command):
    if command.get("body").get("type") == "LEFT":
        mouse.move(-1*int(command.get("body").get("magnitude")), 0)
    if command.get("body").get("type") == "RIGHT":
        mouse.move(int(command.get("body").get("magnitude")), 0)
    if command.get("body").get("type") == "UP":
        mouse.move(0, -1*int(command.get("body").get("magnitude")))
    if command.get("body").get("type") == "DOWN":
        mouse.move(0, int(command.get("body").get("magnitude")))
        
def parse_click_command(command):
    if command.get("body").get("type") == "LEFT":
        if command.get("body").get("action") == "CLICK":
            mouse.click(Mouse.LEFT_BUTTON)
        elif command.get("body").get("action") == "HOLD":
            mouse.press(Mouse.LEFT_BUTTON)
        elif command.get("body").get("action") == "RELEASE":
            mouse.release(Mouse.LEFT_BUTTON)
    elif command.get("body").get("type") == "MIDDLE":
        if command.get("body").get("action") == "CLICK":
            mouse.click(Mouse.MIDDLE_BUTTON)
        elif command.get("body").get("action") == "HOLD":
            mouse.press(Mouse.MIDDLE_BUTTON)
        elif command.get("body").get("action") == "RELEASE":
            mouse.release(Mouse.MIDDLE_BUTTON)
    elif command.get("body").get("type") == "RIGHT":
        if command.get("body").get("action") == "CLICK":
            mouse.click(Mouse.RIGHT_BUTTON)
        elif command.get("body").get("action") == "HOLD":
            mouse.press(Mouse.RIGHT_BUTTON)
        elif command.get("body").get("action") == "RELEASE":
            mouse.release(Mouse.RIGHT_BUTTON)
        
def parse_press_command(command):
    runScriptLine(convertLine(command.get("body").get("keycodes")))

def parse_type_command(command):
    layout.write(command.get("body").get("text"))

def parse_mode_command(command):
    global inputMode
    
    if command.get("body").get("type") == "LITERAL":
        inputMode = 0
    elif command.get("body").get("type") == "PARSED":
        inputMode = 1
        
def parse_scroll_command(command):
    if command.get("body").get("type") == "UP":
        mouse.move(0, 0, int(command.get("body").get("magnitude")))
    elif command.get("body").get("type") == "DOWN":
        mouse.move(0, 0, -1*int(command.get("body").get("magnitude")))
    
def execute_instructions(environ):
    print("Received instructions")
    json = json_module.loads(environ["wsgi.input"].getvalue())
    
    try:
        for command in json.get("commands"):
            if command.get("type") == "MOVE":
                parse_move_command(command)
            elif command.get("type") == "CLICK":
                parse_click_command(command)
            elif command.get("type") == "PRESS":
                parse_press_command(command)
            elif command.get("type") == "TYPE":
                parse_type_command(command)
            elif command.get("type") == "MODE":
                parse_mode_command(command)
            elif command.get("type") == "SCROLL":
                parse_scroll_command(command)
                
            if command.get("type") != "CLICK":
                time.sleep(1)
            
        return ("200 OK", [], [])
    except:
        return ("400 Bad Request", [], [])
        

def get_input_mode(environ):
    global inputMode
    
    print("Sending input mode")
    return ("200 OK", [], [str(inputMode)])

def get_button_status(environ):
    global buttonStatus
    
    print("Sending button status")
    return ("200 OK", [], [str(buttonStatus)])

web_app = SimpleWSGIApplication(static_dir=static)

web_app.on("GET", "/", serve_index)
web_app.on("POST", "/", switch_led)
web_app.on("POST", "/execute", execute_instructions)
web_app.on("GET", "/getInputMode", get_input_mode)

server.set_interface(esp)
wsgiServer = server.WSGIServer(80, application=web_app)

wsgiServer.start()
print("Web server started")

#print(esp.ping(TEXT_URL))
while True:
    # Our main loop where we have the server poll for incoming requests
    try:
        wsgiServer.update_poll()


    except OSError as e:
        print("Failed to update server, restarting ESP32\n", e)
        wifi.reset()
        continue
 
