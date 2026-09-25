import sqlite3
import os
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

app = Flask(__name__)
DB_FILE = "fridge_monitor.db"

# Force Flask to reload HTML templates immediately whenever they change
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Force the browser to NEVER cache responses during development
@app.after_request
def add_cache_control_headers(response):
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "-1"
    return response


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Table for historical readings
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            temperature REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Table for discovered hardware sensors and custom display aliases
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT UNIQUE NOT NULL,
            display_name TEXT,
            device_type TEXT NOT NULL DEFAULT 'FRIDGE',
            sort_order INTEGER NOT NULL DEFAULT 1
        )
    """
    )

    # Ensure display_name column exists for existing databases
    cursor.execute("PRAGMA table_info(devices)")
    columns = [col["name"] for col in cursor.fetchall()]
    if "display_name" not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN display_name TEXT")

    # The 27 simulated units from seed_history.py to purge completely
    legacy_seeded_devices = [
        "CAKE_FREEZER", "ICE_CREAM_FREEZER", "CAKE_FRIDGE_GLASS", "PARLOUR_LEFT",
        "PARLOUR_RIGHT", "SAUCE_FRIDGE", "SAUCE_BOTTLE_FRIDGE", "WINE_FRIDGE",
        "BEER_FRIDGE", "JUICE_FRIDGE", "CANS", "BLIZZARD_GRILL", "BLIZZARD_FREEZER_GRILL",
        "BLIZZARD_PIE", "BLIZZARD_CHEESE", "BLIZZARD_FREEZER", "FOSTERS_FREEZER",
        "3_DOOR_BLIZARD", "FISH_FRIDGE", "TEFCOLD_FREEZER", "FOSTERS_FRIDGE",
        "WHITE_FRIDGE", "WALK_IN_FREEZER", "WALK_IN_FRIDGE", "ICE_CREAM_CHEST",
        "PUDDING_CHEST", "MAIN_KITCHEN_CHEST", "TEST_FRIDGE"
    ]

    # Delete all simulated readings and device entries
    placeholders = ",".join(["?"] * len(legacy_seeded_devices))
    cursor.execute(f"DELETE FROM readings WHERE device_id IN ({placeholders})", legacy_seeded_devices)
    cursor.execute(f"DELETE FROM devices WHERE device_name IN ({placeholders})", legacy_seeded_devices)

    conn.commit()
    conn.close()


# Initialise database immediately on startup
init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({
        "THRESHOLD_FRIDGE": float(os.getenv("THRESHOLD_FRIDGE", 6.0)),
        "THRESHOLD_FISH": float(os.getenv("THRESHOLD_FISH", -3.0)),
        "THRESHOLD_FREEZER": float(os.getenv("THRESHOLD_FREEZER", -10.0)),
        "ALERT_DELAY_HOURS": int(os.getenv("ALERT_DELAY_HOURS", 2)),
    })


@app.route("/api/devices", methods=["GET"])
def get_devices():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM devices ORDER BY sort_order ASC")
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        item = dict(row)
        if not item.get("display_name"):
            item["display_name"] = item["device_name"]
        results.append(item)
    return jsonify(results)


@app.route("/api/devices/add", methods=["POST"])
def add_device():
    data = request.get_json(silent=True)
    if not data or "device_name" not in data or "device_type" not in data:
        return jsonify({"status": "error"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(sort_order) as max_order FROM devices")
    max_order = cursor.fetchone()["max_order"] or 0

    device_name = data["device_name"].strip().upper()
    display_name = data.get("display_name", device_name).strip()

    try:
        cursor.execute(
            "INSERT INTO devices (device_name, display_name, device_type, sort_order) VALUES (?, ?, ?, ?)",
            (device_name, display_name, data["device_type"], max_order + 1),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass

    conn.close()
    return jsonify({"status": "success"})


@app.route("/api/devices/rename", methods=["POST"])
def rename_device():
    data = request.get_json(silent=True)
    if not data or "device_name" not in data or "display_name" not in data:
        return jsonify({"status": "error", "message": "Missing parameters"}), 400

    device_name = data["device_name"].strip().upper()
    display_name = data["display_name"].strip()
    device_type = data.get("device_type")

    conn = get_db_connection()
    cursor = conn.cursor()
    if device_type:
        cursor.execute(
            "UPDATE devices SET display_name = ?, device_type = ? WHERE device_name = ?",
            (display_name, device_type.upper(), device_name),
        )
    else:
        cursor.execute(
            "UPDATE devices SET display_name = ? WHERE device_name = ?",
            (display_name, device_name),
        )
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})


@app.route("/api/devices/reorder", methods=["POST"])
def reorder_devices():
    data = request.get_json(silent=True)
    if not data or "order" not in data:
        return jsonify({"status": "error"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    for index, device_name in enumerate(data["order"]):
        cursor.execute(
            "UPDATE devices SET sort_order = ? WHERE device_name = ?",
            (index + 1, device_name),
        )

    conn.commit()
    conn.close()
    return jsonify({"status": "success"})


@app.route("/api/readings", methods=["GET"])
def get_readings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.device_id, COALESCE(d.display_name, r.device_id) as display_name, r.temperature, r.timestamp
        FROM readings r
        LEFT JOIN devices d ON r.device_id = d.device_name
        ORDER BY r.id DESC LIMIT 20
    """)
    rows = cursor.fetchall()
    conn.close()
    results = []
    for row in rows:
        results.append({
            "device_id": row["device_id"],
            "display_name": row["display_name"],
            "temperature": row["temperature"],
            "timestamp": row["timestamp"],
        })
    return jsonify(results)


