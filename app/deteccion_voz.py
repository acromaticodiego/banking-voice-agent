"""Cuándo hay alguien hablando, medido contra el ruido de ESTA llamada.

Hasta el 2026-09-24 esto era una constante: `UMBRAL_VOZ = 0.005` sobre la media
absoluta del trozo. Funcionaba, y funcionaba por una coincidencia — el ruido de
la habitación donde se desarrolla mide 0,0011, así que había 13 dB de margen y
nunca se abría un turno de más.

`probe/sordera_asr.py` enseñó lo que costaba esa coincidencia:

  · con la voz a la **mitad** de volumen, el turno no se abría en ninguna de
    las 6 grabaciones;
  · con el audio pasado por una **línea telefónica**, se abría en 1 de 6.

Y lo peor no es que no se oiga: es que **nadie se entera**. El turno no llega a
cerrarse, así que no hay transcripción vacía, así que el guardia del turno
vacío tampoco actúa. Alguien habla, el agente calla, y no hay ni un registro de
que hubiera alguien. Un umbral fijo no describe una llamada: describe la
habitación en la que se escribió.

## Cómo se calibra

Siguiendo el suelo de ruido de la propia llamada, con una asimetría que es todo
el truco: **el suelo baja rápido y sube muy despacio.**

El motivo es que el suelo hay que aprenderlo del silencio, no de la voz. Si
subiera al mismo ritmo que baja, una frase larga lo arrastraría hacia arriba y
el detector se quedaría sordo justo mientras alguien habla — que es el fallo
que se está arreglando, reaparecido por otra puerta. Bajando rápido, en cambio,
el detector se adapta en cuanto la sala se calla, que es cuando la información
es buena.

El umbral es el suelo multiplicado por un factor, con un mínimo absoluto por
debajo del cual no baja: en un silencio digital perfecto el suelo tiende a cero
y cualquier cosa lo multiplicaría.
"""

from __future__ import annotations

# El habla mide unas 10 veces el ruido de fondo en todo el material medido
# —tanto a volumen normal como atenuada, porque atenuar baja las dos cosas—,
# así que un factor de 10 sería el límite. El valor elegido está en
# `probe/umbral_voz.py` con la tabla de la que sale.
FACTOR_SOBRE_EL_SUELO = 3.0

# Por debajo de esto no se baja. Un canal digitalmente mudo —un WAV de ceros,
# un códec que manda silencio comprimido— tiene suelo cero, y tres veces cero
# es cero: sin este tope, cualquier bit suelto abriría un turno.
SUELO_MINIMO = 0.0004

# Lo rápido que el suelo sigue al audio. Bajar: casi inmediato, porque un
# silencio nuevo es información fiable sobre la sala. Subir: 250 veces más
# lento, para que una frase larga no arrastre el suelo hasta enmudecer al
# detector.
BAJADA = 0.5
SUBIDA = 0.002


class DetectorDeVoz:
    """Dice si un trozo de audio lleva voz, comparándolo con el ruido de fondo.

    Se le empujan niveles (la media absoluta de cada trozo) y va manteniendo su
    propia idea de cuánto suena esta llamada cuando nadie habla.
    """

    def __init__(self, factor: float = FACTOR_SOBRE_EL_SUELO,
                 suelo_minimo: float = SUELO_MINIMO) -> None:
        self.factor = factor
        self.suelo_minimo = suelo_minimo
        self.suelo: float | None = None

    @property
    def umbral(self) -> float:
        suelo = self.suelo_minimo if self.suelo is None else max(self.suelo,
                                                                 self.suelo_minimo)
        return suelo * self.factor

    def hay_voz(self, nivel: float) -> bool:
        """¿Este trozo es voz? Y de paso, aprende de él.

        El orden importa y es deliberado: **se decide con el umbral de antes y
        se aprende después**. Al revés, un trozo de voz podría subir el suelo lo
        justo para declararse a sí mismo silencio.
        """
        es_voz = nivel > self.umbral
        self._aprender(nivel, es_voz)
        return es_voz

    def _aprender(self, nivel: float, es_voz: bool) -> None:
        if self.suelo is None:
            self.suelo = nivel
            return
        if nivel < self.suelo:
            self.suelo += (nivel - self.suelo) * BAJADA
        elif not es_voz:
            # Solo sube con trozos que NO se han declarado voz. Con los de voz
            # el suelo dejaría de ser el del silencio y pasaría a ser un
            # promedio de la llamada, que no sirve para distinguir nada.
            self.suelo += (nivel - self.suelo) * SUBIDA
