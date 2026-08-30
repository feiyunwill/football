// Copyright 2026 Google LLC & Contributors
// Integration tests: EngineCallbacks interface, engine_bridge, and
// client-server protocol flow using mock game engine.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/client_state.hpp"

#include <gtest/gtest.h>
#include <cstring>
#include <functional>
#include <thread>
#include <chrono>
#include <vector>
#include <atomic>

using namespace frame_sync;

// ===== Mock Game Engine =====

struct MockGameEngine {
  float position = 0.0f;
  int step_count = 0;
  uint32_t seed = 42;
  uint64_t state_hash_counter = 0;

  StateBlob save() {
    StateBlob blob(sizeof(float) + sizeof(int) + sizeof(uint64_t));
    std::memcpy(blob.data(), &position, sizeof(float));
    std::memcpy(blob.data() + sizeof(float), &step_count, sizeof(int));
    std::memcpy(blob.data() + sizeof(float) + sizeof(int),
                &state_hash_counter, sizeof(uint64_t));
    return blob;
  }

  void restore(const StateBlob& blob) {
    if (blob.size() < sizeof(float) + sizeof(int) + sizeof(uint64_t)) return;
    std::memcpy(&position, blob.data(), sizeof(float));
    std::memcpy(&step_count, blob.data() + sizeof(float), sizeof(int));
    std::memcpy(&state_hash_counter,
                blob.data() + sizeof(float) + sizeof(int), sizeof(uint64_t));
  }

  void step(const SlotInput& input) {
    position += input.dir_x;
    ++step_count;
    state_hash_counter ^= static_cast<uint64_t>(step_count) * 31337;
  }

  uint64_t compute_hash() {
    return state_hash_counter;
  }

  void reset() {
    position = 0.0f;
    step_count = 0;
    state_hash_counter = 0;
  }
};

// ===== EngineCallbacks Interface Tests =====

TEST(EngineCallbacksTest, DefaultCallbacksAreEmpty) {
  EngineCallbacks cb;
  EXPECT_FALSE(cb.save_state);
  EXPECT_FALSE(cb.restore_state);
  EXPECT_FALSE(cb.step);
  EXPECT_FALSE(cb.compute_hash);
}

TEST(EngineCallbacksTest, WiringToMockEngine) {
  MockGameEngine engine;
  EngineCallbacks cb;

  cb.save_state = [&]() -> StateBlob { return engine.save(); };
  cb.restore_state = [&](const StateBlob& b) { engine.restore(b); };
  cb.step = [&](const SlotInput& i) { engine.step(i); };
  cb.compute_hash = [&]() -> uint64_t { return engine.compute_hash(); };

  // Step
  SlotInput input{1.0f, 0.0f, 0};
  cb.step(input);
  EXPECT_FLOAT_EQ(engine.position, 1.0f);
  EXPECT_EQ(engine.step_count, 1);

  // Save
  StateBlob blob = cb.save_state();
  EXPECT_EQ(blob.size(), sizeof(float) + sizeof(int) + sizeof(uint64_t));

  // Step more
  cb.step(input);
  EXPECT_FLOAT_EQ(engine.position, 2.0f);

  // Restore
  cb.restore_state(blob);
  EXPECT_FLOAT_EQ(engine.position, 1.0f);
  EXPECT_EQ(engine.step_count, 1);

  // Hash
  uint64_t h = cb.compute_hash();
  EXPECT_NE(h, 0u);
}

// ===== FNV-1a Hash Tests =====

TEST(Fnv1aHashTest, Deterministic) {
  std::string data = "hello world";
  uint64_t h1 = frame_sync::Fnv1aHash(data);
  uint64_t h2 = frame_sync::Fnv1aHash(data);
  EXPECT_EQ(h1, h2);
}

TEST(Fnv1aHashTest, DifferentInputsDifferentHashes) {
  uint64_t h1 = frame_sync::Fnv1aHash("input_a");
  uint64_t h2 = frame_sync::Fnv1aHash("input_b");
  EXPECT_NE(h1, h2);
}

TEST(Fnv1aHashTest, EmptyString) {
  uint64_t h = frame_sync::Fnv1aHash("");
  // FNV offset basis
  EXPECT_EQ(h, 14695981039346656037ULL);
}

// ===== MultiplayerConfig Tests =====

TEST(MultiplayerConfigTest, DefaultValues) {
  MultiplayerConfig config;
  EXPECT_EQ(config.host, "127.0.0.1");
  EXPECT_EQ(config.port, 12345u);
  EXPECT_EQ(config.left_agents, 1u);
  EXPECT_EQ(config.right_agents, 1u);
  EXPECT_EQ(config.seed, 42u);
  EXPECT_FALSE(config.is_server);
  EXPECT_TRUE(config.render);
  EXPECT_EQ(config.frame_rate_hz, 10);
}

// ===== ClientState Integration with EngineCallbacks =====

