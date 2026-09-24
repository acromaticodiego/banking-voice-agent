r"""La medición del reservado: el protocolo, escrito ANTES de correrlo.

Los 8 casos reservados se miden **una vez en la vida del proyecto**. En cuanto
se miran, dejan de ser un reservado: cualquier cosa que se toque después
—prompt, clasificador, rúbrica— ya está informada por el resultado, y nadie,
ni uno mismo, puede demostrar lo contrario. Así que el protocolo no se decide
mirando el número: se decide antes, se escribe en este fichero, y luego se
ejecuta.

## El protocolo

  · **k = 5 corridas.** 6 de los 12 casos de calibración cambian de desenlace
    entre corridas del mismo día con el mismo modelo. Con k=1 el número
    tendría ±2 casos de ruido sobre 8, y no distinguiría un agente que
    resuelve siempre de uno que acertó esa vez. La mediana de 5 aguanta una
    corrida rara sin moverse; la de 3 no.

  · **Lo que se publica son cuatro cosas, no una:** la mediana, el rango, el
    conteo por caso (en cuántas de las 5 acertó) y la tabla de estables. Un
    caso que acierta 3 de 5 y otro que acierta 5 de 5 valen lo mismo en la
    mediana y no son lo mismo, y esa diferencia es justo lo que hay que contar
    de un sistema con un modelo dentro.

  · **La mayoría por caso** (≥3 de 5) es el resumen de una sola cifra, para
    cuando haga falta una: es lo que el agente hace *habitualmente*, no lo que
    hizo una tarde.

  · **Una corrida con fallos del proveedor se repite, no se promedia.** Un 429
    hace que el agente salga escalando a un humano, así que el desenlace no lo
    decidió él. Se reintenta hasta `--reintentos` veces; si no se consigue,
    el programa se niega a dar un número.

  · **Se espera entre corridas** hasta que el límite por minuto se recupere,
    leyéndolo de las cabeceras. El plan gratuito da 8000 tokens por minuto y
    una corrida entera consume varios miles: medir seguido no es más rápido,
    es medir con la cola de peticiones dentro del número.

  · **Se anotan la fecha, el modelo, el prompt, el reloj del turno y el
    commit.** Sin eso, dentro de tres meses el número no se puede repetir ni
    defender.

## La barrera

Sin `--declaro-medicion-final` esto no corre. Y si ya existe un artefacto de
medición final, tampoco: hace falta `--repetir-medicion-quemada`, que además
deja escrito en el artefacto que el reservado ya estaba quemado. No es
burocracia: es que la segunda medición de un reservado no mide lo mismo que la
primera, y quien lea el número tiene derecho a saberlo.

## Ensayo

`--ensayo` corre exactamente este protocolo sobre los 12 casos de
**calibración**. Sirve para comprobar el protocolo sin gastar el reservado, que
es lo que se hizo el 2026-09-24 antes de dejarlo escrito.

Uso:
  .\.venv\Scripts\python.exe -m app.evaluation.medicion_final --ensayo --corridas 2
  .\.venv\Scripts\python.exe -m app.evaluation.medicion_final --declaro-medicion-final
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
import uvicorn

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "probe"))

from common import cargar_env  # noqa: E402

from app.agent.loop import SISTEMA  # noqa: E402
from app.evaluation.correr import (BASE, PUERTO, acierta,  # noqa: E402
                                   correr_caso, turno_del_agente)
from app.evaluation.particion import calibracion, reservado  # noqa: E402
from app.tools.service import app as app_herramientas  # noqa: E402

# Holgado a propósito, como en `correr.py`: lo que se mide son decisiones. El
# reloj de la demo son 3000 ms y con el prompt actual salta en 9 de cada 12
# casos, así que medir con él sería medir latencia y llamarlo tarea completada.
PRESUPUESTO_MS = 15000.0


def commit_actual() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=RAIZ, capture_output=True, text=True,
                              timeout=10).stdout.strip() or "desconocido"
    except Exception:  # noqa: BLE001
        return "desconocido"


def esperar_cuota(groq, modelo: str, minimo: int = 6000) -> None:
    """Espera a que el límite por minuto se recupere antes de la corrida.

    Se lee de las cabeceras en vez de dormir un rato fijo, porque el rato fijo
    o sobra o no llega. Una petición mínima basta para que el servidor diga
    cuánto queda.
    """
    for intento in range(12):
        try:
            respuesta = groq.chat.completions.with_raw_response.create(
                model=modelo, messages=[{"role": "user", "content": "."}],
                max_tokens=1)
            quedan = int(respuesta.headers.get(
                "x-ratelimit-remaining-tokens", minimo))
            if quedan >= minimo:
                return
            espera = respuesta.headers.get("x-ratelimit-reset-tokens", "10s")
            print(f"    quedan {quedan} tokens en el minuto, hacen falta "
                  f"{minimo}. Esperando ({espera})...")
        except Exception as exc:  # noqa: BLE001
            print(f"    no se pudo leer la cuota ({type(exc).__name__}), "
                  f"esperando de todos modos")
        time.sleep(20)
    print("    AVISO: la cuota no se recuperó; la corrida puede salir sucia")


def es_limite_diario(incidencias: list[dict]) -> bool:
    """¿El problema es el límite DIARIO de tokens?

    Importa distinguirlo porque la respuesta es distinta: si es el límite por
    minuto, se espera y se repite; si es el diario, hoy no hay nada que hacer y
    seguir reintentando solo gasta peticiones y tiempo.

    Y no se puede leer de las cabeceras: Groq solo publica ahí los límites por
    minuto. El diario aparece únicamente en el cuerpo del 429, que es por lo
    que el 24/09 se diagnosticó mal tres veces seguidas.
    """
    return any("tokens per day" in i.get("error", "") for i in incidencias)


def hay_cuota_para_empezar(groq, modelo: str) -> tuple[bool, str]:
    """Una petición del tamaño real, ANTES de tocar el reservado.

    Esto no es prudencia de más: es que un reservado se gasta al mirarlo, y se
    gasta **por corridas**. Si el protocolo arranca, hace dos corridas y se
    queda sin cuota a la tercera, el programa se niega a dar un número —bien—
    pero los 8 casos ya han pasado por el agente y sus resultados ya se han
    visto por pantalla. Medio reservado gastado no es medio reservado: es un
    reservado del que ya se sabe algo.

    El límite diario no sale en ninguna cabecera, así que la única forma de
    preguntarlo es pedir algo del tamaño de lo que se va a pedir y ver si lo
    rechazan.
    """
    try:
        groq.chat.completions.create(
            model=modelo,
            messages=[{"role": "system", "content": SISTEMA},
                      {"role": "user", "content": "Hola, mi cédula es 1070234567"}],
            max_tokens=400, reasoning_effort="low")
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"


def una_corrida(casos, groq, modelo: str) -> dict:
    """Una pasada por todos los casos, con su contabilidad."""
    incidencias: list[dict] = []
    agotados: list[str] = []
    hacer_turno = turno_del_agente(groq, modelo, PRESUPUESTO_MS, SISTEMA,
                                   incidencias, agotados)
    resultados = [correr_caso(c, hacer_turno) for c in casos]
    return {"resultados": resultados, "incidencias": incidencias,
            "agotados": sorted(set(agotados)),
            "aciertos": sum(1 for r in resultados if r["acierta"])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--declaro-medicion-final", action="store_true")
    parser.add_argument("--ensayo", action="store_true",
                        help="corre el protocolo sobre calibración, para "
                             "probarlo sin gastar el reservado")
    parser.add_argument("--corridas", type=int, default=5,
                        help="k. Por defecto 5, y el motivo está en el "
                             "docstring: no se cambia sin escribir por qué")
    parser.add_argument("--reintentos", type=int, default=3,
                        help="corridas extra permitidas cuando una sale "
                             "contaminada por fallos del proveedor")
    parser.add_argument("--repetir-medicion-quemada", action="store_true")
    args = parser.parse_args()

    if args.ensayo:
        casos, cual = calibracion(), "calibracion-ensayo"
    else:
        # La barrera de siempre: pedir el reservado sin declararlo lanza.
        casos = reservado(declaro_medicion_final=args.declaro_medicion_final)
        cual = "reservado"

    destino = RAIZ / "artifacts" / f"medicion-final-{cual}.json"
    if destino.exists() and not args.repetir_medicion_quemada:
        print(f"Ya existe {destino.name}: este conjunto ya se midió.")
        print("La segunda medición de un reservado no mide lo mismo que la "
              "primera, porque todo lo que se tocó por el camino ya estaba "
              "informado por el resultado. Si de verdad hay que repetirla, "
              "--repetir-medicion-quemada, y quedará escrito en el artefacto.")
        return 1

    entorno = cargar_env()
    from groq import Groq
    groq = Groq(api_key=entorno["GROQ_API_KEY"].strip(), max_retries=2)
    modelo = entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

    servidor = uvicorn.Server(uvicorn.Config(app_herramientas, port=PUERTO,
                                             log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(50):
        if servidor.started:
            break
        time.sleep(0.1)

    print(f"MEDICIÓN {'DE ENSAYO' if args.ensayo else 'FINAL'} sobre {cual}: "
          f"{len(casos)} casos, k={args.corridas}, modelo {modelo}, "
          f"presupuesto {PRESUPUESTO_MS:.0f} ms, commit {commit_actual()}\n")

    if not args.ensayo:
        puede, motivo = hay_cuota_para_empezar(groq, modelo)
        if not puede:
            print("NO SE EMPIEZA. El proveedor ya está rechazando peticiones "
                  f"del tamaño real:\n    {motivo}")
            print("\nArrancar ahora significaría gastar el reservado a medias, "
                  "y medio reservado no es medio reservado: es un reservado del "
                  "que ya se sabe algo. Vuelve cuando haya cuota "
                  "(probe/limites_groq.py lo dice).")
            servidor.should_exit = True
            hilo.join(timeout=5)
            return 3
        print("  cuota comprobada con una petición del tamaño real.\n")

    limpias: list[dict] = []
    descartadas: list[dict] = []
    intentos = 0
    while len(limpias) < args.corridas and intentos < args.corridas + args.reintentos:
        intentos += 1
        if intentos > 1:
            esperar_cuota(groq, modelo)
        print(f"  corrida {len(limpias) + 1}/{args.corridas} "
              f"(intento {intentos})...")
        corrida = una_corrida(casos, groq, modelo)
        if corrida["incidencias"]:
            print(f"    DESCARTADA: {len(corrida['incidencias'])} fallo(s) del "
                  f"proveedor. Se repite, no se promedia.")
            descartadas.append(corrida)
            if es_limite_diario(corrida["incidencias"]):
                print("\n    Es el límite DIARIO de tokens. Reintentar hoy no "
                      "arregla nada: se para aquí en vez de gastar cuota en "
                      "corridas que ya se sabe que van a salir sucias.")
                break
            continue
        print(f"    {corrida['aciertos']}/{len(casos)}"
              + (f", reloj agotado en {corrida['agotados']}"
                 if corrida["agotados"] else ""))
        limpias.append(corrida)

    servidor.should_exit = True
    hilo.join(timeout=5)

    if len(limpias) < args.corridas:
        print(f"\nNO HAY NÚMERO. Solo {len(limpias)} de {args.corridas} "
              f"corridas salieron limpias en {intentos} intentos.")
        print("Dar la mediana de menos corridas de las que dice el protocolo "
              "sería cambiar el protocolo después de verlo fallar.")
        if not args.ensayo and (limpias or descartadas):
            # Y si se llegó a correr aunque sea una vez, el reservado ya no
            # está entero. Queda por escrito, porque la próxima medición ya
            # no será la primera y quien lea el número tiene que saberlo.
            aviso = RAIZ / "artifacts" / "reservado-gastado-a-medias.json"
            previo = (json.loads(aviso.read_text(encoding="utf-8"))
                      if aviso.exists() else {"intentos": []})
            previo["intentos"].append({
                "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
                "commit": commit_actual(),
                "corridas_limpias": len(limpias),
                "corridas_descartadas": len(descartadas),
                "aciertos_vistos": [c["aciertos"] for c in limpias],
            })
            aviso.write_text(json.dumps(previo, indent=2, ensure_ascii=False),
                             encoding="utf-8")
            print(f"\nEL RESERVADO YA NO ESTÁ ENTERO: se corrió "
                  f"{len(limpias) + len(descartadas)} vez/veces y los "
                  f"resultados se han visto. Anotado en {aviso.name}.")
        return 2

    # -------------------------------------------------- lo que se publica
    por_caso: dict[str, list[str]] = defaultdict(list)
    for corrida in limpias:
        for r in corrida["resultados"]:
            por_caso[r["id"]].append(r["obtenido"])

    aciertos = [c["aciertos"] for c in limpias]
    filas = []
    for caso in casos:
        vueltas = por_caso[caso.id]
        buenas = sum(1 for v in vueltas if acierta(caso, v))
        mayoria = buenas * 2 > len(vueltas)
        filas.append({
            "id": caso.id,
            "esperado": caso.desenlace,
            "tambien_acepta": caso.tambien_acepta,
            "aciertos": buenas,
            "de": len(vueltas),
            "mayoria": mayoria,
            "estable": len(set(vueltas)) == 1,
            "desenlaces": vueltas,
        })

    print(f"\n  caso                                aciertos  mayoría  estable")
    for f in filas:
        print(f"  {f['id']:<34} {f['aciertos']}/{f['de']}      "
              f"{'sí' if f['mayoria'] else 'NO':<8} "
              f"{'sí' if f['estable'] else 'NO'}    {f['desenlaces']}")

    fugas = sorted({r["id"] for c in limpias for r in c["resultados"]
                    if r["filtraciones"]})
    promesas = sorted({r["id"] for c in limpias for r in c["resultados"]
                       if r["promesas"]})
    sin_fundamento = sorted({r["id"] for c in limpias for r in c["resultados"]
                             if r["numeros_sin_fundamento"]
                             or r["acciones_sin_fundamento"]})

    resumen = {
        "conjunto": cual,
        "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
        "modelo": modelo,
        "prompt": "actual",
        "presupuesto_ms": PRESUPUESTO_MS,
        "commit": commit_actual(),
        "corridas": len(limpias),
        "corridas_descartadas": len(descartadas),
        "aciertos_por_corrida": aciertos,
        "mediana": statistics.median(aciertos),
        "rango": [min(aciertos), max(aciertos)],
        "por_mayoria": sum(1 for f in filas if f["mayoria"]),
        "estables": sum(1 for f in filas if f["estable"]),
        "total": len(casos),
        "fugas_de_datos": fugas,
        "promesas_sin_base": promesas,
        "afirmaciones_sin_fundamento": sin_fundamento,
        "reservado_ya_estaba_quemado": bool(args.repetir_medicion_quemada),
        "por_caso": filas,
        "detalle": limpias,
    }

    print(f"\n  aciertos por corrida : {aciertos}")
    print(f"  mediana              : {resumen['mediana']:g}/{len(casos)}")
    print(f"  rango                : {min(aciertos)}-{max(aciertos)}")
    print(f"  por mayoría          : {resumen['por_mayoria']}/{len(casos)}")
    print(f"  estables             : {resumen['estables']}/{len(casos)}")
    print(f"  fugas de datos       : {len(fugas)}"
          + (f"  -> {fugas}" if fugas else ""))
    print(f"  promesas sin base    : {len(promesas)}"
          + (f"  -> {promesas}" if promesas else ""))
    print(f"  sin fundamento       : {len(sin_fundamento)}"
          + (f"  -> {sin_fundamento}" if sin_fundamento else ""))
    if descartadas:
        print(f"  corridas descartadas : {len(descartadas)} por fallos del "
              f"proveedor")

    destino.write_text(json.dumps(resumen, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    print(f"\nGuardado en {destino.name}")
    if not args.ensayo:
        print("EL RESERVADO QUEDA QUEMADO. Lo que se cambie a partir de ahora "
              "está informado por este resultado, y eso hay que decirlo cada "
              "vez que se cite el número.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
