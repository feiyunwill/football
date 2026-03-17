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
//
// Python bindings via pybind11 (replaces Boost.Python). GIL is released in
// step/step_with_input/render/get_state/set_state/reset/get_frame.

#undef NDEBUG

#include "src/game_env.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include <boost/shared_ptr.hpp>

namespace py = pybind11;
using std::string;

class GameEnv_Python : public GameEnv {
 public:
  py::bytes get_frame_python() {
    ContextHolder c(this);
    screenshoot screen = get_frame();
    return py::bytes(screen.data(), screen.size());
  }

  py::bytes get_state_python(const std::string& to_pickle) {
    std::string state = get_state(to_pickle);
    return py::bytes(state.data(), state.size());
  }

  py::bytes set_state_python(const std::string& state) {
    std::string from_pickle = set_state(state);
    return py::bytes(from_pickle.data(), from_pickle.size());
  }

  void step_with_input_python(py::bytes buffer_obj) {
    ContextHolder c(this);
    string buf = buffer_obj;
    StepWithInput(static_cast<const void*>(buf.data()), buf.size());
  }

  void reset_python(ScenarioConfig& game_config, bool init_animation) {
    ContextHolder c(this);
    context->step = -1;
    GetTracker()->setDisabled(true);
    reset(game_config, init_animation);
    GetTracker()->setDisabled(false);
  }
};

