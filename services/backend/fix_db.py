import sqlite3
import os

try:
    print("Connecting to db.sqlite3...")
    conn = sqlite3.connect("db.sqlite3", timeout=10)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(api_camera);")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"Columns in api_camera: {columns}")
    
    if "enabled_lanes" not in columns:
        print("Missing enabled_lanes. Adding it manually...")
        cursor.execute('ALTER TABLE api_camera ADD COLUMN enabled_lanes TEXT NULL;')
        conn.commit()
        print("Successfully added column.")
    else:
        print("enabled_lanes already exists.")
        
    conn.close()
except Exception as e:
    print(f"Error: {e}")
