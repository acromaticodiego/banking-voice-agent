r"""El camino bueno del protocolo, hasta el final y sin gastar un token.

## Por qué hace falta, y por qué justo antes de medir el reservado

El protocolo de la medición final tiene un tramo que **solo se ejecuta cuando
salen las k corridas limpias**: el resumen, la tabla por caso, la mayoría, el
coste por conversación y la escritura del artefacto. Todo lo que se había
probado hasta el 2026-09-26 era el tramo que se NIEGA —sin cuota, con corridas
contaminadas, con el libro ciego—, que es el que se ejercita solo.

Y el tramo del final se toco el 25/09 para añadir la métrica 5, que hasta
entonces salía con `consumo: null`. Código nuevo, en la ruta que solo corre al
terminar, de un programa que se ejecuta **una vez en la vida del proyecto**. Si
ese bloque tuviera un `KeyError` o una división por cero, reventaría después de
las cinco corridas: el reservado quemado, los resultados vistos por pantalla y
ningún artefacto escrito. No habría segunda oportunidad.

## Cómo se prueba sin tocar el reservado ni la cuota

`una_corrida` se sustituye por una que devuelve corridas **sintéticas** y
limpias, con su consumo dentro. El protocolo se ejecuta entero sobre el conjunto
de calibración (`--ensayo`), así que:

  · no se hace ni una petición al modelo —`hay_cuota_para_empezar` solo se llama
    cuando no es ensayo—;
  · no se toca el reservado;
  · y el artefacto se escribe en un directorio temporal, porque `RAIZ` se
    redirige: sin eso, la prueba pisaría el artefacto del ensayo de verdad.

Lo que se comprueba es que el programa **llega al final**, da los cinco números
del protocolo y deja el coste en el artefacto con cifras dentro.

    .\.venv\Scripts\python.exe -m app.evaluation.prueba_protocolo
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from app.evaluation import cuota, medicion_final  # noqa: E402
from app.evaluation.particion import calibracion  # noqa: E402

CASOS = calibracion()

# Desenlaces inventados con una forma concreta: el primer caso acierta siempre,
# el segundo falla siempre, y el tercero acierta 3 de 5. Así la tabla tiene que
# distinguir estable de inestable y la mayoría tiene que salir distinta de la
# mediana, que es justo lo que el protocolo promete publicar.
def _corrida_sintetica(vuelta: int):
    def una(casos, groq, modelo):
        resultados = []
        for i, caso in enumerate(casos):
            if i == 1:
                obtenido = "pide_repetir" if caso.desenlace != "pide_repetir" else "escala"
            elif i == 2:
                obtenido = caso.desenlace if vuelta < 3 else "escala"
            else:
                obtenido = caso.desenlace
            resultados.append({
                "id": caso.id, "esperado": caso.desenlace, "obtenido": obtenido,
                "acierta": medicion_final.acierta(caso, obtenido),
                "dijo": "texto de prueba", "herramientas": [], "resultados": [],
                "filtraciones": ["4582"] if i == 4 and vuelta == 0 else [],
                "promesas": [], "numeros_sin_fundamento": [],
                "acciones_sin_fundamento": [],
            })
        consumo = {c.id: {"tokens_entrada": 2000, "tokens_salida": 150,
                          "peticiones": 3} for c in casos}
        return {"resultados": resultados, "incidencias": [], "agotados": [],
                "aciertos": sum(1 for r in resultados if r["acierta"]),
                "consumo": consumo,
                "tokens_entrada": 2000 * len(casos),
                "tokens_salida": 150 * len(casos),
                "peticiones": 3 * len(casos)}
    return una


def prueba_el_protocolo_llega_al_final() -> None:
    vuelta = {"n": -1}

    def una_corrida(casos, groq, modelo):
        vuelta["n"] += 1
        return _corrida_sintetica(vuelta["n"])(casos, groq, modelo)

    original, argv, raiz = (medicion_final.una_corrida, sys.argv,
                            medicion_final.RAIZ)
    with tempfile.TemporaryDirectory() as temporal:
        destino = Path(temporal)
        (destino / "artifacts").mkdir()
        medicion_final.RAIZ = destino
        medicion_final.una_corrida = una_corrida
        medicion_final.esperar_cuota = lambda groq, modelo, minimo=6000: None
        sys.argv = ["medicion_final", "--ensayo", "--corridas", "5"]
        try:
            codigo = medicion_final.main()
        finally:
            (medicion_final.una_corrida, sys.argv,
             medicion_final.RAIZ) = original, argv, raiz

        assert codigo == 0, f"el protocolo no llegó al final: salió con {codigo}"
        fichero = destino / "artifacts" / "medicion-final-calibracion-ensayo.json"
        assert fichero.exists(), "no escribió el artefacto"
        datos = json.loads(fichero.read_text(encoding="utf-8"))

    # Los cinco números que el protocolo promete publicar.
    for clave in ("mediana", "rango", "por_mayoria", "estables",
                  "aciertos_por_corrida", "por_caso", "coste"):
        assert clave in datos, f"falta {clave} en el artefacto"
    assert len(datos["aciertos_por_corrida"]) == 5, datos["aciertos_por_corrida"]
    assert datos["corridas"] == 5

    # El caso que falla siempre no puede salir por mayoría, y el que acierta 3 de
    # 5 sí: si estos dos coincidieran, la mayoría no estaría midiendo nada.
    por_id = {f["id"]: f for f in datos["por_caso"]}
    siempre_mal = por_id[CASOS[1].id]
    tres_de_cinco = por_id[CASOS[2].id]
    assert siempre_mal["aciertos"] == 0 and not siempre_mal["mayoria"]
    assert tres_de_cinco["aciertos"] == 3, tres_de_cinco["aciertos"]
    assert tres_de_cinco["mayoria"], "3 de 5 es mayoría"
    assert not tres_de_cinco["estable"], "3 de 5 no puede salir estable"

    # Y la fuga de una sola corrida tiene que aparecer: contarla solo cuando
    # pasa en todas dejaría escapar justo el caso del 25/09.
    assert CASOS[4].id in datos["fugas_de_datos"], datos["fugas_de_datos"]


def prueba_el_coste_sale_con_cifras() -> None:
    """La métrica 5, que es el bloque que nunca se había ejecutado.

    60 conversaciones (12 casos x 5 corridas) a 2150 tokens cada una. Los
    números están elegidos para que el resultado se pueda comprobar a mano: si
    el divisor fuera el número de corridas o de turnos en vez de las
    conversaciones, ninguna de estas igualdades se cumpliría.
    """
    vuelta = {"n": -1}

    def una_corrida(casos, groq, modelo):
        vuelta["n"] += 1
        return _corrida_sintetica(vuelta["n"])(casos, groq, modelo)

    original, argv, raiz = (medicion_final.una_corrida, sys.argv,
                            medicion_final.RAIZ)
    with tempfile.TemporaryDirectory() as temporal:
        destino = Path(temporal)
        (destino / "artifacts").mkdir()
        medicion_final.RAIZ = destino
        medicion_final.una_corrida = una_corrida
        medicion_final.esperar_cuota = lambda groq, modelo, minimo=6000: None
        sys.argv = ["medicion_final", "--ensayo", "--corridas", "5"]
        try:
            medicion_final.main()
        finally:
            (medicion_final.una_corrida, sys.argv,
             medicion_final.RAIZ) = original, argv, raiz
        datos = json.loads((destino / "artifacts" /
                            "medicion-final-calibracion-ensayo.json"
                            ).read_text(encoding="utf-8"))

    coste = datos["coste"]
    assert coste["conversaciones"] == 60, coste["conversaciones"]
    assert coste["tokens_entrada"] == 2000 * 12 * 5
    assert coste["tokens_salida"] == 150 * 12 * 5
    assert abs(coste["tokens_por_conversacion"] - 2150) < 0.01, coste
    # El precio de este modelo está confirmado, así que el coste NO puede ser
    # None: si lo fuera, la medición final saldría sin métrica 5 otra vez.
    assert coste["dolares_total"] is not None, "el coste salió sin número"
    assert coste["dolares_por_conversacion"] > 0
    esperado = coste["dolares_total"] / 60
    assert abs(coste["dolares_por_conversacion"] - esperado) < 1e-12
    assert coste["precio_fecha"], "el coste tiene que venir con su fecha"


PRUEBAS = [prueba_el_protocolo_llega_al_final, prueba_el_coste_sale_con_cifras]


# Las dos mutaciones que importan aquí. La segunda es el fallo que este fichero
# vino a evitar: que la medición final salga otra vez sin métrica 5, como pasó
# hasta el 25/09 con `consumo: null`.
def _mut_todo_acierta() -> None:
    medicion_final.acierta = lambda caso, obtenido: True


def _mut_el_precio_sin_confirmar() -> None:
    """Un precio sin confirmar hace que `coste()` devuelva None.

    Es exactamente como salía el artefacto antes del 25/09. Y la primera versión
    de esta mutación no mutaba nada: pasaba `entrada=` y `salida=` a `replace`
    cuando los campos se llaman `entrada_por_millon` y `salida_por_millon`, el
    `TypeError` caía en un `except` que devolvía el precio intacto, y la
    mutación salía «sin cazar» como si la prueba fuera mala. **Un mutador no
    puede tener fallback silencioso**: si no muta, hay que enterarse. Por eso
    aquí no hay try.
    """
    import precios  # noqa: PLC0415
    from dataclasses import replace  # noqa: PLC0415
    original = precios.para
    precios.para = lambda modelo: replace(original(modelo), confirmado=False)


MUTACIONES = [("todo acierta, la tabla por caso no mide nada", _mut_todo_acierta),
              ("el precio sale sin confirmar y el coste queda en None",
               _mut_el_precio_sin_confirmar)]


def main() -> int:
    # El libro, en temporal y con sitio de sobra: lo que se prueba aquí es el
    # final del protocolo, no el canario, que tiene su propia prueba.
    with tempfile.TemporaryDirectory() as temporal:
        cuota.LIBRO = Path(temporal) / "consumo-groq.jsonl"
        cuota.anotar(1000, "prueba", )
        fallos = []
        for prueba in PRUEBAS:
            try:
                prueba()
                print(f"  ok  {prueba.__name__}")
            except AssertionError as exc:
                fallos.append(prueba.__name__)
                print(f"  MAL {prueba.__name__}: {exc}")
            except Exception as exc:  # noqa: BLE001
                fallos.append(prueba.__name__)
                print(f"  MAL {prueba.__name__}: {type(exc).__name__}: {exc}")
        print(f"\n  {len(PRUEBAS) - len(fallos)}/{len(PRUEBAS)} del camino bueno "
              f"del protocolo, sin gastar un token")
        if fallos:
            return 1
        if "--romper" not in sys.argv:
            print("  (con --romper se comprueba que estas pruebas cazan algo)")
            return 0

        print("\n  MUTACIONES")
        import precios  # noqa: PLC0415
        guardados = (medicion_final.acierta, precios.para)
        sin_cazar = []
        for nombre, mutar in MUTACIONES:
            mutar()
            saltaron = []
            for prueba in PRUEBAS:
                try:
                    prueba()
                except Exception:  # noqa: BLE001
                    saltaron.append(prueba.__name__)
            medicion_final.acierta, precios.para = guardados
            if saltaron:
                print(f"    cazada  {nombre}  -> {saltaron[0]}")
            else:
                print(f"    NADIE CAZA  {nombre}")
                sin_cazar.append(nombre)
        if sin_cazar:
            print(f"\n  {len(sin_cazar)} mutación(es) sin cazar.")
            return 1
        print(f"\n  las {len(MUTACIONES)} mutaciones se cazan")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
