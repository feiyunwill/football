#include <EGL/egl.h>
#include <SDL_opengl.h>
#include <dlfcn.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <vector>

namespace {
GLuint captured[3]{};
template<class F> F Proc(const char* name) {
  auto ptr = eglGetProcAddress(name);
  if (!ptr) std::abort();
  return reinterpret_cast<F>(ptr);
}
struct Stats {
  double min=std::numeric_limits<double>::infinity();
  double max=-std::numeric_limits<double>::infinity();
  double sum=0;
  size_t count=0;
  void Add(float value) {
    if (!std::isfinite(value)) std::abort();
    min=std::min(min,double(value));
    max=std::max(max,double(value));
    sum+=value;
    ++count;
  }
};
void Readback() {
  const char* path=std::getenv("FOOTBALL_PBR_RESOURCE_TRACE");
  if (!path) std::abort();
  FILE* out=std::fopen(path,"wx");
  if (!out) std::abort();
  auto get=Proc<void(*)(GLenum,GLint*)>("glGetIntegerv");
  auto active=Proc<void(*)(GLenum)>("glActiveTexture");
  auto level=Proc<void(*)(GLenum,GLint,GLenum,GLint*)>("glGetTexLevelParameteriv");
  auto image=Proc<void(*)(GLenum,GLint,GLenum,GLenum,void*)>("glGetTexImage");
  auto error=Proc<GLenum(*)()>("glGetError");
  GLint old=0;
  get(GL_ACTIVE_TEXTURE,&old);
  std::fprintf(out,"{\"textures\":{");
  auto read=[&](const char* name,int unit,bool cube,int mip,int channels,bool comma) {
    active(GL_TEXTURE0+unit);
    GLint id=0,w=0,h=0;
    get(cube?GL_TEXTURE_BINDING_CUBE_MAP:GL_TEXTURE_BINDING_2D,&id);
    if(id<=0)std::abort();
    if(unit==4)captured[0]=GLuint(id);
    if(unit==5)captured[1]=GLuint(id);
    if(unit==6)captured[2]=GLuint(id);
    const int faceCount=cube?6:1;
    const int storedChannels=cube?4:2;
    Stats stats;
    for(int face=0;face<faceCount;++face) {
      const GLenum target=cube?GL_TEXTURE_CUBE_MAP_POSITIVE_X+face:GL_TEXTURE_2D;
      level(target,mip,GL_TEXTURE_WIDTH,&w);
      level(target,mip,GL_TEXTURE_HEIGHT,&h);
      if(w<=0||h!=w)std::abort();
      std::vector<float> values(size_t(w)*h*storedChannels);
      image(target,mip,cube?GL_RGBA:GL_RG,GL_FLOAT,values.data());
      if(error()!=GL_NO_ERROR)std::abort();
      for(size_t i=0;i<size_t(w)*h;++i)
        for(int ch=0;ch<channels;++ch)stats.Add(values[i*storedChannels+ch]);
    }
    if(stats.count!=size_t(faceCount)*w*h*channels)std::abort();
    std::fprintf(out,"%s\"%s\":{\"id\":%d,\"mip\":%d,\"size\":%d,"
       "\"faces\":%d,\"min\":%.9g,\"max\":%.9g,\"mean\":%.9g}",
       comma?",":"",name,id,mip,w,faceCount,stats.min,stats.max,
       stats.sum/double(stats.count));
  };
  read("irradiance",4,true,0,3,false);
  read("prefilter_sharp",5,true,0,3,true);
  read("prefilter_rough",5,true,4,3,true);
  read("brdf_lut",6,false,0,2,true);
  active(GLenum(old));
  std::fprintf(out,"}}\n");
  if(std::fclose(out))std::abort();
}
}
extern "C" void ProbeFullscreen(void*) asm("_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
extern "C" void ProbeFullscreen(void* self) {
  static auto next=reinterpret_cast<void(*)(void*)>(
      dlsym(RTLD_NEXT,"_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv"));
  if(!next)std::abort();
  static bool done=false;
  if(!done) {
    auto get=Proc<void(*)(GLenum,GLint*)>("glGetIntegerv");
    auto location=Proc<GLint(*)(GLuint,const GLchar*)>("glGetUniformLocation");
    GLint program=0;get(GL_CURRENT_PROGRAM,&program);
    if(program>0 && location(program,"irradianceMap")>=0) {
      done=true;
      Readback();
    }
  }
  next(self);
}

extern "C" void ProbeDestroy(void*)
  asm("_ZN7blunted16OpenGLRenderer3D19DestroyIBLResourcesEv");
extern "C" void ProbeDestroy(void* self) {
  static auto next=reinterpret_cast<void(*)(void*)>(
      dlsym(RTLD_NEXT,"_ZN7blunted16OpenGLRenderer3D19DestroyIBLResourcesEv"));
  if(!next)std::abort();
  auto isTexture=Proc<GLboolean(*)(GLuint)>("glIsTexture");
  const int before[3]={int(isTexture(captured[0])),
                       int(isTexture(captured[1])),
                       int(isTexture(captured[2]))};
  next(self);
  if(!captured[0])return;
  const char* path=std::getenv("FOOTBALL_PBR_RELEASE_TRACE");
  if(!path)std::abort();
  FILE* out=std::fopen(path,"a");
  if(!out)std::abort();
  std::fprintf(out,"{\"ids\":[%u,%u,%u],\"live_before\":[%d,%d,%d],"
      "\"live_after\":[%d,%d,%d]}\n",captured[0],captured[1],captured[2],
      before[0],before[1],before[2],
      int(isTexture(captured[0])),int(isTexture(captured[1])),
      int(isTexture(captured[2])));
  if(std::fclose(out))std::abort();
  captured[0]=captured[1]=captured[2]=0;
}
