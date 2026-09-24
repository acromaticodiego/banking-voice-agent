# ADR 0009 — Cuándo se decide que alguien está hablando

- **Fecha:** 2026-09-24
- **Estado:** aceptada
- **Contexto:** el umbral que abre un turno era una constante, y la constante
  describía la habitación en la que se escribió.

## El problema

`app/vivo.py` abría turno cuando la media absoluta de un trozo de 20 ms pasaba
de `UMBRAL_VOZ = 0.005`. Funcionaba, y **funcionaba por una coincidencia**: el
ruido de la habitación de desarrollo mide 0,0011, así que había 13 dB de margen
y nunca se abría un turno de más.

Medido en `probe/sordera_asr.py` sobre las seis grabaciones degradadas:

| | ¿abre turno? |
|---|---|
| original | 6 de 6 |
| voz a la mitad de volumen | **0 de 6** |
| voz al 25% | **0 de 6** |
| por línea telefónica | **1 de 6** |

**Alguien que habla bajito no es oído. Y alguien que llama por teléfono,
tampoco.** Eso último hace inviable el punto 7 del plan —telefonía real con
Twilio— porque el audio de una llamada llega más flojo que un micrófono de
portátil a 20 cm.

Lo peor no es que no se oiga: es que **nadie se entera**. El turno no llega a
cerrarse, así que no hay transcripción vacía, así que el guardia del turno
vacío tampoco actúa. Alguien habla, el agente calla, y no queda ni rastro de
que hubiera alguien al otro lado. De los fallos de este proyecto, es el único
que no deja huella.

## La decisión

**El umbral se calibra con el ruido de la propia llamada** (`app/deteccion_voz.py`):
se sigue un suelo de ruido y el umbral es ese suelo por un factor, con un
mínimo absoluto para que un canal digitalmente mudo no abra turno con cualquier
bit suelto.

El suelo **baja rápido y sube despacio**, y —esto se escribe así porque el
comentario original decía otra cosa y era falso— lo que impide que una frase
larga deje sordo al detector no es la lentitud de la subida: es que **los
trozos declarados voz no alimentan la subida en absoluto**. La subida lenta
sirve para otra cosa: que un ruido que no llega a contar como voz no levante el
suelo de golpe.

### El factor, elegido con el criterio escrito antes de la tabla

`probe/umbral_voz.py`, 2026-09-24, 72 clips de habla degradada que el ASR
entiende y 48 de silencio. El criterio, fijado antes de mirar: *ningún clip de
silencio puede abrir turno; dentro de eso, oír toda la voz que el ASR entiende*.

| | oye voz | abre silencios |
|---|---|---|
| umbral fijo 0,005 (hasta hoy) | 40 / 72 | 15 / 48 |
| factor 2,0 | 70 / 72 | 1 / 48 |
| **factor 2,5 (elegido)** | **63 / 72** | **0 / 48** |
| factor 3,0 | 57 / 72 | 0 / 48 |

El 2,0 oye siete clips más y **se descarta igual**, porque el criterio se fijó
antes y manda no abrir silencios. Los nueve clips a los que el 2,5 se queda
sordo son degradaciones extremas —voz al 10%, ruido al mismo nivel que la voz—
donde el ASR tampoco acierta gran cosa.

Lo que hace fácil esta decisión es que **el adaptativo gana al fijo en las dos
direcciones a la vez**: oye un 58% más de voz y abre cero silencios en vez de
quince. No hay intercambio que discutir.

El detector va también en `app/pipeline.py`, que tenía su propia copia de la
constante. Una tubería de medir con su propio detector mide su propio detector.
Y vive en la llamada, no en el turno: el suelo de ruido es una propiedad de la
sala desde la que llaman, y tirarlo en cada turno obligaría a reaprenderlo cada
vez que alguien contesta.

## El límite que esto NO arregla, y por qué no se arregla hoy

Si el ruido de fondo sube **por encima del umbral** a mitad de llamada —alguien
enciende un ventilador, sale a la calle— todos los trozos se declaran voz, el
suelo deja de aprender, y el detector se queda abierto: **500 de 500 trozos**,
comprobado en `app/prueba_deteccion_voz.py`. El agente abriría turnos que nadie
dijo; con el filtro del ADR 0008 puesto llegan vacíos, caen en el guardia del
turno vacío y acaban en un humano. Degrada mal, pero degrada, y deja rastro.

El arreglo evidente es *"nadie habla N segundos seguidos sin una sola pausa, así
que una racha más larga significa que el suelo está mal calibrado"*. **No se
hace, y el motivo está medido:** la racha continua de habla más larga en las
seis grabaciones reales es de **9,9 segundos**. Entre eso y un ruido sostenido
no queda hueco que separe con seis grabaciones de un solo hablante, y elegir un
umbral con ese margen es exactamente el error que el ADR 0008 rechazó dos horas
antes para la señal de confianza. Aplicar allí una vara y aquí otra, porque
este arreglo apetece más, sería peor que no arreglarlo.

Se arregla cuando haya grabaciones de otras salas y otras voces, que es el
punto 5 del plan.

## Lo demás que sigue sin estar medido

- **Una sola sala y un solo micrófono**, otra vez. Las degradaciones son
  atenuación y ruido añadido, no una sala distinta: la atenuación no trae la
  reverberación que sí trae alejarse de verdad de un micrófono.
- **El arranque de la llamada está medido y no es un problema.** El suelo se
  inicializa con el primer trozo que llega, así que si alguien empieza a hablar
  en el instante en que se conecta, nace en el nivel de la voz. Parecía que eso
  costaría el primer turno; **no lo cuesta**: de los 72 clips con voz abren
  turno 63 con un segundo de sala por delante y **los mismos 63 sin él**. El
  motivo es que la energía del habla sube y baja entre sílabas, y el suelo, que
  baja rápido, se planta en los valles en unas décimas.

  Esto salió de un sitio inesperado: al cambiar el detector, una prueba de otro
  módulo empezó a fallar porque su audio sintético era ruido de nivel
  perfectamente **constante**. Un tono plano no es voz, y contra él el detector
  sí se queda sordo. La prueba se arregló y la lección se queda: los dobles de
  audio tienen que fluctuar, o miden algo que no existe.
