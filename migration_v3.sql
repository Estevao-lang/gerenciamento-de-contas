-- ============================================================
-- FinanceFlow — Migration v3
-- Aplica melhorias de estrutura no banco existente
-- Execute no pgAdmin (local) e no Neon (Vercel)
-- ============================================================

-- 1. Cria conta_fixa se não existir (quem pulou migration_v2)
CREATE TABLE IF NOT EXISTS conta_fixa (
    id               SERIAL          PRIMARY KEY,
    usuario_id       INTEGER         NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    descricao        VARCHAR(200)    NOT NULL,
    valor            NUMERIC(12,2)   NOT NULL CHECK (valor > 0),
    categoria        VARCHAR(50)     NOT NULL DEFAULT 'Outros',
    dia_vencimento   INTEGER         NOT NULL CHECK (dia_vencimento BETWEEN 1 AND 28),
    recorrencia      VARCHAR(20)     NOT NULL DEFAULT 'mensal',
    data_inicio      DATE            NOT NULL,
    data_fim         DATE,
    parcelas_total   INTEGER         CHECK (parcelas_total > 0),
    ativa            BOOLEAN         NOT NULL DEFAULT TRUE,
    criado_em        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- 2. Adiciona colunas novas em conta
ALTER TABLE conta
    ADD COLUMN IF NOT EXISTS conta_fixa_id  INTEGER REFERENCES conta_fixa(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS data_pagamento DATE,
    ADD COLUMN IF NOT EXISTS criado_em      TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 3. Adiciona criado_em nas outras tabelas (ignorado se já existir)
ALTER TABLE usuario       ADD COLUMN IF NOT EXISTS criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE lista_compras ADD COLUMN IF NOT EXISTS criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE conta_fixa    ADD COLUMN IF NOT EXISTS criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 4. Migra Float → NUMERIC(12,2) nos campos de valor (preserva dados)
ALTER TABLE conta         ALTER COLUMN valor         TYPE NUMERIC(12,2) USING valor::NUMERIC(12,2);
ALTER TABLE conta         ALTER COLUMN data_pagamento TYPE DATE;
ALTER TABLE conta_fixa    ALTER COLUMN valor         TYPE NUMERIC(12,2) USING valor::NUMERIC(12,2);
ALTER TABLE usuario       ALTER COLUMN saldo         TYPE NUMERIC(12,2) USING saldo::NUMERIC(12,2);
ALTER TABLE usuario       ALTER COLUMN limite_alerta TYPE NUMERIC(12,2) USING limite_alerta::NUMERIC(12,2);
ALTER TABLE item_lista    ALTER COLUMN valor         TYPE NUMERIC(12,2) USING valor::NUMERIC(12,2);

-- 5. Preenche data_pagamento retroativamente para contas já pagas
UPDATE conta SET data_pagamento = data_vencimento WHERE paga = TRUE AND data_pagamento IS NULL;

-- 6. Índices novos
CREATE INDEX IF NOT EXISTS idx_conta_fixa_usuario  ON conta_fixa(usuario_id);
CREATE INDEX IF NOT EXISTS idx_conta_fixa_ativa     ON conta_fixa(usuario_id, ativa);
CREATE INDEX IF NOT EXISTS idx_conta_paga           ON conta(usuario_id, paga);
CREATE INDEX IF NOT EXISTS idx_conta_fixa_ref       ON conta(conta_fixa_id);

-- 7. Atualiza views
CREATE OR REPLACE VIEW v_saldo_usuario AS
SELECT
    u.id,
    u.nome,
    u.email,
    u.saldo                                                             AS saldo_manual,
    COALESCE(SUM(c.valor) FILTER (WHERE c.paga = TRUE),  0)            AS total_pago,
    COALESCE(SUM(c.valor) FILTER (WHERE c.paga = FALSE), 0)            AS total_pendente,
    COUNT(*) FILTER (WHERE c.paga = FALSE AND c.data_vencimento < CURRENT_DATE) AS contas_atrasadas
FROM usuario u
LEFT JOIN conta c ON c.usuario_id = u.id
GROUP BY u.id, u.nome, u.email, u.saldo;

CREATE OR REPLACE VIEW v_compromisso_mensal AS
SELECT
    cf.usuario_id,
    SUM(cf.valor) FILTER (WHERE cf.recorrencia = 'mensal')     AS total_mensal,
    SUM(cf.valor) FILTER (WHERE cf.recorrencia = 'bimestral')  AS total_bimestral,
    SUM(cf.valor) FILTER (WHERE cf.recorrencia = 'trimestral') AS total_trimestral,
    COUNT(*)                                                     AS total_fixas_ativas
FROM conta_fixa cf WHERE cf.ativa = TRUE
GROUP BY cf.usuario_id;

-- Confirmação
SELECT 'Migration v3 aplicada com sucesso!' AS status;
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
