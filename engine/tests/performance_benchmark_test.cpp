// Copyright 2026 Google LLC & Contributors
// Performance benchmark: measures full frame sync pipeline throughput.
// Tests: protocol encode/decode, delta compression, client state, hash computation.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/client_state.hpp"
#include "frame_sync/jitter_stats.hpp"
#include "frame_sync/state_compression.hpp"

#include <gtest/gtest.h>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <vector>
#include <numeric>

using namespace frame_sync;

// ===== Protocol Encoding Throughput =====

TEST(PerformanceBenchmark, AuthoritativeFrameEncodeDecode) {
  const int kIterations = 10000;
  const int kSlots = 22;  // 11v11

  std::vector<SlotInput> inputs(kSlots);
  for (int i = 0; i < kSlots; ++i) {
    inputs[i] = {static_cast<float>(i), 0.5f, static_cast<uint16_t>(i & 0xFF)};
  }

  uint8_t buf[4096];
  auto start = std::chrono::steady_clock::now();

  for (int iter = 0; iter < kIterations; ++iter) {
    size_t n = PackAuthoritativeFrame(iter, inputs.data(),
                                       static_cast<uint16_t>(kSlots),
                                       buf, sizeof(buf));
    ASSERT_GT(n, 0u);

    frame_id_t fid;
    std::vector<SlotInput> decoded;
    size_t used = UnpackAuthoritativeFrame(buf, n, &fid, &decoded);
    ASSERT_EQ(used, n);
    ASSERT_EQ(decoded.size(), static_cast<size_t>(kSlots));
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;
  double us_per_op = static_cast<double>(us) / kIterations;

  std::cout << "AuthoritativeFrame encode+decode (" << kSlots << " slots): " 
            << ops_per_sec << " ops/sec, " << us_per_op << " us/op" << std::endl;

  // Should be fast enough for 10 fps with 22 slots
  EXPECT_GT(ops_per_sec, 1000.0);  // at least 1000 ops/sec
}

TEST(PerformanceBenchmark, ClientFrameInputEncodeDecode) {
  const int kIterations = 10000;

  std::vector<uint16_t> slot_indices = {0, 1, 2};
  std::vector<SlotInput> inputs = {{1.0f, 0.0f, 0}, {0.0f, 1.0f, 0}, {-1.0f, 0.0f, 0}};

  uint8_t buf[1024];
  auto start = std::chrono::steady_clock::now();

  for (int iter = 0; iter < kIterations; ++iter) {
    size_t n = PackClientFrameInput(iter, slot_indices.data(), inputs.data(),
                                     static_cast<uint16_t>(inputs.size()),
                                     buf, sizeof(buf));
    ASSERT_GT(n, 0u);

    frame_id_t fid;
    std::vector<std::pair<uint16_t, SlotInput>> decoded;
    size_t used = UnpackClientFrameInput(buf, n, &fid, &decoded);
    ASSERT_EQ(used, n);
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;

  std::cout << "ClientFrameInput encode+decode: " << ops_per_sec << " ops/sec" << std::endl;
  EXPECT_GT(ops_per_sec, 1000.0);
}

// ===== Delta Compression Throughput =====

TEST(PerformanceBenchmark, DeltaCompressionThroughput) {
  const int kIterations = 50000;
  const int kSlots = 22;

  DeltaEncoder encoder(kSlots);
  std::vector<SlotInput> previous(kSlots);
  std::vector<SlotInput> current(kSlots);

  for (int i = 0; i < kSlots; ++i) {
    previous[i] = {static_cast<float>(i), 0.5f, static_cast<uint16_t>(i)};
    current[i] = {static_cast<float>(i) + 0.1f, 0.6f, static_cast<uint16_t>(i)};
  }

  // Warmup
  for (int i = 0; i < 100; ++i) {
    auto deltas = encoder.Encode(current);
    encoder.Decode(deltas);
  }

  auto start = std::chrono::steady_clock::now();

  size_t total_delta_bytes = 0;
  size_t total_full_bytes = 0;

  for (int iter = 0; iter < kIterations; ++iter) {
    auto deltas = encoder.Encode(current);
    for (const auto& d : deltas) {
      total_delta_bytes += d.packed_size();
    }
    total_full_bytes += kSlots * SLOT_INPUT_BYTES;
    encoder.Decode(deltas);
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;
  float compression_ratio = static_cast<float>(total_delta_bytes) / total_full_bytes;

  std::cout << "Delta compression (" << kSlots << " slots): " << ops_per_sec 
            << " ops/sec, ratio=" << compression_ratio << std::endl;

  EXPECT_GT(ops_per_sec, 10000.0);  // should be very fast
  EXPECT_LT(compression_ratio, 1.0f);  // should compress
}

// ===== ClientState Performance =====

TEST(PerformanceBenchmark, ClientStateSnapshotThroughput) {
  const int kIterations = 10000;
  const size_t kStateSize = 1024;  // typical state blob size

  ClientState cs(MAX_PREDICT_AHEAD_FRAMES + 16);
  SlotInput input{1.0f, 0.0f, 0};
  StateBlob state(kStateSize, 0xAB);

  auto start = std::chrono::steady_clock::now();

  for (int iter = 0; iter < kIterations; ++iter) {
    cs.save_snapshot(iter, input, [&]() { return state; });
    cs.evict_old(iter);
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;

  std::cout << "ClientState snapshot (" << kStateSize << "B): " << ops_per_sec << " ops/sec" << std::endl;
  EXPECT_GT(ops_per_sec, 5000.0);
}

TEST(PerformanceBenchmark, ClientStateRollbackPerformance) {
  const int kIterations = 1000;
  const int kPredictFrames = 10;

  auto start = std::chrono::steady_clock::now();

  for (int iter = 0; iter < kIterations; ++iter) {
    ClientState cs(MAX_PREDICT_AHEAD_FRAMES + 16);
    SlotInput input{1.0f, 0.0f, 0};
    StateBlob state(256, 0xCD);

    // Save snapshots
    for (int f = 0; f < kPredictFrames; ++f) {
      cs.save_snapshot(f, input, [&]() { return state; });
    }

    // Rollback to frame 0
    cs.rollback_to(0, input,
                   [](const StateBlob&) {},
                   [](const SlotInput&) {});
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;

  std::cout << "ClientState rollback (" << kPredictFrames << " frames): " << ops_per_sec << " ops/sec" << std::endl;
  EXPECT_GT(ops_per_sec, 100.0);
}

// ===== FNV-1a Hash Throughput =====

TEST(PerformanceBenchmark, Fnv1aHashThroughput) {
  const int kIterations = 100000;
  const size_t kDataSize = 4096;  // typical state digest size

  std::string data(kDataSize, 'x');

  auto start = std::chrono::steady_clock::now();

  uint64_t result = 0;
  for (int iter = 0; iter < kIterations; ++iter) {
    result = Fnv1aHash(data);
    data[0] = static_cast<char>(iter & 0xFF);  // prevent optimization
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;
  double mb_per_sec = (kIterations * kDataSize) / (us * 1.0);

  std::cout << "Fnv1aHash (" << kDataSize << "B): " << ops_per_sec 
            << " ops/sec, " << mb_per_sec << " MB/s" << std::endl;
  EXPECT_GT(ops_per_sec, 10000.0);
  EXPECT_NE(result, 0u);  // prevent dead code elimination
}

// ===== JitterStats Performance =====

TEST(PerformanceBenchmark, JitterStatsUpdateThroughput) {
  const int kIterations = 100000;

  JitterStats stats;

  auto start = std::chrono::steady_clock::now();

  for (int iter = 0; iter < kIterations; ++iter) {
    stats.record_arrival(iter * 10.0 + (iter % 3) * 2.0);
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;

  std::cout << "JitterStats update: " << ops_per_sec << " ops/sec" << std::endl;
  EXPECT_GT(ops_per_sec, 50000.0);
}

// ===== SlotInput Copy Performance =====

TEST(PerformanceBenchmark, SlotInputMemcpyThroughput) {
  const int kIterations = 1000000;
  const int kSlots = 22;

  std::vector<SlotInput> src(kSlots);
  std::vector<SlotInput> dst(kSlots);

  for (int i = 0; i < kSlots; ++i) {
    src[i] = {static_cast<float>(i), 0.5f, static_cast<uint16_t>(i)};
  }

  auto start = std::chrono::steady_clock::now();

  for (int iter = 0; iter < kIterations; ++iter) {
    std::memcpy(dst.data(), src.data(), kSlots * sizeof(SlotInput));
    src[0].dir_x = static_cast<float>(iter);  // prevent optimization
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;
  double mb_per_sec = (kIterations * kSlots * sizeof(SlotInput)) / (us * 1000.0);

  std::cout << "SlotInput memcpy (" << kSlots << " slots): " << ops_per_sec 
            << " ops/sec, " << mb_per_sec << " MB/s" << std::endl;
  EXPECT_GT(ops_per_sec, 100000.0);
}

// ===== StateHash Pack/Unpack Performance =====

TEST(PerformanceBenchmark, StateHashPackUnpackThroughput) {
  const int kIterations = 100000;

  uint8_t buf[64];
  frame_id_t frame_id = 42;
  state_hash_t hash = 0xDEADBEEF12345678ULL;

  auto start = std::chrono::steady_clock::now();

  for (int iter = 0; iter < kIterations; ++iter) {
    size_t n = PackStateHash(frame_id + iter, hash + iter, buf, sizeof(buf));
    frame_id_t out_fid;
    state_hash_t out_hash;
    size_t used = UnpackStateHash(buf, n, &out_fid, &out_hash);
    (void)used;
  }

  auto elapsed = std::chrono::steady_clock::now() - start;
  auto us = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
  double ops_per_sec = kIterations * 1000000.0 / us;

  std::cout << "StateHash pack+unpack: " << ops_per_sec << " ops/sec" << std::endl;
  EXPECT_GT(ops_per_sec, 50000.0);
}
