// Diagnostic interposition only: every intercepted method calls the original.
#include "scene/scene3d/node.hpp"
#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <unistd.h>

namespace {
struct Counts {
  unsigned long long invalidations[8]{}, roots[8]{};
  unsigned long long node_calls{}, root_bbox_dirty{}, root_dirty_partial_descendant{};
  unsigned long long root_fully_dirty{}, root_fully_dirty_partial_descendant{};
  unsigned long long reads[3]{}, misses[3]{}, reads_during_update{};
};
thread_local Counts counts[6];
thread_local unsigned phase=0, depth=0;
thread_local const blunted::Spatial* root=nullptr;
thread_local unsigned root_mask=0;
thread_local bool root_bbox=false, partial_descendant=false;
char origin[4096]{};

template<class F> F original(const char* name) {
  // Python loads extension dependencies with local symbol visibility.
  static void* engine=dlopen(std::getenv("FOOTBALL_SPATIAL_ENGINE"),RTLD_LAZY|RTLD_NOLOAD);
  auto address=engine?dlsym(engine,name):nullptr;
  if (!address) { std::fprintf(stderr,"spatial probe missing symbol: %s\n",name); _exit(86); }
  Dl_info info{};
  if (dladdr(address,&info)) std::snprintf(origin,sizeof(origin),"%s",info.dli_fname);
  return reinterpret_cast<F>(address);
}
__attribute__((destructor)) void dump() {
  const char* dir=std::getenv("FOOTBALL_SPATIAL_PROBE_DIR");
  if (!dir || !origin[0]) return;
  char path[4096]; std::snprintf(path,sizeof(path),"%s/spatial-%d.json",dir,int(getpid()));
  FILE* file=std::fopen(path,"w"); if (!file) _exit(87);
  std::fprintf(file,"{\"origin\":\"%s\",\"pid\":%d,\"phases\":[",origin,int(getpid()));
  for (unsigned p=0;p<6;++p) {
    const auto& c=counts[p];
    std::fprintf(file,"%s{\"phase\":%u,\"node_calls\":%llu,\"root_bbox_dirty\":%llu,\"root_dirty_partial_descendant\":%llu,\"root_fully_dirty\":%llu,\"root_fully_dirty_partial_descendant\":%llu,\"reads_during_update\":%llu,\"invalidations\":[",p?",":"",p,c.node_calls,c.root_bbox_dirty,c.root_dirty_partial_descendant,c.root_fully_dirty,c.root_fully_dirty_partial_descendant,c.reads_during_update);
    for(unsigned i=0;i<8;++i) std::fprintf(file,"%s%llu",i?",":"",c.invalidations[i]);
    std::fprintf(file,"],\"roots\":[");
    for(unsigned i=0;i<8;++i) std::fprintf(file,"%s%llu",i?",":"",c.roots[i]);
    std::fprintf(file,"],\"reads\":[%llu,%llu,%llu],\"misses\":[%llu,%llu,%llu]}",c.reads[0],c.reads[1],c.reads[2],c.misses[0],c.misses[1],c.misses[2]);
  }
  std::fprintf(file,"]}\n"); if(std::fclose(file)) _exit(87);
}
}
extern "C" unsigned football_spatial_phase(unsigned next) {
  unsigned previous=phase; phase=next<6?next:0; return previous;
}
namespace blunted {
void Spatial::InvalidateSpatialData() {
  unsigned mask=unsigned(dirty_derived_position_) | (unsigned(dirty_derived_rotation_)<<1) | (unsigned(dirty_derived_scale_)<<2);
  ++counts[phase].invalidations[mask];
  if(depth && this!=root && mask!=7) partial_descendant=true;
  using F=void(*)(Spatial*); static F real=original<F>("_ZN7blunted7Spatial21InvalidateSpatialDataEv"); real(this);
}
Vector3 Spatial::GetDerivedPosition() const {
  ++counts[phase].reads[0]; counts[phase].misses[0]+=dirty_derived_position_;
  if(depth) ++counts[phase].reads_during_update;
  using F=Vector3(*)(const Spatial*); static F real=original<F>("_ZNK7blunted7Spatial18GetDerivedPositionEv"); return real(this);
}
Quaternion Spatial::GetDerivedRotation() const {
  ++counts[phase].reads[1]; counts[phase].misses[1]+=dirty_derived_rotation_;
  if(depth) ++counts[phase].reads_during_update;
  using F=Quaternion(*)(const Spatial*); static F real=original<F>("_ZNK7blunted7Spatial18GetDerivedRotationEv"); return real(this);
}
Vector3 Spatial::GetDerivedScale() const {
  ++counts[phase].reads[2]; counts[phase].misses[2]+=dirty_derived_scale_;
  if(depth) ++counts[phase].reads_during_update;
  using F=Vector3(*)(const Spatial*); static F real=original<F>("_ZNK7blunted7Spatial15GetDerivedScaleEv"); return real(this);
}
void Node::RecursiveUpdateSpatialData(e_SpatialDataType type,e_SystemType exclude) {
  const bool top=depth==0; const unsigned current_phase=phase;
  if(top) {
    root=this; root_mask=unsigned(dirty_derived_position_) | (unsigned(dirty_derived_rotation_)<<1) | (unsigned(dirty_derived_scale_)<<2);
    root_bbox=aabb_.dirty; partial_descendant=false;
    ++counts[current_phase].roots[root_mask];
    counts[current_phase].root_bbox_dirty+=root_bbox;
  }
  ++counts[current_phase].node_calls; ++depth;
  using F=void(*)(Node*,e_SpatialDataType,e_SystemType);
  static F real=original<F>("_ZN7blunted4Node26RecursiveUpdateSpatialDataENS_17e_SpatialDataTypeENS_12e_SystemTypeE");
  real(this,type,exclude); --depth;
  if(top) {
    if(root_mask==7) {
      counts[current_phase].root_dirty_partial_descendant+=partial_descendant;
      if(root_bbox) { ++counts[current_phase].root_fully_dirty; counts[current_phase].root_fully_dirty_partial_descendant+=partial_descendant; }
    }
    root=nullptr;
  }
}
}
