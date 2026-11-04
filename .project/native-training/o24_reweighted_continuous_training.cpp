// One persistent learner for duration/resource acceptance. This is a copy-only
// stability experiment,not a new selected checkpoint or learning confirmation.
#include "training/ppo_learner.hpp"
#include "frame_sync/default_scenario.hpp"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <stdexcept>

int main(int argc,char** argv){
  using namespace football::training;
  try{
    if(argc!=5)throw std::invalid_argument("seed compatible-schema6-model NEW_OUTPUT_DIRECTORY seconds");
    const uint64_t seed=std::stoull(argv[1]);const double seconds=std::stod(argv[4]);
    if(!std::isfinite(seconds)||seconds<1||seconds>4000)throw std::invalid_argument("Invalid duration budget");
    const std::filesystem::path output(argv[3]);
    if(!std::filesystem::create_directory(output))throw std::invalid_argument("Output must be new");
    PpoLearnerConfig config;config.seed=seed;config.policy.hidden=64;config.parameters.epochs=4;config.parameters.minibatch=64;
    config.scenario=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*config.scenario);config.scenario->deterministic=true;
    config.scenario_variation=PpoScenarioVariation::TwoOnOneBroadReweighted;
    PpoLearner learner(config);learner.load(argv[2]);
    const auto initial_version=learner.version(),initial_transitions=learner.transitions(),initial_optimizer=learner.optimizer().step;
    if(initial_version!=8192 || initial_transitions!=8192*256 || initial_optimizer!=8192*16)
      throw std::runtime_error("Expected the real fully trained schema6 state,not derived inference weights");
    const auto start=std::chrono::steady_clock::now();double next_checkpoint=60,next_progress=0;size_t resumes=0,updates=0;
    auto elapsed=[&]{return std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();};
    std::cout<<std::setprecision(17);
    while(elapsed()<seconds){
      const auto iteration=learner.train(256);++updates;
      if(iteration.learning_rate!=config.parameters.learning_rate*.1)throw std::runtime_error("Schema6 annealed floor LR mismatch");
      if(!std::isfinite(iteration.update.loss)||!std::isfinite(iteration.update.entropy)||!std::isfinite(iteration.update.gradient_norm))
        throw std::runtime_error("Nonfinite persistent training update");
      if(elapsed()>=next_checkpoint){
        const auto checkpoint=output/("minute-"+std::to_string(resumes)+".fppo");
        learner.save(checkpoint);
        const auto saved=learner.get_state();
        {
          PpoLearner restored(config);restored.load(checkpoint);
          if(restored.get_state()!=saved)throw std::runtime_error("Disk checkpoint differs from full live state");
          const auto expected=learner.train(16),actual=restored.train(16);++updates;
          if(expected.trajectory_sha256!=actual.trajectory_sha256||expected.learning_rate!=config.parameters.learning_rate*.1||actual.learning_rate!=expected.learning_rate||learner.get_state()!=restored.get_state())
            throw std::runtime_error("Persistent learner continuation differs after full restore");
        }
        ++resumes;next_checkpoint=elapsed()+60;
      }
      if(elapsed()>=next_progress){
        std::cout<<"{\"progress\":true,\"seconds\":"<<elapsed()<<",\"version\":"<<learner.version()
          <<",\"transitions\":"<<learner.transitions()-initial_transitions<<",\"restore_checks\":"<<resumes<<"}\n"<<std::flush;
        next_progress=elapsed()+10;
      }
    }
    learner.save(output/"stability-only-final.fppo");
    const auto transitions=learner.transitions()-initial_transitions;const auto optimizer_steps=learner.optimizer().step-initial_optimizer;
    if(transitions==0||optimizer_steps==0||learner.version()<=initial_version)throw std::runtime_error("No real training progress");
    std::cout<<"{\"passed\":true,\"seconds\":"<<elapsed()<<",\"transitions\":"<<transitions<<",\"updates\":"<<updates
      <<",\"optimizer_steps\":"<<optimizer_steps<<",\"restore_checks\":"<<resumes
      <<",\"learning_rate_floor_verified\":true,\"duration_gate\":"<<(seconds>=3600&&elapsed()>=3600&&resumes>=50?"true":"false")<<"}\n";
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
