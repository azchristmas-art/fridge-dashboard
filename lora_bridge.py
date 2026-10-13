#!/usr/bin/env python3
# ==============================================================================
# RASPBERRY PI ZERO LORA GATEWAY BRIDGE
# Receives 868MHz LoRa packets from Heltec V3 nodes and forwards to backend API
# ==============================================================================

import time
import json
import requests
import RPi.GPIO as GPIO
from pyLora import LoRa, RPi_SPI

# --- Configuration ---
API_URL = "https://fridge-dashboard-25vm.onrender.com/api/log"
API_HEADERS = {"Content-Type": "application/json"}

# LoRa Radio Frequency (UK / Europe standard)
LORA_FREQUENCY = 868000000 

# Hardware SPI Pin Setup (Pi Hut Expansion HAT)
CS_PIN = 25     # NSS / Chip Select
RESET_PIN = 17  # Reset pin
DIO0_PIN = 4    # DIO0 interrupt pin

def setup_lora_radio():
    """
    Initialise the SPI interface and configure the LoRa transceiver module.
    """
    print("Initialising LoRa Radio on SPI bus...")
    
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    spi = RPi_SPI(0, 0)
    lora = LoRa(spi, cs_pin=CS_PIN, reset_pin=RESET_PIN, dio0_pin=DIO0_PIN)
    
    lora.set_frequency(LORA_FREQUENCY)
    lora.set_pa_config(pa_select=1)
    lora.set_spreading_factor(7)
    lora.set_bandwidth(125000)
    lora.set_coding_rate(5)
    
    lora.set_mode_rx()
    print(f"Radio successfully configured and listening on {LORA_FREQUENCY / 1000000} MHz.")
    
    return lora

def forward_to_api(payload_dict):
    """
    Take the decoded JSON dictionary and POST it to the backend API.
    """
    try:
        print(f"Forwarding payload to API: {payload_dict}")
        response = requests.post(
            API_URL, 
            headers=API_HEADERS, 
            json=payload_dict, 
            timeout=10
        )
        
        if response.status_code == 201:
            print("Successfully saved to database.")
        else:
            print(f"Server rejected data. Status Code: {response.status_code}")
            print(f"Server response: {response.text}")
            
    except requests.exceptions.RequestException as error:
        print(f"Network error whilst attempting to forward data: {error}")
        print("Continuing to listen for new radio packets...")

def process_incoming_packet(lora_instance):
    """
    Check if a packet has arrived, decode the bytes into text, and parse the JSON.
    """
    if lora_instance.rx_done():
        payload_bytes = lora_instance.read_payload()
        lora_instance.clear_irq_flags()
        
        try:
            payload_string = "".join([chr(byte) for byte in payload_bytes])
            print("\n--- Packet Received ---")
            print(f"Raw string: {payload_string}")
            print(f"Signal Strength (RSSI): {lora_instance.packet_rssi()} dBm")
            
            fridge_data = json.loads(payload_string)
            
            if "device_id" in fridge_data and "temperature" in fridge_data:
                forward_to_api(fridge_data)
            else:
                print(f"Malformed payload ignored (missing device_id or temperature): {fridge_data}")
            
        except UnicodeDecodeError:
            print("Error: Received garbled radio transmission (could not decode bytes).")
        except json.JSONDecodeError:
            print("Error: Received valid string, but it was not formatted as valid JSON.")
        except Exception as e:
            print(f"Unexpected error processing packet: {e}")
            
        finally:
            lora_instance.set_mode_rx()

def run_bridge():
    """
    Main loop keeping the bridge alive indefinitely.
    """
    try:
        radio = setup_lora_radio()
        print("Gateway Bridge is active. Press CTRL+C to stop.")
        
        while True:
            process_incoming_packet(radio)
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nShutdown signal received. Closing bridge safely...")
    except Exception as e:
        print(f"Fatal bridge error: {e}")
    finally:
        GPIO.cleanup()
        print("Programme terminated cleanly.")

if __name__ == "__main__":
    run_bridge()
