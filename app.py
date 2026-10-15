import os
import sqlite3
import threading
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
import gspread
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# Load environment configuration
load_dotenv()

app = Flask(__name__)
DB_FILE = "fridge_monitor.db"

# Force Flask to reload HTML templates immediately whenever modified
app.config["TEMPLATES_AUTO_RELOAD"] = True

# --- IN-MEMORY CACHES FOR BACKGROUND TASKS ---
LAST_SUMMARY_DATE = datetime.now().strftime("%Y-%m-%d") # Prevents running the daily summary on mid-day reboots
LAST_ALERT_SENT = {} # Tracks alert cooldowns per device


# --- CACHE CONTROL ---
@app.after_request
def add_cache_control_headers(response):
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "-1"
    return response


# --- GOOGLE SHEETS CONNECTION ---
def get_google_sheet(sheet_name="Units"):
    """Connects to Google Cloud and returns the requested worksheet."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    client = gspread.service_account(filename="credentials.json")
    spreadsheet = client.open_by_key(sheet_id)
    return spreadsheet.worksheet(sheet_name)


# --- LOCAL DATABASE CONNECTION ---
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            device_type TEXT NOT NULL DEFAULT 'FRIDGE',
            sort_order INTEGER DEFAULT 999
        )
        """
    )
    conn.commit()
    conn.close()

init_db()


# --- PHASE 3: EMAIL ALERT LOGIC ---
def send_alert_email(display_name, temp, threshold):
    """Fires a critical alert email using Google SMTP."""
    try:
        sender = os.getenv("EMAIL_USER")
        password = os.getenv("EMAIL_PASS")
        receiver = "theboulevardselsey@gmail.com"

        if not sender or not password:
            print("Warning: Email credentials (EMAIL_USER / EMAIL_PASS) not configured in .env")
            return

        msg = EmailMessage()
        msg.set_content(f"CRITICAL ALERT: {display_name} has been running above {threshold}°C for over 20 minutes.\n\nCurrent Temperature: {temp}°C\n\nPlease check the unit immediately to prevent stock loss.")
        msg["Subject"] = f"CRITICAL ALERT: {display_name} is at {temp}°C"
        msg["From"] = sender
        msg["To"] = receiver

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Alert email dispatched successfully for {display_name}")
    except Exception as e:
        print(f"Failed to send email alert: {e}")


def check_thresholds_and_alert(device_id, current_temp):
    """Evaluates the last 20 minutes of telemetry to prevent false alarms before emailing."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT display_name, device_type FROM devices WHERE device_name = ?", (device_id,))
        device = cursor.fetchone()
        if not device:
            conn.close()
            return

        display_name = device["display_name"]
        device_type = device["device_type"]
        
        # Determine safety limit based on type
        threshold = float(os.getenv("THRESHOLD_FREEZER", -15.0)) if device_type == 'FREEZER' else float(os.getenv("THRESHOLD_FRIDGE", 8.0))

        if current_temp <= threshold:
            conn.close()
            return # Unit is running at a safe temperature

        # If warm, check if the lowest temperature in the last 20 minutes was STILL above the threshold
        twenty_mins_ago = (datetime.now() - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            SELECT MIN(temperature) as min_temp, COUNT(id) as count
            FROM readings
            WHERE device_id = ? AND timestamp >= ?
        """, (device_id, twenty_mins_ago))
        stats = cursor.fetchone()
        conn.close()

        # Needs at least 2 readings in the window to prove a sustained excursion
        if stats and stats["count"] >= 2 and stats["min_temp"] > threshold:
            now = datetime.now()
            last_alert = LAST_ALERT_SENT.get(device_id)
            
            # Apply a 1-hour cooldown so the kitchen isn't bombarded with emails
            if not last_alert or (now - last_alert).total_seconds() >= 3600:
                send_alert_email(display_name, current_temp, threshold)
                LAST_ALERT_SENT[device_id] = now
                
    except Exception as e:
        print(f"Error checking temperature thresholds: {e}")


