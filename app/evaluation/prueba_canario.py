r"""El canario: que se niegue a empezar la medición final sin cuota para acabarla.

Esta prueba existe por lo que pasó el 2026-09-25, y lo que pasó fue esto: la
sonda de límites dijo «pasa. Hay cuota para medir», se corrieron tres corridas
de calibración y la cuarta murió a mitad con `Used 199423` de 200 000. Si ese
día se hubiera elegido medir el reservado en vez de calibración, el canario
—que solo comprobaba que UNA petición del tamaño real pasara— habría dado luz
verde y el conjunto se habría gastado a medias. Y medio reservado no es medio
reservado: es un reservado del que ya se sabe algo.

## Cómo se comprueba sin arriesgar nada

`una_corrida` se sustituye por una función que **lanza** si alguien la llama.
Es el mismo truco que `prueba_silencio.py` usa con el modelo: la única forma de
demostrar que algo no se llama es hacer que llamarlo reviente. Así, si el orden
del flujo se rompiera algún día y la comprobación de cuota pasara a hacerse
después de la primera corrida, esta prueba fallaría en vez de quemar el
reservado de verdad.

No gasta ni un token: con la ventana llena, `main` sale antes de la primera
petición.

    .\.venv\Scripts\python.exe -m app.evaluation.prueba_canario
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from app.evaluation import cuota, medicion_final  # noqa: E402
from app.evaluation.particion import reservado  # noqa: E402

AHORA = 1_800_000_000.0
HORA = 3600.0
RESERVADO = reservado(declaro_medicion_final=True)


class SeCorrioElReservado(Exception):
    """Que esto se lance es el fallo que la prueba busca."""


def _explota(casos, groq, modelo):
    raise SeCorrioElReservado(
        f"se llamó a una_corrida con {len(casos)} casos: el canario dejó "
        f"pasar una medición que no cabía")


def con_libro(apuntes: list[tuple[float, int]]) -> None:
    cuota.LIBRO.write_text("", encoding="utf-8")
    for cuando, tokens in apuntes:
        cuota.anotar(tokens, "prueba", cuando=cuando)


def prueba_la_ventana_llena_no_deja_empezar() -> None:
    """Con la ventana gastada, `hay_sitio_para` dice no y dice cuándo sí."""
    con_libro([(time.time() - HORA, 199_737)])
    cabe, detalle = medicion_final.hay_sitio_para(RESERVADO, 5)
    assert not cabe, detalle
    assert "NO caben" in detalle, detalle
    assert "Habrá sitio dentro de" in detalle, detalle


def prueba_la_ventana_limpia_deja_empezar() -> None:
    """Con un gasto pequeño y reciente, las 5 corridas caben de sobra."""
    con_libro([(time.time() - HORA, 5_000)])
    cabe, detalle = medicion_final.hay_sitio_para(RESERVADO, 5)
    assert cabe, detalle
    assert "caben las 5 corridas" in detalle, detalle


def prueba_el_margen_descarta_la_ventana_justa() -> None:
    """Lo que cabe justo NO cabe: el libro es una cota optimista.

    El reservado con k=5 son ~89 250 tokens estimados. Con 100 000 libres
    «cabría», y es exactamente el caso peligroso: el libro solo ve lo que pasa
    por el código instrumentado, así que 100 000 según el libro pueden ser
    60 000 de verdad. El margen del 50% está para descartar esto.
    """
    con_libro([(time.time() - HORA, cuota.LIMITE_VENTANA - 100_000)])
    assert cuota.disponible() == 100_000
    necesarios = cuota.estimar(RESERVADO, 5)
    assert necesarios < 100_000, "el reservado cabría sin margen"
    cabe, detalle = medicion_final.hay_sitio_para(RESERVADO, 5)
    assert not cabe, f"la ventana justa no debería valer: {detalle}"


def prueba_el_libro_vacio_no_es_cuota_libre() -> None:
    """No saber no es lo mismo que saber que hay sitio.

    Es la equivocación del 25/09 con otra cara: ese día se concluyó que había
    cuota porque una petición pasó. Un libro sin apuntes tiene dos explicaciones
    opuestas —la ventana está limpia, o el gasto ocurrió por fuera— y el módulo
    no puede elegir por su cuenta.
    """
    con_libro([])
    assert cuota.libro_ciego()
    cabe, detalle = medicion_final.hay_sitio_para(RESERVADO, 5)
    assert not cabe, detalle
    assert "NO TIENE NI UN APUNTE" in detalle, detalle

    # Y declarándolo, sí: la decisión es de quien la firma, no del programa.
    cabe, detalle = medicion_final.hay_sitio_para(RESERVADO, 5,
                                                 libro_vacio_asumido=True)
    assert cabe, detalle
    assert "se ha declarado" in detalle, detalle


def prueba_k_mas_alto_necesita_mas_sitio() -> None:
    """La estimación escala con k, que es lo que el canario viejo no miraba.

    Con 40 000 libres cabe una corrida del reservado y no caben cinco. El
    canario que solo comprobaba «¿pasa una petición?» habría dicho sí a las dos.
    """
    con_libro([(time.time() - HORA, cuota.LIMITE_VENTANA - 40_000)])
    cabe_una, _ = medicion_final.hay_sitio_para(RESERVADO, 1)
    cabe_cinco, detalle = medicion_final.hay_sitio_para(RESERVADO, 5)
    assert cabe_una, "una corrida cabe en 40 000"
    assert not cabe_cinco, detalle


def prueba_el_reservado_no_se_toca_cuando_no_cabe() -> None:
    """La de verdad: `main` sale sin llamar a `una_corrida` ni una vez.

    Si esto falla lanzando `SeCorrioElReservado`, el canario dejó pasar una
    medición que no cabía y el reservado se habría gastado a medias.
    """
    con_libro([(time.time() - HORA, 199_737)])
    original, argv, raiz = (medicion_final.una_corrida, sys.argv,
                            medicion_final.RAIZ)
    medicion_final.una_corrida = _explota
    sys.argv = ["medicion_final", "--declaro-medicion-final"]
    # RAIZ va a un temporal desde el 2026-09-26, y el motivo es que el reservado
    # ya está medido: con el artefacto de verdad en su sitio, `main` salía con 1
    # por el guardia de «este conjunto ya se midió» y **nunca llegaba al
    # canario**. La prueba seguía en verde el día anterior y habría dejado de
    # cubrir lo que dice el día siguiente, sin avisar. Con RAIZ redirigida, el
    # artefacto no existe en ese directorio y el flujo llega donde tiene que
    # llegar.
    with tempfile.TemporaryDirectory() as temporal:
        (Path(temporal) / "artifacts").mkdir()
        medicion_final.RAIZ = Path(temporal)
        try:
            codigo = medicion_final.main()
        except SeCorrioElReservado as exc:
            raise AssertionError(str(exc)) from exc
        finally:
            (medicion_final.una_corrida, sys.argv,
             medicion_final.RAIZ) = original, argv, raiz
    assert codigo == 3, f"esperaba salir con 3 (no se empieza), salió {codigo}"


PRUEBAS = [prueba_la_ventana_llena_no_deja_empezar,
           prueba_la_ventana_limpia_deja_empezar,
           prueba_el_margen_descarta_la_ventana_justa,
           prueba_el_libro_vacio_no_es_cuota_libre,
           prueba_k_mas_alto_necesita_mas_sitio,
           prueba_el_reservado_no_se_toca_cuando_no_cabe]


# Las mutaciones. Están dentro y no se hacen a mano una vez porque el 24/09
# este proyecto encontró tres pruebas que pasaban con lo que decían proteger
# roto, y hacerlo a mano no deja rastro para el siguiente que toque el módulo.
def _mut_el_canario_dice_siempre_que_cabe() -> None:
    medicion_final.hay_sitio_para = lambda *a, **k: (True, "cabe (mutado)")


def _mut_el_margen_desaparece() -> None:
    original = medicion_final.hay_sitio_para

    def sin_margen(casos, corridas, libro_vacio_asumido=False):
        # Comprobar sin margen es creerse la cota optimista del libro.
        necesarios = cuota.estimar(casos, corridas)
        if cuota.disponible() >= necesarios:
            return True, "cabe sin margen (mutado)"
        return original(casos, corridas, libro_vacio_asumido)
    medicion_final.hay_sitio_para = sin_margen


def _mut_el_libro_vacio_cuenta_como_libre() -> None:
    cuota.libro_ciego = lambda ahora=None: False


def _mut_la_estimacion_ignora_k() -> None:
    original = cuota.estimar
    cuota.estimar = lambda casos, corridas=1: original(casos, 1)


MUTACIONES = [("el canario dice siempre que cabe",
               _mut_el_canario_dice_siempre_que_cabe),
              ("el margen del 50% desaparece", _mut_el_margen_desaparece),
              ("un libro vacío cuenta como cuota libre",
               _mut_el_libro_vacio_cuenta_como_libre),
              ("la estimación ignora k", _mut_la_estimacion_ignora_k)]


def correr(pruebas) -> list[str]:
    fallos = []
    for prueba in pruebas:
        try:
            prueba()
        except AssertionError as exc:
            fallos.append(f"{prueba.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            fallos.append(f"{prueba.__name__}: {type(exc).__name__}: {exc}")
    return fallos


def main() -> int:
    romper = "--romper" in sys.argv
    with tempfile.TemporaryDirectory() as temporal:
        cuota.LIBRO = Path(temporal) / "consumo-groq.jsonl"
        fallos = []
        for prueba in PRUEBAS:
            resultado = correr([prueba])
            if resultado:
                fallos.append(prueba.__name__)
                print(f"  MAL {resultado[0]}")
            else:
                print(f"  ok  {prueba.__name__}")
        print(f"\n  {len(PRUEBAS) - len(fallos)}/{len(PRUEBAS)} del canario")
        if fallos:
            return 1
        if not romper:
            print("\n  (con --romper se comprueba que estas pruebas cazan algo)")
            return 0

        print("\n  MUTACIONES: cada una deja pasar una medición que no cabe")
        guardados = (medicion_final.hay_sitio_para, cuota.libro_ciego,
                     cuota.estimar)
        sin_cazar = []
        for nombre, mutar in MUTACIONES:
            mutar()
            resultado = correr(PRUEBAS)
            (medicion_final.hay_sitio_para, cuota.libro_ciego,
             cuota.estimar) = guardados
            if resultado:
                print(f"    cazada  {nombre}  -> {len(resultado)} prueba(s), "
                      f"la primera {resultado[0].split(':')[0]}")
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
