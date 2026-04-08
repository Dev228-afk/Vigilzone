import os
import redis
from dotenv import load_dotenv

def test_connection():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Adjust for relative path from where the script is called
    env_path = os.path.join(base_dir, "services", "backend", ".env")
    load_dotenv(env_path)
    
    url = os.getenv("REDIS_URL")
    print(f"Testing URL from .env: {url}")
    
    if not url:
        print("Error: REDIS_URL not found in .env")
        return

    try:
        r = redis.Redis.from_url(url, decode_responses=True)
        print(f"Ping result: {r.ping()}")
        print("Successfully connected to Redis!")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_connection()
