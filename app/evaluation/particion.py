r"""Calibración y reservado, con el reservado bajo llave.

El reservado solo vale si **nunca** participó en ajustar nada. Eso no se
consigue con buena voluntad: se consigue haciendo que pedirlo sea incómodo y
deje rastro. Aquí, pedirlo sin declarar que es la medición final **lanza una
excepción**.

No es teatro. Trabajando contra un conjunto se mira el resultado, se cambia una
regla, se vuelve a mirar. Hacer eso tres veces contra el reservado lo convierte
en calibración sin que nadie lo decida, y ya no hay forma de saberlo después.
La barrera está para que la decisión de quemarlo sea explícita y con fecha.

La partición es **fija y por nombre**, no aleatoria. Con una semilla, cambiar
el orden del catálogo cambia quién cae dónde, y un caso que estaba reservado
aparece en calibración sin que nadie lo note.
"""

from __future__ import annotations

from app.evaluation.catalogo import CASOS, Caso

# Repartidos a mano para que los cuatro desenlaces estén en las dos mitades. Un
# reservado sin casos de "rechaza" mediría un agente que nunca se niega y daría
# un número estupendo.
RESERVADO = {
    "pregunta-estado-tras-verificar",   # resuelve
    "documento-no-existe",              # escala
    "insiste-tras-negativa",            # rechaza
    "documento-con-ruido",              # pide_repetir
}


class ReservadoBloqueado(RuntimeError):
    """Se pidió el reservado sin declarar que es la medición final."""


def calibracion() -> list[Caso]:
    """Los casos con los que sí se puede trastear, las veces que haga falta."""
    return [c for c in CASOS if c.id not in RESERVADO]


def reservado(declaro_medicion_final: bool = False) -> list[Caso]:
    """Los casos que solo se miden una vez, y se queman al hacerlo."""
    if not declaro_medicion_final:
        raise ReservadoBloqueado(
            "El reservado no se mira para trastear. Si de verdad es la medición "
            "final, llámalo con declaro_medicion_final=True, y anota la fecha y "
            "el modelo: a partir de ahí ese conjunto está quemado."
        )
    return [c for c in CASOS if c.id in RESERVADO]


if __name__ == "__main__":
    from collections import Counter

    cal = calibracion()
    print(f"calibración: {len(cal)} casos  "
          f"{dict(Counter(c.desenlace for c in cal))}")

    try:
        reservado()
    except ReservadoBloqueado as exc:
        print(f"\nreservado, pedido a la ligera: BLOQUEADO")
        print(f"  {exc}")
    else:
        print("\nFALLO: el reservado se dejó pedir sin declarar nada.")
        raise SystemExit(1)

    res = reservado(declaro_medicion_final=True)
    print(f"\nreservado, declarándolo: {len(res)} casos  "
          f"{dict(Counter(c.desenlace for c in res))}")

    solapan = {c.id for c in cal} & {c.id for c in res}
    if solapan:
        print(f"\nFALLO: casos en los dos lados: {solapan}")
        raise SystemExit(1)
    if len(cal) + len(res) != len(CASOS):
        print("\nFALLO: la partición pierde o duplica casos.")
        raise SystemExit(1)
    if len(set(c.desenlace for c in res)) < 4:
        print("\nFALLO: el reservado no ejerce los cuatro desenlaces.")
        raise SystemExit(1)
    print("\nLa partición no solapa, no pierde casos, y las dos mitades "
          "ejercen los cuatro desenlaces.")
