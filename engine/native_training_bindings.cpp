#include "src/training/native_training.hpp"
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <cstring>

namespace py = pybind11;
namespace {
py::array_t<float> observations(const std::vector<football::training::Simple115>& rows) {
  static_assert(sizeof(football::training::Simple115) == 115 * sizeof(float));
  py::array_t<float> result({static_cast<py::ssize_t>(rows.size()), py::ssize_t{115}});
  if (!rows.empty()) std::memcpy(result.mutable_data(), rows.data(), rows.size() * sizeof(rows[0]));
  return result;
}
}  // namespace

void BindNativeTraining(py::module_& module) {
  using football::training::NativeTrainingEnv;
  py::class_<NativeTrainingEnv>(module, "NativeTrainingEnv")
      // 2026-10-14: the fourth optional argument selects compact simple115 packing.
      // .def(py::init<int, int, bool>(), py::arg("width") = 1280,
      //      py::arg("height") = 720, py::arg("builtin_ai_action") = false)
      // 2026-10-14: optional dense checkpoint shaping uses native per-agent state.
      // .def(py::init<int, int, bool, bool>(), py::arg("width") = 1280,
      .def(py::init<int, int, bool, bool, bool>(), py::arg("width") = 1280,
           py::arg("height") = 720, py::arg("builtin_ai_action") = false,
           py::arg("fixed_positions") = true, py::arg("checkpoint_rewards") = false)
      .def("reset", [](NativeTrainingEnv& env, ScenarioConfig& scenario, int physics_steps) {
        std::vector<football::training::Simple115> result;
        {
          py::gil_scoped_release release;
          result = env.reset(scenario, physics_steps);
        }
        return observations(result);
      }, py::arg("scenario"), py::arg("physics_steps") = 10)
      .def("step", [](NativeTrainingEnv& env, const std::vector<int>& actions) {
        football::training::TrainingTransition result;
        {
          py::gil_scoped_release release;
          result = env.step(actions);
        }
        py::array_t<float> rewards(result.rewards.size());
        if (!result.rewards.empty())
          std::memcpy(rewards.mutable_data(), result.rewards.data(), result.rewards.size() * sizeof(float));
        return py::make_tuple(observations(result.observations), rewards,
                              result.terminated, result.score_reward);
      })
      .def("step_many", [](NativeTrainingEnv& env, const py::array& actions) {
        const char kind = actions.dtype().kind();
        if ((kind != 'i' && kind != 'u') || actions.ndim() != 2 ||
            actions.shape(0) < 1 || actions.shape(0) > football::training::kMaxTrainingBatchSteps ||
            actions.shape(1) < 1 || actions.shape(1) > 11)
          throw py::value_error("Expected an integer action array with shape [1..256, 1..11]");
        auto values = py::array_t<int64_t, py::array::c_style | py::array::forcecast>::ensure(actions);
        if (!values) throw py::value_error("Cannot read integer actions");
        // Copy and validate while holding the GIL; released work owns no Python memory.
        std::vector<int> input(values.size());
        for (py::ssize_t i = 0; i < values.size(); ++i) {
          const auto value = values.data()[i];
          if (value < 0 || value >= 20) throw py::value_error("Action outside training action set");
          input[i] = static_cast<int>(value);
        }
        football::training::TrainingBatch result;
        const auto requested_steps = static_cast<size_t>(actions.shape(0));
        {
          py::gil_scoped_release release;
          result = env.step_many(input, requested_steps);
        }
        const auto steps = static_cast<py::ssize_t>(result.terminated.size());
        const auto players = static_cast<py::ssize_t>(result.players);
        py::array_t<float> rows({steps, players, py::ssize_t{115}});
        py::array_t<float> rewards({steps, players});
        py::array_t<bool> terminated(steps);
        py::array_t<int> scores(steps);
        std::memcpy(rows.mutable_data(), result.observations.data(), result.observations.size() * sizeof(result.observations[0]));
        std::memcpy(rewards.mutable_data(), result.rewards.data(), result.rewards.size() * sizeof(float));
        std::memcpy(scores.mutable_data(), result.score_rewards.data(), result.score_rewards.size() * sizeof(int));
        for (py::ssize_t i = 0; i < steps; ++i) terminated.mutable_data()[i] = result.terminated[i] != 0;
        return py::make_tuple(rows, rewards, terminated, scores);
      }, py::arg("actions").noconvert())
      .def("get_state_digest", [](NativeTrainingEnv& env) {
        std::string result;
        {
          py::gil_scoped_release release;
          result = env.get_state_digest();
        }
        return py::bytes(result);
      })
      .def("close", &NativeTrainingEnv::close, py::call_guard<py::gil_scoped_release>());
}
