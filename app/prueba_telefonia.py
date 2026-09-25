r"""El canal telefónico, comprobado sin Twilio, sin cuenta y sin gastar nada.

Twilio manda un WebSocket con mensajes JSON y audio µ-law de 8 kHz en base64.
Todo eso se puede emular: esta prueba **es** un cliente de Twilio de mentira que
manda la misma secuencia —`connected`, `start`, muchos `media`, `stop`— y
comprueba lo que vuelve.

Lo que queda fuera y hay que decirlo: **el transporte**. Que Twilio de verdad
abra el socket, que el túnel funcione y que el número suene solo se comprueba
llamando por teléfono, y eso necesita una cuenta y un túnel. Lo que esta prueba
establece es que **cuando el audio llegue, el sistema lo entiende y contesta en
el formato correcto**, que es la parte donde están los errores silenciosos.

Cuatro grupos, de menos a más:

 1. **G.711 contra la biblioteca estándar**, en los 65 536 valores posibles. Es
    la que encontró que la primera versión del códec difería en 381 de ellos.
 2. **Las conversiones**: escalas, frecuencias y el silencio, que en µ-law no
    es cero sino 0xFF.
 3. **El puente entero** con dobles: la secuencia de Twilio entra y salen
    mensajes `media` bien formados.
 4. **Una frase de verdad por el canal completo**, con el ASR real: WAV a 16 kHz
    → µ-law de 8 kHz como lo mandaría Twilio → el puente → Whisper. Si el
    documento sobrevive a ese viaje, el canal sirve. Necesita GPU y se salta
    diciéndolo.

  .\.venv\Scripts\python.exe -m app.prueba_telefonia
"""

from __future__ import annotations

import base64
import json
import sys
import warnings
from pathlib import Path

import numpy as np

from app.telefonia import g711
from app.telefonia.media_streams import (
    FRECUENCIA_LINEA,
    FRECUENCIA_SISTEMA,
    MUESTRAS_POR_TROZO,
    PuenteTwilio,
    a_frecuencia,
    twiml,
)

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "probe"))

fallos = 0
saltadas: list[str] = []


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}")
    else:
        fallos += 1
        print(f"    FALLA  {nombre}" + (f" -> {detalle}" if detalle else ""))


# ----------------------------------------------------- 1. contra la referencia

def prueba_g711_contra_la_biblioteca() -> None:
    print("  G.711 idéntico a la implementación de referencia")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import audioop  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        saltadas.append("G.711 contra audioop (no existe en este Python)")
        print("    (saltada: `audioop` ya no está en este Python)")
        return

    todas = np.arange(-32768, 32768, dtype=np.int16)
    comprobar("codificar, en los 65 536 valores posibles",
              g711.de_pcm16(todas) == audioop.lin2ulaw(todas.tobytes(), 2))
    todos_los_bytes = bytes(range(256))
    comprobar("decodificar, en los 256 bytes posibles",
              np.array_equal(g711.a_pcm16(todos_los_bytes),
                             np.frombuffer(audioop.ulaw2lin(todos_los_bytes, 2),
                                           dtype=np.int16)))


# ------------------------------------------------------- 2. las conversiones

def prueba_las_conversiones() -> None:
    print("  las escalas y el silencio, que es donde se cuelan los errores")
    comprobar("el silencio en µ-law es 0xFF y no 0x00",
              g711.de_pcm16(np.zeros(4, dtype=np.int16)) == b"\xff\xff\xff\xff",
              "un cable cortado da ceros; el silencio de verdad, 0xFF")
    comprobar("y al volver sigue siendo silencio",
              float(np.max(np.abs(g711.a_float(b"\xff" * 80)))) < 0.001,
              str(float(np.max(np.abs(g711.a_float(b"\xff" * 80))))))

    generador = np.random.default_rng(3)
    original = (generador.standard_normal(8000) * 0.2).astype(np.float32)
    vuelta = g711.a_float(g711.de_float(original))
    error = float(np.max(np.abs(vuelta - original)))
    comprobar("la ida y vuelta conserva la forma de onda",
              error < 0.02, f"error máximo {error:.4f}")
    comprobar("y no invierte el signo, que sonaría igual y rompería el VAD",
              float(np.corrcoef(original, vuelta)[0, 1]) > 0.99,
              str(float(np.corrcoef(original, vuelta)[0, 1])))

    comprobar("22 050 Hz a 8 000 da la duración correcta",
              abs(len(a_frecuencia(np.zeros(22050, dtype=np.float32), 22050, 8000))
                  - 8000) <= 2)
    comprobar("y 8 000 a 16 000 también",
              abs(len(a_frecuencia(np.zeros(8000, dtype=np.float32), 8000, 16000))
                  - 16000) <= 2)
    comprobar("el TwiML usa Connect y no Start, que solo escucha",
              "<Connect>" in twiml("wss://x/y") and "Start" not in twiml("wss://x/y"))


