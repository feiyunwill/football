# Copyright 2019 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set(BASE_HEADERS
   src/base/log.hpp
   src/base/utils.hpp
   src/base/properties.hpp
   src/base/sdl_surface.hpp
)

set(BASE_GEOMETRY_HEADERS
   src/base/geometry/aabb.hpp
   src/base/geometry/trianglemeshutils.hpp
   src/base/geometry/plane.hpp
   src/base/geometry/triangle.hpp
   src/base/geometry/line.hpp
)

set(BASE_MATH_HEADERS
   src/base/math/quaternion.hpp
   src/base/math/matrix3.hpp
   src/base/math/matrix4.hpp
   src/base/math/vector3.hpp
   src/base/math/bluntmath.hpp
)

set(BASE_SOURCES
   src/base/sdl_surface.cpp
   src/base/utils.cpp
   src/base/properties.cpp
   src/base/log.cpp
   src/base/geometry/triangle.cpp
   src/base/geometry/line.cpp
   src/base/geometry/trianglemeshutils.cpp
   src/base/geometry/aabb.cpp
   src/base/geometry/plane.cpp
   src/base/math/vector3.cpp
   src/base/math/matrix3.cpp
   src/base/math/bluntmath.cpp
   src/base/math/quaternion.cpp
   src/base/math/matrix4.cpp
)

set(SYSTEMS_COMMON_HEADERS
   src/systems/isystem.hpp
   src/systems/isystemobject.hpp
)

# 2026-09-13: sample UI input at bounded render work opportunities.
# set(SYSTEMS_GRAPHICS_HEADERS
set(SYSTEMS_GRAPHICS_HEADERS
   src/systems/graphics/render_service.hpp
   src/systems/graphics/graphics_task.hpp
   src/systems/graphics/graphics_scene.hpp
   src/systems/graphics/graphics_object.hpp
   src/systems/graphics/graphics_system.hpp
)

set(SYSTEMS_GRAPHICS_OBJECTS_HEADERS
   src/systems/graphics/objects/graphics_overlay2d.hpp
   src/systems/graphics/objects/graphics_camera.hpp
   src/systems/graphics/objects/graphics_light.hpp
   src/systems/graphics/objects/graphics_geometry.hpp
)

set(SYSTEMS_GRAPHICS_RESOURCES_HEADERS
   src/systems/graphics/resources/vertexbuffer.hpp
   src/systems/graphics/resources/texture.hpp
)

set(SYSTEMS_GRAPHICS_RENDERING_HEADERS
   src/systems/graphics/rendering/interface_renderer3d.hpp
   src/systems/graphics/rendering/opengl_renderer3d.hpp
)

# 2026-09-13: sample UI input at bounded render work opportunities.
# set(SYSTEMS_GRAPHICS_SOURCES
set(SYSTEMS_GRAPHICS_SOURCES
   src/systems/graphics/render_service.cpp
   src/systems/graphics/graphics_object.cpp
   src/systems/graphics/graphics_task.cpp
   src/systems/graphics/objects/graphics_geometry.cpp
   src/systems/graphics/objects/graphics_camera.cpp
   src/systems/graphics/objects/graphics_light.cpp
   src/systems/graphics/objects/graphics_overlay2d.cpp
   src/systems/graphics/graphics_scene.cpp
   src/systems/graphics/resources/vertexbuffer.cpp
   src/systems/graphics/resources/texture.cpp
   src/systems/graphics/rendering/opengl_renderer3d.cpp
   src/systems/graphics/graphics_system.cpp
)

set(LOADERS_HEADERS
   src/loaders/aseloader.hpp
   src/loaders/imageloader.hpp
)

set(LOADERS_SOURCES
   src/loaders/imageloader.cpp
   src/loaders/aseloader.cpp
)

set(TYPES_HEADERS
   src/types/subject.hpp
   src/types/spatial.hpp
   src/types/resource.hpp
   src/types/material.hpp
   src/types/observer.hpp
   src/types/interpreter.hpp
   src/types/refcounted.hpp
   src/types/command.hpp
   src/types/loader.hpp
   src/types/messagequeue.hpp
)

set(TYPES_SOURCES
   src/types/spatial.cpp
   src/types/refcounted.cpp
   src/types/observer.cpp
   src/types/command.cpp
)

set(SCENE_HEADERS
   src/scene/scene.hpp
   src/scene/iscene.hpp
   src/scene/object.hpp
   src/scene/objectfactory.hpp
)

