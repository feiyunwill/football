// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// written by bastiaan konings schuiling 2008 - 2015
// this work is public domain. the code is undocumented, scruffy, untested, and should generally not be used for anything important.
// i do not offer support, so don't ask. to be used for inspiration :)

#ifndef _HPP_AISUPPORT_AIFUNCTIONS
#define _HPP_AISUPPORT_AIFUNCTIONS

#include "../../gamedefines.hpp"

class MentalImage;
class Ball;
class Match;
class Team;
class Player;
class PlayerBase;

#include "../../base/math/vector3.hpp"

#include "../../data/teamdata.hpp"

#include <array>

struct TimeNeeded {
  TimeNeeded() { DO_VALIDATION;
    usual_ms = 0;
    optimistic_ms = 0;
  }
  unsigned int usual_ms = 0;
  unsigned int optimistic_ms = 0;
};

Vector3 AI_GetAdaptedFormationPosition(
    Match *match, Player *player, float backXBound, float frontXBound,
    float lowYBound, float highYBound, float xFocus, float xFocusStrength,
    float yFocus, float yFocusStrength, const Vector3 &microFocus,
    float microFocusStrength, float midfieldFocus, float midfieldFocusStrength,
    bool useDynamicFormationPosition = true);
float AI_CalculateFreeSpace(Match *match, const MentalImage *mentalImage,
                            int teamID, const Vector3 &focusPos,
                            float safeDistance = 8.0,
                            float futureTime_sec = 0.3);
float AI_GetOffsideLine(Match *match, const MentalImage *mentalImage, int teamID, unsigned int futureSim_ms = 0);
void AI_GetBestDribbleMovement(Match *match, PlayerBase* player, const MentalImage *mentalImage, Vector3 &desiredDirection, float &desiredVelocity, const TeamTactics &teamTactics);
Vector3 AI_GetForceFieldMovement(const std::vector<ForceSpot> &forceField, const Vector3 &currentPos, float attractorDampingDistance = 10);
TimeNeeded AI_GetTimeNeededForDistance_ms(const Vector3 &playerPos, const Vector3 &playerMovement, const Vector3 &targetPos, float maxVelocity = sprintVelocity, bool precise = false, unsigned int maxTime_ms = -1);

// 2026-09-13: one possession scan owns one immutable player-state snapshot.
// Lazily reuse only target-independent running trajectories; walking foot
// offsets still follow the original target-dependent calculation. No heap use.
class AIReachabilityTrajectory {
 public:
  AIReachabilityTrajectory() = delete;
  AIReachabilityTrajectory(const Vector3& position, const Vector3& movement,
                           float max_velocity);
  ~AIReachabilityTrajectory() = default;
  AIReachabilityTrajectory(const AIReachabilityTrajectory&) = delete;
  AIReachabilityTrajectory& operator=(const AIReachabilityTrajectory&) = delete;
  AIReachabilityTrajectory(AIReachabilityTrajectory&&) = delete;
  AIReachabilityTrajectory& operator=(AIReachabilityTrajectory&&) = delete;

  TimeNeeded Estimate(const Vector3& target, bool precise = false,
                      unsigned int maximum_ms = -1);

 private:
  friend TimeNeeded AI_GetTimeNeededForDistance_ms(
      const Vector3&, const Vector3&, const Vector3&, float, bool, unsigned int);
  template <bool Reuse>
  static TimeNeeded EstimateImpl(const Vector3& position, const Vector3& movement,
                                const Vector3& target, float max_velocity,
                                bool precise, unsigned int maximum_ms,
                                AIReachabilityTrajectory* trajectory);
  void Prepare();
  void GrowTo(unsigned int index);

  const Vector3 position_;
  const Vector3 movement_;
  const float max_velocity_;
  const Vector3 drift_position_;
  Vector3 initial_position_;
  bool prepared_ = false;
  bool reusable_ = false;
  unsigned int size_ = 0;
  // x, y, z, usual radius, optimistic radius after each original 10 ms step.
  // Entries are written before publication through size_; avoid eager clearing.
  std::array<std::array<float, 5>, 70> states_;
};
unsigned int AI_GetToBallMovement(Match *match, const MentalImage *mentalImage, Player *player, const Vector3 &desiredDirection, float desiredVelocityFloat, Vector3 &bestDirection, float &bestVelocityFloat, Vector3 &bestLookAt, float haste = 0.0f);
unsigned int AI_GetBallControlMovement(const MentalImage *mentalImage, Player *player, const Vector3 &desiredDirection, float desiredVelocityFloat, Vector3 &bestDirection, float &bestVelocityFloat, Vector3 &bestLookAt);
bool AI_HasPossession(Ball *ball, Player *player);
Player *AI_GetClosestPlayer(Team *team, const Vector3 &position,
                            bool onlyAIControlled, Player *except = 0, bool onlySelectable = false);
void AI_GetClosestPlayers(Team *team, const Vector3 &position, bool onlyAIControlled, std::vector<Player*> &result, unsigned int playerCount = 3, bool onlySelectable = false);
Player *AI_GetBestSwitchTargetPlayer(Match *match, Team *team, const Vector3 &desiredMovement);
void AI_GetAutoPass(e_FunctionType passType, const Vector3 &vector, Vector3 &resultingDirection, float &resultingPower);
void AI_GetPass(Player *player, e_FunctionType passType, const Vector3 &inputDirection, float inputPower, float autoDirectionBias, float autoPowerBias, Vector3 &resultingDirection, float &resultingPower, Player *&targetPlayer, Player *forcedTargetPlayer = 0);
Vector3 AI_GetShotDirection(Player *player, const Vector3 &inputDirection, float autoDirectionBias = 1.0f); // this is to get a 'rough' idea of where to shoot, so we can pick the proper animation. exact direction will be tweaked later on.

float AI_GetMindSet(e_PlayerRole role);

#endif
