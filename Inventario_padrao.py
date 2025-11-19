
from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
import pandas as pd
import os
from datetime import datetime
from functools import wraps
from flask import abort


app = Flask(__name__)
app.secret_key = 'supersecretkey'
# Diretórios
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # garante a pasta de uploads
# Banco de dados (caminho absoluto para o ARQUIVO .db)
DB_NAME = os.path.join(BASE_DIR, 'database.db')
# Config do Flask
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT,
        data_inicio TEXT,
        data_fim TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT,
        senha TEXT,
        nivel TEXT,
        planta TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cartoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT,
        titular TEXT,
        status TEXT,
        ultimo_inventario TEXT,
        usuario_inventario TEXT,
        planta TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historico_inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cartao_id INTEGER,
        numero TEXT,
        status TEXT,
        usuario TEXT,
        data TEXT,
        mes TEXT,
        inventario_id INTEGER,
        planta TEXT,
        FOREIGN KEY(cartao_id) REFERENCES cartoes(id)
    )""")
    cursor.execute("SELECT * FROM usuarios WHERE nome='admin'")
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO usuarios (nome, senha, nivel, planta) VALUES ('admin', 'admin123', 'Admin', '1412')")
    conn.commit()
    conn.close()

init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, nome, nivel, planta):
        self.id = id
        self.nome = nome
        self.nivel = nivel
        self.planta = planta

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, nome, nivel, planta FROM usuarios WHERE id=?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return User(row[0], row[1], row[2], row[3]) if row else None
    #return None
def role_required(*roles):
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.nivel not in roles:
                # Você pode usar flash + redirect, mas abort 403 força a proteção no backend
                flash('Acesso negado para o seu nível de usuário.')
                return redirect(url_for('dashboard'))
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        senha = request.form.get('senha', '').strip()
        planta = request.form.get('planta', '').strip()

        if not nome or not senha or not planta:
            flash('Informe nome, senha e planta.')
            return render_template('login.html')

        conn = get_db_connection()
        try:
            user = conn.execute(
                'SELECT * FROM usuarios WHERE nome=? AND senha=? AND planta=?',
                (nome, senha, planta)
            ).fetchone()
        finally:
            conn.close()

        if user:
            login_user(User(user['id'], user['nome'], user['nivel'], user['planta']))
            session['planta'] = planta
            flash('Login realizado com sucesso!')
            return redirect(url_for('dashboard'))  # PRG
        else:
            flash('Credenciais inválidas ou planta incorreta')
            return render_template('login.html')

    # GET
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash('Logout realizado com sucesso!')
    return redirect(url_for('login'))

@app.route('/', methods=['GET'])
@login_required
def dashboard():
    # mês no formato YYYY-MM (ex.: '2025-11'); se não vier, usa mês atual
    mes = request.args.get('mes') or datetime.now().strftime("%Y-%m")

    conn = get_db_connection()
    try:
        def get_counts(planta):
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status='OK' THEN 1 ELSE 0 END) AS ok,
                    SUM(CASE WHEN status IN ('Não encontrado', 'Cartão não localizado no dia') THEN 1 ELSE 0 END) AS nao
                FROM historico_inventario
                WHERE planta=? AND strftime('%Y-%m', data)=?
                """,
                (planta, mes)
            ).fetchone()
            ok = row['ok'] if row and row['ok'] is not None else 0
            nao = row['nao'] if row and row['nao'] is not None else 0
            return ok, nao

        ok1412, nao1412 = get_counts('1412')
        ok1420, nao1420 = get_counts('1420')

        # Também podemos mostrar total de inventários concluídos no mês (opcional)
        inv_mes = conn.execute(
            "SELECT COUNT(1) AS qtd FROM inventario WHERE strftime('%Y-%m', data_fim)=?",
            (mes,)
        ).fetchone()
        inv_qtd = inv_mes['qtd'] if inv_mes else 0

        return render_template(
            'dashboard.html',
            mes=mes,
            dados={
                '1412': {'ok': ok1412, 'nao': nao1412},
                '1420': {'ok': ok1420, 'nao': nao1420},
            },
            inv_qtd=inv_qtd
        )
    finally:
        conn.close()

