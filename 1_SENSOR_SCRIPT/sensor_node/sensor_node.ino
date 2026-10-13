/*
 * Commercial Fridge Monitor - ESP32 LoRa V3 Transmitter Node
 * Frequency: 868.0 MHz (UK / EU Standard)
 */

#include <RadioLib.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// =========================================================================
// UNIT IDENTIFICATION (Change this name before uploading to each unit)
// =========================================================================
const String DEVICE_NAME = "CAKE_FREEZER";

// Sleep configuration (10 minutes)
#define TIME_TO_SLEEP_MINUTES 10
#define uS_TO_S_FACTOR 1000000ULL

// Pin definitions (Heltec ESP32 LoRa V3)
#define ONE_WIRE_BUS 4
#define LORA_NSS   8
#define LORA_DIO1  14
#define LORA_NRST  12
#define LORA_BUSY  13

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);
SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_NRST, LORA_BUSY);

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n--- Sensor Node Boot ---");
  Serial.print("Device: ");
  Serial.println(DEVICE_NAME);

  // 1. Read temperature probe
  sensors.begin();
  sensors.requestTemperatures();
  float currentTemp = sensors.getTempCByIndex(0);

  if (currentTemp <= -120.0) {
    Serial.println("Probe error: check wiring.");
    currentTemp = 999.9;
  } else {
    Serial.print("Temperature: ");
    Serial.print(currentTemp);
    Serial.println(" °C");
  }

  // 2. Transmit packet over 868 MHz LoRa
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 14, 8, 0);
  if (state == RADIOLIB_ERR_NONE) {
    String payload = DEVICE_NAME + ":" + String(currentTemp, 1);
    radio.transmit(payload.c_str());
    Serial.println("Broadcast complete: " + payload);
  }

  // 3. Power down into deep sleep
  radio.sleep();
  esp_sleep_enable_timer_wakeup(TIME_TO_SLEEP_MINUTES * 60 * uS_TO_S_FACTOR);
  esp_deep_sleep_start();
}

void loop() {
  // Unused: device wakes up directly into setup()
}
