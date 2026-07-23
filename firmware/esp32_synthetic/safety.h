#pragma once

#include <cstddef>
#include <cstdint>

namespace greenhouse::safety {

inline constexpr std::uint32_t kRelayHardMaxMs = 30'000U;
inline constexpr std::uint32_t kWatchdogTimeoutMs = 4'000U;
inline constexpr std::uint32_t kRelayCommandMaxMs = 25'000U;
inline constexpr std::uint32_t kRelayCooldownMs = 60'000U;
inline constexpr std::uint32_t kTelemetryPublishIntervalMs = 10'000U;
inline constexpr std::uint32_t kTelemetryStaleMs = 30'000U;
inline constexpr std::uint32_t kMqttReconnectIntervalMs = 5'000U;
inline constexpr std::uint32_t kMaxCommandTtlSeconds = 60U;
inline constexpr std::uint32_t kCommandFutureToleranceSeconds = 5U;
inline constexpr std::size_t kMaxCommandPayloadBytes = 384U;
inline constexpr std::size_t kMaxTelemetryPayloadBytes = 384U;

static_assert(kRelayCommandMaxMs + kWatchdogTimeoutMs < kRelayHardMaxMs);
static_assert(kRelayHardMaxMs < 0x8000'0000U);
static_assert(kRelayCooldownMs < 0x8000'0000U);
static_assert(kTelemetryStaleMs < 0x8000'0000U);

[[nodiscard]] constexpr bool intervalElapsed(
    std::uint32_t now,
    std::uint32_t started_at,
    std::uint32_t interval
) noexcept {
    return static_cast<std::uint32_t>(now - started_at) >= interval;
}

[[nodiscard]] constexpr std::uint32_t cappedRelayDurationMs(
    std::uint32_t requested_ms
) noexcept {
    return requested_ms < kRelayCommandMaxMs ? requested_ms : kRelayCommandMaxMs;
}

[[nodiscard]] constexpr bool commandTimestampIsFresh(
    std::uint64_t now_epoch_seconds,
    std::uint64_t issued_at_epoch_seconds,
    std::uint32_t ttl_seconds
) noexcept {
    if (ttl_seconds == 0U || ttl_seconds > kMaxCommandTtlSeconds) {
        return false;
    }
    if (issued_at_epoch_seconds > now_epoch_seconds) {
        return issued_at_epoch_seconds - now_epoch_seconds <= kCommandFutureToleranceSeconds;
    }
    return now_epoch_seconds - issued_at_epoch_seconds <= ttl_seconds;
}

[[nodiscard]] constexpr bool cooldownComplete(
    std::uint32_t now,
    std::uint32_t stopped_at,
    bool has_stopped
) noexcept {
    return !has_stopped || intervalElapsed(now, stopped_at, kRelayCooldownMs);
}

}  // namespace greenhouse::safety
