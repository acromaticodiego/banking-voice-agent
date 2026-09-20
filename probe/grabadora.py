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
from record_sample import FRASES, FRECUENCIA  # noqa: E402

# Por debajo de esto la grabación no sirve y hay que repetirla. El umbral no es
# caprichoso: con un pico de 3.300 sobre 32.767, medido en el primer intento de
# este proyecto, el habla quedó en el 2,7% de las muestras y no había con qué
# medir nada.
PICO_MINIMO = 4000
PROPORCION_MINIMA = 0.15  # fracción de muestras con señal que se espera al hablar


class Grabadora(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Grabadora de muestras")
        self.geometry("760x560")

        self.cola: queue.Queue[np.ndarray] = queue.Queue()
        self.trozos: list[np.ndarray] = []
        self.flujo: sd.InputStream | None = None
        self.grabado: np.ndarray | None = None
        self.nivel = 0.0

        self._construir()
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

        # Frase
        ttk.Label(marco, text="Frase").pack(anchor="w")
        self.combo_frase = ttk.Combobox(marco, state="readonly", width=30,
                                        values=list(FRASES))
        self.combo_frase.current(0)
        self.combo_frase.bind("<<ComboboxSelected>>", lambda _e: self._mostrar_frase())
        self.combo_frase.pack(anchor="w")

        self.texto = tk.Text(marco, height=5, wrap="word", font=("Segoe UI", 13),
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
        self.texto.delete("1.0", "end")
        self.texto.insert("1.0", FRASES[self.combo_frase.get()])

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
        self.estado.set("GRABANDO. Lee la frase y dale a Parar cuando termines.")
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
        """Dice si la muestra sirve, con los mismos números del diagnóstico."""
        datos = self.grabado
        duracion = len(datos) / FRECUENCIA
        pico = int(np.abs(datos).max())
        con_señal = float((np.abs(datos) > 500).mean())
        self.estado.set(
            f"{duracion:.1f} s grabados. Pico {pico}/32767. "
            f"Habla en el {con_señal * 100:.0f}% de las muestras.")

        if pico < PICO_MINIMO:
            self.veredicto.set("DEMASIADO BAJO. Acércate al micrófono o cambia de "
                               "dispositivo, y repite: así el voz a texto no mide nada.")
            self.etiqueta_veredicto.config(foreground="#b03030")
        elif con_señal < PROPORCION_MINIMA:
            self.veredicto.set("Hay mucho silencio para lo que dura. ¿Paraste tarde, o "
                               "te dejaste media frase? Repítela si no la dijiste entera.")
            self.etiqueta_veredicto.config(foreground="#c08a2e")
        elif pico > 32000:
            self.veredicto.set("SATURANDO. Sepárate un poco: lo que se recorta arriba "
                               "no se recupera.")
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
                "segundos": round(len(self.grabado) / FRECUENCIA, 2),
                "frecuencia_hz": FRECUENCIA,
                "pico": int(np.abs(self.grabado).max()),
                "dispositivo": self.combo_dispositivo.get(),
                "transcripcion_verdadera": FRASES[nombre],
            }, indent=2, ensure_ascii=False), encoding="utf-8")

        self.estado.set(f"Guardada en artifacts/{destino.name}. "
                        f"Elige otra frase en el desplegable y repite.")
        self.boton_guardar.config(state="disabled")


if __name__ == "__main__":
    Grabadora().mainloop()
