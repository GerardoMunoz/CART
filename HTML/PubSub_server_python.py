#!/usr/bin/env python3
"""
Pub/Sub Broker + Tkinter UI + WebSocket support

- TCP broker (igual que antes)
- WebSocket broker paralelo (mismos topics)
- RemoteConnector (TCP) y RemoteConnectorWS (WebSocket)

Message format desde clientes:
  {"action": "SUB", "topic": "chat/general"}
  {"action": "PUB", "topic": "UDFJC/emb1/robot0/RPi/state", "data": {...}}
"""

import socket
import threading
import json
import queue
import time
import traceback
import asyncio
import websockets

from tkinter import (
    Tk, Frame, Label, Button, Entry, Text, Scrollbar, Listbox, END, LEFT, RIGHT, BOTH, Y, X, StringVar
)

# ---------------------------
# Broker implementation (TCP)
# ---------------------------

class Broker:
    def __init__(self, host="0.0.0.0", port=5051, ui_queue=None):
        self.host = host
        self.port = port
        self.server_sock = None
        self.running = False
        self.clients = {}  # client_socket -> {"addr": addr, "thread": th}
        self.subscriptions = {}  # topic -> set(client_socket)
        self.lock = threading.Lock()
        self.ui_queue = ui_queue or (lambda *args, **kwargs: None)
        # Hooks para publicar también hacia otros backends (p.ej. WebSockets)
        self.external_publishers = []

    def register_external_publisher(self, fn):
        """Registra una función fn(topic, data, origin) para ser llamada en cada publish."""
        with self.lock:
            self.external_publishers.append(fn)

    def start(self):
        if self.running:
            return False
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        # backlog > 10 para aceptar bastantes conexiones
        self.server_sock.listen(20)
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self.ui_queue(("info", f"Broker (TCP) listening on {self.host}:{self.port}"))
        return True

    def stop(self):
        self.running = False
        try:
            # close all client sockets
            with self.lock:
                for csock in list(self.clients):
                    try:
                        csock.shutdown(socket.SHUT_RDWR)
                    except:
                        pass
                    try:
                        csock.close()
                    except:
                        pass
                self.clients.clear()
                self.subscriptions.clear()
            if self.server_sock:
                try:
                    self.server_sock.close()
                except:
                    pass
        except Exception as e:
            self.ui_queue(("error", f"Error stopping broker: {e}"))
        self.ui_queue(("info", "Broker (TCP) stopped"))

    def _accept_loop(self):
        while self.running:
            try:
                client, addr = self.server_sock.accept()
                self.ui_queue(("client_connect", f"{addr}"))
                with self.lock:
                    self.clients[client] = {"addr": addr, "thread": None}
                th = threading.Thread(target=self._client_thread, args=(client,), daemon=True)
                with self.lock:
                    self.clients[client]["thread"] = th
                th.start()
            except OSError:
                break
            except Exception as e:
                self.ui_queue(("error", f"Accept error: {e}"))
                traceback.print_exc()

    def _client_thread(self, client):
        addr = self.clients[client]["addr"]
        buf = b""
        try:
            client.settimeout(0.5)
            while self.running:
                try:
                    data = client.recv(1024)
                    if not data:
                        break
                    buf += data
                    # split by newline
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line:
                            continue
                        try:
                            # sockets in Python return bytes; decode
                            text = line.decode('utf-8').strip()
                        except:
                            text = line.decode('latin-1').strip()
                        try:
                            pkt = json.loads(text)
                        except Exception:
                            self.ui_queue(("error", f"Invalid JSON from {addr}: {text}"))
                            continue
                        self.ui_queue(("message_in", (addr, pkt)))
                        self._handle_packet(client, pkt)
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    break
                except Exception as e:
                    self.ui_queue(("error", f"Client read error {addr}: {e}"))
                    traceback.print_exc()
                    break
        finally:
            self._remove_client(client)
            try:
                client.close()
            except:
                pass
            self.ui_queue(("client_disconnect", f"{addr}"))

    def _handle_packet(self, client, pkt):
        action = pkt.get("action", "").upper()
        topic = pkt.get("topic", "")
        if action == "SUB":
            with self.lock:
                if topic not in self.subscriptions:
                    self.subscriptions[topic] = set()
                self.subscriptions[topic].add(client)
            self.ui_queue(("info", f"Client subscribed {topic}"))
            # Optionally send ack
            self._safe_send(client, {"topic": topic, "status": "subscribed"})
        elif action == "UNSUB":
            with self.lock:
                if topic in self.subscriptions and client in self.subscriptions[topic]:
                    self.subscriptions[topic].remove(client)
            self.ui_queue(("info", f"Client unsubscribed {topic}"))
        elif action == "PUB":
            data = pkt.get("data", None)
            # broadcast to subscribers whose topic matches exactly
            self.publish(topic, data, origin=client)
        else:
            self.ui_queue(("error", f"Unknown action: {action}"))

    def _safe_send(self, client, obj):
        try:
            payload = json.dumps(obj) + "\n"
            client.send(payload.encode('utf-8'))
        except Exception:
            # if sending fails, remove client
            self._remove_client(client)

    def publish(self, topic, data, origin=None):
        # publish to exact-match subscribers and wildcard simple match (prefix/#)
        with self.lock:
            targets = set()
            # exact
            if topic in self.subscriptions:
                targets |= self.subscriptions[topic]
            # simple prefix match with trailing '#': topic_base/#
            for t_sub, clients in self.subscriptions.items():
                if t_sub.endswith("/#"):
                    base = t_sub[:-2]
                    if topic.startswith(base):
                        targets |= clients

        msg_obj = {"topic": topic, "data": data}
        self.ui_queue(("published", (topic, data, len(targets))))

        # Enviar a clientes TCP
        for c in list(targets):
            if c is origin:
                continue
            self._safe_send(c, msg_obj)

        # Notificar a publicadores externos (p.ej. WebSockets)
        for fn in list(self.external_publishers):
            try:
                fn(topic, data, origin)
            except Exception as e:
                self.ui_queue(("error", f"External publisher error: {e}"))

    def _remove_client(self, client):
        with self.lock:
            # remove from clients and subscriptions
            if client in self.clients:
                del self.clients[client]
            for topic, clients in list(self.subscriptions.items()):
                if client in clients:
                    clients.remove(client)
                    if not clients:
                        del self.subscriptions[topic]


