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

#include "node.hpp"

#include "../../main.hpp"
#include "../../scene/objectfactory.hpp"
#include "scene3d.hpp"
#include "../objects/geometry.hpp"
#include <typeinfo>

namespace blunted {

Node::Node(const std::string &name) : Spatial(name) {
  DO_VALIDATION;
  aabb_.aabb.Reset();
  aabb_.dirty = false;
}

Node::Node(const Node &source, const std::string &postfix,
           std::shared_ptr<Scene3D> scene3D)
    : Spatial(source) {
  DO_VALIDATION;
  SetName(source.GetName() + postfix);
  std::vector<boost::intrusive_ptr<Node> > gatherNodes;
  source.GetNodes(gatherNodes);
  for (int i = 0; i < (signed int)gatherNodes.size(); i++) {
    DO_VALIDATION;
    boost::intrusive_ptr<Node> copy(
        new Node(*gatherNodes[i].get(), postfix, scene3D));
    AddNode(copy);
  }

  std::list<boost::intrusive_ptr<Object> > gatherObjects;
  source.GetObjects(gatherObjects, false);
  std::list<boost::intrusive_ptr<Object> >::iterator objectIter =
      gatherObjects.begin();
  while (objectIter != gatherObjects.end()) {
    DO_VALIDATION;
    boost::intrusive_ptr<Object> objCopy =
        GetContext().object_factory.CopyObject((*objectIter), postfix);
    scene3D->CreateSystemObjects(objCopy);
    objCopy->Synchronize();
    AddObject(objCopy);

    objectIter++;
  }
}

Node::~Node() { DO_VALIDATION; }

void Node::Exit() {
  InvalidatePruningEligibility();
  DO_VALIDATION;
  int objCount = objects_.size();
  for (int i = 0; i < objCount; i++) {
    DO_VALIDATION;
    objects_[i]->Exit();
  }
  objects_.clear();
  int nodeCount = nodes_.size();
  for (int i = 0; i < nodeCount; i++) {
    DO_VALIDATION;
    nodes_[i]->Exit();
  }
  nodes_.clear();
}

void Node::AddNode(boost::intrusive_ptr<Node> node) {
  InvalidatePruningEligibility();
  DO_VALIDATION;
  nodes_.push_back(node);
  node->SetParent(this);
  node->RecursiveUpdateSpatialData(e_SpatialDataType_Both);
  InvalidateBoundingVolume();
}

void Node::DeleteNode(boost::intrusive_ptr<Node> node) {
  InvalidatePruningEligibility();
  DO_VALIDATION;
  std::vector<boost::intrusive_ptr<Node> >::iterator nodeIter =
      find(nodes_.begin(), nodes_.end(), node);
  if (nodeIter != nodes_.end()) {
    DO_VALIDATION;
    (*nodeIter)->Exit();
    nodes_.erase(nodeIter);
  }
  InvalidateBoundingVolume();
}

  void Node::GetNodes(std::vector < boost::intrusive_ptr<Node> > &gatherNodes, bool recurse) const {
    int nodesSize = nodes_.size();
    for (int i = 0; i < nodesSize; i++) {
      DO_VALIDATION;
      gatherNodes.push_back(nodes_[i]);
      if (recurse) nodes_[i]->GetNodes(gatherNodes, recurse);
    }
  }

  void Node::AddObject(boost::intrusive_ptr<Object> object) {
    InvalidatePruningEligibility();
    DO_VALIDATION;
    assert(object.get());
    objects_.push_back(object);
    object->SetParent(this);

    object->RecursiveUpdateSpatialData(e_SpatialDataType_Both);
    InvalidateBoundingVolume();
  }

  boost::intrusive_ptr<Object> Node::GetObject(const std::string &name) {
    DO_VALIDATION;
    std::vector < boost::intrusive_ptr<Object> >::iterator objIter = objects_.begin();
    while (objIter != objects_.end()) {
      DO_VALIDATION;
      if ((*objIter)->GetName() == name) {
        DO_VALIDATION;
        return (*objIter);
      } else {
        objIter++;
      }
    }
    return boost::intrusive_ptr<Object>();
  }

  void Node::DeleteObject(boost::intrusive_ptr<Object> object,
                          bool exitObject) {
    InvalidatePruningEligibility();
    DO_VALIDATION;
    std::vector < boost::intrusive_ptr<Object> >::iterator objIter = find(objects_.begin(), objects_.end(), object);
    if (objIter != objects_.end()) {
      DO_VALIDATION;
      if (exitObject) (*objIter)->Exit();
      (*objIter)->SetParent(0);
      objects_.erase(objIter);
    } else
      Log(e_Error, "Node", "DeleteObject",
          "Object " + object->GetName() + " not found among node " + GetName() +
              "'s children!");
    aabb_.dirty = true;
  }

