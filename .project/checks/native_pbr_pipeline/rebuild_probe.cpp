#include "systems/graphics/rendering/opengl_renderer3d.hpp"
#include <EGL/egl.h>
#include <SDL_opengl.h>
#include <dlfcn.h>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <string>
#include <vector>
namespace {
unsigned long long create_calls=0,ibl_draws=0,directional_seen=0;
std::array<GLuint,3> previous_ids{};
FILE* trace=nullptr;
FILE* destruction_trace=nullptr;
unsigned long long destruction_calls=0;
template<class T>T proc(const char* name){auto p=eglGetProcAddress(name);if(!p)std::abort();return reinterpret_cast<T>(p);}
template<class T>T next(const char* name){auto p=dlsym(RTLD_NEXT,name);if(!p)std::abort();return reinterpret_cast<T>(p);}
std::string variant(){const char* p=std::getenv("FOOTBALL_IBL_LIGHT_VARIANT");return p?p:"";}
__attribute__((destructor))void finish(){
 if(trace){if(std::fclose(trace))std::abort();trace=nullptr;}
 if(destruction_trace){if(std::fclose(destruction_trace))std::abort();destruction_trace=nullptr;}
 const char* path=std::getenv("FOOTBALL_IBL_LIGHT_SUMMARY");if(!path)return;
 FILE* f=std::fopen(path,"wx");if(!f)std::abort();
 std::fprintf(f,R"({"create_calls":%llu,"ibl_draws":%llu,"directional_seen":%llu,"destruction_calls":%llu})" "\n",create_calls,ibl_draws,directional_seen,destruction_calls);
 if(std::fclose(f))std::abort();
}
}
extern "C" void ProbeCreate(void*,const std::deque<blunted::LightQueueEntry>&)
 asm("_ZN7blunted16OpenGLRenderer3D18CreateIBLResourcesERKSt5dequeINS_15LightQueueEntryESaIS2_EE");
extern "C" void ProbeCreate(void* self,const std::deque<blunted::LightQueueEntry>& lights){
 static auto fn=next<void(*)(void*,const std::deque<blunted::LightQueueEntry>&)>(
  "_ZN7blunted16OpenGLRenderer3D18CreateIBLResourcesERKSt5dequeINS_15LightQueueEntryESaIS2_EE");
 ++create_calls;
 for(const auto& light:lights)if(light.type==0)++directional_seen;
 const auto v=variant();
 if(v=="changed" && create_calls>=4){
  auto modified=lights;
  blunted::LightQueueEntry synthetic;
  synthetic.type=0;
  synthetic.position=blunted::Vector3(1.f,0.f,0.f);
  synthetic.color=blunted::Vector3(4.f,.1f,.1f);
  modified.push_back(synthetic);
  fn(self,modified);
 } else if(v=="constant" || v=="changed") fn(self,lights);
 else std::abort();
}
extern "C" void ProbeOverlay(void*) asm("_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
extern "C" void ProbeOverlay(void* self){
 static auto fn=next<void(*)(void*)>("_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
 auto get=proc<void(*)(GLenum,GLint*)>("glGetIntegerv");
 auto location=proc<GLint(*)(GLuint,const GLchar*)>("glGetUniformLocation");
 GLint program=0;get(GL_CURRENT_PROGRAM,&program);
 if(program>0 && location(program,"irradianceMap")>=0){
  if(!trace){const char* path=std::getenv("FOOTBALL_IBL_LIGHT_TRACE");if(!path)std::abort();trace=std::fopen(path,"wx");if(!trace)std::abort();}
  ++ibl_draws;
  auto active=proc<void(*)(GLenum)>("glActiveTexture");
  auto texget=proc<void(*)(GLenum,GLint,GLenum,GLint*)>("glGetTexLevelParameteriv");
  auto image=proc<void(*)(GLenum,GLint,GLenum,GLenum,void*)>("glGetTexImage");
  auto istex=proc<GLboolean(*)(GLuint)>("glIsTexture");
  auto error=proc<GLenum(*)()>("glGetError");
  GLint old_active=0;get(GL_ACTIVE_TEXTURE,&old_active);
  std::array<GLuint,3> ids{};
  for(int i=0;i<3;++i){
   active(GL_TEXTURE4+i);
   GLint id=0;get(i<2?GL_TEXTURE_BINDING_CUBE_MAP:GL_TEXTURE_BINDING_2D,&id);
   if(id<=0)std::abort();
   ids[i]=GLuint(id);
  }
  std::array<int,3> old_live{};
  for(int i=0;i<3;++i)old_live[i]=previous_ids[i]?int(istex(previous_ids[i])):-1;
  active(GL_TEXTURE4);
  GLint width=0;texget(GL_TEXTURE_CUBE_MAP_POSITIVE_X,0,GL_TEXTURE_WIDTH,&width);
  if(width!=32)std::abort();
  std::vector<float> data(size_t(width)*size_t(width)*4);
  image(GL_TEXTURE_CUBE_MAP_POSITIVE_X,0,GL_RGBA,GL_FLOAT,data.data());
  if(error()!=GL_NO_ERROR)std::abort();
  double means[3]{};
  for(size_t i=0;i<data.size();i+=4)
   for(int c=0;c<3;++c){if(!std::isfinite(data[i+c]))std::abort();means[c]+=data[i+c];}
  for(double& v:means)v/=double(width*width);
  active(GLenum(old_active));
  std::fprintf(trace,R"({"draw":%llu,"create_calls":%llu,"ids":[%u,%u,%u],"old_live":[%d,%d,%d],"irr_mean":[%.9g,%.9g,%.9g]})" "\n",
   ibl_draws,create_calls,ids[0],ids[1],ids[2],old_live[0],old_live[1],old_live[2],means[0],means[1],means[2]);
  if(std::fflush(trace))std::abort();
  previous_ids=ids;
 }
 fn(self);
}

extern "C" void ProbeDestroy(void*) asm("_ZN7blunted16OpenGLRenderer3D19DestroyIBLResourcesEv");
extern "C" void ProbeDestroy(void* self){
 static auto fn=next<void(*)(void*)>("_ZN7blunted16OpenGLRenderer3D19DestroyIBLResourcesEv");
 auto istex=proc<GLboolean(*)(GLuint)>("glIsTexture");
 std::array<int,3> before{},after{};
 for(int i=0;i<3;++i)before[i]=previous_ids[i]?int(istex(previous_ids[i])):-1;
 fn(self);
 for(int i=0;i<3;++i)after[i]=previous_ids[i]?int(istex(previous_ids[i])):-1;
 ++destruction_calls;
 if(!destruction_trace){
  const char* path=std::getenv("FOOTBALL_IBL_DESTRUCTION_TRACE");if(!path)std::abort();
  destruction_trace=std::fopen(path,"wx");if(!destruction_trace)std::abort();
 }
 std::fprintf(destruction_trace,R"({"call":%llu,"after_create_calls":%llu,"ids":[%u,%u,%u],"live_before":[%d,%d,%d],"live_after":[%d,%d,%d]})" "\n",
  destruction_calls,create_calls,previous_ids[0],previous_ids[1],previous_ids[2],
  before[0],before[1],before[2],after[0],after[1],after[2]);
 if(std::fflush(destruction_trace))std::abort();
}
