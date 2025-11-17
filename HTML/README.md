
# Broker Pub/Sub Distribuido

Este directorio implementa un broker de mensajes **Pub/Sub** ligero orientado a sistemas embebidos y un dashboard web. Proporciona comunicación en tiempo real entre dispositivos como microcontroladores (MicroPytho), clientes Python y aplicaciones web mediante WebSockets.

---

## Características principales

- PubSub_server_python.py:

  - Broker TCP con soporte para múltiples clientes simultáneos.
  - Servidor WebSocket para integrarse con navegadores y aplicaciones web.
  - Protocolo de mensajes basado en **JSON**: 
    - `action`: Puede ser `PUB`, `SUB`, `UNSUB`
    - `topic`: Similar a MQTT
    - `data`: En formato JSON
  - Maneja conexiones entrantes.
  - Administra listas de suscripción.
  - Distribuye mensajes.
  - Soporte para envío de imágenes y binarios codificados en **base64**.
- PubSub_client_web.html: Cliente Web modular (conexión, mensajes, log con filtros, visualización de cámara).
- PubSub_clinet_micropython.py: Cliente MicroPython para cámaras RGB565.
- PubSub_client_python.py: Cliente Python sencillo para pruebas por socket.
  - Captura fotogramas de cámara (RGB565).
  - Los empaqueta como JSON codificado en base64.
  - Publica en el tópico: `camera/frame`.

---

---

## Cómo ejecutar

### 1. Iniciar el broker
```
python3 PubSub_server.py
```
Escucha por defecto en:
- TCP: `0.0.0.0:5051`
- WebSocket: `0.0.0.0:5052`

### 2. Cliente Python (TCP)
```
python3 PubSub_client.py
```

### 3. Cliente Web
Abra el archivo HTML del cliente en su navegador:
```
client.html
```
o ejecútelo desde este enlace

https://gerardomunoz.github.io/CART/broker/PubSub_client_web.html
Ingrese:
- IP del servidor
- Puerto (5052)
- Conectar

### 4. Cliente MicroPython
en ESP32
```
publish_frame(sock)
```
Publica imágenes en tiempo real usando JSON + base64.

---

## Buenas prácticas

- Mantener tópicos jerárquicos: `robot1/sensor/temp`.
- Evitar tópicos extremadamente largos.
- Enviar siempre JSON para estandarizar el protocolo.
- Para binarios usar campos `*_b64` dentro de `data`.

---

## Extensibilidad

Puedes agregar módulos fácilmente:
- Sensores (IMU, GPS, temperatura)
- Actuadores (motores, servos, relés)
- Múltiples cámaras
- Dashboards personalizados
- WebSocket seguro (WSS)

---

## Licencia

Proyecto distribuido bajo licencia **MIT**.

---

## Contribuciones

Los PR son bienvenidos. Para contribuir:
1. Haz un fork.
2. Crea una rama `feature/...`.
3. Envía un pull request.