# ---------------------------
# RemoteConnector: TCP client
# ---------------------------

class RemoteConnector:
    """Simple TCP client to send JSON packets to remote server (not persistent by default)."""
    def __init__(self, ui_queue=None):
        self.ui_queue = ui_queue or (lambda *args, **kwargs: None)

    def send_packet(self, host, port, packet_obj, timeout=5.0):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host, int(port)))
            payload = json.dumps(packet_obj) + "\n"
            s.send(payload.encode('utf-8'))
            # optionally wait for response (read a short reply)
            try:
                s.settimeout(1.0)
                resp = s.recv(2048)
                if resp:
                    try:
                        text = resp.decode('utf-8').strip()
                    except:
                        text = resp.decode('latin-1').strip()
                    try:
                        obj = json.loads(text)
                    except:
                        obj = text
                    self.ui_queue(("remote_resp", (host, port, obj)))
            except socket.timeout:
                pass
            s.close()
            return True
        except Exception as e:
            self.ui_queue(("error", f"Remote send error to {host}:{port}: {e}"))
            return False


# ---------------------------
# RemoteConnectorWS: WebSocket client
# ---------------------------

class RemoteConnectorWS:
    """Cliente simple WebSocket para enviar paquetes JSON a un servidor WS."""
    def __init__(self, ui_queue=None):
        self.ui_queue = ui_queue or (lambda *args, **kwargs: None)

    async def _send_packet_async(self, uri, packet_obj, timeout=5.0):
        try:
            async with websockets.connect(uri, open_timeout=timeout, close_timeout=1) as ws:
                payload = json.dumps(packet_obj)
                await ws.send(payload)
                # opcional: intentar leer una respuesta corta
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    try:
                        obj = json.loads(resp)
                    except:
                        obj = resp
                    self.ui_queue(("remote_resp", (uri, obj)))
                except asyncio.TimeoutError:
                    pass
            return True
        except Exception as e:
            self.ui_queue(("error", f"Remote WS send error to {uri}: {e}"))
            return False

    def send_packet(self, uri, packet_obj, timeout=5.0):
        # Ejecuta la corrutina en un bucle propio (one-shot)
        return asyncio.run(self._send_packet_async(uri, packet_obj, timeout))


# ---------------------------
# WebSocketServer: servidor WS ligado al Broker
# ---------------------------

