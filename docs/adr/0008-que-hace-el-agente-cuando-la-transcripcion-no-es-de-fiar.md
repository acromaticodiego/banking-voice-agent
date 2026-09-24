# ADR 0008 — Qué hace el agente cuando la transcripción no es de fiar

- **Fecha:** 2026-09-24
- **Estado:** aceptada
- **Contexto:** el guardia del turno vacío tapa el silencio limpio. No tapa el
  silencio del que Whisper se inventa una frase, que tiene letras y pasa el
  filtro como si alguien hubiera hablado.

## El problema

El agente ya sabe qué hacer cuando no le dicen nada: `es_silencio()` mira si la
transcripción tiene alguna letra o dígito, y si no la tiene contesta "¿Sigue
ahí? No le escucho." sin gastar un token. Eso está implementado y probado desde
el 2026-09-24.

Pero la transcripción de un silencio **no siempre es la cadena vacía**. Whisper
se inventa frases sobre el ruido de fondo, y lo que se inventa tiene letras:

> `sala-8s-4` → *"Este es el canal de subtítulos en español de la Iglesia…"*
> `fuerte-2s-0` → *"¡Suscríbete!"*
> `sala-8s-5` → *"¿Qué pasa?"*
> `sala-8s-3` → *"¡Muchas gracias!"*

Las dos primeras delatan su origen —material de subtítulos de internet— y a
ojo se reconocen. **La tercera no delata nada.** "¿Qué pasa?" es una frase que
un cliente diría por teléfono, llega al modelo como un turno legítimo, y el
agente le contesta a una habitación vacía. Es el mismo fallo que el saludo al
silencio, pero disfrazado de conversación.

Y hay un segundo camino, que no necesita que la sala esté en silencio: el
buffer que se transcribe lleva pegada la **cola de silencio que cerró el turno**
(300 ms, o 1200 con la ventana larga, o 3600 con las dos reanudaciones que el
sistema permite). Sobre esa cola, Whisper llegó a repetir la frase entera
detrás de sí misma: **15 palabras de más** en un turno real.

**Ese caso concreto hay que leerlo con cuidado, y se explica abajo:** salió con
la primera versión del material, que estaba mal construida. Con el material
corregido no se reprodujo. Que Whisper repita sobre el silencio es un
comportamiento conocido suyo; **su frecuencia en este sistema no está
establecida** y no se apoya el filtro en ella.

## Lo que se midió antes de decidir

`probe/confianza_asr.py`, 2026-09-24, `faster-whisper small` en GPU, un
hablante, una sala, 106 clips: 42 con voz y 64 sin ella. El silencio no es
sintético: son 142 tramos de cuarto de segundo sacados de las propias
grabaciones —los que no llevan ni un trozo mudo y cuyo pico no pasa de tres
veces el suelo real de su fichero— cosidos en clips de 1, 2, 4 y 8 segundos.

| | sin filtro | con `vad_filter=True` |
|---|---|---|
| clips sin voz que producen texto | **16 de 64** | **0 de 64** |
| clips con voz que se quedan mudos | 0 de 42 | 0 de 42 |
| latencia, turno de 3 s + 1,2 s, mediana n=18 | 178 ms | 202 ms (**+24 ms**) |

Desglose de los 16 por duración del silencio: 1 de 13 a 1 s, 4 de 15 a 2 s, 5
de 15 a 4 s, 6 de 17 a 8 s. **Cuanto más silencio se le da, más se inventa** —
pero ya inventa con un solo segundo, que es una duración de pausa corriente. Y
ninguno de los 24 clips pasados por la línea telefónica alucinó: la banda de
300–3400 Hz se lleva por delante la parte del ruido que el modelo confunde con
voz.

**Este 16 de 64 es el segundo número; el primero fue 7 de 64 y estaba mal.**
El banco de silencio se construía cogiendo los tramos cuya energía bajara del
10% de la del fichero, y resultó que lo que más baja la energía de un tramo no
es el silencio de la sala: son los ceros exactos que el grabador deja al
principio y al final, 18 trozos de 20 ms en cada grabación. El banco se llenaba
justo de los tramos contaminados —10 en total, la mitad medio mudos— y cada
clip alternaba silencio digital con ruido real. Con un criterio relativo al
suelo real de cada fichero salen 142 tramos de sala de verdad, y sobre ellos
Whisper inventa **más del doble**. El material malo no exageraba el problema:
lo escondía.

**El VAD de energía que ya existe protege por accidente, y con poco margen.**
El ruido de esta habitación mide 0,0011 de media absoluta y `UMBRAL_VOZ` es
0,005, así que en esta sala un silencio nunca llega a abrir un turno. Son 13 dB
de margen: un aire acondicionado, un manos libres o una calle se los comen. Por
eso la sonda incluye `sala-fuerte`, el mismo ruido subido justo por encima del
umbral, y ahí alucinan **5 de 12 clips**, uno de ellos con un solo segundo de
ruido, que es una duración de pausa perfectamente normal.

