r"""El bucle del agente: decidir, llamar herramientas, recuperarse, responder.

Lo que este bucle tiene y un chatbot con voz no:

  · **Trabaja contra un reloj.** Cada turno lleva un presupuesto. Si se agota
    a mitad, el agente no se queda pensando: dice algo y sigue.
  · **No afirma nada que no venga de una herramienta.** La regla está en el
    prompt, pero el prompt no basta: el expediente guarda qué devolvió cada
    herramienta, así que lo afirmado se puede contrastar después. Una regla
    que no se puede comprobar no es una regla, es un deseo.
  · **Cuando una herramienta falla, no inventa ni cuelga.** Se lo dice al
    modelo como resultado de la herramienta, y el modelo decide: reintentar,
    preguntar otra cosa, o escalar a un humano. Escalar es admitir lo que no
    se sabe, y es una salida legítima, no un fracaso.
  · **Idempotencia.** Cada turno lleva una clave. Si se reintenta, las
    acciones con efecto no se ejecutan dos veces.

Deja un `rastro`: cada paso con su instante, la herramienta llamada, los
argumentos, lo que devolvió y cuánto tardó. Eso es el expediente.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

import httpx

SISTEMA = (
    "Agente telefónico de un banco colombiano. Frases cortas: esto se habla. "
    "No afirmes ningún dato que no venga de una herramienta. Si dudas de lo que "
    "oíste, pide que lo repitan. Antes de dar información de una cuenta, "
    "verifica la identidad con el documento. Si una herramienta falla, no "
    "inventes: escala a un humano. "
    "NUNCA digas el nombre del titular ni ningún otro dato de la cuenta antes "
    "de haber verificado la identidad: pregúntalo y compáralo en silencio. "
    "Quien llama tiene que demostrar quién es, no confirmar lo que tú ya le "
    "has dicho."
)

HERRAMIENTAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_identidad",
            "description": "Busca un cliente por documento.",
            "parameters": {
                "type": "object",
                "properties": {"documento": {"type": "string"}},
                "required": ["documento"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estado_tarjeta",
            "description": "Estado de la tarjeta de un cliente verificado.",
            "parameters": {
                "type": "object",
                "properties": {"id_cliente": {"type": "string"}},
                "required": ["id_cliente"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalar_a_humano",
            "description": "Pasa la llamada a un asesor humano.",
            "parameters": {
                "type": "object",
                "properties": {"motivo": {"type": "string"}},
                "required": ["motivo"],
            },
        },
    },
]

# Acciones con efecto: llevan clave de idempotencia. Consultar no la necesita
# —preguntar dos veces no rompe nada— pero abrir un ticket sí.
CON_EFECTO = {"escalar_a_humano"}


@dataclass
class Paso:
    """Una cosa que pasó en el turno, con su instante y su duración."""
    tipo: str            # "modelo" | "herramienta" | "limite"
    detalle: str
    ms: float
    argumentos: dict | None = None
    resultado: dict | None = None
    error: str | None = None


@dataclass
class Turno:
    texto: str = ""
    rastro: list[Paso] = field(default_factory=list)
    ms_primer_hablable: float | None = None
    ms_total: float = 0.0
    agotado: bool = False
    clave: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def resumen(self) -> str:
        llamadas = [p for p in self.rastro if p.tipo == "herramienta"]
        return (f"{len(llamadas)} llamada(s) a herramienta, "
                f"{self.ms_total:.0f} ms en total"
                + (", PRESUPUESTO AGOTADO" if self.agotado else ""))


class Agente:
    def __init__(self, cliente_groq, modelo: str, base_herramientas: str,
                 presupuesto_ms: float = 3000.0) -> None:
        self.groq = cliente_groq
        self.modelo = modelo
        self.base = base_herramientas.rstrip("/")
        self.presupuesto_ms = presupuesto_ms
        self.historia: list[dict] = [{"role": "system", "content": SISTEMA}]

    # ------------------------------------------------------------ herramientas

    def _ejecutar(self, nombre: str, argumentos: dict, clave: str) -> tuple[dict, float]:
        cuerpo = dict(argumentos)
        if nombre in CON_EFECTO:
            cuerpo["clave_idempotencia"] = clave
        arranque = time.perf_counter()
        try:
            with httpx.Client(timeout=5) as c:
                r = c.post(f"{self.base}/{nombre}", json=cuerpo)
            ms = (time.perf_counter() - arranque) * 1000
            if r.status_code >= 400:
                # Al modelo se le dice que falló, no se le oculta. Es él quien
                # decide qué hacer, y para eso necesita saberlo.
                return {"error": f"la herramienta respondió {r.status_code}",
                        "reintentable": r.status_code >= 500}, ms
            return r.json(), ms
        except Exception as exc:  # noqa: BLE001
            ms = (time.perf_counter() - arranque) * 1000
            return {"error": f"no se pudo llamar a la herramienta: "
                             f"{type(exc).__name__}", "reintentable": True}, ms

    # ------------------------------------------------------------------ turno

    def turno(self, dicho: str, max_pasos: int = 4) -> Turno:
        """Un turno completo: lo que dijo la persona, lo que contesta el agente."""
        turno = Turno()
        arranque = time.perf_counter()
        self.historia.append({"role": "user", "content": dicho})

        for _ in range(max_pasos):
            transcurrido = (time.perf_counter() - arranque) * 1000
            if transcurrido > self.presupuesto_ms:
                # El reloj manda. Decir algo tarde es peor que decir poco a
                # tiempo, y callarse es lo peor de todo.
                turno.agotado = True
                turno.rastro.append(Paso("limite", "presupuesto del turno agotado",
                                         transcurrido))
                turno.texto = ("Permítame un momento, por favor, sigo "
                               "verificando la información.")
                break

            t0 = time.perf_counter()
            respuesta = self.groq.chat.completions.create(
                model=self.modelo,
                messages=self.historia,
                tools=HERRAMIENTAS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=400,
                reasoning_effort="low",
            )
            ms_modelo = (time.perf_counter() - t0) * 1000
            mensaje = respuesta.choices[0].message
            turno.rastro.append(Paso("modelo",
                                     "decide llamar herramienta" if mensaje.tool_calls
                                     else "contesta",
                                     ms_modelo))
            if turno.ms_primer_hablable is None:
                turno.ms_primer_hablable = (time.perf_counter() - arranque) * 1000

            # `tool_calls` se omite si no hay ninguna. Poner null ahí lo
            # rechaza la API con un 400, y no se veía en pruebas de un solo
            # turno porque ese mensaje nunca se reenviaba. Lo destapó la
            # primera conversación de dos turnos.
            anotacion: dict = {"role": "assistant", "content": mensaje.content or ""}
            if mensaje.tool_calls:
                anotacion["tool_calls"] = [
                    {"id": t.id, "type": "function",
                     "function": {"name": t.function.name,
                                  "arguments": t.function.arguments}}
                    for t in mensaje.tool_calls
                ]
            self.historia.append(anotacion)

            if not mensaje.tool_calls:
                turno.texto = (mensaje.content or "").strip()
                break

            for llamada in mensaje.tool_calls:
                nombre = llamada.function.name
                try:
                    argumentos = json.loads(llamada.function.arguments or "{}")
                except json.JSONDecodeError:
                    argumentos = {}
                resultado, ms = self._ejecutar(nombre, argumentos, turno.clave)
                turno.rastro.append(Paso("herramienta", nombre, ms,
                                         argumentos=argumentos, resultado=resultado,
                                         error=resultado.get("error")))
                self.historia.append({
                    "role": "tool",
                    "tool_call_id": llamada.id,
                    "content": json.dumps(resultado, ensure_ascii=False),
                })

        if not turno.texto:
            turno.texto = ("Disculpe, no pude completar la consulta. "
                           "Le paso con un asesor.")
        self.historia.append({"role": "assistant", "content": turno.texto})
        turno.ms_total = (time.perf_counter() - arranque) * 1000
        return turno