  void Node::GetObjects(std::list < boost::intrusive_ptr<Object> > &gatherObjects, bool recurse, int depth) const {
    int objectsSize = objects_.size();
    for (int i = 0; i < objectsSize; i++) {
      DO_VALIDATION;
      gatherObjects.push_back(objects_[i]);
    }
    if (recurse) {
      DO_VALIDATION;
      int nodesSize = nodes_.size();
      for (int i = 0; i < nodesSize; i++) {
        DO_VALIDATION;
        nodes_[i]->GetObjects(gatherObjects, recurse, depth + 1);
      }
    }
  }

  void Node::GetObjects(std::deque < boost::intrusive_ptr<Object> > &gatherObjects, const vector_Planes &bounding, bool recurse, int depth) const {
    int objectsSize = objects_.size();
    for (int i = 0; i < objectsSize; i++) {
      DO_VALIDATION;
      if (objects_[i]->GetAABB().Intersects(bounding)) gatherObjects.push_back(objects_[i]);
    }
    if (recurse) {
      DO_VALIDATION;
      int nodesSize = nodes_.size();
      for (int i = 0; i < nodesSize; i++) {
        DO_VALIDATION;
        if (nodes_[i]->GetAABB().Intersects(bounding)) nodes_[i]->GetObjects(gatherObjects, bounding, recurse, depth + 1);
      }
    }
  }

  void Node::ProcessState(EnvState* state) {
    NoteSpatialDataRead();
    state->process(position_);
    state->process(rotation_);
    state->process(scale_);
    state->process(local_mode_);
    dirty_derived_position_ = true;
    dirty_derived_rotation_ = true;
    dirty_derived_scale_ = true;
    aabb_.dirty = true;
    for (auto& node : nodes_) {
      node->ProcessState(state);
    }

  }

  void Node::PokeObjects(e_ObjectType targetObjectType,
                         e_SystemType targetSystemType) {
    DO_VALIDATION;
    int objectsSize = objects_.size();
    for (int i = 0; i < objectsSize; i++) {
      DO_VALIDATION;
      if (objects_[i]->IsEnabled()) if (objects_[i]->GetObjectType() == targetObjectType) objects_[i]->Poke(targetSystemType);
    }
    int nodesSize = nodes_.size();
    for (int i = 0; i < nodesSize; i++) {
      DO_VALIDATION;
      nodes_[i]->PokeObjects(targetObjectType, targetSystemType);
    }
  }

  void Node::InvalidatePruningEligibility() {
    for (Node* node = this; node; node = node->parent_) {
      node->pruning_eligibility_ = -1;
      node->subtree_invalidation_complete_ = false;
    }
  }

  bool Node::CanPruneHeadlessInvalidation() const {
    if (pruning_eligibility_ != -1) return pruning_eligibility_ == 1;
    bool eligible = typeid(*this) == typeid(Node);
    for (const auto& node : nodes_) {
      if (node->parent_ != this || !node->CanPruneHeadlessInvalidation())
        eligible = false;
    }
    for (const auto& object : objects_) {
      if (object->parent_ != this || typeid(*object) != typeid(Geometry))
        eligible = false;
    }
    pruning_eligibility_ = eligible ? 1 : 0;
    return eligible;
  }

  void Node::RecursiveUpdateSpatialData(e_SpatialDataType spatialDataType,
                                        e_SystemType excludeSystem) {
    DO_VALIDATION;

    // GetGraphicsSystem is also the existing null-safe context lookup. Trees
    // used outside a selected environment retain the original update path.
    const bool canReuse = GetGraphicsSystem() && !GetGameConfig().render &&
                          !GetTracker()->enabled() && CanPruneHeadlessInvalidation();
    if (canReuse && subtree_invalidation_complete_) return;
    NoteSpatialDataRead();
    InvalidateSpatialData();
    InvalidateBoundingVolume();
    int nodesSize = nodes_.size();
    for (int i = 0; i < nodesSize; i++) {
      DO_VALIDATION;

      nodes_[i]->RecursiveUpdateSpatialData(spatialDataType, excludeSystem);
    }
    int objectsSize = objects_.size();
    for (int i = 0; i < objectsSize; i++) {
      DO_VALIDATION;
      objects_[i]->RecursiveUpdateSpatialData(spatialDataType, excludeSystem);
    }
    // Exact Geometry in headless mode has no callbacks or derived reads. Other
    // dynamic types, rendering and active tracker verification never cache.
    if (canReuse) subtree_invalidation_complete_ = true;
  }

  AABB Node::GetAABB() const {
    NoteSpatialDataRead();
    AABB tmp;
    if (aabb_.dirty == true) {
      DO_VALIDATION;
      tmp.Reset();
      int nodesSize = nodes_.size();
      for (int i = 0; i < nodesSize; i++) {
        DO_VALIDATION;
        tmp += (nodes_[i]->GetAABB());
      }
      int objectsSize = objects_.size();
      for (int i = 0; i < objectsSize; i++) {
        DO_VALIDATION;
        tmp += (objects_[i]->GetAABB());
      }
      aabb_.dirty = false;
      aabb_.aabb = tmp;
    } else {
      tmp = aabb_.aabb;
    }
    return tmp;
  }

}
