// 2026-09-13: compare the production estimator against its frozen previous body.
#include "onthepitch/AIsupport/AIfunctions.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
#define AI_GetTimeNeededForDistance_ms ReferenceTimeNeededForDistance_ms
#include "fixtures/ai_time_needed_20260913.inc"
#undef AI_GetTimeNeededForDistance_ms

std::uint64_t cases = 0;
std::uint64_t assertions = 0;
std::uint64_t cached_cases = 0;
std::uint64_t zero_results = 0;
std::uint64_t fast_distance_cases = 0;
std::uint64_t finite_timeout_cases = 0;

void Require(bool condition, const char* message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}

void Compare(const Vector3& position, const Vector3& movement,
             const Vector3& target, float speed, bool precise,
             unsigned int maximum) {
  const auto expected = ReferenceTimeNeededForDistance_ms(
      position, movement, target, speed, precise, maximum);
  const auto actual = AI_GetTimeNeededForDistance_ms(
      position, movement, target, speed, precise, maximum);
  ++cases;
  if (actual.usual_ms != expected.usual_ms ||
      actual.optimistic_ms != expected.optimistic_ms) {
    std::cerr << "Mismatch case=" << cases << " precise=" << precise
              << " maximum=" << maximum << " speed=" << speed
              << " expected=" << expected.usual_ms << ',' << expected.optimistic_ms
              << " actual=" << actual.usual_ms << ',' << actual.optimistic_ms
              << " position=" << position.coords[0] << ',' << position.coords[1]
              << ',' << position.coords[2] << " movement=" << movement.coords[0]
              << ',' << movement.coords[1] << ',' << movement.coords[2]
              << " target=" << target.coords[0] << ',' << target.coords[1]
              << ',' << target.coords[2] << '\n';
  }
  Require(actual.usual_ms == expected.usual_ms, "Usual arrival time changed");
  Require(actual.optimistic_ms == expected.optimistic_ms,
          "Optimistic arrival time changed");
  // 2026-09-13: compare both cold and populated cache against the frozen body.
  AIReachabilityTrajectory trajectory(position, movement, speed);
  for (int repeat = 0; repeat < 2; ++repeat) {
    const auto cached = trajectory.Estimate(target, precise, maximum);
    ++cached_cases;
    Require(cached.usual_ms == expected.usual_ms, "Cached usual time changed");
    Require(cached.optimistic_ms == expected.optimistic_ms, "Cached optimistic time changed");
  }
  zero_results += actual.usual_ms == 0;
  fast_distance_cases += (position - target).GetLength() > (precise ? 48.f : 16.f);
  finite_timeout_cases += maximum != std::numeric_limits<unsigned int>::max();
}

constexpr std::array<unsigned int, 18> timeouts = {
    0, 1, 9, 10, 11, 19, 20, 21, 99, 100, 699, 700, 701, 999,
    1000, 1001, 10000, std::numeric_limits<unsigned int>::max()};

void Boundaries() {
  std::vector<float> distances;
  for (float value : {0.f, .1f, .28f, .38f, .9f, 1.f, 2.f, 16.f, 48.f, 100.f}) {
    distances.push_back(std::nextafter(value, -std::numeric_limits<float>::infinity()));
    distances.push_back(value);
    distances.push_back(std::nextafter(value, std::numeric_limits<float>::infinity()));
  }
  const std::array<Vector3, 9> movements = {
      Vector3(0.f), Vector3(-0.f), Vector3(idleDribbleSwitch, 0.f, 0.f),
      Vector3(std::nextafter(idleDribbleSwitch, 0.f), 0.f, 0.f),
      Vector3(std::nextafter(idleDribbleSwitch, 10.f), 0.f, 0.f),
      Vector3(-6.f, 0.f, 0.f), Vector3(0.f, 8.f, 0.f),
      Vector3(3.f, -4.f, .5f), Vector3(0.f, 0.f, 4.f)};
  // Axis-aligned origin cases retain nextafter distance boundaries exactly.
  for (bool precise : {false, true}) {
    for (unsigned int maximum : timeouts) {
      for (float speed : {.1f, 1.f, 6.5f, 10.f}) {
        for (float distance : distances) {
          for (const auto& movement : movements) {
            Compare(Vector3(0.f), movement, Vector3(distance, 0.f, 0.f),
                    speed, precise, maximum);
          }
        }
      }
    }
  }
  // Translation, opposing headings, nonzero height, and all coordinate axes.
  for (const auto& position : {Vector3(47.5f, -29.25f, .5f),
                               Vector3(-47.5f, 29.25f, -.5f)}) {
    for (const auto& direction : {Vector3(1.f, 0.f, 0.f), Vector3(0.f, -1.f, 0.f),
                                  Vector3(0.f, 0.f, 1.f), Vector3(.6f, -.8f, .25f)}) {
      for (float distance : distances) {
        for (const auto& movement : movements) {
          for (unsigned int maximum : timeouts) {
            for (bool precise : {false, true}) {
              Compare(position, movement, position + direction * distance,
                      6.5f, precise, maximum);
            }
          }
        }
      }
    }
  }
}

