r"""Mide el turno de punta a punta y compara con la suma de las etapas.

La pregunta que responde no es "cuánto tarda". Es **si el desglose que llevo
publicando explica todo el tiempo que pasa**. Si el cronómetro único ve más de
lo que suman las etapas, hay una espera que nadie está midiendo.

Uso:
  .\.venv\Scripts\python.exe -m app.medir_turno [--audio muestra-libre-datos.wav]
                                                [--repeticiones 3]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from pathlib import Path

import uvicorn

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "probe"))

from common import ARTEFACTOS, Medicion, cargar_env, guardar  # noqa: E402

from app.agent.loop import Agente  # noqa: E402
from app.pipeline import Tuberia, leer_wav  # noqa: E402
from app.tools.service import app as app_herramientas  # noqa: E402

PUERTO = 8125
BASE = f"http://127.0.0.1:{PUERTO}"

# Coste de la cola del ASR medido en probe/probe_whisper_local.py: lo que
# quedaría por transcribir al callarse la persona si el voz a texto fuese en
# streaming. Se usa SOLO para la estimación, y va etiquetado como tal.
COLA_ASR_MS = 162.2

# El presupuesto que se publicó en el README, compuesto con las sondas por
# separado. Cada cifra es el mejor caso de su etapa, medida aislada. Aquí se
# contrasta con lo que hace el turno completo corriendo de verdad.
PRESUPUESTO_PUBLICADO = {
    "fin de habla": 300.0,
    "voz a texto": 162.2,
    "agente": 325.2,     # era "modelo": primer contenido hablable de UNA llamada
    "texto a voz": 128.3,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", default="muestra-libre-datos.wav")
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--ventana-ms", type=int, default=300)
    args = parser.parse_args()

    ruta = ARTEFACTOS / args.audio
    if not ruta.exists():
        print(f"No existe {ruta}. Graba con probe/grabadora.py", file=sys.stderr)
        return 2
    audio = leer_wav(ruta)

    entorno = cargar_env()
    clave = entorno.get("GROQ_API_KEY", "").strip()
    if not clave:
        print("Falta GROQ_API_KEY en .env", file=sys.stderr)
        return 2
    modelo_llm = entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

    from groq import Groq
    from piper import PiperVoice

    from probe_whisper_local import cargar_modelo

    print("Levantando las herramientas...")
    servidor = uvicorn.Server(uvicorn.Config(app_herramientas, port=PUERTO,
                                             log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(50):
        if servidor.started:
            break
        time.sleep(0.1)

    print("Cargando voz a texto...")
    asr, dispositivo, _, _ = cargar_modelo("small")
    print(f"  {dispositivo}")
    print("Cargando texto a voz...")
    voz = PiperVoice.load(str(RAIZ / "voices" / "es_MX-claude-high.onnx"))

    groq = Groq(api_key=clave, max_retries=0)

    print(f"\nAudio: {ruta.name}, {len(audio) / 16000:.1f} s")
    print(f"Se alimenta en tiempo real, en trozos de 20 ms. Cada vuelta tarda "
          f"lo que dura el audio.\n")

    punta = Medicion(
        etapa="turno", implementacion=f"tubería completa ({dispositivo})",
        que_mide="desde el último trozo de audio con voz hasta el primer trozo "
                 "de audio reproducible",
    )
    por_etapa: dict[str, list[float]] = {}
    huecos: list[float] = []
    ultimo = None

    for vuelta in range(1, args.repeticiones + 1):
        # Agente nuevo en cada vuelta: la historia acumulada cambiaría el
        # tamaño del contexto y con él la latencia del modelo.
        agente = Agente(groq, modelo_llm, BASE)
        tuberia = Tuberia(asr, voz, agente, ventana_silencio_ms=args.ventana_ms)
        r = tuberia.turno(audio)
        ultimo = r

        punta.muestras_ms.append(r.punta_a_punta_ms)
        for e in r.etapas:
            por_etapa.setdefault(e.nombre, []).append(e.ms)
        huecos.append(r.sin_contabilizar_ms)

        print(f"  vuelta {vuelta}/{args.repeticiones}: "
              f"punta a punta {r.punta_a_punta_ms:.0f} ms, "
              f"suma de etapas {r.suma_etapas_ms:.0f} ms, "
              f"sin contabilizar {r.sin_contabilizar_ms:.0f} ms")

    servidor.should_exit = True
    hilo.join(timeout=5)

    print(f"\n  dijo     : {ultimo.dicho}")
    print(f"  contestó : {ultimo.contestado}")

    print("\nDESGLOSE (mediana de las vueltas)")
    print("=" * 66)
    for nombre, valores in por_etapa.items():
        detalle = next(e.detalle for e in ultimo.etapas if e.nombre == nombre)
        print(f"  {nombre:<16}{statistics.median(valores):>9.0f} ms   {detalle}")
    print("-" * 66)
    suma = sum(statistics.median(v) for v in por_etapa.values())
    medida = statistics.median(punta.muestras_ms)
    print(f"  {'suma de etapas':<16}{suma:>9.0f} ms")
    print(f"  {'punta a punta':<16}{medida:>9.0f} ms   UN SOLO CRONÓMETRO")
    print(f"  {'sin contabilizar':<16}{medida - suma:>9.0f} ms")

    print("\n  (el 'sin contabilizar' es ruido de medida por construcción: las")
    print("   etapas se cronometran pegadas y cubren todo el intervalo. La")
    print("   comprobación de verdad es la de abajo.)")

    # ESTA es la comparación que vale. El presupuesto publicado se compuso con
    # las sondas por separado, cada etapa en su mejor caso y aislada de las
    # demás. Aquí está el mismo turno corriendo de verdad.
    print("\n¿SE PARECE AL PRESUPUESTO PUBLICADO?")
    print("=" * 66)
    print(f"  {'etapa':<18}{'presupuesto':>13}{'de verdad':>12}")
    print("-" * 66)
    for nombre, publicado in PRESUPUESTO_PUBLICADO.items():
        real = statistics.median(por_etapa[nombre])
        print(f"  {nombre:<18}{publicado:>10.0f} ms{real:>9.0f} ms"
              + ("   <-- " + f"{real / publicado:.1f}x" if real > publicado * 1.3 else ""))
    print("-" * 66)
    total_publicado = sum(PRESUPUESTO_PUBLICADO.values())
    print(f"  {'TOTAL':<18}{total_publicado:>10.0f} ms{medida:>9.0f} ms")
    print(f"  {'objetivo':<18}{800:>10} ms")

    if medida > total_publicado * 1.3:
        print(f"\n  El turno de verdad tarda {medida / total_publicado:.1f} veces lo que")
        print("  decía el presupuesto. Las sondas medían cada etapa aislada y en su")
        print("  mejor caso; un turno encadena varias llamadas al modelo con una")
        print("  herramienta en medio, y eso ninguna sonda lo veía.")

    estimado = suma - statistics.median(por_etapa["voz a texto"]) + COLA_ASR_MS
    print(f"\nCon un voz a texto en streaming (ESTIMACIÓN, no medición):")
    print(f"  {estimado:.0f} ms, sustituyendo la transcripción entera "
          f"({statistics.median(por_etapa['voz a texto']):.0f} ms) por el coste")
    print(f"  de la cola medido aparte ({COLA_ASR_MS:.0f} ms).")

    punta.notas = (f"Audio {ruta.name}. Ventana de silencio {args.ventana_ms} ms. "
                   f"Suma de etapas {suma:.0f} ms, sin contabilizar {medida - suma:.0f} ms. "
                   f"El voz a texto transcribe la intervención entera, no en streaming.")
    etapas_med = [
        Medicion(etapa="turno", implementacion=f"etapa: {nombre}",
                 que_mide=next(e.detalle for e in ultimo.etapas if e.nombre == nombre),
                 muestras_ms=valores)
        for nombre, valores in por_etapa.items()
    ]
    destino = guardar([punta, *etapas_med], "turno")
    print(f"\nGuardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
