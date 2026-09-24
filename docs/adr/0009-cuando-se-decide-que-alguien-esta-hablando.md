# ADR 0009 — Cuándo se decide que alguien está hablando

- **Fecha:** 2026-09-24
- **Estado:** **REVERTIDA el mismo día.** Se implementó, rompió el sistema, y
  al buscar por qué resultó que la medición que la justificaba estaba mal.
- **Contexto:** el umbral que abre un turno es una constante, y parecía que la
  constante describía la habitación en la que se escribió.

> Este ADR se deja entero, con lo que se creyó y con lo que resultó ser, porque
> **la decisión equivocada y su desmontaje valen más que la decisión**. El
> código vive en `app/deteccion_voz.py`, fuera de la ruta del turno, con sus
> pruebas.

## Lo que parecía el problema

`app/vivo.py` abre turno cuando se acumulan 600 ms de trozos cuya media
absoluta pasa de `UMBRAL_VOZ = 0.005`. Midiendo en `probe/sordera_asr.py` salió
esto:

| | ¿abre turno? |
|---|---|
| original | 6 de 6 |
| voz a la mitad de volumen | **0 de 6** |
| por línea telefónica | **1 de 6** |

De ahí salía una conclusión alarmante y una consecuencia: *quien hable bajito
no es oído, quien llame por teléfono tampoco, y el punto 7 del plan —telefonía
real con Twilio— está apoyado en algo que no puede funcionar*. Y encima el
fallo no deja rastro: sin turno cerrado no hay transcripción vacía, así que ni
el guardia del turno vacío se entera.

## Lo que se hizo

Un detector que calibra el umbral con el ruido de la propia llamada
(`app/deteccion_voz.py`): un suelo de ruido que baja rápido y sube despacio, y
el umbral es ese suelo por un factor. El factor se eligió con `probe/umbral_voz.py`
y con el criterio escrito antes de ver la tabla —*ningún clip de silencio puede
abrir turno; dentro de eso, oír toda la voz que el ASR entiende*—: **2,5**, que
oía 63 de 72 clips de habla degradada sin abrir ninguno de 48 silencios, contra
40 de 72 y 15 de 48 del umbral fijo.

Sobre el papel ganaba en las dos direcciones a la vez. Se puso en `vivo.py` y
en `pipeline.py`, con pruebas deterministas, y las pruebas pasaron.

## Lo que pasó

**`app/prueba_pasarela.py` se puso roja**: el turno dejó de cerrarse. Las cinco
comprobaciones del stack levantado fallaron a la vez.

El mecanismo, medido: sobre una grabación real, el detector adaptativo declara
voz en el **96-97% de los trozos** —el fijo, en el 38-47%— y el silencio
seguido más largo cae de 2520 ms a **380 ms**. Como tras una reanudación la
ventana de cierre es de 1200 ms, **el turno no termina nunca**. El agente se
queda escuchando para siempre.

Y al ir a buscar por qué las sondas no lo habían visto, aparecieron tres cosas,
cada una peor que la anterior.

### 1. Las sondas medían si el turno se ABRE, nunca si se CIERRA

Un detector de voz sirve para las dos cosas. `probe/umbral_voz.py` solo
preguntaba si se acumulaban 600 ms de voz; con eso, un detector que declare
voz *siempre* saca la puntuación perfecta. Medía media función.

### 2. El material de silencio y el parámetro estaban acoplados

Los clips de silencio se seleccionaban exigiendo que su pico no pasara de **3
veces** el suelo del fichero. Después se barrió el factor y se eligió **2,5**.
Cualquier factor igual o mayor que 3 habría dado cero falsos **por
construcción**: la tabla no medía el detector, medía el criterio de selección.
El ruido de una grabación real —respiraciones, roces, ruidos de boca— pasa de
ese 3× con frecuencia, y por eso el 0 de 48 se convirtió en 96% de trozos
declarados voz en cuanto tocó audio de verdad.

### 3. Y la premisa era falsa: la sonda modelaba mal el sistema

`probe/sordera_asr.py` decidía "¿abre turno?" comparando **el nivel medio del
clip entero** contra el umbral. El sistema no hace eso: acumula `voz_ms` trozo
a trozo **y no lo reinicia** cuando hay un silencio en medio, así que una voz
floja acumula sus 600 ms a lo largo de la intervención aunque su nivel medio
esté por debajo del umbral. Y `probe/umbral_voz.py` hacía una tercera cosa
distinta: reiniciaba la racha en cada silencio.

**Tres modelos del sistema y ninguno era el sistema.** Medido con la clase
`Llamada` de verdad:

| caso | umbral fijo | adaptativo |
|---|---|---|
| original | **6 / 6** | **0 / 6** |
| voz a la mitad | **6 / 6** | 5 / 6 |
| voz al 25% | **6 / 6** | 6 / 6 |
| por línea telefónica | **6 / 6** | 5 / 6 |

El umbral fijo oye perfectamente la voz a la mitad, al 25% y la telefónica. **El
problema que este ADR venía a resolver no existía**, y la solución rompía el
caso normal.

## La decisión, entonces

**Se revierte.** `app/vivo.py` y `app/pipeline.py` vuelven al umbral fijo de
0,005, y `app/prueba_pasarela.py` vuelve a pasar 5 de 5 contra el stack
levantado.

`app/deteccion_voz.py` y sus pruebas se conservan **fuera de la ruta**, junto
con `probe/umbral_voz.py`, porque el diseño no es malo: es que no estaba
medido. Si algún día el umbral fijo falla de verdad —otra sala, otro
micrófono, Twilio— el punto de partida está escrito, y también lo está la
forma correcta de medirlo, que es la de la tabla de arriba: **contra la clase
`Llamada`, no contra una idea de la clase `Llamada`**.

## Lo que queda aprendido, que es lo que vale

1. **Una sonda que reimplementa la lógica del sistema mide la
   reimplementación.** Las tres sondas de este ADR copiaron la regla de
   "cuándo hay voz suficiente" y las tres la copiaron distinta. La que acertó
   fue la que importó `Llamada` y le empujó audio.
2. **Un criterio de selección de material que usa la misma magnitud que el
   parámetro a elegir no mide nada.** Elegir el silencio por "pico < 3× suelo"
   y luego preguntar si un factor de 2,5 lo abre es preguntarle a la respuesta.
3. **Un detector de voz se mide por las dos puertas.** Abrir turno y cerrarlo
   son la misma decisión tomada dos veces, y una sonda que solo mira una puede
   aprobar un detector que no calla nunca.
4. **La prueba que lo cazó fue la del stack levantado**, no las deterministas.
   Las seis pruebas del detector estaban en verde mientras el sistema no podía
   terminar un turno.
