from flask import (
    Flask, request, jsonify, send_from_directory, session,
    redirect, Response, url_for,
)
from pathlib import Path
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, re, os, io, json, csv, random, secrets, urllib.parse
import hashlib, base64
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "arktika.db"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 МБ на отдельный файл
MAX_TOTAL_SIZE = 60 * 1024 * 1024
ALLOWED_WORK = {"pdf", "docx"}
ALLOWED_PRESENTATION = {"pdf", "pptx"}
ALLOWED_VIDEO = {"mp4", "mov", "avi", "webm", "mkv"}

PROJECT_STATUSES = ["draft", "review", "accepted", "expertise", "evaluated"]
STATUS_LABELS = {
    "draft": "Черновик",
    "review": "На проверке",
    "accepted": "Допущена",
    "expertise": "На экспертизе",
    "evaluated": "Оценена",
}

QUIZ_QUESTION_COUNT = 10
QUIZ_TIME_LIMIT = 15 * 60  # 15 минут
QUIZ_PASS_RATIO = 0.6

ROLES = ["participant", "supervisor", "expert", "commission", "admin", "partner"]
ROLE_LABELS = {
    "participant": "Участник", "supervisor": "Руководитель", "expert": "Эксперт",
    "commission": "Член комиссии", "admin": "Администратор", "partner": "Партнёр",
}
# Роли, которые проходят модерацию регистрации оргкомитетом.
ROLES_REQUIRE_APPROVAL = {"supervisor", "expert", "commission", "partner"}
ROLE_HOME = {
    "participant": "/pages/cabinet.html",
    "supervisor": "/pages/supervisor.html",
    "expert": "/pages/expert.html",
    "admin": "/pages/admin.html",
}


def role_home(role):
    return ROLE_HOME.get(role, "/pages/cabinet.html")

app = Flask(__name__)
app.secret_key = os.environ.get("ARKTIKA_SECRET_KEY", "change-this-secret-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = MAX_TOTAL_SIZE
app.json.ensure_ascii = False

# Токены входа на вкладку. Хранятся в sessionStorage браузера, поэтому каждая
# вкладка имеет собственную сессию (обычная cookie-сессия общая для всех вкладок).
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

_token_serializer = URLSafeTimedSerializer(app.secret_key, salt="arktika-auth-token")
TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 дней


def make_auth_token(user_id):
    return _token_serializer.dumps({"uid": int(user_id)})


def parse_auth_token(token):
    try:
        data = _token_serializer.loads(token, max_age=TOKEN_MAX_AGE)
        return int(data.get("uid"))
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None


# VK ID (OAuth 2.1). Настоящая интеграция включается переменными окружения:
#   VK_CLIENT_ID      — ID приложения VK ID
#   VK_REDIRECT_URI   — адрес возврата, должен совпадать с настройками приложения
#   VK_SERVICE_TOKEN  — сервисный ключ (обязателен для конфиденциальных приложений)
#   VK_ID_BASE        — базовый адрес VK ID (по умолчанию https://id.vk.ru)
VK_CLIENT_ID = os.getenv("VK_CLIENT_ID", "")
VK_CLIENT_SECRET = os.getenv("VK_CLIENT_SECRET", "")
VK_SERVICE_TOKEN = os.getenv("VK_SERVICE_TOKEN", "")
VK_REDIRECT_URI = os.getenv("VK_REDIRECT_URI", "")
VK_ID_BASE = os.environ.get("VK_ID_BASE", "https://id.vk.ru").rstrip("/")
VK_SCOPE = os.environ.get("VK_SCOPE", "email")


def vk_enabled():
    """Настроен ли настоящий VK ID (иначе используется демонстрационный вход)."""
    return bool(VK_CLIENT_ID and VK_REDIRECT_URI)

print("VK_CLIENT_ID задан:", bool(VK_CLIENT_ID))
print("VK_REDIRECT_URI задан:", bool(VK_REDIRECT_URI))
print("VK ID включён:", vk_enabled())


# --------------------------------------------------------------------------- #
# База данных
# --------------------------------------------------------------------------- #
def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table, column, decl):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            school TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            school TEXT NOT NULL, password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_name TEXT NOT NULL, title TEXT NOT NULL,
            nomination TEXT NOT NULL, idea TEXT NOT NULL, file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS quiz_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_name TEXT, score INTEGER NOT NULL, total INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        /* --- Личный кабинет --- */
        CREATE TABLE IF NOT EXISTS supervisors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            teacher_name TEXT NOT NULL,
            teacher_email TEXT NOT NULL,
            organization TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            token TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            text TEXT NOT NULL,
            option_a TEXT NOT NULL, option_b TEXT NOT NULL,
            option_c TEXT NOT NULL, option_d TEXT NOT NULL,
            correct_option TEXT NOT NULL,
            explanation TEXT
        );
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            answers TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            duration_seconds INTEGER,
            passed INTEGER NOT NULL DEFAULT 0,
            certificate_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            attempt_id INTEGER,
            full_name TEXT,
            score INTEGER,
            total INTEGER,
            kind TEXT NOT NULL DEFAULT 'quiz',
            issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            expert_name TEXT,
            score INTEGER,
            criteria TEXT,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS vks_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_id INTEGER,
            title TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            join_link TEXT,
            room TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            description TEXT,
            score INTEGER,
            issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        /* --- Управление контентом (CMS) --- */
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, body TEXT NOT NULL, category TEXT,
            image TEXT, published INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'video',
            url TEXT, description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS banners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, text TEXT, link TEXT, cta TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        /* --- Управление конкурсом --- */
        CREATE TABLE IF NOT EXISTS stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, start_date TEXT, end_date TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            auto_advance INTEGER NOT NULL DEFAULT 0, order_index INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS nominations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, description TEXT,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS criteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, description TEXT,
            weight REAL NOT NULL DEFAULT 1, max_score REAL NOT NULL DEFAULT 10,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS expert_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expert_id INTEGER NOT NULL, project_id INTEGER NOT NULL,
            mode TEXT DEFAULT 'auto', status TEXT DEFAULT 'assigned',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(expert_id, project_id)
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL, expert_id INTEGER NOT NULL,
            total_score REAL, recommendation TEXT, comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP, UNIQUE(project_id, expert_id)
        );
        CREATE TABLE IF NOT EXISTS evaluation_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id INTEGER NOT NULL, criterion_id INTEGER NOT NULL,
            score REAL NOT NULL, comment TEXT
        );
        CREATE TABLE IF NOT EXISTS mailings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL, subject TEXT, body TEXT, audience TEXT,
            recipients_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL DEFAULT 'news', target_id INTEGER,
            author TEXT, body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Расширяем существующие таблицы дополнительными полями.
        for col, decl in [
            ("full_name", "TEXT"), ("birth_date", "TEXT"), ("grade", "TEXT"),
            ("region", "TEXT"), ("guardian_name", "TEXT"), ("guardian_contact", "TEXT"),
            ("role", "TEXT DEFAULT 'participant'"), ("vk_id", "TEXT"),
            ("email_verified", "INTEGER DEFAULT 0"),
            ("approval_status", "TEXT DEFAULT 'approved'"),
            ("consent_pdn", "INTEGER DEFAULT 0"), ("consent_at", "TEXT"),
            ("organization", "TEXT"), ("position", "TEXT"),
            ("expertise", "TEXT"), ("phone", "TEXT"),
        ]:
            ensure_column(conn, "users", col, decl)

        for col, decl in [
            ("user_id", "INTEGER"), ("abstract", "TEXT"),
            ("presentation_name", "TEXT"), ("video_url", "TEXT"),
            ("video_name", "TEXT"), ("status", "TEXT DEFAULT 'draft'"),
            ("updated_at", "TIMESTAMP"),
            ("supervisor_confirmed", "INTEGER DEFAULT 0"),
            ("supervisor_confirmed_at", "TIMESTAMP"),
        ]:
            ensure_column(conn, "projects", col, decl)

        ensure_column(conn, "supervisors", "supervisor_user_id", "INTEGER")
        ensure_column(conn, "questions", "difficulty", "TEXT DEFAULT 'средний'")

        seed_questions(conn)
        seed_reference(conn)


def seed_reference(conn):
    """Этапы, номинации, критерии, администратор и примеры контента."""
    if not conn.execute("SELECT COUNT(*) FROM criteria").fetchone()[0]:
        conn.executemany(
            "INSERT INTO criteria(name,description,weight,max_score,active) VALUES(?,?,?,?,1)",
            [
                ("Актуальность и новизна", "Соответствие тематике конкурса, оригинальность идеи.", 0.25, 10),
                ("Научная обоснованность", "Достоверность информации, корректность выводов.", 0.25, 10),
                ("Практическая значимость", "Возможность применения результатов на практике.", 0.20, 10),
                ("Качество оформления", "Соответствие работы требованиям к оформлению.", 0.15, 10),
                ("Защита работы", "Умение раскрыть суть работы и ответить на вопросы жюри.", 0.15, 10),
            ])
    if not conn.execute("SELECT COUNT(*) FROM nominations").fetchone()[0]:
        conn.executemany("INSERT INTO nominations(name,description,active) VALUES(?,?,1)",
                         [("Исследовательские работы", "Научно-исследовательские проекты"),
                          ("Творческие работы", "Творческие и художественные проекты"),
                          ("Просветительские проекты", "Просветительские и информационные проекты")])
    if not conn.execute("SELECT COUNT(*) FROM stages").fetchone()[0]:
        conn.executemany(
            """INSERT INTO stages(name,start_date,end_date,status,auto_advance,order_index)
               VALUES(?,?,?,?,?,?)""",
            [("I этап — Тестирование", "2026-09-01", "2026-10-31", "active", 1, 1),
             ("II этап — Проекты", "2026-10-01", "2026-12-15", "active", 1, 2),
             ("III этап — ВКС-защита", "2026-12-20", "2027-01-20", "planned", 0, 3)])
    if not conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]:
        conn.executemany(
            "INSERT INTO news(title,body,category,published) VALUES(?,?,?,?)",
            [("Старт нового сезона конкурса",
              "Открыт приём заявок на участие во Всероссийском конкурсе «Удивительная и неизведанная Арктика».", "Новости", 1),
             ("Объявлены номинации конкурса",
              "Уточнён список номинаций и критерии оценки конкурсных работ.", "Конкурс", 1)])
    if not conn.execute("SELECT COUNT(*) FROM banners").fetchone()[0]:
        conn.executemany(
            "INSERT INTO banners(title,text,link,cta,active) VALUES(?,?,?,?,1)",
            [("Прими участие в конкурсе", "Пройди тестирование и подай проект до 15 декабря.",
              "/pages/auth.html#register", "Регистрация")])
    if not conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]:
        conn.executemany(
            "INSERT INTO media(title,kind,url,description) VALUES(?,?,?,?)",
            [("Документальный фильм об Арктике", "video", "https://vk.com/video",
              "Видео о природе Арктики и белом медведе.")])
    admin_email = os.environ.get("ARKTIKA_ADMIN_EMAIL", "admin@arctic.local")
    admin_pass = os.environ.get("ARKTIKA_ADMIN_PASSWORD", "admin12345")
    if not conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        conn.execute(
            """INSERT OR IGNORE INTO users(name,email,school,password_hash,role,
               approval_status,consent_pdn,consent_at,full_name)
               VALUES(?,?,?,?, 'admin','approved',1,CURRENT_TIMESTAMP,?)""",
            ("Администратор", admin_email, "Оргкомитет конкурса",
             generate_password_hash(admin_pass), "Администратор"))


