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
import json
import base64
import asyncio
from typing import Set, Optional
from PIL import Image
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

CURRENT_ROM_NAME = DEFAULT_ROM_NAME
CURRENT_ROM_BYTES = DEFAULT_ROM_BYTES


class RomUploadModel(BaseModel):
    name: str
    data: str   # Base64 encoded .nes file


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
    return {"status": "ok", "game": CURRENT_ROM_NAME or DEFAULT_ROM_NAME}


@app.get("/api/download_current_rom")
async def download_current_rom():
    from fastapi.responses import Response
    if CURRENT_ROM_BYTES:
        return Response(content=bytes(CURRENT_ROM_BYTES), media_type="application/octet-stream")
    return {"error": "No ROM in memory"}


@app.get("/api/debug_run")
async def debug_run():
    import traceback
    try:
        rom = CURRENT_ROM_BYTES or DEFAULT_ROM_BYTES
        if not rom:
            return {"ok": False, "error": "No ROM in memory"}
        bus = create_emulator_instance(rom)
        for _ in range(10000):
            bus.clock()
        return {
            "ok": True,
            "game": CURRENT_ROM_NAME,
            "mapper": bus.cart.mapper_id,
            "pc": f"{bus.cpu.PC:04X}",
            "palette": list(bus.ppu.palette[:16])
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/upload_rom")
async def upload_rom_api(payload: RomUploadModel):
    """Permite subir una ROM en Base64 desde el navegador para fijarla en el servidor."""
    global CURRENT_ROM_NAME, CURRENT_ROM_BYTES
    try:
        raw_bytes = base64.b64decode(payload.data)
        if len(raw_bytes) < 16 or raw_bytes[:4] != b"NES\x1a":
            return {"ok": False, "error": "El archivo no es una ROM NES válida (formato iNES requerido)."}
        
        CURRENT_ROM_NAME = payload.name
        CURRENT_ROM_BYTES = raw_bytes
        print(f"[SERVER] Nueva ROM fijada en la nube: {CURRENT_ROM_NAME} ({len(raw_bytes)} bytes)")
        return {"ok": True, "name": CURRENT_ROM_NAME, "size": len(raw_bytes)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
    apu.audio_enabled = False
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
    active_rom_bytes = CURRENT_ROM_BYTES or DEFAULT_ROM_BYTES
    active_rom_name = CURRENT_ROM_NAME or DEFAULT_ROM_NAME

    if not active_rom_bytes:
        await websocket.send_json({
            "type": "error",
            "message": "No hay ninguna ROM configurada en el servidor."
        })
        await websocket.close()
        return

    # Iniciar instancia del emulador
    try:
        bus = create_emulator_instance(active_rom_bytes)
    except Exception as e:
        print(f"[ERROR] Error al crear instancia de emulador: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})
        await websocket.close()
        return

    # Notificar nombre de la ROM
    await websocket.send_json({
        "type": "info",
        "title": active_rom_name
    })

    stop_event = asyncio.Event()

    # ─── Tarea de recepción de input y comandos ───
    async def receive_inputs():
        nonlocal bus
        try:
            while not stop_event.is_set():
                message = await websocket.receive()
                if "bytes" in message and message["bytes"]:
                    # Paquete binario con máscara de botones (1 byte)
                    btn_mask = message["bytes"][0]
                    bus.ctrl1.set_button_mask(btn_mask)
                elif "text" in message and message["text"]:
                    try:
                        data = json.loads(message["text"])
                        msg_type = data.get("type")
                        if msg_type == "ping":
                            await websocket.send_json({"type": "pong"})
                        elif msg_type == "load_rom":
                            rom_b64 = data.get("data")
                            rom_name = data.get("name", "Juego")
                            if rom_b64:
                                raw_bytes = base64.b64decode(rom_b64)
                                if len(raw_bytes) >= 16 and raw_bytes[:4] == b"NES\x1a":
                                    global CURRENT_ROM_NAME, CURRENT_ROM_BYTES
                                    CURRENT_ROM_NAME = rom_name
                                    CURRENT_ROM_BYTES = raw_bytes
                                    bus = create_emulator_instance(raw_bytes)
                                    await websocket.send_json({"type": "info", "title": rom_name})
                                    print(f"[WS] ROM cambiada en vivo con éxito a: {rom_name}")
                                else:
                                    await websocket.send_json({"type": "error", "message": "El archivo no es una ROM NES válida."})
                    except Exception as err:
                        print(f"[WS] Error en mensaje: {err}")
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
        jpeg_quality = 65
        frame_skip = 2

        try:
            while not stop_event.is_set():
                start = time.perf_counter()

                current_bus = bus
                for _ in range(frame_skip):
                    current_bus.ppu.frame_ready = False
                    while not current_bus.ppu.frame_ready:
                        current_bus.clock()

                img = Image.fromarray(current_bus.ppu.framebuffer)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=jpeg_quality, optimize=False)
                frame_bytes = buf.getvalue()

                await websocket.send_bytes(frame_bytes)

                elapsed = time.perf_counter() - start
                sleep_time = (frame_time * frame_skip) - elapsed
                if sleep_time > 0.001:
                    await asyncio.sleep(sleep_time)
                else:
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
    port = int(os.environ.get("PORT", "8080").strip())
    print(f"\n=======================================================")
    print(f"  NES Cloud Emulator — Servidor en ejecución")
    print(f"  Abre en tu navegador: http://localhost:{port}")
    print(f"  Juego incrustado: {DEFAULT_ROM_NAME}")
    print(f"=======================================================\n")
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
