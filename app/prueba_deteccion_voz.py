r"""El detector de voz, sin cuota, sin GPU y sin micrófono.

Lo que estas pruebas protegen no es "que detecte voz" —eso lo mide
`probe/umbral_voz.py` sobre audio real— sino los invariantes de los que depende
que siga detectándola dentro de un mes:

  · que una voz floja se oiga, que es el fallo que arregló el ADR 0009;
  · que el ruido de una sala, por fuerte que sea, no abra turno;
  · y sobre todo **la asimetría**: el suelo baja rápido y sube muy despacio.
    Ese detalle es todo el diseño y no se ve mirando el código un minuto. Si
    alguien lo simplifica —"¿para qué dos constantes si una vale?"— el detector
    sigue funcionando en la demo y se queda sordo a mitad de las frases largas,
    que es el fallo que vino a arreglar. La prueba está para que esa
    simplificación no pase callando.

  .\.venv\Scripts\python.exe -m app.prueba_deteccion_voz
"""

from __future__ import annotations

import numpy as np

from app.deteccion_voz import UMBRAL_FIJO_ANTERIOR, DetectorDeVoz
from app.vivo import FRECUENCIA, MUESTRAS_POR_TROZO, TROZO_MS, Llamada

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


def tono(nivel: float, ms: int, semilla: int = 7) -> np.ndarray:
    """Ruido blanco a un nivel dado. Sirve igual: el detector mira energía."""
    generador = np.random.default_rng(semilla)
    n = int(FRECUENCIA * ms / 1000)
    bruto = generador.standard_normal(n)
    return (bruto / np.abs(bruto).mean() * nivel).astype(np.float32)


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
    """La asimetría, que es el corazón del diseño.

    Diez segundos de voz seguida sin una sola pausa. Si el suelo subiera al
    ritmo al que baja, se plantaría en el nivel de la voz y los últimos trozos
    dejarían de contar como voz: el detector se quedaría sordo justo con quien
    más habla.
    """
    print("  diez segundos de voz seguida no suben el suelo hasta enmudecerla")
    detector = calibrado()
    oidos = empujar_niveles(detector, HABLA, int(10_000 / TROZO_MS))
    comprobar("los 500 trozos siguen contando como voz", all(oidos),
              f"se perdieron {oidos.count(False)}; umbral final {detector.umbral:.5f}")
    comprobar("y el suelo sigue pareciéndose al de la sala, no al de la voz",
              detector.suelo < HABLA / 3,
              f"suelo {detector.suelo:.5f} contra habla {HABLA}")


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


def prueba_la_llamada_usa_el_detector() -> None:
    """De punta a punta: que `Llamada` abra turno con voz floja."""
    print("  una llamada de verdad abre turno con voz floja")

    class Segmento:
        # Un segmento cualquiera con una frase entera. Tiene que estar
        # COMPLETA: con texto vacío o a medias, `parece_incompleto` manda
        # seguir escuchando —que es lo correcto— y el turno no se cierra, y
        # entonces esta prueba mediría el fin de turno y no el detector.
        text = "Buenas tardes, llamo por mi tarjeta."
        no_speech_prob = 0.1
        avg_logprob = -0.3
        compression_ratio = 1.1

    class ASRDeMentira:
        def transcribe(self, audio, **kwargs):
            class Info:
                language_probability = 0.9
            return [Segmento()], Info()

    class VozDeMentira:
        def synthesize(self, texto):
            return []

    class AgenteDeMentira:
        def turno(self, dicho, al_hablar=None, **kwargs):
            class T:
                texto = ""
                rastro: list = []
            return T()

    llamada = Llamada(ASRDeMentira(), VozDeMentira(), AgenteDeMentira())
    llamada.empujar(tono(SALA / 4, 1000))                 # la sala, floja
    avisos = llamada.empujar(tono(HABLA / 4, 800))        # alguien habla, flojo
    avisos += llamada.empujar(tono(SALA / 4, 500))        # y se calla
    comprobar("el turno se cerró", any(a.tipo == "oido" for a in avisos),
              f"avisos: {[a.tipo for a in avisos]}")

    # Y la comprobación que da sentido a la anterior: con el umbral de antes,
    # ese mismo audio no habría abierto turno nunca.
    nivel = float(np.abs(tono(HABLA / 4, 800)[:MUESTRAS_POR_TROZO]).mean())
    comprobar("y con el umbral fijo de antes no se habría abierto",
              nivel < UMBRAL_FIJO_ANTERIOR,
              f"nivel {nivel:.5f} contra {UMBRAL_FIJO_ANTERIOR}")


def main() -> int:
    print("El detector de voz, contra el ruido de cada llamada\n")
    for prueba in (prueba_la_sala_no_es_voz,
                   prueba_la_voz_normal_se_oye,
                   prueba_la_voz_floja_se_oye,
                   prueba_una_sala_ruidosa_tampoco_abre,
                   prueba_la_frase_larga_no_deja_sordo,
                   prueba_el_suelo_baja_deprisa,
                   prueba_el_silencio_digital_no_abre,
                   prueba_la_llamada_usa_el_detector):
        try:
            prueba()
        except Exception as exc:  # noqa: BLE001
            comprobar(f"{prueba.__name__} termina sin reventar", False,
                      f"{type(exc).__name__}: {exc}")
    print(f"\n{'TODO BIEN' if not fallos else f'{fallos} FALLOS'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
