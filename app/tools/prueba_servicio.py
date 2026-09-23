r"""Comprueba las herramientas contra un servidor de verdad.

Levanta uvicorn en un hilo y le habla por HTTP a 127.0.0.1. No usa un cliente
de mentira contra la aplicación en memoria: la regla del proyecto es verificar
contra el stack levantado, y un transporte simulado no prueba ni el servidor
ni la serialización ni las cabeceras.

Uso:  .\.venv\Scripts\python.exe -m app.tools.prueba_servicio
"""

from __future__ import annotations

import threading
import time

import httpx
import uvicorn

from app.tools.service import app

PUERTO = 8123
BASE = f"http://127.0.0.1:{PUERTO}"

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"  ok  {nombre}")
    else:
        fallos += 1
        print(f"  MAL {nombre}    {detalle}")


def main() -> int:
    servidor = uvicorn.Server(uvicorn.Config(app, port=PUERTO, log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()

    for _ in range(50):
        if servidor.started:
            break
        time.sleep(0.1)
    if not servidor.started:
        print("el servidor no arrancó")
        return 2

    try:
        with httpx.Client(base_url=BASE, timeout=10) as c:
            comprobar("responde /salud", c.get("/salud").json()["estado"] == "vivo")

            r = c.post("/consultar_identidad", json={"documento": "1070234567"}).json()
            comprobar("encuentra al cliente", r.get("id_cliente") == "CL-0001", str(r))

            # El documento viene de la voz: el ASR puede meter puntos o espacios.
            r = c.post("/consultar_identidad", json={"documento": "1.070.234.567"}).json()
            comprobar("limpia puntos del documento", r.get("id_cliente") == "CL-0001", str(r))

            r = c.post("/consultar_identidad", json={"documento": "9999999"}).json()
            comprobar("distingue no encontrado de error",
                      r.get("encontrado") is False, str(r))

            r = c.post("/estado_tarjeta", json={"id_cliente": "CL-0001"}).json()
            comprobar("devuelve la tarjeta bloqueada",
                      r["tarjetas"][0]["estado"] == "bloqueada", str(r))

            # Idempotencia: el mismo turno reintentado no abre dos tickets.
            uno = c.post("/escalar_a_humano",
                         json={"motivo": "prueba", "clave_idempotencia": "t-1"}).json()
            dos = c.post("/escalar_a_humano",
                         json={"motivo": "prueba", "clave_idempotencia": "t-1"}).json()
            comprobar("escalar dos veces con la misma clave da un solo ticket",
                      uno["ticket"] == dos["ticket"], f"{uno} vs {dos}")
            comprobar("la segunda se marca como repetida", dos["repetida"] is True)

            otro = c.post("/escalar_a_humano",
                          json={"motivo": "prueba", "clave_idempotencia": "t-2"}).json()
            comprobar("una clave distinta sí abre otro ticket",
                      otro["ticket"] != uno["ticket"])

            r = c.post("/consultar_identidad", json={"documento": "1070234567"},
                       headers={"X-Fallar": "core-caido"})
            comprobar("se puede provocar el fallo", r.status_code == 503, str(r.status_code))

            arranque = time.perf_counter()
            c.post("/consultar_identidad", json={"documento": "1070234567"},
                   headers={"X-Tardar-Ms": "300"})
            tardanza = (time.perf_counter() - arranque) * 1000
            comprobar(f"se puede provocar el retraso ({tardanza:.0f} ms)",
                      280 <= tardanza <= 600, f"{tardanza:.0f} ms")
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    print(f"\n{'todo bien' if not fallos else str(fallos) + ' comprobaciones fallidas'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
