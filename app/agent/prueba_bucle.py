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

from app.agent.loop import Agente  # noqa: E402
from app.tools.service import app as app_herramientas  # noqa: E402

PUERTO = 8124
BASE = f"http://127.0.0.1:{PUERTO}"

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}")
    else:
        fallos += 1
        print(f"    MAL {nombre}    {detalle}")


def herramientas_usadas(turno) -> list[str]:
    return [p.detalle for p in turno.rastro if p.tipo == "herramienta"]


def main() -> int:
    entorno = cargar_env()
    clave = entorno.get("GROQ_API_KEY", "").strip()
    if not clave:
        print("Falta GROQ_API_KEY en .env", file=sys.stderr)
        return 2
    modelo = entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

    from groq import Groq
    groq = Groq(api_key=clave, max_retries=0)

    servidor = uvicorn.Server(uvicorn.Config(app_herramientas, port=PUERTO,
                                             log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(50):
        if servidor.started:
            break
        time.sleep(0.1)

    try:
        # ---------------------------------------------------------- 1. resuelve
        print("\n[1] Resuelve: documento válido, tarjeta bloqueada")
        agente = Agente(groq, modelo, BASE)
        t1 = agente.turno("Buenas, me bloquearon la tarjeta. Mi documento es el "
                          "1070234567.")
        print(f"    agente: {t1.texto}")
        print(f"    rastro: {t1.resumen()}  ->  {herramientas_usadas(t1)}")
        comprobar("llama a consultar_identidad",
                  "consultar_identidad" in herramientas_usadas(t1))
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
                  "consultar_identidad" in usadas3, str(usadas3))
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
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    print(f"\n{'todo bien' if not fallos else str(fallos) + ' comprobaciones fallidas'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
