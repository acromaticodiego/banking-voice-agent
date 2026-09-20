# La sonda del día 1

No construye nada. Mide si el presupuesto de 800 ms por turno es alcanzable en
esta máquina, para saberlo hoy y no dentro de tres semanas.

Qué se mide exactamente, y por qué esas fronteras y no otras: `docs/adr/0001`.

## Preparar

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-probe.txt
python -m piper.download_voices --download-dir voices es_MX-claude-high es_ES-davefx-medium
Copy-Item .env.example .env   # y pega ahí la clave de Groq
```

## Ejecutar, en este orden

```powershell
.\.venv\Scripts\python.exe probe\check_entorno.py         # ¿GPU? ¿micrófono?
.\.venv\Scripts\python.exe probe\record_sample.py         # 10 s de voz, lees la frase en pantalla
.\.venv\Scripts\python.exe probe\probe_whisper_local.py   # voz -> texto
.\.venv\Scripts\python.exe probe\probe_groq.py            # modelo
.\.venv\Scripts\python.exe probe\probe_piper.py           # texto -> voz
.\.venv\Scripts\python.exe probe\presupuesto.py           # el veredicto
```

`presupuesto.py` **se niega a dar un veredicto** si falta alguna etapa por
medir, y sale con código 1. Es a propósito: un total al que le falta una etapa
es peor que no tener total, porque parece un total.

## Lo que queda fuera de esta sonda

- **Deepgram.** A propósito. Nova-3 y Aura-2 se miden en una segunda pasada,
  cuando la sonda ya esté bien, para no gastar crédito afinando el método.
- **El detector de fin de habla.** Todavía no existe; entra en el presupuesto
  como una suposición declarada que se pasa por parámetro.
- **La red.** Todo esto es local. El número que sale es un límite inferior.

## Dónde quedan los resultados

En `artifacts/*.json`, con la fecha, la máquina, el tamaño de muestra, las
muestras crudas y la frase exacta de qué instante a qué instante se cronometró.
Esos JSON sí se versionan. El audio no.
