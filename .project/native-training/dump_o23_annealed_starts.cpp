// Reconstruct the deterministic episode-keyed geometry stream. The Python
// runner conservatively requests completed_episodes+1,possibly one unused start.
#include "training/scenario_sampling.hpp"
#include "frame_sync/default_scenario.hpp"
#include <charconv>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string_view>
uint64_t number(std::string_view s){uint64_t n;auto p=std::from_chars(s.data(),s.data()+s.size(),n);if(p.ec!=std::errc{}||p.ptr!=s.data()+s.size())throw std::invalid_argument("Invalid counter");return n;}
int main(int argc,char** argv){
  using namespace football::training;
  try{
    if(argc!=4)throw std::invalid_argument("variation seed conservative-episode-count");
    const auto value=number(argv[1]),seed=number(argv[2]),count=number(argv[3]);
    if(value!=5||count<1||count>2097153)throw std::invalid_argument("Invalid reconstruction budget");
    PolicyRng episodes(seed^UINT64_C(0x589965cc75374cc3));std::cout<<std::setprecision(17);
    for(size_t i=0;i<count;++i){
      auto scene=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*scene);scene->deterministic=true;
      scene->game_engine_random_seed=uint32_t(episodes.index(2000000001));
      const auto group=ApplyPpoStart(*scene,static_cast<PpoScenarioVariation>(value),scene->game_engine_random_seed);
      std::cout<<"{\"episode\":"<<i<<",\"engine_seed\":"<<scene->game_engine_random_seed<<",\"start_index\":"<<group<<",\"geometry\":[";
      const auto& a=scene->left_team[1].position;const auto& t=scene->left_team[2].position;const auto& d=scene->right_team[1].position;
      bool comma=false;for(float x:{a.coords[0],a.coords[1],t.coords[0],t.coords[1],d.coords[0],d.coords[1]}){std::cout<<(comma?",":"")<<x;comma=true;}
      std::cout<<"],\"formation_y_scale\":"<<FORMATION_Y_SCALE<<",\"ball\":["<<scene->ball_position.coords[0]<<','<<scene->ball_position.coords[1]<<"]}\n";
    }
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
