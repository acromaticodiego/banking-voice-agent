r"""¿Sabe el sistema cuándo NO ha oído bien? (sonda local, cero tokens)

El guardia del turno vacío (`app/agent/loop.py`) mira si la transcripción tiene
alguna letra o algún dígito. Con eso basta para el silencio limpio, y está
comprobado. Lo que no tapa, y quedó anotado como lo que falta, es esto:
**Whisper alucina sobre el silencio y devuelve "Gracias." o un trozo de
subtítulos.** Eso tiene letras, así que el guardia lo deja pasar, el modelo lo
recibe como si alguien hubiera hablado, y el agente contesta a nadie. Al
teléfono —donde el silencio es lo más común que hay: la persona se apartó, se
cortó, el micrófono está muteado— eso no es un caso raro.

Esta sonda no arregla nada. Mide dos cosas con las que decidir:

  1. **Cada cuánto pasa**, sobre silencio de verdad de este micrófono y esta
     sala, y si `vad_filter=True` (Silero, dentro de faster-whisper) lo tapa.
  2. **Si existe la señal** con la que verlo cuando pasa, porque hoy se tira a
     la basura: en `app/vivo.py` la llamada es `segmentos, _ = transcribe(...)`
     y de cada segmento solo se usa `.text`. faster-whisper devuelve además
     `no_speech_prob`, `avg_logprob` y `compression_ratio` por segmento, y la
     probabilidad del idioma en el `info` que se descarta con `_`.

## El criterio, escrito ANTES de ver los números

Un guardia que rechace habla de verdad deja al agente sordo, y colgarle a
alguien que sí estaba hablando es peor que contestarle a un silencio. Así que:

  · **El punto de corte no puede rechazar ni un solo clip con voz.** Esa es la
    restricción dura, no una preferencia.
  · Dentro de esa restricción, que cace todo el material sin voz que pueda.
  · Si ninguna señal separa sin tocar el habla, **la conclusión es que no
    separa**, y se dice. No se busca luego una combinación a medida de estos
    clips, que es como se fabrica un número que solo funciona el día que se
    midió.

## De dónde sale el silencio

No de una fila de ceros: de esta habitación. De cada grabación se sacan todos
los tramos de medio segundo cuya energía está muy por debajo de la del fichero,
y con ese banco se cosen clips de 1, 2, 4 y 8 segundos. La duración importa y
por eso hay cuatro: a Whisper se le dan cada vez más segundos de nada, que es
justo la situación en la que se le conoce la manía de inventar.

**Dónde puede fallar esta verdad, dicho antes de usarla:** "sin voz" lo decide
la energía, no un oído. Un tramo flojo podría llevar el final de una palabra o
una respiración, y entonces contaríamos como invento algo que sí se dijo. El
error va en la dirección incómoda —infla la cifra de alucinación en vez de
taparla—, y con `--guardar-clips` los WAV quedan en `artifacts/` para poder
escucharlos y desmentirlo.

## Y de paso, el coste

`vad_filter=True` va en la ruta crítica del turno, que ya se come su
presupuesto de 3000 ms, así que aquí se mide lo que cuesta en milisegundos y
no solo si funciona. Una solución que arregla la alucinación y añade 400 ms al
turno no es gratis y no se puede decidir sin el número.

Uso:
  .\.venv\Scripts\python.exe probe\confianza_asr.py [--modelo small] [--repeticiones 3]
  .\.venv\Scripts\python.exe probe\confianza_asr.py --guardar-clips
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import ARTEFACTOS, RAIZ, Medicion, describe_host, guardar, percentil  # noqa: E402
from linea_telefonica import a_linea_telefonica  # noqa: E402
from probe_whisper_local import cargar_modelo, leer_wav  # noqa: E402
from probe_wer import limpiar  # noqa: E402

sys.path.insert(0, str(RAIZ))
from app.vivo import UMBRAL_VOZ  # noqa: E402

FRECUENCIA = 16000
TRAMO_S = 0.5
DURACIONES_SALA_S = (1.0, 2.0, 4.0, 8.0)
CLIPS_POR_DURACION = 6
SNR_TAPADA_DB = 0.0

# Las colas de silencio que el sistema de verdad le pega al habla antes de
# transcribir. No son inventadas: son las ventanas de `app/vivo.py`. 300 ms es
# la ventana corta que cierra un turno normal; 1200 ms la larga a la que se
# pasa cuando la frase parece a medias; 3600 ms es esa larga con las dos
# reanudaciones que el sistema permite. El buffer se transcribe entero, así
# que esto es lo que Whisper recibe de verdad cada vez que alguien habla.
COLAS_S = (0.3, 1.2, 3.6)

# Una sala más ruidosa que esta. El VAD de energía de `app/vivo.py` solo abre
# turno por encima de `UMBRAL_VOZ`, y el ruido de esta habitación se queda muy
# por debajo; con este factor se pregunta qué pasaría en una sala, un manos
# libres o una calle donde el suelo de ruido sí lo supere, que es la condición
# en la que el silencio llegaría a Whisper sin que nadie haya hablado.
FACTOR_SALA_FUERTE = 1.2

# Un tramo cuenta como sala si su energía está por debajo de esta fracción de
# la energía del fichero entero. Conservador a propósito: con un umbral alto
# entrarían colas de palabras y la verdad de la sonda dejaría de ser verdad.
UMBRAL_SALA = 0.10


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(audio, dtype=np.float64) ** 2)))


@dataclass
class Clip:
    """Un trozo de audio con lo que sabemos de él ANTES de transcribirlo."""

    nombre: str
    audio: np.ndarray
    hay_voz: bool          # la verdad conocida, no lo que diga el modelo
    familia: str           # "habla", "sala", "sala-telefono", "sintetico", ...
    base: str | None = None   # de qué clip deriva, para comparar textos

    @property
    def duracion_s(self) -> float:
        return len(self.audio) / FRECUENCIA


@dataclass
class Lectura:
    """Lo que devolvió el modelo sobre un clip, con las señales que hoy se tiran."""

    clip: str
    familia: str
    hay_voz: bool
    vad: bool
    duracion_s: float
    rms: float
    nivel_vad: float       # media absoluta: lo que mira el VAD de energía en vivo
    base: str | None
    texto: str
    segmentos: int
    no_speech_max: float | None
    avg_logprob_min: float | None
    compresion_max: float | None
    prob_idioma: float
    ms: float

    @property
    def dijo_algo(self) -> bool:
        """Lo mismo que pregunta hoy el guardia del turno vacío."""
        return any(c.isalnum() for c in self.texto)


# --------------------------------------------------------------- el material

def banco_de_sala(rutas: list[Path]) -> list[np.ndarray]:
    """Todos los tramos de medio segundo que son ruido de fondo, de todas las
    grabaciones. Cosidos después, dan silencio largo que no se repite a sí
    mismo: un mismo tramo en bucle sería periódico, y la periodicidad es
    exactamente la clase de estructura que un modelo se inventa."""
    tramos: list[np.ndarray] = []
    n = int(TRAMO_S * FRECUENCIA)
    for ruta in rutas:
        audio, frecuencia, _ = leer_wav(ruta)
        if frecuencia != FRECUENCIA:
            continue
        umbral = rms(audio) * UMBRAL_SALA
        for i in range(0, len(audio) - n + 1, n):
            trozo = audio[i:i + n]
            if rms(trozo) < umbral:
                tramos.append(trozo.astype(np.float32))
    return tramos


def coser(tramos: list[np.ndarray], duracion_s: float,
          generador: np.random.Generator) -> np.ndarray:
    cuantos = int(np.ceil(duracion_s * FRECUENCIA / (TRAMO_S * FRECUENCIA)))
    elegidos = [tramos[i] for i in generador.integers(0, len(tramos), cuantos)]
    return np.concatenate(elegidos)[:int(duracion_s * FRECUENCIA)]


def ventana_mas_callada(audio: np.ndarray, ventana_s: float = 2.0) -> np.ndarray | None:
    """El tramo más callado de un clip concreto, para el ruido de su propia sala."""
    n = int(ventana_s * FRECUENCIA)
    if len(audio) < n:
        return None
    paso = max(1, int(0.25 * FRECUENCIA))
    mejor, minimo = None, None
    for i in range(0, len(audio) - n + 1, paso):
        trozo = audio[i:i + n]
        energia = rms(trozo)
        if minimo is None or energia < minimo:
            mejor, minimo = trozo, energia
    return mejor


def mezclar_a_snr(voz: np.ndarray, ruido: np.ndarray, snr_db: float) -> np.ndarray:
    """Voz + ruido de sala escalado hasta la relación señal/ruido pedida.

    El ruido es el de la propia habitación, amplificado. No es lo mismo que
    grabar en una calle —el espectro es el de esta sala, solo que más alto— y
    hay que contarlo así: es un sucedáneo para ver si la confianza se mueve,
    no una medición de robustez al ruido.
    """
    if len(ruido) < len(voz):
        ruido = np.tile(ruido, int(np.ceil(len(voz) / len(ruido))))
    ruido = ruido[:len(voz)].astype(np.float64)
    p_voz = float(np.mean(voz.astype(np.float64) ** 2))
    p_ruido = float(np.mean(ruido ** 2))
    if p_ruido <= 0:
        return voz
    factor = np.sqrt(p_voz / (p_ruido * (10 ** (snr_db / 10))))
    mezcla = voz.astype(np.float64) + factor * ruido
    pico = float(np.max(np.abs(mezcla)))
    if pico > 1.0:                      # que no recorte: el recorte es otro problema
        mezcla = mezcla / pico
    return mezcla.astype(np.float32)


def construir_clips(rutas: list[Path]) -> tuple[list[Clip], int]:
    """El material de la sonda, con su verdad pegada."""
    clips: list[Clip] = []

    for ruta in rutas:
        audio, frecuencia, _ = leer_wav(ruta)
        if frecuencia != FRECUENCIA:
            print(f"  (saltada {ruta.name}: {frecuencia} Hz, no 16 kHz)")
            continue
        corto = ruta.stem.replace("muestra-", "")
        clips.append(Clip(corto, audio, True, "habla"))
        clips.append(Clip(f"{corto}@tel",
                          a_linea_telefonica(audio, frecuencia).astype(np.float32),
                          True, "habla-telefono"))
        propia = ventana_mas_callada(audio)
        if propia is not None:
            clips.append(Clip(f"{corto}/tapada",
                              mezclar_a_snr(audio, propia, SNR_TAPADA_DB),
                              True, "habla-tapada"))

    tramos = banco_de_sala(rutas)
    generador = np.random.default_rng(20260924)
    if tramos:
        for duracion in DURACIONES_SALA_S:
            for i in range(CLIPS_POR_DURACION):
                sala = coser(tramos, duracion, generador)
                clips.append(Clip(f"sala-{duracion:g}s-{i}", sala, False, "sala"))
                clips.append(Clip(f"sala-{duracion:g}s-{i}@tel",
                                  a_linea_telefonica(sala, FRECUENCIA).astype(np.float32),
                                  False, "sala-telefono"))

        # La sala de una habitación más ruidosa: la única en la que el VAD de
        # energía abriría un turno sin que nadie haya hablado.
        for duracion in DURACIONES_SALA_S:
            for i in range(3):
                sala = coser(tramos, duracion, generador)
                nivel = float(np.abs(sala).mean())
                if nivel > 0:
                    sala = (sala * (UMBRAL_VOZ * FACTOR_SALA_FUERTE / nivel)).astype(np.float32)
                clips.append(Clip(f"fuerte-{duracion:g}s-{i}", sala, False, "sala-fuerte"))

        # Y lo que el sistema le pasa a Whisper DE VERDAD: el habla con la cola
        # de silencio que cerró el turno pegada detrás.
        for ruta in rutas:
            audio, frecuencia, _ = leer_wav(ruta)
            if frecuencia != FRECUENCIA:
                continue
            corto = ruta.stem.replace("muestra-", "")
            for cola_s in COLAS_S:
                cola = coser(tramos, cola_s, generador)
                clips.append(Clip(f"{corto}+{cola_s:g}s",
                                  np.concatenate([audio.astype(np.float32), cola]),
                                  True, "habla-con-cola", base=corto))

    for duracion in (2.0, 8.0):
        n = int(duracion * FRECUENCIA)
        clips.append(Clip(f"digital-{duracion:g}s", np.zeros(n, dtype=np.float32),
                          False, "sintetico"))
        clips.append(Clip(f"blanco-{duracion:g}s",
                          (generador.standard_normal(n) * 0.01).astype(np.float32),
                          False, "sintetico"))
    return clips, len(tramos)


def guardar_wav(clip: Clip) -> None:
    destino = ARTEFACTOS / f"clip-{clip.nombre.replace('/', '_').replace('@', '-')}.wav"
    datos = np.clip(clip.audio, -1.0, 1.0)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FRECUENCIA)
        w.writeframes((datos * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- la lectura

def leer(modelo, clip: Clip, vad: bool) -> Lectura:
    arranque = time.perf_counter()
    segmentos, info = modelo.transcribe(clip.audio, language="es", beam_size=1,
                                        vad_filter=vad)
    segs = list(segmentos)              # el generador es perezoso: aquí se ejecuta
    ms = (time.perf_counter() - arranque) * 1000
    texto = "".join(s.text for s in segs).strip()
    return Lectura(
        clip=clip.nombre, familia=clip.familia, hay_voz=clip.hay_voz, vad=vad,
        duracion_s=round(clip.duracion_s, 2), rms=round(rms(clip.audio), 5),
        nivel_vad=round(float(np.abs(clip.audio).mean()), 5), base=clip.base,
        texto=texto, segmentos=len(segs),
        no_speech_max=max((s.no_speech_prob for s in segs), default=None),
        avg_logprob_min=min((s.avg_logprob for s in segs), default=None),
        compresion_max=max((s.compression_ratio for s in segs), default=None),
        prob_idioma=info.language_probability, ms=ms,
    )


def texto_extra(lecturas: list[Lectura]) -> list[dict]:
    """¿Le pega Whisper palabras de más cuando el turno lleva su cola de silencio?

    Es el modo de fallo que sí puede darse hoy sin cambiar nada: el buffer de
    `app/vivo.py` se transcribe entero, cola incluida, así que la comparación
    es contra el mismo audio sin cola. Se mira el prefijo: si lo que sale
    empieza igual y sigue, lo de después es lo que se inventó al final; si ni
    siquiera empieza igual, se dice que el texto cambió, que es otra cosa y
    tampoco es buena.
    """
    indice = {(l.clip, l.vad): l for l in lecturas}
    salida = []
    for l in lecturas:
        if l.base is None:
            continue
        base = indice.get((l.base, l.vad))
        if base is None:
            continue
        palabras, palabras_base = limpiar(l.texto), limpiar(base.texto)
        mismo_principio = palabras[:len(palabras_base)] == palabras_base
        salida.append({
            "clip": l.clip, "vad": l.vad, "base": l.base,
            "palabras_base": len(palabras_base), "palabras": len(palabras),
            "mismo_principio": mismo_principio,
            "añadido": " ".join(palabras[len(palabras_base):]) if mismo_principio else None,
            "texto": l.texto,
        })
    return salida


def separa(lecturas: list[Lectura], senal: str, direccion: str) -> dict:
    """¿Separa esta señal el material sin voz del material con voz?

    `direccion` dice de qué lado está la sospecha: "alta" si valores altos
    significan "aquí no habló nadie" (no_speech_prob), "baja" si es al revés
    (avg_logprob). El punto de corte se elige con la restricción dura: no
    tocar ni un clip con voz. Solo se miran los clips que produjeron algún
    segmento, porque de los mudos no hay señal que mirar y ya los caza el
    guardia que existe.
    """
    con_voz = [getattr(l, senal) for l in lecturas
               if l.hay_voz and getattr(l, senal) is not None]
    sin_voz = [(l, getattr(l, senal)) for l in lecturas
               if not l.hay_voz and getattr(l, senal) is not None]
    if not con_voz or not sin_voz:
        return {"senal": senal, "direccion": direccion,
                "veredicto": f"sin material: {len(con_voz)} con voz, "
                             f"{len(sin_voz)} sin voz dieron segmentos"}

    if direccion == "alta":
        corte = max(con_voz)            # el corte más agresivo que no toca el habla
        cazados = [l.clip for l, v in sin_voz if v > corte]
    else:
        corte = min(con_voz)
        cazados = [l.clip for l, v in sin_voz if v < corte]

    alucinados = [l.clip for l, _ in sin_voz if l.dijo_algo]
    return {
        "senal": senal, "direccion": direccion, "corte": round(corte, 4),
        "con_voz": {"n": len(con_voz), "min": round(min(con_voz), 4),
                    "max": round(max(con_voz), 4)},
        "sin_voz": {"n": len(sin_voz), "min": round(min(v for _, v in sin_voz), 4),
                    "max": round(max(v for _, v in sin_voz), 4)},
        "sin_voz_que_hablan": alucinados,
        "cazados_de_los_que_hablan": [c for c in cazados if c in alucinados],
        "cazados": cazados,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", default="small")
    parser.add_argument("--repeticiones", type=int, default=3,
                        help="pasadas sobre los clips de habla, para el coste en ms")
    parser.add_argument("--audio", default="muestra-*.wav")
    parser.add_argument("--guardar-clips", action="store_true",
                        help="deja los WAV en artifacts/ para poder escucharlos")
    args = parser.parse_args()

    rutas = [r for r in sorted(ARTEFACTOS.glob(args.audio)) if "telefono" not in r.stem]
    if not rutas:
        print(f"No hay grabaciones en {ARTEFACTOS}.", file=sys.stderr)
        return 2
    print(f"Grabaciones de partida: {', '.join(r.stem for r in rutas)}")

    clips, tramos = construir_clips(rutas)
    con = sum(c.hay_voz for c in clips)
    print(f"Banco de sala: {tramos} tramos de {TRAMO_S} s por debajo del "
          f"{UMBRAL_SALA:.0%} de la energía de su fichero")
    print(f"{len(clips)} clips: {con} con voz, {len(clips) - con} sin voz\n")
    if args.guardar_clips:
        for clip in clips:
            guardar_wav(clip)
        print(f"  WAV escritos en {ARTEFACTOS} (los .wav no se versionan)\n")

    print(f"Cargando faster-whisper '{args.modelo}'...")
    modelo, dispositivo, carga_ms, _ = cargar_modelo(args.modelo)
    print(f"  cargado en {dispositivo}, {carga_ms:.0f} ms\n")

    lecturas: list[Lectura] = []
    for vad in (False, True):
        print(f"--- vad_filter={vad} " + "-" * 50)
        print(f"  {'clip':<20} {'voz':<4} {'s':>5} {'segs':>4} {'no_speech':>10} "
              f"{'avg_logp':>9} {'ms':>6}  texto")
        for clip in clips:
            lectura = leer(modelo, clip, vad)
            lecturas.append(lectura)
            if not lectura.dijo_algo and not clip.hay_voz:
                continue            # los mudos sin voz son el caso bueno: no se listan
            ns = (f"{lectura.no_speech_max:.3f}"
                  if lectura.no_speech_max is not None else "-")
            lp = (f"{lectura.avg_logprob_min:.3f}"
                  if lectura.avg_logprob_min is not None else "-")
            print(f"  {lectura.clip:<20} {'sí' if clip.hay_voz else 'NO':<4} "
                  f"{lectura.duracion_s:>5.1f} {lectura.segmentos:>4} {ns:>10} "
                  f"{lp:>9} {lectura.ms:>6.0f}  {lectura.texto[:44]}")
        print("  (los clips sin voz que salen mudos no se listan: son el caso bueno)\n")

    # ------------------------------------------------------------- el veredicto
    print("=" * 74)
    print("LO QUE HOY SE LE ESCAPA AL GUARDIA DEL TURNO VACÍO")
    resumen_alucinacion = {}
    for vad in (False, True):
        mudos = [l for l in lecturas if not l.hay_voz and l.vad is vad]
        hablan = [l for l in mudos if l.dijo_algo]
        resumen_alucinacion[f"vad={vad}"] = {
            "sin_voz": len(mudos), "producen_texto": len(hablan),
            "por_duracion": {
                f"{d:g}s": [sum(1 for l in hablan if abs(l.duracion_s - d) < 0.01),
                            sum(1 for l in mudos if abs(l.duracion_s - d) < 0.01)]
                for d in DURACIONES_SALA_S
            },
            "por_familia": {
                f: [sum(1 for l in hablan if l.familia == f),
                    sum(1 for l in mudos if l.familia == f)]
                for f in sorted({l.familia for l in mudos})
            },
        }
        print(f"  vad_filter={str(vad):<5} {len(hablan)} de {len(mudos)} clips sin voz "
              f"producen texto con letras")
        for clave, (cuantos, total) in resumen_alucinacion[f"vad={vad}"]["por_familia"].items():
            print(f"      por familia  {clave:<16} {cuantos}/{total}")
        for clave, (cuantos, total) in resumen_alucinacion[f"vad={vad}"]["por_duracion"].items():
            print(f"      por duración {clave:<16} {cuantos}/{total}")
        for l in hablan:
            print(f"      {l.clip:<20} {l.duracion_s:>4.1f} s -> {l.texto[:56]!r}")
        # Y la otra cara: habla que se queda sin transcribir.
        sordos = [l for l in lecturas if l.hay_voz and l.vad is vad and not l.dijo_algo]
        print(f"  {'':<18} {len(sordos)} de "
              f"{sum(1 for l in lecturas if l.hay_voz and l.vad is vad)} clips CON voz "
              f"se quedan sin transcribir")

    print("\n" + "=" * 74)
    print("EL HABLA CON SU COLA DE SILENCIO, que es lo que el sistema transcribe hoy")
    colas = texto_extra(lecturas)
    for vad in (False, True):
        delos = [c for c in colas if c["vad"] is vad]
        crecen = [c for c in delos if c["mismo_principio"] and c["añadido"]]
        cambian = [c for c in delos if not c["mismo_principio"]]
        print(f"  vad_filter={str(vad):<5} {len(crecen)} de {len(delos)} ganan palabras "
              f"al final; {len(cambian)} cambian de texto")
        for c in crecen:
            print(f"      {c['clip']:<20} +{c['palabras'] - c['palabras_base']:>2} -> "
                  f"{c['añadido'][:56]!r}")
        for c in cambian:
            print(f"      {c['clip']:<20} texto distinto ({c['palabras_base']} -> "
                  f"{c['palabras']} palabras)")

    analisis = {}
    for vad in (False, True):
        subconjunto = [l for l in lecturas if l.vad is vad]
        analisis[f"vad={vad}"] = {
            "no_speech_max": separa(subconjunto, "no_speech_max", "alta"),
            "avg_logprob_min": separa(subconjunto, "avg_logprob_min", "baja"),
        }

    print("\n" + "=" * 74)
    print("¿SEPARA ALGUNA SEÑAL? (corte = el más agresivo que no toca ningún clip con voz)")
    for etiqueta, bloque in analisis.items():
        print(f"  {etiqueta}")
        for senal, r in bloque.items():
            if "corte" not in r:
                print(f"    {senal:<18} {r['veredicto']}")
                continue
            print(f"    {senal:<18} corte {r['corte']:>8}   "
                  f"con voz [{r['con_voz']['min']}, {r['con_voz']['max']}] n={r['con_voz']['n']}"
                  f"   sin voz [{r['sin_voz']['min']}, {r['sin_voz']['max']}] "
                  f"n={r['sin_voz']['n']}")
            print(f"    {'':<18} caza {len(r['cazados'])}/{r['sin_voz']['n']} sin voz, "
                  f"y {len(r['cazados_de_los_que_hablan'])}/"
                  f"{len(r['sin_voz_que_hablan'])} de los que alucinan")

    # ------------------------------------------------ el coste del vad_filter
    print("\n" + "=" * 74)
    print(f"COSTE DEL vad_filter, {args.repeticiones} pasadas sobre los clips de habla")
    habla = [c for c in clips if c.familia == "habla"]
    mediciones = []
    for vad in (False, True):
        m = Medicion(
            etapa="asr",
            implementacion=f"faster-whisper {args.modelo} ({dispositivo}) vad={vad}",
            que_mide="transcribir el clip entero de habla, de llamada a resultado",
            notas=f"Clips: {', '.join(c.nombre for c in habla)}. "
                  f"Va en la ruta crítica del turno.",
        )
        for _ in range(args.repeticiones):
            for clip in habla:
                m.muestras_ms.append(leer(modelo, clip, vad).ms)
        mediciones.append(m)
        print(m.linea())
    delta = (percentil(mediciones[1].muestras_ms, 0.50)
             - percentil(mediciones[0].muestras_ms, 0.50))
    print(f"  diferencia de medianas: {delta:+.0f} ms sobre un presupuesto de "
          f"turno de 3000 ms")

    destino = guardar(mediciones, f"confianza-asr-coste-{args.modelo}")
    fecha = datetime.now(timezone.utc).astimezone()
    crudo = ARTEFACTOS / f"confianza-asr-{fecha:%Y%m%d-%H%M%S}.json"
    crudo.write_text(json.dumps({
        "fecha": fecha.isoformat(), "host": describe_host(), "modelo": args.modelo,
        "dispositivo": dispositivo, "snr_tapada_db": SNR_TAPADA_DB,
        "umbral_sala": UMBRAL_SALA, "tramos_de_sala": tramos,
        "criterio": "el corte no puede rechazar ningún clip con voz",
        "umbral_voz_del_sistema": UMBRAL_VOZ, "colas_s": list(COLAS_S),
        "alucinacion": resumen_alucinacion, "colas": colas,
        "lecturas": [asdict(l) for l in lecturas], "analisis": analisis,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {crudo.name} y {destino.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
