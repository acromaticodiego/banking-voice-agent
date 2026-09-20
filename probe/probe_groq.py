"""Sonda de latencia del modelo: Groq.

Mide **tiempo hasta el primer token**, no el tiempo total de la respuesta.
El motivo está en `docs/adr/0001`: en la conversación el TTS empieza a
sintetizar en cuanto hay una frase, así que el tiempo total de generación se
solapa con la síntesis y sumarlo entero al presupuesto del turno es contarlo
dos veces. El total se registra igual, pero como dato secundario.

Dos escenarios, porque el bucle real hace las dos cosas y no cuestan lo mismo:

  1. `respuesta`  — el agente contesta hablando.
  2. `herramienta` — el agente decide llamar a una herramienta. Lleva las
     definiciones de las herramientas en el contexto, que son tokens de entrada
     que la primera no paga.

Uso:  python probe/probe_groq.py [--repeticiones 10]
"""

from __future__ import annotations

import argparse
import sys
import time

from common import Medicion, cargar_env, guardar

SISTEMA = (
    "Eres el agente telefónico de un banco. Hablas español de Colombia, en frases "
    "cortas, porque lo que dices se convierte en voz. Nunca afirmas un dato que no "
    "te haya devuelto una herramienta: ni un saldo, ni un nombre, ni una fecha. "
    "Si no estás seguro de lo que oíste, pides que lo repitan."
)

# El mismo contrato en un tercio de los tokens. No es un recorte cosmético: el
# prompt de sistema y las definiciones de herramientas se vuelven a procesar en
# CADA turno, y una conversación son diez o quince turnos. Lo que aquí sobra se
# paga quince veces.
#
# Lo que se conserva es lo que cambia el comportamiento —no inventar datos,
# frases cortas, pedir que repitan— y lo que se va es la explicación de por qué.
# El modelo no necesita que le justifiquen la regla, necesita la regla.
SISTEMA_CORTO = (
    "Agente telefónico de un banco colombiano. Frases cortas: esto se habla. "
    "No afirmes ningún dato que no venga de una herramienta. Si dudas de lo que "
    "oíste, pide que lo repitan."
)

PROMPTS = {"largo": SISTEMA, "corto": SISTEMA_CORTO}

HERRAMIENTAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_identidad",
            "description": "Busca a un cliente por su número de documento.",
            "parameters": {
                "type": "object",
                "properties": {
                    "documento": {"type": "string", "description": "Número de documento"},
                },
                "required": ["documento"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estado_tarjeta",
            "description": "Devuelve el estado de la tarjeta de un cliente verificado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_cliente": {"type": "string"},
                },
                "required": ["id_cliente"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalar_a_humano",
            "description": "Pasa la llamada a un asesor humano con el motivo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {"type": "string"},
                },
                "required": ["motivo"],
            },
        },
    },
]

# Las mismas capacidades sin la prosa. Los nombres de función y de argumento ya
# dicen lo que hacen; la descripción larga repite el nombre con más palabras.
HERRAMIENTAS_CORTAS = [
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

JUEGOS = {"largo": HERRAMIENTAS, "corto": HERRAMIENTAS_CORTAS}


def escenarios_con(variante: str) -> dict:
    """Los dos escenarios, montados con el prompt y las herramientas que toque.

    El prompt de sistema y las definiciones de herramientas viajan juntos: son
    las dos mitades del mismo coste de prefill, que se vuelve a pagar en cada
    turno de la conversación.
    """
    sistema = PROMPTS[variante]
    return {
    "respuesta": {
        "mensajes": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": "Buenas, llamo porque me bloquearon la tarjeta y no sé por qué."},
        ],
        "herramientas": None,
    },
    "herramienta": {
        "mensajes": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": "Buenas, llamo porque me bloquearon la tarjeta."},
            {"role": "assistant", "content": "Con gusto le ayudo. ¿Me regala su número de documento?"},
            {"role": "user", "content": "Claro, es el mil setenta millones doscientos treinta y cuatro mil quinientos sesenta y siete."},
        ],
        "herramientas": JUEGOS[variante],
    },
    }


