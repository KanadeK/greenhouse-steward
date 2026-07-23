#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_err.h>
#include <esp_idf_version.h>
#include <esp_task_wdt.h>
#include <math.h>
#include <time.h>

#include "safety.h"
#include "secrets.h"

#ifndef GREENHOUSE_ENABLE_REAL_RELAY
#define GREENHOUSE_ENABLE_REAL_RELAY 0
#endif

namespace {

constexpr bool ENABLE_REAL_RELAY = GREENHOUSE_ENABLE_REAL_RELAY == 1;
constexpr std::uint8_t RELAY_PIN = 26U;
constexpr std::uint32_t MINIMUM_VALID_EPOCH_SECONDS = 1'704'067'200U;
constexpr std::uint16_t MQTT_PACKET_BUFFER_BYTES = 768U;
constexpr std::uint16_t MQTT_SOCKET_TIMEOUT_SECONDS = 3U;
constexpr std::size_t TOPIC_CAPACITY = 128U;
constexpr std::size_t CLIENT_ID_CAPACITY = 80U;
constexpr std::size_t COMMAND_ID_CAPACITY = 65U;
constexpr float PI_F = 3.14159265358979323846F;

WiFiClientSecure tls_client;
PubSubClient mqtt_client(tls_client);

char telemetry_topic[TOPIC_CAPACITY] = {};
char command_topic[TOPIC_CAPACITY] = {};
char status_topic[TOPIC_CAPACITY] = {};
char mqtt_client_id[CLIENT_ID_CAPACITY] = {};
char last_command_id[COMMAND_ID_CAPACITY] = {};

bool relay_active = false;
bool has_relay_stopped = false;
bool has_published_telemetry = false;
bool has_last_command_id = false;
std::uint32_t relay_started_ms = 0U;
std::uint32_t relay_applied_ms = 0U;
std::uint32_t relay_stopped_ms = 0U;
std::uint32_t last_telemetry_success_ms = 0U;
std::uint32_t last_telemetry_attempt_ms = 0U;
std::uint32_t last_mqtt_attempt_ms = 0U;

void writeRelayHardware(bool energized) {
    if (ENABLE_REAL_RELAY) {
        digitalWrite(RELAY_PIN, energized ? HIGH : LOW);
        return;
    }
    digitalWrite(RELAY_PIN, LOW);
}

void failClosedBoot(const char* reason) {
    writeRelayHardware(false);
    Serial.print("Boot blocked in relay-off state: ");
    Serial.println(reason);
    while (true) {
        delay(1'000U);
    }
}

bool safeDeviceId(const char* value) {
    const std::size_t length = strlen(value);
    if (length == 0U || length > 48U) {
        return false;
    }
    for (std::size_t index = 0U; index < length; ++index) {
        const char character = value[index];
        const bool accepted =
            (character >= 'a' && character <= 'z')
            || (character >= 'A' && character <= 'Z')
            || (character >= '0' && character <= '9')
            || character == '-'
            || character == '_';
        if (!accepted) {
            return false;
        }
    }
    return true;
}

bool buildTopics() {
    const int telemetry_length = snprintf(
        telemetry_topic,
        sizeof(telemetry_topic),
        "greenhouse/%s/telemetry",
        DEVICE_ID
    );
    const int command_length = snprintf(
        command_topic,
        sizeof(command_topic),
        "greenhouse/%s/command/relay",
        DEVICE_ID
    );
    const int status_length = snprintf(
        status_topic,
        sizeof(status_topic),
        "greenhouse/%s/status",
        DEVICE_ID
    );
    const int client_length = snprintf(
        mqtt_client_id,
        sizeof(mqtt_client_id),
        "greenhouse-%s",
        DEVICE_ID
    );
    return telemetry_length > 0
        && static_cast<std::size_t>(telemetry_length) < sizeof(telemetry_topic)
        && command_length > 0
        && static_cast<std::size_t>(command_length) < sizeof(command_topic)
        && status_length > 0
        && static_cast<std::size_t>(status_length) < sizeof(status_topic)
        && client_length > 0
        && static_cast<std::size_t>(client_length) < sizeof(mqtt_client_id);
}

bool configurationIsSafe() {
    return safeDeviceId(DEVICE_ID)
        && strlen(WIFI_SSID) > 0U
        && strlen(WIFI_PASSWORD) > 0U
        && strlen(MQTT_HOST) > 0U
        && MQTT_PORT == 8883U
        && strlen(MQTT_USERNAME) > 0U
        && strlen(MQTT_PASSWORD) > 0U
        && strlen(NTP_SERVER) > 0U
        && strstr(MQTT_ROOT_CA, "-----BEGIN CERTIFICATE-----") != nullptr
        && buildTopics();
}

bool clockIsSynchronized() {
    const time_t now = time(nullptr);
    return now >= static_cast<time_t>(MINIMUM_VALID_EPOCH_SECONDS);
}

bool formatTimestamp(char* output, std::size_t output_size) {
    const time_t now = time(nullptr);
    if (now < static_cast<time_t>(MINIMUM_VALID_EPOCH_SECONDS)) {
        return false;
    }
    tm utc_time = {};
    if (gmtime_r(&now, &utc_time) == nullptr) {
        return false;
    }
    return strftime(output, output_size, "%Y-%m-%dT%H:%M:%SZ", &utc_time) == 20U;
}

void forceRelayOff(const char* reason, std::uint32_t now_ms) {
    const bool was_active = relay_active;
    relay_active = false;
    relay_started_ms = 0U;
    relay_applied_ms = 0U;
    writeRelayHardware(false);
    if (was_active) {
        has_relay_stopped = true;
        relay_stopped_ms = now_ms;
        Serial.print("Relay forced off: ");
        Serial.println(reason);
    }
}

bool telemetryIsFresh(std::uint32_t now_ms) {
    return has_published_telemetry
        && !greenhouse::safety::intervalElapsed(
            now_ms,
            last_telemetry_success_ms,
            greenhouse::safety::kTelemetryStaleMs
        );
}

void enforceRelaySafety(std::uint32_t now_ms) {
    if (!relay_active) {
        return;
    }
    if (greenhouse::safety::intervalElapsed(now_ms, relay_started_ms, relay_applied_ms)) {
        forceRelayOff("duration_elapsed", now_ms);
        return;
    }
    if (!telemetryIsFresh(now_ms)) {
        forceRelayOff("telemetry_stale", now_ms);
        return;
    }
    if (WiFi.status() != WL_CONNECTED || !mqtt_client.connected()) {
        forceRelayOff("transport_disconnected", now_ms);
    }
}

void rememberCommandId(const char* command_id) {
    strlcpy(last_command_id, command_id, sizeof(last_command_id));
    has_last_command_id = true;
}

bool duplicateCommand(const char* command_id) {
    return has_last_command_id && strcmp(last_command_id, command_id) == 0;
}

void rejectCommand(const char* reason, std::uint32_t now_ms) {
    forceRelayOff(reason, now_ms);
    Serial.print("Relay command rejected: ");
    Serial.println(reason);
}

void startRelay(std::uint32_t requested_seconds, std::uint32_t now_ms) {
    const std::uint32_t requested_ms =
        requested_seconds >= greenhouse::safety::kRelayHardMaxMs / 1'000U
        ? greenhouse::safety::kRelayHardMaxMs
        : requested_seconds * 1'000U;
    relay_applied_ms = greenhouse::safety::cappedRelayDurationMs(requested_ms);
    relay_started_ms = now_ms;
    relay_active = true;
    writeRelayHardware(true);
    Serial.print(ENABLE_REAL_RELAY ? "Real relay enabled for ms: " : "Simulated relay enabled for ms: ");
    Serial.println(relay_applied_ms);
}

void mqttCallback(char*, byte* payload, unsigned int length) {
    const std::uint32_t now_ms = millis();
    if (length == 0U || length > greenhouse::safety::kMaxCommandPayloadBytes) {
        rejectCommand("payload_size", now_ms);
        return;
    }

    StaticJsonDocument<512U> document;
    const DeserializationError error = deserializeJson(document, payload, length);
    if (error) {
        rejectCommand("invalid_json", now_ms);
        return;
    }
    if (!document["command_id"].is<const char*>()
        || !document["action"].is<const char*>()
        || !document["issued_at_epoch_s"].is<std::uint64_t>()
        || !document["ttl_seconds"].is<std::uint32_t>()) {
        rejectCommand("missing_command_field", now_ms);
        return;
    }

    const char* command_id = document["command_id"].as<const char*>();
    const char* action = document["action"].as<const char*>();
    const std::uint64_t issued_at = document["issued_at_epoch_s"].as<std::uint64_t>();
    const std::uint32_t ttl_seconds = document["ttl_seconds"].as<std::uint32_t>();
    const std::size_t command_id_length = strlen(command_id);
    if (command_id_length == 0U || command_id_length >= COMMAND_ID_CAPACITY) {
        rejectCommand("command_id_size", now_ms);
        return;
    }
    if (!clockIsSynchronized()
        || !greenhouse::safety::commandTimestampIsFresh(
            static_cast<std::uint64_t>(time(nullptr)),
            issued_at,
            ttl_seconds
        )) {
        rejectCommand("command_expired", now_ms);
        return;
    }
    if (duplicateCommand(command_id)) {
        Serial.println("Duplicate relay command ignored without changing the deadline");
        return;
    }

    if (strcmp(action, "stop") == 0) {
        rememberCommandId(command_id);
        forceRelayOff("remote_stop", now_ms);
        return;
    }
    if (strcmp(action, "water") != 0 || !document["duration_seconds"].is<std::uint32_t>()) {
        rejectCommand("invalid_action", now_ms);
        return;
    }

    const std::uint32_t requested_seconds = document["duration_seconds"].as<std::uint32_t>();
    if (requested_seconds == 0U
        || requested_seconds > greenhouse::safety::kRelayHardMaxMs / 1'000U) {
        rejectCommand("invalid_duration", now_ms);
        return;
    }
    if (!telemetryIsFresh(now_ms)) {
        rejectCommand("telemetry_stale", now_ms);
        return;
    }
    if (!greenhouse::safety::cooldownComplete(
            now_ms,
            relay_stopped_ms,
            has_relay_stopped
        )) {
        rejectCommand("relay_cooldown", now_ms);
        return;
    }

    rememberCommandId(command_id);
    if (relay_active) {
        Serial.println("Relay command ignored without extending the active deadline");
        return;
    }
    startRelay(requested_seconds, now_ms);
}

float syntheticTemperature(std::uint32_t now_ms) {
    const float phase = static_cast<float>(now_ms % 600'000U) / 600'000.0F;
    return 23.5F + 2.5F * sinf(phase * 2.0F * PI_F);
}

float syntheticHumidity(std::uint32_t now_ms) {
    const float phase = static_cast<float>(now_ms % 900'000U) / 900'000.0F;
    return 60.0F + 7.0F * sinf(phase * 2.0F * PI_F + 0.8F);
}

float syntheticSoilMoisture(std::uint32_t now_ms) {
    const float cycle = static_cast<float>(now_ms % 3'600'000U) / 3'600'000.0F;
    return 58.0F - 18.0F * cycle;
}

float syntheticLight(std::uint32_t now_ms) {
    const float phase = static_cast<float>(now_ms % 1'200'000U) / 1'200'000.0F;
    const float daylight = sinf(phase * PI_F);
    return daylight > 0.0F ? daylight * 32'000.0F : 0.0F;
}

bool publishTelemetry(std::uint32_t now_ms) {
    last_telemetry_attempt_ms = now_ms;
    if (!mqtt_client.connected() || !clockIsSynchronized()) {
        return false;
    }

    char timestamp[21U] = {};
    if (!formatTimestamp(timestamp, sizeof(timestamp))) {
        return false;
    }

    StaticJsonDocument<512U> document;
    document["schema_version"] = 1;
    document["device_id"] = DEVICE_ID;
    document["timestamp"] = timestamp;
    JsonObject readings = document.createNestedObject("readings");
    readings["temperature_c"] = syntheticTemperature(now_ms);
    readings["humidity_pct"] = syntheticHumidity(now_ms);
    readings["soil_moisture_pct"] = syntheticSoilMoisture(now_ms);
    readings["light_lux"] = syntheticLight(now_ms);

    const std::size_t required_length = measureJson(document);
    if (required_length == 0U
        || required_length > greenhouse::safety::kMaxTelemetryPayloadBytes) {
        return false;
    }
    char payload[greenhouse::safety::kMaxTelemetryPayloadBytes + 1U] = {};
    const std::size_t length = serializeJson(document, payload, sizeof(payload));
    if (length != required_length) {
        return false;
    }
    const bool published = mqtt_client.publish(
        telemetry_topic,
        reinterpret_cast<const std::uint8_t*>(payload),
        static_cast<unsigned int>(length),
        false
    );
    if (published) {
        has_published_telemetry = true;
        last_telemetry_success_ms = now_ms;
    }
    return published;
}

void maintainMqtt(std::uint32_t now_ms) {
    if (WiFi.status() != WL_CONNECTED) {
        if (mqtt_client.connected()) {
            mqtt_client.disconnect();
        }
        forceRelayOff("wifi_disconnected", now_ms);
        return;
    }
    if (mqtt_client.connected()) {
        return;
    }

    forceRelayOff("mqtt_disconnected", now_ms);
    if (!clockIsSynchronized()
        || !greenhouse::safety::intervalElapsed(
            now_ms,
            last_mqtt_attempt_ms,
            greenhouse::safety::kMqttReconnectIntervalMs
        )) {
        return;
    }
    last_mqtt_attempt_ms = now_ms;

    const bool connected = mqtt_client.connect(
        mqtt_client_id,
        MQTT_USERNAME,
        MQTT_PASSWORD,
        status_topic,
        1U,
        true,
        "offline"
    );
    if (!connected) {
        return;
    }
    mqtt_client.publish(status_topic, "online", true);
    if (!publishTelemetry(now_ms) || !mqtt_client.subscribe(command_topic, 1U)) {
        forceRelayOff("mqtt_session_setup_failed", now_ms);
        mqtt_client.disconnect();
    }
}

bool configureWatchdog() {
#if ESP_IDF_VERSION_MAJOR >= 5
    esp_task_wdt_config_t config = {};
    config.timeout_ms = greenhouse::safety::kWatchdogTimeoutMs;
    config.idle_core_mask = 0U;
    config.trigger_panic = true;
    esp_err_t result = esp_task_wdt_init(&config);
    if (result == ESP_ERR_INVALID_STATE) {
        result = esp_task_wdt_reconfigure(&config);
    }
#else
    const esp_err_t result = esp_task_wdt_init(
        greenhouse::safety::kWatchdogTimeoutMs / 1'000U,
        true
    );
#endif
    if (result != ESP_OK) {
        return false;
    }
    const esp_err_t add_result = esp_task_wdt_add(nullptr);
    return add_result == ESP_OK;
}

}  // namespace

void setup() {
    Serial.begin(115'200U);
    pinMode(RELAY_PIN, OUTPUT);
    writeRelayHardware(false);

    if (!configurationIsSafe()) {
        failClosedBoot("configuration validation failed");
    }
    if (!configureWatchdog()) {
        failClosedBoot("task watchdog initialization failed");
    }

    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    configTime(0, 0, NTP_SERVER);

    tls_client.setCACert(MQTT_ROOT_CA);
    mqtt_client.setServer(MQTT_HOST, MQTT_PORT);
    mqtt_client.setBufferSize(MQTT_PACKET_BUFFER_BYTES);
    mqtt_client.setSocketTimeout(MQTT_SOCKET_TIMEOUT_SECONDS);
    mqtt_client.setCallback(mqttCallback);

    const std::uint32_t now_ms = millis();
    last_mqtt_attempt_ms = now_ms - greenhouse::safety::kMqttReconnectIntervalMs;
    last_telemetry_attempt_ms = now_ms;
}

void loop() {
    std::uint32_t now_ms = millis();
    enforceRelaySafety(now_ms);
    maintainMqtt(now_ms);

    if (mqtt_client.connected()) {
        mqtt_client.loop();
        now_ms = millis();
        if (!mqtt_client.connected()) {
            forceRelayOff("mqtt_disconnected", now_ms);
        } else if (greenhouse::safety::intervalElapsed(
                       now_ms,
                       last_telemetry_attempt_ms,
                       greenhouse::safety::kTelemetryPublishIntervalMs
                   )
            && !publishTelemetry(now_ms)) {
            forceRelayOff("telemetry_publish_failed", now_ms);
        }
    }

    enforceRelaySafety(millis());
    esp_task_wdt_reset();
    delay(10U);
}
