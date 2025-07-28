import os
import random
from datetime import datetime
from io import BytesIO

from flask import Flask, flash, render_template, redirect, url_for, request, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
import qrcode
from qrcode.image.pil import PilImage
import json

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your_secret_key")

# --- Настройки базы ---
DATABASE_URL = os.environ.get("DATABASE_URL") or "sqlite:///users.db"

if DATABASE_URL.startswith("postgresql://") and "sslmode" not in DATABASE_URL:
    if "?" in DATABASE_URL:
        DATABASE_URL += "&sslmode=require"
    else:
        DATABASE_URL += "?sslmode=require"

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False



db = SQLAlchemy(app)


# --- Модели ---

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    last_spin = db.Column(db.String(10), default="")  # формат YYYY-MM-DD
    used_qrs_json = db.Column(db.Text, default="[]")  # список использованных QR
    # Хранить очки команды здесь не будем, сделаем отдельной таблицей

    def get_used_qrs(self):
        try:
            return json.loads(self.used_qrs_json)
        except:
            return []

    def set_used_qrs(self, qrs_list):
        self.used_qrs_json = json.dumps(qrs_list)

class TeamScore(db.Model):
    __tablename__ = "team_scores"
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(64))
    score = db.Column(db.Integer, default=0)


class Log(db.Model):
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True)  # Может быть null, если системное действие
    username = db.Column(db.String(64), nullable=True)
    action = db.Column(db.String(128), nullable=False)
    result = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# --- Функции работы с пользователями и командами ---

def get_user_by_username(username):
    return User.query.filter_by(username=username).first()

def create_user(username, password, role, is_admin=False):
    user = User(username=username, password=password, role=role, is_admin=is_admin)
    db.session.add(user)
    db.session.commit()
    return user

def update_user(user):
    db.session.commit()

def get_team_score(team_id):
    team = TeamScore.query.filter_by(team_id=team_id).first()
    if not team:
        team = TeamScore(team_id=team_id, name=f"Команда {team_id}", score=0)
        db.session.add(team)
        db.session.commit()
    return team

def update_team_score(team_id, delta):
    team = get_team_score(team_id)
    team.score += delta
    db.session.commit()
    return team.score

def log_action(user, action, result=None):
    log = Log(user_id=user.id if user else None,
              username=user.username if user else None,
              action=action,
              result=result)
    db.session.add(log)
    db.session.commit()

# --- Роуты ---

@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')

    username = session['user']
    user = get_user_by_username(username)
    if not user:
        return redirect('/login')

    # Получаем очки команд (все 3)
    team_scores = TeamScore.query.all()
    team_data = {team.team_id: {'name': team.name, 'score': team.score} for team in team_scores}
    # Если какой-то команды нет, создадим
    for team_id in ['1','2','3']:
        if team_id not in team_data:
            ts = get_team_score(team_id)
            team_data[team_id] = {'name': ts.name, 'score': ts.score}

    return render_template('index.html',
                           username=user.username,
                           role=user.role,
                           is_admin=user.is_admin,
                           team_data=team_data)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', '').strip()

        if not username or not password or not role:
            error = 'Заполните все поля!'
            return render_template('login.html', error=error)

        user = get_user_by_username(username)

        if user:
            if user.password == password:
                session['user'] = username
                return redirect('/')
            else:
                error = 'Неверный пароль'
                return render_template('login.html', error=error)
        else:
            # Проверяем сколько пользователей в команде
            team_count = User.query.filter_by(role=role).count()
            if team_count >= 35:
                error = f"В команде {role} уже 35 участников, регистрация закрыта."
                return render_template('login.html', error=error)

            # Создаём нового пользователя
            create_user(username, password, role)
            session['user'] = username
            return redirect('/')

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')


@app.route('/spin')
def spin():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    username = session['user']
    user = get_user_by_username(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    today_str = datetime.now().strftime('%Y-%m-%d')
    if user.last_spin == today_str:
        return jsonify({'error': 'Вы уже крутили сегодня! Попробуйте завтра.'}), 403

    result = random.choices(
        population=[1, 2, 3, 4, 5, 6, 7],
        weights=[5, 50, 5, 10, 10, 10, 10],
        k=1
    )[0]

    user.last_spin = today_str

    if result == 2:
        verses_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verses.json')
        try:
            with open(verses_path, encoding='utf-8') as f:
                verses_data = json.load(f)
                verses = verses_data.get('verses', [])
        except Exception as e:
            verses = []

        verse = random.choice(verses) if verses else "Стих не найден"

        team = get_team_score(user.role)
        team.score += 1
        db.session.commit()

        update_user(user)
        log_action(user, 'spin', f"Выиграл балл +1 и стих: {verse}")

        return jsonify({'result': result, 'message': verse})

    if result == 6:
        team = get_team_score(user.role)
        team.score += 1
        db.session.commit()
        update_user(user)
        log_action(user, 'spin', "Выиграл балл +1")

    update_user(user)
    log_action(user, 'spin', f"Результат: {result}")

    return jsonify({'result': result})



@app.route('/logs')
def view_logs():
    if 'user' not in session:
        return redirect('/login')

    username = session['user']
    user = get_user_by_username(username)
    if not user or not user.is_admin:
        return "<h1>Доступ запрещён</h1>", 403

    logs = Log.query.order_by(Log.timestamp.desc()).limit(100).all()
    return render_template('logs.html', logs=logs)


def load_initial_data():
    """ Загружает данные из data.json, если база пустая """
    if not User.query.first():
        try:
            with open("users.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            for username, info in data.items():
                if username == "_team_scores":
                    for team_id, team_data in info.items():
                        if not TeamScore.query.filter_by(team_id=team_id).first():
                            team = TeamScore(
                                team_id=team_id,
                                name=team_data["name"],
                                score=team_data["score"]
                            )
                            db.session.add(team)
                else:
                    if not User.query.filter_by(username=username).first():
                        user = User(
                            username=username,
                            password=info["password"],
                            role=info["role"],
                            is_admin=info["is_admin"]
                        )
                        user.set_used_qrs(info.get("used_qrs", []))
                        db.session.add(user)

            db.session.commit()
            print("✅ Начальные данные успешно загружены")
        except Exception as e:
            print(f"❌ Ошибка при загрузке данных: {e}")


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    with app.app_context():
        db.create_all()
        load_initial_data()
    app.run(host='0.0.0.0', port=port, debug=True)
