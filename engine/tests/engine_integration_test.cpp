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

// ===== Full Client-Server Loop Simulation =====
// Simulates the complete frame sync loop in-process:
//   Server: collect inputs → step → broadcast authoritative frame
//   Client: predict → receive authoritative → rollback if needed
// Verifies both engines stay in sync after N frames.

TEST(FullLoopTest, ClientServerSyncWithoutRollback) {
  // Two independent mock engines (server authoritative, client predicted)
  MockGameEngine server_engine;
  MockGameEngine client_engine;

  // Wire callbacks
  EngineCallbacks server_cb;
  server_cb.save_state = [&]() { return server_engine.save(); };
  server_cb.restore_state = [&](const StateBlob& b) { server_engine.restore(b); };
  server_cb.step = [&](const SlotInput& i) { server_engine.step(i); };
  server_cb.compute_hash = [&]() { return server_engine.compute_hash(); };

  EngineCallbacks client_cb;
  client_cb.save_state = [&]() { return client_engine.save(); };
  client_cb.restore_state = [&](const StateBlob& b) { client_engine.restore(b); };
  client_cb.step = [&](const SlotInput& i) { client_engine.step(i); };
  client_cb.compute_hash = [&]() { return client_engine.compute_hash(); };

  ClientState cs(MAX_PREDICT_AHEAD_FRAMES + 4);
  frame_id_t server_frame = 0;
  frame_id_t client_frame = 0;
  frame_id_t last_confirmed = 0;

  // Run 20 frames — server and client use same inputs (no divergence)
  for (int i = 0; i < 20; ++i) {
    SlotInput input{1.0f, 0.0f, 0};

    // Server: step and pack authoritative frame
    server_cb.step(input);
    std::vector<SlotInput> auth_inputs = {input};
    uint8_t buf[256];
    size_t n = PackAuthoritativeFrame(server_frame, auth_inputs.data(),
                                       static_cast<uint16_t>(auth_inputs.size()),
                                       buf, sizeof(buf));
    ++server_frame;

    // Client: predict one frame
    cs.save_snapshot(client_frame, input, client_cb.save_state);
    client_cb.step(input);
    ++client_frame;

    // Client: unpack and apply authoritative frame
    frame_id_t fid;
    std::vector<SlotInput> unpacked;
    size_t used = UnpackAuthoritativeFrame(buf, n, &fid, &unpacked);
    ASSERT_EQ(used, n);
    last_confirmed = fid;
  }

  // Both engines should have identical state
  EXPECT_FLOAT_EQ(server_engine.position, client_engine.position);
  EXPECT_EQ(server_engine.step_count, client_engine.step_count);
  EXPECT_EQ(server_engine.state_hash_counter, client_engine.state_hash_counter);
  EXPECT_EQ(server_engine.position, 20.0f);
  EXPECT_EQ(server_engine.step_count, 20);
}

