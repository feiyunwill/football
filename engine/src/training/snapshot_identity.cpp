#include "training/snapshot_identity.hpp"
#include "game_env.hpp"
#include "training_snapshot_identity.hpp"
#include "frame_sync/state_hash.hpp"
#include <filesystem>
#include <fstream>
#include <set>
namespace football::training {
namespace {
std::string Hex(frame_sync::SHA256& hash) {
  uint8_t digest[32]; hash.finalize(digest);
  std::string result;
  constexpr char digits[] = "0123456789abcdef";
  for (auto byte : digest) { result += digits[byte >> 4]; result += digits[byte & 15]; }
  return result;
}
std::string FileDigest(const std::filesystem::path& path) {
  snapshot::Require(std::filesystem::file_size(path) <= 67108864, "Training resource exceeds file budget");
  std::ifstream stream(path, std::ios::binary);
  if (!stream) throw std::runtime_error("Cannot read training resource");
  frame_sync::SHA256 hash;
  std::array<char, 65536> buffer;
  size_t count = 0;
  while (stream) {
    stream.read(buffer.data(), buffer.size());
    const size_t length = static_cast<size_t>(stream.gcount());
    count += length;
    snapshot::Require(count <= 67108864, "Training resource exceeds file budget");
    hash.update(reinterpret_cast<const uint8_t*>(buffer.data()), length);
  }
  if (!stream.eof()) throw std::runtime_error("Cannot read complete training resource");
  return Hex(hash);
}
}
std::string TrainingCompatibility(const GameEnv& env) {
  namespace fs = std::filesystem;
  const fs::path root(env.game_config.data_dir);
  std::set<std::string> paths;
  size_t entries = 0;
  uintmax_t total = 0;
  for (const auto& file : fs::recursive_directory_iterator(root)) {
    snapshot::Require(++entries <= 16384, "Training resource directory exceeds budget");
    if (!file.is_regular_file()) continue;
    const auto length = file.file_size();
    snapshot::Require(length <= 67108864, "Training resource exceeds file budget");
    total += length;
    snapshot::Require(total <= 536870912, "Training dataset exceeds budget");
    paths.insert(file.path().lexically_relative(root).generic_string());
  }
  snapshot::Require(paths.size() == identity::kResources.size(), "Training dataset does not match build");
  for (const auto& file : identity::kResources) {
    snapshot::Require(paths.contains(std::string(file.path)) && FileDigest(root / file.path) == file.sha,
                      "Training resource does not match build");
  }
  // Dimensions affect the kernel's runtime configuration, although training is headless.
  std::string value(identity::kBuild);
  snapshot::detail::Append32(value, env.game_config.render_resolution_x);
  snapshot::detail::Append32(value, env.game_config.render_resolution_y);
  snapshot::detail::Append32(value, sizeof(int));
  snapshot::detail::Append32(value, sizeof(long));
  snapshot::detail::Append32(value, sizeof(void*));
  frame_sync::SHA256 hash;
  hash.update(reinterpret_cast<const uint8_t*>(value.data()), value.size());
  return Hex(hash);
}
}  // namespace football::training
