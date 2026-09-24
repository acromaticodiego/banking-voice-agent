r"""Que el contador de tokens cuente, y que cuente lo que no se ve.

La métrica 5 del proyecto es el coste por conversación. Los tokens los devuelve
el proveedor en cada respuesta, así que la parte medida es casi gratis —y por
eso mismo es fácil que se quede a medias sin que nadie lo note: un contador que
devuelve cero no da error, da una llamada que sale gratis.

Estas comprobaciones usan un modelo de mentira que declara su consumo, así que
son exactas y no gastan cuota. Y la que de verdad importa es la última: **el
coste de una conversación crece más que linealmente**, porque cada turno
reenvía toda la historia anterior. Medir un turno y multiplicar por el número
de turnos da un número bajo y tranquilizador que no es el que se factura.

  .\.venv\Scripts\python.exe -m app.agent.prueba_consumo
"""

from __future__ import annotations

import threading
import time

import uvicorn

from app.agent.loop import Agente
from app.tools.service import app as app_herramientas

PUERTO = 8188
BASE = f"http://127.0.0.1:{PUERTO}"

fallos = 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    if condicion:
        print(f"    ok  {nombre}   {detalle}")
    else:
        fallos += 1
        print(f"    MAL {nombre}   {detalle}")


class ModeloQueCobra:
    """Contesta lo que le digan y declara un consumo proporcional a la historia.

    El consumo de entrada se calcula sobre los mensajes que recibe, que es
    exactamente de dónde sale en la realidad: el prompt del sistema, las
    herramientas y todos los turnos anteriores viajan en cada petición.
    """

    def __init__(self, texto: str = "Muy bien.") -> None:
        self.texto = texto
        self.llamadas = 0
        self.chat = self._Chat(self)

    class _Chat:
        def __init__(self, dueno) -> None:
            self.completions = ModeloQueCobra._Completions(dueno)

    class _Completions:
        def __init__(self, dueno) -> None:
            self.dueno = dueno

        def create(self, **argumentos):
            self.dueno.llamadas += 1
            mensajes = argumentos.get("messages", [])
            # Una palabra, un token: no es la tokenización de verdad, pero
            # aquí lo que se comprueba es la contabilidad, no el tokenizador.
            entrada = sum(len(str(m.get("content", "")).split())
                          for m in mensajes)
            texto = self.dueno.texto
            return ModeloQueCobra._Respuesta(texto, entrada,
                                             len(texto.split()))

    class _Respuesta:
        def __init__(self, texto: str, entrada: int, salida: int) -> None:
            self.choices = [ModeloQueCobra._Eleccion(texto)]
            self.usage = ModeloQueCobra._Uso(entrada, salida)

    class _Eleccion:
        def __init__(self, texto: str) -> None:
            self.message = ModeloQueCobra._Mensaje(texto)

    class _Mensaje:
        def __init__(self, texto: str) -> None:
            self.content = texto
            self.tool_calls = None

    class _Uso:
        def __init__(self, entrada: int, salida: int) -> None:
            self.prompt_tokens = entrada
            self.completion_tokens = salida
            self.total_tokens = entrada + salida


class ModeloRoto:
    """Revienta siempre. Un turno que falla no puede cobrar nada."""

    class chat:  # noqa: N801
        class completions:  # noqa: N801
            @staticmethod
            def create(**_):
                raise RuntimeError("429 de mentira")


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
        print("\n[1] Un turno cuenta lo que declaró el proveedor")
        modelo = ModeloQueCobra()
        agente = Agente(modelo, "de-mentira", BASE)
        turno = agente.turno("hola buenas tardes")
        pasos = [p for p in turno.rastro if p.tipo == "modelo"]
        print(f"    entrada {turno.tokens_entrada}, salida "
              f"{turno.tokens_salida}, peticiones {turno.peticiones}")
        comprobar("hay tokens de entrada", turno.tokens_entrada > 0)
        comprobar("hay tokens de salida", turno.tokens_salida > 0)
        comprobar("una petición", turno.peticiones == 1)
        comprobar("el paso lleva su propio consumo",
                  pasos[0].tokens_entrada == turno.tokens_entrada
                  and pasos[0].tokens_salida == turno.tokens_salida)
        comprobar("el agente lleva el acumulado de la conversación",
                  agente.tokens_entrada == turno.tokens_entrada)

        print("\n[2] El silencio no cobra: no llega a pedir nada")
        agente2 = Agente(ModeloQueCobra(), "de-mentira", BASE)
        silencio = agente2.turno("")
        comprobar("cero tokens", silencio.tokens_entrada == 0
                  and silencio.tokens_salida == 0)
        comprobar("cero peticiones", silencio.peticiones == 0)
        comprobar("y el acumulado sigue a cero", agente2.peticiones == 0)

        print("\n[3] Un turno que revienta tampoco cobra")
        agente3 = Agente(ModeloRoto(), "de-mentira", BASE)
        roto = agente3.turno("hola")
        comprobar("cero tokens", roto.tokens_entrada == 0
                  and roto.tokens_salida == 0, roto.texto[:40])
        comprobar("pero sí escaló", any(p.tipo == "herramienta"
                                        for p in roto.rastro))

        print("\n[4] LA QUE IMPORTA: el coste crece más que linealmente")
        # Cada turno reenvía la historia anterior, así que el tercero cuesta
        # más que el primero sin que nadie haya dicho nada más largo. Medir un
        # turno y multiplicar da un número bajo y tranquilizador que no es el
        # que se factura.
        agente4 = Agente(ModeloQueCobra(), "de-mentira", BASE)
        por_turno = []
        for _ in range(3):
            t = agente4.turno("necesito ayuda con mi tarjeta por favor")
            por_turno.append(t.tokens_entrada)
        print(f"    entrada por turno: {por_turno}")
        comprobar("cada turno entra más caro que el anterior",
                  por_turno[0] < por_turno[1] < por_turno[2])
        lineal = por_turno[0] * 3
        real = sum(por_turno)
        print(f"    tres turnos: {real} tokens de entrada, contra {lineal} "
              f"si se multiplicara el primero por tres "
              f"({real / lineal:.2f}×)")
        comprobar("y el total supera la estimación lineal", real > lineal)

        print("\n[5] Sin precio confirmado no hay coste inventado")
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "probe"))
        from precios import Precio, para  # noqa: PLC0415

        sin_confirmar = para("openai/gpt-oss-20b")
        comprobar("el precio de hoy está sin confirmar",
                  not sin_confirmar.confirmado, sin_confirmar.fuente)
        comprobar("y por eso no devuelve coste",
                  sin_confirmar.coste(1000, 1000) is None)
        comprobar("un modelo que no está en la tabla tampoco",
                  para("inventado/xxx").coste(10, 10) is None)
        puesto = Precio(modelo="x", entrada_por_millon=0.10,
                        salida_por_millon=0.50, fecha="hoy",
                        fuente="prueba", confirmado=True)
        esperado = 1_000_000 * 0.10 / 1e6 + 1_000_000 * 0.50 / 1e6
        comprobar("con precio confirmado, la cuenta sale",
                  abs(puesto.coste(1_000_000, 1_000_000) - esperado) < 1e-12,
                  f"{puesto.coste(1_000_000, 1_000_000)} $")
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)

    print(f"\n{'todo bien' if not fallos else str(fallos) + ' comprobaciones fallidas'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