QUESTION_BANK = [
    ("Белый медведь", "Где чаще всего рождают белые медведи?",
     ["На льду открытого моря", "На Медвежьих островах", "В горах Чукотки", "В сибирской тайге"], "b",
     "Медвежьи острова в Якутии — одно из важнейших мест рождения белых медведей."),
    ("Белый медведь", "Главная особенность белого медведя — это…",
     ["Способность жить в пустыне", "Белый мех и адаптация к холоду", "Умение летать", "Обитание в тропиках"], "b",
     "Белый мех и толстый слой жира помогают медведю выживать в Арктике."),
    ("Белый медведь", "Чем в основном питается белый медведь?",
     ["Рыбой и тюленями", "Ягодами", "Травой", "Насекомыми"], "a",
     "Основа рациона — тюлени, а также рыба и падаль."),
    ("Белый медведь", "Почему белый медведь занесён в Красную книгу?",
     ["Он слишком крупный", "Его численность сокращается", "Он живёт только в зоопарках", "Он опасен для людей"], "b",
     "Сокращение льдов и браконьерство снижают численность вида."),
    ("Белый медведь", "Какой заповедник создан для охраны белых медведей в Якутии?",
     ["«Медвежьи острова»", "«Ленские столбы»", "«Остров Врангеля»", "«Таймырский»"], "a",
     "Государственный заповедник «Медвежьи острова» создан в 2020 году."),
    ("Арктическая природа", "Какой океан омывает Арктику?",
     ["Северный Ледовитый", "Тихий", "Атлантический", "Индийский"], "a",
     "Арктику омывает Северный Ледовитый океан."),
    ("Арктическая природа", "Что такое тундра?",
     ["Тропический лес", "Природная зона с низкорослой растительностью", "Пустыня", "Лесостепь"], "b",
     "В тундре нет высоких деревьев из-за вечной мерзлоты и холода."),
    ("Арктическая природа", "Какое явление называют северным сиянием?",
     ["Радуга над морем", "Свечение в атмосфере", "Туман", "Миражи"], "b",
     "Северное сияние — свечение верхних слоёв атмосферы."),
    ("Арктическая природа", "Что такое многолетняя мерзлота?",
     ["Слой почвы, который не оттаивает годами", "Ледник на вершине горы", "Зимний снег", "Замёрзшее озеро"], "a",
     "Мерзлота — промёрзший грунт, сохраняющийся много лет."),
    ("Арктическая природа", "Что такое айсберг?",
     ["Плавучая ледяная гора", "Морское течение", "Вид рыбы", "Горная вершина"], "a",
     "Айсберг — крупная плавающая часть ледника."),
    ("Арктическая природа", "Какое растение встречается в тундре?",
     ["Баобаб", "Карликовая берёза", "Пальма", "Бамбук"], "b",
     "Карликовая берёза — типичное растение тундры."),
    ("Арктическая природа", "Что такое полярная ночь?",
     ["Ночь длиной в сутки весь год", "Период, когда солнце не появляется над горизонтом", "Затмение", "Ночь у экватора"], "b",
     "Зимой за Полярным кругом солнце не встаёт из-за горизонта."),
    ("Северный морской путь", "Северный морской путь — это…",
     ["Торговый маршрут вдоль севера России", "Дорога через пустыню", "Тропа через Гималаи", "Маршрут по Волге"], "a",
     "СМП соединяет европейскую часть России и Дальний Восток."),
    ("Северный морской путь", "Какое судно первым прошло Севморпуть за одну навигацию?",
     ["«Ленин»", "«Сибиряков»", "«Титаник»", "«Ермак»"], "b",
     "Ледокольный пароход «Александр Сибиряков» сделал это в 1932 году."),
    ("Северный морской путь", "Сколько морей проходит Северный морской путь?",
     ["Одно", "Несколько арктических морей", "Ни одного", "Только Чёрное"], "b",
     "Маршрут проходит через ряд арктических морей."),
    ("Экология Арктики", "Что является главной угрозой для Арктики?",
     ["Глобальное потепление и загрязнение", "Избыток снега", "Полярные животные", "Северное сияние"], "a",
     "Таяние льдов и загрязнение — ключевые угрозы."),
    ("Экология Арктики", "Какой газ усиливает таяние арктических льдов?",
     ["Углекислый газ", "Кислород", "Азот", "Гелий"], "a",
     "Углекислый газ — парниковый газ, усиливающий потепление."),
    ("Экология Арктики", "Как школьник может помочь Арктике?",
     ["Выбросить мусор в море", "Распространять экологические знания", "Разжечь костёр на мху", "Ловить краснокнижных животных"], "b",
     "Распространение знаний и бережное отношение к природе помогают сохранить Арктику."),
    ("История и география", "Какая зона России называется арктической?",
     ["Районы севернее Полярного круга", "Только Краснодарский край", "Республика Крым", "Средняя полоса"], "a",
     "Арктическая зона — территории севернее Полярного круга."),
    ("История и география", "Какой архипелаг — крупнейший в российской Арктике?",
     ["Новая Земля", "Соловецкие острова", "Курилы", "Сахалин"], "a",
     "Новая Земля — один из крупнейших арктических архипелагов России."),
]


def seed_questions(conn):
    count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    if count:
        return
    for topic, text, options, correct, explanation in QUESTION_BANK:
        conn.execute(
            """INSERT INTO questions(topic,text,option_a,option_b,option_c,option_d,correct_option,explanation)
               VALUES(?,?,?,?,?,?,?,?)""",
            (topic, text, options[0], options[1], options[2], options[3], correct, explanation),
        )


# --------------------------------------------------------------------------- #
# Вспомогательные функции
# --------------------------------------------------------------------------- #
def text_field(value, label, limit=3000, required=True):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"Заполни поле «{label}».")
        return ""
    if not isinstance(value, str):
        raise ValueError(f"Поле «{label}» заполнено неверно.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"Поле «{label}» слишком длинное.")
    return value


def current_user():
    token = request.headers.get("X-Auth-Token")
    if not token:
        return None
    uid = parse_auth_token(token)
    if not uid:
        return None
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def require_login():
    user = current_user()
    if not user:
        return None, (jsonify(error="Требуется вход в личный кабинет."), 401)
    return user, None


def require_roles(*roles):
    """Возвращает (user, None) если роль подходит, иначе (None, (ответ, код))."""
    user, err = require_login()
    if err:
        return None, err
    if user["role"] not in roles:
        return None, (jsonify(error="Недостаточно прав для этого раздела."), 403)
    if user["approval_status"] == "blocked":
        return None, (jsonify(error="Аккаунт заблокирован."), 403)
    return user, None


def ext_of(filename):
    name = (filename or "").strip().replace("\\", "/")
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def save_upload(file_storage, allowed, max_size=MAX_FILE_SIZE):
    """Сохраняет файл, проверяя расширение и размер. Возвращает сохранённое имя."""
    if not file_storage or not file_storage.filename:
        return None
    original = file_storage.filename
    ext = ext_of(original)
    if ext not in allowed:
        raise ValueError(f"Недопустимый формат файла. Разрешены: {', '.join(sorted(allowed)).upper()}.")
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > max_size:
        raise ValueError(f"Файл «{original}» больше {max_size // (1024 * 1024)} МБ.")
    # secure_filename может обрезать кириллицу, поэтому безопасное имя формируем
    # отдельно, а расширение берём из исходного имени файла.
    stem = secure_filename(original.rsplit(".", 1)[0]) or "file"
    saved = f"{secrets.token_hex(8)}_{stem}.{ext}"
    file_storage.save(UPLOAD_DIR / saved)
    return saved


def profile_complete(user):
    return bool(user["full_name"] and user["birth_date"] and user["grade"] and user["region"])


def user_public(user):
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "full_name": user["full_name"],
        "birth_date": user["birth_date"],
        "grade": user["grade"],
        "school": user["school"],
        "region": user["region"],
        "guardian_name": user["guardian_name"],
        "guardian_contact": user["guardian_contact"],
        "organization": user["organization"],
        "position": user["position"],
        "expertise": user["expertise"],
        "phone": user["phone"],
        "role": user["role"],
        "role_label": ROLE_LABELS.get(user["role"], user["role"]),
        "approval_status": user["approval_status"],
        "consent_pdn": bool(user["consent_pdn"]),
        "vk_id": user["vk_id"],
        "email_verified": bool(user["email_verified"]),
        "profile_complete": profile_complete(user),
        "home": role_home(user["role"]),
    }


def log_email(to, subject, body):
    """Отправляет письмо через SMTP, если настроен; иначе сохраняет его в outbox."""
    import smtplib
    from email.message import EmailMessage

    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", username).strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = os.environ.get("SMTP_SSL", "0").lower() in ("1", "true", "yes")

    if host and sender:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.ehlo()
                if os.environ.get("SMTP_STARTTLS", "1").lower() not in ("0", "false", "no"):
                    smtp.starttls()
                    smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
        app.logger.info("EMAIL SENT -> %s: %s", to, subject)
        return "sent"

    outbox = BASE_DIR / "outbox"
    outbox.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", to)
    path = outbox / f"{stamp}_{safe}.txt"
    path.write_text(f"Кому: {to}\nТема: {subject}\n\n{body}\n", encoding="utf-8")
    app.logger.warning("SMTP не настроен; письмо сохранено в outbox для %s: %s", to, subject)
    return "queued"


# --------------------------------------------------------------------------- #
# Сертификаты, дипломы, QR
# --------------------------------------------------------------------------- #
def certificate_number():
    return f"ARK-{datetime.now().year}-{secrets.token_hex(3).upper()}"


