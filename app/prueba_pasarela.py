r"""Comprueba la pasarela entera contra un servidor levantado.

Empuja un WAV por el WebSocket en trozos de 20 ms, igual que haría el
navegador, y comprueba que del otro lado sale una conversación: se oye lo
dicho, se llama a una herramienta, se contesta, y vuelve audio de verdad.

No sustituye a abrir la página —el micrófono, el remuestreo y la reproducción
solo se prueban ahí— pero sí cubre todo lo que está detrás del socket, que es
donde está la lógica.

Uso:  .\.venv\Scripts\python.exe -m app.prueba_pasarela
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import uvicorn
import websockets

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "probe"))

from app.agent.loop import TEXTO_FALLO_DEL_MODELO  # noqa: E402
from app.gateway import app  # noqa: E402

PUERTO = 8141
MUESTRAS_POR_TROZO = 320  # 20 ms a 16 kHz

fallos = 0
saltadas = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "",
              incidencia: str = "") -> None:
    """Comprueba algo, salvo que el proveedor del modelo se haya caido.

    Con un 429, el agente escala a un humano -que es lo correcto- y entonces
    "contesta algo" y "llama a alguna herramienta" se cumplen solas. Esta
    prueba salia VERDE con el modelo caido, y verde no puede significar "no lo
    he mirado". Una comprobacion saltada no es una comprobacion pasada, asi
    que el programa acaba en 3.
    """
    global fallos, saltadas
    if incidencia:
        saltadas += 1
        print(f"  --  {nombre}    SALTADA: {incidencia}")
    elif condicion:
        print(f"  ok  {nombre}")
    else:
        fallos += 1
        print(f"  MAL {nombre}    {detalle}")


async def hablar_y_escuchar(ruta: Path) -> dict:
    with wave.open(str(ruta), "rb") as w:
        crudo = w.readframes(w.getnframes())
    muestras = np.frombuffer(crudo, dtype=np.int16)

    recogido = {"oido": [], "dice": [], "herramientas": [], "tiempos": None,
                "bytes_audio": 0, "estados": []}

    async with websockets.connect(f"ws://127.0.0.1:{PUERTO}/ws",
                                  max_size=None) as ws:
        async def escuchar() -> None:
            try:
                async for mensaje in ws:
                    if isinstance(mensaje, bytes):
                        recogido["bytes_audio"] += len(mensaje)
                        # El navegador avisa al terminar de reproducir; aquí se
                        # avisa enseguida, porque no hay altavoz que esperar.
                        await ws.send(json.dumps({"fin": "reproduccion"}))
                        continue
                    m = json.loads(mensaje)
                    if m["tipo"] == "oido":
                        recogido["oido"].append(m["texto"])
                    elif m["tipo"] == "dice":
                        recogido["dice"].append((m["datos"]["clase"], m["texto"]))
                    elif m["tipo"] == "herramienta":
                        recogido["herramientas"].append(m["texto"])
                    elif m["tipo"] == "tiempos":
                        recogido["tiempos"] = m["datos"]
                    elif m["tipo"] == "estado":
                        recogido["estados"].append(m["texto"])
            except websockets.ConnectionClosed:
                pass

        tarea = asyncio.create_task(escuchar())

        # En tiempo real, como el navegador: si se vuelca de golpe, el detector
        # de fin de habla ve toda la intervención en un instante y la medición
        # de latencia deja de significar nada.
        arranque = time.perf_counter()
        for i in range(0, len(muestras), MUESTRAS_POR_TROZO):
            trozo = muestras[i:i + MUESTRAS_POR_TROZO]
            objetivo = arranque + (i + len(trozo)) / 16000
            espera = objetivo - time.perf_counter()
            if espera > 0:
                await asyncio.sleep(espera)
            await ws.send(trozo.tobytes())

        # Margen para que termine el turno que se disparó con el último trozo.
        await asyncio.sleep(12)
        tarea.cancel()
    return recogido


async def llamada_de_twilio(ruta_wav: Path) -> dict:
    """Una llamada entera por el endpoint de Twilio, con un WebSocket de verdad.

    El emulador de la secuencia de Twilio se importa de `app.prueba_telefonia`
    en vez de copiarse: dos emuladores del mismo protocolo se despegan en
    cuanto alguien toca uno, y entonces una de las dos pruebas empieza a
    comprobar un protocolo que no existe.

    Lo que esto añade sobre `prueba_telefonia` es el transporte local: que el
    endpoint acepte el socket, que reciba texto y que devuelva texto. Lo único
    que queda sin comprobar después de esto es Twilio en sí y el túnel.
    """
    from app.prueba_telefonia import mensajes_de_twilio  # noqa: PLC0415

    with wave.open(str(ruta_wav), "rb") as w:
        crudo = w.readframes(w.getnframes())
    audio = np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / 32768.0

    recogido: dict = {"media": 0, "marcas": 0, "bytes_audio": 0, "otros": []}
    async with websockets.connect(f"ws://127.0.0.1:{PUERTO}/twilio",
                                  max_size=None) as ws:
        async def recoger():
            async for crudo_mensaje in ws:
                mensaje = json.loads(crudo_mensaje)
                if mensaje.get("event") == "media":
                    recogido["media"] += 1
                    recogido["bytes_audio"] += len(
                        base64.b64decode(mensaje["media"]["payload"]))
                elif mensaje.get("event") == "mark":
                    recogido["marcas"] += 1
                else:
                    recogido["otros"].append(mensaje.get("event"))

        tarea = asyncio.ensure_future(recoger())
        for mensaje in mensajes_de_twilio(audio):
            if mensaje["event"] == "stop":
                # El stop va al final, después de esperar la respuesta.
                await asyncio.sleep(14)
                await ws.send(json.dumps(mensaje))
                break
            await ws.send(json.dumps(mensaje))
        await asyncio.sleep(1)
        tarea.cancel()
    return recogido


def main() -> int:
    servidor = uvicorn.Server(uvicorn.Config(app, port=PUERTO, log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(600):   # cargar los modelos tarda unos segundos
        if servidor.started:
            break
        time.sleep(0.1)
    if not servidor.started:
        print("la pasarela no arrancó")
        return 2

    import httpx
    pagina = httpx.get(f"http://127.0.0.1:{PUERTO}/", timeout=10)
    comprobar("sirve la página", pagina.status_code == 200
              and "AudioWorklet" in pagina.text)

    # El endpoint que Twilio pide al recibir una llamada. Se comprueba aquí y no
    # en `prueba_telefonia` porque aquí hay un servidor de verdad escuchando:
    # allí se comprueba el protocolo, y esto es el transporte.
    voz = httpx.post(f"http://127.0.0.1:{PUERTO}/twilio/voz", timeout=10)
    comprobar("responde el TwiML que Twilio pide al entrar una llamada",
              voz.status_code == 200 and "<Connect>" in voz.text
              and "/twilio" in voz.text, voz.text[:120])
    comprobar("y lo manda por wss, que es lo único que Twilio acepta",
              "wss://" in voz.text, voz.text[:120])

    # --- y la llamada de teléfono completa, por el socket de verdad
    ruta_twilio = RAIZ / "artifacts" / "muestra-documento.wav"
    if ruta_twilio.exists():
        print()
        print("  llamando por el endpoint de Twilio (socket real, audio µ-law)...")
        t = asyncio.run(llamada_de_twilio(ruta_twilio))
        print(f"  de vuelta: {t['media']} trozos de audio "
              f"({t['bytes_audio']} bytes de µ-law), {t['marcas']} marca(s)")
        comprobar("el endpoint de Twilio acepta el socket y contesta audio",
                  t["media"] > 0, str(t))
        comprobar("en trozos de 160 bytes, que son los 20 ms de la línea",
                  t["bytes_audio"] % 160 == 0,
                  f"{t['bytes_audio']} bytes no es múltiplo de 160")
        comprobar("y manda la marca de fin para saber cuándo calló",
                  t["marcas"] > 0, str(t["marcas"]))

    ruta = RAIZ / "artifacts" / "muestra-libre-datos.wav"
    if not ruta.exists():
        print(f"falta {ruta}", file=sys.stderr)
        return 2

    print(f"\n  empujando {ruta.name} por el socket, en tiempo real...")
    r = asyncio.run(hablar_y_escuchar(ruta))

    print(f"\n  oído      : {r['oido']}")
    print(f"  dicho     : {r['dice']}")
    print(f"  herramientas: {r['herramientas']}")
    print(f"  tiempos   : {r['tiempos']}")
    print(f"  audio devuelto: {r['bytes_audio']} bytes\n")

    comprobar("transcribe lo que se dijo", bool(r["oido"]) and len(r["oido"][0]) > 10,
              str(r["oido"]))
    # Se reconoce por la constante del bucle, no por un trozo de texto
    # copiado: el dia que la frase cambie, esto seguiria mirando la vieja y
    # volveria a dar verde con el modelo caido.
    fallo = any(TEXTO_FALLO_DEL_MODELO in texto for _, texto in r["dice"])
    incidencia = "el modelo fallo (429 o 400) y el agente escalo" if fallo else ""

    comprobar("contesta algo", bool(r["dice"]), str(r["dice"]))
    comprobar("devuelve audio de verdad", r["bytes_audio"] > 10000,
              f"{r['bytes_audio']} bytes")
    comprobar("informa de los dos tiempos",
              bool(r["tiempos"]) and r["tiempos"]["primer_audio_ms"] > 0
              and r["tiempos"]["primer_dato_ms"] > 0, str(r["tiempos"]))
    comprobar("llama a alguna herramienta", bool(r["herramientas"]),
              str(r["herramientas"]), incidencia=incidencia)

    servidor.should_exit = True
    hilo.join(timeout=5)
    if saltadas:
        print(f"\n{saltadas} comprobación(es) SALTADAS porque el modelo se "
              f"cayó. Repite la prueba: esto no es verde.")
    print(f"\n{'todo bien' if not fallos else str(fallos) + ' comprobaciones fallidas'}")
    if fallos:
        return 1
    return 3 if saltadas else 0


if __name__ == "__main__":
    raise SystemExit(main())
