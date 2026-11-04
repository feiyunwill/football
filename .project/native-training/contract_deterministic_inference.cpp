#include "deterministic_inference.hpp"
#include <iostream>
#include <vector>

void require(bool ok) {if(!ok)throw std::runtime_error("Inference controller contract failed");}
int main() {
  try {
    for(const std::string mode:{"balanced","repeat8"}) {
      DeterministicInference original(mode),restored(mode);
      auto probabilities=[](int step) {
        std::array<double,19> p{};p[5]=step<40?.7:.1;p[13]=step<40?.2:.7;p[11]=1-p[5]-p[13];return p;
      };
      for(int i=0;i<37;++i)original.choose(probabilities(i));
      const auto saved=original.get_state();
      for(int i=37;i<60;++i)restored.choose(probabilities(i));
      restored.set_state(saved);require(saved==restored.get_state());
      for(int i=37;i<200;++i)require(original.choose(probabilities(i))==restored.choose(probabilities(i)));
      const auto before=restored.get_state();
      for(const std::string bad:std::array<std::string,4>{"bad",before+" trailing","DIC1 wrong 0 -1 0",std::string(4097,'a')}) {
        bool rejected=false;try{restored.set_state(bad);}catch(const std::invalid_argument&){rejected=true;}
        require(rejected && restored.get_state()==before);
      }
      std::array<double,19> invalid{};invalid[0]=.5;
      bool rejected=false;try{restored.choose(invalid);}catch(const std::invalid_argument&){rejected=true;}
      require(rejected && restored.get_state()==before);
    }
    // Repeated identical probabilities must retain minority actions without RNG.
    DeterministicInference balanced("balanced");std::array<double,19> p{};p[5]=.8;p[11]=.2;
    std::array<int,19> counts{};for(int i=0;i<100;++i)++counts[balanced.choose(p)];
    require(counts[5]==80 && counts[11]==20);
    DeterministicInference guarded("repeat8");
    for(int i=0;i<8;++i)require(guarded.choose(p)==5);require(guarded.choose(p)==11);
    std::cout<<"{\"passed\":true,\"serialized_continuations\":2,\"rng_used\":false}\n";
    return 0;
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
