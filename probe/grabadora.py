r"""Grabadora mínima con botones, para las muestras de voz de la sonda.

Existe porque la grabación por ventana fija no funcionó: el script daba diez
segundos y se acababa antes de que la frase estuviera dicha, y no había forma
de ver si el micrófono estaba captando algo hasta abrir el fichero después.

Lo que arregla, y por eso tiene lo que tiene:

  · **Tú decides cuándo para.** Nada de ventana fija.
  · **Barra de nivel en vivo.** Si el micrófono no capta, se ve antes de leer
    la frase entera, no después.
  · **Selector de micrófono.** Esta máquina expone varios dispositivos de
    entrada y el que Windows pone por defecto no es necesariamente el que oye.
  · **Reproducir antes de guardar.** La muestra es la verdad contra la que se
    va a medir la transcripción; vale la pena oírla.

Tkinter a propósito: viene con Python y no añade una dependencia a un proyecto
que todavía no ha decidido nada.

Uso:  .\.venv\Scripts\python.exe probe\grabadora.py
"""

from __future__ import annotations

import json
import queue
import sys
import tkinter as tk
import wave
from pathlib import Path
from tkinter import ttk

import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).parent))
from common import ARTEFACTOS  # noqa: E402
from record_sample import FRECUENCIA, GUIONES  # noqa: E402

# Por debajo de esto la grabación no sirve y hay que repetirla. El umbral no es
# caprichoso: con un pico de 3.300 sobre 32.767, medido en el primer intento de
# este proyecto, el habla quedó en el 2,7% de las muestras y no había con qué
# medir nada.
PICO_MINIMO = 4000
# El resto del criterio —cuánta habla hay y cuánto silencio queda al final—
# no vive aquí: lo decide `probe_vad.por_que_no_sirve`, que es el mismo juez
# que aceptará o rechazará la grabación cuando se mida. Tener dos criterios
# para la misma pregunta es la forma segura de perder una tarde.