set(SCENE2D_HEADERS
   src/scene/scene2d/scene2d.hpp
)

set(SCENE_OBJECTS_HEADERS
   src/scene/objects/skybox.hpp
   src/scene/objects/geometry.hpp
   src/scene/objects/light.hpp
   src/scene/objects/image2d.hpp
   src/scene/objects/camera.hpp
)

set(SCENE3D_HEADERS
   src/scene/scene3d/scene3d.hpp
   src/scene/scene3d/node.hpp
)

set(SCENE_RESOURCES_HEADERS
   src/scene/resources/geometrydata.hpp
   src/scene/resources/surface.hpp
)

set(SCENE_SOURCES
   src/scene/objectfactory.cpp
   src/scene/scene2d/scene2d.cpp
   src/scene/scene.cpp
   src/scene/objects/image2d.cpp
   src/scene/objects/light.cpp
   src/scene/objects/geometry.cpp
   src/scene/objects/skybox.cpp
   src/scene/objects/camera.cpp
   src/scene/scene3d/scene3d.cpp
   src/scene/scene3d/node.cpp
   src/scene/object.cpp
   src/scene/resources/surface.cpp
   src/scene/resources/geometrydata.cpp
)

set(MANAGERS_HEADERS
   src/managers/resourcemanager.hpp
)

set(UTILS_HEADERS
   src/utils/animation.hpp
   src/utils/objectloader.hpp
   src/utils/xmlloader.hpp
   src/utils/splitgeometry.hpp
   src/utils/orbitcamera.hpp
)

set(UTILS_EXT_HEADERS
   src/utils/animationextensions/animationextension.hpp
   src/utils/animationextensions/footballanimationextension.hpp
)

set(UTILS_SOURCES
   src/utils/orbitcamera.cpp
   src/utils/animation.cpp
   src/utils/splitgeometry.cpp
   src/utils/objectloader.cpp
   src/utils/xmlloader.cpp
   src/utils/animationextensions/footballanimationextension.cpp
)

set(UTILS_GUI2_HEADERS
   src/utils/gui2/windowmanager.hpp
   src/utils/gui2/page.hpp
   src/utils/gui2/style.hpp
   src/utils/gui2/guitask.hpp
   src/utils/gui2/view.hpp
)

set(UTILS_GUI2_WIDGETS_HEADERS
   src/utils/gui2/widgets/image.hpp
   src/utils/gui2/widgets/caption.hpp
   src/utils/gui2/widgets/frame.hpp
   src/utils/gui2/widgets/root.hpp
)

set(UTILS_GUI2_SOURCES
   src/utils/gui2/style.cpp
   src/utils/gui2/widgets/caption.cpp
   src/utils/gui2/widgets/image.cpp
   src/utils/gui2/widgets/root.cpp
   src/utils/gui2/widgets/frame.cpp
   src/utils/gui2/view.cpp
   src/utils/gui2/windowmanager.cpp
   src/utils/gui2/guitask.cpp
   src/utils/gui2/page.cpp
)

set(BLUNTED_CORE_HEADERS
   src/defines.hpp
   src/blunted.hpp
)

set(BLUNTED_CORE_SOURCES
   src/blunted.cpp
)


###### SEPARATION

# 2026-09-09: separate the Python adapter and correct swapped header/source lists.
# set(AI_HEADERS
#   ai.cpp
#   src/ai/ai_keyboard.hpp
#   src/ai/ai_tactics.hpp
#   src/game_env.cpp
# )
#
# set(AI_SOURCES
#   ai.hpp
#   src/ai/ai_keyboard.cpp
#   src/ai/ai_tactics.cpp
#   src/game_env.hpp
# )
#
set(PYTHON_BINDING_SOURCES ai.cpp)
# 2026-09-09: native acceptance links the same engine as shipping executables.
set(ENGINE_STATE_CONTRACT_SOURCES tests/engine_state_contract.cpp)
set(ENGINE_LIFETIME_CONTRACT_SOURCES tests/engine_lifetime_contract.cpp)
set(AI_HEADERS
  src/ai/ai_keyboard.hpp
  src/ai/ai_tactics.hpp
  src/game_env.hpp
)
set(AI_SOURCES
  src/ai/ai_keyboard.cpp
  src/ai/ai_tactics.cpp
  src/game_env.cpp
)

set(CLIENT_SOURCES
   src/client.cpp
   src/game_env.hpp
)