# --- PHASE 4: 24-HOUR COMPLIANCE SUMMARY ---
def process_midnight_summary():
    """Runs exactly once just after midnight to calculate the previous 24h compliance metrics."""
    global LAST_SUMMARY_DATE
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # If the date has changed and we are in the midnight hour
    if today_str != LAST_SUMMARY_DATE and now.hour == 0:
        yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        date_formatted = (now - timedelta(days=1)).strftime('%d/%m/%Y')

        try:
            summary_sheet = get_google_sheet("24h Summary")
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM devices ORDER BY sort_order ASC")
            devices = cursor.fetchall()

            for device in devices:
                device_id = device["device_name"]
                display_name = device["display_name"]
                device_type = device["device_type"]
                threshold = float(os.getenv("THRESHOLD_FREEZER", -15.0)) if device_type == 'FREEZER' else float(os.getenv("THRESHOLD_FRIDGE", 8.0))

                # 1. Get Daily Min, Max, Average
                cursor.execute("""
                    SELECT MIN(temperature) as min_temp, MAX(temperature) as max_temp, AVG(temperature) as avg_temp
                    FROM readings WHERE device_id = ? AND timestamp LIKE ?
                """, (device_id, f"{yesterday}%"))
                stats = cursor.fetchone()

                if stats["min_temp"] is None:
                    continue # Unit was offline or not recorded yesterday

                # 2. Get Morning Temp (~08:00)
                cursor.execute("""
                    SELECT temperature FROM readings
                    WHERE device_id = ? AND timestamp LIKE ? AND time(timestamp) >= '08:00:00'
                    ORDER BY timestamp ASC LIMIT 1
                """, (device_id, f"{yesterday}%"))
                m_temp = cursor.fetchone()
                morning_temp = round(m_temp["temperature"], 1) if m_temp else "N/A"

                # 3. Get Evening Temp (~20:00)
                cursor.execute("""
                    SELECT temperature FROM readings
                    WHERE device_id = ? AND timestamp LIKE ? AND time(timestamp) <= '20:00:00'
                    ORDER BY timestamp DESC LIMIT 1
                """, (device_id, f"{yesterday}%"))
                e_temp = cursor.fetchone()
                evening_temp = round(e_temp["temperature"], 1) if e_temp else "N/A"

                min_temp = round(stats["min_temp"], 1)
                max_temp = round(stats["max_temp"], 1)
                avg_temp = round(stats["avg_temp"], 1)
                compliance = "ATTENTION" if max_temp > threshold else "PASS"

                # 4. Calculate Excursion Duration (Assuming 10-minute intervals = 10 mins per breach)
                cursor.execute("""
                    SELECT COUNT(*) as exc_count FROM readings
                    WHERE device_id = ? AND timestamp LIKE ? AND temperature > ?
                """, (device_id, f"{yesterday}%", threshold))
                exc_count = cursor.fetchone()["exc_count"]
                excursion_time = f"{exc_count * 10} mins" if exc_count > 0 else "0 mins"

                # 5. Append to Google Sheet Master Tab
                row = [
                    date_formatted, display_name, device_id,
                    morning_temp, evening_temp, max_temp, min_temp, avg_temp,
                    compliance, excursion_time, ""
                ]
                summary_sheet.append_row(row)

            conn.close()
            LAST_SUMMARY_DATE = today_str 
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 24h Summary generated and pushed for {yesterday}")
        except Exception as e:
            print(f"Failed to generate midnight summary: {e}")


# --- MASTER BACKGROUND PIPELINE ---
def background_telemetry_pipeline(device_id, temperature, timestamp_str):
    """Handles all slow external network requests asynchronously to keep the local HTTP API fast."""
    # 1. Stream raw log to Sheets
    try:
        daily_sheet = get_google_sheet("Daily Raw Data")
        daily_sheet.append_row([timestamp_str, device_id, temperature])
    except Exception as err:
        print(f"Warning: Could not stream telemetry to Google Sheets: {err}")

    # 2. Check for critical excursions
    check_thresholds_and_alert(device_id, temperature)

    # 3. Process midnight EHO paperwork if required
    process_midnight_summary()


