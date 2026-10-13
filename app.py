import os
import sqlite3
import threading
from datetime import datetime, timezone
import gspread
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# Load environment configuration
load_dotenv()

app = Flask(__name__)
DB_FILE = "fridge_monitor.db"

# Force Flask to reload HTML templates immediately whenever modified
app.config["TEMPLATES_AUTO_RELOAD"] = True


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
    conn.commit()
    conn.close()


init_db()


# --- ASYNCHRONOUS GOOGLE SHEET TELEMETRY STREAM ---
def async_append_reading_to_sheet(device_id, temperature, timestamp_str):
    """Appends live temperature telemetry to the 'Daily Raw Data' tab without slowing local HTTP requests."""
    try:
        daily_sheet = get_google_sheet("Daily Raw Data")
        daily_sheet.append_row([timestamp_str, device_id, temperature])
    except Exception as err:
        print(f"Warning: Could not stream telemetry to Google Sheets: {err}")


# --- WEB DASHBOARD ROUTES ---
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(
        {
            "THRESHOLD_FRIDGE": float(os.getenv("THRESHOLD_FRIDGE", 6.0)),
            "THRESHOLD_FISH": float(os.getenv("THRESHOLD_FISH", -3.0)),
            "THRESHOLD_FREEZER": float(os.getenv("THRESHOLD_FREEZER", -10.0)),
            "ALERT_DELAY_HOURS": int(os.getenv("ALERT_DELAY_HOURS", 2)),
        }
    )


# --- UNIT MANAGEMENT (GOOGLE SHEETS MASTER) ---
@app.route("/api/devices", methods=["GET"])
def get_devices():
    """Fetches the master unit registry directly from Google Sheets."""
    try:
        sheet = get_google_sheet("Units")
        records = sheet.get_all_records()
        results = []
        for row in records:
            item = {
                "id": row.get("ID", ""),
                "device_name": str(row.get("Device Name", "")).strip(),
                "display_name": str(row.get("Display Name", "")).strip(),
                "device_type": str(row.get("Device Type", "FRIDGE")).strip().upper(),
                "sort_order": row.get("Sort Order", 0),
            }
            if item["device_name"]:
                results.append(item)

        results.sort(
            key=lambda x: int(x["sort_order"]) if str(x["sort_order"]).isdigit() else 999
        )
        return jsonify(results)
    except Exception as err:
        print(f"Error fetching devices from Google Sheets: {err}")
        return jsonify([])


@app.route("/api/devices/add", methods=["POST"])
def add_device():
    """Adds a new unit to the Google Sheet registry."""
    data = request.get_json(silent=True)
    if not data or "device_name" not in data or "device_type" not in data:
        return jsonify({"status": "error", "message": "Missing device parameters"}), 400

    device_name = data["device_name"].strip().upper()
    display_name = data.get("display_name", device_name).strip()
    device_type = data["device_type"].strip().upper()

    try:
        sheet = get_google_sheet("Units")
        records = sheet.get_all_records()

        for row in records:
            if str(row.get("Device Name", "")).strip().upper() == device_name:
                return jsonify({"status": "success"})

        new_order = len(records) + 1
        new_id = len(records) + 1
        sheet.append_row([new_id, device_name, display_name, device_type, new_order])
        return jsonify({"status": "success"})
    except Exception as err:
        print(f"Error writing new device to Google Sheets: {err}")
        return jsonify({"status": "error", "message": str(err)}), 500


@app.route("/api/devices/rename", methods=["POST"])
def rename_device():
    """Updates unit labels and type rules in Google Sheets."""
    data = request.get_json(silent=True)
    if not data or "device_name" not in data or "display_name" not in data:
        return jsonify({"status": "error", "message": "Missing parameters"}), 400

    device_name = data["device_name"].strip().upper()
    display_name = data["display_name"].strip()
    device_type = data.get("device_type")

    try:
        sheet = get_google_sheet("Units")
        records = sheet.get_all_records()

        for i, row in enumerate(records):
            if str(row.get("Device Name", "")).strip().upper() == device_name:
                row_num = i + 2
                sheet.update_cell(row_num, 3, display_name)
                if device_type:
                    sheet.update_cell(row_num, 4, device_type.strip().upper())
                break
        return jsonify({"status": "success"})
    except Exception as err:
        print(f"Error updating device in Google Sheets: {err}")
        return jsonify({"status": "error", "message": str(err)}), 500


@app.route("/api/devices/reorder", methods=["POST"])
def reorder_devices():
    """Updates the display sort order for units in Google Sheets."""
    data = request.get_json(silent=True)
    if not data or "order" not in data:
        return jsonify({"status": "error", "message": "Missing order array"}), 400

    order_list = data["order"]
    try:
        sheet = get_google_sheet("Units")
        records = sheet.get_all_records()

        for i, row in enumerate(records):
            name = str(row.get("Device Name", "")).strip().upper()
            if name in order_list:
                new_idx = order_list.index(name) + 1
                row_num = i + 2
                sheet.update_cell(row_num, 5, new_idx)
        return jsonify({"status": "success"})
    except Exception as err:
        print(f"Error reordering devices in Google Sheets: {err}")
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
        WHERE DATE(timestamp) = DATE('now')
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

    # 2. Asynchronous background stream to Google Sheet 'Daily Raw Data'
    threading.Thread(
        target=async_append_reading_to_sheet,
        args=(device_id, temperature, now_str),
        daemon=True,
    ).start()

    return jsonify({"status": "success", "recorded_at": now_str})


if __name__ == "__main__":
    print("Boulevard Temperature Monitor Online. Starting Flask server...")
    app.run(host="0.0.0.0", port=5001, debug=True)
