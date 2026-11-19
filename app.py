import os
import secrets
import sqlite3
import json
import uuid
from urllib.parse import urlparse, parse_qs
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "naqd_nama.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD_HASH = "pbkdf2:sha256:600000$1227e8c5957fa46c6bf9800aa156007b$e9234303315d912645b22564b604fea0268b07cf1e843cb276e69e5eb328f867"
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", DEFAULT_ADMIN_PASSWORD_HASH)
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def save_image(file):
    if not file or not file.filename:
        return ""
    original = secure_filename(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return ""
    filename = f"{uuid.uuid4().hex}.{ext}"
    file.save(UPLOAD_DIR / filename)
    return url_for("static", filename=f"uploads/{filename}")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('film','game')),
                genre TEXT NOT NULL DEFAULT 'متفرقه',
                year TEXT DEFAULT '',
                score REAL NOT NULL DEFAULT 7.0,
                poster TEXT DEFAULT '',
                platform TEXT DEFAULT '',
                summary TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
        if "images" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN images TEXT NOT NULL DEFAULT '[]'")
        if "country" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN country TEXT NOT NULL DEFAULT ''")
        if "film_type" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN film_type TEXT NOT NULL DEFAULT 'cinema'")
        if "game_device" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN game_device TEXT NOT NULL DEFAULT 'computer'")
        if "trailer" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN trailer TEXT NOT NULL DEFAULT ''")
        if "content_type" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN content_type TEXT NOT NULL DEFAULT 'review'")
        if "author" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN author TEXT NOT NULL DEFAULT 'تحریریه Zengo'")
        if "meta_description" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN meta_description TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in columns:
            conn.execute("ALTER TABLE reviews ADD COLUMN updated_at TIMESTAMP")
        # Keep older entries visible in the new subcategories.
        conn.execute("UPDATE reviews SET film_type='cinema' WHERE kind='film' AND (film_type IS NULL OR film_type='')")
        conn.execute("UPDATE reviews SET game_device='mobile' WHERE kind='game' AND platform IN ('Android','iOS') AND game_device='computer'")
        conn.execute("CREATE TABLE IF NOT EXISTS site_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')")
        defaults = {
            "home_heading": "دنیای سرگرمی، از زاویه‌ای تازه",
            "home_description": "خبرها، انتخاب‌ها و نقدهایی برای کسانی که به چیزی فراتر از تماشا و بازی فکر می‌کنند.",
            "youtube_url": "", "x_url": "", "instagram_url": "",
            "ads_enabled": "0", "contact_email": "",
            "home_editorial_title": "خبر، راهنما و تحلیل",
            "home_games_title": "تازه‌ترین نقد بازی‌ها",
            "home_films_title": "تازه‌ترین نقد فیلم و سریال",
            "footer_description": "نگاهی دقیق‌تر به فیلم، سریال و بازی.",
            "accent_theme": "violet"
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO site_settings(key,value) VALUES(?,?)", (key, value))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(review_id) REFERENCES reviews(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_comments_review ON comments(review_id)")
        count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        if count == 0:
            samples = [
                ("نمونه: میان‌ستاره‌ای", "film", "علمی‌تخیلی", "2014", 8.7, "", "داستانی درباره سفر در فضا، زمان و پیوندهای انسانی.", "این یک نقد نمونه است. از پنل مدیریت می‌توانی اطلاعات و نقدهای واقعی خودت را اضافه کنی."),
                ("نمونه: ویچر ۳", "game", "نقش‌آفرینی", "2015", 9.2, "", "جهانی گسترده با شخصیت‌ها و انتخاب‌های داستانی.", "این یک نقد نمونه است. متن کامل نقد را از پنل مدیریت ویرایش کن."),
                ("نمونه: تلماسه", "film", "علمی‌تخیلی", "2021", 8.1, "", "اقتباسی حماسی با فضاسازی چشمگیر.", "این یک نقد نمونه است. این بخش را با دیدگاه و تحلیل خودت جایگزین کن.")
            ]
            conn.executemany("INSERT INTO reviews(title,kind,genre,year,score,poster,summary,body) VALUES(?,?,?,?,?,?,?,?)", samples)

