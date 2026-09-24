r"""Lo que cuesta un millón de tokens, con su fuente y su fecha.

Un solo sitio, y a propósito. El coste por conversación es una multiplicación:
los tokens los cuenta el proveedor y son un hecho; el precio es un número que
alguien ha tenido que ir a mirar, y que cambia. Si el precio está repartido por
tres scripts, el día que cambie quedan dos números viejos dando resultados que
parecen medidos.

**Sin precio confirmado no se inventa un coste.** Es la diferencia entre "la
conversación gastó 4 812 tokens" —que es medición— y "la conversación costó
0,0009 $" —que es medición multiplicada por un supuesto—. Las dos se pueden
publicar, pero la segunda solo si el supuesto se publica con ella.

Para rellenarlo: el precio por modelo está en la consola de Groq, en
Settings > Billing, o en https://groq.com/pricing. Se anota el número, la
fecha y de dónde salió, y se pone `confirmado=True`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Precio:
    modelo: str
    entrada_por_millon: float | None   # dólares por millón de tokens de entrada
    salida_por_millon: float | None    # ídem de salida
    fecha: str                         # cuándo se miró
    fuente: str                        # dónde
    confirmado: bool = False
    # Entrada ya vista antes, que el proveedor cobra más barata. En este
    # proyecto no es un detalle: cada turno reenvía la conversación entera, así
    # que la entrada repetida es justo la que más crece.
    entrada_cacheada_por_millon: float | None = None

    def coste(self, tokens_entrada: int, tokens_salida: int) -> float | None:
        """Dólares, o None si el precio no está confirmado."""
        if not self.confirmado or self.entrada_por_millon is None \
                or self.salida_por_millon is None:
            return None
        return (tokens_entrada * self.entrada_por_millon / 1e6
                + tokens_salida * self.salida_por_millon / 1e6)


PRECIOS: dict[str, Precio] = {
    # Confirmado el 2026-09-24 en la ficha del modelo de la documentación de
    # Groq. `groq.com/pricing` sigue SIN listar este modelo —por eso el primer
    # intento se quedó sin número—, pero la ficha del modelo sí lo publica, y
    # lo hace por partida doble: el precio por millón y cuántos tokens da un
    # dólar. Las dos columnas cuadran entre sí, que es lo que permite fiarse:
    #
    #     Input         $0.075   13M / $1     (1 / 0,075 = 13,3M)
    #     Cached Input  $0.037   27M / $1     (1 / 0,037 = 27,0M)
    #     Output        $0.30    3.3M / $1    (1 / 0,30  =  3,3M)
    #
    # Lo que se paga HOY en este proyecto es cero: se desarrolla en el plan
    # gratuito. Estos precios no son la factura, son lo que costaría operarlo,
    # que es la pregunta que decide si el sistema es viable.
    "openai/gpt-oss-20b": Precio(
        modelo="openai/gpt-oss-20b",
        entrada_por_millon=0.075,
        salida_por_millon=0.30,
        entrada_cacheada_por_millon=0.037,
        fecha="2026-09-24",
        fuente="https://console.groq.com/docs/model/openai/gpt-oss-20b",
        confirmado=True,
    ),
}


def para(modelo: str) -> Precio:
    """El precio de un modelo, o uno sin confirmar si no está en la tabla."""
    if modelo in PRECIOS:
        return PRECIOS[modelo]
    return Precio(modelo=modelo, entrada_por_millon=None,
                  salida_por_millon=None, fecha="-",
                  fuente="no está en la tabla de precios", confirmado=False)


if __name__ == "__main__":
    for nombre, precio in PRECIOS.items():
        estado = "confirmado" if precio.confirmado else "SIN CONFIRMAR"
        print(f"{nombre}: {estado}  ({precio.fuente}, {precio.fecha})")
        if precio.confirmado:
            print(f"  entrada {precio.entrada_por_millon} $/M, "
                  f"salida {precio.salida_por_millon} $/M", end="")
            if precio.entrada_cacheada_por_millon is not None:
                print(f", entrada cacheada {precio.entrada_cacheada_por_millon} $/M")
            else:
                print()
