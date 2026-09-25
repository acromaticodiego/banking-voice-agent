r"""El protocolo de Twilio Media Streams, separado del WebSocket que lo trae.

Twilio abre un WebSocket hacia el sistema y le manda mensajes JSON: `connected`,
`start`, muchos `media` con audio µ-law de 8 kHz en base64, y `stop`. De vuelta
espera `media` con el audio de la respuesta en el mismo formato, y acepta
`clear` para tirar lo que tenga en cola.

**Todo eso vive aquí como una función de mensajes a mensajes**, sin red. El
motivo no es purismo: es que así se puede comprobar con un cliente que emule
exactamente lo que manda Twilio, hoy, sin cuenta, sin túnel y sin gastar un
céntimo. Lo único que queda por verificar con una llamada de verdad es el
transporte, y eso está dicho donde toca en vez de disimulado.

## Las tres conversiones, que es donde están los errores

  · **Entrada**: base64 → bytes µ-law → PCM → ±1 → **8 kHz a 16 kHz**, porque
    `faster-whisper` trabaja a 16 kHz. Subir de frecuencia no recupera lo que
    el canal se llevó —los 3400 Hz de arriba no vuelven— y no pretende: es para
    que el modelo reciba lo que espera.
  · **Salida**: Piper sintetiza a 22 050 Hz y la línea quiere 8 000. La razón
    es 160/441, que no es una potencia de dos, así que el remuestreo se hace
    con el filtro que toca y no tirando muestras.
  · **Escala**: el sistema trabaja en ±1 y la línea en enteros de 8 bits. Este
    proyecto ya perdió un rato con un detector sordo por confundir las escalas,
    y por eso las conversiones están en un solo sitio.

## El ritmo

Twilio manda 20 ms por mensaje (160 muestras a 8 kHz) y espera lo mismo de
vuelta. La respuesta del agente son varios segundos de audio, así que se parte
en trozos de 20 ms: mandarla de golpe funciona —Twilio la encola— pero deja al
sistema sin forma de callarse a mitad si quien llama interrumpe, que es justo
lo que hará falta para el barge-in.
"""

from __future__ import annotations

import base64
import json
from fractions import Fraction

import numpy as np
from scipy import signal

from app.telefonia import g711

FRECUENCIA_LINEA = 8000
FRECUENCIA_SISTEMA = 16000
MUESTRAS_POR_TROZO = FRECUENCIA_LINEA * 20 // 1000      # 160: los 20 ms de Twilio

# Lo que Twilio dice que manda. Se comprueba en vez de suponerse: si algún día
# cambia a otro códec, el síntoma sería audio ininteligible y la causa estaría
# a cuatro capas de distancia.
FORMATO_ESPERADO = ("audio/x-mulaw", 8000, 1)

# El nombre de la marca con la que Twilio avisa de que acabó de reproducir la
# respuesta. Es una constante porque la manda una parte del código y la recibe
# otra, y un literal repetido en dos sitios se despega en cuanto alguien lo
# cambia en uno.
MARCA_FIN = "fin-de-respuesta"


def a_frecuencia(audio: np.ndarray, desde: int, hasta: int) -> np.ndarray:
    """Remuestrea con el filtro que toca, por la razón exacta entre las dos.

    `resample_poly` necesita enteros, así que la razón se reduce con
    `Fraction`: 22050 a 8000 es 160/441, y redondear eso a mano —o tirar
    muestras— mete un aliasing que en una llamada se oye como metal.
    """
    if desde == hasta:
        return np.asarray(audio, dtype=np.float32)
    razon = Fraction(hasta, desde).limit_denominator(1000)
    salida = signal.resample_poly(np.asarray(audio, dtype=np.float64),
                                  razon.numerator, razon.denominator)
    return salida.astype(np.float32)


