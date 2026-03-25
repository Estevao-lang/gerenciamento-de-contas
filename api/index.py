import sys
import os

# Garante que o diretório raiz do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text

# Cria tabelas e aplica migrations no cold start do Vercel
with app.app_context():
    db.create_all()
    try:
        with db.engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE conta ADD COLUMN IF NOT EXISTS conta_fixa_id "
                "INTEGER REFERENCES conta_fixa(id) ON DELETE SET NULL"
            ))
            conn.commit()
    except Exception:
        pass
