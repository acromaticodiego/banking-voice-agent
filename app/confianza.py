"""Lo que el voz a texto sabe de sí mismo, y que hasta hoy se tiraba.

`faster-whisper` devuelve por cada segmento tres números además del texto
—`no_speech_prob`, `avg_logprob` y `compression_ratio`— y una probabilidad de
idioma en el `info`. La llamada del sistema era `segmentos, _ = transcribe(...)`
y de cada segmento solo se usaba `.text`: el modelo decía lo poco seguro que
estaba y nadie lo escuchaba.

Esto no decide nada. Resume esas señales para que queden escritas en el rastro
del turno, y la decisión de actuar sobre ellas está **deliberadamente
aplazada**. El motivo está medido y es el ADR 0008:

  · Sobre 64 clips sin voz de esta sala y este micrófono, un corte por
    `avg_logprob` cazaba 7 de 7 inventos... hasta que entraron seis clips de
    habla más, y bajó a 5 de 7; y al arreglar el material de silencio, que
    estaba mal construido, quedó en 6 de 16. Tres medidas, cada una peor, y
    ninguna por un error de medición: el umbral nunca había sido bueno, solo
    había visto poco.
  · `no_speech_prob` no separa: hay habla de verdad que llega a 0,78 y los
    inventos van de 0,50 a 0,83, o sea que los rangos se solapan casi enteros.
  · El invento más peligroso —repetir el final de la frase que sí se dijo—
    tiene `avg_logprob` -0,386, que es BUENO. Repetir lo que uno acaba de
    decir es lo más probable del mundo para un modelo de lenguaje, así que
    ningún umbral de confianza lo caza. Eso lo arregla el VAD, no la señal.

Lo que sí se hace con lo medido está en `app/vivo.py`: `vad_filter=True`. Y lo
que se guarda aquí es lo que permitirá decidir el umbral cuando haya varias
voces y varias salas, en vez de decidirlo con siete casos.
"""

from __future__ import annotations


def resumir(segmentos: list, prob_idioma: float | None = None) -> dict:
    """Las señales de un turno, en un diccionario que cabe en el rastro.

    Se guardan los extremos y no la media porque lo que delata a un turno
    inventado es su peor segmento, no su promedio: una frase de verdad con
    tres palabras de aire pegadas al final tiene buen promedio y un segmento
    pésimo, y es justo ese el que hay que poder ver después.

    `segmentos` es lo que devuelve faster-whisper, o cualquier cosa con esos
    atributos. Una lista vacía —que es lo normal cuando de verdad no habló
    nadie— devuelve el resumen con todo a `None` y `segmentos: 0`, que no es
    un error: es la respuesta.
    """
    if not isinstance(segmentos, (list, tuple)):
        # Se exige una secuencia a propósito. faster-whisper devuelve un
        # generador perezoso que se recorre UNA vez: si llegara aquí sin
        # materializar, quien lo consumiera primero se quedaría con todo y el
        # otro con nada, en silencio. Mejor una excepción que lo diga.
        raise TypeError(
            "resumir() espera una lista de segmentos ya materializada. "
            "El generador de faster-whisper se agota al recorrerlo, y "
            "compartirlo entre el texto y las señales deja vacío a uno de "
            "los dos sin dar ningún error.")
    if not segmentos:
        return {"segmentos": 0, "no_speech_max": None, "avg_logprob_min": None,
                "compresion_max": None, "prob_idioma": prob_idioma}
    return {
        "segmentos": len(segmentos),
        "no_speech_max": round(max(s.no_speech_prob for s in segmentos), 4),
        "avg_logprob_min": round(min(s.avg_logprob for s in segmentos), 4),
        "compresion_max": round(max(s.compression_ratio for s in segmentos), 3),
        "prob_idioma": round(prob_idioma, 4) if prob_idioma is not None else None,
    }
