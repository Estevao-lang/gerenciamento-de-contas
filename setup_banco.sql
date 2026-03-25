-- ============================================================
-- FinanceFlow — Setup completo do banco PostgreSQL
-- Versão 2 (inclui conta_fixa, data_pagamento, índices)
--
-- Execute no pgAdmin ou Neon SQL Editor
-- ============================================================

-- ============================================================
-- TABELA: usuario
-- ============================================================
CREATE TABLE IF NOT EXISTS usuario (
    id              SERIAL          PRIMARY KEY,
    nome            VARCHAR(100)    NOT NULL,
    email           VARCHAR(100)    NOT NULL UNIQUE,
    senha           VARCHAR(255)    NOT NULL,
    limite_alerta   NUMERIC(12,2)   NOT NULL DEFAULT 1000.00,
    saldo           NUMERIC(12,2)   NOT NULL DEFAULT 0.00,
    criado_em       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TABELA: conta_fixa (deve existir antes de conta por causa da FK)
-- ============================================================
CREATE TABLE IF NOT EXISTS conta_fixa (
    id               SERIAL          PRIMARY KEY,
    usuario_id       INTEGER         NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    descricao        VARCHAR(200)    NOT NULL,
    valor            NUMERIC(12,2)   NOT NULL CHECK (valor > 0),
    categoria        VARCHAR(50)     NOT NULL DEFAULT 'Outros',
    dia_vencimento   INTEGER         NOT NULL CHECK (dia_vencimento BETWEEN 1 AND 28),
    recorrencia      VARCHAR(20)     NOT NULL DEFAULT 'mensal'
                         CHECK (recorrencia IN ('mensal','bimestral','trimestral','semestral','anual')),
    data_inicio      DATE            NOT NULL,
    data_fim         DATE,
    parcelas_total   INTEGER         CHECK (parcelas_total > 0),
    ativa            BOOLEAN         NOT NULL DEFAULT TRUE,
    criado_em        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conta_fixa_usuario  ON conta_fixa(usuario_id);
CREATE INDEX IF NOT EXISTS idx_conta_fixa_ativa     ON conta_fixa(usuario_id, ativa);

-- ============================================================
-- TABELA: conta
-- ============================================================
CREATE TABLE IF NOT EXISTS conta (
    id               SERIAL          PRIMARY KEY,
    usuario_id       INTEGER         NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    conta_fixa_id    INTEGER         REFERENCES conta_fixa(id) ON DELETE SET NULL,
    descricao        VARCHAR(200)    NOT NULL,
    valor            NUMERIC(12,2)   NOT NULL CHECK (valor > 0),
    data_vencimento  DATE            NOT NULL,
    data_pagamento   DATE,                        -- preenchida ao marcar como paga
    paga             BOOLEAN         NOT NULL DEFAULT FALSE,
    categoria        VARCHAR(50)     NOT NULL DEFAULT 'Outros',
    criado_em        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conta_usuario        ON conta(usuario_id);
CREATE INDEX IF NOT EXISTS idx_conta_vencimento     ON conta(data_vencimento);
CREATE INDEX IF NOT EXISTS idx_conta_paga           ON conta(usuario_id, paga);
CREATE INDEX IF NOT EXISTS idx_conta_fixa_ref       ON conta(conta_fixa_id);

-- ============================================================
-- TABELA: lista_compras
-- ============================================================
CREATE TABLE IF NOT EXISTS lista_compras (
    id            SERIAL          PRIMARY KEY,
    usuario_id    INTEGER         NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    titulo        VARCHAR(100)    NOT NULL,
    data_criacao  DATE            NOT NULL DEFAULT CURRENT_DATE,
    finalizada    BOOLEAN         NOT NULL DEFAULT FALSE,
    criado_em     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lista_compras_usuario ON lista_compras(usuario_id);

-- ============================================================
-- TABELA: item_lista
-- ============================================================
CREATE TABLE IF NOT EXISTS item_lista (
    id            SERIAL          PRIMARY KEY,
    lista_id      INTEGER         NOT NULL REFERENCES lista_compras(id) ON DELETE CASCADE,
    descricao     VARCHAR(200)    NOT NULL,
    valor         NUMERIC(12,2)   NOT NULL CHECK (valor >= 0),
    quantidade    INTEGER         NOT NULL DEFAULT 1 CHECK (quantidade > 0),
    foto_base64   TEXT,
    foto_mime     VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_item_lista_lista ON item_lista(lista_id);

-- ============================================================
-- VIEWS
-- ============================================================
CREATE OR REPLACE VIEW v_saldo_usuario AS
SELECT
    u.id                                                            AS usuario_id,
    u.nome,
    u.email,
    u.saldo                                                         AS saldo_manual,
    COALESCE(SUM(c.valor) FILTER (WHERE c.paga = TRUE),  0)        AS total_pago,
    COALESCE(SUM(c.valor) FILTER (WHERE c.paga = FALSE), 0)        AS total_pendente,
    COUNT(*) FILTER (WHERE c.paga = FALSE
                       AND c.data_vencimento < CURRENT_DATE)       AS contas_atrasadas
FROM usuario u
LEFT JOIN conta c ON c.usuario_id = u.id
GROUP BY u.id, u.nome, u.email, u.saldo;

CREATE OR REPLACE VIEW v_gastos_por_categoria AS
SELECT
    c.usuario_id,
    c.categoria,
    SUM(c.valor)    AS total,
    COUNT(*)        AS qtd_contas,
    AVG(c.valor)    AS media_valor
FROM conta c
WHERE c.paga = TRUE
GROUP BY c.usuario_id, c.categoria
ORDER BY total DESC;

CREATE OR REPLACE VIEW v_gastos_por_mes AS
SELECT
    c.usuario_id,
    DATE_TRUNC('month', c.data_vencimento)::DATE    AS mes,
    SUM(c.valor)                                     AS total,
    COUNT(*)                                         AS qtd_contas
FROM conta c
WHERE c.paga = TRUE
GROUP BY c.usuario_id, DATE_TRUNC('month', c.data_vencimento)
ORDER BY mes;

CREATE OR REPLACE VIEW v_compromisso_mensal AS
SELECT
    cf.usuario_id,
    SUM(cf.valor) FILTER (WHERE cf.recorrencia = 'mensal')      AS total_mensal,
    SUM(cf.valor) FILTER (WHERE cf.recorrencia = 'bimestral')   AS total_bimestral,
    SUM(cf.valor) FILTER (WHERE cf.recorrencia = 'trimestral')  AS total_trimestral,
    SUM(cf.valor) FILTER (WHERE cf.recorrencia = 'semestral')   AS total_semestral,
    SUM(cf.valor) FILTER (WHERE cf.recorrencia = 'anual')       AS total_anual,
    COUNT(*)                                                      AS total_fixas_ativas
FROM conta_fixa cf
WHERE cf.ativa = TRUE
GROUP BY cf.usuario_id;

-- ============================================================
-- Verificação final
-- ============================================================
SELECT tablename FROM pg_tables  WHERE schemaname = 'public' ORDER BY tablename;
SELECT viewname  FROM pg_views   WHERE schemaname = 'public' ORDER BY viewname;
