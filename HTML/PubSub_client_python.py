#!/usr/bin/env python3
"""
Pub/Sub TCP Client con GUI (para probar PubSub_server.py)
---------------------------------------------------------
Permite:
- Conectarse al broker TCP (por defecto localhost:5051)
- Suscribirse a tópicos
- Publicar mensajes JSON
- Ver los mensajes recibidos
- Ejecutar pruebas automáticas con payloads válidos de topics.md

Autor: ChatGPT
"""

import socket
import threading
import json
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import time


class PubSubClient:
    def __init__(self, host="localhost", port=5051, log_func=None):
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        self.thread = None
        self.log = log_func or (lambda msg: print(msg))

    def connect(self):
        if self.running:
            self.log("Ya está conectado.")
            return True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.running = True
            self.thread = threading.Thread(target=self._recv_loop, daemon=True)
            self.thread.start()
            self.log(f"Conectado a {self.host}:{self.port}")
            return True
        except Exception as e:
            self.log(f"Error de conexión: {e}")
            return False

    def disconnect(self):
        self.running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                self.sock.close()
            except:
                pass
        self.sock = None
        self.log("Desconectado del broker")

    def send_json(self, obj):
        if not self.sock:
            self.log("No conectado")
            return
        try:
            data = json.dumps(obj) + "\n"
            self.sock.send(data.encode("utf-8"))
            self.log(f"→ Enviado: {data.strip()}")
        except Exception as e:
            self.log(f"Error al enviar: {e}")

    def _recv_loop(self):
        buf = b""
        while self.running:
            try:
                data = self.sock.recv(1024)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("utf-8").strip()
                    if not text:
                        continue
                    try:
                        obj = json.loads(text)
                        self.log(f"← Recibido: {json.dumps(obj)}")
                    except Exception:
                        self.log(f"← (texto) {text}")
            except Exception:
                break
        self.disconnect()


# -----------------------------
# GUI con Tkinter
# -----------------------------
class PubSubGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Cliente Pub/Sub TCP")
        self.client = None

        # Frame de conexión
        frm_conn = ttk.Frame(root, padding=5)
        frm_conn.pack(fill=tk.X)
        ttk.Label(frm_conn, text="Host:").pack(side=tk.LEFT)
        self.host_var = tk.StringVar(value="localhost")
        ttk.Entry(frm_conn, textvariable=self.host_var, width=15).pack(side=tk.LEFT, padx=2)
        ttk.Label(frm_conn, text="Puerto:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="5051")
        ttk.Entry(frm_conn, textvariable=self.port_var, width=6).pack(side=tk.LEFT, padx=2)
        self.btn_conn = ttk.Button(frm_conn, text="Conectar", command=self.toggle_connection)
        self.btn_conn.pack(side=tk.LEFT, padx=5)

        # Frame de suscripción/publicación
        frm_io = ttk.LabelFrame(root, text="Mensajes", padding=5)
        frm_io.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(frm_io, text="Tópico:").pack(anchor="w")
        self.topic_var = tk.StringVar(value="UDFJC/emb1/robot0/RPi/state")
        ttk.Entry(frm_io, textvariable=self.topic_var, width=60).pack(fill=tk.X, padx=2)

        ttk.Label(frm_io, text="Payload JSON:").pack(anchor="w")
        self.txt_payload = scrolledtext.ScrolledText(frm_io, height=6)
        self.txt_payload.pack(fill=tk.BOTH, padx=2, pady=2)
        self.txt_payload.insert("1.0", json.dumps({
            "v": 0.2,
            "w": 0.0,
            "alfa0": 0,
            "alfa1": 45,
            "alfa2": 30,
            "duration": 2.0
        }, indent=2))

        frm_btns = ttk.Frame(frm_io)
        frm_btns.pack(fill=tk.X, pady=3)
        ttk.Button(frm_btns, text="Suscribirse", command=self.subscribe).pack(side=tk.LEFT, padx=2)
        ttk.Button(frm_btns, text="Publicar", command=self.publish).pack(side=tk.LEFT, padx=2)
        ttk.Button(frm_btns, text="Prueba automática", command=self.auto_test).pack(side=tk.LEFT, padx=5)

        # Log
        frm_log = ttk.LabelFrame(root, text="Log", padding=5)
        frm_log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.txt_log = scrolledtext.ScrolledText(frm_log, height=15, state="normal")
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    # -------------------------
    # Funciones GUI
    # -------------------------
    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.insert(tk.END, f"[{ts}] {msg}\n")
        self.txt_log.see(tk.END)

    def toggle_connection(self):
        if self.client and self.client.running:
            self.client.disconnect()
            self.client = None
            self.btn_conn.config(text="Conectar")
        else:
            host = self.host_var.get().strip()
            port = int(self.port_var.get().strip())
            self.client = PubSubClient(host, port, log_func=self.log)
            ok = self.client.connect()
            if ok:
                self.btn_conn.config(text="Desconectar")

    def subscribe(self):
        if not self.client:
            self.log("No conectado.")
            return
        topic = self.topic_var.get().strip()
        if not topic:
            self.log("Debe ingresar un tópico.")
            return
        pkt = {"action": "SUB", "topic": topic}
        self.client.send_json(pkt)

    def publish(self):
        if not self.client:
            self.log("No conectado.")
            return
        topic = self.topic_var.get().strip()
        txt = self.txt_payload.get("1.0", tk.END).strip()
        try:
            data = json.loads(txt)
        except Exception as e:
            self.log(f"JSON inválido: {e}")
            return
        pkt = {"action": "PUB", "topic": topic, "data": data}
        self.client.send_json(pkt)

    def auto_test(self):
        if not self.client:
            self.log("Debe conectarse primero.")
            return

        # Tópicos base
        topic_state = "UDFJC/emb1/robot0/RPi/state"
        topic_seq = "UDFJC/emb1/robot0/RPi/sequence"

        # Suscripción a ambos
        self.client.send_json({"action": "SUB", "topic": topic_state})
        self.client.send_json({"action": "SUB", "topic": topic_seq})

        # Payloads
        state_payload = {
            "v": 0.2, "w": 0.0, "alfa0": 0, "alfa1": 45, "alfa2": 30, "duration": 2.0
        }
        seq_payload = {
            "action": "create",
            "sequence": {
                "name": "saludo",
                "states": [
                    {"v": 10, "w": 0, "alfa0": 0, "alfa1": 0, "alfa2": 0, "duration": 1.0},
                    {"v": 15.7, "w": 90, "alfa0": 0, "alfa1": 0, "alfa2": 0, "duration": 1.0},
                    {"v": 0, "w": 0, "alfa0": -90, "alfa1": 0, "alfa2": 0, "duration": 1.0},
                ]
            }
        }

        # Publicar ambos mensajes
        self.client.send_json({"action": "PUB", "topic": topic_state, "data": state_payload})
        self.client.send_json({"action": "PUB", "topic": topic_seq, "data": seq_payload})
        self.client.send_json({"action": "PUB", "topic": topic_seq,
                               "data": {"action": "execute_now", "name": "saludo"}})

        self.log("→ Prueba automática enviada.")

# -----------------------------
# Main
# -----------------------------
def main():
    root = tk.Tk()
    app = PubSubGUI(root)
    root.geometry("800x700")
    root.mainloop()


if __name__ == "__main__":
    main()
