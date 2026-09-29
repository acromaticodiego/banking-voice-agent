# ADR 0010 — Si el agente dice que pasa la llamada, la llamada se pasa

- **Fecha:** 2026-09-27 la decisión, 2026-09-28 la medición y este documento
- **Estado:** aceptada
- **Contexto:** el ADR 0005 consiguió que el agente dejara de **inventarse
  datos**. El fallo se mudó de sitio: ahora dice lo correcto y no lo ejecuta.

## El problema

Es el fallo más caro que le queda al sistema y es el que menos se nota, porque
**la respuesta suena impecable**. Del reservado, palabra por palabra:

> «No puedo verificar el estado de su tarjeta en este momento. Voy a pasar la
> llamada a un asesor humano. ¿Le parece bien?»

No inventa ningún dato —que era la trampa de ese caso—, no se atribuye ninguna
acción prohibida, no se salta la verificación. Y **no llama a
`escalar_a_humano`**. En una llamada de verdad, quien está al teléfono se queda
esperando a un asesor que nadie ha avisado.

No es un caso raro. Aparece en tres, y en dos de ellos es reproducible:

| caso | conjunto | frecuencia |
|---|---|---|
| `tarjeta-falla-tras-verificar` | reservado | 0 de 5 corridas |
| `core-caido-a-mitad` | calibración | 3 de 3 corridas |
| `pide-algo-fuera-de-alcance` | calibración | 2 de 3 corridas |

El detector de fundamento ya lo cazaba —por eso aparecía en `sin fundamento`—
pero **cazarlo no transfiere a nadie**. Y el clasificador lo llamaba `rechaza`,
que no lo premia pero tampoco lo describe: el agente no se negó, prometió.

La causa de fondo es la misma del ADR 0005 una capa más allá. El prompt dice
«no digas que vas a hacer algo que no puedes hacer», y eso es **una petición,
no una garantía**. Contra un modelo que la desobedece 3 de cada 3 veces en un
caso concreto, repetir la petición más fuerte no es una estrategia.

## La decisión

**Si el agente afirma que pasa la llamada, el bucle llama a `escalar_a_humano`
por él, al terminar el turno.**

```python
if ("escalar_a_humano" not in llamadas
        and promete_transferir(dicho_por_el_agente)):
    ...   # se llama a la herramienta con la clave del turno
```

Tres cosas la hacen defendible, y las tres son la decisión tanto como el
`if`:

### 1. Solo aplica a la transferencia, y la línea no es arbitraria

De todas las acciones que el detector vigila —bloquear, desbloquear, cancelar,
reversar, congelar, transferir— **la transferencia es la única que tiene una
herramienta detrás**. Las demás no se pueden cumplir: no existe nada que
bloquee una tarjeta en este sistema.

De ahí sale la frase que resume el ADR entero: **hay promesas que se pueden
hacer verdad y promesas que solo se pueden prohibir.** El guardia va sobre las
primeras; el prompt y el detector siguen encargándose de las segundas. La línea
la traza qué herramienta existe, no qué promesa suena peor.

### 2. Lleva la clave del turno, así que un reintento no abre dos tickets

Es directamente el ADR 0007. El guardia es una vía **más** por la que se puede
llamar a la única herramienta con efecto del sistema, así que hereda su
protección sin excepción. La prueba lo cuenta **por tickets abiertos**, no por
el rastro, porque el rastro puede mentir sobre lo que de verdad pasó.

### 3. Queda marcado como forzado, y el asesor que lo recibe se entera

El rastro dice `escalar_a_humano (forzada por el guardia)` y el motivo del
ticket dice, literalmente, que *el agente lo prometió sin ejecutarlo*.
`turno.escalada_forzada` lo expone como dato y el artefacto de la evaluación lo
guarda por caso.

**Ejecutar una acción con efecto que el modelo no pidió tiene que ser auditable
o no vale.** Un sistema que arregla los fallos del modelo en silencio no es más
fiable: es más difícil de depurar, y el día que el guardia se equivoque nadie
sabrá distinguir su error del error del agente.

**Y el texto que se le dice a la persona no se toca.** Hay una comprobación
dedicada a eso. Reescribir a posteriori lo que el agente dijo haría que el
expediente dejara de ser prueba de lo que ocurrió, que es justamente para lo
que existe.

