# app/database.py
import os
from sqlmodel import create_engine

# The database URL comes from the environment (e.g., set by Railway)
DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_engine(DATABASE_URL, echo=True) 
# The 'engine' variable is defined here.