ESCENARIOS = escenarios_con("largo")  # el que se midió el día 1


def preparar(modelo: str, esfuerzo: str | None, escenario: str,
             variante: str) -> tuple[list[Medicion], dict, str]:
    """Mide un modelo en un escenario.

    Distingue tres instantes, y la distinción no es académica: los `gpt-oss`
    razonan antes de contestar, y esos tokens de razonamiento **no se pueden
    pronunciar**. El TTS no puede empezar con ellos. Si midiera el primer token
    a secas estaría contando como "ya hay algo que decir" un tramo en el que no
    hay nada que decir, y el presupuesto saldría falseado a la baja.

      · primer trozo    — llega cualquier cosa, razonamiento incluido.
      · primer hablable — llega texto para la persona, o una llamada a
                          herramienta. **Este es el que entra en el presupuesto.**
      · total           — última pieza. Dato secundario: se solapa con la síntesis.
    """
    config = escenarios_con(variante)[escenario]
    etiqueta = (f"{modelo}"
                + (f" esfuerzo={esfuerzo}" if esfuerzo else "")
                + f" prompt={variante}")

    primero = Medicion(
        etapa="llm", implementacion=f"groq {etiqueta} [{escenario}] (primer trozo)",
        que_mide="desde que se envía la petición hasta el primer trozo de cualquier tipo",
        notas="Incluye razonamiento, que no se puede pronunciar. Dato secundario.",
    )
    hablable = Medicion(
        etapa="llm", implementacion=f"groq {etiqueta} [{escenario}]",
        que_mide="desde que se envía la petición hasta el primer contenido hablable "
                 "o la primera llamada a herramienta",
    )
    total = Medicion(
        etapa="llm", implementacion=f"groq {etiqueta} [{escenario}] (total)",
        que_mide="desde que se envía la petición hasta el último trozo (dato secundario)",
        notas="No entra en el presupuesto del turno: se solapa con la síntesis.",
    )
    mediciones = [hablable, primero, total]
    return mediciones, config, etiqueta


class Ritmo:
    """Mantiene las peticiones por debajo del techo de tokens por minuto.

    Sin esto las mediciones no se pueden comparar entre sí. El plan gratuito de
    esta cuenta da 8000 tokens por minuto (comprobado con
    `probe/limites_groq.py`), y al pasarse, las peticiones hacen cola: aparece
    una meseta de ~2,7 s que no tiene nada que ver con el modelo.

    El daño no es que salga un número alto: es que sale alto **para la
    configuración que se midió la última**, y entonces la comparación mide el
    orden de ejecución en vez de lo que se pretendía medir. Ya pasó una vez, y
    el prompt corto parecía ocho veces más rápido que el largo.
    """

    def __init__(self, tokens_por_minuto: int) -> None:
        self.techo = tokens_por_minuto
        self.gastos: list[tuple[float, int]] = []

    def esperar(self, previsto: int) -> float:
        ahora = time.monotonic()
        self.gastos = [(t, n) for t, n in self.gastos if ahora - t < 60]
        gastado = sum(n for _, n in self.gastos)
        if gastado + previsto <= self.techo:
            return 0.0
        # Esperar a que salga de la ventana lo justo para que quepa.
        sobra = gastado + previsto - self.techo
        acumulado = 0
        for t, n in self.gastos:
            acumulado += n
            if acumulado >= sobra:
                espera = max(0.0, 60 - (ahora - t)) + 0.2
                time.sleep(espera)
                return espera
        return 0.0

    def anotar(self, tokens: int) -> None:
        self.gastos.append((time.monotonic(), tokens))


