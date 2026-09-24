r"""¿Sabe el sistema cuándo NO ha oído bien? (sonda local, cero tokens)

El guardia del turno vacío (`app/agent/loop.py`) mira si la transcripción tiene
alguna letra o algún dígito. Con eso basta para el silencio limpio, y está
comprobado. Lo que no tapa, y quedó anotado como lo que falta, es esto:
**Whisper alucina sobre el silencio y devuelve "Gracias." o un trozo de
subtítulos.** Eso tiene letras, así que el guardia lo deja pasar, el modelo lo
recibe como si alguien hubiera hablado, y el agente contesta a nadie. Al
teléfono —donde el silencio es lo más común que hay: la persona se apartó, se
cortó, el micrófono está muteado— eso no es un caso raro.

Esta sonda no arregla nada. Mide si existe la señal con la que arreglarlo,
porque hoy se tira a la basura: en `app/vivo.py` la llamada es
`segmentos, _ = self.asr.transcribe(...)` y de cada segmento solo se usa
`.text`. faster-whisper devuelve además, por segmento, `no_speech_prob`,
`avg_logprob` y `compression_ratio`, y en el `info` que se descarta con `_` va
la probabilidad del idioma. La pregunta de la sonda es si alguno de esos
números separa "aquí no habló nadie" de "aquí habló alguien", sobre el audio
real de esta máquina y de este hablante.

## El criterio, escrito ANTES de ver los números

Un guardia que rechace habla de verdad deja al agente sordo, y colgarle a
alguien que sí estaba hablando es peor que contestarle a un silencio. Así que:

  · **El punto de corte no puede rechazar ni un solo clip con voz.** Esa es la
    restricción dura, no una preferencia.
  · Dentro de esa restricción, que cace todo el material sin voz que pueda.
  · Si ninguna señal separa sin tocar el habla, **la conclusión es que no
    separa**, y se dice. No se busca luego una combinación a medida de estos
    18 clips, que es como se fabrica un número que solo funciona el día que se
    midió.

## Qué material se mide

De verdad, del micrófono de esta máquina, no sintético:

  · `habla` — las grabaciones que ya existen en `artifacts/`.
  · `sala` — la ventana de 2 s más callada de cada una de esas grabaciones.
    Es el ruido de fondo real de la habitación y del micrófono: el silencio
    que de verdad le va a llegar al agente, no una fila de ceros.
  · las dos anteriores **por línea telefónica** (300–3400 Hz, 8 kHz, µ-law),
    que es como llegarán de verdad.
  · `habla-tapada` — el habla mezclada con ese mismo ruido de sala subido
    hasta 0 dB de relación señal/ruido. Sirve para saber si la señal mide
    "no se entiende" o solo "no hay nadie": son dos guardias distintos y el
    agente necesita saber cuál es cuál.
  · `silencio-digital` y `ruido-blanco`, sintéticos, como referencia de los
    extremos.

## Y de paso, el coste

`vad_filter=True` (Silero) le quita a Whisper el audio sin voz antes de
transcribir, y es la otra manera de tapar esto. Pero va en la ruta crítica del
turno, que ya se come su presupuesto de 3000 ms, así que aquí se mide lo que
cuesta en milisegundos y no solo si funciona. Una solución que arregla la
alucinación y añade 400 ms al turno no es gratis y no se puede decidir sin el
número.

Uso:
  .\.venv\Scripts\python.exe probe\confianza_asr.py [--modelo small] [--repeticiones 3]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import ARTEFACTOS, Medicion, describe_host, guardar, percentil  # noqa: E402
from linea_telefonica import a_linea_telefonica  # noqa: E402
from probe_whisper_local import cargar_modelo, leer_wav  # noqa: E402

VENTANA_SALA_S = 2.0
SNR_TAPADA_DB = 0.0


@dataclass
class Clip:
    """Un trozo de audio con lo que sabemos de él ANTES de transcribirlo."""

    nombre: str
    audio: np.ndarray
    hay_voz: bool          # la verdad conocida, no lo que diga el modelo
    familia: str           # "habla", "sala", "habla-telefono", ...

    @property
    def duracion_s(self) -> float:
        return len(self.audio) / 16000


@dataclass
class Lectura:
    """Lo que devolvió el modelo sobre un clip, con las señales que hoy se tiran."""

    clip: str
    familia: str
    hay_voz: bool
    vad: bool
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


def ventana_mas_callada(audio: np.ndarray, frecuencia: int,
                        ventana_s: float = VENTANA_SALA_S) -> np.ndarray | None:
    """El tramo más callado del clip: ruido de sala real, no ceros.

    Se busca por energía en ventanas solapadas. Devuelve None si el clip no da
    para una ventana entera, porque media ventana rellenada con algo no es el
    ruido de nadie.
    """
    n = int(ventana_s * frecuencia)
    if len(audio) < n:
        return None
    paso = max(1, int(0.25 * frecuencia))
    mejor, energia_min = None, None
    for i in range(0, len(audio) - n + 1, paso):
        trozo = audio[i:i + n]
        energia = float(np.sqrt(np.mean(trozo.astype(np.float64) ** 2)))
        if energia_min is None or energia < energia_min:
            mejor, energia_min = trozo, energia
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


def leer(modelo, clip: Clip, vad: bool) -> Lectura:
    import time
    arranque = time.perf_counter()
    segmentos, info = modelo.transcribe(clip.audio, language="es", beam_size=1,
                                        vad_filter=vad)
    segs = list(segmentos)              # el generador es perezoso: aquí se ejecuta
    ms = (time.perf_counter() - arranque) * 1000
    texto = "".join(s.text for s in segs).strip()
    return Lectura(
        clip=clip.nombre, familia=clip.familia, hay_voz=clip.hay_voz, vad=vad,
        texto=texto, segmentos=len(segs),
        no_speech_max=max((s.no_speech_prob for s in segs), default=None),
        avg_logprob_min=min((s.avg_logprob for s in segs), default=None),
        compresion_max=max((s.compression_ratio for s in segs), default=None),
        prob_idioma=info.language_probability, ms=ms,
    )


def construir_clips(rutas: list[Path]) -> list[Clip]:
    """El material de la sonda, con su verdad pegada."""
    clips: list[Clip] = []
    salas: list[np.ndarray] = []
    for ruta in rutas:
        audio, frecuencia, _ = leer_wav(ruta)
        if frecuencia != 16000:
            print(f"  (saltado {ruta.name}: {frecuencia} Hz, no 16 kHz)")
            continue
        corto = ruta.stem.replace("muestra-", "")
        clips.append(Clip(f"{corto}", audio, True, "habla"))
        clips.append(Clip(f"{corto}@tel", a_linea_telefonica(audio, frecuencia).astype(np.float32),
                          True, "habla-telefono"))
        sala = ventana_mas_callada(audio, frecuencia)
        if sala is None:
            continue
        salas.append(sala)
        clips.append(Clip(f"{corto}/sala", sala, False, "sala"))
        clips.append(Clip(f"{corto}/sala@tel",
                          a_linea_telefonica(sala, frecuencia).astype(np.float32),
                          False, "sala-telefono"))
        clips.append(Clip(f"{corto}/tapada",
                          mezclar_a_snr(audio, sala, SNR_TAPADA_DB), True, "habla-tapada"))

    clips.append(Clip("silencio-digital", np.zeros(int(2.0 * 16000), dtype=np.float32),
                      False, "sintetico"))
    generador = np.random.default_rng(20260924)
    clips.append(Clip("ruido-blanco",
                      (generador.standard_normal(int(2.0 * 16000)) * 0.01).astype(np.float32),
                      False, "sintetico"))
    return clips


def separa(lecturas: list[Lectura], senal: str, direccion: str) -> dict:
    """¿Separa esta señal el material sin voz del material con voz?

    `direccion` dice de qué lado está la sospecha: "alta" si valores altos
    significan "aquí no habló nadie" (no_speech_prob), "baja" si es al revés
    (avg_logprob). El punto de corte se elige con la restricción dura: no
    tocar ni un clip con voz. Lo que se devuelve incluye el solapamiento
    aunque sea malo, porque esa es la respuesta interesante.
    """
    con_voz = [getattr(l, senal) for l in lecturas if l.hay_voz and getattr(l, senal) is not None]
    sin_voz = [(l, getattr(l, senal)) for l in lecturas
               if not l.hay_voz and getattr(l, senal) is not None]
    if not con_voz or not sin_voz:
        return {"senal": senal, "veredicto": "sin material suficiente"}

    if direccion == "alta":
        # El corte más agresivo que no toca ningún clip con voz.
        corte = max(con_voz)
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
    args = parser.parse_args()

    rutas = [r for r in sorted(ARTEFACTOS.glob(args.audio)) if "telefono" not in r.stem]
    if not rutas:
        print(f"No hay grabaciones en {ARTEFACTOS}.", file=sys.stderr)
        return 2
    print(f"Grabaciones de partida: {', '.join(r.stem for r in rutas)}\n")

    clips = construir_clips(rutas)
    con, sin = sum(c.hay_voz for c in clips), sum(not c.hay_voz for c in clips)
    print(f"{len(clips)} clips: {con} con voz, {sin} sin voz\n")

    print(f"Cargando faster-whisper '{args.modelo}'...")
    modelo, dispositivo, carga_ms, _ = cargar_modelo(args.modelo)
    print(f"  cargado en {dispositivo}, {carga_ms:.0f} ms\n")

    lecturas: list[Lectura] = []
    for vad in (False, True):
        print(f"--- vad_filter={vad} " + "-" * 52)
        print(f"  {'clip':<22} {'voz':<4} {'segs':>4} {'no_speech':>10} "
              f"{'avg_logp':>9} {'ms':>6}  texto")
        for clip in clips:
            lectura = leer(modelo, clip, vad)
            lecturas.append(lectura)
            ns = f"{lectura.no_speech_max:.3f}" if lectura.no_speech_max is not None else "   -"
            lp = f"{lectura.avg_logprob_min:.3f}" if lectura.avg_logprob_min is not None else "   -"
            print(f"  {lectura.clip:<22} {'sí' if clip.hay_voz else 'NO':<4} "
                  f"{lectura.segmentos:>4} {ns:>10} {lp:>9} {lectura.ms:>6.0f}  "
                  f"{lectura.texto[:52]}")
        print()

    # ------------------------------------------------------------- el veredicto
    print("=" * 74)
    print("LO QUE HOY SE LE ESCAPA AL GUARDIA DEL TURNO VACÍO")
    for vad in (False, True):
        mudos = [l for l in lecturas if not l.hay_voz and l.vad is vad]
        hablan = [l for l in mudos if l.dijo_algo]
        print(f"  vad_filter={str(vad):<5} {len(hablan)} de {len(mudos)} clips sin voz "
              f"producen texto con letras")
        for l in hablan:
            print(f"      {l.clip:<22} -> {l.texto[:60]!r}")

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
                  f"con voz [{r['con_voz']['min']}, {r['con_voz']['max']}]   "
                  f"sin voz [{r['sin_voz']['min']}, {r['sin_voz']['max']}]")
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
    delta = percentil(mediciones[1].muestras_ms, 0.50) - percentil(mediciones[0].muestras_ms, 0.50)
    print(f"  diferencia de medianas: {delta:+.0f} ms sobre un presupuesto de turno de 3000 ms")

    destino = guardar(mediciones, f"confianza-asr-coste-{args.modelo}")
    fecha = datetime.now(timezone.utc).astimezone()
    crudo = ARTEFACTOS / f"confianza-asr-{fecha:%Y%m%d-%H%M%S}.json"
    crudo.write_text(json.dumps({
        "fecha": fecha.isoformat(), "host": describe_host(), "modelo": args.modelo,
        "dispositivo": dispositivo, "snr_tapada_db": SNR_TAPADA_DB,
        "criterio": "el corte no puede rechazar ningún clip con voz",
        "lecturas": [asdict(l) for l in lecturas], "analisis": analisis,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {crudo.name} y {destino.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
