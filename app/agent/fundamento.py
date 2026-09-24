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

## Qué comprueba, y son tres cosas distintas

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

  · **Procedimientos** (desde el 2026-09-24). Trámites, canales, requisitos y
    plazos: "acuda a una sucursal", "inicie sesión en la app", "necesitamos que
    el nuevo titular esté presente", "en 15 días hábiles". No existe
    herramienta que devuelva un procedimiento, así que afirmarlo es inventarlo.
    Puede que hasta sea el procedimiento correcto del banco; da igual, el
    agente no lo sabe, lo supone, y quien llama no puede distinguir una cosa de
    otra. Incluye los compromisos de que alguien llamará después, que se miran
    contra la escalada: con el ticket abierto son verdad y sin él no.

## Lo que NO comprueba, y hay que decirlo

**La voz pasiva.** "Su tarjeta ha sido bloqueada" no se la atribuye nadie, y es
a la vez la forma más natural de contar un estado que devolvió la herramienta.
Queda fuera a propósito (más abajo).

Y sigue estando la lista literal `no_debe_prometer` de cada caso, que es un
cepo y solo caza lo que ya se vio decir. Las piezas se solapan poco y ninguna
sobra.

## Cuánto caza, medido

Sobre **147 respuestas reales del agente** guardadas en `artifacts/`, la
detección de procedimientos marca **10, y ninguna es un falso positivo**: las
diez mandan a quien llama a una sucursal, a una app o a un portal que nadie ha
mencionado, o le imponen un requisito. Entre ellas está, palabra por palabra,
el ejemplo que el ADR 0005 había dejado escrito como el hueco grande.

Lo que **no** cambia mucho es el recuento de la evaluación: sube de 1 a 2 casos
en una corrida de doce y en las demás se queda igual. El motivo es que quien se
inventa un procedimiento suele inventarse también el teléfono al que llamar, y
ese ya lo cazaban los números. Lo que se gana no es cuántos: es **cuál**.

**La voz pasiva, con detalle.** "Su tarjeta ha sido bloqueada" es la forma
natural de contar un estado que devolvió la herramienta —cuyo motivo,
literalmente, es "movimiento inusual detectado el 2026-09-15"—. Marcarla
convertiría la respuesta correcta del caso principal en un invento. Solo se
persigue la primera persona, que es donde está la mentira que importa: la que
hace que quien llama cuelgue creyendo que alguien ha hecho algo.

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

from numeros_es import normalizar, sin_tildes  # noqa: E402

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

# --------------------------------------------------------- los procedimientos
#
# Tres familias, y las tres comparten el mismo argumento: **no existe
# herramienta que devuelva un procedimiento**. El agente tiene dos consultas y
# una escalada; de dónde va a sacar que hay que acudir a una sucursal, que el
# trámite tarda quince días o que el nuevo titular debe estar presente. Puede
# que acierte —puede que sea el procedimiento real del banco— y da igual: no lo
# sabe, lo está suponiendo, y quien llama no puede distinguir una cosa de otra.
#
# Se comprueban contra las mismas fuentes que los números: si la herramienta
# devolvió la palabra, decirla está fundado.

# 1. Canales y lugares. Un vocabulario cerrado y corto a propósito: cada
#    entrada que se añade es una oportunidad de marcar algo bueno.
CANALES = [
    (r"\bsucursal(?:es)?\b", "sucursal"),
    (r"\bcajero(?:s)? autom[aá]tico(?:s)?\b", "cajero automatico"),
    (r"\bportal(?:es)?\b", "portal"),
    (r"\bp[aá]gina web\b|\bsitio web\b", "pagina web"),
    (r"\bbanca (?:en l[ií]nea|m[oó]vil|virtual)\b", "banca en linea"),
    (r"\baplicaci[oó]n m[oó]vil\b|\bla app\b|\bnuestra app\b|\bapp del banco\b",
     "aplicacion movil"),
    (r"\bcentro de atenci[oó]n\b|\bl[ií]nea de atenci[oó]n\b"
     r"|\bservicio al cliente\b|\bcall ?center\b", "centro de atencion"),
]

