r"""Cuánto de un resultado es el agente y cuánto es la tirada de dados.

Existe por un susto del 2026-09-23. Tres corridas seguidas del mismo conjunto
de 12 casos, el mismo modelo, el mismo día, dieron 6, 5 y 7 aciertos. Ninguna
mentía: cada una era una medición correcta de una sola tirada. Pero decir "el
agente saca 7 de 12" con eso es lo mismo que tirar un dado una vez y decir que
el dado vale 4.

Lo que hace este módulo no cuesta ni una petición: relee lo que quedó guardado
de cada corrida y **lo reclasifica con el clasificador de hoy**. Eso importa
más de lo que parece. Las corridas de una tarde se hacen con clasificadores
distintos, porque el clasificador también se arregla por el camino; comparar
sus `obtenido` tal cual mezcla dos variables y no se puede saber cuál movió el
número. Reclasificando, la única variable que queda es el agente.

  .\.venv\Scripts\python.exe -m app.evaluation.estabilidad
  .\.venv\Scripts\python.exe -m app.evaluation.estabilidad --casos 8   # reservado

Para la medición final del reservado esto no es un adorno: **un caso inestable
que cae del lado bueno vale lo mismo en la tabla que uno que el agente resuelve
siempre**, y son cosas distintas. La medición honesta del reservado son varias
corridas, con la mediana y el rango, y decidido ANTES de quemarlo.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app.agent.fundamento import revisar
from app.evaluation.catalogo import por_id
from app.evaluation.correr import clasificar

RAIZ = Path(__file__).resolve().parents[2]


def sin_fundamento(datos: dict) -> str:
    """Cuántos casos de esa corrida dijeron algo que no les constaba.

    Se recalcula aquí en vez de leer el campo guardado, por la misma razón que
    los desenlaces se reclasifican: el detector también se arregla por el
    camino, y comparar corridas con dos versiones suyas mezcla variables. Con
    el de hoy, todas se miden igual.

    Las corridas de antes del 2026-09-24 no guardaban lo que devolvieron las
    herramientas. Sin esas fuentes, el detector daría por inventado cualquier
    número que el agente leyó correctamente, así que no se calcula y se dice.
    """
    if not all("resultados" in r for r in datos["resultados"]):
        return "sin fundamento: no medible (no se guardaron las herramientas)"
    marcados = 0
    for r in datos["resultados"]:
        revision = revisar(r["dijo"], r["resultados"],
                           por_id(r["id"]).turnos, r["herramientas"])
        marcados += 0 if revision.limpio else 1
    return f"sin fundamento: {marcados}/{datos['total']}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quien", default="agente",
                        choices=["agente", "base"])
    parser.add_argument("--conjunto", default="calibracion",
                        choices=["calibracion", "reservado"])
    parser.add_argument("--casos", type=int, default=None,
                        help="solo las corridas con este número de casos. Sin "
                             "esto se mezclarían corridas de conjuntos de "
                             "tamaños distintos, que no son comparables.")
    parser.add_argument("--prompt", choices=["actual", "anterior"],
                        default=None,
                        help="solo las corridas con esta versión del prompt")
    parser.add_argument("--presupuesto-ms", type=float, default=None,
                        help="solo las corridas con este reloj de turno")
    args = parser.parse_args()

    patron = f"evaluacion-{args.conjunto}-{args.quien}-*.json"
    corridas = []
    for fichero in sorted((RAIZ / "artifacts").glob(patron)):
        datos = json.loads(fichero.read_text(encoding="utf-8"))
        if args.casos and datos["total"] != args.casos:
            continue
        # Las corridas de antes del 2026-09-24 no guardaban ni el prompt ni el
        # presupuesto, así que se etiquetan con lo que eran entonces: el prompt
        # de antes y el reloj de 3000 ms. Inventarles un "desconocido" las
        # dejaría fuera de toda comparación, y describirlas mal sería peor.
        prompt = datos.get("prompt", "anterior")
        presupuesto = datos.get("presupuesto_ms", 3000.0)
        if args.prompt and prompt != args.prompt:
            continue
        if args.presupuesto_ms and presupuesto != args.presupuesto_ms:
            continue
        corridas.append((fichero.name, datos))

    if not corridas:
        print(f"No hay corridas guardadas que encajen con {patron}"
              + (f" y {args.casos} casos" if args.casos else ""))
        return 1

    tamanos = {d["total"] for _, d in corridas}
    if len(tamanos) > 1:
        # Mezclar un conjunto de 6 con uno de 12 da una media que no es de
        # nada. Se dice y se sale, en vez de imprimir un número inventado.
        print(f"Hay corridas de tamaños distintos: {sorted(tamanos)}. "
              f"Usa --casos N para quedarte con uno.")
        return 1

    # Lo mismo con las condiciones: el 2026-09-24 el prompt se alargó y el
    # reloj del turno se relajó, y las dos cosas mueven el número. Tres
    # corridas de un brazo y tres del otro, metidas en el mismo saco, dan una
    # mediana de nada con una estabilidad falsa. Mejor negarse que promediar.
    condiciones = {(d.get("prompt", "anterior"),
                    d.get("presupuesto_ms", 3000.0)) for _, d in corridas}
    if len(condiciones) > 1:
        print("Estas corridas no se hicieron en las mismas condiciones:")
        for prompt, presupuesto in sorted(condiciones):
            print(f"    prompt {prompt}, presupuesto {presupuesto:.0f} ms")
        print("  Filtra con --prompt y --presupuesto-ms. Promediarlas daría "
              "una mediana de dos experimentos distintos y una tabla de "
              "estabilidad que mide el cambio de condiciones, no al agente.")
        return 1

    tabla: dict[str, list[str]] = defaultdict(list)
    for _, datos in corridas:
        for r in datos["resultados"]:
            obtenido = clasificar(r["dijo"], r["herramientas"])
            tabla[r["id"]].append("OK" if obtenido == r["esperado"]
                                  else obtenido)

    n = len(corridas)
    prompt, presupuesto = condiciones.pop()
    print(f"{args.quien} sobre {args.conjunto}: {n} corrida(s) de "
          f"{tamanos.pop()} casos, prompt {prompt}, presupuesto "
          f"{presupuesto:.0f} ms, reclasificadas con el clasificador de hoy\n")
    for nombre, datos in corridas:
        print(f"    {nombre}   {sin_fundamento(datos)}")
    print()

    estables, inestables = [], []
    for identificador, vueltas in tabla.items():
        siempre = len(set(vueltas)) == 1
        (estables if siempre else inestables).append(identificador)
        print(f"  {'estable  ' if siempre else 'INESTABLE'} "
              f"{identificador:<34} {vueltas}")

    por_corrida = [sum(1 for c in tabla if tabla[c][i] == "OK")
                   for i in range(n)]
    print(f"\n  aciertos por corrida : {por_corrida}")
    if n > 1:
        print(f"  mediana              : {statistics.median(por_corrida):g}"
              f"/{len(tabla)}")
        print(f"  rango                : {min(por_corrida)}-{max(por_corrida)}")
    print(f"  estables             : {len(estables)}/{len(tabla)}")
    print(f"  inestables           : {len(inestables)}/{len(tabla)}"
          + (f"  -> {sorted(inestables)}" if inestables else ""))
    if n == 1:
        print("\n  UNA SOLA CORRIDA. No hay forma de saber qué parte de esto "
              "es el agente y qué parte es la temperatura.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
