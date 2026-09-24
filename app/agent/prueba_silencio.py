r"""Un turno vacío no es un turno, y esto lo comprueba sin gastar nada.

El caso `silencio-total` del conjunto de evaluación fallaba **igual en las tres
corridas** —o sea que no era ruido, era el comportamiento—: la transcripción de
un silencio es la cadena vacía, llegaba al modelo como un turno normal, y el
modelo contestaba a la nada con un saludo completo y una petición de documento.

Lo que hace especial a esta prueba es el modelo que usa: uno que **revienta si
alguien lo llama**. Así, si el guardia del silencio dejara de actuar, esto no
fallaría por un desenlace discutible: fallaría por intentar hablar con un
modelo que no existe, que es mucho más difícil de pasar por alto.

Y no gasta cuota. Eso importa más de lo que parece: el 2026-09-24 se agotaron
los 200 000 tokens diarios de Groq a mediodía, y a partir de ahí lo único que
se pudo seguir comprobando fue lo que no depende del proveedor. Un camino que
solo se puede probar cuando hay cuota se acaba probando poco.

  .\.venv\Scripts\python.exe -m app.agent.prueba_silencio
"""

from __future__ import annotations

import threading
import time

import httpx
import uvicorn

from app.agent.loop import PREGUNTAS_POR_SILENCIO, Agente
from app.evaluation.catalogo import por_id
from app.evaluation.correr import correr_caso
from app.tools.service import app as app_herramientas

PUERTO = 8177
BASE = f"http://127.0.0.1:{PUERTO}"

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}")
    else:
        fallos += 1
        print(f"    MAL {nombre}    {detalle}")


class ModeloProhibido:
    """Cualquier llamada al modelo es un fallo de la prueba."""

    class chat:  # noqa: N801
        class completions:  # noqa: N801
            @staticmethod
            def create(**_):
                raise AssertionError(
                    "SE LLAMÓ AL MODELO en un turno vacío: el guardia del "
                    "silencio no está actuando")


def llamo_al_modelo(turno) -> bool:
    """¿Intentó hablar con el modelo?

    No se puede comprobar con un `try`: el bucle captura los fallos del modelo
    a propósito, para no dejar a nadie escuchando silencio al teléfono cuando
    el proveedor se cae. La huella queda en el rastro.
    """
    return any(p.tipo == "modelo" for p in turno.rastro)


def main() -> int:
    servidor = uvicorn.Server(uvicorn.Config(app_herramientas, port=PUERTO,
                                             log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(50):
        if servidor.started:
            break
        time.sleep(0.1)

    try:
        # ------------------------------------- 1. el caso del conjunto, tal cual
        print("\n[1] El caso `silencio-total` acierta sin tocar el modelo")
        caso = por_id("silencio-total")
        agente = Agente(ModeloProhibido(), "prohibido", BASE)

        def hacer_turno(_caso, frase):
            turno = agente.turno(frase)
            return (turno.texto,
                    [p.detalle.split(" ")[0] for p in turno.rastro
                     if p.tipo == "herramienta"],
                    [p.resultado for p in turno.rastro
                     if p.tipo == "herramienta" and p.resultado is not None])

        resultado = correr_caso(caso, hacer_turno)
        print(f"    dijo: {resultado['dijo']}")
        comprobar(f"desenlace {caso.desenlace}", resultado["acierta"],
                  resultado["obtenido"])

        # ---------------------------------- 2. al tercer silencio, escala
        print("\n[2] Dos preguntas y al tercero un humano, con su ticket")
        with httpx.Client(base_url=BASE, timeout=10) as c:
            antes = c.get("/salud").json()["tickets"]
            agente2 = Agente(ModeloProhibido(), "prohibido", BASE)
            turnos = [agente2.turno("") for _ in range(3)]
            despues = c.get("/salud").json()["tickets"]
        for i, t in enumerate(turnos, 1):
            print(f"    {i}. {t.texto}")
        comprobar("las dos primeras no dicen lo mismo",
                  turnos[0].texto != turnos[1].texto)
        comprobar("las dos primeras son las escritas",
                  [t.texto for t in turnos[:2]] == PREGUNTAS_POR_SILENCIO)
        comprobar("la tercera pasa a un asesor",
                  "asesor" in turnos[2].texto.lower(), turnos[2].texto)
        comprobar("y abre exactamente un ticket", despues - antes == 1,
                  f"{antes}->{despues}")
        comprobar("ninguno de los tres llama al modelo",
                  not any(llamo_al_modelo(t) for t in turnos))

        # --------------------------- 3. la racha se corta si alguien habla
        print("\n[3] Un turno con voz sí va al modelo, y pone la racha a cero")
        agente3 = Agente(ModeloProhibido(), "prohibido", BASE)
        agente3.turno("")
        comprobar("tras un silencio, la racha va por 1", agente3.silencios == 1,
                  str(agente3.silencios))
        con_voz = agente3.turno("hola, buenas")
        comprobar("un turno con voz intenta hablar con el modelo",
                  llamo_al_modelo(con_voz))
        comprobar("y la racha vuelve a cero", agente3.silencios == 0,
                  str(agente3.silencios))

        # --------------------------- 4. lo que el ASR devuelve de verdad
        print("\n[4] Espacios y puntuación sueltos también son silencio")
        # Un silencio no siempre llega como "". `faster-whisper` devuelve
        # espacios, y a veces un punto o una coma. Si el guardia solo mirara
        # `not dicho`, un punto suelto se iría al modelo y volvería el saludo.
        agente4 = Agente(ModeloProhibido(), "prohibido", BASE)
        raros = ["", " ", "   ", ".", " . ", "..", ",", "\n", " ,. ", "?"]
        for raro in raros:
            turno = agente4.turno(raro)
            if llamo_al_modelo(turno) or not turno.silencio:
                comprobar(f"{raro!r} se trata como silencio", False,
                          f"silencio={turno.silencio}")
                break
        else:
            comprobar(f"las {len(raros)} formas de no decir nada", True)
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    print(f"\n{'todo bien' if not fallos else str(fallos) + ' comprobaciones fallidas'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
