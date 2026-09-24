r"""El detector de voz que NO está en uso, y las pruebas que lo describen.

**Este módulo no corre en el sistema.** El detector adaptativo se puso en la
ruta del turno el 2026-09-24 y se revirtió el mismo día: la medición que lo
justificaba modelaba mal `app/vivo.py`, y con el sistema de verdad el umbral
fijo oye lo que se decía que no oía, mientras que el adaptativo **rompía el
cierre del turno** en el caso normal. La historia entera está en el ADR 0009,
que quedó como decisión revertida.

Se conserva, con sus pruebas, porque el hallazgo vale más que el código: la
tabla de cuánto oye cada factor sigue siendo válida para el día que haya
grabaciones de otras salas, y estas pruebas documentan un diseño que alguien
volverá a proponer.

Lo que estas pruebas protegen no es "que detecte voz" —eso lo mide
`probe/umbral_voz.py` sobre audio real— sino los invariantes de los que depende
que siga detectándola dentro de un mes:

  · que una voz floja se oiga, que es el fallo que arregló el ADR 0009;
  · que el ruido de una sala, por fuerte que sea, no abra turno;
  · que una frase larga no arrastre el suelo hasta dejar sordo al detector;
  · y el límite que el ADR 0009 declara y no arregla, fijado aquí a propósito
    para que el día que alguien lo arregle esta prueba falle y le mande a leer
    por qué se dejó así.

**Una de estas pruebas no cubría lo que decía cubrir**, y se descubrió
rompiendo el código a propósito: al poner la subida del suelo igual de rápida
que la bajada, la prueba de la frase larga seguía pasando. Lo que protege de
las frases largas no es la lentitud de la subida sino que los trozos de voz no
alimenten la subida en absoluto, y el comentario del código decía lo otro. La
prueba de la subida lenta que hay ahora cubre lo que esa constante sí hace.

  .\.venv\Scripts\python.exe -m app.prueba_deteccion_voz
"""

from __future__ import annotations

import numpy as np

from app.deteccion_voz import UMBRAL_FIJO_ANTERIOR, DetectorDeVoz
from app.vivo import FRECUENCIA, TROZO_MS

fallos = 0

# Niveles tomados del material real (`artifacts/confianza-asr-*.json`): el
# suelo de la sala de trabajo y el habla de las grabaciones.
SALA = 0.0011
HABLA = 0.0125


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}")
    else:
        fallos += 1
        print(f"    FALLA  {nombre}" + (f" -> {detalle}" if detalle else ""))


def empujar_niveles(detector: DetectorDeVoz, nivel: float, trozos: int) -> list[bool]:
    return [detector.hay_voz(nivel) for _ in range(trozos)]


def calibrado(nivel_sala: float = SALA, trozos: int = 50) -> DetectorDeVoz:
    """Un detector que ya ha oído un segundo de la sala, como en una llamada."""
    detector = DetectorDeVoz()
    empujar_niveles(detector, nivel_sala, trozos)
    return detector


# ------------------------------------------------------------------ pruebas

def prueba_la_sala_no_es_voz() -> None:
    print("  el ruido de la sala no es voz")
    detector = calibrado()
    comprobar("50 trozos de sala seguidos, ninguno cuenta como voz",
              not any(empujar_niveles(detector, SALA, 50)),
              f"umbral {detector.umbral:.5f}, sala {SALA}")


def prueba_la_voz_normal_se_oye() -> None:
    print("  la voz a volumen normal se oye")
    detector = calibrado()
    comprobar("todos los trozos de habla cuentan como voz",
              all(empujar_niveles(detector, HABLA, 30)),
              f"umbral {detector.umbral:.5f}")


def prueba_la_voz_floja_se_oye() -> None:
    """El fallo del ADR 0009: con el umbral fijo, esto no se oía."""
    print("  la voz floja también, que es de lo que iba todo esto")
    for divisor in (2, 4, 10):
        detector = calibrado(SALA / divisor)
        oidos = empujar_niveles(detector, HABLA / divisor, 30)
        comprobar(f"voz y sala divididas entre {divisor}", all(oidos),
                  f"umbral {detector.umbral:.6f}, voz {HABLA / divisor:.6f}")
    comprobar("y el umbral fijo de antes NO la oía (por eso se cambió)",
              HABLA / 10 < UMBRAL_FIJO_ANTERIOR,
              f"{HABLA / 10} contra {UMBRAL_FIJO_ANTERIOR}")


def prueba_una_sala_ruidosa_tampoco_abre() -> None:
    print("  una sala mucho más ruidosa que esta tampoco abre turno")
    for veces in (5, 20, 100):
        detector = calibrado(SALA * veces)
        comprobar(f"sala x{veces}", not any(empujar_niveles(detector, SALA * veces, 50)),
                  f"umbral {detector.umbral:.5f}")


