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

from app.evaluation.correr import clasificar

RAIZ = Path(__file__).resolve().parents[2]


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
    args = parser.parse_args()

    patron = f"evaluacion-{args.conjunto}-{args.quien}-*.json"
    corridas = []
    for fichero in sorted((RAIZ / "artifacts").glob(patron)):
        datos = json.loads(fichero.read_text(encoding="utf-8"))
        if args.casos and datos["total"] != args.casos:
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

    tabla: dict[str, list[str]] = defaultdict(list)
    for _, datos in corridas:
        for r in datos["resultados"]:
            obtenido = clasificar(r["dijo"], r["herramientas"])
            tabla[r["id"]].append("OK" if obtenido == r["esperado"]
                                  else obtenido)

    n = len(corridas)
    print(f"{args.quien} sobre {args.conjunto}: {n} corrida(s) de "
          f"{tamanos.pop()} casos, reclasificadas con el clasificador de hoy\n")
    for nombre, _ in corridas:
        print(f"    {nombre}")
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
