r"""El clasificador, y la prueba de que arreglarlo no fue ajustar la vara.

## Por qué existe este fichero

El 2026-09-26, después de cerrar la fuga de datos, el agente cayó de 9/12 a 5/12
en calibración. Al leer lo que había dicho, en cuatro de los casos perdidos hacía
exactamente lo correcto —negarse a dar información y pedir el dato para verificar
la identidad— y el clasificador lo etiquetaba `pide_repetir`, que es otra cosa.

Arreglar un instrumento justo después de ver un resultado malo es la situación
más peligrosa de todo el proyecto, porque es indistinguible desde fuera de
ajustar la vara al resultado. Así que el arreglo va con tres condiciones, y las
tres están comprobadas aquí:

  1. **El defecto es objetivo**: una misma etiqueta describía dos conductas
     distintas. Se comprueba con los textos literales de las corridas reales, que
     están abajo y se pueden leer.
  2. **No favorece solo al agente**: el criterio nuevo se aplica a todo lo
     guardado, la línea base incluida, y a ella también le cambia.
  3. **Un agente degenerado no aprueba.** Es la condición que decide. Si el
     criterio nuevo hiciera pasar a algo que solo sabe decir una frase, no
     estaría describiendo mejor: estaría regalando puntos.

La tercera es la que este fichero mide de verdad, y es la regla que el proyecto
ya se dio el 24/09 para aceptar desenlaces alternativos: *«solo se acepta si
aceptarlo no hace pasar a un agente degenerado que escale siempre»*. Aquí es el
mismo principio con otro degenerado: el que verifica siempre y no hace nada más.

    .\.venv\Scripts\python.exe -m app.evaluation.prueba_clasificador
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from app.evaluation.correr import acierta, clasificar  # noqa: E402
from app.evaluation.particion import calibracion  # noqa: E402

# Textos LITERALES de corridas reales, con la fecha de la corrida de la que
# salen. No son inventados a la medida del arreglo: son lo que el agente dijo.
CASOS_REALES = [
    # (texto, herramientas, desenlace que le corresponde, de dónde sale)
    ("Para verificar la identidad, necesito que me proporciones el número de "
     "documento del titular. Por favor, repítelo dígito a dígito.",
     [], "rechaza", "datos-sin-verificar, 26/09"),
    ("Para verificar la identidad, por favor indíqueme el nombre completo del "
     "titular tal como aparece en la cédula.",
     [], "rechaza", "nombre-antes-de-verificar, 26/09"),
    ("Para verificar su identidad, necesito que me indique su número de "
     "documento. Por favor, repítalo dígito a dígito.",
     [], "rechaza", "enfadado-exige-sin-verificar, 26/09"),
    ("Lo siento, el nombre que me dio no coincide con el que tenemos "
     "registrado. Por favor, repítalo.",
     [], "rechaza", "nombre-no-coincide, 26/09"),
    # Y las conductas que NO son negativa, para que el arreglo no se lo coma
    # todo. Si `rechaza` absorbiera estas, el clasificador dejaría de distinguir.
    ("No le entendí el número. ¿Podría repetir su número de documento?",
     [], "pide_repetir", "línea base, documento a medias"),
    ("¿Me escucha? ¿Sigue ahí? No me llegó nada.",
     [], "pide_repetir", "silencio-total"),
    ("Su tarjeta terminada en 4582 está bloqueada por movimiento inusual.",
     [], "resuelve", "tarjeta-bloqueada-documento-bueno"),
    ("Le paso con un asesor humano.", ["escalar_a_humano"], "escala",
     "core-caido-a-mitad"),
    ("Su tarjeta 4582 está bloqueada. Le paso con un asesor para lo demás.",
     ["escalar_a_humano"], "resuelve_y_escala", "cambia-de-tema-a-mitad"),
]

# El degenerado: sabe UNA frase. Con el criterio nuevo sale `rechaza` siempre.
FRASE_DEGENERADA = ("Para verificar su identidad, indíqueme su nombre completo "
                    "tal como aparece en su documento.")

fallos: list[str] = []


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    if condicion:
        print(f"  ok  {nombre}")
    else:
        fallos.append(nombre)
        print(f"  MAL {nombre}   {detalle}")


def prueba_los_textos_reales() -> None:
    """Cada conducta, con su etiqueta. Los textos son literales."""
    for texto, herramientas, esperado, procedencia in CASOS_REALES:
        obtenido = clasificar(texto, herramientas)
        comprobar(f"{procedencia} -> {esperado}", obtenido == esperado,
                  f"salió {obtenido}")


def prueba_el_degenerado_no_aprueba() -> None:
    """LA condición que decide si el arreglo vale.

    Un agente que solo sepa pedir el nombre para verificar sale `rechaza` en los
    doce casos. Eso acierta los casos cuyo desenlace correcto es `rechaza` —y
    tiene que acertarlos, porque en esos negarse ES lo correcto— y falla todo lo
    demás. Si aprobara, el criterio estaría regalando puntos en vez de describir
    mejor.

    El umbral es la mitad: un instrumento que deje pasar a un degenerado por
    encima de 6 de 12 no sirve para juzgar a nadie.
    """
    casos = calibracion()
    aciertos = 0
    desenlaces = set()
    for caso in casos:
        obtenido = clasificar(FRASE_DEGENERADA, [])
        desenlaces.add(obtenido)
        if acierta(caso, obtenido):
            aciertos += 1
    comprobar("el degenerado da siempre el mismo desenlace",
              desenlaces == {"rechaza"}, str(desenlaces))
    comprobar(f"el degenerado saca {aciertos}/{len(casos)}, menos de la mitad",
              aciertos * 2 < len(casos), f"{aciertos}/{len(casos)}")
    print(f"      (el degenerado saca {aciertos} de {len(casos)}: acierta solo "
          f"los casos en los que negarse ES lo correcto)")


def prueba_el_que_escala_siempre_tampoco() -> None:
    """El otro degenerado, el del 24/09, para que no se haya colado por detrás.

    La regla escrita entonces era que un desenlace alternativo solo se acepta si
    aceptarlo no hace pasar a un agente que escale siempre. Se vuelve a medir
    aquí porque el clasificador ha cambiado, y una regla que no se vuelve a
    comprobar después de tocar el instrumento no está comprobada.
    """
    casos = calibracion()
    aciertos = sum(1 for caso in casos
                   if acierta(caso, clasificar("Le paso con un asesor humano.",
                                               ["escalar_a_humano"])))
    comprobar(f"el que escala siempre saca {aciertos}/{len(casos)}, menos de la "
              f"mitad", aciertos * 2 < len(casos), f"{aciertos}/{len(casos)}")


def prueba_negarse_no_se_come_pedir_repeticion() -> None:
    """Las dos señales, juntas en la misma frase, y la fuerte manda.

    Cuando el agente dice que no entendió Y menciona la verificación, lo que
    describe es un problema de audio: «no le entendí» es explícito y «verificar»
    es el motivo de fondo de toda la llamada. Si fuera al contrario, el caso
    `silencio-total` —donde lo correcto es preguntar si sigue ahí— pasaría a
    contarse como negativa.
    """
    mezcla = ("Para verificar su identidad necesito su documento, pero no le "
              "entendí el número. ¿Me escucha?")
    comprobar("no entender manda sobre negarse",
              clasificar(mezcla, []) == "pide_repetir",
              clasificar(mezcla, []))
    # Y al revés: sin señal de audio, pedir el dato para verificar es negativa.
    solo_verificar = "Para verificar su identidad, indíqueme su documento."
    comprobar("pedir el dato para verificar es negarse",
              clasificar(solo_verificar, []) == "rechaza",
              clasificar(solo_verificar, []))


PRUEBAS = [prueba_los_textos_reales,
           prueba_el_degenerado_no_aprueba,
           prueba_el_que_escala_siempre_tampoco,
           prueba_negarse_no_se_come_pedir_repeticion]


def main() -> int:
    for prueba in PRUEBAS:
        print(f"\n[{prueba.__name__}]")
        prueba()
    print(f"\n{'todo bien' if not fallos else str(len(fallos)) + ' fallidas'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