def prueba_la_frase_larga_no_deja_sordo() -> None:
    """Que hablar mucho seguido no deje sordo al detector.

    Diez segundos de voz sin una sola pausa, que no es una exageración: medida
    sobre las seis grabaciones reales, la racha continua de habla más larga es
    de 9,9 segundos. Si el suelo aprendiera de los trozos de voz, se plantaría
    en el nivel de la voz y los últimos trozos dejarían de contar como tal: el
    detector se quedaría sordo justo con quien más habla.
    """
    print("  diez segundos de voz seguida no suben el suelo hasta enmudecerla")
    detector = calibrado()
    oidos = empujar_niveles(detector, HABLA, int(10_000 / TROZO_MS))
    comprobar("los 500 trozos siguen contando como voz", all(oidos),
              f"se perdieron {oidos.count(False)}; umbral final {detector.umbral:.5f}")
    comprobar("y el suelo sigue pareciéndose al de la sala, no al de la voz",
              detector.suelo < HABLA / 3,
              f"suelo {detector.suelo:.5f} contra habla {HABLA}")


def prueba_un_ruido_aislado_no_levanta_el_suelo() -> None:
    """Para esto sirve la subida lenta, y no para lo que decía el comentario.

    Un ruido de fondo que sube un poco pero no llega a contar como voz —un
    ordenador que arranca el ventilador— no puede levantar el suelo de golpe:
    si lo hiciera, la voz que venga detrás se compararía contra un suelo
    inflado por un ruido de un segundo.
    """
    print("  un ruido por debajo del umbral no levanta el suelo de golpe")
    detector = calibrado()
    justo_por_debajo = detector.umbral * 0.9
    empujar_niveles(detector, justo_por_debajo, 50)      # un segundo
    comprobar("tras un segundo, el suelo apenas se ha movido",
              detector.suelo < SALA * 1.4,
              f"suelo {detector.suelo:.5f} tras empujar {justo_por_debajo:.5f}")
    comprobar("y la voz normal se sigue oyendo después",
              all(empujar_niveles(detector, HABLA, 10)),
              f"umbral {detector.umbral:.5f}")


def prueba_limite_conocido_la_sala_que_sube() -> None:
    """El límite que el ADR 0009 declara y NO arregla.

    Esta prueba no comprueba que algo funcione: fija un comportamiento que se
    sabe malo, para que el día que alguien lo arregle esto falle y le obligue a
    venir a leer por qué se dejó así.
    """
    print("  LÍMITE CONOCIDO: si el ruido sube por encima del umbral, se queda abierto")
    detector = calibrado()
    ruido_nuevo = detector.umbral * 2
    abiertos = empujar_niveles(detector, ruido_nuevo, 500)   # diez segundos
    comprobar("hoy se declaran voz los 500 trozos (ADR 0009, límite declarado)",
              all(abiertos), f"se declararon voz {abiertos.count(True)} de 500")
    comprobar("y el suelo no se entera, porque solo aprende de lo que no es voz",
              abs(detector.suelo - SALA) < SALA * 0.5,
              f"suelo {detector.suelo:.5f}")


def prueba_el_suelo_baja_deprisa() -> None:
    """La otra mitad de la asimetría: adaptarse cuando la sala se calla."""
    print("  cuando la sala se calla, el suelo baja enseguida")
    detector = calibrado(SALA * 50)
    alto = detector.suelo
    empujar_niveles(detector, SALA, 25)      # medio segundo de sala tranquila
    comprobar("medio segundo basta para bajar el suelo casi del todo",
              detector.suelo < SALA * 1.5,
              f"de {alto:.5f} a {detector.suelo:.5f}")


def prueba_el_silencio_digital_no_abre() -> None:
    print("  un canal digitalmente mudo no abre turno con cualquier bit")
    detector = DetectorDeVoz()
    empujar_niveles(detector, 0.0, 50)
    comprobar("el suelo no se hunde por debajo del mínimo",
              detector.umbral > 0,
              f"umbral {detector.umbral}")
    comprobar("un trozo minúsculo no cuenta como voz",
              not detector.hay_voz(0.0002), f"umbral {detector.umbral}")


def main() -> int:
    print("El detector de voz, contra el ruido de cada llamada\n")
    for prueba in (prueba_la_sala_no_es_voz,
                   prueba_la_voz_normal_se_oye,
                   prueba_la_voz_floja_se_oye,
                   prueba_una_sala_ruidosa_tampoco_abre,
                   prueba_la_frase_larga_no_deja_sordo,
                   prueba_un_ruido_aislado_no_levanta_el_suelo,
                   prueba_limite_conocido_la_sala_que_sube,
                   prueba_el_suelo_baja_deprisa,
                   prueba_el_silencio_digital_no_abre):
        try:
            prueba()
        except Exception as exc:  # noqa: BLE001
            comprobar(f"{prueba.__name__} termina sin reventar", False,
                      f"{type(exc).__name__}: {exc}")
    print(f"\n{'TODO BIEN' if not fallos else f'{fallos} FALLOS'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
