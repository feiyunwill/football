#include "training/ppo_learner.hpp"
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <thread>
#include <unistd.h>
using namespace football::training;
void require(bool value) { if (!value) throw std::runtime_error("PPO checkpoint contract failed"); }
template<class F> void rejects(F action) { try { action(); } catch (const std::exception&) { return; } require(false); }
void seal(std::string& bytes) {
  frame_sync::SHA256 hash; hash.update(reinterpret_cast<const uint8_t*>(bytes.data()+44),bytes.size()-44);
  uint8_t checksum[32]; hash.finalize(checksum); std::memcpy(bytes.data()+12,checksum,32);
}
int main(int, char**) {
  try {
    for (bool stacked : {false,true}) {
      PpoLearnerConfig config;
      config.policy={stacked ? size_t{2} : size_t{1},stacked ? size_t{460} : size_t{115},3,!stacked,stacked};
      config.parameters.epochs=2; config.parameters.minibatch=4;
      config.scenario=frame_sync::MakeDefaultScenario(stacked?0:1,stacked?2:0,42);
      config.scenario->game_duration=50; config.episode_limit=7; config.cadence=2; config.checkpoint_rewards=stacked;
      PpoLearner baseline(config), restored(config);
      require(baseline.get_state()==restored.get_state());
      auto first=baseline.train(8); require(first.update.parameter_delta>0 && baseline.version()==1);
      const auto checkpoint=baseline.get_state();
      restored.set_state(checkpoint); require(restored.get_state()==checkpoint);
      auto a=baseline.train(9),b=restored.train(9);
      require(a.trajectory_sha256==b.trajectory_sha256 && a.reward==b.reward &&
              a.update.parameter_delta==b.update.parameter_delta && baseline.get_state()==restored.get_state());
      const auto before=restored.get_state();
      auto malformed=before; malformed[0]='X'; rejects([&] {restored.set_state(malformed);});
      malformed=before; malformed.back()^=1; rejects([&] {restored.set_state(malformed);});
      rejects([&] {restored.set_state(std::string_view(before).substr(0,before.size()-1));});
      malformed=before; malformed[56]=0; malformed[57]=0; malformed[58]=0; malformed[59]=0;
      seal(malformed); rejects([&] {restored.set_state(malformed);}); // invalid players with a valid checksum
      // Corrupt the duplicated observation but reseal: late staging restore must not change target.
      malformed=before; const size_t observation_offset=malformed.size()-8-config.policy.inputs()*4;
      malformed[observation_offset]^=1; seal(malformed); rejects([&] {restored.set_state(malformed);});
      require(restored.get_state()==before);
      auto changed=config; changed.seed=43; PpoLearner incompatible(changed);
      const auto foreign=incompatible.get_state(); rejects([&] {incompatible.set_state(checkpoint);});
      require(incompatible.get_state()==foreign);
      const auto folder=std::filesystem::temp_directory_path()/ ("football-ppo-checkpoint-"+std::to_string(getpid()));
      std::filesystem::create_directory(folder);
      const auto path=folder/"state.bin";
      baseline.save(path); restored.load(path); require(restored.get_state()==baseline.get_state());
      rejects([&] {baseline.save(folder);});
      require(std::filesystem::is_regular_file(path));
      const auto link=folder/"link.bin"; std::filesystem::create_symlink(path,link);
      const auto before_link=restored.get_state(); rejects([&] {restored.load(link);});
      require(restored.get_state()==before_link); std::filesystem::remove(link);
      { std::ofstream output(path,std::ios::binary|std::ios::trunc); output << "bad"; }
      const auto target=restored.get_state(); rejects([&] {restored.load(path);}); require(restored.get_state()==target);
      std::filesystem::remove(path); std::filesystem::remove(folder);
      bool rejected=false;
      std::thread thread([&] {try {restored.train(1);} catch (const std::logic_error&) {rejected=true;}});
      thread.join(); require(rejected && restored.get_state()==target);
      auto detached=restored.config(); detached.scenario->game_duration=1;
      require(restored.config().scenario->game_duration==50);
    }
    std::printf("{\"passed\":true,\"real_update_resume_modes\":2}\n"); return 0;
  } catch (const std::exception& error) {std::fprintf(stderr,"%s\n",error.what()); return 1;}
}
