# =============================================================
# CLIENTE TCP PARA BROKER JSON (sin WebSocket, sin HTTP)
# Envía frames de la cámara como PUB "camera/frame"
# =============================================================

import network, time, sys, gc
import usocket as socket
import ubinascii
import json
from machine import Pin, I2C, PWM, Timer
from ov7670_wrapper import *
import _thread

timer_flag = False
# ----------------- CONFIG WIFI -----------------
SSID = "PEREZ"
with open(".env") as f:
    PASSWORD = f.read().strip()

print("Conectando a WiFi...")
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
if not wlan.isconnected():
    wlan.connect(SSID, PASSWORD)
    timeout = time.time() + 15
    while not wlan.isconnected():
        if time.time() > timeout:
            raise RuntimeError("No se pudo conectar a WiFi")
        time.sleep(0.5)
print("✅ WiFi OK, IP:", wlan.ifconfig()[0])

# ----------------- CONFIG BROKER TCP -----------------
# 👉 Usa la IPv4 de tu PC: 192.168.1.3 (según tu ipconfig)
BROKER_HOST = "192.168.1.3"
BROKER_PORT = 5051          # puerto del Broker TCP (Tkinter)

TOPIC_FRAME = "UDFJC/emb1/robot0/camera/frame"
SEND_INTERVAL = 3.0         # segundos entre envíos

# ----------------- CÁMARA OV7670 -----------------
WIDTH = 160
HEIGHT = 120
BUFSZ = WIDTH * HEIGHT * 2
buf = bytearray(BUFSZ)

print("Configurando MCLK para OV7670 en GP22...")
pwm = PWM(Pin(22))
pwm.freq(30_000_000)
pwm.duty_u16(32768)

print("Inicializando I2C y OV7670...")
i2c = I2C(0, freq=400_000, scl=Pin(13), sda=Pin(12))

try:
    ov7670 = OV7670Wrapper(
        i2c_bus=i2c,
        mclk_pin_no=22,
        pclk_pin_no=21,
        data_pin_base=2,
        vsync_pin_no=17,
        href_pin_no=26,
        reset_pin_no=14,
        shutdown_pin_no=15,
    )
    ov7670.wrapper_configure_rgb()
    ov7670.wrapper_configure_base()
    w, h = ov7670.wrapper_configure_size(OV7670_WRAPPER_SIZE_DIV4)
    ov7670.wrapper_configure_test_pattern(OV7670_WRAPPER_TEST_PATTERN_NONE)
    print("✅ OV7670 OK, resolución:", w, "x", h)

    def get_frame():
        ov7670.capture(buf)
        return buf

except Exception as e:
    print("❌ Error al inicializar cámara:", e)
    # Generar patrón simple si no hay cámara
    def get_frame():
        global buf
        for i in range(len(buf)):
            buf[i] = i & 0xFF
        return buf

# ----------------- CLIENTE TCP AL BROKER -----------------

def connect_to_broker():
    """Abre un socket TCP al broker y lo devuelve."""
    addr = socket.getaddrinfo(BROKER_HOST, BROKER_PORT)[0][-1]
    s = socket.socket()
    s.connect(addr)
    s.settimeout(5)
    print("🔌 Conectado al broker TCP:", BROKER_HOST, BROKER_PORT)
    return s

def send_json_line(sock, obj):
    """Envía un JSON + '\n' por el socket (protocolo del Broker)."""
    line = json.dumps(obj) + "\n"
    # Enviar todo (puede que send no mande todo en una sola llamada)
    data = line.encode("utf-8")
    total = 0
    while total < len(data):
        total += sock.send(data[total:])

def publish_frame(sock):
    """Captura un frame, lo codifica y lo envía como PUB al broker."""
    frame = get_frame()
    # Codificar en base64 para meterlo en JSON
    frame_b64 = ubinascii.b2a_base64(frame).decode().strip()

    pkt = {
        "action": "PUB",
        "topic": TOPIC_FRAME,
        "data": {
            "w": WIDTH,
            "h": HEIGHT,
            "format": "RGB565",
            "ts": time.time(),
            "frame_b64": frame_b64,
        },
    }
    send_json_line(sock, pkt)
    print("📤 Frame enviado, tamaño:", len(frame), "bytes")

# ----------------- BUCLE PRINCIPAL -----------------

def main_loop():
    global timer_flag
    sock = None
    while True:
        try:
            if sock is None:
                sock = connect_to_broker()
            publish_frame(sock)
            time.sleep(SEND_INTERVAL)
            if timer_flag:
                timer_flag=False
                send_json_line(sock,{
                                "action": "PUB",
                                "topic": "UDFJC/emb1/robot0/debug/msg",
                                "data": {"text":"RPi WatchDog"}})
                print("RPi WatchDog")
        except Exception as e:
            print("⚠ Error con broker:", e)
            # Cerrar socket y reintentar luego
            try:
                if sock:
                    sock.close()
            except:
                pass
            sock = None
            time.sleep(3)

# Opcional: podrías correrlo en un hilo
# _thread.start_new_thread(main_loop, ())

def timer_callback(timer):
    global timer_flag
    timer_flag = True
    
my_timer = machine.Timer()
my_timer.init(mode=machine.Timer.PERIODIC, period=10000, callback=timer_callback)


main_loop()