set(FRAME_SYNC_HEADERS
   # 2026-09-09: shared reconciliation, hashing, and production lobby.
   src/frame_sync/default_scenario.hpp
   src/frame_sync/frame_simulation.hpp
   src/frame_sync/state_hash.hpp
   src/frame_sync/lobby_server.hpp
   src/frame_sync/protocol.hpp
   src/frame_sync/input_codec.hpp
   src/frame_sync/deterministic_prng.hpp
   src/frame_sync/interpolator.hpp
   src/frame_sync/state_compression.hpp
   src/frame_sync/jitter_stats.hpp
   src/frame_sync/ux_optimizer.hpp
   src/frame_sync/state_delta_codec.hpp
   src/frame_sync/prediction_accuracy_tracker.hpp
   src/frame_sync/adaptive_prediction_cap.hpp
   src/frame_sync/replay_system.hpp
   src/frame_sync/adaptive_jitter_buffer.hpp
   src/frame_sync/latency_compensator.hpp
   src/frame_sync/state_snapshot_codec.hpp
   src/frame_sync/spectator.hpp
   src/frame_sync/network_diagnostics.hpp
   src/frame_sync/lobby_protocol.hpp
   src/frame_sync/room_manager.hpp
)

set(FRAME_SYNC_SOURCES
   src/frame_sync/input_codec.cpp
)

set(CORE_HEADERS
   src/cmake/backtrace.h
   src/cmake/file.h
   src/gamedefines.hpp
   src/utils.hpp
   src/main.hpp
   src/gametask.hpp
   src/misc/hungarian.h
   ${FRAME_SYNC_HEADERS}
)

set(CORE_SOURCES
   src/cmake/backtrace.cpp
   src/cmake/file.cpp
   src/misc/perlin.cpp
   src/misc/hungarian.cpp
   src/gametask.cpp
   src/utils.cpp
   src/main.cpp
   src/gamedefines.cpp
   src/defines.cpp
   ${FRAME_SYNC_SOURCES}
)

set(GAME_HEADERS
   src/ecs/entity.hpp
   src/ecs/transform.hpp
   src/ecs/world.hpp
   src/ecs/query.hpp
   src/ecs/system_batch.hpp
   src/onthepitch/ecs_components.hpp
   src/onthepitch/ecs_systems.hpp
   src/onthepitch/ecs_direct_systems.hpp
   src/onthepitch/humangamer.hpp
   src/onthepitch/officials.hpp
   src/onthepitch/player/humanoid/humanoidbase.hpp
   src/onthepitch/player/humanoid/humanoid.hpp
   src/onthepitch/player/humanoid/animcollection.hpp
   src/onthepitch/player/humanoid/humanoid_utils.hpp
   src/onthepitch/player/playerofficial.hpp
   src/onthepitch/player/playerbase.hpp
   src/onthepitch/player/player.hpp
   src/onthepitch/player/controller/icontroller.hpp
   src/onthepitch/player/controller/elizacontroller.hpp
   src/onthepitch/player/controller/humancontroller.hpp
   src/onthepitch/player/controller/playercontroller.hpp
   src/onthepitch/player/controller/strategies/strategy.hpp
   src/onthepitch/player/controller/strategies/offtheball/default_off.hpp
   src/onthepitch/player/controller/strategies/offtheball/default_def.hpp
   src/onthepitch/player/controller/strategies/offtheball/default_mid.hpp
   src/onthepitch/player/controller/strategies/offtheball/goalie_default.hpp
   src/onthepitch/player/controller/refereecontroller.hpp
   src/onthepitch/referee.hpp
   src/onthepitch/ball.hpp
   src/onthepitch/team.hpp
   src/onthepitch/match.hpp
   src/onthepitch/AIsupport/AIfunctions.hpp
   src/onthepitch/AIsupport/mentalimage.hpp
   src/onthepitch/teamAIcontroller.hpp
   src/onthepitch/proceduralpitch.hpp
)