TEST(ClientStateEngineIntegrationTest, PredictAndRollback) {
  MockGameEngine engine;
  EngineCallbacks cb;

  cb.save_state = [&]() -> StateBlob { return engine.save(); };
  cb.restore_state = [&](const StateBlob& b) { engine.restore(b); };
  cb.step = [&](const SlotInput& i) { engine.step(i); };

  ClientState cs(MAX_PREDICT_AHEAD_FRAMES + 4);
  frame_id_t frame = 0;

  // Predict 4 frames
  SlotInput input{1.0f, 0.0f, 0};
  for (int i = 0; i < 4; ++i) {
    cs.save_snapshot(frame, input, cb.save_state);
    cb.step(input);
    ++frame;
  }
  EXPECT_FLOAT_EQ(engine.position, 4.0f);

  // Server sends authoritative frame 2 with different input
  SlotInput auth_input{10.0f, 0.0f, 0};
  bool ok = cs.rollback_to(2, auth_input, cb.restore_state, cb.step);

  EXPECT_TRUE(ok);
  // Restored to frame 2 (position=2.0), stepped once with auth_input
  EXPECT_FLOAT_EQ(engine.position, 12.0f);
  EXPECT_EQ(cs.rollback_count(), 1);
}

TEST(ClientStateEngineIntegrationTest, HashVerification) {
  MockGameEngine engine;
  ClientState cs(8);

  // Simulate server sending hash
  engine.step(SlotInput{1.0f, 0.0f, 0});
  uint64_t server_hash = engine.compute_hash();
  cs.record_server_hash(10, server_hash);

  // Client computes same hash
  EXPECT_EQ(cs.check_hash(10, server_hash), ClientState::HashCheck::kMatch);
  EXPECT_EQ(cs.check_hash(10, 0xDEADBEEF),
            ClientState::HashCheck::kMismatch);
}

// ===== Protocol + EngineCallbacks End-to-End =====

TEST(EndToEndTest, AuthoritativeFrameRoundTrip) {
  MockGameEngine engine;
  EngineCallbacks cb;

  cb.save_state = [&]() -> StateBlob { return engine.save(); };
  cb.restore_state = [&](const StateBlob& b) { engine.restore(b); };
  cb.step = [&](const SlotInput& i) { engine.step(i); };

  // Simulate: client predicts 2 frames, server sends authoritative frame 1
  ClientState cs(8);
  frame_id_t frame = 0;

  SlotInput predicted{1.0f, 0.0f, 0};

  // Predict frame 0
  cs.save_snapshot(frame, predicted, cb.save_state);
  cb.step(predicted);
  ++frame;

  // Predict frame 1
  cs.save_snapshot(frame, predicted, cb.save_state);
  cb.step(predicted);
  ++frame;

  EXPECT_FLOAT_EQ(engine.position, 2.0f);

  // Server sends authoritative frame 0 with input=5.0
  SlotInput auth{5.0f, 0.0f, 0};

  // Pack and unpack authoritative frame
  std::vector<SlotInput> auth_inputs = {auth};
  uint8_t buf[256];
  size_t n = PackAuthoritativeFrame(0, auth_inputs.data(),
                                     static_cast<uint16_t>(auth_inputs.size()),
                                     buf, sizeof(buf));
  EXPECT_GT(n, 0u);

  // Unpack
  frame_id_t fid;
  std::vector<SlotInput> unpacked;
  size_t used = UnpackAuthoritativeFrame(buf, n, &fid, &unpacked);
  EXPECT_EQ(used, n);
  EXPECT_EQ(fid, 0u);
  EXPECT_EQ(unpacked.size(), 1u);
  EXPECT_FLOAT_EQ(unpacked[0].dir_x, 5.0f);

  // Rollback to frame 0 with server's input
  bool ok = cs.rollback_to(0, unpacked[0], cb.restore_state, cb.step);
  EXPECT_TRUE(ok);

  // Position: restored to 0.0, stepped once with 5.0
  EXPECT_FLOAT_EQ(engine.position, 5.0f);
}

// ===== StateHash Pack/Unpack =====

TEST(StateHashTest, PackUnpackRoundTrip) {
  frame_id_t frame_id = 42;
  state_hash_t hash = 0xDEADBEEF12345678ULL;

  uint8_t buf[64];
  size_t n = PackStateHash(frame_id, hash, buf, sizeof(buf));
  EXPECT_GT(n, 0u);

  frame_id_t out_fid;
  state_hash_t out_hash;
  size_t used = UnpackStateHash(buf, n, &out_fid, &out_hash);
  EXPECT_EQ(used, n);
  EXPECT_EQ(out_fid, frame_id);
  EXPECT_EQ(out_hash, hash);
}

// ===== Multiple Slots =====

TEST(MultiSlotTest, PackUnpackFrameInput) {
  frame_id_t frame_id = 7;
  std::vector<uint16_t> slot_indices = {0, 2};
  std::vector<SlotInput> inputs = {
    {1.0f, 0.5f, 0x0001},
    {0.0f, -1.0f, 0x000F}
  };

  uint8_t buf[256];
  size_t n = PackClientFrameInput(frame_id, slot_indices.data(),
                                   inputs.data(),
                                   static_cast<uint16_t>(inputs.size()),
                                   buf, sizeof(buf));
  EXPECT_GT(n, 0u);

  frame_id_t out_fid;
  std::vector<std::pair<uint16_t, SlotInput>> out_entries;
  size_t used = UnpackClientFrameInput(buf, n, &out_fid, &out_entries);
  EXPECT_EQ(used, n);
  EXPECT_EQ(out_fid, frame_id);
  EXPECT_EQ(out_entries.size(), 2u);
  EXPECT_EQ(out_entries[0].first, 0u);
  EXPECT_FLOAT_EQ(out_entries[0].second.dir_x, 1.0f);
  EXPECT_EQ(out_entries[1].first, 2u);
  EXPECT_FLOAT_EQ(out_entries[1].second.dir_y, -1.0f);
}
