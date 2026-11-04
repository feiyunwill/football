// Actual PpoLearner duration/resource check for the fixed-AI teammate task.
#include "training/ppo_learner.hpp"
#include "frame_sync/default_scenario.hpp"
#include <chrono>
#include <cstdio>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <unistd.h>
using namespace football::training;
using Clock=std::chrono::steady_clock;
size_t fds() {
  size_t count=0;for(const auto& entry:std::filesystem::directory_iterator("/proc/self/fd")) { (void)entry;++count; }return count;
}
size_t rss() {
  size_t size=0,resident=0;std::ifstream in("/proc/self/statm");in>>size>>resident;
  if(!in) throw std::runtime_error("Cannot read native RSS");return resident*size_t(sysconf(_SC_PAGESIZE));
}
int main(int argc,char** argv) {
  try {
    if(argc!=4) return 2;
    const int requested=std::stoi(argv[1]);if(requested<1 || requested>3600) return 2;
    const std::filesystem::path output=argv[2];const bool checkpoints=std::string(argv[3])=="1";
    PpoLearnerConfig config;config.seed=424242;config.policy.hidden=64;
    config.parameters.epochs=4;config.parameters.minibatch=64;config.checkpoint_rewards=checkpoints;
    config.scenario=frame_sync::MakeDefaultScenario(2,0,42);ConfigureTwoOnOne(*config.scenario);
    config.scenario->deterministic=true;config.scenario_variation=PpoScenarioVariation::TwoOnOne;
    std::ofstream samples(output/"minute.jsonl");if(!samples) throw std::runtime_error("Cannot create samples");
    // Prime process-global engine caches, then compare the same warmed FD baseline.
    {PpoLearner prime(config);for(int i=0;i<4;++i) prime.train(256);}
    const size_t fd_before=fds();size_t fd_after=0,updates=0,transitions=0,practice=0,full=0;
    double duration=0,cpu=0,last=0,next=60;size_t previous=0;
    {
      PpoLearner learner(config);const auto start=Clock::now();const auto cpu_start=std::clock();
      do {
        auto update=learner.train(256);++updates;transitions+=update.transitions;
        practice+=update.finishing_practice_episodes;full+=update.cooperative_episodes;
        duration=std::chrono::duration<double>(Clock::now()-start).count();
        if(duration>=next || duration>=requested) {
          const auto memory=rss(),descriptors=fds();const double rate=(transitions-previous)/(duration-last);
          samples<<std::setprecision(17)<<"{\"elapsed\":"<<duration<<",\"updates\":"<<updates
              <<",\"transitions\":"<<transitions<<",\"tps\":"<<rate<<",\"rss\":"<<memory
              <<",\"fds\":"<<descriptors<<",\"practice_episodes\":"<<practice<<",\"cooperative_episodes\":"<<full<<"}\n";
          samples.flush();if(!samples) throw std::runtime_error("Cannot flush native samples");
          std::printf("{\"elapsed\":%.3f,\"updates\":%zu,\"tps\":%.3f,\"rss\":%zu,\"fds\":%zu}\n",duration,updates,rate,memory,descriptors);std::fflush(stdout);
          previous=transitions;last=duration;next+=60;
        }
      } while(duration<requested);
      cpu=double(std::clock()-cpu_start)/CLOCKS_PER_SEC;
      learner.save(output/"final.fppo");
      learner.train(256);learner.save(output/"expected-resume.fppo");
    }
    fd_after=fds();const bool passed=duration>=requested && updates>0 && transitions==updates*256 && fd_before==fd_after;
    std::ofstream report(output/"native.json");report<<std::setprecision(17)
       <<"{\"passed\":"<<(passed?"true":"false")<<",\"requested_seconds\":"<<requested
       <<",\"duration_seconds\":"<<duration<<",\"updates\":"<<updates<<",\"transitions\":"<<transitions
       <<",\"transitions_per_second\":"<<transitions/duration<<",\"cpu_seconds\":"<<cpu
       <<",\"fd_before\":"<<fd_before<<",\"fd_after\":"<<fd_after<<",\"priming_transitions\":1024"
       <<",\"practice_episodes\":"<<practice<<",\"cooperative_episodes\":"<<full
       <<",\"seed\":424242,\"hidden\":64,\"players\":1,\"native_agents\":2,\"rollout\":256"
       <<",\"epochs\":4,\"minibatch\":64,\"cadence\":10,\"episode_limit\":256"
       <<",\"checkpoint_rewards\":"<<(checkpoints?"true":"false")<<"}\n";
    report.close();if(!report) throw std::runtime_error("Cannot write native report");
    return passed ? 0 : 1;
  } catch(const std::exception& error) {std::fprintf(stderr,"%s\n",error.what());return 1;}
}
