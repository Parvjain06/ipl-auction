from flask import Flask, render_template, request, redirect
from sqlalchemy import create_engine, text
import os
import random
import threading

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")
else:
    DATABASE_URL = "sqlite:///ipl.db"

engine = create_engine(DATABASE_URL)

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
        else:
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
                conn.execute(text(f"ALTER TABLE players ADD COLUMN IF NOT EXISTS {col} {pg_type}"))

            conn.execute(text("DROP TABLE IF EXISTS teams"))
            conn.execute(text("""
            CREATE TABLE teams(
            id SERIAL PRIMARY KEY,
            name TEXT, budget INTEGER
            )
            """))
            conn.execute(text("DROP TABLE IF EXISTS auction"))
            conn.execute(text("""
            CREATE TABLE auction(
            id SERIAL PRIMARY KEY,
            player_id INTEGER, current_price INTEGER,
            highest_bidder TEXT, status TEXT
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
    """Generate realistic random stats and base prices for all players."""
    with engine.connect() as conn:
        players = conn.execute(text("SELECT id, role, matches, runs, wickets FROM players")).fetchall()
        for p in players:
            role = p.role or "Batsman"
            matches = p.matches or 50
            runs = p.runs or 0
            wickets = p.wickets or 0

            # Calculate batting average
            innings = max(1, int(matches * 0.9))
            batting_avg = round(runs / innings, 2) if runs > 0 else round(random.uniform(5, 15), 2)

            # Strike rate based on role
            if role == "Bowler":
                strike_rate = round(random.uniform(90, 120), 2)
                economy = round(random.uniform(5.5, 8.5), 2)
            elif role == "Allrounder":
                strike_rate = round(random.uniform(120, 155), 2)
                economy = round(random.uniform(6.5, 9.0), 2)
            else:  # Batsman
                strike_rate = round(random.uniform(125, 170), 2)
                economy = 0.0

            # Centuries & fifties based on runs
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


_initialized = False

def run_initialization():
    global _initialized
    try:
        create_tables()
        print("✅ Tables created", flush=True)
        seed_teams()
        print("✅ Teams seeded", flush=True)
        generate_player_stats()
        print("✅ Player stats generated", flush=True)
        _initialized = True
        print("✅ Initialization complete!", flush=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ Startup error: {e}", flush=True)
        _initialized = True

init_thread = threading.Thread(target=run_initialization, daemon=True)
init_thread.start()


@app.before_request
def wait_for_init():
    if not _initialized:
        init_thread.join(timeout=60)


# --------------------------
# HOME — Role Selection
# --------------------------

@app.route("/")
def index():
    return render_template("index.html")


# --------------------------
# AUCTIONEER PAGE
# --------------------------

@app.route("/auctioneer")
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
# TEAM SELECTION PAGE
# --------------------------

@app.route("/select_team")
def select_team():
    with engine.connect() as conn:
        teams = conn.execute(text("SELECT * FROM teams")).fetchall()
    return render_template("select_team.html", teams=teams)


# --------------------------
# TEAM BIDDING PAGE
# --------------------------

@app.route("/team/<name>")
def team_page(name):
    with engine.connect() as conn:
        team = conn.execute(
            text("SELECT * FROM teams WHERE name=:n"), {"n": name}
        ).fetchone()
        if not team:
            return redirect("/select_team")

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
def bid():
    team_name = request.form["team"]
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
# CLOSE AUCTION — Sell (Auctioneer)
# --------------------------

@app.route("/close", methods=["POST"])
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