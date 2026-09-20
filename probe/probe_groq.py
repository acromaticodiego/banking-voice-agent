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

ESCENARIOS = {
    "respuesta": {
        "mensajes": [
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": "Buenas, llamo porque me bloquearon la tarjeta y no sé por qué."},
        ],
        "herramientas": None,
    },
    "herramienta": {
        "mensajes": [
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": "Buenas, llamo porque me bloquearon la tarjeta."},
            {"role": "assistant", "content": "Con gusto le ayudo. ¿Me regala su número de documento?"},
            {"role": "user", "content": "Claro, es el mil setenta millones doscientos treinta y cuatro mil quinientos sesenta y siete."},
        ],
        "herramientas": HERRAMIENTAS,
    },
}


def medir(cliente, modelo: str, esfuerzo: str | None, escenario: str,
          repeticiones: int) -> list[Medicion]:
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
    config = ESCENARIOS[escenario]
    etiqueta = f"{modelo}" + (f" esfuerzo={esfuerzo}" if esfuerzo else "")

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

    razonamientos = []
    # Una primera llamada que se descarta: paga el TLS y el calentamiento de la
    # conexión, y no representa lo que pasa en mitad de una llamada telefónica.
    for i in range(repeticiones + 1):
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
        try:
            for trozo in cliente.chat.completions.create(**argumentos):
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
        except Exception as exc:  # noqa: BLE001 - queremos el motivo literal en el informe
            for m in mediciones:
                m.error = f"{type(exc).__name__}: {exc}"
            return mediciones

        if i == 0:
            continue  # descartada
        if t_hablable is None:
            hablable.notas += " Una respuesta no llegó a decir nada pronunciable. "
            continue
        primero.muestras_ms.append((t_primero - arranque) * 1000)
        hablable.muestras_ms.append((t_hablable - arranque) * 1000)
        total.muestras_ms.append((fin - arranque) * 1000)
        razonamientos.append(trozos_razonamiento)
        print(f"    {escenario} {i}/{repeticiones}: "
              f"primer trozo {primero.muestras_ms[-1]:.0f} ms, "
              f"hablable {hablable.muestras_ms[-1]:.0f} ms, "
              f"total {total.muestras_ms[-1]:.0f} ms, "
              f"{trozos_razonamiento} trozos de razonamiento")

    if razonamientos:
        media = sum(razonamientos) / len(razonamientos)
        hablable.notas += (f" Media de {media:.0f} trozos de razonamiento antes de "
                           f"decir nada pronunciable.")
    return mediciones


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeticiones", type=int, default=10,
                        help="muestras por escenario, sin contar la de calentamiento")
    parser.add_argument("--modelos", nargs="+", default=None,
                        help="uno o varios; por defecto los candidatos al bucle")
    parser.add_argument("--esfuerzos", nargs="+", default=["low", "medium"],
                        help="reasoning_effort a probar en los modelos que razonan")
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

    cliente = Groq(api_key=clave)

    # El reparto del CLAUDE.md: el bucle en el pequeño, el razonamiento difícil
    # en el grande y una sola vez. Se miden los dos para saber cuánto cuesta
    # esa salida al grande antes de decidir cuándo se permite.
    combinaciones = []
    for nombre in (args.modelos or [modelo, "openai/gpt-oss-120b"]):
        if "gpt-oss" in nombre:
            combinaciones.extend((nombre, e) for e in args.esfuerzos)
        else:
            combinaciones.append((nombre, None))

    print(f"Midiendo {len(combinaciones)} configuraciones, "
          f"{args.repeticiones} muestras por escenario.")
    print("Se descarta la primera llamada de cada escenario (calentamiento de conexión).\n")

    mediciones: list[Medicion] = []
    for nombre, esfuerzo in combinaciones:
        etiqueta = nombre + (f" (esfuerzo {esfuerzo})" if esfuerzo else "")
        print(f"--- {etiqueta}")
        for escenario in ESCENARIOS:
            print(f"  escenario: {escenario}")
            mediciones.extend(medir(cliente, nombre, esfuerzo, escenario,
                                    args.repeticiones))
            print()

    print("Resultado (la línea sin paréntesis es la que entra en el presupuesto):")
    for m in mediciones:
        print(m.linea())

    destino = guardar(mediciones, "groq")
    print(f"\nGuardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
