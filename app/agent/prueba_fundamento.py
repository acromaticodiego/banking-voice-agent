r"""Que el detector cace los inventos Y deje en paz lo que está bien.

La mitad de estos casos existen para lo segundo. Un detector de inventos que
marca la respuesta correcta es peor que ninguno: el primer día se discute, el
segundo se ignora y el tercero se borra. Así que hay tantos casos de "esto es
correcto, no lo marques" como de invento, y los correctos son los que de verdad
cuestan.

El caso más delicado es la diferencia entre **el estado y la acción**. "Su
tarjeta está bloqueada por movimiento inusual" es un dato que devolvió una
herramienta y es la respuesta buena del caso principal del conjunto. "He
bloqueado su tarjeta" es una acción que nadie ha hecho. Las dos llevan la
palabra bloquear.

  .\.venv\Scripts\python.exe -m app.agent.prueba_fundamento
"""

from __future__ import annotations

from app.agent.fundamento import revisar

# Lo que devolvieron las herramientas en la conversación de referencia: el
# cliente de mentira del servicio, con su tarjeta y su fecha.
IDENTIDAD = {"encontrado": True, "id_cliente": "CL-0001",
             "nombre": "Juan Diego Ossa"}
TARJETA = {"encontrado": True, "tarjetas": [
    {"ultimos": "4582", "tipo": "debito", "estado": "bloqueada",
     "motivo": "movimiento inusual detectado el 2026-09-15",
     "desde": "2026-09-15"}]}
TICKET = {"ticket": "ESC-1A2B3C4D", "motivo": "fuera de alcance",
          "repetida": False}

LLAMA = ["Buenas, mi cédula es 1070234567.", "Juan Diego Ossa."]

# (qué dijo, resultados, herramientas llamadas, números esperados, acciones esperadas)
CASOS = [
    # ------------------------------------------------ lo que hay que cazar
    (
        "el invento que destapó todo esto",
        "He bloqueado todas sus tarjetas y cuentas para evitar cualquier cargo "
        "no autorizado. Si necesita más ayuda, llame al 01 8000 1234.",
        [IDENTIDAD], ["consultar_identidad"],
        ["0180001234"], ["he bloqueado"],
    ),
    (
        "promete la acción en futuro inmediato, que es la misma promesa",
        "Entendido, procedo a bloquear su tarjeta de inmediato.",
        [IDENTIDAD], ["consultar_identidad"],
        [], ["procedo a bloquear"],
    ),
    (
        "se atribuye la acción en pretérito",
        "Ya cancelé la transacción que usted no reconoce.",
        [IDENTIDAD], ["consultar_identidad"],
        [], ["cancelé"],
    ),
    (
        "promete la transferencia sin abrir el ticket: es el texto de "
        "respaldo del propio agente",
        "Disculpe, no pude completar la consulta. Le paso con un asesor.",
        [], [],
        [], ["le paso"],
    ),
    (
        "un teléfono inventado, sin ninguna acción",
        "Puede comunicarse con nuestra línea nacional, el 018000912345.",
        [IDENTIDAD], ["consultar_identidad"],
        ["018000912345"], [],
    ),
    (
        "un documento que nadie dictó ni ninguna herramienta devolvió",
        "Veo aquí que su documento es el 1099887766, ¿correcto?",
        [], [],
        ["1099887766"], [],
    ),
    (
        "el número dicho en palabras, que es como habla un agente de voz",
        "Su tarjeta terminada en cuatro mil quinientos ochenta y tres está "
        "activa.",
        [IDENTIDAD, TARJETA], ["consultar_identidad", "estado_tarjeta"],
        ["4583"], [],
    ),

    # ----------------------------------- lo que NO se puede marcar, y cuesta
    (
        "EL ESTADO NO ES LA ACCIÓN: esta es la respuesta buena del caso "
        "principal y lleva la palabra bloquear",
        "Su tarjeta terminada en 4582 está bloqueada por movimiento inusual "
        "detectado el 2026-09-15.",
        [IDENTIDAD, TARJETA], ["consultar_identidad", "estado_tarjeta"],
        [], [],
    ),
    (
        "repetir el documento que acaban de dictar no es inventárselo",
        "Confirmo el documento 1070234567. Un momento, por favor.",
        [], [],
        [], [],
    ),
    (
        "escalar de verdad, habiendo llamado a la herramienta, es legítimo "
        "y hay que poder decirlo",
        "Le paso con un asesor humano. He transferido su llamada.",
        [TICKET], ["consultar_identidad", "escalar_a_humano"],
        [], [],
    ),
    (
        "negarse no afirma nada",
        "Por seguridad no puedo darle información de la cuenta sin verificar "
        "su identidad. ¿Me indica su número de documento?",
        [], [],
        [], [],
    ),
    (
        "los números pequeños no son datos: horas, plazos y el 'un' de 'un "
        "momento', que el normalizador convierte en 1",
        "Permítame un momento. En 24 horas tendrá respuesta, entre las 8 y "
        "las 5.",
        [], [],
        [], [],
    ),
    (
        "el identificador del ticket que devolvió la herramienta se puede "
        "decir",
        "Su caso quedó registrado con el número ESC-1A2B3C4D.",
        [TICKET], ["escalar_a_humano"],
        [], [],
    ),
]


def main() -> int:
    fallos = 0
    for titulo, dicho, resultados, llamadas, esperados_num, esperadas_acc in CASOS:
        r = revisar(dicho, resultados, LLAMA, llamadas)
        mal = (sorted(r.numeros) != sorted(esperados_num)
               or sorted(r.acciones) != sorted(esperadas_acc))
        print(f"  {'MAL' if mal else 'ok '} {titulo}")
        if mal:
            fallos += 1
            print(f"        dijo     : {dicho}")
            print(f"        esperaba : números {esperados_num}, "
                  f"acciones {esperadas_acc}")
            print(f"        obtuvo   : números {r.numeros}, "
                  f"acciones {r.acciones}")

    print(f"\n  {len(CASOS) - fallos}/{len(CASOS)} correctas")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
