"""Comprobación rápida del entorno antes de medir.

Responde a dos preguntas que cambian el plan del día si salen mal:
¿ve CTranslate2 la GPU?, y ¿hay micrófono por donde grabar?
"""

import ctranslate2
import sounddevice as sd

print("ctranslate2", ctranslate2.__version__)
try:
    print("GPUs que ve CTranslate2:", ctranslate2.get_cuda_device_count())
except Exception as exc:  # noqa: BLE001
    print("CUDA no disponible:", type(exc).__name__, exc)

print("--- dispositivos de entrada de audio ---")
por_defecto = sd.default.device[0]
for indice, dispositivo in enumerate(sd.query_devices()):
    if dispositivo["max_input_channels"] > 0:
        marca = "*" if indice == por_defecto else " "
        print(f" {marca} [{indice}] {dispositivo['name']}")
