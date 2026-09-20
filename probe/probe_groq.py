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


def medir(cliente, modelo: str, escenario: str, repeticiones: int) -> tuple[Medicion, Medicion]:
    config = ESCENARIOS[escenario]
    ttft = Medicion(
        etapa="llm",
        implementacion=f"groq {modelo} [{escenario}]",
        que_mide="desde que se envía la petición hasta el primer token recibido",
    )
    total = Medicion(
        etapa="llm",
        implementacion=f"groq {modelo} [{escenario}] (total)",
        que_mide="desde que se envía la petición hasta el último token (dato secundario)",
        notas="No entra en el presupuesto del turno: se solapa con la síntesis.",
    )

    tokens_salida = []
    # Una primera llamada que se descarta: paga el TLS y el calentamiento de la
    # conexión, y no representa lo que pasa en mitad de una llamada telefónica.
    for i in range(repeticiones + 1):
        argumentos = {
            "model": modelo,
            "messages": config["mensajes"],
            "stream": True,
            "max_tokens": 120,
            "temperature": 0.2,
        }
        if config["herramientas"]:
            argumentos["tools"] = config["herramientas"]
            argumentos["tool_choice"] = "auto"

        arranque = time.perf_counter()
        primer_token = None
        piezas = 0
        try:
            flujo = cliente.chat.completions.create(**argumentos)
            for trozo in flujo:
                delta = trozo.choices[0].delta if trozo.choices else None
                hay_contenido = delta is not None and (
                    getattr(delta, "content", None) or getattr(delta, "tool_calls", None)
                )
                if hay_contenido and primer_token is None:
                    primer_token = time.perf_counter()
                if hay_contenido:
                    piezas += 1
            fin = time.perf_counter()
        except Exception as exc:  # noqa: BLE001 - queremos el motivo literal en el informe
            ttft.error = f"{type(exc).__name__}: {exc}"
            total.error = ttft.error
            return ttft, total

        if i == 0:
            continue  # descartada
        if primer_token is None:
            ttft.notas += " Una respuesta llegó vacía. "
            continue
        ttft.muestras_ms.append((primer_token - arranque) * 1000)
        total.muestras_ms.append((fin - arranque) * 1000)
        tokens_salida.append(piezas)
        print(f"    {escenario} {i}/{repeticiones}: "
              f"primer token {ttft.muestras_ms[-1]:.0f} ms, "
              f"completa {total.muestras_ms[-1]:.0f} ms, {piezas} trozos")

    if tokens_salida:
        media = sum(tokens_salida) / len(tokens_salida)
        total.notas += f" Media de {media:.0f} trozos de streaming por respuesta."
    return ttft, total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeticiones", type=int, default=10,
                        help="muestras por escenario, sin contar la de calentamiento")
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
    print(f"Midiendo Groq con el modelo {modelo}, {args.repeticiones} muestras por escenario.")
    print("Se descarta la primera llamada de cada escenario (calentamiento de conexión).\n")

    mediciones: list[Medicion] = []
    for escenario in ESCENARIOS:
        print(f"  escenario: {escenario}")
        mediciones.extend(medir(cliente, modelo, escenario, args.repeticiones))
        print()

    print("Resultado:")
    for m in mediciones:
        print(m.linea())

    destino = guardar(mediciones, "groq")
    print(f"\nGuardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
