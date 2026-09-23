r"""La pasarela: navegador por un lado, tubería por el otro.

Sirve la página y atiende el WebSocket por el que llega el audio. El estado de
cada llamada vive en su objeto `Llamada`, no aquí: la pasarela es un tubo.

**El micrófono solo funciona en `localhost` o en `https`.** Por la IP de la red
el navegador bloquea `getUserMedia` sin avisar de nada, y se pierde media tarde
buscando el fallo en el código. Abrir siempre http://127.0.0.1:8000/

Levantar:
  .\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "probe"))

from common import cargar_env  # noqa: E402

from app.agent.loop import Agente  # noqa: E402
from app.tools.service import app as app_herramientas  # noqa: E402
from app.vivo import Llamada  # noqa: E402

PUERTO_HERRAMIENTAS = 8100
BASE_HERRAMIENTAS = f"http://127.0.0.1:{PUERTO_HERRAMIENTAS}"

app = FastAPI(title="Agente de voz")

PIEZAS: dict = {}


@app.on_event("startup")
def arrancar() -> None:
    """Carga los modelos y levanta las herramientas.

    Se hace al arrancar y no en la primera llamada porque cargar el voz a texto
    tarda cuatro segundos: hacerlo con alguien al teléfono sería regalar esos
    cuatro segundos al primer turno.
    """
    from piper import PiperVoice
    from probe_whisper_local import cargar_modelo

    servidor = uvicorn.Server(uvicorn.Config(
        app_herramientas, port=PUERTO_HERRAMIENTAS, log_level="error"))
    threading.Thread(target=servidor.run, daemon=True).start()
    for _ in range(50):
        if servidor.started:
            break
        time.sleep(0.1)

    print("Cargando voz a texto...")
    asr, dispositivo, _, _ = cargar_modelo("small")
    print(f"  {dispositivo}")
    print("Cargando texto a voz...")
    voz = PiperVoice.load(str(RAIZ / "voices" / "es_MX-claude-high.onnx"))

    entorno = cargar_env()
    from groq import Groq
    PIEZAS.update({
        "asr": asr,
        "voz": voz,
        "groq": Groq(api_key=entorno["GROQ_API_KEY"].strip(), max_retries=0),
        "modelo": entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip(),
        "dispositivo": dispositivo,
    })
    print("\nListo.  ->  http://127.0.0.1:8000/\n")


@app.get("/", response_class=HTMLResponse)
def pagina() -> str:
    return (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")


@app.websocket("/ws")
async def conversacion(ws: WebSocket) -> None:
    await ws.accept()
    agente = Agente(PIEZAS["groq"], PIEZAS["modelo"], BASE_HERRAMIENTAS,
                    adelantar=True)
    llamada = Llamada(PIEZAS["asr"], PIEZAS["voz"], agente)

    await ws.send_text(json.dumps({
        "tipo": "estado", "texto": "escuchando",
        "datos": {"dispositivo": PIEZAS["dispositivo"]}}))

    try:
        while True:
            mensaje = await ws.receive()
            if mensaje.get("type") == "websocket.disconnect":
                break

            # El navegador avisa por texto cuando ha terminado de reproducir.
            # Sin ese aviso el micrófono sigue abierto mientras el agente
            # habla y el sistema se oye a sí mismo. La cancelación de eco de
            # verdad iría aquí; mientras no exista, se cierra la entrada
            # mientras suena la respuesta, y se dice.
            if mensaje.get("text") is not None:
                if json.loads(mensaje["text"]).get("fin") == "reproduccion":
                    llamada.hablando = False
                continue
            if mensaje.get("bytes") is None:
                continue

            muestras = np.frombuffer(mensaje["bytes"],
                                     dtype=np.int16).astype(np.float32) / 32768.0
            avisos = llamada.empujar(muestras)

            for aviso in avisos:
                if aviso.tipo == "dice":
                    # El audio va en binario y la etiqueta en texto justo antes,
                    # para que la pantalla sepa de qué es el audio que viene.
                    llamada.hablando = True
                    await ws.send_text(json.dumps({
                        "tipo": "dice", "texto": aviso.texto,
                        "datos": {"clase": aviso.datos["clase"],
                                  "frecuencia": aviso.datos["frecuencia"]}}))
                    await ws.send_bytes(aviso.datos["pcm"])
                else:
                    await ws.send_text(json.dumps({
                        "tipo": aviso.tipo, "texto": aviso.texto,
                        "datos": aviso.datos}))
    except WebSocketDisconnect:
        pass
