r"""Sonda del fin de habla: ¿cuánto silencio hay que esperar antes de contestar?

Es la etapa que en el presupuesto del día 1 entró como suposición de 400 ms sin
medir, y es la que más manda: son 400 de 1096 ms. También es el parámetro que
más fácil se ajusta a ojo hasta que "suena bien", que es exactamente lo que no
se debe hacer.

El compromiso que se mide aquí tiene dos lados y van en direcciones opuestas:

  · Ventana corta  -> el agente contesta antes, pero **corta a la persona** en
    mitad de una frase. Una pausa de duda pasa por final de turno.
  · Ventana larga  -> nunca corta, pero se suma entera al presupuesto de cada
    turno y la conversación se siente lenta.

Así que se barre la ventana y se cuenta, para cada valor, cuántas veces parte
una frase que era una sola. La verdad de referencia es que **cada grabación
contiene una única intervención**: la persona lee una frase y calla. Si el
detector encuentra tres trozos de habla, ha cortado dos veces.

La grabación con titubeos es la que decide. Las otras dos son frases leídas de
corrido y cualquier ventana las aguanta; una calibración hecha solo con ellas
diría que 150 ms es suficiente, y en una llamada real sería falso.

Uso:  .\.venv\Scripts\python.exe probe\probe_vad.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import ARTEFACTOS, Medicion, guardar  # noqa: E402
from probe_whisper_local import leer_wav  # noqa: E402

VENTANAS_MS = [100, 150, 200, 250, 300, 400, 500, 700, 1000]


def segmentos_con(audio: np.ndarray, ventana_ms: int) -> tuple[list[dict], float]:
    """Trozos de habla que encuentra Silero con esa ventana de silencio."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opciones = VadOptions(min_silence_duration_ms=ventana_ms,
                          speech_pad_ms=0)
    arranque = time.perf_counter()
    trozos = get_speech_timestamps(audio, opciones, sampling_rate=16000)
    return trozos, (time.perf_counter() - arranque) * 1000


PAUSA_DE_LECTURA_S = 1.5


def pausas_de(audio: np.ndarray) -> list[float]:
    """Silencios que hay DENTRO de la intervención, en segundos.

    Se miden con la ventana más fina del barrido para no fundir pausas
    contiguas. Es el dato del que sale la ventana de fin de habla: cualquier
    ventana más corta que una pausa interna corta a la persona ahí.
    """
    trozos, _ = segmentos_con(audio, min(VENTANAS_MS))
    return [(b["start"] - a["end"]) / 16000 for a, b in zip(trozos, trozos[1:])]


