# ESP32 synthetic telemetry example

This Arduino sketch publishes deterministic synthetic greenhouse readings over
MQTT/TLS. It is suitable for exercising Greenhouse Steward without connecting
real sensors. Physical relay output is disabled in the default build.

## Telemetry contract

The sketch publishes every 10 seconds to:

```text
greenhouse/{device_id}/telemetry
```

Each JSON payload contains exactly these fields:

```json
{
  "schema_version": 1,
  "device_id": "esp32-synthetic-01",
  "timestamp": "2026-07-23T08:00:00Z",
  "readings": {
    "temperature_c": 24.25,
    "humidity_pct": 61.5,
    "soil_moisture_pct": 47.0,
    "light_lux": 18000.0
  }
}
```

`schema_version` is the integer `1`; booleans and other version values are not
valid. `timestamp` is RFC 3339 UTC and is emitted only after NTP
synchronization. The top-level and nested reading keys are exact: consumers
must reject missing or additional keys. Metric names and units match the Python
domain model. The checked-in
`golden_telemetry.json` is a representative contract sample.

## Relay command contract

Commands are accepted on:

```text
greenhouse/{device_id}/command/relay
```

A watering request uses:

```json
{
  "command_id": "operator-20260723-001",
  "action": "water",
  "issued_at_epoch_s": 1784793600,
  "ttl_seconds": 15,
  "duration_seconds": 20
}
```

A stop request uses the same fields except `duration_seconds` is omitted and
`action` is `stop`. Generate a unique `command_id` and current Unix timestamp
for every command. Commands are rejected when malformed, duplicated, expired,
too far in the future, larger than 384 bytes, or received without fresh
telemetry.

## Safety behavior

- `GREENHOUSE_ENABLE_REAL_RELAY` defaults to `0`, so
  `ENABLE_REAL_RELAY` is false and the relay pin is held low.
- A real relay requires an explicit build definition of
  `GREENHOUSE_ENABLE_REAL_RELAY=1`.
- The absolute relay limit is 30 seconds. Accepted commands are capped at 25
  seconds, leaving four seconds for the task watchdog and additional shutdown
  margin.
- A new command cannot extend an active relay deadline.
- A stopped relay has a 60-second cooldown.
- MQTT or Wi-Fi loss, telemetry older than 30 seconds, failed publication, an
  invalid command, or the relay deadline immediately drives the output low.
- Every command has a maximum 60-second TTL and a replay-resistant command ID.
- All `millis()` interval checks use unsigned subtraction and remain correct
  across the 32-bit rollover.
- The ESP task watchdog resets a blocked sketch. The relay pin is driven low
  before network initialization after every boot.

Firmware is not a substitute for electrical protection. A real active-high
relay driver needs an external pull-down, a normally-off power path, and an
independent hardware timeout appropriate to the pump and installation.

## Configuration

1. Copy `secrets.example.h` to `secrets.h`.
2. Set the Wi-Fi, authenticated MQTT, device, and trusted NTP values.
3. Paste the broker CA certificate into `MQTT_ROOT_CA`.
4. Keep MQTT on port 8883. The sketch refuses an empty CA or another port.

`secrets.h` contains deployment credentials and must remain outside version
control.

The sketch uses the Arduino ESP32 core, ArduinoJson, and PubSubClient.
Certificate verification is mandatory; there is no insecure TLS mode.

## Host safety check

The safety arithmetic is standard C++ and has no Arduino dependency:

```bash
c++ -std=c++17 -Wall -Wextra -pedantic \
  firmware/esp32_synthetic/host_safety_test.cpp \
  -o host_safety_test
./host_safety_test
```

The Python firmware tests validate the same constants, source-level safety
contract, topic, and golden payload without requiring PlatformIO.
