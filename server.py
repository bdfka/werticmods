"""
WerticMods — API-сервер.
Только JSON. UI живёт на GitHub Pages (docs/index.html).
"""
import os, json, sqlite3
import requests
from functools import wraps
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

DB = "werticmods.db"
MODRINTH = "https://api.modrinth.com/v2"
UA = {"User-Agent": "WerticMods/1.0 (github.com/yourname/werticmods)"}

# Разрешённые origins для CORS
ALLOWED = [
    "http://127.0.0.1:5000",
    "http://localhost:5000",
    "null",  # file://
]
# Динамически добавим github.io домены — см. CORS(app, ...)

app = Flask(__name__)
app.secret_key = "werticmods_secret_change_me"
app.config.update(
    SESSION_COOKIE_SAMESITE="None",   # чтобы работало с github.io → localhost
    SESSION_COOKIE_SECURE=False,      # localhost без https
)

# CORS: разрешаем github.io и localhost
CORS(app,
     supports_credentials=True,
     origins=[
         r"https://.*\.github\.io",
         r"http://127\.0\.0\.1(:\d+)?",
         r"http://localhost(:\d+)?",
     ])

# ---------------- DB ----------------
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nick TEXT UNIQUE NOT NULL,
        pass TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 0,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS resources(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        banner TEXT, icon TEXT,
        downloads TEXT, libraries TEXT, optional_libraries TEXT,
        game_version TEXT, loader TEXT,
        coauthors TEXT DEFAULT '[]',
        gallery TEXT DEFAULT '[]',
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT, answer TEXT,
        status TEXT DEFAULT 'open',
        created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    if not c.execute("SELECT 1 FROM users WHERE nick='bdfka'").fetchone():
        c.execute("INSERT INTO users(nick,pass,is_admin,verified) VALUES(?,?,1,1)",
                  ("bdfka", generate_password_hash("bdfka")))
    c.commit()
    c.close()

init_db()

# ---------------- helpers ----------------
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return dict(u) if u else None

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not current_user():
            return jsonify(error="auth required"), 401
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        u = current_user()
        if not u or not u["is_admin"]:
            return jsonify(error="admin only"), 403
        return f(*a, **k)
    return w

# ---------------- AUTH ----------------
@app.post("/api/register")
def register():
    d = request.json or {}
    nick = (d.get("nick") or "").strip()
    pw = d.get("pass") or ""
    if len(nick) < 3 or len(pw) < 3:
        return jsonify(error="Ник и пароль минимум 3 символа"), 400
    c = db()
    try:
        c.execute("INSERT INTO users(nick,pass) VALUES(?,?)",
                  (nick, generate_password_hash(pw)))
        c.commit()
    except sqlite3.IntegrityError:
        c.close()
        return jsonify(error="Ник занят"), 400
    uid = c.execute("SELECT id FROM users WHERE nick=?", (nick,)).fetchone()["id"]
    c.close()
    session["uid"] = uid
    return jsonify(ok=True, user=current_user())

@app.post("/api/login")
def login():
    d = request.json or {}
    c = db()
    u = c.execute("SELECT * FROM users WHERE nick=?", (d.get("nick"),)).fetchone()
    c.close()
    if not u or not check_password_hash(u["pass"], d.get("pass") or ""):
        return jsonify(error="Неверный ник или пароль"), 400
    session["uid"] = u["id"]
    return jsonify(ok=True, user=current_user())

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
def me():
    return jsonify(user=current_user())

@app.get("/api/health")
def health():
    """Проверка связи фронта с сервером."""
    return jsonify(ok=True, version="1.0")

# ---------------- RESOURCES ----------------
@app.get("/api/resources")
def list_resources():
    q = request.args.get("q", "").strip()
    t = request.args.get("type", "").strip()
    c = db()
    sql = """SELECT r.*, u.nick, u.verified FROM resources r
             JOIN users u ON u.id=r.author_id WHERE 1=1"""
    args = []
    if q:
        sql += " AND (r.name LIKE ? OR r.description LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if t:
        sql += " AND r.type=?"
        args.append(t)
    sql += " ORDER BY r.id DESC"
    rows = [dict(x) for x in c.execute(sql, args).fetchall()]
    c.close()
    return jsonify(resources=rows)

@app.get("/api/resources/<int:rid>")
def get_resource(rid):
    c = db()
    r = c.execute("""SELECT r.*, u.nick AS author_nick, u.verified AS author_verified
                     FROM resources r JOIN users u ON u.id=r.author_id
                     WHERE r.id=?""", (rid,)).fetchone()
    if not r:
        c.close()
        return jsonify(error="Не найдено"), 404
    r = dict(r)
    try:
        r["coauthors_list"] = json.loads(r.get("coauthors") or "[]")
    except Exception:
        r["coauthors_list"] = []
    try:
        r["gallery_list"] = json.loads(r.get("gallery") or "[]")
    except Exception:
        r["gallery_list"] = []
    coauth = []
    for nick in r["coauthors_list"]:
        u = c.execute("SELECT id,nick,verified FROM users WHERE nick=?", (nick,)).fetchone()
        coauth.append(dict(u) if u else {"nick": nick, "id": None, "verified": 0})
    r["coauthors_details"] = coauth
    c.close()
    return jsonify(resource=r)

@app.post("/api/resources")
@login_required
def create_resource():
    d = request.json or {}
    u = current_user()
    if not d.get("name") or not d.get("type"):
        return jsonify(error="Название и тип обязательны"), 400
    co = json.dumps([n.strip() for n in (d.get("coauthors", "") or "").split(",") if n.strip()])
    gal = json.dumps([g.strip() for g in (d.get("gallery", "") or "").split(";") if g.strip()])
    c = db()
    c.execute("""INSERT INTO resources(author_id,type,name,description,banner,icon,
                 downloads,libraries,optional_libraries,game_version,loader,
                 coauthors,gallery) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (u["id"], d["type"], d["name"], d.get("description", ""),
               d.get("banner", ""), d.get("icon", ""), d.get("downloads", ""),
               d.get("libraries", ""), d.get("optional_libraries", ""),
               d.get("game_version", ""), d.get("loader", ""), co, gal))
    c.commit()
    rid = c.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    c.close()
    return jsonify(ok=True, id=rid)

@app.put("/api/resources/<int:rid>")
@login_required
def edit_resource(rid):
    u = current_user()
    d = request.json or {}
    c = db()
    r = c.execute("SELECT * FROM resources WHERE id=?", (rid,)).fetchone()
    if not r:
        c.close()
        return jsonify(error="Не найдено"), 404
    if r["author_id"] != u["id"] and not u["is_admin"]:
        c.close()
        return jsonify(error="Нет прав"), 403
    co = json.dumps([n.strip() for n in (d.get("coauthors", "") or "").split(",") if n.strip()])
    gal = json.dumps([g.strip() for g in (d.get("gallery", "") or "").split(";") if g.strip()])
    fields = ["type", "name", "description", "banner", "icon", "downloads",
              "libraries", "optional_libraries", "game_version", "loader"]
    sets = ", ".join(f"{f}=?" for f in fields) + ", coauthors=?, gallery=?"
    c.execute(f"UPDATE resources SET {sets} WHERE id=?",
              [d.get(f, r[f]) for f in fields] + [co, gal, rid])
    c.commit()
    c.close()
    return jsonify(ok=True)

@app.delete("/api/resources/<int:rid>")
@login_required
def delete_resource(rid):
    u = current_user()
    c = db()
    r = c.execute("SELECT * FROM resources WHERE id=?", (rid,)).fetchone()
    if not r:
        c.close()
        return jsonify(error="Не найдено"), 404
    if r["author_id"] != u["id"] and not u["is_admin"]:
        c.close()
        return jsonify(error="Нет прав"), 403
    c.execute("DELETE FROM resources WHERE id=?", (rid,))
    c.commit()
    c.close()
    return jsonify(ok=True)

# ---------------- MODRINTH ----------------
@app.get("/api/modrinth/search")
def mr_search():
    q = request.args.get("q", "").strip()
    t = request.args.get("type", "mod")
    facets = json.dumps([[f"project_type:{t}"]])
    try:
        r = requests.get(f"{MODRINTH}/search",
                         params={"query": q, "facets": facets, "limit": 20},
                         headers=UA, timeout=20)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify(error=str(e), hits=[]), 502

@app.get("/api/modrinth/versions/<pid>")
def mr_versions(pid):
    try:
        r = requests.get(f"{MODRINTH}/project/{pid}/version", headers=UA, timeout=20)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify(error=str(e)), 502

@app.post("/api/modrinth/install")
@login_required
def mr_install():
    d = request.json or {}
    url = d.get("url")
    filename = d.get("filename")
    version = (d.get("version") or "").strip()
    if not url or not filename:
        return jsonify(error="url и filename обязательны"), 400
    base = os.path.join(os.path.expanduser("~"), ".minecraft")
    target = os.path.join(base, "versions", version, "mods") if version else os.path.join(base, "mods")
    os.makedirs(target, exist_ok=True)
    try:
        r = requests.get(url, headers=UA, stream=True, timeout=120)
        r.raise_for_status()
        path = os.path.join(target, filename)
        with open(path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(ok=True, path=path)

# ---------------- ADMIN ----------------
@app.get("/api/admin/users")
@admin_required
def admin_users():
    c = db()
    rows = [dict(x) for x in c.execute(
        "SELECT id,nick,is_admin,verified,created FROM users ORDER BY id").fetchall()]
    c.close()
    return jsonify(users=rows)

@app.post("/api/admin/verify/<int:uid>")
@admin_required
def admin_verify(uid):
    val = 1 if (request.json or {}).get("verified") else 0
    c = db()
    c.execute("UPDATE users SET verified=? WHERE id=?", (val, uid))
    c.commit()
    c.close()
    return jsonify(ok=True)

@app.post("/api/admin/makeadmin/<int:uid>")
@admin_required
def admin_make(uid):
    val = 1 if (request.json or {}).get("admin") else 0
    c = db()
    c.execute("UPDATE users SET is_admin=? WHERE id=?", (val, uid))
    c.commit()
    c.close()
    return jsonify(ok=True)

# ---------------- TICKETS ----------------
@app.post("/api/tickets")
@login_required
def ticket_create():
    u = current_user()
    c = db()
    c.execute("INSERT INTO tickets(user_id,message) VALUES(?,?)",
              (u["id"], (request.json or {}).get("message", "")))
    c.commit()
    c.close()
    return jsonify(ok=True)

@app.get("/api/tickets")
@login_required
def tickets_list():
    u = current_user()
    c = db()
    if u["is_admin"]:
        rows = c.execute("""SELECT t.*, us.nick FROM tickets t
                            LEFT JOIN users us ON us.id=t.user_id
                            ORDER BY t.id DESC""").fetchall()
    else:
        rows = c.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC",
                         (u["id"],)).fetchall()
    c.close()
    return jsonify(tickets=[dict(x) for x in rows])

@app.post("/api/tickets/<int:tid>/answer")
@admin_required
def ticket_answer(tid):
    c = db()
    c.execute("UPDATE tickets SET answer=?, status='closed' WHERE id=?",
              ((request.json or {}).get("answer", ""), tid))
    c.commit()
    c.close()
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)