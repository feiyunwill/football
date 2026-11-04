// Behavioral edge checks for headless subtree invalidation reuse.
#include "frame_sync/default_scenario.hpp"
#include "game_env.hpp"
#include "scene/objects/geometry.hpp"
#include <cmath>
#include <climits>
#include <iostream>
#include <stdexcept>
using namespace blunted;
namespace {
int checks=0;
void Require(bool ok,const char* message) { ++checks; if(!ok) throw std::runtime_error(message); }
void Near(const Vector3& got,const Vector3& want,const char* message) {
  Require((got-want).GetLength()<0.001f,message);
}
struct Observer final:IGeometryInterpreter {
  int moves=0,rotations=0;
  e_SystemType GetSystemType() const override { return e_SystemType_Graphics; }
  void OnLoad(boost::intrusive_ptr<Geometry>) override {}
  void OnUpdateGeometry(boost::intrusive_ptr<Geometry>,bool) override {}
  void OnUnload() override {}
  void OnMove(const Vector3&) override { ++moves; }
  void OnRotate(const Quaternion&) override { ++rotations; }
  void OnPoke() override {}
};
struct CustomObject final:Object {
  int updates=0;
  CustomObject():Object("custom",e_ObjectType_Geometry) {}
  void RecursiveUpdateSpatialData(e_SpatialDataType type,e_SystemType exclude=e_SystemType_None) override {
    ++updates; Object::RecursiveUpdateSpatialData(type,exclude);
  }
};
struct CustomNode final:Node {
  int updates=0;
  CustomNode():Node("custom-node") {}
  void RecursiveUpdateSpatialData(e_SpatialDataType type,e_SystemType exclude=e_SystemType_None) override {
    ++updates; Node::RecursiveUpdateSpatialData(type,exclude);
  }
};
void Run(GameEnv& env) {
  ContextHolder selected(&env);
  boost::intrusive_ptr<Node> root(new Node("root")), middle(new Node("middle")), leaf(new Node("leaf"));
  root->AddNode(middle); middle->AddNode(leaf);
  middle->SetPosition(Vector3(1,0,0)); leaf->SetPosition(Vector3(2,0,0));
  root->SetPosition(Vector3(10,0,0)); root->SetPosition(Vector3(20,0,0));
  Near(leaf->GetDerivedPosition(),Vector3(23,0,0),"Repeated root updates lost descendant position");
  root->SetPosition(Vector3(30,0,0));
  Near(leaf->GetDerivedPosition(),Vector3(33,0,0),"Independent descendant read did not revoke reuse");

  root->RecursiveUpdateSpatialData(e_SpatialDataType_Both);
  leaf->SetLocalMode(e_LocalMode_Absolute); leaf->SetPosition(Vector3(4,5,6));
  Near(leaf->GetDerivedPosition(),Vector3(4,5,6),"Absolute child fixture failed");
  leaf->SetPosition(Vector3(7,8,9),false); root->SetPosition(Vector3(40,0,0));
  Near(leaf->GetDerivedPosition(),Vector3(7,8,9),"Absolute-child read did not revoke ancestor reuse");
  leaf->SetLocalMode(e_LocalMode_Relative); leaf->SetPosition(Vector3(2,0,0));

  root->SetScale(Vector3(2)); root->SetScale(Vector3(3));
  Near(leaf->GetDerivedScale(),Vector3(3),"Scale-only read/update invalidation failed");
  root->SetScale(Vector3(4));
  Near(leaf->GetDerivedScale(),Vector3(4),"Scale-only descendant read did not revoke reuse");
  root->SetScale(Vector3(1));
  Quaternion turn; turn.SetAngleAxis(0.5f,Vector3(0,0,1));
  root->SetRotation(turn); (void)leaf->GetDerivedRotation();
  Quaternion turn2; turn2.SetAngleAxis(1.f,Vector3(0,0,1)); root->SetRotation(turn2);
  const auto got=leaf->GetDerivedRotation();
  Require(std::fabs(std::fabs(got.GetDotProduct(turn2))-1.f)<0.001f,"Rotation-only descendant read did not revoke reuse");
  root->SetRotation(Quaternion(QUATERNION_IDENTITY)); root->SetPosition(Vector3(0));

  boost::intrusive_ptr<Geometry> geometry(new Geometry("box"));
  boost::intrusive_ptr<Resource<GeometryData>> mesh(new Resource<GeometryData>("box-data"));
  mesh->GetResource()->AddTriangleMesh(Material{},new float[9]{-1,-1,0, 1,-1,0, 0,1,1},9,{0,3,6});
  geometry->SetGeometryData(mesh);
  root->AddObject(geometry);
  const auto before=geometry->GetAABB(); root->SetPosition(Vector3(32,0,0));
  const auto after=geometry->GetAABB();
  Require(std::fabs(after.minxyz.coords[0]-before.minxyz.coords[0]-32.f)<0.01f,"Geometry AABB read did not revoke reuse");
  const auto root_before=root->GetAABB(); root->SetPosition(Vector3(64,0,0)); const auto root_after=root->GetAABB();
  Require(std::fabs(root_after.minxyz.coords[0]-root_before.minxyz.coords[0]-32.f)<0.01f,"Node AABB read did not revoke reuse");

  boost::intrusive_ptr<CustomObject> custom(new CustomObject);
  root->AddObject(custom); int n=custom->updates;
  root->SetPosition(Vector3(1)); root->SetPosition(Vector3(2));
  Require(custom->updates==n+2,"Custom dynamic object update was skipped after topology change");
  root->DeleteObject(custom,false);
  boost::intrusive_ptr<CustomNode> custom_node(new CustomNode);
  root->AddNode(custom_node); n=custom_node->updates;
  root->SetPosition(Vector3(3)); root->SetPosition(Vector3(4));
  Require(custom_node->updates==n+2,"Custom dynamic node update was skipped");
  root->DeleteNode(custom_node);

  boost::intrusive_ptr<Node> other(new Node("other"));
  root->DeleteObject(geometry,false); other->AddObject(geometry);
  other->SetPosition(Vector3(50,0,0));
  Near(geometry->GetDerivedPosition(),Vector3(50,0,0),"Reparented geometry retained old ancestor cache");
  other->SetPosition(Vector3(60,0,0));
  Near(geometry->GetDerivedPosition(),Vector3(60,0,0),"Reparented geometry read did not revoke new ancestor reuse");
  other->DeleteObject(geometry,false); root->AddObject(geometry);

  boost::intrusive_ptr<Observer> observer(new Observer); geometry->Attach(observer);
  env.game_config.render=true;
  n=observer->moves; const int rotations=observer->rotations;
  root->SetPosition(Vector3(5)); root->SetPosition(Vector3(6));
  Require(observer->moves==n+2 && observer->rotations==rotations,"Position observer notifications changed in rendering mode");
  root->RecursiveUpdateSpatialData(e_SpatialDataType_Both);
  Require(observer->rotations==rotations+1,"Rotation observer notification lost");
  n=observer->moves; root->RecursiveUpdateSpatialData(e_SpatialDataType_Both,e_SystemType_Graphics);
  Require(observer->moves==n,"Excluded rendering observer was called");
  env.game_config.render=false;
  root->SetPosition(Vector3(7)); root->SetPosition(Vector3(8));
  Require(observer->moves==n,"Headless mode emitted rendering notifications");

  const auto disabled=GetContext().tracker_disabled;
  GetTracker()->setup(LONG_MAX,LONG_MAX);
  root->SetPosition(Vector3(9)); root->SetPosition(Vector3(10));
  Near(geometry->GetDerivedPosition(),Vector3(10),"Active-tracker fallback changed state");
  GetContext().tracker_disabled=disabled;
  geometry->Detach(observer);
  root->Exit(); other->Exit();
}
}
int main(int, char**) {
  try {
    GameEnv env; env.game_config.render=false;
    auto scenario=frame_sync::MakeDefaultScenario(1,1,42); env.start_game(*scenario);
    Run(env); env.close();
    std::cout<<"Spatial invalidation behavior: "<<checks<<" checks passed\n";
    return 0;
  } catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
}