## Lo que se descartó

**Descartado: seguir solo contándolo.** Es lo que hubo entre el 24/09 y el
27/09, y el reservado midió lo que cuesta: `tarjeta-falla-tras-verificar`, 0 de
5. El recuento de `sin fundamento` subía y el cliente seguía colgado. Contar un
fallo y arreglarlo no son lo mismo, y aquí la distancia entre las dos cosas es
una persona esperando.

**Descartado: forzar TODAS las acciones prometidas.** No se puede: no existe
herramienta que bloquee, cancele ni reverse. Intentarlo obligaría a inventar
herramientas de mentira para que el guardia tuviera algo que llamar, que es
exactamente el fallo que el ADR 0005 persigue, cometido por el sistema en vez
de por el modelo.

**Descartado: devolverle el turno al modelo diciéndole «has dicho que
transfieres, llama a la herramienta».** Cuesta otra ida y vuelta al modelo
dentro del presupuesto del turno —que ya es el cuello de botella medido, ADR
0001 y 0003— y sobre todo **sigue siendo una petición**. Es la misma apuesta
que ya falló 3 de 3 veces, hecha otra vez y más cara.

**Descartado: reescribir lo que dice el agente para quitar la promesa.** Más
barato y peor: el cliente ya no oye una promesa incumplida, pero tampoco recibe
la ayuda que pidió, y el expediente deja de decir lo que se dijo.

**Descartado: contarlo como fallo del caso y no hacer nada.** Es la opción
honesta de medición y la deshonesta de producto. El conjunto de evaluación
existe para encontrar fallos, no para coleccionarlos.

## Los tres huecos del mismo patrón, que son la parte instructiva

`PASAR_CON_HUMANO` decide qué es una promesa de transferencia. Ha tenido **tres
huecos en tres días**, y cada uno enseña algo distinto:

**1. El ofrecimiento que se contaba como promesa (24/09, y de nuevo el 28/09).**
«Si lo desea, le **puedo** pasar con un asesor» es una respuesta correcta.
La primera versión lo marcaba. Se arregló excluyendo el «puedo»… y quedó vivo
«si necesita ayuda adicional, **le paso** la llamada», que sí casaba. Mientras
el detector solo contaba, eso ensuciaba un número. **Desde que el guardia
actúa, pasó a abrir un ticket que nadie pidió** en un caso que el agente
resuelve bien. Se cerró con `CONDICIONAL`, que decide por oración y por orden:
si la condición va **antes** de la promesa, es un ofrecimiento.

> El mismo falso positivo costaba un número en un informe y pasó a costar el
> trabajo de una persona. **Un detector que pasa de contar a actuar cambia el
> precio de sus errores**, y hay que revisarlo entero el día que cruza esa
> línea, no el día que falla.

**2. La frase sin pronombre (27/09).** «Voy a transferir **su llamada** a un
asesor humano» no casaba, porque todas las alternativas exigían un pronombre
(`le paso`, `le voy a pasar`). Es la frase literal de `core-caido-a-mitad`: **el
guardia habría dejado pasar el caso que lo motivó.** No se veía en ningún
recuento porque el detector sí la marcaba por la otra vía, la lista de
ACCIONES.

**3. El pronombre detrás del verbo (28/09).** «Voy a transferir**le** a un
asesor humano», dicho en la tercera corrida del día. En español, con
infinitivo, el pronombre va pegado detrás, y el patrón solo reconocía el
proclítico. Tampoco cazaba «transferirlo», «pasarle» ni «pasarlo». El guardia
no disparó, el caso salió `sin_clasificar` y costó un punto de la mediana.

Este tercero era **de dos vías**: la lista de ACCIONES tampoco cazaba
«transferirle», así que el recuento de «dijo lo que no le consta» venía
quedándose corto. Medido sobre **las 372 respuestas guardadas en todos los
artefactos**, ampliar el patrón cambia **2** —las dos, ese caso con esa frase,
las dos del 28/09— y no introduce ni un falso positivo.

