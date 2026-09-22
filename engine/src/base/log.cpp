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

// written by bastiaan konings schuiling 2008 - 2014
// this work is public domain. the code is undocumented, scruffy, untested, and should generally not be used for anything important.
// i do not offer support, so don't ask. to be used for inspiration :)

#include <chrono>
#include "log.hpp"
#include "../main.hpp"
#include "../defines.hpp"

#include <iostream>
#include <fstream>
#include <string>

// 2026-09-09: bounded records, reentrant timestamp, defined fatal termination.
// std::string now() {
//   auto now = std::chrono::system_clock::now();
//   time_t tt;
//   tt = std::chrono::system_clock::to_time_t(now);
//   return ctime(&tt);
// }
//
// namespace blunted {
//
// void Log(e_LogType logType, std::string className, std::string methodName,
//          std::string message) {
//   std::string logTypeString;
//
//   switch (logType) {
//     case e_Warning:
//       logTypeString = "Warning";
//       break;
//     case e_Error:
//       logTypeString = "ERROR";
//       break;
//     case e_FatalError:
//       logTypeString = "FATAL ERROR !!! N00000 !!!";
//       break;
//   }
//
//   std::string date = now();
//   date = date.substr(0, date.length() - 1);
//   printf("%s [%s] in [%s::%s]: %s\n", date.c_str(), logTypeString.c_str(),
//          className.c_str(), methodName.c_str(), message.c_str());
//
//   if (logType == e_FatalError) {
//     print_stacktrace();
//     int *foo = (int *)-1;  // make a bad pointer
//     printf("%d\n", *foo);  // causes segfault
//     exit(1);
//   }
// }
// }

std::string now() {
  const auto time = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
  char buffer[32] = {};
#ifdef _WIN32
  if (ctime_s(buffer, sizeof(buffer), &time) != 0) return "unknown time";
#else
  if (!ctime_r(&time, buffer)) return "unknown time";
#endif
  std::string result(buffer);
  if (!result.empty() && result.back() == '\n') result.pop_back();
  return result;
}

namespace blunted {
void Log(e_LogType type, const std::string& class_name, const std::string& method_name,
         const std::string& message) {
  const char* label = type == e_Warning ? "Warning" : type == e_Error ? "ERROR" :
                      type == e_FatalError ? "FATAL ERROR" : "UNKNOWN";
  const bool truncated = class_name.size() > 128 || method_name.size() > 128 || message.size() > 3500;
  char line[4096];
  const auto date = now();
  const int count = std::snprintf(line, sizeof(line), "%s [%s] in [%.*s::%.*s]: %.*s%s",
      date.c_str(), label, int(std::min<size_t>(class_name.size(), 128)), class_name.c_str(),
      int(std::min<size_t>(method_name.size(), 128)), method_name.c_str(),
      int(std::min<size_t>(message.size(), 3500)), message.c_str(),
      truncated ? "...[truncated]" : "");
  size_t size = count < 0 ? 0 : std::min<size_t>(count, sizeof(line) - 2);
  for (size_t i = 0; i < size; ++i)
    if (line[i] == '\n' || line[i] == '\r') line[i] = ' ';
  line[size++] = '\n';
  std::fwrite(line, 1, size, stdout);
  if (type == e_FatalError) {
    print_stacktrace();
    std::fflush(stdout); std::fflush(stderr);
    std::abort();
  }
}
}
