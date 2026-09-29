# SIA Monitor

Centro de monitoreo **tipo DVR** para Windows: muestra varias cámaras en una cuadrícula y **lee las
placas de todas al mismo tiempo**. Cada placa leída se envía al backend de **SIA Admin** (el mismo
del panel web de placas y la app móvil):

- Queda en el **historial de placas** con la cámara y el lugar, esté o no en el listado.
- Si la placa está en el **listado de placas buscadas**, el monitor dispara una alerta (sonido,
  borde rojo en la cámara, foto de la placa y notificación de Windows) y el **administrador recibe
  la notificación en el panel web**.

```
 Parqueadero A          Parqueadero B          Sede C
 📹 📹 📹               📹 📹                  📹 📹 📹 📹
        └──────────────── RTSP ─┴──────────────────────┘
                        ▼
        🖥️  SIA Monitor (este programa)
            cuadrícula en vivo + lectura de placas en el PC
                        ▼  solo el texto de la placa (no el video)
        Backend Amplify: reportSighting → historial + ¿está en el listado?
                        ▼
        🚨 Alerta en el monitor  +  🔔 notificación en el panel web
```

## Cómo lee las placas

1. Cada cámara se lee en su propio hilo, con reconexión automática si se cae la señal.
2. Cuatro veces por segundo (configurable) el último cuadro pasa por el motor de reconocimiento
   [fast-alpr](https://github.com/ankandrew/fast-alpr): un detector YOLO ubica la placa y un OCR
   entrenado con placas lee el texto. **Todo corre en el PC**; el video no sale a internet.
3. El texto se valida con los formatos colombianos (`ABC123`, `ABC12D`, `ABC12`) corrigiendo
   confusiones típicas (O/0, B/8…).
4. Una placa se confirma cuando se lee 2 veces en 3 segundos. Luego queda en espera 10 minutos
   por cámara, para que un carro estacionado no se registre en cada cuadro.
5. Se envía a `reportSighting`. Si no hay internet, las lecturas quedan en cola y se reintentan.

## Instalación (Windows 10/11)

1. Descarga `SIAMonitor-windows.zip` desde la pestaña **Actions** (último build de `main`,
   sección *Artifacts*) o desde **Releases**, y descomprímelo, por ejemplo en
   `C:\SIAMonitor`.
2. Copia `amplify_outputs.json` del backend de SIA (consola de Amplify → app **SIA Admin** → rama
   `main` → *Deployed backend resources* → **Download amplify_outputs.json**) **en la misma
   carpeta que `SIAMonitor.exe`**.
   Si no está, el programa lo pide al abrir.
3. En Cognito, crea un usuario para el monitor (ej. `monitor.central@correo.com`) y agrégalo al
   grupo **`camara`**.
4. Abre `SIAMonitor.exe` e inicia sesión. La primera vez pide cambiar la contraseña
   temporal y descarga los modelos de reconocimiento (~10 MB, requiere internet).

## Agregar cámaras

**➕ Agregar cámara** → nombre, fuente de video, lugar (sector) y coordenadas (opcional, para el
mapa del historial). Con **Probar conexión** se ve una imagen antes de guardar. Clic derecho o doble
clic sobre una cámara para editarla o eliminarla.

| Equipo | Fuente de video |
|---|---|
| Cámara/NVR **Hikvision** | `rtsp://usuario:clave@IP:554/Streaming/Channels/101` (canal 1, calidad principal; `102` = subcalidad; canal 2 = `201`) |
| Cámara/NVR **Dahua / Imou** | `rtsp://usuario:clave@IP:554/cam/realmonitor?channel=1&subtype=0` |
| Otras cámaras IP (ONVIF) | la URL RTSP que indique el manual o el software del fabricante |
| Webcam o capturadora HDMI→USB | `0`, `1`, `2`… |
| Archivo de video (pruebas) | `C:\videos\prueba.mp4` |

**Cámaras en otros lugares**: el PC del monitor debe poder llegar a la cámara por internet. Lo
recomendable es una **VPN** entre sedes (ej. Tailscale/ZeroTier, o la VPN del router). Otra opción
es abrir en el router de la sede el puerto RTSP hacia el NVR, con usuario y clave fuertes.

**Recomendaciones para leer bien placas**
- Cámara apuntando a la entrada/salida, a 3–8 m de la placa, ángulo menor a 30°.
- La placa debe ocupar al menos ~130 px de ancho en la imagen (1080p con zoom óptico si está lejos).
- De noche: cámara con infrarrojo o iluminación; obturación rápida para vehículos en movimiento.

## Capacidad

| PC | Cámaras analizando a la vez (aprox.) |
|---|---|
| Core i5 / Ryzen 5 reciente, 8 GB RAM | 6–10 |
| Core i7 / Ryzen 7, 16 GB RAM | 12–20 |

Si se necesitan más cámaras, se pueden instalar varios monitores (por ejemplo, uno por sede), todos
con cuentas del grupo `camara`. Todas las lecturas y alertas llegan al mismo panel web.

Ajustes avanzados en `%APPDATA%\SIA Monitor\config.json`:
`analyze_fps` (cuadros analizados por segundo por cámara), `cooldown_minutes`, `min_confidence`.

## Modo prueba (sin servidor)

```
SIAMonitor.exe --sin-servidor
```

Muestra las placas leídas sin enviarlas al backend. Sirve para instalar y ajustar cámaras en sitio.

## Archivos del programa

- Configuración y cámaras: `%APPDATA%\SIA Monitor\config.json`
- Registro de lecturas y errores: `%APPDATA%\SIA Monitor\monitor.log`

## Desarrollo

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/Mac: source .venv/bin/activate
pip install -r requirements-dev.txt
python run.py                     # o: python run.py --sin-servidor
pytest                            # pruebas (incluye el motor de placas con video sintético)
pyinstaller --noconfirm monitor.spec   # genera dist/SIAMonitor/
```

GitHub Actions (`.github/workflows/build.yml`) corre las pruebas y genera el `.zip` de Windows en
cada push a `main`. Al crear un tag `v1.0.0` publica el `.zip` como Release.

## Estructura

```
sia_monitor/
  app.py            Inicio: configuración, login y ventana principal
  backend.py        Cognito (grupo camara) y GraphQL: reportSighting / createPlateDetection
  camera.py         Lectura de cada cámara (RTSP/USB/archivo), reconexión y análisis
  engine.py         Motor de reconocimiento de placas (fast-alpr, ONNX)
  plates.py         Validación y corrección de placas colombianas
  tracker.py        Confirmación por lecturas repetidas y espera por cámara
  reporter.py       Cola de envío al servidor con reintentos
  config.py         Configuración persistente
  ui/               Interfaz (PySide6): login, cuadrícula, cámaras y alertas
tests/              Pruebas (pytest)
monitor.spec        Empaquetado PyInstaller
```
