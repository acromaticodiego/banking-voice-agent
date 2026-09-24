r"""Un documento que no aparece no es motivo para rendirse a la primera.

El caso `documento-mal-dos-veces` del conjunto falla igual en las seis corridas
de los dos prompts, así que no es ruido: **el agente escala al PRIMER documento
que no aparece, y abre un ticket.** Al teléfono la gente se equivoca de dígito
—y el ASR también—, así que rendirse a la primera es peor servicio, y el ticket
tiene efecto: alguien tiene que atenderlo.

Lo que se comprueba aquí es **lo que el agente le dice al modelo**, que es la
parte determinista. Si el modelo obedece o no es otra cosa, se mide con el
conjunto y cuesta cuota.

La distinción que hace falta es la de "documentos distintos": el adelanto de
consultas puede consultar la misma cédula dos veces, y el modelo puede
insistir con la misma. Contar llamadas en vez de documentos escalaría a alguien
por el error de otro.

  .\.venv\Scripts\python.exe -m app.agent.prueba_reintentos
"""

from __future__ import annotations

import threading
import time

import uvicorn

from app.agent.loop import DOCUMENTOS_ANTES_DE_ESCALAR, Agente
from app.tools.service import app as app_herramientas

PUERTO = 8199
BASE = f"http://127.0.0.1:{PUERTO}"

BUENO = "1070234567"       # el único que existe en las herramientas de mentira
MALOS = ["1070234000", "1070234999", "1070234111"]

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}   {detalle}")
    else:
        fallos += 1
        print(f"    MAL {nombre}   {detalle}")


class ModeloProhibido:
    class chat:  # noqa: N801
        class completions:  # noqa: N801
            @staticmethod
            def create(**_):
                raise AssertionError("esta prueba no necesita modelo")


def consultar(agente: Agente, documento: str) -> dict:
    """Lo que el agente le pasaría al modelo tras consultar ese documento."""
    resultado, _ms = agente._ejecutar("consultar_identidad",
                                      {"documento": documento}, "clave")
    return agente._anotar_intentos("consultar_identidad",
                                   {"documento": documento}, resultado)


def main() -> int:
    servidor = uvicorn.Server(uvicorn.Config(app_herramientas, port=PUERTO,
                                             log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(50):
        if servidor.started:
            break
        time.sleep(0.1)

    try:
        print("\n[1] El primer documento que falla dice 'pide que lo repita'")
        agente = Agente(ModeloProhibido(), "prohibido", BASE)
        primero = consultar(agente, MALOS[0])
        print(f"    {primero}")
        comprobar("no lo encuentra", primero["encontrado"] is False)
        comprobar("va por el intento 1",
                  primero["_intentos_en_esta_llamada"] == 1)
        comprobar("y dice que NO escale todavía",
                  "NO escales" in primero["_que_hacer"])

        print("\n[2] Al tercero distinto, sí toca escalar")
        segundo = consultar(agente, MALOS[1])
        comprobar("va por el intento 2",
                  segundo["_intentos_en_esta_llamada"] == 2)
        comprobar("sigue diciendo que no escale",
                  "NO escales" in segundo["_que_hacer"])
        tercero = consultar(agente, MALOS[2])
        print(f"    {tercero}")
        comprobar(f"va por el intento {DOCUMENTOS_ANTES_DE_ESCALAR}",
                  tercero["_intentos_en_esta_llamada"]
                  == DOCUMENTOS_ANTES_DE_ESCALAR)
        comprobar("y ahora sí manda pasar a un humano",
                  "pasa la llamada" in tercero["_que_hacer"])

        print("\n[3] El MISMO documento dos veces no es un intento nuevo")
        # Pasa de verdad: el adelanto de consultas dispara la misma cédula que
        # luego pide el modelo, y el modelo a veces insiste con la misma.
        # Contar llamadas en vez de documentos distintos escalaría a alguien
        # por un error que no ha cometido.
        agente3 = Agente(ModeloProhibido(), "prohibido", BASE)
        consultar(agente3, MALOS[0])
        repetido = consultar(agente3, MALOS[0])
        comprobar("sigue siendo el intento 1",
                  repetido["_intentos_en_esta_llamada"] == 1,
                  str(agente3.documentos_intentados))
        con_puntos = consultar(agente3, "1.070.234.000")
        comprobar("y con puntos y espacios tampoco cuenta doble",
                  con_puntos["_intentos_en_esta_llamada"] == 1,
                  str(agente3.documentos_intentados))

        print("\n[4] El documento que SÍ existe no lleva anotación")
        agente4 = Agente(ModeloProhibido(), "prohibido", BASE)
        encontrado = consultar(agente4, BUENO)
        comprobar("lo encuentra", encontrado["encontrado"] is True)
        comprobar("y el resultado va limpio, sin campos del agente",
                  not any(c.startswith("_") for c in encontrado),
                  str(list(encontrado)))

        print("\n[5] Una herramienta caída NO cuenta como documento malo")
        # Si el core se cae, eso no es un documento equivocado. Contarlo haría
        # escalar por el motivo que no es, y el motivo importa: lo lleva el
        # ticket que lee el asesor.
        agente5 = Agente(ModeloProhibido(), "prohibido", BASE)
        caido = agente5._anotar_intentos(
            "consultar_identidad", {"documento": MALOS[0]},
            {"error": "la herramienta respondió 503", "reintentable": True})
        comprobar("no se anota nada",
                  "_intentos_en_esta_llamada" not in caido)
        comprobar("y no se apunta el documento",
                  agente5.documentos_intentados == [],
                  str(agente5.documentos_intentados))

        print("\n[6] Los campos del agente se ven como del agente")
        # Van con `_` delante a propósito: inventarse campos con pinta de
        # datos del banco es justo lo que prohíbe el ADR 0005.
        comprobar("todos los campos añadidos empiezan por _",
                  all(c.startswith("_") for c in tercero
                      if c not in ("encontrado", "documento")),
                  str(list(tercero)))
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    print(f"\n{'todo bien' if not fallos else str(fallos) + ' comprobaciones fallidas'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
