r"""El turno completo, con un solo cronómetro.

Hasta ahora había cuatro etapas medidas por separado y una suma en un papel. El
ADR 0001 dejó escrito que eso no basta:

> El cronómetro de punta a punta se mantendrá como comprobación de que el
> desglose suma lo que dice sumar. Si no cuadra, es que hay una espera que no
> estoy midiendo, y eso es justo lo que quiero descubrir.

Esto es esa comprobación. El audio se alimenta **en tiempo real**, en trozos de
20 ms con su espera correspondiente, como llegaría por teléfono. Nada de
procesar un fichero de golpe: una tubería que va a destiempo con el reloj es
justo lo que se está buscando.

El cronómetro único arranca cuando se alimenta el último trozo con voz —el
instante en que la persona de verdad se calló— y para cuando hay un primer
trozo de audio que reproducir. Eso es lo que percibe quien llama, menos la red.

**Lo que aquí NO se simula, y hay que decirlo:** el voz a texto transcribe la
intervención entera al final, porque `faster-whisper` no es un modelo de
streaming. Un ASR de verdad va transcribiendo mientras la persona habla y al
callarse solo le queda la cola. Por eso se informan los dos números: el medido
aquí, y el que saldría sustituyendo esa etapa por el coste de la cola. El
segundo es una estimación y se etiqueta como tal.
"""

from __future__ import annotations

import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "probe"))

FRECUENCIA = 16000
TROZO_MS = 20
MUESTRAS_POR_TROZO = FRECUENCIA * TROZO_MS // 1000

# Amplitud media por encima de la cual un trozo de 20 ms cuenta como voz, en la
# escala del audio normalizado a ±1. Equivale a unas 165 unidades de entero de
# 16 bits, por debajo del 500 que las sondas usan para "hay señal" porque aquí
# se mira la MEDIA de un trozo corto y no el pico de la grabación entera.
UMBRAL_VOZ = 0.005


@dataclass
class Etapa:
    nombre: str
    ms: float
    detalle: str = ""


@dataclass
class TurnoCompleto:
    etapas: list[Etapa] = field(default_factory=list)
    punta_a_punta_ms: float = 0.0
    dicho: str = ""
    contestado: str = ""
    muestras_audio: int = 0
    rastro: list = field(default_factory=list)

    @property
    def suma_etapas_ms(self) -> float:
        return sum(e.ms for e in self.etapas)

    @property
    def sin_contabilizar_ms(self) -> float:
        """Lo que el cronómetro ve y el desglose no explica."""
        return self.punta_a_punta_ms - self.suma_etapas_ms


