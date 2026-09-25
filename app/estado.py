r"""El estado de una llamada en curso, fuera del proceso que la atiende.

`app/vivo.py` lleva desde el principio diciendo esto en su cabecera:

    "La pasarela no guarda nada suyo: si mañana este estado se mueve a Redis,
     se pueden levantar N pasarelas detrás de un balanceador y cualquiera
     atiende cualquier turno."

Era verdad por diseño y **no estaba demostrado**, que es una forma elegante de
decir que no se sabía. Esto lo mueve y, sobre todo, lo demuestra: hay una
prueba que atiende el primer turno en una pasarela, el segundo en otra
distinta, y comprueba que la conversación sigue.

## Qué viaja y qué no

Viaja **la conversación**: la historia de mensajes, cuántos silencios seguidos
van, qué documentos se han probado ya, el consumo acumulado, y qué le pidió el
agente a quien llama en el último turno.

**No viaja el audio.** El buffer de una intervención se llena y se vacía dentro
de un mismo turno, y un turno lo atiende entera la pasarela que tiene el
WebSocket abierto: mandar trozos de 20 ms a Redis y traerlos de vuelta costaría
más que transcribirlos. Lo que tiene que cruzar la frontera entre pasarelas es
lo que hace falta para seguir la conversación, no lo que hace falta para
terminar la frase.

Esa distinción es la que hace que esto sea barato: se escribe **una vez por
turno**, no una vez por trozo de audio.

## Si Redis no está

Se usa memoria y se dice, igual que con el expediente. Un sistema que no
arranca porque falta una pieza de infraestructura no se puede enseñar en el
portátil de nadie.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probe"))

URL_POR_DEFECTO = "redis://127.0.0.1:56379/0"

# Cuánto sobrevive el estado de una llamada sin que nadie lo toque. Una hora:
# lo bastante para una reconexión y una llamada larga, lo bastante poco para no
# dejar conversaciones de ayer ocupando memoria. Que caduque solo es parte del
# diseño; si hiciera falta guardarlas, para eso está el expediente.
SEGUNDOS_DE_VIDA = 3600


class EnMemoria:
    """Lo de siempre: el estado vive en el proceso y se va con él."""

    def __init__(self) -> None:
        self.datos: dict[str, dict] = {}
        self.fallos = 0
        self.ultimo_error: str | None = None

    @property
    def compartido(self) -> bool:
        """Si es False, la afirmación de escalar horizontal NO se sostiene."""
        return False

    def guardar(self, id_llamada: str, estado: dict) -> None:
        self.datos[id_llamada] = json.loads(json.dumps(estado, default=str))

    def cargar(self, id_llamada: str) -> dict | None:
        return self.datos.get(id_llamada)

    def olvidar(self, id_llamada: str) -> None:
        self.datos.pop(id_llamada, None)


class EnRedis:
    """El estado donde lo puede leer cualquier pasarela."""

    def __init__(self, url: str) -> None:
        import redis  # noqa: PLC0415

        self.cliente = redis.Redis.from_url(url, decode_responses=True,
                                            socket_connect_timeout=3)
        self.cliente.ping()          # sin esto, el fallo aparecería más tarde
        self.fallos = 0
        self.ultimo_error: str | None = None

    @property
    def compartido(self) -> bool:
        return True

    def _clave(self, id_llamada: str) -> str:
        return f"llamada:{id_llamada}"

    def _fallo(self, donde: str, exc: Exception) -> None:
        self.fallos += 1
        self.ultimo_error = f"{donde}: {type(exc).__name__}: {exc}"

    def guardar(self, id_llamada: str, estado: dict) -> None:
        """Se escribe una vez por turno. Si Redis no responde, la llamada
        sigue: se pierde la posibilidad de retomarla en otra pasarela, que es
        malo, pero cortarle la llamada a quien está hablando es peor."""
        try:
            self.cliente.set(self._clave(id_llamada),
                             json.dumps(estado, ensure_ascii=False, default=str),
                             ex=SEGUNDOS_DE_VIDA)
        except Exception as exc:  # noqa: BLE001
            self._fallo("guardar", exc)

    def cargar(self, id_llamada: str) -> dict | None:
        try:
            crudo = self.cliente.get(self._clave(id_llamada))
            return json.loads(crudo) if crudo else None
        except Exception as exc:  # noqa: BLE001
            self._fallo("cargar", exc)
            return None

    def olvidar(self, id_llamada: str) -> None:
        try:
            self.cliente.delete(self._clave(id_llamada))
        except Exception as exc:  # noqa: BLE001
            self._fallo("olvidar", exc)


def desde_entorno(url: str | None = None, callar: bool = False):
    """El almacén de estado que toque, con la razón dicha en voz alta."""
    if url is None:
        url = os.environ.get("ESTADO_URL")
    if url is None:
        try:
            from common import cargar_env  # noqa: PLC0415
            url = cargar_env().get("ESTADO_URL")
        except Exception:  # noqa: BLE001
            url = None
    if url is None:
        url = URL_POR_DEFECTO

    try:
        return EnRedis(url)
    except Exception as exc:  # noqa: BLE001
        if not callar:
            print(f"  estado: sin Redis ({type(exc).__name__}), se queda en "
                  f"memoria. La llamada funciona igual, pero no se puede "
                  f"retomar en otra pasarela.", file=sys.stderr)
        return EnMemoria()
