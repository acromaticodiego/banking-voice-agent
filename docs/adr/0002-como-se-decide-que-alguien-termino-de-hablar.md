# ADR 0002 — Cómo se decide que alguien terminó de hablar

- **Fecha:** 2026-09-19
- **Estado:** abierta. El primer intento de medirlo falló y aquí queda por qué.
- **Contexto:** es el término más grande del presupuesto del turno y el único
  que sigue sin medir.

## Por qué importa tanto

En el presupuesto del día 1, el fin de habla entró como **400 ms supuestos** de
un total de 1096 ms. Es el 36% del turno y es el único número que nadie midió.
También es el parámetro que más fácil se ajusta a ojo: se prueba, "suena bien",
y se deja. Eso es exactamente lo que este proyecto dice que no se hace.

El compromiso tiene dos lados opuestos:

- **Ventana corta**: el agente contesta antes, pero corta a la persona a mitad
  de frase. Una pausa de duda pasa por final de turno.
- **Ventana larga**: no corta nunca, pero se paga entera en cada turno.

## Lo que se intentó, y por qué no sirvió

Se barrió la ventana de silencio de Silero VAD de 100 a 1000 ms sobre tres
grabaciones propias, contando cuántas veces partía en dos una intervención que
era una sola. La idea: quedarse con la ventana más corta que no parte ninguna.

**El resultado fue una tabla limpia y sin valor.** Las tres grabaciones eran de
frases **leídas de una pantalla**, y las pausas dentro de ellas salieron así:

```
documento:  0.16 0.22 0.22 0.29 0.35 1.22 2.02 2.69 2.91   (máx 2.91 s)
monto:      0.16 1.98 2.11 3.26                            (máx 3.26 s)
titubeos:   0.19 0.26 0.26 0.77 0.83 1.09 1.34 1.44        (máx 1.44 s)
```

Esas pausas de dos y tres segundos no son titubeos: son el tiempo de buscar en
la pantalla dónde sigue el texto. Y ahí está el problema de fondo: **si una
persona se calla 2,9 segundos, dar el turno por terminado es la decisión
correcta.** Contarlo como un corte castiga al detector por acertar.

O sea que el barrido no medía lo que decía medir. Con esa verdad de referencia
falsa, ninguna ventana del barrido "aprobaba", y la conclusión habría sido que
hace falta esperar más de un segundo — un 25% del presupuesto del turno tirado
por un defecto del método.

Es el mismo error de siempre: **coherente no es correcto**. La tabla cuadraba
consigo misma perfectamente.

## Lo que se hace en su lugar

1. **Grabar habla espontánea, no lectura.** Preguntas que se contestan con las
   propias palabras. Las pausas de quien habla sin leer son de otro tamaño, y
   son las únicas que el agente va a ver por teléfono. Están en
   `probe/record_sample.py` como `PREGUNTAS`, y la sonda solo mira los ficheros
   `muestra-libre-*.wav` por defecto.
2. **La sonda se niega ella sola.** Si encuentra pausas de más de 1,5 s dentro
   de una intervención, avisa de que el audio es de lectura y no da conclusión.
   Un aviso impreso vale más que un comentario en el código que nadie lee
   cuando vuelve a ejecutar esto dentro de un mes.

## La duda que esta medición ya dejó planteada

Aun con habla espontánea, puede que **ninguna ventana de silencio funcione**.
La grabación con titubeos, que es la más parecida a una conversación, tenía
pausas internas de 1,09 y 1,34 s. Si eso se repite hablando de verdad, un
detector que solo mire el silencio tiene que elegir entre cortar a la gente o
gastarse 1,3 s del presupuesto en cada turno.

La salida, si pasa, es **decidir el fin de turno también por el contenido**: una
frase acabada en "mi documento es el uno cero siete..." está claramente a
medias, y eso lo sabe el texto, no el silencio. Es más trabajo y es otra
decisión que habrá que escribir aquí. No se adelanta hasta tener el dato.

## Lo que este ADR NO decide todavía

El valor de la ventana. Sigue sin medirse, y hasta que se mida el presupuesto
del turno lleva una suposición dentro, declarada como tal en cada informe que
la sonda imprime.
