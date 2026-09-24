r"""El expediente: que se guarde entero, y que caerse no cueste una llamada.

Dos mitades, y la segunda es la que de verdad importa.

La primera necesita PostgreSQL y **se salta sola si no lo hay**, diciéndolo.
Saltar en silencio sería peor que no tener prueba: dejaría un verde que no
significa nada, que es el error que este proyecto lleva doce veces
coleccionando.

La segunda no necesita nada y comprueba el comportamiento que se decidió en
`app/expediente/almacen.py`: **si la base de datos falla, la llamada sigue**.
Se rompe la conexión a propósito y se mira que anotar no lance, que el fallo
quede contado y que el sistema pueda seguir atendiendo. El día que alguien
"mejore" esto envolviendo las escrituras en un `raise`, esta prueba es la que
lo para.

  .\.venv\Scripts\python.exe -m app.prueba_expediente
"""

from __future__ import annotations

import sys

from app.expediente import DSN_POR_DEFECTO, EnMemoria, EnPostgres, TurnoAnotado

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}")
    else:
        fallos += 1
        print(f"    FALLA  {nombre}" + (f" -> {detalle}" if detalle else ""))


def turno_de_ejemplo(orden: int) -> TurnoAnotado:
    """Un turno con todo lo que un auditor querría ver: lo que se oyó, lo que
    se contestó, la herramienta con sus argumentos y su resultado enteros, y
    lo que el detector encontró sin fundamento."""
    return TurnoAnotado(
        oido=f"Mi cédula es 1070234567, turno {orden}.",
        contestado="Su tarjeta de débito terminada en 4582 está bloqueada.",
        puente="Permítame un momento, lo estoy revisando.",
        confianza={"segmentos": 2, "no_speech_max": 0.09,
                   "avg_logprob_min": -0.31, "prob_idioma": 0.99},
        sin_fundamento={"numeros": [], "acciones": [], "procedimientos": []},
        ms_asr=463, ms_total=2234, ms_primer_audio=1424, ms_primer_dato=2061,
        tokens_entrada=812, tokens_salida=96, peticiones=2,
        clave=f"clave{orden:04d}",
        pasos=[
            {"tipo": "herramienta", "detalle": "consultar_identidad", "ms": 12,
             "argumentos": {"documento": "1070234567"},
             "resultado": {"encontrado": True, "nombre": "Juan Diego Ossa"},
             "error": None, "tokens_entrada": 0, "tokens_salida": 0},
            {"tipo": "modelo", "detalle": "decide contestar", "ms": 1459,
             "argumentos": None, "resultado": None, "error": None,
             "tokens_entrada": 812, "tokens_salida": 96},
        ])


# ------------------------------------------------------- con base de datos

def pruebas_con_postgres(almacen: EnPostgres) -> None:
    print("  el expediente sobrevive a colgar")
    id_llamada = almacen.abrir()
    almacen.anotar_turno(id_llamada, turno_de_ejemplo(1))
    almacen.anotar_turno(id_llamada, turno_de_ejemplo(2))
    almacen.cerrar(id_llamada, motivo="colgo")
    comprobar("escribir dos turnos no dio ningún fallo", almacen.fallos == 0,
              str(almacen.ultimo_error))

    leida = almacen.leer(id_llamada)
    comprobar("la llamada se puede volver a leer", leida is not None)
    if leida is None:
        return

    comprobar("con sus dos turnos", len(leida["conversacion"]) == 2,
              str(len(leida["conversacion"])))
    comprobar("y en orden",
              [t["orden"] for t in leida["conversacion"]] == [1, 2])
    comprobar("el contador de turnos de la llamada cuadra", leida["turnos"] == 2,
              str(leida["turnos"]))
    comprobar("los tokens se acumularon", leida["tokens_entrada"] == 1624,
              str(leida["tokens_entrada"]))
    comprobar("queda escrito cómo terminó", leida["motivo_cierre"] == "colgo",
              str(leida["motivo_cierre"]))

    primero = leida["conversacion"][0]
    comprobar("se guardó lo que se oyó", "1070234567" in primero["oido"])
    comprobar("y lo que se contestó", "4582" in primero["contestado"])
    comprobar("la confianza del voz a texto viaja entera",
              primero["confianza"]["no_speech_max"] == 0.09,
              str(primero["confianza"]))
    comprobar("y la clave de idempotencia del turno",
              primero["clave"] == "clave0001", str(primero["clave"]))

    herramienta = [p for p in primero["pasos"] if p["tipo"] == "herramienta"]
    comprobar("el paso de herramienta está", len(herramienta) == 1)
    if herramienta:
        comprobar("CON SUS ARGUMENTOS, que es la mitad del expediente",
                  herramienta[0]["argumentos"] == {"documento": "1070234567"},
                  str(herramienta[0]["argumentos"]))
        comprobar("y con lo que devolvió, entero y sin resumir",
                  herramienta[0]["resultado"]["nombre"] == "Juan Diego Ossa",
                  str(herramienta[0]["resultado"]))

    print("  'no se revisó' y 'se revisó y estaba limpio' no son lo mismo")
    otra = almacen.abrir()
    almacen.anotar_turno(otra, TurnoAnotado(oido="hola", sin_fundamento=None))
    almacen.anotar_turno(otra, TurnoAnotado(oido="hola", sin_fundamento={
        "numeros": [], "acciones": [], "procedimientos": []}))
    leida2 = almacen.leer(otra)
    assert leida2 is not None
    sin_revisar = leida2["conversacion"][0]["sin_fundamento"]
    revisado = leida2["conversacion"][1]["sin_fundamento"]
    comprobar("el turno sin revisar guarda NULL", sin_revisar is None,
              str(sin_revisar))
    comprobar("el revisado y limpio guarda el diccionario vacío",
              revisado == {"numeros": [], "acciones": [], "procedimientos": []},
              str(revisado))


