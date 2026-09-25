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
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
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

    from app.estado import desde_entorno as estado_desde_entorno
    from app.expediente import desde_entorno
    expediente = desde_entorno()
    print(f"Expediente: {type(expediente).__name__}")
    estado = estado_desde_entorno()
    print(f"Estado de la llamada: {type(estado).__name__}"
          + ("" if estado.compartido else "  (NO compartido: no se puede "
                                          "retomar en otra pasarela)"))

    entorno = cargar_env()
    from groq import Groq
    PIEZAS.update({
        "asr": asr,
        "voz": voz,
        "groq": Groq(api_key=entorno["GROQ_API_KEY"].strip(), max_retries=0),
        "modelo": entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip(),
        "dispositivo": dispositivo,
        "expediente": expediente,
        "estado": estado,
    })
    print("\nListo.  ->  http://127.0.0.1:8000/\n")


@app.api_route("/twilio/voz", methods=["GET", "POST"])
async def twilio_voz(peticion: Request) -> Response:
    """Lo que Twilio pide cuando entra una llamada: a dónde conectarse.

    La URL del WebSocket sale de `TWILIO_STREAM_URL` si está puesta, y si no se
    construye desde la petición cambiando el esquema a `wss`. Lo segundo
    funciona detrás de un túnel y es lo que ahorra un paso al probar; lo primero
    es lo que hay que usar en cualquier sitio serio, porque una URL deducida de
    una cabecera es una URL que alguien puede cambiar desde fuera.
    """
    from app.telefonia import twiml  # noqa: PLC0415

    url = os.environ.get("TWILIO_STREAM_URL")
    if not url:
        anfitrion = peticion.headers.get("host", "127.0.0.1:8000")
        url = f"wss://{anfitrion}/twilio"
    return Response(content=twiml(url), media_type="application/xml")


@app.websocket("/twilio")
async def twilio_stream(ws: WebSocket) -> None:
    """Una llamada de teléfono de verdad, si hay un túnel delante.

    Twilio manda todo por texto: JSON con el audio en base64. El puente no sabe
    de red —`app/telefonia/media_streams.py`— así que aquí solo queda recibir,
    pasarle el mensaje y enviar lo que devuelva.
    """
    from app.telefonia import PuenteTwilio  # noqa: PLC0415

    await ws.accept()
    agente = Agente(PIEZAS["groq"], PIEZAS["modelo"], BASE_HERRAMIENTAS,
                    adelantar=True)
    # `permitir_interrupcion=True` solo aquí: por teléfono la línea ya cancela
    # el eco, así que se puede escuchar mientras el agente habla. En el
    # navegador sigue apagado, y el motivo está en `app/vivo.py`.
    llamada = Llamada(PIEZAS["asr"], PIEZAS["voz"], agente,
                      expediente=PIEZAS.get("expediente"),
                      permitir_interrupcion=True)
    puente = PuenteTwilio(llamada)
    almacen_estado = PIEZAS.get("estado")

    try:
        while True:
            mensaje = await ws.receive()
            if mensaje.get("type") == "websocket.disconnect":
                break
            crudo = mensaje.get("text")
            if crudo is None:
                continue
            for salida in puente.al_recibir(crudo):
                await ws.send_text(json.dumps(salida))
            if puente.terminada:
                break
            if almacen_estado and puente.transcripciones:
                almacen_estado.guardar(llamada.id_llamada,
                                       llamada.exportar_estado())
    except WebSocketDisconnect:
        pass
    finally:
        llamada.colgar()
        if puente.call_sid:
            print(f"  llamada de Twilio {puente.call_sid} terminada: "
                  f"{len(puente.transcripciones)} turno(s)")


@app.get("/", response_class=HTMLResponse)
def pagina() -> str:
    return (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")


@app.websocket("/ws")
async def conversacion(ws: WebSocket) -> None:
    await ws.accept()
    agente = Agente(PIEZAS["groq"], PIEZAS["modelo"], BASE_HERRAMIENTAS,
                    adelantar=True)
    llamada = Llamada(PIEZAS["asr"], PIEZAS["voz"], agente,
                      expediente=PIEZAS.get("expediente"))

    # Retomar una llamada empezada en otra pasarela. El navegador vuelve con
    # `?llamada=<id>` y aquí se recoge la conversación donde se quedó: es lo
    # que hace cierta la frase de que esta pasarela no guarda nada suyo.
    almacen_estado = PIEZAS.get("estado")
    retomada = ws.query_params.get("llamada")
    if retomada and almacen_estado is not None:
        guardado = almacen_estado.cargar(retomada)
        if guardado:
            llamada.importar_estado(guardado)
            print(f"  llamada {retomada} retomada en esta pasarela")

    await ws.send_text(json.dumps({
        "tipo": "estado", "texto": "escuchando",
        "datos": {"dispositivo": PIEZAS["dispositivo"],
                  "llamada": llamada.id_llamada,
                  "retomada": bool(retomada and almacen_estado
                                   and almacen_estado.cargar(retomada))}}))

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

            # Un turno cerrado es el momento de guardar: una vez por turno y
            # no una vez por trozo de audio, que es lo que hace esto barato.
            if any(a.tipo == "tiempos" for a in avisos) and almacen_estado:
                almacen_estado.guardar(llamada.id_llamada,
                                       llamada.exportar_estado())

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
    finally:
        # Colgar es el momento en que el expediente deja de crecer, así que es
        # el momento de cerrarlo. Va en `finally` porque una llamada que acaba
        # mal es justo la que más falta hace poder leer después.
        llamada.colgar()