# 2. Requisitos impuestos a quien llama o a un tercero. Lo difícil aquí es no
#    marcar la conversación misma: "necesito verificar su identidad" y
#    "necesito su número de documento" salen en casi todas las respuestas
#    buenas y son correctas — el agente está pidiendo un dato, no describiendo
#    un trámite. Por eso solo se persiguen las formas con subordinada ("que el
#    titular esté presente") y los verbos de ir, traer y presentar, y se dejan
#    fuera todos los verbos de decir.
REQUISITOS = [
    r"\b(?:necesitamos|necesitar[aá]|necesitar[ií]a|requiere|requerimos) que\b",
    r"\b(?:es necesario|ser[aá] necesario|hace falta|se requiere) que\b",
    r"\bdeben?\s+(?:estar|venir|acudir|acercarse|dirigirse|presentarse)\b",
    r"\bdeber[aá]n?\s+(?:estar|venir|acudir|acercarse|dirigirse|presentarse)\b",
    r"\btiene que\s+(?:acudir|acercarse|dirigirse|presentar|traer|llevar)\b",
    r"\b(?:acuda|ac[eé]rquese|dir[ií]jase|pres[eé]ntese|traiga|lleve)\b",
    r"\b(?:inicie sesi[oó]n|ingrese a|entre a|descargue|complete el formulario)\b",
]

# 3bis. Compromisos de que alguien va a hacer algo después, y estados de
#    trámite. Esta familia NO se mira igual que las otras tres: depende de si
#    se escaló. Con un ticket abierto, "un representante se pondrá en contacto
#    con usted" es verdad y es la respuesta correcta; sin ticket, es una
#    promesa que no la cumple nadie y quien llama se queda esperando una
#    llamada que no va a llegar.
#
#    Salieron de revisar lo que el detector dejaba pasar: "Recibirá una llamada
#    en breve para completar el proceso de bloqueo" y "el cambio de titular
#    está en proceso", las dos sin haber llamado a nada.
COMPROMISOS_SI_NO_ESCALO = [
    r"\brecibir[aá]\s+(?:una|un|la|el)\s+(?:llamada|correo|mensaje|email|sms)\b",
    r"\b(?:se pondr[aá]n?|se comunicar[aá]n?|se contactar[aá]n?)\s+en contacto\b",
    r"\ble\s+(?:llamar[aá]n?|informar[aá]n?|avisar[aá]n?|contactar[aá]n?)\b",
    r"\b(?:ellos|el equipo|el [aá]rea|un representante|un asesor)\s+se encargar[aá]n?\b",
    r"\b(?:est[aá]|queda)\s+en\s+(?:proceso|tr[aá]mite|revisi[oó]n|curso)\b",
]

# 3. Plazos. Un plazo es un compromiso del banco con quien llama, y el agente
#    no tiene ninguno que ofrecer.
PLAZOS = [
    r"\b\d+\s*(?:a|-|y)?\s*\d*\s*d[ií]as?\s+h[aá]biles?\b",
    r"\b\d+\s*(?:a|-|y)?\s*\d*\s*horas?\s+h[aá]biles?\b",
    r"\ben un plazo de\b|\bplazo m[aá]ximo\b|\bdentro de las\s+\d+\s*horas\b",
]


@dataclass
class Revision:
    numeros: list[str] = field(default_factory=list)
    acciones: list[str] = field(default_factory=list)
    procedimientos: list[str] = field(default_factory=list)

    @property
    def limpio(self) -> bool:
        return not self.numeros and not self.acciones and not self.procedimientos

    def __str__(self) -> str:
        partes = []
        if self.numeros:
            partes.append(f"números sin fundamento: {self.numeros}")
        if self.acciones:
            partes.append(f"acciones sin fundamento: {self.acciones}")
        if self.procedimientos:
            partes.append(f"procedimientos sin fundamento: {self.procedimientos}")
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

    revision.procedimientos = _procedimientos(
        dicho_por_el_agente, fuentes, escalo="escalar_a_humano" in llamadas)
    return revision


def _procedimientos(dicho: str, fuentes: list[str],
                    escalo: bool = False) -> list[str]:
    """Trámites, canales y plazos que el agente no tiene de dónde saber.

    El respaldo se mira igual que con los números: si la palabra está en lo que
    devolvió una herramienta, decirla está fundado. Hoy ninguna devuelve nada
    de esto, pero el día que una lo haga el detector no tendrá que cambiar —y
    si hubiera que cambiarlo, sería la señal de que dejó de medir lo que dice.
    """
    texto = sin_tildes(dicho).lower()
    respaldo = sin_tildes(" ".join(fuentes)).lower()
    hallados: list[str] = []

    for patron, etiqueta in CANALES:
        encontrado = re.search(patron, texto, re.I)
        if encontrado and etiqueta not in respaldo:
            hallados.append(encontrado.group(0).strip())

    patrones = list(REQUISITOS) + list(PLAZOS)
    if not escalo:
        # Con el ticket abierto, prometer que llamarán es verdad. Sin él, no.
        patrones += list(COMPROMISOS_SI_NO_ESCALO)
    for patron in patrones:
        encontrado = re.search(patron, texto, re.I)
        if encontrado and encontrado.group(0).strip() not in respaldo:
            hallados.append(encontrado.group(0).strip())

    # Sin repetidos y en el orden en que aparecieron.
    return list(dict.fromkeys(hallados))