def qr_png(data):
    import qrcode
    qr = qrcode.QRCode(box_size=6, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a4d80", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def register_fonts():
    """Подбирает TTF-шрифт с поддержкой кириллицы."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [
        ("Arial", "C:/Windows/Fonts/arial.ttf", "Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"),
        ("DejaVu", "C:/Windows/Fonts/DejaVuSans.ttf", "DejaVu-Bold", "C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
        ("Segoe", "C:/Windows/Fonts/segoeui.ttf", "Segoe-Bold", "C:/Windows/Fonts/segoeuib.ttf"),
    ]
    for reg_name, reg_path, bold_name, bold_path in candidates:
        if os.path.exists(reg_path):
            pdfmetrics.registerFont(TTFont(reg_name, reg_path))
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
                return reg_name, bold_name
            return reg_name, reg_name
    return "Helvetica", "Helvetica-Bold"


AWARD_TITLES = {
    "certificate": "СЕРТИФИКАТ УЧАСТНИКА",
    "diploma": "ДИПЛОМ",
    "thanks": "БЛАГОДАРНОСТЬ",
    "supervisor": "СЕРТИФИКАТ РУКОВОДИТЕЛЯ",
    "expert": "СЕРТИФИКАТ ЭКСПЕРТА",
}


def render_award_pdf(kind, full_name, subtitle, number, issued, verify_url, score=None):
    """Генерирует PDF-награду (сертификат/диплом/благодарность) с QR-кодом."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    font, font_bold = register_fonts()
    buf = io.BytesIO()
    width, height = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(width, height))

    # Рамка
    c.setStrokeColorRGB(0.10, 0.30, 0.50)
    c.setLineWidth(6)
    c.rect(24, 24, width - 48, height - 48)
    c.setStrokeColorRGB(1.0, 0.42, 0.21)
    c.setLineWidth(1.5)
    c.rect(36, 36, width - 72, height - 72)

    c.setFillColorRGB(0.10, 0.30, 0.50)
    c.setFont(font_bold, 16)
    c.drawCentredString(width / 2, height - 90, "Удивительная и неизведанная Арктика")
    c.setFont(font, 11)
    c.drawCentredString(width / 2, height - 110, "Всероссийский конкурс")

    c.setFont(font_bold, 34)
    c.drawCentredString(width / 2, height - 175, AWARD_TITLES.get(kind, "НАГРАДА"))

    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont(font, 14)
    c.drawCentredString(width / 2, height - 215, "награждается")

    c.setFillColorRGB(0.10, 0.30, 0.50)
    c.setFont(font_bold, 26)
    c.drawCentredString(width / 2, height - 260, full_name or "Участник")

    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont(font, 13)
    for i, line in enumerate([subtitle]):
        c.drawCentredString(width / 2, height - 300 - i * 20, line)
    if score is not None:
        c.drawCentredString(width / 2, height - 320, f"Результат: {score}")

    # QR-код с проверкой подлинности
    qr_buf = qr_png(verify_url)
    qr_img = ImageReader(qr_buf)
    c.drawImage(qr_img, 70, 70, width=120, height=120)
    c.setFont(font, 8)
    c.drawString(70, 58, "Проверка подлинности:")
    c.drawString(70, 48, verify_url)

    c.setFont(font, 11)
    c.drawCentredString(width / 2, 90, f"Номер документа: {number}")
    c.drawCentredString(width / 2, 72, f"Дата выдачи: {issued}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


# --------------------------------------------------------------------------- #
# Базовые / служебные маршруты
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/api/health")
def health():
    return jsonify(status="ok", message="Backend работает")


@app.get("/api/stats")
def stats():
    """Публичная статистика из текущей базы данных."""
    with db() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "role" in columns:
            # Считаем именно участников, не включая администраторов, экспертов и руководителей.
            users_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'participant'").fetchone()[0]
        else:
            users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        projects_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        lessons_count = len(list((BASE_DIR / "education").glob("lesson*.html")))
    return jsonify(users=users_count, participants=users_count, projects=projects_count, lessons=lessons_count)


# --------------------------------------------------------------------------- #
# Аутентификация
# --------------------------------------------------------------------------- #
@app.post("/api/register")
def register():
    """Публичная регистрация (совместимость со старым API)."""
    data = request.get_json(silent=True) or {}
    try:
        name = text_field(data.get("name"), "Имя", 100)
        email = text_field(data.get("email"), "Email", 254).lower()
        school = text_field(data.get("school"), "Школа", 150)
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return jsonify(error="Введи корректный email."), 400
        with db() as conn:
            cur = conn.execute("INSERT INTO participants(name,email,school) VALUES(?,?,?)",
                               (name, email, school))
            pid = cur.lastrowid
        return jsonify(message="Регистрация прошла успешно.", participant_id=pid), 201
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except sqlite3.IntegrityError:
        return jsonify(error="Этот email уже зарегистрирован."), 409


@app.post("/api/auth/register")
def auth_register():
    data = request.get_json(silent=True) or {}
    role = data.get("role", "participant")
    if role not in ("participant", "supervisor", "expert"):
        role = "participant"
    try:
        name = text_field(data.get("name"), "Имя и фамилия", 150)
        email = text_field(data.get("email"), "Email", 254).lower()
        password = data.get("password", "")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return jsonify(error="Введи корректный email."), 400
        if not isinstance(password, str) or len(password) < 8:
            return jsonify(error="Пароль должен содержать минимум 8 символов."), 400
        if not data.get("consent_pdn"):
            return jsonify(error="Необходимо согласие на обработку персональных данных (152-ФЗ)."), 400

        if role == "participant":
            school = text_field(data.get("school"), "Школа", 150)
            organization, position, expertise = None, None, None
            grade = (data.get("grade") or None)
            region = (data.get("region") or None)
        else:
            organization = text_field(data.get("organization"), "Организация", 200)
            position = text_field(data.get("position"), "Должность", 150)
            school = organization
            grade, region = None, None
            expertise = (data.get("expertise") or None) if role == "expert" else None

        approval = "pending" if role in ROLES_REQUIRE_APPROVAL else "approved"
        with db() as conn:
            cur = conn.execute(
                """INSERT INTO users(name,email,school,password_hash,full_name,grade,region,role,
                   approval_status,consent_pdn,consent_at,organization,position,expertise)
                   VALUES(?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP,?,?,?)""",
                (name, email, school, generate_password_hash(password), name, grade, region,
                 role, approval, organization, position, expertise),
            )
            uid = cur.lastrowid
            conn.execute("INSERT OR IGNORE INTO participants(name,email,school) VALUES(?,?,?)",
                         (name, email, school))
            if role == "supervisor":
                # Связываем уже добавленных этим email участников с новым кабинетом руководителя.
                conn.execute(
                    "UPDATE supervisors SET supervisor_user_id=? WHERE lower(teacher_email)=?",
                    (uid, email))
        msg = "Регистрация прошла успешно."
        if approval == "pending":
            msg += " Заявка отправлена на модерацию оргкомитету."
        return jsonify(message=msg, name=name, role=role,
                       approval_status=approval, token=make_auth_token(uid),
                       redirect=role_home(role)), 201
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except sqlite3.IntegrityError:
        return jsonify(error="Этот email уже зарегистрирован."), 409


@app.post("/api/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "")
    password = data.get("password", "")
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error="Проверь email и пароль."), 400
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Неверный email или пароль."), 401
    if user["approval_status"] == "blocked":
        return jsonify(error="Аккаунт заблокирован. Обратитесь к оргкомитету."), 403
    return jsonify(message="Вход выполнен.", name=user["name"], role=user["role"],
                   token=make_auth_token(user["id"]),
                   redirect=role_home(user["role"]))


@app.get("/api/auth/me")
def auth_me():
    user = current_user()
    if not user:
        return jsonify(authenticated=False)
    return jsonify(authenticated=True, user=user_public(user), redirect=role_home(user["role"]))


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify(message="Вы вышли из аккаунта.")


# --- VK ID (OAuth 2.1 + PKCE) ---
VK_ROLE_LABELS = {"participant": "Участник", "supervisor": "Руководитель", "expert": "Эксперт"}


def _vk_role(value):
    return value if value in VK_ROLE_LABELS else "participant"


def _vk_pkce_pair():
    """Возвращает (code_verifier, code_challenge) для PKCE (RFC 7636, S256)."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _vk_http_post(url, data):
    import urllib.request
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _vk_fetch_user_info(access_token, vk_id):
    """Запрашивает немаскированные данные пользователя (имя, email) по access_token."""
    base = {"user_id": vk_id, "first_name": None, "last_name": None, "email": None}
    if not access_token:
        return base
    try:
        payload = _vk_http_post(VK_ID_BASE + "/oauth2/user_info",
                                {"client_id": VK_CLIENT_ID, "access_token": access_token})
        user = payload.get("user") or {}
        base["user_id"] = str(user.get("user_id") or vk_id)
        base["first_name"] = user.get("first_name") or None
        base["last_name"] = user.get("last_name") or None
        base["email"] = user.get("email") or None
    except Exception as exc:  # pragma: no cover
        app.logger.warning("VK ID user_info error: %s", exc)
    return base


@app.get("/api/auth/vk/login")
def vk_login():
    """Вход и регистрация через VK ID. Параметр ?role= задаёт роль при регистрации."""
    role = _vk_role(request.args.get("role"))
    if not vk_enabled():
        # Прототип: без настроенных ключей используем демонстрационный вход.
        return redirect("/api/auth/vk/demo?role=" + role)

    verifier, challenge = _vk_pkce_pair()
    state = secrets.token_urlsafe(32)
    session["vk_state"] = state
    session["vk_verifier"] = verifier
    session["vk_role"] = role
    session.permanent = True

    params = {
        "response_type": "code",
        "client_id": VK_CLIENT_ID,
        "redirect_uri": VK_REDIRECT_URI,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": VK_SCOPE,
        "prompt": request.args.get("prompt", ""),
        "lang_id": "0",
    }
    params = {k: v for k, v in params.items() if v}
    return redirect(VK_ID_BASE + "/authorize?" + urllib.parse.urlencode(params))


@app.get("/api/auth/vk/callback")
def vk_callback():
    role = _vk_role(request.args.get("role") or session.get("vk_role"))
    if not vk_enabled():
        return redirect("/api/auth/vk/demo?role=" + role)

    code = request.args.get("code")
    device_id = request.args.get("device_id")
    state = request.args.get("state")
    verifier = session.pop("vk_verifier", None)
    expected_state = session.pop("vk_state", None)
    session.pop("vk_role", None)

    if not code or not state or not expected_state or state != expected_state or not verifier:
        return redirect("/pages/auth.html?vk=error")

    try:
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": VK_CLIENT_ID,
            "device_id": device_id,
            "redirect_uri": VK_REDIRECT_URI,
            "state": state,
        }
        # Для конфиденциальных приложений обязателен сервисный ключ.
        if VK_SERVICE_TOKEN:
            token_data["service_token"] = VK_SERVICE_TOKEN
        payload = _vk_http_post(VK_ID_BASE + "/oauth2/auth", token_data)

        if payload.get("error"):
            app.logger.warning("VK ID token error: %s (%s)",
                               payload.get("error"), payload.get("error_description"))
            return redirect("/pages/auth.html?vk=error")

        vk_id = str(payload.get("user_id", ""))
        if not vk_id:
            return redirect("/pages/auth.html?vk=error")

        info = _vk_fetch_user_info(payload.get("access_token"), vk_id)
        email = info.get("email") or f"vk_{vk_id}@vk.local"
        name_bits = [b for b in (info.get("last_name"), info.get("first_name")) if b]
        name = " ".join(name_bits) or None
        user = find_or_create_vk_user(vk_id, email, name=name, role=role)
        return redirect(role_home(user["role"]) + "?token=" + make_auth_token(user["id"]))
    except Exception as exc:  # pragma: no cover
        app.logger.warning("VK ID OAuth error: %s", exc)
    return redirect("/pages/auth.html?vk=error")


@app.get("/api/auth/vk/demo")
def vk_demo():
    """Демонстрационный вход через VK ID для прототипа (реальный OAuth — при наличии ключей)."""
    role = _vk_role(request.args.get("role"))
    vk_id = "demo-" + secrets.token_hex(3)
    user = find_or_create_vk_user(vk_id, vk_id + "@vk.local", role=role)
    return redirect(role_home(user["role"]) + "?vk=demo&token=" + make_auth_token(user["id"]))


def find_or_create_vk_user(vk_id, email, name=None, role="participant"):
    role = _vk_role(role)
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE vk_id=?", (vk_id,)).fetchone()
        if user:
            return user
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user:
            conn.execute("UPDATE users SET vk_id=? WHERE id=?", (vk_id, user["id"]))
            return conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        display = name or f"{VK_ROLE_LABELS[role]} VK {vk_id[-4:]}"
        approval = "pending" if role in ROLES_REQUIRE_APPROVAL else "approved"
        cur = conn.execute(
            """INSERT INTO users(name,email,school,password_hash,vk_id,email_verified,
               full_name,role,approval_status,consent_pdn,consent_at)
               VALUES(?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)""",
            (display, email, "Не указана", "", vk_id, int(not email.endswith("@vk.local")), display, role, approval),
        )
        uid = cur.lastrowid
        if role == "participant":
            conn.execute("INSERT OR IGNORE INTO participants(name,email,school) VALUES(?,?,?)",
                         (display, email, "Не указана"))
        return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


# --------------------------------------------------------------------------- #
# Профиль
# --------------------------------------------------------------------------- #
@app.get("/api/profile")
def get_profile():
    user, err = require_login()
    if err:
        return err
    return jsonify(user=user_public(user))


@app.post("/api/profile")
def update_profile():
    user, err = require_login()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        full_name = text_field(data.get("full_name"), "ФИО", 150)
        birth_date = text_field(data.get("birth_date"), "Дата рождения", 20)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", birth_date):
            return jsonify(error="Дата рождения должна быть в формате ГГГГ-ММ-ДД."), 400
        grade = text_field(data.get("grade"), "Класс", 30)
        school = text_field(data.get("school"), "Школа", 150)
        region = text_field(data.get("region"), "Регион", 120)
        guardian_name = text_field(data.get("guardian_name"), "ФИО законного представителя", 150)
        guardian_contact = text_field(data.get("guardian_contact"), "Контакты законного представителя", 150)
        with db() as conn:
            conn.execute("""UPDATE users SET name=?, full_name=?, birth_date=?, grade=?, school=?,
                            region=?, guardian_name=?, guardian_contact=? WHERE id=?""",
                         (full_name, full_name, birth_date, grade, school, region,
                          guardian_name, guardian_contact, user["id"]))
        session["user_name"] = full_name
        user = current_user()
        return jsonify(message="Профиль сохранён.", user=user_public(user))
    except ValueError as e:
        return jsonify(error=str(e)), 400


# --------------------------------------------------------------------------- #
# Руководитель (педагог) с подтверждением по email
# --------------------------------------------------------------------------- #
@app.get("/api/supervisors")
def list_supervisors():
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            "SELECT id,teacher_name,teacher_email,organization,status,created_at,confirmed_at "
            "FROM supervisors WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return jsonify(supervisors=[dict(r) for r in rows])


@app.post("/api/supervisors")
def add_supervisor():
    user, err = require_login()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        teacher_name = text_field(data.get("teacher_name"), "ФИО руководителя", 150)
        teacher_email = text_field(data.get("teacher_email"), "Email руководителя", 254).lower()
        organization = text_field(data.get("organization"), "Организация", 150, required=False)
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", teacher_email):
            return jsonify(error="Введи корректный email руководителя."), 400
        token = secrets.token_urlsafe(24)
        with db() as conn:
            supervisor_account = conn.execute(
                "SELECT id FROM users WHERE lower(email)=? AND role='supervisor'",
                (teacher_email,)).fetchone()
            sup_uid = supervisor_account["id"] if supervisor_account else None
            cur = conn.execute(
                """INSERT INTO supervisors(user_id,teacher_name,teacher_email,organization,token,supervisor_user_id)
                   VALUES(?,?,?,?,?,?)""",
                (user["id"], teacher_name, teacher_email, organization, token, sup_uid))
            sid = cur.lastrowid
        confirm_url = request.url_root.rstrip("/") + url_for("confirm_supervisor", token=token)
        log_email(
            teacher_email,
            "Подтверждение руководства проектом участника",
            f"Уважаемый(ая) {teacher_name}!\n\n"
            f"Участник {user['name']} указал Вас руководителем проекта.\n"
            f"Подтвердите, пожалуйста, переходом по ссылке:\n{confirm_url}\n",
        )
        return jsonify(message="Руководитель добавлен. Письмо с подтверждением отправлено.",
                       supervisor_id=sid, status="pending", confirm_url=confirm_url), 201
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.delete("/api/supervisors/<int:sid>")
def delete_supervisor(sid):
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        conn.execute("DELETE FROM supervisors WHERE id=? AND user_id=?", (sid, user["id"]))
    return jsonify(message="Руководитель удалён.")


@app.get("/api/supervisors/confirm")
def confirm_supervisor():
    token = request.args.get("token", "")
    with db() as conn:
        row = conn.execute("SELECT * FROM supervisors WHERE token=?", (token,)).fetchone()
        if not row:
            return _info_page("Ссылка недействительна", "Подтверждение не найдено или уже выполнено.", ok=False)
        if row["status"] == "confirmed":
            return _info_page("Уже подтверждено", "Руководитель уже подтверждён.", ok=True)
        conn.execute("UPDATE supervisors SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP WHERE id=?",
                     (row["id"],))
    return _info_page("Подтверждено", f"Спасибо! Руководство {row['teacher_name']} подтверждено.", ok=True)


def _info_page(title, text, ok=True):
    color = "#1a4d80" if ok else "#b3261e"
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title><link rel="stylesheet" href="/css/style.css"></head>
    <body><section class="section"><div class="container" style="max-width:640px;text-align:center">
    <h1 class="section__title" style="color:{color}">{title}</h1>
    <p style="font-size:1.1rem;margin-bottom:2rem">{text}</p>
    <a href="/pages/cabinet.html" class="btn btn--primary">Перейти в личный кабинет</a>
    </div></section></body></html>"""
    return Response(html, mimetype="text/html")


# --------------------------------------------------------------------------- #
# Тестирование (I этап)
# --------------------------------------------------------------------------- #
@app.get("/api/quiz/questions")
def quiz_questions():
    count = min(int(request.args.get("count", QUIZ_QUESTION_COUNT)), 20)
    with db() as conn:
        rows = conn.execute("SELECT * FROM questions ORDER BY RANDOM() LIMIT ?", (count,)).fetchall()
        if not rows:
            return jsonify(error="Банк вопросов пуст."), 500
        answers, questions = {}, []
        for r in rows:
            opts = [("a", r["option_a"]), ("b", r["option_b"]),
                    ("c", r["option_c"]), ("d", r["option_d"])]
            random.shuffle(opts)
            keys = "abcd"
            items, correct = [], None
            for i, (orig_key, txt) in enumerate(opts):
                new_key = keys[i]
                items.append({"key": new_key, "text": txt})
                if orig_key == r["correct_option"]:
                    correct = new_key
            answers[str(r["id"])] = correct
            questions.append({"id": r["id"], "topic": r["topic"], "text": r["text"], "options": items})
        token = secrets.token_urlsafe(20)
        user = current_user()
        conn.execute("INSERT INTO quiz_sessions(token,user_id,answers) VALUES(?,?,?)",
                     (token, user["id"] if user else None, json.dumps(answers)))
    return jsonify(token=token, questions=questions, count=len(questions),
                   time_limit=QUIZ_TIME_LIMIT, pass_ratio=QUIZ_PASS_RATIO)


@app.post("/api/quiz/submit")
def quiz_submit():
    data = request.get_json(silent=True) or {}
    token = data.get("token", "")
    answers = data.get("answers", {})
    duration = data.get("duration")
    if not isinstance(answers, dict):
        return jsonify(error="Некорректные ответы."), 400
    with db() as conn:
        qs = conn.execute("SELECT * FROM quiz_sessions WHERE token=?", (token,)).fetchone()
        if not qs:
            return jsonify(error="Сессия тестирования не найдена. Начните заново."), 400
        correct_map = json.loads(qs["answers"])
        score, details = 0, []
        question_ids = list(correct_map.keys())
        rows = conn.execute(
            f"SELECT id,text,explanation,correct_option FROM questions WHERE id IN ({','.join('?' * len(question_ids))})",
            question_ids).fetchall() if question_ids else []
        qinfo = {str(r["id"]): r for r in rows}
        for qid, correct in correct_map.items():
            given = answers.get(qid)
            ok = given == correct
            if ok:
                score += 1
            details.append({
                "question_id": int(qid),
                "correct": ok,
                "correct_option": correct,
                "given": given,
                "text": qinfo.get(qid)["text"] if qid in qinfo else "",
                "explanation": qinfo.get(qid)["explanation"] if qid in qinfo else "",
            })
        total = len(correct_map)
        passed = total > 0 and (score / total) >= QUIZ_PASS_RATIO
        conn.execute("DELETE FROM quiz_sessions WHERE token=?", (token,))

        user = current_user()
        attempt_id = None
        certificate = None
        if user:
            cur = conn.execute(
                """INSERT INTO quiz_attempts(user_id,score,total,duration_seconds,passed)
                   VALUES(?,?,?,?,?)""",
                (user["id"], score, total, duration if isinstance(duration, int) else None, 1 if passed else 0))
            attempt_id = cur.lastrowid
            if passed:
                certificate = issue_certificate(conn, user, attempt_id, score, total)

    return jsonify(score=score, total=total, passed=passed,
                   details=details, attempt_id=attempt_id, certificate=certificate)


def issue_certificate(conn, user, attempt_id, score, total):
    number = certificate_number()
    while conn.execute("SELECT 1 FROM certificates WHERE number=?", (number,)).fetchone():
        number = certificate_number()
    cur = conn.execute(
        """INSERT INTO certificates(number,user_id,attempt_id,full_name,score,total,kind)
           VALUES(?,?,?,?,?,?, 'quiz')""",
        (number, user["id"], attempt_id, user["full_name"] or user["name"], score, total))
    cid = cur.lastrowid
    conn.execute("UPDATE quiz_attempts SET certificate_id=? WHERE id=?", (cid, attempt_id))
    return {"id": cid, "number": number,
            "download_url": f"/certificate/{number}.pdf",
            "verify_url": f"/verify/{number}"}


@app.get("/api/quiz/attempts")
def quiz_attempts():
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            """SELECT a.id,a.score,a.total,a.duration_seconds,a.passed,a.created_at,
                      c.number AS certificate_number
               FROM quiz_attempts a LEFT JOIN certificates c ON c.id=a.certificate_id
               WHERE a.user_id=? ORDER BY a.created_at DESC""", (user["id"],)).fetchall()
    return jsonify(attempts=[dict(r) for r in rows])


