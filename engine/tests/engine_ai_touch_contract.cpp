
// 2026-09-14: real GameEnv players and shipped animation assets expose the bool conversion.
#include "frame_sync/engine_tcp_bridge.hpp"
#include "onthepitch/player/humanoid/humanoid.hpp"
#include "onthepitch/player/player.hpp"
#include "gametask.hpp"
#include <iostream>
#include <array>
#include <type_traits>
#include <cmath>
struct PlayerAccess : PlayerBase {
  // A member pointer keeps the declaring base type; no derived-object cast is used.
  using PlayerBase::humanoid;
  PlayerAccess() = delete;
  ~PlayerAccess() override = default;
  PlayerAccess(const PlayerAccess&) = delete;
  PlayerAccess& operator=(const PlayerAccess&) = delete;
  PlayerAccess(PlayerAccess&&) = delete;
  PlayerAccess& operator=(PlayerAccess&&) = delete;
};
struct TouchAccess : Humanoid {
  using Humanoid::NeedTouch;
  TouchAccess() = delete;
  ~TouchAccess() override = default;
  TouchAccess(const TouchAccess&) = delete;
  TouchAccess& operator=(const TouchAccess&) = delete;
  TouchAccess(TouchAccess&&) = delete;
  TouchAccess& operator=(TouchAccess&&) = delete;
};
static_assert(std::is_same_v<decltype(&TouchAccess::NeedTouch),bool (Humanoid::*)(int,const PlayerCommand&)>);
unsigned assertions=0,ball_control_assets=0,quiet_idle_total=0;
std::array<unsigned,4> total_categories{};
void Require(bool v,const char* msg){++assertions;if(!v)throw std::runtime_error(msg);}
void Check(unsigned seed){
  namespace fs=frame_sync;
  GameEnv env;env.game_config.render=false;env.game_config.physics_steps_per_frame=2;
  auto scenario=fs::MakeNativeMatchScenario(fs::NativeMatchContract(seed,1,1));
  env.start_game(*scenario);env.state=game_running;
  // 2026-09-14: normal simulation creates the first mental image; start_game alone does not.
  const std::array inputs{fs::SlotInput::Default(),fs::SlotInput::Default()};
  fs::MakeGameEnvCallbacks(&env).step_frame(inputs);
  ContextHolder guard(&env);
  auto* match=env.context->gameTask->GetMatch();
  auto* player=match->GetTeam(0)->MainSelectedPlayer();
  Require(player!=nullptr,"No actual selected player");
  auto* humanoid=dynamic_cast<Humanoid*>((player->*(&PlayerAccess::humanoid)).get());
  Require(humanoid!=nullptr,"No actual humanoid");
  auto& state=humanoid->MutableSpatialState();
  const auto saved=state;
  const auto digest=env.get_state_digest();
  state.angle=0;state.movement=Vector3(0.f);state.directionVec=Vector3(0.f,-1.f,0.f);
  const auto& assets=match->GetAnimCollection()->GetAnimations();
  PlayerCommand idle;idle.desiredVelocityFloat=0.f;idle.desiredFunctionType=e_FunctionType_BallControl;
  int quiet_id=-1;
  std::array<unsigned,4> categories{},needed{},missed{};
  unsigned quiet_idle=0;
  for(unsigned id=0;id<assets.size();++id){
   auto* anim=assets[id];
   if(anim->GetAnimType()!=e_DefString_BallControl)continue;
   ++ball_control_assets;
   const auto category=FloatToEnumVelocity(anim->GetOutgoingVelocity());
   Require(category>=e_Velocity_Idle && category<=e_Velocity_Sprint,"Invalid real animation speed");
   const bool result=(humanoid->*(&TouchAccess::NeedTouch))(id,idle);
   ++categories[category];
   if(result)++needed[category];
   else if(category!=e_Velocity_Idle){
    ++missed[category];
    std::cout<<"{\"missed_animation\":"<<id<<",\"speed\":"<<anim->GetOutgoingVelocity()<<",\"angle\":"<<anim->GetOutgoingAngle()<<"}\n";
   }else {++quiet_idle;quiet_id=static_cast<int>(id);}
   auto moving=idle;moving.desiredVelocityFloat=std::nextafter(idleDribbleSwitch,10.f);
   Require((humanoid->*(&TouchAccess::NeedTouch))(id,moving),"Moving command lost touch while stopping animation");
  }
  Require(quiet_id>=0,"No idle control animation");
  auto boundary=idle;boundary.desiredVelocityFloat=idleDribbleSwitch;
  Require(!(humanoid->*(&TouchAccess::NeedTouch))(quiet_id,boundary),"Idle command threshold changed");
  // 2026-09-14: prove query purity before the intentional ball mutation.
  state=saved;
  Require(env.get_state_digest()==digest,"Touch query changed logical state");
  const auto snapshot=env.get_state("");
  match->GetBall()->SetMomentum(Vector3(3.f,0.f,0.f));
  Require((humanoid->*(&TouchAccess::NeedTouch))(quiet_id,idle),"Fast ball passed an idle player without touch");
  // SetMomentum also invalidates predictions: restore the complete owned snapshot.
  env.set_state(snapshot);
  Require(env.get_state_digest()==digest,"Fast-ball fixture failed to restore its snapshot");
  std::cout<<"{\"assets\":"<<assets.size()<<",\"quiet_idle\":"<<quiet_idle<<",\"categories\":[";
  for(unsigned i=0;i<4;++i)std::cout<<(i?",":"")<<categories[i];
  std::cout<<"],\"needed\":[";
  for(unsigned i=0;i<4;++i)std::cout<<(i?",":"")<<needed[i];
  std::cout<<"],\"missed\":[";
  for(unsigned i=0;i<4;++i)std::cout<<(i?",":"")<<missed[i];
  std::cout<<"]}\n";
  Require(categories==std::array<unsigned,4>{28,26,18,18},"Shipped control animation cohort changed");
  Require(quiet_idle==8,"Stationary control animation cohort changed");
  for(unsigned i=0;i<4;++i)Require(categories[i]>0,"Missing shipped speed category");
  Require(quiet_idle>0,"Idle player always retouches a stationary ball");
  Require(missed[1]+missed[2]+missed[3]==0,"Moving animation skipped necessary touch");
  quiet_idle_total+=quiet_idle;
  for(unsigned i=0;i<4;++i)total_categories[i]+=categories[i];
}
int main(int,char**){
 try{
  for(unsigned seed:{42u,43u,20260914u})Check(seed);
  Require(ball_control_assets==270,"Incomplete three-seed control cohort");
  std::cout<<"{\"passed\":true,\"assertions\":"<<assertions<<",\"skipped\":0,\"actual_gameenv\":true,\"seeds\":3,\"ball_control_assets\":"<<ball_control_assets<<",\"quiet_idle\":"<<quiet_idle_total<<"}\n";
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
