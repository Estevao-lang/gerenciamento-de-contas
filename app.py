from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime, timedelta, date
from calendar import monthrange
from sqlalchemy import func, text, Numeric
import os
from io import BytesIO
import base64
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
import re
from werkzeug.security import generate_password_hash, check_password_hash

# Carregar variáveis de ambiente
load_dotenv()

app = Flask(__name__, static_folder='static')

# ── Chave secreta obrigatória ─────────────────────────────
_secret = os.getenv('SECRET_KEY', '')
if not _secret:
    import secrets as _s
    _secret = _s.token_hex(32)   # gera uma por processo (não persiste entre workers)
    print('[AVISO] SECRET_KEY não definida — use uma chave fixa em produção!')
app.secret_key = _secret

# ── Cookies de sessão seguros ─────────────────────────────
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE']   = os.getenv('FLASK_DEBUG', 'false').lower() != 'true'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# ── CSRF ─────────────────────────────────────────────────
app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hora
csrf = CSRFProtect(app)

# ── Rate Limiter ──────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri='memory://',
)

# ── Configuração do PostgreSQL ────────────────────────────
_db_url = os.getenv('DATABASE_URL', '')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ── Headers de segurança em todas as respostas ────────────
@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options']        = 'SAMEORIGIN'
    response.headers['X-XSS-Protection']       = '1; mode=block'
    response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']     = 'geolocation=(), microphone=(), camera=()'
    return response

# ── Erro CSRF ─────────────────────────────────────────────
@app.errorhandler(CSRFError)
def csrf_error(e):
    flash('Sessão expirada ou requisição inválida. Tente novamente.', 'danger')
    return redirect(request.referrer or url_for('index'))

# Função auxiliar para converter números no formato brasileiro
def parse_brl_number(value):
    """Converte string no formato brasileiro (1.234,56) para float"""
    try:
        cleaned = value.replace('R$', '').strip()
        cleaned = cleaned.replace('.', '').replace(',', '.')
        return float(cleaned)
    except (ValueError, TypeError):
        return None

# Função para formatar valores em moeda brasileira
def format_currency(value):
    if value is None:
        return "R$ 0,00"
    return f"R$ {value:,.2f}".replace(',', 'temp').replace('.', ',').replace('temp', '.')

MON = db.Numeric(12, 2)   # tipo para valores monetários

# ── Planos e limites ──────────────────────────────────────
PLANOS = {
    'gratuito': {'contas_mes': 15, 'contas_fixas': 3,    'listas': 2},
    'pro':      {'contas_mes': None, 'contas_fixas': None, 'listas': None},
}

def usuario_pro(u):
    if getattr(u, 'plano', 'gratuito') != 'pro':
        return False
    expira = getattr(u, 'plano_expira_em', None)
    if expira and expira < datetime.today().date():
        return False
    return True

def check_limite(usuario, recurso):
    """Limites desativados durante o beta — todos os usuários têm acesso ilimitado."""
    return True

# Modelo de Usuário
class Usuario(db.Model, UserMixin):
    id                     = db.Column(db.Integer, primary_key=True)
    nome                   = db.Column(db.String(100), nullable=False)
    email                  = db.Column(db.String(100), unique=True, nullable=False)
    senha                  = db.Column(db.String(255), nullable=False)
    limite_alerta          = db.Column(MON, default=1000.0)
    saldo                  = db.Column(MON, default=0.0)
    criado_em              = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    # Plano de assinatura
    plano                  = db.Column(db.String(20), default='gratuito')   # gratuito | pro
    plano_expira_em        = db.Column(db.Date, nullable=True)
    stripe_customer_id     = db.Column(db.String(100), nullable=True)
    stripe_subscription_id = db.Column(db.String(100), nullable=True)
    contas        = db.relationship('Conta', backref='usuario', lazy=True, cascade="all, delete-orphan")
    listas_compras= db.relationship('ListaCompras', backref='usuario', lazy=True, cascade="all, delete-orphan")
    contas_fixas  = db.relationship('ContaFixa', backref='usuario', lazy=True, cascade="all, delete-orphan")

