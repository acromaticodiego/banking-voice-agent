r"""Leer un expediente, como lo leería quien audita.

Un expediente que solo se puede consultar escribiendo SQL a mano no es un
expediente, es una tabla. Esto lo imprime en el orden en que pasaron las cosas
y con la pregunta que de verdad se le hace delante: **el agente dijo esto, ¿de
dónde lo sacó?**

Por eso cada turno se imprime con lo que se oyó, lo que se contestó y, en
medio, las herramientas con sus argumentos y su resultado. Y por eso lo que el
detector encontró sin fundamento va pegado al turno y no en un resumen al
final: al final, nadie lo lee.

Uso:
  .\.venv\Scripts\python.exe -m app.expediente.leer              # las últimas
  .\.venv\Scripts\python.exe -m app.expediente.leer <id-llamada>
"""

from __future__ import annotations

import argparse
import json
import sys

from app.expediente import DSN_POR_DEFECTO, EnPostgres


def ultimas(almacen: EnPostgres, cuantas: int) -> list[tuple]:
    with almacen.conexion.cursor() as cur:
        cur.execute(
            "SELECT id, abierta_en, cerrada_en, motivo_cierre, turnos, "
            "tokens_entrada + tokens_salida FROM llamada "
            "ORDER BY abierta_en DESC LIMIT %s", (cuantas,))
        return cur.fetchall()


def imprimir(llamada: dict) -> None:
    print("=" * 78)
    print(f"LLAMADA {llamada['id']}")
    print(f"  abierta   : {llamada['abierta_en']}")
    print(f"  cerrada   : {llamada['cerrada_en'] or 'SIGUE ABIERTA'}"
          + (f"  ({llamada['motivo_cierre']})" if llamada['motivo_cierre'] else ""))
    print(f"  turnos    : {llamada['turnos']}")
    print(f"  consumo   : {llamada['tokens_entrada']} tokens de entrada, "
          f"{llamada['tokens_salida']} de salida, "
          f"{llamada['peticiones']} peticiones al modelo")

    for turno in llamada["conversacion"]:
        print()
        print(f"  --- turno {turno['orden']} "
              + ("(TURNO VACÍO, nadie dijo nada) " if turno["silencio"] else "")
              + "-" * 40)
        if turno["oido"]:
            print(f"    quien llama : {turno['oido']}")
        if turno["puente"]:
            print(f"    mientras    : {turno['puente']}")
        for paso in turno["pasos"]:
            if paso["tipo"] == "herramienta":
                print(f"    herramienta : {paso['detalle']}  ({paso['ms']} ms)")
                print(f"        con     : {_corto(paso['argumentos'])}")
                print(f"        devolvió: {_corto(paso['resultado'])}")
                if paso["error"]:
                    print(f"        ERROR   : {paso['error']}")
            elif paso["tipo"] == "limite":
                print(f"    RELOJ       : {paso['detalle']}")
        print(f"    el agente   : {turno['contestado']}")

        marcado = turno["sin_fundamento"]
        if marcado is None:
            print("    revisión    : no se revisó")
        else:
            hallazgos = {k: v for k, v in marcado.items() if v}
            if hallazgos:
                print(f"    SIN FUNDAMENTO: {hallazgos}")
            else:
                print("    revisión    : todo lo dicho tiene de dónde salir")
        if turno["agotado"]:
            print("    (se agotó el presupuesto del turno)")


def _corto(valor, limite: int = 150) -> str:
    if valor is None:
        return "—"
    texto = json.dumps(valor, ensure_ascii=False, default=str)
    return texto if len(texto) <= limite else texto[:limite] + "…"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("id_llamada", nargs="?", default=None)
    parser.add_argument("--dsn", default=DSN_POR_DEFECTO)
    parser.add_argument("--cuantas", type=int, default=10)
    args = parser.parse_args()

    try:
        almacen = EnPostgres(args.dsn, crear_esquema=False)
    except Exception as exc:  # noqa: BLE001
        print(f"No hay expediente que leer: {type(exc).__name__}.", file=sys.stderr)
        print("Levántalo con  docker compose up -d", file=sys.stderr)
        return 2

    try:
        if args.id_llamada:
            llamada = almacen.leer(args.id_llamada)
            if llamada is None:
                print(f"No existe la llamada {args.id_llamada}", file=sys.stderr)
                return 1
            imprimir(llamada)
            return 0

        filas = ultimas(almacen, args.cuantas)
        if not filas:
            print("No hay ninguna llamada guardada todavía.")
            return 0
        print(f"{'llamada':<38} {'abierta':<22} {'turnos':>6} {'tokens':>8}")
        for f in filas:
            print(f"{str(f[0]):<38} {f[1]:%Y-%m-%d %H:%M:%S}      "
                  f"{f[4]:>6} {f[5]:>8}"
                  + ("" if f[2] else "   (abierta)"))
        print(f"\nPara ver una entera:  python -m app.expediente.leer <id>")
        return 0
    finally:
        almacen.cerrar_conexion()


if __name__ == "__main__":
    raise SystemExit(main())