class Tuberia:
    """Alimenta audio en tiempo real y produce la respuesta hablada."""

    def __init__(self, modelo_asr, voz_tts, agente, ventana_silencio_ms: int = 300,
                 voz_minima_ms: int = 600):
        self.asr = modelo_asr
        self.tts = voz_tts
        self.agente = agente
        self.ventana_ms = ventana_silencio_ms
        # Cuánta voz acumulada hace falta antes de permitir declarar el fin del
        # turno. Sin esto, un carraspeo o un golpe de mesa al principio cuenta
        # como intervención y el sistema contesta a los 900 ms con la
        # transcripción vacía. Pasó en la primera ejecución.
        self.voz_minima_ms = voz_minima_ms

    # ------------------------------------------------------------------ VAD

    def _hay_voz(self, trozo: np.ndarray) -> bool:
        """Detector de energía sobre un trozo de 20 ms.

        Silero trabaja sobre ventanas de 32 ms y no encaja en el ritmo de 20 ms
        de la telefonía sin un adaptador. Para esta comprobación basta la
        energía: lo que se está midiendo es si el reloj cuadra, no la calidad
        del detector.

        El umbral va en la escala del audio normalizado a ±1, no en la del
        entero de 16 bits. Ponerlo en la escala equivocada no da un detector
        malo: da uno que no oye absolutamente nada, que fue lo que pasó.
        """
        return bool(np.abs(trozo).mean() > UMBRAL_VOZ)

    # --------------------------------------------------------------- turno

    def turno(self, audio: np.ndarray) -> TurnoCompleto:
        resultado = TurnoCompleto(muestras_audio=len(audio))
        acumulado: list[np.ndarray] = []
        silencio_ms = 0
        voz_ms = 0
        ultimo_con_voz = None      # reloj de pared del último trozo con voz
        t_fin_declarado = None

        reloj_audio = time.perf_counter()
        for inicio in range(0, len(audio), MUESTRAS_POR_TROZO):
            trozo = audio[inicio:inicio + MUESTRAS_POR_TROZO]
            acumulado.append(trozo)

            # Esperar a que el reloj de pared alcance al reloj del audio: así
            # el trozo llega cuando llegaría por teléfono, ni antes ni después.
            objetivo = reloj_audio + (inicio + len(trozo)) / FRECUENCIA
            pendiente = objetivo - time.perf_counter()
            if pendiente > 0:
                time.sleep(pendiente)

            if self._hay_voz(trozo):
                silencio_ms = 0
                voz_ms += TROZO_MS
                ultimo_con_voz = time.perf_counter()
            else:
                silencio_ms += TROZO_MS
                if (voz_ms >= self.voz_minima_ms
                        and silencio_ms >= self.ventana_ms):
                    t_fin_declarado = time.perf_counter()
                    break

        if ultimo_con_voz is None:
            raise ValueError("no se detectó voz en el audio")
        if t_fin_declarado is None:
            # El audio se acabó sin que hubiera silencio suficiente. Se declara
            # el fin aquí, pero queda dicho: la grabación no daba para más.
            t_fin_declarado = time.perf_counter()

        # ----- EL CRONÓMETRO ÚNICO arranca cuando la persona se calló de verdad
        t_cero = ultimo_con_voz

        resultado.etapas.append(Etapa(
            "fin de habla", (t_fin_declarado - t_cero) * 1000,
            f"ventana de silencio de {self.ventana_ms} ms"))

        completo = np.concatenate(acumulado)

        t = time.perf_counter()
        segmentos, _ = self.asr.transcribe(completo, language="es", beam_size=1)
        resultado.dicho = "".join(s.text for s in segmentos).strip()
        resultado.etapas.append(Etapa(
            "voz a texto", (time.perf_counter() - t) * 1000,
            f"intervención entera ({len(completo) / FRECUENCIA:.1f} s), no en streaming"))

        t = time.perf_counter()
        turno_agente = self.agente.turno(resultado.dicho)
        resultado.contestado = turno_agente.texto
        resultado.rastro = turno_agente.rastro
        llamadas = sum(1 for p in turno_agente.rastro if p.tipo == "herramienta")
        resultado.etapas.append(Etapa(
            "agente", (time.perf_counter() - t) * 1000,
            f"{llamadas} llamada(s) a herramienta"))

        t = time.perf_counter()
        primer_trozo_ms = None
        for trozo_audio in self.tts.synthesize(resultado.contestado):
            if trozo_audio.audio_int16_bytes:
                primer_trozo_ms = (time.perf_counter() - t) * 1000
                break
        resultado.etapas.append(Etapa(
            "texto a voz", primer_trozo_ms or 0.0, "hasta el primer trozo reproducible"))

        resultado.punta_a_punta_ms = (time.perf_counter() - t_cero) * 1000
        return resultado


def leer_wav(ruta: Path) -> np.ndarray:
    with wave.open(str(ruta), "rb") as w:
        crudo = w.readframes(w.getnframes())
        if w.getframerate() != FRECUENCIA:
            raise ValueError(f"{ruta.name}: {w.getframerate()} Hz, se esperaban {FRECUENCIA}")
    return np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / 32768.0
