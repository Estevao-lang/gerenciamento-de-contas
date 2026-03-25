-- ============================================================
-- FinanceFlow — Migration v2: Contas Fixas
-- Execute no pgAdmin (local) e no Neon (Vercel)
-- ============================================================

-- 1. Criar tabela conta_fixa
CREATE TABLE IF NOT EXISTS conta_fixa (
    id               SERIAL PRIMARY KEY,
    descricao        VARCHAR(200)  NOT NULL,
    valor            FLOAT         NOT NULL,
    categoria        VARCHAR(50)   DEFAULT 'Outros',
    dia_vencimento   INTEGER       NOT NULL CHECK (dia_vencimento BETWEEN 1 AND 28),
    recorrencia      VARCHAR(20)   DEFAULT 'mensal',
    data_inicio      DATE          NOT NULL,
    data_fim         DATE,
    parcelas_total   INTEGER,
    ativa            BOOLEAN       DEFAULT TRUE,
    usuario_id       INTEGER       NOT NULL REFERENCES usuario(id) ON DELETE CASCADE
);

-- 2. Adicionar FK na tabela conta
ALTER TABLE conta
    ADD COLUMN IF NOT EXISTS conta_fixa_id INTEGER REFERENCES conta_fixa(id) ON DELETE SET NULL;

-- 3. Índice para performance
CREATE INDEX IF NOT EXISTS idx_conta_fixa_usuario ON conta_fixa(usuario_id);
CREATE INDEX IF NOT EXISTS idx_conta_conta_fixa   ON conta(conta_fixa_id);