# --------------------------------------------------- sin base de datos

def prueba_la_caida_no_cuesta_la_llamada() -> None:
    """Lo más importante de este archivo."""
    print("  una base de datos caída NO tumba la llamada")
    try:
        almacen = EnPostgres(DSN_POR_DEFECTO)
    except Exception:  # noqa: BLE001
        print("    (sin Postgres: se usa el almacén en memoria para la forma)")
        almacen = None

    if almacen is None:
        return

    id_llamada = almacen.abrir()
    almacen.cerrar_conexion()          # se cae la base a mitad de llamada
    try:
        almacen.anotar_turno(id_llamada, turno_de_ejemplo(9))
        almacen.cerrar(id_llamada)
        comprobar("anotar con la conexión rota no lanza", True)
    except Exception as exc:  # noqa: BLE001
        comprobar("anotar con la conexión rota no lanza", False,
                  f"{type(exc).__name__}: {exc}")
    comprobar("y el expediente perdido queda CONTADO, no en silencio",
              almacen.fallos >= 1, f"fallos={almacen.fallos}")
    comprobar("con el motivo a mano para poder leerlo",
              bool(almacen.ultimo_error), str(almacen.ultimo_error))


def pruebas_en_memoria() -> None:
    print("  el almacén en memoria cumple la misma interfaz")
    almacen = EnMemoria()
    id_llamada = almacen.abrir()
    almacen.anotar_turno(id_llamada, turno_de_ejemplo(1))
    almacen.cerrar(id_llamada, motivo="escalada")
    leida = almacen.leer(id_llamada)
    comprobar("guarda y devuelve", leida is not None and len(leida["turnos"]) == 1)
    comprobar("y anota cómo terminó",
              leida is not None and leida["motivo"] == "escalada")


def main() -> int:
    print("El expediente de la llamada\n")
    pruebas_en_memoria()

    try:
        almacen = EnPostgres(DSN_POR_DEFECTO)
    except Exception as exc:  # noqa: BLE001
        print(f"\n  SALTADAS las pruebas contra PostgreSQL: no hay base de "
              f"datos ({type(exc).__name__}).")
        print("  Esto NO es verde: levántala con  docker compose up -d  "
              "y repite.")
        print("\n  SIN COMPROBAR (código de salida 2)")
        # Código 2, y no 0, por una razón que este proyecto ya se ha tragado
        # varias veces: un programa que avisa por pantalla de que no ha
        # comprobado nada y luego sale con 0 acaba contado como verde por
        # cualquier bucle que mire el código de salida. Pasó con esta misma
        # prueba el mismo día que se escribió: el aviso estaba ahí, en su
        # línea, y la tabla de resultados dijo OK igualmente.
        return 2

    try:
        pruebas_con_postgres(almacen)
    finally:
        almacen.cerrar_conexion()
    prueba_la_caida_no_cuesta_la_llamada()

    print(f"\n{'TODO BIEN' if not fallos else f'{fallos} FALLOS'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