*(Ese umbral fijo de 0,005 dejó de existir unas horas después, el mismo día:
medirlo aquí llevó al ADR 0009.)*

## Lo que se descartó, y por qué

**Un umbral sobre la confianza del modelo**, que era la opción elegante.
faster-whisper devuelve `no_speech_prob`, `avg_logprob` y `compression_ratio`
por segmento, y hoy se tiraban: la llamada era `segmentos, _ = transcribe(...)`
y de cada segmento solo se usaba `.text`. El criterio se fijó antes de mirar
los números —*el corte no puede rechazar ni un solo clip con voz, porque dejar
sordo al agente es peor que contestarle a un silencio*— y con él:

- **`no_speech_prob` no separa.** Hay habla de verdad que llega a 0,78 y los
  inventos van de 0,50 a 0,83: los dos rangos se solapan casi enteros, y el
  corte que no toca el habla caza 3 de 16. La señal que parece hecha para esto
  es la que no sirve.
- **`avg_logprob` separaba… hasta que entró más material.** Cazaba 7 de 7 con
  un corte en −0,58. Al añadir seis clips de turno con voz, el peor clip de
  habla legítima se puso en −0,98, el corte bajó con él y pasó a cazar 5 de 7.
  Y con el material de silencio corregido, **6 de 16**. Tres medidas, cada una
  peor que la anterior, y ninguna por un error de medición: el umbral nunca
  había sido bueno, solo había visto poco.
- **La repetición del final no la caza ninguna señal.** El turno que ganó 15
  palabras tiene `avg_logprob` −0,386, que es *bueno*: repetir lo que uno
  acaba de decir es lo más probable del mundo para un modelo de lenguaje. Un
  umbral de confianza es ciego justo al fallo más peligroso de los tres.

También se descartó **tirar el segmento en vez del turno**, que es más fino: el
corte por segmento (`no_speech` > 0,519, el máximo de 34 segmentos de habla)
caza 14 de 16, que es lo mejor que consigue cualquier umbral aquí. Sigue siendo
peor que el filtro, que caza 16 de 16, y cuesta una regla más que explicar y un
número que ajustar cada vez que cambie el micrófono.

## La decisión

**`vad_filter=True` en la ruta del turno, y las señales anotadas sin actuar.**

1. **El filtro va en `app/vivo.py` y en `app/pipeline.py`.** En las dos: una
   tubería de medir que no lleva el mismo filtro que la de correr no mide el
   sistema, mide otro. Cuesta +24 ms sobre un turno de 2389, que es el 1%.

2. **Las tres señales se resumen y se pegan al aviso del turno**
   (`app/confianza.py`), y **no deciden nada**. Es material para cuando haya
   varias voces y varias salas: entonces el umbral se podrá fijar con datos en
   vez de con dieciséis casos de una habitación. Se guardan los extremos y no el promedio, porque lo
   que delata a un turno es su peor segmento: una frase de verdad con tres
   palabras de aire pegadas tiene buen promedio y un segmento pésimo.

3. **No hace falta conducta nueva.** Con el filtro puesto, un turno de silencio
   llega como cadena vacía, que es exactamente lo que el guardia del turno
   vacío ya sabe tratar: dos preguntas distintas y al tercero un humano con su
   ticket. El arreglo consiste en que la señal llegue limpia al guardia que ya
   existe y ya está probado.

## Lo que esta decisión NO arregla

- **Una sola sala y un solo micrófono.** 16 de 64 es una tasa de esta
  habitación. Con otras voces y otros ruidos el número será otro, y puede que
  el filtro deje pasar cosas que aquí no pasaron.
- **La verdad "sin voz" la decide la energía, no un oído.** Un tramo flojo
  podría llevar el final de una palabra, y entonces se habría contado como
  invento algo que sí se dijo. El error va en la dirección incómoda —infla la
  cifra— y los WAV se pueden dejar en `artifacts/` con `--guardar-clips` para
  desmentirlo escuchándolos. Que el primer criterio de selección fuera malo y
  escondiera la mitad del problema es la razón de que este apartado exista.
- **Que el filtro pueda comerse habla de verdad en condiciones peores.** Aquí
  no se comió ninguno de 42 clips, pero con voz baja o muy lejos del micrófono
  eso no está medido, y sería el fallo grave: un agente sordo es peor que uno
  que contesta a un silencio. Es lo primero que hay que volver a mirar cuando
  haya grabaciones nuevas.

Por eso `app/prueba_confianza.py` usa un ASR de mentira que **revienta si
alguien llama a `transcribe` sin el filtro**. El filtro parece prescindible: no
rompe ninguna demo, no cambia ningún texto en una sala callada y ahorra 24 ms.
Un guardia cuyo efecto no se nota es justo el que alguien quita por limpieza.