class WebSocketServer:
    """
    Servidor WebSocket que comparte topics con el Broker TCP.

    - SUB/UNSUB/PUB vía WebSocket
    - Usa un hook que registra en Broker.register_external_publisher
    """
    def __init__(self, host="0.0.0.0", port=5052, broker=None, ui_queue=None):
        self.host = host
        self.port = port
        self.broker = broker
        self.ui_queue = ui_queue or (lambda *args, **kwargs: None)

        self.loop = None
        self.server = None
        self.thread = None
        self.running = False

        self.ws_subscriptions = {}  # topic -> set(websocket)
        self.lock = threading.Lock()

    def start(self):
        if self.running:
            return False
        self.running = True

        # registrar hook en el broker para que todo publish llegue también aquí
        if self.broker is not None:
            self.broker.register_external_publisher(self._broker_publish_hook)

        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        return True

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.server = self.loop.run_until_complete(
            websockets.serve(self._handler, self.host, self.port, max_queue=32)
        )
        self.ui_queue(("info", f"WebSocket broker listening on {self.host}:{self.port}"))
        try:
            self.loop.run_forever()
        finally:
            if self.server is not None:
                self.server.close()
                self.loop.run_until_complete(self.server.wait_closed())
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()
            self.ui_queue(("info", "WebSocket server stopped"))

    async def _handler(self, websocket, path):
        addr = websocket.remote_address
        self.ui_queue(("client_connect", f"WS {addr}"))
        try:
            async for message in websocket:
                try:
                    pkt = json.loads(message)
                except Exception:
                    self.ui_queue(("error", f"Invalid JSON from WS {addr}: {message!r}"))
                    continue
                self.ui_queue(("message_in", (addr, pkt)))
                await self._handle_packet(websocket, pkt)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._remove_ws(websocket)
            self.ui_queue(("client_disconnect", f"WS {addr}"))

    async def _handle_packet(self, websocket, pkt):
        action = pkt.get("action", "").upper()
        topic = pkt.get("topic", "")

        if action == "SUB":
            with self.lock:
                if topic not in self.ws_subscriptions:
                    self.ws_subscriptions[topic] = set()
                self.ws_subscriptions[topic].add(websocket)
            # ACK
            try:
                await websocket.send(json.dumps({"topic": topic, "status": "subscribed"}))
            except Exception:
                pass

        elif action == "UNSUB":
            with self.lock:
                if topic in self.ws_subscriptions and websocket in self.ws_subscriptions[topic]:
                    self.ws_subscriptions[topic].remove(websocket)
                    if not self.ws_subscriptions[topic]:
                        del self.ws_subscriptions[topic]

        elif action == "PUB":
            data = pkt.get("data", None)
            if self.broker is not None:
                # reusa la lógica del broker (publica también a TCP)
                self.broker.publish(topic, data, origin=websocket)

        else:
            self.ui_queue(("error", f"Unknown WS action: {action}"))

    def _broker_publish_hook(self, topic, data, origin):
        """
        Hook llamado por Broker.publish() en un hilo cualquiera.
        Aquí reenviamos el mensaje a los clientes WebSocket suscritos.
        """
        if not self.loop or not self.running:
            return

        msg = json.dumps({"topic": topic, "data": data})
        with self.lock:
            targets = set()
            # exact match
            if topic in self.ws_subscriptions:
                targets |= self.ws_subscriptions[topic]
            # wildcard simple topic_base/#
            for t_sub, clients in self.ws_subscriptions.items():
                if t_sub.endswith("/#"):
                    base = t_sub[:-2]
                    if topic.startswith(base):
                        targets |= clients

        for ws in list(targets):
            if ws is origin:
                continue
            try:
                asyncio.run_coroutine_threadsafe(ws.send(msg), self.loop)
            except Exception:
                # La limpieza real se hará cuando el WS falle/close
                pass

    def _remove_ws(self, websocket):
        with self.lock:
            for topic, clients in list(self.ws_subscriptions.items()):
                if websocket in clients:
                    clients.remove(websocket)
                    if not clients:
                        del self.ws_subscriptions[topic]

    def stop(self):
        self.running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)


# ---------------------------
# Tkinter UI
# ---------------------------

class PubSubUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Pub/Sub Broker - Tk UI " + socket.gethostbyname(socket.gethostname()))
        self.ui_q = queue.Queue()
        self.broker = Broker(host="0.0.0.0", port=5051, ui_queue=self._ui_queue_put)
        self.remote = RemoteConnector(ui_queue=self._ui_queue_put)
        self.remote_ws = RemoteConnectorWS(ui_queue=self._ui_queue_put)
        self.ws_server = WebSocketServer(host="0.0.0.0", port=5052, broker=self.broker, ui_queue=self._ui_queue_put)

        # Top frame: control
        top = Frame(root)
        top.pack(fill=X, padx=5, pady=5)
        self.start_btn = Button(top, text="Start Broker", command=self.start_broker)
        self.start_btn.pack(side=LEFT)
        self.stop_btn = Button(top, text="Stop Broker", command=self.stop_broker, state="disabled")
        self.stop_btn.pack(side=LEFT, padx=(5,0))
        Label(top, text="TCP Port:").pack(side=LEFT, padx=(10,0))
        self.port_var = StringVar(value="5051")
        self.port_entry = Entry(top, width=6, textvariable=self.port_var)
        self.port_entry.pack(side=LEFT)
        Label(top, text="WS Port: 5052").pack(side=LEFT, padx=(10,0))

        # Middle: clients and publish
        mid = Frame(root)
        mid.pack(fill=BOTH, expand=True, padx=5, pady=5)

        # Left: clients
        client_frame = Frame(mid)
        client_frame.pack(side=LEFT, fill=Y)
        Label(client_frame, text="TCP Clients / Subscriptions").pack()
        self.clients_list = Listbox(client_frame, width=40, height=12)
        self.clients_list.pack(side=LEFT, fill=Y)
        self.client_scroll = Scrollbar(client_frame, command=self.clients_list.yview)
        self.client_scroll.pack(side=RIGHT, fill=Y)
        self.clients_list.config(yscrollcommand=self.client_scroll.set)

        # Right: publish panel
        pub_frame = Frame(mid)
        pub_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(10,0))
        Label(pub_frame, text="Publish (topic / JSON)").pack(anchor="w")
        self.topic_entry = Entry(pub_frame)
        self.topic_entry.insert(0, "UDFJC/emb1/robot0/RPi/state")
        self.topic_entry.pack(fill=X)
        self.payload_text = Text(pub_frame, height=8)
        self.payload_text.pack(fill=BOTH, expand=True)
        self.payload_text.insert("1.0", json.dumps({"v":0.2,"w":0,"alfa0":0,"alfa1":45,"alfa2":30,"duration":2.0}, indent=2))
        btns = Frame(pub_frame)
        btns.pack(fill=X, pady=(5,0))
        Button(btns, text="Publish Locally", command=self.publish_local).pack(side=LEFT)
        Button(btns, text="Send to RPi (TCP)...", command=self.send_to_rpi_popup).pack(side=LEFT, padx=(5,0))
        Button(btns, text="Send via WS...", command=self.send_to_ws_popup).pack(side=LEFT, padx=(5,0))

        # Bottom: log
        bottom = Frame(root)
        bottom.pack(fill=BOTH, expand=True, padx=5, pady=5)
        Label(bottom, text="Log").pack(anchor="w")
        self.log_text = Text(bottom, height=10)
        self.log_text.pack(fill=BOTH, expand=True)
        self._log("Ready")

        # start UI poll loop
        self.root.after(100, self._poll_ui)

    # --------------------
    # Broker control
    # --------------------
    def start_broker(self):
        try:
            port = int(self.port_var.get())
        except:
            self._log("Invalid port")
            return
        self.broker.port = port
        ok = self.broker.start()
        if ok:
            # arrancar servidor WebSocket asociado
            self.ws_server.start()
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            self._log(f"Broker started: TCP {port}, WS {self.ws_server.port}")
        else:
            self._log("Broker already running")

    def stop_broker(self):
        self.broker.stop()
        if self.ws_server:
            self.ws_server.stop()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    # --------------------
    # Publishing
    # --------------------
    def publish_local(self):
        topic = self.topic_entry.get().strip()
        txt = self.payload_text.get("1.0", END).strip()
        if not topic:
            self._log("Empty topic")
            return
        try:
            data = json.loads(txt)
        except Exception as e:
            self._log(f"Payload not valid JSON: {e}")
            return
        self.broker.publish(topic, data)
        self._log(f"Published locally to {topic}")

    def send_to_rpi_popup(self):
        # simple popup modal to get host/port and use current topic/payload (TCP)
        popup = Tk()
        popup.title("Send to RPi (TCP)")
        Label(popup, text="Host (IP)").pack()
        host_e = Entry(popup); host_e.pack(); host_e.insert(0, "192.168.1.50")
        Label(popup, text="Port").pack()
        port_e = Entry(popup); port_e.pack(); port_e.insert(0, "5051")
        def do_send():
            host = host_e.get().strip()
            port = port_e.get().strip()
            try:
                port_i = int(port)
            except:
                self._log("Invalid port")
                popup.destroy(); return
            topic = self.topic_entry.get().strip()
            try:
                data = json.loads(self.payload_text.get("1.0", END).strip())
            except:
                self._log("Invalid JSON payload")
                popup.destroy(); return
            pkt = {"action":"PUB", "topic": topic, "data": data}
            ok = self.remote.send_packet(host, port_i, pkt)
            if ok:
                self._log(f"Sent TCP to {host}:{port_i} -> {topic}")
            popup.destroy()
        Button(popup, text="Send", command=do_send).pack()
        popup.mainloop()

    def send_to_ws_popup(self):
        # popup para enviar un paquete PUB por WebSocket
        popup = Tk()
        popup.title("Send via WebSocket")
        Label(popup, text="Host (IP)").pack()
        host_e = Entry(popup); host_e.pack(); host_e.insert(0, "192.168.1.50")
        Label(popup, text="Port (WS)").pack()
        port_e = Entry(popup); port_e.pack(); port_e.insert(0, "5052")
        def do_send():
            host = host_e.get().strip()
            port = port_e.get().strip()
            try:
                port_i = int(port)
            except:
                self._log("Invalid WS port")
                popup.destroy(); return
            uri = f"ws://{host}:{port_i}"
            topic = self.topic_entry.get().strip()
            try:
                data = json.loads(self.payload_text.get("1.0", END).strip())
            except:
                self._log("Invalid JSON payload")
                popup.destroy(); return
            pkt = {"action": "PUB", "topic": topic, "data": data}
            ok = self.remote_ws.send_packet(uri, pkt)
            if ok:
                self._log(f"Sent WS to {uri} -> {topic}")
            popup.destroy()
        Button(popup, text="Send", command=do_send).pack()
        popup.mainloop()

    # --------------------
    # UI helpers
    # --------------------
    def _ui_queue_put(self, item):
        # squeeze into main thread queue
        self.ui_q.put(item)

    def _poll_ui(self):
        # process broker/ui events
        while not self.ui_q.empty():
            item = self.ui_q.get_nowait()
            try:
                self._handle_ui_event(item)
            except Exception as e:
                self._log(f"UI event handler error: {e}")
        # refresh client list
        self._refresh_clients()
        self.root.after(100, self._poll_ui)

    def _handle_ui_event(self, evt):
        typ = evt[0]
        if typ == "info":
            self._log(evt[1])
        elif typ == "error":
            self._log("ERROR: " + str(evt[1]))
        elif typ == "client_connect":
            self._log("Client connected: " + str(evt[1]))
        elif typ == "client_disconnect":
            self._log("Client disconnected: " + str(evt[1]))
        elif typ == "message_in":
            addr, pkt = evt[1]
            self._log(f"IN  {addr}: {json.dumps(pkt)}")
        elif typ == "published":
            topic, data, n = evt[1]
            self._log(f"PUBLISHED {topic} -> {n} subscribers")
        elif typ == "remote_resp":
            host, port_or_obj, maybe_obj = evt[1] if isinstance(evt[1], tuple) and len(evt[1]) == 3 else (None, None, None)
            self._log(f"Remote response: {evt[1]}")
        else:
            self._log(f"Event: {evt}")

    def _refresh_clients(self):
        # populate listbox with current TCP clients and their subscriptions (best-effort)
        self.clients_list.delete(0, END)
        with self.broker.lock:
            for client, info in self.broker.clients.items():
                addr = info["addr"]
                # find subscriptions for this client
                subs = []
                for topic, clients in self.broker.subscriptions.items():
                    if client in clients:
                        subs.append(topic)
                self.clients_list.insert(END, f"{addr} -> {', '.join(subs) if subs else '(no subs)'}")

    def _log(self, text):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(END, f"[{ts}] {text[:100]}\n")
        self.log_text.see(END)


# ---------------------------
# Helpers to build topics.md payloads
# ---------------------------

def make_state_payload(v=0.2, w_deg=0.0, alfa0_deg=0, alfa1_deg=45, alfa2_deg=30, duration=2.0):
    """Build the immediate state payload as specified in topics.md"""
    return {
        "v": v,
        "w": w_deg,        # degrees per second as in topics.md (broker will not convert)
        "alfa0": alfa0_deg,
        "alfa1": alfa1_deg,
        "alfa2": alfa2_deg,
        "duration": duration
    }

def make_sequence_payload(name, states):
    """Create a 'create sequence' action payload"""
    return {
        "action": "create",
        "sequence": {
            "name": name,
            "states": states
        }
    }

# ---------------------------
# Main
# ---------------------------

def main():
    root = Tk()
    app = PubSubUI(root)
    root.geometry("900x700")
    root.mainloop()

if __name__ == "__main__":
    main()
