r"""Cortarle la palabra al agente: la métrica 6, sin micrófono y sin nadie delante.

El barge-in llevaba semanas marcado como "hace falta Juan Diego con el
micrófono", por dos razones que eran ciertas: sin cancelación de eco el
micrófono del portátil capta la propia voz del agente, y había que oírlo para
saber si funcionaba.

**El canal telefónico quita las dos.** La línea ya trae cancelación de eco, y el
emulador de Twilio permite mandar voz *mientras el agente habla* y mirar qué
pasa. Así que esto se comprueba entero aquí, determinista y sin coste.

Lo que se comprueba, y el orden importa:

 1. Que una interrupción de verdad **corta** al agente.
 2. Que un ruido corto **no** lo corta. Es la mitad que se olvida: un sistema
    que se calla cada vez que alguien carraspea es peor que uno que no se calla
    nunca, porque no se puede ni terminar una frase.
 3. Que **no se pierde lo que la persona dijo** al interrumpir. Si se tirara, el
    turno nuevo empezaría a media palabra y quien interrumpe tendría que
    repetirlo todo.
 4. Que por la línea se manda `clear`, que es lo que hace que el corte se note:
    sin él el agente se calla por dentro y sigue sonando por el teléfono.
 5. Que en el navegador **sigue apagado**, porque ahí el eco lo rompería.

  .\.venv\Scripts\python.exe -m app.prueba_interrupcion
"""

from __future__ import annotations

import numpy as np

from app.telefonia import MUESTRAS_POR_TROZO as MUESTRAS_LINEA  # noqa: F401
from app.vivo import FRECUENCIA, MS_PARA_INTERRUMPIR, Llamada

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}")
    else:
        fallos += 1
        print(f"    FALLA  {nombre}" + (f" -> {detalle}" if detalle else ""))


# ------------------------------------------------------------------- dobles

class ASRQueDicta:
    def __init__(self, frases: list[str]) -> None:
        self.frases = list(frases)
        self.duraciones: list[float] = []

    def transcribe(self, audio, **kwargs):
        self.duraciones.append(len(audio) / FRECUENCIA)
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
    class _Trozo:
        def __init__(self) -> None:
            generador = np.random.default_rng(5)
            self.audio_int16_bytes = (
                generador.standard_normal(22050) * 0.2 * 32767
            ).astype(np.int16).tobytes()
            self.sample_rate = 22050

    def synthesize(self, texto: str):
        return [self._Trozo()]


class AgenteQueContesta:
    def turno(self, dicho, al_hablar=None, **kwargs):
        if al_hablar:
            al_hablar("Su tarjeta de débito está bloqueada desde el quince.",
                      "respuesta")

        class T:
            texto = "Su tarjeta de débito está bloqueada desde el quince."
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


def voz(ms: int, semilla: int = 7) -> np.ndarray:
    generador = np.random.default_rng(semilla)
    n = int(FRECUENCIA * ms / 1000)
    return (generador.standard_normal(n) * 0.05).astype(np.float32)


def silencio(ms: int) -> np.ndarray:
    return np.zeros(int(FRECUENCIA * ms / 1000), dtype=np.float32)


def llamada_hablando(frases: list[str], permitir: bool = True):
    """Una llamada que ya ha contestado un turno, o sea: con el agente hablando."""
    llamada = Llamada(ASRQueDicta(frases), VozQueSuena(), AgenteQueContesta(),
                      permitir_interrupcion=permitir)
    llamada.empujar(silencio(200))
    llamada.empujar(voz(800))
    avisos = llamada.empujar(silencio(500))
    dijo = [a for a in avisos if a.tipo == "dice"]
    llamada.hablando = bool(dijo)      # es lo que hace la pasarela al enviar
    return llamada, avisos


# ------------------------------------------------------------------ pruebas

