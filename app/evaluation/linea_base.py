r"""Lo mismo, sin modelo de lenguaje. Un árbol de decisión sobre las reglas.

Existe para poder decir **cuánto aporta el agente**, y no solo que funciona. Un
13 de 14 no significa nada sin saber qué saca una cosa tonta sobre los mismos
casos: si la línea base saca 12, el modelo está de adorno.

Está escrita de buena fe, no para perder. Hace lo que haría cualquiera con un
rato: busca un documento, si lo encuentra consulta, si la consulta falla escala,
y si no hay documento lo pide. Esa es justamente la trampa de las reglas —cubre
lo previsto y se cae en cuanto la conversación se sale del guion— y enseñarlo es
el objetivo.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "probe"))

from numeros_es import normalizar  # noqa: E402

PATRON = re.compile(r"\b(\d{6,11})\b")

PIDE_DATOS_AJENOS = re.compile(
    r"\b(saldo|a nombre de qui[eé]n|de la cuenta de|su cuenta)\b", re.I)


def _escalar(base: str, motivo: str) -> dict:
    """Escala de verdad, llamando a la herramienta.

    Hasta el 2026-09-24 estas dos ramas DECÍAN "le paso con un asesor" y se
    apuntaban `escalar_a_humano` en la lista de herramientas usadas sin llamar
    a nada. El clasificador lee esa lista, así que la línea base se llevaba el
    desenlace `escala` gratis, sin abrir el ticket que el agente sí abre. Medir
    contra un rival al que se le regala un punto no dice nada de nadie.
    """
    with httpx.Client(timeout=10) as c:
        return c.post(f"{base}/escalar_a_humano",
                      json={"motivo": motivo}).json()


def decidir_sin_modelo(caso, frase: str,
                       base: str) -> tuple[str, list[str], list[dict]]:
    """Un turno, decidido por reglas.

    Devuelve lo que diría, qué herramientas llamó y **lo que devolvieron**. Lo
    tercero se añadió el 2026-09-24: sin los cuerpos de las respuestas no se
    puede comprobar si lo que se dijo salía de algún sitio, y esa comprobación
    tiene que pasar por la línea base igual que por el agente. Si solo se mide
    al agente, el número no tiene con qué compararse — y aquí la comparación es
    especialmente cruel para el agente, porque unas reglas que solo saben
    imprimir lo que les devolvió una herramienta no pueden inventarse nada. Eso
    es exactamente lo que hay que poder decir en voz alta.
    """
    normalizado = normalizar(frase)
    encontrado = PATRON.search(normalizado)

    # Sin documento no se hace nada. Si además está pidiendo datos de otro, se
    # niega; si no, lo pide.
    if not encontrado:
        if PIDE_DATOS_AJENOS.search(frase):
            return ("Por seguridad necesito verificar su identidad antes de "
                    "darle información de la cuenta.", [], [])
        return ("No le entendí el número. ¿Podría repetir su número de "
                "documento?", [], [])

    if caso.fallar_herramienta == "consultar_identidad":
        ticket = _escalar(base, "no se pudo verificar la identidad")
        return ("Tuve un problema para verificar su identidad. Le paso con un "
                "asesor.", ["escalar_a_humano"], [ticket])

    with httpx.Client(timeout=10) as c:
        r = c.post(f"{base}/consultar_identidad",
                   json={"documento": encontrado.group(1)}).json()
    if not r.get("encontrado"):
        ticket = _escalar(base, "documento no encontrado")
        return ("No encontré ese documento en el sistema. Le paso con un "
                "asesor.", ["consultar_identidad", "escalar_a_humano"],
                [r, ticket])

    with httpx.Client(timeout=10) as c:
        t = c.post(f"{base}/estado_tarjeta",
                   json={"id_cliente": r["id_cliente"]}).json()
    tarjeta = t["tarjetas"][0]
    return (f"Su tarjeta terminada en {tarjeta['ultimos']} está "
            f"{tarjeta['estado']} por {tarjeta['motivo']}.",
            ["consultar_identidad", "estado_tarjeta"], [r, t])
