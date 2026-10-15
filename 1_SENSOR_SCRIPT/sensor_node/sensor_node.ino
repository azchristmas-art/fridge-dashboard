// -----------------------------------------------------------------------------
// Commercial Fridge Monitor - ESP32 LoRa V3 Transmitter Node
// Frequency: 868.0 MHz (UK / EU Standard)
// -----------------------------------------------------------------------------

#include <RadioLib.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// =========================================================================
// UNIT IDENTIFICATION (Change this name before uploading to each unit)
// =========================================================================
// Hardware ID: Must match Column B ("Device Name") in the Google Sheet exactly
const String DEVICE_NAME = "HELTEC-01";

// Sleep configuration: Powers down the board for 10 minutes between readings to save battery
#define TIME_TO_SLEEP_MINUTES 10
#define uS_TO_S_FACTOR 1000000ULL

// =========================================================================
// PIN DEFINITIONS (Heltec ESP32 LoRa V3)
// =========================================================================
// The pin connected to the digital temperature probe
#define ONE_WIRE_BUS 4

// The pins connected to the internal LoRa radio chip
#define LORA_NSS   8
#define LORA_DIO1  14
#define LORA_NRST  12
#define LORA_BUSY  13

// Set up the digital temperature probe on Pin 4
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// Set up the LoRa radio chip safely by creating a module first, then passing it to the radio
Module mod(LORA_NSS, LORA_DIO1, LORA_NRST, LORA_BUSY);
SX1262 radio(&mod);

void setup() {
  // Start the serial connection so we can read diagnostic text on the Mac
  Serial.begin(115200);
  delay(500);

  Serial.println("\n--- Sensor Node Boot ---");
  Serial.print("Device: ");
  Serial.println(DEVICE_NAME);

  // 1. Wake up and read the temperature probe
  sensors.begin();
  sensors.requestTemperatures();
  float currentTemp = sensors.getTempCByIndex(0);

  // If the probe is disconnected or broken, it usually reads -127.0
  if (currentTemp <= -120.0) {
    Serial.println("Probe error: check wiring.");
    currentTemp = 999.9;
  } else {
    Serial.print("Temperature: ");
    Serial.print(currentTemp);
    Serial.println(" °C");
  }

  // 2. Transmit the packet over the 868 MHz LoRa radio
  // Settings: 868.0 MHz, 125.0 kHz bandwidth, spreading factor 9, coding rate 7
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 14, 8, 0);
  
  if (state == RADIOLIB_ERR_NONE) {
    // Construct the message payload, e.g. "HELTEC-01:4.5"
    String payload = DEVICE_NAME + ":" + String(currentTemp, 1);
    
    // Broadcast it into the kitchen for the Raspberry Pi to hear
    radio.transmit(payload.c_str());
    Serial.println("Broadcast complete: " + payload);
  } else {
    // If the radio fails to initialise, print the error code
    Serial.print("Radio failed to start. Error code: ");
    Serial.println(state);
  }

  // 3. Power down the entire board into deep sleep
  // It will wake up automatically after the time defined at the top
  radio.sleep();
  esp_sleep_enable_timer_wakeup(TIME_TO_SLEEP_MINUTES * 60 * uS_TO_S_FACTOR);
  esp_deep_sleep_start();
}

void loop() {
  // Unused: Because the device goes into deep sleep at the end of setup(), 
  // it completely turns off. When it wakes up, it starts from setup() again, 
  // meaning it never reaches this loop.
}