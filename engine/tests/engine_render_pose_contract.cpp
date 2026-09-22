// 2026-09-10: real native skeleton/card fixtures; no substitute engine or renderer.
#include "frame_sync/default_scenario.hpp"
#include "game_env.hpp"
#include "onthepitch/officials.hpp"
#include "onthepitch/referee.hpp"
#include "onthepitch/player/playerofficial.hpp"

#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>

// Fixture access is limited to native acceptance. Skeletons, animation keyframes,
// card geometry, state serialization and rendering remain the actual engine's.
// No simulation step runs while card metadata is overridden.
// 2026-09-10: use registered real showcard clips instead of renaming a shared animation.
// struct RenderPoseContractAccess {
//   Referee& referee;
//   HumanoidBase& humanoid;
//   Foul saved_foul;
//   e_FunctionType saved_function;
//   e_FunctionType saved_previous;
//   std::string saved_name;
// 
//   RenderPoseContractAccess(Referee& ref, HumanoidBase& human)
//       : referee(ref), humanoid(human), saved_foul(ref.foul),
//         saved_function(human.currentAnim.functionType),
//         saved_previous(human.previousAnim_functionType),
//         saved_name(human.currentAnim.anim->GetName()) {}
// 
//   void SetCard(int type, bool special, bool left_hand) {
//     referee.foul.foulType = type;
//     humanoid.currentAnim.functionType = special ? e_FunctionType_Special : saved_function;
//     // Explicitly remove historical special state to reproduce snapshot jumps.
//     humanoid.previousAnim_functionType = e_FunctionType_None;
//     humanoid.currentAnim.anim->SetName(left_hand ? "contract_card_mirror" : "contract_card");
//   }
// 
//   boost::intrusive_ptr<Node>& Joint(BodyPart part) { return humanoid.nodeMap[part]; }
// 
//   void Restore() {
//     referee.foul = saved_foul;
//     humanoid.currentAnim.functionType = saved_function;
//     humanoid.previousAnim_functionType = saved_previous;
//     humanoid.currentAnim.anim->SetName(saved_name);
//   }
// };
struct RenderPoseContractAccess {
  Referee& referee;
  HumanoidBase& humanoid;
  Foul saved_foul;
  Anim saved_animation;
  e_FunctionType saved_previous;
  std::array<int, 2> card_animation_ids{-1, -1};

  RenderPoseContractAccess(Referee& ref, HumanoidBase& human)
      : referee(ref), humanoid(human), saved_foul(ref.foul),
        saved_animation(human.currentAnim), saved_previous(human.previousAnim_functionType) {
    const auto& animations = humanoid.anims->GetAnimations();
    for (size_t i = 0; i < animations.size(); ++i) {
      const auto name = animations[i]->GetName();
      if (name.find("showcard") != std::string::npos) {
        const bool left = name.find("mirror") != std::string::npos;
        card_animation_ids[left] = static_cast<int>(i);
      }
    }
    if (card_animation_ids[0] < 0 || card_animation_ids[1] < 0)
      throw std::runtime_error("Actual right/left showcard animations are required");
  }

  void SetCard(int type, bool special, bool left_hand, bool apply_pose = false) {
    referee.foul.foulType = type;
    if (special) {
      humanoid.currentAnim.id = card_animation_ids[left_hand];
      humanoid.currentAnim.anim = humanoid.anims->GetAnim(humanoid.currentAnim.id);
      humanoid.currentAnim.frameNum = humanoid.currentAnim.anim->GetFrameCount() / 2;
      humanoid.currentAnim.functionType = e_FunctionType_Special;
      if (apply_pose) {
        BiasedOffsets offsets;
        humanoid.currentAnim.anim->Apply(humanoid.nodeMap, humanoid.currentAnim.frameNum,
                                        0, false, 0.f, Vector3(0), 0.f, offsets,
                                        nullptr, 0, false, true);
      }
    } else {
      humanoid.currentAnim = saved_animation;
    }
    // Explicitly remove historical special state to reproduce snapshot jumps.
    humanoid.previousAnim_functionType = e_FunctionType_None;
  }

  boost::intrusive_ptr<Node>& Joint(BodyPart part) { return humanoid.nodeMap[part]; }

  void Restore() {
    referee.foul = saved_foul;
    humanoid.currentAnim = saved_animation;
    humanoid.previousAnim_functionType = saved_previous;
  }
};

