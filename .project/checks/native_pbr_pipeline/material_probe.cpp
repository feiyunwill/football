#include "systems/graphics/rendering/opengl_renderer3d.hpp"
#include "systems/graphics/resources/texture.hpp"
#include <EGL/egl.h>
#include <SDL_opengl.h>
#include <cmath>
#include <vector>
#include <dlfcn.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <list>
#include <set>
#include <string>
namespace {
unsigned long long queue_calls=0, material_indices=0, same_texture_pairs=0;
unsigned long long uniform_calls=0, nondefault_uniform_calls=0;
unsigned long long split_uniform_calls=0;
std::set<std::array<float,3>> uniform_values;
unsigned long long aux_pixels=0,aux_metal_zero=0,aux_metal_one=0,aux_rough_half=0,aux_rough_one=0,aux_ao_zero=0,aux_ao_one=0;
bool aux_read=false;
std::string variant() {
 const char* p=std::getenv("FOOTBALL_MATERIAL_VARIANT");
 return p?p:"";
}
template<class T> T proc(const char* name) {
 auto p=eglGetProcAddress(name);
 if(!p)std::abort();
 return reinterpret_cast<T>(p);
}
template<class T> T next(const char* name) {
 auto p=dlsym(RTLD_NEXT,name);
 if(!p) std::abort();
 return reinterpret_cast<T>(p);
}
__attribute__((destructor)) void finish() {
 const char* path=std::getenv("FOOTBALL_MATERIAL_TRACE");
 if(!path)return;
 FILE* f=std::fopen(path,"wx");
 if(!f)std::abort();
 std::fprintf(f,R"({"queue_calls":%llu,"material_indices":%llu,"same_texture_pairs":%llu,"uniform_calls":%llu,"nondefault_uniform_calls":%llu,"split_uniform_calls":%llu,"distinct_uniform_values":%zu,"aux_read":%d,"aux_pixels":%llu,"aux_metal_zero":%llu,"aux_metal_one":%llu,"aux_rough_half":%llu,"aux_rough_one":%llu,"aux_ao_zero":%llu,"aux_ao_one":%llu})" "\n",
  queue_calls,material_indices,same_texture_pairs,uniform_calls,nondefault_uniform_calls,split_uniform_calls,uniform_values.size(),int(aux_read),aux_pixels,aux_metal_zero,aux_metal_one,aux_rough_half,aux_rough_one,aux_ao_zero,aux_ao_one);
 if(std::fclose(f))std::abort();
}
}
extern "C" void ProbeRender(void*,const std::deque<blunted::VertexBufferQueueEntry>&,blunted::e_RenderMode)
 asm("_ZN7blunted16OpenGLRenderer3D18RenderVertexBufferERKSt5dequeINS_22VertexBufferQueueEntryESaIS2_EENS_12e_RenderModeE");
extern "C" void ProbeRender(void* self,const std::deque<blunted::VertexBufferQueueEntry>& queue,blunted::e_RenderMode mode) {
 static auto fn=next<void(*)(void*,const std::deque<blunted::VertexBufferQueueEntry>&,blunted::e_RenderMode)>(
  "_ZN7blunted16OpenGLRenderer3D18RenderVertexBufferERKSt5dequeINS_22VertexBufferQueueEntryESaIS2_EENS_12e_RenderModeE");
 ++queue_calls;
 const auto v=variant();
 if(!v.empty()) {
  for(const auto& entry:queue) {
   auto* indices=entry.vertexBufferIndices;
   if(!indices)continue;
   unsigned index=0;
   int previous_texture=-1;
   for(auto& item:*indices) {
    auto* resource=item.material.diffuseTexture?item.material.diffuseTexture->GetResource():nullptr;
    const int texture=resource?resource->GetID():0;
    if(previous_texture==texture && previous_texture>=0)++same_texture_pairs;
    previous_texture=texture;
    if(v=="baseline") {item.material.metallic=0.f;item.material.roughness=.5f;item.material.ao=1.f;}
    else if(v=="metal") {item.material.metallic=1.f;item.material.roughness=.5f;item.material.ao=1.f;}
    else if(v=="rough") {item.material.metallic=0.f;item.material.roughness=1.f;item.material.ao=1.f;}
    else if(v=="occluded") {item.material.metallic=0.f;item.material.roughness=.5f;item.material.ao=0.f;}
    else if(v=="split") {item.material.metallic=index%2?1.f:0.f;item.material.roughness=.5f;item.material.ao=1.f;}
    else std::abort();
    ++material_indices;
    ++index;
   }
  }
 }
 fn(self,queue,mode);
}
extern "C" void ProbeUniform(void*,const std::string&,const std::string&,float,float,float)
 asm("_ZN7blunted16OpenGLRenderer3D16SetUniformFloat3ERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEES8_fff");
