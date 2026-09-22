// 2026-09-22: persistent contracts for the actual shared-engine resource reader.
#include "file.h"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <typeinfo>
#include <vector>

namespace {
size_t assertions = 0;
void Require(bool value, const char* reason) {
  ++assertions;
  if (!value) throw std::runtime_error(reason);
}
std::string LegacyRead(const std::filesystem::path& path) {
  std::ifstream file;
  file.open(path.string().c_str(), std::ios::in);
  std::string result((std::istreambuf_iterator<char>(file)),
                     std::istreambuf_iterator<char>());
  file.close();
  return result;
}
std::string Pattern(size_t size) {
  std::string result(size, '\0');
  for (size_t i = 0; i < size; ++i)
    result[i] = static_cast<char>((i * 131 + (i >> 8) + (i >> 16) * 17) % 256);
  return result;
}
}  // namespace

int main() {
  std::filesystem::path scratch;
  std::vector<std::filesystem::path> created;
  auto cleanup = [&] {
    std::error_code error;
    for (const auto& file : created) std::filesystem::remove(file, error);
    if (!scratch.empty()) std::filesystem::remove(scratch, error);
  };
  try {
    const auto token = std::chrono::steady_clock::now().time_since_epoch().count();
    for (unsigned attempt = 0; attempt < 100; ++attempt) {
      const auto path = std::filesystem::temp_directory_path() /
          ("football-file-read-" + std::to_string(token) + "-" + std::to_string(attempt));
      if (std::filesystem::create_directory(path)) { scratch = path; break; }
    }
    Require(!scratch.empty(), "Could not create private test directory");
    std::vector<std::string> cases{"", "\n", "a\r\nb\r", "final",
                                  std::string("a\0b\x1a\n", 5)};
    std::string all_bytes;
    for (unsigned i = 0; i < 256; ++i) all_bytes.push_back(static_cast<char>(i));
    cases.push_back(all_bytes);
    for (size_t size : {65535u, 65536u, 65537u, 131072u, 131073u})
      cases.push_back(Pattern(size));
    for (size_t i = 0; i < cases.size(); ++i) {
      const auto path = scratch / std::to_string(i);
      created.push_back(path);
      std::ofstream output(path, std::ios::binary);
      output.write(cases[i].data(), static_cast<std::streamsize>(cases[i].size()));
      output.close();
      Require(bool(output), "Could not write fixture");
      const auto expected = LegacyRead(path);
      const auto actual = GetFile(path.string());
      Require(actual == expected, "Text or block boundary semantics changed");
#ifndef WIN32
      Require(actual == cases[i], "Binary fixture bytes changed");
#endif
    }
    const auto absent = scratch / "absent";
    Require(GetFile(absent.string()).empty(), "Missing path must return empty");
    Require(!std::filesystem::exists(absent), "Read created a missing file");
    std::string old_error, new_error, old_result, new_result;
    try { old_result = LegacyRead(scratch); }
    catch (const std::exception& e) { old_error = typeid(e).name(); }
    try { new_result = GetFile(scratch.string()); }
    catch (const std::exception& e) { new_error = typeid(e).name(); }
    Require(old_error == new_error && old_result == new_result,
            "Underlying read-error semantics changed");
    // Re-read a replaced resource: the reader must not return a stale cached value.
    const auto reused = created.back();
    std::ofstream(reused, std::ios::binary | std::ios::trunc) << "replacement";
    Require(GetFile(reused.string()) == "replacement", "Replaced resource read was stale");
    cleanup();
    Require(!std::filesystem::exists(scratch), "Temporary resources not released");
    std::cout << "{\"passed\":true,\"checks\":" << cases.size() + 3
              << ",\"assertions\":" << assertions << ",\"skipped\":0}\n";
  } catch (const std::exception& error) {
    cleanup();
    std::cerr << error.what() << '\n';
    return 1;
  }
}
