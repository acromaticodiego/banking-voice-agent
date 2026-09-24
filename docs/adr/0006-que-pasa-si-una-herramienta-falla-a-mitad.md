# ADR 0006 — Qué pasa si una herramienta falla a mitad de la llamada

- **Fecha:** 2026-09-24 (la decisión se implementó antes; esto la escribe)
- **Estado:** aceptada
- **Contexto:** el agente no puede hacer su trabajo sin las herramientas, y las
  herramientas son HTTP contra un core bancario. Van a fallar.

## El problema

Un agente de voz que consulta un core bancario tiene tres formas de portarse
mal cuando la consulta se cae, y las tres se han visto en sistemas de verdad:

1. **Inventar.** El modelo tiene contexto suficiente para producir una
   respuesta plausible sin el dato. "Su tarjeta está activa" dicho sin haber
   podido preguntar es la peor salida posible, porque es indistinguible de la
   buena.
2. **Colgarse.** Reintentar en silencio mientras quien llama escucha nada. A
   los dos segundos la gente dice "¿aló?"; a los cinco, cuelga.
3. **Romperse.** Propagar la excepción y cortar la llamada. Técnicamente
   honesto y comercialmente inaceptable.

Y hay un cuarto caso, más sutil, que es el que da nombre a este ADR: la
herramienta no falla al principio, **falla a mitad**. La identidad ya se
verificó, el agente ya sabe con quién habla, ya ha dicho "permítame un
momento"… y entonces se cae la consulta de la tarjeta. Ahí la tentación de
rellenar el hueco es máxima, porque todo lo demás ha ido bien.

## La decisión

**El fallo se le cuenta al modelo como resultado de la herramienta, y decide
él.** No se oculta, no se reintenta por debajo, y no se convierte en excepción.

`app/agent/loop.py`, en `_llamar`:

```python
if r.status_code >= 400:
    return {"error": f"la herramienta respondió {r.status_code}",
            "reintentable": r.status_code >= 500}, ms
```

Dos cosas de esas cuatro líneas son la decisión entera:

- **`error` es un resultado, no una excepción.** Llega al modelo como el
  contenido del mensaje `tool`, igual que llegaría un dato. El bucle sigue
  vivo, le quedan pasos y puede decidir: reintentar, preguntar otra cosa, o
  pasar la llamada a un humano.
- **`reintentable` distingue 5xx de 4xx.** Un 503 es "vuelve a intentarlo"; un
  400 es "lo estás pidiendo mal y volver a pedirlo igual no va a funcionar".
  Sin esa distinción, el modelo reintenta lo que no tiene arreglo y se come el
  presupuesto del turno.

**Escalar a un humano es una salida legítima, no un fracaso.** Está escrito en
el prompt y es la mitad del diseño: un agente que solo sabe resolver es un
agente que, cuando no puede, inventa.

## Lo que hace que esto sea comprobable y no un deseo

**La cabecera `X-Fallar`.** Las herramientas revientan a voluntad, así que el
camino de error no es teórico: se prueba en cada tanda.

- `app/agent/prueba_bucle.py`, escenario 2: la consulta de identidad se cae y
  se comprueba que el agente **no dice ningún dato** y **no se queda callado**.
- El conjunto de evaluación lleva dos casos de esto, y no son el mismo:
  `core-caido-a-mitad` (se cae antes de verificar) y
  `tarjeta-falla-tras-verificar` (se cae después, que es el caso difícil).
  Los dos con `no_debe_decir=["4582", "bloquead"]`, así que si el agente
  rellena el hueco, se ve.

Medido el 2026-09-24 en `prueba_bucle`: la escalada tras el fallo costó 394 ms
y el turno entero 763 ms, con una sola llamada a herramienta. Un fallo sale
**más rápido** que un éxito, lo cual tiene sentido y conviene decirlo: nadie
espera a nadie.

## Lo que se descartó

**Descartado: reintentar dentro de `_llamar`.** Es lo que hace el SDK de Groq
por su cuenta, y este proyecto ya se llevó un susto con eso: una muestra de
80,6 s que parecía latencia del modelo y era el SDK reintentando un 429 por
dentro con el cronómetro corriendo. Un reintento invisible convierte una
medición de latencia en una mentira. Si hay que reintentar, lo decide el
modelo y queda en el rastro.

**Descartado: lanzar una excepción y que la atrape quien llame.** El bucle está
dentro de una llamada telefónica: lo que hay "más arriba" es una persona
esperando. El error tiene que resolverse en el turno.

**Descartado: un mensaje de error bonito para el modelo** ("no he podido
verificar su identidad, inténtelo más tarde"). Suena mejor y es peor: el modelo
lo repite tal cual y quien llama se queda sin saber que el problema es del
banco. El resultado crudo, con el código de estado, le deja decidir.

**Descartado: tratar igual el 4xx y el 5xx.** Ver arriba.

## Lo que queda abierto

1. **El reintento del modelo no tiene tope propio.** Lo limita el presupuesto
   del turno y `max_pasos`, que son topes de otra cosa. Un modelo terco puede
   gastar los cuatro pasos reintentando lo mismo.
2. **Un fallo parcial de varias herramientas** —la identidad va, la tarjeta
   no— se resuelve bien hoy por casualidad: el modelo ve el error y escala.
   No hay nada que garantice que no conteste con la mitad de los datos.
3. **Nada distingue "se cayó" de "tardó demasiado".** `X-Tardar-Ms` existe y el
   presupuesto del turno salta, pero el modelo no se entera de que la
   herramienta sigue viva: solo ve que el turno se acabó.
