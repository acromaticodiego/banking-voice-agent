r"""El libro de la cuota: que cuente lo de la ventana y nada más.

No gasta ni una petición ni un token: todo va con un libro temporal y con la
hora pasada a mano, así que es determinista.

## Por qué lleva las mutaciones dentro

El 2026-09-24 este proyecto descubrió tres pruebas que pasaban sin cubrir lo
que decían cubrir, y una de ellas seguía en verde con la propiedad que
protegía deliberadamente rota. La lección fue que romper las pruebas a
propósito es la única manera de saber que sirven, y que hacerlo a mano una vez
no deja rastro: la siguiente persona que toque el módulo no repetirá el
ejercicio.

Así que está dentro. `--romper` aplica una a una las mutaciones de la lista de
abajo —cada una desactiva una propiedad concreta del módulo— y comprueba que
con cada una **falla al menos una prueba**. Si una mutación pasa sin que salte
nada, la salida lo dice con nombre y apellidos: esa propiedad no está
protegida.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from app.evaluation import cuota  # noqa: E402
from app.evaluation.particion import calibracion, reservado  # noqa: E402

AHORA = 1_800_000_000.0  # una hora fija, para que nada dependa del reloj
HORA = 3600.0

# El cuerpo literal del 429 que el 2026-09-25 destapó que la ventana es
# deslizante. Se guarda tal cual porque el formato del mensaje es lo único de
# donde se puede sacar el gasto real, y si Groq lo cambia esta prueba lo dirá.
MENSAJE_429 = (
    "RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit "
    "reached for model `openai/gpt-oss-20b` in organization `org_01m2y` "
    "service tier `on_demand` on tokens per day (TPD): Limit 200000, "
    "Used 199423, Requested 737. Please try again in 1m9.12s"
)


def con_libro_limpio(apuntes: list[tuple[float, int]]) -> None:
    """Deja el libro con exactamente esos apuntes: (hora, tokens)."""
    cuota.LIBRO.write_text("", encoding="utf-8")
    for cuando, tokens in apuntes:
        cuota.anotar(tokens, "prueba", cuando=cuando)


def prueba_la_ventana_deja_salir_lo_viejo() -> None:
    """Un gasto de hace más de 24 h no cuenta. Es toda la razón del módulo."""
    con_libro_limpio([(AHORA - 25 * HORA, 50_000),
                      (AHORA - 2 * HORA, 30_000)])
    assert cuota.gastado(AHORA) == 30_000, cuota.gastado(AHORA)
    assert len(cuota.entradas(AHORA)) == 1
    assert cuota.disponible(AHORA) == 170_000, cuota.disponible(AHORA)


def prueba_el_borde_de_la_ventana() -> None:
    """Justo dentro cuenta; justo fuera, no.

    El borde importa porque la decisión de si se puede empezar una medición se
    toma a veces a minutos de que la ventana se despeje.
    """
    con_libro_limpio([(AHORA - VENTANA_JUSTO_DENTRO, 10_000)])
    assert cuota.gastado(AHORA) == 10_000
    con_libro_limpio([(AHORA - cuota.VENTANA_S, 10_000)])
    assert cuota.gastado(AHORA) == 0, "un gasto de hace exactamente 24 h ya salió"


VENTANA_JUSTO_DENTRO = 24 * 3600 - 1


def prueba_lo_que_cabe_no_espera() -> None:
    con_libro_limpio([(AHORA - HORA, 100_000)])
    assert cuota.espera_para(90_000, AHORA) == 0.0
    assert cuota.espera_para(100_000, AHORA) == 0.0, "100 000 caben justos"


def prueba_cuando_cabra_mira_las_marcas_de_tiempo() -> None:
    """La cifra que de verdad hace falta: a qué hora habrá sitio.

    Tres gastos de 60 000, hace 23, 20 y 1 horas. Dentro hay 180 000, así que
    quedan 20 000. Para que quepan 70 000 hacen falta 50 000 más, y eso lo da
    el primer apunte en salir: el de hace 23 h, que sale dentro de 1 h.

    Y para que quepan 130 000 no basta ese: hacen falta dos, así que hay que
    esperar a que salga el de hace 20 h, o sea 4 h.
    """
    con_libro_limpio([(AHORA - 23 * HORA, 60_000),
                      (AHORA - 20 * HORA, 60_000),
                      (AHORA - 1 * HORA, 60_000)])
    assert cuota.disponible(AHORA) == 20_000, cuota.disponible(AHORA)
    espera = cuota.espera_para(70_000, AHORA)
    assert abs(espera - 1 * HORA) < 1.0, f"esperaba 1 h, dio {espera}"
    espera = cuota.espera_para(130_000, AHORA)
    assert abs(espera - 4 * HORA) < 1.0, f"esperaba 4 h, dio {espera}"


def prueba_lo_imposible_se_distingue_de_la_espera() -> None:
    """Pedir más que la ventana entera no es «espera»: es que no cabe nunca."""
    con_libro_limpio([(AHORA - HORA, 10_000)])
    assert cuota.espera_para(cuota.LIMITE_VENTANA + 1, AHORA) is None
    assert cuota.espera_para(cuota.LIMITE_VENTANA, AHORA) is not None


def prueba_se_lee_el_used_del_429() -> None:
    assert cuota.used_del_429(MENSAJE_429) == 199_423
    assert cuota.used_del_429("un error cualquiera sin cifras") is None
    assert cuota.used_del_429("") is None


def prueba_se_distingue_la_falta_de_cuota_de_otros_fallos() -> None:
    """«Mi petición de prueba falló» no es «no hay cuota».

    Los dos mensajes de abajo son literales del 2026-09-25: el 400 es el que
    hacía que el canario de la medición final anunciara falta de cuota cuando
    lo que fallaba era su propia petición, y el de conexión es la trampa
    conocida del entorno (el DNS a api.groq.com se cae cada pocos minutos).
    """
    assert cuota.es_falta_de_cuota(MENSAJE_429)
    assert cuota.es_falta_de_cuota(
        "RateLimitError: Rate limit reached for model `openai/gpt-oss-20b`")
    assert not cuota.es_falta_de_cuota(
        "BadRequestError: Error code: 400 - {'error': {'message': 'Tool choice "
        "is none, but model called a tool'}}")
    assert not cuota.es_falta_de_cuota("APIConnectionError: Connection error.")
    assert not cuota.es_falta_de_cuota("")


def prueba_la_correccion_es_conservadora() -> None:
    """Lo que el libro no veía se anota, y con la marca de AHORA.

    Es el caso del 25/09: el libro tenía 148 000 y Groq dijo 199 423. Los
    51 423 que faltaban se gastaron en algún momento desconocido, y ponerles la
    hora de ahora hace que salgan de la ventana lo más tarde posible. Si se les
    pusiera una hora antigua, el libro volvería a prometer cuota que no hay.
    """
    con_libro_limpio([(AHORA - 2 * HORA, 148_000)])
    desajuste = cuota.corregir_con_429(MENSAJE_429, ahora=AHORA)
    assert desajuste == 51_423, desajuste
    assert cuota.gastado(AHORA) == 199_423, cuota.gastado(AHORA)
    assert cuota.disponible(AHORA) == 577

    # Y sale de la ventana 24 h después de ahora, no 22 h después.
    assert cuota.gastado(AHORA + 23 * HORA) == 51_423
    assert cuota.gastado(AHORA + cuota.VENTANA_S + 1) == 0

    # Un 429 cuando el libro ya está al día no inventa gasto de más.
    con_libro_limpio([(AHORA - HORA, 199_423)])
    assert cuota.corregir_con_429(MENSAJE_429, ahora=AHORA) == 0
    assert cuota.gastado(AHORA) == 199_423


def prueba_un_apunte_corrupto_no_tumba_el_libro() -> None:
    con_libro_limpio([(AHORA - HORA, 1_000)])
    with cuota.LIBRO.open("a", encoding="utf-8") as fichero:
        fichero.write("esto no es json\n{\"cuando\": \"ayer\"}\n\n")
    cuota.anotar(2_000, "despues del destrozo", cuando=AHORA - HORA)
    assert cuota.gastado(AHORA) == 3_000, cuota.gastado(AHORA)


def prueba_la_estimacion_de_los_conjuntos_reales() -> None:
    """Con los conjuntos de verdad, para que el número sea comprobable.

    Calibración: 12 casos, 24 turnos. Reservado: 8 casos, 14 turnos. A 1275
    tokens por turno, medido el 25/09 con n=3.
    """
    cal, res = calibracion(), reservado(declaro_medicion_final=True)
    assert cuota.estimar(cal) == 1275 * 24, cuota.estimar(cal)
    assert cuota.estimar(res) == 1275 * 14 == 17_850, cuota.estimar(res)
    assert cuota.estimar(res, corridas=5) == 89_250, cuota.estimar(res, 5)
    # La medición final no cabe en lo que queda de una ventana medio gastada, y
    # eso es exactamente lo que el 25/09 nadie comprobó.
    con_libro_limpio([(AHORA - 2 * HORA, 148_000)])
    assert cuota.disponible(AHORA) < cuota.estimar(res, corridas=5)


PRUEBAS = [prueba_la_ventana_deja_salir_lo_viejo,
           prueba_se_distingue_la_falta_de_cuota_de_otros_fallos,
           prueba_el_borde_de_la_ventana,
           prueba_lo_que_cabe_no_espera,
           prueba_cuando_cabra_mira_las_marcas_de_tiempo,
           prueba_lo_imposible_se_distingue_de_la_espera,
           prueba_se_lee_el_used_del_429,
           prueba_la_correccion_es_conservadora,
           prueba_un_apunte_corrupto_no_tumba_el_libro,
           prueba_la_estimacion_de_los_conjuntos_reales]


# Cada mutación desactiva UNA propiedad del módulo. Si ninguna prueba salta,
# esa propiedad no está protegida por nada.
def _mut_ventana_infinita() -> None:
    cuota.VENTANA_S = 10 ** 9


def _mut_espera_siempre_cero() -> None:
    cuota.espera_para = lambda necesarios, ahora=None: 0.0


def _mut_limite_enorme() -> None:
    cuota.LIMITE_VENTANA = 10 ** 9


def _mut_correccion_con_marca_vieja() -> None:
    original = cuota.corregir_con_429

    def corregir(mensaje, ahora=None):
        ahora = time.time() if ahora is None else ahora
        # El error que la prueba tiene que cazar: fechar lo desconocido en el
        # pasado, con lo que sale de la ventana antes de tiempo.
        return original(mensaje, ahora=ahora - 23 * HORA)
    cuota.corregir_con_429 = corregir


def _mut_todo_parece_falta_de_cuota() -> None:
    cuota.es_falta_de_cuota = lambda mensaje: True


def _mut_no_anota_la_correccion() -> None:
    cuota.corregir_con_429 = lambda mensaje, ahora=None: 0


MUTACIONES = [("la ventana no caduca nunca", _mut_ventana_infinita),
              ("espera_para dice siempre que ya cabe", _mut_espera_siempre_cero),
              ("el límite de la ventana es enorme", _mut_limite_enorme),
              ("la corrección del 429 se fecha en el pasado",
               _mut_correccion_con_marca_vieja),
              ("la corrección del 429 no anota nada", _mut_no_anota_la_correccion),
              ("cualquier fallo parece falta de cuota",
               _mut_todo_parece_falta_de_cuota)]


def correr(pruebas) -> tuple[int, list[str]]:
    fallos = []
    for prueba in pruebas:
        try:
            prueba()
        except AssertionError as exc:
            fallos.append(f"{prueba.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            fallos.append(f"{prueba.__name__}: {type(exc).__name__}: {exc}")
    return len(pruebas) - len(fallos), fallos


def main() -> int:
    romper = "--romper" in sys.argv
    with tempfile.TemporaryDirectory() as temporal:
        cuota.LIBRO = Path(temporal) / "consumo-groq.jsonl"
        bien, fallos = correr(PRUEBAS)
        print(f"  {bien}/{len(PRUEBAS)} pruebas del libro de la cuota")
        for fallo in fallos:
            print(f"    MAL {fallo}")
        if fallos:
            return 1
        if not romper:
            print("\n  (con --romper se comprueba que estas pruebas cazan algo)")
            return 0

        print("\n  MUTACIONES: cada una rompe una propiedad a propósito y las "
              "pruebas tienen que darse cuenta")
        sin_cazar = []
        guardados = (cuota.VENTANA_S, cuota.LIMITE_VENTANA,
                     cuota.espera_para, cuota.corregir_con_429,
                     cuota.es_falta_de_cuota)
        for nombre, mutar in MUTACIONES:
            mutar()
            _, fallos_mutado = correr(PRUEBAS)
            (cuota.VENTANA_S, cuota.LIMITE_VENTANA,
             cuota.espera_para, cuota.corregir_con_429,
             cuota.es_falta_de_cuota) = guardados
            if fallos_mutado:
                cazada = fallos_mutado[0].split(":")[0]
                print(f"    cazada  {nombre}  -> {len(fallos_mutado)} "
                      f"prueba(s), la primera {cazada}")
            else:
                print(f"    NADIE CAZA  {nombre}")
                sin_cazar.append(nombre)
        if sin_cazar:
            print(f"\n  {len(sin_cazar)} mutación(es) sin cazar: hay "
                  f"propiedades que ninguna prueba protege.")
            return 1
        print(f"\n  las {len(MUTACIONES)} mutaciones se cazan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