def una_llamada(cliente, modelo, esfuerzo, config) -> dict:
    """Una petición, cronometrada. Devuelve los tres instantes y los tokens."""
    argumentos = {
        "model": modelo,
        "messages": config["mensajes"],
        "stream": True,
        "max_tokens": 400,
        "temperature": 0.2,
    }
    if esfuerzo:
        argumentos["reasoning_effort"] = esfuerzo
    if config["herramientas"]:
        argumentos["tools"] = config["herramientas"]
        argumentos["tool_choice"] = "auto"

    arranque = time.perf_counter()
    t_primero = t_hablable = None
    trozos_razonamiento = 0
    tokens = 0
    for trozo in cliente.chat.completions.create(**argumentos):
        # Groq mete el consumo en el último trozo, bajo `x_groq`. Hace falta
        # para marcar el ritmo: sin saber cuántos tokens costó cada llamada no
        # se puede respetar el techo por minuto, y sin respetarlo las
        # mediciones no se pueden comparar entre sí.
        for fuente in (getattr(trozo, "usage", None),
                       getattr(getattr(trozo, "x_groq", None), "usage", None)):
            if fuente is not None and getattr(fuente, "total_tokens", None):
                tokens = fuente.total_tokens
        delta = trozo.choices[0].delta if trozo.choices else None
        if delta is None:
            continue
        razona = getattr(delta, "reasoning", None)
        dice = getattr(delta, "content", None) or getattr(delta, "tool_calls", None)
        if (razona or dice) and t_primero is None:
            t_primero = time.perf_counter()
        if razona and not dice:
            trozos_razonamiento += 1
        if dice and t_hablable is None:
            t_hablable = time.perf_counter()
    fin = time.perf_counter()

    return {
        "primero_ms": (t_primero - arranque) * 1000 if t_primero else None,
        "hablable_ms": (t_hablable - arranque) * 1000 if t_hablable else None,
        "total_ms": (fin - arranque) * 1000,
        "razonamiento": trozos_razonamiento,
        "tokens": tokens,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeticiones", type=int, default=10,
                        help="muestras por escenario, sin contar la de calentamiento")
    parser.add_argument("--modelos", nargs="+", default=None,
                        help="uno o varios; por defecto los candidatos al bucle")
    parser.add_argument("--esfuerzos", nargs="+", default=["low", "medium"],
                        help="reasoning_effort a probar en los modelos que razonan")
    parser.add_argument("--prompts", nargs="+", default=["largo"],
                        choices=list(PROMPTS),
                        help="variante de prompt de sistema y herramientas")
    parser.add_argument("--tokens-por-minuto", type=int, default=8000,
                        help="techo del plan; compruébalo con probe/limites_groq.py")
    args = parser.parse_args()

    entorno = cargar_env()
    clave = entorno.get("GROQ_API_KEY", "").strip()
    if not clave:
        print("Falta GROQ_API_KEY. Copia .env.example a .env y pega la clave ahí.",
              file=sys.stderr)
        return 2
    modelo = entorno.get("GROQ_MODEL", "llama-3.1-8b-instant").strip()

    try:
        from groq import Groq
    except ImportError:
        print("Falta el paquete `groq`. Instala con: pip install -r requirements-probe.txt",
              file=sys.stderr)
        return 2

    # `max_retries=0` a propósito. Por defecto el SDK reintenta los 429 por
    # dentro, durmiendo lo que le diga el servidor, y el cronómetro de esta
    # sonda sigue corriendo: aparece una muestra de 80 s que parece latencia
    # del modelo y es una espera administrativa. Un rechazo por límite tiene
    # que salir como error y contarse aparte, no promediarse con los tiempos
    # buenos.
    cliente = Groq(api_key=clave, max_retries=0)

    # El reparto del CLAUDE.md: el bucle en el pequeño, el razonamiento difícil
    # en el grande y una sola vez. Se miden los dos para saber cuánto cuesta
    # esa salida al grande antes de decidir cuándo se permite.
    combinaciones = []
    for nombre in (args.modelos or [modelo, "openai/gpt-oss-120b"]):
        for variante in args.prompts:
            if "gpt-oss" in nombre:
                combinaciones.extend((nombre, e, variante) for e in args.esfuerzos)
            else:
                combinaciones.append((nombre, None, variante))

    # Cada tarea es una configuración en un escenario. Se recorren INTERCALADAS,
    # una vuelta por repetición, en vez de agotar una configuración antes de
    # pasar a la siguiente. Así, si el plan empieza a encolar peticiones a
    # mitad de la tanda, el castigo se reparte entre todas en vez de caer
    # entero sobre la última, que es lo que arruinó la comparación anterior.
    tareas = []
    for nombre, esfuerzo, variante in combinaciones:
        for escenario in ("respuesta", "herramienta"):
            meds, config, etiqueta = preparar(nombre, esfuerzo, escenario, variante)
            tareas.append({"modelo": nombre, "esfuerzo": esfuerzo,
                           "escenario": escenario, "config": config,
                           "etiqueta": etiqueta, "meds": meds,
                           "razonamientos": []})

    ritmo = Ritmo(args.tokens_por_minuto)
    print(f"Midiendo {len(combinaciones)} configuraciones x 2 escenarios "
          f"= {len(tareas)} series, {args.repeticiones} muestras cada una.")
    print(f"Intercaladas, y a ritmo de {args.tokens_por_minuto} tokens por minuto "
          "para no chocar con el techo del plan.")
    print("La vuelta 0 se descarta: calentamiento de conexión.\n")

    mediciones: list[Medicion] = []
    for vuelta in range(args.repeticiones + 1):
        esperado = 0.0
        for tarea in tareas:
            previsto = max(300, int(sum(t for _, t in ritmo.gastos[-3:]) / 3)
                           if len(ritmo.gastos) >= 3 else 600)
            esperado += ritmo.esperar(previsto)
            try:
                r = una_llamada(cliente, tarea["modelo"], tarea["esfuerzo"],
                                tarea["config"])
            except Exception as exc:  # noqa: BLE001 - el motivo literal al informe
                if "rate_limit" in str(exc) or "429" in str(exc):
                    # No es un fallo de la medición ni del modelo: es el techo
                    # del plan. Se cuenta aparte y se espera a que se libere la
                    # ventana, en vez de contaminar los tiempos.
                    tarea["rechazos"] = tarea.get("rechazos", 0) + 1
                    time.sleep(20)
                    continue
                for m in tarea["meds"]:
                    m.error = f"{type(exc).__name__}: {exc}"
                continue
            ritmo.anotar(r["tokens"] or 600)
            if vuelta == 0 or r["hablable_ms"] is None:
                continue
            hablable, primero, total = tarea["meds"]
            hablable.muestras_ms.append(r["hablable_ms"])
            primero.muestras_ms.append(r["primero_ms"])
            total.muestras_ms.append(r["total_ms"])
            tarea["razonamientos"].append(r["razonamiento"])
        if vuelta > 0:
            hechas = sum(1 for t in tareas if t["meds"][0].muestras_ms)
            print(f"  vuelta {vuelta}/{args.repeticiones} completa "
                  f"({hechas} series con muestra"
                  + (f", {esperado:.0f} s esperando al límite" if esperado else "")
                  + ")")

    rechazos = sum(t.get("rechazos", 0) for t in tareas)
    if rechazos:
        print(f"\n{rechazos} peticiones rechazadas por el techo de tokens del "
              "plan. No entran en los tiempos.")

    for tarea in tareas:
        if tarea.get("rechazos"):
            tarea["meds"][0].notas += (f" {tarea['rechazos']} peticiones rechazadas "
                                       "por límite del plan, excluidas.")
        if tarea["razonamientos"]:
            media = sum(tarea["razonamientos"]) / len(tarea["razonamientos"])
            tarea["meds"][0].notas += (f" Media de {media:.0f} trozos de razonamiento "
                                       "antes de decir nada pronunciable.")
        mediciones.extend(tarea["meds"])

    print("\nResultado (la línea sin paréntesis es la que entra en el presupuesto):")
    for m in mediciones:
        print(m.linea())

    destino = guardar(mediciones, "groq")
    print(f"\nGuardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
