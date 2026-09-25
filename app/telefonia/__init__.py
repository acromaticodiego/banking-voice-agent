"""Telefonía: el canal por el que llega una llamada de verdad.

Dos piezas, y la separación importa:

  · `g711` produce y consume los bytes µ-law exactos que viajan por la línea,
    comprobados contra la implementación de la biblioteca estándar en los
    65 536 valores posibles.
  · `media_streams` traduce el protocolo de Twilio a una `Llamada` del sistema,
    **sin tocar la red**, para que se pueda comprobar entero con un cliente que
    emule lo que Twilio manda.
"""

from __future__ import annotations

from app.telefonia import g711  # noqa: F401
from app.telefonia.media_streams import (  # noqa: F401
    FRECUENCIA_LINEA,
    FRECUENCIA_SISTEMA,
    MUESTRAS_POR_TROZO,
    PuenteTwilio,
    a_frecuencia,
    twiml,
)