void GeneratedCases() {
  std::mt19937 random(20260913);
  auto coordinate = [&random](float scale) {
    return (static_cast<int>(random() % 200001) - 100000) * scale;
  };
  for (int sample = 0; sample < 100000; ++sample) {
    const Vector3 position(coordinate(.0006f), coordinate(.0004f), coordinate(.00001f));
    const Vector3 movement(coordinate(.00008f), coordinate(.00008f), coordinate(.00001f));
    const float scale = sample % 2 ? .0006f : .000015f;
    const Vector3 target = position + Vector3(coordinate(scale), coordinate(scale),
                                              coordinate(.00002f));
    const float speed = .1f + (random() % 9901) * .001f;
    const unsigned int maximum = timeouts[random() % timeouts.size()];
    Compare(position, movement, target, speed, sample % 2 != 0, maximum);
  }
}
// 2026-09-13: reuse one owner across unrelated targets and non-monotonic
// deadlines. A far first query must not require trajectory initialization.
void SharedTrajectories() {
  std::mt19937 random(20260914);
  auto coordinate = [&random](float scale) {
    return (static_cast<int>(random() % 200001) - 100000) * scale;
  };
  for (int owner = 0; owner < 1000; ++owner) {
    const Vector3 position(coordinate(.0006f), coordinate(.0004f), coordinate(.00001f));
    Vector3 movement(coordinate(.00008f), coordinate(.00008f), coordinate(.00001f));
    if (owner % 5 == 0) movement = Vector3(0.f);
    if (owner % 5 == 1) movement = Vector3(idleDribbleSwitch, 0.f, 0.f);
    if (owner % 5 == 2) movement = Vector3(std::nextafter(idleDribbleSwitch, 10.f), 0.f, 0.f);
    if (owner % 5 == 3) movement = Vector3(0.f, 0.f, 4.f);
    const float speed = .1f + (random() % 9901) * .001f;
    AIReachabilityTrajectory trajectory(position, movement, speed);
    for (int query = 0; query < 128; ++query) {
      const Vector3 target = query == 0 ? position + Vector3(100.f, 0.f, 0.f) :
          (query % 7 == 0 ? position : position +
              Vector3(coordinate(.00015f), coordinate(.00015f), coordinate(.00002f)));
      const unsigned int maximum = timeouts[(127 - query) % timeouts.size()];
      const bool precise = query % 2 != 0;
      const auto expected = ReferenceTimeNeededForDistance_ms(
          position, movement, target, speed, precise, maximum);
      const auto actual = trajectory.Estimate(target, precise, maximum);
      ++cached_cases;
      Require(actual.usual_ms == expected.usual_ms, "Reused trajectory usual time changed");
      Require(actual.optimistic_ms == expected.optimistic_ms,
              "Reused trajectory optimistic time changed");
    }
  }
}

}  // namespace

int main() {
  try {
    const auto at_rest = AI_GetTimeNeededForDistance_ms(Vector3(0.f), Vector3(0.f),
                                                       Vector3(0.f), 6.5f, false);
    Require(at_rest.usual_ms == 0 && at_rest.optimistic_ms == 0,
            "At-target arrival must remain zero");
    const auto far = AI_GetTimeNeededForDistance_ms(Vector3(0.f), Vector3(0.f),
                                                    Vector3(100.f, 0.f, 0.f), 10.f);
    Require(far.usual_ms == 13333 && far.optimistic_ms == 13133,
            "Far-distance rounding changed");
    Boundaries();
    GeneratedCases();
    SharedTrajectories();
    Require(cached_cases == 561280, "Cached differential cohort changed");
    Require(sizeof(AIReachabilityTrajectory) <= 1536, "Trajectory exceeds stack budget");
    Require(cases == 216640, "Differential case cohort changed");
    Require(zero_results > 0 && fast_distance_cases > 0 && finite_timeout_cases > 0,
            "Missing close, far, or bounded-time cases");
    std::cout << "{\"passed\":true,\"skipped\":0,\"assertions\":" << assertions
              << ",\"cached_cases\":" << cached_cases
              << ",\"trajectory_bytes\":" << sizeof(AIReachabilityTrajectory)
              << ",\"cases\":" << cases << ",\"zero_results\":" << zero_results
              << ",\"fast_distance_cases\":" << fast_distance_cases
              << ",\"finite_timeout_cases\":" << finite_timeout_cases << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