namespace {
int assertions = 0;
int card_cases = 0;
int images = 0;
void Require(bool value, const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}
void Near(const Vector3& actual, const Vector3& expected, const char* message) {
  Require((actual - expected).GetLength() < 0.0001f, message);
}
void SameRotation(const Quaternion& actual, const Quaternion& expected) {
  for (const Vector3 axis : {Vector3(1, 0, 0), Vector3(0, 1, 0), Vector3(0, 0, 1)})
    Near(actual * axis, expected * axis, "Attachment rotation differs from the visible joint");
}
void Hidden(Officials& officials) {
  Near(officials.GetYellowCardGeom()->GetPosition(), Vector3(0, 0, -10), "Stale yellow card remains visible");
  Near(officials.GetRedCardGeom()->GetPosition(), Vector3(0, 0, -10), "Stale red card remains visible");
}
void CheckCard(Officials& officials, int type, const Vector3& position,
               const Quaternion& rotation) {
  auto selected = type == 2 ? officials.GetYellowCardGeom() : officials.GetRedCardGeom();
  auto unused = type == 2 ? officials.GetRedCardGeom() : officials.GetYellowCardGeom();
  Near(selected->GetPosition(), position, "Card detached from interpolated hand");
  SameRotation(selected->GetRotation(), rotation);
  Near(unused->GetPosition(), Vector3(0, 0, -10), "Both card colours remain visible");
}
void Image(GameEnv& env, const std::filesystem::path& output, const std::string& name) {
  const auto pixels = env.get_frame();
  Require(pixels.size() == 320 * 180 * 3, "Unexpected native image size");
  size_t different = 0;
  for (size_t i = 3; i < pixels.size(); i += 3)
    different += pixels.compare(i, 3, pixels, 0, 3) != 0;
  Require(different > 100, "Native render is blank");
  const auto path = output / (name + ".ppm");
  Require(!std::filesystem::exists(path), "Image evidence must not be overwritten");
  std::ofstream file(path, std::ios::binary);
  file << "P6\n320 180\n255\n";
  file.write(pixels.data(), static_cast<std::streamsize>(pixels.size()));
  file.close();
  Require(file.good(), "Could not save native image evidence");
  ++images;
}

// Independent single-bone skinning oracle, using the un-interpolated animation
// node and the actual player's scale. It does not call the attachment query.
Vector3 OrdinaryAttachment(PlayerOfficial& player, BodyPart part, const Vector3& local) {
  const auto& node = player.GetNodeMap()[part];
  Require(bool(node), "Required native elbow joint is missing");
  const auto root = player.GetHumanoidNode()->GetPosition().Get2D();
  const float scale = player.GetPlayerData()->GetHeight() / defaultPlayerHeight;
  return root + (node->GetDerivedPosition() - root + node->GetDerivedRotation() * local) * scale;
}

void Scenario(bool reverse, const std::filesystem::path& output) {
  GameEnv env;
  env.game_config.render = true;
  env.game_config.render_resolution_x = 320;
  env.game_config.render_resolution_y = 180;
  auto scenario = frame_sync::MakeDefaultScenario(1, 1, 42);
  scenario->reverse_team_processing = reverse;
  env.start_game(*scenario);
  env.state = game_running;
  env.step();
  const auto original = env.get_state("");
  const auto original_digest = env.get_state_digest();
  {
    ContextHolder context(&env);
    auto* match = env.context->gameTask->GetMatch();
    auto& officials = *match->GetOfficials();
    auto& referee = *officials.GetReferee();
    auto& humanoid = *referee.CastHumanoid();
    RenderPoseContractAccess fixture(*match->GetReferee(), humanoid);
    // 2026-09-10: the fixture now preserves the entire actual animation context.
    // Require(fixture.saved_function != e_FunctionType_Special, "Fixture must start outside a card animation");
    Require(fixture.saved_animation.functionType != e_FunctionType_Special, "Fixture must start outside a card animation");
    const auto root = referee.GetHumanoidNode();
    const auto initial_position = root->GetPosition();
    const Vector3 delta(4, 2, 0);
    const auto visible_delta = reverse ? delta * Vector3(-1, -1, 1) : delta;
    const Vector3 offset(0.04f, 0, -0.25f);

    // The query must match actual scaled skinning at both elbows and leave
    // outputs untouched when a requested body part has no registered joint.
    referee.Put(false);
    for (const BodyPart hand : {left_elbow, right_elbow}) {
      Vector3 position;
      Quaternion rotation;
      Require(referee.GetRenderAttachmentPose(hand, offset, position, rotation), "Native attachment unavailable");
      Near(position, OrdinaryAttachment(referee, hand, offset), "Attachment uses unscaled or logical coordinates");
      SameRotation(rotation, referee.GetNodeMap()[hand]->GetDerivedRotation());
    }
    Vector3 sentinel(98, 76, 54);
    Quaternion rotation;
    bool rejected = false;
    try { referee.GetRenderAttachmentPose(body_part_max, offset, sentinel, rotation); }
    catch (const std::out_of_range&) { rejected = true; }
    Require(rejected, "Out-of-range attachment part was accepted");
    Near(sentinel, Vector3(98, 76, 54), "Rejected query changed its output");

    for (const bool left : {false, true}) {
      for (const int colour : {2, 3}) {
        root->SetPosition(initial_position);
        // 2026-09-10: actual showcard keyframes, including their root height.
        // fixture.SetCard(colour, true, left);
        fixture.SetCard(colour, true, left, true);
        const auto case_position = root->GetPosition();
        env.render();
        const auto geometry = colour == 2 ? officials.GetYellowCardGeom() : officials.GetRedCardGeom();
        const auto start = geometry->GetPosition();
        const auto orientation = geometry->GetRotation();
        Vector3 attachment;
        Quaternion attachment_rotation;
        Require(referee.GetRenderAttachmentPose(left ? left_elbow : right_elbow, offset,
                                                attachment, attachment_rotation), "Selected hand has no display pose");
        CheckCard(officials, colour, attachment, attachment_rotation);
        env.save_render_state();
        // 2026-09-10: retain the real clip's root height during translation.
        // root->SetPosition(initial_position + delta);
        root->SetPosition(case_position + delta);
        const auto target_digest = env.get_state_digest();
        for (const float alpha : {0.f, 0.5f, 1.f}) {
          env.render_interpolated(alpha);
          CheckCard(officials, colour, start + visible_delta * alpha, orientation);
          Require(env.get_state_digest() == target_digest, "Interpolated attachment mutated canonical simulation");
          if (!left && colour == 3)
            Image(env, output, std::string(reverse ? "reverse" : "normal") + "_red_" + std::to_string(int(alpha * 2)));
        }
        // Repeated correction must capture the visible halfway pose, even
        // though the logical animation node is already at the target.
        env.render_interpolated(0.5f);
        const auto halfway = geometry->GetPosition();
        env.save_render_state(true);
        // 2026-09-10: correction uses the same actual clip root height.
        // root->SetPosition(initial_position + delta * 2.f);
        root->SetPosition(case_position + delta * 2.f);
        const auto correction_digest = env.get_state_digest();
        env.render_interpolated(0.f);
        CheckCard(officials, colour, halfway, orientation);
        env.render_interpolated(0.5f);
        CheckCard(officials, colour, (halfway + start + visible_delta * 2.f) * 0.5f, orientation);
        Require(env.get_state_digest() == correction_digest, "Correction attachment mutated simulation");
        ++card_cases;
      }
    }

    // An independent 90-degree rotation fixture checks that the card offset
    // rotates with the displayed joint, rather than a current logical node.
    fixture.SetCard(3, true, false, true);
    env.render();
    Vector3 first_joint;
    Quaternion first_rotation;
    Require(referee.GetRenderAttachmentPose(right_elbow, Vector3(0), first_joint, first_rotation), "First joint unavailable");
    const auto first_root_rotation = root->GetRotation();
    env.save_render_state();
    Quaternion quarter_turn;
    quarter_turn.SetAngleAxis(std::numbers::pi_v<float> / 2.f, Vector3(0, 0, 1));
    root->SetRotation(quarter_turn * first_root_rotation);
    env.render_interpolated(1.f);
    Vector3 final_joint;
    Quaternion final_rotation;
    Require(referee.GetRenderAttachmentPose(right_elbow, Vector3(0), final_joint, final_rotation), "Final joint unavailable");
    SameRotation(final_rotation, quarter_turn * first_rotation);
    Quaternion half_turn;
    half_turn.SetAngleAxis(std::numbers::pi_v<float> / 4.f, Vector3(0, 0, 1));
    const auto midway_rotation = half_turn * first_rotation;
    const float scale = referee.GetPlayerData()->GetHeight() / defaultPlayerHeight;
    const auto rotation_digest = env.get_state_digest();
    env.render_interpolated(0.5f);
    CheckCard(officials, 3, (first_joint + final_joint) * 0.5f +
              midway_rotation * (offset * scale), midway_rotation);
    Require(env.get_state_digest() == rotation_digest, "Rotating attachment changed simulation");
    root->SetRotation(first_root_rotation);

    // Appearance is discrete: yellow/right -> red/left -> hidden. alpha zero
    // keeps the last displayed appearance; alpha one matches ordinary Put.
    root->SetPosition(initial_position);
    // 2026-09-10: begin appearance transitions with an actual held-card pose.
    // fixture.SetCard(2, true, false);
    fixture.SetCard(2, true, false, true);
    env.render();
    const auto yellow_position = officials.GetYellowCardGeom()->GetPosition();
    const auto yellow_rotation = officials.GetYellowCardGeom()->GetRotation();
    env.save_render_state(true);
    fixture.SetCard(3, true, true);
    for (const float alpha : {0.f, 0.5f}) {
      env.render_interpolated(alpha);
      CheckCard(officials, 2, yellow_position, yellow_rotation);
    }
    env.render_interpolated(1.f);
    const auto red_position = officials.GetRedCardGeom()->GetPosition();
    const auto red_rotation = officials.GetRedCardGeom()->GetRotation();
    Vector3 left_position;
    Quaternion left_rotation;
    Require(referee.GetRenderAttachmentPose(left_elbow, offset, left_position, left_rotation), "Left hand unavailable");
    CheckCard(officials, 3, left_position, left_rotation);
    env.save_render_state(true);
    fixture.SetCard(0, false, false);
    env.render_interpolated(0.5f);
    CheckCard(officials, 3, red_position, red_rotation);
    env.render_interpolated(1.f);
    Hidden(officials);

    // A normal logical-endpoint capture also holds the old appearance.
    fixture.SetCard(0, false, false);
    env.render();
    env.save_render_state(false);
    fixture.SetCard(2, true, false);
    env.render_interpolated(0.5f);
    Hidden(officials);
    env.render_interpolated(1.f);
    Require(officials.GetYellowCardGeom()->GetPosition().coords[2] > -9, "New card never appeared");

    // Missing mapping must hide both cards, not dereference a null animation
    // node or leave a previous card onscreen. Restore before snapshot checks.
    auto saved_joint = fixture.Joint(right_elbow);
    fixture.Joint(right_elbow).reset();
    Vector3 missing_position(98, 76, 54);
    Quaternion missing_rotation;
    Require(!referee.GetRenderAttachmentPose(right_elbow, offset, missing_position, missing_rotation), "Missing joint accepted");
    Near(missing_position, Vector3(98, 76, 54), "Missing joint changed output");
    officials.Put(reverse);
    Hidden(officials);
    fixture.Joint(right_elbow) = saved_joint;
    for (const int invalid_foul : {0, 1, 4}) {
      fixture.SetCard(invalid_foul, true, false);
      env.render();
      Hidden(officials);
    }

    fixture.SetCard(3, true, false);
    env.render();
    fixture.Restore();
    root->SetPosition(initial_position);
    env.set_state(original);
    env.render();
    Hidden(officials);
    Require(env.get_state_digest() == original_digest, "Restoring a non-card snapshot changed canonical state");
  }
  env.close();
  Require(!env.context && GetGame() == nullptr, "Render contract leaked context ownership");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    Require(argc == 2, "Expected a fresh image output directory");
    const std::filesystem::path output(argv[1]);
    Require(std::filesystem::create_directory(output), "Image output directory already exists");
    Scenario(false, output);
    Scenario(true, output);
    Require(card_cases == 8 && images == 6, "Native card coverage incomplete");
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"card_cases\":" << card_cases << ",\"images\":" << images
              << ",\"actual_GameEnv\":true,\"skipped\":0}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Native render pose contract: " << error.what() << '\n';
    return 1;
  }
}