def prueba_una_interrupcion_corta_al_agente() -> None:
    print("  hablar encima del agente le corta la palabra")
    llamada, _ = llamada_hablando(["Mi cédula es 1070234567.", "Espere, espere."])
    comprobar("el agente estaba hablando", llamada.hablando is True)

    avisos = llamada.empujar(voz(600, semilla=9))      # 600 > 400
    cortes = [a for a in avisos if a.tipo == "interrumpido"]
    comprobar("se avisa de la interrupción", len(cortes) == 1, str(avisos))
    comprobar("y el agente deja de estar hablando", llamada.hablando is False)
    if cortes:
        comprobar("con los milisegundos de voz que la provocaron",
                  cortes[0].datos["ms_de_voz"] >= MS_PARA_INTERRUMPIR,
                  str(cortes[0].datos))
        comprobar("y contada, para poder medir cuántas veces pasa",
                  llamada.interrupciones == 1)


def prueba_un_ruido_corto_no_corta() -> None:
    """La mitad que se olvida."""
    print("  un carraspeo NO le corta la palabra")
    llamada, _ = llamada_hablando(["Hola."])
    avisos = llamada.empujar(voz(200, semilla=11))     # un carraspeo: 200 < 400
    comprobar("no se interrumpe", not [a for a in avisos if a.tipo == "interrumpido"],
              str(avisos))
    comprobar("y el agente sigue hablando", llamada.hablando is True)

    print("  ni dos ruiditos separados que sumen lo mismo")
    llamada2, _ = llamada_hablando(["Hola."])
    for _ in range(3):
        llamada2.empujar(voz(200, semilla=13))
        llamada2.empujar(silencio(100))       # la racha se rompe aquí
    comprobar("tres sílabas sueltas no bastan", llamada2.hablando is True,
              f"interrupciones={llamada2.interrupciones}")


def prueba_no_se_pierde_lo_que_dijo() -> None:
    """La comprobación tiene que ser por DURACIÓN y con la cuenta hecha.

    La primera versión de esta prueba miraba que el turno nuevo durase más de
    medio segundo, y eso lo cumplía el audio que se empuja DESPUÉS de la
    interrupción él solo. Se tiró a propósito el audio recuperado y la prueba
    siguió verde: comprobaba algo cierto que no era lo que decía comprobar.

    Ahora la cuenta está escrita: interrumpen con 600 ms, después se empujan
    300 más y 500 de silencio. Con el audio recuperado el turno pasa de 1,2 s;
    sin él se queda en 0,8. El corte en 1,0 distingue los dos casos y no hay
    forma de que pase por accidente.
    """
    print("  lo que la persona dice al interrumpir NO se pierde")
    llamada, _ = llamada_hablando(["Primer turno.", "Espere, mi cédula es otra."])
    asr = llamada.asr

    avisos = llamada.empujar(voz(600, semilla=17))
    cortes = [a for a in avisos if a.tipo == "interrumpido"]
    comprobar("se recuperó el audio de la interrupción",
              bool(cortes) and cortes[0].datos["muestras_recuperadas"] > 0,
              str(cortes[0].datos) if cortes else "sin corte")

    llamada.empujar(voz(300, semilla=17))
    llamada.empujar(silencio(500))
    comprobar("el turno nuevo llegó a transcribirse", len(asr.duraciones) == 2,
              str(asr.duraciones))
    if len(asr.duraciones) == 2:
        comprobar("y lleva DENTRO los 600 ms de la interrupción",
                  asr.duraciones[1] > 1.0,
                  f"{asr.duraciones[1]:.2f} s: sin el audio recuperado serían 0,8")


def prueba_el_navegador_sigue_sordo_a_proposito() -> None:
    print("  en el navegador sigue apagado, que es lo correcto sin eco cancelado")
    llamada, _ = llamada_hablando(["Hola."], permitir=False)
    avisos = llamada.empujar(voz(1000, semilla=19))
    comprobar("no se interrumpe por mucho que se hable", avisos == [], str(avisos))
    comprobar("y el agente sigue hablando", llamada.hablando is True)
    comprobar("sin contar interrupciones", llamada.interrupciones == 0)


