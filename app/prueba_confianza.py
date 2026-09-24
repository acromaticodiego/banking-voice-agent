r"""Que el filtro de voz siga puesto, y que lo que el ASR sabe de sí mismo se anote.

Lo que de verdad protege esta prueba no es `resumir`, que es aritmética de tres
líneas: es que **nadie quite `vad_filter=True` de la ruta del turno sin
enterarse**. Por eso el ASR de mentira no comprueba el argumento y devuelve un
resultado distinto: revienta. Si alguien lo quita —o escribe otra llamada a
`transcribe` en otro sitio—, esto no falla por un texto discutible, falla con
una excepción que dice exactamente qué falta.

Y eso importa porque el filtro parece prescindible: quitarlo no rompe ninguna
demo, no cambia ningún texto en una sala callada y ahorra 24 ms. Lo que hace
es que el sistema deje de inventarse turnos que nadie dijo, y eso solo se ve
en una sala con ruido o en una cola de silencio larga. Un guardia cuyo efecto
no se nota es justo el que alguien quita por limpieza.

No gasta cuota ni necesita GPU: el ASR, la voz y el agente son de mentira.

  .\.venv\Scripts\python.exe -m app.prueba_confianza
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.confianza import resumir
from app.vivo import FRECUENCIA, Llamada

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}")
    else:
        fallos += 1
        print(f"    FALLA  {nombre}" + (f" -> {detalle}" if detalle else ""))


# ------------------------------------------------------------------- dobles

@dataclass
class SegmentoFalso:
    text: str
    no_speech_prob: float
    avg_logprob: float
    compression_ratio: float


class InfoFalsa:
    language_probability = 0.98765


class ASRQueExigeElFiltro:
    """Transcribe, pero solo si le piden el filtro de voz. Si no, revienta."""

    def __init__(self, segmentos: list[SegmentoFalso]) -> None:
        self.segmentos = segmentos
        self.llamadas = 0

    def transcribe(self, audio, **kwargs):
        self.llamadas += 1
        if kwargs.get("vad_filter") is not True:
            raise AssertionError(
                "transcribe() sin vad_filter=True. Sin ese filtro Whisper se "
                "inventa turnos sobre el silencio: medido el 2026-09-24, 7 de "
                "64 clips de sala real producen texto. ADR 0008.")
        # El generador perezoso de verdad se consume una sola vez: si el
        # sistema no lo materializa, el texto sale vacío y la prueba lo caza.
        return iter(self.segmentos), InfoFalsa()


@dataclass
class TrozoDeVoz:
    audio_int16_bytes: bytes = b"\x00\x00"
    sample_rate: int = 22050


class VozFalsa:
    def synthesize(self, texto: str):
        return [TrozoDeVoz()]


@dataclass
class TurnoFalso:
    texto: str = "De acuerdo."
    rastro: list = field(default_factory=list)


class AgenteFalso:
    def __init__(self) -> None:
        self.dichos = []

    def turno(self, dicho, al_hablar=None, **kwargs):
        self.dichos.append(dicho)
        if al_hablar:
            al_hablar("De acuerdo.", "respuesta")
        return TurnoFalso()


def llamada_con(segmentos):
    asr = ASRQueExigeElFiltro(segmentos)
    agente = AgenteFalso()
    return Llamada(asr, VozFalsa(), agente), asr, agente


def empujar_un_turno(llamada: Llamada):
    """Voz suficiente para abrir turno y silencio suficiente para cerrarlo."""
    generador = np.random.default_rng(7)
    voz = (generador.standard_normal(int(0.8 * FRECUENCIA)) * 0.05).astype(np.float32)
    silencio = np.zeros(int(0.5 * FRECUENCIA), dtype=np.float32)
    llamada.empujar(voz)
    return llamada.empujar(silencio)


# ------------------------------------------------------------------ pruebas

def prueba_resumir_sin_segmentos() -> None:
    print("  un turno del que no salió ningún segmento")
    r = resumir([], 0.5)
    comprobar("dice que hubo cero segmentos", r["segmentos"] == 0, str(r))
    comprobar("las señales van a None y no a cero",
              r["no_speech_max"] is None and r["avg_logprob_min"] is None,
              "un cero aquí se leería como 'muy seguro', que es lo contrario")


def prueba_resumir_toma_los_extremos() -> None:
    print("  el peor segmento manda, no el promedio")
    segmentos = [
        SegmentoFalso("Mi cédula es 70234567.", 0.02, -0.25, 1.20),
        SegmentoFalso(" Gracias por ver el vídeo.", 0.93, -1.80, 0.64),
    ]
    r = resumir(segmentos, 0.99)
    comprobar("no_speech es el máximo", r["no_speech_max"] == 0.93, str(r))
    comprobar("avg_logprob es el mínimo", r["avg_logprob_min"] == -1.8, str(r))
    comprobar("compresión es el máximo", r["compresion_max"] == 1.2, str(r))
    comprobar("el promedio habría tapado el segmento malo",
              r["avg_logprob_min"] < (-0.25 + -1.80) / 2,
              "con la media, -1.02: dentro del rango del habla normal")


def prueba_el_turno_pide_el_filtro() -> None:
    print("  la ruta del turno pide vad_filter=True")
    llamada, asr, _ = llamada_con([SegmentoFalso("Buenas tardes.", 0.1, -0.3, 1.1)])
    try:
        avisos = empujar_un_turno(llamada)
    except AssertionError as exc:
        comprobar("transcribe con el filtro puesto", False, str(exc))
        return
    comprobar("transcribe con el filtro puesto", asr.llamadas == 1)
    oido = [a for a in avisos if a.tipo == "oido"]
    comprobar("el turno llegó a cerrarse", len(oido) == 1, f"avisos: {avisos}")


def prueba_sin_filtro_revienta() -> None:
    """La prueba de la prueba: quitar el filtro tiene que doler."""
    print("  y si alguien quita el filtro, se entera")
    llamada, asr, _ = llamada_con([SegmentoFalso("Buenas tardes.", 0.1, -0.3, 1.1)])

    def transcribe_sin_filtro(audio, **kwargs):
        kwargs.pop("vad_filter", None)
        return ASRQueExigeElFiltro.transcribe(asr, audio, **kwargs)

    llamada.asr.transcribe = transcribe_sin_filtro
    try:
        empujar_un_turno(llamada)
        comprobar("quitar el filtro revienta", False,
                  "pasó sin quejarse: el guardia no guarda nada")
    except AssertionError as exc:
        comprobar("quitar el filtro revienta", "vad_filter" in str(exc))


def prueba_las_senales_quedan_escritas() -> None:
    print("  las señales del ASR quedan en el aviso del turno")
    segmentos = [SegmentoFalso("Mi cédula es 70234567.", 0.02, -0.25, 1.20),
                 SegmentoFalso(" Gracias por ver el vídeo.", 0.93, -1.80, 0.64)]
    llamada, _, agente = llamada_con(segmentos)
    avisos = empujar_un_turno(llamada)
    oido = [a for a in avisos if a.tipo == "oido"]
    comprobar("hay un aviso de lo oído", len(oido) == 1, f"avisos: {avisos}")
    if not oido:
        return
    confianza = oido[0].datos.get("confianza")
    comprobar("lleva la confianza pegada", isinstance(confianza, dict), str(oido[0].datos))
    comprobar("y es la del peor segmento",
              confianza and confianza["no_speech_max"] == 0.93, str(confianza))
    comprobar("la probabilidad de idioma viene del info",
              confianza and confianza["prob_idioma"] == 0.9877, str(confianza))
    comprobar("el texto de los dos segmentos llega entero al agente",
              agente.dichos == ["Mi cédula es 70234567. Gracias por ver el vídeo."],
              f"el agente oyó {agente.dichos}")


def prueba_el_generador_se_materializa() -> None:
    """faster-whisper devuelve un generador perezoso y solo se recorre una vez.

    Si el sistema lo recorriera para el texto y otra vez para las señales, lo
    segundo saldría vacío sin que nadie se queje. Aquí el doble devuelve un
    `iter(...)` de verdad, así que esa forma de fallar se caza sola.
    """
    print("  el generador perezoso no se consume dos veces")
    llamada, _, _ = llamada_con([SegmentoFalso("Hola.", 0.3, -0.4, 1.0)])
    avisos = empujar_un_turno(llamada)
    oido = [a for a in avisos if a.tipo == "oido"][0]
    comprobar("hay texto", oido.texto == "Hola.", repr(oido.texto))
    comprobar("y además hay señales, no un resumen vacío",
              oido.datos["confianza"]["segmentos"] == 1,
              str(oido.datos["confianza"]))


def main() -> int:
    print("La confianza del voz a texto, sin cuota y sin GPU\n")
    # Cada prueba va envuelta: una que reviente tiene que contarse como fallo
    # suyo y dejar correr a las demás. Sin esto, romper el sistema a propósito
    # -que es como se comprueba que estas pruebas cubren algo- deja de decir
    # cuántas cosas se rompieron y solo dice cuál fue la primera.
    for prueba in (prueba_resumir_sin_segmentos,
                   prueba_resumir_toma_los_extremos,
                   prueba_el_turno_pide_el_filtro,
                   prueba_sin_filtro_revienta,
                   prueba_las_senales_quedan_escritas,
                   prueba_el_generador_se_materializa):
        try:
            prueba()
        except Exception as exc:  # noqa: BLE001
            comprobar(f"{prueba.__name__} termina sin reventar", False,
                      f"{type(exc).__name__}: {exc}")
    print(f"\n{'TODO BIEN' if not fallos else f'{fallos} FALLOS'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
