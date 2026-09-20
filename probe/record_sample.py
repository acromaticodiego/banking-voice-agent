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

# Tres frases y no una, porque un número de transcripción con n=1 no es un
# número. Cada una ataca una cosa distinta de las que rompen el ASR en español:
#
#   1. Un número de documento dicho cifra a cifra. Es el dato que el agente no
#      puede permitirse adivinar, y donde un ASR se come o inventa dígitos.
#   2. Una cantidad de dinero y una fecha. Los números con "mil" y "cientos"
#      se transcriben mal de otra manera: no se pierden, se deforman.
#   3. Titubeos y una corrección a media frase. Es como habla la gente por
#      teléfono de verdad, y es donde un sistema que espera frases limpias se
#      cae. Si el agente no aguanta esto, no aguanta una llamada.
FRASES = {
    "documento": (
        "Buenas tardes, llamo porque me bloquearon la tarjeta esta mañana "
        "y necesito saber por qué. Mi número de documento es el "
        "uno cero siete cero dos tres cuatro cinco seis siete."
    ),
    "monto": (
        "Es que me apareció un cobro de trescientos cuarenta y siete mil "
        "doscientos pesos el martes pasado, en un almacén que yo no conozco, "
        "y quiero que me lo revisen."
    ),
    "titubeos": (
        "Sí, eh... mire, es que la tarjeta, o sea, la de crédito no, "
        "la débito, la que termina en cuatro cinco ocho dos, "
        "esa es la que no me está sirviendo desde ayer."
    ),
}

FRASE = FRASES["documento"]  # la de por defecto, por compatibilidad


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segundos", type=float, default=10.0)
    parser.add_argument("--frases", nargs="*", default=list(FRASES),
                        choices=list(FRASES),
                        help="cuáles grabar; por defecto las tres, una detrás de otra")
    args = parser.parse_args()

    try:
        import sounddevice as sd
    except ImportError:
        print("Falta `sounddevice`. pip install -r requirements-probe.txt", file=sys.stderr)
        return 2

    ARTEFACTOS.mkdir(exist_ok=True)
    grabadas = []

    for numero, nombre in enumerate(args.frases, start=1):
        texto = FRASES[nombre]
        destino = ARTEFACTOS / f"muestra-{nombre}.wav"

        print(f"\n[{numero}/{len(args.frases)}] Lee esto en voz alta, a tu ritmo "
              f"normal de hablar por teléfono:\n")
        print(f"  {texto}\n")
        input("  Pulsa Enter cuando la tengas leída por encima y estés listo...")
        print(f"  Grabo {args.segundos:.0f} segundos.")
        for cuenta in (3, 2, 1):
            print(f"    {cuenta}...", flush=True)
            time.sleep(1)
        print("    GRABANDO", flush=True)

        audio = sd.rec(int(args.segundos * FRECUENCIA), samplerate=FRECUENCIA,
                       channels=1, dtype="int16")
        sd.wait()
        print("    listo.")

        with wave.open(str(destino), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(FRECUENCIA)
            w.writeframes(audio.tobytes())

        referencia = destino.with_suffix(".json")
        referencia.write_text(
            json.dumps({"fichero": destino.name, "frase": nombre,
                        "segundos": args.segundos, "frecuencia_hz": FRECUENCIA,
                        "transcripcion_verdadera": texto},
                       indent=2, ensure_ascii=False),
            encoding="utf-8")
        grabadas.append(destino)

    print("\nGrabadas:")
    for ruta in grabadas:
        print(f"  {ruta}  (+ su {ruta.stem}.json con la transcripción verdadera)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