# --- WEB DASHBOARD ROUTES ---
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(
        {
            "THRESHOLD_FRIDGE": float(os.getenv("THRESHOLD_FRIDGE", 8.0)),
            "THRESHOLD_FISH": float(os.getenv("THRESHOLD_FISH", -3.0)),
            "THRESHOLD_FREEZER": float(os.getenv("THRESHOLD_FREEZER", -15.0)),
            "ALERT_DELAY_HOURS": int(os.getenv("ALERT_DELAY_HOURS", 2)),
        }
    )


# --- UNIT MANAGEMENT (LOCAL SQLITE MASTER) ---
@app.route("/api/devices", methods=["GET"])
def get_devices():
    """Fetches the master unit registry directly from local SQLite."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM devices ORDER BY sort_order ASC")
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "device_name": row["device_name"],
                "display_name": row["display_name"],
                "device_type": row["device_type"],
                "sort_order": row["sort_order"],
            })
        return jsonify(results)
    except Exception as err:
        print(f"Error fetching devices from SQLite: {err}")
        return jsonify([])


@app.route("/api/devices/add", methods=["POST"])
def add_device():
    """Adds a new unit to the local SQLite registry."""
    data = request.get_json(silent=True)
    if not data or "device_name" not in data or "device_type" not in data:
        return jsonify({"status": "error", "message": "Missing device parameters"}), 400

    device_name = data["device_name"].strip().upper()
    display_name = data.get("display_name", device_name).strip()
    device_type = data["device_type"].strip().upper()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM devices WHERE device_name = ?", (device_name,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"status": "success"})
            
        cursor.execute("SELECT MAX(sort_order) as max_order FROM devices")
        result = cursor.fetchone()
        new_order = (result["max_order"] or 0) + 1
        
        cursor.execute(
            "INSERT INTO devices (device_name, display_name, device_type, sort_order) VALUES (?, ?, ?, ?)",
            (device_name, display_name, device_type, new_order)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as err:
        print(f"Error writing new device to SQLite: {err}")
        return jsonify({"status": "error", "message": str(err)}), 500


@app.route("/api/devices/rename", methods=["POST"])
def rename_device():
    """Updates unit labels and type rules in local SQLite."""
    data = request.get_json(silent=True)
    if not data or "device_name" not in data or "display_name" not in data:
        return jsonify({"status": "error", "message": "Missing parameters"}), 400

    device_name = data["device_name"].strip().upper()
    display_name = data["display_name"].strip()
    device_type = data.get("device_type")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if device_type:
            cursor.execute(
                "UPDATE devices SET display_name = ?, device_type = ? WHERE device_name = ?",
                (display_name, device_type.strip().upper(), device_name)
            )
        else:
             cursor.execute(
                "UPDATE devices SET display_name = ? WHERE device_name = ?",
                (display_name, device_name)
            )
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as err:
        print(f"Error updating device in SQLite: {err}")
        return jsonify({"status": "error", "message": str(err)}), 500


@app.route("/api/devices/reorder", methods=["POST"])
def reorder_devices():
    """Updates the display sort order for units in local SQLite."""
    data = request.get_json(silent=True)
    if not data or "order" not in data:
        return jsonify({"status": "error", "message": "Missing order array"}), 400

    order_list = data["order"]
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for idx, name in enumerate(order_list):
            cursor.execute(
                "UPDATE devices SET sort_order = ? WHERE device_name = ?",
                (idx + 1, name.strip().upper())
            )
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as err:
        print(f"Error reordering devices in SQLite: {err}")
        return jsonify({"status": "error", "message": str(err)}), 500


# --- TEMPERATURE TELEMETRY & REPORTING ROUTES ---
@app.route("/api/latest", methods=["GET"])
def get_latest():
    """Returns the most recent temperature reading for each unit."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT r1.device_id, r1.temperature, r1.timestamp
        FROM readings r1
        INNER JOIN (
            SELECT device_id, MAX(id) as max_id
            FROM readings
            GROUP BY device_id
        ) r2 ON r1.id = r2.max_id
        """
    )
    rows = cursor.fetchall()
    conn.close()

    latest_data = {}
    for r in rows:
        latest_data[r["device_id"]] = {
            "temperature": round(r["temperature"], 1),
            "timestamp": r["timestamp"],
        }
    return jsonify(latest_data)


@app.route("/api/today", methods=["GET"])
def get_today():
    """Returns min, max, and duration statistics for the current 24-hour cycle."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 
            device_id,
            MIN(temperature) as min_temp,
            MAX(temperature) as max_temp,
            COUNT(*) as reading_count
        FROM readings
        WHERE DATE(timestamp) = DATE('now', 'localtime')
        GROUP BY device_id
        """
    )
    rows = cursor.fetchall()
    conn.close()

    today_summary = {}
    for r in rows:
        today_summary[r["device_id"]] = {
            "min": round(r["min_temp"], 1),
            "max": round(r["max_temp"], 1),
            "count": r["reading_count"],
        }
    return jsonify(today_summary)


@app.route("/api/readings", methods=["GET"])
@app.route("/api/history", methods=["GET"])
def get_history():
    """Provides historical readings for charting."""
    device_id = request.args.get("device_id")
    conn = get_db_connection()
    cursor = conn.cursor()

    if device_id:
        cursor.execute(
            """
            SELECT device_id, temperature, timestamp
            FROM readings
            WHERE device_id = ?
            ORDER BY id DESC LIMIT 144
            """,
            (device_id,),
        )
    else:
        cursor.execute(
            """
            SELECT device_id, temperature, timestamp
            FROM readings
            ORDER BY id DESC LIMIT 500
            """
        )

    rows = cursor.fetchall()
    conn.close()

    readings = [
        {
            "device_id": r["device_id"],
            "temperature": round(r["temperature"], 1),
            "timestamp": r["timestamp"],
        }
        for r in reversed(rows)
    ]
    return jsonify(readings)


@app.route("/api/diagnostics/overall", methods=["GET"])
@app.route("/api/diagnostics", methods=["GET"])
def get_diagnostics_overall():
    """Returns overall telemetry and health metrics."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total_readings FROM readings")
    total = cursor.fetchone()["total_readings"]
    conn.close()

    return jsonify(
        {
            "status": "ONLINE",
            "database": "CONNECTED",
            "google_sheets": "SYNCED",
            "total_local_readings": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/api/log_reading", methods=["POST"])
@app.route("/api/log", methods=["POST"])
def log_reading():
    """Receives incoming sensor telemetry, saves locally, and streams to Google Sheets."""
    data = request.get_json(silent=True)
    if not data or "device_id" not in data or "temperature" not in data:
        return jsonify({"status": "error", "message": "Invalid telemetry payload"}), 400

    device_id = data["device_id"].strip().upper()
    temperature = float(data["temperature"])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Immediate local persistence
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO readings (device_id, temperature, timestamp) VALUES (?, ?, ?)",
        (device_id, temperature, now_str),
    )
    conn.commit()
    conn.close()

    # 2. Asynchronous background pipeline (Sheets Sync, Alerts, Midnight Summary)
    threading.Thread(
        target=background_telemetry_pipeline,
        args=(device_id, temperature, now_str),
        daemon=True,
    ).start()

    return jsonify({"status": "success", "recorded_at": now_str})


if __name__ == "__main__":
    print("Boulevard Temperature Monitor Online. Starting Flask server...")
    app.run(host="0.0.0.0", port=5001, debug=True)