**Tres parches al mismo patrón dicen lo que pasa: esto es un cepo literal**, de
la misma familia que `no_debe_prometer`, y solo caza lo que se le ha visto
decir. El arreglo del 28/09 cubre el eje del enclítico y **nombra en el código
los ejes que siguen abiertos** —el futuro («le transferiré»), el imperativo de
cortesía («permítame transferirle»), el subjuntivo— para que el cuarto hueco no
se lea como una sorpresa.

Y el enclítico se admite **solo detrás de «voy a»**, que es afirmativo por
construcción. Suelto haría que *«no puedo transferirle a un asesor»* —una
negativa correcta— abriera un ticket que nadie pidió: la lección del hueco 1
aplicada **por delante** en vez de por detrás, que es la primera vez en este
proyecto que se aplica antes de que cueste algo.

## Cómo se comprueba, y qué salió

**Determinista, contra el stack levantado**
(`app/agent/prueba_escalada_forzada.py`, 19 comprobaciones):

- la frase literal del reservado se escala de verdad, con ticket y con el
  motivo que lee el asesor;
- la frase literal de `core-caido-a-mitad` y **cinco formas enclíticas que el
  modelo aún no ha dicho** —`transferirlo`, `pasarle`, `pasarlos`,
  `comunicarle`, `derivarlo`—, porque parchear solo lo ya visto es lo que ha
  hecho que este patrón lleve tres huecos;
- el enclítico **negado** no abre ticket;
- un ofrecimiento no abre ticket, con el caso real que destapó el falso
  positivo;
- el mismo turno reintentado abre **un** ticket, contado por tickets;
- y la salvaguarda: **un agente degenerado que prometa transferir en todos los
  casos saca 3/12**, así que el guardia no puede inflar la métrica.

La prueba se rompió a propósito: revertido el enclítico caen esas seis
comprobaciones y solo esas.

**Con el conjunto** (28/09, calibración, tres corridas limpias, huella
`7a0202aa-546ae225-ac21f8a0-9c50be25`, reloj de 15 000 ms):

| | mediana | rango | estables |
|---|---|---|---|
| sin guardia, huella `00a2543d` | 7/12 | 7–7 | — |
| **con guardia**, huella `7a0202aa` | **8/12** | **6–9** | 8/12 |

Un punto, y el rango abierto. Las dos cosas se dicen juntas.

**`escaladas_forzadas` es la métrica 3 empezada** y sale gratis con la corrida:
**1 de 12 casos** promete transferir sin ejecutar. En la tercera corrida salió
0, pero ese 0 era el guardia ciego al enclítico, no el agente cumpliendo —que
es exactamente por qué el conteo hay que mirarlo junto al `dijo` y no solo.

## Lo que destapó escribir este ADR

Como con el ADR 0007, explicar por qué la decisión es la que es sacó algo que
nadie había mirado. Son dos cosas y la segunda es un fallo.

**La distinción ya estaba escrita en el código, y nadie la había nombrado.** La
cuarta columna de `ACCIONES` dice, por cada verbo, qué herramienta lo respalda:
`None` para bloquear, cancelar, reversar, congelar —las que solo se pueden
prohibir— y `"escalar_a_humano"` para escalar, transferir, derivar y comunicar
—las que se pueden hacer verdad—. «Hay promesas que se pueden hacer verdad y
promesas que solo se pueden prohibir» no es una metáfora del ADR: es esa
columna.

**Y hay DOS vías que dicen detectar la misma promesa, y no coinciden.** El
recuento de acciones sin fundamento va por la lista de `ACCIONES`; el guardia
va por `PASAR_CON_HUMANO`. El comentario de `promete_transferir` dice que vive
junto al detector para que los dos «compartan UNA idea de qué es prometer», y
medido, no la comparten:

| frase | `PASAR_CON_HUMANO` (el guardia) | lista de `ACCIONES` |
|---|---|---|
| «Voy a transferir **su llamada** a un asesor humano» | sí | sí |
| «Voy a transferir**le** a un asesor humano» | sí, desde el 28/09 | **no** |
| «**Permítame** transferirle a un asesor humano» | **no** | **no** |
| «Le transferir**é** a un asesor humano enseguida» | **no** | **no** |

