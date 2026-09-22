// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0.
// Frozen 2026-09-13 before loop optimization; do not update to match candidate.
TimeNeeded AI_GetTimeNeededForDistance_ms(const Vector3 &playerPos,
                                          const Vector3 &playerMovement,
                                          const Vector3 &targetPos,
                                          float maxVelocity, bool precise,
                                          unsigned int maxTime_ms) {
  DO_VALIDATION;

  TimeNeeded result;

  float optimizeDist = 16.0f;
  if (precise) optimizeDist = 48.0f;

  float initialDist = (playerPos - targetPos).GetLength();
  unsigned int defaultOptimizedTime_ms = int(
      std::round((targetPos - (playerPos + playerMovement * 0.2f)).GetLength() /
                 (maxVelocity * 0.75f) * 1000));
  if (initialDist > optimizeDist) {
    DO_VALIDATION;
    result.usual_ms = defaultOptimizedTime_ms;
    result.optimistic_ms = result.usual_ms - 200;
    return result;
  }

  // definitive best version of all versions
  // The One Version
  // or else..

  Vector3 currentPos = playerPos;
  Vector3 currentMovement = playerMovement;

  float ffo = 0.1f; // in front of foot offset (ideal ball position)
  if (currentMovement.GetLength() > idleDribbleSwitch) {

    DO_VALIDATION;
    currentPos += currentMovement.GetNormalized() * ffo;
    currentPos += currentMovement * 0.01f;
  } else {
    DO_VALIDATION;
    currentPos += (targetPos - playerPos).GetNormalized(0) * ffo;
  }

  unsigned int currentTime_ms = 0;
  const unsigned int timeStep_ms = 10;
  const unsigned int changeTime_ms = 700;
  float radius_usual = 0.28f; // starting distance from our base position where we can reach balls (effectively: leg extension length)
  float radius_optimistic = 0.9f;
  float resultingRadius_usual = radius_usual; // initial value > 0 because we don't want division by zero
  bool foundOptimisticTime = false;

  float adaptedMaxVelocity = maxVelocity * 0.94f; // don't use full maxvelocity, since the last part of that velo is very hard to attain (due to exponential air resistance)

  while (true) {
    DO_VALIDATION;  // =]

    // too unstable! timeStep_ms = clamp(int(round(previousDistance * 30)) - 20, 10, 40); // variable timestep may not be 100% correct, so don't overdo it
    // round to 10s
    //timeStep_ms = int(floor(timeStep_ms / 10.0f)) * 10;

    float bias = clamp((float)currentTime_ms / (float)changeTime_ms, 0.0f, 1.0f);
    //bias = pow(bias, 1.7f); // higher exp == slower
    //bias = 0.1f + pow(bias, 0.8f) * 0.9f; // higher exp == slower
    //bias = 0.01f + pow(bias, 1.0f) * 0.99f; // higher exp == slower
    //bias = 0.1f + bias * 0.9f;

    if (bias >= 1.0f) {
      DO_VALIDATION;

      // we can now simply calculate the time needed
      float remainingDistance_usual = clamp((targetPos - currentPos).GetLength() - radius_usual, 0.0f, 100000.0f);
      result.usual_ms = currentTime_ms + (remainingDistance_usual / adaptedMaxVelocity) * 1000;
      resultingRadius_usual = radius_usual + remainingDistance_usual;

      if (!foundOptimisticTime) {
        DO_VALIDATION;
        float remainingDistance_optimistic = clamp((targetPos - currentPos).GetLength() - radius_optimistic, 0.0f, 100000.0f);
        result.optimistic_ms = currentTime_ms + (remainingDistance_optimistic / adaptedMaxVelocity) * 1000;
      }

      break;

    } else {
      DO_VALIDATION;
      // manual copy: this function is called a lot, so if we use the Vector3::operator*, it's creating a lot of temp vars.
      // currentMovement = playerMovement * (1.0f - bias);
      currentMovement.coords[0] = playerMovement.coords[0] * (1.0f - bias);
      currentMovement.coords[1] = playerMovement.coords[1] * (1.0f - bias);

      //currentPos += currentMovement * timeStep_ms * 0.001f;
      currentPos.coords[0] += currentMovement.coords[0] * timeStep_ms * 0.001f;
      currentPos.coords[1] += currentMovement.coords[1] * timeStep_ms * 0.001f;

      // within this radius, we can get to a ball
      radius_usual += adaptedMaxVelocity * bias * timeStep_ms * 0.001f;
      radius_optimistic += adaptedMaxVelocity * bias * timeStep_ms * 0.001f;

      float targetDistance = (targetPos - currentPos).GetSquaredLength();
      //if (currentTime_ms > 1000 && currentTime_ms % 100 == 0) printf("currentTime_ms: %i, targetDistance: %f, currentMovementLength: %f, bias: %f, radius: %f, changeTime_ms: %i\n", currentTime_ms, targetDistance, currentMovement.GetLength(), bias, radius, changeTime_ms);
      if ((targetDistance < radius_optimistic * radius_optimistic ||
           (maxTime_ms != -1 && currentTime_ms > (unsigned int)maxTime_ms)) &&
          !foundOptimisticTime) {
        DO_VALIDATION;
        result.optimistic_ms = currentTime_ms;
        foundOptimisticTime = true;
      }
      if (targetDistance < radius_usual * radius_usual ||
          (maxTime_ms != -1 && currentTime_ms > (unsigned int)maxTime_ms)) {
        DO_VALIDATION;
        //currentTime_ms += int(round(((targetPos - currentPos).GetLength() / radius) * 40.0));
        resultingRadius_usual = radius_usual;
        result.usual_ms = currentTime_ms;
        break;
      }
    }

    currentTime_ms += timeStep_ms;
  }

  if (maxTime_ms != -1 && currentTime_ms > (unsigned int)maxTime_ms) {
    DO_VALIDATION;
    result.usual_ms = std::max(defaultOptimizedTime_ms, (currentTime_ms + 100) * 2);
    if (!foundOptimisticTime) result.optimistic_ms = result.usual_ms;
    return result;
  }

  // very, very close! just take distance as time, so we can still compare to other players properly
  if (result.usual_ms == 0) {
    DO_VALIDATION;
    result.usual_ms = int(std::round(
        clamp((targetPos - playerPos).GetLength() / resultingRadius_usual, 0.0f,
              1.0f) *
        10));
    result.optimistic_ms = result.usual_ms;
  }

  return result;

  /* too simple version
  return int(round((targetPos - (playerPos + playerMovement * 0.02)).GetLength() / (sprintVelocity * 0.9) * 1000));
  */
}
