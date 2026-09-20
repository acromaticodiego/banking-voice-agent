"""¿Carga faster-whisper en la GPU de esta máquina, o hay que resignarse a CPU?

Se comprueba por separado y con audio sintético para no gastar el turno de
grabación del usuario averiguando algo que puede fallar por cuDNN.
"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from probe_whisper_local import cargar_modelo  # noqa: E402

ruido = (np.random.randn(16000 * 3) * 0.01).astype(np.float32)

modelo, dispositivo, carga_ms, errores = cargar_modelo("small")
print(f"cargado en {dispositivo} en {carga_ms:.0f} ms")
for e in errores:
    print(f"  descartado -> {e}")

arranque = time.perf_counter()
segmentos, _ = modelo.transcribe(ruido, language="es", beam_size=1)
texto = "".join(s.text for s in segmentos)
print(f"transcribir 3 s de ruido: {(time.perf_counter() - arranque) * 1000:.0f} ms")
print(f"salida: {texto!r}")