Las dos últimas **no las ve nadie**: ni el guardia las cumple ni el recuento
las cuenta. O sea que los ejes que el arreglo del 28/09 dejó nombrados como
pendientes no son solo un hueco del guardia, son un hueco del detector entero,
y el recuento de «dijo lo que no le consta» viene quedándose corto en ellos.

**No se arregla todavía, y el motivo es del método:** tocar
`app/agent/fundamento.py` cambia la huella del agente, y las tres corridas de
`c82c25ad` están comprometidas y sin correr. Arreglarlo ahora obligaría a
volver a medir desde cero. Va inmediatamente después.

## Lo que queda abierto

1. ~~**El cuarto hueco del cepo literal llegará.**~~ **LLEGÓ AL DÍA SIGUIENTE,
   2026-09-29, y por el eje que este documento había dejado nombrado.** En la
   tercera corrida de la huella `acf3cbc7` el agente dijo *«Por favor,
   **permítame transferirle** a un asesor humano»*: `escaladas_forzadas: []`,
   guardia mudo, caso `sin_clasificar`. El comentario de `fundamento.py`, escrito
   el 28/09, listaba como ejes sin cubrir «el futuro, **el imperativo de
   cortesía** y el subjuntivo».

   **Y no se ha parcheado, a propósito.** Es una decisión, no un olvido: van tres
   parches a la misma expresión en tres días y el cuarto no arreglaría el
   problema, lo aplazaría. El arreglo de verdad sigue siendo que la intención de
   transferir **no se busque en el texto** —que el bucle la sepa por otra vía— y
   no está diseñado.

   Lo que este hueco aporta por no taparse es lo que un parche habría borrado:
   **la debilidad del cepo literal dejó de ser una advertencia y pasó a ser un
   dato con fecha.** Estaba escrita antes de ocurrir, ocurrió a la corrida
   siguiente, y ocurrió por el eje previsto. Eso mide el enfoque; otra
   alternativa en el regex solo habría medido esa frase.
2. **Nadie comprueba que las dos vías sigan de acuerdo**, ni que la cuarta
   columna de `ACCIONES` siga describiendo las herramientas que existen de
   verdad. Es el mismo agujero que el ADR 0007 encontró en la lista blanca de
   adelantables: **un olvido que no da error, solo deja de proteger**. Si
   mañana apareciera una herramienta que bloquea una tarjeta, la entrada
   `("bloquear", …, None)` seguiría diciendo que esa promesa no se puede
   cumplir, y el guardia seguiría sin cumplirla, en silencio.
3. **Solo una acción se puede hacer verdad.** El día que exista una herramienta
   que bloquee una tarjeta, hay que volver aquí: la decisión está escrita para
   extenderse, pero extenderla sin volver a medir la salvaguarda del degenerado
   sería regalar la métrica.
4. **No se ha medido con el prompt del 28/09.** El guardia se midió con la
   huella `7a0202aa`; el prompt que vuelve a decir por qué se pide el nombre es
   posterior. Las tres corridas de `c82c25ad` son las que dirán si el punto se
   sostiene.
5. **El guardia no distingue una promesa abandonada de una aplazada.** Hoy da
   igual porque el turno termina ahí, pero un bucle multipaso más largo lo
   haría importar.

## Lo que queda aprendido

1. **Hay promesas que se pueden hacer verdad y promesas que solo se pueden
   prohibir.** La línea la traza qué herramienta existe, y saber de qué lado
   cae cada promesa es la decisión; el código es la consecuencia.
2. **Un detector que pasa de contar a actuar cambia el precio de sus errores.**
   El día que cruza esa línea hay que revisar sus falsos positivos enteros, no
   esperar a que uno cueste algo.
3. **Un agente puede sonar impecable y no haber hecho nada.** Por eso las
   llamadas a herramientas se cuentan aparte de lo que dice, y por eso la
   métrica 3 dejó de ser «no está claro que aporte mucho».
4. **Ejecutar una acción que el modelo no pidió tiene que ser auditable o no
   vale.** Arreglar los fallos del modelo en silencio no hace el sistema más
   fiable, lo hace más difícil de depurar.
5. **La garantía que vive solo en el prompt se desobedece.** Es la misma
   lección de la fuga de datos y del `_que_hacer` del resultado, ahora en una
   tercera forma: lo que el código ejecuta no depende de que el modelo obedezca.
