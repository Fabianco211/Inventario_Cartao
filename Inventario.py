from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import os
from datetime import datetime
from io import BytesIO


app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Configuração do banco PostgreSQL via variável de ambiente
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------------- Models ----------------
class Inventario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(50))
    data_inicio = db.Column(db.String(50))
    data_fim = db.Column(db.String(50))

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    nivel = db.Column(db.String(50))
    planta = db.Column(db.String(50))
    must_change = db.Column(db.Integer, default=0)

class Cartao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(100))
    titular = db.Column(db.String(100))
    status = db.Column(db.String(50))
    ultimo_inventario = db.Column(db.String(50))
    usuario_inventario = db.Column(db.String(100))
    planta = db.Column(db.String(50))

class HistoricoInventario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cartao_id = db.Column(db.Integer, db.ForeignKey('cartao.id'))
    numero = db.Column(db.String(100))
    status = db.Column(db.String(50))
    usuario = db.Column(db.String(100))
    data = db.Column(db.String(50))
    mes = db.Column(db.String(20))
    inventario_id = db.Column(db.Integer)
    planta = db.Column(db.String(50))

# ---------------- Inicialização do banco ----------------
with app.app_context():
    db.create_all()
    # Seed admin (se não existir)
    if not Usuario.query.filter_by(nome='admin', planta='1412').first():
        admin = Usuario(
            nome='admin',
            senha=generate_password_hash('admin123'),
            nivel='Admin',
            planta='1412',
            must_change=0
        )
        db.session.add(admin)
        db.session.commit()



# ---------------- Login manager ----------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    # Com SQLAlchemy, basta buscar pelo ID usando o model Usuario
    return Usuario.query.get(int(user_id))

# ---------------- Rotas ----------------
# ---------------- Auth routes ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        senha = request.form.get('senha', '').strip()
        planta = request.form.get('planta', '').strip()

        if not nome or not senha or not planta:
            flash('Informe nome, senha e planta.')
            return render_template('login.html')

        # Buscar usuário com ORM
        user = Usuario.query.filter_by(nome=nome, planta=planta).first()

        if not user:
            flash('Usuário não encontrado para a planta informada.')
            return render_template('login.html')

        # Verificar senha
        def is_hash(s):
            return isinstance(s, str) and (s.startswith('pbkdf2:') or s.startswith('scrypt:') or s.startswith('argon2:'))

        senha_bd = user.senha
        senha_ok = check_password_hash(senha_bd, senha) if is_hash(senha_bd) else (senha == senha_bd)
        if not senha_ok:
            flash('Senha incorreta.')
            return render_template('login.html')

        # Migrar senha em texto puro para hash
        if not is_hash(senha_bd):
            user.senha = generate_password_hash(senha)
            db.session.commit()

        # Login com Flask-Login
        login_user(user)
        session['planta'] = user.planta

        # Verificar se precisa trocar senha
        must_change = int(user.must_change or 0)
        if must_change == 1:
            flash('Por favor, troque sua senha para continuar.')
            return redirect(url_for('alterar_senha'))

        flash('Login realizado com sucesso!')
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()  # encerra a sessão do Flask-Login
    session.clear()  # limpa dados adicionais da sessão
    flash('Logout realizado com sucesso!')
    return redirect(url_for('login'))


# ---------------- Dashboard ----------------
@app.route('/', methods=['GET'])
@login_required
def dashboard():
    mes = request.args.get('mes') or datetime.now().strftime('%Y-%m')

    def get_counts(planta):
        ok = HistoricoInventario.query.filter_by(planta=planta).filter(
            HistoricoInventario.mes == mes,
            HistoricoInventario.status == 'OK'
        ).count()

        nao = HistoricoInventario.query.filter_by(planta=planta).filter(
            HistoricoInventario.mes == mes,
            HistoricoInventario.status.in_(['Não encontrado', 'Cartão não localizado no dia'])
        ).count()

        return ok, nao

    ok1412, nao1412 = get_counts('1412')
    ok1420, nao1420 = get_counts('1420')

    inv_qtd = Inventario.query.filter(
        Inventario.data_fim != None,
        Inventario.data_fim.like(f"{mes}%")
    ).count()

    return render_template(
        'dashboard.html',
        mes=mes,
        dados={'1412': {'ok': ok1412, 'nao': nao1412}, '1420': {'ok': ok1420, 'nao': nao1420}},
        inv_qtd=inv_qtd
        )


