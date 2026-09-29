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

            # --------------------------------------------- la verificación
            # El documento solo, sin nombre: existe pero NO está verificado, y
            # sobre todo NO sale el id_cliente. Antes del 2026-09-26 esta misma
            # llamada devolvía el nombre del titular, y ahí estaba la fuga.
            r = c.post("/consultar_identidad", json={"documento": "1070234567"}).json()
            comprobar("el documento solo no verifica",
                      r.get("encontrado") is True and r.get("verificado") is False,
                      str(r))
            comprobar("sin verificar no hay id_cliente", "id_cliente" not in r, str(r))
            comprobar("dice qué hacer", "nombre_declarado" in str(r), str(r))

            # El documento viene de la voz: el ASR puede meter puntos o espacios.
            r = c.post("/consultar_identidad",
                       json={"documento": "1.070.234.567",
                             "nombre_declarado": "Juan Diego Ossa"}).json()
            comprobar("limpia puntos del documento y verifica",
                      r.get("id_cliente") == "CL-0001", str(r))

            # El caso que el conjunto de evaluación no perdona: nombre que no es
            # del titular. No verifica y no dice cuál era el bueno.
            r = c.post("/consultar_identidad",
                       json={"documento": "1070234567",
                             "nombre_declarado": "Andrés Gómez Ríos"}).json()
            comprobar("un nombre ajeno no verifica",
                      r.get("verificado") is False and r.get("nombre_coincide") is False,
                      str(r))

            # Tolerancias y límites de la comparación, que son una decisión y
            # están razonados en `_nombre_coincide`.
            for declarado, vale in (("Juan Diego Ossa", True), ("Juan Ossa", True),
                                    ("juan diego ossa", True), ("JUAN OSSA", True),
                                    ("Diego Ossa", True), ("Ossa", False),
                                    ("Juan Diego", False),
                                    ("Juan Diego Ossa Restrepo", False),
                                    ("", False)):
                r = c.post("/consultar_identidad",
                           json={"documento": "1070234567",
                                 "nombre_declarado": declarado}).json()
                comprobar(f"nombre {declarado!r} -> {'verifica' if vale else 'no'}",
                          bool(r.get("verificado")) is vale, str(r))

            # EL INVARIANTE FUERTE: el nombre del titular no puede aparecer en
            # NINGUNA respuesta, ni en la que verifica ni en la que rechaza. Es
            # lo único que hace imposible la fuga en vez de improbable: el
            # modelo no puede decir lo que nunca ha recibido.
            #
            # La primera versión de esta comprobación NO cazaba nada, y se
            # descubrió rompiéndola a propósito el 2026-09-26: hacía
            # `bruto.replace(nombre_declarado, "")` antes de buscar, con la idea
            # de no confundir un eco del nombre declarado con una fuga. Al volver
            # a añadir `"nombre": cliente["nombre"]` a la respuesta, el replace
            # borraba exactamente la cadena que había que detectar y la prueba
            # seguía en verde. Es la categoría 11 de la lista de mediciones
            # falsas —una prueba que pasa con lo que dice proteger roto— cometida
            # dentro de la prueba escrita para evitarla.
            #
            # Se busca en el texto crudo, sin limpiar nada. La herramienta no
            # tiene por qué hacer eco del nombre declarado, así que si aparece es
            # un problema de todos modos.
            for cuerpo in ({"documento": "1070234567"},
                           {"documento": "1070234567",
                            "nombre_declarado": "Juan Diego Ossa"},
                           {"documento": "1070234567",
                            "nombre_declarado": "Andrés Gómez Ríos"},
                           {"documento": "9999999"}):
                bruto = c.post("/consultar_identidad", json=cuerpo).text
                comprobar(f"el nombre del titular no sale con {list(cuerpo)}",
                          "Ossa" not in bruto, bruto)

            r = c.post("/estado_tarjeta", json={"id_cliente": "CL-0001"}).json()
            comprobar("devuelve la tarjeta bloqueada",
                      r["tarjetas"][0]["estado"] == "bloqueada", str(r))

            # Un id_cliente inventado no da datos, y lo dice con lo que hay que
            # hacer: es el atajo que quedaría si alguien adivinara el formato.
            r = c.post("/estado_tarjeta", json={"id_cliente": "CL-9999"}).json()
            comprobar("un id_cliente inventado no da tarjetas",
                      r.get("encontrado") is False and "tarjetas" not in r, str(r))
            comprobar("y explica que hay que verificar primero",
                      "consultar_identidad" in str(r.get("_que_hacer", "")), str(r))

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

            # ---------------------------------------------------------------
            # El esquema que se le anuncia al modelo tiene que describir la
            # herramienta que hay detrás, y hasta el 2026-09-29 no lo hacía.
            #
            # `nombre_declarado` es `str | None` aquí —la primera llamada va sin
            # nombre a propósito— y el esquema lo declaraba `"type": "string"`.
            # Cuando el modelo mandó `null` para decir «todavía no lo tengo»,
            # Groq rechazó la petición entera con un 400 y el agente salió
            # escalando: **un fallo del proveedor contado como decisión del
            # agente**, que es la sexta forma de medición falsa del proyecto.
            # Contaminó 2 de 2 corridas antes de verse.
            #
            # Nadie comprobaba esto, y es el agujero del ADR 0007 otra vez: un
            # desacuerdo que no da error, solo deja de funcionar el día que el
            # modelo usa la parte del contrato que nadie estaba respetando.
            print("\n[esquema] lo que se le anuncia al modelo == lo que acepta "
                  "la herramienta")
            from app.agent.loop import HERRAMIENTAS  # noqa: PLC0415
            from app.tools.service import (ConsultaIdentidad,  # noqa: PLC0415
                                           Escalada, EstadoTarjeta)

            # Campos que la herramienta acepta pero que el MODELO no rellena:
            # los pone el bucle. Hoy solo la clave de idempotencia (ADR 0007).
            # Escribirlos aquí obliga a decidir a cuál de los dos lados va cada
            # campo nuevo, en vez de dejarlo sin clasificar y sin protección.
            INYECTADOS_POR_EL_BUCLE = {"clave_idempotencia"}

            modelos = {"consultar_identidad": ConsultaIdentidad,
                       "estado_tarjeta": EstadoTarjeta,
                       "escalar_a_humano": Escalada}
            declaradas = {h["function"]["name"] for h in HERRAMIENTAS}
            comprobar("todas las herramientas del bucle están aquí cubiertas",
                      declaradas == set(modelos), str(declaradas ^ set(modelos)))

            for h in HERRAMIENTAS:
                nombre = h["function"]["name"]
                modelo = modelos.get(nombre)
                if modelo is None:
                    continue
                params = h["function"]["parameters"]
                obligatorios = set(params.get("required", []))
                for campo, info in modelo.model_fields.items():
                    esquema = params["properties"].get(campo)
                    if campo in INYECTADOS_POR_EL_BUCLE:
                        # Y aquí la comprobación se invierte: estos campos
                        # tienen que estar FUERA del esquema. Si el modelo
                        # pudiera poner la clave de idempotencia podría
                        # reutilizar la de otro turno y quedarse con el ticket
                        # ajeno, o forzar que su escalada se marcase como
                        # repetida y no abrir ninguna. La protección del ADR
                        # 0007 depende de que la clave la ponga el bucle.
                        comprobar(f"{nombre}.{campo} lo pone el bucle y el "
                                  f"modelo NO puede ponerlo",
                                  esquema is None, str(esquema))
                        continue
                    comprobar(f"{nombre}.{campo} está en el esquema",
                              esquema is not None)
                    if esquema is None:
                        continue
                    # Un campo con valor por defecto es opcional en la
                    # herramienta. El esquema tiene que permitir expresarlo:
                    # o no exigiéndolo, o admitiendo `null`.
                    opcional_aqui = not info.is_required()
                    tipos = esquema.get("type")
                    admite_null = (tipos == "null"
                                   or (isinstance(tipos, list)
                                       and "null" in tipos))
                    if opcional_aqui:
                        comprobar(
                            f"{nombre}.{campo} es opcional y el esquema lo "
                            f"permite (fuera de required y admite null)",
                            campo not in obligatorios and admite_null,
                            f"required={campo in obligatorios}, type={tipos!r}")
                    else:
                        comprobar(
                            f"{nombre}.{campo} es obligatorio y el esquema lo "
                            f"exige", campo in obligatorios,
                            f"required={obligatorios}")
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    print(f"\n{'todo bien' if not fallos else str(fallos) + ' comprobaciones fallidas'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