TEST(FullLoopTest, ClientServerSyncWithRollback) {
  // Server and client run 10 frames. Server diverges at frame 2 (input=5.0
  // instead of 1.0). Client predicts ahead, then rolls back when it receives
  // the authoritative frame.
  MockGameEngine server_engine;
  MockGameEngine client_engine;

  EngineCallbacks server_cb;
  server_cb.save_state = [&]() { return server_engine.save(); };
  server_cb.restore_state = [&](const StateBlob& b) { server_engine.restore(b); };
  server_cb.step = [&](const SlotInput& i) { server_engine.step(i); };

  EngineCallbacks client_cb;
  client_cb.save_state = [&]() { return client_engine.save(); };
  client_cb.restore_state = [&](const StateBlob& b) { client_engine.restore(b); };
  client_cb.step = [&](const SlotInput& i) { client_engine.step(i); };

  ClientState cs(MAX_PREDICT_AHEAD_FRAMES + 4);
  frame_id_t server_frame = 0;
  frame_id_t client_frame = 0;
  frame_id_t last_confirmed = 0;
  bool rollback_done = false;
  std::unordered_map<frame_id_t, SlotInput> predicted_inputs;

  const int kTotalFrames = 10;

  for (int i = 0; i < kTotalFrames; ++i) {
    // Server input: diverges at frame 2
    SlotInput server_input = (server_frame == 2) ?
        SlotInput{5.0f, 0.0f, 0} : SlotInput{1.0f, 0.0f, 0};
    server_cb.step(server_input);

    // Client predicts with input=1.0 (doesn't know about server divergence)
    SlotInput client_input{1.0f, 0.0f, 0};
    cs.save_snapshot(client_frame, client_input, client_cb.save_state);
    client_cb.step(client_input);
    predicted_inputs[client_frame] = client_input;
    ++client_frame;

    // Server broadcasts authoritative frame
    std::vector<SlotInput> auth_inputs = {server_input};
    uint8_t buf[256];
    size_t n = PackAuthoritativeFrame(server_frame, auth_inputs.data(),
                                       static_cast<uint16_t>(auth_inputs.size()),
                                       buf, sizeof(buf));
    ++server_frame;

    // Client receives authoritative frame
    frame_id_t fid;
    std::vector<SlotInput> unpacked;
    size_t used = UnpackAuthoritativeFrame(buf, n, &fid, &unpacked);
    ASSERT_EQ(used, n);

    // On frame 2: rollback + re-simulate
    if (fid == 2 && !rollback_done && client_frame > 2) {
      rollback_done = true;
      bool ok = cs.rollback_to(2, unpacked[0],
                               client_cb.restore_state, client_cb.step);
      EXPECT_TRUE(ok);

      // Re-simulate frames 3..client_frame-1 with predicted inputs
      for (auto f = 3u; f < client_frame; ++f) {
        auto it = predicted_inputs.find(f);
        if (it != predicted_inputs.end()) {
          client_cb.step(it->second);
        }
      }
    }

    last_confirmed = fid;
  }

  // Server: 1+1+5+1*7 = 14.0
  // Client after rollback: restored to 2.0, +5.0=7.0, +1+1=9.0, +1*5=14.0
  EXPECT_FLOAT_EQ(server_engine.position, client_engine.position);
  EXPECT_EQ(server_engine.step_count, client_engine.step_count);
  EXPECT_TRUE(rollback_done);
}

TEST(FullLoopTest, StateHashVerificationAcrossFrames) {
  MockGameEngine server_engine;
  MockGameEngine client_engine;

  ClientState cs(8);

  // Both engines process the same 15 frames
  for (int i = 0; i < 15; ++i) {
    SlotInput input{1.0f, 0.0f, 0};
    server_engine.step(input);
    client_engine.step(input);

    // Every K frames, server sends state hash
    if ((i + 1) % STATE_HASH_INTERVAL_K == 0) {
      uint64_t server_hash = server_engine.compute_hash();
      cs.record_server_hash(i + 1, server_hash);

      // Client verifies with its own hash
      uint64_t client_hash = client_engine.compute_hash();
      EXPECT_EQ(cs.check_hash(i + 1, client_hash),
                ClientState::HashCheck::kMatch);
    }
  }

  // Both engines identical
  EXPECT_EQ(server_engine.state_hash_counter, client_engine.state_hash_counter);
}

TEST(FullLoopTest, MultiSlotClientServerSync) {
  // 2 slots: slot 0 (left), slot 1 (right)
  MockGameEngine left_engine;
  MockGameEngine right_engine;

  ClientState cs(8);
  frame_id_t frame = 0;

  for (int i = 0; i < 10; ++i) {
    // Server collects inputs for both slots
    SlotInput left_input{1.0f, 0.0f, 0};
    SlotInput right_input{-1.0f, 0.0f, 0};
    std::vector<SlotInput> all_inputs = {left_input, right_input};

    // Pack authoritative frame
    uint8_t buf[256];
    size_t n = PackAuthoritativeFrame(frame, all_inputs.data(),
                                       static_cast<uint16_t>(all_inputs.size()),
                                       buf, sizeof(buf));

    // Both engines step
    left_engine.step(left_input);
    right_engine.step(right_input);

    // Client unpacks
    frame_id_t fid;
    std::vector<SlotInput> unpacked;
    size_t used = UnpackAuthoritativeFrame(buf, n, &fid, &unpacked);
    ASSERT_EQ(used, n);
    ASSERT_EQ(unpacked.size(), 2u);

    ++frame;
  }

  // Left moved +10, right moved -10
  EXPECT_FLOAT_EQ(left_engine.position, 10.0f);
  EXPECT_FLOAT_EQ(right_engine.position, -10.0f);
  EXPECT_EQ(left_engine.step_count, 10);
  EXPECT_EQ(right_engine.step_count, 10);
}
