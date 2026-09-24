-- El expediente de una llamada.
--
-- Tres tablas y ninguna más, porque el expediente tiene que poder leerlo una
-- persona que audita, no solo un programa. La pregunta a la que responde es
-- siempre la misma: "el agente dijo esto, ¿de dónde lo sacó?". Por eso lo que
-- devolvió cada herramienta se guarda entero y tal cual, y no un resumen:
-- un resumen es una interpretación, y la interpretación es justo lo que se
-- está auditando.

CREATE TABLE IF NOT EXISTS llamada (
    id              UUID PRIMARY KEY,
    abierta_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    cerrada_en      TIMESTAMPTZ,
    -- Por qué terminó: "colgo", "escalada", "error". Nulo mientras sigue viva.
    motivo_cierre   TEXT,
    turnos          INTEGER     NOT NULL DEFAULT 0,
    tokens_entrada  INTEGER     NOT NULL DEFAULT 0,
    tokens_salida   INTEGER     NOT NULL DEFAULT 0,
    peticiones      INTEGER     NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turno (
    id              BIGSERIAL PRIMARY KEY,
    llamada_id      UUID        NOT NULL REFERENCES llamada(id) ON DELETE CASCADE,
    orden           INTEGER     NOT NULL,
    en              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Las dos mitades de la conversación, literales.
    oido            TEXT        NOT NULL DEFAULT '',
    contestado      TEXT        NOT NULL DEFAULT '',
    puente          TEXT        NOT NULL DEFAULT '',

    -- Lo que el voz a texto sabía de su propia transcripción (ADR 0008). Se
    -- guarda aunque hoy no decida nada: el día que haya varias voces y varias
    -- salas, el umbral se fijará con esto y no con siete casos.
    confianza       JSONB,

    -- Lo que el detector determinista encontró sin fundamento en lo que el
    -- agente dijo: números, acciones y procedimientos. Vacío es la respuesta
    -- buena, y por eso se guarda también vacío: "no se revisó" y "se revisó y
    -- estaba limpio" no son lo mismo y no pueden parecerlo.
    sin_fundamento  JSONB,

    ms_asr          INTEGER,
    ms_total        INTEGER,
    ms_primer_audio INTEGER,
    ms_primer_dato  INTEGER,

    agotado         BOOLEAN     NOT NULL DEFAULT FALSE,
    silencio        INTEGER     NOT NULL DEFAULT 0,
    tokens_entrada  INTEGER     NOT NULL DEFAULT 0,
    tokens_salida   INTEGER     NOT NULL DEFAULT 0,
    peticiones      INTEGER     NOT NULL DEFAULT 0,

    -- La clave de idempotencia del turno (ADR 0007). Va aquí porque es la que
    -- permite explicar, tres meses después, por qué un reintento no abrió un
    -- segundo ticket.
    clave           TEXT,

    UNIQUE (llamada_id, orden)
);

CREATE TABLE IF NOT EXISTS paso (
    id              BIGSERIAL PRIMARY KEY,
    turno_id        BIGINT      NOT NULL REFERENCES turno(id) ON DELETE CASCADE,
    orden           INTEGER     NOT NULL,

    -- "modelo" | "herramienta" | "limite" | "silencio"
    tipo            TEXT        NOT NULL,
    detalle         TEXT        NOT NULL DEFAULT '',
    ms              INTEGER,

    -- Con qué se llamó y qué contestó, enteros. Esta columna y la siguiente
    -- son el expediente de verdad: sin ellas queda un registro de que algo
    -- pasó, no de qué pasó.
    argumentos      JSONB,
    resultado       JSONB,
    error           TEXT,

    tokens_entrada  INTEGER     NOT NULL DEFAULT 0,
    tokens_salida   INTEGER     NOT NULL DEFAULT 0,

    UNIQUE (turno_id, orden)
);

-- Las dos preguntas que se le hacen de verdad a un expediente: "tráeme esta
-- llamada entera" y "enséñame las llamadas de este rato".
CREATE INDEX IF NOT EXISTS turno_por_llamada ON turno (llamada_id, orden);
CREATE INDEX IF NOT EXISTS paso_por_turno ON paso (turno_id, orden);
CREATE INDEX IF NOT EXISTS llamada_por_fecha ON llamada (abierta_en DESC);
