r"""La frase que el proyecto llevaba meses sin poder demostrar.

`app/vivo.py` dice en su cabecera que la pasarela no guarda nada suyo y que,
con el estado en Redis, **se pueden levantar N pasarelas y cualquiera atiende
cualquier turno**. Eso era verdad por diseño, que es una forma elegante de
decir que nadie lo había comprobado.

Esta prueba lo comprueba de la única manera que vale: **el primer turno lo
atiende una pasarela y el segundo otra distinta**, con objetos nuevos, sin nada
compartido en memoria, y la conversación sigue. Si alguien rompiera el traspaso
del estado, aquí el agente del segundo turno llegaría sin saber quién llamaba.

Lo que hace creíble el resultado es el modelo de mentira: registra la historia
exacta que le llega en cada petición. Así la comprobación no es "contestó algo
coherente" —que un modelo amable puede simular— sino "en la petición que hizo
la SEGUNDA pasarela estaban los mensajes del turno que atendió la PRIMERA".

No gasta cuota. Necesita Redis; sin él sale con código 2 y lo dice, porque un
verde que significa "no lo he mirado" es el error que este proyecto lleva trece
veces coleccionando.

  .\.venv\Scripts\python.exe -m app.prueba_estado
"""

from __future__ import annotations

import numpy as np

from app.agent.loop import Agente
from app.estado import URL_POR_DEFECTO, EnMemoria, EnRedis
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

class ModeloQueRecuerda:
    """Contesta lo que se le diga y guarda las historias que ha recibido."""

    def __init__(self, respuestas: list[str]) -> None:
        self.respuestas = list(respuestas)
        self.historias: list[list[dict]] = []
        self.chat = self._Chat(self)

    class _Chat:
        def __init__(self, dueno) -> None:
            self.completions = ModeloQueRecuerda._Completions(dueno)

    class _Completions:
        def __init__(self, dueno) -> None:
            self.dueno = dueno

        def create(self, **argumentos):
            self.dueno.historias.append(list(argumentos.get("messages") or []))
            texto = (self.dueno.respuestas.pop(0)
                     if self.dueno.respuestas else "De acuerdo.")
            return ModeloQueRecuerda._Respuesta(texto)

    class _Respuesta:
        def __init__(self, texto: str) -> None:
            self.choices = [ModeloQueRecuerda._Eleccion(texto)]
            self.usage = ModeloQueRecuerda._Uso()

    class _Eleccion:
        def __init__(self, texto: str) -> None:
            self.message = ModeloQueRecuerda._Mensaje(texto)

    class _Mensaje:
        def __init__(self, texto: str) -> None:
            self.content = texto
            self.tool_calls = None

    class _Uso:
        prompt_tokens = 100
        completion_tokens = 20
        total_tokens = 120


class ASRQueDicta:
    """Devuelve la frase que le toque, como si alguien la hubiera dicho."""

    def __init__(self, frases: list[str]) -> None:
        self.frases = list(frases)

    def transcribe(self, audio, **kwargs):
        texto = self.frases.pop(0) if self.frases else ""

        class Segmento:
            text = texto
            no_speech_prob = 0.05
            avg_logprob = -0.3
            compression_ratio = 1.1

        class Info:
            language_probability = 0.99

        return [Segmento()], Info()


class VozMuda:
    def synthesize(self, texto: str):
        return []


