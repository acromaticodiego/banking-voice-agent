r"""Rellena el libro de la cuota con lo ya gastado, leyéndolo de los artefactos.

Se escribió el 2026-09-25 porque ese día el libro nació vacío **después** de
gastarse casi los 200 000 tokens de la ventana, y un libro vacío es peligroso
justo en la dirección mala: `disponible()` diría 200 000 cuando Groq decía
`Used 199423`. Si alguien hubiera lanzado la medición del reservado con el libro
así, el canario habría dado luz verde y el conjunto se habría gastado a medias.

Qué hace, en este orden:

1. Lee los artefactos `evaluacion-*.json` y anota el consumo de cada corrida con
   la hora que lleva en el nombre del fichero, que es cuando se guardó.
2. Anota el consumo del ensayo del protocolo si lo encuentra. Ojo: hasta hoy ese
   módulo no contaba tokens, así que de las corridas viejas solo se puede
   **estimar** —y se marca como estimación en la etiqueta, para que nadie lo
   confunda con una medición.
3. Aplica la corrección de un 429 si alguna corrida lo trae. Ese `Used` es la
   única cifra real del gasto de la ventana, y pone al día todo lo que el libro
   no podía ver: peticiones a mano, sondas sueltas y —el caso del 25/09— el
   gasto del día anterior que seguía dentro de las 24 h.

Es idempotente de dos maneras, y la segunda se añadió tras pisarla: `--rehacer`
borra el libro antes de sembrarlo, y sin `--rehacer` **se salta los artefactos
que ya están apuntados**, mirando la etiqueta. La primera versión no hacía lo
segundo, y correrla dos veces por descuido duplicó el gasto en el libro: un libro
que se infla solo es tan malo como uno que se queda corto, porque el canario se
negaría a medir cuando sí hay sitio.

    .\.venv\Scripts\python.exe probe\sembrar_libro_cuota.py --rehacer
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.evaluation import cuota  # noqa: E402

ARTEFACTOS = RAIZ / "artifacts"
# evaluacion-calibracion-agente-20260925-085248.json
PATRON_FECHA = re.compile(r"-(\d{8})-(\d{6})\.json$")


def cuando_de(fichero: Path) -> float | None:
    """La hora del nombre del fichero, que es cuando se guardó la corrida.

    Se prefiere al `mtime` porque un `git checkout` o una copia cambian el
    mtime y no cambian el nombre.
    """
    hallado = PATRON_FECHA.search(fichero.name)
    if not hallado:
        return None
    try:
        return time.mktime(time.strptime(hallado.group(1) + hallado.group(2),
                                         "%Y%m%d%H%M%S"))
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rehacer", action="store_true",
                        help="borra el libro antes de sembrarlo")
    parser.add_argument("--horas", type=float, default=24.0,
                        help="solo los artefactos de las últimas N horas")
    args = parser.parse_args()

    if args.rehacer and cuota.LIBRO.exists():
        cuota.LIBRO.unlink()
        print(f"  libro borrado: {cuota.LIBRO.name}")

    ahora = time.time()
    limite = ahora - args.horas * 3600
    anotados = 0
    mensajes_429: list[str] = []
    # Lo que ya está apuntado, para no contarlo dos veces.
    ya_estan = {e["etiqueta"] for e in cuota.entradas(ahora)}

    for fichero in sorted(ARTEFACTOS.glob("evaluacion-*.json")):
        cuando = cuando_de(fichero)
        if cuando is None or cuando < limite:
            continue
        datos = json.loads(fichero.read_text(encoding="utf-8"))
        consumo = datos.get("consumo") or {}
        tokens = sum(c.get("tokens_entrada", 0) + c.get("tokens_salida", 0)
                     for c in consumo.values())
        for incidencia in datos.get("incidencias", []):
            mensajes_429.append(str(incidencia.get("error", "")))
        if not tokens:
            print(f"  {fichero.name}: sin consumo anotado, se salta")
            continue
        etiqueta = f"artefacto {fichero.name}"
        if etiqueta in ya_estan:
            print(f"  {fichero.name}: ya estaba en el libro, se salta")
            continue
        cuota.anotar(tokens, etiqueta, cuando=cuando)
        anotados += 1
        print(f"  {fichero.name}: {tokens} tokens a las "
              f"{time.strftime('%H:%M', time.localtime(cuando))}")

    print(f"\n  {anotados} corrida(s) anotada(s). El libro dice "
          f"{cuota.gastado()} tokens en la ventana.")

    # Y ahora lo que de verdad cierra el hueco: el `Used` del 429.
    for mensaje in mensajes_429:
        desajuste = cuota.corregir_con_429(mensaje, ahora=ahora)
        if desajuste:
            used = cuota.used_del_429(mensaje)
            print(f"\n  Un 429 dice que la ventana llevaba {used} tokens: "
                  f"{desajuste} más de los que el libro veía.")
            print("  Anotados con la hora de ahora, que es lo conservador: no "
                  "se sabe cuándo se gastaron, así que se les hace salir de la "
                  "ventana lo más tarde posible.")
            break

    print(f"\n  ventana de 24 h: {cuota.gastado()} gastados, quedan "
          f"~{cuota.disponible()} de {cuota.LIMITE_VENTANA}")
    for horas in (2, 6, 12, 24):
        espera = cuota.espera_para(90_000, ahora + horas * 3600)
        cuando = ("ya cabe" if espera == 0 else
                  "no cabe nunca" if espera is None else
                  f"habría que esperar {espera / 3600:.1f} h más")
        print(f"    dentro de {horas:>2} h, para una medición de 90 000 "
              f"tokens: {cuando}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
