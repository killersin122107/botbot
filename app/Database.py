import os
from sqlmodel import create_engine, SQLModel, Session

# 1. Get the Database URL
# The DATABASE_URL is essential and comes from the environment set up by Railway.
# It is used to connect to your database instance.
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    # This check is crucial to ensure the app doesn't crash with a None URL.
    print("FATAL ERROR: DATABASE_URL environment variable is missing!")
    # For local testing, you might use a placeholder, but for Railway, it must be set.
    # raise ValueError("DATABASE_URL environment variable is not set.") 

# 2. Create the Database Engine
# 'echo=True' tells the engine to print all generated SQL statements for debugging.
engine = create_engine(DATABASE_URL, echo=True)

def create_db_and_tables():
    """
    Creates the database schema based on all models that inherit from SQLModel.
    Your main bot.py file will call this function at startup.
    """
    # SQLModel uses this function to inspect all classes inheriting from SQLModel
    # and create the corresponding tables in the database if they don't exist.
    SQLModel.metadata.create_all(engine)
    
# The 'engine' and 'create_db_and_tables' objects are now defined and ready to be imported 
# by your main bot.py file, resolving the 'ModuleNotFoundError'.