def prueba_por_la_linea_se_manda_clear() -> None:
    """Lo que hace que el corte se note al otro lado del teléfono."""
    print("  por la línea se manda `clear` para tirar el audio en cola")
    import base64  # noqa: PLC0415

    from app.telefonia import PuenteTwilio, g711
    from app.telefonia.media_streams import a_frecuencia

    llamada = Llamada(ASRQueDicta(["Mi cédula es 1070234567.", "Espere."]),
                      VozQueSuena(), AgenteQueContesta(),
                      permitir_interrupcion=True)
    puente = PuenteTwilio(llamada)
    puente.al_recibir({"event": "start", "streamSid": "MZ1",
                       "start": {"mediaFormat": {"encoding": "audio/x-mulaw",
                                                 "sampleRate": 8000,
                                                 "channels": 1}}})

    def por_la_linea(muestras: np.ndarray) -> list[dict]:
        """Mandar audio como lo mandaría Twilio: µ-law de 8 kHz en base64."""
        en_linea = a_frecuencia(muestras, FRECUENCIA, 8000)
        salida: list[dict] = []
        for i in range(0, len(en_linea), MUESTRAS_LINEA):
            trozo = en_linea[i:i + MUESTRAS_LINEA]
            if len(trozo) < MUESTRAS_LINEA:
                break
            salida.extend(puente.al_recibir({
                "event": "media", "streamSid": "MZ1",
                "media": {"payload": base64.b64encode(
                    g711.de_float(trozo)).decode("ascii")}}))
        return salida

    por_la_linea(silencio(200))
    por_la_linea(voz(800))
    respuesta = por_la_linea(silencio(500))
    comprobar("el agente contestó por la línea",
              any(m.get("event") == "media" for m in respuesta),
              str([m.get("event") for m in respuesta][:5]))
    comprobar("y quedó marcado como hablando", llamada.hablando is True)

    # Y ahora se le habla encima.
    durante = por_la_linea(voz(600, semilla=23))
    eventos = [m.get("event") for m in durante]
    comprobar("se manda `clear` a Twilio", "clear" in eventos, str(eventos[:6]))
    comprobar("el puente cuenta la interrupción", puente.interrupciones == 1,
              str(puente.interrupciones))
    comprobar("y el `clear` va con su streamSid",
              all(m.get("streamSid") == "MZ1"
                  for m in durante if m.get("event") == "clear"))


def prueba_los_numeros_de_la_prueba_siguen_valiendo() -> None:
    """Las duraciones de este archivo son fijas —600 ms para interrumpir, 200
    para no— y solo significan algo si el umbral sigue entre las dos.

    Se escriben fijas y no como `MS_PARA_INTERRUMPIR ± algo` por una razón que
    se vio al romper el código a propósito: derivadas del parámetro, bajar el
    umbral a 100 hacía que la prueba pidiera audio de duración negativa y
    reventara con un `ValueError`. Una prueba que explota en vez de fallar no
    dice qué está mal. Así, si alguien mueve el umbral, esto lo avisa aquí y
    las demás comprobaciones siguen significando lo que dicen.
    """
    print("  las duraciones de esta prueba siguen teniendo sentido")
    comprobar("600 ms interrumpen y 200 no, con el umbral actual",
              200 < MS_PARA_INTERRUMPIR < 600,
              f"MS_PARA_INTERRUMPIR = {MS_PARA_INTERRUMPIR}: hay que revisar "
              f"las duraciones de este archivo")


def main() -> int:
    print("Interrumpir al agente (métrica 6), por el canal telefónico\n")
    for prueba in (prueba_los_numeros_de_la_prueba_siguen_valiendo,
                   prueba_una_interrupcion_corta_al_agente,
                   prueba_un_ruido_corto_no_corta,
                   prueba_no_se_pierde_lo_que_dijo,
                   prueba_el_navegador_sigue_sordo_a_proposito,
                   prueba_por_la_linea_se_manda_clear):
        try:
            prueba()
        except Exception as exc:  # noqa: BLE001
            comprobar(f"{prueba.__name__} termina sin reventar", False,
                      f"{type(exc).__name__}: {exc}")
    print(f"\n{'TODO BIEN' if not fallos else f'{fallos} FALLOS'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
