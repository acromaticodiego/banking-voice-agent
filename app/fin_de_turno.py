r"""¿Ha terminado de hablar, o solo está respirando?

El silencio solo no basta. Medido en `docs/adr/0002`: la ventana más corta que
no corta a nadie a mitad de turno es de 1600 ms, el 188% del presupuesto
entero. Y con una ventana que sí cabe, el sistema corta a la gente mientras
dicta su cédula — pasó, y está en `docs/adr/0004`:

    dijo: "claro que sí, mirá mis datos son mi cédula es 70 234"

Esto mira **lo que se ha dicho**, no cuánto lleva callado. Si la frase está a
medias, se espera más. Si está entera, se contesta ya.

## Por qué son reglas y no una llamada a un modelo

Preguntarle al modelo "¿terminó?" cuesta otra petición en la ruta crítica, y el
modelo es justo la etapa cara: 325 ms en el mejor caso. Gastar eso en cada
pausa para decidir si esperar 900 ms más es pagar el problema para no tenerlo.

Las reglas cuestan microsegundos y se pueden leer. Cuando no acierten, el
siguiente paso es un clasificador pequeño entrenado, no el modelo grande.

## El coste de equivocarse no es simétrico

- **Decir "terminó" cuando no ha terminado** corta a la persona en mitad de su
  documento, pierde el dato, y obliga a repetir la llamada entera.
- **Decir "no ha terminado" cuando sí** hace esperar 900 ms de más.

Lo primero es mucho peor, así que ante la duda se espera.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "probe"))

# Palabras que no pueden ser la última de una intervención terminada. Casi
# todas piden algo detrás: una preposición sin complemento, un verbo copulativo
# sin atributo, un artículo sin sustantivo.
COLGANDO = {
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "y", "o", "que", "con", "para", "por", "en", "a", "al", "sin", "sobre",
    "mi", "mis", "su", "sus", "tu", "tus", "es", "son", "era", "eran",
    "esta", "este", "esa", "ese", "como", "cuando", "porque", "pero",
    "entonces", "osea", "sea", "eh", "este...", "bueno",
}

# Un documento colombiano tiene entre seis y once dígitos. Menos que eso,
# cuando lo que se pidió fue el documento, es una cifra a medio decir.
MINIMO_DOCUMENTO = 6
MAXIMO_DOCUMENTO = 11


def _tokens(texto: str) -> list[str]:
    limpio = re.sub(r"[^\w\sáéíóúüñ]", " ", texto.lower())
    return limpio.split()


def parece_incompleto(texto: str, esperando: str | None = None) -> str | None:
    """Devuelve el motivo si la intervención está a medias, o None si está entera.

    `esperando` dice qué se le pidió a la persona, si es que se le pidió algo.
    Con "documento", un número corto deja de ser ambiguo: es una cédula a medio
    decir, y eso no se puede saber sin conocer lo que se preguntó.
    """
    from numeros_es import normalizar

    palabras = _tokens(texto)
    if not palabras:
        return "no se ha dicho nada todavía"

    if palabras[-1] in COLGANDO:
        return f"termina en «{palabras[-1]}», que pide algo detrás"

    normalizado = normalizar(texto)
    cifras = re.findall(r"\d+", normalizado)

    if esperando == "documento":
        completo = [c for c in cifras
                    if MINIMO_DOCUMENTO <= len(c) <= MAXIMO_DOCUMENTO]
        if not completo:
            if cifras:
                return (f"se pidió el documento y lo dicho hasta ahora es "
                        f"«{cifras[-1]}», demasiado corto")
            return "se pidió el documento y todavía no se ha dicho ningún número"

    # Una intervención que acaba justo en un número corto suele estar a medio
    # decir aunque no se hubiera pedido nada: "la que termina en cuatro cinco".
    ultimo = _tokens(normalizado)[-1] if _tokens(normalizado) else ""
    if ultimo.isdigit() and len(ultimo) < MINIMO_DOCUMENTO and esperando:
        return f"acaba en un número corto («{ultimo}») y aún se espera {esperando}"

    return None


if __name__ == "__main__":
    pruebas = [
        # (texto, esperando, debe_estar_incompleto)
        ("claro que sí, mirá mis datos son mi cédula es 70 234", "documento", True),
        ("mi cédula es 70 23 4 5 6 7", "documento", False),
        ("mi cédula es", "documento", True),
        # Estos dos se añadieron después de mutar el código: quitar la regla
        # del documento incompleto NO rompía ninguna prueba, porque en todas
        # el número corto quedaba al final y lo cazaba la otra regla. Aquí el
        # número corto está en medio y la frase sigue, así que solo la regla
        # del documento puede verlo.
        ("mi cédula es 234 y llamo por lo de la tarjeta", "documento", True),
        ("ahora mismo no me acuerdo", "documento", True),
        ("mi número de documento es el uno cero siete cero dos tres cuatro cinco seis siete",
         "documento", False),
        ("buenas, me bloquearon la tarjeta y no sé por qué", None, False),
        ("es que me apareció un cobro de trescientos cuarenta y siete mil doscientos pesos",
         None, False),
        ("no funciona desde el día de ayer", None, False),
        ("mire, es que la tarjeta, o sea, la de", None, True),
        ("quiero hablar con un asesor porque", None, True),
        ("", None, True),
    ]
    fallos = 0
    for texto, esperando, debe in pruebas:
        motivo = parece_incompleto(texto, esperando)
        bien = (motivo is not None) == debe
        fallos += 0 if bien else 1
        print(f"  {'ok ' if bien else 'MAL'} {texto[:58]!r:<62} "
              f"-> {motivo or 'entera'}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} correctas")
    raise SystemExit(1 if fallos else 0)
