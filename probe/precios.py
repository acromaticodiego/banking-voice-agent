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

    def coste(self, tokens_entrada: int, tokens_salida: int) -> float | None:
        """Dólares, o None si el precio no está confirmado."""
        if not self.confirmado or self.entrada_por_millon is None \
                or self.salida_por_millon is None:
            return None
        return (tokens_entrada * self.entrada_por_millon / 1e6
                + tokens_salida * self.salida_por_millon / 1e6)


PRECIOS: dict[str, Precio] = {
    # SIN CONFIRMAR. El 2026-09-24 se intentó leer de groq.com/pricing y la
    # página no listaba el modelo, así que no se pone un número de memoria:
    # un precio inventado convertiría la métrica de coste en una opinión con
    # cuatro decimales. Los tokens se miden igual; el dólar espera.
    "openai/gpt-oss-20b": Precio(
        modelo="openai/gpt-oss-20b",
        entrada_por_millon=None,
        salida_por_millon=None,
        fecha="2026-09-24",
        fuente="pendiente: consola de Groq > Settings > Billing",
        confirmado=False,
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
                  f"salida {precio.salida_por_millon} $/M")
