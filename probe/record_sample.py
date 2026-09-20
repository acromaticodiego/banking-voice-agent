"""Graba una muestra de voz para medir el voz->texto.

La frase está escrita de antemano a propósito. Dos motivos:

  1. Comparar el mismo audio entre `faster-whisper` y Deepgram Nova-3 solo
     tiene sentido si es literalmente el mismo audio.
  2. Deja la transcripción verdadera escrita, así que la misma muestra sirve
     después para la tasa de error de transcripción sin volver a grabar. Un
     número de documento dicho en voz alta es justo donde el ASR se rompe, y
     es justo el dato que el agente no puede permitirse adivinar.

El WAV se queda en `artifacts/` y está en .gitignore: no se versiona voz.

Uso:  python probe/record_sample.py [--segundos 10]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

from common import ARTEFACTOS

FRECUENCIA = 16000  # Hz. Es lo que usa la telefonía y lo que espera Whisper.

FRASE = (
    "Buenas tardes, llamo porque me bloquearon la tarjeta esta mañana "
    "y necesito saber por qué. Mi número de documento es el "
    "uno cero siete cero dos tres cuatro cinco seis siete."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segundos", type=float, default=10.0)
    parser.add_argument("--salida", default="muestra-voz.wav")
    args = parser.parse_args()

    try:
        import sounddevice as sd
    except ImportError:
        print("Falta `sounddevice`. pip install -r requirements-probe.txt", file=sys.stderr)
        return 2

    ARTEFACTOS.mkdir(exist_ok=True)
    destino = ARTEFACTOS / args.salida

    print("Lee esta frase en voz alta, a tu ritmo normal de hablar por teléfono:\n")
    print(f"  {FRASE}\n")
    print(f"Grabo {args.segundos:.0f} segundos. Empieza cuando veas GRABANDO.")
    for cuenta in (3, 2, 1):
        print(f"  {cuenta}...", flush=True)
        time.sleep(1)
    print("  GRABANDO", flush=True)

    audio = sd.rec(int(args.segundos * FRECUENCIA), samplerate=FRECUENCIA,
                   channels=1, dtype="int16")
    sd.wait()
    print("  listo.")

    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FRECUENCIA)
        w.writeframes(audio.tobytes())

    referencia = destino.with_suffix(".json")
    referencia.write_text(
        json.dumps({"fichero": destino.name, "segundos": args.segundos,
                    "frecuencia_hz": FRECUENCIA, "transcripcion_verdadera": FRASE},
                   indent=2, ensure_ascii=False),
        encoding="utf-8")

    print(f"\nAudio en {destino}")
    print(f"Transcripción verdadera en {referencia}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