# --------------------------------------------------------------------------- #
# Сертификаты и проверка подлинности
# --------------------------------------------------------------------------- #
@app.get("/api/certificates")
def certificates():
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM certificates WHERE user_id=? ORDER BY issued_at DESC", (user["id"],)).fetchall()
    return jsonify(certificates=[
        {"number": r["number"], "kind": r["kind"], "score": r["score"], "total": r["total"],
         "issued_at": r["issued_at"], "download_url": f"/certificate/{r['number']}.pdf",
         "verify_url": f"/verify/{r['number']}"} for r in rows])


def _get_certificate(number):
    with db() as conn:
        return conn.execute("SELECT * FROM certificates WHERE number=?", (number,)).fetchone()


@app.get("/certificate/<number>.pdf")
def certificate_pdf(number):
    cert = _get_certificate(number)
    if not cert:
        return _info_page("Документ не найден", "Сертификат с таким номером отсутствует.", ok=False)
    verify_url = request.url_root.rstrip("/") + f"/verify/{number}"
    issued = (cert["issued_at"] or "")[:10]
    subtitle = "за успешное прохождение I этапа (тестирование)"
    pdf = render_award_pdf("certificate", cert["full_name"], subtitle, number, issued,
                           verify_url, score=f"{cert['score']} из {cert['total']}")
    return Response(pdf.read(), mimetype="application/pdf", headers={
        "Content-Disposition": f'inline; filename="certificate-{number}.pdf"'})


@app.get("/verify/<number>")
def verify_page(number):
    cert = _get_certificate(number)
    if not cert:
        return _info_page("Документ не найден", f"Документ {number} не найден в реестре.", ok=False)
    text = (f"Документ {cert['number']} действителен. "
            f"Выдан: {cert['full_name']}. Результат: {cert['score']} из {cert['total']}. "
            f"Дата выдачи: {(cert['issued_at'] or '')[:10]}.")
    return _info_page("Документ подтверждён", text, ok=True)


@app.get("/api/verify/<number>")
def verify_api(number):
    cert = _get_certificate(number)
    if not cert:
        return jsonify(valid=False, error="Не найдено"), 404
    return jsonify(valid=True, number=cert["number"], full_name=cert["full_name"],
                   score=cert["score"], total=cert["total"], issued_at=cert["issued_at"])


