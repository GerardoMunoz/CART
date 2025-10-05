# CART
 Communication of Agents in Real Time
```python
# main.py
import network
import socket
import time
import ubinascii
import uhashlib
import ustruct
import _thread
import ujson
import os

# === CONFIG ===
SSID = "Ejemplo"
PASSWORD = "12345678"
FILE_PATH = "choreography.html"
BROKER_IP = "10.119.61.1"
BROKER_PORT = 5051
HTTP_PORT = 80

# === Clases ===

class WiFiManager:
    def __init__(self, ssid, password, wlan_iface=network.STA_IF):
        self.ssid = ssid
        self.password = password
        self.wlan = network.WLAN(wlan_iface)
        self.wlan.active(True)

    def connect(self, timeout=20):
        if self.wlan.isconnected():
            print("WiFi: already connected:", self.wlan.ifconfig())
            return True
        print("WiFi: connecting to", self.ssid)
        self.wlan.connect(self.ssid, self.password)
        t0 = time.time()
        while not self.wlan.isconnected():
            time.sleep(0.5)
            if time.time() - t0 > timeout:
                print("WiFi: connect timeout")
                return False
        print("WiFi: connected:", self.wlan.ifconfig())
        return True

    def is_connected(self):
        return self.wlan.isconnected()


class ImageGenerator:
    @staticmethod
    def generate_test_image(width=40, height=30):
        """Genera una imagen simple RGB888 (3 bytes por pixel)"""
        img = bytearray()
        bar_width = max(1, width // 4)
        colors = [
            (255, 0, 0),    # rojo
            (0, 255, 0),    # verde
            (0, 0, 255),    # azul
            (255, 255, 0),  # amarillo
        ]
        for y in range(height):
            for x in range(width):
                c = colors[(x // bar_width) % len(colors)]
                img.extend(bytes(c))
        return img, width, height


class WebSocketClientHandler:
    """Representa un cliente WebSocket individual"""
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, sock, addr, server):
        self.sock = sock
        self.addr = addr
        self.server = server
        self.alive = True

    def handshake(self, request_text):
        """Realiza el handshake WebSocket simple"""
        key = None
        for line in request_text.split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
                break
        if not key:
            return False
        sha1 = uhashlib.sha1(key.encode() + self.GUID.encode())
        accept = ubinascii.b2a_base64(sha1.digest()).decode().strip()
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: {}\r\n\r\n".format(accept)
        )
        self.sock.send(resp.encode())
        return True

    def recv_frame(self):
        """Recibe tramas de texto (y pequeñas) según RFC simple"""
        try:
            hdr = self.sock.recv(2)
            if not hdr or len(hdr) < 2:
                return None
            b1, b2 = hdr[0], hdr[1]
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F

            if length == 126:
                ext = self.sock.recv(2)
                length = (ext[0] << 8) | ext[1]
            elif length == 127:
                ext = self.sock.recv(8)
                length = 0
                for i in range(8):
                    length = (length << 8) | ext[i]

            mask = None
            if masked:
                mask = self.sock.recv(4)

            # leer payload (puede venir en varias recv)
            data = bytearray()
            remaining = length
            while remaining > 0:
                chunk = self.sock.recv(remaining)
                if not chunk:
                    break
                data.extend(chunk)
                remaining -= len(chunk)

            if masked and mask:
                for i in range(len(data)):
                    data[i] ^= mask[i % 4]

            if opcode == 0x8:  # close
                return None
            if opcode == 0x1:  # text
                return data.decode()
            # ignorar otros opcodes para simplicidad
            return None
        except Exception as e:
            print("recv_frame error:", e)
            return None

    def send_text(self, msg):
        try:
            payload = msg.encode()
            length = len(payload)
            if length < 126:
                header = bytearray([0x81, length])
            elif length < (1 << 16):
                header = bytearray([0x81, 126, (length >> 8) & 0xFF, length & 0xFF])
            else:
                header = bytearray([0x81, 127]) + length.to_bytes(8, "big")
            frame = header + payload
            self.sock.send(frame)
        except Exception as e:
            print("send_text error:", e)
            raise

    def send_binary(self, data: bytes):
        try:
            length = len(data)
            if length < 126:
                header = bytearray([0x82, length])
            elif length < (1 << 16):
                header = bytearray([0x82, 126, (length >> 8) & 0xFF, length & 0xFF])
            else:
                header = bytearray([0x82, 127]) + length.to_bytes(8, "big")
            self.sock.send(header + data)
        except Exception as e:
            print("send_binary error:", e)
            raise

    def run(self):
        """Loop principal para el cliente WS: recibe mensajes y responde"""
        try:
            while self.alive:
                msg = self.recv_frame()
                if msg is None:
                    break
                print("WS recv from", self.addr, ":", msg)
                # ejemplo: al recibir cualquier cosa, enviar imagen de prueba
                img, w, h = ImageGenerator.generate_test_image()
                header = ustruct.pack(">HH", w, h)
                try:
                    self.send_binary(header + img)
                except Exception as e:
                    print("Error enviando imagen:", e)
                    break
        finally:
            print("Closing websocket client", self.addr)
            self.alive = False
            self.server.remove_ws_client(self)
            try:
                self.sock.close()
            except:
                pass


class WebServer:
    """Servidor HTTP y WebSocket (ambos en la misma clase)"""
    def __init__(self, host="0.0.0.0", port=80, file_path="choreography.html"):
        self.host = host
        self.port = port
        self.file_path = file_path
        self.ws_clients = []   # lista de WebSocketClientHandler
        self.sock = None
        self.running = False

    def start(self):
        addr = socket.getaddrinfo(self.host, self.port)[0][-1]
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(addr)
        self.sock.listen(5)
        self.running = True
        print("WebServer listening on", addr)
        # loop de aceptación (bloqueante)
        while self.running:
            try:
                cl, addr = self.sock.accept()
                print("Client connected from", addr)
                # handle in new thread to allow multiple WS clients
                _thread.start_new_thread(self._handle_client, (cl, addr))
            except Exception as e:
                print("accept error:", e)
                time.sleep(1)

    def _handle_client(self, cl_sock, addr):
        try:
            # leer la request inicial (simple)
            req = b""
            # recibimos hasta cabeceras (termina en \r\n\r\n)
            cl_sock.settimeout(2)
            while True:
                chunk = cl_sock.recv(1024)
                if not chunk:
                    break
                req += chunk
                if b"\r\n\r\n" in req:
                    break
            cl_sock.settimeout(None)
            request_text = req.decode(errors="ignore")
            # comprobar si es upgrade a websocket
            if "Upgrade: websocket" in request_text or "upgrade: websocket" in request_text.lower():
                ws = WebSocketClientHandler(cl_sock, addr, self)
                if ws.handshake(request_text):
                    print("WebSocket handshake complete", addr)
                    self.add_ws_client(ws)
                    # manejar loop de cliente en un hilo propio
                    ws.run()
                else:
                    print("Handshake failed for", addr)
                    cl_sock.close()
            else:
                # servir archivo estático
                self._serve_file_http(cl_sock, request_text)
                cl_sock.close()
        except Exception as e:
            print("Error handling client", addr, e)
            try:
                cl_sock.close()
            except:
                pass

    def _serve_file_http(self, client_sock, request_text):
        # Responder cabecera
        try:
            # Determinar contenido simple por extensión
            content_type = "text/html"
            if self.file_path.endswith(".html"):
                content_type = "text/html"
            elif self.file_path.endswith(".js"):
                content_type = "application/javascript"
            elif self.file_path.endswith(".css"):
                content_type = "text/css"
            header = "HTTP/1.1 200 OK\r\nContent-Type: {}\r\n\r\n".format(content_type)
            client_sock.send(header.encode())
            # abrir archivo en binario y enviar en chunks
            with open(self.file_path, "rb") as f:
                while True:
                    chunk = f.read(1000)
                    if not chunk:
                        break
                    # corregir posible corte en CRLF (si fuese necesario)
                    # si el último byte es '\r', leer uno más
                    while len(chunk) > 0 and chunk[-1] == 13:  # b'\r' == 13
                        extra = f.read(1)
                        if not extra:
                            break
                        chunk += extra
                    client_sock.send(chunk)
                    time.sleep_ms(20)
            print("Served", self.file_path)
        except Exception as e:
            print("Error sirviendo archivo:", e)

    # Métodos para manejar lista de clientes
    def add_ws_client(self, ws_handler):
        self.ws_clients.append(ws_handler)
        print("Added WS client, total:", len(self.ws_clients))

    def remove_ws_client(self, ws_handler):
        try:
            self.ws_clients.remove(ws_handler)
        except ValueError:
            pass
        print("Removed WS client, total:", len(self.ws_clients))

    def broadcast_text(self, msg):
        """Enviar mensaje de texto a todos los clientes WS conectados"""
        for ws in self.ws_clients[:]:
            try:
                ws.send_text(msg)
            except Exception as e:
                print("Broadcast send_text error:", e)
                self.remove_ws_client(ws)

    def broadcast_json(self, obj):
        try:
            self.broadcast_text(ujson.dumps(obj))
        except Exception as e:
            print("broadcast_json error:", e)


class PubSubClient:
    """Cliente simple que conecta a un broker TCP 'tipo line-based JSON'"""
    def __init__(self, broker_ip, broker_port, webserver: WebServer, sub_topic="UDFJC/emb1/robot0/RPi/state"):
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.webserver = webserver
        self.sub_topic = sub_topic
        self.sock = None
        self.running = False

    def connect(self):
        try:
            self.sock = socket.socket()
            self.sock.connect((self.broker_ip, self.broker_port))
            print("PubSub: conectado a broker", (self.broker_ip, self.broker_port))
            # enviar paquete de suscripción (formato JSON line-based)
            sub_pkt = {"action": "SUB", "topic": self.sub_topic}
            self.sock.send(ujson.dumps(sub_pkt).encode() + b"\n")
            return True
        except Exception as e:
            print("PubSub connect error:", e)
            try:
                if self.sock:
                    self.sock.close()
            except:
                pass
            self.sock = None
            return False

    def run(self):
        """loop que recibe mensajes del broker y los reenvía a navegadores"""
        self.running = True
        while True:
            if not self.connect():
                print("PubSub: reintentando en 2s")
                time.sleep(2)
                continue
            try:
                # leer por líneas (line-based JSON)
                buffer = b""
                while True:
                    data = self.sock.recv(1024)
                    if not data:
                        time.sleep(0.1)
                        continue
                    buffer += data
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line:
                            continue
                        try:
                            msg = ujson.loads(line)
                        except Exception as e:
                            print("PubSub decode error:", e, line)
                            continue
                        print("📩 Broker:", msg)
                        # reenviar a todos los navegadores (texto JSON)
                        self.webserver.broadcast_json(msg)
            except Exception as e:
                print("PubSub run error:", e)
                try:
                    self.sock.close()
                except:
                    pass
                self.sock = None
                time.sleep(1)


# === MAIN ===

def main():
    wifi = WiFiManager(SSID, PASSWORD)
    if not wifi.connect():
        print("No se pudo conectar a WiFi; intentando continuar sin red.")
    # crear servidor web (HTTP + WebSocket)
    webserver = WebServer(host="0.0.0.0", port=HTTP_PORT, file_path=FILE_PATH)
    # crear PubSub y arrancarlo en thread
    pubsub = PubSubClient(BROKER_IP, BROKER_PORT, webserver)
    _thread.start_new_thread(pubsub.run, ())

    # arrancar servidor web (bloqueante)
    webserver.start()

if __name__ == "__main__":
    main()

```
