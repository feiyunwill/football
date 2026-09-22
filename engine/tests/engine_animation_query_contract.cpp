// 2026-09-09: preserve metadata semantics while removing hot-path allocations.
#include "base/utils.hpp"
#include "utils/animation.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
int assertions = 0;
void Require(bool condition, const char* message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}

// Independent oracle: the previous tokenizing implementation and atof rounding.
blunted::Vector3 PreviousParser(const std::string& text) {
  if (text.empty()) return blunted::Vector3(0.0f);
  std::vector<std::string> tokens;
  blunted::tokenize(text, tokens, ",");
  if (tokens.empty() || tokens.size() > 3) throw std::logic_error("Invalid fixture");
  blunted::Vector3 value;
  for (size_t i = 0; i < tokens.size(); ++i) value.coords[i] = atof(tokens[i].c_str());
  return value;
}

void Compare(const std::string& text) {
  const auto expected = PreviousParser(text);
  const auto actual = blunted::GetVectorFromString(text);
  for (int i = 0; i < 3; ++i) {
    Require(std::bit_cast<uint32_t>(expected.coords[i]) ==
                std::bit_cast<uint32_t>(actual.coords[i]),
            "Vector parser changed floating point bits");
  }
}

void Parsing() {
  for (const std::string text : {
           "", "1", "1,2", "1,2,3", ",,1,,,2,,3,,", "-0,+0,-0.0",
           " \t1 ,\n-2,\r+3", "1e-40,-1e30,0x1.8p2", "1suffix,word,  ",
           "nan,-inf,inf", "1e+,0x,-.5", "1e-999,1e999,-1e999"}) {
    Compare(text);
  }
  Compare(std::string("1\0suffix,2,-0", 13));
  for (const size_t length : {126, 127, 128, 129, 4096}) {
    Compare(std::string(length, ' ') + "-0,2,3");
    Compare("1." + std::string(length, '0') + "5,-2,3");
  }
  // Fixed generation exercises delimiter skipping and all coordinate counts.
  std::mt19937 random(20260909);
  for (int sample = 0; sample < 10000; ++sample) {
    std::string text(random() % 4, ',');
    const int count = 1 + random() % 3;
    for (int coordinate = 0; coordinate < count; ++coordinate) {
      if (coordinate) text.append(1 + random() % 4, ',');
      text += (random() % 2 ? " \t-" : " +");
      text += std::to_string(random() % 1000000);
      text += "." + std::to_string(random() % 1000000);
      text += "e" + std::to_string(static_cast<int>(random() % 80) - 40);
      if (random() % 3 == 0) text += "suffix";
    }
    text.append(random() % 4, ',');
    Compare(text);
  }
}

void Variables() {
  blunted::VariableCache cache;
  const std::string key = "incomingballdirection_maxdeviation";
  Require(cache.get_ref(key).empty(), "Missing property must stay empty");
  const auto* empty = &cache.get_ref(key);
  Require(empty == &cache.get_ref("another_missing_key"), "Missing lookup is unstable");
  const std::string value(256, 'v');
  cache.set(key, value);
  Require(cache.get_ref(key) == cache.get(key), "Reference and owning APIs disagree");
  const auto* original = &cache.get_ref(key);
  const auto owned = cache.get(key);
  const std::string padded = "prefix" + key + "suffix";
  Require(&cache.get_ref(std::string_view(padded).substr(6, key.size())) == original,
          "Lookup requires null termination or creates a different value");
  for (int i = 0; i < 1000; ++i) cache.set("unrelated_" + std::to_string(i), value);
  Require(&cache.get_ref(key) == original && *original == value,
          "Unrelated insertion invalidated property reference");
  cache.set(key, "replacement");
  Require(cache.get_ref(key) == "replacement", "Updated property is stale");
  Require(owned == value, "Owning API lost copy semantics");
  const auto copy = cache;
  Require(copy.get_ref(key) == cache.get_ref(key) &&
              &copy.get_ref(key) != &cache.get_ref(key),
          "Copied cache aliases another cache's storage");
  cache.set("idlelevel", "0.25");
  cache.set("specialvar1", "3.5");
  cache.set("incoming_special_state", "left_hand");
  cache.mirror();
  Require(cache.idlelevel() == 0.25f && cache.specialvar1() == 3.5f &&
              cache.incoming_special_state() == "right_hand",
          "Typed metadata behavior changed");
  blunted::Animation animation;
  Require(animation.GetVariable("missing") == animation.GetVariableRef("missing"),
          "Animation reference API differs from owning API");
}
}  // namespace

int main() {
  try {
    Parsing();
    Variables();
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"skipped\":0}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