# --------------------------------------------------------------------------- #
# Проекты (II этап)
# --------------------------------------------------------------------------- #
@app.post("/api/projects")
def create_project():
    data = request.form if request.content_type and request.content_type.startswith("multipart/") \
        else (request.get_json(silent=True) or {})
    user = current_user()
    try:
        title = text_field(data.get("title"), "Название проекта", 200)
        nomination = text_field(data.get("nomination"), "Номинация", 100)
        abstract = text_field(data.get("abstract") or data.get("idea"), "Аннотация", 3000)
        status = data.get("status", "review")
        if status not in ("draft", "review"):
            status = "review"
        name = user["full_name"] or user["name"] if user else text_field(
            data.get("participant_name", "Участник"), "Имя", 100)

        file_name = save_upload(request.files.get("file"), ALLOWED_WORK)
        presentation_name = save_upload(request.files.get("presentation"), ALLOWED_PRESENTATION)
        video_name = save_upload(request.files.get("video"), ALLOWED_VIDEO)
        video_url = text_field(data.get("video_url"), "Ссылка на видеоролик", 500, required=False)

        if status == "draft" and not (file_name or presentation_name or video_name or video_url) \
                and not abstract:
            # Пустой черновик тоже допустим
            pass

        with db() as conn:
            cur = conn.execute(
                """INSERT INTO projects
                   (participant_name,title,nomination,idea,file_name,user_id,abstract,
                    presentation_name,video_url,video_name,status,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (name, title, nomination, abstract, file_name, user["id"] if user else None,
                 abstract, presentation_name, video_url or None, video_name, status))
            pid = cur.lastrowid
        return jsonify(message="Проект сохранён." if status == "draft" else "Проект отправлен на проверку.",
                       project_id=pid, status=status), 201
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.get("/api/projects")
def list_projects():
    user = current_user()
    with db() as conn:
        if user:
            rows = conn.execute("SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC",
                                (user["id"],)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT 100").fetchall()
    return jsonify(projects=[_project_json(r) for r in rows])


def _project_json(r):
    keys = r.keys()
    return {
        "id": r["id"], "title": r["title"], "nomination": r["nomination"],
        "abstract": r["abstract"] if "abstract" in keys else r["idea"],
        "file_name": r["file_name"],
        "presentation_name": r["presentation_name"] if "presentation_name" in keys else None,
        "video_url": r["video_url"] if "video_url" in keys else None,
        "video_name": r["video_name"] if "video_name" in keys else None,
        "status": r["status"] if "status" in keys else "review",
        "status_label": STATUS_LABELS.get(r["status"] if "status" in keys else "review", "На проверке"),
        "supervisor_confirmed": (r["supervisor_confirmed"] if "supervisor_confirmed" in keys else 0) or 0,
        "supervisor_confirmed_at": r["supervisor_confirmed_at"] if "supervisor_confirmed_at" in keys else None,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"] if "updated_at" in keys else None,
    }


@app.patch("/api/projects/<int:pid>")
def update_project(pid):
    user, err = require_login()
    if err:
        return err
    data = request.form if request.content_type and request.content_type.startswith("multipart/") \
        else (request.get_json(silent=True) or {})
    with db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (pid, user["id"])).fetchone()
        if not proj:
            return jsonify(error="Проект не найден."), 404
        try:
            fields, params = [], []
            for key, col, limit in [("title", "title", 200), ("nomination", "nomination", 100),
                                    ("abstract", "abstract", 3000)]:
                if data.get(key) is not None:
                    fields.append(f"{col}=?")
                    params.append(text_field(data.get(key), key, limit))
            for form_key, col, allowed in [("file", "file_name", ALLOWED_WORK),
                                           ("presentation", "presentation_name", ALLOWED_PRESENTATION),
                                           ("video", "video_name", ALLOWED_VIDEO)]:
                saved = save_upload(request.files.get(form_key), allowed)
                if saved:
                    fields.append(f"{col}=?")
                    params.append(saved)
            if data.get("video_url") is not None:
                fields.append("video_url=?")
                params.append(text_field(data.get("video_url"), "Ссылка", 500, required=False))
            new_status = data.get("status")
            if new_status and new_status in PROJECT_STATUSES:
                fields.append("status=?")
                params.append(new_status)
            elif proj["status"] == "draft" and "status" not in data:
                pass
            fields.append("updated_at=CURRENT_TIMESTAMP")
            params.append(pid)
            conn.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id=?", params)
        except ValueError as e:
            return jsonify(error=str(e)), 400
        proj = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return jsonify(message="Проект обновлён.", project=_project_json(proj))


@app.post("/api/projects/<int:pid>/submit")
def submit_project(pid):
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (pid, user["id"])).fetchone()
        if not proj:
            return jsonify(error="Проект не найден."), 404
        if not proj["file_name"]:
            return jsonify(error="Прикрепите файл работы (PDF/DOCX) перед отправкой."), 400
        conn.execute("UPDATE projects SET status='review', updated_at=CURRENT_TIMESTAMP WHERE id=?", (pid,))
    return jsonify(message="Проект отправлен на проверку.", status="review")


# --------------------------------------------------------------------------- #
# Результаты, рецензии
# --------------------------------------------------------------------------- #
@app.get("/api/my/results")
def my_results():
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        attempts = conn.execute(
            """SELECT a.*, c.number AS certificate_number FROM quiz_attempts a
               LEFT JOIN certificates c ON c.id=a.certificate_id
               WHERE a.user_id=? ORDER BY a.created_at DESC""", (user["id"],)).fetchall()
        projects = conn.execute("SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC",
                                (user["id"],)).fetchall()
        reviews = {}
        for p in projects:
            rs = conn.execute("SELECT * FROM reviews WHERE project_id=? ORDER BY created_at DESC",
                              (p["id"],)).fetchall()
            reviews[str(p["id"])] = [dict(r) for r in rs]
    best = max((a["score"] / a["total"] for a in attempts if a["total"]), default=0)
    return jsonify(
        quiz_attempts=[dict(a) for a in attempts],
        best_score=round(best * 100),
        projects=[{**_project_json(p), "reviews": reviews.get(str(p["id"]), [])} for p in projects],
    )


# --------------------------------------------------------------------------- #
# Расписание ВКС-защиты
# --------------------------------------------------------------------------- #
@app.get("/api/my/schedule")
def my_schedule():
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM vks_schedule WHERE user_id=? ORDER BY scheduled_at", (user["id"],)).fetchall()
    return jsonify(schedule=[dict(r) for r in rows])


# --------------------------------------------------------------------------- #
# Достижения
# --------------------------------------------------------------------------- #
@app.get("/api/my/achievements")
def my_achievements():
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        awards = conn.execute("SELECT * FROM achievements WHERE user_id=? ORDER BY issued_at DESC",
                              (user["id"],)).fetchall()
        certs = conn.execute("SELECT * FROM certificates WHERE user_id=? ORDER BY issued_at DESC",
                             (user["id"],)).fetchall()
    items = [
        {"id": f"cert-{c['number']}", "kind": "certificate", "title": "Сертификат участника",
         "description": f"I этап: {c['score']} из {c['total']}", "issued_at": c["issued_at"],
         "download_url": f"/certificate/{c['number']}.pdf",
         "verify_url": f"/verify/{c['number']}", "number": c["number"]}
        for c in certs
    ]
    for a in awards:
        if a["kind"] == "certificate":
            continue
        items.append({
            "id": f"award-{a['id']}", "kind": a["kind"], "title": a["title"],
            "description": a["description"], "issued_at": a["issued_at"],
            "download_url": f"/award/{a['id']}.pdf",
        })
    items.sort(key=lambda x: x.get("issued_at") or "", reverse=True)
    return jsonify(achievements=items)


@app.get("/award/<int:aid>.pdf")
def award_pdf(aid):
    user = current_user()
    if not user:
        return _info_page("Нужен вход", "Войдите в личный кабинет.", ok=False)
    with db() as conn:
        a = conn.execute("SELECT * FROM achievements WHERE id=? AND user_id=?", (aid, user["id"])).fetchone()
    if not a:
        return _info_page("Документ не найден", "Награда не найдена.", ok=False)
    verify_url = request.url_root.rstrip("/") + f"/pages/cabinet.html"
    pdf = render_award_pdf(a["kind"], user["full_name"] or user["name"], a["description"] or "",
                           f"ARK-AWARD-{a['id']:04d}", (a["issued_at"] or "")[:10], verify_url,
                           score=a["score"])
    return Response(pdf.read(), mimetype="application/pdf", headers={
        "Content-Disposition": f'inline; filename="award-{aid}.pdf"'})


# --------------------------------------------------------------------------- #
# Сводка по кабинету
# --------------------------------------------------------------------------- #
@app.get("/api/my/summary")
def my_summary():
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        attempts = conn.execute("SELECT COUNT(*) c FROM quiz_attempts WHERE user_id=?", (user["id"],)).fetchone()["c"]
        certs = conn.execute("SELECT COUNT(*) c FROM certificates WHERE user_id=?", (user["id"],)).fetchone()["c"]
        projects = conn.execute("SELECT COUNT(*) c FROM projects WHERE user_id=?", (user["id"],)).fetchone()["c"]
        supervisors = conn.execute(
            "SELECT COUNT(*) c FROM supervisors WHERE user_id=? AND status='confirmed'",
            (user["id"],)).fetchone()["c"]
        awards = conn.execute(
            "SELECT COUNT(*) c FROM achievements WHERE user_id=? AND kind!='certificate'",
            (user["id"],)).fetchone()["c"]
        schedule = conn.execute(
            "SELECT COUNT(*) c FROM vks_schedule WHERE user_id=?", (user["id"],)).fetchone()["c"]
        best = conn.execute(
            "SELECT MAX(CAST(score AS REAL)/total) m FROM quiz_attempts WHERE user_id=? AND total>0",
            (user["id"],)).fetchone()["m"]
    return jsonify(
        profile_complete=profile_complete(user),
        quiz_attempts=attempts, certificates=certs, best_score=round((best or 0) * 100),
        projects=projects, supervisors=supervisors, awards=awards, schedule=schedule,
    )


# --------------------------------------------------------------------------- #
# Демонстрационные данные для кабинета
# --------------------------------------------------------------------------- #
@app.post("/api/demo/seed")
def demo_seed():
    user, err = require_login()
    if err:
        return err
    uid = user["id"]
    with db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE user_id=? ORDER BY id LIMIT 1", (uid,)).fetchone()
        if not proj:
            cur = conn.execute(
                """INSERT INTO projects(participant_name,title,nomination,idea,user_id,abstract,status,updated_at)
                   VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (user["full_name"] or user["name"], "Белый медведь: хозяин Арктики",
                 "Исследовательские работы",
                 "Исследование о жизни белого медведя и сохранении его популяции.",
                 uid, "Исследование о жизни белого медведя и сохранении его популяции.", "evaluated"))
            pid = cur.lastrowid
        else:
            pid = proj["id"]
            conn.execute("UPDATE projects SET status='evaluated' WHERE id=?", (pid,))
        if not conn.execute("SELECT 1 FROM reviews WHERE project_id=?", (pid,)).fetchone():
            conn.executemany(
                "INSERT INTO reviews(project_id,expert_name,score,criteria,comment) VALUES(?,?,?,?,?)",
                [(pid, "Эксперт ИБПК СО РАН", 9, "Актуальность",
                  "Тема раскрыта глубоко, отличные выводы."),
                 (pid, "Эксперт заповедника", 8, "Научная обоснованность",
                  "Интересный подход, стоит усилить список источников.")])
        import datetime as _dt
        when = (_dt.datetime.now() + _dt.timedelta(days=3)).strftime("%Y-%m-%dT10:00")
        if not conn.execute("SELECT 1 FROM vks_schedule WHERE user_id=?", (uid,)).fetchone():
            conn.execute(
                """INSERT INTO vks_schedule(user_id,project_id,title,scheduled_at,join_link,room)
                   VALUES(?,?,?,?,?,?)""",
                (uid, pid, "ВКС-защита проекта", when,
                 "https://vk.com/call/arctic-protect-" + secrets.token_hex(3), "Зал Арктика"))
        if not conn.execute("SELECT 1 FROM achievements WHERE user_id=? AND kind='diploma'", (uid,)).fetchone():
            conn.execute(
                "INSERT INTO achievements(user_id,title,kind,description,score) VALUES(?,?,?,?,?)",
                (uid, "Диплом призёра конкурса", "diploma",
                 "II место в номинации «Исследовательские работы»", 2))
        if not conn.execute("SELECT 1 FROM achievements WHERE user_id=? AND kind='thanks'", (uid,)).fetchone():
            conn.execute(
                "INSERT INTO achievements(user_id,title,kind,description) VALUES(?,?,?,?)",
                (uid, "Благодарность участнику", "thanks",
                 "За активное участие во Всероссийском конкурсе"))
    return jsonify(message="Демонстрационные данные добавлены.")


