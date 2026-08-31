// Copyright 2019 Google LLC & Contributors
// Performance benchmark for frame sync optimizations.

#include <chrono>
#include <iostream>
#include <vector>
#include <cstring>
#include "frame_sync/protocol.hpp"
#include "frame_sync/state_compression.hpp"
#include "frame_sync/protocol_io.hpp"

using namespace frame_sync;

// Benchmark delta computation
void benchmark_delta_computation(size_t iterations) {
  SlotInput current, previous;
  current.dir_x = 0.5f;
  current.dir_y = -0.3f;
  current.buttons = 0x00FF;
  previous.dir_x = 0.4f;
  previous.dir_y = -0.2f;
  previous.buttons = 0x00FE;
  
  auto start = std::chrono::high_resolution_clock::now();
  
  for (size_t i = 0; i < iterations; ++i) {
    DeltaSlotInput delta = DeltaSlotInput::Compute(current, previous);
    // Prevent optimization
    volatile uint8_t flags = delta.flags;
    (void)flags;
  }
  
  auto end = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start);
  
  std::cout << "Delta Computation: " << duration.count() / iterations << " ns/iter" << std::endl;
}

// Benchmark delta packing
void benchmark_delta_packing(size_t iterations) {
  DeltaSlotInput delta;
  delta.flags = 0x07;
  delta.dir_x = 0.5f;
  delta.dir_y = -0.3f;
  delta.buttons = 0x00FF;
  
  uint8_t buffer[64];
  
  auto start = std::chrono::high_resolution_clock::now();
  
  for (size_t i = 0; i < iterations; ++i) {
    size_t packed = delta.Pack(buffer, sizeof(buffer));
    // Prevent optimization
    volatile size_t result = packed;
    (void)result;
  }
  
  auto end = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start);
  
  std::cout << "Delta Packing: " << duration.count() / iterations << " ns/iter" << std::endl;
}

// Benchmark delta unpacking
void benchmark_delta_unpacking(size_t iterations) {
  DeltaSlotInput delta;
  delta.flags = 0x07;
  delta.dir_x = 0.5f;
  delta.dir_y = -0.3f;
  delta.buttons = 0x00FF;
  
  uint8_t buffer[64];
  size_t packed_size = delta.Pack(buffer, sizeof(buffer));
  
  auto start = std::chrono::high_resolution_clock::now();
  
  for (size_t i = 0; i < iterations; ++i) {
    DeltaSlotInput unpacked;
    [[maybe_unused]] size_t unpacked_size = unpacked.Unpack(buffer, packed_size);
    // Prevent optimization
    volatile uint8_t flags = unpacked.flags;
    (void)flags;
  }
  
  auto end = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start);
  
  std::cout << "Delta Unpacking: " << duration.count() / iterations << " ns/iter" << std::endl;
}

// Benchmark full SlotInput pack/unpack
void benchmark_slot_input_pack(size_t iterations) {
  SlotInput input;
  input.dir_x = 0.5f;
  input.dir_y = -0.3f;
  input.buttons = 0x00FF;
  
  uint8_t buffer[64];
  
  auto start = std::chrono::high_resolution_clock::now();
  
  for (size_t i = 0; i < iterations; ++i) {
    // Use DeltaSlotInput::Pack instead
    DeltaSlotInput delta;
    delta.flags = 0x07;
    delta.dir_x = input.dir_x;
    delta.dir_y = input.dir_y;
    delta.buttons = input.buttons;
    size_t packed = delta.Pack(buffer, sizeof(buffer));
    // Prevent optimization
    volatile size_t result = packed;
    (void)result;
  }
  
  auto end = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start);
  
  std::cout << "SlotInput Pack: " << duration.count() / iterations << " ns/iter" << std::endl;
}

void benchmark_slot_input_unpack(size_t iterations) {
  SlotInput input;
  input.dir_x = 0.5f;
  input.dir_y = -0.3f;
  input.buttons = 0x00FF;
  
  uint8_t buffer[64];
  DeltaSlotInput delta;
  delta.flags = 0x07;
  delta.dir_x = input.dir_x;
  delta.dir_y = input.dir_y;
  delta.buttons = input.buttons;
  size_t packed_size = delta.Pack(buffer, sizeof(buffer));
  
  auto start = std::chrono::high_resolution_clock::now();
  
  for (size_t i = 0; i < iterations; ++i) {
    DeltaSlotInput unpacked;
    [[maybe_unused]] size_t unpacked_size = unpacked.Unpack(buffer, packed_size);
    // Prevent optimization
    volatile uint16_t buttons = unpacked.buttons;
    (void)buttons;
  }
  
  auto end = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start);
  
  std::cout << "SlotInput Unpack: " << duration.count() / iterations << " ns/iter" << std::endl;
}

// Benchmark DeltaEncoder batch operations
void benchmark_delta_encoder_batch(size_t num_slots, size_t iterations) {
  DeltaEncoder encoder(num_slots);
  std::vector<SlotInput> inputs(num_slots);
  
  // Initialize with some variation
  for (size_t i = 0; i < num_slots; ++i) {
    inputs[i].dir_x = static_cast<float>(i) / num_slots;
    inputs[i].dir_y = -static_cast<float>(i) / num_slots;
    inputs[i].buttons = static_cast<uint16_t>(i & 0xFF);
  }
  
  auto start = std::chrono::high_resolution_clock::now();
  
  for (size_t iter = 0; iter < iterations; ++iter) {
    auto deltas = encoder.Encode(inputs);
    auto decoded = encoder.Decode(deltas);
    // Prevent optimization
    volatile size_t size = decoded.size();
    (void)size;
  }
  
  auto end = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start);
  
  std::cout << "DeltaEncoder Batch (" << num_slots << " slots): " 
            << duration.count() / iterations << " ns/iter" << std::endl;
}

// Benchmark packed size calculation
void benchmark_packed_size(size_t iterations) {
  DeltaSlotInput delta;
  delta.flags = 0x07;
  
  auto start = std::chrono::high_resolution_clock::now();
  
  for (size_t i = 0; i < iterations; ++i) {
    size_t size = delta.packed_size();
    // Prevent optimization
    volatile size_t result = size;
    (void)result;
  }
  
  auto end = std::chrono::high_resolution_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start);
  
  std::cout << "Packed Size: " << duration.count() / iterations << " ns/iter" << std::endl;
}

int main() {
  std::cout << "=== Frame Sync Performance Benchmark ===" << std::endl;
  std::cout << std::endl;
  
  const size_t kIterations = 1000000;
  
  std::cout << "Running " << kIterations << " iterations per benchmark..." << std::endl;
  std::cout << std::endl;
  
  benchmark_delta_computation(kIterations);
  benchmark_delta_packing(kIterations);
  benchmark_delta_unpacking(kIterations);
  benchmark_slot_input_pack(kIterations);
  benchmark_slot_input_unpack(kIterations);
  benchmark_packed_size(kIterations);
  
  std::cout << std::endl;
  std::cout << "Batch operations:" << std::endl;
  benchmark_delta_encoder_batch(2, kIterations / 10);
  benchmark_delta_encoder_batch(4, kIterations / 10);
  benchmark_delta_encoder_batch(11, kIterations / 10);
  
  std::cout << std::endl;
  std::cout << "=== Benchmark Complete ===" << std::endl;
  
  return 0;
}
