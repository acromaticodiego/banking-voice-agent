"""Sonda de latencia del texto->voz local: Piper.

Mide **tiempo hasta el primer trozo de audio**, no hasta terminar la frase.
Piper sintetiza por oraciones y las va entregando; en la llamada real el primer
trozo ya se está reproduciendo mientras se genera el segundo, así que lo que
entra en el presupuesto del turno es el primero.

Se mide también el factor de tiempo real (segundos de síntesis por segundo de
audio producido). Si ese factor es menor que 1, el audio se genera más deprisa
de lo que se escucha y la reproducción nunca se queda sin material: el resto de
la respuesta sale gratis en latencia percibida. Ese es el número que decide si
conviene una voz `high` o una `medium`.

Uso:  python probe/probe_piper.py [--repeticiones 10]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from common import RAIZ, Medicion, guardar

VOCES = {
    "es_MX-claude-high": RAIZ / "voices" / "es_MX-claude-high.onnx",
    "es_ES-davefx-medium": RAIZ / "voices" / "es_ES-davefx-medium.onnx",
}

# Lo que diría el agente en un turno real: una primera frase corta que se puede
# empezar a reproducir enseguida, y el resto detrás. Está escrito así a
# propósito, y es una decisión de diseño del agente, no del TTS: la primera
# frase que emite el modelo marca el tiempo hasta que se oye algo.
TEXTO = (
    "Claro que sí, ya lo reviso. "
    "Su tarjeta aparece bloqueada por seguridad desde esta mañana, "
    "y para levantarlo necesito confirmar dos datos más."
)


def medir(voz_nombre: str, ruta: Path, repeticiones: int) -> list[Medicion]:
    from piper import PiperVoice

    arranque = time.perf_counter()
    voz = PiperVoice.load(str(ruta))
    carga_ms = (time.perf_counter() - arranque) * 1000
    print(f"  {voz_nombre}: modelo cargado en {carga_ms:.0f} ms")

    primero = Medicion(
        etapa="tts", implementacion=f"piper {voz_nombre}",
        que_mide="desde que se entrega el texto hasta el primer trozo de audio reproducible",
    )
    completo = Medicion(
        etapa="tts", implementacion=f"piper {voz_nombre} (total)",
        que_mide="desde que se entrega el texto hasta el último trozo (dato secundario)",
        notas="No entra en el presupuesto: se solapa con la reproducción.",
    )

    factores = []
    for i in range(repeticiones + 1):  # la primera se descarta: calentamiento
        inicio = time.perf_counter()
        ttfb = None
        muestras = 0
        frecuencia = 0
        for trozo in voz.synthesize(TEXTO):
            if ttfb is None:
                ttfb = time.perf_counter()
            muestras += len(trozo.audio_int16_bytes) // 2
            frecuencia = trozo.sample_rate
        fin = time.perf_counter()

        if i == 0:
            continue
        duracion_audio = muestras / frecuencia if frecuencia else 0
        primero.muestras_ms.append((ttfb - inicio) * 1000)
        completo.muestras_ms.append((fin - inicio) * 1000)
        factores.append(((fin - inicio) / duracion_audio) if duracion_audio else 0)
        print(f"    {i}/{repeticiones}: primer trozo {primero.muestras_ms[-1]:.0f} ms, "
              f"completo {completo.muestras_ms[-1]:.0f} ms, "
              f"{duracion_audio:.1f} s de audio")

    if factores:
        medio = sum(factores) / len(factores)
        completo.notas += (f" Factor de tiempo real: {medio:.2f} s de síntesis por s de audio"
                           f" ({'la reproducción no se queda sin material' if medio < 1 else 'NO alcanza a la reproducción'}).")
    return [primero, completo]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeticiones", type=int, default=10)
    args = parser.parse_args()

    faltan = [n for n, p in VOCES.items() if not p.exists()]
    if faltan:
        print("Faltan voces: " + ", ".join(faltan), file=sys.stderr)
        print("Descárgalas con: python -m piper.download_voices --download-dir voices "
              + " ".join(faltan), file=sys.stderr)
        return 2

    mediciones: list[Medicion] = []
    for nombre, ruta in VOCES.items():
        mediciones.extend(medir(nombre, ruta, args.repeticiones))
        print()

    print("Resultado:")
    for m in mediciones:
        print(m.linea())
        if m.notas:
            print(f"        {m.notas.strip()}")

    destino = guardar(mediciones, "piper")
    print(f"\nGuardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
