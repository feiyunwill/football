#include "training/ppo_learner.hpp"
#include "training/cooperation_metrics.hpp"
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <thread>
#include <set>
#include <cmath>
#include <array>
#include <source_location>
#include <unistd.h>
using namespace football::training;
void require(bool value,const std::source_location& at=std::source_location::current()) {
  if (!value) throw std::runtime_error("PPO checkpoint contract failed at line "+std::to_string(at.line()));
}
template<class F> void rejects(F action) { try { action(); } catch (const std::exception&) { return; } require(false); }
void seal(std::string& bytes) {
  frame_sync::SHA256 hash; hash.update(reinterpret_cast<const uint8_t*>(bytes.data()+44),bytes.size()-44);
  uint8_t checksum[32]; hash.finalize(checksum); std::memcpy(bytes.data()+12,checksum,32);
}
int main(int, char**) {
  try {
    {
      const auto annealed=PpoScenarioVariation::TwoOnOneBroadAnnealed;
      require(PpoPayloadSchema(annealed)==5);
      const auto reweighted=PpoScenarioVariation::TwoOnOneBroadReweighted;
      require(PpoPayloadSchema(reweighted)==6);
      const auto lowlr=PpoScenarioVariation::TwoOnOneBroadReweightedLowLr;
      require(PpoPayloadSchema(lowlr)==7);
      const auto midlr=PpoScenarioVariation::TwoOnOneBroadReweightedMidLr;
      require(PpoPayloadSchema(midlr)==8);
      const auto finisher=PpoScenarioVariation::TwoOnOneBroadReweightedFinisher;
      require(PpoPayloadSchema(finisher)==9);
      const auto balanced=PpoScenarioVariation::TwoOnOneBroadBalancedFinisher;
      require(PpoPayloadSchema(balanced)==10);
      const auto edge_balanced=PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher;
      require(PpoPayloadSchema(edge_balanced)==11);
      const auto entropy_stable=PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher;
      require(PpoPayloadSchema(entropy_stable)==12);
      const auto entropy_midpoint=PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher;
      require(PpoPayloadSchema(entropy_midpoint)==13);
      const auto entropy_high=PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher;
      require(PpoPayloadSchema(entropy_high)==14);
      const auto firststep_entropy=PpoScenarioVariation::TwoOnOneBroadFirstStepEntropyFinisher;
      require(PpoPayloadSchema(firststep_entropy)==15);
      for(uint64_t version:{UINT64_C(0),UINT64_C(4096),UINT64_C(7373),UINT64_C(8192),UINT64_C(1000000000000)})
        require(PpoEffectiveLearningRate(reweighted,version,.0003)==PpoEffectiveLearningRate(annealed,version,.0003));
      for(uint64_t version:{UINT64_C(0),UINT64_C(4096),UINT64_C(7373),UINT64_C(8192),UINT64_C(1000000000000)})
        require(PpoEffectiveLearningRate(lowlr,version,.0002)==PpoEffectiveLearningRate(annealed,version,.0002));
      for(uint64_t version:{UINT64_C(0),UINT64_C(4096),UINT64_C(7373),UINT64_C(8192),UINT64_C(1000000000000)})
        require(PpoEffectiveLearningRate(midlr,version,.00025)==PpoEffectiveLearningRate(annealed,version,.00025));
      for(uint64_t version:{UINT64_C(0),UINT64_C(4096),UINT64_C(7373),UINT64_C(8192),UINT64_C(1000000000000)})
        require(PpoEffectiveLearningRate(finisher,version,.0003)==PpoEffectiveLearningRate(annealed,version,.0003));
      for(uint64_t version:{UINT64_C(0),UINT64_C(4096),UINT64_C(7373),UINT64_C(8192),UINT64_C(1000000000000)})
        require(PpoEffectiveLearningRate(balanced,version,.0003)==PpoEffectiveLearningRate(annealed,version,.0003));
      for(uint64_t version:{UINT64_C(0),UINT64_C(4096),UINT64_C(7373),UINT64_C(8192),UINT64_C(1000000000000)})
        require(PpoEffectiveLearningRate(firststep_entropy,version,.0003)==PpoEffectiveLearningRate(annealed,version,.0003));
      require(PpoEffectiveLearningRate(annealed,0,.0003)==.0003);
      require(std::abs(PpoEffectiveLearningRate(annealed,4096,.0003)-.00015)<1e-18);
      require(PpoEffectiveLearningRate(annealed,7372,.0003)>.0003*.1);
      for(uint64_t version:{UINT64_C(7373),UINT64_C(8192),UINT64_C(1000000000000)})
        require(PpoEffectiveLearningRate(annealed,version,.0003)==.0003*.1);
      for(uint32_t variation=0;variation<5;++variation)
        for(uint64_t version:{UINT64_C(0),UINT64_C(4096),UINT64_C(8192)})
          require(PpoEffectiveLearningRate(static_cast<PpoScenarioVariation>(variation),version,.0003)==.0003);
      rejects([&]{PpoEffectiveLearningRate(annealed,0,0);});
      rejects([&]{PpoEffectiveLearningRate(static_cast<PpoScenarioVariation>(16),0,.0003);});
      for(uint32_t partition=0;partition<7;++partition)for(uint32_t seed=0;seed<100;++seed){
        auto original=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*original);auto other=*original;
        const auto a=ApplyPpoStart(*original,PpoScenarioVariation::TwoOnOneBroad,seed,static_cast<StartPartition>(partition));
        const auto b=ApplyPpoStart(other,annealed,seed,static_cast<StartPartition>(partition));
        require(a==b && original->ball_position==other.ball_position);
        auto balanced_scene=other;
        const auto c=ApplyPpoStart(balanced_scene,balanced,seed,static_cast<StartPartition>(partition));
        require(c==b && balanced_scene.ball_position==other.ball_position && balanced_scene.left_team[2].position==other.left_team[2].position && balanced_scene.right_team[1].position==other.right_team[1].position);
        auto weighted=other,again=other;
        const auto g=ApplyPpoStart(weighted,reweighted,seed,static_cast<StartPartition>(partition));
        require(g==ApplyPpoStart(again,reweighted,seed,static_cast<StartPartition>(partition)));
        require(weighted.ball_position==again.ball_position && weighted.left_team[2].position==again.left_team[2].position && weighted.right_team[1].position==again.right_team[1].position);
        if(g==b)require(weighted.ball_position==other.ball_position && weighted.left_team[2].position==other.left_team[2].position && weighted.right_team[1].position==other.right_team[1].position);
        require(original->left_team[1].position==other.left_team[1].position && original->left_team[2].position==other.left_team[2].position && original->right_team[1].position==other.right_team[1].position);
      }
    }
    {
      CooperationMetrics metrics;
      metrics.observe({0,1,1}); metrics.action({0,1,1},11);
      metrics.observe({-1,-1,1}); metrics.observe({0,2,1});
      require(metrics.pass_requests==1 && metrics.completed_passes==1 && metrics.teammate_transfers==1);
      metrics.action({0,2,1},11); require(metrics.pass_requests==1);
      metrics.observe({0,1,1}); metrics.action({0,1,1},9);
      metrics.observe({1,1,1}); metrics.observe({0,2,1});
      require(metrics.completed_passes==1 && metrics.turnovers==1);
      metrics.observe({0,1,1}); metrics.action({0,1,1},11);
      for(int i=0;i<31;++i) metrics.action({-1,-1,1},0);
      metrics.observe({0,2,1}); require(metrics.completed_passes==1);
      metrics.observe({0,1,1});metrics.action({0,1,1},11);metrics.observe({0,0,1});
      require(metrics.completed_passes==1); // Goalkeeper reception does not meet2v1 cooperation.
      ObservationBuffer raw(1,115);std::fill(raw.buffer().begin(),raw.buffer().end(),-1.f);
      std::array<uint8_t,10> sticky{};sticky[4]=sticky[8]=1;
      auto first=CooperationObservation(raw,false,sticky),second=CooperationObservation(raw,true,sticky);
      require(first.buffer()[21]==-1 && second.buffer()[21]==1 && raw.buffer()[21]==-1);
      for(size_t i=0;i<115;++i) if(i!=21 && (i<28 || i>=38)) require(first.buffer()[i]==raw.buffer()[i] && second.buffer()[i]==raw.buffer()[i]);
      for(size_t i=0;i<10;++i) require(first.buffer()[28+i]==sticky[i] && second.buffer()[28+i]==sticky[i]);
      ObservationBuffer joint(2,115);std::fill(joint.buffer().begin(),joint.buffer().end(),7.f);
      std::copy(raw.buffer().begin(),raw.buffer().end(),joint.buffer().begin());
      require(PrimaryCooperationObservation(joint)==raw && CooperationObservation(joint,true,sticky)==second);
      require(CooperativeReward(1,0,0)==1 && CooperativeReward(0,0,1)==2 &&
              CooperativeReward(0,1,2)==0 && CooperativeReward(1,1,1)==1 &&
              CooperativeReward(-1,0,0)==-1 && CooperativeReward(1,0,0,1)==1 &&
              CooperativeReward(1,1,1,1)==3 && CooperativeReward(1,0,1,1)==5 &&
              CooperativeReward(-1,1,1,-1)==-1 && CooperativeReward(.1,1,1,0)==.1);
      metrics.observe({0,1,1}); metrics.action({0,1,1},11); metrics.action({0,1,1},12);
      metrics.observe({0,2,1}); require(metrics.completed_passes==1);
    }
    {
      constexpr int partitions=uint32_t(StartPartition::Holdout)+1;
      std::set<std::pair<float,float>> starts[partitions];
      for(uint32_t part=0;part<partitions;++part) for(uint32_t seed=0;seed<500;++seed) {
        auto scene=frame_sync::MakeDefaultScenario(1,0,42); ConfigureTwoOnOne(*scene);
        auto same=*scene;
        auto a=ApplyPpoStart(*scene,PpoScenarioVariation::TwoOnOne,seed,static_cast<StartPartition>(part));
        auto b=ApplyPpoStart(same,PpoScenarioVariation::TwoOnOne,seed,static_cast<StartPartition>(part));
        require(a==b && scene->ball_position==same.ball_position && a<12);
        require(scene->ControllableLeftPlayers()==2 && scene->left_team[1].controllable && !scene->left_team[2].lazy);
        starts[part].insert({scene->ball_position.coords[0],scene->ball_position.coords[1]});
      }
      for(int i=0;i<partitions;++i) {
        require(starts[i].size()==12);
        for(int j=i+1;j<partitions;++j) for(auto point:starts[i]) require(!starts[j].contains(point));
      }
    }
    {
      auto scene=frame_sync::MakeDefaultScenario(2,0,42);ConfigureTwoOnOne(*scene);
      NativeTrainingEnv env(160,90,true);env.reset(*scene,10);
      const auto before=env.get_state();(void)env.sticky_actions();require(before==env.get_state());
      env.step(std::array<int,2>{13,19});require(env.sticky_actions()[8]==1);
      env.step(std::array<int,2>{15,19});require(env.sticky_actions()[8]==0);
      env.step(std::array<int,2>{17,19});require(env.sticky_actions()[9]==1);
      env.step(std::array<int,2>{18,19});require(env.sticky_actions()[9]==0);
      env.step(std::array<int,2>{5,19});auto held=env.sticky_actions();require(held[4]==1);
      const auto saved=env.get_state();env.step(std::array<int,2>{14,19});
      auto released=env.sticky_actions();for(int i=0;i<8;++i) require(released[i]==0);
      env.set_state(saved);require(env.sticky_actions()==held && env.get_state()==saved);
    }
    {
      auto scene=frame_sync::MakeDefaultScenario(2,0,42);ConfigureTwoOnOne(*scene);
      scene->ball_position=blunted::Vector3(.67f,.14f,0);
      NativeTrainingEnv env(160,90,true);auto observed=env.reset(*scene,10);
      require(observed.size()==2 && observed.buffer()[98]==1 && observed.buffer()[115+99]==1);
      bool received=false,moved=false;
      const float x=observed.buffer()[88],y=observed.buffer()[89];
      for(int i=0;i<128;++i) {
        auto step=env.step(std::array<int,2>{0,19});auto owner=env.possession();
        require(owner.controlled_player==1);
        received=received || (owner.team==0 && owner.player==2);
        if(received && std::hypot(step.observations.buffer()[88]-x,step.observations.buffer()[89]-y)>.04) moved=true;
        if(step.terminated) break;
      }
      require(received && moved); // The fixed teammate must act after receiving, not freeze.
    }
    std::set<std::pair<float,float>> partitions[4];
    for(uint32_t part=0;part<4;++part) for(uint32_t seed=0;seed<500;++seed) {
      auto scene=frame_sync::MakeDefaultScenario(1,0,42);
      scene->left_team={FormationEntry(-1,0,e_PlayerRole_GK,false,true),FormationEntry(.75f,0,e_PlayerRole_CB,false,true)};
      scene->right_team={FormationEntry(1,0,e_PlayerRole_GK,true,true)};
      auto duplicate=*scene;
      auto a=ApplyPpoStart(*scene,PpoScenarioVariation::EmptyGoal,seed,static_cast<StartPartition>(part));
      auto b=ApplyPpoStart(duplicate,PpoScenarioVariation::EmptyGoal,seed,static_cast<StartPartition>(part));
      require(a==b && a<12 && scene->ball_position==duplicate.ball_position);
      partitions[part].insert({scene->ball_position.coords[0],scene->ball_position.coords[1]});
    }
    for(int i=0;i<4;++i) {
      require(partitions[i].size()==12);
      for(int j=i+1;j<4;++j) for(auto point:partitions[i]) require(!partitions[j].contains(point));
    }
    for(auto variation:{PpoScenarioVariation::TwoOnOneBroad,PpoScenarioVariation::TwoOnOneBroadReweighted,PpoScenarioVariation::TwoOnOneBroadReweightedLowLr,PpoScenarioVariation::TwoOnOneBroadReweightedMidLr,PpoScenarioVariation::TwoOnOneBroadReweightedFinisher,PpoScenarioVariation::TwoOnOneBroadBalancedFinisher,PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher,PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher,PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher,PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher}) {
      std::set<std::pair<float,float>> positions;size_t legacy=0;std::array<size_t,5> families{};
      for(uint32_t seed=0;seed<5000;++seed) {
        auto scene=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*scene);auto duplicate=*scene;
        const auto group=ApplyPpoStart(*scene,variation,seed);
        require(group==ApplyPpoStart(duplicate,variation,seed));
        require(scene->ball_position==duplicate.ball_position && scene->left_team[2].position==duplicate.left_team[2].position && scene->right_team[1].position==duplicate.right_team[1].position);
        positions.insert({scene->ball_position.coords[0],scene->ball_position.coords[1]});
        if(group>=5){
          ++legacy;require(group<17);
          auto original=duplicate;const auto index=ApplyPpoStart(original,PpoScenarioVariation::TwoOnOne,seed);
          require(group==index+5 && original.ball_position==scene->ball_position && original.left_team[2].position==scene->left_team[2].position);
        }else{
          ++families[group];const auto& a=scene->left_team[1].position;const auto& t=scene->left_team[2].position;const auto& d=scene->right_team[1].position;
          const float ay=a.coords[1]/FORMATION_Y_SCALE,ty=t.coords[1]/FORMATION_Y_SCALE,dy=d.coords[1]/FORMATION_Y_SCALE;
          require(a.coords[0]>=.27999f && a.coords[0]<=.68001f && std::abs(ay)<=.34001f);
          require(t.coords[0]>a.coords[0] && t.coords[0]<=.89001f && std::abs(ty)<=.32001f);
          require(d.coords[0]>a.coords[0] && d.coords[0]<=.88001f && std::abs(dy)<=.15001f);
          if(group==1)require(a.coords[0]<=.44001f);
          if(group==2)require(std::abs(ay)>=.21999f);
          if(group==3)require(d.coords[0]-a.coords[0]<=.12001f);
          if(group==4)require(std::abs(ty-ay)>=.07999f);
        }
      }
      require(legacy>750 && legacy<1250 && positions.size()>3000);
      if(variation==PpoScenarioVariation::TwoOnOneBroad || variation==PpoScenarioVariation::TwoOnOneBroadBalancedFinisher || variation==PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher || variation==PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher || variation==PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher) {
        for(auto count:families)require(count>600 && count<1000);
      } else if(variation==PpoScenarioVariation::TwoOnOneBroadReweightedFinisher) {
        require(families[4]>2750 && families[4]<3250);
        for(size_t g=0;g<4;++g)require(families[g]>150 && families[g]<350);
      } else if(variation==PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher) {
        for(size_t g=0;g<4;++g)require(families[g]>500 && families[g]<850);
        require(families[4]>850 && families[4]<1150);
      } else {
        require(families[4]>1750 && families[4]<2250);
        for(size_t g=0;g<4;++g)require(families[g]>350 && families[g]<650);
      }
    }
    for(auto variation:{PpoScenarioVariation::EmptyGoal,PpoScenarioVariation::Keeper,PpoScenarioVariation::TwoOnOne,PpoScenarioVariation::TwoOnOneBroad,PpoScenarioVariation::TwoOnOneBroadAnnealed,PpoScenarioVariation::TwoOnOneBroadReweighted,PpoScenarioVariation::TwoOnOneBroadReweightedLowLr,PpoScenarioVariation::TwoOnOneBroadReweightedMidLr,PpoScenarioVariation::TwoOnOneBroadReweightedFinisher,PpoScenarioVariation::TwoOnOneBroadBalancedFinisher,PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher,PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher,PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher,PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher}) {
      PpoLearnerConfig c; c.policy.hidden=3;c.episode_limit=3;c.cadence=2;c.parameters.epochs=1;c.parameters.minibatch=4;
      if(variation==PpoScenarioVariation::TwoOnOneBroadReweightedLowLr)c.parameters.learning_rate=.0002;
      if(variation==PpoScenarioVariation::TwoOnOneBroadReweightedMidLr)c.parameters.learning_rate=.00025;
      if(variation==PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher)c.parameters.entropy_coefficient=.02;
      if(variation==PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher)c.parameters.entropy_coefficient=.015;
      if(variation==PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher)c.parameters.entropy_coefficient=.025;
      c.scenario=frame_sync::MakeDefaultScenario(1,0,42);
      c.scenario->left_team={FormationEntry(-1,0,e_PlayerRole_GK,false,true),FormationEntry(.75f,0,e_PlayerRole_CB,false,true)};
      c.scenario->right_team={FormationEntry(1,variation==PpoScenarioVariation::EmptyGoal ? .6f : 0.f,e_PlayerRole_GK,variation==PpoScenarioVariation::EmptyGoal,true)};
      if(IsCooperativeVariation(variation)) ConfigureTwoOnOne(*c.scenario);
      c.scenario_variation=variation;
      PpoLearner a(c),b(c);const auto initial_update=a.train(4);auto checkpoint=a.get_state();b.set_state(checkpoint);
      require(initial_update.learning_rate==c.parameters.learning_rate);
      if(IsCooperativeVariation(variation)) {
        auto malformed=checkpoint; malformed[44]=2;seal(malformed);
        auto before=b.get_state();rejects([&]{b.set_state(malformed);});require(before==b.get_state());
        malformed=checkpoint;malformed[malformed.size()-40]=char(255);seal(malformed);
        rejects([&]{b.set_state(malformed);});require(before==b.get_state());
      }
      auto first=a.train(7),second=b.train(7);
      require(first.learning_rate==second.learning_rate);
      if(IsAnnealedVariation(variation))require(first.learning_rate<initial_update.learning_rate);
      else require(first.learning_rate==initial_update.learning_rate);
      if(IsCooperativeVariation(variation)) require(first.completed_episodes==first.finishing_practice_episodes+first.cooperative_episodes);
      require(first.trajectory_sha256==second.trajectory_sha256 && a.get_state()==b.get_state());
      auto fixed=c;fixed.scenario_variation=PpoScenarioVariation::Fixed;
      if(IsCooperativeVariation(variation)) fixed.scenario=frame_sync::MakeDefaultScenario(1,0,42);
      PpoLearner incompatible(fixed);
      auto before=incompatible.get_state();rejects([&]{incompatible.set_state(checkpoint);});require(before==incompatible.get_state());
      if(IsCooperativeVariation(variation)) {
        auto other=c;other.scenario_variation=variation==PpoScenarioVariation::TwoOnOne ? PpoScenarioVariation::TwoOnOneBroad : PpoScenarioVariation::TwoOnOne;
        PpoLearner wrong_task(other);const auto saved=wrong_task.get_state();
        rejects([&]{wrong_task.set_state(checkpoint);});require(saved==wrong_task.get_state());
      }
      if(IsAnnealedVariation(variation)){
        auto other=c;other.scenario_variation=variation==PpoScenarioVariation::TwoOnOneBroadReweightedFinisher ? PpoScenarioVariation::TwoOnOneBroadReweightedMidLr : (variation==PpoScenarioVariation::TwoOnOneBroadReweightedLowLr || variation==PpoScenarioVariation::TwoOnOneBroadReweightedMidLr) ? PpoScenarioVariation::TwoOnOneBroadReweighted : variation==PpoScenarioVariation::TwoOnOneBroadReweighted ? PpoScenarioVariation::TwoOnOneBroadAnnealed : PpoScenarioVariation::TwoOnOneBroad;PpoLearner wrong_task(other);
        const auto unchanged=wrong_task.get_state();rejects([&]{wrong_task.set_state(checkpoint);});require(unchanged==wrong_task.get_state());
        const auto current=a.get_state();rejects([&]{a.set_state(unchanged);});require(current==a.get_state());
      }
    }
    {
      PpoLearnerConfig c;c.policy.hidden=3;c.parameters.epochs=1;c.parameters.minibatch=16;
      c.scenario=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*c.scenario);
      c.scenario_variation=PpoScenarioVariation::TwoOnOne;
      PpoLearner a(c),b(c);std::string checkpoint;bool passed=false;
      for(int i=0;i<64 && !passed;++i) {
        a.train(64);checkpoint=a.get_state();
        uint64_t completions=0;for(int j=0;j<8;++j) completions|=uint64_t(uint8_t(checkpoint[checkpoint.size()-40+j]))<<(8*j);
        passed=completions>0;
      }
      require(passed); // Exercise an actual post-pass phase, not only a reset flag.
      b.set_state(checkpoint);auto first=a.train(7),second=b.train(7);
      require(first.trajectory_sha256==second.trajectory_sha256 && a.get_state()==b.get_state());
    }
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
