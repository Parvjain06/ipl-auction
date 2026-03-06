from flask import Flask, render_template, request, redirect, session
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import random
import threading
import sys

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "ipl-auction-secret-key-2026")

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")
else:
    DATABASE_URL = "sqlite:///ipl.db"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

is_sqlite = DATABASE_URL.startswith("sqlite")

DEFAULT_TEAMS = ["MI", "CSK", "RCB", "KKR", "SRH"]
TEAM_BUDGET = 1000

STAT_COLS = [
    ("sold", "INTEGER DEFAULT 0"),
    ("sold_price", "INTEGER"),
    ("sold_team", "TEXT"),
    ("batting_avg", "REAL"),
    ("strike_rate", "REAL"),
    ("economy", "REAL"),
    ("centuries", "INTEGER"),
    ("fifties", "INTEGER"),
    ("catches", "INTEGER"),
]


def log(msg):
    print(msg, flush=True)


# --------------------------
# CREATE TABLES & SEED DATA
# --------------------------

def create_tables():
    with engine.connect() as conn:
        if is_sqlite:
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS players(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, country TEXT, role TEXT,
            matches INTEGER, runs INTEGER, wickets INTEGER,
            base_price INTEGER,
            sold INTEGER DEFAULT 0, sold_price INTEGER, sold_team TEXT,
            batting_avg REAL, strike_rate REAL, economy REAL,
            centuries INTEGER, fifties INTEGER, catches INTEGER
            )
            """))
            for col, coltype in STAT_COLS:
                try:
                    conn.execute(text(f"ALTER TABLE players ADD COLUMN {col} {coltype}"))
                except Exception:
                    pass
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS teams(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, budget INTEGER
            )
            """))
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auction(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER, current_price INTEGER,
            highest_bidder TEXT, status TEXT
            )
            """))
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE, password_hash TEXT, role TEXT
            )
            """))
        else:
            # Players
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS players(
            id SERIAL PRIMARY KEY,
            name TEXT, country TEXT, role TEXT,
            matches INTEGER, runs INTEGER, wickets INTEGER,
            base_price INTEGER,
            sold INTEGER DEFAULT 0, sold_price INTEGER, sold_team TEXT,
            batting_avg REAL, strike_rate REAL, economy REAL,
            centuries INTEGER, fifties INTEGER, catches INTEGER
            )
            """))
            for col, coltype in STAT_COLS:
                pg_type = coltype.replace("REAL", "DOUBLE PRECISION")
                try:
                    conn.execute(text(f"ALTER TABLE players ADD COLUMN IF NOT EXISTS {col} {pg_type}"))
                except Exception:
                    pass

            # Teams — CREATE IF NOT EXISTS (don't drop!)
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS teams(
            id SERIAL PRIMARY KEY,
            name TEXT, budget INTEGER
            )
            """))

            # Auction — CREATE IF NOT EXISTS, add missing columns
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auction(
            id SERIAL PRIMARY KEY,
            player_id INTEGER, current_price INTEGER,
            highest_bidder TEXT, status TEXT
            )
            """))
            try:
                conn.execute(text("ALTER TABLE auction ADD COLUMN IF NOT EXISTS highest_bidder TEXT"))
            except Exception:
                pass

            # Users
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE, password_hash TEXT, role TEXT
            )
            """))

        conn.commit()


def seed_teams():
    with engine.connect() as conn:
        for team_name in DEFAULT_TEAMS:
            existing = conn.execute(
                text("SELECT * FROM teams WHERE name=:n"), {"n": team_name}
            ).fetchone()
            if not existing:
                conn.execute(
                    text("INSERT INTO teams(name, budget) VALUES(:n, :b)"),
                    {"n": team_name, "b": TEAM_BUDGET},
                )
        conn.commit()


