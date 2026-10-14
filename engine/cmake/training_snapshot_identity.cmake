# A conservative source/resource/ABI identity; independent of Python bindings.
file(GLOB_RECURSE TRAINING_ID_SOURCES CONFIGURE_DEPENDS RELATIVE "${PROJECT_SOURCE_DIR}"
  "${PROJECT_SOURCE_DIR}/src/*.cpp" "${PROJECT_SOURCE_DIR}/src/*.hpp" "${PROJECT_SOURCE_DIR}/src/*.h")
file(GLOB_RECURSE TRAINING_ID_RESOURCES CONFIGURE_DEPENDS RELATIVE "${PROJECT_SOURCE_DIR}"
  "${PROJECT_SOURCE_DIR}/data/*")
set(TRAINING_ID_FILES ${TRAINING_ID_SOURCES} ${TRAINING_ID_RESOURCES}
  CMakeLists.txt sources.cmake cmake/training_snapshot_identity.cmake)
list(SORT TRAINING_ID_FILES)
set(TRAINING_ID_MANIFEST "training-abi-v1\n${CMAKE_CXX_COMPILER_ID}:${CMAKE_CXX_COMPILER_VERSION}:${CMAKE_CXX_COMPILER_TARGET}\n${CMAKE_SYSTEM_NAME}:${CMAKE_SYSTEM_PROCESSOR}:${CMAKE_SIZEOF_VOID_P}:${CMAKE_CXX_BYTE_ORDER}\n${CMAKE_BUILD_TYPE}:${CMAKE_CXX_STANDARD}:${CMAKE_CXX_FLAGS}:${CMAKE_CXX_FLAGS_RELEASE}:${CMAKE_CXX_FLAGS_DEBUG}:${CMAKE_CXX_FLAGS_RELWITHDEBINFO}:${CMAKE_CXX_FLAGS_MINSIZEREL}:${FOOTBALL_ENABLE_SANITIZERS}:${FOOTBALL_USE_MINGW}:${Boost_VERSION}\n")
foreach(INPUT IN LISTS TRAINING_ID_FILES)
  file(SHA256 "${PROJECT_SOURCE_DIR}/${INPUT}" INPUT_SHA)
  string(APPEND TRAINING_ID_MANIFEST "${INPUT}:${INPUT_SHA}\n")
  # Content changes, not merely glob membership, must trigger regeneration.
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${PROJECT_SOURCE_DIR}/${INPUT}")
endforeach()
string(SHA256 TRAINING_ID_SHA "${TRAINING_ID_MANIFEST}")
list(LENGTH TRAINING_ID_RESOURCES TRAINING_ID_RESOURCES_LENGTH)
# Construct after the resource count is known.
set(TRAINING_ID_HEADER "#pragma once\n#include <array>\n#include <string_view>\nnamespace football::training::identity {\ninline constexpr std::string_view kBuild = \"${TRAINING_ID_SHA}\";\nstruct Resource { std::string_view path; std::string_view sha; };\ninline constexpr std::array<Resource, ${TRAINING_ID_RESOURCES_LENGTH}> kResources = {{\n")
list(SORT TRAINING_ID_RESOURCES)
foreach(INPUT IN LISTS TRAINING_ID_RESOURCES)
  file(SHA256 "${PROJECT_SOURCE_DIR}/${INPUT}" INPUT_SHA)
  string(REGEX REPLACE "^data/" "" RESOURCE_PATH "${INPUT}")
  string(APPEND TRAINING_ID_HEADER "{\"${RESOURCE_PATH}\", \"${INPUT_SHA}\"},\n")
endforeach()
string(APPEND TRAINING_ID_HEADER "}};\n}\n")
file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/generated/training_snapshot_identity.hpp"
  CONTENT "${TRAINING_ID_HEADER}")