# ---------------- Inventário ----------------
@app.route('/inventario', methods=['GET', 'POST'])
@login_required
def inventario():
    inventario_ativo = Inventario.query.filter_by(status="Ativo").first()
    planta = session.get('planta')
    agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    mes_atual = datetime.now().strftime('%Y-%m')

    if request.method == 'POST':
        acao = request.form.get('acao')

        # INICIAR
        if acao == 'iniciar':
            if inventario_ativo:
                flash('Já existe um inventário ativo.')
                return redirect(url_for('inventario'))

            novo_inv = Inventario(status="Ativo", data_inicio=agora)
            db.session.add(novo_inv)
            Cartao.query.filter_by(planta=planta).update({"status": "Em inventário", "usuario_inventario": None})
            db.session.commit()

            flash('Inventário iniciado e cartões definidos como "Em inventário".')
            return redirect(url_for('inventario'))

        # REGISTRAR
        elif acao == 'registrar':
            numero = (request.form.get('numero') or '').strip()
            if not inventario_ativo:
                flash('Inicie o inventário antes de registrar.')
                return redirect(url_for('inventario'))
            if not numero:
                flash('Informe o número do cartão.')
                return redirect(url_for('inventario'))

            cartao = Cartao.query.filter_by(numero=numero, planta=planta).first()
            if not cartao:
                flash('Cartão não encontrado na base!')
                return redirect(url_for('inventario'))

            existe = HistoricoInventario.query.filter_by(cartao_id=cartao.id, inventario_id=inventario_ativo.id).first()

            cartao.status = "OK"
            cartao.ultimo_inventario = agora
            cartao.usuario_inventario = current_user.nome

            if not existe:
                hist = HistoricoInventario(
                    cartao_id=cartao.id,
                    numero=cartao.numero,
                    status="OK",
                    usuario=current_user.nome,
                    data=agora,
                    mes=mes_atual,
                    inventario_id=inventario_ativo.id,
                    planta=planta
                )
                db.session.add(hist)

            db.session.commit()
            flash(f'Cartão {numero} inventariado com sucesso!')
            return redirect(url_for('inventario'))

        # FINALIZAR
        elif acao == 'finalizar':
            if not inventario_ativo:
                flash('Não há inventário ativo para finalizar.')
                return redirect(url_for('inventario'))

            inventario_id = inventario_ativo.id
            faltantes = Cartao.query.filter_by(planta=planta).filter(
                ~Cartao.id.in_([h.cartao_id for h in HistoricoInventario.query.filter_by(inventario_id=inventario_id)])
            ).all()

            for c in faltantes:
                c.status = "Não encontrado"
                c.ultimo_inventario = agora
                c.usuario_inventario = current_user.nome

                hist = HistoricoInventario(
                    cartao_id=c.id,
                    numero=c.numero,
                    status="Não encontrado",
                    usuario=current_user.nome,
                    data=agora,
                    mes=mes_atual,
                    inventario_id=inventario_id,
                    planta=planta
                )
                db.session.add(hist)

            inventario_ativo.status = "Finalizado"
            inventario_ativo.data_fim = agora
            db.session.commit()

            flash(f'Inventário finalizado! {len(faltantes)} cartão(ões) marcado(s) como "Não encontrado".')
            return redirect(url_for('dashboard'))

        else:
            flash('Ação inválida.')
            return redirect(url_for('inventario'))

    # GET
    inventario_ativo = Inventario.query.filter_by(status="Ativo").first()
    cartoes = Cartao.query.filter_by(planta=planta).order_by(Cartao.numero).all()
    return render_template('inventario.html', inventario_ativo=inventario_ativo, cartoes=cartoes)

