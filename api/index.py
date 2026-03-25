import sys
import os

# Garante que o diretório raiz do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text

# Cria tabelas e aplica migrations no cold start do Vercel
with app.app_context():
    db.create_all()
    _migrations = [
        # conta_fixa_id
        "ALTER TABLE conta ADD COLUMN IF NOT EXISTS conta_fixa_id INTEGER REFERENCES conta_fixa(id) ON DELETE SET NULL",
        # data_pagamento
        "ALTER TABLE conta ADD COLUMN IF NOT EXISTS data_pagamento DATE",
        # criado_em nas tabelas
        "ALTER TABLE conta         ADD COLUMN IF NOT EXISTS criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "ALTER TABLE usuario        ADD COLUMN IF NOT EXISTS criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "ALTER TABLE lista_compras  ADD COLUMN IF NOT EXISTS criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "ALTER TABLE conta_fixa     ADD COLUMN IF NOT EXISTS criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        # preenche data_pagamento retroativamente
        "UPDATE conta SET data_pagamento = data_vencimento WHERE paga = TRUE AND data_pagamento IS NULL",
        # índices
        "CREATE INDEX IF NOT EXISTS idx_conta_fixa_usuario ON conta_fixa(usuario_id)",
        "CREATE INDEX IF NOT EXISTS idx_conta_paga         ON conta(usuario_id, paga)",
        "CREATE INDEX IF NOT EXISTS idx_conta_fixa_ref     ON conta(conta_fixa_id)",
        # planos
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS plano VARCHAR(20) NOT NULL DEFAULT 'gratuito'",
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS plano_expira_em DATE",
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(100)",
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(100)",
    ]
    try:
        with db.engine.connect() as conn:
            for sql in _migrations:
                try:
                    conn.execute(text(sql))
                except Exception:
                    pass
            conn.commit()
    except Exception:
        pass