set(GAME_SOURCES
   src/onthepitch/ecs_systems.cpp
   src/onthepitch/ecs_direct_systems.cpp
   src/ecs/system_batch.cpp
   src/onthepitch/officials.cpp
   src/onthepitch/player/humanoid/humanoid_utils.cpp
   src/onthepitch/player/humanoid/animcollection.cpp
   src/onthepitch/player/humanoid/humanoidbase.cpp
   src/onthepitch/player/humanoid/humanoid.cpp
   src/onthepitch/player/playerofficial.cpp
   src/onthepitch/player/player.cpp
   src/onthepitch/player/playerbase.cpp
   src/onthepitch/player/controller/playercontroller.cpp
   src/onthepitch/player/controller/humancontroller.cpp
   src/onthepitch/player/controller/icontroller.cpp
   src/onthepitch/player/controller/refereecontroller.cpp
   src/onthepitch/player/controller/elizacontroller.cpp
   src/onthepitch/player/controller/strategies/strategy.cpp
   src/onthepitch/player/controller/strategies/offtheball/default_mid.cpp
   src/onthepitch/player/controller/strategies/offtheball/default_off.cpp
   src/onthepitch/player/controller/strategies/offtheball/default_def.cpp
   src/onthepitch/player/controller/strategies/offtheball/goalie_default.cpp
   src/onthepitch/humangamer.cpp
   src/onthepitch/ball.cpp
   src/onthepitch/match.cpp
   src/onthepitch/referee.cpp
   src/onthepitch/AIsupport/mentalimage.cpp
   src/onthepitch/AIsupport/AIfunctions.cpp
   src/onthepitch/proceduralpitch.cpp
   src/onthepitch/team.cpp
   src/onthepitch/teamAIcontroller.cpp
)

set(MENU_HEADERS
   src/menu/pagefactory.hpp
   src/menu/startmatch/loadingmatch.hpp
   src/menu/menutask.hpp
   src/menu/ingame/gamepage.hpp
   src/menu/ingame/scoreboard.hpp
   src/menu/ingame/radar.hpp
   src/menu/mainmenu.hpp
   src/menu/settings.hpp
   src/menu/pausemenu.hpp
)

set(MENU_SOURCES
   src/menu/startmatch/loadingmatch.cpp
   src/menu/pagefactory.cpp
   src/menu/menutask.cpp
   src/menu/ingame/radar.cpp
   src/menu/ingame/gamepage.cpp
   src/menu/ingame/scoreboard.cpp
   src/menu/mainmenu.cpp
   src/menu/settings.cpp
   src/menu/pausemenu.cpp
)

set(DATA_HEADERS
   src/data/matchdata.hpp
   src/data/teamdata.hpp
   src/data/playerdata.hpp
)

set(DATA_SOURCES
   src/data/matchdata.cpp
   src/data/playerdata.cpp
   src/data/teamdata.cpp
)

# 2026-09-09: snapshot version/integrity boundary.
set(SNAPSHOT_CONTRACT_HEADERS src/base/snapshot_envelope.hpp)
set(ENGINE_SIMULATION_CONTRACT_SOURCES tests/engine_simulation_contract.cpp)
list(APPEND CORE_HEADERS ${SNAPSHOT_CONTRACT_HEADERS})

# 2026-09-09: architecture acceptance and the production SDL event handler.
set(ENGINE_ARCHITECTURE_CONTRACT_SOURCES tests/engine_architecture_contract.cpp)
list(APPEND CORE_HEADERS src/frame_sync/standalone_controls.hpp)

# 2026-09-09: repeatable real-engine performance measurements.
set(ENGINE_MATCH_BENCHMARK_SOURCES tests/engine_match_benchmark.cpp)
# 2026-09-13: fixed long-match sampling; preserve the immutable short fixture.
set(ENGINE_SOAK_BENCHMARK_SOURCES tests/engine_soak_benchmark.cpp)
set(ENGINE_HOTSPOT_PROFILE_SOURCES tests/engine_hotspot_profile.cpp)
set(ENGINE_ANIMATION_QUERY_CONTRACT_SOURCES tests/engine_animation_query_contract.cpp)

# 2026-09-13: frozen pre-optimization oracle is included by the native test.
set(ENGINE_AI_REACHABILITY_CONTRACT_SOURCES tests/engine_ai_reachability_contract.cpp)
set(ECS_QUERY_CONTRACT_TEST_SOURCES tests/ecs_query_contract_test.cpp)
list(APPEND CORE_HEADERS src/frame_sync/memory_budget.hpp)
set(MEMORY_BUDGET_TEST_SOURCES tests/memory_budget_test.cpp)
set(RELIABLE_UDP_BUDGET_TEST_SOURCES tests/reliable_udp_budget_test.cpp)
set(ENGINE_MEMORY_CONTRACT_SOURCES tests/engine_memory_contract.cpp)
list(APPEND CORE_HEADERS src/frame_sync/bounded_tcp_writer.hpp
  src/frame_sync/tcp_frame_server.hpp)
