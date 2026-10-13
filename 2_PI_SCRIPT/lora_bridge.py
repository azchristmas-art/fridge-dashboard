import time
import requests
import json

# Where our local web dashboard is listening for readings
API_URL = "http://127.0.0.1:5001/api/log"

def process_radio_message(raw_message):
    """
    Takes an incoming radio message like 'CAKE_FREEZER:-14.5' 
    and sends it straight to your web dashboard.
    """
    try:
        # Clean up the text
        clean_text = raw_message.strip()
        
        # Check if the message contains our divider ':'
        if ":" not in clean_text:
            print(f"[Ignored] Message not recognized: '{clean_text}'")
            return

        # Split into the fridge name and temperature
        device_name, temp_str = clean_text.split(":", 1)
        temperature = float(temp_str)

        payload = {
            "device_id": device_name.strip(),
            "temperature": temperature
        }

        # Hand the reading directly to your Flask server
        response = requests.post(API_URL, json=payload, timeout=5)
        
        if response.status_code == 201:
            print(f"[Radio Received] Logged {device_name} -> {temperature} °C")
        else:
            print(f"[Server Warning] Server received but rejected: {response.text}")

    except ValueError:
        print(f"[Error] Could not convert temperature value from: '{raw_message}'")
    except requests.exceptions.RequestException as err:
        print(f"[Connection Error] Dashboard server not reachable: {err}")

def start_listening():
    print("==================================================")
    print("   Raspberry Pi LoRa Radio Bridge is Active       ")
    print("   Listening for incoming kitchen temperatures... ")
    print("==================================================")
    
    # When your physical board arrives, the radio hardware listener
    # will feed messages directly into process_radio_message().
    # For now, it stays on standby.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping LoRa Radio Bridge cleanly.")

if __name__ == "__main__":
    start_listening()
