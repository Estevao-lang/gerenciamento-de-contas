-- ============================================================
-- FinanceFlow - Setup completo do banco PostgreSQL
-- Execute este script no DBeaver conectado ao seu servidor local
--
-- Passo a passo no DBeaver:
--   1. Conecte em "postgres 3" (cloud.maia.systems:8001) ou crie
--      uma conexão local: Host=localhost, Port=5432, DB=postgres
--   2. Clique com botão direito no servidor > "Criar > Banco de dados"
--      Nome: financeflow
--   3. Abra o "Editor SQL" com o banco financeflow selecionado
--   4. Cole e execute este script inteiro (Ctrl+Enter ou F5)
-- ============================================================

-- Garante que executa no banco correto
-- (selecione o banco financeflow antes de rodar)

-- ============================================================
-- TABELA: usuario
-- ============================================================
CREATE TABLE IF NOT EXISTS usuario (
    id              SERIAL PRIMARY KEY,
    nome            VARCHAR(100)        NOT NULL,
    email           VARCHAR(100)        NOT NULL UNIQUE,
    senha           VARCHAR(255)        NOT NULL,
    limite_alerta   NUMERIC(12, 2)      NOT NULL DEFAULT 1000.00,
    saldo           NUMERIC(12, 2)      NOT NULL DEFAULT 0.00,
    criado_em       TIMESTAMPTZ         NOT NULL DEFAULT NOW()
);

