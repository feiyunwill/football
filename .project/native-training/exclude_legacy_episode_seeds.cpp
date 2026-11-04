// Optional conservative exclusion corpus for the five documented training seeds.
// At most524288 transitions means at most524289 episode starts,including reset0.
// Excludes the whole RNG prefix rather than assuming unlogged episode counts.
#include "training/categorical_policy.hpp"
#include <array>
#include <fstream>
#include <iostream>
#include <stdexcept>
int main(int argc,char** argv){
  using namespace football::training;static_assert(kPolicyRngVersion==1);
  try{
    if(argc!=2)throw std::invalid_argument("NEW output.u32le");
    std::ofstream output(argv[1],std::ios::binary);if(!output)throw std::runtime_error("Cannot create exclusions");
    size_t count=0;
    for(uint64_t seed:std::array<uint64_t,5>{42,123,2026,31415,271828}){
      PolicyRng episodes(seed^UINT64_C(0x589965cc75374cc3));
      for(size_t i=0;i<524289;++i){
        const auto value=uint32_t(episodes.index(2000000001));
        for(int shift=0;shift<32;shift+=8)output.put(char(value>>shift));
        ++count;
      }
    }
    output.close();if(!output)throw std::runtime_error("Exclusion write failed");
    std::cout<<"{\"passed\":true,\"rng_version\":1,\"values\":"<<count<<",\"scope\":\"Conservative episode-stream prefixes for five fixed training seeds only\"}\n";
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
