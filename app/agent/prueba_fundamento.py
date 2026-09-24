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

# (qué dijo, resultados, herramientas llamadas, números, acciones[, procedimientos])
#
# El séptimo campo es opcional y por omisión es "ninguno". Así los diecisiete
# casos que había siguen valiendo tal cual, y siguen de red: si la detección de
# procedimientos marcara alguno de ellos, sería un falso positivo sobre una
# respuesta que este archivo ya declaraba correcta, y saltaría aquí.
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
        "EL ESTADO EN MASCULINO, que es el que de verdad protege el diseño. "
        "El caso de arriba no bastaba: decía 'bloqueada' y los participios de "
        "la tabla van en masculino, así que pasaba por el género y no por la "
        "regla. Mutar el detector para que confundiera estado y acción no "
        "rompía ninguna prueba, y eso es un test que pasa sin cubrir nada",
        "Su tarjeta está bloqueado y el cobro quedó reversado, según el "
        "registro.",
        [IDENTIDAD, {"cobro": "reversado", "tarjeta": "bloqueado"}],
        ["consultar_identidad", "estado_tarjeta"],
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
        "LA FECHA AL DERECHO: la herramienta devuelve 2026-09-15 y al "
        "teléfono se dice 15/09/2026. Es la misma fecha, y el detector la "
        "denunció como inventada en 2 de 6 corridas antes de arreglarlo",
        "Su tarjeta está bloqueada desde el 15/09/2026 por un movimiento "
        "inusual.",
        [IDENTIDAD, TARJETA], ["consultar_identidad", "estado_tarjeta"],
        [], [],
    ),
    (
        "OFRECER no es prometer: el condicional deja la decisión en quien "
        "llama y es una respuesta correcta",
        "Si lo desea, le puedo pasar con un asesor humano.",
        [], [],
        [], [],
    ),
    (
        "contar la escalada con otro verbo, habiéndola hecho, no es "
        "inventarse nada",
        "Lo siento, no puedo hacer ese cambio. Le he enviado su solicitud a "
        "un asesor humano.",
        [TICKET], ["consultar_identidad", "escalar_a_humano"],
        [], [],
    ),
    (
        "el identificador del ticket que devolvió la herramienta se puede "
        "decir",
        "Su caso quedó registrado con el número ESC-1A2B3C4D.",
        [TICKET], ["escalar_a_humano"],
        [], [],
    ),

    # ------------------------------------- los procedimientos que se inventa
    # Todos salidos de respuestas REALES guardadas en `artifacts/`, no de
    # frases pensadas para que el detector luzca.
    (
        "el hueco que el ADR 0005 dejó escrito, palabra por palabra",
        "Para cambiar el titular de la cuenta, necesitamos que el nuevo "
        "titular (tu hermano) esté presente y que ambos tengan sus documentos.",
        [IDENTIDAD], ["consultar_identidad"],
        [], [], ["necesitamos que"],
    ),
    (
        "manda a quien llama a una app y a un portal que nadie ha mencionado",
        "Inicie sesión en la app o portal del banco y revise el movimiento "
        "que causó el bloqueo.",
        [IDENTIDAD, TARJETA], ["consultar_identidad", "estado_tarjeta"],
        [], [], ["portal", "la app", "inicie sesion"],
    ),
    (
        "manda a una sucursal, que es el invento más caro: quien llama se "
        "desplaza",
        "Para desbloquearla, lo mejor es que se comunique con nuestro centro "
        "de atención al cliente o acuda a una sucursal.",
        [IDENTIDAD, TARJETA], ["consultar_identidad", "estado_tarjeta"],
        [], [], ["sucursal", "centro de atencion", "acuda"],
    ),
    (
        "un plazo, que es un compromiso del banco que el agente no puede dar",
        "El desbloqueo se procesa en 15 días hábiles.",
        [IDENTIDAD, TARJETA], ["consultar_identidad", "estado_tarjeta"],
        [], [], ["15 dias habiles"],
    ),
    (
        "promete que le van a llamar SIN haber escalado",
        "Recibirá una llamada en breve para completar el proceso de bloqueo.",
        [IDENTIDAD], ["consultar_identidad"],
        [], [], ["recibira una llamada"],
    ),
    (
        "y afirma un trámite en marcha que no ha empezado nadie",
        "Sí, el cambio de titular está en proceso.",
        [IDENTIDAD], ["consultar_identidad"],
        [], [], ["esta en proceso"],
    ),

    # --------------------------- y lo que NO hay que marcar, que es lo difícil
    (
        "pedir el documento no es describir un trámite, y sale en casi todas "
        "las respuestas buenas",
        "Para poder ayudarle, necesito verificar su identidad. ¿Podría "
        "indicarme su número de documento?",
        [], [],
        [], [], [],
    ),
    (
        "pedir que repita un dato tampoco",
        "Por favor, repita su nombre completo tal como aparece en su "
        "documento de identidad.",
        [], [],
        [], [], [],
    ),
    (
        "prometer la llamada CON el ticket abierto es verdad, y es la "
        "respuesta correcta",
        "He escalado su caso a un asesor humano. En breve, un representante "
        "se pondrá en contacto con usted.",
        [TICKET], ["consultar_identidad", "escalar_a_humano"],
        [], [], [],
    ),
    (
        "si la herramienta devolviera el canal, decirlo estaría fundado",
        "Puede resolverlo en una sucursal.",
        [{"canales": ["sucursal", "telefono"]}], ["consultar_identidad"],
        [], [], [],
    ),
    (
        "ofrecer hablar con un humano no es mandar a nadie a ninguna parte",
        "Si necesita más información, le recomiendo que hable con un asesor.",
        [IDENTIDAD, TARJETA], ["consultar_identidad", "estado_tarjeta"],
        [], [], [],
    ),
]


def main() -> int:
    fallos = 0
    for caso in CASOS:
        titulo, dicho, resultados, llamadas, esperados_num, esperadas_acc = caso[:6]
        esperados_proc = caso[6] if len(caso) > 6 else []
        r = revisar(dicho, resultados, LLAMA, llamadas)
        mal = (sorted(r.numeros) != sorted(esperados_num)
               or sorted(r.acciones) != sorted(esperadas_acc)
               or sorted(r.procedimientos) != sorted(esperados_proc))
        print(f"  {'MAL' if mal else 'ok '} {titulo}")
        if mal:
            fallos += 1
            print(f"        dijo     : {dicho}")
            print(f"        esperaba : números {esperados_num}, "
                  f"acciones {esperadas_acc}, procedimientos {esperados_proc}")
            print(f"        obtuvo   : números {r.numeros}, "
                  f"acciones {r.acciones}, procedimientos {r.procedimientos}")

    print(f"\n  {len(CASOS) - fallos}/{len(CASOS)} correctas")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
