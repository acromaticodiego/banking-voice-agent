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
# Silencio que tiene que quedar DESPUÉS de la frase. No es cosmético: la sonda
# del fin de habla mide cuánto tarda en notarse que alguien calló, y para eso
# hace falta que calle dentro de la grabación. Un segundo más que la ventana
# más larga que se barre (1000 ms), para poder probarla entera.
COLA_MINIMA_S = 2.0


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

        # Frase
        ttk.Label(marco, text="Frase").pack(anchor="w")
        self.combo_frase = ttk.Combobox(marco, state="readonly", width=30,
                                        values=list(FRASES))
        self.combo_frase.current(0)
        self.combo_frase.bind("<<ComboboxSelected>>", lambda _e: self._mostrar_frase())
        self.combo_frase.pack(anchor="w")

        self.pendientes = tk.StringVar(value="")
        ttk.Label(marco, textvariable=self.pendientes, foreground="#444",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

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
        """Dice si la muestra sirve, con los mismos números del diagnóstico."""
        datos = self.grabado
        duracion = len(datos) / FRECUENCIA
        pico = int(np.abs(datos).max())
        con_señal = float((np.abs(datos) > 500).mean())

        # Silencio final: sin él, la muestra no sirve para medir el fin de
        # habla, porque no contiene ningún momento en que alguien calle. Es el
        # defecto que invalidó las tres primeras grabaciones de este proyecto.
        fuertes = np.flatnonzero(np.abs(datos) > 500)
        cola_s = (len(datos) - fuertes[-1]) / FRECUENCIA if fuertes.size else 0.0

        self.estado.set(
            f"{duracion:.1f} s grabados. Pico {pico}/32767. "
            f"Habla en el {con_señal * 100:.0f}% de las muestras. "
            f"Silencio final: {cola_s:.1f} s.")

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
        elif cola_s < COLA_MINIMA_S:
            self.veredicto.set(
                f"FALTA SILENCIO AL FINAL: solo {cola_s:.1f} s. Repítela y, al acabar "
                f"la frase, quédate callado {COLA_MINIMA_S:.0f} segundos antes de dar a "
                "Parar. Sin ese silencio no se puede medir cuánto tarda el sistema en "
                "darse cuenta de que has terminado de hablar.")
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

        self.boton_guardar.config(state="disabled")

        # Pasar solo a la frase siguiente. Sin esto, quien graba las tres
        # seguidas sin tocar el desplegable las guarda las tres encima de la
        # misma, y no se entera hasta que mira los ficheros. Pasó.
        siguiente = (self.combo_frase.current() + 1) % len(FRASES)
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
        for nombre in FRASES:
            ruta = ARTEFACTOS / f"muestra-{nombre}.wav"
            if not ruta.exists():
                estados.append(f"· {nombre}")
                continue
            try:
                with wave.open(str(ruta), "rb") as w:
                    datos = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                pico = int(np.abs(datos).max()) if datos.size else 0
            except (OSError, wave.Error):
                pico = 0
            estados.append(f"{'✓' if pico >= PICO_MINIMO else '✗'} {nombre}")
        self.pendientes.set("Muestras:   " + "    ".join(estados)
                            + "     (✗ = grabada pero demasiado baja, repítela)")


if __name__ == "__main__":
    Grabadora().mainloop()
