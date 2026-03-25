-- ============================================================
-- Popula as contas do mês para o usuário
-- SUBSTITUA 'SEU@EMAIL.COM' pelo email da sua conta
-- Execute no pgAdmin com o banco financeflow selecionado
-- ============================================================

DO $$
DECLARE
    v_uid INTEGER;
    v_email TEXT := 'estevao09.gabriel@gmail.com';  -- <- TROQUE AQUI
    v_venc DATE := DATE_TRUNC('month', CURRENT_DATE)::DATE + 27; -- vence dia 28 do mês atual
BEGIN
    -- Busca o usuário pelo email
    SELECT id INTO v_uid FROM usuario WHERE email = v_email;

    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'Usuário com email % não encontrado. Verifique o email.', v_email;
    END IF;

    -- Remove contas do mês atual para evitar duplicatas (opcional)
    -- DELETE FROM conta WHERE usuario_id = v_uid AND DATE_TRUNC('month', data_vencimento) = DATE_TRUNC('month', CURRENT_DATE);

    -- Insere todas as contas do orçamento
    INSERT INTO conta (usuario_id, descricao, valor, data_vencimento, paga, categoria) VALUES
        (v_uid, 'Aluguel',              2200.00, v_venc,       FALSE, 'Moradia'),
        (v_uid, 'Compras mercado/feira',2000.00, v_venc,       FALSE, 'Alimentação'),
        (v_uid, 'Faculdade',             300.00, v_venc,       FALSE, 'Educação'),
        (v_uid, 'Shopee',                400.00, v_venc,       FALSE, 'Lazer'),
        (v_uid, 'ChatGPT',               100.00, v_venc,       FALSE, 'Serviços'),
        (v_uid, 'Celular',               100.00, v_venc,       FALSE, 'Serviços'),
        (v_uid, 'Internet',              100.00, v_venc,       FALSE, 'Serviços'),
        (v_uid, 'Airbnb',                430.00, v_venc,       FALSE, 'Lazer'),
        (v_uid, 'Passagem de ônibus',    110.00, v_venc,       FALSE, 'Transporte'),
        (v_uid, 'Sogra',                1680.00, v_venc,       FALSE, 'Outros'),
        (v_uid, 'Contas água e luz',      80.00, v_venc,       FALSE, 'Moradia'),
        (v_uid, 'Nubank (dívida)',       200.00, v_venc,       FALSE, 'Outros'),
        (v_uid, 'Pan (dívida)',          470.00, v_venc,       FALSE, 'Outros'),
        (v_uid, 'Inter (dívida)',        561.00, v_venc,       FALSE, 'Outros'),
        (v_uid, 'Dm Sonda',              240.00, v_venc,       FALSE, 'Saúde'),
        (v_uid, 'Pet',                   300.00, v_venc,       FALSE, 'Outros');

    -- Atualiza o saldo com o orçamento total informado
    UPDATE usuario
    SET saldo = 9400.00,
        limite_alerta = 9271.00  -- alerta quando gastar tudo
    WHERE id = v_uid;

    RAISE NOTICE 'Sucesso! 16 contas inseridas para o usuário % (id=%)', v_email, v_uid;
END $$;

-- Confirma o que foi inserido
SELECT
    descricao,
    valor,
    categoria,
    data_vencimento,
    CASE WHEN paga THEN 'Paga' ELSE 'Pendente' END AS status
FROM conta
WHERE usuario_id = (SELECT id FROM usuario WHERE email = 'estevao09.gabriel@gmail.com')
ORDER BY categoria, descricao;

-- Mostra resumo por categoria
SELECT
    categoria,
    COUNT(*)        AS qtd,
    SUM(valor)      AS total
FROM conta
WHERE usuario_id = (SELECT id FROM usuario WHERE email = 'estevao09.gabriel@gmail.com')
GROUP BY categoria
ORDER BY total DESC;