@app.route('/inventario', methods=['GET', 'POST'])
@login_required
def inventario():
    conn = get_db_connection()
    try:
        # Carrega inventário ativo no início
        inventario_ativo = conn.execute(
            'SELECT * FROM inventario WHERE status="Ativo"'
        ).fetchone()

        if request.method == 'POST':
            acao = request.form.get('acao')
            planta = session.get('planta')
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mes_atual = datetime.now().strftime("%Y-%m")

            # ---------------- INICIAR ----------------
            if acao == 'iniciar':
                if inventario_ativo:
                    flash('Já existe um inventário ativo.')
                    return redirect(url_for('inventario'))

                conn.execute(
                    'INSERT INTO inventario (status, data_inicio) VALUES ("Ativo", ?)',
                    (agora,)
                )
                # Ao iniciar, colocar todos os cartões como "Em inventário"
                conn.execute(
                    'UPDATE cartoes SET status=?, usuario_inventario=NULL WHERE planta=?',
                    ('Em inventário', planta)
                )
                conn.commit()
                flash('Inventário iniciado e cartões definidos como "Em inventário".')
                return redirect(url_for('inventario'))

            # ---------------- REGISTRAR ----------------
            elif acao == 'registrar':
                numero = (request.form.get('numero') or '').strip()
                if not inventario_ativo:
                    flash('Inicie o inventário antes de registrar.')
                    return redirect(url_for('inventario'))

                if not numero:
                    flash('Informe o número do cartão.')
                    return redirect(url_for('inventario'))

                cartao = conn.execute(
                    'SELECT * FROM cartoes WHERE numero=? AND planta=?',
                    (numero, planta)
                ).fetchone()
                if not cartao:
                    flash('Cartão não encontrado na base!')
                    return redirect(url_for('inventario'))

                # Evita duplicar registro no mesmo inventário
                existe = conn.execute(
                    'SELECT 1 FROM historico_inventario WHERE cartao_id=? AND inventario_id=?',
                    (cartao['id'], inventario_ativo['id'])
                ).fetchone()

                conn.execute(
                    'UPDATE cartoes SET status="OK", ultimo_inventario=?, usuario_inventario=? WHERE id=?',
                    (agora, current_user.nome, cartao['id'])
                )
                if not existe:
                    conn.execute(
                        'INSERT INTO historico_inventario '
                        '(cartao_id, numero, status, usuario, data, mes, inventario_id, planta) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (cartao['id'], cartao['numero'], 'OK', current_user.nome,
                         agora, mes_atual, inventario_ativo['id'], planta)
                    )
                conn.commit()
                flash(f'Cartão {numero} inventariado com sucesso!')
                return redirect(url_for('inventario'))

            # ---------------- FINALIZAR ----------------
            elif acao == 'finalizar':
                if not inventario_ativo:
                    flash('Não há inventário ativo para finalizar.')
                    return redirect(url_for('inventario'))

                inventario_id = inventario_ativo['id']

                # Cartões que NÃO receberam registro neste inventário
                faltantes = conn.execute(
                    '''
                    SELECT id, numero
                    FROM cartoes
                    WHERE planta=? AND id NOT IN (
                        SELECT cartao_id
                        FROM historico_inventario
                        WHERE inventario_id=?
                    )
                    ''',
                    (planta, inventario_id)
                ).fetchall()

                for c in faltantes:
                    conn.execute(
                        'UPDATE cartoes '
                        'SET status=?, ultimo_inventario=?, usuario_inventario=? '
                        'WHERE id=?',
                        ('Não encontrado', agora, current_user.nome, c['id'])
                    )
                    conn.execute(
                        'INSERT INTO historico_inventario '
                        '(cartao_id, numero, status, usuario, data, mes, inventario_id, planta) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (c['id'], c['numero'], 'Não encontrado', current_user.nome,
                         agora, mes_atual, inventario_id, planta)
                    )

                conn.execute(
                    'UPDATE inventario SET status="Finalizado", data_fim=? WHERE id=?',
                    (agora, inventario_id)
                )
                conn.commit()
                flash(f'Inventário finalizado! {len(faltantes)} cartão(ões) marcado(s) como "Não encontrado".')
                return redirect(url_for('dashboard'))

            # ---------------- AÇÃO INVÁLIDA ----------------
            else:
                flash('Ação inválida.')
                return redirect(url_for('inventario'))

        # ---------------- GET: render ----------------
        # Recarrega status do inventário ativo para o template
        inventario_ativo = conn.execute(
            'SELECT * FROM inventario WHERE status="Ativo"'
        ).fetchone()
        cartoes = conn.execute(
            'SELECT * FROM cartoes WHERE planta=? ORDER BY numero',
            (session.get('planta'),)
        ).fetchall()

        return render_template('inventario.html',
                               inventario_ativo=inventario_ativo,
                               cartoes=cartoes)
    finally:
        conn.close()

