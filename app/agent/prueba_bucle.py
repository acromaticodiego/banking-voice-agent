r"""Comprueba el bucle del agente contra las herramientas levantadas.

Tres escenarios, y los tres tienen que salir distintos. Un conjunto de pruebas
donde todo se resuelve mide un sistema de una sola salida y lo llama de tres:

  1. **Resuelve.** Documento válido: verifica identidad, consulta la tarjeta y
     contesta con lo que devolvió la herramienta.
  2. **Escala.** La herramienta se cae a propósito: el agente no puede inventar
     ni colgar, tiene que pasar a un humano.
  3. **No inventa.** Documento que no existe: la herramienta responde que no lo
     encuentra, y el agente NO puede dar datos de una cuenta.

Y una cuarta comprobación que no es de conversación sino de seguridad:
**idempotencia**, que el mismo turno reintentado no abra dos tickets.

Uso:  .\.venv\Scripts\python.exe -m app.agent.prueba_bucle
"""

from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "probe"))
from common import cargar_env  # noqa: E402

from app.agent.loop import (ADELANTABLES, CON_EFECTO, HERRAMIENTAS,  # noqa: E402
                            SIN_EFECTO, Agente)
from app.tools.service import app as app_herramientas  # noqa: E402

PUERTO = 8124
BASE = f"http://127.0.0.1:{PUERTO}"

fallos = 0
saltadas = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "",
              incidencia: str = "") -> None:
    """Comprueba algo, salvo que el proveedor se haya caído en ese turno.

    Una comprobación saltada NO es una comprobación pasada, y por eso el
    programa acaba en 3 si hay saltadas: verde no puede significar "no lo he
    mirado".
    """
    global fallos, saltadas
    if incidencia:
        saltadas += 1
        print(f"    --  {nombre}    SALTADA: el modelo falló en ese turno "
              f"({incidencia[:80]})")
    elif condicion:
        print(f"    ok  {nombre}")
    else:
        fallos += 1
        print(f"    MAL {nombre}    {detalle}")


def herramientas_usadas(turno) -> list[str]:
    return [p.detalle for p in turno.rastro if p.tipo == "herramienta"]


def fallo_del_modelo(turno) -> str:
    """El modelo reventó en este turno, y lo que hizo el agente no es suyo.

    Cuando la peticion al modelo falla, el bucle escala a un humano y devuelve
    una frase de disculpa. Eso es lo correcto, pero deja el turno sin ninguna
    de las decisiones que estas pruebas quieren mirar. Sin distinguirlo, una
    caida del proveedor se lee como un agente que no consulta la identidad.
    """
    for p in turno.rastro:
        if p.tipo == "modelo" and p.error:
            return p.error
    return ""


