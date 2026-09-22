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

#include "utils.hpp"

#include <format>
#include <print>
#include <array>
#include <cstring>
#include <stdexcept>
#include <string_view>
// 2026-09-21: exception-safe parser ownership.
#include <memory>
#include "../main.hpp"
#include "file.h"
#include "log.hpp"
#include "math/quaternion.hpp"
#include "math/vector3.hpp"

namespace blunted {

s_treeentry::~s_treeentry() {
  DO_VALIDATION;
  if (subtree) {
    DO_VALIDATION;
    delete subtree;
    subtree = NULL;
  }
}

  // ----- load .ase file into a tree

s_tree *tree_load(std::string asefile) {
  DO_VALIDATION;
  asefile = GetGameConfig().updatePath(asefile);
  const std::string &datafile = GetFile(asefile);
  const char *data = datafile.c_str();
  int len = datafile.size();
  s_tree *tree = tree_readblock(data, len);
  return tree;
}

// 2026-09-21: retained original parser; unbounded newline scan and fixed2048 buffer.
// s_tree *tree_readblock(const char *&datafile, int &len) {
//   DO_VALIDATION;
//   s_tree *content = new s_tree();
// 
//   bool quit = false;
// 
//   while (len > 0 && quit == false) {
//     DO_VALIDATION;
//     char tmp[2048];
//     int l = 0;
//     for (l = 0; datafile[0] != '\n'; l++) {
//       DO_VALIDATION;
//       tmp[l] = datafile[0];
//       datafile++;
//       len--;
//     }
//     tmp[l] = 0;
//     datafile++;
//     len--;
//     std::string line;
//     line.assign(tmp);
//     std::vector<std::string> tokens;
// 
//     // delete CR character, if it's there
//     if (line.length() > 1) {
//       DO_VALIDATION;
//       if (line[line.length() - 1] == '\r')
//         line = line.substr(0, line.length() - 1);
//     }
// 
//     line = stringchomp(line, '\t');
//     line = stringchomp(line, ' ');
//     tokenize(line, tokens, " \t");
// 
//     if (tokens.size() > 0) {
//       DO_VALIDATION;
//       if (tokens.at(0).compare("}") == 0) {
//         DO_VALIDATION;
//         quit = true;
//       } else {
//         s_treeentry *entry = new s_treeentry();
//         if (tokens.at(0).substr(0, 1).compare("*") == 0) {
//           DO_VALIDATION;
//           entry->name = tokens.at(0).substr(1);
//         } else {
//           entry->name = tokens.at(0);
//         }
//         for (unsigned int i = 1; i < tokens.size(); i++) {
//           DO_VALIDATION;
//           entry->values.push_back(tokens[i]);
//         }
// 
//         if (tokens.at(tokens.size() - 1).compare("{") == 0) {
//           DO_VALIDATION;  // iterate
//           entry->values.pop_back();
//           entry->subtree = tree_readblock(datafile, len);
//         }
//         content->entries.push_back(entry);
//       }
//     }
//   }
// 
//   return content;
// }

// 2026-09-21: bounded views remove the fixed line buffer and intermediate
// token copies; RAII retains ownership until each child attaches successfully.
s_tree *tree_readblock(const char *&datafile, int &len) {
  DO_VALIDATION;
  if (len < 0 || (len > 0 && datafile == nullptr))
    throw std::invalid_argument("Invalid ASE input span");

  const auto read_block = [&](auto&& self, unsigned depth) -> std::unique_ptr<s_tree> {
    // Limit recursive parse and tree destruction before accepting another child.
    constexpr unsigned kMaxDepth = 256;
    if (depth >= kMaxDepth)
      throw std::runtime_error("ASE nesting limit exceeded");
    auto content = std::make_unique<s_tree>();
    while (len > 0) {
      const auto* newline = static_cast<const char*>(
          std::memchr(datafile, '\n', static_cast<size_t>(len)));
      const size_t line_size = newline ? static_cast<size_t>(newline - datafile)
                                       : static_cast<size_t>(len);
      std::string_view line(datafile, line_size);
      const size_t consumed = line_size + (newline ? 1 : 0);
      datafile += consumed;
      len -= static_cast<int>(consumed);

      // Legacy token semantics: embedded NUL ends the visible line; only a
      // nonempty CRLF line loses CR, and spaces/tabs delimit even quoted values.
      const size_t nul = line.find('\0');
      if (nul != std::string_view::npos) line = line.substr(0, nul);
      if (line.size() > 1 && line.back() == '\r') line.remove_suffix(1);
      const auto next_token = [&line]() -> std::string_view {
        const size_t begin = line.find_first_not_of(" \t");
        if (begin == std::string_view::npos) {
          line = {};
          return {};
        }
        line.remove_prefix(begin);
        const size_t end = line.find_first_of(" \t");
        const auto token = line.substr(0, end);
        line.remove_prefix(token.size());
        return token;
      };
      auto token = next_token();
      if (token.empty()) continue;
      if (token == "}") break;
      auto entry = std::make_unique<s_treeentry>();
      entry->name = token.starts_with('*') ? token.substr(1) : token;
      auto last_token = token;
      while (!(token = next_token()).empty()) {
        entry->values.emplace_back(token);
        last_token = token;
      }
      if (last_token == "{") {
        if (entry->values.empty())
          throw std::runtime_error("ASE opening brace requires an entry name");
        entry->values.pop_back();
        entry->subtree = self(self, depth + 1).release();
      }
      content->entries.push_back(entry.get());
      entry.release();
    }
    return content;
  };
  return read_block(read_block, 0).release();
}