@app.route('/cadastro-cartoes', methods=['GET', 'POST'])
@login_required
def cadastro_cartoes():
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            planta = request.form.get('planta') or session.get('planta')

            # Importação (CSV/Excel)
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
                        titular = (str(row['titular']).strip()
                                   if pd.notna(row['titular']) else current_user.nome)
                        if numero:
                            conn.execute(
                                'INSERT INTO cartoes (numero, titular, planta) VALUES (?, ?, ?)',
                                (numero, titular, planta)
                            )
                    conn.commit()
                    flash('Cartões importados com sucesso!')
                except Exception as e:
                    flash(f'Erro ao processar arquivo: {e}')
                return redirect(url_for('cadastro_cartoes'))  # PRG

            # Colagem de lista
            elif 'lista_cartoes' in request.form and request.form['lista_cartoes'].strip() != '':
                lista = request.form['lista_cartoes'].replace('\r', '').split('\n')
                for numero in lista:
                    numero = numero.strip()
                    if numero:
                        conn.execute(
                            'INSERT INTO cartoes (numero, titular, planta) VALUES (?, ?, ?)',
                            (numero, current_user.nome, planta)
                        )
                conn.commit()
                flash('Cartões adicionados via colagem!')
                return redirect(url_for('cadastro_cartoes'))  # PRG

            # Exclusão – somente Admin
            elif 'excluir' in request.form:
                if current_user.nivel != 'Admin':
                    flash('Ação não permitida: apenas Admin pode excluir cartões.')
                else:
                    id_cartao = request.form['excluir']
                    conn.execute('DELETE FROM cartoes WHERE id=?', (id_cartao,))
                    conn.commit()
                    flash('Cartão excluído com sucesso!')
                return redirect(url_for('cadastro_cartoes'))  # PRG

        # GET: lista os cartões
        cartoes = conn.execute(
            'SELECT * FROM cartoes WHERE planta=?',
            (session.get('planta'),)
        ).fetchall()
        return render_template('cadastro_cartoes.html', cartoes=cartoes)
    finally:
        conn.close()

@app.route('/historico', methods=['GET'])
@login_required
def historico():
    mes = request.args.get('mes')  # formato esperado: 'YYYY-MM', ex.: '2025-11'
    conn = get_db_connection()
    try:
        params = [session.get('planta')]
        sql = "SELECT * FROM historico_inventario WHERE planta=?"

        # Se o usuário escolheu um mês, filtramos por 'YYYY-MM' extraído da coluna 'data'
        if mes:
            sql += " AND strftime('%Y-%m', data) = ?"
            params.append(mes)

        sql += " ORDER BY data DESC"
        historico = conn.execute(sql, params).fetchall()

        # Para popular o seletor com meses existentes (opcional, ajuda UX)
        meses_disponiveis = conn.execute(
            "SELECT DISTINCT strftime('%Y-%m', data) AS ym "
            "FROM historico_inventario WHERE planta=? ORDER BY ym DESC",
            (session.get('planta'),)
        ).fetchall()

        return render_template(
            'historico.html',
            historico=historico,
            mes=mes,
            meses_disponiveis=[row['ym'] for row in meses_disponiveis]
        )
    finally:
        conn.close()