class PuenteTwilio:
    """Traduce entre los mensajes de Twilio y una `Llamada` del sistema.

    No habla por red: recibe un mensaje y devuelve la lista de mensajes que hay
    que enviar. Quien tenga el WebSocket los manda.
    """

    def __init__(self, llamada) -> None:
        self.llamada = llamada
        self.stream_sid: str | None = None
        self.call_sid: str | None = None
        self.arrancada = False
        self.terminada = False
        # Lo que la pantalla del navegador vería; aquí se guarda para poder
        # contarlo después y para las pruebas.
        self.transcripciones: list[str] = []
        self.dicho_por_el_agente: list[str] = []
        self.avisos_de_formato: list[str] = []
        self.trozos_enviados = 0
        self.marcas_recibidas = 0
        self.dtmf: list = []

    # ------------------------------------------------------------- recepción

    def al_recibir(self, crudo: str | dict) -> list[dict]:
        mensaje = json.loads(crudo) if isinstance(crudo, str) else crudo
        evento = mensaje.get("event")

        if evento == "connected":
            return []
        if evento == "start":
            return self._arrancar(mensaje)
        if evento == "media":
            return self._audio(mensaje)
        if evento == "stop":
            self.terminada = True
            self.llamada.colgar("colgo")
            return []
        if evento == "mark":
            # Twilio devuelve la marca cuando ha terminado de REPRODUCIR lo que
            # iba antes de ella. Es la única forma honesta de saber que el
            # agente ya calló: la alternativa es calcularlo por la duración del
            # audio, que ignora lo que la línea tenga en cola.
            if (mensaje.get("mark") or {}).get("name") == MARCA_FIN:
                self.llamada.hablando = False
                self.marcas_recibidas += 1
            return []
        if evento == "dtmf":
            # Las teclas del teléfono. No se usan todavía y se dice: un menú de
            # tonos sería otra conversación, no esta.
            self.dtmf.append((mensaje.get("dtmf") or {}).get("digit"))
            return []
        return []

    def _arrancar(self, mensaje: dict) -> list[dict]:
        inicio = mensaje.get("start") or {}
        self.stream_sid = mensaje.get("streamSid") or inicio.get("streamSid")
        self.call_sid = inicio.get("callSid")
        formato = inicio.get("mediaFormat") or {}
        actual = (formato.get("encoding"), formato.get("sampleRate"),
                  formato.get("channels"))
        if actual != FORMATO_ESPERADO:
            # No se aborta: se anota y se sigue intentando. Una llamada que
            # entra con un formato raro y se corta sin decir por qué es peor
            # que una llamada que suena mal y deja el motivo escrito.
            self.avisos_de_formato.append(
                f"formato inesperado {actual}, se esperaba {FORMATO_ESPERADO}")
        self.arrancada = True
        return []

    def _audio(self, mensaje: dict) -> list[dict]:
        carga = (mensaje.get("media") or {}).get("payload")
        if not carga:
            return []
        de_la_linea = g711.a_float(base64.b64decode(carga))
        muestras = a_frecuencia(de_la_linea, FRECUENCIA_LINEA, FRECUENCIA_SISTEMA)

        salida: list[dict] = []
        for aviso in self.llamada.empujar(muestras):
            if aviso.tipo == "oido":
                self.transcripciones.append(aviso.texto)
            elif aviso.tipo == "dice":
                self.dicho_por_el_agente.append(aviso.texto)
                salida.extend(self.hablar(aviso.datos["pcm"],
                                          aviso.datos["frecuencia"]))
        return salida

    # --------------------------------------------------------------- emisión

    def hablar(self, pcm: bytes, frecuencia: int) -> list[dict]:
        """El audio del agente, en trozos de 20 ms de µ-law, como los quiere Twilio."""
        if not pcm:
            return []
        muestras = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        en_linea = a_frecuencia(muestras, frecuencia, FRECUENCIA_LINEA)

        # Mientras el agente habla se ignora la entrada, igual que en el
        # navegador. Aquí no es por el eco del altavoz —la línea telefónica ya
        # trae su cancelación— sino para no partir la respuesta en dos turnos.
        # Se levanta al recibir la marca, no al calcular una duración.
        self.llamada.hablando = True

        mensajes = []
        for i in range(0, len(en_linea), MUESTRAS_POR_TROZO):
            trozo = en_linea[i:i + MUESTRAS_POR_TROZO]
            if len(trozo) < MUESTRAS_POR_TROZO:
                # El último trozo se completa con silencio en vez de mandarse
                # corto: un trozo a medias desalinea el reloj de la línea.
                trozo = np.concatenate(
                    [trozo, np.zeros(MUESTRAS_POR_TROZO - len(trozo),
                                     dtype=np.float32)])
            mensajes.append({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": base64.b64encode(
                    g711.de_float(trozo)).decode("ascii")},
            })
        self.trozos_enviados += len(mensajes)
        # La marca va DETRÁS del audio: Twilio la devuelve cuando ha terminado
        # de reproducir todo lo anterior.
        mensajes.append({"event": "mark", "streamSid": self.stream_sid,
                         "mark": {"name": MARCA_FIN}})
        return mensajes

    def callar(self) -> dict:
        """Tirar lo que Twilio tenga en cola. Es la mitad del barge-in que sí
        depende de nosotros; la otra es decidir cuándo."""
        return {"event": "clear", "streamSid": self.stream_sid}


def twiml(url_stream: str) -> str:
    """El XML que Twilio pide al recibir la llamada, y que le dice a dónde
    conectarse. `Connect` y no `Start`: `Connect` es bidireccional —el agente
    tiene que poder hablar— y `Start` solo escucha."""
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Connect><Stream url="{url_stream}" /></Connect>'
            "</Response>")
