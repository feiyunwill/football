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

#ifndef _HPP_MENU_SETTINGS
#define _HPP_MENU_SETTINGS

#include "../utils/gui2/windowmanager.hpp"
#include "../utils/gui2/page.hpp"
#include "../utils/gui2/widgets/caption.hpp"

using namespace blunted;

class SettingsPage : public Gui2Page {
 public:
  SettingsPage(Gui2WindowManager *windowManager, const Gui2PageData &pageData);
  virtual ~SettingsPage();

 private:
  void CreateSettingsItems();
  void UpdateSelection();
  void HandleInput();

  Gui2Caption *volumeCaption;
  Gui2Caption *graphicsCaption;
  Gui2Caption *controlsCaption;
  Gui2Caption *backCaption;

  int selectedItem;
  std::vector<Gui2Caption*> settingItems;
};

#endif