set(BOUNDED_TCP_WRITER_TEST_SOURCES tests/bounded_tcp_writer_test.cpp)
set(LOBBY_CAPACITY_TEST_SOURCES tests/lobby_capacity_test.cpp)
set(LOBBY_CLIENT_CAPACITY_TEST_SOURCES tests/lobby_client_capacity_test.cpp)
set(TCP_FRAME_SERVER_TEST_SOURCES tests/tcp_frame_server_test.cpp)

# 2026-09-09: bounded integrated TCP server and real GameEnv bot observation bridge.
list(APPEND CORE_HEADERS src/frame_sync/engine_tcp_server.hpp src/frame_sync/engine_tcp_bridge.hpp)
set(ENGINE_TCP_CONTRACT_SOURCES tests/engine_tcp_contract.cpp)

# 2026-09-09: actual bounded queue/render/log contracts.
set(ENGINE_RUNTIME_CONTRACT_SOURCES tests/engine_runtime_contract.cpp)

# 2026-09-09: shared bounded native TCP transport and whole-frame client.
list(APPEND CORE_HEADERS src/frame_sync/tcp_client_transport.hpp src/frame_sync/tcp_frame_client.hpp)
set(TCP_CLIENT_CAPACITY_TEST_SOURCES tests/tcp_client_capacity_test.cpp)
set(ENGINE_TCP_CLIENT_CONTRACT_SOURCES tests/engine_tcp_client_contract.cpp)
list(APPEND CORE_HEADERS src/frame_sync/reconnecting_client.hpp)

# 2026-09-10: actual skeleton/card interpolation, appearance and snapshot isolation.
set(ENGINE_RENDER_POSE_CONTRACT_SOURCES tests/engine_render_pose_contract.cpp)
# 2026-09-13: actual RGB capture on/off, packing and state isolation.
set(ENGINE_FRAME_CAPTURE_CONTRACT_SOURCES tests/engine_frame_capture_contract.cpp)

# 2026-09-10: bounded native replay streaming and checked filesystem publication.
list(APPEND CORE_HEADERS src/frame_sync/replay_file.hpp)
set(REPLAY_FILE_TEST_SOURCES tests/replay_file_test.cpp)

# 2026-09-13: shared native replay directory admission and crash recovery.
list(APPEND CORE_HEADERS src/frame_sync/replay_directory.hpp)
set(REPLAY_DIRECTORY_TEST_SOURCES tests/replay_directory_test.cpp)

# 2026-09-13: permanent shared input, scheduling, presentation and authority regressions.
set(ENGINE_NATIVE_INPUT_BUFFER_CONTRACT_SOURCES tests/engine_native_input_buffer_contract.cpp)
set(ENGINE_NATIVE_INPUT_GAMEENV_CONTRACT_SOURCES tests/engine_native_input_gameenv_contract.cpp)
set(ENGINE_NATIVE_INPUT_ADMISSION_CONTRACT_SOURCES tests/engine_native_input_admission_contract.cpp)
set(ENGINE_NATIVE_PRESENTATION_CONTRACT_SOURCES tests/engine_native_presentation_contract.cpp)
set(ENGINE_SERVER_INPUT_WINDOW_CONTRACT_SOURCES tests/engine_server_input_window_contract.cpp)
set(ENGINE_NATIVE_CLOCK_REPLAY_CONTRACT_SOURCES tests/engine_native_clock_replay_contract.cpp)
set(ENGINE_NATIVE_SDL_INPUT_CONTRACT_SOURCES tests/engine_native_sdl_input_contract.cpp)
set(ENGINE_NATIVE_WINDOW_TRACE_SOURCES tests/engine_native_window_trace.cpp)

# 2026-09-13: native product simulation and replay contract.
set(ENGINE_NATIVE_MATCH_CONTRACT_SOURCES tests/engine_native_match_contract.cpp)
list(APPEND CORE_HEADERS src/frame_sync/native_match_contract.hpp src/frame_sync/native_match_scenario.hpp src/frame_sync/native_match_replay.hpp)

# 2026-09-13: publication before native engine work.
list(APPEND CORE_HEADERS src/frame_sync/native_input_publication.hpp)

# 2026-09-13: native transport ownership and concurrent sampled input contract.
set(ENGINE_NATIVE_TRANSPORT_PUMP_CONTRACT_SOURCES tests/engine_native_transport_pump_contract.cpp)
list(APPEND CORE_HEADERS src/frame_sync/native_shared_input.hpp src/frame_sync/native_transport_pump.hpp)

