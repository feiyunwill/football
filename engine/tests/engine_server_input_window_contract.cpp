// 2026-09-13: independent ordered-map oracle for bounded future authority admission.
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "server_input_window.hpp"
#include "frame_sync/server_input_window.hpp"
#include <iostream>
#include <map>
#include <limits>
#include <vector>
namespace {
namespace fs = frame_sync;
size_t assertions = 0;
void Require(bool value, const char* reason) {
  ++assertions; if (!value) throw std::runtime_error(reason);
}
bool Same(const fs::SlotInput& a, const fs::SlotInput& b) {
  return a.dir_x == b.dir_x && a.dir_y == b.dir_y && a.buttons == b.buttons;
}
template<class Error, class Function> void Throws(Function f) {
  bool caught = false; try { f(); } catch (const Error&) { caught = true; }
  Require(caught, "Expected rejection missing");
}
void Run(size_t slots) {
  fs::ServerInputWindow window(slots);
  std::map<uint32_t, std::map<uint16_t, fs::SlotInput>> expected;
  uint64_t random = 78193 + slots;
  auto next = [&] { random = random * 6364136223846793005ULL + 1; return random >> 32; };
  for (uint32_t frame = 0; frame < 6000; ++frame) {
    Require(window.current() == frame, "Frame sequence skipped");
    for (int attempt = 0; attempt < 12; ++attempt) {
      const auto fid = frame + static_cast<uint32_t>(next() % 21);
      const auto slot = static_cast<uint16_t>(next() % slots);
      fs::SlotInput input = fs::SlotInput::Default();
      input.dir_x = float(int(next() % 3) - 1); input.buttons = next() % 2 ? 512 : 0;
      const std::pair<uint16_t,fs::SlotInput> packet{slot,input};
      fs::InputAdmission outcome;
      if (fid - frame >= 16) outcome = fs::InputAdmission::OutsideWindow;
      else if (expected.contains(fid) && expected.at(fid).contains(slot) &&
               !Same(expected.at(fid).at(slot),input)) outcome = fs::InputAdmission::Conflict;
      else { expected[fid][slot] = input; outcome = fs::InputAdmission::Accepted; }
      Require(window.Receive(fid, {&packet,1}) == outcome, "Independent admission differs");
    }
    if (frame % 7 == 0) {
      const auto slot = static_cast<uint16_t>(next() % slots);
      window.RemoveSlot(slot);
      for (auto& [fid, entries] : expected) entries.erase(slot);
    }
    std::vector<fs::SlotInput> output(slots);
    for (uint16_t slot=0; slot<slots; ++slot)
      Require(window.Has(slot) == (expected.contains(frame) && expected.at(frame).contains(slot)),
              "Current readiness differs");
    window.Consume(output);
    for (uint16_t slot=0; slot<slots; ++slot) {
      const auto input = expected.contains(frame) && expected.at(frame).contains(slot)
          ? expected.at(frame).at(slot) : fs::SlotInput::Default();
      Require(Same(output[slot],input), "Authority frame input lost or overwritten");
    }
    expected.erase(frame);
    const std::pair<uint16_t,fs::SlotInput> late{0,fs::SlotInput::Default()};
    Require(window.Receive(frame,{&late,1}) == fs::InputAdmission::Stale,"Committed frame mutated");
  }
}
void Boundaries() {
  Throws<std::invalid_argument>([]{ fs::ServerInputWindow bad(0); });
  Throws<std::invalid_argument>([]{ fs::ServerInputWindow bad(23); });
  fs::ServerInputWindow window(2);
  std::array<std::pair<uint16_t,fs::SlotInput>,2> packet{{
    {0,{1,0,512}},{1,{0,0,0}}}};
  Require(window.Receive(0,packet)==fs::InputAdmission::Accepted,"Initial packet rejected");
  Require(window.Receive(0,packet)==fs::InputAdmission::Accepted,"Identical duplicate rejected");
  packet[0].second = {0,0,0}; packet[1].second = {1,0,0};
  Require(window.Receive(0,packet)==fs::InputAdmission::Conflict,"Conflicting packet accepted");
  std::array<fs::SlotInput,2> output;
  window.Consume(output);
  Require(Same(output[0],{1,0,512}) && Same(output[1],{0,0,0}),"Rejected packet partially changed state");
  packet[1].first=0;
  Require(window.Receive(1,packet)==fs::InputAdmission::Invalid,"Duplicate slots accepted");
  packet[1].first=2;
  Require(window.Receive(1,packet)==fs::InputAdmission::Invalid,"Foreign slot accepted");
  packet[1].first=1;packet[1].second.dir_x=std::numeric_limits<float>::quiet_NaN();
  Require(window.Receive(1,packet)==fs::InputAdmission::Invalid,"NaN accepted");
  window.Consume(output);
  Require(Same(output[0],{0,0,0}) && Same(output[1],{0,0,0}),"Invalid packet retained");
  Throws<std::out_of_range>([&]{ window.Has(2); });
  Throws<std::out_of_range>([&]{ window.RemoveSlot(2); });
  Throws<std::invalid_argument>([&]{ window.Consume(std::span<fs::SlotInput>(output.data(),1)); });
  fs::ServerInputWindow near(2,UINT32_MAX-1);
  packet[1].second={0,0,0};
  Require(near.Receive(UINT32_MAX,packet)==fs::InputAdmission::Accepted,"Valid near-wrap input rejected");
  near.Consume(output);
  Require(near.current()==UINT32_MAX,"Near-wrap frame differs");
  Throws<std::overflow_error>([&]{ near.Consume(output); });
  Require(near.current()==UINT32_MAX,"Rejected wrap changed frame");
  Require(sizeof(fs::ServerInputWindow)<=4096,"Fixed input window exceeds 4 KiB");
}
}
int main(int, char**) {
  try {
    Boundaries();for (size_t slots : {1u,2u,22u}) Run(slots);
    std::cout << "{\"passed\":true,\"skipped\":0,\"assertions\":" << assertions
              << ",\"frames\":18000,\"fixed_bytes\":" << sizeof(fs::ServerInputWindow)
              << ",\"actual_network\":false}\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
