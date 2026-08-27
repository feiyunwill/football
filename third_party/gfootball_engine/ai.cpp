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

// 2026-08-26 移除 Boost：shared_ptr 全面改用 std，pybind11 holder 本就是 std::shared_ptr。
// #include <boost/shared_ptr.hpp>
#include <memory>

namespace py = pybind11;
using std::string;

// 2026-04-02 pybind11：使 std::shared_ptr 成为合法 holder（否则 class_<T, std::shared_ptr<T>> 静态断言失败）
PYBIND11_DECLARE_HOLDER_TYPE(T, std::shared_ptr<T>);

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

  // 2026-08-26 确定性调试：以 reference 状态为基准比对当前状态，第一个不一致
  // 字段会在 stdout 打印 Position/Type/Value/Reference（EnvState save 模式）。
  void compare_state_python(const std::string& reference) {
    ContextHolder c(this);
    compare_state(reference);
  }

  // 2026-08-26 位级差异调试：memcmp 级比对，返回全部「判等但字节不同」记录，
  // 用于定位结构体 padding / 非规范 bool 的跨进程字节漂移（见 game_env.hpp）。
  std::vector<std::string> compare_state_bitwise_python(
      const std::string& reference) {
    ContextHolder c(this);
    return compare_state_bitwise(reference);
  }

  // 2026-08-26 canonical 状态摘要：跳过 setValidate(false) 不稳定区段，跨进程可比，
  // 供帧同步 StateHash 校验使用（见 game_env.hpp get_state_digest）。
  py::bytes get_state_digest_python() {
    std::string digest = get_state_digest();
    return py::bytes(digest.data(), digest.size());
  }

  // 2026-08-25 修复（原因）：原签名收 py::bytes 按值拷贝（INCREF）与析构（DECREF）
  // 均落在绑定层 gil_scoped_release 区间内，触发 pybind11 "dec_ref() PyGILState_Check()
  // failure" 断言中止。改为收 std::string：pybind11 的参数转换发生在 call_guard 构造
  // 之前，受保护区间内不再触碰任何 Python 对象。
  void step_with_input_python(std::string buf) {
    ContextHolder c(this);
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

  // 2026-04-02 pybind11：构造器通过 .def(py::init<...>) 注册（不可再作为 class_ 构造参数）
  // py::class_<Position>(m, "Position", py::init<float, float, float, bool>(),
  //                      py::arg("x") = 0.0f, py::arg("y") = 0.0f,
  //                      py::arg("z") = 0.0f, py::arg("env_coords") = false)
  py::class_<Position>(m, "Position")
      .def(py::init<float, float, float, bool>(),
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

  // py::class_<ControllerInfo>(m, "ControllerInfo", py::init<int>())
  py::class_<ControllerInfo>(m, "ControllerInfo")
      .def(py::init<int>())
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
      // 2026-08-25 修复（原因）：pybind11 不自动导出构造器，Boost.Python 时代默认构造
      // 可直接调用，迁移后缺 .def(py::init<>()) 导致 Python 侧 libgame.GameEnv() 报
      // "_gameplayfootball.GameEnv: No constructor defined!"。补注册默认构造。
      .def(py::init<>())
      .def("start_game", &GameEnv_Python::start_game)
      .def("get_info", &GameEnv_Python::get_info)
      // 2026-08-25 修复（原因）：返回 py::bytes 的方法（get_frame/get_state/set_state）
      // 原挂 gil_scoped_release，bytes 的构造与引用计数发生在已释放 GIL 区间内，
      // 触发 pybind11 "dec_ref() PyGILState_Check() failure" 断言中止。移除这三处
      // call_guard（step/step_with_input/reset 返回 void，仍保留释放 GIL）。
      .def("get_frame", &GameEnv_Python::get_frame_python)
      .def("perform_action", &GameEnv_Python::action)
      .def("sticky_action_state", &GameEnv_Python::sticky_action_state)
      .def("step", &GameEnv_Python::step,
           py::call_guard<py::gil_scoped_release>())
      .def("step_with_input", &GameEnv_Python::step_with_input_python,
           py::call_guard<py::gil_scoped_release>())
      .def("get_state", &GameEnv_Python::get_state_python)
      .def("set_state", &GameEnv_Python::set_state_python)
      .def("compare_state", &GameEnv_Python::compare_state_python)
      .def("compare_state_bitwise",
           &GameEnv_Python::compare_state_bitwise_python)
      .def("get_state_digest", &GameEnv_Python::get_state_digest_python)
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

  // py::class_<Vector3>(m, "Vector3", py::init<float, float, float>())
  py::class_<Vector3>(m, "Vector3")
      .def(py::init<float, float, float>())
      .def("__getitem__", &Vector3::GetEnvCoord)
      .def("__setitem__", &Vector3::SetEnvCoord);

  py::class_<GameConfig, std::shared_ptr<GameConfig>>(m, "GameConfig")
      .def_static("make", &GameConfig::make)
      .def_readwrite("render", &GameConfig::render)
      .def_readwrite("physics_steps_per_frame",
                     &GameConfig::physics_steps_per_frame)
      .def_readwrite("render_resolution_x", &GameConfig::render_resolution_x)
      .def_readwrite("render_resolution_y", &GameConfig::render_resolution_y);

  py::class_<ScenarioConfig, std::shared_ptr<ScenarioConfig>>(m, "ScenarioConfig")
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

  // py::class_<FormationEntry>(m, "FormationEntry",
  //                          py::init<float, float, e_PlayerRole, bool, bool>())
  py::class_<FormationEntry>(m, "FormationEntry")
      .def(py::init<float, float, e_PlayerRole, bool, bool>())
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
