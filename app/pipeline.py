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

from app.fin_de_turno import parece_incompleto

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "probe"))

FRECUENCIA = 16000
TROZO_MS = 20
MUESTRAS_POR_TROZO = FRECUENCIA * TROZO_MS // 1000

# Amplitud media por encima de la cual un trozo de 20 ms cuenta como voz, en la
# escala del audio normalizado a ±1. Equivale a unas 165 unidades de entero de
# 16 bits, por debajo del 500 que las sondas usan para "hay señal" porque aquí
# se mira la MEDIA de un trozo corto y no el pico de la grabación entera.
#
# Tiene que ser el mismo número que el de `app/vivo.py`. Lo fue por copia hasta
# el 2026-09-24, cuando los dos pasaron a un detector compartido y volvieron
# aquí el mismo día: ver el ADR 0009.
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
    puente: str = ""
    adelantos_usados: int = 0
    # Cada vez que el sistema decidió NO contestar todavía porque la frase
    # estaba a medias, con el motivo. Es lo que hay que poder enseñar para
    # defender que la espera extra estuvo justificada.
    reanudaciones: list = field(default_factory=list)
    muestras_audio: int = 0
    rastro: list = field(default_factory=list)

    # Los dos instantes que hay que publicar juntos. El primero es cuándo quien
    # llama deja de oír silencio; el segundo, cuándo se entera de algo. Una
    # frase puente mejora el primero y no toca el segundo, así que dar solo el
    # primero sería maquillar la métrica.
    ms_primer_audio: float | None = None
    ms_primer_dato: float | None = None

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
                 voz_minima_ms: int = 600, fin_por_contenido: bool = False,
                 ventana_larga_ms: int = 1200, esperando: str | None = None,
                 max_reanudaciones: int = 2):
        self.asr = modelo_asr
        self.tts = voz_tts
        self.agente = agente
        self.ventana_ms = ventana_silencio_ms
        # Cuánta voz acumulada hace falta antes de permitir declarar el fin del
        # turno. Sin esto, un carraspeo o un golpe de mesa al principio cuenta
        # como intervención y el sistema contesta a los 900 ms con la
        # transcripción vacía. Pasó en la primera ejecución.
        self.voz_minima_ms = voz_minima_ms
        # Decidir el fin de turno tambien por el contenido, no solo por el
        # silencio. Es la salida que el ADR 0002 dejo escrita.
        self.fin_por_contenido = fin_por_contenido
        # Lo que se espera cuando la frase parece estar a medias. Mas largo que
        # la ventana normal: el coste solo se paga en los turnos que lo
        # necesitan, en vez de en todos.
        self.ventana_larga_ms = ventana_larga_ms
        self.esperando = esperando
        self.max_reanudaciones = max_reanudaciones

    # ------------------------------------------------------------------ VAD

    def _hay_voz(self, trozo: np.ndarray) -> bool:
        """Detector de energía sobre un trozo de 20 ms, contra el ruido de fondo.

        Silero trabaja sobre ventanas de 32 ms y no encaja en el ritmo de 20 ms
        de la telefonía sin un adaptador, así que aquí se sigue midiendo
        energía; lo que cambió el 2026-09-24 es contra qué se compara.

        El nivel va en la escala del audio normalizado a ±1, no en la del
        entero de 16 bits. Ponerlo en la escala equivocada no da un detector
        malo: da uno que no oye absolutamente nada, que fue lo que pasó.
        """
        return bool(np.abs(trozo).mean() > UMBRAL_VOZ)

    # --------------------------------------------------------------- turno

    def _escuchar(self, audio, desde, acumulado, ventana_ms, voz_ms_previa,
                  reloj_audio):
        """Consume audio hasta que hay silencio suficiente, o hasta que se acaba.

        Devuelve dónde se quedó, cuándo se declaró el fin, y cuándo fue el
        último trozo con voz. Está separado del resto para poder **reanudar**
        la escucha si la frase resulta estar a medias.
        """
        silencio_ms = 0
        voz_ms = voz_ms_previa
        ultimo_con_voz = None
        for inicio in range(desde, len(audio), MUESTRAS_POR_TROZO):
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
                if voz_ms >= self.voz_minima_ms and silencio_ms >= ventana_ms:
                    return (inicio + MUESTRAS_POR_TROZO, time.perf_counter(),
                            ultimo_con_voz, voz_ms)
        return len(audio), time.perf_counter(), ultimo_con_voz, voz_ms

    def turno(self, audio: np.ndarray) -> TurnoCompleto:
        resultado = TurnoCompleto(muestras_audio=len(audio))
        acumulado: list[np.ndarray] = []
        reloj_audio = time.perf_counter()
        posicion, voz_ms = 0, 0
        ventana = self.ventana_ms
        ultimo_con_voz = None
        reanudaciones = 0
        t_cero = None

        while True:
            posicion, t_fin, con_voz, voz_ms = self._escuchar(
                audio, posicion, acumulado, ventana, voz_ms, reloj_audio)
            if con_voz is not None:
                ultimo_con_voz = con_voz
            if ultimo_con_voz is None:
                raise ValueError("no se detectó voz en el audio")

            # El cronómetro arranca en el último trozo con voz de TODA la
            # intervención, no del trozo actual: si hubo que seguir
            # escuchando, lo que cuenta es cuándo se calló del todo.
            t_cero = ultimo_con_voz
            t = time.perf_counter()
            # Con `vad_filter=True`, igual que en vivo: si la tubería de medir
            # no lleva el mismo filtro que la de correr, el número que sale no
            # es el del sistema. Cuesta +24 ms y va dentro de `ms_asr`. ADR 0008.
            segmentos, _ = self.asr.transcribe(np.concatenate(acumulado),
                                               language="es", beam_size=1,
                                               vad_filter=True)
            resultado.dicho = "".join(s.text for s in segmentos).strip()
            ms_asr = (time.perf_counter() - t) * 1000

            # Aquí el silencio deja de mandar solo. Con la transcripción
            # delante se ve si la frase está a medias, y si lo está se vuelve a
            # escuchar en vez de contestar a un documento cortado.
            motivo = (parece_incompleto(resultado.dicho, self.esperando)
                      if self.fin_por_contenido else None)
            if (motivo and reanudaciones < self.max_reanudaciones
                    and posicion < len(audio)):
                resultado.reanudaciones.append(f"{resultado.dicho!r}: {motivo}")
                resultado.etapas.append(Etapa(
                    f"escucha extra {reanudaciones + 1}", ms_asr,
                    f"no se contestó: {motivo}"))
                ventana = self.ventana_larga_ms
                reanudaciones += 1
                continue

            resultado.etapas.insert(0, Etapa(
                "fin de habla", (t_fin - t_cero) * 1000,
                f"ventana de {ventana} ms"
                + (f", tras {reanudaciones} escucha(s) extra" if reanudaciones else "")))
            resultado.etapas.append(Etapa("voz a texto", ms_asr,
                                          "intervención entera, no en streaming"))
            break

        # El agente avisa en cuanto hay algo pronunciable. Puede ser la frase
        # puente, no la respuesta: por eso se apuntan los dos instantes.
        def hablar(texto: str, clase: str) -> None:
            inicio_tts = time.perf_counter()
            for trozo_audio in self.tts.synthesize(texto):
                if trozo_audio.audio_int16_bytes:
                    break
            ahora = time.perf_counter()
            if resultado.ms_primer_audio is None:
                resultado.ms_primer_audio = (ahora - t_cero) * 1000
                resultado.etapas.append(Etapa(
                    "texto a voz", (ahora - inicio_tts) * 1000,
                    f"hasta el primer trozo reproducible ({clase})"))
            if clase == "respuesta":
                resultado.ms_primer_dato = (ahora - t_cero) * 1000

        t = time.perf_counter()
        turno_agente = self.agente.turno(resultado.dicho, al_hablar=hablar)
        resultado.contestado = turno_agente.texto
        resultado.puente = turno_agente.puente
        resultado.adelantos_usados = turno_agente.adelantos_usados
        resultado.rastro = turno_agente.rastro
        llamadas = sum(1 for p in turno_agente.rastro if p.tipo == "herramienta")
        resultado.etapas.append(Etapa(
            "agente", (time.perf_counter() - t) * 1000,
            f"{llamadas} llamada(s) a herramienta"))

        resultado.punta_a_punta_ms = (time.perf_counter() - t_cero) * 1000
        return resultado


def leer_wav(ruta: Path) -> np.ndarray:
    with wave.open(str(ruta), "rb") as w:
        crudo = w.readframes(w.getnframes())
        if w.getframerate() != FRECUENCIA:
            raise ValueError(f"{ruta.name}: {w.getframerate()} Hz, se esperaban {FRECUENCIA}")
    return np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / 32768.0
