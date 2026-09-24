r"""El bucle del agente: decidir, llamar herramientas, recuperarse, responder.

Lo que este bucle tiene y un chatbot con voz no:

  · **Trabaja contra un reloj.** Cada turno lleva un presupuesto. Si se agota
    a mitad, el agente no se queda pensando: dice algo y sigue.
  · **No afirma nada que no venga de una herramienta.** La regla está en el
    prompt, pero el prompt no basta: el expediente guarda qué devolvió cada
    herramienta, así que lo afirmado se puede contrastar después. Una regla
    que no se puede comprobar no es una regla, es un deseo.
  · **Cuando una herramienta falla, no inventa ni cuelga.** Se lo dice al
    modelo como resultado de la herramienta, y el modelo decide: reintentar,
    preguntar otra cosa, o escalar a un humano. Escalar es admitir lo que no
    se sabe, y es una salida legítima, no un fracaso.
  · **Idempotencia.** Cada turno lleva una clave. Si se reintenta, las
    acciones con efecto no se ejecutan dos veces.

Deja un `rastro`: cada paso con su instante, la herramienta llamada, los
argumentos, lo que devolvió y cuánto tardó. Eso es el expediente.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# `numeros_es` vive con las sondas: es la misma pieza que normaliza los
# numeros dichos en voz alta, y duplicarla seria tener dos verdades.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "probe"))

# La regla de "no afirmes lo que no venga de una herramienta" estaba escrita
# solo para los DATOS, y una acción no es un dato. Por ese hueco salió, el
# 2026-09-23 y sin llamar a nada: "He bloqueado todas sus tarjetas y cuentas...
# llame al 01 8000 1234". Ni existe herramienta que bloquee, ni existe ese
# teléfono. Así que ahora se nombran las tres cosas por separado —datos,
# acciones y procedimientos— y se dice explícitamente qué herramientas hay, que
# es lo que convierte "no puedes bloquear" en algo comprobable por el propio
# modelo y no en una prohibición abstracta.
#
# Y el prompt no basta, por definición: es una petición, no una garantía. Lo
# que lo convierte en regla es `app/agent/fundamento.py`, que compara lo dicho
# con lo que devolvieron las herramientas.
SISTEMA = (
    "Agente telefónico de un banco colombiano. Frases cortas: esto se habla. "
    "No afirmes ningún dato que no venga de una herramienta. Si dudas de lo que "
    "oíste, pide que lo repitan. Antes de dar información de una cuenta, "
    "verifica la identidad con el documento. Si una herramienta falla, no "
    "inventes: escala a un humano. "
    "NUNCA digas el nombre del titular ni ningún otro dato de la cuenta antes "
    "de haber verificado la identidad: pregúntalo y compáralo en silencio. "
    "Quien llama tiene que demostrar quién es, no confirmar lo que tú ya le "
    "has dicho. "
    "TAMPOCO TE ATRIBUYAS ACCIONES. Solo tienes tres herramientas: consultar "
    "una identidad, consultar el estado de una tarjeta y pasar la llamada a un "
    "asesor humano. No puedes bloquear, desbloquear, cancelar, reversar ni "
    "cambiar nada, así que no digas que lo has hecho ni que vas a hacerlo. "
    "Decir que la tarjeta ESTÁ bloqueada, si lo devolvió la herramienta, es "
    "correcto; decir que TÚ la has bloqueado es falso. "
    "Y no inventes procedimientos: ni teléfonos, ni horarios, ni plazos, ni "
    "requisitos, ni papeles que haya que llevar a una oficina. Si no lo ha "
    "devuelto una herramienta, no lo sabes. Cuando lo que piden necesita una "
    "acción que no tienes, dilo en una frase y pasa la llamada a un asesor. "
    "SI UN DOCUMENTO NO APARECE, no te rindas a la primera: pide que lo "
    "repitan dígito a dígito. Al teléfono la gente se equivoca y tú puedes "
    "haber oído mal. La herramienta te dice en `_intentos_en_esta_llamada` "
    "cuántos documentos distintos van fallando y en `_que_hacer` qué toca; "
    "hazle caso a eso y no a tu impresión."
)

HERRAMIENTAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_identidad",
            "description": "Busca un cliente por documento.",
            "parameters": {
                "type": "object",
                "properties": {"documento": {"type": "string"}},
                "required": ["documento"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estado_tarjeta",
            "description": "Estado de la tarjeta de un cliente verificado.",
            "parameters": {
                "type": "object",
                "properties": {"id_cliente": {"type": "string"}},
                "required": ["id_cliente"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalar_a_humano",
            "description": "Pasa la llamada a un asesor humano.",
            "parameters": {
                "type": "object",
                "properties": {"motivo": {"type": "string"}},
                "required": ["motivo"],
            },
        },
    },
]

# Acciones con efecto: llevan clave de idempotencia. Consultar no la necesita
# —preguntar dos veces no rompe nada— pero abrir un ticket sí.
CON_EFECTO = {"escalar_a_humano"}

# Herramientas que se pueden disparar ANTES de que el modelo las pida.
# Solo las de lectura pura: preguntar dos veces por un documento no cambia
# nada, y si el modelo acaba no pidiéndola, lo único que se pierde es una
# consulta. Ninguna con efecto entra aquí, y no por prudencia: adelantar una
# escalada sería abrir un ticket que nadie pidió.
ADELANTABLES = {"consultar_identidad"}

# Un documento colombiano dicho en voz alta y ya normalizado a cifras. Entre
# seis y once dígitos seguidos: por debajo es un importe o una hora, por
# encima no es un documento.
PATRON_DOCUMENTO = re.compile(r"\b(\d{6,11})\b")

# Lo que dice el agente mientras una herramienta corre.
#
# Existe porque el turno con herramienta son dos llamadas al modelo con una
# consulta en medio, y medido de punta a punta eso son 1267 ms de silencio. Una
# persona al teléfono no aguanta un segundo y medio de nada sin pensar que se
# cortó la llamada.
#
# La frase es verdad: el agente **está** consultando. Si fuera mentira sería
# peor que el silencio.
#
# Y tiene un coste que hay que decir: usada en todos los turnos suena a relleno
# y delata que el sistema es lento. Por eso solo se emite cuando el modelo
# decide llamar a una herramienta en su PRIMER paso, que es el caso en que se
# sabe que va a haber espera.
FRASE_PUENTE = "Permítame un momento, lo estoy revisando."

# Un turno vacío no es un turno.
#
# La transcripción de un silencio es la cadena vacía, y hasta el 2026-09-24
# llegaba al modelo como un turno normal. El modelo, obediente, contestaba a la
# nada con un saludo completo: "¡Hola! Soy el asistente virtual del banco. Para
# poder ayudarle, necesito verificar su identidad. ¿Podría indicarme su número
# de documento?" — a alguien que no ha dicho nada. Sale igual en las tres
# corridas del caso `silencio-total`, o sea que no es ruido: es el
# comportamiento.
#
# Se arregla antes del modelo, y no solo por elegancia: al teléfono, el silencio
# es información —se cortó la llamada, la persona se apartó, el micrófono está
# muteado— y la respuesta correcta no depende de nada que haya que razonar. Es
# siempre la misma, así que no hace falta gastar un modelo, ni un token, ni
# esperar 2,4 segundos para decirla.
#
# Lo que NO se arregla aquí: Whisper a veces alucina sobre el silencio y
# devuelve "Gracias." o un trozo de subtítulos. Eso no es una cadena vacía y
# este guardia no lo ve. Queda anotado como lo que falta.
# Lo que dice el agente cuando el que falla es el proveedor del modelo. Es una
# constante y no un literal suelto porque las pruebas necesitan reconocerla:
# cuando el modelo revienta, el agente escala a un humano —que es lo correcto—
# y entonces "contesta algo" y "llama a alguna herramienta" se cumplen solas.
# Sin poder distinguir esta frase, un 429 del plan gratuito sale VERDE en la
# prueba de la pasarela, y verde no puede significar "no lo he mirado".
TEXTO_FALLO_DEL_MODELO = ("Disculpe, tuve un problema técnico. "
                          "Le paso con un asesor.")

# Cuántos documentos DISTINTOS se prueban antes de pasar a un humano. Tres,
# que es lo que hace un banco de verdad y lo que aguanta una persona: el
# primero puede ser un dígito mal dicho, el segundo un dígito mal oído, y al
# tercero ya no es un despiste.
DOCUMENTOS_ANTES_DE_ESCALAR = 3

PREGUNTAS_POR_SILENCIO = [
    "¿Sigue ahí? No le escucho.",
    "Sigo sin escucharle. Si me oye, dígame algo, por favor.",
]

# Al tercero se pasa a un humano. Dos preguntas son insistir; tres son
# encerrar a alguien en un bucle con una máquina que no le oye. Y se escala de
# verdad, con su ticket: el ADR 0005 está para no volver a prometer lo que no
# se hace.
SILENCIOS_ANTES_DE_ESCALAR = len(PREGUNTAS_POR_SILENCIO) + 1


def es_silencio(dicho: str) -> bool:
    """¿Esto que llegó del ASR es 'nada'?

    No basta con `not dicho`: el ASR devuelve espacios, y a veces un punto o
    una coma sueltos. Lo que decide es si hay alguna letra o algún dígito.
    """
    return not any(c.isalnum() for c in dicho)


def _consumo(respuesta) -> tuple[int, int]:
    """Tokens de entrada y de salida de una respuesta del modelo.

    Groq los pone en `usage` cuando la respuesta no va en streaming, y en
    `x_groq.usage` cuando sí (ahí llegan en el último trozo). Se miran los dos
    sitios porque el bucle podría pasar a streaming cualquier día, y un
    contador que devuelve cero en silencio es peor que no tenerlo: el coste
    saldría gratis y nadie lo dudaría.
    """
    for fuente in (getattr(respuesta, "usage", None),
                   getattr(getattr(respuesta, "x_groq", None), "usage", None)):
        if fuente is None:
            continue
        entrada = getattr(fuente, "prompt_tokens", None)
        salida = getattr(fuente, "completion_tokens", None)
        if entrada is not None or salida is not None:
            return int(entrada or 0), int(salida or 0)
    return 0, 0


@dataclass
class Paso:
    """Una cosa que pasó en el turno, con su instante y su duración."""
    tipo: str            # "modelo" | "herramienta" | "limite" | "silencio"
    detalle: str
    ms: float
    argumentos: dict | None = None
    resultado: dict | None = None
    error: str | None = None
    tokens_entrada: int = 0
    tokens_salida: int = 0


@dataclass
class Turno:
    texto: str = ""
    rastro: list[Paso] = field(default_factory=list)
    ms_primer_hablable: float | None = None
    ms_total: float = 0.0
    agotado: bool = False
    silencio: int = 0             # si fue un turno vacío, el cuántos seguidos
    tokens_entrada: int = 0
    tokens_salida: int = 0
    peticiones: int = 0           # llamadas al modelo que costaron dinero
    puente: str = ""              # lo que se dijo mientras la herramienta corría
    adelantada: bool = False      # se disparó una consulta antes de que el modelo la pidiera
    adelantos_usados: int = 0     # cuántas de esas consultas acabó usando el modelo
    ms_puente: float | None = None
    clave: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def resumen(self) -> str:
        llamadas = [p for p in self.rastro if p.tipo == "herramienta"]
        return (f"{len(llamadas)} llamada(s) a herramienta, "
                f"{self.ms_total:.0f} ms en total"
                + (", PRESUPUESTO AGOTADO" if self.agotado else ""))


class Agente:
    def __init__(self, cliente_groq, modelo: str, base_herramientas: str,
                 presupuesto_ms: float = 3000.0, adelantar: bool = False,
                 tardanza_herramienta_ms: int = 0,
                 sistema: str = SISTEMA) -> None:
        self.groq = cliente_groq
        self.modelo = modelo
        self.base = base_herramientas.rstrip("/")
        self.presupuesto_ms = presupuesto_ms
        # El prompt entra por parámetro para poder correr los mismos casos con
        # dos versiones el mismo día. Cambiar el prompt cambia a la vez lo que
        # el agente decide y lo que tarda en decidirlo, y sin poder alternar
        # entre los dos no hay forma de separar las dos cosas.
        self.historia: list[dict] = [{"role": "system", "content": sistema}]
        self.adelantar = adelantar
        # Lo que tardaría un core bancario de verdad. La herramienta de mentira
        # contesta en 5 ms, y con eso el problema que se quiere medir no existe.
        self.tardanza_ms = tardanza_herramienta_ms
        self._adelantadas: dict[tuple, dict] = {}
        self._hilos_vivos: list = []
        # Silencios seguidos. Se pone a cero en cuanto alguien dice algo: dos
        # silencios con una frase en medio son dos incidentes, no una racha.
        self.silencios = 0
        # Y el consumo de TODA la conversación, que es la unidad en la que se
        # factura una llamada. Por turno no dice nada: lo que le cuesta a un
        # banco es la llamada entera, y crece más que linealmente porque cada
        # turno reenvía la historia anterior.
        self.tokens_entrada = 0
        self.tokens_salida = 0
        self.peticiones = 0
        # Los documentos distintos que se han probado y no aparecen. Van por
        # conversación y no por turno: quien llama se equivoca en un turno y
        # se corrige en el siguiente.
        self.documentos_intentados: list[str] = []

    # ------------------------------------------------------ adelantar consulta

    def _lanzar_adelantada(self, dicho: str, clave: str):
        """Dispara `consultar_identidad` sin esperar a que el modelo la pida.

        Si en lo que dijo la persona hay algo con forma de documento, la
        consulta puede salir YA, en paralelo con la primera llamada al modelo,
        en vez de detrás. Cuando el modelo la pida, el resultado ya está.

        La apuesta se pierde a veces —quien llama dice un número que no era su
        documento, o el modelo decide preguntar otra cosa— y entonces se ha
        gastado una consulta de lectura para nada. Ese es todo el coste, y por
        eso solo se adelantan herramientas sin efecto.
        """
        if not self.adelantar:
            return None
        from numeros_es import normalizar

        encontrado = PATRON_DOCUMENTO.search(normalizar(dicho))
        if not encontrado:
            return None
        documento = encontrado.group(1)
        llave = ("consultar_identidad", documento)

        def trabajo() -> None:
            resultado, ms = self._llamar(
                "consultar_identidad", {"documento": documento}, clave)
            self._adelantadas[llave] = {"resultado": resultado, "ms": ms}

        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()
        return hilo

    # ------------------------------------------------------------ herramientas

    def _ejecutar(self, nombre: str, argumentos: dict, clave: str) -> tuple[dict, float]:
        """Devuelve el resultado, usando el adelantado si lo hay."""
        if nombre in ADELANTABLES:
            llave = (nombre, "".join(c for c in str(argumentos.get("documento", ""))
                                     if c.isdigit()))
            # Puede estar ya hecha, o estar corriendo. En el segundo caso se
            # espera a que acabe: aun así se ha ganado todo el tiempo que
            # llevaba en marcha mientras el modelo pensaba.
            for _ in range(200):
                if llave in self._adelantadas:
                    hecho = self._adelantadas.pop(llave)
                    return hecho["resultado"], 0.0
                if not any(h.is_alive() for h in self._hilos_vivos):
                    break
                time.sleep(0.005)
        return self._llamar(nombre, argumentos, clave)

    def _anotar_intentos(self, nombre: str, argumentos: dict,
                         resultado: dict) -> dict:
        """Le dice al modelo cuántos documentos van fallando en esta llamada.

        El caso `documento-mal-dos-veces` falla igual en las seis corridas de
        los dos prompts, así que no es ruido: **el agente escala al PRIMER
        documento que no aparece, y abre un ticket.** Al teléfono la gente se
        equivoca de dígito —y el ASR también—, así que rendirse a la primera es
        peor servicio, y el ticket tiene efecto: alguien tiene que atenderlo.

        La decisión no se deja en manos del prompt solo, porque el prompt no
        sabe contar: cuando la herramienta dice "no lo encuentro", el modelo no
        tiene forma de saber si es el primer intento o el tercero. Un turno
        posterior ve la historia, sí, pero interpretarla es justo lo que hace
        mal. Así que el dato se le da masticado, y contado por quien puede
        contarlo.

        Se cuentan documentos DISTINTOS, no llamadas: repetir la misma cédula
        —porque el adelanto ya la consultó, o porque el modelo insiste— no es
        un intento nuevo de la persona.

        Los campos van con `_` delante para que se vea que los pone el agente y
        no el core bancario. Inventarse campos con pinta de datos del banco
        sería, precisamente, lo que el ADR 0005 prohíbe.
        """
        if nombre != "consultar_identidad" or resultado.get("encontrado"):
            return resultado
        if resultado.get("error"):
            # La herramienta se cayó; eso no es un documento equivocado y
            # contarlo como intento haría escalar por el motivo que no es.
            return resultado
        documento = "".join(c for c in str(argumentos.get("documento", ""))
                            if c.isdigit())
        if documento and documento not in self.documentos_intentados:
            self.documentos_intentados.append(documento)
        intentos = len(self.documentos_intentados)
        anotado = dict(resultado)
        anotado["_intentos_en_esta_llamada"] = intentos
        anotado["_intentos_antes_de_escalar"] = DOCUMENTOS_ANTES_DE_ESCALAR
        if intentos < DOCUMENTOS_ANTES_DE_ESCALAR:
            anotado["_que_hacer"] = (
                "Pídele que repita el documento dígito a dígito. NO escales "
                "todavía: al teléfono equivocarse una vez es normal.")
        else:
            anotado["_que_hacer"] = (
                "Ya van demasiados documentos distintos sin encontrar. Ahora "
                "sí: pasa la llamada a un asesor humano.")
        return anotado

    def _llamar(self, nombre: str, argumentos: dict, clave: str) -> tuple[dict, float]:
        cuerpo = dict(argumentos)
        if nombre in CON_EFECTO:
            cuerpo["clave_idempotencia"] = clave
        cabeceras = {}
        if self.tardanza_ms:
            cabeceras["X-Tardar-Ms"] = str(self.tardanza_ms)
        arranque = time.perf_counter()
        try:
            with httpx.Client(timeout=10) as c:
                r = c.post(f"{self.base}/{nombre}", json=cuerpo, headers=cabeceras)
            ms = (time.perf_counter() - arranque) * 1000
            if r.status_code >= 400:
                # Al modelo se le dice que falló, no se le oculta. Es él quien
                # decide qué hacer, y para eso necesita saberlo.
                return {"error": f"la herramienta respondió {r.status_code}",
                        "reintentable": r.status_code >= 500}, ms
            return r.json(), ms
        except Exception as exc:  # noqa: BLE001
            ms = (time.perf_counter() - arranque) * 1000
            return {"error": f"no se pudo llamar a la herramienta: "
                             f"{type(exc).__name__}", "reintentable": True}, ms

    def _preguntar_al_modelo(self, reintentos: int = 1):
        """Una petición al modelo, con un reintento para los fallos de forma.

        Los `tool_use_failed` son del generador, no de la red: el modelo emitió
        una llamada a herramienta que no valida. Volver a pedirlo suele salir
        bien porque la temperatura no es cero. Un solo reintento: dos ya se
        comen el presupuesto del turno, y para eso está la salida a un humano.
        """
        ultimo = None
        for intento in range(reintentos + 1):
            try:
                return self.groq.chat.completions.create(
                    model=self.modelo,
                    messages=self.historia,
                    tools=HERRAMIENTAS,
                    tool_choice="auto",
                    temperature=0.2,
                    max_tokens=400,
                    reasoning_effort="low",
                )
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                if "tool_use_failed" not in str(exc):
                    raise
        raise ultimo

    # ------------------------------------------------------------------ turno

    def turno(self, dicho: str, max_pasos: int = 4, al_hablar=None) -> Turno:
        """Un turno completo: lo que dijo la persona, lo que contesta el agente.

        `al_hablar` se llama en cuanto hay algo que se pueda pronunciar, que no
        siempre es la respuesta. Si el modelo decide consultar una herramienta,
        lo primero que hay que decir es la frase puente, y la respuesta buena
        llega después. Quien mida esto tiene que quedarse con los dos
        instantes, no solo con el primero.
        """
        turno = Turno()
        arranque = time.perf_counter()

        # Antes que nada: si no ha llegado nada, esto no es un turno. No se
        # llama al modelo, no se ensucia la historia con un mensaje vacío, y
        # se contesta lo único que se puede contestar a un silencio. Cuesta
        # cero tokens y cero espera.
        if es_silencio(dicho):
            self.silencios += 1
            turno.silencio = self.silencios
            if self.silencios >= SILENCIOS_ANTES_DE_ESCALAR:
                turno.texto = ("No consigo escucharle. Le paso con un asesor "
                               "para que le devuelva la llamada.")
                resultado, ms = self._llamar(
                    "escalar_a_humano",
                    {"motivo": f"{self.silencios} silencios seguidos"},
                    turno.clave)
                turno.rastro.append(Paso("herramienta", "escalar_a_humano", ms,
                                         argumentos={"motivo": "silencio"},
                                         resultado=resultado,
                                         error=resultado.get("error")))
            else:
                turno.texto = PREGUNTAS_POR_SILENCIO[self.silencios - 1]
            turno.rastro.insert(0, Paso("silencio",
                                        f"turno vacío ({self.silencios})",
                                        0.0))
            # La historia NO se toca: no se dijo nada, así que para el modelo
            # del turno siguiente no ha pasado nada. Meter aquí el mensaje
            # vacío y la pregunta sería enseñarle a conversar con el silencio.
            if al_hablar:
                al_hablar(turno.texto, "respuesta")
            turno.ms_primer_hablable = (time.perf_counter() - arranque) * 1000
            turno.ms_total = turno.ms_primer_hablable
            return turno

        # Alguien ha dicho algo: la racha de silencios se acabó.
        self.silencios = 0

        # Lo primero, antes incluso de preguntarle al modelo: si en lo que
        # dijo la persona ya hay un documento, la consulta sale ahora y corre
        # en paralelo con la decision del modelo.
        hilo = self._lanzar_adelantada(dicho, turno.clave)
        if hilo is not None:
            self._hilos_vivos = [hilo]
            turno.adelantada = True

        self.historia.append({"role": "user", "content": dicho})
        paso = 0

        for _ in range(max_pasos):
            paso += 1
            transcurrido = (time.perf_counter() - arranque) * 1000
            if transcurrido > self.presupuesto_ms:
                # El reloj manda. Decir algo tarde es peor que decir poco a
                # tiempo, y callarse es lo peor de todo.
                turno.agotado = True
                turno.rastro.append(Paso("limite", "presupuesto del turno agotado",
                                         transcurrido))
                turno.texto = ("Permítame un momento, por favor, sigo "
                               "verificando la información.")
                break

            t0 = time.perf_counter()
            try:
                respuesta = self._preguntar_al_modelo()
            except Exception as exc:  # noqa: BLE001
                # El modelo puede generar una llamada a herramienta mal formada
                # —vista de verdad: `functions/escalar_a_humano` con el prefijo
                # pegado— y entonces la API devuelve un 400 y se lleva el turno
                # por delante. Un fallo del proveedor no puede dejar a alguien
                # escuchando silencio al teléfono: se anota y se sale por la
                # salida honesta, que es un humano.
                turno.rastro.append(Paso("modelo", "el modelo falló",
                                         (time.perf_counter() - t0) * 1000,
                                         error=f"{type(exc).__name__}: {exc}"))
                turno.texto = TEXTO_FALLO_DEL_MODELO
                resultado, ms = self._llamar("escalar_a_humano",
                                             {"motivo": "fallo del modelo"},
                                             turno.clave)
                turno.rastro.append(Paso("herramienta", "escalar_a_humano", ms,
                                         argumentos={"motivo": "fallo del modelo"},
                                         resultado=resultado))
                if al_hablar:
                    al_hablar(turno.texto, "respuesta")
                break
            ms_modelo = (time.perf_counter() - t0) * 1000
            mensaje = respuesta.choices[0].message
            # El consumo viene en la respuesta y hasta el 2026-09-24 nadie lo
            # leía. Es la métrica 5 —coste por conversación— casi gratis: los
            # tokens son un hecho que devuelve el proveedor, y lo único que
            # hay que añadir después es el precio.
            #
            # Se anota por PASO y no solo por turno, porque un turno con
            # herramienta son dos llamadas y la segunda lleva dentro todo lo
            # que devolvió la herramienta: si el core bancario contesta un
            # JSON grande, el coste se va por ahí y en el total no se ve.
            entrada, salida = _consumo(respuesta)
            turno.rastro.append(Paso("modelo",
                                     "decide llamar herramienta" if mensaje.tool_calls
                                     else "contesta",
                                     ms_modelo,
                                     tokens_entrada=entrada,
                                     tokens_salida=salida))
            turno.tokens_entrada += entrada
            turno.tokens_salida += salida
            turno.peticiones += 1
            self.tokens_entrada += entrada
            self.tokens_salida += salida
            self.peticiones += 1
            if turno.ms_primer_hablable is None:
                turno.ms_primer_hablable = (time.perf_counter() - arranque) * 1000

            # `tool_calls` se omite si no hay ninguna. Poner null ahí lo
            # rechaza la API con un 400, y no se veía en pruebas de un solo
            # turno porque ese mensaje nunca se reenviaba. Lo destapó la
            # primera conversación de dos turnos.
            anotacion: dict = {"role": "assistant", "content": mensaje.content or ""}
            if mensaje.tool_calls:
                anotacion["tool_calls"] = [
                    {"id": t.id, "type": "function",
                     "function": {"name": t.function.name,
                                  "arguments": t.function.arguments}}
                    for t in mensaje.tool_calls
                ]
            self.historia.append(anotacion)

            if not mensaje.tool_calls:
                turno.texto = (mensaje.content or "").strip()
                if al_hablar and turno.texto:
                    al_hablar(turno.texto, "respuesta")
                break

            # Va a haber espera: la herramienta y otra llamada al modelo. Se
            # dice la frase puente ahora, no al final.
            if paso == 1 and al_hablar:
                turno.puente = FRASE_PUENTE
                turno.ms_puente = (time.perf_counter() - arranque) * 1000
                al_hablar(FRASE_PUENTE, "puente")

            for llamada in mensaje.tool_calls:
                nombre = llamada.function.name
                try:
                    argumentos = json.loads(llamada.function.arguments or "{}")
                except json.JSONDecodeError:
                    argumentos = {}
                resultado, ms = self._ejecutar(nombre, argumentos, turno.clave)
                resultado = self._anotar_intentos(nombre, argumentos, resultado)
                # Una consulta servida por el adelanto sale a coste cero en la
                # ruta critica: ya estaba hecha. Se marca para poder contarlas,
                # porque ese conteo SI es deterministico, mientras que el
                # efecto en el tiempo total se pierde en la varianza de las
                # llamadas al modelo.
                if ms == 0.0 and nombre in ADELANTABLES:
                    nombre_paso = f"{nombre} (adelantada)"
                    turno.adelantos_usados += 1
                else:
                    nombre_paso = nombre
                turno.rastro.append(Paso("herramienta", nombre_paso, ms,
                                         argumentos=argumentos, resultado=resultado,
                                         error=resultado.get("error")))
                self.historia.append({
                    "role": "tool",
                    "tool_call_id": llamada.id,
                    "content": json.dumps(resultado, ensure_ascii=False),
                })

        if not turno.texto:
            # Esta frase prometía un asesor y no llamaba a nadie. Lo destapó
            # `fundamento.py` el 2026-09-24, y no en el modelo: en este
            # fichero. El agente se quedaba sin pasos, decía "le paso con un
            # asesor" y colgaba la promesa en el aire, sin ticket, sin
            # expediente y sin nadie al otro lado. Es la misma mentira que se
            # le prohíbe al modelo, escrita a mano.
            #
            # Ahora se escala de verdad antes de decirlo. Lleva la clave del
            # turno, así que un reintento no abre dos tickets.
            resultado, ms = self._llamar(
                "escalar_a_humano",
                {"motivo": "el turno acabó sin respuesta del modelo"},
                turno.clave)
            turno.rastro.append(Paso("herramienta", "escalar_a_humano", ms,
                                     argumentos={"motivo": "turno sin respuesta"},
                                     resultado=resultado,
                                     error=resultado.get("error")))
            turno.texto = ("Disculpe, no pude completar la consulta. "
                           "Le paso con un asesor.")
        self.historia.append({"role": "assistant", "content": turno.texto})
        turno.ms_total = (time.perf_counter() - arranque) * 1000
        return turno
