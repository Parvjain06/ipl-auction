import pandas as pd
from sqlalchemy import create_engine, text
import os
import random

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://")
else:
    DATABASE_URL = "sqlite:///ipl.db"

engine = create_engine(DATABASE_URL)

df = pd.read_excel("players.xlsx")

# Assign random base prices (multiples of 10, within 10-100)
df["base_price"] = [random.choice(range(10, 110, 10)) for _ in range(len(df))]

# Add missing columns that app.py expects
if "sold" not in df.columns:
    df["sold"] = 0
if "sold_price" not in df.columns:
    df["sold_price"] = None
if "sold_team" not in df.columns:
    df["sold_team"] = None

df.to_sql("players", engine, if_exists="replace", index=False)

print("Players imported with random base prices (10-100)")