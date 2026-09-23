"""Convierte números escritos en palabras a cifras, en español.

Existe por un problema concreto de medición. La transcripción verdadera de una
muestra dice "uno cero siete cero dos tres cuatro cinco seis siete" y Whisper
devolvió "1070234567". Palabra por palabra son diez errores; en realidad
acertó el dato entero. Sin normalizar, la tasa de error mide ortografía en vez
de comprensión, y encima castiga al sistema por hacerlo bien.

Y no es solo cosa de la medición: **el agente va a necesitar esto en
producción**. Quien llama dice su documento hablando, y la herramienta que
consulta identidad espera cifras. Esta pieza acaba dentro del sistema.

Dos formas de decir un número y hay que distinguirlas:

  · Cifra a cifra: "cuatro cinco ocho dos" -> 4582. Así se dicen los
    documentos y los últimos dígitos de una tarjeta.
  · Cardinal: "trescientos cuarenta y siete mil doscientos" -> 347200. Así se
    dice el dinero.

La regla para separarlas: una tirada de dos o más palabras que sean TODAS
dígitos sueltos (cero..nueve) es una cifra a cifra. Cualquier otra cosa se
lee como cardinal. No es infalible —"dos mil" empieza con un dígito suelto—
pero el cardinal gana en cuanto aparece una palabra que no es dígito suelto.
"""

from __future__ import annotations

import re
import unicodedata

DIGITOS = {
    "cero": 0, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
}

MENORES = {
    **DIGITOS,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}

DECENAS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}

CENTENAS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
    "setecientos": 700, "ochocientos": 800, "novecientos": 900,
}

MULTIPLICADORES = {"mil": 1000, "millon": 1000000, "millones": 1000000}

PALABRAS = set(MENORES) | set(DECENAS) | set(CENTENAS) | set(MULTIPLICADORES)


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def es_cifra(token: str) -> bool:
    return bool(re.fullmatch(r"\d+", token))


def _cardinal(palabras: list[str]) -> int:
    """Lee una tirada de palabras como un número cardinal."""
    total = 0      # lo ya cerrado por un multiplicador
    parcial = 0    # lo que se está juntando ahora
    for palabra in palabras:
        if palabra == "y":
            continue
        if es_cifra(palabra):
            # Forma mixta: el ASR escribe "347 mil 200", cifra y palabra
            # mezcladas. Es lo que devuelve Whisper de verdad, no un caso raro.
            parcial += int(palabra)
        elif palabra in CENTENAS:
            parcial += CENTENAS[palabra]
        elif palabra in DECENAS:
            parcial += DECENAS[palabra]
        elif palabra in MENORES:
            parcial += MENORES[palabra]
        elif palabra in MULTIPLICADORES:
            factor = MULTIPLICADORES[palabra]
            # "mil" a secas vale mil: "mil doscientos" son 1200, no 200.
            parcial = (parcial or 1) * factor
            total += parcial
            parcial = 0
    return total + parcial


def normalizar(texto: str) -> str:
    """Devuelve el texto con los números en cifras."""
    tokens = sin_tildes(texto.lower()).split()
    salida: list[str] = []
    i = 0
    while i < len(tokens):
        limpio = re.sub(r"[^\w]", "", tokens[i])
        if limpio not in PALABRAS and not es_cifra(limpio):
            salida.append(tokens[i])
            i += 1
            continue

        # Tomar la tirada completa de palabras de número (la "y" une decenas
        # con unidades y no rompe la tirada).
        tirada = []
        j = i
        while j < len(tokens):
            palabra = re.sub(r"[^\w]", "", sin_tildes(tokens[j].lower()))
            if palabra in PALABRAS or es_cifra(palabra):
                tirada.append(palabra)
            elif palabra == "y" and j + 1 < len(tokens):
                siguiente = re.sub(r"[^\w]", "",
                                   sin_tildes(tokens[j + 1].lower()))
                if siguiente in PALABRAS or es_cifra(siguiente):
                    tirada.append("y")
                else:
                    break
            else:
                break
            j += 1

        utiles = [p for p in tirada if p != "y"]
        # Cifra a cifra: vale tanto "uno cero siete" como "1 0 7", porque el ASR
        # devuelve lo segundo. Un solo digito suelto no cuenta: "tengo 3 pesos"
        # no es una tirada.
        sueltos = [p for p in utiles if p in DIGITOS or (es_cifra(p) and len(p) == 1)]
        # Y también vale "70 23 4 5 6 7", que es como sale de Whisper cuando
        # alguien dicta su cédula por grupos. Si la tirada son solo cifras y no
        # hay ningún multiplicador, se concatena: sumarla como cardinal da 115,
        # que no es un número que nadie haya dicho. Con "mil" o "millones" de
        # por medio manda el cardinal, porque ahí sí se está diciendo una
        # cantidad.
        solo_cifras = utiles and all(es_cifra(p) for p in utiles)
        hay_multiplicador = any(p in MULTIPLICADORES for p in utiles)
        if len(utiles) >= 2 and (len(sueltos) == len(utiles)
                                 or (solo_cifras and not hay_multiplicador)):
            salida.append("".join(p if es_cifra(p) else str(DIGITOS[p])
                                  for p in utiles))
        else:
            salida.append(str(_cardinal(tirada)))
        i = j
    return " ".join(salida)


if __name__ == "__main__":
    pruebas = [
        ("uno cero siete cero dos tres cuatro cinco seis siete", "1070234567"),
        ("trescientos cuarenta y siete mil doscientos pesos",
         "347200 pesos"),
        # Este caso se añadió después de mutar el código a propósito: quitar el
        # `or 1` de la línea del multiplicador NO rompía ninguna prueba, porque
        # en todas las demás "mil" llevaba algo delante. Un "mil" a secas vale
        # mil, y hasta ahora nadie lo comprobaba.
        ("mil doscientos pesos", "1200 pesos"),
        ("mil", "1000"),
        # Estos tres salen de lo que Whisper devolvio de verdad sobre las
        # grabaciones. No son casos inventados: son los que hicieron que la
        # tasa de error normalizada saliera PEOR que la literal.
        ("es el 1 0 7 0 2 3 4 5 6 7", "es el 1070234567"),
        ("un cobro de 347 mil 200 pesos", "un cobro de 347200 pesos"),
        ("termina en cuatro, cinco, ocho, dos", "termina en 4582"),
        # De una grabación real, dictando la cédula por grupos. Sumado como
        # cardinal daba 115 y el documento se perdía: el agente no encontraba
        # nada con forma de documento y no podía adelantar la consulta.
        ("mi cédula es 70 23 4 5 6 7", "mi cedula es 70234567"),
        ("es el 10 70 23 45 67", "es el 1070234567"),
        ("la que termina en cuatro cinco ocho dos",
         "la que termina en 4582"),
        ("mi nombre es Juan Diego", "mi nombre es juan diego"),
        ("el martes pasado", "el martes pasado"),
    ]
    fallos = 0
    for entrada, esperado in pruebas:
        obtenido = normalizar(entrada)
        marca = "ok " if obtenido == esperado else "MAL"
        if obtenido != esperado:
            fallos += 1
        print(f"  {marca} {entrada!r}\n      -> {obtenido!r}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} correctas")
    raise SystemExit(1 if fallos else 0)
