r"""Una llamada en vivo: audio que llega por trozos, respuesta que sale hablada.

La diferencia con `app/pipeline.py` no es cosmética. Allí el audio existe entero
desde el principio y se va soltando al ritmo del reloj para simular una llamada.
Aquí **no existe todavía**: llega cuando quien habla lo produce, y el sistema no
puede mirar el futuro. Es la misma tubería, pero empujada en vez de tirada.

Todo el estado de la llamada vive en este objeto, uno por conexión. La pasarela
no guarda nada suyo: si mañana este estado se mueve a Redis, se pueden levantar
N pasarelas detrás de un balanceador y cualquiera atiende cualquier turno. Esa
es la frase que hay que poder defender, y por eso el estado está aquí y no
repartido por la pasarela.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from app.confianza import resumir
from app.deteccion_voz import DetectorDeVoz
from app.fin_de_turno import parece_incompleto

FRECUENCIA = 16000
TROZO_MS = 20
MUESTRAS_POR_TROZO = FRECUENCIA * TROZO_MS // 1000


@dataclass
class Aviso:
    """Algo que contarle a la pantalla mientras pasa."""
    tipo: str          # "estado" | "oido" | "herramienta" | "dice" | "tiempos"
    texto: str = ""
    datos: dict = field(default_factory=dict)


class Llamada:
    """Una conversación. Se le empuja audio y devuelve avisos."""

    def __init__(self, asr, voz, agente, ventana_ms: int = 300,
                 ventana_larga_ms: int = 1200, voz_minima_ms: int = 600,
                 max_reanudaciones: int = 2) -> None:
        self.asr = asr
        self.voz = voz
        self.agente = agente
        self.ventana_ms = ventana_ms
        self.ventana_larga_ms = ventana_larga_ms
        self.voz_minima_ms = voz_minima_ms
        self.max_reanudaciones = max_reanudaciones

        self.buffer: list[np.ndarray] = []
        self.silencio_ms = 0
        self.voz_ms = 0
        self.ultimo_con_voz: float | None = None
        self.ventana_actual = ventana_ms
        self.reanudaciones = 0
        # Lo último que el agente le pidió a la persona. Sin esto, "70 234" es
        # ambiguo; sabiendo que se pidió el documento, es una cédula a medias.
        self.esperando: str | None = None
        self.hablando = False
        # El detector es de la LLAMADA y no del turno: el suelo de ruido es una
        # propiedad de la sala desde la que llaman, y tirarlo en cada turno
        # obligaría a reaprenderlo desde cero cada vez que alguien contesta.
        self.detector = DetectorDeVoz()

    # ------------------------------------------------------------------ audio

    def _hay_voz(self, trozo: np.ndarray) -> bool:
        """Contra el ruido de esta llamada, no contra una constante.

        El umbral fijo de 0,005 que había aquí describía esta habitación: con
        la voz a la mitad no abría turno en ninguna de las 6 grabaciones, y por
        línea telefónica en 1 de 6, sin que nadie se enterara de que alguien
        había hablado. ADR 0009.
        """
        return self.detector.hay_voz(float(np.abs(trozo).mean()))

    def empujar(self, muestras: np.ndarray):
        """Recibe audio del navegador. Devuelve avisos si hay turno que cerrar.

        Mientras el agente habla se ignora la entrada. Es una decisión, no un
        descuido: sin cancelación de eco, el micrófono abierto capta la propia
        voz del agente y el sistema se contesta a sí mismo. El barge-in de
        verdad necesita esa cancelación y todavía no está.
        """
        if self.hablando:
            return []

        self.buffer.append(muestras)
        for i in range(0, len(muestras), MUESTRAS_POR_TROZO):
            trozo = muestras[i:i + MUESTRAS_POR_TROZO]
            if len(trozo) == 0:
                continue
            if self._hay_voz(trozo):
                self.silencio_ms = 0
                self.voz_ms += TROZO_MS
                self.ultimo_con_voz = time.perf_counter()
            else:
                self.silencio_ms += TROZO_MS

        if (self.voz_ms >= self.voz_minima_ms
                and self.silencio_ms >= self.ventana_actual
                and self.ultimo_con_voz is not None):
            return self.cerrar_turno()
        return []

    # ------------------------------------------------------------------ turno

    def cerrar_turno(self) -> list[Aviso]:
        t_cero = self.ultimo_con_voz
        avisos: list[Aviso] = []

        t = time.perf_counter()
        completo = np.concatenate(self.buffer)
        # `vad_filter=True` le quita a Whisper el audio sin voz antes de
        # transcribirlo, y no es una optimización: es lo único que impide que
        # se invente. Medido el 2026-09-24 sobre 64 clips de silencio real de
        # esta sala, sin el filtro 7 producen texto —"¿Qué pasa?",
        # "¡Suscríbete!", un trozo de subtítulos— y con él, ninguno. El buffer
        # que llega aquí lleva además la cola de silencio que cerró el turno,
        # y sin filtro Whisper llegó a repetir la frase entera detrás de sí
        # misma: 15 palabras de más en un turno de verdad. Cuesta +24 ms sobre
        # un turno de 2389. ADR 0008.
        segmentos, info = self.asr.transcribe(completo, language="es",
                                              beam_size=1, vad_filter=True)
        segmentos = list(segmentos)     # el generador es perezoso: aquí se ejecuta
        dicho = "".join(s.text for s in segmentos).strip()
        ms_asr = (time.perf_counter() - t) * 1000
        # Lo que el modelo sabe de su propia transcripción. Se anota y no se
        # actúa sobre ello: el porqué está en `app/confianza.py` y en el ADR.
        senales = resumir(segmentos, getattr(info, "language_probability", None))

        motivo = parece_incompleto(dicho, self.esperando)
        if motivo and self.reanudaciones < self.max_reanudaciones:
            # No se contesta: se sigue escuchando con la ventana larga. El
            # motivo va a la pantalla porque una espera sin explicar parece
            # que el sistema se colgó.
            self.reanudaciones += 1
            self.ventana_actual = self.ventana_larga_ms
            self.silencio_ms = 0
            return [Aviso("estado", "sigo escuchando",
                          {"motivo": motivo, "parcial": dicho,
                           "confianza": senales})]

        avisos.append(Aviso("oido", dicho, {"ms_asr": round(ms_asr),
                                            "confianza": senales}))
        avisos.append(Aviso("estado", "pensando"))

        salida: list[dict] = []
        primer_audio_ms: float | None = None
        primer_dato_ms: float | None = None

        def hablar(texto: str, clase: str) -> None:
            nonlocal primer_audio_ms, primer_dato_ms
            trozos = []
            frecuencia_voz = 22050
            for trozo_audio in self.voz.synthesize(texto):
                trozos.append(trozo_audio.audio_int16_bytes)
                frecuencia_voz = trozo_audio.sample_rate
                if primer_audio_ms is None:
                    primer_audio_ms = (time.perf_counter() - t_cero) * 1000
            if clase == "respuesta":
                primer_dato_ms = (time.perf_counter() - t_cero) * 1000
            salida.append({"texto": texto, "clase": clase,
                           "pcm": b"".join(trozos), "frecuencia": frecuencia_voz})

        turno = self.agente.turno(dicho, al_hablar=hablar)

        for paso in turno.rastro:
            if paso.tipo == "herramienta":
                avisos.append(Aviso("herramienta", paso.detalle,
                                    {"argumentos": paso.argumentos,
                                     "resultado": paso.resultado,
                                     "ms": round(paso.ms)}))

        for trozo in salida:
            avisos.append(Aviso("dice", trozo["texto"],
                                {"clase": trozo["clase"], "pcm": trozo["pcm"],
                                 "frecuencia": trozo["frecuencia"]}))

        avisos.append(Aviso("tiempos", "", {
            "primer_audio_ms": round(primer_audio_ms or 0),
            "primer_dato_ms": round(primer_dato_ms or 0),
            "ms_asr": round(ms_asr),
            "reanudaciones": self.reanudaciones,
        }))

        # Si el agente acaba de pedir el documento, el siguiente turno lo sabe.
        bajo = turno.texto.lower()
        if "documento" in bajo or "cédula" in bajo or "cedula" in bajo:
            self.esperando = "documento"
        elif turno.texto:
            self.esperando = None

        self._reiniciar()
        return avisos

    def _reiniciar(self) -> None:
        self.buffer.clear()
        self.silencio_ms = 0
        self.voz_ms = 0
        self.ultimo_con_voz = None
        self.ventana_actual = self.ventana_ms
        self.reanudaciones = 0
