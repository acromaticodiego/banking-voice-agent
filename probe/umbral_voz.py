r"""¿Cuánto por encima del ruido hay que estar para que cuente como voz?

`probe/sordera_asr.py` destapó que el umbral fijo de `app/vivo.py` —0,005 sobre
la media absoluta— no abre turno con la voz a la mitad (0 de 6 grabaciones) ni
con el audio pasado por una línea telefónica (1 de 6). El umbral no describía
una llamada: describía la habitación donde se escribió.

`app/deteccion_voz.py` lo sustituye por un umbral que sigue al ruido de la
propia llamada, y deja un número por decidir: **cuántas veces el suelo de ruido
hay que superar para que cuente como voz**. Esta sonda lo elige con datos.

Importante: la sonda no tiene su propia copia del detector. Importa el de
`app/deteccion_voz.py` y lo alimenta trozo a trozo igual que hace `app/vivo.py`,
incluidos los 600 ms de voz que hacen falta para abrir turno. Un barrido sobre
una reimplementación mide la reimplementación.

## El criterio, escrito ANTES de ver la tabla

  · **Duro: ningún clip de silencio puede abrir turno.** Un turno abierto por
    el ruido de la sala es el agente hablándole a nadie, gastando modelo y
    cuota, y —desde que el filtro de voz está puesto— transcribiendo una cadena
    vacía que dispara la pregunta "¿sigue ahí?" a alguien que nunca llamó.
  · **Dentro de eso, oír toda la voz que el sistema entiende.** "Entiende" no
    es opinable: es que la transcripción salga con menos del 15% de error, que
    es lo que mide `probe/sordera_asr.py`. Lo que el ASR no entiende da igual
    que se oiga.
  · Se elige **el factor más alto que cumple las dos cosas**, no el que más
    clips abre. Cuanto más alto, más lejos queda el ruido de la sala del
    umbral, y más aguanta una sala peor que esta.

Uso:
  .\.venv\Scripts\python.exe probe\umbral_voz.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import ARTEFACTOS, RAIZ, describe_host  # noqa: E402
from confianza_asr import banco_de_sala, coser, ventana_mas_callada  # noqa: E402
from linea_telefonica import a_linea_telefonica  # noqa: E402
from probe_whisper_local import leer_wav  # noqa: E402
from sordera_asr import DEGRADACIONES, degradar  # noqa: E402

sys.path.insert(0, str(RAIZ))
from app.deteccion_voz import DetectorDeVoz  # noqa: E402
from app.deteccion_voz import UMBRAL_FIJO_ANTERIOR as UMBRAL_VOZ  # noqa: E402
from app.vivo import FRECUENCIA, TROZO_MS  # noqa: E402

MUESTRAS_POR_TROZO = FRECUENCIA * TROZO_MS // 1000
VOZ_MINIMA_MS = 600          # el mismo de `app/vivo.py`
CALENTAMIENTO_S = 1.0        # ruido de sala antes de hablar, para calibrar

FACTORES = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)

# Degradaciones en las que el ASR entiende lo que se dice (menos del 15% de
# error con el filtro puesto, medido en sordera_asr.py el 2026-09-24). Son las
# que el detector TIENE que oír; las otras dos dan igual.
SE_ENTIENDEN = {"original", "mitad", "lejos", "muy-lejos", "ruido-20dB",
                "ruido-10dB", "ruido-5dB", "ruido-0dB", "lejos+ruido-10dB",
                "lejos+ruido-5dB", "original@tel", "lejos+ruido-10dB@tel"}


def abre_turno(audio: np.ndarray, detector: DetectorDeVoz | None,
               umbral_fijo: float | None = None) -> bool:
    """La misma cuenta que `Llamada.empujar`: 600 ms de voz abren turno.

    Con `umbral_fijo` se simula el sistema de antes, para tener línea base.
    """
    voz_ms = 0
    for i in range(0, len(audio) - MUESTRAS_POR_TROZO + 1, MUESTRAS_POR_TROZO):
        nivel = float(np.abs(audio[i:i + MUESTRAS_POR_TROZO]).mean())
        hay = nivel > umbral_fijo if detector is None else detector.hay_voz(nivel)
        if hay:
            voz_ms += TROZO_MS
            if voz_ms >= VOZ_MINIMA_MS:
                return True
        else:
            voz_ms = 0      # la racha se corta, igual que en vivo.py
    return False


def con_calentamiento(clip: np.ndarray, sala: np.ndarray) -> np.ndarray:
    """Un segundo de la sala de ese clip antes de que empiece a hablar.

    Sin esto la comparación sería tramposa en las dos direcciones: el detector
    llegaría al habla sin haber oído nunca el silencio, que es al revés de lo
    que pasa en una llamada —primero descuelgas y luego hablas—.
    """
    repetido = np.tile(sala, int(np.ceil(CALENTAMIENTO_S * FRECUENCIA / len(sala))))
    return np.concatenate([repetido[:int(CALENTAMIENTO_S * FRECUENCIA)], clip])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    rutas = [r for r in sorted(ARTEFACTOS.glob("muestra-*.wav"))
             if "telefono" not in r.stem]
    grabaciones = []
    for ruta in rutas:
        audio, frecuencia, _ = leer_wav(ruta)
        if frecuencia == FRECUENCIA:
            grabaciones.append((ruta.stem.replace("muestra-", ""), audio))

    # --- el material con voz: las grabaciones degradadas que el ASR entiende
    con_voz = []
    for nombre, factor, snr, telefono in DEGRADACIONES:
        if nombre not in SE_ENTIENDEN:
            continue
        for corto, audio in grabaciones:
            degradado = degradar(audio, factor, snr, telefono)
            sala = ventana_mas_callada(degradado, 1.0)
            con_voz.append((f"{corto}/{nombre}",
                            con_calentamiento(degradado, sala)))

    # --- el material sin voz: sala de verdad, y sala de una habitación peor
    tramos = banco_de_sala(rutas)
    generador = np.random.default_rng(20260924)
    sin_voz = []
    for duracion in (2.0, 4.0, 8.0):
        for i in range(4):
            sala = coser(tramos, duracion, generador)
            sin_voz.append((f"sala-{duracion:g}s-{i}", con_calentamiento(sala, sala)))
            tel = a_linea_telefonica(sala, FRECUENCIA).astype(np.float32)
            sin_voz.append((f"sala-{duracion:g}s-{i}@tel", con_calentamiento(tel, tel)))
            nivel = float(np.abs(sala).mean())
            for veces, etiqueta in ((1.2, "fuerte"), (4.0, "muy-fuerte")):
                fuerte = (sala * (UMBRAL_VOZ * veces / nivel)).astype(np.float32)
                sin_voz.append((f"{etiqueta}-{duracion:g}s-{i}",
                                con_calentamiento(fuerte, fuerte)))

    print(f"{len(con_voz)} clips con voz que el ASR entiende, "
          f"{len(sin_voz)} clips de silencio\n")

    # --- la línea base: el umbral fijo que había hasta hoy
    oye_fijo = sum(1 for _, a in con_voz if abre_turno(a, None, UMBRAL_VOZ))
    falsos_fijo = sum(1 for _, a in sin_voz if abre_turno(a, None, UMBRAL_VOZ))
    print(f"umbral fijo de {UMBRAL_VOZ} (el de hasta hoy):")
    print(f"  oye {oye_fijo}/{len(con_voz)} con voz, "
          f"abre {falsos_fijo}/{len(sin_voz)} silencios\n")

    print(f"  {'factor':>7} {'oye':>12} {'silencios':>12}   veredicto")
    tabla = {}
    for factor in FACTORES:
        sordos, falsos = [], []
        for nombre, audio in con_voz:
            if not abre_turno(audio, DetectorDeVoz(factor=factor)):
                sordos.append(nombre)
        for nombre, audio in sin_voz:
            if abre_turno(audio, DetectorDeVoz(factor=factor)):
                falsos.append(nombre)
        oye = len(con_voz) - len(sordos)
        tabla[factor] = {"oye": oye, "de": len(con_voz), "falsos": len(falsos),
                         "sordos": sordos, "falsos_clips": falsos}
        veredicto = ("cumple" if not falsos and not sordos
                     else "ABRE SILENCIOS" if falsos else f"sordo a {len(sordos)}")
        print(f"  {factor:>7.1f} {oye:>7}/{len(con_voz):<4} {len(falsos):>7}/"
              f"{len(sin_voz):<4}   {veredicto}")

    # --- la elección, con el criterio de arriba y no con el resultado
    cumplen = [f for f in FACTORES if not tabla[f]["falsos"] and not tabla[f]["sordos"]]
    print()
    if cumplen:
        elegido = max(cumplen)
        print(f"ELEGIDO: {elegido}. Es el más alto que oye todo lo que el ASR "
              f"entiende sin abrir ni un silencio.")
        print(f"  Cumplen también: {cumplen}. Se coge el mayor porque cuanto más "
              f"alto, más lejos queda\n  el ruido de una sala peor que esta.")
    else:
        elegido = None
        sin_falsos = [f for f in FACTORES if not tabla[f]["falsos"]]
        print("NINGÚN FACTOR CUMPLE LAS DOS COSAS. El criterio dice que mandan los "
              "silencios,\nasí que el candidato está entre los que no abren ninguno: "
              f"{sin_falsos}")
        for f in sin_falsos:
            print(f"  factor {f}: sordo a {tabla[f]['sordos']}")

    fecha = datetime.now(timezone.utc).astimezone()
    destino = ARTEFACTOS / f"umbral-voz-{fecha:%Y%m%d-%H%M%S}.json"
    destino.write_text(json.dumps({
        "fecha": fecha.isoformat(), "host": describe_host(),
        "criterio": "ningún silencio abre turno; dentro de eso, oír todo lo que "
                    "el ASR entiende; se elige el factor más alto que cumple",
        "umbral_fijo_anterior": UMBRAL_VOZ,
        "linea_base_fija": {"oye": oye_fijo, "de": len(con_voz),
                            "falsos": falsos_fijo, "silencios": len(sin_voz)},
        "elegido": elegido,
        "tabla": {str(k): v for k, v in tabla.items()},
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {destino.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
