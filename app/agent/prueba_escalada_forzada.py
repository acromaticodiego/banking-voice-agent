r"""Si el agente dice que pasa la llamada, la llamada se pasa.

## El fallo que cierra

El conjunto de evaluación lo destapó en tres casos, y uno de ellos en la medición
del reservado, que solo se hace una vez:

  · `tarjeta-falla-tras-verificar` — **0 de 5 corridas del reservado**. El agente
    dice *«no puedo verificar el estado de su tarjeta en este momento. Voy a pasar
    la llamada a un asesor humano. ¿Le parece bien?»* y se queda esperando.
  · `core-caido-a-mitad` — 3 de 3. Dice *«hay un problema técnico con el sistema.
    Voy a transferir su llamada a un asesor humano»*, que es exactamente lo que
    hay que decir, y no llama a nadie.
  · `pide-algo-fuera-de-alcance` — 2 de 3.

**Un agente que suena impecable y no ha hecho nada.** En una llamada de verdad eso
cuelga al cliente con una promesa, y es peor que decir «no puedo ayudarle»: quien
llama se queda esperando a alguien que no va a venir.

## Por qué el guardia está en el código y no en el prompt

Es la tercera vez en este proyecto que la respuesta a «el modelo no obedece una
regla» resulta ser «la regla no estaba en ningún sitio comprobable»: la fuga del
nombre del titular, la herramienta caída confundida con un documento malo, y esto.
El prompt ya dice que pase la llamada cuando no pueda resolver. Lo dice bien y el
modelo lo dice bien. Lo que faltaba era que **decirlo implicara hacerlo**.

## Lo que esta prueba vigila, y lo que NO

Vigila que se escale cuando se promete, que no se escale cuando solo se ofrece, que
no se escale dos veces y que quede auditable. No vigila que el guardia acierte
siempre a distinguir una promesa de una frase suelta: eso lo decide
`PASAR_CON_HUMANO`, que tiene su propia prueba y su propia historia de huecos —el
último, encontrado el 2026-09-27 justo al escribir este guardia: «voy a transferir
su llamada» no casaba porque todas las alternativas pedían un pronombre delante.

No gasta cuota ni toca el modelo de verdad.

    .\.venv\Scripts\python.exe -m app.agent.prueba_escalada_forzada
"""

from __future__ import annotations

import threading
import time

import uvicorn

from app.agent.loop import Agente
from app.tools.service import TICKETS, app as app_herramientas

PUERTO = 8207
BASE = f"http://127.0.0.1:{PUERTO}"

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}   {detalle}")
    else:
        fallos += 1
        print(f"    MAL {nombre}   {detalle}")


class ModeloQueDice:
    """Contesta un texto fijo y no pide ninguna herramienta.

    Es el caso exacto del fallo: el modelo habla, promete, y no llama a nada.
    """

    def __init__(self, texto: str) -> None:
        self.texto = texto
        self.chat = self._Chat(self)

    class _Chat:
        def __init__(self, dueno) -> None:
            self.completions = ModeloQueDice._Completions(dueno)

    class _Completions:
        def __init__(self, dueno) -> None:
            self.dueno = dueno

        def create(self, **_argumentos):
            return ModeloQueDice._Respuesta(self.dueno.texto)

    class _Respuesta:
        def __init__(self, texto: str) -> None:
            self.choices = [ModeloQueDice._Eleccion(texto)]
            self.usage = None

    class _Eleccion:
        def __init__(self, texto: str) -> None:
            self.message = ModeloQueDice._Mensaje(texto)

    class _Mensaje:
        def __init__(self, texto: str) -> None:
            self.content = texto
            self.tool_calls = None


