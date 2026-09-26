r"""Las herramientas del agente, como servicios HTTP.

Una por capacidad, detrás de una interfaz estable, para que mañana se cambien
por un core bancario de verdad sin tocar el agente. **Esto no es una
arquitectura de microservicios**: el sistema es un monolito de tiempo real con
las herramientas fuera, porque una herramienta es justamente lo que tiene que
poder sustituirse.

Los datos son de mentira y están en memoria. Da igual: lo que se está probando
es que el agente llame a la herramienta correcta con los argumentos correctos,
y eso se prueba igual contra datos falsos.

Tres cosas que sí son de verdad y no se pueden dejar para después:

  · **Idempotencia.** `escalar_a_humano` acepta una clave; si un turno se
    reintenta, no se abren dos tickets. Un reintento es lo normal cuando hay
    red de por medio, y una acción con efecto que se ejecuta dos veces es un
    incidente, no un detalle.
  · **Fallo a voluntad.** La cabecera `X-Fallar` hace que una herramienta
    reviente. Sin poder provocar el fallo no se puede probar qué hace el
    agente cuando algo se cae a mitad de llamada, que es una de las cosas que
    este proyecto tiene que demostrar.
  · **Latencia a voluntad.** `X-Tardar-Ms` retrasa la respuesta. El
    presupuesto del turno cambia entero según lo que tarde la herramienta, y
    conviene poder medirlo sin esperar a tener un core real detrás.

Levantar:  .\.venv\Scripts\python.exe -m uvicorn app.tools.service:app --port 8100
"""

from __future__ import annotations

import asyncio
import unicodedata
import uuid
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Herramientas del agente de voz")

# Clientes de mentira. El documento es el de las grabaciones de prueba.
CLIENTES = {
    "1070234567": {
        "id_cliente": "CL-0001",
        "nombre": "Juan Diego Ossa",
        "tarjetas": [
            {"ultimos": "4582", "tipo": "debito", "estado": "bloqueada",
             "motivo": "movimiento inusual detectado el 2026-09-15",
             "desde": "2026-09-15"},
        ],
    },
}

# Tickets ya abiertos, por clave de idempotencia.
TICKETS: dict[str, dict] = {}


async def _simular(fallar: str | None, tardar_ms: str | None) -> None:
    """Aplica el fallo y el retraso pedidos por cabecera."""
    if tardar_ms:
        await asyncio.sleep(int(tardar_ms) / 1000)
    if fallar:
        raise HTTPException(status_code=503,
                            detail=f"fallo provocado a propósito: {fallar}")


def _normalizar_nombre(texto: str) -> list[str]:
    """Un nombre dicho por teléfono, convertido en palabras comparables.

    Sin acentos, sin mayúsculas y sin puntuación, porque nada de eso llega
    fiable desde la voz: el ASR escribe «Andres» o «Andrés» según le parezca.
    """
    limpio = unicodedata.normalize("NFD", texto or "")
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn")
    limpio = "".join(c if c.isalnum() or c.isspace() else " " for c in limpio)
    return [p for p in limpio.lower().split() if p]


def _nombre_coincide(declarado: str, titular: str) -> bool:
    """¿El nombre que da quien llama corresponde al del titular?

    La regla, con su porqué, porque es una decisión y no un detalle:

      · **Todas** las palabras declaradas tienen que estar en el nombre del
        titular. Si alguien añade un apellido que no es, no coincide: está
        aportando información falsa, no incompleta.
      · Tiene que estar el **último apellido**, que es la parte que un impostor
        con acceso al documento tiene menos probabilidad de acertar.
      · Y hacen falta **al menos dos palabras**: con una sola, «Ossa» bastaría
        para entrar, y eso lo sabe cualquiera que haya visto la cédula.

    Así «Juan Diego Ossa», «Juan Ossa» y «Diego Ossa» valen para un titular que
    se llama Juan Diego Ossa, y no valen «Ossa», «Juan Diego» ni «Juan Diego
    Ossa Restrepo».

    En un banco de verdad esta comparación la haría el servicio de verificación
    con las reglas del banco —tolerancias de nombres compuestos, apellidos de
    casada, homónimos—. Lo que importa aquí no es la regla exacta sino **dónde
    vive**: en el código del servicio, no en una instrucción que el modelo puede
    desobedecer.
    """
    palabras_titular = _normalizar_nombre(titular)
    palabras = _normalizar_nombre(declarado)
    if len(palabras) < 2 or not palabras_titular:
        return False
    if not set(palabras) <= set(palabras_titular):
        return False
    return palabras_titular[-1] in palabras


class ConsultaIdentidad(BaseModel):
    documento: str
    # El nombre que dice quien llama. Opcional porque el agente llama primero
    # con el documento —así sabe si existe antes de pedir nada más— y vuelve con
    # el nombre para verificar.
    nombre_declarado: str | None = None