def get_site_settings():
    with db() as conn:
        rows = conn.execute("SELECT key,value FROM site_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}

def get_current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with db() as conn:
        row = conn.execute("SELECT id, username FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


@app.context_processor
def inject_site_settings():
    settings = get_site_settings()
    accent_colors = {"violet": "#9b82ff", "cyan": "#36c9d8", "coral": "#ff806e", "lime": "#a5ce68"}
    return {
        "site_settings": settings,
        "site_accent": accent_colors.get(settings.get("accent_theme", "violet"), "#9b82ff"),
        "current_user": get_current_user(),
    }


def login_user_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("برای این کار باید وارد حساب کاربری شوی.", "error")
            return redirect(url_for("user_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def get_genres(kind):
    """Return genres used by the selected catalog, with a safe fallback."""
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT genre FROM reviews WHERE kind=? AND genre<>'' ORDER BY genre COLLATE NOCASE",
            (kind,),
        ).fetchall()
    names = [row["genre"] for row in rows]
    if "متفرقه" not in names:
        names.append("متفرقه")
    return [{"name": name} for name in names]


@app.template_filter("from_json")
def from_json_filter(value):
    try:
        return json.loads(value or "[]") if isinstance(value, str) else (value or [])
    except (TypeError, ValueError):
        return []

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
def index():
    with db() as conn:
        reviews = conn.execute("SELECT * FROM reviews ORDER BY created_at DESC, id DESC").fetchall()
        featured = conn.execute("SELECT * FROM reviews WHERE content_type IN ('news','guide','feature') ORDER BY created_at DESC, id DESC LIMIT 6").fetchall()
    return render_template("index.html", reviews=reviews, featured=featured)

@app.route("/films")
def films():
    return render_template("categories.html", category="film")

@app.route("/films/<film_type>")
def film_catalog(film_type):
    if film_type not in ("series", "cinema"):
        abort(404)
    with db() as conn:
        reviews = conn.execute("SELECT * FROM reviews WHERE kind='film' AND film_type=? ORDER BY created_at DESC, id DESC", (film_type,)).fetchall()
    return render_template("catalog.html", reviews=reviews, genres=get_genres("film"), page_kind="film", subtype=film_type)

@app.route("/news")
def news():
    with db() as conn:
        items = conn.execute(
            "SELECT * FROM reviews WHERE content_type IN ('news','guide','feature') ORDER BY created_at DESC, id DESC LIMIT 60"
        ).fetchall()
    return render_template("news.html", items=items)


@app.route("/games")
def games():
    return render_template("categories.html", category="game")

@app.route("/games/<game_device>")
def game_catalog(game_device):
    if game_device not in ("mobile", "computer"):
        abort(404)
    with db() as conn:
        reviews = conn.execute("SELECT * FROM reviews WHERE kind='game' AND game_device=? ORDER BY created_at DESC, id DESC", (game_device,)).fetchall()
    return render_template("catalog.html", reviews=reviews, genres=get_genres("game"), page_kind="game", subtype=game_device)

@app.route("/search")
def search():
    kind = request.args.get("kind", "film").strip().lower()
    query = request.args.get("q", "").strip()[:100]
    if kind not in ("film", "game"):
        abort(400)
    results = []
    if query:
        pattern = f"%{query}%"
        with db() as conn:
            results = conn.execute(
                """SELECT * FROM reviews WHERE kind=? AND
                   (title LIKE ? OR summary LIKE ? OR body LIKE ? OR genre LIKE ? OR country LIKE ? OR platform LIKE ?)
                   ORDER BY created_at DESC, id DESC LIMIT 100""",
                (kind, pattern, pattern, pattern, pattern, pattern, pattern),
            ).fetchall()
    return render_template("search_results.html", results=results, kind=kind, query=query)


def trailer_details(value):
    """Return a safe embed URL or direct-video URL for supported trailer hosts."""
    if not value:
        return None
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            return None
        if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if not video_id and parsed.path.startswith("/embed/"):
                video_id = parsed.path.split("/embed/", 1)[1].split("/", 1)[0]
            if video_id and len(video_id) <= 20:
                return {"type": "embed", "url": f"https://www.youtube-nocookie.com/embed/{video_id}"}
        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/", 1)[0]
            if video_id and len(video_id) <= 20:
                return {"type": "embed", "url": f"https://www.youtube-nocookie.com/embed/{video_id}"}
        if host in ("vimeo.com", "www.vimeo.com"):
            video_id = parsed.path.strip("/").split("/", 1)[0]
            if video_id.isdigit():
                return {"type": "embed", "url": f"https://player.vimeo.com/video/{video_id}"}
        if host and parsed.path.lower().endswith((".mp4", ".webm", ".ogg")):
            return {"type": "video", "url": value.strip()}
    except (ValueError, AttributeError):
        pass
    return None


@app.route("/review/<int:review_id>")
def review_detail(review_id):
    with db() as conn:
        review = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        related = []
        comments = []
        if review:
            related = conn.execute(
                """SELECT * FROM reviews WHERE id<>? AND kind=? AND genre=?
                   ORDER BY created_at DESC, id DESC LIMIT 3""",
                (review_id, review["kind"], review["genre"]),
            ).fetchall()
            if len(related) < 3:
                extra = conn.execute(
                    """SELECT * FROM reviews WHERE id<>? AND kind=? AND id NOT IN ({})
                       ORDER BY created_at DESC, id DESC LIMIT ?""".format(
                        ",".join(str(r["id"]) for r in related) or "0"
                    ),
                    (review_id, review["kind"], 3 - len(related)),
                ).fetchall()
                related = list(related) + list(extra)
            comments = conn.execute(
                """SELECT c.id, c.body, c.created_at, u.username
                   FROM comments c JOIN users u ON u.id = c.user_id
                   WHERE c.review_id=? ORDER BY c.created_at DESC, c.id DESC LIMIT 200""",
                (review_id,),
            ).fetchall()
    if not review:
        abort(404)
    trailer = trailer_details(review["trailer"] if "trailer" in review.keys() else "")
    word_count = len((review["body"] or "").split())
    reading_minutes = max(1, round(word_count / 220))
    return render_template(
        "review.html",
        review=review,
        trailer=trailer,
        related=related,
        reading_minutes=reading_minutes,
        comments=comments,
    )


@app.route("/review/<int:review_id>/comment", methods=["POST"])
@login_user_required
def post_comment(review_id):
    body = (request.form.get("body") or "").strip()
    if len(body) < 2:
        flash("متن نظر خیلی کوتاه است.", "error")
        return redirect(url_for("review_detail", review_id=review_id))
    if len(body) > 2000:
        flash("متن نظر حداکثر ۲۰۰۰ کاراکتر باشد.", "error")
        return redirect(url_for("review_detail", review_id=review_id))
    with db() as conn:
        exists = conn.execute("SELECT id FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not exists:
            abort(404)
        conn.execute(
            "INSERT INTO comments(review_id, user_id, body) VALUES (?,?,?)",
            (review_id, session["user_id"], body),
        )
    flash("نظر شما ثبت شد.", "success")
    return redirect(url_for("review_detail", review_id=review_id) + "#comments")


def _valid_username(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 32:
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    # also allow common Persian letters
    for ch in name:
        if ch in allowed:
            continue
        if "\u0600" <= ch <= "\u06FF":
            continue
        return False
    return True


@app.route("/register", methods=["GET", "POST"])
def user_register():
    if session.get("user_id"):
        return redirect(url_for("index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        if not _valid_username(username):
            flash("نام کاربری باید ۳ تا ۳۲ کاراکتر و بدون فاصله/نویسه‌های خاص باشد.", "error")
            return render_template("auth_user.html", mode="register")
        if len(password) < 6 or len(password) > 128:
            flash("رمز عبور حداقل ۶ کاراکتر باشد.", "error")
            return render_template("auth_user.html", mode="register")
        if password != password2:
            flash("تکرار رمز با رمز عبور یکسان نیست.", "error")
            return render_template("auth_user.html", mode="register")
        if username.lower() == ADMIN_USERNAME.lower():
            flash("این نام کاربری در دسترس نیست.", "error")
            return render_template("auth_user.html", mode="register")
        try:
            with db() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash) VALUES (?,?)",
                    (username, generate_password_hash(password)),
                )
                row = conn.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            session.pop("admin", None)
            session["user_id"] = row["id"]
            session["username"] = username
            flash("حساب کاربری ساخته شد. خوش آمدی!", "success")
            return redirect(request.args.get("next") or url_for("index"))
        except sqlite3.IntegrityError:
            flash("این نام کاربری قبلاً ثبت شده است.", "error")
            return render_template("auth_user.html", mode="register")
    return render_template("auth_user.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def user_login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        with db() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash FROM users WHERE username=? COLLATE NOCASE",
                (username,),
            ).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.pop("admin", None)
            session["user_id"] = row["id"]
            session["username"] = row["username"]
            flash("با موفقیت وارد شدی.", "success")
            nxt = request.args.get("next") or request.form.get("next") or url_for("index")
            if not str(nxt).startswith("/"):
                nxt = url_for("index")
            return redirect(nxt)
        flash("نام کاربری یا رمز عبور اشتباه است.", "error")
    return render_template("auth_user.html", mode="login")


@app.route("/logout", methods=["POST", "GET"])
def user_logout():
    session.pop("user_id", None)
    session.pop("username", None)
    flash("از حساب خارج شدی.", "success")
    return redirect(url_for("index"))

@app.route("/api/reviews")
def api_reviews():
    with db() as conn:
        rows = conn.execute("SELECT id,title,kind,content_type,genre,year,score,poster,summary,author,created_at FROM reviews ORDER BY created_at DESC").fetchall()
    return jsonify([dict(row) for row in rows])

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if secrets.compare_digest(username, ADMIN_USERNAME) and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("نام کاربری یا رمز عبور درست نیست.", "error")
    return render_template("login.html")

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    with db() as conn:
        reviews = conn.execute("SELECT * FROM reviews ORDER BY created_at DESC, id DESC").fetchall()
    return render_template("admin.html", reviews=reviews)


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    keys = ("youtube_url", "x_url", "instagram_url", "contact_email", "ads_enabled",
            "home_editorial_title", "home_games_title", "home_films_title", "footer_description", "accent_theme")
    if request.method == "POST":
        values = {key: request.form.get(key, "").strip()[:500] for key in keys}
        values["ads_enabled"] = "1" if request.form.get("ads_enabled") == "1" else "0"
        if values["accent_theme"] not in {"violet", "cyan", "coral", "lime"}:
            values["accent_theme"] = "violet"
        for key in ("home_editorial_title", "home_games_title", "home_films_title", "footer_description"):
            values[key] = values[key][:120]
        email = values["contact_email"]
        if email and ("@" not in email or len(email) > 254):
            flash("ایمیل تماس معتبر نیست.", "error")
            return render_template("settings.html", settings=get_site_settings())
        for key in ("youtube_url", "x_url", "instagram_url"):
            value = values[key]
            if value and (not value.startswith("https://") or len(value) > 300):
                flash("لینک شبکه‌های اجتماعی باید با https:// شروع شود.", "error")
                return render_template("settings.html", settings=get_site_settings())
        with db() as conn:
            conn.executemany("INSERT INTO site_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", values.items())
        flash("تنظیمات سایت ذخیره شد.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("settings.html", settings=get_site_settings())

@app.route("/admin/review/new", methods=["GET", "POST"])
@app.route("/admin/review/<int:review_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_review(review_id=None):
    review = None
    if review_id is not None:
        with db() as conn:
            review = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not review:
            abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        kind = request.form.get("kind", "film")
        genre = request.form.get("genre", "").strip() or "متفرقه"
        year = request.form.get("year", "").strip()
        poster = request.form.get("poster", "").strip()
        uploaded_poster = save_image(request.files.get("poster_file"))
        if uploaded_poster:
            poster = uploaded_poster
        platform = request.form.get("platform", "").strip() if kind == "game" else ""
        country = request.form.get("country", "").strip()
        film_type = request.form.get("film_type", "cinema").strip() if kind == "film" else "cinema"
        game_device = request.form.get("game_device", "computer").strip() if kind == "game" else "computer"
        trailer = request.form.get("trailer", "").strip()
        content_type = request.form.get("content_type", "review").strip()
        if content_type not in ("review", "news", "guide", "feature"):
            content_type = "review"
        author = request.form.get("author", "تحریریه Zengo").strip()[:100] or "تحریریه Zengo"
        meta_description = request.form.get("meta_description", "").strip()[:300]
        trailer_info = trailer_details(trailer) if trailer else None
        if trailer and not trailer_info:
            flash("لینک تریلر معتبر نیست. لینک امن YouTube، Vimeo یا فایل MP4/WEBM با HTTPS وارد کن.", "error")
            return render_template("edit.html", review=request.form, page_title="ویرایش نقد" if review else "افزودن نقد")
        if film_type not in ("series", "cinema"):
            film_type = "cinema"
        if game_device not in ("mobile", "computer"):
            game_device = "computer"
        new_images = [save_image(f) for f in request.files.getlist("gallery_files")]
        new_images = [item for item in new_images if item]
        try:
            old_images = json.loads(review["images"] or "[]") if review else []
        except (TypeError, ValueError):
            old_images = []
        images = old_images + new_images
        summary = request.form.get("summary", "").strip()
        body = request.form.get("body", "").strip()
        try:
            score = float(request.form.get("score", "7"))
        except ValueError:
            score = 7.0
        score = min(10, max(0, score))
        if not title or not summary or not body or kind not in ("film", "game"):
            flash("عنوان، خلاصه و متن نقد را کامل کن.", "error")
            return render_template("edit.html", review=request.form, page_title="ویرایش نقد" if review else "افزودن نقد")
        with db() as conn:
            if review:
                conn.execute("""UPDATE reviews SET title=?,kind=?,genre=?,year=?,score=?,poster=?,platform=?,summary=?,body=?,images=?,country=?,film_type=?,game_device=?,trailer=?,content_type=?,author=?,meta_description=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                             (title, kind, genre, year, score, poster, platform, summary, body, json.dumps(images, ensure_ascii=False), country, film_type, game_device, trailer, content_type, author, meta_description, review_id))
            else:
                conn.execute("""INSERT INTO reviews(title,kind,genre,year,score,poster,platform,summary,body,images,country,film_type,game_device,trailer,content_type,author,meta_description) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (title, kind, genre, year, score, poster, platform, summary, body, json.dumps(images, ensure_ascii=False), country, film_type, game_device, trailer, content_type, author, meta_description))
        flash("نقد با موفقیت ذخیره شد.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("edit.html", review=review, page_title="ویرایش نقد" if review else "افزودن نقد")

@app.route("/admin/review/<int:review_id>/delete", methods=["POST"])
@admin_required
def delete_review(review_id):
    with db() as conn:
        conn.execute("DELETE FROM reviews WHERE id=?", (review_id,))
    flash("نقد حذف شد.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/about")
def about():
    return render_template("info_page.html", page_key="about", page_title="درباره Zengo")

@app.route("/editorial-policy")
def editorial_policy():
    return render_template("info_page.html", page_key="editorial", page_title="سیاست تحریریه")

@app.route("/advertise")
def advertise():
    return render_template("info_page.html", page_key="advertise", page_title="تبلیغات و همکاری")

@app.route("/privacy")
def privacy():
    return render_template("info_page.html", page_key="privacy", page_title="حریم خصوصی")

@app.route("/contact")
def contact():
    return render_template("info_page.html", page_key="contact", page_title="تماس با ما")

@app.route("/sitemap.xml")
def sitemap():
    from flask import make_response
    with db() as conn:
        rows = conn.execute("SELECT id, created_at FROM reviews ORDER BY id DESC").fetchall()
    base = request.url_root.rstrip("/")
    urls = [("/", "daily", "1.0"), ("/films", "weekly", "0.8"), ("/games", "weekly", "0.8"), ("/news", "daily", "0.8"), ("/about", "monthly", "0.3"), ("/editorial-policy", "monthly", "0.3"), ("/advertise", "monthly", "0.3"), ("/privacy", "monthly", "0.2"), ("/contact", "monthly", "0.3")]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, freq, priority in urls:
        parts.append(f'<url><loc>{base}{path}</loc><changefreq>{freq}</changefreq><priority>{priority}</priority></url>')
    for row in rows:
        parts.append(f'<url><loc>{base}/review/{row["id"]}</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>')
    parts.append('</urlset>')
    response = make_response("\n".join(parts))
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    return response

@app.route("/robots.txt")
def robots_txt():
    from flask import make_response
    response = make_response(f"User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nSitemap: {request.url_root.rstrip('/')}/sitemap.xml\n")
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response

@app.route("/manifest.json")
def manifest():
    return app.send_static_file("manifest.json")

@app.route("/sw.js")
def service_worker():
    return app.send_static_file("sw.js")

@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404

init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
