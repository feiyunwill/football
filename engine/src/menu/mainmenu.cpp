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

#include "mainmenu.hpp"

#include "pagefactory.hpp"
#include "../main.hpp"

using namespace blunted;

MainMenuPage::MainMenuPage(Gui2WindowManager *windowManager,
                           const Gui2PageData &pageData)
    : Gui2Page(windowManager, pageData), selectedItem(0) {
  DO_VALIDATION;

  CreateMenuItems();
  UpdateSelection();
  this->SetFocus();
  this->Show();
}

MainMenuPage::~MainMenuPage() { DO_VALIDATION; }

void MainMenuPage::CreateMenuItems() {
  DO_VALIDATION;

  logoImage = new Gui2Image(windowManager, "main_menu_logo", 30, 10, 40, 20);
  logoImage->LoadImage("media/menu/main/logo.png");
  this->AddView(logoImage);
  logoImage->Show();

  startGameCaption = new Gui2Caption(windowManager, "main_menu_start", 40, 40, 20, 5, "Start Game");
  multiplayerCaption = new Gui2Caption(windowManager, "main_menu_multiplayer", 40, 50, 20, 5, "Multiplayer");
  settingsCaption = new Gui2Caption(windowManager, "main_menu_settings", 40, 60, 20, 5, "Settings");
  exitCaption = new Gui2Caption(windowManager, "main_menu_exit", 40, 70, 20, 5, "Exit");

  this->AddView(startGameCaption);
  this->AddView(multiplayerCaption);
  this->AddView(settingsCaption);
  this->AddView(exitCaption);

  startGameCaption->Show();
  multiplayerCaption->Show();
  settingsCaption->Show();
  exitCaption->Show();

  menuItems.push_back(startGameCaption);
  menuItems.push_back(multiplayerCaption);
  menuItems.push_back(settingsCaption);
  menuItems.push_back(exitCaption);
}

void MainMenuPage::UpdateSelection() {
  DO_VALIDATION;

  for (size_t i = 0; i < menuItems.size(); i++) {
    if (static_cast<int>(i) == selectedItem) {
      menuItems[i]->SetColor(Vector3(240, 60, 60));
    } else {
      menuItems[i]->SetColor(Vector3(255, 255, 255));
    }
  }
}

void MainMenuPage::HandleInput() {
  DO_VALIDATION;

  if (windowManager->GetButtonPressed(0, 0)) {
    selectedItem--;
    if (selectedItem < 0) selectedItem = menuItems.size() - 1;
    UpdateSelection();
  }

  if (windowManager->GetButtonPressed(0, 1)) {
    selectedItem++;
    if (selectedItem >= static_cast<int>(menuItems.size())) selectedItem = 0;
    UpdateSelection();
  }

  if (windowManager->GetButtonPressed(0, 2)) {
    switch (selectedItem) {
      case 0:
        break;
      case 1:
        break;
      case 2:
        break;
      case 3:
        break;
    }
  }

  if (windowManager->GetButtonPressed(0, 3)) {
  }
}
