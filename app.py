from flask import Flask, render_template, request, redirect
import pandas as pd
from sqlalchemy import create_engine, text
import os

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")
else:
    DATABASE_URL = "sqlite:///ipl.db"

engine = create_engine(DATABASE_URL)


# -----------------------------
# CREATE TABLES
# -----------------------------
def create_tables():

    with engine.connect() as conn:

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS players(
        id SERIAL PRIMARY KEY,
        name TEXT,
        country TEXT,
        role TEXT,
        matches INTEGER,
        runs INTEGER,
        wickets INTEGER,
        base_price INTEGER
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS auction(
        id SERIAL PRIMARY KEY,
        player_id INTEGER,
        current_price INTEGER,
        status TEXT
        )
        """))

        conn.commit()


create_tables()


# -----------------------------
# LOAD PLAYERS FROM EXCEL
# -----------------------------
def load_players():

    try:

        df = pd.read_excel("players.xlsx")

        with engine.connect() as conn:

            result = conn.execute(text("SELECT COUNT(*) FROM players"))
            count = result.scalar()

            if count == 0:

                for _, row in df.iterrows():

                    conn.execute(text("""
                    INSERT INTO players(name,country,role,matches,runs,wickets,base_price)
                    VALUES(:name,:country,:role,:matches,:runs,:wickets,:base_price)
                    """), row.to_dict())

                conn.commit()

    except:
        pass


load_players()


# -----------------------------
# HOME PAGE (PLAYER LIST)
# -----------------------------
@app.route("/")
def index():

    name = request.args.get("name")
    country = request.args.get("country")
    role = request.args.get("role")

    query = "SELECT * FROM players WHERE 1=1"
    params = {}

    if name:
        query += " AND LOWER(name) LIKE LOWER(:name)"
        params["name"] = f"%{name}%"

    if country:
        query += " AND country = :country"
        params["country"] = country

    if role:
        query += " AND role = :role"
        params["role"] = role

    with engine.connect() as conn:
        players = conn.execute(text(query), params).fetchall()

    return render_template("index.html", players=players)


# -----------------------------
# PLAYER STATS PAGE
# -----------------------------
@app.route("/player/<int:pid>")
def player(pid):

    with engine.connect() as conn:

        player = conn.execute(text("""
        SELECT * FROM players WHERE id=:id
        """), {"id": pid}).fetchone()

    return render_template("player.html", player=player)


# -----------------------------
# START AUCTION
# -----------------------------
@app.route("/auction/<int:pid>")
def auction(pid):

    with engine.connect() as conn:

        player = conn.execute(text("""
        SELECT * FROM players WHERE id=:id
        """), {"id": pid}).fetchone()

        auction = conn.execute(text("""
        SELECT * FROM auction
        WHERE player_id=:pid AND status='OPEN'
        """), {"pid": pid}).fetchone()

        if not auction:

            conn.execute(text("""
            INSERT INTO auction(player_id,current_price,status)
            VALUES(:pid,:price,'OPEN')
            """), {"pid": pid, "price": player.base_price})

            conn.commit()

            auction = conn.execute(text("""
            SELECT * FROM auction
            WHERE player_id=:pid AND status='OPEN'
            """), {"pid": pid}).fetchone()

    return render_template("auction.html", player=player, auction=auction)


# -----------------------------
# PLACE BID
# -----------------------------
@app.route("/bid/<int:pid>", methods=["POST"])
def bid(pid):

    bid = int(request.form["bid"])

    with engine.connect() as conn:

        auction = conn.execute(text("""
        SELECT * FROM auction
        WHERE player_id=:pid AND status='OPEN'
        """), {"pid": pid}).fetchone()

        if not auction:
            return "Auction closed"

        if bid <= auction.current_price:
            return "Bid must be higher than current price"

        conn.execute(text("""
        UPDATE auction
        SET current_price=:price
        WHERE id=:id
        """), {"price": bid, "id": auction.id})

        conn.commit()

    return redirect(f"/auction/{pid}")


# -----------------------------
# CLOSE AUCTION
# -----------------------------
@app.route("/close/<int:pid>")
def close(pid):

    with engine.connect() as conn:

        conn.execute(text("""
        UPDATE auction
        SET status='CLOSED'
        WHERE player_id=:pid
        """), {"pid": pid})

        conn.commit()

    return redirect("/")


# -----------------------------
# UPLOAD NEW PLAYER DATASET
# -----------------------------
@app.route("/upload", methods=["GET", "POST"])
def upload():

    if request.method == "POST":

        file = request.files["file"]

        df = pd.read_excel(file)

        df.to_sql("players", engine, if_exists="replace", index=False)

        return "Dataset uploaded successfully"

    return render_template("upload.html")


# -----------------------------
# RUN APP
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)