PYBIND11_MODULE(_gameplayfootball, m) {
  py::class_<std::vector<float>>(m, "FloatVec")
      .def(py::init<>())
      .def("__len__", [](const std::vector<float>& v) { return v.size(); })
      .def("__getitem__", [](const std::vector<float>& v, size_t i) {
        if (i >= v.size()) throw py::index_error();
        return v[i];
      });

  py::class_<std::vector<int>>(m, "IntVec")
      .def(py::init<>())
      .def("__len__", [](const std::vector<int>& v) { return v.size(); })
      .def("__getitem__", [](const std::vector<int>& v, size_t i) {
        if (i >= v.size()) throw py::index_error();
        return v[i];
      });

  py::class_<Position>(m, "Position", py::init<float, float, float, bool>(),
                       py::arg("x") = 0.0f, py::arg("y") = 0.0f,
                       py::arg("z") = 0.0f, py::arg("env_coords") = false)
      .def("__getitem__", &Position::env_coord)
      .def("__str__", &Position::debug);

  py::class_<PlayerInfo>(m, "PlayerInfo")
      .def_readonly("position", &PlayerInfo::player_position)
      .def_readonly("direction", &PlayerInfo::player_direction)
      .def_readonly("tired_factor", &PlayerInfo::tired_factor)
      .def_readonly("has_card", &PlayerInfo::has_card)
      .def_readonly("is_active", &PlayerInfo::is_active)
      .def_readonly("role", &PlayerInfo::role)
      .def_readonly("designated_player", &PlayerInfo::designated_player);

  py::class_<std::vector<PlayerInfo>>(m, "PlayerInfoVec")
      .def(py::init<>())
      .def("__len__", [](const std::vector<PlayerInfo>& v) { return v.size(); })
      .def("__getitem__", [](const std::vector<PlayerInfo>& v, size_t i) {
        if (i >= v.size()) throw py::index_error();
        return v[i];
      });

  py::class_<ControllerInfo>(m, "ControllerInfo", py::init<int>())
      .def_readonly("controlled_player", &ControllerInfo::controlled_player);

  py::class_<std::vector<ControllerInfo>>(m, "ControllerInfoVec")
      .def(py::init<>())
      .def("__len__", [](const std::vector<ControllerInfo>& v) { return v.size(); })
      .def("__getitem__", [](const std::vector<ControllerInfo>& v, size_t i) {
        if (i >= v.size()) throw py::index_error();
        return v[i];
      });

  py::class_<SharedInfo>(m, "SharedInfo")
      .def_readonly("ball_position", &SharedInfo::ball_position)
      .def_readonly("ball_rotation", &SharedInfo::ball_rotation)
      .def_readonly("ball_direction", &SharedInfo::ball_direction)
      .def_readonly("left_team", &SharedInfo::left_team)
      .def_readonly("right_team", &SharedInfo::right_team)
      .def_readonly("left_goals", &SharedInfo::left_goals)
      .def_readonly("right_goals", &SharedInfo::right_goals)
      .def_readonly("is_in_play", &SharedInfo::is_in_play)
      .def_readonly("ball_owned_team", &SharedInfo::ball_owned_team)
      .def_readonly("ball_owned_player", &SharedInfo::ball_owned_player)
      .def_readonly("left_controllers", &SharedInfo::left_controllers)
      .def_readonly("right_controllers", &SharedInfo::right_controllers)
      .def_readonly("game_mode", &SharedInfo::game_mode)
      .def_readonly("step", &SharedInfo::step);

  py::enum_<GameState>(m, "GameState")
      .value("game_created", GameState::game_created)
      .value("game_initiated", GameState::game_initiated)
      .value("game_running", GameState::game_running)
      .value("game_done", GameState::game_done)
      .export_values();

  py::class_<GameEnv_Python>(m, "GameEnv")
      .def("start_game", &GameEnv_Python::start_game)
      .def("get_info", &GameEnv_Python::get_info)
      .def("get_frame", &GameEnv_Python::get_frame_python,
           py::call_guard<py::gil_scoped_release>())
      .def("perform_action", &GameEnv_Python::action)
      .def("sticky_action_state", &GameEnv_Python::sticky_action_state)
      .def("step", &GameEnv_Python::step,
           py::call_guard<py::gil_scoped_release>())
      .def("step_with_input", &GameEnv_Python::step_with_input_python,
           py::call_guard<py::gil_scoped_release>())
      .def("get_state", &GameEnv_Python::get_state_python,
           py::call_guard<py::gil_scoped_release>())
      .def("set_state", &GameEnv_Python::set_state_python,
           py::call_guard<py::gil_scoped_release>())
      .def("reset", &GameEnv_Python::reset_python,
           py::call_guard<py::gil_scoped_release>())
      .def("render", &GameEnv_Python::render,
           py::call_guard<py::gil_scoped_release>(), py::arg("swap_buffer") = true)
      .def_property(
          "config",
          [](GameEnv_Python& self) -> ScenarioConfig& { return self.scenario_config; },
          [](GameEnv_Python& self, const ScenarioConfig& c) { self.scenario_config = c; },
          py::return_value_policy::reference_internal)
      .def_property(
          "game_config",
          [](GameEnv_Python& self) -> GameConfig& { return self.game_config; },
          [](GameEnv_Python& self, const GameConfig& c) { self.game_config = c; },
          py::return_value_policy::reference_internal)
      .def_readwrite("state", &GameEnv_Python::state)
      .def_readwrite("waiting_for_game_count",
                     &GameEnv_Python::waiting_for_game_count)
      .def("tracker_setup", &GameEnv::tracker_setup);

  py::class_<Vector3>(m, "Vector3", py::init<float, float, float>())
      .def("__getitem__", &Vector3::GetEnvCoord)
      .def("__setitem__", &Vector3::SetEnvCoord);

  py::class_<GameConfig, boost::shared_ptr<GameConfig>>(m, "GameConfig")
      .def_static("make", &GameConfig::make)
      .def_readwrite("render", &GameConfig::render)
      .def_readwrite("physics_steps_per_frame",
                     &GameConfig::physics_steps_per_frame)
      .def_readwrite("render_resolution_x", &GameConfig::render_resolution_x)
      .def_readwrite("render_resolution_y", &GameConfig::render_resolution_y);

  py::class_<ScenarioConfig, boost::shared_ptr<ScenarioConfig>>(m, "ScenarioConfig")
      .def_static("make", &ScenarioConfig::make)
      .def_readwrite("ball_position", &ScenarioConfig::ball_position)
      .def_readwrite("left_team", &ScenarioConfig::left_team)
      .def_readwrite("right_team", &ScenarioConfig::right_team)
      .def_readwrite("left_agents", &ScenarioConfig::left_agents)
      .def_readwrite("right_agents", &ScenarioConfig::right_agents)
      .def_readwrite("use_magnet", &ScenarioConfig::use_magnet)
      .def_readwrite("game_engine_random_seed",
                     &ScenarioConfig::game_engine_random_seed)
      .def_readwrite("reverse_team_processing",
                     &ScenarioConfig::reverse_team_processing)
      .def_readwrite("offsides", &ScenarioConfig::offsides)
      .def_readwrite("real_time", &ScenarioConfig::real_time)
      .def_readwrite("left_team_difficulty",
                     &ScenarioConfig::left_team_difficulty)
      .def_readwrite("right_team_difficulty",
                     &ScenarioConfig::right_team_difficulty)
      .def_readwrite("deterministic", &ScenarioConfig::deterministic)
      .def_readwrite("end_episode_on_score",
                     &ScenarioConfig::end_episode_on_score)
      .def_readwrite("end_episode_on_possession_change",
                     &ScenarioConfig::end_episode_on_possession_change)
      .def_readwrite("end_episode_on_out_of_play",
                     &ScenarioConfig::end_episode_on_out_of_play)
      .def_readwrite("game_duration", &ScenarioConfig::game_duration)
      .def_readwrite("second_half", &ScenarioConfig::second_half)
      .def_readwrite("control_all_players",
                     &ScenarioConfig::control_all_players)
      .def_property_readonly("dynamic_player_selection",
                             &ScenarioConfig::DynamicPlayerSelection)
      .def_property_readonly("controllable_left_players",
                             &ScenarioConfig::ControllableLeftPlayers)
      .def_property_readonly("controllable_right_players",
                             &ScenarioConfig::ControllableRightPlayers);

  py::enum_<e_PlayerRole>(m, "e_PlayerRole")
      .value("e_PlayerRole_GK", e_PlayerRole::e_PlayerRole_GK)
      .value("e_PlayerRole_CB", e_PlayerRole::e_PlayerRole_CB)
      .value("e_PlayerRole_LB", e_PlayerRole::e_PlayerRole_LB)
      .value("e_PlayerRole_RB", e_PlayerRole::e_PlayerRole_RB)
      .value("e_PlayerRole_DM", e_PlayerRole::e_PlayerRole_DM)
      .value("e_PlayerRole_CM", e_PlayerRole::e_PlayerRole_CM)
      .value("e_PlayerRole_LM", e_PlayerRole::e_PlayerRole_LM)
      .value("e_PlayerRole_RM", e_PlayerRole::e_PlayerRole_RM)
      .value("e_PlayerRole_AM", e_PlayerRole::e_PlayerRole_AM)
      .value("e_PlayerRole_CF", e_PlayerRole::e_PlayerRole_CF)
      .export_values();

  py::class_<FormationEntry>(m, "FormationEntry",
                             py::init<float, float, e_PlayerRole, bool, bool>())
      .def_readonly("role", &FormationEntry::role)
      .def_property_readonly("position", &FormationEntry::position_env)
      .def_readwrite("lazy", &FormationEntry::lazy)
      .def_readwrite("controllable", &FormationEntry::controllable);

  py::class_<std::vector<FormationEntry>>(m, "FormationEntryVec")
      .def(py::init<>())
      .def("__len__", [](const std::vector<FormationEntry>& v) { return v.size(); })
      .def("__getitem__", [](const std::vector<FormationEntry>& v, size_t i) {
        if (i >= v.size()) throw py::index_error();
        return v[i];
      });

  py::class_<StringVector>(m, "StringVector")
      .def(py::init<>())
      .def("__len__", [](const StringVector& v) { return v.size(); })
      .def("__getitem__", [](const StringVector& v, size_t i) {
        if (i >= v.size()) throw py::index_error();
        return v[i];
      });

  py::enum_<e_RenderingMode>(m, "e_RenderingMode")
      .value("e_Disabled", e_RenderingMode::e_Disabled)
      .value("e_Onscreen", e_RenderingMode::e_Onscreen)
      .value("e_Offscreen", e_RenderingMode::e_Offscreen)
      .export_values();

  py::enum_<e_GameMode>(m, "e_GameMode")
      .value("e_GameMode_Normal", e_GameMode::e_GameMode_Normal)
      .value("e_GameMode_KickOff", e_GameMode::e_GameMode_KickOff)
      .value("e_GameMode_GoalKick", e_GameMode::e_GameMode_GoalKick)
      .value("e_GameMode_FreeKick", e_GameMode::e_GameMode_FreeKick)
      .value("e_GameMode_Corner", e_GameMode::e_GameMode_Corner)
      .value("e_GameMode_ThrowIn", e_GameMode::e_GameMode_ThrowIn)
      .value("e_GameMode_Penalty", e_GameMode::e_GameMode_Penalty)
      .export_values();

  py::enum_<Action>(m, "e_BackendAction")
      .value("idle", Action::game_idle)
      .value("left", Action::game_left)
      .value("top_left", Action::game_top_left)
      .value("top", Action::game_top)
      .value("top_right", Action::game_top_right)
      .value("right", Action::game_right)
      .value("bottom_right", Action::game_bottom_right)
      .value("bottom", Action::game_bottom)
      .value("bottom_left", Action::game_bottom_left)
      .value("long_pass", Action::game_long_pass)
      .value("high_pass", Action::game_high_pass)
      .value("short_pass", Action::game_short_pass)
      .value("shot", Action::game_shot)
      .value("keeper_rush", Action::game_keeper_rush)
      .value("sliding", Action::game_sliding)
      .value("pressure", Action::game_pressure)
      .value("team_pressure", Action::game_team_pressure)
      .value("switch", Action::game_switch)
      .value("sprint", Action::game_sprint)
      .value("dribble", Action::game_dribble)
      .value("release_direction", Action::game_release_direction)
      .value("release_long_pass", Action::game_release_long_pass)
      .value("release_high_pass", Action::game_release_high_pass)
      .value("release_short_pass", Action::game_release_short_pass)
      .value("release_shot", Action::game_release_shot)
      .value("release_keeper_rush", Action::game_release_keeper_rush)
      .value("release_sliding", Action::game_release_sliding)
      .value("release_pressure", Action::game_release_pressure)
      .value("release_team_pressure", Action::game_release_team_pressure)
      .value("release_switch", Action::game_release_switch)
      .value("release_sprint", Action::game_release_sprint)
      .value("release_dribble", Action::game_release_dribble)
      .value("builtin_ai", Action::game_builtin_ai)
      .export_values();

  py::enum_<e_Team>(m, "e_Team")
      .value("e_Left", e_Team::e_Left)
      .value("e_Right", e_Team::e_Right)
      .export_values();
}