@app.post("/api/quiz-results")
def save_quiz_result():
    """Совместимость со старым API."""
    data = request.get_json(silent=True) or {}
    score, total = data.get("score"), data.get("total")
    name = data.get("participant_name", "")
    if type(score) is not int or type(total) is not int or total < 1 or total > 50 or score < 0 or score > total:
        return jsonify(error="Некорректный результат теста."), 400
    if name:
        try:
            name = text_field(name, "Имя", 100)
        except ValueError as e:
            return jsonify(error=str(e)), 400
    with db() as conn:
        cur = conn.execute("INSERT INTO quiz_results(participant_name,score,total) VALUES(?,?,?)",
                           (name or None, score, total))
        rid = cur.lastrowid
    return jsonify(message="Результат теста сохранён.", result_id=rid), 201


@app.post("/api/contact")
def contact():
    data = request.get_json(silent=True) or {}
    try:
        name = text_field(data.get("name"), "Имя", 100)
        email = text_field(data.get("email"), "Email", 254)
        subject = text_field(data.get("subject"), "Тема", 200)
        message = text_field(data.get("message"), "Сообщение", 3000)
        with db() as conn:
            cur = conn.execute("INSERT INTO contact_messages(name,email,subject,message) VALUES(?,?,?,?)",
                               (name, email, subject, message))
        return jsonify(message="Сообщение сохранено.", message_id=cur.lastrowid), 201
    except ValueError as e:
        return jsonify(error=str(e)), 400


# --------------------------------------------------------------------------- #
# Кабинет руководителя (педагога)
# --------------------------------------------------------------------------- #
def _linked_participants(conn, supervisor):
    rows = conn.execute(
        """SELECT s.id AS link_id, s.status AS link_status, s.organization,
                  u.id AS participant_id, u.name, u.full_name, u.school, u.grade,
                  u.region, u.email
           FROM supervisors s JOIN users u ON u.id = s.user_id
           WHERE s.supervisor_user_id = ? OR lower(s.teacher_email) = ?
           ORDER BY u.name""",
        (supervisor["id"], supervisor["email"])).fetchall()
    result = []
    for r in rows:
        projects = conn.execute(
            "SELECT id,title,nomination,status,supervisor_confirmed,created_at "
            "FROM projects WHERE user_id=? ORDER BY created_at DESC",
            (r["participant_id"],)).fetchall()
        result.append({
            "participant_id": r["participant_id"],
            "name": r["full_name"] or r["name"], "email": r["email"],
            "school": r["school"], "grade": r["grade"], "region": r["region"],
            "link_status": r["link_status"], "organization": r["organization"],
            "projects": [{"id": p["id"], "title": p["title"], "nomination": p["nomination"],
                          "status": p["status"], "status_label": STATUS_LABELS.get(p["status"], p["status"]),
                          "supervisor_confirmed": p["supervisor_confirmed"] or 0,
                          "created_at": p["created_at"]} for p in projects],
        })
    return result


@app.get("/api/supervisor/participants")
def supervisor_participants():
    user, err = require_roles("supervisor")
    if err:
        return err
    with db() as conn:
        participants = _linked_participants(conn, user)
    return jsonify(participants=participants, count=len(participants))


def _supervisor_project(conn, supervisor, pid):
    """Возвращает заявку, если участник прикреплён к этому руководителю, иначе None."""
    proj = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not proj:
        return None, jsonify(error="Заявка не найдена."), 404
    linked_ids = {p["participant_id"] for p in _linked_participants(conn, supervisor)}
    if proj["user_id"] not in linked_ids:
        return None, jsonify(error="Этот участник не прикреплён к вам."), 403
    return proj, None, None


@app.post("/api/supervisor/projects/<int:pid>/confirm")
def supervisor_confirm_project(pid):
    user, err = require_roles("supervisor")
    if err:
        return err
    with db() as conn:
        proj, resp, code = _supervisor_project(conn, user, pid)
        if resp:
            return resp, code
        if proj["status"] == "draft":
            return jsonify(error="Заявка ещё не отправлена участником."), 400
        conn.execute(
            "UPDATE projects SET supervisor_confirmed=1, supervisor_confirmed_at=CURRENT_TIMESTAMP "
            "WHERE id=?", (pid,))
        conn.execute(
            """UPDATE supervisors SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP
               WHERE user_id=? AND (supervisor_user_id=? OR lower(teacher_email)=lower(?))""",
            (proj["user_id"], user["id"], user["email"]))
    return jsonify(message="Заявка ученика подтверждена.", supervisor_confirmed=1)


@app.delete("/api/supervisor/projects/<int:pid>/confirm")
def supervisor_unconfirm_project(pid):
    user, err = require_roles("supervisor")
    if err:
        return err
    with db() as conn:
        proj, resp, code = _supervisor_project(conn, user, pid)
        if resp:
            return resp, code
        conn.execute(
            "UPDATE projects SET supervisor_confirmed=0, supervisor_confirmed_at=NULL "
            "WHERE id=?", (pid,))
        conn.execute(
            """UPDATE supervisors SET status='pending', confirmed_at=NULL
               WHERE user_id=? AND (supervisor_user_id=? OR lower(teacher_email)=lower(?))""",
            (proj["user_id"], user["id"], user["email"]))
    return jsonify(message="Подтверждение снято.", supervisor_confirmed=0)


@app.get("/api/supervisor/summary")
def supervisor_summary():
    user, err = require_roles("supervisor")
    if err:
        return err
    with db() as conn:
        participants = _linked_participants(conn, user)
        confirmed = sum(1 for p in participants if p["link_status"] == "confirmed")
        projects = sum(len(p["projects"]) for p in participants)
    return jsonify(participants=len(participants), confirmed=confirmed,
                   projects=projects, certificate_ready=len(participants) > 0)


@app.get("/api/supervisor/certificate.pdf")
def supervisor_certificate_pdf():
    user, err = require_roles("supervisor")
    if err:
        return err
    with db() as conn:
        participants = _linked_participants(conn, user)
    if not participants:
        return _info_page("Сертификат пока недоступен",
                          "Сертификат руководителя формируется после появления прикреплённых участников.",
                          ok=False)
    verify_url = request.url_root.rstrip("/") + "/pages/supervisor.html"
    pdf = render_award_pdf(
        "supervisor", user["full_name"] or user["name"],
        f"за подготовку {len(participants)} участник(ов) конкурса",
        "ARK-SUP-" + str(user["id"]).zfill(4), datetime.now().strftime("%Y-%m-%d"), verify_url)
    return Response(pdf.read(), mimetype="application/pdf", headers={
        "Content-Disposition": 'inline; filename="supervisor-certificate.pdf"'})


# --------------------------------------------------------------------------- #
# Кабинет эксперта
# --------------------------------------------------------------------------- #
@app.get("/api/criteria")
def get_criteria():
    with db() as conn:
        rows = conn.execute("SELECT * FROM criteria WHERE active=1 ORDER BY id").fetchall()
    return jsonify(criteria=[dict(r) for r in rows])


def _weighted_score(conn, scores):
    crits = conn.execute("SELECT id,weight,max_score FROM criteria WHERE active=1").fetchall()
    total = 0.0
    for c in crits:
        raw = scores.get(str(c["id"]), scores.get(c["id"]))
        if isinstance(raw, dict):
            raw = raw.get("score")
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        val = max(0.0, min(val, c["max_score"]))
        if c["max_score"]:
            total += (val / c["max_score"]) * c["weight"]
    return round(total * 100, 2)


@app.get("/api/expert/assignments")
def expert_assignments():
    user, err = require_roles("expert")
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            """SELECT a.id AS assignment_id, a.status AS assignment_status, a.mode,
                      p.id,p.title,p.nomination,p.status,p.created_at,
                      u.full_name AS participant_name, u.school,
                      e.total_score, e.recommendation, e.id AS evaluation_id
               FROM expert_assignments a
               JOIN projects p ON p.id = a.project_id
               LEFT JOIN users u ON u.id = p.user_id
               LEFT JOIN evaluations e ON e.project_id = a.project_id AND e.expert_id = a.expert_id
               WHERE a.expert_id=? ORDER BY a.created_at DESC""", (user["id"],)).fetchall()
    return jsonify(assignments=[{
        "assignment_id": r["assignment_id"], "assignment_status": r["assignment_status"],
        "mode": r["mode"], "project_id": r["id"], "title": r["title"],
        "nomination": r["nomination"], "status": r["status"],
        "status_label": STATUS_LABELS.get(r["status"], r["status"]),
        "participant_name": r["participant_name"], "school": r["school"],
        "total_score": r["total_score"], "recommendation": r["recommendation"],
        "evaluated": r["evaluation_id"] is not None,
    } for r in rows])


