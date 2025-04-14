from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy(session_options={"autoflush": False})

class Conta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    paga = db.Column(db.Boolean, default=False)
    categoria = db.Column(db.String(50))

    def __repr__(self):
        return f'<Conta {self.descricao}>'