extern "C" void ProbeUniform(void* self,const std::string& shader,const std::string& name,float x,float y,float z) {
 static auto fn=next<void(*)(void*,const std::string&,const std::string&,float,float,float)>(
  "_ZN7blunted16OpenGLRenderer3D16SetUniformFloat3ERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEES8_fff");
 if(shader=="pbr_geometry" && name=="materialPBR") {
  ++uniform_calls;
  uniform_values.insert({x,y,z});
  if(x!=0.f || y!=.5f || z!=1.f)++nondefault_uniform_calls;
  if(variant()=="split")++split_uniform_calls;
 }
 fn(self,shader,name,x,y,z);
}

extern "C" void ProbeOverlay(void*) asm("_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
extern "C" void ProbeOverlay(void* self) {
 static auto fn=next<void(*)(void*)>("_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
 if(!aux_read) {
  auto get=proc<void(*)(GLenum,GLint*)>("glGetIntegerv");
  auto location=proc<GLint(*)(GLuint,const GLchar*)>("glGetUniformLocation");
  GLint program=0,old_active=0,tex=0,width=0,height=0;
  get(GL_CURRENT_PROGRAM,&program);
  if(program>0 && location(program,"irradianceMap")>=0) {
   auto active=proc<void(*)(GLenum)>("glActiveTexture");
   auto level=proc<void(*)(GLenum,GLint,GLenum,GLint*)>("glGetTexLevelParameteriv");
   auto image=proc<void(*)(GLenum,GLint,GLenum,GLenum,void*)>("glGetTexImage");
   auto error=proc<GLenum(*)()>("glGetError");
   get(GL_ACTIVE_TEXTURE,&old_active);
   active(GL_TEXTURE3);
   get(GL_TEXTURE_BINDING_2D,&tex);
   if(tex<=0)std::abort();
   level(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width);
   level(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&height);
   if(width<=0 || height<=0 || width>4096 || height>4096)std::abort();
   std::vector<float> data(size_t(width)*size_t(height)*4);
   image(GL_TEXTURE_2D,0,GL_RGBA,GL_FLOAT,data.data());
   if(error()!=GL_NO_ERROR)std::abort();
   active(GLenum(old_active));
   for(size_t i=0;i<data.size();i+=4) {
    const float m=data[i],r=data[i+1],a=data[i+2];
    if(!std::isfinite(m)||!std::isfinite(r)||!std::isfinite(a))std::abort();
    if(r<.04f)continue;
    ++aux_pixels;
    if(std::abs(m)<.02f)++aux_metal_zero;
    if(std::abs(m-1.f)<.02f)++aux_metal_one;
    if(std::abs(r-.5f)<.02f)++aux_rough_half;
    if(std::abs(r-1.f)<.02f)++aux_rough_one;
    if(std::abs(a)<.02f)++aux_ao_zero;
    if(std::abs(a-1.f)<.02f)++aux_ao_one;
   }
   aux_read=true;
  }
 }
 fn(self);
}
