// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>

namespace mkwvk::PipelineCachePolicy {
// Intel's driver has been observed crashing when a background cache read overlaps pipeline
// creation (Hookshot #999, reported/tested by @ploob-boop). Forced saves remain available.
constexpr bool DeferIntelBackgroundSave(bool force, std::uint32_t vendor_id,
                                        bool explicit_opt_in) noexcept {
    return !force && vendor_id == 0x8086u && !explicit_opt_in;
}
} // namespace mkwvk::PipelineCachePolicy