@app.route('/historico/export', methods=['GET'])
@login_required
def historico_export():
    mes = request.args.get('mes')  # mesmo formato 'YYYY-MM'
    conn = get_db_connection()
    try:
        params = [session.get('planta')]
        sql = "SELECT id, cartao_id, numero, status, usuario, data, mes, inventario_id, planta " \
              "FROM historico_inventario WHERE planta=?"

        if mes:
            sql += " AND strftime('%Y-%m', data) = ?"
            params.append(mes)

        sql += " ORDER BY data DESC"

        # DataFrame direto do SQL
        df = pd.read_sql_query(sql, conn, params=params)

        # Garante tipos/datas legíveis (opcional)
        if 'data' in df.columns:
            df['data'] = pd.to_datetime(df['data'], errors='coerce')

        # Gera arquivo em memória
        from io import BytesIO
        output = BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)

        nome_arquivo = f"historico_{mes or 'todos'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return send_file(
            output,
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    finally:
        conn.close()

@app.route('/gestao-usuarios', methods=['GET', 'POST'])
@login_required
def gestao_usuarios():
    # Somente Admin
    if current_user.nivel != 'Admin':
        flash('Acesso negado! Somente Admin pode gerenciar usuários.')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    try:
        if request.method == 'POST':
            # Adicionar
            if 'adicionar' in request.form:
                nome = request.form.get('nome', '').strip()
                senha = request.form.get('senha', '').strip()
                nivel = request.form.get('nivel', '').strip()  # 'Admin' ou 'Operador'
                planta = request.form.get('planta', '').strip() or session.get('planta')

                if not nome or not senha or not nivel:
                    flash('Preencha nome, senha e nível.')
                    return redirect(url_for('gestao_usuarios'))

                # Evitar duplicados (por nome + planta)
                existente = conn.execute(
                    'SELECT 1 FROM usuarios WHERE nome=? AND planta=?',
                    (nome, planta)
                ).fetchone()
                if existente:
                    flash('Usuário já existe para esta planta.')
                    return redirect(url_for('gestao_usuarios'))

                conn.execute(
                    'INSERT INTO usuarios (nome, senha, nivel, planta) VALUES (?, ?, ?, ?)',
                    (nome, senha, nivel, planta)
                )
                conn.commit()
                flash('Usuário cadastrado com sucesso!')
                return redirect(url_for('gestao_usuarios'))

            # Resetar senha
            if 'resetar' in request.form:
                id_usuario = request.form.get('resetar')
                conn.execute('UPDATE usuarios SET senha="123456" WHERE id=?', (id_usuario,))
                conn.commit()
                flash('Senha resetada para 123456!')
                return redirect(url_for('gestao_usuarios'))

            # Editar
            if 'editar' in request.form:
                id_usuario = request.form.get('editar')
                novo_nome = request.form.get('novo_nome', '').strip()
                novo_nivel = request.form.get('novo_nivel', '').strip()
                nova_planta = request.form.get('nova_planta', '').strip()

                if not novo_nome or not novo_nivel or not nova_planta:
                    flash('Informe nome, nível e planta para editar.')
                    return redirect(url_for('gestao_usuarios'))

                # Bloquear duplicidade após edição (nome+planta)
                existente = conn.execute(
                    'SELECT 1 FROM usuarios WHERE nome=? AND planta=? AND id<>?',
                    (novo_nome, nova_planta, id_usuario)
                ).fetchone()
                if existente:
                    flash('Já existe outro usuário com esse nome nessa planta.')
                    return redirect(url_for('gestao_usuarios'))

                conn.execute(
                    'UPDATE usuarios SET nome=?, nivel=?, planta=? WHERE id=?',
                    (novo_nome, novo_nivel, nova_planta, id_usuario)
                )
                conn.commit()
                flash('Usuário editado com sucesso!')
                return redirect(url_for('gestao_usuarios'))

            # Excluir
            if 'excluir' in request.form:
                id_usuario = request.form.get('excluir')

                # Impedir que o admin apague a si mesmo (opcional, recomendável)
                if str(current_user.id) == str(id_usuario):
                    flash('Você não pode excluir seu próprio usuário enquanto está logado.')
                    return redirect(url_for('gestao_usuarios'))

                conn.execute('DELETE FROM usuarios WHERE id=?', (id_usuario,))
                conn.commit()
                flash('Usuário excluído com sucesso!')
                return redirect(url_for('gestao_usuarios'))

        # GET: lista usuários
        usuarios = conn.execute('SELECT * FROM usuarios').fetchall()
        return render_template('gestao_usuarios.html', usuarios=usuarios)
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)
