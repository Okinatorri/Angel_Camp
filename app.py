import os
import json
import random
from datetime import datetime
from io import BytesIO

from flask import Flask, flash ,render_template, redirect, url_for, request, session, jsonify, send_file
import qrcode

app = Flask(__name__)
app.secret_key = 'your_secret_key'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, 'users.json')


# Загрузка/сохранение пользователей
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


# Главная
@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')

    users = load_users()
    login = session['user']
    username = users.get(login, {}).get('name', login)

    team_data = users.get('_team_scores', {
        "1": {"name": "Команда 1", "score": 0},
        "2": {"name": "Команда 2", "score": 0},
        "3": {"name": "Команда 3", "score": 0}
    })

    return render_template(
        'index.html',
        username=username,
        role=users[login]['role'],
        is_admin=users[login].get('is_admin', False),
        team_data=team_data
    )


# Админ-панель
@app.route('/admin')
def admin_panel():
    if 'user' not in session:
        return redirect('/login')

    users = load_users()
    username = session['user']

    if not users[username].get('is_admin', False):
        return '<h1>Доступ запрещен</h1>', 403

    teams = {'1': [], '2': [], '3': []}
    for uname, data in users.items():
        if uname.startswith('_'): continue
        role = data.get('role')
        if role in teams:
            teams[role].append(uname)

    team_data = users.get('_team_scores', {
        "1": {"name": "Команда 1", "score": 0},
        "2": {"name": "Команда 2", "score": 0},
        "3": {"name": "Команда 3", "score": 0}
    })

    return render_template(
        'admin.html',
        username=username,
        teams=teams,
        team_data=team_data
    )


# Вход/регистрация
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

        users = load_users()

        # --- Ограничение на кол-во в команде ---
        # Считаем, сколько пользователей уже в этой команде
        team_members_count = sum(1 for u, data in users.items()
                                 if not u.startswith('_') and data.get('role') == role)

        if team_members_count >= 35:
            error = f"В команде {role} уже 35 участников, регистрация закрыта."
            return render_template('login.html', error=error)

        # --- Запрет на создание 2 аккаунтов ---
        # Если такой username уже есть, проверяем пароль
        if username in users:
            if users[username]['password'] == password:
                session['user'] = username
                return redirect('/')
            else:
                error = 'Неверный пароль'
                return render_template('login.html', error=error)

        # Проверяем, не зарегистрирован ли пользователь под другим именем (запрет 2 аккаунтов)
        # Здесь можно проверить, например, по IP или другим данным, если есть.
        # Но без доп. данных это сложно. Можно добавить в users поле "email" и проверять по нему.
        # Если у тебя нет email или других идентификаторов, запретить создание другого аккаунта не получится.

        # Для упрощения считаем, что username уникален — этого достаточно

        # Создаем нового пользователя
        users[username] = {'password': password, 'role': role}
        save_users(users)
        session['user'] = username
        return redirect('/')

    return render_template('login.html', error=error)



# Выход
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')


# Крутилка
@app.route('/spin')
def spin():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    username = session['user']
    users = load_users()
    today_str = datetime.now().strftime('%Y-%m-%d')
    last_spin = users[username].get('last_spin', '')

    if last_spin == today_str:
        return jsonify({'error': 'Ви вже крутили сьогодні! Спробуйте взавтра.'}), 403

    result = random.choices(
        population=[1, 2, 3, 4, 5, 6, 7],
        weights=[5, 50, 5, 10, 10, 10, 10],
        k=1
    )[0]

    users[username]['last_spin'] = today_str

    if result == 2:
        verses_path = os.path.join(BASE_DIR, 'verses.json')
        try:
            with open(verses_path, encoding='utf-8') as f:
                verses_data = json.load(f)
                verses = verses_data.get('verses', [])
        except Exception as e:
            print("Ошибка загрузки verses.json:", e)
            verses = []

        if verses:
            verse = random.choice(verses)  # просто строка
        else:
            verse = "Стих не найден"

        role = users[username].get('role')
        if '_team_scores' not in users:
            users['_team_scores'] = {}
        if role not in users['_team_scores']:
            users['_team_scores'][role] = {'name': f'Команда {role}', 'score': 0}
        users['_team_scores'][role]['score'] += 1

        save_users(users)

        return jsonify({
            'result': result,
            'message': verse
        })

    if result == 6:
        role = users[username].get('role')
        if '_team_scores' not in users:
            users['_team_scores'] = {}
        if role not in users['_team_scores']:
            users['_team_scores'][role] = {'name': f'Команда {role}', 'score': 0}
        users['_team_scores'][role]['score'] += 1

    save_users(users)
    return jsonify({'result': result})



# Колесо (шаблон)
@app.route('/koles')
def koleso():
    if 'user' not in session:
        return redirect('/login')

    users = load_users()
    username = session['user']
    team_data = users.get('_team_scores', {})
    return render_template('koleso.html',
                           username=username,
                           role=users[username]['role'],
                           is_admin=users[username].get('is_admin', False),
                           team_data=team_data)


# Обновление счёта вручную (например из JS)
@app.route('/update_score', methods=['POST'])
def update_score():
    data = request.get_json()
    team_id = str(data['team_id'])
    delta = int(data['delta'])

    users = load_users()
    if '_team_scores' not in users:
        users['_team_scores'] = {}
    if team_id not in users['_team_scores']:
        users['_team_scores'][team_id] = {'name': f'Команда {team_id}', 'score': 0}

    users['_team_scores'][team_id]['score'] += delta
    save_users(users)
    return jsonify({'new_score': users['_team_scores'][team_id]['score']})


# QR-код для команды
@app.route('/qr/<team_id>')
def get_qr_code(team_id):
    base_url = request.url_root.rstrip('/')
    url = f"{base_url}/scan/{team_id}"

    qr = qrcode.make(url, image_factory=PilImage)  # ← фикс
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype='image/png')


# Сканирование QR — даёт 1 балл
@app.route('/scan/<qr_id>')
def scan_qr(qr_id):
    if 'user' not in session:
        return redirect('/login')

    user_login = session['user']
    users = load_users()

    if user_login not in users:
        flash("❌ Пользователь не найден", 'danger')
        return redirect('/')

    # Инициализация полей, если нет
    if 'used_qrs' not in users[user_login]:
        users[user_login]['used_qrs'] = []

    if '_team_scores' not in users:
        users['_team_scores'] = {}

    user_team = users[user_login].get('role')
    if not user_team:
        flash("❌ У пользователя не указана команда", 'danger')
        return redirect('/')

    if user_team not in users['_team_scores']:
        users['_team_scores'][user_team] = {'name': f'Команда {user_team}', 'score': 0}

    # Проверка: уже сканировал этот QR?
    if qr_id in users[user_login]['used_qrs']:
        flash("⚠️ Вы уже использовали этот QR-код!", 'warning')
        return redirect('/')

    # ✅ Увеличиваем балл ТОЛЬКО для команды пользователя
    users['_team_scores'][user_team]['score'] += 1
    users[user_login]['used_qrs'].append(qr_id)

    save_users(users)
    flash(f"✅ +1 балл команде {users['_team_scores'][user_team]['name']}", 'success')
    return redirect('/')





if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # на Render будет своя PORT, локально 5000
    app.run(host='0.0.0.0', port=port, debug=True)
