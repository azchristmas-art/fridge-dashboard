import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect("fridge_monitor.db")
cursor = conn.cursor()

# Clear out any normal recent readings for this specific unit
cursor.execute("DELETE FROM readings WHERE device_id = 'CAKE_FREEZER' AND timestamp >= datetime('now', '-3 hours')")

# Inject 3 hours of critical temperatures
now = datetime.now()
records = []
for i in range(180): 
    timestamp = (now - timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')
    records.append(("CAKE_FREEZER", 25.5, timestamp))

cursor.executemany(
    "INSERT INTO readings (device_id, temperature, timestamp) VALUES (?, ?, ?)",
    records
)
conn.commit()
conn.close()

print("Disaster injected! CAKE_FREEZER has been at 25.5°C for the last 3 hours.")
