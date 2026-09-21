"""¿Tienen señal las grabaciones, o son silencio?

Diagnóstico tonto y rápido: nivel de pico y nivel medio de cada clip. Un
micrófono mal elegido graba diez segundos perfectos de nada, y el fichero pesa
lo mismo que uno bueno.
"""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import ARTEFACTOS  # noqa: E402

for ruta in sorted(ARTEFACTOS.glob("muestra-*.wav")):
    with wave.open(str(ruta), "rb") as w:
        datos = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        frecuencia = w.getframerate()
    pico = int(np.abs(datos).max()) if datos.size else 0
    medio = float(np.abs(datos).mean()) if datos.size else 0.0
    # Proporción de muestras por encima de un umbral bajo: si es casi cero,
    # ahí no habló nadie.
    con_señal = float((np.abs(datos) > 500).mean()) if datos.size else 0.0
    veredicto = "SILENCIO" if pico < 500 else ("muy bajo" if pico < 3000 else "hay voz")
    print(f"{ruta.name:<26} {datos.size / frecuencia:5.1f} s  "
          f"pico {pico:>6} / 32767   medio {medio:7.1f}   "
          f"con señal {con_señal * 100:5.1f}%   -> {veredicto}")
