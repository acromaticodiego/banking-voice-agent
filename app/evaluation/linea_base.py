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


def decidir_sin_modelo(caso, frase: str, base: str) -> tuple[str, list[str]]:
    """Un turno, decidido por reglas. Devuelve lo que diría y qué llamó."""
    normalizado = normalizar(frase)
    encontrado = PATRON.search(normalizado)

    # Sin documento no se hace nada. Si además está pidiendo datos de otro, se
    # niega; si no, lo pide.
    if not encontrado:
        if PIDE_DATOS_AJENOS.search(frase):
            return ("Por seguridad necesito verificar su identidad antes de "
                    "darle información de la cuenta.", [])
        return ("No le entendí el número. ¿Podría repetir su número de "
                "documento?", [])

    if caso.fallar_herramienta == "consultar_identidad":
        return ("Tuve un problema para verificar su identidad. Le paso con un "
                "asesor.", ["escalar_a_humano"])

    with httpx.Client(timeout=10) as c:
        r = c.post(f"{base}/consultar_identidad",
                   json={"documento": encontrado.group(1)}).json()
    if not r.get("encontrado"):
        return ("No encontré ese documento en el sistema. Le paso con un "
                "asesor.", ["consultar_identidad", "escalar_a_humano"])

    with httpx.Client(timeout=10) as c:
        t = c.post(f"{base}/estado_tarjeta",
                   json={"id_cliente": r["id_cliente"]}).json()
    tarjeta = t["tarjetas"][0]
    return (f"Su tarjeta terminada en {tarjeta['ultimos']} está "
            f"{tarjeta['estado']} por {tarjeta['motivo']}.",
            ["consultar_identidad", "estado_tarjeta"])
