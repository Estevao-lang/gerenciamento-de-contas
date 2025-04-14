from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
from database import db, Conta

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///contas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Criar banco de dados
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    total_pago = db.session.query(db.func.sum(Conta.valor)).filter(Conta.paga == True).scalar() or 0
    total_pendente = db.session.query(db.func.sum(Conta.valor)).filter(Conta.paga == False).scalar() or 0
    ultimas_contas = Conta.query.order_by(Conta.data_vencimento.desc()).limit(5).all()
    return render_template('index.html', 
                         total_pago=total_pago, 
                         total_pendente=total_pendente,
                         ultimas_contas=ultimas_contas)

@app.route('/adicionar', methods=['GET', 'POST'])
def adicionar_conta():
    if request.method == 'POST':
        descricao = request.form['descricao']
        valor = float(request.form['valor'])
        data_vencimento = datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
        categoria = request.form['categoria']
        paga = request.form.get('paga') == 'true'
        
        nova_conta = Conta(
            descricao=descricao,
            valor=valor,
            data_vencimento=data_vencimento,
            paga=paga,
            categoria=categoria
        )
        
        db.session.add(nova_conta)
        db.session.commit()
        
        return redirect(url_for('listar_contas'))
    
    return render_template('adicionar_conta.html')

@app.route('/contas')
def listar_contas():
    contas = Conta.query.order_by(Conta.data_vencimento).all()
    return render_template('listar_contas.html', contas=contas)

@app.route('/pagar/<int:id>')
def pagar_conta(id):
    conta = Conta.query.get_or_404(id)
    conta.paga = True
    db.session.commit()
    return redirect(url_for('listar_contas'))

if __name__ == '__main__':
    app.run(debug=True)