def generate_player_stats():
    with engine.connect() as conn:
        players = conn.execute(text("SELECT id, role, matches, runs, wickets FROM players")).fetchall()
        for p in players:
            role = p.role or "Batsman"
            matches = p.matches or 50
            runs = p.runs or 0

            innings = max(1, int(matches * 0.9))
            batting_avg = round(runs / innings, 2) if runs > 0 else round(random.uniform(5, 15), 2)

            if role == "Bowler":
                strike_rate = round(random.uniform(90, 120), 2)
                economy = round(random.uniform(5.5, 8.5), 2)
            elif role == "Allrounder":
                strike_rate = round(random.uniform(120, 155), 2)
                economy = round(random.uniform(6.5, 9.0), 2)
            else:
                strike_rate = round(random.uniform(125, 170), 2)
                economy = 0.0

            if runs > 5000:
                centuries = random.randint(5, 15)
                fifties = random.randint(20, 50)
            elif runs > 2000:
                centuries = random.randint(2, 8)
                fifties = random.randint(10, 25)
            elif runs > 500:
                centuries = random.randint(0, 3)
                fifties = random.randint(2, 10)
            else:
                centuries = 0
                fifties = random.randint(0, 3)

            catches = random.randint(10, max(15, matches // 3))
            base_price = random.choice(range(10, 110, 10))

            conn.execute(text("""
            UPDATE players SET
                base_price=:bp, batting_avg=:ba, strike_rate=:sr,
                economy=:ec, centuries=:c, fifties=:f, catches=:ca,
                sold = COALESCE(sold, 0)
            WHERE id=:id
            """), {
                "bp": base_price, "ba": batting_avg, "sr": strike_rate,
                "ec": economy, "c": centuries, "f": fifties, "ca": catches,
                "id": p.id
            })
        conn.commit()


# --------------------------
# BACKGROUND INIT
# --------------------------

_initialized = False

def run_initialization():
    global _initialized
    try:
        log("⏳ Starting initialization...")
        create_tables()
        log("✅ Tables created")
        seed_teams()
        log("✅ Teams seeded")
        generate_player_stats()
        log("✅ Player stats generated")
    except Exception as e:
        import traceback
        traceback.print_exc()
        log(f"❌ Startup error: {e}")
    finally:
        _initialized = True
        log("✅ Initialization complete!")

init_thread = threading.Thread(target=run_initialization, daemon=True)
init_thread.start()


@app.before_request
def wait_for_init():
    if not _initialized:
        log(f"⏳ Request waiting for init: {request.path}")
        init_thread.join(timeout=120)
        log(f"✅ Init done, serving: {request.path}")


# --------------------------
# AUTH HELPERS
# --------------------------

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if "user" not in session:
                return redirect("/login")
            if role and session.get("role") != role:
                return redirect("/")
            return f(*args, **kwargs)
        return wrapped
    return decorator


# --------------------------
# HOME
# --------------------------

@app.route("/")
def index():
    return render_template("index.html", session=session)


# --------------------------
# SIGNUP
# --------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html", teams=DEFAULT_TEAMS)

    role = request.form["role"]
    password = request.form["password"]

    if role == "auctioneer":
        username = "auctioneer"
    else:
        username = request.form.get("team", "").strip()
        if username not in DEFAULT_TEAMS:
            return render_template("signup.html", teams=DEFAULT_TEAMS, error="Invalid team")

    if not password or len(password) < 3:
        return render_template("signup.html", teams=DEFAULT_TEAMS, error="Password must be at least 3 characters")

    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT * FROM users WHERE username=:u"), {"u": username}
        ).fetchone()
        if existing:
            return render_template("signup.html", teams=DEFAULT_TEAMS, error=f"'{username}' is already registered. Please login.")

        conn.execute(text("""
        INSERT INTO users(username, password_hash, role)
        VALUES(:u, :p, :r)
        """), {"u": username, "p": generate_password_hash(password), "r": role})
        conn.commit()

    session["user"] = username
    session["role"] = role
    log(f"✅ Signup: {username} ({role})")

    if role == "auctioneer":
        return redirect("/auctioneer")
    else:
        return redirect(f"/team/{username}")


# --------------------------
# LOGIN
# --------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", teams=DEFAULT_TEAMS)

    username = request.form["username"].strip()
    password = request.form["password"]
    log(f"🔑 Login attempt: {username}")

    with engine.connect() as conn:
        user = conn.execute(
            text("SELECT * FROM users WHERE username=:u"), {"u": username}
        ).fetchone()

    if not user or not check_password_hash(user.password_hash, password):
        log(f"❌ Login failed: {username}")
        return render_template("login.html", teams=DEFAULT_TEAMS, error="Invalid username or password")

    session["user"] = user.username
    session["role"] = user.role
    log(f"✅ Login success: {username} ({user.role})")

    if user.role == "auctioneer":
        return redirect("/auctioneer")
    else:
        return redirect(f"/team/{user.username}")


# --------------------------
# LOGOUT
# --------------------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# --------------------------
# AUCTIONEER PAGE
# --------------------------

@app.route("/auctioneer")
@login_required(role="auctioneer")
def auctioneer():
    with engine.connect() as conn:
        players = conn.execute(text("SELECT * FROM players")).fetchall()
        teams = conn.execute(text("SELECT * FROM teams")).fetchall()
        auction = conn.execute(
            text("SELECT * FROM auction WHERE status='OPEN'")
        ).fetchone()

        auction_player = None
        if auction:
            auction_player = conn.execute(
                text("SELECT * FROM players WHERE id=:id"),
                {"id": auction.player_id},
            ).fetchone()

    return render_template(
        "auctioneer.html",
        players=players,
        teams=teams,
        auction=auction,
        auction_player=auction_player,
    )


# --------------------------
# TEAM BIDDING PAGE
# --------------------------

@app.route("/team/<name>")
@login_required(role="team")
def team_page(name):
    if session.get("user") != name:
        return redirect(f"/team/{session.get('user')}")

    with engine.connect() as conn:
        team = conn.execute(
            text("SELECT * FROM teams WHERE name=:n"), {"n": name}
        ).fetchone()
        if not team:
            return redirect("/")

        auction = conn.execute(
            text("SELECT * FROM auction WHERE status='OPEN'")
        ).fetchone()

        auction_player = None
        if auction:
            auction_player = conn.execute(
                text("SELECT * FROM players WHERE id=:id"),
                {"id": auction.player_id},
            ).fetchone()

        my_players = conn.execute(
            text("SELECT * FROM players WHERE sold_team=:t"),
            {"t": name},
        ).fetchall()

    return render_template(
        "team.html",
        team=team,
        auction=auction,
        auction_player=auction_player,
        my_players=my_players,
    )


# --------------------------
# START AUCTION (Auctioneer)
# --------------------------

@app.route("/start/<int:pid>")
@login_required(role="auctioneer")
def start(pid):
    with engine.connect() as conn:
        open_auction = conn.execute(
            text("SELECT * FROM auction WHERE status='OPEN'")
        ).fetchone()
        if open_auction:
            return redirect("/auctioneer")

        player = conn.execute(
            text("SELECT * FROM players WHERE id=:id"), {"id": pid}
        ).fetchone()
        if not player or player.sold == 1:
            return redirect("/auctioneer")

        conn.execute(
            text("""INSERT INTO auction(player_id, current_price, highest_bidder, status)
            VALUES(:pid, :price, NULL, 'OPEN')"""),
            {"pid": pid, "price": player.base_price},
        )
        conn.commit()

    return redirect("/auctioneer")


# --------------------------
# PLACE BID (Teams)
# --------------------------

@app.route("/bid", methods=["POST"])
@login_required(role="team")
def bid():
    team_name = session.get("user")
    bid_amount = int(request.form["bid"])

    with engine.connect() as conn:
        auction = conn.execute(
            text("SELECT * FROM auction WHERE status='OPEN'")
        ).fetchone()
        if not auction:
            return redirect(f"/team/{team_name}")

        if bid_amount <= auction.current_price:
            return redirect(f"/team/{team_name}")

        team_row = conn.execute(
            text("SELECT * FROM teams WHERE name=:n"), {"n": team_name}
        ).fetchone()
        if not team_row or bid_amount > team_row.budget:
            return redirect(f"/team/{team_name}")

        conn.execute(
            text("UPDATE auction SET current_price=:p, highest_bidder=:t WHERE id=:id"),
            {"p": bid_amount, "t": team_name, "id": auction.id},
        )
        conn.commit()

    return redirect(f"/team/{team_name}")


# --------------------------
# CLOSE AUCTION (Auctioneer)
# --------------------------

@app.route("/close", methods=["POST"])
@login_required(role="auctioneer")
def close():
    with engine.connect() as conn:
        auction = conn.execute(
            text("SELECT * FROM auction WHERE status='OPEN'")
        ).fetchone()
        if not auction:
            return redirect("/auctioneer")

        if not auction.highest_bidder:
            conn.execute(
                text("UPDATE auction SET status='UNSOLD' WHERE id=:id"),
                {"id": auction.id},
            )
            conn.commit()
            return redirect("/auctioneer")

        conn.execute(
            text("UPDATE players SET sold=1, sold_price=:price, sold_team=:team WHERE id=:pid"),
            {"price": auction.current_price, "team": auction.highest_bidder, "pid": auction.player_id},
        )
        conn.execute(
            text("UPDATE teams SET budget=budget-:price WHERE name=:team"),
            {"price": auction.current_price, "team": auction.highest_bidder},
        )
        conn.execute(
            text("UPDATE auction SET status='CLOSED' WHERE id=:id"),
            {"id": auction.id},
        )
        conn.commit()

    return redirect("/auctioneer")


# --------------------------
# MARK UNSOLD (Auctioneer)
# --------------------------

@app.route("/unsold", methods=["POST"])
@login_required(role="auctioneer")
def unsold():
    with engine.connect() as conn:
        auction = conn.execute(
            text("SELECT * FROM auction WHERE status='OPEN'")
        ).fetchone()
        if not auction:
            return redirect("/auctioneer")

        conn.execute(
            text("UPDATE auction SET status='UNSOLD' WHERE id=:id"),
            {"id": auction.id},
        )
        conn.commit()

    return redirect("/auctioneer")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)