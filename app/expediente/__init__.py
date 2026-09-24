"""El expediente de la llamada: qué se dijo, qué se llamó y qué devolvió.

`desde_entorno()` es la puerta de entrada. Decide sola si hay una base de datos
que usar, y si no la hay **dice que se queda en memoria en vez de fallar**: la
demo tiene que poder correr en un portátil sin Docker, y un proyecto que exige
levantar infraestructura para enseñarse no se enseña.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.expediente.almacen import (  # noqa: F401
    EnMemoria,
    EnPostgres,
    TurnoAnotado,
    pasos_desde_rastro,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "probe"))

DSN_POR_DEFECTO = ("postgresql://agente:agente_local@127.0.0.1:55432/expediente")


def desde_entorno(dsn: str | None = None, callar: bool = False):
    """El almacén que toque, con la razón dicha en voz alta.

    Busca el DSN en el argumento, luego en `EXPEDIENTE_DSN` (entorno o `.env`),
    y si no hay nada usa el de `docker-compose.yml`. Si no se puede conectar,
    devuelve `EnMemoria` y lo explica: quedarse sin expediente por sorpresa es
    justo lo que este módulo vino a arreglar.
    """
    if dsn is None:
        dsn = os.environ.get("EXPEDIENTE_DSN")
    if dsn is None:
        try:
            from common import cargar_env  # noqa: PLC0415
            dsn = cargar_env().get("EXPEDIENTE_DSN")
        except Exception:  # noqa: BLE001
            dsn = None
    if dsn is None:
        dsn = DSN_POR_DEFECTO

    try:
        return EnPostgres(dsn)
    except Exception as exc:  # noqa: BLE001
        if not callar:
            print(f"  expediente: sin base de datos ({type(exc).__name__}), "
                  f"se queda en memoria y se perderá al cerrar. "
                  f"Para tenerlo: docker compose up -d", file=sys.stderr)
        return EnMemoria()
