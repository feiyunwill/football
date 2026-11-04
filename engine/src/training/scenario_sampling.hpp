#pragma once
#include "main.hpp"
#include "training/categorical_policy.hpp"
#include <stdexcept>
#include <cmath>
#include <algorithm>
namespace football::training {
enum class PpoScenarioVariation : uint32_t { Fixed=0, EmptyGoal=1, Keeper=2, TwoOnOne=3, TwoOnOneBroad=4, TwoOnOneBroadAnnealed=5, TwoOnOneBroadReweighted=6, TwoOnOneBroadReweightedLowLr=7, TwoOnOneBroadReweightedMidLr=8, TwoOnOneBroadReweightedFinisher=9, TwoOnOneBroadBalancedFinisher=10, TwoOnOneBroadEdgeBalancedFinisher=11, TwoOnOneBroadEntropyStableFinisher=12, TwoOnOneBroadEntropyMidpointFinisher=13, TwoOnOneBroadEntropyHighFinisher=14, TwoOnOneBroadFirstStepEntropyFinisher=15 };
inline bool IsCooperativeVariation(PpoScenarioVariation value) {
  return value==PpoScenarioVariation::TwoOnOne || value==PpoScenarioVariation::TwoOnOneBroad || value==PpoScenarioVariation::TwoOnOneBroadAnnealed || value==PpoScenarioVariation::TwoOnOneBroadReweighted || value==PpoScenarioVariation::TwoOnOneBroadReweightedLowLr || value==PpoScenarioVariation::TwoOnOneBroadReweightedMidLr || value==PpoScenarioVariation::TwoOnOneBroadReweightedFinisher || value==PpoScenarioVariation::TwoOnOneBroadBalancedFinisher || value==PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher || value==PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher || value==PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher || value==PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher || value==PpoScenarioVariation::TwoOnOneBroadFirstStepEntropyFinisher;
}
inline bool IsAnnealedVariation(PpoScenarioVariation value) {
  return value==PpoScenarioVariation::TwoOnOneBroadAnnealed || value==PpoScenarioVariation::TwoOnOneBroadReweighted || value==PpoScenarioVariation::TwoOnOneBroadReweightedLowLr || value==PpoScenarioVariation::TwoOnOneBroadReweightedMidLr || value==PpoScenarioVariation::TwoOnOneBroadReweightedFinisher || value==PpoScenarioVariation::TwoOnOneBroadBalancedFinisher || value==PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher || value==PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher || value==PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher || value==PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher || value==PpoScenarioVariation::TwoOnOneBroadFirstStepEntropyFinisher;
}

// One controllable attacker, one engine-AI teammate, a defender and a keeper.
// Goalkeepers are roster requirements and are not included in the 2v1 count.
inline void ConfigureTwoOnOne(ScenarioConfig& scene) {
  scene.left_agents=2; scene.right_agents=0;
  scene.left_team={FormationEntry(-1,0,e_PlayerRole_GK,false,false),
                   FormationEntry(.5f,-.14f,e_PlayerRole_CF,false,true),
                   FormationEntry(.65f,.14f,e_PlayerRole_CF,false,true)};
  scene.right_team={FormationEntry(1,0,e_PlayerRole_GK,false,false),
                    FormationEntry(.66f,0,e_PlayerRole_CB,false,false)};
  scene.ball_position=blunted::Vector3(.52f,-.14f,0);
  scene.game_duration=600; scene.offsides=false;
  scene.end_episode_on_score=true; scene.end_episode_on_out_of_play=true;
  scene.end_episode_on_possession_change=true;
}
enum class StartPartition : uint32_t { Train=0, Validation=1, Test=2, Confirmation=3, Replication=4, Prospective=5, Holdout=6 };
// Disjoint finite geometry sets; the episode seed samples a start independently
// of policy/action RNG. This function consumes no learner RNG state.
inline uint32_t ApplyPpoStart(ScenarioConfig& scene, PpoScenarioVariation variation,
                             uint32_t seed, StartPartition partition=StartPartition::Train) {
  if (uint32_t(variation)>15 || uint32_t(partition)>uint32_t(StartPartition::Holdout))
    throw std::invalid_argument("Unknown PPO scenario variation/partition");
  if (variation==PpoScenarioVariation::Fixed) return 0;
  if (IsCooperativeVariation(variation)) {
    if(scene.left_agents!=2 || scene.right_agents!=0 || scene.left_team.size()!=3 || scene.right_team.size()!=2)
      throw std::invalid_argument("2v1 requires learner/fixed-AI slots and3/2 rosters");
    if(variation==PpoScenarioVariation::TwoOnOneBroad || IsAnnealedVariation(variation)) {
      // Versioned broad80 sampler.20% legacy points,80% five continuous families.
      // The RNG is episode-keyed; restoring the same engine seed recreates geometry.
      PolicyRng broad(uint64_t(seed)^UINT64_C(0xbb67ae8584caa73b)^
                      (uint64_t(partition)*UINT64_C(0x9e3779b97f4a7c15)));
      if(broad.index(5)==0)return 5+ApplyPpoStart(scene,PpoScenarioVariation::TwoOnOne,seed,partition);
      // Schema6 changes only family exposure:20% legacy,40% family4,
      //10% each other family. Prior tasks retain the exact index(5) stream.
      const auto group=variation==PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher
        ? [&]{const auto pick=static_cast<uint32_t>(broad.index(16));return pick<4 ? 4u : (pick-4u)%4u;}()
        : variation==PpoScenarioVariation::TwoOnOneBroadReweightedFinisher
        ? std::min<uint32_t>(4,static_cast<uint32_t>(broad.index(16)))
        : (variation==PpoScenarioVariation::TwoOnOneBroadReweighted || variation==PpoScenarioVariation::TwoOnOneBroadReweightedLowLr || variation==PpoScenarioVariation::TwoOnOneBroadReweightedMidLr)
          ? std::min<uint32_t>(4,static_cast<uint32_t>(broad.index(8)))
          : static_cast<uint32_t>(broad.index(5));
      auto uniform=[&](double lo,double hi){return lo+(hi-lo)*broad.uniform();};
      double ax=uniform(.44,.68),ay=uniform(-.22,.22),gap=uniform(.12,.20);
      if(group==1)ax=uniform(.28,.44);
      if(group==2)ay=(broad.index(2)==0?-1:1)*uniform(.22,.34);
      if(group==3)gap=uniform(.06,.12);
      double tx=ax+uniform(.08,.18),ty=(ay>0?-1:1)*uniform(.12,.26);
      if(group==4){
        tx=ax+uniform(.025,.21);ty=uniform(-.32,.32);
        if(std::abs(ty-ay)<.08)ty=ay>=0?-.24:.24;
      }
      const double dx=ax+gap,dy=ay*.25+uniform(-.06,.06);
      const float x=ax,y=ay;
      scene.left_team[1]=FormationEntry(x,y,e_PlayerRole_CF,false,true);
      scene.left_team[2]=FormationEntry(float(tx),float(ty),e_PlayerRole_CF,false,true);
      scene.right_team[1]=FormationEntry(float(dx),float(dy),e_PlayerRole_CB,false,false);
      scene.ball_position=blunted::Vector3(x+.02f,y,0);
      return group;
    }
    PolicyRng rng(uint64_t(seed)^UINT64_C(0x6a09e667f3bcc909));
    const uint32_t index=static_cast<uint32_t>(rng.index(12));
    const float offset=.0125f*uint32_t(partition);
    const float x=.44f+.06f*(index%4)+offset, y=-.16f+.16f*(index/4)+offset;
    scene.left_team[1]=FormationEntry(x,y,e_PlayerRole_CF,false,true);
    scene.left_team[2]=FormationEntry(x+.12f,y<=0 ? .18f : -.18f,e_PlayerRole_CF,false,true);
    scene.right_team[1]=FormationEntry(x+.15f,y*.25f,e_PlayerRole_CB,false,false);
    scene.ball_position=blunted::Vector3(x+.02f,y,0);
    return index;
  }
  if (scene.left_agents!=1 || scene.right_agents!=0 || scene.left_team.size()!=2 || scene.right_team.size()!=1)
    throw std::invalid_argument("Variable shooting scenarios require one left agent and2/1 rosters");
  PolicyRng rng(uint64_t(seed)^UINT64_C(0x7f4a7c159e3779b9));
  const uint32_t index=static_cast<uint32_t>(rng.index(12));
  const float offset=.0125f*uint32_t(partition);
  const float x=.68f+.05f*(index%4)+offset, y=-.10f+.10f*(index/4)+offset;
  scene.left_team[1]=FormationEntry(x,y,e_PlayerRole_CB,false,true);
  scene.ball_position=blunted::Vector3(x+.02f,y,0);
  return index;
}
} // namespace football::training