# 2026-09-13: validate cooperative render service ownership and timing.
set(ENGINE_RENDER_SERVICE_CONTRACT_SOURCES tests/engine_render_service_contract.cpp)

# 2026-09-13: deterministic local input timeline and fixed-deadline contract.
set(ENGINE_NATIVE_INPUT_TIMELINE_CONTRACT_SOURCES tests/engine_native_input_timeline_contract.cpp)
list(APPEND CORE_HEADERS src/frame_sync/native_input_timeline.hpp)

# 2026-09-13: main-thread UI service and synchronized local observation ownership.
set(ENGINE_NATIVE_UI_OWNER_CONTRACT_SOURCES tests/engine_native_ui_owner_contract.cpp)
list(APPEND CORE_HEADERS src/frame_sync/native_ui_owner.hpp src/frame_sync/native_shared_timeline.hpp)

# 2026-09-13: independent native input cadence and its permanent contract.
set(ENGINE_NATIVE_PUBLICATION_CLOCK_CONTRACT_SOURCES tests/engine_native_publication_clock_contract.cpp)
list(APPEND CORE_HEADERS src/frame_sync/native_publication_clock.hpp)

# 2026-09-13: real native AI takeover survives temporary player deselection.
set(ENGINE_NATIVE_BOT_SELECTION_CONTRACT_SOURCES tests/engine_native_bot_selection_contract.cpp)

# 2026-09-14: register the real GameEnv touch-decision regression.
set(ENGINE_AI_TOUCH_CONTRACT_SOURCES tests/engine_ai_touch_contract.cpp)

# 2026-09-14: shared tactical state, role decisions and real takeover replay.
set(ENGINE_AI_TACTICS_CONTRACT_SOURCES tests/engine_ai_tactics_contract.cpp)
set(ENGINE_AI_TACTICS_ROLES_CONTRACT_SOURCES tests/engine_ai_tactics_roles_contract.cpp)
set(ENGINE_AI_TACTICAL_STATE_CONTRACT_SOURCES tests/engine_ai_tactical_state_contract.cpp)
set(ENGINE_NATIVE_TACTICS_REPLAY_CONTRACT_SOURCES tests/engine_native_tactics_replay_contract.cpp)

# 2026-09-14: native recovery credentials, explicit wire framing and bounded snapshot transfer.
list(APPEND CORE_HEADERS
  src/frame_sync/native_recovery_credentials.hpp
  src/frame_sync/native_recovery_wire.hpp
  src/frame_sync/native_recovery_transfer.hpp)
set(ENGINE_NATIVE_RECOVERY_TCP_CONTRACT_SOURCES tests/engine_native_recovery_tcp_contract.cpp)
set(FOOTBALL_NATIVE_RECOVERY_SOURCES src/frame_sync/native_recovery_digest.cpp)

# 2026-09-15: register the owned resource-loading callback in the shared engine.
list(APPEND CORE_SOURCES src/game_load.cpp)
list(APPEND CORE_HEADERS src/game_load.hpp
  src/frame_sync/native_recovery_replay.hpp
  src/frame_sync/native_sdl_thread_state.hpp)
set(ENGINE_LOADING_CONTRACT_TARGETS
  engine_prepared_lifecycle_contract
  engine_tracker_owner_contract
  engine_loading_cancellation_contract
  engine_loading_seat_contract
  engine_loading_tcp_contract
  engine_loading_client_drain_contract)

# 2026-09-22: native asset parser bounds and ownership regression.
set(ENGINE_ASE_PARSER_CONTRACT_SOURCES tests/engine_ase_parser_contract.cpp)

# 2026-09-22: bounded resource reads preserve legacy file semantics.
set(ENGINE_FILE_READ_CONTRACT_SOURCES tests/engine_file_read_contract.cpp)

# 2026-09-24: native reliable UDP product transport and permanent regressions.
list(APPEND CORE_HEADERS
  src/frame_sync/native_udp_bootstrap.hpp
  src/frame_sync/native_udp_dialer.hpp
  src/frame_sync/native_udp_listener.hpp
  src/frame_sync/native_udp_stream.hpp
)
set(NATIVE_UDP_TEST_TARGETS
  native_udp_bootstrap_test
  native_udp_window_test
  native_udp_stream_test
  native_udp_listener_test
  native_udp_dialer_test
  native_udp_terminal_drain_test
)
