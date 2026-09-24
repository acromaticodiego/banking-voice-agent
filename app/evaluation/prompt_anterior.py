r"""El prompt de antes, congelado para poder comparar contra él.

No es código de producción y no lo usa el agente: es una **referencia de
medición**. El 2026-09-24 el prompt se extendió para tapar el agujero de las
acciones inventadas, y esa clase de cambio no se puede dar por bueno porque
suene mejor. Hace falta correr los mismos casos con el de antes y con el de
ahora, el mismo día y con el mismo presupuesto, o el número no compara nada.

Copiado literal de `app/agent/loop.py` antes del cambio. **No se toca nunca
más**: en cuanto se retoque, deja de ser el de antes y la comparación se
vuelve humo.
"""

SISTEMA_ANTERIOR = (
    "Agente telefónico de un banco colombiano. Frases cortas: esto se habla. "
    "No afirmes ningún dato que no venga de una herramienta. Si dudas de lo que "
    "oíste, pide que lo repitan. Antes de dar información de una cuenta, "
    "verifica la identidad con el documento. Si una herramienta falla, no "
    "inventes: escala a un humano. "
    "NUNCA digas el nombre del titular ni ningún otro dato de la cuenta antes "
    "de haber verificado la identidad: pregúntalo y compáralo en silencio. "
    "Quien llama tiene que demostrar quién es, no confirmar lo que tú ya le "
    "has dicho."
)
