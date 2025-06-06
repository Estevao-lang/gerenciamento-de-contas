from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
import os
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
import re

# Carregar variáveis de ambiente
load_dotenv()

app = Flask(__name__, static_folder='static')
# Configuração do PostgreSQL para Render.com
render_db_user = 'gerencismento_contas_user'
render_db_password = 'SUA_SENHA_REAL'  # Obtenha esta do dashboard do Render
render_db_host = 'dpg-d110bsh5pdvs73efmph0-a'
render_db_port = '5432'
render_db_name = 'gerencismento_contas'

# Construa a string de conexão
render_db_url = f'postgresql://{render_db_user}:{render_db_password}@{render_db_host}:{render_db_port}/{render_db_name}'

# Configuração do SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', render_db_url)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Função auxiliar para converter números no formato brasileiro
def parse_brl_number(value):
    """Converte string no formato brasileiro (1.234,56) para float"""
    try:
        # Remove pontos de milhar e substitui vírgula decimal por ponto
        cleaned = value.replace('.', '').replace(',', '.')
        return float(cleaned)
    except (ValueError, TypeError):
        return None

# Função para formatar valores em moeda brasileira
def format_currency(value):
    return "R$ {:,.2f}".format(value).replace(',', 'v').replace('.', ',').replace('v', '.')

# Modelo de Usuário
class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    limite_alerta = db.Column(db.Float, default=1000.0)
    saldo = db.Column(db.Float, default=0.0)  # Campo ESSENCIAL adicionado
    contas = db.relationship('Conta', backref='usuario', lazy=True)
    listas_compras = db.relationship('ListaCompras', backref='usuario', lazy=True)

# Modelo de Conta
class Conta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    paga = db.Column(db.Boolean, default=False)
    categoria = db.Column(db.String(50))
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    
    @property
    def dias_vencimento(self):
        hoje = datetime.today().date()
        return (self.data_vencimento - hoje).days

