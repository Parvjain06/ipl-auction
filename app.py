from flask import Flask, render_template, request, redirect
import pandas as pd
from sqlalchemy import create_engine, text
import os

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://","postgresql://")
else:
    DATABASE_URL = "sqlite:///ipl.db"

engine = create_engine(DATABASE_URL)

# Helper to detect DB type
is_sqlite = DATABASE_URL.startswith("sqlite")


# --------------------------
# CREATE TABLES
# --------------------------

def create_tables():

    with engine.connect() as conn:

        if is_sqlite:
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS players(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            country TEXT,
            role TEXT,
            matches INTEGER,
            runs INTEGER,
            wickets INTEGER,
            base_price INTEGER,
            sold INTEGER DEFAULT 0,
            sold_price INTEGER,
            sold_team TEXT
            )
            """))

            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS teams(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            budget INTEGER
            )
            """))

            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auction(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            current_price INTEGER,
            highest_bidder TEXT,
            status TEXT
            )
            """))
        else:
            # Players table — keep existing data
            conn.execute(text("""
            CREATE TABLE IF NOT EXISTS players(
            id SERIAL PRIMARY KEY,
            name TEXT,
            country TEXT,
            role TEXT,
            matches INTEGER,
            runs INTEGER,
            wickets INTEGER,
            base_price INTEGER,
            sold INTEGER DEFAULT 0,
            sold_price INTEGER,
            sold_team TEXT
            )
            """))

            # Drop and recreate teams & auction to fix schema
            conn.execute(text("DROP TABLE IF EXISTS teams"))
            conn.execute(text("""
            CREATE TABLE teams(
            id SERIAL PRIMARY KEY,
            name TEXT,
            budget INTEGER
            )
            """))

            conn.execute(text("DROP TABLE IF EXISTS auction"))
            conn.execute(text("""
            CREATE TABLE auction(
            id SERIAL PRIMARY KEY,
            player_id INTEGER,
            current_price INTEGER,
            highest_bidder TEXT,
            status TEXT
            )
            """))

        conn.commit()

create_tables()


# --------------------------
# HOME PAGE
# --------------------------

@app.route("/")
def index():

    with engine.connect() as conn:

        players = conn.execute(text("""
        SELECT * FROM players
        """)).fetchall()

        teams = conn.execute(text("""
        SELECT * FROM teams
        """)).fetchall()

        auction = conn.execute(text("""
        SELECT * FROM auction WHERE status='OPEN'
        """)).fetchone()

        # Get player name for current auction
        auction_player = None
        if auction:
            auction_player = conn.execute(text("""
            SELECT * FROM players WHERE id=:id
            """),{"id":auction.player_id}).fetchone()

    return render_template(
        "index.html",
        players=players,
        teams=teams,
        auction=auction,
        auction_player=auction_player
    )


# --------------------------
# ADD TEAM
# --------------------------

@app.route("/add_team", methods=["POST"])
def add_team():

    name = request.form["name"].strip()
    budget = int(request.form["budget"])

    if not name or budget <= 0:
        return redirect("/")

    with engine.connect() as conn:

        # Check if team already exists
        existing = conn.execute(text("""
        SELECT * FROM teams WHERE name=:name
        """),{"name":name}).fetchone()

        if existing:
            return redirect("/")

        conn.execute(text("""
        INSERT INTO teams(name, budget) VALUES(:name, :budget)
        """),{"name":name, "budget":budget})

        conn.commit()

    return redirect("/")


# --------------------------
# START AUCTION (Auctioneer)
# --------------------------

@app.route("/start/<int:pid>")
def start(pid):

    with engine.connect() as conn:

        # Check if there's already an open auction
        open_auction = conn.execute(text("""
        SELECT * FROM auction WHERE status='OPEN'
        """)).fetchone()

        if open_auction:
            return redirect("/")

        player = conn.execute(text("""
        SELECT * FROM players WHERE id=:id
        """),{"id":pid}).fetchone()

        if not player or player.sold == 1:
            return redirect("/")

        conn.execute(text("""
        INSERT INTO auction(player_id, current_price, highest_bidder, status)
        VALUES(:pid, :price, NULL, 'OPEN')
        """),{"pid":pid, "price":player.base_price})

        conn.commit()

    return redirect("/")


# --------------------------
# PLACE BID (Teams)
# --------------------------

@app.route("/bid", methods=["POST"])
def bid():

    team = request.form["team"]
    bid_amount = int(request.form["bid"])

    with engine.connect() as conn:

        auction = conn.execute(text("""
        SELECT * FROM auction WHERE status='OPEN'
        """)).fetchone()

        if not auction:
            return redirect("/")

        if bid_amount <= auction.current_price:
            return redirect("/")

        # Check team budget
        team_row = conn.execute(text("""
        SELECT * FROM teams WHERE name=:name
        """),{"name":team}).fetchone()

        if not team_row or bid_amount > team_row.budget:
            return redirect("/")

        conn.execute(text("""
        UPDATE auction
        SET current_price=:price, highest_bidder=:team
        WHERE id=:id
        """),{"price":bid_amount, "team":team, "id":auction.id})

        conn.commit()

    return redirect("/")


# --------------------------
# CLOSE AUCTION (Sell to highest bidder)
# --------------------------

@app.route("/close", methods=["POST"])
def close():

    with engine.connect() as conn:

        auction = conn.execute(text("""
        SELECT * FROM auction WHERE status='OPEN'
        """)).fetchone()

        if not auction:
            return redirect("/")

        if not auction.highest_bidder:
            # No one bid — mark as unsold
            conn.execute(text("""
            UPDATE auction SET status='UNSOLD' WHERE id=:id
            """),{"id":auction.id})
            conn.commit()
            return redirect("/")

        # Sell to the highest bidder
        conn.execute(text("""
        UPDATE players
        SET sold=1,
        sold_price=:price,
        sold_team=:team
        WHERE id=:pid
        """),{
        "price":auction.current_price,
        "team":auction.highest_bidder,
        "pid":auction.player_id
        })

        conn.execute(text("""
        UPDATE teams
        SET budget = budget - :price
        WHERE name=:team
        """),{
        "price":auction.current_price,
        "team":auction.highest_bidder
        })

        conn.execute(text("""
        UPDATE auction
        SET status='CLOSED'
        WHERE id=:id
        """),{"id":auction.id})

        conn.commit()

    return redirect("/")


# --------------------------
# MARK UNSOLD
# --------------------------

@app.route("/unsold", methods=["POST"])
def unsold():

    with engine.connect() as conn:

        auction = conn.execute(text("""
        SELECT * FROM auction WHERE status='OPEN'
        """)).fetchone()

        if not auction:
            return redirect("/")

        conn.execute(text("""
        UPDATE auction SET status='UNSOLD' WHERE id=:id
        """),{"id":auction.id})

        conn.commit()

    return redirect("/")


if __name__ == "__main__":

    port = int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0", port=port)