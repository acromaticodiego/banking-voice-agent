"""¿Qué límites tiene esta cuenta de Groq, y quedan cerca?

Existe por una sospecha concreta: en las mediciones del modelo aparece una
meseta de ~2,7 s que no se parece a la varianza de inferencia. Las muestras
salen bimodales —trece por debajo de 705 ms y dos en torno a 3 s— y eso tiene
pinta de cola, no de modelo lento.

Antes de culpar al modelo o de pagar un plan, se le pregunta al servidor.
Groq devuelve los límites en las cabeceras de cada respuesta.

## Por qué esta sonda mentía por omisión (2026-09-24)

Las cabeceras traen **solo los límites por minuto**: `limit-tokens: 8000`. El
que de verdad para el trabajo no sale ahí. El 24/09 las evaluaciones empezaron
a fallar con 429 mientras esta sonda decía tranquilamente que quedaban 7920
tokens, y el diagnóstico fue equivocado tres veces seguidas —"es el límite por
minuto, espaciando las corridas se arregla"— hasta que se leyó el cuerpo del
error:

    Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199919

**200 000 tokens al día**, y no aparece en ninguna cabecera. Una sonda que
enseña los límites que no importan y calla el que manda es peor que no tener
sonda, porque da confianza. Así que ahora, además de las cabeceras, se hace una
petición del tamaño de las de verdad —con el prompt del sistema y las
herramientas— y si el servidor la rechaza, se enseña **qué límite** fue, cuánto
se ha gastado y cuándo se recupera.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import cargar_env  # noqa: E402

from groq import Groq  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.agent.loop import HERRAMIENTAS, SISTEMA  # noqa: E402

entorno = cargar_env()
# Sin reintentos: aquí lo que se busca es justamente el rechazo. Con reintentos
# el SDK se lo come por dentro y la sonda no se enteraría de nada.
cliente = Groq(api_key=entorno["GROQ_API_KEY"].strip(), max_retries=0)
modelo = entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

print(f"modelo: {modelo}\n")

respuesta = cliente.chat.completions.with_raw_response.create(
    model=modelo,
    messages=[{"role": "user", "content": "di solo: hola"}],
    max_tokens=5,
)

print("  cabeceras (SOLO llevan los límites por minuto):")
interesantes = [c for c in respuesta.headers if "ratelimit" in c.lower()
                or "retry" in c.lower()]
if not interesantes:
    print("    el servidor no devolvió cabeceras de límite.")
for cabecera in sorted(interesantes):
    print(f"    {cabecera}: {respuesta.headers[cabecera]}")

# Y ahora una del tamaño de las de verdad. Las de la evaluación llevan el
# prompt del sistema, las tres herramientas y varios turnos de historia: son
# dos órdenes de magnitud más grandes que un "di hola", y el límite diario solo
# se ve cuando alguien pide de verdad.
print("\n  una petición del tamaño real (prompt del sistema + herramientas):")
try:
    cliente.chat.completions.create(
        model=modelo,
        messages=[{"role": "system", "content": SISTEMA},
                  {"role": "user", "content": "Hola, mi cédula es 1070234567"}],
        tools=HERRAMIENTAS, tool_choice="auto", max_tokens=400,
        reasoning_effort="low",
    )
    print("    pasa. Hay cuota para medir.")
except Exception as exc:  # noqa: BLE001
    texto = str(exc)
    print(f"    RECHAZADA: {type(exc).__name__}")
    cual = re.search(r"on (tokens per day \(TPD\)|tokens per minute \(TPM\)|"
                     r"requests per day \(RPD\)|requests per minute \(RPM\))",
                     texto)
    gastado = re.search(r"Limit (\d+), Used (\d+)", texto)
    cuando = re.search(r"try again in ([\dhms.]+)", texto)
    if cual:
        print(f"    el límite que manda: {cual.group(1)}")
    if gastado:
        limite, usado = int(gastado.group(1)), int(gastado.group(2))
        print(f"    gastado: {usado} de {limite} "
              f"({100 * usado / limite:.1f}%)")
    if cuando:
        print(f"    se recupera en: {cuando.group(1)}")
    if not (cual or gastado):
        print(f"    {texto[:300]}")
    print("\n    Si es TPD, esperar no sirve: hoy no hay más mediciones. Y no "
          "sale en ninguna cabecera, así que la parte de arriba seguirá "
          "diciendo que queda cuota de sobra.")
