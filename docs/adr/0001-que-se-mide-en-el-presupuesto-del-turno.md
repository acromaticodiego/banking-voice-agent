# ADR 0001 — Qué se mide exactamente en el presupuesto del turno

- **Fecha:** 2026-09-19
- **Estado:** aceptada
- **Contexto:** día de medición, antes de escribir una línea del sistema

## El problema

El proyecto se juzga por la latencia por turno, con un objetivo de 800 ms. Pero
"latencia por turno" no es una magnitud única: hay al menos tres formas de
medirla y dan números que se diferencian en un factor de cinco. Si elijo la
forma equivocada, el día de medición me dice que el presupuesto es inalcanzable
cuando sí lo es, o al revés, y en los dos casos tiro tres semanas.

## La decisión

**Se mide el tiempo hasta que cada etapa empieza a producir, no hasta que
termina.** En concreto, el presupuesto del turno es:

```
turno = t_fin_de_habla + t_asr_final + t_primer_token + t_primer_byte_de_audio
```

- `t_fin_de_habla`: desde que la persona calla hasta que el detector decide que
  calló. Es configuración, no cómputo, y se decide en otro ADR.
- `t_asr_final`: desde esa decisión hasta que hay una transcripción cerrada.
- `t_primer_token`: desde que se envía la petición al modelo hasta el primer
  token. **No** hasta el último.
- `t_primer_byte_de_audio`: desde que el TTS recibe la primera frase hasta que
  devuelve la primera muestra reproducible.

## Por qué, y qué se descartó

**Descartado: sumar el tiempo total de cada etapa.** Es lo primero que uno hace
y está mal. El TTS empieza a sintetizar en cuanto el modelo ha emitido una
frase completa; no espera al final de la respuesta. Sumar la generación entera
y después la síntesis entera cuenta dos veces un tramo que en la conversación
real ocurre en paralelo. Con una respuesta de tres frases, esa suma infla el
número lo bastante como para hacer fracasar un diseño que funciona.

**Descartado: medir de punta a punta con un cronómetro sobre la demo.** Da el
número verdadero, pero es un número solo: cuando no cabe en el presupuesto no
dice qué etapa hay que arreglar. La métrica de portada exige el desglose. El
cronómetro de punta a punta se mantendrá después como comprobación de que el
desglose suma lo que dice sumar —si no cuadra, es que hay una espera que no
estoy midiendo, y eso es justo lo que quiero descubrir.

**Descartado: medir solo el modelo.** Es la tentación, porque es la etapa
vistosa y la que se compara entre proveedores. Pero en una conversación real el
detector de fin de habla se lleva habitualmente más milisegundos que el modelo,
y es gratis recortarlo. Medir solo el modelo optimiza la parte que menos manda.

## Consecuencia incómoda que acepto

El número que salga de aquí **no es lo que percibe la persona que llama**. Falta
el tiempo de red del audio en ambos sentidos, y falta el tramo de reproducción.
Es un límite inferior, medido en esta máquina y en condiciones buenas. Hay que
decirlo así cada vez que se publique la cifra, porque un límite inferior
presentado como la experiencia real es exactamente la clase de número que
cuadra consigo mismo y está mal.

## Cómo se verifica que esta decisión se respeta

Cada sonda declara en el campo `que_mide` la frase exacta de qué instante a qué
instante cronometra, y ese texto viaja dentro del JSON de resultados. Un número
sin esa frase no se publica.