def por_que_no_sirve(audio: np.ndarray, duracion: float) -> str | None:
    """Filtra las grabaciones con las que esta medición no se puede hacer.

    Las dos comprobaciones salen de dos grabaciones reales que colé como
    buenas y no lo eran:

      · Una tenía dos segundos de habla en diez: la frase se quedó a medias.
      · La otra hablaba hasta el último instante del fichero. Ahí no hay
        silencio final, luego no hay ningún fin de turno que detectar, y el
        detector "acertaba" porque no tenía nada que acertar.

    La segunda es la importante y la menos evidente: para medir cuánto tarda
    en notarse que alguien calló, hace falta que alguien calle **dentro** de
    la grabación.
    """
    trozos, _ = segmentos_con(audio, 300)
    if not trozos:
        return "el detector no encuentra habla: demasiado baja"

    habla = sum(t["end"] - t["start"] for t in trozos) / 16000
    if habla < 0.4 * duracion:
        return (f"solo {habla:.1f} s de habla en {duracion:.1f} s de clip: "
                "la frase se quedó a medias")

    cola_silencio = duracion - trozos[-1]["end"] / 16000
    minimo = max(VENTANAS_MS) / 1000
    if cola_silencio < minimo:
        return (f"habla hasta {cola_silencio * 1000:.0f} ms del final; hacen falta "
                f"al menos {minimo * 1000:.0f} ms de silencio después de callar, "
                "o no hay fin de turno que medir")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    # Por defecto solo las espontáneas. Las lecturas están grabadas para medir
    # la tasa de error de transcripción, no el fin de habla, y meterlas aquí
    # fue justamente lo que invalidó el primer barrido.
    parser.add_argument("--audio", default="muestra-libre-*.wav")
    args = parser.parse_args()

    rutas = sorted(ARTEFACTOS.glob(args.audio))
    if not rutas:
        print(f"No hay ficheros que encajen con {args.audio}.", file=sys.stderr)
        return 2

    clips, descartados = [], []
    for ruta in rutas:
        audio, frecuencia, duracion = leer_wav(ruta)
        if frecuencia != 16000:
            descartados.append((ruta.name, f"{frecuencia} Hz, se esperaban 16000"))
            continue
        motivo = por_que_no_sirve(audio, duracion)
        if motivo:
            descartados.append((ruta.name, motivo))
            continue
        clips.append((ruta.name, audio, duracion))

    if descartados:
        print("Grabaciones descartadas, y por qué:")
        for nombre, motivo in descartados:
            print(f"  {nombre}: {motivo}")
        print()
    if not clips:
        print("No queda ninguna grabación utilizable. Vuelve a grabar con "
              "probe/grabadora.py.", file=sys.stderr)
        return 2

    # Antes del barrido: ¿de qué tamaño son las pausas que hay dentro de cada
    # intervención? De ahí sale la ventana, y de ahí sale también si estas
    # grabaciones sirven para elegirla.
    print("Pausas dentro de cada intervención:")
    todas_las_pausas = []
    lectura = False
    for nombre, audio, _duracion in clips:
        pausas = pausas_de(audio)
        todas_las_pausas.extend(pausas)
        if pausas:
            largas = [p for p in pausas if p >= PAUSA_DE_LECTURA_S]
            lectura = lectura or bool(largas)
            print(f"  {nombre}: " + ", ".join(f"{p:.2f}" for p in sorted(pausas))
                  + f"  (máxima {max(pausas):.2f} s)")
        else:
            print(f"  {nombre}: ninguna, habla de corrido")
    print()

    if lectura:
        print("=" * 72)
        print("ESTA MEDICIÓN NO VALE, Y NO ES CULPA DEL DETECTOR.")
        print("=" * 72)
        print(f"Hay pausas de más de {PAUSA_DE_LECTURA_S:.1f} s dentro de lo que debería")
        print("ser una sola intervención. Eso no es titubear: es leer de una pantalla y")
        print("parar a buscar dónde sigue. Si una persona se calla tres segundos, dar el")
        print("turno por terminado es la decisión CORRECTA, así que contar eso como un")
        print("corte castiga al detector por acertar.")
        print()
        print("Con este audio no se puede elegir la ventana. Hace falta habla espontánea:")
        print("alguien contestando una pregunta con sus propias palabras, no leyendo.")
        print("Las pausas de quien habla de corrido son de otro tamaño, y son las que")
        print("de verdad va a ver el agente por teléfono.")
        print()
        print("El barrido sigue abajo para que se vea el dato, pero no se usa para")
        print("decidir nada.")
        print()

    print(f"Barriendo la ventana de silencio sobre {len(clips)} grabaciones.")
    print("Verdad de referencia: cada grabación es UNA sola intervención.\n")

    ancho = max(len(n) for n, _, _ in clips)
    cabecera = f"{'ventana':>9} | " + " | ".join(f"{n:^{max(ancho, 12)}}" for n, _, _ in clips)
    print(cabecera)
    print("-" * len(cabecera))

    coste = Medicion(
        etapa="vad", implementacion="silero (el que trae faster-whisper)",
        que_mide="cómputo de recorrer el clip entero buscando habla",
        notas="Se reparte entre todo el audio; por turno es una fracción. "
              "No es el retraso del fin de habla: ese es la ventana.",
    )

    sin_cortes = []
    mudos = set()
    for ventana in VENTANAS_MS:
        celdas = []
        cortes_totales = 0
        valida = True
        for nombre, audio, _duracion in clips:
            trozos, ms = segmentos_con(audio, ventana)
            coste.muestras_ms.append(ms)
            if not trozos:
                # Cero trozos NO es "no hay cortes": es que el detector no ha
                # oído hablar a nadie. Contarlo como éxito fue el primer error
                # de esta sonda y daba por buena una ventana de 100 ms sobre
                # grabaciones que estaban casi mudas.
                mudos.add(nombre)
                valida = False
                celdas.append(f"{'SIN HABLA':^{max(ancho, 12)}}")
                continue
            cortes = len(trozos) - 1
            cortes_totales += cortes
            marca = "ok" if cortes == 0 else f"CORTA x{cortes}"
            celdas.append(f"{marca:^{max(ancho, 12)}}")
        print(f"{ventana:>7} ms | " + " | ".join(celdas))
        if cortes_totales == 0 and valida:
            sin_cortes.append(ventana)

    print()
    if mudos:
        print("AVISO: el detector no encuentra habla en " + ", ".join(sorted(mudos)) + ".")
        print("Esas grabaciones no cuentan para la calibración: hay que repetirlas.")
        print()

    if lectura:
        print("Sin conclusión: el audio es de lectura, no de conversación "
              "(ver el aviso de arriba).")
    elif sin_cortes:
        print(f"La ventana más corta que no parte ninguna de las {len(clips)} "
              f"grabaciones es {min(sin_cortes)} ms.")
        print("Ese es el retraso de fin de habla que entra en el presupuesto, "
              "no los 400 ms supuestos.")
    else:
        print("NINGUNA ventana del barrido evita los cortes, y las pausas no son "
              "de lectura.")
        print("O el detector por silencio no basta para este habla —y entonces hace "
              "falta")
        print("decidir el fin de turno también por el contenido, no solo por el "
              "silencio—")
        print(f"o hay que subir por encima de {max(VENTANAS_MS)} ms y asumir el coste.")

    print()
    print("Coste de cómputo del detector:")
    print(coste.linea())
    print("  (sobre el clip entero; en streaming se paga repartido y no en el turno)")

    print("\nLo que esta medición NO demuestra:")
    print(f"  · Son {len(clips)} grabaciones de UNA sola persona, leyendo. Calibra, "
          "no valida.")
    print("  · Leer una frase escrita no es hablar por teléfono: en una llamada real")
    print("    las pausas de duda son más largas y más frecuentes.")
    print("  · La ventana elegida aquí es un punto de partida para afinar con")
    print("    conversaciones de verdad, no un valor final.")

    destino = guardar([coste], "vad")
    print(f"\nGuardado en {destino}")
    return 0 if sin_cortes else 1


if __name__ == "__main__":
    raise SystemExit(main())
