r"""La otra cara del filtro de voz: ¿cuándo deja sordo al agente? (cero tokens)

`probe/confianza_asr.py` midió lo que el filtro arregla: 7 de 64 clips de
silencio dejan de transcribirse como frases. Esta sonda mide lo que el filtro
puede romper, que es un fallo peor.

**Contestarle a una habitación vacía es ridículo; no oír a alguien que sí está
hablando es colgarle.** El ADR 0008 lo dejó escrito como el flanco abierto de
su propia decisión: "aquí no se comió ninguno de 42 clips, pero con voz baja o
muy lejos del micrófono eso no está medido, y sería el fallo grave". Esto lo
mide, y se hace hoy y no cuando aparezca en una demo, porque mañana se quema
el conjunto reservado con este filtro dentro del sistema.

## Cómo se degrada el audio, y por qué así

De las grabaciones que ya hay, sin grabar nada nuevo:

  · **Atenuación** (×0,5 a ×0,05) — alguien que habla bajito, o que está lejos
    del micrófono. No es una simulación perfecta de la distancia, que además
    trae reverberación y no solo volumen, y hay que decirlo: es la mitad
    barata del problema.
  · **Ruido** a 20, 10, 5 y 0 dB de relación señal/ruido, con el ruido de la
    propia sala amplificado.
  · **Las dos cosas a la vez**, que es la llamada de verdad: alguien lejos del
    teléfono en una calle.
  · Y lo peor de todo **por línea telefónica**, que es como llegará.

## Las dos sorderas, que no son la misma

  1. **La de Whisper con el filtro puesto**: el audio llega y el filtro decide
     que ahí no hay voz. Se ve comparando lo que sale con filtro y sin él.
  2. **La del propio sistema, antes de Whisper**: `app/vivo.py` solo abre turno
     cuando la media absoluta del trozo pasa de `UMBRAL_VOZ` (0,005). Una voz
     atenuada no llega a ese umbral y **el turno no se abre siquiera**, así que
     no hay transcripción que filtrar. Esa sordera no la causa el filtro, ya
     estaba, y esta sonda la mide de paso porque es la que se encuentra antes.

De las seis grabaciones, tres tienen transcripción verdadera escrita. En esas
la comparación no es "con filtro salió menos texto" —que no dice si el texto
que falta era bueno— sino la tasa de error contra la verdad, que es la cifra
que el proyecto ya publica.

Uso:
  .\.venv\Scripts\python.exe probe\sordera_asr.py [--modelo small]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import ARTEFACTOS, RAIZ, describe_host  # noqa: E402
from linea_telefonica import a_linea_telefonica  # noqa: E402
from numeros_es import normalizar  # noqa: E402
from probe_wer import cifras, limpiar, tasa  # noqa: E402
from probe_whisper_local import cargar_modelo, leer_wav  # noqa: E402

sys.path.insert(0, str(RAIZ))
from app.deteccion_voz import UMBRAL_FIJO_ANTERIOR as UMBRAL_VOZ  # noqa: E402

FRECUENCIA = 16000

# nombre, factor de volumen, SNR en dB (None = sin añadir ruido), por teléfono
DEGRADACIONES = [
    ("original",            1.00, None, False),
    ("mitad",               0.50, None, False),
    ("lejos",               0.25, None, False),
    ("muy-lejos",           0.10, None, False),
    ("susurro",             0.05, None, False),
    ("ruido-20dB",          1.00, 20.0, False),
    ("ruido-10dB",          1.00, 10.0, False),
    ("ruido-5dB",           1.00, 5.0, False),
    ("ruido-0dB",           1.00, 0.0, False),
    ("lejos+ruido-10dB",    0.25, 10.0, False),
    ("lejos+ruido-5dB",     0.25, 5.0, False),
    ("original@tel",        1.00, None, True),
    ("lejos+ruido-10dB@tel", 0.25, 10.0, True),
    ("muy-lejos@tel",       0.10, None, True),
]


@dataclass
class Resultado:
    grabacion: str
    degradacion: str
    vad: bool
    nivel: float           # media absoluta: lo que mira el VAD de energía
    abre_turno: bool       # ¿lo dejaría pasar `app/vivo.py`?
    texto: str
    palabras: int
    wer_normalizado: float | None
    numeros_recuperados: str | None


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(audio, dtype=np.float64) ** 2)))


def ventana_mas_callada(audio: np.ndarray, ventana_s: float = 1.0) -> np.ndarray:
    n = int(ventana_s * FRECUENCIA)
    if len(audio) < n:
        return audio
    paso = int(0.25 * FRECUENCIA)
    mejor, minimo = audio[:n], None
    for i in range(0, len(audio) - n + 1, paso):
        energia = rms(audio[i:i + n])
        if minimo is None or energia < minimo:
            mejor, minimo = audio[i:i + n], energia
    return mejor


def degradar(audio: np.ndarray, factor: float, snr_db: float | None,
             telefono: bool) -> np.ndarray:
    """Primero el ruido, luego el volumen, y el teléfono al final.

    El orden no es casual: mezclar a una relación señal/ruido y *después*
    bajarlo todo mantiene esa relación y solo cambia el nivel, que es lo que
    pasa de verdad cuando alguien se aparta del micrófono. Al revés, atenuar
    antes de mezclar, cambiaría las dos cosas a la vez y no se sabría cuál
    rompió qué. Y el canal telefónico va el último porque es lo último que le
    pasa al audio antes de llegar.
    """
    salida = audio.astype(np.float64)
    if snr_db is not None:
        sala = ventana_mas_callada(audio)
        ruido = np.tile(sala, int(np.ceil(len(audio) / len(sala))))[:len(audio)]
        ruido = ruido.astype(np.float64)
        p_voz, p_ruido = float(np.mean(salida ** 2)), float(np.mean(ruido ** 2))
        if p_ruido > 0:
            salida = salida + ruido * np.sqrt(p_voz / (p_ruido * 10 ** (snr_db / 10)))
    pico = float(np.max(np.abs(salida)))
    if pico > 1.0:
        salida = salida / pico
    salida = (salida * factor).astype(np.float32)
    if telefono:
        salida = a_linea_telefonica(salida, FRECUENCIA).astype(np.float32)
    return salida


def transcribir(modelo, audio, vad: bool) -> str:
    segmentos, _ = modelo.transcribe(audio, language="es", beam_size=1,
                                     vad_filter=vad)
    return "".join(s.text for s in segmentos).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", default="small")
    args = parser.parse_args()

    grabaciones = []
    for ruta_json in sorted(ARTEFACTOS.glob("muestra-*.json")):
        datos = json.loads(ruta_json.read_text(encoding="utf-8"))
        wav = ARTEFACTOS / datos["fichero"]
        if not wav.exists():
            continue
        audio, frecuencia, _ = leer_wav(wav)
        if frecuencia != FRECUENCIA:
            continue
        grabaciones.append((wav.stem.replace("muestra-", ""), audio,
                            datos.get("transcripcion_verdadera")))

    con_verdad = sum(1 for _, _, v in grabaciones if v)
    print(f"{len(grabaciones)} grabaciones, {con_verdad} con transcripción "
          f"verdadera escrita")
    print(f"{len(DEGRADACIONES)} degradaciones x 2 modos = "
          f"{len(grabaciones) * len(DEGRADACIONES) * 2} transcripciones\n")

    print(f"Cargando faster-whisper '{args.modelo}'...")
    modelo, dispositivo, _, _ = cargar_modelo(args.modelo)
    print(f"  {dispositivo}\n")

    resultados: list[Resultado] = []
    for nombre, factor, snr, telefono in DEGRADACIONES:
        print(f"--- {nombre} " + "-" * (58 - len(nombre)))
        print(f"  {'grabación':<16} {'abre':<5} {'sin filtro':>30} {'con filtro':>30}")
        for corto, audio, verdad in grabaciones:
            degradado = degradar(audio, factor, snr, telefono)
            nivel = float(np.abs(degradado).mean())
            abre = nivel > UMBRAL_VOZ
            fila = []
            for vad in (False, True):
                texto = transcribir(modelo, degradado, vad)
                wer = numeros = None
                if verdad:
                    wer = round(tasa(normalizar(verdad), normalizar(texto))[0] * 100, 1)
                    esperados = cifras(verdad)
                    obtenidos = cifras(texto)
                    numeros = (f"{sum(1 for n in esperados if n in obtenidos)}"
                               f"/{len(esperados)}")
                resultados.append(Resultado(
                    grabacion=corto, degradacion=nombre, vad=vad, nivel=round(nivel, 5),
                    abre_turno=abre, texto=texto, palabras=len(limpiar(texto)),
                    wer_normalizado=wer, numeros_recuperados=numeros))
                marca = (f"{wer:5.1f}% {numeros}" if wer is not None
                         else f"{len(limpiar(texto)):3d} palabras")
                fila.append(f"{marca}  {texto[:14]!r}" if texto else f"{marca}  MUDO")
            print(f"  {corto:<16} {'sí' if abre else 'NO':<5} {fila[0]:>30} {fila[1]:>30}")
        print()

    # ------------------------------------------------------------- el veredicto
    print("=" * 78)
    print("SORDERA: habla que se pierde POR el filtro (el filtro calla y sin él se oía)")
    indice = {(r.grabacion, r.degradacion, r.vad): r for r in resultados}
    sorderas = []
    for (grabacion, degradacion, vad), r in indice.items():
        if not vad:
            continue
        sin = indice[(grabacion, degradacion, False)]
        if r.palabras == 0 and sin.palabras > 0:
            sorderas.append((grabacion, degradacion, sin.palabras))
    if not sorderas:
        print("  ninguna: no hay ni un caso en que el filtro callara algo que sin él sonara")
    for grabacion, degradacion, palabras in sorderas:
        print(f"  {grabacion:<16} {degradacion:<22} perdió {palabras} palabras")

    print("\n" + "=" * 78)
    print("PÉRDIDA DE PALABRAS con el filtro, cuando no es sordera total")
    perdidas = []
    for (grabacion, degradacion, vad), r in indice.items():
        if not vad or r.palabras == 0:
            continue
        sin = indice[(grabacion, degradacion, False)]
        if sin.palabras > r.palabras:
            perdidas.append((grabacion, degradacion, sin.palabras, r.palabras))
    if not perdidas:
        print("  ninguna")
    for grabacion, degradacion, antes, ahora in sorted(perdidas,
                                                       key=lambda x: x[2] - x[3],
                                                       reverse=True)[:12]:
        print(f"  {grabacion:<16} {degradacion:<22} {antes} -> {ahora} palabras")

    print("\n" + "=" * 78)
    print("LA CIFRA QUE DECIDE: tasa de error contra la verdad escrita (n=3 por fila)")
    print("  Comparar cuánto texto sale no vale: el filtro quita texto INVENTADO y")
    print("  eso también es 'perder palabras'. Contra la verdad no hay esa duda.")
    print(f"\n  {'degradación':<22} {'abre turno':<11} {'sin filtro':>12} {'con filtro':>12}")
    resumen = {}
    for nombre, *_ in DEGRADACIONES:
        fila = {}
        for vad in (False, True):
            wers = [r.wer_normalizado for r in resultados
                    if r.degradacion == nombre and r.vad is vad
                    and r.wer_normalizado is not None]
            fila["con" if vad else "sin"] = (round(sum(wers) / len(wers), 1)
                                             if wers else None)
        abre = [r.abre_turno for r in resultados if r.degradacion == nombre]
        fila["abre_turno"] = f"{sum(abre)}/{len(abre)}"
        resumen[nombre] = fila
        print(f"  {nombre:<22} {fila['abre_turno']:<11} "
              f"{fila['sin']:>11}% {fila['con']:>11}%")

    fecha = datetime.now(timezone.utc).astimezone()
    destino = ARTEFACTOS / f"sordera-asr-{fecha:%Y%m%d-%H%M%S}.json"
    destino.write_text(json.dumps({
        "fecha": fecha.isoformat(), "host": describe_host(), "modelo": args.modelo,
        "dispositivo": dispositivo, "umbral_voz_del_sistema": UMBRAL_VOZ,
        "degradaciones": [list(d) for d in DEGRADACIONES],
        "sorderas_por_el_filtro": [list(s) for s in sorderas],
        "resumen_wer": resumen,
        "resultados": [asdict(r) for r in resultados],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {destino.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