# ---------------------------------------------------------- 3. el puente

class ASRQueDicta:
    def __init__(self, frases: list[str]) -> None:
        self.frases = list(frases)
        self.recibido: list[int] = []

    def transcribe(self, audio, **kwargs):
        self.recibido.append(len(audio))
        texto = self.frases.pop(0) if self.frases else ""

        class Segmento:
            text = texto
            no_speech_prob = 0.05
            avg_logprob = -0.3
            compression_ratio = 1.1

        class Info:
            language_probability = 0.99

        return [Segmento()], Info()


class VozQueSuena:
    """Sintetiza medio segundo a 22 050 Hz, como Piper."""

    class _Trozo:
        def __init__(self) -> None:
            generador = np.random.default_rng(5)
            muestras = (generador.standard_normal(11025) * 0.2 * 32767).astype(np.int16)
            self.audio_int16_bytes = muestras.tobytes()
            self.sample_rate = 22050

    def synthesize(self, texto: str):
        return [self._Trozo()]


class AgenteQueContesta:
    def __init__(self) -> None:
        self.dichos: list[str] = []

    def turno(self, dicho, al_hablar=None, **kwargs):
        self.dichos.append(dicho)
        if al_hablar:
            al_hablar("Su tarjeta está bloqueada.", "respuesta")

        class T:
            texto = "Su tarjeta está bloqueada."
            rastro: list = []
            puente = ""
            ms_total = 1200.0
            agotado = False
            silencio = 0
            tokens_entrada = 100
            tokens_salida = 20
            peticiones = 1
            clave = "abc123"
        return T()