  // tree structure utility functions

const s_treeentry *treeentry_find(const s_tree *tree,
                                  const std::string needle) {
  DO_VALIDATION;
  assert(tree);

  for (unsigned int i = 0; i < tree->entries.size(); i++) {
    DO_VALIDATION;
    assert(tree->entries[i]);
    if (tree->entries[i]->name.compare(needle) == 0) return tree->entries[i];
  }
  return NULL;
}

const s_tree *tree_find(const s_tree *tree, const std::string needle) {
  DO_VALIDATION;
  // assert(tree);

  for (unsigned int i = 0; i < tree->entries.size(); i++) {
    DO_VALIDATION;
    assert(tree->entries[i]);
    if (tree->entries[i]->name.compare(needle) == 0) {
      DO_VALIDATION;
      assert(tree->entries[i]->subtree);
      return tree->entries[i]->subtree;
    }
  }
  return NULL;
}

  // string functions

std::string stringchomp(std::string input, char chomp) {
  DO_VALIDATION;
  if (input.find_first_not_of(chomp) < input.length())
    return (input.substr(input.find_first_not_of(chomp)));
  return "";
}

  // tokenizer code from oopweb.com
void tokenize(const std::string &str, std::vector<std::string> &tokens,
              const std::string &delimiters) {
  DO_VALIDATION;
  // Skip delimiters at beginning.
  std::string::size_type lastPos = str.find_first_not_of(delimiters, 0);
  // Find first "non-delimiter".
  std::string::size_type pos = str.find_first_of(delimiters, lastPos);

  while (std::string::npos != pos || std::string::npos != lastPos) {
    DO_VALIDATION;
    // Found a token, add it to the vector.
    tokens.push_back(str.substr(lastPos, pos - lastPos));
    // Skip delimiters.  Note the "not_of"
    lastPos = str.find_first_not_of(delimiters, pos);
    // Find next "non-delimiter"
    pos = str.find_first_of(delimiters, lastPos);
  }
}

std::string file_to_string(std::string filename) {
  DO_VALIDATION;
  return GetFile(GetGameConfig().updatePath(filename));
}

void file_to_vector(std::string filename,
                    std::vector<std::string> &destination) {
  DO_VALIDATION;
  std::string file = GetFile(GetGameConfig().updatePath(filename));
  int last_pos = 0;
  for (int x = 0; x < file.length(); x++) {
    DO_VALIDATION;
    if (file[x] == '\n') {
      DO_VALIDATION;
      destination.push_back(file.substr(last_pos, x - last_pos));
      last_pos = x + 1;
    }
  }
  if (last_pos < file.length()) {
    DO_VALIDATION;
    destination.push_back(file.substr(last_pos, file.length() - last_pos));
  }
}

std::string get_file_name(const std::string &filename) {
  DO_VALIDATION;
#ifdef WIN32
  // 2026-08-26 移除 Boost：boost::filesystem → std::filesystem。
  std::string chompedFilename =
      std::filesystem::path(filename).filename().string();
#else
  std::string chompedFilename =
      filename.substr(filename.find_last_of('\\') + 1);
  chompedFilename = chompedFilename.substr(filename.find_last_of('/') + 1);
#endif
  return chompedFilename;
}

std::string get_file_extension(const std::string &filename) {
  DO_VALIDATION;
  return filename.substr(filename.find_last_of('.') + 1);
}

std::string int_to_str(int i) {
  DO_VALIDATION;
  return std::format("{}", i);
}

std::string real_to_str(real r) {
  DO_VALIDATION;
  return std::format("{}", r);
}

std::string GetStringFromVector(const Vector3 &vec) {
  DO_VALIDATION;
  return std::format("{}, {}, {}", vec.coords[0], vec.coords[1], vec.coords[2]);
}

Vector3 GetVectorFromString(const std::string &vecString) {
  DO_VALIDATION;
  if (vecString.compare("") == 0) {
    DO_VALIDATION;
    std::println("vectorfromstring warning, no value");
    return Vector3(0.0f);
  }
  // 2026-09-09: vector metadata is parsed in the animation selection hot path.
  // Keep comma skipping and atof conversion, but avoid a heap-backed token list.
  // std::vector<std::string> tokenizedString;
  // std::string delimiter = ",";
  // tokenize(vecString, tokenizedString, delimiter);
  // assert(tokenizedString.size() > 0);
  // assert(tokenizedString.size() <= 3);
  // Vector3 vector;
  // vector.coords[0] = atof(tokenizedString.at(0).c_str());
  // if (tokenizedString.size() > 1)
  //   vector.coords[1] = atof(tokenizedString.at(1).c_str());
  // if (tokenizedString.size() > 2)
  //   vector.coords[2] = atof(tokenizedString.at(2).c_str());
  const std::string_view input(vecString);
  std::array<std::string_view, 3> tokens;
  size_t count = 0;
  auto begin = input.find_first_not_of(',');
  while (begin != std::string_view::npos) {
    const auto end = input.find(',', begin);
    if (count < tokens.size()) tokens[count] = input.substr(begin, end - begin);
    ++count;
    begin = input.find_first_not_of(',', end);
  }
  assert(count > 0);
  assert(count <= tokens.size());
  // Preserve the previous release-build rejection of delimiter-only input.
  if (count == 0) throw std::out_of_range("Vector text contains no coordinates");
  Vector3 vector;
  for (size_t i = 0; i < std::min(count, tokens.size()); ++i) {
    // Null terminate each token: passing the original suffix to atof would
    // change comma-decimal locale behavior. Long metadata keeps the old path.
    char scratch[128];
    if (tokens[i].size() < sizeof(scratch)) {
      std::memcpy(scratch, tokens[i].data(), tokens[i].size());
      scratch[tokens[i].size()] = '\0';
      vector.coords[i] = atof(scratch);
    } else {
      vector.coords[i] = atof(std::string(tokens[i]).c_str());
    }
  }
  return vector;
}

Quaternion GetQuaternionFromString(const std::string &quatString) {
  DO_VALIDATION;
  std::vector<std::string> tokenizedString;
  std::string delimiter = ",";
  tokenize(quatString, tokenizedString, delimiter);
  assert(tokenizedString.size() == 4);
  radian angle;
  Vector3 vector;
  angle = atof(tokenizedString.at(0).c_str()) / 360.0 * 2.0 * pi;
  vector.coords[0] = atof(tokenizedString.at(1).c_str());
  vector.coords[1] = atof(tokenizedString.at(2).c_str());
  vector.coords[2] = atof(tokenizedString.at(3).c_str());
  Quaternion quaternion;
  quaternion.SetAngleAxis(angle, vector);
  return quaternion;
}

  }  // namespace blunted
