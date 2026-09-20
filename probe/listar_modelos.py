"""¿Qué modelos tiene de verdad esta cuenta de Groq, hoy?

Los catálogos cambian y los nombres de los ejemplos caducan. Antes de medir
contra un modelo hay que preguntarle a la cuenta cuál puede usar, no darlo por
supuesto: un 404 a mitad de una tanda de medición cuesta más que esta llamada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import cargar_env  # noqa: E402

from groq import Groq  # noqa: E402

entorno = cargar_env()
cliente = Groq(api_key=entorno["GROQ_API_KEY"].strip())

modelos = sorted(cliente.models.list().data, key=lambda m: m.id)
print(f"{len(modelos)} modelos disponibles:\n")
for m in modelos:
    contexto = getattr(m, "context_window", "?")
    duenno = getattr(m, "owned_by", "?")
    print(f"  {m.id:<46} contexto {contexto:>7}  ({duenno})")
