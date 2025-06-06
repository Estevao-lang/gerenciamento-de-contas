from datetime import datetime, timedelta
from app import app, db
from app import Usuario, Conta  # Importando os modelos diretamente do app

def criar_banco():
    with app.app_context():
        # Criar todas as tabelas
        db.create_all()
        
        # Adicionar usuário admin inicial
        admin = Usuario.query.filter_by(email="admin@example.com").first()
        if not admin:
            admin = Usuario(
                nome="Admin",
                email="admin@example.com",
                senha="senha_admin",  # Na prática, armazene hash de senha
                limite_alerta=5000.0
            )
            db.session.add(admin)
            db.session.commit()
        
        # Adicionar contas de exemplo
        contas_exemplo = [
            Conta(
                descricao="Aluguel",
                valor=1500.0,
                data_vencimento=datetime.now().date() + timedelta(days=5),
                categoria="Moradia",
                usuario_id=admin.id
            ),
            Conta(
                descricao="Supermercado",
                valor=450.0,
                data_vencimento=datetime.now().date() + timedelta(days=10),
                categoria="Alimentação",
                usuario_id=admin.id
            )
        ]
        
        for conta in contas_exemplo:
            if not Conta.query.filter_by(descricao=conta.descricao, usuario_id=admin.id).first():
                db.session.add(conta)
        
        db.session.commit()
        print("Banco de dados criado com sucesso!")

if __name__ == '__main__':
    criar_banco()