@app.route("/api/latest", methods=["GET"])
def get_latest():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.device_id, COALESCE(d.display_name, r.device_id) as display_name, 
               COALESCE(d.device_type, 'FRIDGE') as device_type, r.temperature, r.timestamp 
        FROM readings r
        LEFT JOIN devices d ON r.device_id = d.device_name
        WHERE r.id IN (SELECT MAX(id) FROM readings GROUP BY device_id)
    """)
    rows = cursor.fetchall()
    conn.close()
    results = [
        {
            "device_id": row["device_id"],
            "display_name": row["display_name"],
            "device_type": row["device_type"],
            "temperature": row["temperature"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]
    return jsonify(results)


@app.route("/api/today", methods=["GET"])
def get_today():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.device_id, COALESCE(d.display_name, r.device_id) as display_name, r.temperature, r.timestamp 
        FROM readings r
        LEFT JOIN devices d ON r.device_id = d.device_name
        WHERE date(r.timestamp) = date('now', 'localtime') 
        ORDER BY r.timestamp ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    results = [
        {
            "device_id": row["device_id"],
            "display_name": row["display_name"],
            "temperature": row["temperature"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]
    return jsonify(results)


@app.route("/api/history/<timeframe>/<device_id>", methods=["GET"])
def get_history(timeframe, device_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    days = 7 if timeframe == "week" else 30
    
    cursor.execute(f"""
        SELECT 
            date(timestamp) as reading_date,
            AVG(temperature) as avg_temp,
            MAX(temperature) as max_temp,
            MIN(temperature) as min_temp
        FROM readings
        WHERE device_id = ? AND timestamp >= date('now', '-{days} days')
        GROUP BY date(timestamp)
        ORDER BY date(timestamp) ASC
    """, (device_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = [
        {
            "date": row["reading_date"],
            "avg": round(row["avg_temp"], 2),
            "high": round(row["max_temp"], 2),
            "low": round(row["min_temp"], 2)
        }
        for row in rows
    ]
    return jsonify(results)


@app.route("/api/diagnostics/overall", methods=["GET"])
def get_diagnostics_overall():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT device_name, COALESCE(display_name, device_name) as display_name, device_type FROM devices ORDER BY sort_order ASC")
    devices = cursor.fetchall()
    
    thresh_fridge = float(os.getenv("THRESHOLD_FRIDGE", 6.0))
    thresh_fish = float(os.getenv("THRESHOLD_FISH", -3.0))
    thresh_freezer = float(os.getenv("THRESHOLD_FREEZER", -10.0))
    
    results = []
    for dev in devices:
        d_name = dev["device_name"]
        d_display = dev["display_name"]
        d_type = dev["device_type"]
        
        threshold = thresh_fridge
        if d_type == "FISH":
            threshold = thresh_fish
        elif d_type == "FREEZER":
            threshold = thresh_freezer
            
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN temperature > ? THEN 1 END) as breach_readings,
                COUNT(CASE WHEN temperature > ? AND (prev_temp <= ? OR prev_temp IS NULL) THEN 1 END) as breach_episodes
            FROM (
                SELECT temperature, LAG(temperature) OVER (ORDER BY timestamp) as prev_temp
                FROM readings
                WHERE device_id = ?
            )
        """, (threshold, threshold, threshold, d_name))
        
        row = cursor.fetchone()
        breach_mins = (row["breach_readings"] or 0) * 10
        breach_count = row["breach_episodes"] or 0
        
        results.append({
            "name": d_display,
            "device_id": d_name,
            "type": d_type,
            "count": breach_count,
            "totalMins": breach_mins
        })
        
    conn.close()
    results.sort(key=lambda x: x["totalMins"], reverse=True)
    return jsonify(results)


@app.route("/api/log", methods=["POST"])
def log_reading():
    data = request.get_json(silent=True)
    if not data or "device_id" not in data or "temperature" not in data:
        return jsonify({"status": "error", "message": "Invalid payload"}), 400

    device_id = data["device_id"].strip().upper()
    temperature = float(data["temperature"])

    conn = get_db_connection()
    cursor = conn.cursor()

    # Dynamic auto-discovery: register unknown sensor IDs automatically
    cursor.execute("SELECT id FROM devices WHERE device_name = ?", (device_id,))
    device_exists = cursor.fetchone()

    if not device_exists:
        cursor.execute("SELECT COALESCE(MAX(sort_order), 0) as max_order FROM devices")
        max_order = cursor.fetchone()["max_order"] or 0
        
        dev_type = "FRIDGE"
        if "FREEZER" in device_id:
            dev_type = "FREEZER"
        elif "FISH" in device_id:
            dev_type = "FISH"

        cursor.execute(
            "INSERT INTO devices (device_name, display_name, device_type, sort_order) VALUES (?, ?, ?, ?)",
            (device_id, device_id, dev_type, max_order + 1),
        )

    # Record incoming temperature log
    cursor.execute(
        "INSERT INTO readings (device_id, temperature) VALUES (?, ?)",
        (device_id, temperature),
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "success"}), 201


if __name__ == "__main__":
    print("Database initialised. Starting the web server...")
    app.run(host="0.0.0.0", port=5001, debug=True)