@app.post("/api/expert/assignments/auto")
def auto_assign_projects():
    user, err = require_roles("expert", "admin")
    if err:
        return err
    with db() as conn:
        experts = [r["id"] for r in conn.execute(
            "SELECT id FROM users WHERE role='expert' AND approval_status!='blocked'")]
        if not experts:
            return jsonify(error="Нет зарегистрированных экспертов для распределения."), 400
        counts = {e: conn.execute("SELECT COUNT(*) c FROM expert_assignments WHERE expert_id=?",
                                  (e,)).fetchone()["c"] for e in experts}
        projects = conn.execute(
            """SELECT id FROM projects
               WHERE status IN ('review','accepted')
                 AND id NOT IN (SELECT project_id FROM expert_assignments)
               ORDER BY created_at""").fetchall()
        assigned = 0
        for p in projects:
            eid = min(experts, key=lambda e: counts[e])
            conn.execute("INSERT OR IGNORE INTO expert_assignments(expert_id,project_id,mode) VALUES(?,?, 'auto')",
                         (eid, p["id"]))
            conn.execute("UPDATE projects SET status='expertise', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (p["id"],))
            counts[eid] += 1
            assigned += 1
    return jsonify(message=f"Автоматически распределено работ: {assigned}.", assigned=assigned)


@app.post("/api/expert/assignments")
def manual_assign_project():
    user, err = require_roles("expert", "admin")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        project_id = int(data.get("project_id"))
        expert_id = int(data.get("expert_id") or user["id"])
    except (TypeError, ValueError):
        return jsonify(error="Укажите проект и эксперта."), 400
    with db() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            return jsonify(error="Проект не найден."), 404
        if not conn.execute("SELECT 1 FROM users WHERE id=? AND role='expert'", (expert_id,)).fetchone():
            return jsonify(error="Эксперт не найден."), 404
        conn.execute("INSERT OR IGNORE INTO expert_assignments(expert_id,project_id,mode) VALUES(?,?, 'manual')",
                     (expert_id, project_id))
        conn.execute("UPDATE projects SET status='expertise', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (project_id,))
    return jsonify(message="Работа назначена эксперту."), 201


@app.delete("/api/expert/assignments/<int:aid>")
def delete_assignment(aid):
    user, err = require_roles("expert", "admin")
    if err:
        return err
    with db() as conn:
        if user["role"] == "admin":
            conn.execute("DELETE FROM expert_assignments WHERE id=?", (aid,))
        else:
            conn.execute("DELETE FROM expert_assignments WHERE id=? AND expert_id=?", (aid, user["id"]))
    return jsonify(message="Назначение снято.")


@app.get("/api/expert/project/<int:pid>")
def expert_project(pid):
    user, err = require_roles("expert", "admin")
    if err:
        return err
    with db() as conn:
        p = conn.execute(
            """SELECT p.*, u.full_name AS participant_name, u.school, u.region
               FROM projects p LEFT JOIN users u ON u.id=p.user_id WHERE p.id=?""", (pid,)).fetchone()
        if not p:
            return jsonify(error="Проект не найден."), 404
        criteria = conn.execute("SELECT * FROM criteria WHERE active=1 ORDER BY id").fetchall()
        evaluation = conn.execute("SELECT * FROM evaluations WHERE project_id=? AND expert_id=?",
                                  (pid, user["id"])).fetchone()
        scores = {}
        if evaluation:
            for s in conn.execute("SELECT criterion_id,score,comment FROM evaluation_scores WHERE evaluation_id=?",
                                  (evaluation["id"],)).fetchall():
                scores[str(s["criterion_id"])] = {"score": s["score"], "comment": s["comment"]}
    return jsonify(
        project={**_project_json(p), "participant_name": p["participant_name"], "school": p["school"]},
        criteria=[dict(c) for c in criteria],
        evaluation=({"recommendation": evaluation["recommendation"], "comment": evaluation["comment"],
                     "total_score": evaluation["total_score"]} if evaluation else None),
        scores=scores)


@app.post("/api/expert/evaluations")
def save_evaluation():
    user, err = require_roles("expert")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        pid = int(data.get("project_id"))
    except (TypeError, ValueError):
        return jsonify(error="Не указан проект."), 400
    scores = data.get("scores") or {}
    comment = text_field(data.get("comment"), "Комментарий", 3000, required=False)
    recommendation = text_field(data.get("recommendation"), "Рекомендация", 2000, required=False)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
            return jsonify(error="Проект не найден."), 404
        total = _weighted_score(conn, scores)
        existing = conn.execute("SELECT id FROM evaluations WHERE project_id=? AND expert_id=?",
                                (pid, user["id"])).fetchone()
        if existing:
            eid = existing["id"]
            conn.execute("""UPDATE evaluations SET total_score=?, recommendation=?, comment=?,
                            updated_at=CURRENT_TIMESTAMP WHERE id=?""", (total, recommendation, comment, eid))
            conn.execute("DELETE FROM evaluation_scores WHERE evaluation_id=?", (eid,))
        else:
            cur = conn.execute(
                """INSERT INTO evaluations(project_id,expert_id,total_score,recommendation,comment)
                   VALUES(?,?,?,?,?)""", (pid, user["id"], total, recommendation, comment))
            eid = cur.lastrowid
        for cid, sc in scores.items():
            try:
                score_val = float(sc.get("score") if isinstance(sc, dict) else sc)
            except (TypeError, ValueError, AttributeError):
                continue
            comment_val = sc.get("comment") if isinstance(sc, dict) else None
            conn.execute(
                "INSERT INTO evaluation_scores(evaluation_id,criterion_id,score,comment) VALUES(?,?,?,?)",
                (eid, int(cid), score_val, comment_val))
        conn.execute("UPDATE expert_assignments SET status='done' WHERE project_id=? AND expert_id=?",
                     (pid, user["id"]))
        conn.execute("UPDATE projects SET status='evaluated', updated_at=CURRENT_TIMESTAMP WHERE id=?", (pid,))
        # Дублируем отзыв в карточку участника.
        expert_name = user["full_name"] or user["name"]
        conn.execute("DELETE FROM reviews WHERE project_id=? AND expert_name=?", (pid, expert_name))
        conn.execute(
            "INSERT INTO reviews(project_id,expert_name,score,criteria,comment) VALUES(?,?,?,?,?)",
            (pid, expert_name, round(total), recommendation or "Взвешенная оценка",
             comment or "Оценка выставлена экспертом."))
    return jsonify(message="Оценка сохранена.", total_score=total)


@app.get("/api/expert/ranking")
def expert_ranking():
    user, err = require_login()
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            """SELECT p.id,p.title,p.nomination,
                      AVG(e.total_score) AS avg_score, COUNT(e.id) AS reviews
               FROM projects p JOIN evaluations e ON e.project_id=p.id
               GROUP BY p.id ORDER BY avg_score DESC, p.title""").fetchall()
    ranking = []
    for i, r in enumerate(rows, start=1):
        ranking.append({"rank": i, "project_id": r["id"], "title": r["title"],
                        "nomination": r["nomination"], "avg_score": round(r["avg_score"] or 0, 2),
                        "reviews": r["reviews"]})
    return jsonify(ranking=ranking)


# --------------------------------------------------------------------------- #
# Административная часть (оргкомитет)
# --------------------------------------------------------------------------- #
def _require_admin():
    return require_roles("admin")


@app.get("/api/admin/stats")
def admin_stats():
    user, err = _require_admin()
    if err:
        return err
    with db() as conn:
        g = lambda q, *a: conn.execute(q, a).fetchone()[0]
        role_counts = {r["role"]: r["c"] for r in conn.execute(
            "SELECT role, COUNT(*) c FROM users GROUP BY role").fetchall()}
        status_counts = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM projects GROUP BY status").fetchall()}
        regions = [dict(r) for r in conn.execute(
            """SELECT COALESCE(NULLIF(region,''),'Не указан') region, COUNT(*) c
               FROM users WHERE role='participant' GROUP BY region ORDER BY c DESC LIMIT 15""").fetchall()]
        schools = [dict(r) for r in conn.execute(
            """SELECT school, COUNT(*) c FROM users WHERE role='participant'
               GROUP BY school ORDER BY c DESC LIMIT 15""").fetchall()]
        dynamics = [dict(r) for r in conn.execute(
            """SELECT strftime('%Y-%m', created_at) ym, COUNT(*) c FROM projects
               GROUP BY ym ORDER BY ym""").fetchall()]
        nominations = [dict(r) for r in conn.execute(
            "SELECT nomination, COUNT(*) c FROM projects GROUP BY nomination ORDER BY c DESC").fetchall()]
    return jsonify(
        users=dict(conn_users=sum(role_counts.values()), **role_counts),
        participants=role_counts.get("participant", 0),
        supervisors=role_counts.get("supervisor", 0),
        experts=role_counts.get("expert", 0),
        pending=g("SELECT COUNT(*) FROM users WHERE approval_status='pending'"),
        projects=g("SELECT COUNT(*) FROM projects"),
        projects_by_status=status_counts,
        certificates=g("SELECT COUNT(*) FROM certificates"),
        regions_count=g("SELECT COUNT(DISTINCT region) FROM users WHERE region IS NOT NULL AND region<>''"),
        schools_count=g("SELECT COUNT(DISTINCT school) FROM users WHERE role='participant'"),
        regions=regions, schools=schools, dynamics=dynamics, nominations=nominations,
    )


@app.get("/api/admin/users")
def admin_users():
    user, err = _require_admin()
    if err:
        return err
    role = request.args.get("role")
    status = request.args.get("status")
    query = "SELECT * FROM users WHERE 1=1"
    params = []
    if role:
        query += " AND role=?"
        params.append(role)
    if status:
        query += " AND approval_status=?"
        params.append(status)
    query += " ORDER BY id"
    with db() as conn:
        rows = conn.execute(query, params).fetchall()
    return jsonify(users=[{
        "id": r["id"], "name": r["name"], "email": r["email"], "role": r["role"],
        "role_label": ROLE_LABELS.get(r["role"], r["role"]), "school": r["school"],
        "region": r["region"], "organization": r["organization"],
        "approval_status": r["approval_status"], "consent_pdn": bool(r["consent_pdn"]),
        "consent_at": r["consent_at"], "created_at": r["created_at"],
    } for r in rows])


@app.patch("/api/admin/users/<int:uid>")
def admin_update_user(uid):
    user, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    fields, params = [], []
    if data.get("role") in ROLES:
        fields.append("role=?")
        params.append(data["role"])
    if data.get("approval_status") in ("pending", "approved", "blocked"):
        fields.append("approval_status=?")
        params.append(data["approval_status"])
    if not fields:
        return jsonify(error="Нет полей для обновления."), 400
    params.append(uid)
    with db() as conn:
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", params)
    return jsonify(message="Пользователь обновлён.")


@app.post("/api/admin/users/<int:uid>/<action>")
def admin_user_action(uid, action):
    user, err = _require_admin()
    if err:
        return err
    mapping = {"approve": "approved", "block": "blocked", "reject": "blocked", "pending": "pending"}
    if action not in mapping:
        return jsonify(error="Неизвестное действие."), 400
    with db() as conn:
        conn.execute("UPDATE users SET approval_status=? WHERE id=?", (mapping[action], uid))
    return jsonify(message="Статус пользователя обновлён.")


@app.delete("/api/admin/users/<int:uid>")
def admin_delete_user(uid):
    user, err = _require_admin()
    if err:
        return err
    if uid == user["id"]:
        return jsonify(error="Нельзя удалить собственную учётную запись."), 400
    with db() as conn:
        for table in ("supervisors", "quiz_attempts", "certificates", "projects",
                      "vks_schedule", "achievements"):
            conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM expert_assignments WHERE expert_id=?", (uid,))
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
    return jsonify(message="Пользователь удалён.")


ADMIN_RESOURCES = {
    "news": ("news", ["title", "body", "category", "image", "published"]),
    "media": ("media", ["title", "kind", "url", "description"]),
    "banners": ("banners", ["title", "text", "link", "cta", "active"]),
    "stages": ("stages", ["name", "start_date", "end_date", "status", "auto_advance", "order_index"]),
    "nominations": ("nominations", ["name", "description", "active"]),
    "criteria": ("criteria", ["name", "description", "weight", "max_score", "active"]),
    "questions": ("questions", ["topic", "text", "option_a", "option_b", "option_c",
                                "option_d", "correct_option", "explanation", "difficulty"]),
}
BOOL_FIELDS = {"published", "active", "auto_advance"}


@app.route("/api/admin/<resource>", methods=["GET", "POST"])
def admin_resource(resource):
    user, err = _require_admin()
    if err:
        return err
    if resource not in ADMIN_RESOURCES:
        return jsonify(error="Раздел не найден."), 404
    table, fields = ADMIN_RESOURCES[resource]
    with db() as conn:
        if request.method == "GET":
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            return jsonify(items=[dict(r) for r in rows])
        data = request.get_json(silent=True) or {}
        if not data.get("title") and not data.get("name") and not data.get("text"):
            return jsonify(error="Заполните обязательные поля."), 400
        cols, vals = [], []
        for f in fields:
            if f in data:
                v = data[f]
                if f in BOOL_FIELDS:
                    v = 1 if v else 0
                cols.append(f)
                vals.append(v)
        if not cols:
            return jsonify(error="Нет данных для сохранения."), 400
        placeholders = ",".join("?" * len(cols))
        cur = conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals)
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(message="Запись добавлена.", item=dict(row)), 201


