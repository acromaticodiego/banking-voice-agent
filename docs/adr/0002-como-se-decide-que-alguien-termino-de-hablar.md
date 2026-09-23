# ADR 0002 — Cómo se decide que alguien terminó de hablar

- **Fecha:** 2026-09-19
- **Estado:** medida. La detección por silencio sola no cabe en el presupuesto,
  y el dato está abajo.
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

## El resultado, ya con habla espontánea

Tres grabaciones propias contestando a un agente, sin leer. Pausas internas:

```
libre-bloqueo:  1.50
libre-cobro:    0.16  0.19  0.54
libre-datos:    0.16  0.22  0.93
```

Otra población distinta de la anterior: la mayoría por debajo de un segundo, y
ninguna de dos o tres segundos. El umbral que separa "lectura" de
"conversación" se subió de 1,5 a 2,0 s **con las grabaciones delante**, no por
conveniencia: la única pausa de 1,50 s cae entre dos frases completas.

Lo que hay en cada pausa, transcrito:

```
bloqueo:  "...no funciona desde el día de ayer."  [1.50 s]  "Nadie me avisó nada..."
datos:    "...mi cédula es 1070234567"            [0.93 s]  "mi nombre completo es Juan Diego..."
cobro:    "...me apareció la compra de la nada"   [0.54 s]  "pero yo no la hice"
```

Las tres son distintas y por eso importan:

- La de **bloqueo** viene después de una frase acabada. Cortar ahí es
  defendible: gramaticalmente el turno podía haber terminado.
- La de **datos** está **a mitad de una respuesta**: la persona ha dicho el
  documento y va a decir el nombre. Cortar ahí es cortarle mientras se
  identifica, en la parte más delicada de la llamada.
- La de **cobro** es un respiro corto, 540 ms, y ninguna ventana razonable la
  toca.

## La decisión

**Para no cortar a nadie dentro de su turno hace falta una ventana de 1600 ms.**
Eso es el 188% del presupuesto de 800 ms del turno entero, antes de transcribir,
pensar o sintetizar nada.

O sea: **el objetivo de 800 ms es inalcanzable con detección por silencio
sola.** No es cuestión de afinar el umbral; no hay umbral que valga. Cualquier
valor que quepa en el presupuesto corta a la gente, y cualquier valor que no
corte se come el presupuesto.

Lo que se hace en su lugar es **decidir el fin de turno también por el
contenido**: preguntar si lo dicho hasta ahora está acabado. "Mi cédula es
1070234567" está claramente a medias cuando el agente pidió documento **y**
nombre; "no funciona desde el día de ayer" no lo está. Esa diferencia la sabe
el texto, no el silencio.

Con eso la ventana de silencio baja a unos 300 ms en el caso normal y solo se
alarga cuando la frase parece incompleta. El coste se paga donde hace falta en
vez de en todos los turnos.

## Lo que se descarta, y por qué

**Descartado: subir la ventana a 1600 ms y aceptarlo.** Es lo honrado si no
hubiera alternativa, pero convierte cada turno en dos segundos largos de espera
y el producto deja de parecerse a una conversación. Es preferible un sistema
que ocasionalmente se pise a uno que siempre se hace esperar.

**Descartado: bajar la ventana a 300 ms sin más.** Corta en las tres
grabaciones, y una de ellas es alguien identificándose. Un agente que corta a
quien está dando su documento no es solo molesto: pierde el dato.

**Descartado: afinar el umbral de Silero en vez de la ventana.** Mueve dónde
empieza y acaba el habla, no cuánto se espera después. No ataca el problema.

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

## Implementado el 2026-09-23, y lo que costó

Está en `app/fin_de_turno.py`. Cuando la ventana corta de silencio se cumple,
antes de contestar se mira **lo que se ha dicho**. Si la frase está a medias, se
sigue escuchando con una ventana larga en vez de contestar.

Son reglas, no una llamada a un modelo, y el motivo es de presupuesto:
preguntarle al modelo "¿ha terminado?" cuesta otra petición en la ruta crítica,
y el modelo es justo la etapa cara. Gastar 325 ms en cada pausa para decidir si
esperar 900 más es pagar el problema para no tenerlo. Cuando las reglas no
basten, el siguiente paso es un clasificador pequeño entrenado, no el grande.

Dos reglas:

- La última palabra no puede ser de las que piden algo detrás: `de`, `y`, `mi`,
  `es`, `porque`…
- Si se pidió el documento y todavía no hay un número de seis a once dígitos,
  la persona no ha terminado de decirlo.

**El resultado, sobre la misma grabación:**

| | sin la regla | con la regla |
|---|---|---|
| lo que el sistema oyó | `"mi cédula es 70 234"` | `"mi cédula es 70 23 4 5 6 7"` |
| consultas adelantadas usadas | 0 de 1 | **1 de 1** |
| primer audio | 1570 ms | 2795 ms |
| primer dato | 2978 ms | 3625 ms |

Deja de cortar. Y al haber por fin un documento entero, el adelanto de consultas
del [ADR 0004](0004-adelantar-la-consulta-antes-de-que-el-modelo-la-pida.md)
—que llevaba dos ramas sin dispararse ni una vez— empieza a usarse.

**Cuesta 1225 ms**, y no se disimula. Son los ~900 de ventana larga más una
segunda transcripción que cae en la ruta crítica. El coste asimétrico manda:
cortar a alguien mientras dicta su cédula pierde el dato y obliga a repetir la
llamada entera; esperar de más solo es lento. Pero 3625 ms hasta el primer dato
está muy lejos de los 800 del objetivo, y eso sigue sin resolverse.

La segunda transcripción es lo primero que hay que quitar: con un ASR en
streaming no haría falta transcribir dos veces, porque el texto ya estaría hecho
cuando toca decidir.

## Lo que este ADR NO decide todavía

El valor de la ventana. Sigue sin medirse, y hasta que se mida el presupuesto
del turno lleva una suposición dentro, declarada como tal en cada informe que
la sonda imprime.