# ---------------- Cadastro de Cartões ----------------
@app.route('/cadastro-cartoes', methods=['GET', 'POST'])
@login_required
def cadastro_cartoes():
    if request.method == 'POST':
        planta = request.form.get('planta') or session.get('planta')

        # Upload de arquivo
        if 'file' in request.files and request.files['file'].filename != '':
            file = request.files['file']
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(filepath)
            try:
                if file.filename.lower().endswith('.csv'):
                    df = pd.read_csv(filepath)
                else:
                    df = pd.read_excel(filepath, engine='openpyxl')

                if 'numero' not in df.columns:
                    raise ValueError("Arquivo não possui a coluna obrigatória 'numero'.")
                if 'titular' not in df.columns:
                    df['titular'] = current_user.nome

                for _, row in df.iterrows():
                    numero = str(row['numero']).strip()
                    titular = str(row['titular']).strip() if pd.notna(row['titular']) else current_user.nome
                    if numero:
                        novo_cartao = Cartao(numero=numero, titular=titular, planta=planta)
                        db.session.add(novo_cartao)

                db.session.commit()
                flash('Cartões importados com sucesso!')
            except Exception as e:
                flash(f'Erro ao processar arquivo: {e}')
            return redirect(url_for('cadastro_cartoes'))

        # Colagem
        elif 'lista_cartoes' in request.form and request.form['lista_cartoes'].strip() != '':
            lista = request.form['lista_cartoes'].replace('\r', '').split('\n')
            for numero in lista:
                numero = numero.strip()
                if numero:
                    novo_cartao = Cartao(numero=numero, titular=current_user.nome, planta=planta)
                    db.session.add(novo_cartao)
            db.session.commit()
            flash('Cartões adicionados via colagem!')
            return redirect(url_for('cadastro_cartoes'))

        # Excluir
        elif 'excluir' in request.form:
            if current_user.nivel != 'Admin':
                flash('Ação não permitida: apenas Admin pode excluir cartões.')
            else:
                id_cartao = request.form['excluir']
                cartao = Cartao.query.get(id_cartao)
                if cartao:
                    db.session.delete(cartao)
                    db.session.commit()
                    flash('Cartão excluído com sucesso!')
            return redirect(url_for('cadastro_cartoes'))

    # GET
    cartoes = Cartao.query.filter_by(planta=session.get('planta')).order_by(Cartao.numero).all()
    return render_template('cadastro_cartoes.html', cartoes=cartoes)

# ---------------- Histórico ----------------
@app.route('/historico', methods=['GET'])
@login_required
def historico():
    mes = request.args.get('mes')
    planta = session.get('planta')

    # Consulta com ORM
    query = HistoricoInventario.query.filter_by(planta=planta)
    if mes:
        query = query.filter(HistoricoInventario.mes == mes)

    historico_rows = query.order_by(HistoricoInventario.data.desc()).all()

    # Meses disponíveis (distinct)
    meses_disponiveis = db.session.query(HistoricoInventario.mes).filter_by(planta=planta).distinct().order_by(HistoricoInventario.mes.desc()).all()
    meses_lista = [m[0] for m in meses_disponiveis]

    return render_template('historico.html', historico=historico_rows, mes=mes, meses_disponiveis=meses_lista)


# ---------------- Histórico Export ----------------
@app.route('/historico/export', methods=['GET'])
@login_required
def historico_export():
    mes = request.args.get('mes')
    planta = session.get('planta')

    # Consulta ORM com filtros
    query = HistoricoInventario.query.filter_by(planta=planta)
    if mes:
        query = query.filter(HistoricoInventario.mes == mes)

    # Ordenação
    historico_rows = query.order_by(HistoricoInventario.data.desc()).all()

    # Converter para DataFrame
    data = [
        {
            'id': row.id,
            'cartao_id': row.cartao_id,
            'numero': row.numero,
            'status': row.status,
            'usuario': row.usuario,
            'data': row.data,
            'mes': row.mes,
            'inventario_id': row.inventario_id,
            'planta': row.planta
        }
        for row in historico_rows
    ]
    df = pd.DataFrame(data)

    # Ajustar coluna data
    if 'data' in df.columns:
        df['data'] = pd.to_datetime(df['data'], errors='coerce')

    # Gerar arquivo Excel em memória
    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)

    # Nome do arquivo dinâmico
    nome_arquivo = f"historico_{mes or 'todos'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ---------------- Gestão de Usuários ----------------