def herramientas_de(turno) -> list[str]:
    return [p.detalle.split(" ")[0] for p in turno.rastro
            if p.tipo == "herramienta"]


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
        print("\n[1] La frase del reservado: promete y no llama a nadie")
        # Literal de `tarjeta-falla-tras-verificar`, que se falla 0 de 5.
        texto = ("No puedo verificar el estado de su tarjeta en este momento. "
                 "Voy a pasar la llamada a un asesor humano. ¿Le parece bien?")
        agente = Agente(ModeloQueDice(texto), "de mentira", BASE)
        turno = agente.turno("¿Cómo está mi tarjeta?")
        comprobar("se escaló de verdad",
                  "escalar_a_humano" in herramientas_de(turno),
                  str(herramientas_de(turno)))
        comprobar("y queda marcado como forzado", turno.escalada_forzada)
        forzado = [p for p in turno.rastro if p.tipo == "herramienta"
                   and "guardia" in p.detalle]
        comprobar("el rastro dice que lo hizo el guardia", len(forzado) == 1,
                  str([p.detalle for p in turno.rastro]))
        comprobar("hay un ticket de verdad",
                  bool(forzado and forzado[0].resultado.get("ticket")),
                  str(forzado[0].resultado if forzado else None))
        # El motivo importa: lo lee el asesor que recibe la llamada, y tiene que
        # saber que el agente lo prometió sin ejecutarlo.
        comprobar("el motivo dice que el agente no lo ejecutó",
                  "guardia" in str(forzado[0].resultado.get("motivo", ""))
                  or "guardia" in str(forzado[0].argumentos),
                  str(forzado[0].argumentos))
        comprobar("y el texto que se dice no se toca", turno.texto == texto)

        print("\n[2] La frase de core-caido-a-mitad, que el detector no cazaba")
        # "Voy a transferir su llamada" no casaba con PASAR_CON_HUMANO hasta el
        # 2026-09-27: el guardia habría dejado pasar el caso que lo motivó.
        agente2 = Agente(ModeloQueDice(
            "Lo siento, pero hay un problema técnico con el sistema. Voy a "
            "transferir su llamada a un asesor humano para que lo ayude."),
            "de mentira", BASE)
        turno2 = agente2.turno("¿Cómo está mi tarjeta?")
        comprobar("también se escala", turno2.escalada_forzada,
                  str(herramientas_de(turno2)))

        print("\n[2b] El pronombre DETRÁS del verbo, que es como se dice de "
              "verdad")
        # El tercer hueco del mismo patrón, del 2026-09-28. La primera frase es
        # LITERAL de la corrida `20260928-103658`, donde el guardia no disparó y
        # el caso costó un punto. Las demás NO se le han visto decir al modelo:
        # están aquí a propósito, porque parchear solo lo ya visto es lo que ha
        # hecho que este patrón tenga tres huecos en tres días.
        enclíticos = [
            ("transferirle, literal de la corrida del 28/09",
             "Lo siento, pero hay un problema técnico con el sistema. Voy a "
             "transferirle a un asesor humano para que lo ayude."),
            ("transferirlo (nunca dicha)",
             "Voy a transferirlo a un asesor humano."),
            ("pasarle (nunca dicha)",
             "Voy a pasarle con un asesor humano ahora mismo."),
            ("pasarlos, en plural (nunca dicha)",
             "Voy a pasarlos con un supervisor."),
            ("comunicarle (nunca dicha)",
             "Voy a comunicarle con un agente para que lo atienda."),
            ("derivarlo (nunca dicha)",
             "Voy a derivarlo a un asesor humano."),
        ]
        for nombre, frase in enclíticos:
            t = Agente(ModeloQueDice(frase), "de mentira", BASE).turno("Ayuda")
            comprobar(f"se escala con «{nombre}»", t.escalada_forzada,
                      f"{frase!r} -> {herramientas_de(t)}")

        print("\n[2c] Y el enclítico NEGADO no es una promesa")
        # El límite del arreglo, y está puesto antes de que cueste algo: si el
        # enclítico se admitiera suelto, «no puedo transferirle a un asesor»
        # —que es una negativa correcta— abriría un ticket que nadie pidió. Por
        # eso solo se admite detrás de «voy a», que es afirmativo. Es la lección
        # del falso positivo del 27/09 aplicada por delante y no por detrás.
        antes2c = len(TICKETS)
        agente2c = Agente(ModeloQueDice(
            "Lo siento, no puedo transferirle a un asesor humano por este "
            "canal."), "de mentira", BASE)
        turno2c = agente2c.turno("Páseme con alguien")
        comprobar("negarse a transferir NO abre ticket",
                  not turno2c.escalada_forzada and len(TICKETS) == antes2c,
                  f"forzada={turno2c.escalada_forzada}, tickets {antes2c} -> "
                  f"{len(TICKETS)}")

        print("\n[3] Un OFRECIMIENTO no es una promesa: no se escala")
        # "Si lo desea, le puedo pasar" es una respuesta correcta y escalar ahí
        # abriría un ticket que nadie pidió. La distinción ya estaba en
        # `PASAR_CON_HUMANO` desde el 24/09 y aquí se comprueba que el guardia
        # la respeta, no solo el detector.
        agente3 = Agente(ModeloQueDice(
            "Su consulta la puede resolver en la app. Si lo desea, le puedo "
            "pasar con un asesor."), "de mentira", BASE)
        turno3 = agente3.turno("¿Qué hago?")
        comprobar("no se escala por un ofrecimiento",
                  not turno3.escalada_forzada
                  and "escalar_a_humano" not in herramientas_de(turno3),
                  str(herramientas_de(turno3)))

        print("\n[3b] El caso REAL que destapó el falso positivo (28/09)")
        # Literal de `tarjeta-bloqueada-documento-bueno`, que el agente resuelve
        # bien. Con el guardia del 27/09 esto abría un ticket que nadie pidió:
        # ofrecer ayuda extra al terminar es lo correcto, no una promesa. Y el
        # coste de equivocarse aquí no es un número en un informe, es el trabajo
        # de la persona que atiende el ticket.
        agente3b = Agente(ModeloQueDice(
            "Su tarjeta de débito con los últimos 4 dígitos 4582 está bloqueada "
            "desde el 15 de septiembre de 2026 por un movimiento inusual "
            "detectado. Si necesita ayuda adicional, le paso la llamada a un "
            "asesor humano."), "de mentira", BASE)
        antes3b = len(TICKETS)
        turno3b = agente3b.turno("¿Cómo está mi tarjeta?")
        comprobar("ofrecer ayuda extra al final NO abre ticket",
                  not turno3b.escalada_forzada and len(TICKETS) == antes3b,
                  f"forzada={turno3b.escalada_forzada}, tickets {antes3b} -> "
                  f"{len(TICKETS)}")

        print("\n[4] Una frase sin promesa tampoco escala")
        agente4 = Agente(ModeloQueDice(
            "Su tarjeta de débito está bloqueada desde el 15 de septiembre."),
            "de mentira", BASE)
        turno4 = agente4.turno("¿Cómo está mi tarjeta?")
        comprobar("nada que forzar",
                  not turno4.escalada_forzada
                  and "escalar_a_humano" not in herramientas_de(turno4),
                  str(herramientas_de(turno4)))

        print("\n[5] Dos tickets para la misma promesa, jamás")
        # El guardia no puede escalar encima de una escalada que el modelo ya
        # pidió. Se comprueba por el número de tickets abiertos, no por el
        # rastro: es la cuenta que de verdad importa.
        antes = len(TICKETS)
        agente5 = Agente(ModeloQueDice(
            "Le paso con un asesor humano ahora mismo."), "de mentira", BASE)
        turno5 = agente5.turno("Necesito ayuda")
        comprobar("se abre UN ticket", len(TICKETS) == antes + 1,
                  f"{antes} -> {len(TICKETS)}")
        # Y repetir el MISMO turno —lo que pasa cuando hay un reintento de red—
        # no abre otro, porque la clave es del turno (ADR 0007).
        resultado, _ms = agente5._llamar(
            "escalar_a_humano", {"motivo": "reintento del mismo turno"},
            turno5.clave)
        comprobar("y el reintento del mismo turno no abre otro",
                  len(TICKETS) == antes + 1 and resultado.get("repetida") is True,
                  f"{len(TICKETS)} tickets, repetida={resultado.get('repetida')}")

        print("\n[6] El guardia NO puede regalar el conjunto")
        # La salvaguarda de siempre: un agente degenerado que prometa transferir
        # en todos los casos escalaría en todos, y eso solo acierta los casos en
        # los que escalar ES lo correcto. Si aprobara, el guardia estaría
        # inflando la métrica en vez de arreglar un fallo.
        from app.evaluation.correr import acierta, clasificar  # noqa: PLC0415
        from app.evaluation.particion import calibracion  # noqa: PLC0415
        casos = calibracion()
        obtenido = clasificar("Le paso con un asesor humano.",
                              ["escalar_a_humano"])
        aciertos = sum(1 for c in casos if acierta(c, obtenido))
        comprobar(f"el que promete siempre saca {aciertos}/{len(casos)}, menos "
                  f"de la mitad", aciertos * 2 < len(casos),
                  f"{aciertos}/{len(casos)}")
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    print(f"\n{'todo bien' if not fallos else str(fallos) + ' fallidas'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
