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


# --------------------------
# CREATE TABLES
# --------------------------

def create_tables():

    with engine.connect() as conn:

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS players(
        id INTEGER PRIMARY KEY,
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
        id INTEGER PRIMARY KEY,
        name TEXT,
        budget INTEGER
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS auction(
        id INTEGER PRIMARY KEY,
        player_id INTEGER,
        current_price INTEGER,
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

    return render_template(
        "index.html",
        players=players,
        teams=teams,
        auction=auction
    )


# --------------------------
# START AUCTION (Auctioneer)
# --------------------------

@app.route("/start/<int:pid>")
def start(pid):

    with engine.connect() as conn:

        player = conn.execute(text("""
        SELECT * FROM players WHERE id=:id
        """),{"id":pid}).fetchone()

        conn.execute(text("""
        INSERT INTO auction(player_id,current_price,status)
        VALUES(:pid,:price,'OPEN')
        """),{"pid":pid,"price":player.base_price})

        conn.commit()

    return redirect("/")


# --------------------------
# PLACE BID (Teams)
# --------------------------

@app.route("/bid",methods=["POST"])
def bid():

    team = request.form["team"]
    bid = int(request.form["bid"])

    with engine.connect() as conn:

        auction = conn.execute(text("""
        SELECT * FROM auction WHERE status='OPEN'
        """)).fetchone()

        if bid <= auction.current_price:
            return "Bid must be higher"

        conn.execute(text("""
        UPDATE auction
        SET current_price=:price
        WHERE id=:id
        """),{"price":bid,"id":auction.id})

        conn.commit()

    return redirect("/")


# --------------------------
# CLOSE AUCTION
# --------------------------

@app.route("/close",methods=["POST"])
def close():

    team = request.form["team"]

    with engine.connect() as conn:

        auction = conn.execute(text("""
        SELECT * FROM auction WHERE status='OPEN'
        """)).fetchone()

        conn.execute(text("""
        UPDATE players
        SET sold=1,
        sold_price=:price,
        sold_team=:team
        WHERE id=:pid
        """),{
        "price":auction.current_price,
        "team":team,
        "pid":auction.player_id
        })

        conn.execute(text("""
        UPDATE teams
        SET budget = budget - :price
        WHERE name=:team
        """),{
        "price":auction.current_price,
        "team":team
        })

        conn.execute(text("""
        UPDATE auction
        SET status='CLOSED'
        """))

        conn.commit()

    return redirect("/")


if __name__ == "__main__":

    port = int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0",port=port)