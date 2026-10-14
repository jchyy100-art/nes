"""
server.py — Servidor Web en la Nube para Emulador NES
======================================================
Servidor FastAPI + WebSocket que corre el emulador NES en segundo
plano, transmite los fotogramas en tiempo real al navegador y recibe
los comandos del control Xbox o teclado con baja latencia.

Uso local:
    python server.py

Despliegue en la nube (Railway / Render):
    uvicorn server:app --host 0.0.0.0 --port $PORT
"""

import os
import sys
import io
import time
import asyncio
from typing import Set
from PIL import Image
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# ─── Importar componentes del emulador ───
from memory import Bus
from cpu import CPU
from ppu import PPU
from apu import APU
from cartridge import Cartridge
from controller import Controller

# ─── Importar ROM incrustada ───
try:
    import embedded_rom
    DEFAULT_ROM_NAME = getattr(embedded_rom, "ROM_NAME", "NES Game")
    DEFAULT_ROM_BYTES = embedded_rom.get_rom_bytes()
except Exception as e:
    print(f"[WARN] No se encontro embedded_rom.py: {e}")
    DEFAULT_ROM_NAME = "NES Demo"
    DEFAULT_ROM_BYTES = None


app = FastAPI(title="NES Cloud Emulator")

# Ruta absoluta del directorio web
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
INDEX_PATH = os.path.join(WEB_DIR, "index.html")


@app.get("/")
async def get_index():
    """Sirve la página web del emulador."""
    return FileResponse(INDEX_PATH)


@app.get("/health")
async def health_check():
    """Ruta de comprobación de salud para Railway / Render."""
    return {"status": "ok", "game": DEFAULT_ROM_NAME}


# Servir archivos estáticos adicionales si los hubiera
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def create_emulator_instance(rom_bytes: bytes):
    """Crea una sesión aislada del emulador NES para el jugador."""
    bus = Bus()
    cart = Cartridge(rom_bytes)
    bus.cart = cart

    ppu = PPU(bus)
    bus.ppu = ppu

    apu = APU(bus)
    bus.apu = apu

    cpu = CPU(bus)
    bus.cpu = cpu

    ctrl1 = Controller(player=1)
    ctrl2 = Controller(player=2)
    bus.ctrl1 = ctrl1
    bus.ctrl2 = ctrl2

    bus.reset()
    return bus


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Canal WebSocket bidireccional:
    - Servidor -> Cliente: Fotogramas de video comprimidos (JPEG binario)
    - Cliente -> Servidor: Estado de botones del control (1 byte binario) o ping JSON
    """
    await websocket.accept()
    print("[WS] Jugador conectado desde el navegador.")

    # Verificar que haya una ROM disponible
    if not DEFAULT_ROM_BYTES:
        await websocket.send_json({
            "type": "error",
            "message": "No hay ninguna ROM incrustada configurada."
        })
        await websocket.close()
        return

    # Iniciar instancia del emulador
    try:
        bus = create_emulator_instance(DEFAULT_ROM_BYTES)
    except Exception as e:
        print(f"[ERROR] Error al crear instancia de emulador: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})
        await websocket.close()
        return

    # Notificar nombre de la ROM
    await websocket.send_json({
        "type": "info",
        "title": DEFAULT_ROM_NAME
    })

    stop_event = asyncio.Event()

    # ─── Tarea de recepción de input ───
    async def receive_inputs():
        try:
            while not stop_event.is_set():
                message = await websocket.receive()
                if "bytes" in message and message["bytes"]:
                    # Paquete binario con máscara de botones (1 byte)
                    btn_mask = message["bytes"][0]
                    bus.ctrl1.set_button_mask(btn_mask)
                elif "text" in message and message["text"]:
                    # Mensajes de control/ping
                    if '"ping"' in message["text"]:
                        await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            stop_event.set()

    # ─── Tarea de emulación y streaming de video ───
    async def stream_frames():
        target_fps = 60
        frame_time = 1.0 / target_fps
        jpeg_quality = 70   # Óptimo equilibrio calidad/latencia

        try:
            while not stop_event.is_set():
                start = time.perf_counter()

                # Ejecutar hasta completar un frame completo de la PPU
                bus.ppu.frame_ready = False
                while not bus.ppu.frame_ready:
                    bus.clock()

                # Comprimir framebuffer (240, 256, 3) a JPEG en memoria
                img = Image.fromarray(bus.ppu.framebuffer)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=jpeg_quality, optimize=False)
                frame_bytes = buf.getvalue()

                # Enviar frame binario al navegador
                await websocket.send_bytes(frame_bytes)

                # Control de velocidad de fotogramas (60 FPS estables)
                elapsed = time.perf_counter() - start
                sleep_time = frame_time - elapsed
                if sleep_time > 0.001:
                    await asyncio.sleep(sleep_time)
                else:
                    # Ceder brevemente el loop de eventos
                    await asyncio.sleep(0.001)

        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[WS] Streaming finalizado: {e}")
        finally:
            stop_event.set()

    input_task = asyncio.create_task(receive_inputs())
    stream_task = asyncio.create_task(stream_frames())

    done, pending = await asyncio.wait(
        [input_task, stream_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    for task in pending:
        task.cancel()

    print("[WS] Jugador desconectado.")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"\n=======================================================")
    print(f"  NES Cloud Emulator — Servidor en ejecución")
    print(f"  Abre en tu navegador: http://localhost:{port}")
    print(f"  Juego incrustado: {DEFAULT_ROM_NAME}")
    print(f"=======================================================\n")
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