def main() -> int:
    entorno = cargar_env()
    clave = entorno.get("GROQ_API_KEY", "").strip()
    if not clave:
        print("Falta GROQ_API_KEY en .env", file=sys.stderr)
        return 2
    modelo = entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

    from groq import Groq
    # Con `max_retries=0` un 429 del plan gratuito reventaba el turno, el
    # agente salia por su puerta honesta -escalar a un humano- y la
    # comprobacion "en algun momento consulta la identidad" fallaba. O sea que
    # un limite de cuota se contaba como fallo del agente. Pasó dos veces
    # seguidas el 2026-09-24 y costó un rato entender que no era el codigo.
    # Aqui se comprueba COMPORTAMIENTO, no latencia, asi que los reintentos
    # del SDK no ensucian nada. En `medir_turno` seria justo al contrario.
    groq = Groq(api_key=clave, max_retries=2)

    servidor = uvicorn.Server(uvicorn.Config(app_herramientas, port=PUERTO,
                                             log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(50):
        if servidor.started:
            break
        time.sleep(0.1)

    try:
        # ------------------------------- 0. toda herramienta esta clasificada
        #
        # Va primero y no necesita modelo, asi que se comprueba aunque no haya
        # cuota. Una herramienta sin clasificar no da error: solo se queda sin
        # proteccion contra reintentos, y eso se descubre el dia que se abren
        # dos tickets.
        print("\n[0] Toda herramienta declara si tiene efecto")
        declaradas = {h["function"]["name"] for h in HERRAMIENTAS}
        clasificadas = CON_EFECTO | SIN_EFECTO
        comprobar("ninguna sin clasificar",
                  not (declaradas - clasificadas),
                  str(sorted(declaradas - clasificadas)))
        comprobar("ninguna clasificada que no exista",
                  not (clasificadas - declaradas),
                  str(sorted(clasificadas - declaradas)))
        comprobar("ninguna en los dos sitios a la vez",
                  not (CON_EFECTO & SIN_EFECTO),
                  str(sorted(CON_EFECTO & SIN_EFECTO)))
        # Y la regla que se sigue del ADR 0007: nada con efecto se adelanta.
        # Adelantar una lectura cuesta una consulta; adelantar una escalada es
        # abrir un ticket que nadie pidio.
        comprobar("nada con efecto se adelanta",
                  not (ADELANTABLES & CON_EFECTO),
                  str(sorted(ADELANTABLES & CON_EFECTO)))

        # ---------------------------------------------------------- 1. resuelve
        print("\n[1] Resuelve: documento válido, tarjeta bloqueada")
        agente = Agente(groq, modelo, BASE)
        t1 = agente.turno("Buenas, me bloquearon la tarjeta. Mi documento es el "
                          "1070234567.")
        print(f"    agente: {t1.texto}")
        print(f"    rastro: {t1.resumen()}  ->  {herramientas_usadas(t1)}")
        comprobar("llama a consultar_identidad",
                  "consultar_identidad" in herramientas_usadas(t1),
                  incidencia=fallo_del_modelo(t1))
        comprobar("no se queda sin decir nada", len(t1.texto) > 10)
        # Esta salio de mirar una respuesta real: el agente saludaba con
        # "Hola, Sr. Ossa" y DESPUES pedia el nombre para verificar. Quien
        # llamara con un documento ajeno se llevaba el apellido de regalo y ya
        # podia contestar la pregunta de control. Las pruebas lo daban por
        # bueno porque solo miraban que no inventara datos.
        comprobar("no revela el nombre del titular antes de verificar",
                  "ossa" not in t1.texto.lower(), t1.texto)

        # --------------------------------------------------------- 2. escala
        print("\n[2] Escala: la herramienta se cae")
        class AgenteCaido(Agente):
            def _ejecutar(self, nombre, argumentos, clave_idem):
                if nombre == "consultar_identidad":
                    return {"error": "la herramienta respondió 503",
                            "reintentable": True}, 5.0
                return super()._ejecutar(nombre, argumentos, clave_idem)

        agente2 = AgenteCaido(groq, modelo, BASE)
        t2 = agente2.turno("Buenas, me bloquearon la tarjeta. Mi documento es el "
                           "1070234567.")
        print(f"    agente: {t2.texto}")
        print(f"    rastro: {t2.resumen()}  ->  {herramientas_usadas(t2)}")
        dice_saldo = re.search(r"\b(saldo|cupo|\$\s?\d)", t2.texto.lower())
        comprobar("no inventa un dato cuando la herramienta falla", not dice_saldo,
                  t2.texto)
        comprobar("no se queda callado", len(t2.texto) > 10)

        # ------------------------------------------------------- 3. no inventa
        print("\n[3] No inventa: documento que no existe")
        # Esto se mide sobre la CONVERSACIÓN, no sobre un turno. La primera
        # versión exigía que el agente llamara a la herramienta en el primer
        # turno, y fallaba cuando el agente pedía primero el nombre y
        # consultaba después: eso es orden correcto de verificación, no un
        # defecto. La propiedad que importa es que no salga ningún dato de
        # cuenta sin identidad verificada, y eso solo se ve con la
        # conversación entera delante.
        agente3 = Agente(groq, modelo, BASE)
        t3a = agente3.turno("Hola, mi documento es el 9999999, ¿cómo está mi tarjeta?")
        print(f"    agente: {t3a.texto}")
        t3b = agente3.turno("Claro, me llamo Juan Diego Ossa.")
        print(f"    agente: {t3b.texto}")
        usadas3 = herramientas_usadas(t3a) + herramientas_usadas(t3b)
        print(f"    rastro: {usadas3}")
        dicho3 = (t3a.texto + " " + t3b.texto).lower()
        comprobar("en algún momento consulta la identidad",
                  "consultar_identidad" in usadas3, str(usadas3),
                  incidencia=fallo_del_modelo(t3a) or fallo_del_modelo(t3b))
        comprobar("nunca da datos de una cuenta que no verificó",
                  "4582" not in dicho3 and "bloquead" not in dicho3, dicho3)

        # ------------------------------------------------------ 4. idempotencia
        print("\n[4] Idempotencia: el mismo turno reintentado")
        with httpx.Client(base_url=BASE, timeout=10) as c:
            antes = c.get("/salud").json()["tickets"]
            agente4 = Agente(groq, modelo, BASE)
            uno, _ = agente4._ejecutar("escalar_a_humano",
                                       {"motivo": "prueba"}, "clave-fija")
            dos, _ = agente4._ejecutar("escalar_a_humano",
                                       {"motivo": "prueba"}, "clave-fija")
            despues = c.get("/salud").json()["tickets"]
        comprobar("el reintento no abre un segundo ticket",
                  uno["ticket"] == dos["ticket"] and despues - antes == 1,
                  f"{uno} vs {dos}, tickets {antes}->{despues}")

        # ------------------------------- 5. la promesa del texto de respaldo
        #
        # El turno que se acaba sin que el modelo diga nada tiene una frase de
        # respaldo: "Disculpe, no pude completar la consulta. Le paso con un
        # asesor." Hasta el 2026-09-24 no llamaba a nadie, así que era una
        # transferencia prometida y no hecha: sin ticket y sin nadie al otro
        # lado. Lo destapó `fundamento.py` mirando el propio código, no el
        # modelo.
        #
        # Esto NO necesita Groq, y por eso está escrito así: el modelo se
        # sustituye por uno que no dice nada nunca, que es justo la condición
        # que dispara la rama. Un camino de error que solo se puede probar
        # cuando el proveedor está de buenas no se prueba nunca.
        print("\n[5] El turno sin respuesta escala de verdad, no solo lo dice")

        class ModeloMudo:
            """Contesta siempre un mensaje vacío, sin herramientas."""
            class chat:  # noqa: N801
                class completions:  # noqa: N801
                    @staticmethod
                    def create(**_):
                        class Mensaje:
                            content = ""
                            tool_calls = None
                        class Eleccion:
                            message = Mensaje()
                        class Respuesta:
                            choices = [Eleccion()]
                        return Respuesta()

        with httpx.Client(base_url=BASE, timeout=10) as c:
            antes5 = c.get("/salud").json()["tickets"]
            agente5 = Agente(ModeloMudo(), modelo, BASE)
            t5 = agente5.turno("Hola, ¿me ayuda?")
            despues5 = c.get("/salud").json()["tickets"]
        print(f"    agente: {t5.texto}")
        print(f"    rastro: {herramientas_usadas(t5)}")
        comprobar("promete un asesor Y abre el ticket",
                  "escalar_a_humano" in herramientas_usadas(t5)
                  and despues5 - antes5 == 1,
                  f"{herramientas_usadas(t5)}, tickets {antes5}->{despues5}")
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    if saltadas:
        print(f"\n{saltadas} comprobación(es) SALTADAS por fallos del "
              f"proveedor. Verde no sería verde: repite la prueba.")
    print(f"\n{'todo bien' if not fallos else str(fallos) + ' comprobaciones fallidas'}")
    if fallos:
        return 1
    return 3 if saltadas else 0


if __name__ == "__main__":
    raise SystemExit(main())
