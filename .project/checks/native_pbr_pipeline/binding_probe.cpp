// Read-only GL state snapshots at actual engine pass entry/exit; forwards unchanged.
#include "systems/graphics/rendering/opengl_renderer3d.hpp"
#include <EGL/egl.h>
#include <SDL_opengl.h>
#include <dlfcn.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
namespace {
FILE* output=nullptr;unsigned long long sequence=0;
template<class F> F Proc(const char* name) {
 auto p=eglGetProcAddress(name);if(!p)std::abort();return reinterpret_cast<F>(p);
}
template<class F> F Next(const char* name) {
 auto p=dlsym(RTLD_NEXT,name);if(!p)std::abort();return reinterpret_cast<F>(p);
}
void Snapshot(const char* phase) {
 if(!output) {
  const char* path=std::getenv("FOOTBALL_PBR_BINDING_TRACE");if(!path)std::abort();
  output=std::fopen(path,"wx");if(!output)std::abort();
 }
 const auto get=Proc<void(*)(GLenum,GLint*)>("glGetIntegerv");
 const auto program_get=Proc<void(*)(GLuint,GLenum,GLint*)>("glGetProgramiv");
 const auto active_uniform=Proc<void(*)(GLuint,GLuint,GLsizei,GLsizei*,GLint*,GLenum*,GLchar*)>("glGetActiveUniform");
 const auto location=Proc<GLint(*)(GLuint,const GLchar*)>("glGetUniformLocation");
 const auto value_f=Proc<void(*)(GLuint,GLint,GLfloat*)>("glGetUniformfv");
 const auto value_i=Proc<void(*)(GLuint,GLint,GLint*)>("glGetUniformiv");
 const auto active=Proc<void(*)(GLenum)>("glActiveTexture");
 const auto texture_get=Proc<void(*)(GLenum,GLint,GLenum,GLint*)>("glGetTexLevelParameteriv");
 GLint program=0,fbo=0,viewport[4]{},old_active=0,draw0=0,draw1=0;
 get(GL_CURRENT_PROGRAM,&program);get(GL_DRAW_FRAMEBUFFER_BINDING,&fbo);get(GL_VIEWPORT,viewport);
 get(GL_ACTIVE_TEXTURE,&old_active);get(GL_DRAW_BUFFER0,&draw0);get(GL_DRAW_BUFFER1,&draw1);
 if(program<=0)std::abort();
 std::fprintf(output,"{\"sequence\":%llu,\"phase\":\"%s\",\"program\":%d,\"fbo\":%d,\"viewport\":[%d,%d,%d,%d],\"draw_buffers\":[%d,%d],\"uniforms\":{",
              ++sequence,phase,program,fbo,viewport[0],viewport[1],viewport[2],viewport[3],draw0,draw1);
 GLint count=0;program_get(program,GL_ACTIVE_UNIFORMS,&count);
 for(GLint i=0;i<count;++i) {
  char name[512]{};GLsizei length=0;GLint size=0;GLenum type=0;
  active_uniform(program,i,sizeof(name),&length,&size,&type,name);
  if(length<=0 || length>=511 || size<=0)std::abort();
  const GLint loc=location(program,name);if(loc<0)std::abort();
  std::fprintf(output,"%s\"%s\":{\"type\":%u,\"size\":%d,\"location\":%d,\"values\":[",i?",":"",name,unsigned(type),size,loc);
  const bool integer=type==GL_INT || type==GL_BOOL || type==GL_SAMPLER_2D || type==GL_SAMPLER_CUBE || type==GL_SAMPLER_2D_SHADOW;
  const unsigned components=type==GL_FLOAT_MAT4?16:type==GL_FLOAT_MAT3?9:type==GL_FLOAT_VEC4?4:type==GL_FLOAT_VEC3?3:type==GL_FLOAT_VEC2?2:1;
  if(integer){GLint value[16]{};value_i(program,loc,value);std::fprintf(output,"%d",value[0]);}
  else {
   GLfloat value[16]{};value_f(program,loc,value);
   for(unsigned j=0;j<components;++j) {
    if(!std::isfinite(value[j]))std::abort();
    std::fprintf(output,"%s%.9g",j?",":"",double(value[j]));
   }
  }
  std::fprintf(output,"]}");
 }
 std::fprintf(output,"},\"textures\":[");
 for(unsigned unit=0;unit<8;++unit) {
  active(GL_TEXTURE0+unit);GLint tex2d=0,cube=0,width=0,height=0,cube_width=0;
  get(GL_TEXTURE_BINDING_2D,&tex2d);get(GL_TEXTURE_BINDING_CUBE_MAP,&cube);
  if(tex2d) {texture_get(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width);texture_get(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&height);}
  if(cube)texture_get(GL_TEXTURE_CUBE_MAP_POSITIVE_X,0,GL_TEXTURE_WIDTH,&cube_width);
  std::fprintf(output,"%s{\"unit\":%u,\"texture2d\":%d,\"width\":%d,\"height\":%d,\"cube\":%d,\"cube_width\":%d}",
               unit?",":"",unit,tex2d,width,height,cube,cube_width);
 }
 active(GLenum(old_active));
 std::fprintf(output,"]}\n");if(std::fflush(output))std::abort();
}
__attribute__((destructor)) void Close() {if(output){if(std::fclose(output))std::abort();output=nullptr;}}
}
extern "C" void ProbeFullscreen(void*) asm("_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
extern "C" void ProbeFullscreen(void* self) {
 static const auto next=Next<void(*)(void*)>("_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
 Snapshot("fullscreen_entry");next(self);Snapshot("fullscreen_exit");
}
extern "C" void ProbeLights(void*,std::deque<blunted::LightQueueEntry>&,const blunted::Matrix4&,const blunted::Matrix4&)
 asm("_ZN7blunted16OpenGLRenderer3D12RenderLightsERSt5dequeINS_15LightQueueEntryESaIS2_EERKNS_7Matrix4ES8_");
extern "C" void ProbeLights(void* self,std::deque<blunted::LightQueueEntry>& queue,const blunted::Matrix4& projection,const blunted::Matrix4& view) {
 static const auto next=Next<void(*)(void*,std::deque<blunted::LightQueueEntry>&,const blunted::Matrix4&,const blunted::Matrix4&)>(
  "_ZN7blunted16OpenGLRenderer3D12RenderLightsERSt5dequeINS_15LightQueueEntryESaIS2_EERKNS_7Matrix4ES8_");
 Snapshot("lighting_entry");next(self,queue,projection,view);Snapshot("lighting_exit");
}
