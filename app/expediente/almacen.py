r"""Dónde queda lo que pasó en una llamada, cuando la llamada termina.

El README lleva desde el principio prometiendo esto:

    "Al colgar queda un expediente con qué se dijo, qué herramienta se llamó,
     con qué argumentos, qué devolvió y qué evidencia justificó cada decisión."

Y hasta el 2026-09-24 era falso: el rastro existía en memoria y se perdía al
cerrar el proceso. De todas las distancias entre lo que el proyecto promete y
lo que hace, esa era la mayor, y en banca es la que más se nota — un agente
que atiende y no deja registro no se puede desplegar, por bueno que sea.

## La decisión que hay detrás de casi todo este archivo

**Una base de datos caída no puede tumbar una llamada en curso.** Si Postgres
no responde a mitad de una conversación, lo correcto no es cortarle la llamada
a quien está hablando: es seguir atendiéndole y anotar que se perdió el
registro. Es el mismo criterio del ADR 0006 con las herramientas —el error es
un resultado, no una excepción— y tiene un precio que hay que decir en voz
alta: **se puede perder expediente**. Por eso lo que se pierde se cuenta, y
`fallos` y `ultimo_error` son parte de la interfaz y no un detalle interno.
Un expediente que se pierde en silencio es peor que no tenerlo, porque nadie
sabe que falta.

La alternativa —cortar la llamada para garantizar el registro— es defendible en
otros sistemas, y en algunos reguladores es la obligatoria. Si algún día hay
que cambiar, el sitio es este y la decisión está escrita.

## Dos almacenes, misma interfaz

  · `EnMemoria` es lo que había, con nombre. Sirve para las pruebas y para
    correr la demo sin levantar nada.
  · `EnPostgres` es el de verdad.

Que los dos cumplan la misma interfaz no es elegancia: es lo que permite que
las pruebas del sistema no necesiten una base de datos, y que una demo en un
portátil ajeno no dependa de Docker.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ESQUEMA = Path(__file__).with_name("esquema.sql")


@dataclass
class TurnoAnotado:
    """Lo que se guarda de un turno. Plano a propósito: lo que entra aquí es lo
    que se puede auditar después, así que se ve de un vistazo qué hay y qué no."""

    oido: str = ""
    contestado: str = ""
    puente: str = ""
    confianza: dict | None = None
    sin_fundamento: dict | None = None
    ms_asr: int | None = None
    ms_total: int | None = None
    ms_primer_audio: int | None = None
    ms_primer_dato: int | None = None
    agotado: bool = False
    silencio: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    peticiones: int = 0
    clave: str | None = None
    pasos: list[dict] = field(default_factory=list)


def pasos_desde_rastro(rastro: list) -> list[dict]:
    """El rastro que produce el bucle del agente, listo para guardar.

    Vive aquí y no en el bucle porque el bucle no tiene por qué saber que
    existe una base de datos.
    """
    return [{
        "tipo": p.tipo,
        "detalle": p.detalle,
        "ms": round(p.ms) if p.ms is not None else None,
        "argumentos": p.argumentos,
        "resultado": p.resultado,
        "error": p.error,
        "tokens_entrada": p.tokens_entrada,
        "tokens_salida": p.tokens_salida,
    } for p in rastro]


class EnMemoria:
    """El expediente de hasta hoy: existe mientras el proceso vive."""

    def __init__(self) -> None:
        self.llamadas: dict[str, dict] = {}
        self.fallos = 0
        self.ultimo_error: str | None = None

    @property
    def disponible(self) -> bool:
        return True

    def abrir(self) -> str:
        id_llamada = str(uuid.uuid4())
        self.llamadas[id_llamada] = {"turnos": [], "cerrada": None, "motivo": None}
        return id_llamada

    def anotar_turno(self, id_llamada: str, turno: TurnoAnotado) -> None:
        self.llamadas[id_llamada]["turnos"].append(turno)

    def cerrar(self, id_llamada: str, motivo: str = "colgo") -> None:
        self.llamadas[id_llamada]["cerrada"] = True
        self.llamadas[id_llamada]["motivo"] = motivo

    def leer(self, id_llamada: str) -> dict | None:
        return self.llamadas.get(id_llamada)


class EnPostgres:
    """El expediente que sobrevive a colgar, y al proceso.

    Cada turno se escribe **cuando termina**, no al colgar. Si se guardara todo
    al final, una caída del proceso a mitad de llamada se llevaría la
    conversación entera — y las llamadas que peor acaban son justo las que más
    falta hace poder leer después.
    """

    def __init__(self, dsn: str, crear_esquema: bool = True) -> None:
        import psycopg  # noqa: PLC0415

        self._psycopg = psycopg
        self.dsn = dsn
        self.fallos = 0
        self.ultimo_error: str | None = None
        self.conexion = psycopg.connect(dsn, autocommit=True)
        if crear_esquema:
            with self.conexion.cursor() as cur:
                cur.execute(ESQUEMA.read_text(encoding="utf-8"))

    @property
    def disponible(self) -> bool:
        return self.conexion is not None and not self.conexion.closed

    # ------------------------------------------------------------- escritura

    def _fallo(self, donde: str, exc: Exception) -> None:
        """Lo que se pierde, se cuenta. Ver la cabecera del módulo."""
        self.fallos += 1
        self.ultimo_error = f"{donde}: {type(exc).__name__}: {exc}"

    def abrir(self) -> str:
        id_llamada = str(uuid.uuid4())
        try:
            with self.conexion.cursor() as cur:
                cur.execute("INSERT INTO llamada (id) VALUES (%s)", (id_llamada,))
        except Exception as exc:  # noqa: BLE001
            self._fallo("abrir", exc)
        return id_llamada

    def anotar_turno(self, id_llamada: str, turno: TurnoAnotado) -> None:
        try:
            with self.conexion.transaction(), self.conexion.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM turno "
                            "WHERE llamada_id = %s", (id_llamada,))
                fila = cur.fetchone()
                orden = fila[0] if fila else 1

                cur.execute(
                    """INSERT INTO turno (llamada_id, orden, oido, contestado,
                           puente, confianza, sin_fundamento, ms_asr, ms_total,
                           ms_primer_audio, ms_primer_dato, agotado, silencio,
                           tokens_entrada, tokens_salida, peticiones, clave)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING id""",
                    (id_llamada, orden, turno.oido, turno.contestado, turno.puente,
                     _js(turno.confianza), _js(turno.sin_fundamento),
                     turno.ms_asr, turno.ms_total, turno.ms_primer_audio,
                     turno.ms_primer_dato, turno.agotado, turno.silencio,
                     turno.tokens_entrada, turno.tokens_salida, turno.peticiones,
                     turno.clave))
                fila = cur.fetchone()
                assert fila is not None
                id_turno = fila[0]

                for i, paso in enumerate(turno.pasos, start=1):
                    cur.execute(
                        """INSERT INTO paso (turno_id, orden, tipo, detalle, ms,
                               argumentos, resultado, error, tokens_entrada,
                               tokens_salida)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (id_turno, i, paso.get("tipo", ""), paso.get("detalle", ""),
                         paso.get("ms"), _js(paso.get("argumentos")),
                         _js(paso.get("resultado")), paso.get("error"),
                         paso.get("tokens_entrada", 0), paso.get("tokens_salida", 0)))

                # Los totales de la llamada se llevan al día en la misma
                # transacción que el turno. Sumarlos al cerrar obligaría a
                # releerlo todo, y una llamada que nunca se cierra —el proceso
                # se cayó, la red se fue— se quedaría con los contadores a cero
                # teniendo los turnos guardados.
                cur.execute(
                    """UPDATE llamada SET turnos = turnos + 1,
                           tokens_entrada = tokens_entrada + %s,
                           tokens_salida = tokens_salida + %s,
                           peticiones = peticiones + %s
                       WHERE id = %s""",
                    (turno.tokens_entrada, turno.tokens_salida,
                     turno.peticiones, id_llamada))
        except Exception as exc:  # noqa: BLE001
            self._fallo("anotar_turno", exc)

    def cerrar(self, id_llamada: str, motivo: str = "colgo") -> None:
        try:
            with self.conexion.cursor() as cur:
                cur.execute("UPDATE llamada SET cerrada_en = now(), "
                            "motivo_cierre = %s WHERE id = %s",
                            (motivo, id_llamada))
        except Exception as exc:  # noqa: BLE001
            self._fallo("cerrar", exc)

    # --------------------------------------------------------------- lectura

    def leer(self, id_llamada: str) -> dict | None:
        """La llamada entera, como la leería quien audita."""
        try:
            with self.conexion.cursor() as cur:
                cur.execute(
                    "SELECT id, abierta_en, cerrada_en, motivo_cierre, turnos, "
                    "tokens_entrada, tokens_salida, peticiones "
                    "FROM llamada WHERE id = %s", (id_llamada,))
                fila = cur.fetchone()
                if fila is None:
                    return None
                llamada = {
                    "id": str(fila[0]), "abierta_en": fila[1], "cerrada_en": fila[2],
                    "motivo_cierre": fila[3], "turnos": fila[4],
                    "tokens_entrada": fila[5], "tokens_salida": fila[6],
                    "peticiones": fila[7], "conversacion": [],
                }

                cur.execute(
                    "SELECT id, orden, oido, contestado, puente, confianza, "
                    "sin_fundamento, ms_total, agotado, silencio, clave "
                    "FROM turno WHERE llamada_id = %s ORDER BY orden",
                    (id_llamada,))
                turnos = cur.fetchall()
                for t in turnos:
                    cur.execute(
                        "SELECT orden, tipo, detalle, ms, argumentos, resultado, "
                        "error FROM paso WHERE turno_id = %s ORDER BY orden",
                        (t[0],))
                    pasos = [{"orden": p[0], "tipo": p[1], "detalle": p[2],
                              "ms": p[3], "argumentos": p[4], "resultado": p[5],
                              "error": p[6]} for p in cur.fetchall()]
                    llamada["conversacion"].append({
                        "orden": t[1], "oido": t[2], "contestado": t[3],
                        "puente": t[4], "confianza": t[5], "sin_fundamento": t[6],
                        "ms_total": t[7], "agotado": t[8], "silencio": t[9],
                        "clave": t[10], "pasos": pasos})
                return llamada
        except Exception as exc:  # noqa: BLE001
            self._fallo("leer", exc)
            return None

    def cerrar_conexion(self) -> None:
        if self.conexion is not None and not self.conexion.closed:
            self.conexion.close()


def _js(valor: Any) -> str | None:
    """A JSON para una columna JSONB, o None. `None` y `{}` no son lo mismo:
    "no se revisó" y "se revisó y no había nada" tienen que poder distinguirse
    tres meses después."""
    if valor is None:
        return None
    return json.dumps(valor, ensure_ascii=False, default=str)
