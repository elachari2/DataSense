import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)

def test_connection():
    with get_engine().connect() as conn:
        version = conn.execute(text("SELECT version();")).scalar()
        has_vector = conn.execute(
            text("SELECT COUNT(*) FROM pg_extension WHERE extname='vector';")
        ).scalar()
    return version, bool(has_vector)

if __name__ == "__main__":
    print(test_connection())
