// Candidate container semantics at the complete accepted snapshot size boundary.
// This probe does not replace real engine snapshot/trajectory contracts.
#include <boost/circular_buffer.hpp>
#include <algorithm>
#include <cassert>
#include <iostream>
#include <list>

int main() {
  for (size_t count : {0u, 1u, 400u, 401u, 999u, 1000u}) {
    std::list<int> reference;
    boost::circular_buffer<int> candidate(1001);
    reference.resize(count); candidate.resize(count);
    int item = 0;
    for (auto& value : reference) value = item++;
    item = 0;
    for (auto& value : candidate) value = item++;
    for (int tick = 0; tick < 3000; ++tick) {
      reference.push_back(tick); candidate.push_back(tick);
      if (reference.size() > 401) reference.pop_front();
      if (candidate.size() > 401) candidate.pop_front();
      for (auto& value : reference) value = -value;
      for (auto part : {candidate.array_one(), candidate.array_two()})
        for (size_t i = 0; i < part.second; ++i) part.first[i] = -part.first[i];
      assert(reference.size() == candidate.size());
      assert(std::equal(reference.begin(), reference.end(), candidate.begin()));
      assert(std::equal(reference.rbegin(), reference.rend(), candidate.rbegin()));
    }
  }
  std::cout << "6 restored sizes x 3000 push/pop/mirror checks passed\n";
}
