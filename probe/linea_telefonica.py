r"""Pasar el audio por lo que le hace una línea telefónica.

## Por qué hace falta

La tasa de error de transcripción del proyecto está medida sobre grabaciones de
un micrófono de portátil, en una habitación silenciosa, a 16 kHz y con todo el
espectro. Nada de eso llega por teléfono. Un número medido así no es
optimista: **es de otro problema**. Y el proyecto se presenta para un agente
que atiende llamadas.

Simular el canal es lo que más acerca ese número a la realidad por el menor
esfuerzo: no hace falta volver a grabar nada, ni una centralita, ni Twilio.
Las mismas grabaciones, con la verdad escrita que ya tienen, pasadas por el
canal.

## Qué le hace de verdad una línea telefónica

Tres cosas, y se aplican en este orden porque es el orden en que ocurren:

  1. **Recorta la banda a 300–3400 Hz.** Es la banda de voz de la telefonía
     desde los años 60. Por debajo de 300 se va el cuerpo de la voz; por
     encima de 3400 se van las fricativas —la /s/, la /f/, la /z/—, que en
     español son justo las que distinguen "seis" de "diez" o marcan el plural.
  2. **Muestrea a 8 kHz.** La mitad de lo que usa el modelo. Nyquist obliga a
     recortar antes de bajar, y por eso el filtro va primero: si no, lo de
     arriba de 4 kHz no desaparece, se refleja hacia abajo como ruido.
  3. **Cuantiza en µ-law de 8 bits (G.711).** Es el códec del que sale casi
     todo el audio de telefonía. No es una pérdida de volumen: es ruido de
     cuantización, más grosero en las partes flojas de la señal, que es donde
     viven las consonantes sordas.

Y después hay que **volver a 16 kHz**, porque es lo que el modelo espera. Eso
no recupera nada de lo perdido —remuestrear no inventa información— y es
exactamente lo que hace un sistema de verdad cuando le entra audio de una
llamada.

## Lo que esto NO es

No es una llamada. Falta la pérdida de paquetes, el jitter, el eco, la
compresión del móvil, el ruido de la calle y el altavoz del manos libres. Y
sigue siendo **un solo hablante** en una habitación callada: esto cambia el
canal, no la voz ni el ruido. Así que el número que sale es "la misma persona,
por teléfono", no "la tasa de error del sistema en producción".

  .\.venv\Scripts\python.exe probe\linea_telefonica.py      # se comprueba solo
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import signal

BANDA_BAJA = 300.0
BANDA_ALTA = 3400.0
FRECUENCIA_TELEFONO = 8000

# G.711 µ-law. El 255 es el número de escalones y el µ=255 es la constante de
# la norma; no son elecciones nuestras.
MU = 255.0


def _banda_de_voz(audio: np.ndarray, frecuencia: int) -> np.ndarray:
    """Recorta a 300–3400 Hz con un Butterworth de orden 6.

    En `sos` y no en coeficientes `b, a`: un IIR de este orden en forma
    directa se vuelve numéricamente inestable y el filtro empieza a sonar a
    cosas que no están en la señal. Con secciones de segundo orden no pasa.

    `sosfiltfilt` filtra en los dos sentidos, así que no desplaza la señal en
    el tiempo. Un desplazamiento no cambiaría la transcripción, pero sí
    ensuciaría cualquier medida de latencia hecha sobre este audio.
    """
    nyquist = frecuencia / 2
    sos = signal.butter(6, [BANDA_BAJA / nyquist, BANDA_ALTA / nyquist],
                        btype="band", output="sos")
    return signal.sosfiltfilt(sos, audio)


def _a_mu_law(audio: np.ndarray) -> np.ndarray:
    """Cuantiza a 8 bits en µ-law y vuelve. Lo que se pierde, se pierde.

    Los escalones van de -127 a 127 y NO de 0 a 255. La primera versión usaba
    `round((x + 1) * 127,5)`, que reparte los 256 escalones por todo el rango
    pero deja el cero entre dos: el silencio salía con un offset de 0,004, y
    un silencio que no es silencio vuelve sordo al detector de fin de habla
    —que es una trampa que este proyecto ya había documentado con las escalas
    del audio—. Lo cazó la comprobación de "el silencio sigue en silencio".

    Se pierde un escalón de los 256. A cambio, el cero es el cero.
    """
    audio = np.clip(audio, -1.0, 1.0)
    comprimido = np.sign(audio) * np.log1p(MU * np.abs(audio)) / np.log1p(MU)
    escalones = np.round(comprimido * 127.0)
    descomprimido = escalones / 127.0
    return (np.sign(descomprimido)
            * ((1.0 + MU) ** np.abs(descomprimido) - 1.0) / MU)


def a_linea_telefonica(audio: np.ndarray, frecuencia: int = 16000,
                       con_mu_law: bool = True) -> np.ndarray:
    """El audio como habría llegado por una línea telefónica.

    Entra y sale a la misma frecuencia —la que espera el modelo— pero por el
    camino pasa por 8 kHz de verdad: lo que se pierde ahí no vuelve.
    """
    audio = np.asarray(audio, dtype=np.float64)
    limitado = _banda_de_voz(audio, frecuencia)

    # A 8 kHz y de vuelta. `resample_poly` hace el filtrado de guarda que toca
    # en cada sentido; bajar tomando una muestra de cada dos reflejaría todo
    # lo que quedara por encima de 4 kHz.
    factor = frecuencia // FRECUENCIA_TELEFONO
    if factor < 1:
        raise ValueError(f"{frecuencia} Hz ya está por debajo de los 8 kHz "
                         f"de la telefonía")
    a_ocho = signal.resample_poly(limitado, 1, factor)
    if con_mu_law:
        a_ocho = _a_mu_law(a_ocho)
    devuelto = signal.resample_poly(a_ocho, factor, 1)

    # `resample_poly` puede devolver una muestra de más o de menos por el
    # redondeo del número de muestras. Se recorta o se rellena para que el
    # audio siga midiendo lo mismo y las medidas por segundo no se muevan.
    if len(devuelto) > len(audio):
        devuelto = devuelto[:len(audio)]
    elif len(devuelto) < len(audio):
        devuelto = np.pad(devuelto, (0, len(audio) - len(devuelto)))
    return devuelto.astype(np.float32)


# --------------------------------------------------------------- comprobación

def _energia_en(audio: np.ndarray, frecuencia: int,
                desde: float, hasta: float) -> float:
    """Energía de la señal entre dos frecuencias, en dB."""
    espectro = np.abs(np.fft.rfft(audio)) ** 2
    ejes = np.fft.rfftfreq(len(audio), 1 / frecuencia)
    dentro = (ejes >= desde) & (ejes < hasta)
    total = espectro[dentro].sum()
    return 10 * np.log10(total + 1e-20)


def convertir_wav(entrada: Path, salida: Path) -> None:
    """Deja en disco cómo suena una grabación pasada por el canal.

    Existe porque un filtro de audio es la clase de código que puede no estar
    haciendo nada y aprobar todas las pruebas numéricas que se le pongan. Con
    el fichero delante se oye en tres segundos, y además sirve para el vídeo:
    "esto es lo que el agente oye en una llamada".
    """
    import wave

    with wave.open(str(entrada), "rb") as origen:
        frecuencia = origen.getframerate()
        canales = origen.getnchannels()
        crudo = origen.readframes(origen.getnframes())
    # El audio del proyecto va normalizado en ±1, no en enteros de 16 bits:
    # es una de las trampas documentadas, y confundir las dos escalas no da un
    # filtro malo, da uno que no hace nada o uno que satura.
    audio = np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / 32768.0
    if canales > 1:
        audio = audio.reshape(-1, canales).mean(axis=1)

    pasado = a_linea_telefonica(audio, frecuencia)
    with wave.open(str(salida), "wb") as destino:
        destino.setnchannels(1)
        destino.setsampwidth(2)
        destino.setframerate(frecuencia)
        destino.writeframes(
            (np.clip(pasado, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
    print(f"{entrada.name} -> {salida.name}  ({frecuencia} Hz, "
          f"{len(audio) / frecuencia:.1f} s)")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", type=Path, default=None,
                        help="convierte esta grabación y sale")
    parser.add_argument("--salida", type=Path, default=None)
    args = parser.parse_args()

    if args.wav:
        salida = args.salida or args.wav.with_name(
            args.wav.stem + "-telefono.wav")
        convertir_wav(args.wav, salida)
        return 0

    fallos = 0

    def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
        nonlocal fallos
        if condicion:
            print(f"  ok  {nombre}   {detalle}")
        else:
            fallos += 1
            print(f"  MAL {nombre}   {detalle}")

    frecuencia = 16000
    duracion = 2.0
    t = np.arange(int(frecuencia * duracion)) / frecuencia

    # Un barrido de 50 a 7000 Hz: se ve de un golpe qué sobrevive y qué no.
    barrido = signal.chirp(t, f0=50, f1=7000, t1=duracion, method="linear")
    barrido *= 0.5
    # Y con los bordes desvanecidos. Sin esto, el salto de amplitud en la
    # primera y la última muestra es un impulso, y un impulso tiene energía en
    # TODAS las frecuencias: el transitorio del filtro en los bordes se colaba
    # en la banda de graves y hacía parecer que el rechazo era de 28 dB en vez
    # de 40. Se estaba midiendo el borde de la señal, no el filtro.
    desvanecido = int(0.05 * frecuencia)
    ventana = np.ones_like(barrido)
    rampa = 0.5 * (1 - np.cos(np.linspace(0, np.pi, desvanecido)))
    ventana[:desvanecido] = rampa
    ventana[-desvanecido:] = rampa[::-1]
    barrido *= ventana
    pasado = a_linea_telefonica(barrido, frecuencia)

    # Las bandas se miden CON MARGEN respecto a los cortes, y esto costó un
    # diagnóstico equivocado: midiendo 0-300 Hz el rechazo salía de solo 17 dB
    # y parecía que el filtro no filtraba. Lo que pasaba es que 0-300 incluye
    # la banda de transición, donde un Butterworth de orden 6 casi no atenúa
    # —a 290 Hz todavía deja pasar casi todo—, así que el número mezclaba
    # rechazo con transición. Un filtro se especifica dejando el hueco.
    print("Energía por banda, antes y después (dB):")
    bandas = [(0, 150), (500, 3000), (4500, 8000)]
    medidas = []
    for desde, hasta in bandas:
        antes = _energia_en(barrido, frecuencia, desde, hasta)
        despues = _energia_en(pasado, frecuencia, desde, hasta)
        medidas.append((desde, hasta, antes, despues))
        print(f"  {desde:>5}-{hasta:<5} Hz   {antes:8.1f} -> {despues:8.1f} "
              f"({despues - antes:+.1f})")

    print()
    _, _, antes_grave, despues_grave = medidas[0]
    _, _, antes_voz, despues_voz = medidas[1]
    _, _, antes_agudo, despues_agudo = medidas[2]

    # El recorte de banda se mide SIN µ-law, y no por conveniencia: el ruido
    # de cuantización de G.711 es de banda ancha y levanta el suelo también
    # fuera de la banda de voz. Eso es fiel a lo que hace una línea de verdad,
    # así que no se puede exigir a la vez rechazo profundo y µ-law puesto:
    # serían dos cosas distintas medidas con el mismo número.
    sin_mu = a_linea_telefonica(barrido, frecuencia, con_mu_law=False)
    grave_limpio = _energia_en(sin_mu, frecuencia, 0, 150)
    agudo_limpio = _energia_en(sin_mu, frecuencia, 4500, 8000)
    print(f"  (sin µ-law: graves {grave_limpio - antes_grave:+.1f} dB, "
          f"agudos {agudo_limpio - antes_agudo:+.1f} dB)\n")

    comprobar("lo de debajo de 150 Hz se va",
              grave_limpio - antes_grave < -30,
              f"{grave_limpio - antes_grave:+.1f} dB")
    comprobar("lo de encima de 4500 Hz se va",
              agudo_limpio - antes_agudo < -30,
              f"{agudo_limpio - antes_agudo:+.1f} dB")
    comprobar("la banda de voz se mantiene",
              abs(despues_voz - antes_voz) < 3,
              f"{despues_voz - antes_voz:+.1f} dB")
    # El ruido de µ-law se mide con un tono puro, y DENTRO de la banda. No
    # puede estar por encima de 4 kHz: se cuantiza a 8 kHz, así que su ruido
    # vive por debajo de Nyquist y el remuestreo de vuelta a 16 kHz recorta
    # ahí. Buscarlo en los agudos era buscarlo donde es imposible que esté.
    #
    # Con un tono de 1 kHz, la banda de 2 a 3,9 kHz debería estar casi vacía;
    # lo que aparezca ahí es cuantización.
    tono = 0.5 * np.sin(2 * np.pi * 1000 * t) * ventana
    tono_mu = a_linea_telefonica(tono, frecuencia)
    tono_limpio = a_linea_telefonica(tono, frecuencia, con_mu_law=False)
    suelo_mu = _energia_en(tono_mu, frecuencia, 2000, 3900)
    suelo_limpio = _energia_en(tono_limpio, frecuencia, 2000, 3900)
    print(f"  (tono de 1 kHz: suelo en 2-3,9 kHz {suelo_limpio:.1f} dB sin "
          f"µ-law, {suelo_mu:.1f} dB con µ-law)\n")
    comprobar("µ-law mete ruido de cuantización en la banda",
              suelo_mu > suelo_limpio + 10,
              f"{suelo_limpio:.1f} -> {suelo_mu:.1f} dB")

    # La cuantización tiene que notarse: si µ-law no hiciera nada, el paso
    # sobraría y estaríamos diciendo que simulamos algo que no simulamos.
    diferencia = float(np.sqrt(np.mean((pasado - sin_mu) ** 2)))
    comprobar("µ-law deja un residuo medible", diferencia > 1e-4,
              f"rms {diferencia:.2e}")

    comprobar("la duración no cambia", len(pasado) == len(barrido),
              f"{len(barrido)} -> {len(pasado)}")

    # Y sobre silencio no puede inventar nada: si lo hiciera, el detector de
    # fin de habla se dispararía con el propio filtro.
    silencio = np.zeros(int(frecuencia * 0.5))
    pico = float(np.max(np.abs(a_linea_telefonica(silencio, frecuencia))))
    comprobar("el silencio sigue en silencio", pico < 1e-6, f"pico {pico:.2e}")

    print(f"\n{'todo bien' if not fallos else str(fallos) + ' fallos'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
