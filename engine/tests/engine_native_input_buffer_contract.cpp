// 2026-09-13: formal gate compiles the canonical implementation.
// #include "native_input_buffer.hpp"
#include "frame_sync/native_input_buffer.hpp"
#include <bit>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>

namespace {
std::uint64_t assertions = 0, operations = 0;
void Require(bool value, const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}
std::vector<std::string> Keys(const std::string& text) {
  std::vector<std::string> result;
  if (text == "-") return result;
  std::istringstream stream(text);
  std::string key;
  while (std::getline(stream, key, ',')) result.push_back(key);
  return result;
}
template<class Function> void Rejects(bool expected, Function function) {
  bool rejected = false;
  try { function(); } catch (const std::exception&) { rejected = true; }
  Require(rejected == expected, "Validation result differs from Python oracle");
}
}

int main(int argc, char** argv) {
  try {
    Require(argc == 2, "Expected fixed oracle operation file");
    std::ifstream input(argv[1]);
    Require(input.good(), "Cannot open operation file");
    std::unique_ptr<frame_sync::NativeInputBuffer> buffer;
    std::string line;
    while (std::getline(input, line)) {
      ++operations;
      std::istringstream row(line);
      char kind{};
      row >> kind;
      if (kind == 'B') {
        std::uint64_t bits{}; bool error{}; row >> bits >> error;
        Rejects(error, [&] { buffer = std::make_unique<frame_sync::NativeInputBuffer>(std::bit_cast<double>(bits)); });
      } else {
        Require(bool(buffer), "Operation before buffer creation");
        if (kind == 'F') {
          frame_sync::PythonWindowInput::Sample sample;
          std::string keys, pressed;
          std::uint32_t x{}, y{}; bool error{};
          row >> keys >> pressed >> x >> y >> sample.buttons >> sample.pressed_buttons
              >> sample.focused >> sample.connected >> sample.quit >> error;
          sample.keys = Keys(keys); sample.pressed_keys = Keys(pressed);
          sample.axes = {std::bit_cast<float>(x), std::bit_cast<float>(y)};
          Rejects(error, [&] { buffer->Feed(sample); });
        } else if (kind == 'S') {
          bool value{}, reset{}, error{}; row >> value >> reset >> error;
          Rejects(error, [&] { buffer->SetSuspended(value, reset); });
        } else if (kind == 'T') {
          std::uint32_t x{}, y{}; std::uint16_t buttons{}; row >> x >> y >> buttons;
          const auto actual = buffer->Take();
          Require(std::bit_cast<std::uint32_t>(actual.dir_x) == x, "Direction X wire bits differ");
          Require(std::bit_cast<std::uint32_t>(actual.dir_y) == y, "Direction Y wire bits differ");
          Require(actual.buttons == buttons, "Full button mask differs");
        } else if (kind == 'C') {
          std::array<bool, 3> expected{}; row >> expected[0] >> expected[1] >> expected[2];
          Require(buffer->TakeCommands() == expected, "Command edges differ");
        } else if (kind == 'R') {
          bool release{}, quit{}; row >> release >> quit;
          Require(buffer->release_required() == release && buffer->quit_requested() == quit,
                  "Release barrier or quit latch differs");
        } else if (kind == 'X') buffer->Close();
        else throw std::runtime_error("Unknown oracle operation");
      }
      Require(!row.fail(), "Truncated oracle operation");
      std::string extra;
      Require(!(row >> extra), "Unexpected trailing oracle fields");
    }
    Require(input.eof() && operations > 10000, "Incomplete operation cohort");
    std::cout << "{\"passed\":true,\"skipped\":0,\"assertions\":" << assertions
              << ",\"operations\":" << operations << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "operation=" << operations << ": " << error.what() << '\n';
    return 1;
  }
}
