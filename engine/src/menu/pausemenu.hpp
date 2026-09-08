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

#ifndef _HPP_MENU_PAUSEMENU
#define _HPP_MENU_PAUSEMENU

#include "../utils/gui2/windowmanager.hpp"
#include "../utils/gui2/page.hpp"
#include "../utils/gui2/widgets/caption.hpp"

using namespace blunted;

class PauseMenuPage : public Gui2Page {
 public:
  PauseMenuPage(Gui2WindowManager *windowManager, const Gui2PageData &pageData);
  virtual ~PauseMenuPage();

 private:
  void CreateMenuItems();
  void UpdateSelection();
  void HandleInput();

  Gui2Caption *resumeCaption;
  Gui2Caption *settingsCaption;
  Gui2Caption *exitCaption;

  int selectedItem;
  std::vector<Gui2Caption*> menuItems;
};

#endif