#pragma once
#include "training/native_training.hpp"
#include <stdexcept>
#include <algorithm>

namespace football::training {
// Decision-boundary diagnostics, not engine kick-event counts. Requests are
// actions9..11 while the fixed learner owns the ball; a completion requires a
// designated outfield teammate(index2) to acquire it within30 decisions without opponent custody.
// Free-ball intervals are preserved. Cadence can hide intermediate touches.
struct CooperationMetrics {
  size_t pass_requests=0, completed_passes=0, teammate_transfers=0, turnovers=0;
  int last_team=-1,last_player=-1,pending_player=-1;
  size_t pending_age=0;
  void observe(TrainingPossession value) {
    if(value.team<0) return;
    if(value.team==1 && last_team==0) ++turnovers;
    if(value.team==0 && last_team==0 && value.player!=last_player) ++teammate_transfers;
    if(pending_player>=0 && value.team==0 && value.player!=pending_player) {
      if(value.player==2) ++completed_passes;
      pending_player=-1;
    }
    if(value.team==1) pending_player=-1;
    last_team=value.team; last_player=value.player;
  }
  void action(TrainingPossession before,int action) {
    if(pending_player>=0 && ++pending_age>30) pending_player=-1;
    if(before.team==0 && before.player==before.controlled_player && before.player>=0) {
      if(action>=9 && action<=11) {
        ++pass_requests; pending_player=before.player; pending_age=0;
      } else if(action==12) pending_player=-1;
    }
  }
};
// The task policy sees bonus-earned history in an unused fixed-layout padding
// slot (left player10 y). Engine observations/snapshots retain simple115 exactly.
inline ObservationBuffer PrimaryCooperationObservation(const ObservationBuffer& raw) {
  if((raw.size()!=1 && raw.size()!=2) || (raw.columns()!=115 && raw.columns()!=460))
    throw std::invalid_argument("Cooperation requires primary/fixed-AI simple115/stacked rows");
  ObservationBuffer result(1,raw.columns());
  std::copy_n(raw.buffer().begin(),raw.columns(),result.buffer().begin()); return result;
}
inline ObservationBuffer CooperationObservation(const ObservationBuffer& raw,bool passed,const std::array<uint8_t,10>& sticky) {
  auto result=PrimaryCooperationObservation(raw); result.buffer()[21]=passed ? 1.f : -1.f;
  // Three-player left/two-player right rosters leave these slots unused in both
  // fixed and compact layouts. Native observations/history stay unmodified.
  for(size_t i=0;i<sticky.size();++i) {
    if(sticky[i]>1) throw std::invalid_argument("Invalid cooperation sticky flag");
    result.buffer()[28+i]=sticky[i];
  }
  return result;
}
// Preserve every actual goal reward. The once-only auxiliary bonus cannot be
// farmed by repeatedly transferring possession and never gates scoring credit.
inline double CooperativeReward(double raw,size_t before,size_t after,double scored=0) {
  return raw+(before==0 && after>0 ? 2.0 : 0)+(after>0 && scored>0 ? 2.0*scored : 0);
}
} // namespace football::training
