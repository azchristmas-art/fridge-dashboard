import sqlite3

devices = [
  ("HELTEC-01", "FREEZER", "Cake freezer", 1),
  ("HELTEC-02", "FREEZER", "Ice cream freezer", 2),
  ("HELTEC-03", "FRIDGE", "Parlour left", 3),
  ("HELTEC-04", "FRIDGE", "Parlour right", 4),
  ("HELTEC-05", "FRIDGE", "Sauce fridge", 5),
  ("HELTEC-06", "FRIDGE", "Sauce Bottle fridge", 6),
  ("HELTEC-07", "FRIDGE", "Wine fridge", 7),
  ("HELTEC-08", "FRIDGE", "Beer fridge", 8),
  ("HELTEC-09", "FRIDGE", "Juice fridge", 9),
  ("HELTEC-10", "FRIDGE", "Cans", 10),
  ("HELTEC-11", "FRIDGE", "Blizzard grill", 11),
  ("HELTEC-12", "FREEZER", "Blizzard freezer grill", 12),
  ("HELTEC-13", "FRIDGE", "Blizzard pie", 13),
  ("HELTEC-14", "FRIDGE", "Blizzard Cheese", 14),
  ("HELTEC-15", "FREEZER", "Blizzard freezer", 15),
  ("HELTEC-16", "FRIDGE", "Fosters Freezer", 16),
  ("HELTEC-17", "FRIDGE", "3 Door Blizard", 17),
  ("HELTEC-18", "FISH", "Fish fridge", 18),
  ("HELTEC-19", "FRIDGE", "Tefcold freezer", 19),
  ("HELTEC-20", "FRIDGE", "Fosters fridge", 20),
  ("HELTEC-21", "FRIDGE", "White Fridge", 21),
  ("HELTEC-22", "FREEZER", "Walk in freezer", 22),
  ("HELTEC-23", "FRIDGE", "Walk in fridge", 23),
  ("HELTEC-24", "FREEZER", "Ice cream chest", 24),
  ("HELTEC-25", "FREEZER", "Pudding chest", 25),
  ("HELTEC-26", "FREEZER", "Main kitchen chest", 26)
]

conn = sqlite3.connect("fridge_monitor.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'FRIDGE',
    sort_order INTEGER DEFAULT 999
)
""")

for dev in devices:
    cursor.execute("""
        INSERT OR IGNORE INTO devices (device_name, device_type, display_name, sort_order)
        VALUES (?, ?, ?, ?)
    """, dev)

conn.commit()
conn.close()
print("Migration complete: 26 units seeded into local SQLite.")