# Novo modelo: Item da lista de compras
class ItemLista(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    lista_id = db.Column(db.Integer, db.ForeignKey('lista_compras.id'), nullable=False)

# Novo modelo: Lista de compras
class ListaCompras(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(100), nullable=False)
    data_criacao = db.Column(db.Date, nullable=False, default=datetime.today().date)
    finalizada = db.Column(db.Boolean, default=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    itens = db.relationship('ItemLista', backref='lista', lazy=True, cascade="all, delete-orphan")
    
    @property
    def total(self):
        return sum(item.valor for item in self.itens)

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

def enviar_email(destinatario, assunto, corpo):
    try:
        msg = MIMEText(corpo)
        msg['Subject'] = assunto
        msg['From'] = os.getenv('EMAIL_FROM')
        msg['To'] = destinatario

        with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
            server.starttls()
            server.login(os.getenv('EMAIL_USER'), os.getenv('EMAIL_PASSWORD'))
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        return False

def verificar_alertas(usuario):
    # Verificar saldo total
    total_pago = db.session.query(func.sum(Conta.valor)).filter(
        Conta.paga == True,
        Conta.usuario_id == usuario.id
    ).scalar() or 0

    if usuario.limite_alerta and total_pago > usuario.limite_alerta:
        assunto = "Alerta de Limite de Gastos"
        corpo = f"Seus gastos ({total_pago}) excederam seu limite definido de {usuario.limite_alerta}!"
        enviar_email(usuario.email, assunto, corpo)
        flash('Limite de gastos excedido! Verifique seu email para detalhes.', 'warning')

def gerar_grafico_categorias(usuario_id):
    categorias = db.session.query(
        Conta.categoria,
        func.sum(Conta.valor).label('total')
    ).filter(
        Conta.usuario_id == usuario_id,
        Conta.paga == True
    ).group_by(Conta.categoria).all()

    if not categorias:
        return None

    nomes = [c[0] for c in categorias]
    valores = [float(c[1]) for c in categorias]

    plt.figure(figsize=(8, 6))
    plt.pie(valores, labels=nomes, autopct='%1.1f%%', startangle=90)
    plt.axis('equal')
    plt.title('Distribuição de Gastos por Categoria')
    
    buffer = BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def analisar_gastos(usuario_id):
    # Gastos por categoria
    gastos_categoria = db.session.query(
        Conta.categoria,
        func.sum(Conta.valor).label('total')
    ).filter(
        Conta.usuario_id == usuario_id,
        Conta.paga == True
    ).group_by(Conta.categoria).order_by(func.sum(Conta.valor).desc()).all()

    # Gastos mensais
    gastos_mensais = db.session.query(
        func.date_trunc('month', Conta.data_vencimento).label('mes'),
        func.sum(Conta.valor).label('total')
    ).filter(
        Conta.usuario_id == usuario_id,
        Conta.paga == True
    ).group_by('mes').order_by('mes').all()

    # Análise de recomendações
    recomendacoes = []
    if gastos_categoria:
        maior_categoria = gastos_categoria[0][0]
        recomendacoes.append(
            f"Seus maiores gastos são em '{maior_categoria}'. "
            "Considere revisar despesas nesta categoria."
        )

    if len(gastos_mensais) > 1:
        ultimo_mes = gastos_mensais[-1][1]
        penultimo_mes = gastos_mensais[-2][1]
        if ultimo_mes > penultimo_mes:
            percentual = ((ultimo_mes - penultimo_mes) / penultimo_mes) * 100
            recomendacoes.append(
                f"Seus gastos aumentaram {percentual:.2f}% no último mês. "
                "Avalie onde pode reduzir despesas."
            )

    return {
        'gastos_categoria': gastos_categoria,
        'gastos_mensais': gastos_mensais,
        'recomendacoes': recomendacoes,
        'grafico': gerar_grafico_categorias(usuario_id)
    }

# Rotas de Autenticação
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']
        
        if Usuario.query.filter_by(email=email).first():
            flash('Email já cadastrado!', 'danger')
            return redirect(url_for('registro'))
        
        novo_usuario = Usuario(nome=nome, email=email, senha=senha)
        db.session.add(novo_usuario)
        db.session.commit()
        
        flash('Registro realizado com sucesso! Faça login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and usuario.senha == senha:
            login_user(usuario)
            return redirect(url_for('index'))
        else:
            flash('Login falhou. Verifique email e senha!', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Rotas da Aplicação
@app.route('/')
@login_required
def index():
    total_pago = db.session.query(func.sum(Conta.valor)).filter(
        Conta.paga == True,
        Conta.usuario_id == current_user.id
    ).scalar() or 0
    
    total_pendente = db.session.query(func.sum(Conta.valor)).filter(
        Conta.paga == False,
        Conta.usuario_id == current_user.id
    ).scalar() or 0
    
    proximas_contas = Conta.query.filter(
        Conta.usuario_id == current_user.id,
        Conta.paga == False,
        Conta.data_vencimento >= datetime.today().date()
    ).order_by(Conta.data_vencimento).limit(5).all()
    
    verificar_alertas(current_user)
    
    return render_template('index.html', 
                         total_pago=total_pago,
                         total_pendente=total_pendente,
                         saldo=current_user.saldo,
                         proximas_contas=proximas_contas)

@app.route('/contas')
@login_required
def listar_contas():
    contas = Conta.query.filter_by(usuario_id=current_user.id).order_by(Conta.data_vencimento).all()
    return render_template('listar_contas.html', contas=contas, format_currency=format_currency)

@app.route('/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_conta():
    if request.method == 'POST':
        descricao = request.form['descricao']
        valor = parse_brl_number(request.form['valor'])
        data_vencimento = datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
        categoria = request.form['categoria']
        paga = 'paga' in request.form
        
        # Validação do valor
        if valor is None:
            flash('Formato de valor inválido! Use: 1.234,56', 'danger')
            return render_template('adicionar_conta.html')
        
        nova_conta = Conta(
            descricao=descricao,
            valor=valor,
            data_vencimento=data_vencimento,
            paga=paga,
            categoria=categoria,
            usuario_id=current_user.id
        )
        
        db.session.add(nova_conta)
        db.session.commit()
        
        # Se a conta for marcada como paga, subtrai do saldo
        if paga:
            current_user.saldo -= valor
            db.session.commit()
        
        verificar_alertas(current_user)
        flash('Conta adicionada com sucesso!', 'success')
        return redirect(url_for('listar_contas'))
    
    return render_template('adicionar_conta.html')

@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_conta(id):
    conta = Conta.query.get_or_404(id)
    
    if conta.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_contas'))
    
    if request.method == 'POST':
        valor_anterior = conta.valor
        
        conta.descricao = request.form['descricao']
        
        # Converter valor usando a função auxiliar
        valor = parse_brl_number(request.form['valor'])
        if valor is None:
            flash('Formato de valor inválido! Use: 1.234,56', 'danger')
            return render_template('editar_conta.html', conta=conta)
        
        conta.valor = valor
        conta.data_vencimento = datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
        conta.categoria = request.form['categoria']
        
        # Verificar se o status de pagamento mudou
        nova_paga = 'paga' in request.form
        if nova_paga != conta.paga:
            if nova_paga:
                # Se foi marcada como paga agora, subtrai do saldo
                current_user.saldo -= valor
            else:
                # Se foi desmarcada, adiciona o valor de volta ao saldo
                current_user.saldo += valor_anterior
            
            conta.paga = nova_paga
        
        db.session.commit()
        verificar_alertas(current_user)
        flash('Conta atualizada com sucesso!', 'success')
        return redirect(url_for('listar_contas'))
    
    return render_template('editar_conta.html', conta=conta, format_currency=format_currency)

@app.route('/excluir/<int:id>')
@login_required
def excluir_conta(id):
    conta = Conta.query.get_or_404(id)
    
    if conta.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_contas'))
    
    # Se a conta estava paga, adiciona o valor de volta ao saldo
    if conta.paga:
        current_user.saldo += conta.valor
        db.session.commit()
    
    db.session.delete(conta)
    db.session.commit()
    flash('Conta excluída com sucesso!', 'success')
    return redirect(url_for('listar_contas'))

@app.route('/pagar/<int:id>')
@login_required
def pagar_conta(id):
    conta = Conta.query.get_or_404(id)
    
    if conta.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_contas'))
    
    if not conta.paga:
        conta.paga = True
        # Subtrai o valor da conta do saldo
        current_user.saldo -= conta.valor
        db.session.commit()
        verificar_alertas(current_user)
        flash('Conta marcada como paga!', 'success')
    else:
        flash('Esta conta já está paga', 'info')
    
    return redirect(url_for('listar_contas'))

# Rotas para listas de compras
@app.route('/listas_compras')
@login_required
def listar_listas_compras():
    listas = ListaCompras.query.filter_by(usuario_id=current_user.id).order_by(ListaCompras.data_criacao.desc()).all()
    return render_template('listar_listas_compras.html', listas=listas, format_currency=format_currency)

@app.route('/lista_compras/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_lista_compras():
    if request.method == 'POST':
        titulo = request.form['titulo']
        
        # Criar nova lista
        nova_lista = ListaCompras(
            titulo=titulo,
            usuario_id=current_user.id
        )
        db.session.add(nova_lista)
        db.session.flush()  # Para obter o ID antes do commit
        
        # Processar itens da lista
        descricoes = request.form.getlist('item_descricao[]')
        valores = request.form.getlist('item_valor[]')
        
        for i in range(len(descricoes)):
            if descricoes[i].strip():
                valor = parse_brl_number(valores[i])
                if valor is None:
                    flash(f'Formato inválido para o valor do item: {descricoes[i]}', 'danger')
                    db.session.rollback()
                    return render_template('adicionar_lista_compras.html')
                
                novo_item = ItemLista(
                    descricao=descricoes[i],
                    valor=valor,
                    lista_id=nova_lista.id
                )
                db.session.add(novo_item)
        
        db.session.commit()
        flash('Lista de compras criada com sucesso!', 'success')
        return redirect(url_for('ver_lista_compras', id=nova_lista.id))
    
    return render_template('adicionar_lista_compras.html')

@app.route('/lista_compras/<int:id>')
@login_required
def ver_lista_compras(id):
    lista = ListaCompras.query.get_or_404(id)
    
    if lista.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_listas_compras'))
    
    return render_template('ver_lista_compras.html', lista=lista, format_currency=format_currency)

@app.route('/lista_compras/finalizar/<int:id>')
@login_required
def finalizar_lista_compras(id):
    lista = ListaCompras.query.get_or_404(id)
    
    if lista.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_listas_compras'))
    
    if not lista.finalizada:
        lista.finalizada = True
        # Subtrai o total da lista do saldo
        current_user.saldo -= lista.total
        db.session.commit()
        flash(f'Lista finalizada! R$ {lista.total:.2f} debitados do seu saldo.', 'success')
    else:
        flash('Esta lista já foi finalizada', 'info')
    
    return redirect(url_for('ver_lista_compras', id=id))

@app.route('/lista_compras/excluir/<int:id>')
@login_required
def excluir_lista_compras(id):
    lista = ListaCompras.query.get_or_404(id)
    
    if lista.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_listas_compras'))
    
    # Se a lista foi finalizada, devolve o valor ao saldo
    if lista.finalizada:
        current_user.saldo += lista.total
        db.session.commit()
    
    db.session.delete(lista)
    db.session.commit()
    flash('Lista de compras excluída com sucesso!', 'success')
    return redirect(url_for('listar_listas_compras'))

@app.route('/perfil', methods=['GET', 'POST'])
@login_required

# Rota de perfil (APENAS UMA DEFINIÇÃO - corrigida com endpoint único)
@app.route('/perfil', methods=['GET', 'POST'], endpoint='perfil_route')
@login_required
def perfil():
    if request.method == 'POST':
        current_user.nome = request.form['nome']
        current_user.email = request.form['email']
        
        try:
            limite_str = request.form['limite_alerta'].replace('.', '').replace(',', '.')
            current_user.limite_alerta = float(limite_str)
        except ValueError:
            flash('Formato inválido para limite de alerta! Use: 1.234,56', 'danger')
            return redirect(url_for('perfil_route'))
        
        try:
            saldo_str = request.form['saldo'].replace('.', '').replace(',', '.')
            current_user.saldo = float(saldo_str)
        except ValueError:
            flash('Formato inválido para saldo! Use: 1.234,56', 'danger')
            return redirect(url_for('perfil_route'))
        
        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('perfil_route'))
    
    return render_template('perfil.html')

@app.route('/analise')
@login_required
def analise():
    dados = analisar_gastos(current_user.id)
    return render_template('analise.html', dados=dados)

# Context processor para injetar data/hora atual em todos os templates
@app.context_processor
def inject_current_datetime():
    return {
        'now': datetime.now(),
        'current_year': datetime.now().year,
        'format_currency': format_currency
    }

# Inicialização do banco de dados
def inicializar_banco():
    with app.app_context():
        db.create_all()
        print("Banco de dados inicializado!")

# Chamar a função durante a inicialização
inicializar_banco()

if __name__ == '__main__':
    app.run(debug=True)