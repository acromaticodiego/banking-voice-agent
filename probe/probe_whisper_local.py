"""Sonda de latencia del voz->texto local: faster-whisper.

Mide dos cosas distintas y no hay que confundirlas:

  · `asr_lote`  — transcribir los 10 segundos enteros. NO es la latencia del
    turno. Sirve para el factor de tiempo real (segundos de proceso por segundo
    de audio), que es lo que dice si la máquina aguanta el ritmo del habla.

  · `asr_cola`  — transcribir solo los últimos 2 segundos. Esto sí se parece a
    la latencia del turno: en una tubería por trozos, cuando la persona calla
    ya está casi todo procesado y lo que falta es rematar la cola. Es una
    aproximación, no la medida real de un ASR en streaming, y así hay que
    contarla.

Whisper no es un modelo de streaming. Esta sonda no pretende que lo sea:
pretende decir si merece la pena desarrollar contra él sin gastar crédito.

Uso:  python probe/probe_whisper_local.py [--modelo small] [--repeticiones 5]
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

from common import ARTEFACTOS, Medicion, guardar


def leer_wav(ruta: Path) -> tuple["object", int, float]:
    import numpy as np
    with wave.open(str(ruta), "rb") as w:
        frecuencia = w.getframerate()
        cuadros = w.getnframes()
        crudo = w.readframes(cuadros)
    audio = np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, frecuencia, cuadros / frecuencia


def cargar_modelo(nombre: str):
    """Intenta GPU y cae a CPU sin mentir sobre cuál acabó usando.

    En Windows, CTranslate2 necesita cuBLAS y cuDNN para CUDA y no siempre
    están; si falla, un número de CPU declarado como tal vale más que un número
    de GPU que no se ejecutó.

    Importante: **no basta con que el modelo cargue**. Con las DLL de cuBLAS
    ausentes, `WhisperModel(device="cuda")` construye el objeto sin quejarse y
    revienta más tarde, en la primera inferencia. Por eso aquí se transcribe
    medio segundo de ruido antes de dar el dispositivo por bueno: una carga que
    no falla no demuestra nada.
    """
    import numpy as np
    from faster_whisper import WhisperModel

    ruido = (np.random.randn(8000) * 0.01).astype(np.float32)
    intentos = [("cuda", "float16"), ("cpu", "int8")]
    errores = []
    for dispositivo, precision in intentos:
        try:
            arranque = time.perf_counter()
            modelo = WhisperModel(nombre, device=dispositivo, compute_type=precision,
                                  download_root=str(Path(__file__).parent.parent / "models"))
            segmentos, _ = modelo.transcribe(ruido, language="es", beam_size=1)
            list(segmentos)  # el generador es perezoso: aquí se ejecuta de verdad
            carga_ms = (time.perf_counter() - arranque) * 1000
            return modelo, f"{dispositivo}/{precision}", carga_ms, errores
        except Exception as exc:  # noqa: BLE001
            errores.append(f"{dispositivo}/{precision}: {type(exc).__name__}: {exc}")
    raise RuntimeError("no se pudo cargar el modelo. " + " | ".join(errores))


def transcribir(modelo, audio) -> tuple[str, float]:
    arranque = time.perf_counter()
    segmentos, _info = modelo.transcribe(audio, language="es", beam_size=1,
                                         vad_filter=False)
    texto = "".join(s.text for s in segmentos)  # el generador es perezoso: aquí se ejecuta
    return texto.strip(), (time.perf_counter() - arranque) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", default="small",
                        help="tiny, base, small, medium, large-v3")
    parser.add_argument("--repeticiones", type=int, default=5,
                        help="pasadas por cada fichero de audio")
    parser.add_argument("--audio", default="muestra-*.wav",
                        help="patrón de ficheros dentro de artifacts/")
    args = parser.parse_args()

    rutas = sorted(ARTEFACTOS.glob(args.audio))
    if not rutas:
        print(f"No hay ficheros que encajen con {args.audio} en {ARTEFACTOS}. "
              "Graba primero: python probe/record_sample.py", file=sys.stderr)
        return 2

    muestras_audio = []
    for ruta in rutas:
        audio, frecuencia, duracion = leer_wav(ruta)
        muestras_audio.append((ruta, audio, frecuencia, duracion))
        print(f"Audio: {ruta.name}, {duracion:.1f} s a {frecuencia} Hz")

    print(f"\nCargando faster-whisper '{args.modelo}' (la primera vez lo descarga)...")
    try:
        modelo, dispositivo, carga_ms, errores = cargar_modelo(args.modelo)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"  cargado en {dispositivo}, {carga_ms:.0f} ms")
    for e in errores:
        print(f"  (descartado -> {e})")

    ficheros = ", ".join(r.name for r, *_ in muestras_audio)
    lote = Medicion(
        etapa="asr", implementacion=f"faster-whisper {args.modelo} ({dispositivo}) [lote]",
        que_mide="transcribir el clip completo, de principio a fin",
        notas=f"No es la latencia del turno; sirve para el factor de tiempo real. "
              f"Ficheros: {ficheros}.",
    )
    tail = Medicion(
        etapa="asr", implementacion=f"faster-whisper {args.modelo} ({dispositivo}) [cola 2s]",
        que_mide="transcribir los últimos 2 s de audio",
        notas=f"Aproximación a lo que queda por procesar cuando la persona calla. "
              f"No es un ASR en streaming de verdad. Ficheros: {ficheros}.",
    )

    # Una pasada de calentamiento sobre el primer clip: la primera
    # transcripción paga la reserva de memoria del dispositivo y no representa
    # el estado estacionario.
    transcribir(modelo, muestras_audio[0][1])

    factores = []
    for ruta, audio, frecuencia, duracion in muestras_audio:
        print(f"\n  {ruta.name}:")
        cola = audio[-int(2.0 * frecuencia):]
        del_fichero = []
        for i in range(1, args.repeticiones + 1):
            texto, ms_lote = transcribir(modelo, audio)
            _, ms_cola = transcribir(modelo, cola)
            lote.muestras_ms.append(ms_lote)
            tail.muestras_ms.append(ms_cola)
            del_fichero.append(ms_lote)
            print(f"    {i}/{args.repeticiones}: lote {ms_lote:.0f} ms, "
                  f"cola 2s {ms_cola:.0f} ms")
            if i == 1:
                # Se imprime para poder mirarla a ojo. La tasa de error frente
                # a la transcripción verdadera se mide aparte, no aquí: esta
                # sonda es de latencia.
                print(f"      transcripción: {texto}")
        factores.append((sum(del_fichero) / len(del_fichero)) / (duracion * 1000))

    factor = sum(factores) / len(factores)
    lote.notas += f" Factor de tiempo real medio: {factor:.2f} s de proceso por s de audio."

    print("\nResultado:")
    print(lote.linea())
    print(tail.linea())
    print(f"  factor de tiempo real: {factor:.2f}x "
          f"({'aguanta el habla en vivo' if factor < 1 else 'NO aguanta el habla en vivo'})")

    destino = guardar([lote, tail], f"whisper-{args.modelo}")
    print(f"\nGuardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
