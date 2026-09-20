"""¿Qué límites tiene esta cuenta de Groq, y quedan cerca?

Existe por una sospecha concreta: en las mediciones del modelo aparece una
meseta de ~2,7 s que no se parece a la varianza de inferencia. Las muestras
salen bimodales —trece por debajo de 705 ms y dos en torno a 3 s— y eso tiene
pinta de cola, no de modelo lento.

Antes de culpar al modelo o de pagar un plan, se le pregunta al servidor.
Groq devuelve los límites en las cabeceras de cada respuesta.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import cargar_env  # noqa: E402

from groq import Groq  # noqa: E402

entorno = cargar_env()
cliente = Groq(api_key=entorno["GROQ_API_KEY"].strip())
modelo = entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

respuesta = cliente.chat.completions.with_raw_response.create(
    model=modelo,
    messages=[{"role": "user", "content": "di solo: hola"}],
    max_tokens=5,
)

print(f"modelo: {modelo}\n")
interesantes = [c for c in respuesta.headers if "ratelimit" in c.lower()
                or "retry" in c.lower()]
if not interesantes:
    print("El servidor no devolvió cabeceras de límite.")
for cabecera in sorted(interesantes):
    print(f"  {cabecera}: {respuesta.headers[cabecera]}")
