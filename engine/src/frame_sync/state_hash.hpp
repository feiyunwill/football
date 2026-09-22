// Copyright 2026 Google LLC & Contributors
// 2026-09-09: shared SHA-256 digest prefix, matching the Python protocol.
#ifndef GFOOTBALL_FRAME_SYNC_STATE_HASH_HPP
#define GFOOTBALL_FRAME_SYNC_STATE_HASH_HPP
#include "frame_sync/protocol.hpp"
#include <algorithm>
#include <cstring>
namespace frame_sync {
struct SHA256 {
  uint32_t h[8];
  uint64_t total_len;
  uint8_t buf[64];
  size_t buf_len;

  static constexpr uint32_t k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  };

  SHA256() {
    h[0] = 0x6a09e667; h[1] = 0xbb67ae85;
    h[2] = 0x3c6ef372; h[3] = 0xa54ff53a;
    h[4] = 0x510e527f; h[5] = 0x9b05688c;
    h[6] = 0x1f83d9ab; h[7] = 0x5be0cd19;
    total_len = 0;
    buf_len = 0;
  }

  static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

  void process_block(const uint8_t block[64]) {
    uint32_t w[64];
    for (int i = 0; i < 16; ++i) {
      w[i] = (uint32_t(block[i*4]) << 24) | (uint32_t(block[i*4+1]) << 16) |
             (uint32_t(block[i*4+2]) << 8) | uint32_t(block[i*4+3]);
    }
    for (int i = 16; i < 64; ++i) {
      uint32_t s0 = rotr(w[i-15], 7) ^ rotr(w[i-15], 18) ^ (w[i-15] >> 3);
      uint32_t s1 = rotr(w[i-2], 17) ^ rotr(w[i-2], 19) ^ (w[i-2] >> 10);
      w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3];
    uint32_t e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; ++i) {
      uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      uint32_t ch = (e & f) ^ (~e & g);
      uint32_t temp1 = hh + S1 + ch + k[i] + w[i];
      uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      uint32_t temp2 = S0 + maj;
      hh = g; g = f; f = e; e = d + temp1;
      d = c; c = b; b = a; a = temp1 + temp2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d;
    h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }

  void update(const uint8_t* data, size_t len) {
    total_len += len;
    size_t offset = 0;
    if (buf_len > 0) {
      size_t to_copy = std::min(len, 64 - buf_len);
      memcpy(buf + buf_len, data, to_copy);
      buf_len += to_copy;
      offset += to_copy;
      if (buf_len == 64) {
        process_block(buf);
        buf_len = 0;
      }
    }
    while (offset + 64 <= len) {
      process_block(data + offset);
      offset += 64;
    }
    if (offset < len) {
      memcpy(buf, data + offset, len - offset);
      buf_len = len - offset;
    }
  }

  void finalize(uint8_t out32[32]) {
    uint64_t bits = total_len * 8;
    uint8_t pad = 0x80;
    update(&pad, 1);
    pad = 0x00;
    while (buf_len != 56) {
      update(&pad, 1);
    }
    uint8_t len_be[8];
    for (int i = 7; i >= 0; --i) {
      len_be[i] = static_cast<uint8_t>(bits & 0xFF);
      bits >>= 8;
    }
    update(len_be, 8);
    for (int i = 0; i < 8; ++i) {
      out32[i*4]   = static_cast<uint8_t>(h[i] >> 24);
      out32[i*4+1] = static_cast<uint8_t>(h[i] >> 16);
      out32[i*4+2] = static_cast<uint8_t>(h[i] >> 8);
      out32[i*4+3] = static_cast<uint8_t>(h[i]);
    }
  }
};

// Compute 64-bit state hash: SHA-256 of state digest, take first 8 bytes as uint64_t.
inline state_hash_t ComputeStateHash(const void* data, size_t len) {
  SHA256 sha;
  sha.update(static_cast<const uint8_t*>(data), len);
  uint8_t digest[32];
  sha.finalize(digest);
  frame_sync::state_hash_t result;
  result = 0;
  for (size_t i = 0; i < sizeof(result); ++i) result |= static_cast<uint64_t>(digest[i]) << (8 * i);
  return result;
}

}  // namespace frame_sync
#endif