@app.post("/consultar_identidad")
async def consultar_identidad(
    cuerpo: ConsultaIdentidad,
    x_fallar: Annotated[str | None, Header()] = None,
    x_tardar_ms: Annotated[str | None, Header()] = None,
) -> dict:
    """Verifica una identidad SIN revelar el dato de control.

    Hasta el 2026-09-26 esta herramienta devolvía `nombre`, y ahí estaba la
    fuga. El sistema le entregaba al modelo el nombre del titular y el prompt le
    pedía que no lo dijera: *«pregúntalo y compáralo en silencio»*. Es pedirle a
    un modelo que guarde un secreto que no necesita conocer, y no lo guardó. La
    medición del reservado lo dejó claro —`pide-por-un-tercero-con-permiso`, 3 de
    5 corridas— y en calibración pasaba lo mismo con `nombre-no-coincide`.

    Ahora quien compara es la herramienta. El agente manda el nombre que le
    dieron y recibe un sí o un no. **No puede filtrar lo que nunca tiene**, y eso
    no depende de que obedezca: depende de que la información no exista en su
    contexto.

    El `id_cliente` sale solo cuando la verificación pasa, así que tenerlo es la
    prueba de haber verificado, y es lo que `estado_tarjeta` exige. Límite
    conocido y anotado: un modelo que adivinara el formato del `id_cliente`
    podría saltarse el paso. Cerrarlo del todo pide un testigo aleatorio por
    llamada, que es la siguiente vuelta de este mismo arreglo.
    """
    await _simular(x_fallar, x_tardar_ms)
    # El documento llega desde la voz: puede traer puntos, espacios o guiones.
    documento = "".join(c for c in cuerpo.documento if c.isdigit())
    cliente = CLIENTES.get(documento)
    if not cliente:
        # No es un error del sistema: es que no existe. El agente tiene que
        # poder distinguir "no lo encuentro" de "no pude preguntarlo", porque
        # lo primero se le dice a la persona y lo segundo se escala.
        return {"encontrado": False, "documento": documento}
    if not cuerpo.nombre_declarado:
        return {
            "encontrado": True, "verificado": False,
            "_falta": "nombre_declarado",
            "_que_hacer": ("El documento existe pero la identidad NO está "
                           "verificada. Pide el nombre completo del titular y "
                           "vuelve a llamar con nombre_declarado. No des ningún "
                           "dato de la cuenta hasta que verificado sea true."),
        }
    if not _nombre_coincide(cuerpo.nombre_declarado, cliente["nombre"]):
        return {
            "encontrado": True, "verificado": False, "nombre_coincide": False,
            "_que_hacer": ("El nombre no corresponde al titular. Puedes pedirlo "
                           "UNA vez más por si se oyó mal. Si vuelve a no "
                           "coincidir, no des ningún dato, no digas cuál es el "
                           "nombre correcto, y pasa la llamada a un asesor."),
        }
    return {"encontrado": True, "verificado": True, "nombre_coincide": True,
            "id_cliente": cliente["id_cliente"]}


class EstadoTarjeta(BaseModel):
    id_cliente: str


@app.post("/estado_tarjeta")
async def estado_tarjeta(
    cuerpo: EstadoTarjeta,
    x_fallar: Annotated[str | None, Header()] = None,
    x_tardar_ms: Annotated[str | None, Header()] = None,
) -> dict:
    await _simular(x_fallar, x_tardar_ms)
    for cliente in CLIENTES.values():
        if cliente["id_cliente"] == cuerpo.id_cliente:
            return {"encontrado": True, "tarjetas": cliente["tarjetas"]}
    # Un `id_cliente` que no existe casi siempre significa una cosa concreta: que
    # el agente llegó aquí sin haber verificado y se lo inventó o lo dedujo. Se
    # dice en el resultado, porque el modelo tiene que poder distinguirlo de «no
    # pude preguntarlo» —que se escala— y de «no existe» —que se dice—.
    return {"encontrado": False, "id_cliente": cuerpo.id_cliente,
            "_que_hacer": ("Ese id_cliente no existe. El id_cliente solo lo "
                           "devuelve consultar_identidad cuando la identidad "
                           "queda verificada: verifica primero y usa el que te "
                           "dé. No des ningún dato de la cuenta.")}


class Escalada(BaseModel):
    motivo: str
    clave_idempotencia: str | None = None


@app.post("/escalar_a_humano")
async def escalar_a_humano(
    cuerpo: Escalada,
    x_fallar: Annotated[str | None, Header()] = None,
    x_tardar_ms: Annotated[str | None, Header()] = None,
) -> dict:
    await _simular(x_fallar, x_tardar_ms)
    clave = cuerpo.clave_idempotencia
    if clave and clave in TICKETS:
        # Mismo turno reintentado: se devuelve el ticket que ya existía en vez
        # de abrir otro, y se dice que fue repetida para que quede en el
        # expediente.
        return {**TICKETS[clave], "repetida": True}
    ticket = {"ticket": f"ESC-{uuid.uuid4().hex[:8].upper()}",
              "motivo": cuerpo.motivo, "repetida": False}
    if clave:
        TICKETS[clave] = ticket
    return ticket


@app.get("/salud")
async def salud() -> dict:
    return {"estado": "vivo", "clientes": len(CLIENTES), "tickets": len(TICKETS)}
