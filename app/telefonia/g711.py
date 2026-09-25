r"""µ-law de verdad: los bytes que viajan por una llamada telefónica (G.711).

Ojo con no confundir esto con `probe/linea_telefonica.py`. Allí se *simula la
pérdida* de µ-law en coma flotante, para medir cuánto degrada la transcripción.
Aquí se producen y se consumen **los bytes exactos** del formato G.711 µ-law,
que es lo que Twilio manda por el WebSocket y lo que espera de vuelta. Uno es
un modelo del canal; el otro es el canal.

## Por qué no se usa `audioop`

Porque desaparece. `audioop.lin2ulaw` hace justo esto y está en la biblioteca
estándar, pero quedó obsoleto y **se elimina en Python 3.13**: montar la
telefonía del proyecto encima sería construir sobre algo con fecha de caducidad
conocida.

Lo que sí se hace con él, mientras exista, es **comprobar que esta
implementación es idéntica a la suya, muestra por muestra, en los 65 536
valores posibles** (`app/prueba_telefonia.py`). Una implementación propia de un
formato estándar sin esa comparación es una forma cara de introducir un ruido
que nadie va a encontrar.

## Cómo funciona, en corto

µ-law comprime 14 bits de rango dinámico en 8, con más resolución cerca del
cero, que es donde está la voz. Cada byte lleva signo, un exponente de 3 bits y
una mantisa de 4, y va **invertido** (complemento a uno) por herencia de las
líneas telefónicas: así el silencio queda como 0xFF, y un cable cortado —que da
ceros— se distingue del silencio de verdad.

Las dos conversiones son tablas: 256 entradas para decodificar y 65 536 para
codificar. Se construyen una vez al importar y después todo es un `lookup`
vectorizado, que es lo que permite hacerlo a ritmo de llamada sin pensar en el
coste.
"""

from __future__ import annotations

import numpy as np

SESGO = 0x84          # 132: el sesgo del estándar, en la escala de 16 bits
TOPE = 32635          # el máximo representable en 16 bits; por encima se recorta

# Y los mismos dos en la escala de 14 bits, que es donde µ-law trabaja de
# verdad. No son adornos: usar los de 16 bits da un códec que difiere del
# estándar en 381 de 65 536 valores, y eso suena a mala línea, no a error.
SESGO_14 = SESGO >> 2     # 33
TOPE_14 = 8159
SILENCIO = 0xFF       # lo que vale un cero codificado, y lo que Twilio espera en el silencio


def _codificar_una(muestra: int) -> int:
    """La lógica del estándar, tal cual, para una sola muestra de 16 bits.

    Existe para construir la tabla y para poder leerla al lado del documento
    del que sale. El código que corre en una llamada es el `lookup`.

    **La primera versión de esto era razonable y estaba mal.** Trabajaba con
    los 16 bits enteros —sesgo 132, recorte 32635, desplazamiento de
    `exponente + 3`—, que es la descripción de µ-law que uno escribe de memoria
    y que parece equivalente. Difería de la implementación de referencia en
    **381 de los 65 536 valores posibles**, porque el estándar trabaja sobre
    **14 bits**: desplaza dos bits a la derecha ANTES de todo, y ese truncado
    cambia el escalón elegido justo en las fronteras entre segmentos.

    381 de 65 536 es medio por ciento. En una llamada eso no suena a error:
    suena a un poco de ruido, del que se le echa la culpa a la línea. Lo cazó
    la comparación con `audioop`, y es la razón de que esa comparación exista.
    """
    fin_de_segmento = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)

    valor = muestra >> 2                 # a 14 bits, como manda el estándar
    if valor < 0:
        valor = -valor
        mascara = 0x7F                   # el signo va en la máscara, invertida
    else:
        mascara = 0xFF
    if valor > TOPE_14:
        valor = TOPE_14
    valor += SESGO_14

    for segmento, fin in enumerate(fin_de_segmento):
        if valor <= fin:
            break
    else:
        return 0x7F ^ mascara

    codificado = (segmento << 4) | ((valor >> (segmento + 1)) & 0x0F)
    return codificado ^ mascara


def _decodificar_una(byte: int) -> int:
    byte = ~byte & 0xFF
    signo = byte & 0x80
    exponente = (byte >> 4) & 0x07
    mantisa = byte & 0x0F
    magnitud = ((mantisa << 3) + SESGO) << exponente
    magnitud -= SESGO
    return -magnitud if signo else magnitud


# Las tablas. Se pagan una vez, al importar.
TABLA_CODIFICAR = np.array(
    [_codificar_una(v) for v in range(-32768, 32768)], dtype=np.uint8)
TABLA_DECODIFICAR = np.array(
    [_decodificar_una(b) for b in range(256)], dtype=np.int16)


def de_pcm16(muestras: np.ndarray) -> bytes:
    """PCM de 16 bits a bytes µ-law."""
    enteros = np.asarray(muestras, dtype=np.int16).astype(np.int32)
    return TABLA_CODIFICAR[enteros + 32768].tobytes()


def a_pcm16(datos: bytes) -> np.ndarray:
    """Bytes µ-law a PCM de 16 bits."""
    return TABLA_DECODIFICAR[np.frombuffer(datos, dtype=np.uint8)]


def de_float(muestras: np.ndarray) -> bytes:
    """Audio normalizado en ±1 a bytes µ-law.

    El recorte es explícito: una muestra fuera de rango no se envuelve sin
    avisar —eso convierte un pico en un chasquido en el oído de quien llama—,
    se recorta.
    """
    recortado = np.clip(np.asarray(muestras, dtype=np.float32), -1.0, 1.0)
    return de_pcm16((recortado * 32767.0).astype(np.int16))


def a_float(datos: bytes) -> np.ndarray:
    """Bytes µ-law a audio normalizado en ±1, que es la escala del sistema.

    La escala importa y este proyecto ya se ha tropezado con ella: un umbral
    puesto en la escala equivocada no da un detector malo, da uno sordo.
    """
    return a_pcm16(datos).astype(np.float32) / 32768.0
