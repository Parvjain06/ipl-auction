import pandas as pd
from sqlalchemy import create_engine, text
import os

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")
else:
    DATABASE_URL = "sqlite:///ipl.db"

engine = create_engine(DATABASE_URL)

df = pd.read_excel("players.xlsx")

# Add missing columns that app.py expects
if "sold" not in df.columns:
    df["sold"] = 0
if "sold_price" not in df.columns:
    df["sold_price"] = None
if "sold_team" not in df.columns:
    df["sold_team"] = None

df.to_sql("players", engine, if_exists="replace", index=False)

print("Players imported successfully")