@app.route('/gestao-usuarios', methods=['GET', 'POST'])
@login_required
def gestao_usuarios():
    if current_user.nivel != 'Admin':
        flash('Acesso negado! Somente Admin pode gerenciar usuários.')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # Adicionar usuário
        if 'adicionar' in request.form:
            nome = request.form.get('nome', '').strip()
            senha = request.form.get('senha', '').strip() or '123456'
            nivel = request.form.get('nivel', '').strip()
            planta = request.form.get('planta', '').strip() or session.get('planta')

            if not nome or not nivel:
                flash('Preencha nome e nível.')
                return redirect(url_for('gestao_usuarios'))

            existente = Usuario.query.filter_by(nome=nome, planta=planta).first()
            if existente:
                flash('Usuário já existe para esta planta.')
                return redirect(url_for('gestao_usuarios'))

            senha_hash = generate_password_hash(senha)
            novo_usuario = Usuario(nome=nome, senha=senha_hash, nivel=nivel, planta=planta, must_change=True)
            db.session.add(novo_usuario)
            db.session.commit()
            flash('Usuário cadastrado (troca de senha obrigatória no primeiro login).')
            return redirect(url_for('gestao_usuarios'))

        # Resetar senha
        if 'resetar' in request.form:
            id_usuario = request.form.get('resetar')
            usuario = Usuario.query.get(id_usuario)
            if usuario:
                usuario.senha = generate_password_hash('123456')
                usuario.must_change = True
                db.session.commit()
                flash('Senha resetada para 123456 (usuário deverá trocar no próximo login).')
            return redirect(url_for('gestao_usuarios'))

        # Editar usuário
        if 'editar' in request.form:
            id_usuario = request.form.get('editar')
            novo_nome = request.form.get('novo_nome', '').strip()
            novo_nivel = request.form.get('novo_nivel', '').strip()
            nova_planta = request.form.get('nova_planta', '').strip()

            if not novo_nome or not novo_nivel or not nova_planta:
                flash('Informe nome, nível e planta para editar.')
                return redirect(url_for('gestao_usuarios'))

            existente = Usuario.query.filter(
                Usuario.nome == novo_nome,
                Usuario.planta == nova_planta,
                Usuario.id != id_usuario
            ).first()
            if existente:
                flash('Já existe outro usuário com esse nome nessa planta.')
                return redirect(url_for('gestao_usuarios'))

            usuario = Usuario.query.get(id_usuario)
            if usuario:
                usuario.nome = novo_nome
                usuario.nivel = novo_nivel
                usuario.planta = nova_planta
                db.session.commit()
                flash('Usuário editado com sucesso!')
            return redirect(url_for('gestao_usuarios'))

        # Excluir usuário
        if 'excluir' in request.form:
            id_usuario = request.form.get('excluir')
            if str(current_user.id) == str(id_usuario):
                flash('Você não pode excluir seu próprio usuário.')
                return redirect(url_for('gestao_usuarios'))

            usuario = Usuario.query.get(id_usuario)
            if usuario:
                db.session.delete(usuario)
                db.session.commit()
                flash('Usuário excluído com sucesso!')
            return redirect(url_for('gestao_usuarios'))

    # GET: listar usuários
    usuarios = Usuario.query.order_by(Usuario.nome).all()
    return render_template('gestao_usuarios.html', usuarios=usuarios)


# ---------------- Alterar Senha (usuário) ----------------
@app.route('/alterar-senha', methods=['GET', 'POST'])
@login_required
def alterar_senha():
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual', '').strip()
        nova = request.form.get('nova', '').strip()
        confirmar = request.form.get('confirmar', '').strip()

        # Validações básicas
        if not senha_atual or not nova or not confirmar:
            flash('Preencha todos os campos.')
            return redirect(url_for('alterar_senha'))

        if nova != confirmar:
            flash('A confirmação não confere com a nova senha.')
            return redirect(url_for('alterar_senha'))

        if len(nova) < 6:
            flash('A nova senha deve ter pelo menos 6 caracteres.')
            return redirect(url_for('alterar_senha'))

        # Buscar usuário via ORM
        usuario = Usuario.query.get(current_user.id)
        if not usuario:
            flash('Usuário não encontrado.')
            return redirect(url_for('alterar_senha'))

        # Verificar senha atual
        atual_ok = check_password_hash(usuario.senha, senha_atual)
        if not atual_ok:
            flash('Senha atual incorreta.')
            return redirect(url_for('alterar_senha'))

        # Atualizar senha e remover flag must_change
        usuario.senha = generate_password_hash(nova)
        usuario.must_change = False
        db.session.commit()

        flash('Senha alterada com sucesso!')
        return redirect(url_for('dashboard'))

    return render_template('alterar_senha.html')

if __name__ == '__main__':
    app.run()
