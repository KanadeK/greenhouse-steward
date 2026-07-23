#include "safety.h"

#include <cassert>
#include <cstdint>
#include <limits>

int main() {
    using greenhouse::safety::cappedRelayDurationMs;
    using greenhouse::safety::commandTimestampIsFresh;
    using greenhouse::safety::cooldownComplete;
    using greenhouse::safety::intervalElapsed;

    static_assert(greenhouse::safety::kRelayHardMaxMs == 30'000U);
    static_assert(
        greenhouse::safety::kRelayCommandMaxMs + greenhouse::safety::kWatchdogTimeoutMs
        < greenhouse::safety::kRelayHardMaxMs
    );

    const std::uint32_t near_rollover = std::numeric_limits<std::uint32_t>::max() - 10U;
    assert(intervalElapsed(5U, near_rollover, 16U));
    assert(!intervalElapsed(5U, near_rollover, 17U));

    assert(cappedRelayDurationMs(1'000U) == 1'000U);
    assert(cappedRelayDurationMs(30'000U) == 25'000U);

    assert(commandTimestampIsFresh(1'000U, 995U, 5U));
    assert(!commandTimestampIsFresh(1'001U, 995U, 5U));
    assert(commandTimestampIsFresh(1'000U, 1'005U, 10U));
    assert(!commandTimestampIsFresh(1'000U, 1'006U, 10U));
    assert(!commandTimestampIsFresh(1'000U, 1'000U, 0U));
    assert(!commandTimestampIsFresh(1'000U, 1'000U, 61U));

    assert(cooldownComplete(0U, 0U, false));
    assert(!cooldownComplete(59'999U, 0U, true));
    assert(cooldownComplete(60'000U, 0U, true));
}
