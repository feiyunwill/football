#include "src/training/native_training.hpp"
#include "src/training/training_snapshot.hpp"
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <cstring>

namespace py = pybind11;
namespace {
// 2026-10-14: shape comes from contiguous C++ storage, never a padded row struct.
// py::array_t<float> observations(const std::vector<football::training::Simple115>& rows) {
py::array_t<float> observations(const football::training::ObservationBuffer& rows) {
  py::array_t<float> result({static_cast<py::ssize_t>(rows.size()), static_cast<py::ssize_t>(rows.columns())});
  if (!rows.buffer().empty()) std::memcpy(result.mutable_data(), rows.buffer().data(), rows.buffer().size_bytes());
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
      // 2026-10-14: optional native four-frame history.
      // .def(py::init<int, int, bool, bool, bool>(), py::arg("width") = 1280,
      .def(py::init<int, int, bool, bool, bool, bool>(), py::arg("width") = 1280,
           py::arg("height") = 720, py::arg("builtin_ai_action") = false,
           py::arg("fixed_positions") = true, py::arg("checkpoint_rewards") = false,
           py::arg("stacked") = false)
      .def("reset", [](NativeTrainingEnv& env, ScenarioConfig& scenario, int physics_steps) {
        // 2026-10-14: released work owns a bounded scene value, not mutable Python storage.
        if (scenario.left_team.size() > football::training::kMaxTrainingAgents ||
            scenario.right_team.size() > football::training::kMaxTrainingAgents)
          throw py::value_error("Training teams must contain at most eleven players");
        ScenarioConfig snapshot = scenario;
        // std::vector<football::training::Simple115> result;
        football::training::ObservationBuffer result;
        {
          py::gil_scoped_release release;
          // result = env.reset(scenario, physics_steps);
          result = env.reset(snapshot, physics_steps);
        }
        return observations(result);
      }, py::arg("scenario"), py::arg("physics_steps") = 10)
      .def("step", [](NativeTrainingEnv& env, const std::vector<int>& actions) {
        const bool profiling = env.profiling_enabled();
        football::training::TrainingTransition result;
        {
          py::gil_scoped_release release;
          result = env.step(actions);
        }
        const auto output_start = profiling ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
        py::array_t<float> rewards(result.rewards.size());
        if (!result.rewards.empty())
          std::memcpy(rewards.mutable_data(), result.rewards.data(), result.rewards.size() * sizeof(float));
        auto tuple = py::make_tuple(observations(result.observations), rewards, result.terminated, result.score_reward);
        if (profiling) env.record_binding_output(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - output_start).count());
        return tuple;
      })
      .def("step_many", [](NativeTrainingEnv& env, const py::array& actions) {
        const bool profiling = env.profiling_enabled();
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
        const auto output_start = profiling ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
        const auto steps = static_cast<py::ssize_t>(result.terminated.size());
        const auto players = static_cast<py::ssize_t>(result.players);
        // py::array_t<float> rows({steps, players, py::ssize_t{115}});
        py::array_t<float> rows({steps, players, static_cast<py::ssize_t>(result.observations.columns())});
        py::array_t<float> rewards({steps, players});
        py::array_t<bool> terminated(steps);
        py::array_t<int> scores(steps);
        // std::memcpy(rows.mutable_data(), result.observations.data(), result.observations.size() * sizeof(result.observations[0]));
        std::memcpy(rows.mutable_data(), result.observations.buffer().data(), result.observations.buffer().size_bytes());
        std::memcpy(rewards.mutable_data(), result.rewards.data(), result.rewards.size() * sizeof(float));
        std::memcpy(scores.mutable_data(), result.score_rewards.data(), result.score_rewards.size() * sizeof(int));
        for (py::ssize_t i = 0; i < steps; ++i) terminated.mutable_data()[i] = result.terminated[i] != 0;
        auto tuple = py::make_tuple(rows, rewards, terminated, scores);
        if (profiling) env.record_binding_output(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - output_start).count());
        return tuple;
      }, py::arg("actions").noconvert())
      .def("get_state_digest", [](NativeTrainingEnv& env) {
        std::string result;
        {
          py::gil_scoped_release release;
          result = env.get_state_digest();
        }
        return py::bytes(result);
      })
      .def("get_state", [](NativeTrainingEnv& env) {
        std::string result;
        { py::gil_scoped_release release; result = env.get_state(); }
        return py::bytes(result);
      })
      .def("set_state", [](NativeTrainingEnv& env, const py::bytes& bytes) {
        // Check size before copying; released work never refers to Python storage.
        const auto length = PyBytes_Size(bytes.ptr());
        if (length < 0 || static_cast<size_t>(length) > football::training::snapshot::kMaxBytes)
          throw py::value_error("Training snapshot exceeds byte budget");
        std::string owned = bytes;
        py::gil_scoped_release release;
        env.set_state(owned);
      }, py::arg("state").noconvert())
      .def("is_closed", &NativeTrainingEnv::is_closed, py::call_guard<py::gil_scoped_release>())
      .def("enable_profiling", [](NativeTrainingEnv& env, const py::object& enabled) {
        if (!PyBool_Check(enabled.ptr())) throw py::type_error("Profiling flag must be bool");
        const bool flag = enabled.cast<bool>();
        py::gil_scoped_release release; env.enable_profiling(flag);
      })
      .def("get_profile", [](NativeTrainingEnv& env) {
        football::training::TrainingProfile p;
        { py::gil_scoped_release release; p = env.get_profile(); }
        py::dict result;
        result["transitions"] = p.transitions; result["engine_calls"] = p.engine_calls;
        result["action_ns"] = p.action_ns; result["engine_ns"] = p.engine_ns; result["info_ns"] = p.info_ns;
        result["transition_ns"] = p.transition_ns; result["encoding_ns"] = p.encoding_ns; result["reward_ns"] = p.reward_ns;
        result["binding_output_ns"] = p.binding_output_ns;
        return result;
      })
      .def("close", &NativeTrainingEnv::close, py::call_guard<py::gil_scoped_release>());
}