-- ============================================================
-- TABELA: conta
-- ============================================================
CREATE TABLE IF NOT EXISTS conta (
    id               SERIAL PRIMARY KEY,
    usuario_id       INTEGER             NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    descricao        VARCHAR(200)        NOT NULL,
    valor            NUMERIC(12, 2)      NOT NULL CHECK (valor > 0),
    data_vencimento  DATE                NOT NULL,
    paga             BOOLEAN             NOT NULL DEFAULT FALSE,
    categoria        VARCHAR(50)         NOT NULL DEFAULT 'Outros',
    criado_em        TIMESTAMPTZ         NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conta_usuario_id      ON conta(usuario_id);
CREATE INDEX IF NOT EXISTS idx_conta_data_vencimento ON conta(data_vencimento);
CREATE INDEX IF NOT EXISTS idx_conta_paga            ON conta(paga);

-- ============================================================
-- TABELA: lista_compras
-- ============================================================
CREATE TABLE IF NOT EXISTS lista_compras (
    id            SERIAL PRIMARY KEY,
    usuario_id    INTEGER         NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    titulo        VARCHAR(100)    NOT NULL,
    data_criacao  DATE            NOT NULL DEFAULT CURRENT_DATE,
    finalizada    BOOLEAN         NOT NULL DEFAULT FALSE,
    criado_em     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lista_compras_usuario_id ON lista_compras(usuario_id);

-- ============================================================
-- TABELA: item_lista
-- ============================================================
CREATE TABLE IF NOT EXISTS item_lista (
    id          SERIAL PRIMARY KEY,
    lista_id    INTEGER         NOT NULL REFERENCES lista_compras(id) ON DELETE CASCADE,
    descricao   VARCHAR(200)    NOT NULL,
    valor       NUMERIC(12, 2)  NOT NULL CHECK (valor >= 0)
);

CREATE INDEX IF NOT EXISTS idx_item_lista_lista_id ON item_lista(lista_id);

-- ============================================================
-- VIEW: v_saldo_usuario
-- Saldo real calculado a partir das contas pagas
-- (use esta view para auditar — o campo saldo em usuario é
--  mantido pelo app para performance)
-- ============================================================
CREATE OR REPLACE VIEW v_saldo_usuario AS
SELECT
    u.id                                                          AS usuario_id,
    u.nome,
    u.email,
    u.saldo                                                       AS saldo_manual,
    COALESCE(SUM(c.valor) FILTER (WHERE c.paga = TRUE),  0)      AS total_pago,
    COALESCE(SUM(c.valor) FILTER (WHERE c.paga = FALSE), 0)      AS total_pendente
FROM usuario u
LEFT JOIN conta c ON c.usuario_id = u.id
GROUP BY u.id, u.nome, u.email, u.saldo;

-- ============================================================
-- VIEW: v_gastos_por_categoria
-- Para a página de análise
-- ============================================================
CREATE OR REPLACE VIEW v_gastos_por_categoria AS
SELECT
    c.usuario_id,
    c.categoria,
    SUM(c.valor)   AS total,
    COUNT(*)       AS qtd_contas
FROM conta c
WHERE c.paga = TRUE
GROUP BY c.usuario_id, c.categoria
ORDER BY total DESC;

-- ============================================================
-- VIEW: v_gastos_por_mes
-- ============================================================
CREATE OR REPLACE VIEW v_gastos_por_mes AS
SELECT
    c.usuario_id,
    DATE_TRUNC('month', c.data_vencimento)::DATE AS mes,
    SUM(c.valor)                                  AS total
FROM conta c
WHERE c.paga = TRUE
GROUP BY c.usuario_id, DATE_TRUNC('month', c.data_vencimento)
ORDER BY mes;

-- ============================================================
-- USUÁRIO DE TESTE
-- ATENÇÃO: substitua a senha antes de usar em produção!
-- Para gerar o hash correto, rode no terminal Python:
--   from werkzeug.security import generate_password_hash
--   print(generate_password_hash("senha123"))
-- Cole o resultado abaixo no lugar do placeholder
-- ============================================================
INSERT INTO usuario (nome, email, senha, limite_alerta, saldo)
VALUES (
    'Admin Teste',
    'admin@financeflow.com',
    'SUBSTITUA_PELO_HASH_WERKZEUG',   -- gere o hash conforme instrução acima
    2000.00,
    0.00
)
ON CONFLICT (email) DO NOTHING;

-- ============================================================
-- DADOS DE EXEMPLO (opcional — remova se não quiser)
-- ============================================================
DO $$
DECLARE v_uid INTEGER;
BEGIN
    SELECT id INTO v_uid FROM usuario WHERE email = 'admin@financeflow.com';

    IF v_uid IS NOT NULL THEN
        INSERT INTO conta (usuario_id, descricao, valor, data_vencimento, paga, categoria) VALUES
            (v_uid, 'Aluguel',          1500.00, CURRENT_DATE + 5,  FALSE, 'Moradia'),
            (v_uid, 'Internet',           99.90, CURRENT_DATE + 10, FALSE, 'Serviços'),
            (v_uid, 'Supermercado',      450.00, CURRENT_DATE - 2,  TRUE,  'Alimentação'),
            (v_uid, 'Plano de Saúde',    320.00, CURRENT_DATE + 15, FALSE, 'Saúde'),
            (v_uid, 'Faculdade',         800.00, CURRENT_DATE + 20, FALSE, 'Educação'),
            (v_uid, 'Conta de Luz',      180.50, CURRENT_DATE - 5,  TRUE,  'Moradia'),
            (v_uid, 'Streaming',          55.90, CURRENT_DATE + 3,  FALSE, 'Lazer');

        -- Atualiza saldo com base nas contas pagas de exemplo
        UPDATE usuario
        SET saldo = -(SELECT COALESCE(SUM(valor), 0) FROM conta WHERE usuario_id = v_uid AND paga = TRUE)
        WHERE id = v_uid;
    END IF;
END $$;

-- ============================================================
-- Verificação final — rode para confirmar que tudo foi criado
-- ============================================================
SELECT 'Tabelas criadas:' AS info;
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;

SELECT 'Views criadas:' AS info;
SELECT viewname FROM pg_views WHERE schemaname = 'public' ORDER BY viewname;

SELECT 'Usuários cadastrados:' AS info;
SELECT id, nome, email, saldo FROM usuario;
