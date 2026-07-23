#pragma once

#include <cstdint>

// Copy this file to secrets.h and replace every deployment-specific value.
// The reserved .invalid host prevents accidental connection with example data.
inline constexpr char WIFI_SSID[] = "greenhouse-network";
inline constexpr char WIFI_PASSWORD[] = "replace-before-flashing";
inline constexpr char MQTT_HOST[] = "broker.example.invalid";
inline constexpr std::uint16_t MQTT_PORT = 8883U;
inline constexpr char MQTT_USERNAME[] = "esp32-synthetic-01";
inline constexpr char MQTT_PASSWORD[] = "replace-before-flashing";
inline constexpr char DEVICE_ID[] = "esp32-synthetic-01";
inline constexpr char NTP_SERVER[] = "ntp.example.invalid";

// Paste the PEM-encoded CA certificate that issued the MQTT broker certificate.
// Firmware refuses to connect while this value is empty.
inline constexpr char MQTT_ROOT_CA[] = "";