class Grabadora(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Grabadora de muestras")
        self.geometry("820x740")

        self.cola: queue.Queue[np.ndarray] = queue.Queue()
        self.trozos: list[np.ndarray] = []
        self.flujo: sd.InputStream | None = None
        self.grabado: np.ndarray | None = None
        self.nivel = 0.0

        self._construir()
        self._pintar_pendientes()
        self._refrescar_medidor()

    # ---------------------------------------------------------------- interfaz

    def _construir(self) -> None:
        marco = ttk.Frame(self, padding=12)
        marco.pack(fill="both", expand=True)

        # Micrófono
        ttk.Label(marco, text="Micrófono").pack(anchor="w")
        self.dispositivos = [
            (i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]
        self.combo_dispositivo = ttk.Combobox(
            marco, state="readonly", width=70,
            values=[f"[{i}] {n}" for i, n in self.dispositivos])
        por_defecto = sd.default.device[0]
        indice = next((k for k, (i, _) in enumerate(self.dispositivos) if i == por_defecto), 0)
        self.combo_dispositivo.current(indice)
        self.combo_dispositivo.pack(anchor="w", pady=(0, 10))

        # Qué se graba
        ttk.Label(marco, text="Muestra").pack(anchor="w")
        self.combo_frase = ttk.Combobox(marco, state="readonly", width=40,
                                        values=list(GUIONES))
        self.combo_frase.current(0)
        self.combo_frase.bind("<<ComboboxSelected>>", lambda _e: self._mostrar_frase())
        self.combo_frase.pack(anchor="w")

        self.pendientes = tk.StringVar(value="")
        ttk.Label(marco, textvariable=self.pendientes, foreground="#444",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

        self.texto = tk.Text(marco, height=13, wrap="word", font=("Segoe UI", 12),
                             relief="solid", borderwidth=1, padx=10, pady=10)
        self.texto.pack(fill="x", pady=8)
        self._mostrar_frase()

        # Medidor de nivel
        ttk.Label(marco, text="Nivel de entrada").pack(anchor="w")
        self.lienzo = tk.Canvas(marco, height=28, bg="#e8e8e8", highlightthickness=0)
        self.lienzo.pack(fill="x", pady=(0, 2))
        self.barra = self.lienzo.create_rectangle(0, 0, 0, 28, fill="#3a7d44", width=0)
        # La marca del umbral: si al hablar la barra no la pasa, la muestra no vale.
        self.marca = self.lienzo.create_line(0, 0, 0, 28, fill="#b03030", width=2)
        ttk.Label(marco, text="la raya roja es el mínimo: al hablar, la barra tiene "
                              "que pasarla con holgura",
                  foreground="#666").pack(anchor="w", pady=(0, 10))

        # Botones
        botones = ttk.Frame(marco)
        botones.pack(fill="x", pady=6)
        self.boton_grabar = ttk.Button(botones, text="Grabar", command=self.grabar)
        self.boton_parar = ttk.Button(botones, text="Parar", command=self.parar,
                                      state="disabled")
        self.boton_oir = ttk.Button(botones, text="Reproducir", command=self.reproducir,
                                    state="disabled")
        self.boton_guardar = ttk.Button(botones, text="Guardar", command=self.guardar,
                                        state="disabled")
        for b in (self.boton_grabar, self.boton_parar, self.boton_oir, self.boton_guardar):
            b.pack(side="left", padx=(0, 8), ipadx=14, ipady=6)

        self.estado = tk.StringVar(value="Elige el micrófono, dale a Grabar y lee la frase.")
        ttk.Label(marco, textvariable=self.estado, wraplength=720,
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 0))

        self.veredicto = tk.StringVar(value="")
        self.etiqueta_veredicto = ttk.Label(marco, textvariable=self.veredicto,
                                            wraplength=720, font=("Segoe UI", 10, "bold"))
        self.etiqueta_veredicto.pack(anchor="w", pady=(6, 0))

        ttk.Label(marco, foreground="#666", wraplength=720,
                  text="Las grabadas se guardan en artifacts/ junto a su transcripción "
                       "verdadera. El audio no se sube al repositorio.").pack(
            anchor="w", side="bottom")

    def _mostrar_frase(self) -> None:
        guion = GUIONES[self.combo_frase.get()]
        self.texto.delete("1.0", "end")
        if guion["tipo"] == "lectura":
            # Las lecturas son una frase suelta y necesitan que se diga qué
            # hacer con ella. Los diálogos ya traen su propio encabezado, y
            # añadirle otro encima solo da más texto que mirar, que es
            # justamente lo que aquí hay que evitar.
            self.texto.insert("1.0", "LEE ESTO EN VOZ ALTA:\n\n" + guion["texto"])
        else:
            self.texto.insert("1.0", guion["texto"])

    def _refrescar_medidor(self) -> None:
        ancho = self.lienzo.winfo_width() or 1
        # Escala de raíz cuadrada: la lineal deja el habla normal pegada al
        # borde izquierdo y no se ve nada.
        proporcion = min(1.0, (self.nivel / 32767.0) ** 0.5)
        self.lienzo.coords(self.barra, 0, 0, ancho * proporcion, 28)
        color = "#3a7d44" if self.nivel >= PICO_MINIMO else "#c08a2e"
        if self.nivel > 30000:
            color = "#b03030"  # saturando
        self.lienzo.itemconfig(self.barra, fill=color)
        x_marca = ancho * min(1.0, (PICO_MINIMO / 32767.0) ** 0.5)
        self.lienzo.coords(self.marca, x_marca, 0, x_marca, 28)
        self.nivel *= 0.6  # caída suave para que el pico se vea y baje
        self.after(50, self._refrescar_medidor)

    # ----------------------------------------------------------------- audio

    def _dispositivo(self) -> int:
        return self.dispositivos[self.combo_dispositivo.current()][0]

    def _callback(self, datos, _cuadros, _tiempo, estado) -> None:
        if estado:
            pass  # desbordes de buffer: no interrumpen la grabación
        copia = datos.copy().reshape(-1)
        self.trozos.append(copia)
        pico = float(np.abs(copia).max())
        self.nivel = max(self.nivel, pico)

    def grabar(self) -> None:
        self.trozos.clear()
        self.grabado = None
        self.veredicto.set("")
        try:
            self.flujo = sd.InputStream(samplerate=FRECUENCIA, channels=1,
                                        dtype="int16", device=self._dispositivo(),
                                        callback=self._callback, blocksize=1024)
            self.flujo.start()
        except Exception as exc:  # noqa: BLE001
            self.estado.set(f"No se pudo abrir el micrófono: {exc}")
            return
        self.estado.set("GRABANDO. Lee la frase y, al terminar, ESPERA DOS SEGUNDOS "
                        "EN SILENCIO antes de darle a Parar.")
        self.boton_grabar.config(state="disabled")
        self.boton_parar.config(state="normal")
        self.boton_oir.config(state="disabled")
        self.boton_guardar.config(state="disabled")

    def parar(self) -> None:
        if self.flujo is not None:
            self.flujo.stop()
            self.flujo.close()
            self.flujo = None
        if not self.trozos:
            self.estado.set("No llegó ni una muestra. Prueba con otro micrófono.")
            self.boton_grabar.config(state="normal")
            self.boton_parar.config(state="disabled")
            return

        self.grabado = np.concatenate(self.trozos)
        self.boton_grabar.config(state="normal")
        self.boton_parar.config(state="disabled")
        self.boton_oir.config(state="normal")
        self.boton_guardar.config(state="normal")
        self._juzgar()

    def _juzgar(self) -> None:
        """Dice si la muestra sirve, **con la misma regla que la sonda**.

        El primer intento juzgaba por densidad de muestras fuertes, y era un
        mal criterio: la onda de la voz cruza el cero constantemente, así que
        una frase bien dicha se queda igualmente en torno al 15%. Daba avisos
        de "hay mucho silencio" sobre grabaciones correctas.

        Ahora pregunta al mismo detector que usará `probe_vad.py`. Si la
        grabadora dice que sirve, la sonda la acepta; si dice que no, explica
        el mismo motivo. Dos jueces distintos para la misma pregunta es una
        forma segura de perder una tarde.
        """
        from probe_vad import por_que_no_sirve, segmentos_con

        datos = self.grabado
        duracion = len(datos) / FRECUENCIA
        pico = int(np.abs(datos).max())

        flotante = datos.astype(np.float32) / 32768.0
        trozos, _ = segmentos_con(flotante, 300)
        habla = sum(t["end"] - t["start"] for t in trozos) / FRECUENCIA
        cola_s = duracion - (trozos[-1]["end"] / FRECUENCIA) if trozos else duracion

        self.estado.set(
            f"{duracion:.1f} s grabados. Pico {pico}/32767. "
            f"Habla {habla:.1f} s ({habla / duracion * 100:.0f}% del clip). "
            f"Silencio final: {cola_s:.1f} s.")

        if pico < PICO_MINIMO:
            self.veredicto.set("DEMASIADO BAJO. Acércate al micrófono o cambia de "
                               "dispositivo, y repite: así el voz a texto no mide nada.")
            self.etiqueta_veredicto.config(foreground="#b03030")
            return
        if pico > 32000:
            self.veredicto.set("SATURANDO. Sepárate un poco: lo que se recorta arriba "
                               "no se recupera.")
            self.etiqueta_veredicto.config(foreground="#b03030")
            return

        motivo = por_que_no_sirve(flotante, duracion)
        if motivo:
            self.veredicto.set(f"NO SIRVE: {motivo}. Repítela.")
            self.etiqueta_veredicto.config(foreground="#b03030")
        else:
            self.veredicto.set("Sirve. Escúchala si quieres y guárdala.")
            self.etiqueta_veredicto.config(foreground="#3a7d44")

    def reproducir(self) -> None:
        if self.grabado is None:
            return
        try:
            sd.play(self.grabado, FRECUENCIA)
        except Exception as exc:  # noqa: BLE001
            self.estado.set(f"No se pudo reproducir: {exc}")

    def guardar(self) -> None:
        if self.grabado is None:
            return
        nombre = self.combo_frase.get()
        ARTEFACTOS.mkdir(exist_ok=True)
        destino = ARTEFACTOS / f"muestra-{nombre}.wav"

        with wave.open(str(destino), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(FRECUENCIA)
            w.writeframes(self.grabado.tobytes())

        destino.with_suffix(".json").write_text(
            json.dumps({
                "fichero": destino.name,
                "frase": nombre,
                "tipo": GUIONES[nombre]["tipo"],
                "segundos": round(len(self.grabado) / FRECUENCIA, 2),
                "frecuencia_hz": FRECUENCIA,
                "pico": int(np.abs(self.grabado).max()),
                "dispositivo": self.combo_dispositivo.get(),
                # Solo las lecturas llevan verdad escrita. En una espontánea se
                # guarda la pregunta, que no es lo que se dijo: usarla como
                # referencia para la tasa de error daría un número sin sentido.
                ("transcripcion_verdadera" if GUIONES[nombre]["tipo"] == "lectura"
                 else "pregunta"): GUIONES[nombre]["texto"],
            }, indent=2, ensure_ascii=False), encoding="utf-8")

        self.boton_guardar.config(state="disabled")

        # Pasar solo a la frase siguiente. Sin esto, quien graba las tres
        # seguidas sin tocar el desplegable las guarda las tres encima de la
        # misma, y no se entera hasta que mira los ficheros. Pasó.
        siguiente = (self.combo_frase.current() + 1) % len(GUIONES)
        self.combo_frase.current(siguiente)
        self._mostrar_frase()
        self._pintar_pendientes()
        self.estado.set(f"Guardada en artifacts/{destino.name}. "
                        f"Ya está puesta la siguiente frase: {self.combo_frase.get()}.")

    def _pintar_pendientes(self) -> None:
        """Dice cuáles hay grabadas ya Y cuáles sirven.

        Se mira el pico del fichero, no si el fichero existe: una toma mala
        ocupa lo mismo que una buena y marcarla como hecha es justo el error
        que hay que evitar.
        """
        estados = []
        for nombre in GUIONES:
            ruta = ARTEFACTOS / f"muestra-{nombre}.wav"
            if not ruta.exists():
                estados.append(f"· {nombre}")
                continue
            try:
                from probe_vad import por_que_no_sirve
                with wave.open(str(ruta), "rb") as w:
                    datos = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                    duracion = w.getnframes() / w.getframerate()
                flotante = datos.astype(np.float32) / 32768.0
                sirve = (int(np.abs(datos).max()) >= PICO_MINIMO
                         and por_que_no_sirve(flotante, duracion) is None)
            except (OSError, wave.Error, ValueError):
                sirve = False
            estados.append(f"{'✓' if sirve else '✗'} {nombre}")
        self.pendientes.set("Muestras:   " + "    ".join(estados)
                            + "     (✗ = grabada pero no sirve, repítela)")


if __name__ == "__main__":
    Grabadora().mainloop()
