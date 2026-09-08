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

#include "pausemenu.hpp"

#include "pagefactory.hpp"
#include "../main.hpp"

using namespace blunted;

PauseMenuPage::PauseMenuPage(Gui2WindowManager *windowManager,
                             const Gui2PageData &pageData)
    : Gui2Page(windowManager, pageData), selectedItem(0) {
  DO_VALIDATION;

  CreateMenuItems();
  UpdateSelection();
  this->SetFocus();
  this->Show();
}

PauseMenuPage::~PauseMenuPage() { DO_VALIDATION; }

void PauseMenuPage::CreateMenuItems() {
  DO_VALIDATION;

  // Title
  Gui2Caption *titleCaption = new Gui2Caption(windowManager, "pause_title", 40, 20, 20, 5, "Paused");
  this->AddView(titleCaption);
  titleCaption->Show();

  // Menu items
  resumeCaption = new Gui2Caption(windowManager, "pause_resume", 40, 40, 20, 5, "Resume");
  settingsCaption = new Gui2Caption(windowManager, "pause_settings", 40, 50, 20, 5, "Settings");
  exitCaption = new Gui2Caption(windowManager, "pause_exit", 40, 60, 20, 5, "Exit Match");

  this->AddView(resumeCaption);
  this->AddView(settingsCaption);
  this->AddView(exitCaption);

  resumeCaption->Show();
  settingsCaption->Show();
  exitCaption->Show();

  menuItems.push_back(resumeCaption);
  menuItems.push_back(settingsCaption);
  menuItems.push_back(exitCaption);
}

void PauseMenuPage::UpdateSelection() {
  DO_VALIDATION;

  for (size_t i = 0; i < menuItems.size(); i++) {
    if (static_cast<int>(i) == selectedItem) {
      menuItems[i]->SetColor(Vector3(240, 60, 60));  // Selected color
    } else {
      menuItems[i]->SetColor(Vector3(255, 255, 255));  // Normal color
    }
  }
}

void PauseMenuPage::HandleInput() {
  DO_VALIDATION;

  // Check for keyboard input
  if (windowManager->GetButtonPressed(0, 0)) {  // Up
    selectedItem--;
    if (selectedItem < 0) selectedItem = menuItems.size() - 1;
    UpdateSelection();
  }

  if (windowManager->GetButtonPressed(0, 1)) {  // Down
    selectedItem++;
    if (selectedItem >= static_cast<int>(menuItems.size())) selectedItem = 0;
    UpdateSelection();
  }

  if (windowManager->GetButtonPressed(0, 2)) {  // Confirm (Enter/A)
    switch (selectedItem) {
      case 0:  // Resume
        // TODO: Resume game
        break;
      case 1:  // Settings
        // TODO: Open settings
        break;
      case 2:  // Exit Match
        // TODO: Exit match and go to main menu
        break;
    }
  }

  if (windowManager->GetButtonPressed(0, 3)) {  // Back (Escape/B)
    // TODO: Resume game
  }
}