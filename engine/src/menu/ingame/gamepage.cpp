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

#include "gamepage.hpp"

#include "../pagefactory.hpp"

#include "../../main.hpp"

#include "../../onthepitch/match.hpp"

using namespace blunted;

GamePage::GamePage(Gui2WindowManager *windowManager_,
                   const Gui2PageData &pageData_)
    : Gui2Page(windowManager_, pageData_), match(nullptr), scoreBoard(nullptr), radar(nullptr) {
  DO_VALIDATION;

  // Get match from game task
  match = GetGameTask()->GetMatch();
  if (match) {
    // Create scoreboard
    scoreBoard = new Gui2ScoreBoard(windowManager, match);
    this->AddView(scoreBoard);
    scoreBoard->Show();

    // Create radar
    Vector3 team1Color1(0, 100, 220);  // Blue team
    Vector3 team1Color2(0, 150, 255);
    Vector3 team2Color1(220, 50, 0);   // Red team
    Vector3 team2Color2(255, 100, 50);
    radar = new Gui2Radar(windowManager, "radar", 75, 70, 20, 25, match, team1Color1, team1Color2, team2Color1, team2Color2);
    this->AddView(radar);
    radar->Show();
  }

  this->Show();
  this->SetFocus();
}

GamePage::~GamePage() { DO_VALIDATION; }