# Modelo de Conta Fixa (recorrente)
class ContaFixa(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    descricao      = db.Column(db.String(200), nullable=False)
    valor          = db.Column(MON, nullable=False)
    categoria      = db.Column(db.String(50), default='Outros')
    dia_vencimento = db.Column(db.Integer, nullable=False)
    recorrencia    = db.Column(db.String(20), default='mensal')
    data_inicio    = db.Column(db.Date, nullable=False)
    data_fim       = db.Column(db.Date, nullable=True)
    parcelas_total = db.Column(db.Integer, nullable=True)
    ativa          = db.Column(db.Boolean, default=True)
    usuario_id     = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    criado_em      = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    @property
    def parcelas_geradas(self):
        return Conta.query.filter_by(conta_fixa_id=self.id).count()

    @property
    def label_recorrencia(self):
        labels = {
            'mensal': 'Mensal', 'bimestral': 'Bimestral',
            'trimestral': 'Trimestral', 'semestral': 'Semestral', 'anual': 'Anual'
        }
        return labels.get(self.recorrencia, self.recorrencia)

# Modelo de Conta
class Conta(db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    descricao       = db.Column(db.String(200), nullable=False)
    valor           = db.Column(MON, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    data_pagamento  = db.Column(db.Date, nullable=True)   # preenchida ao pagar
    paga            = db.Column(db.Boolean, default=False)
    categoria       = db.Column(db.String(50), default="Outros")
    usuario_id      = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    conta_fixa_id   = db.Column(db.Integer, db.ForeignKey('conta_fixa.id'), nullable=True)
    criado_em       = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    @property
    def dias_vencimento(self):
        hoje = datetime.today().date()
        return (self.data_vencimento - hoje).days

# Modelo: Item da lista de compras
class ItemLista(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    valor     = db.Column(MON, nullable=False)
    quantidade = db.Column(db.Integer, default=1, nullable=False)
    lista_id  = db.Column(db.Integer, db.ForeignKey('lista_compras.id'), nullable=False)

    @property
    def subtotal(self):
        return self.valor * self.quantidade

# Modelo: Lista de compras
class ListaCompras(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    titulo       = db.Column(db.String(100), nullable=False)
    data_criacao = db.Column(db.Date, nullable=False, default=datetime.today)
    finalizada   = db.Column(db.Boolean, default=False)
    usuario_id   = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    criado_em    = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    itens        = db.relationship('ItemLista', backref='lista', lazy=True, cascade="all, delete-orphan")

    @property
    def total(self):
        return sum(item.subtotal for item in self.itens) if self.itens else 0

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

def enviar_email(destinatario, assunto, corpo):
    try:
        msg = MIMEText(corpo, 'html')
        msg['Subject'] = assunto
        msg['From'] = os.getenv('EMAIL_FROM')
        msg['To'] = destinatario

        with smtplib.SMTP(os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))) as server:
            server.starttls()
            server.login(os.getenv('EMAIL_USER'), os.getenv('EMAIL_PASSWORD'))
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Erro ao enviar email: {str(e)}")
        return False

def verificar_alertas(usuario):
    # Verificar saldo total
    total_pago = db.session.query(func.sum(Conta.valor)).filter(
        Conta.paga == True,
        Conta.usuario_id == usuario.id
    ).scalar() or 0

    if usuario.limite_alerta and total_pago > usuario.limite_alerta:
        assunto = "⚠️ Alerta de Limite de Gastos"
        corpo = f"""
        <h3>Alerta de Limite de Gastos</h3>
        <p>Seus gastos totais ({format_currency(total_pago)}) excederam seu limite definido de {format_currency(usuario.limite_alerta)}!</p>
        <p>Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
        """
        enviar_email(usuario.email, assunto, corpo)
        flash('Limite de gastos excedido! Verifique seu email para detalhes.', 'warning')

def _e_mes_recorrente(cf, ano, mes):
    """Verifica se o mês/ano cai num ciclo válido da recorrência."""
    intervalos = {'mensal': 1, 'bimestral': 2, 'trimestral': 3, 'semestral': 6, 'anual': 12}
    intervalo = intervalos.get(cf.recorrencia, 1)
    if intervalo == 1:
        return True
    meses_diff = (ano - cf.data_inicio.year) * 12 + (mes - cf.data_inicio.month)
    return meses_diff % intervalo == 0

def gerar_contas_fixas(usuario_id):
    """Gera Contas a partir das ContaFixas ativas para o mês atual e o próximo."""
    hoje = datetime.today().date()
    # Meses a verificar: atual e próximo
    meses_alvo = []
    for delta in range(2):
        m = hoje.month + delta
        y = hoje.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        meses_alvo.append((y, m))

    contas_fixas = ContaFixa.query.filter_by(usuario_id=usuario_id, ativa=True).all()
    gerou = False

    for cf in contas_fixas:
        for ano, mes in meses_alvo:
            ultimo_dia = monthrange(ano, mes)[1]
            dia = min(cf.dia_vencimento, ultimo_dia)
            vencimento = date(ano, mes, dia)

            if vencimento < cf.data_inicio:
                continue
            if cf.data_fim and vencimento > cf.data_fim:
                continue
            if not _e_mes_recorrente(cf, ano, mes):
                continue

            # Verifica limite de parcelas
            if cf.parcelas_total:
                total_geradas = Conta.query.filter_by(conta_fixa_id=cf.id).count()
                if total_geradas >= cf.parcelas_total:
                    cf.ativa = False
                    db.session.flush()
                    break

            # Evita duplicatas
            if Conta.query.filter_by(conta_fixa_id=cf.id, data_vencimento=vencimento).first():
                continue

            nova = Conta(
                descricao=cf.descricao,
                valor=cf.valor,
                data_vencimento=vencimento,
                categoria=cf.categoria,
                paga=False,
                usuario_id=usuario_id,
                conta_fixa_id=cf.id
            )
            db.session.add(nova)
            gerou = True

    if gerou:
        db.session.commit()

def get_ai_client():
    """Retorna cliente Groq (gratuito) ou None se não configurado."""
    try:
        from groq import Groq
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            return None
        return Groq(api_key=api_key)
    except ImportError:
        return None

def contexto_financeiro(usuario_id):
    """Monta resumo dos dados financeiros do usuário para o prompt da IA."""
    hoje = datetime.today().date()

    total_pago = db.session.query(func.sum(Conta.valor)).filter(
        Conta.paga == True, Conta.usuario_id == usuario_id
    ).scalar() or 0

    total_pendente = db.session.query(func.sum(Conta.valor)).filter(
        Conta.paga == False, Conta.usuario_id == usuario_id
    ).scalar() or 0

    gastos_cat = db.session.query(
        Conta.categoria, func.sum(Conta.valor).label('total')
    ).filter(
        Conta.usuario_id == usuario_id, Conta.paga == True
    ).group_by(Conta.categoria).order_by(func.sum(Conta.valor).desc()).limit(10).all()

    proximas = Conta.query.filter(
        Conta.usuario_id == usuario_id,
        Conta.paga == False,
        Conta.data_vencimento >= hoje
    ).order_by(Conta.data_vencimento).limit(5).all()

    fixas = ContaFixa.query.filter_by(usuario_id=usuario_id, ativa=True).all()
    usuario = Usuario.query.get(usuario_id)

    linhas = [
        f"Usuário: {usuario.nome}",
        f"Data atual: {hoje.strftime('%d/%m/%Y')}",
        f"Saldo: {format_currency(usuario.saldo)}",
        f"Total pago (histórico): {format_currency(total_pago)}",
        f"Total pendente: {format_currency(total_pendente)}",
        "",
        "Gastos por categoria (pagos):",
    ]
    for cat, total in gastos_cat:
        linhas.append(f"  - {cat}: {format_currency(float(total))}")

    linhas += ["", "Próximas contas a pagar:"]
    for c in proximas:
        linhas.append(f"  - {c.descricao}: {format_currency(c.valor)} em {c.data_vencimento.strftime('%d/%m/%Y')}")

    if not proximas:
        linhas.append("  Nenhuma conta pendente")

    linhas += ["", "Compromissos mensais fixos:"]
    for cf in fixas:
        linhas.append(f"  - {cf.descricao}: {format_currency(cf.valor)} ({cf.label_recorrencia}, dia {cf.dia_vencimento})")

    if not fixas:
        linhas.append("  Nenhuma conta fixa cadastrada")

    return "\n".join(linhas)


# ────────────────────────────────────────────────────────────
# API: Chatbot IA
# ────────────────────────────────────────────────────────────

SYSTEM_CHAT = """Você é o MeVê Bot, assistente financeiro pessoal do MeVê Contas — app da empresa Me Vê Um Site.
Você tem acesso aos dados financeiros reais do usuário e responde SEMPRE em português brasileiro.
Seja direto, prático e levemente amigável. Use bullet points quando listar coisas.
Você pode ajudar com: análise de gastos, dicas de economia, planejamento, alertas de vencimento e perguntas gerais sobre finanças pessoais.
Nunca invente dados que não estejam no contexto fornecido. Se não souber algo, diga claramente.

DADOS FINANCEIROS DO USUÁRIO:
{contexto}"""

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    client = get_ai_client()
    if not client:
        return jsonify({'error': 'IA não configurada. Adicione GROQ_API_KEY nas variáveis de ambiente.'}), 503

    data = request.get_json(silent=True) or {}
    messages = data.get('messages', [])
    if not messages:
        return jsonify({'error': 'Mensagem vazia'}), 400

    messages = messages[-10:]  # limita histórico

    try:
        contexto = contexto_financeiro(current_user.id)
        completion = client.chat.completions.create(
            model='llama-3.1-8b-instant',
            max_tokens=600,
            messages=[
                {'role': 'system', 'content': SYSTEM_CHAT.format(contexto=contexto)},
                *messages
            ]
        )
        return jsonify({'response': completion.choices[0].message.content})
    except Exception as e:
        return jsonify({'error': f'Erro na IA: {str(e)}'}), 500


@app.route('/api/analise-ia', methods=['POST'])
@login_required
def api_analise_ia():
    client = get_ai_client()
    if not client:
        return jsonify({'error': 'IA não configurada. Adicione GROQ_API_KEY.'}), 503

    try:
        contexto = contexto_financeiro(current_user.id)
        completion = client.chat.completions.create(
            model='llama-3.3-70b-versatile',  # modelo maior para análise detalhada
            max_tokens=900,
            messages=[{
                'role': 'user',
                'content': f"""Analise os dados financeiros abaixo e responda em português com:

1. **Situação atual** — resumo em 2 linhas
2. **Pontos de atenção** — até 3 itens importantes
3. **Recomendações** — 3 ações práticas e específicas (com valores reais)
4. **Previsão do próximo mês** — estimativa baseada nos dados

Use os dados reais. Seja objetivo e direto.

{contexto}"""
            }]
        )
        return jsonify({'analise': completion.choices[0].message.content})
    except Exception as e:
        return jsonify({'error': f'Erro na IA: {str(e)}'}), 500


def gerar_grafico_categorias(usuario_id):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

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
    plt.savefig(buffer, format='png', bbox_inches='tight')
    plt.close()
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

    # Gastos mensais — usa CAST para compatibilidade com PostgreSQL
    gastos_mensais = db.session.query(
        func.date_trunc('month', Conta.data_vencimento).label('mes'),
        func.sum(Conta.valor).label('total')
    ).filter(
        Conta.usuario_id == usuario_id,
        Conta.paga == True
    ).group_by(func.date_trunc('month', Conta.data_vencimento))\
     .order_by(func.date_trunc('month', Conta.data_vencimento)).all()

    # Análise de recomendações
    recomendacoes = []
    if gastos_categoria:
        maior_categoria = gastos_categoria[0][0]
        recomendacoes.append(
            f"Seus maiores gastos são em '{maior_categoria}'. "
            "Considere revisar despesas nesta categoria."
        )

    if len(gastos_mensais) > 1:
        ultimo_mes = gastos_mensais[-1][1] or 0
        penultimo_mes = gastos_mensais[-2][1] or 0
        if penultimo_mes > 0 and ultimo_mes > penultimo_mes:
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
        confirmar_senha = request.form['confirmar_senha']
        
        if senha != confirmar_senha:
            flash('As senhas não coincidem!', 'danger')
            return redirect(url_for('registro'))

        if len(senha) < 6:
            flash('A senha deve ter pelo menos 6 caracteres!', 'danger')
            return redirect(url_for('registro'))

        if Usuario.query.filter_by(email=email).first():
            flash('Email já cadastrado!', 'danger')
            return redirect(url_for('registro'))
        
        # Validação básica de email
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Formato de email inválido!', 'danger')
            return redirect(url_for('registro'))
        
        novo_usuario = Usuario(
            nome=nome, 
            email=email,
            senha=generate_password_hash(senha)
        )
        db.session.add(novo_usuario)
        db.session.commit()
        
        flash('Registro realizado com sucesso! Faça login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'], error_message='Muitas tentativas. Aguarde 1 minuto.')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        usuario = Usuario.query.filter_by(email=email).first()

        if usuario and check_password_hash(usuario.senha, senha):
            login_user(usuario, remember=False)
            next_page = request.args.get('next')
            # evita open redirect — só permite URLs relativas
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('E-mail ou senha incorretos.', 'danger')

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ── Landing page ─────────────────────────────────────────
@app.route('/landing')
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('landing.html')

@app.route('/planos')
def planos():
    return render_template('planos.html')

# ── Stripe ───────────────────────────────────────────────
@app.route('/assinar/pro', methods=['POST'])
@login_required
def assinar_pro():
    try:
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        price_id = os.getenv('STRIPE_PRICE_ID')
        if not stripe.api_key or not price_id:
            flash('Pagamento não configurado ainda. Entre em contato.', 'warning')
            return redirect(url_for('planos'))
        checkout = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            success_url=url_for('sucesso_assinatura', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('planos', _external=True),
            customer_email=current_user.email,
            metadata={'usuario_id': str(current_user.id)},
        )
        return redirect(checkout.url, code=303)
    except Exception as e:
        flash(f'Erro ao iniciar pagamento: {str(e)}', 'danger')
        return redirect(url_for('planos'))

@app.route('/sucesso-assinatura')
@login_required
def sucesso_assinatura():
    flash('Assinatura Pro ativada com sucesso! Bem-vindo ao MeVê Contas Pro.', 'success')
    return render_template('sucesso_assinatura.html')

@app.route('/cancelar-assinatura', methods=['POST'])
@login_required
def cancelar_assinatura():
    try:
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        sub_id = current_user.stripe_subscription_id
        if sub_id:
            stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
        current_user.plano = 'gratuito'
        current_user.plano_expira_em = None
        db.session.commit()
        flash('Assinatura cancelada. Você volta ao plano gratuito.', 'info')
    except Exception as e:
        flash(f'Erro ao cancelar: {str(e)}', 'danger')
    return redirect(url_for('perfil'))

@app.route('/webhook/stripe', methods=['POST'])
@csrf.exempt
def webhook_stripe():
    try:
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        payload = request.get_data()
        sig = request.headers.get('Stripe-Signature', '')
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception:
        return '', 400

    data = event['data']['object']
    if event['type'] == 'checkout.session.completed':
        uid = int(data.get('metadata', {}).get('usuario_id', 0))
        u = Usuario.query.get(uid)
        if u:
            u.plano = 'pro'
            u.plano_expira_em = datetime.today().date() + timedelta(days=365)
            u.stripe_customer_id = data.get('customer')
            u.stripe_subscription_id = data.get('subscription')
            db.session.commit()
    elif event['type'] in ('customer.subscription.deleted',):
        sub = Usuario.query.filter_by(stripe_subscription_id=data.get('id')).first()
        if sub:
            sub.plano = 'gratuito'
            sub.plano_expira_em = None
            db.session.commit()
    return '', 200

# Rotas da Aplicação
@app.route('/')
def index():
    if not current_user.is_authenticated:
        return render_template('landing.html')

    total_pago = db.session.query(func.sum(Conta.valor)).filter(
        Conta.paga == True,
        Conta.usuario_id == current_user.id
    ).scalar() or 0
    
    total_pendente = db.session.query(func.sum(Conta.valor)).filter(
        Conta.paga == False,
        Conta.usuario_id == current_user.id
    ).scalar() or 0
    
    hoje = datetime.now().date()
    proximas_contas = Conta.query.filter(
        Conta.usuario_id == current_user.id,
        Conta.paga == False,
        Conta.data_vencimento >= hoje
    ).order_by(Conta.data_vencimento).limit(5).all()
    
    try:
        gerar_contas_fixas(current_user.id)
    except Exception:
        db.session.rollback()
    verificar_alertas(current_user)

    return render_template('index.html',
                         total_pago=format_currency(total_pago),
                         total_pendente=format_currency(total_pendente),
                         saldo=format_currency(current_user.saldo),
                         proximas_contas=proximas_contas,
                         format_currency=format_currency)

@app.route('/contas')
@login_required
def listar_contas():
    page = request.args.get('page', 1, type=int)
    contas = Conta.query.filter_by(usuario_id=current_user.id)\
                        .order_by(Conta.data_vencimento)\
                        .paginate(page=page, per_page=10)
    return render_template('listar_contas.html', contas=contas)

@app.route('/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_conta():
    if not check_limite(current_user, 'conta'):
        flash('Limite de 15 contas por mês atingido. Faça upgrade para o plano Pro.', 'warning')
        return redirect(url_for('planos'))
    if request.method == 'POST':
        descricao = request.form['descricao']
        valor = parse_brl_number(request.form['valor'])
        data_vencimento = datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
        categoria = request.form['categoria'] or "Outros"
        paga = 'paga' in request.form
        
        if valor is None or valor <= 0:
            flash('Valor inválido! Deve ser maior que zero.', 'danger')
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
        status_anterior = conta.paga
        
        conta.descricao = request.form['descricao']
        
        valor = parse_brl_number(request.form['valor'])
        if valor is None or valor <= 0:
            flash('Valor inválido!', 'danger')
            return render_template('editar_conta.html', conta=conta)
        
        conta.valor = valor
        conta.data_vencimento = datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
        conta.categoria = request.form['categoria'] or "Outros"
        
        nova_paga = 'paga' in request.form
        conta.paga = nova_paga
        
        # Ajuste do saldo
        if status_anterior and not nova_paga:  # De paga para não paga
            current_user.saldo += valor_anterior
        elif not status_anterior and nova_paga:  # De não paga para paga
            current_user.saldo -= valor
        elif status_anterior and nova_paga and valor != valor_anterior:
            current_user.saldo += (valor_anterior - valor)
        
        db.session.commit()
        verificar_alertas(current_user)
        flash('Conta atualizada com sucesso!', 'success')
        return redirect(url_for('listar_contas'))
    
    return render_template('editar_conta.html', conta=conta)

@app.route('/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_conta(id):
    conta = Conta.query.get_or_404(id)
    
    if conta.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_contas'))
    
    if conta.paga:
        current_user.saldo += conta.valor
    
    db.session.delete(conta)
    db.session.commit()
    flash('Conta excluída com sucesso!', 'success')
    return redirect(url_for('listar_contas'))

@app.route('/pagar/<int:id>', methods=['POST'])
@login_required
def pagar_conta(id):
    conta = Conta.query.get_or_404(id)
    
    if conta.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_contas'))
    
    if not conta.paga:
        conta.paga = True
        conta.data_pagamento = datetime.today().date()
        current_user.saldo -= conta.valor
        db.session.commit()
        verificar_alertas(current_user)
        flash('Conta marcada como paga!', 'success')
    else:
        flash('Esta conta já está paga', 'info')
    
    return redirect(url_for('listar_contas'))

# ────────────────────────────────────────────────────────────
# Rotas: Contas Fixas (recorrentes)
# ────────────────────────────────────────────────────────────

CATEGORIAS = [
    "Moradia", "Alimentação", "Transporte", "Saúde", "Educação",
    "Lazer", "Vestuário", "Tecnologia", "Assinaturas", "Serviços",
    "Impostos", "Investimentos", "Empréstimo", "Seguro", "Outros"
]

RECORRENCIAS = [
    ('mensal', 'Mensal'),
    ('bimestral', 'Bimestral (a cada 2 meses)'),
    ('trimestral', 'Trimestral (a cada 3 meses)'),
    ('semestral', 'Semestral (a cada 6 meses)'),
    ('anual', 'Anual'),
]

@app.route('/contas_fixas')
@login_required
def listar_contas_fixas():
    contas_fixas = ContaFixa.query.filter_by(usuario_id=current_user.id)\
                                  .order_by(ContaFixa.ativa.desc(), ContaFixa.dia_vencimento).all()
    total_mensal = sum(
        cf.valor for cf in contas_fixas
        if cf.ativa and cf.recorrencia == 'mensal'
    )
    return render_template('contas_fixas.html',
                           contas_fixas=contas_fixas,
                           total_mensal=total_mensal,
                           format_currency=format_currency)


@app.route('/contas_fixas/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_conta_fixa():
    if not check_limite(current_user, 'conta_fixa'):
        flash('Limite de 3 contas fixas atingido no plano gratuito. Faça upgrade para o Pro.', 'warning')
        return redirect(url_for('planos'))
    if request.method == 'POST':
        descricao = request.form['descricao'].strip()
        valor = parse_brl_number(request.form['valor'])
        categoria = request.form.get('categoria', 'Outros')
        dia = int(request.form['dia_vencimento'])
        recorrencia = request.form.get('recorrencia', 'mensal')
        data_inicio = datetime.strptime(request.form['data_inicio'], '%Y-%m-%d').date()

        data_fim = None
        if request.form.get('data_fim'):
            data_fim = datetime.strptime(request.form['data_fim'], '%Y-%m-%d').date()

        parcelas_total = None
        if request.form.get('parcelas_total'):
            try:
                parcelas_total = int(request.form['parcelas_total'])
            except ValueError:
                pass

        if not descricao:
            flash('Descrição obrigatória.', 'danger')
            return render_template('adicionar_conta_fixa.html', categorias=CATEGORIAS, recorrencias=RECORRENCIAS)
        if valor is None or valor <= 0:
            flash('Valor inválido.', 'danger')
            return render_template('adicionar_conta_fixa.html', categorias=CATEGORIAS, recorrencias=RECORRENCIAS)
        if not (1 <= dia <= 28):
            flash('Dia de vencimento deve ser entre 1 e 28.', 'danger')
            return render_template('adicionar_conta_fixa.html', categorias=CATEGORIAS, recorrencias=RECORRENCIAS)

        nova = ContaFixa(
            descricao=descricao,
            valor=valor,
            categoria=categoria,
            dia_vencimento=dia,
            recorrencia=recorrencia,
            data_inicio=data_inicio,
            data_fim=data_fim,
            parcelas_total=parcelas_total,
            usuario_id=current_user.id
        )
        db.session.add(nova)
        db.session.commit()
        gerar_contas_fixas(current_user.id)
        flash('Conta fixa cadastrada com sucesso!', 'success')
        return redirect(url_for('listar_contas_fixas'))

    return render_template('adicionar_conta_fixa.html', categorias=CATEGORIAS, recorrencias=RECORRENCIAS)


@app.route('/contas_fixas/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_conta_fixa(id):
    cf = ContaFixa.query.get_or_404(id)
    if cf.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_contas_fixas'))

    if request.method == 'POST':
        valor = parse_brl_number(request.form['valor'])
        dia = int(request.form['dia_vencimento'])

        if valor is None or valor <= 0:
            flash('Valor inválido.', 'danger')
            return render_template('adicionar_conta_fixa.html', cf=cf, categorias=CATEGORIAS, recorrencias=RECORRENCIAS)
        if not (1 <= dia <= 28):
            flash('Dia de vencimento deve ser entre 1 e 28.', 'danger')
            return render_template('adicionar_conta_fixa.html', cf=cf, categorias=CATEGORIAS, recorrencias=RECORRENCIAS)

        cf.descricao = request.form['descricao'].strip()
        cf.valor = valor
        cf.categoria = request.form.get('categoria', 'Outros')
        cf.dia_vencimento = dia
        cf.recorrencia = request.form.get('recorrencia', 'mensal')
        cf.data_inicio = datetime.strptime(request.form['data_inicio'], '%Y-%m-%d').date()
        cf.data_fim = datetime.strptime(request.form['data_fim'], '%Y-%m-%d').date() if request.form.get('data_fim') else None
        cf.parcelas_total = int(request.form['parcelas_total']) if request.form.get('parcelas_total') else None

        db.session.commit()
        gerar_contas_fixas(current_user.id)
        flash('Conta fixa atualizada!', 'success')
        return redirect(url_for('listar_contas_fixas'))

    return render_template('adicionar_conta_fixa.html', cf=cf, categorias=CATEGORIAS, recorrencias=RECORRENCIAS)


@app.route('/contas_fixas/toggle/<int:id>', methods=['POST'])
@login_required
def toggle_conta_fixa(id):
    cf = ContaFixa.query.get_or_404(id)
    if cf.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_contas_fixas'))
    cf.ativa = not cf.ativa
    db.session.commit()
    if cf.ativa:
        gerar_contas_fixas(current_user.id)
    status = 'ativada' if cf.ativa else 'pausada'
    flash(f'Conta fixa {status}.', 'success')
    return redirect(url_for('listar_contas_fixas'))


@app.route('/contas_fixas/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_conta_fixa(id):
    cf = ContaFixa.query.get_or_404(id)
    if cf.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_contas_fixas'))
    # Desvincula as contas geradas (não as exclui)
    Conta.query.filter_by(conta_fixa_id=cf.id).update({'conta_fixa_id': None})
    db.session.delete(cf)
    db.session.commit()
    flash('Conta fixa removida.', 'success')
    return redirect(url_for('listar_contas_fixas'))


# Rotas para listas de compras
@app.route('/listas_compras')
@login_required
def listar_listas_compras():
    page = request.args.get('page', 1, type=int)
    listas = ListaCompras.query.filter_by(usuario_id=current_user.id)\
                              .order_by(ListaCompras.data_criacao.desc())\
                              .paginate(page=page, per_page=5)
    return render_template('listar_listas_compras.html', listas=listas)

@app.route('/lista_compras/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_lista_compras():
    if not check_limite(current_user, 'lista'):
        flash('Limite de 2 listas de compras atingido no plano gratuito. Faça upgrade para o Pro.', 'warning')
        return redirect(url_for('planos'))
    if request.method == 'POST':
        titulo = request.form['titulo']
        
        nova_lista = ListaCompras(
            titulo=titulo,
            usuario_id=current_user.id
        )
        db.session.add(nova_lista)
        db.session.flush()
        
        # Processar itens
        descricoes = request.form.getlist('item_descricao[]')
        valores = request.form.getlist('item_valor[]')
        quantidades = request.form.getlist('item_quantidade[]')

        for i, desc in enumerate(descricoes):
            if desc.strip():
                valor = parse_brl_number(valores[i])
                if valor is None or valor <= 0:
                    flash(f'Valor inválido para o item: {desc}', 'danger')
                    db.session.rollback()
                    return render_template('adicionar_lista_compras.html')

                try:
                    qtd = int(quantidades[i]) if i < len(quantidades) else 1
                    qtd = max(1, qtd)
                except (ValueError, IndexError):
                    qtd = 1

                novo_item = ItemLista(
                    descricao=desc,
                    valor=valor,
                    quantidade=qtd,
                    lista_id=nova_lista.id
                )
                db.session.add(novo_item)
        
        if not nova_lista.itens:
            flash('Adicione pelo menos um item válido!', 'danger')
            db.session.rollback()
            return render_template('adicionar_lista_compras.html')
        
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
    
    return render_template('ver_lista_compras.html', lista=lista)

@app.route('/lista_compras/finalizar/<int:id>', methods=['POST'])
@login_required
def finalizar_lista_compras(id):
    lista = ListaCompras.query.get_or_404(id)
    
    if lista.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_listas_compras'))
    
    if not lista.finalizada:
        lista.finalizada = True
        current_user.saldo -= lista.total
        db.session.commit()
        flash(f'Lista finalizada! {format_currency(lista.total)} debitados do seu saldo.', 'success')
    else:
        flash('Esta lista já foi finalizada', 'info')
    
    return redirect(url_for('ver_lista_compras', id=id))

@app.route('/lista_compras/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_lista_compras(id):
    lista = ListaCompras.query.get_or_404(id)
    
    if lista.usuario_id != current_user.id:
        flash('Acesso não autorizado!', 'danger')
        return redirect(url_for('listar_listas_compras'))
    
    if lista.finalizada:
        current_user.saldo += lista.total
    
    db.session.delete(lista)
    db.session.commit()
    flash('Lista de compras excluída com sucesso!', 'success')
    return redirect(url_for('listar_listas_compras'))

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        acao = request.form.get('acao', 'dados')

        if acao == 'senha':
            senha_atual = request.form.get('senha_atual', '')
            nova_senha  = request.form.get('nova_senha', '')
            confirmar   = request.form.get('confirmar_nova', '')
            if not check_password_hash(current_user.senha, senha_atual):
                flash('Senha atual incorreta.', 'danger')
            elif len(nova_senha) < 6:
                flash('A nova senha deve ter pelo menos 6 caracteres.', 'danger')
            elif nova_senha != confirmar:
                flash('As senhas não coincidem.', 'danger')
            else:
                current_user.senha = generate_password_hash(nova_senha)
                db.session.commit()
                flash('Senha alterada com sucesso!', 'success')
            return redirect(url_for('perfil'))

        # Atualiza dados gerais
        novo_email = request.form.get('email', '').strip().lower()
        if novo_email != current_user.email:
            if not re.match(r"[^@]+@[^@]+\.[^@]+", novo_email):
                flash('E-mail inválido.', 'danger')
                return redirect(url_for('perfil'))
            if Usuario.query.filter(Usuario.email == novo_email, Usuario.id != current_user.id).first():
                flash('Este e-mail já está em uso.', 'danger')
                return redirect(url_for('perfil'))
            current_user.email = novo_email

        current_user.nome = request.form.get('nome', current_user.nome)[:100]

        try:
            current_user.limite_alerta = parse_brl_number(request.form['limite_alerta']) or 1000.0
            current_user.saldo         = parse_brl_number(request.form['saldo']) or 0.0
        except ValueError:
            flash('Formato de valor inválido! Use: 1.234,56', 'danger')
            return redirect(url_for('perfil'))

        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('perfil'))

    return render_template('perfil.html')

@app.route('/analise')
@login_required
def analise():
    dados = analisar_gastos(current_user.id)
    return render_template('analise.html', dados=dados, format_currency=format_currency)

# Context processor para injetar funções em todos os templates
@app.context_processor
def inject_utils():
    return {
        'now': datetime.now,
        'format_currency': format_currency,
        'timedelta': timedelta,
        'usuario_pro': usuario_pro,
    }

# Inicialização do banco de dados
def inicializar_banco():
    with app.app_context():
        db.create_all()
        # Migração: adiciona conta_fixa_id em conta e tabela conta_fixa se não existirem
        try:
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE conta ADD COLUMN IF NOT EXISTS conta_fixa_id "
                    "INTEGER REFERENCES conta_fixa(id) ON DELETE SET NULL"
                ))
                conn.commit()
        except Exception:
            pass
        print("Banco de dados inicializado!")

# Chamar a função durante a inicialização
if __name__ == '__main__':
    inicializar_banco()
    app.run(debug=True)