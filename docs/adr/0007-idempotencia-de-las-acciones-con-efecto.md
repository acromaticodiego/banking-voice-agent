# ADR 0007 — Idempotencia de las acciones con efecto

- **Fecha:** 2026-09-24 (la decisión se implementó antes; esto la escribe)
- **Estado:** aceptada
- **Contexto:** el agente reintenta. La red reintenta. El SDK reintenta. Y una
  de las tres herramientas **hace** algo en vez de solo mirar.

## El problema

Las herramientas del agente no son iguales y tratarlas igual es el error:

- `consultar_identidad` y `estado_tarjeta` **leen**. Preguntar dos veces no
  cambia nada. Como mucho se gasta una consulta.
- `escalar_a_humano` **abre un ticket**. Preguntar dos veces abre dos tickets,
  y un ticket no es una fila en una tabla: es una persona que lo atiende, una
  cola que se descuadra y un cliente al que llaman dos veces para lo mismo.

Y los reintentos no son hipotéticos, son el caso normal:

1. **El modelo reintenta.** `_preguntar_al_modelo` repite una vez cuando el
   proveedor devuelve `tool_use_failed`, y el modelo puede volver a emitir la
   misma llamada a herramienta.
2. **La red reintenta.** Un timeout en el que la petición sí llegó es
   exactamente el caso que duplica: el cliente cree que falló y el servidor ya
   lo hizo.
3. **El modelo insiste solo.** Le quedan pasos en el turno y puede llamar dos
   veces a lo mismo, sin que nada vaya mal.

**Una acción con efecto ejecutada dos veces no es un detalle de
implementación: es un incidente.**

## La decisión

**Cada turno lleva una clave, y las herramientas con efecto la reciben.** Si
llega dos veces la misma clave, la herramienta devuelve lo que ya había hecho
en vez de hacerlo otra vez.

En el bucle (`app/agent/loop.py`):

```python
CON_EFECTO = {"escalar_a_humano"}

clave: str = field(default_factory=lambda: uuid.uuid4().hex[:12])   # en Turno

if nombre in CON_EFECTO:
    cuerpo["clave_idempotencia"] = clave
```

En la herramienta (`app/tools/service.py`):

```python
if clave and clave in TICKETS:
    return {**TICKETS[clave], "repetida": True}
```

Tres decisiones dentro de la decisión, y cada una tiene su motivo:

- **La clave es del TURNO, no de la llamada ni de la conversación.** De la
  llamada sería inútil: dos llamadas distintas dentro del mismo turno son
  justamente el reintento que hay que absorber. De la conversación sería
  peligroso: si alguien pide dos escaladas legítimas en turnos distintos
  —primero por una cosa y luego por otra—, la segunda se comería la primera.
  El turno es la unidad en la que un reintento significa "lo mismo otra vez".
- **Solo las de efecto la llevan.** Poner clave a una consulta es ruido:
  preguntar dos veces por un documento no rompe nada, y encima el adelanto de
  consultas existe precisamente para preguntar antes de que nadie lo pida.
- **`repetida: True` va en la respuesta.** La herramienta no miente diciendo
  que abrió un ticket: dice que devuelve el que ya existía. Eso queda en el
  rastro y, por tanto, en el expediente. Una idempotencia silenciosa es
  correcta y no se puede auditar; esta se puede.

## La regla que se sigue de esto, y que no es obvia

**Ninguna herramienta con efecto se puede adelantar.** El adelanto de consultas
(ADR 0004) dispara una herramienta *antes* de que el modelo la pida, apostando
a que la va a pedir. Con una lectura, perder la apuesta cuesta una consulta.
Con una escalada, perder la apuesta es **abrir un ticket que nadie pidió**.

Por eso `ADELANTABLES = {"consultar_identidad"}` es una lista blanca y no una
negra: lo que se adelanta se declara una por una. Con una lista negra, la
herramienta con efecto que se añada mañana se adelanta por omisión.

## Lo que hace que esto sea comprobable

`app/agent/prueba_bucle.py`, escenario 4: se llama dos veces a
`escalar_a_humano` con la **misma** clave y se comprueba lo que importa, que
son dos cosas y no una:

```python
comprobar("el reintento no abre un segundo ticket",
          uno["ticket"] == dos["ticket"] and despues - antes == 1, ...)
```

- **El mismo identificador de ticket** en las dos respuestas.
- Y el **contador de tickets del servicio** subió exactamente uno. Sin esta
  segunda parte, una implementación que devolviera el mismo id y además
  abriera otro ticket pasaría la prueba.

## Lo que se descartó

**Descartado: no tener idempotencia y confiar en que el modelo no repita.** Es
lo más fácil y lo que hace casi todo el mundo. Funciona hasta el primer
timeout, y entonces falla en el sitio donde más se nota.

**Descartado: deduplicar por el contenido de la petición** (mismo motivo, mismo
cliente). Dos escaladas legítimas por el mismo motivo existen: alguien llama,
se corta, vuelve a llamar. Deduplicar por contenido se traga la segunda.

**Descartado: que el bucle recuerde qué ya llamó y no vuelva a llamarlo.** Es
tentador y es la solución equivocada: la protección tiene que estar en **quien
tiene el efecto**. Si mañana el agente corre en tres procesos detrás de un
balanceador —que es el diseño declarado de la pasarela—, el que reintenta
puede no ser el que llamó la primera vez. La clave viaja con la petición
justamente para eso.

**Descartado: guardar los tickets con caducidad.** Hoy el diccionario `TICKETS`
crece para siempre, y da igual porque es un servicio de mentira en memoria.
Contra un core de verdad, la clave se guarda donde se guarde el ticket y la
caducidad es de ellos.

## Lo que queda abierto

1. **El estado vive en memoria.** `TICKETS` es un diccionario del proceso, así
   que la idempotencia se pierde al reiniciar. Es el punto 8 de lo que falta
   —el expediente en PostgreSQL— y es donde esto deja de ser un gesto y pasa a
   ser una garantía.
2. **Solo hay una herramienta con efecto.** La decisión está diseñada para más
   —la lista blanca, la clave por turno— pero no está probada con dos acciones
   distintas en el mismo turno.
3. ~~Nadie comprueba que una herramienta nueva declare si tiene efecto.~~
   **Cerrado al escribir este ADR.** Era el mismo agujero que ya se tapó en el
   catálogo de evaluación con `fallar_herramienta`: un olvido que no da error,
   solo deja de proteger. Ahora hay una segunda lista, `SIN_EFECTO`, y
   `prueba_bucle` comprueba que las dos cubran exactamente las herramientas
   declaradas, que ninguna esté en las dos, y que ninguna con efecto sea
   adelantable. Va como escenario 0 y no necesita modelo, así que se comprueba
   aunque no haya cuota.

   Escribir un ADR de algo ya implementado sirve para esto: al tener que
   explicar por qué la lista blanca es blanca, se ve que nadie comprobaba que
   estuviera completa.