def audio_de_un_turno() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sala, voz y silencio: lo justo para que se abra y se cierre un turno."""
    generador = np.random.default_rng(11)
    sala = (generador.standard_normal(int(0.6 * FRECUENCIA)) * 0.001).astype(np.float32)
    voz = (generador.standard_normal(int(0.9 * FRECUENCIA)) * 0.05).astype(np.float32)
    silencio = np.zeros(int(0.5 * FRECUENCIA), dtype=np.float32)
    return sala, voz, silencio


def pasarela(frases: list[str], respuestas: list[str], expediente=None):
    """Una pasarela recién arrancada: objetos nuevos, nada compartido."""
    modelo = ModeloQueRecuerda(respuestas)
    agente = Agente(modelo, "modelo-de-mentira", "http://127.0.0.1:1/",
                    presupuesto_ms=15000)
    llamada = Llamada(ASRQueDicta(frases), VozMuda(), agente,
                      expediente=expediente)
    return llamada, agente, modelo


def un_turno(llamada: Llamada) -> list:
    sala, voz, silencio = audio_de_un_turno()
    llamada.empujar(sala)
    llamada.empujar(voz)
    return llamada.empujar(silencio)


# ------------------------------------------------------------------ pruebas

def prueba_dos_pasarelas(almacen) -> None:
    print("  el turno 1 en una pasarela y el turno 2 en OTRA")

    # --- pasarela A
    a, agente_a, modelo_a = pasarela(
        ["Buenas, mi cédula es el 1070234567."],
        ["Gracias. ¿Me confirma su nombre completo, por favor?"])
    avisos = un_turno(a)
    comprobar("la pasarela A cierra su turno",
              any(x.tipo == "oido" for x in avisos),
              str([x.tipo for x in avisos]))

    id_llamada = "llamada-de-prueba-0001"
    almacen.guardar(id_llamada, a.exportar_estado())
    comprobar("y guarda el estado sin fallos", almacen.fallos == 0,
              str(almacen.ultimo_error))

    # --- pasarela B: objetos nuevos, otro modelo, nada en común
    b, agente_b, modelo_b = pasarela(
        ["Juan Diego Ossa."],
        ["Verificado, señor Ossa."])
    comprobar("la pasarela B arranca sin saber nada",
              len(agente_b.historia) == 1 and agente_b.historia[0]["role"] == "system",
              str(len(agente_b.historia)))

    guardado = almacen.cargar(id_llamada)
    comprobar("el estado se recupera de Redis", guardado is not None)
    if guardado is None:
        return
    b.importar_estado(guardado)

    un_turno(b)
    comprobar("la pasarela B atiende el segundo turno",
              len(modelo_b.historias) >= 1, str(len(modelo_b.historias)))
    if not modelo_b.historias:
        return

    # LA comprobación: lo que la pasarela B le manda al modelo lleva dentro el
    # turno que atendió la pasarela A.
    ultima = modelo_b.historias[-1]
    texto_entero = " ".join(str(m.get("content") or "") for m in ultima)
    comprobar("y en SU petición está lo que dijo quien llamaba en el turno 1",
              "1070234567" in texto_entero,
              texto_entero[:160])
    comprobar("y también lo que contestó la pasarela A",
              "nombre completo" in texto_entero, texto_entero[:160])
    comprobar("el consumo acumulado viaja con la conversación",
              agente_b.tokens_entrada >= 100,
              f"entrada={agente_b.tokens_entrada}")
    comprobar("y lo que el agente estaba esperando, que sin él '70 234' es "
              "un número ambiguo",
              b.esperando == a.esperando, f"{b.esperando!r} vs {a.esperando!r}")


def prueba_el_prompt_no_viaja(almacen) -> None:
    """Lo que NO debe cruzar la frontera."""
    print("  el prompt del sistema NO viaja con el estado")
    a, agente_a, _ = pasarela(["Hola."], ["Buenas."])
    agente_a.historia[0] = {"role": "system", "content": "PROMPT VIEJO"}
    un_turno(a)
    almacen.guardar("llamada-prompt", a.exportar_estado())

    b, agente_b, _ = pasarela(["Sigo aquí."], ["Claro."])
    agente_b.historia[0] = {"role": "system", "content": "PROMPT NUEVO"}
    estado = almacen.cargar("llamada-prompt")
    assert estado is not None
    b.importar_estado(estado)

    comprobar("la pasarela nueva conserva SU prompt",
              agente_b.historia[0]["content"] == "PROMPT NUEVO",
              agente_b.historia[0]["content"])
    comprobar("y aun así hereda la conversación",
              any("Hola." in str(m.get("content")) for m in agente_b.historia[1:]),
              str(agente_b.historia))
    comprobar("y no se cuela un segundo prompt de sistema",
              sum(1 for m in agente_b.historia if m["role"] == "system") == 1,
              str([m["role"] for m in agente_b.historia]))


def prueba_los_intentos_de_documento_viajan(almacen) -> None:
    """Si esto se pierde, el agente vuelve a dar tres intentos al que ya los gastó."""
    print("  los documentos ya probados viajan (ADR del documento equivocado)")
    a, agente_a, _ = pasarela(["Hola."], ["Buenas."])
    agente_a.documentos_intentados = ["1070234567", "1070234568"]
    almacen.guardar("llamada-intentos", a.exportar_estado())

    b, agente_b, _ = pasarela([], [])
    estado = almacen.cargar("llamada-intentos")
    assert estado is not None
    b.importar_estado(estado)
    comprobar("la pasarela nueva sabe qué documentos ya fallaron",
              agente_b.documentos_intentados == ["1070234567", "1070234568"],
              str(agente_b.documentos_intentados))


def prueba_en_memoria_no_finge() -> None:
    """El almacén de respaldo tiene que confesar que no sirve para escalar."""
    print("  el almacén en memoria NO dice que sea compartido")
    comprobar("EnMemoria.compartido es False", EnMemoria().compartido is False)


def main() -> int:
    print("El estado de la llamada, fuera del proceso\n")
    prueba_en_memoria_no_finge()

    try:
        almacen = EnRedis(URL_POR_DEFECTO)
    except Exception as exc:  # noqa: BLE001
        print(f"\n  SALTADAS las pruebas de traspaso: no hay Redis "
              f"({type(exc).__name__}).")
        print("  Esto NO es verde: levántalo con  docker compose up -d  y repite.")
        print("\n  SIN COMPROBAR (código de salida 2)")
        return 2

    for prueba in (prueba_dos_pasarelas, prueba_el_prompt_no_viaja,
                   prueba_los_intentos_de_documento_viajan):
        try:
            prueba(almacen)
        except Exception as exc:  # noqa: BLE001
            comprobar(f"{prueba.__name__} termina sin reventar", False,
                      f"{type(exc).__name__}: {exc}")
    for clave in ("llamada-de-prueba-0001", "llamada-prompt", "llamada-intentos"):
        almacen.olvidar(clave)

    print(f"\n{'TODO BIEN' if not fallos else f'{fallos} FALLOS'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
