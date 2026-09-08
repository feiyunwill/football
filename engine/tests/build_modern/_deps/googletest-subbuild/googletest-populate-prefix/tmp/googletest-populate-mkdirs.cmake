# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file Copyright.txt or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION ${CMAKE_VERSION}) # this file comes with cmake

# If CMAKE_DISABLE_SOURCE_CHANGES is set to true and the source directory is an
# existing directory in our source tree, calling file(MAKE_DIRECTORY) on it
# would cause a fatal error, even though it would be a no-op.
if(NOT EXISTS "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-src")
  file(MAKE_DIRECTORY "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-src")
endif()
file(MAKE_DIRECTORY
  "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-build"
  "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-subbuild/googletest-populate-prefix"
  "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-subbuild/googletest-populate-prefix/tmp"
  "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-subbuild/googletest-populate-prefix/src/googletest-populate-stamp"
  "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-subbuild/googletest-populate-prefix/src"
  "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-subbuild/googletest-populate-prefix/src/googletest-populate-stamp"
)

set(configSubDirs )
foreach(subDir IN LISTS configSubDirs)
    file(MAKE_DIRECTORY "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-subbuild/googletest-populate-prefix/src/googletest-populate-stamp/${subDir}")
endforeach()
if(cfgdir)
  file(MAKE_DIRECTORY "/home/zuchangqu/project/football/engine/tests/build_modern/_deps/googletest-subbuild/googletest-populate-prefix/src/googletest-populate-stamp${cfgdir}") # cfgdir has leading slash
endif()
