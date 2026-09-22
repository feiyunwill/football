// 2026-09-22: permanent semantic contracts for the real shared-engine ASE parser.
#include "base/utils.hpp"
#include <array>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
size_t assertions = 0;
void Require(bool value, const char* reason) {
  ++assertions;
  if (!value) throw std::runtime_error(reason);
}
template<class Exception, class Function>
void RequireThrows(Function&& function) {
  bool caught = false;
  try { function(); } catch (const Exception&) { caught = true; }
  Require(caught, "Expected parser exception");
}
std::unique_ptr<blunted::s_tree> Parse(const std::string& input) {
  const char* cursor = input.data();
  int remaining = static_cast<int>(input.size());
  auto tree = std::unique_ptr<blunted::s_tree>(blunted::tree_readblock(cursor, remaining));
  Require(remaining == 0, "Parser left unexpected bytes");
  Require(cursor == input.data() + input.size(), "Parser cursor mismatch");
  return tree;
}
void EmptySpan() {
  const char* cursor = nullptr;
  int length = 0;
  std::unique_ptr<blunted::s_tree> tree(blunted::tree_readblock(cursor, length));
  Require(tree && tree->entries.empty(), "Empty tree");
  Require(cursor == nullptr && length == 0, "Empty span changed");
}
void FinalLine() {
  auto bytes = std::make_unique<char[]>(2);
  bytes[0] = '*'; bytes[1] = 'X';
  const char* cursor = bytes.get();
  int length = 2;
  std::unique_ptr<blunted::s_tree> tree(blunted::tree_readblock(cursor, length));
  Require(tree->entries.size() == 1, "Final line entry count");
  Require(tree->entries[0]->name == "X", "Final line name");
  Require(length == 0 && cursor == bytes.get() + 2, "Final line bounds");
}
void LongLine() {
  const std::string value(8192, 'a');
  const auto tree = Parse("*TEXT " + value + "\n");
  Require(tree->entries.size() == 1, "Long line entry count");
  Require(tree->entries[0]->name == "TEXT", "Long line name");
  Require(tree->entries[0]->values == std::vector<std::string>{value}, "Long line value");
}
void TokenSemantics() {
  const auto tree = Parse("\t *NAME\t\"two words\"  4 \r\n");
  Require(tree->entries.size() == 1, "Token entry count");
  Require(tree->entries[0]->name == "NAME", "Token name");
  Require(tree->entries[0]->values == std::vector<std::string>{"\"two", "words\"", "4"},
          "Legacy whitespace and quote tokens");
}
void NestedCursor() {
  const std::string input = " *ROOT {\r\n\t*CHILD 1 2\r\n}\r\n} ignored\n*TAIL 9\n";
  const char* cursor = input.data();
  int length = static_cast<int>(input.size());
  std::unique_ptr<blunted::s_tree> tree(blunted::tree_readblock(cursor, length));
  Require(tree->entries.size() == 1, "Nested root count");
  const auto* root = tree->entries[0];
  Require(root->name == "ROOT" && root->values.empty() && root->subtree, "Nested root");
  Require(root->subtree->entries.size() == 1, "Nested child count");
  const auto* child = root->subtree->entries[0];
  Require(child->name == "CHILD" && child->values == std::vector<std::string>{"1", "2"},
          "Nested child values");
  Require(std::string(cursor, length) == "*TAIL 9\n", "Closing cursor remaining data");
  Require(cursor == input.data() + input.size() - 8, "Closing cursor position");
}
void EmbeddedNul() {
  const auto tree = Parse(std::string("*X 1") + '\0' + " hidden words\n*Y 2\n");
  Require(tree->entries.size() == 2, "NUL line consumption");
  Require(tree->entries[0]->values == std::vector<std::string>{"1"}, "NUL visible value");
  Require(tree->entries[1]->name == "Y", "NUL following entry");
}
void StarAndCarriageReturn() {
  const auto tree = Parse("**NAME 7\n*\n\r\n");
  Require(tree->entries.size() == 3, "Special names count");
  Require(tree->entries[0]->name == "*NAME", "Strip exactly one star");
  Require(tree->entries[1]->name.empty(), "Single star name");
  Require(tree->entries[2]->name == "\r", "Single CR semantics");
}
void InvalidInput() {
  const char* cursor = nullptr;
  int length = 1;
  RequireThrows<std::invalid_argument>([&] { blunted::tree_readblock(cursor, length); });
  length = -1;
  RequireThrows<std::invalid_argument>([&] { blunted::tree_readblock(cursor, length); });
  RequireThrows<std::runtime_error>([] { Parse("{\n"); });
}
void NestedOwnership() {
  std::string allowed;
  for (int i = 0; i < 255; ++i) allowed += "*N {\n";
  allowed += "*LEAF 1\n";
  for (int i = 0; i < 255; ++i) allowed += "}\n";
  const auto tree = Parse(allowed);
  const blunted::s_tree* at = tree.get();
  for (int i = 0; i < 255; ++i) {
    Require(at->entries.size() == 1, "Depth entry count");
    at = at->entries[0]->subtree;
    Require(at != nullptr, "Depth child missing");
  }
  Require(at->entries.size() == 1 && at->entries[0]->name == "LEAF", "Depth leaf");
  RequireThrows<std::runtime_error>([&] { Parse("*EXTRA {\n" + allowed + "}\n"); });
}
void IncompleteClosingBrace() {
  const auto tree = Parse("*ROOT {\n*LEAF 1");
  Require(tree->entries.size() == 1, "Incomplete root");
  const auto* subtree = tree->entries[0]->subtree;
  Require(subtree && subtree->entries.size() == 1, "Incomplete subtree");
  Require(subtree->entries[0]->values == std::vector<std::string>{"1"}, "Incomplete leaf");
}
}  // namespace

int main() {
  try {
    const std::array<void(*)(), 10> cases{EmptySpan, FinalLine, LongLine,
        TokenSemantics, NestedCursor, EmbeddedNul, StarAndCarriageReturn,
        InvalidInput, NestedOwnership, IncompleteClosingBrace};
    for (auto test : cases) test();
    std::cout << "{\"passed\":true,\"checks\":" << cases.size()
              << ",\"assertions\":" << assertions << ",\"skipped\":0}\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
