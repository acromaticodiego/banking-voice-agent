r"""Cuánta cuota de Groq queda, y cuándo habrá más.

Existe por un fallo del 2026-09-25 que estuvo a punto de costar el reservado.

## Lo que se creía

CLAUDE.md decía «200 000 tokens AL DÍA», y de ahí se seguía que un día nuevo
amanece con la cuota limpia. Con esa cuenta, el 25/09 por la mañana se sumaron
los tokens de las corridas del día —el canario y tres corridas de calibración,
unos 148 000— y se concluyó que quedaban ~52 000: sitio de sobra para empezar
la medición del reservado.

No quedaba nada. La cuarta corrida murió con:

    on tokens per day (TPD): Limit 200000, Used 199423, Requested 737.
    Please try again in 1m9.12s

## Lo que es

**No es un día calendario, es una ventana deslizante de 24 horas.** La prueba
está en el propio mensaje: si el contador se pusiera a cero a medianoche, no
habría nada que reintentar en 69 segundos. Lo que se libera en ese minuto y
pico es el consumo de AYER a esta misma hora saliendo de la ventana. Minutos
después, una petición que pedía 60 000 tokens pasaba sin problema.

Así que la suma del día no estaba mal: estaba incompleta. Le faltaban los
~51 000 tokens gastados el día anterior a esa hora, que seguían dentro de la
ventana. Y no se podían recuperar de ninguna parte, porque nadie los había
anotado.

## Qué hace este módulo

Lleva el libro: cada corrida anota cuántos tokens gastó y **cuándo**. Con las
marcas de tiempo se puede responder lo único que de verdad importa antes de
tocar un conjunto reservado: *¿cabe lo que voy a pedir, y si no, a qué hora
cabrá?*

## Lo que el libro NO ve, que es la parte honesta

Solo ve lo que pasa por el código instrumentado. Una petición hecha a mano
—una sonda suelta, otra sesión, un script de prueba— no aparece. Por eso
`gastado()` es una **cota inferior** del gasto real y `disponible()` una **cota
superior** de lo que queda, y por eso quien decide si empezar algo irreversible
tiene que pedir margen por encima de lo que necesita.

Cuando un 429 revela el `Used` de verdad, `corregir_con_429` anota la
diferencia que el libro no veía. Se anota con la marca de AHORA, no con la de
cuando se gastó —que es desconocida—, y eso es deliberadamente conservador: así
ese trozo sale de la ventana lo más tarde posible, y el libro nunca promete
cuota antes de tiempo.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LIBRO = RAIZ / "artifacts" / "consumo-groq.jsonl"

# El límite que de verdad para el trabajo, y el único que no sale en ninguna
# cabecera: solo aparece en el cuerpo de un 429. Leído ahí el 2026-09-25.
LIMITE_VENTANA = 200_000
VENTANA_S = 24 * 3600

# Medido el 2026-09-25 sobre las tres corridas limpias de calibración del día
# (30 653, 30 523 y 30 625 tokens para 24 turnos cada una): 1275 tokens por
# turno, n=3. Sirve para estimar lo que costará un conjunto que todavía no se
# ha corrido.
#
# Es una aproximación y conviene saber por dónde falla: el coste crece MÁS que
# linealmente con los turnos de una misma conversación, porque cada turno
# reenvía la historia anterior. Trasladar tokens/turno de un conjunto de 2,00
# turnos por caso a uno de 1,75 sobreestima un poco. Se prefiere sobreestimar.
TOKENS_POR_TURNO = 1275


def anotar(tokens: int, etiqueta: str, cuando: float | None = None) -> None:
    """Apunta un gasto en el libro. Una línea JSON por gasto."""
    if tokens <= 0:
        return
    LIBRO.parent.mkdir(parents=True, exist_ok=True)
    linea = json.dumps({"cuando": cuando if cuando is not None else time.time(),
                        "tokens": int(tokens), "etiqueta": etiqueta},
                       ensure_ascii=False)
    with LIBRO.open("a", encoding="utf-8") as fichero:
        fichero.write(linea + "\n")


def entradas(ahora: float | None = None) -> list[dict]:
    """Los gastos que siguen dentro de la ventana, del más viejo al más nuevo.

    Una línea ilegible se salta en silencio: el libro es un registro auxiliar y
    no puede tumbar una medición por un apunte corrupto.
    """
    ahora = time.time() if ahora is None else ahora
    if not LIBRO.exists():
        return []
    dentro = []
    for linea in LIBRO.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            dato = json.loads(linea)
            cuando = float(dato["cuando"])
            tokens = int(dato["tokens"])
        except (ValueError, KeyError, TypeError):
            continue
        if ahora - cuando < VENTANA_S:
            dentro.append({"cuando": cuando, "tokens": tokens,
                           "etiqueta": dato.get("etiqueta", "")})
    return sorted(dentro, key=lambda d: d["cuando"])


def gastado(ahora: float | None = None) -> int:
    """Cota INFERIOR del gasto dentro de la ventana: solo lo que el libro vio."""
    return sum(e["tokens"] for e in entradas(ahora))


def libro_ciego(ahora: float | None = None) -> bool:
    """¿El libro no tiene ni un apunte en la ventana?

    Esta distinción es la misma equivocación del 25/09 con otra cara. Ese día
    se confundió «no tengo información sobre la cuota» con «hay cuota»: la
    sonda dijo «pasa, hay cuota para medir» porque una petición pasó, y de ahí
    se concluyó que había sitio para una medición entera.

    Un libro sin apuntes no dice que la ventana esté limpia. Dice que no sabe,
    y puede estar ciego por dos motivos opuestos: porque de verdad no se ha
    gastado nada en 24 h, o porque el gasto ocurrió por fuera del código que
    anota. Quien vaya a hacer algo irreversible tiene que saber en cuál de los
    dos está, y eso no lo puede decidir este módulo por él.
    """
    return not entradas(ahora)


def disponible(ahora: float | None = None) -> int:
    """Cota SUPERIOR de lo que queda. Nunca negativa."""
    return max(0, LIMITE_VENTANA - gastado(ahora))


def estimar(casos, corridas: int = 1) -> int:
    """Lo que costará correr esos casos k veces, según lo medido el 25/09."""
    turnos = sum(len(c.turnos) for c in casos)
    return TOKENS_POR_TURNO * turnos * corridas


def espera_para(necesarios: int, ahora: float | None = None) -> float | None:
    """Segundos que hay que esperar hasta que quepan `necesarios` tokens.

    0.0 si ya caben. `None` si no van a caber nunca —piden más que la ventana
    entera—, que es un caso distinto de «espera un rato» y el que llama tiene
    que poder distinguirlo.

    Se resuelve mirando cuándo sale de la ventana cada apunte: el gasto hecho
    en `t` deja de contar en `t + 24 h`, así que basta recorrer los apuntes de
    más viejo a más nuevo acumulando lo que se liberaría.
    """
    ahora = time.time() if ahora is None else ahora
    if necesarios > LIMITE_VENTANA:
        return None
    dentro = entradas(ahora)
    falta = necesarios - (LIMITE_VENTANA - sum(e["tokens"] for e in dentro))
    if falta <= 0:
        return 0.0
    liberado = 0
    for apunte in dentro:
        liberado += apunte["tokens"]
        if liberado >= falta:
            return max(0.0, apunte["cuando"] + VENTANA_S - ahora)
    # No debería llegar aquí: liberar todos los apuntes deja la ventana entera
    # libre, y `necesarios` cabe en ella por la comprobación de arriba.
    return None


PATRON_429 = re.compile(r"Limit (\d+), Used (\d+)")


def used_del_429(mensaje: str) -> int | None:
    """El `Used` que Groq mete en el cuerpo del 429. La única cifra real."""
    hallado = PATRON_429.search(mensaje or "")
    return int(hallado.group(2)) if hallado else None


def es_falta_de_cuota(mensaje: str) -> bool:
    """¿Este fallo es falta de cuota, o es otra cosa?

    Hace falta distinguirlo porque el canario de la medición final trataba
    CUALQUIER excepción como falta de cuota, y eso da el diagnóstico equivocado
    con toda la confianza del mundo. El 2026-09-25 se vio en vivo: su petición
    de prueba murió con `400 - Tool choice is none, but model called a tool`
    —un fallo de la propia petición, que no dice nada de la cuota— y el
    programa anunció que no había cuota para medir.

    El proyecto ya lleva tres diagnósticos equivocados seguidos por confundir
    límites (el 24/09, el por minuto con el de la ventana). Este es el mismo
    error una capa más arriba: confundir «falló» con «no hay sitio».
    """
    texto = (mensaje or "").lower()
    return ("rate_limit_exceeded" in texto or "tokens per day" in texto
            or "rate limit reached" in texto or "429" in texto)


def corregir_con_429(mensaje: str, ahora: float | None = None) -> int:
    """Anota lo que el libro no veía, y devuelve cuánto era.

    El `Used` del 429 es el gasto de verdad dentro de la ventana. Lo que el
    libro tenga por debajo de eso es gasto que no pasó por el código
    instrumentado, y sin anotarlo el libro volverá a prometer cuota que no hay.

    Se le pone la marca de AHORA a propósito, aunque se gastara antes: así sale
    de la ventana lo más tarde posible y el error queda del lado seguro.
    """
    used = used_del_429(mensaje)
    if used is None:
        return 0
    desajuste = used - gastado(ahora)
    if desajuste > 0:
        anotar(desajuste, "corrección de un 429: lo que el libro no veía",
               cuando=ahora)
    return max(0, desajuste)
