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

#include "settings.hpp"

#include "pagefactory.hpp"
#include "../main.hpp"

using namespace blunted;

SettingsPage::SettingsPage(Gui2WindowManager *windowManager,
                           const Gui2PageData &pageData)
    : Gui2Page(windowManager, pageData), selectedItem(0) {
  DO_VALIDATION;

  CreateSettingsItems();
  UpdateSelection();
  this->SetFocus();
  this->Show();
}

SettingsPage::~SettingsPage() { DO_VALIDATION; }

void SettingsPage::CreateSettingsItems() {
  DO_VALIDATION;

  // Title
  Gui2Caption *titleCaption = new Gui2Caption(windowManager, "settings_title", 40, 10, 20, 5, "Settings");
  this->AddView(titleCaption);
  titleCaption->Show();

  // Settings items
  volumeCaption = new Gui2Caption(windowManager, "settings_volume", 40, 30, 20, 5, "Volume");
  graphicsCaption = new Gui2Caption(windowManager, "settings_graphics", 40, 40, 20, 5, "Graphics");
  controlsCaption = new Gui2Caption(windowManager, "settings_controls", 40, 50, 20, 5, "Controls");
  backCaption = new Gui2Caption(windowManager, "settings_back", 40, 60, 20, 5, "Back");

  this->AddView(volumeCaption);
  this->AddView(graphicsCaption);
  this->AddView(controlsCaption);
  this->AddView(backCaption);

  volumeCaption->Show();
  graphicsCaption->Show();
  controlsCaption->Show();
  backCaption->Show();

  settingItems.push_back(volumeCaption);
  settingItems.push_back(graphicsCaption);
  settingItems.push_back(controlsCaption);
  settingItems.push_back(backCaption);
}

void SettingsPage::UpdateSelection() {
  DO_VALIDATION;

  for (size_t i = 0; i < settingItems.size(); i++) {
    if (static_cast<int>(i) == selectedItem) {
      settingItems[i]->SetColor(Vector3(240, 60, 60));  // Selected color
    } else {
      settingItems[i]->SetColor(Vector3(255, 255, 255));  // Normal color
    }
  }
}

void SettingsPage::HandleInput() {
  DO_VALIDATION;

  // Check for keyboard input
  if (windowManager->GetButtonPressed(0, 0)) {  // Up
    selectedItem--;
    if (selectedItem < 0) selectedItem = settingItems.size() - 1;
    UpdateSelection();
  }

  if (windowManager->GetButtonPressed(0, 1)) {  // Down
    selectedItem++;
    if (selectedItem >= static_cast<int>(settingItems.size())) selectedItem = 0;
    UpdateSelection();
  }

  if (windowManager->GetButtonPressed(0, 2)) {  // Confirm (Enter/A)
    switch (selectedItem) {
      case 0:  // Volume
        // TODO: Open volume settings
        break;
      case 1:  // Graphics
        // TODO: Open graphics settings
        break;
      case 2:  // Controls
        // TODO: Open controls settings
        break;
      case 3:  // Back
        // TODO: Go back to main menu
        break;
    }
  }

  if (windowManager->GetButtonPressed(0, 3)) {  // Back (Escape/B)
    // TODO: Go back to main menu
  }
}