@app.route("/api/admin/<resource>/<int:rid>", methods=["PUT", "PATCH", "DELETE"])
def admin_resource_item(resource, rid):
    user, err = _require_admin()
    if err:
        return err
    if resource not in ADMIN_RESOURCES:
        return jsonify(error="Раздел не найден."), 404
    table, fields = ADMIN_RESOURCES[resource]
    with db() as conn:
        if request.method == "DELETE":
            conn.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
            return jsonify(message="Запись удалена.")
        data = request.get_json(silent=True) or {}
        cols, vals = [], []
        for f in fields:
            if f in data:
                v = data[f]
                if f in BOOL_FIELDS:
                    v = 1 if v else 0
                cols.append(f"{f}=?")
                vals.append(v)
        if not cols:
            return jsonify(error="Нет данных для обновления."), 400
        vals.append(rid)
        conn.execute(f"UPDATE {table} SET {', '.join(cols)} WHERE id=?", vals)
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
    return jsonify(message="Запись обновлена.", item=dict(row) if row else None)


@app.get("/api/admin/experts")
def admin_experts():
    user, err = _require_admin()
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            """SELECT u.id, u.full_name, u.name, u.email, u.organization,
                      (SELECT COUNT(*) FROM expert_assignments a WHERE a.expert_id=u.id) loads
               FROM users u WHERE u.role='expert' ORDER BY loads""").fetchall()
    return jsonify(experts=[dict(r) for r in rows])


@app.get("/api/admin/projects")
def admin_projects():
    user, err = _require_admin()
    if err:
        return err
    with db() as conn:
        rows = conn.execute(
            """SELECT p.*, u.full_name AS participant_name, u.school,
                      (SELECT COUNT(*) FROM evaluations e WHERE e.project_id=p.id) AS evaluations
               FROM projects p LEFT JOIN users u ON u.id=p.user_id
               ORDER BY p.id""").fetchall()
    return jsonify(projects=[{**_project_json(r), "participant_name": r["participant_name"],
                              "school": r["school"], "evaluations": r["evaluations"]} for r in rows])


@app.patch("/api/admin/projects/<int:pid>")
def admin_update_project(pid):
    user, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if data.get("status") not in PROJECT_STATUSES:
        return jsonify(error="Недопустимый статус."), 400
    with db() as conn:
        conn.execute("UPDATE projects SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (data["status"], pid))
    return jsonify(message="Статус проекта обновлён.")


@app.get("/api/admin/comments")
def admin_comments():
    user, err = _require_admin()
    if err:
        return err
    status = request.args.get("status")
    with db() as conn:
        if status:
            rows = conn.execute("SELECT * FROM comments WHERE status=? ORDER BY created_at DESC",
                                (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM comments ORDER BY created_at DESC").fetchall()
    return jsonify(comments=[dict(r) for r in rows])


@app.patch("/api/admin/comments/<int:cid>")
def admin_update_comment(cid):
    user, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if data.get("status") not in ("pending", "approved", "rejected"):
        return jsonify(error="Недопустимый статус."), 400
    with db() as conn:
        conn.execute("UPDATE comments SET status=? WHERE id=?", (data["status"], cid))
    return jsonify(message="Комментарий модерирован.")


@app.get("/api/admin/mailings")
def admin_mailings():
    user, err = _require_admin()
    if err:
        return err
    with db() as conn:
        rows = conn.execute("SELECT * FROM mailings ORDER BY created_at DESC").fetchall()
    return jsonify(mailings=[dict(r) for r in rows])


@app.post("/api/admin/mailings")
def admin_create_mailing():
    user, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    channel = data.get("channel", "email")
    if channel not in ("email", "push", "vk"):
        return jsonify(error="Недопустимый канал рассылки."), 400
    audience = str(data.get("audience", "all"))
    try:
        subject = text_field(data.get("subject"), "Тема", 200)
        body = text_field(data.get("body"), "Текст", 5000)
    except ValueError as e:
        return jsonify(error=str(e)), 400

    # VK ID authenticates users, but does not grant permission to send them VK messages.
    # VK delivery requires a separately configured community bot/API integration.
    if channel == "vk":
        return jsonify(error="Отправка сообщений во ВКонтакте требует токена сообщества и согласия получателей. Сейчас доступна реальная email-рассылка; VK ID используется для входа."), 501
    if channel == "push":
        return jsonify(error="Push-уведомления пока не настроены. Выбери email."), 501

    with db() as conn:
        if audience.startswith("email:"):
            recipient_email = audience.partition(":")[2].strip().lower()
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient_email):
                return jsonify(error="Укажи корректный email конкретного получателя."), 400
            recipients = conn.execute("SELECT id,email,name FROM users WHERE lower(email)=?", (recipient_email,)).fetchall()
            if not recipients:
                return jsonify(error="Пользователь с таким email не найден. Сначала зарегистрируй его на сайте."), 404
        elif audience.startswith("nomination:"):
            nomination = audience.partition(":")[2].strip()
            if not nomination:
                return jsonify(error="Выбери номинацию."), 400
            recipients = conn.execute(
                """SELECT DISTINCT u.id,u.email,u.name FROM users u
                   JOIN projects p ON (p.user_id=u.id OR lower(p.participant_name)=lower(u.name))
                   WHERE u.role='participant' AND p.nomination=? AND u.email NOT LIKE '%@vk.local'
                   ORDER BY u.id""", (nomination,)).fetchall()
        else:
            audience_role = {"participants": "participant", "supervisors": "supervisor",
                             "experts": "expert"}.get(audience, audience)
            if audience == "all":
                recipients = conn.execute("SELECT id,email,name FROM users WHERE email NOT LIKE '%@vk.local'").fetchall()
            elif audience == "pending":
                recipients = conn.execute("SELECT id,email,name FROM users WHERE approval_status='pending' AND email NOT LIKE '%@vk.local'").fetchall()
            else:
                recipients = conn.execute("SELECT id,email,name FROM users WHERE role=? AND email NOT LIKE '%@vk.local'", (audience_role,)).fetchall()
        count = len(recipients)
        cur = conn.execute(
            "INSERT INTO mailings(channel,subject,body,audience,recipients_count) VALUES(?,?,?,?,?)",
            (channel, subject, body, audience, count))

    sent = 0
    queued = 0
    errors = 0
    for recipient in recipients:
        try:
            result = log_email(recipient["email"], subject, body)
            sent += result == "sent"
            queued += result == "queued"
        except Exception:
            errors += 1
            app.logger.exception("Email delivery failed for user id=%s", recipient["id"])
    if sent:
        message = f"Письмо отправлено: {sent} из {count}."
    elif queued and not errors:
        message = f"SMTP не настроен: {queued} писем сохранено в outbox, реальные письма не отправлены."
    else:
        message = f"Рассылка завершена. Отправлено: {sent}, сохранено в outbox: {queued}, ошибок: {errors}."
    return jsonify(message=message, mailing_id=cur.lastrowid, sent=sent, queued=queued, errors=errors), 201


@app.get("/api/admin/report")
def admin_report():
    user, err = _require_admin()
    if err:
        return err
    with db() as conn:
        by_nomination = [dict(r) for r in conn.execute(
            """SELECT nomination,
                      COUNT(*) total,
                      SUM(CASE WHEN status='evaluated' THEN 1 ELSE 0 END) evaluated,
                      SUM(CASE WHEN status IN ('review','accepted','expertise') THEN 1 ELSE 0 END) in_work
               FROM projects GROUP BY nomination""").fetchall()]
        by_region = [dict(r) for r in conn.execute(
            """SELECT COALESCE(NULLIF(region,''),'Не указан') region, COUNT(*) participants
               FROM users WHERE role='participant' GROUP BY region ORDER BY participants DESC""").fetchall()]
    return jsonify(by_nomination=by_nomination, by_region=by_region,
                   generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"))


@app.get("/api/admin/export/<kind>.csv")
def admin_export_csv(kind):
    user, err = _require_admin()
    if err:
        return err
    out = io.StringIO()
    out.write("\ufeff")  # BOM для корректного открытия кириллицы в Excel
    writer = csv.writer(out, delimiter=";")
    with db() as conn:
        if kind == "users":
            writer.writerow(["ID", "ФИО", "Email", "Роль", "Школа/Организация",
                             "Регион", "Статус", "Согласие ПДн", "Дата"])
            for r in conn.execute("SELECT * FROM users ORDER BY id").fetchall():
                writer.writerow([r["id"], r["full_name"] or r["name"], r["email"], r["role"],
                                 r["school"], r["region"], r["approval_status"],
                                 "да" if r["consent_pdn"] else "нет", r["created_at"]])
        elif kind == "projects":
            writer.writerow(["ID", "Название", "Номинация", "Участник", "Статус",
                             "Оценок", "Создан"])
            for r in conn.execute(
                    """SELECT p.*, u.full_name participant, 
                              (SELECT COUNT(*) FROM evaluations e WHERE e.project_id=p.id) ev
                       FROM projects p LEFT JOIN users u ON u.id=p.user_id ORDER BY p.id""").fetchall():
                writer.writerow([r["id"], r["title"], r["nomination"], r["participant"],
                                 r["status"], r["ev"], r["created_at"]])
        elif kind == "report":
            writer.writerow(["Номинация", "Всего", "Оценено", "В работе"])
            for r in conn.execute(
                    """SELECT nomination,
                              COUNT(*) total,
                              SUM(CASE WHEN status='evaluated' THEN 1 ELSE 0 END) ev,
                              SUM(CASE WHEN status IN ('review','accepted','expertise') THEN 1 ELSE 0 END) w
                       FROM projects GROUP BY nomination""").fetchall():
                writer.writerow([r["nomination"], r["total"], r["ev"], r["w"]])
        else:
            return jsonify(error="Неизвестный отчёт."), 404
    data = out.getvalue()
    return Response(data, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{kind}-export.csv"'})


# --------------------------------------------------------------------------- #
# Публичный контент
# --------------------------------------------------------------------------- #
@app.get("/api/news")
def public_news():
    with db() as conn:
        rows = conn.execute("SELECT * FROM news WHERE published=1 ORDER BY created_at DESC").fetchall()
    return jsonify(news=[dict(r) for r in rows])


@app.get("/api/media")
def public_media():
    with db() as conn:
        rows = conn.execute("SELECT * FROM media ORDER BY created_at DESC").fetchall()
    return jsonify(media=[dict(r) for r in rows])


@app.get("/api/banners")
def public_banners():
    with db() as conn:
        rows = conn.execute("SELECT * FROM banners WHERE active=1 ORDER BY id DESC").fetchall()
    return jsonify(banners=[dict(r) for r in rows])


@app.get("/api/stages")
def public_stages():
    with db() as conn:
        rows = conn.execute("SELECT * FROM stages ORDER BY order_index, id").fetchall()
    return jsonify(stages=[dict(r) for r in rows])


@app.get("/api/nominations")
def public_nominations():
    with db() as conn:
        rows = conn.execute("SELECT * FROM nominations WHERE active=1 ORDER BY id").fetchall()
    return jsonify(nominations=[dict(r) for r in rows])


@app.get("/<path:filename>")
def frontend(filename):
    target = (BASE_DIR / filename).resolve()
    if not str(target).startswith(str(BASE_DIR.resolve())) or not target.is_file():
        return jsonify(error="Файл не найден."), 404
    return send_from_directory(BASE_DIR, filename)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Размер загружаемых файлов слишком большой."), 413


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
