import sqlite3

DB_FILE = "fridge_monitor.db"

UNITS_CONFIG = [
    ("HELTEC-01", "Cake freezer", "FREEZER", 1),
    ("HELTEC-02", "Ice cream freezer", "FREEZER", 2),
    ("HELTEC-03", "Parlour left", "FRIDGE", 3),
    ("HELTEC-04", "Parlour right", "FRIDGE", 4),
    ("HELTEC-05", "Sauce fridge", "FRIDGE", 5),
    ("HELTEC-06", "Sauce Bottle fridge", "FRIDGE", 6),
    ("HELTEC-07", "Wine fridge", "FRIDGE", 7),
    ("HELTEC-08", "Beer fridge", "FRIDGE", 8),
    ("HELTEC-09", "Juice fridge", "FRIDGE", 9),
    ("HELTEC-10", "Cans", "FRIDGE", 10),
    ("HELTEC-11", "Blizzard grill", "FRIDGE", 11),
    ("HELTEC-12", "Blizzard freezer grill", "FREEZER", 12),
    ("HELTEC-13", "Blizzard pie", "FRIDGE", 13),
    ("HELTEC-14", "Blizzard Cheese", "FRIDGE", 14),
    ("HELTEC-15", "Blizzard freezer", "FREEZER", 15),
    ("HELTEC-16", "Fosters Freezer", "FRIDGE", 16),
    ("HELTEC-17", "3 Door Blizard", "FRIDGE", 17),
    ("HELTEC-18", "Fish fridge", "FISH", 18),
    ("HELTEC-19", "Tefcold freezer", "FRIDGE", 19),
    ("HELTEC-20", "Fosters fridge", "FRIDGE", 20),
    ("HELTEC-21", "White Fridge", "FRIDGE", 21),
    ("HELTEC-22", "Walk in freezer", "FREEZER", 22),
    ("HELTEC-23", "Walk in fridge", "FRIDGE", 23),
    ("HELTEC-24", "Ice cream chest", "FREEZER", 24),
    ("HELTEC-25", "Pudding chest", "FREEZER", 25),
    ("HELTEC-26", "Main kitchen chest", "FREEZER", 26),
]

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# 1. Ensure tables exist before querying them
cursor.execute("""
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        temperature REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_name TEXT UNIQUE NOT NULL,
        display_name TEXT,
        device_type TEXT NOT NULL DEFAULT 'FRIDGE',
        sort_order INTEGER NOT NULL DEFAULT 1
    )
""")

# 2. Purge corrupted phantom names
cursor.execute("DELETE FROM devices WHERE device_name NOT LIKE 'HELTEC-%'")
cursor.execute("DELETE FROM readings WHERE device_id NOT LIKE 'HELTEC-%'")

# 3. Seed genuine devices with correct kitchen names and categories
for dev_name, disp_name, dev_type, sort_ord in UNITS_CONFIG:
    cursor.execute("""
        INSERT INTO devices (device_name, display_name, device_type, sort_order)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(device_name) DO UPDATE SET
            display_name=excluded.display_name,
            device_type=excluded.device_type,
            sort_order=excluded.sort_order
    """, (dev_name, disp_name, dev_type, sort_ord))

conn.commit()
conn.close()
print("Database cleaned and 26 kitchen units seeded successfully.")
