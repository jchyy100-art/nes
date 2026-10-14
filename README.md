# 🎮 NES Cloud — Emulador de NES en Python con Streaming Web

Emulador completo de Nintendo Entertainment System (NES) escrito en Python, con soporte para **streaming en tiempo real por WebSocket** directamente al navegador web y compatibilidad nativa con **controles Xbox por Bluetooth**.

---

## 🚀 Características

- **Arquitectura Cloud Gaming:** El emulador corre en el servidor (o en la nube) y transmite fotogramas JPEG al navegador a 60 FPS por WebSocket.
- **ROM Incrustada en el Código:** El juego se empaqueta directamente en Python (Base64) con `embed_rom.py`. El servidor arranca con el juego listo, sin depender de archivos externos ni de tu PC.
- **Soporte de Controles Xbox por Bluetooth:**
  - En la versión web: usa la **HTML5 Gamepad API** estándar del navegador. Solo enciende tu control Xbox Bluetooth y conéctalo a tu PC, móvil o tablet.
  - En la versión local (`main.py`): usa `pygame.joystick` y XInput.
- **Mappers soportados:**
  - Mapper 0 (NROM) — *Super Mario Bros., Donkey Kong, Balloon Fight*
  - Mapper 1 (MMC1) — *The Legend of Zelda, Metroid, Mega Man 2*
  - Mapper 2 (UxROM) — *Contra, Castlevania, Duck Tales*
  - Mapper 3 (CNROM) — *Arkanoid, Solomon's Key, Gradius*
  - Mapper 4 (MMC3) — *Super Mario Bros. 3, Kirby's Adventure, Mega Man 3-6*
- **Efecto visual CRT TV:** Filtro de líneas de escaneo retro conmutable en el navegador.
- **Controles táctiles virtuales:** Para jugar desde el teléfono o tablet.

---

## 📁 Estructura del Proyecto

```
nes-emulator/
├── server.py              # Servidor FastAPI + WebSocket para streaming web
├── embed_rom.py           # Herramienta para incrustar ROMs .nes en Python
├── embedded_rom.py        # ROM activa incrustada en Base64
├── main.py                # Modo escritorio clásico con pygame (opcional)
├── cpu.py                 # CPU MOS 6502 completa (256 opcodes oficiales)
├── ppu.py                 # PPU (gráficos 256x240, sprites, scrolling, paleta)
├── apu.py                 # APU (canales Pulse 1/2, Triangle, Noise)
├── memory.py              # Bus de memoria con mapeo y DMA de 256 bytes
├── cartridge.py           # Lector de ROMs iNES y gestor de bancos
├── controller.py          # Gestor de controles Xbox / Teclado
├── mappers/               # Mappers 0, 1, 2, 3 y 4
├── web/
│   └── index.html         # Cliente web HTML5 + Canvas + Gamepad API
├── Dockerfile             # Despliegue en contenedores en la nube
├── railway.toml           # Configuración para Railway
└── requirements.txt       # Dependencias de Python
```

---

## 🕹️ Paso 1: Incrustar tu juego en el código

Para incrustar tu ROM `.nes` en el proyecto y que viaje dentro del código:

```powershell
python embed_rom.py "C:\ruta\a\tu_juego.nes"
```

Esto generará automáticamente el archivo `embedded_rom.py` con el juego integrado en Base64.  
*(Si no tienes una ROM a mano, ya viene una ROM de prueba autogenerada por defecto).*

---

## 💻 Paso 2: Probarlo en tu navegador localmente

1. Inicia el servidor web:
   ```powershell
   python server.py
   ```
2. Abre tu navegador en:
   ```
   http://localhost:8000
   ```
3. Haz clic en **INICIAR PARTIDA**.

---

## ☁️ Paso 3: Subirlo a la nube (Para jugar sin tu PC)

Para que el juego esté en línea 24/7 y puedas jugarlo desde cualquier parte del mundo (PC del trabajo, celular, tablet, amigos):

### Opción A: Despliegue en Railway (Recomendado)
1. Sube esta carpeta a un repositorio privado o público en **GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Emulador NES Cloud con juego incrustado"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/nes-emulator.git
   git push -u origin main
   ```
2. Ve a [Railway.app](https://railway.app/) e inicia sesión con GitHub.
3. Haz clic en **New Project** → **Deploy from GitHub repo** y selecciona `nes-emulator`.
4. Railway detectará automáticamente el `Dockerfile` y generará una URL pública segura (ej: `https://nes-emulator-production.up.railway.app`).
5. ¡Listo! Abre el link desde cualquier dispositivo.

### Opción B: Despliegue en Render (Gratis)
1. Ve a [Render.com](https://render.com/).
2. Haz clic en **New** → **Web Service**.
3. Conecta tu repositorio de GitHub.
4. En **Environment**, selecciona **Docker**.
5. En el plan, elige el plan gratuito (**Free**).
6. Haz clic en **Create Web Service**.

---

## 🎮 Controles

### Control Xbox (Bluetooth / USB)
Al conectar tu control Xbox a tu equipo por Bluetooth o USB, el navegador lo detecta inmediatamente:

| Control Xbox | Función en el NES |
|---|---|
| **Botón A** | Botón A |
| **Botón B** | Botón B |
| **Botón X** | Turbo A |
| **Botón Y** | Turbo B |
| **Start** | Start |
| **Back / View** | Select |
| **D-Pad / Stick Izquierdo** | Direcciones (Arriba, Abajo, Izquierda, Derecha) |

### Teclado (Fallback)
- **Z / Espacio**: Botón A
- **X**: Botón B
- **C**: Turbo A
- **V**: Turbo B
- **Enter**: Start
- **Shift**: Select
- **Flechas / WASD**: D-Pad
