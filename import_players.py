import pandas as pd
from sqlalchemy import create_engine
import os

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

df = pd.read_excel("players.xlsx")

df.to_sql("players", engine, if_exists="replace", index=False)

print("Players imported successfully")