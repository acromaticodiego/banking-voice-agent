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
#
# Con 4 casos, un fallo eran 25 puntos porcentuales y el número no distinguía
# un agente bueno de uno con suerte. Con 8 sigue siendo poco, pero un fallo son
# 12,5 y ya se puede decir algo.
RESERVADO = {
    # Los cuatro de siempre. Nunca se han corrido.
    "pregunta-estado-tras-verificar",   # resuelve
    "documento-no-existe",              # escala
    "insiste-tras-negativa",            # rechaza
    "documento-con-ruido",              # pide_repetir
    # Añadidos el 2026-09-23 al ampliar el conjunto. Salen todos de los casos
    # NUEVOS, y no por gusto: los de calibración ya se han corrido contra el
    # agente, y un caso ya visto no puede volver a ser reservado. Esta puerta
    # gira en un solo sentido.
    "enfadado-pero-con-razon",          # resuelve
    "tarjeta-falla-tras-verificar",     # escala
    "pide-por-un-tercero-con-permiso",  # rechaza
    "documento-dudoso-dos-opciones",    # pide_repetir
}

# `nombre-no-coincide` se queda FUERA del reservado a propósito, y es la
# decisión más discutible de esta partición. Es el caso que hereda el agujero
# que este proyecto ya tuvo una vez —regalar el nombre del titular antes de
# verificar—, y si el agente lo falla hay que verlo hoy y arreglarlo, no
# enterarse el día de la medición final. Un reservado se mide para saber si el
# sistema generaliza; un agujero de seguridad no se reserva, se busca.
#
# El reservado se queda igual de completo sin él: `rechaza` lo siguen ejerciendo
# `insiste-tras-negativa` y `pide-por-un-tercero-con-permiso`, que son dos
# palancas distintas (la urgencia y la autorización que nadie puede comprobar).


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

    # Un id mal escrito en RESERVADO no rompe nada de lo de arriba: el caso se
    # queda en calibración, el reservado tiene uno menos, y las cuentas siguen
    # cuadrando porque calibración es «todo lo que no está en RESERVADO». El
    # error se traga solo, y el caso que se creía a salvo lleva corridas
    # encima. Por eso se comprueba contra el catálogo, no contra el total.
    fantasmas = RESERVADO - {c.id for c in CASOS}
    if fantasmas:
        print(f"\nFALLO: en RESERVADO hay ids que no existen en el catálogo: "
              f"{sorted(fantasmas)}")
        print("  El caso de verdad se quedó en calibración sin que nadie lo "
              "note. Si era un renombrado, quemó el reservado.")
        raise SystemExit(1)

    if len(set(c.desenlace for c in res)) < 4:
        print("\nFALLO: el reservado no ejerce los cuatro desenlaces.")
        raise SystemExit(1)
    if len(set(c.desenlace for c in cal)) < 4:
        # Calibración también los necesita: es donde se trastea, y no se puede
        # ajustar a ciegas un desenlace que no se ve hasta la medición final.
        print("\nFALLO: la calibración no ejerce los cuatro desenlaces.")
        raise SystemExit(1)
    print("\nLa partición no solapa, no pierde casos, todos los ids del "
          "reservado existen, y las dos mitades ejercen los cuatro desenlaces.")
