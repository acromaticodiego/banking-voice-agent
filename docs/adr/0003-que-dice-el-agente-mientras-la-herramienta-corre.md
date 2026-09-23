# ADR 0003 — Qué dice el agente mientras una herramienta corre

- **Fecha:** 2026-09-23
- **Estado:** aceptada
- **Contexto:** medido el turno de punta a punta, el agente se lleva 1296 ms de
  los 1424 del camino crítico.

## El problema

Un turno con herramienta no es una llamada al modelo: son **dos**, con una
consulta HTTP en medio. Decidir qué herramienta llamar, esperar a que responda,
y volver a preguntarle al modelo con el resultado. Medido de punta a punta,
eso son 1296 ms en los que el agente no dice absolutamente nada.

Una persona al teléfono no aguanta segundo y medio de silencio sin pensar que
se cortó la llamada. Y el silencio no se arregla haciendo el modelo más rápido:
la cadena tiene tres eslabones y ninguno es gratis.

## La decisión

**Cuando el modelo decide llamar a una herramienta en su primer paso, el agente
dice una frase puente inmediatamente**, y la respuesta buena llega después:

> *"Permítame un momento, lo estoy revisando."*

Medido sobre el mismo turno, tres vueltas:

| | sin puente | con puente |
|---|---|---|
| primer audio, cuando deja de oírse silencio | 2389 ms | **1424 ms** |
| primer dato, cuando se entera de algo | 2389 ms | 2061 ms |

## La condición que hace honesta esta decisión

**Los dos números se publican siempre juntos.** La frase puente mejora el
primero en casi un segundo y no toca el segundo: la espera sigue ahí, solo que
tapada. Publicar únicamente "1424 ms" convertiría un relleno en una mejora de
rendimiento, y sería la quinta vez en este proyecto que una cifra sale limpia y
miente.

La sonda lo impone: `app/medir_turno.py` imprime los dos y los guarda los dos.
Un informe con uno solo no se puede sacar de ahí sin editarlo a mano.

## Lo que se descartó

**Descartado: callar y ya.** Es lo que había, y son 2389 ms de nada. En una
llamada real eso es cuando la gente dice "¿aló?".

**Descartado: decir la frase puente en todos los turnos.** Suena a relleno y
delata que el sistema es lento. Solo se emite cuando el modelo decide llamar a
una herramienta en su primer paso, que es justo el caso en el que se sabe que
va a haber espera. Los turnos que se contestan directos no la llevan.

**Descartado: una frase puente que no sea verdad** ("ya casi lo tengo", "lo veo
aquí"). El agente **está** consultando, así que "lo estoy revisando" es cierto.
Una frase de relleno que afirma algo falso es exactamente lo que este proyecto
dice que no se hace, y además se descubre en cuanto la consulta devuelve que no
hay nada.

**Descartado: adelantar la respuesta antes de tener el resultado.** Sería
rapidísimo y afirmaría datos que ninguna herramienta ha devuelto. Es la línea
que no se cruza.

## Lo que queda abierto

Los 2061 ms del primer dato siguen muy por encima de los 800 del objetivo. La
frase puente compra tiempo, no lo elimina. Lo que de verdad lo bajaría es
**adelantar la llamada a la herramienta**: si en cuanto el ASR reconoce un
número de documento se dispara `consultar_identidad` sin esperar al modelo, la
consulta corre en paralelo con la primera decisión en vez de detrás. No está
medido y no se da por hecho.