def mensajes_de_twilio(audio_16k: np.ndarray, stream_sid: str = "MZ0001"):
    """La secuencia exacta que manda Twilio, con el audio en trozos de 20 ms."""
    yield {"event": "connected", "protocol": "Call", "version": "1.0.0"}
    yield {"event": "start", "sequenceNumber": "1", "streamSid": stream_sid,
           "start": {"streamSid": stream_sid, "accountSid": "ACfalso",
                     "callSid": "CAfalso", "tracks": ["inbound"],
                     "mediaFormat": {"encoding": "audio/x-mulaw",
                                     "sampleRate": 8000, "channels": 1}}}
    en_linea = a_frecuencia(audio_16k, FRECUENCIA_SISTEMA, FRECUENCIA_LINEA)
    for i in range(0, len(en_linea), MUESTRAS_POR_TROZO):
        trozo = en_linea[i:i + MUESTRAS_POR_TROZO]
        if len(trozo) < MUESTRAS_POR_TROZO:
            break
        yield {"event": "media", "streamSid": stream_sid,
               "media": {"track": "inbound", "chunk": str(i),
                         "timestamp": str(i // 8),
                         "payload": base64.b64encode(
                             g711.de_float(trozo)).decode("ascii")}}
    yield {"event": "stop", "streamSid": stream_sid,
           "stop": {"accountSid": "ACfalso", "callSid": "CAfalso"}}


def audio_con_una_frase() -> np.ndarray:
    generador = np.random.default_rng(7)
    sala = (generador.standard_normal(int(0.6 * FRECUENCIA_SISTEMA)) * 0.001)
    voz = (generador.standard_normal(int(0.9 * FRECUENCIA_SISTEMA)) * 0.05)
    silencio = np.zeros(int(0.6 * FRECUENCIA_SISTEMA))
    return np.concatenate([sala, voz, silencio]).astype(np.float32)


def prueba_el_puente() -> None:
    from app.vivo import Llamada  # noqa: PLC0415

    print("  la secuencia de Twilio entra y sale audio para la línea")
    asr = ASRQueDicta(["Mi cédula es 1070234567."])
    agente = AgenteQueContesta()
    puente = PuenteTwilio(Llamada(asr, VozQueSuena(), agente))

    enviados: list[dict] = []
    for mensaje in mensajes_de_twilio(audio_con_una_frase()):
        enviados.extend(puente.al_recibir(json.dumps(mensaje)))

    comprobar("coge el streamSid del start", puente.stream_sid == "MZ0001",
              str(puente.stream_sid))
    comprobar("y el callSid, que es con lo que se busca una llamada después",
              puente.call_sid == "CAfalso", str(puente.call_sid))
    comprobar("no se queja del formato bueno", puente.avisos_de_formato == [],
              str(puente.avisos_de_formato))
    comprobar("el audio de la línea llega a transcribirse",
              puente.transcripciones == ["Mi cédula es 1070234567."],
              str(puente.transcripciones))
    comprobar("el agente oyó lo que se dijo",
              agente.dichos == ["Mi cédula es 1070234567."], str(agente.dichos))
    comprobar("y contestó", puente.dicho_por_el_agente == ["Su tarjeta está bloqueada."],
              str(puente.dicho_por_el_agente))

    medios = [m for m in enviados if m.get("event") == "media"]
    comprobar("vuelve audio para la línea", len(medios) > 0, str(len(enviados)))
    if medios:
        cargas = [base64.b64decode(m["media"]["payload"]) for m in medios]
        comprobar("en trozos de 20 ms exactos (160 bytes)",
                  all(len(c) == MUESTRAS_POR_TROZO for c in cargas),
                  str(sorted({len(c) for c in cargas})))
        comprobar("todos con su streamSid",
                  all(m["streamSid"] == "MZ0001" for m in medios))
        total = sum(len(c) for c in cargas)
        comprobar("y la duración cuadra con medio segundo de voz",
                  abs(total / FRECUENCIA_LINEA - 0.5) < 0.05,
                  f"{total / FRECUENCIA_LINEA:.3f} s")
        comprobar("el audio que sale NO es silencio",
                  float(np.max(np.abs(g711.a_float(cargas[len(cargas) // 2])))) > 0.01)
    comprobar("el stop cuelga la llamada", puente.terminada)

    print("  la marca de Twilio es lo que dice que el agente ya calló")
    ultimo = enviados[-1] if enviados else {}
    comprobar("detrás del audio va una marca", ultimo.get("event") == "mark",
              str(ultimo.get("event")))
    otra = PuenteTwilio(Llamada(ASRQueDicta(["Hola."]), VozQueSuena(),
                                AgenteQueContesta()))
    otra.al_recibir({"event": "start", "streamSid": "MZ2",
                     "start": {"mediaFormat": {"encoding": "audio/x-mulaw",
                                               "sampleRate": 8000,
                                               "channels": 1}}})
    otra.hablar(VozQueSuena()._Trozo().audio_int16_bytes, 22050)
    comprobar("mientras habla, la entrada se ignora", otra.llamada.hablando is True)
    otra.al_recibir({"event": "mark", "streamSid": "MZ2",
                     "mark": {"name": "fin-de-respuesta"}})
    comprobar("y al llegar la marca se vuelve a escuchar",
              otra.llamada.hablando is False)
    comprobar("una marca ajena no levanta la escucha",
              _marca_ajena_no_levanta())

    print("  un formato inesperado se anota en vez de cortar la llamada")
    otro = PuenteTwilio(Llamada(ASRQueDicta([]), VozQueSuena(), AgenteQueContesta()))
    otro.al_recibir({"event": "start", "streamSid": "MZ9",
                     "start": {"mediaFormat": {"encoding": "audio/l16",
                                               "sampleRate": 16000,
                                               "channels": 1}}})
    comprobar("queda el aviso con los dos formatos",
              len(otro.avisos_de_formato) == 1
              and "audio/l16" in otro.avisos_de_formato[0],
              str(otro.avisos_de_formato))
    comprobar("y la llamada sigue arrancada", otro.arrancada)


# ------------------------------------------- 4. una frase de verdad, por la línea

def _marca_ajena_no_levanta() -> bool:
    """Twilio puede mandar marcas propias; solo la nuestra significa "ya callé"."""
    from app.vivo import Llamada  # noqa: PLC0415

    puente = PuenteTwilio(Llamada(ASRQueDicta([]), VozQueSuena(),
                                  AgenteQueContesta()))
    puente.llamada.hablando = True
    puente.al_recibir({"event": "mark", "streamSid": "MZ3",
                       "mark": {"name": "otra-cosa"}})
    return puente.llamada.hablando is True


def prueba_una_frase_real_por_la_linea() -> None:
    """Lo que de verdad decide si este canal sirve: el documento sobrevive."""
    print("  una grabación real por el canal de Twilio, con el ASR de verdad")
    from common import ARTEFACTOS  # noqa: PLC0415

    wav = ARTEFACTOS / "muestra-documento.wav"
    if not wav.exists():
        saltadas.append("frase real (no hay grabación)")
        print("    (saltada: no hay muestra-documento.wav)")
        return
    try:
        from probe_whisper_local import cargar_modelo, leer_wav  # noqa: PLC0415
        modelo, dispositivo, _, _ = cargar_modelo("small")
    except Exception as exc:  # noqa: BLE001
        saltadas.append(f"frase real (sin ASR: {type(exc).__name__})")
        print(f"    (saltada: no se pudo cargar el ASR: {type(exc).__name__})")
        return

    audio, frecuencia, _ = leer_wav(wav)
    if frecuencia != FRECUENCIA_SISTEMA:
        saltadas.append("frase real (la grabación no está a 16 kHz)")
        return

    # El viaje completo, byte a byte como lo haría Twilio.
    en_linea = a_frecuencia(audio, FRECUENCIA_SISTEMA, FRECUENCIA_LINEA)
    recibido = []
    for i in range(0, len(en_linea), MUESTRAS_POR_TROZO):
        trozo = en_linea[i:i + MUESTRAS_POR_TROZO]
        if len(trozo) < MUESTRAS_POR_TROZO:
            break
        carga = base64.b64encode(g711.de_float(trozo)).decode("ascii")
        recibido.append(g711.a_float(base64.b64decode(carga)))
    vuelta = a_frecuencia(np.concatenate(recibido), FRECUENCIA_LINEA,
                          FRECUENCIA_SISTEMA)

    segmentos, _ = modelo.transcribe(vuelta, language="es", beam_size=1,
                                     vad_filter=True)
    dicho = "".join(s.text for s in segmentos).strip()
    print(f"    transcrito ({dispositivo}): {dicho[:110]}")

    sys.path.insert(0, str(RAIZ / "probe"))
    from numeros_es import normalizar  # noqa: PLC0415

    en_cifras = normalizar(dicho).replace(" ", "")
    comprobar("el documento sobrevive al viaje por la línea",
              "1070234567" in en_cifras,
              f"no aparece en {en_cifras[:90]}")
    comprobar("y sale una frase, no un trozo",
              len(dicho.split()) >= 8, f"{len(dicho.split())} palabras")


def main() -> int:
    print("El canal telefónico (Twilio Media Streams), sin Twilio\n")
    for prueba in (prueba_g711_contra_la_biblioteca, prueba_las_conversiones,
                   prueba_el_puente, prueba_una_frase_real_por_la_linea):
        try:
            prueba()
        except Exception as exc:  # noqa: BLE001
            comprobar(f"{prueba.__name__} termina sin reventar", False,
                      f"{type(exc).__name__}: {exc}")

    if saltadas:
        print("\n  SALTADAS (no cuentan como verde):")
        for s in saltadas:
            print(f"    - {s}")
    print(f"\n{'TODO BIEN' if not fallos else f'{fallos} FALLOS'}"
          + ("  (con partes saltadas)" if saltadas else ""))
    return 1 if fallos else (2 if saltadas else 0)


if __name__ == "__main__":
    raise SystemExit(main())
