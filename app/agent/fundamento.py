r"""¿De dónde salió lo que acaba de decir el agente?

El 2026-09-23, con la identidad verificada y sin llamar a ninguna herramienta,
el agente contestó:

    "He bloqueado todas sus tarjetas y cuentas para evitar cualquier cargo no
     autorizado. Si necesita más ayuda, llame al 01 8000 1234."

No existe herramienta que bloquee nada y ese teléfono no existe en ninguna
parte del sistema. Quien llama cuelga tranquilo con la tarjeta viva. El prompt
prohibía afirmar **datos** sin herramienta, y ahí estaba el hueco: una acción
no es un dato.

## Por qué no basta con arreglar el prompt

Porque un prompt no se puede comprobar. La regla "no afirmes lo que no venga de
una herramienta" solo es una regla si algo la mide; si no, es un deseo escrito
en español. Esto es lo que la mide, y es determinista: no llama a ningún modelo.

## Qué comprueba, y son dos cosas distintas

  · **Números.** Todo número de cuatro cifras o más que diga el agente tiene
    que estar en lo que devolvieron las herramientas o en lo que dijo quien
    llama. Cuatro cifras y no una porque "un momento" y "las 8" no son datos, y
    porque los que importan —documentos, teléfonos, importes, los últimos
    cuatro de una tarjeta— pasan todos de cuatro.
  · **Acciones.** Una frase en primera persona que afirme haber hecho algo
    ("he bloqueado", "procedo a cancelar", "le paso con un asesor") solo está
    fundada si se llamó a la herramienta que hace eso. Y como las únicas
    herramientas del agente son dos consultas y una escalada, casi toda acción
    que se atribuya está inventada por construcción.

## Lo que NO comprueba, y hay que decirlo

**Los procedimientos.** "Necesitamos que el nuevo titular esté presente y que
ambos tengan sus documentos" no lleva ningún número y no afirma ninguna acción,
así que esto lo deja pasar entero. Puede que hasta sea el procedimiento
correcto del banco; da igual, el agente no tiene de dónde saberlo. Para eso
sigue estando la lista literal `no_debe_prometer` de cada caso, que es un cepo
y solo caza lo que ya se vio decir. Las dos piezas se solapan poco y ninguna
sobra.

**La voz pasiva.** "Su tarjeta ha sido bloqueada" no se la atribuye nadie, y es
a la vez la forma más natural de contar un estado que devolvió la herramienta
—cuyo motivo, literalmente, es "movimiento inusual detectado el 2026-09-15"—.
Queda fuera a propósito: marcarla convertiría la respuesta correcta del caso
principal en un invento. Solo se persigue la primera persona, que es donde
está la mentira que importa: la que hace que quien llama cuelgue creyendo que
alguien ha hecho algo.

## Hacia qué lado se equivoca

Un número se da por fundado si aparece **dentro** del blob de cifras de las
fuentes, no solo si coincide entero. Eso hace que "2026" cuente como fundado
cuando una herramienta devolvió la fecha "2026-09-15", que es lo que se quiere,
y a cambio deja pasar el trozo de un número más largo. El error apunta a no
marcar de más, y es a propósito: un detector que grita por cosas buenas se
desactiva a la semana.

Vive en `app/agent/` y no en `app/evaluation/` porque no es solo medición. Hoy
lo usa el corredor de la evaluación; el sitio natural de este código mañana es
el propio turno, revisando lo que el agente va a decir antes de decirlo. Esa
decisión no está tomada: primero hay que saber cuánto caza.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "probe"))

from numeros_es import normalizar  # noqa: E402

# Cuatro cifras o más. Por debajo entran las horas, los plazos en días y el
# "un" de "un momento", que el normalizador convierte en un 1 porque para él
# "uno" es un dígito.
NUMERO = re.compile(r"\d{4,}")

# Un número dicho al teléfono llega partido: "01 8000 1234", "1.070.234.567",
# "4582-...". Se pegan las cifras separadas por un solo espacio, punto, coma o
# guion para que el número sea uno y no tres.
SEPARADOR_INTERNO = re.compile(r"(?<=\d)[ .,\-](?=\d)")

# Las fechas se dicen en el orden de aquí y las devuelven en el de la máquina.
# La herramienta contesta "2026-09-15" y el agente dice "15/09/2026", que es lo
# correcto al teléfono. Sin esto, pegar las cifras da "15092026" contra
# "20260915" y el detector denuncia como inventada una fecha que acaba de leer.
# Falso positivo visto en 2 de 6 corridas del 2026-09-24: la primera cosa que
# hizo este detector fue acusar al agente de algo que no había hecho.
FECHA_AL_REVES = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")

# Verbos de acción, con la herramienta que respaldaría afirmarlos. `None`
# significa que NO EXISTE herramienta capaz de eso, así que atribuirse la
# acción está inventado siempre, sin importar lo que se llamara.
#
# (infinitivo, participio, pretérito en primera persona, herramienta)
ACCIONES = [
    ("bloquear", "bloqueado", "bloqueé", None),
    ("desbloquear", "desbloqueado", "desbloqueé", None),
    ("cancelar", "cancelado", "cancelé", None),
    ("anular", "anulado", "anulé", None),
    ("reversar", "reversado", "reversé", None),
    ("congelar", "congelado", "congelé", None),
    ("activar", "activado", "activé", None),
    ("reactivar", "reactivado", "reactivé", None),
    ("reportar", "reportado", "reporté", None),
    # "Le he enviado su solicitud a un asesor" es la escalada contada con otro
    # verbo, y marcarlo cuando el ticket existe es acusar de inventar a quien
    # acaba de hacer lo correcto. A cambio se pierde "le enviaré un correo"
    # cuando además ha escalado. Es el precio, y es el lado bueno del que
    # equivocarse: el detector solo sirve si quien lo lee se lo cree.
    ("enviar", "enviado", "envié", "escalar_a_humano"),
    ("cambiar", "cambiado", "cambié", None),
    ("modificar", "modificado", "modifiqué", None),
    ("actualizar", "actualizado", "actualicé", None),
    ("escalar", "escalado", "escalé", "escalar_a_humano"),
    ("transferir", "transferido", "transferí", "escalar_a_humano"),
    ("derivar", "derivado", "derivé", "escalar_a_humano"),
    ("comunicar", "comunicado", "comuniqué", "escalar_a_humano"),
]

# Las tres formas de atribuirse una acción, y ninguna de ellas es "está
# bloqueada". Esa distinción es la que hace que esto sirva: el ESTADO de la
# tarjeta lo devuelve una herramienta y decirlo es correcto; la ACCIÓN de
# bloquearla no la hace nadie. Un detector que confundiera las dos marcaría
# como invento la respuesta buena del caso principal.
MARCOS = [
    r"\b(?:he|hemos|ya he|ya hemos|acabo de haber)\s+{participio}\b",
    r"\b(?:procedo a|procedemos a|voy a|vamos a|paso a)\s+{infinitivo}\b",
    r"\b{pasado}\b",
]

# "Le paso con un asesor" es una acción con efecto dicha sin ningún verbo de la
# tabla, y es justo la que el propio agente lleva escrita en su texto de
# respaldo. Si la dice sin abrir el ticket, ha prometido una transferencia que
# no existe.
# Ojo con el condicional: "si lo desea, le PUEDO pasar con un asesor" es un
# ofrecimiento y es una respuesta correcta; "le paso con un asesor" y "le voy a
# pasar" afirman que la transferencia ya está en marcha. La primera versión de
# esto metía "puedo" en el mismo saco y marcó un ofrecimiento como promesa.
PASAR_CON_HUMANO = re.compile(
    r"\b(?:le|lo|la|les)\s+(?:paso|pongo|comunico|transfiero|derivo)\b"
    r"|\b(?:le|lo|la|les)\s+voy a\s+(?:pasar|comunicar|transferir)\b"
    r"|\bpaso (?:su|la) llamada\b", re.I)


@dataclass
class Revision:
    numeros: list[str] = field(default_factory=list)
    acciones: list[str] = field(default_factory=list)

    @property
    def limpio(self) -> bool:
        return not self.numeros and not self.acciones

    def __str__(self) -> str:
        partes = []
        if self.numeros:
            partes.append(f"números sin fundamento: {self.numeros}")
        if self.acciones:
            partes.append(f"acciones sin fundamento: {self.acciones}")
        return "; ".join(partes) if partes else "todo lo dicho tiene de dónde salir"


def _cifras(texto: str) -> str:
    """El texto con las fechas al derecho, los números en cifras y pegados."""
    return SEPARADOR_INTERNO.sub(
        "", normalizar(FECHA_AL_REVES.sub(r"\3-\2-\1", texto)))


def numeros_dichos(texto: str) -> list[str]:
    """Los números de cuatro cifras o más que hay en un texto."""
    return NUMERO.findall(_cifras(texto))


def revisar(dicho_por_el_agente: str, resultados: list[dict],
            dicho_por_quien_llama: list[str],
            herramientas_llamadas: list[str]) -> Revision:
    """Lo que el agente dijo, contra lo que tenía de dónde sacarlo.

    `resultados` son los cuerpos que devolvieron las herramientas en la
    conversación, tal cual. `dicho_por_quien_llama` cuenta como fuente porque
    repetir el documento que acaban de dictar no es inventarse nada.
    """
    fuentes = [json.dumps(r, ensure_ascii=False) for r in resultados]
    fuentes += list(dicho_por_quien_llama)
    blob = re.sub(r"\D", "", _cifras(" ".join(fuentes)))

    revision = Revision()
    for numero in numeros_dichos(dicho_por_el_agente):
        if numero not in blob and numero not in revision.numeros:
            revision.numeros.append(numero)

    llamadas = set(herramientas_llamadas)
    for infinitivo, participio, pasado, herramienta in ACCIONES:
        if herramienta and herramienta in llamadas:
            continue
        for marco in MARCOS:
            patron = marco.format(participio=participio, infinitivo=infinitivo,
                                  pasado=pasado)
            encontrado = re.search(patron, dicho_por_el_agente, re.I)
            if encontrado:
                revision.acciones.append(encontrado.group(0).strip().lower())
                break

    if ("escalar_a_humano" not in llamadas
            and PASAR_CON_HUMANO.search(dicho_por_el_agente)):
        hallado = PASAR_CON_HUMANO.search(dicho_por_el_agente)
        assert hallado is not None
        revision.acciones.append(hallado.group(0).strip().lower())

    return revision
