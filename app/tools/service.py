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


class ConsultaIdentidad(BaseModel):
    documento: str


@app.post("/consultar_identidad")
async def consultar_identidad(
    cuerpo: ConsultaIdentidad,
    x_fallar: Annotated[str | None, Header()] = None,
    x_tardar_ms: Annotated[str | None, Header()] = None,
) -> dict:
    await _simular(x_fallar, x_tardar_ms)
    # El documento llega desde la voz: puede traer puntos, espacios o guiones.
    documento = "".join(c for c in cuerpo.documento if c.isdigit())
    cliente = CLIENTES.get(documento)
    if not cliente:
        # No es un error del sistema: es que no existe. El agente tiene que
        # poder distinguir "no lo encuentro" de "no pude preguntarlo", porque
        # lo primero se le dice a la persona y lo segundo se escala.
        return {"encontrado": False, "documento": documento}
    return {"encontrado": True, "id_cliente": cliente["id_cliente"],
            "nombre": cliente["nombre"]}


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
    return {"encontrado": False, "id_cliente": cuerpo.id_cliente}


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
