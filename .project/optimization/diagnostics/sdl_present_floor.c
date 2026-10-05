#define _POSIX_C_SOURCE 200809L
#include <SDL.h>
#include <SDL_opengl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double milliseconds(struct timespec start, struct timespec end) {
  return (end.tv_sec - start.tv_sec) * 1000.0 +
         (end.tv_nsec - start.tv_nsec) / 1000000.0;
}

static int gallium_path(char *buffer, size_t capacity) {
  FILE *maps = fopen("/proc/self/maps", "r");
  if (!maps) return 0;
  char line[4096];
  while (fgets(line, sizeof(line), maps)) {
    char *path = strchr(line, '/');
    if (!path || !strstr(path, "/libgallium-")) continue;
    path[strcspn(path, "\n")] = '\0';
    if (strlen(path) >= capacity) break;
    strcpy(buffer, path);
    fclose(maps);
    return 1;
  }
  fclose(maps);
  return 0;
}

int main(void) {
  if (SDL_InitSubSystem(SDL_INIT_VIDEO) != 0) {
    fprintf(stderr, "SDL init: %s\n", SDL_GetError());
    return 1;
  }
  SDL_GL_SetAttribute(SDL_GL_RED_SIZE, 8);
  SDL_GL_SetAttribute(SDL_GL_GREEN_SIZE, 8);
  SDL_GL_SetAttribute(SDL_GL_BLUE_SIZE, 8);
  SDL_GL_SetAttribute(SDL_GL_ALPHA_SIZE, 8);
  SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 16);
  SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
  SDL_Window *window = SDL_CreateWindow("Football present floor", SDL_WINDOWPOS_UNDEFINED,
                                        SDL_WINDOWPOS_UNDEFINED, 1920, 1080, SDL_WINDOW_OPENGL);
  if (!window) {
    fprintf(stderr, "SDL window: %s\n", SDL_GetError());
    return 1;
  }
  SDL_GLContext context = SDL_GL_CreateContext(window);
  if (!context || SDL_GL_SetSwapInterval(0) != 0 || SDL_GL_GetSwapInterval() != 0) {
    fprintf(stderr, "SDL context/swap: %s\n", SDL_GetError());
    return 1;
  }
  int width = 0, height = 0;
  SDL_GL_GetDrawableSize(window, &width, &height);
  const char *vendor = (const char *)glGetString(GL_VENDOR);
  const char *renderer = (const char *)glGetString(GL_RENDERER);
  const char *version = (const char *)glGetString(GL_VERSION);
  char gallium[4096] = {0};
  if (width != 1920 || height != 1080 || !vendor || !renderer || !version ||
      !gallium_path(gallium, sizeof(gallium))) {
    fprintf(stderr, "Wrong drawable size or GPU identity\n");
    return 1;
  }
  printf("IDENTITY\t%s\t%s\t%s\t%s\t%d\t%d\t%d\n", vendor, renderer,
         version, gallium, SDL_GL_GetSwapInterval(), width, height);
  for (int frame = 0; frame < 150; ++frame) {
    struct timespec before, submitted, after;
    clock_gettime(CLOCK_MONOTONIC, &before);
    glViewport(0, 0, width, height);
    glClearColor((float)(frame % 17) / 16.0f, 0.2f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    SDL_GL_SwapWindow(window);
    clock_gettime(CLOCK_MONOTONIC, &submitted);
    glFinish();
    clock_gettime(CLOCK_MONOTONIC, &after);
    if (glGetError() != GL_NO_ERROR) {
      fprintf(stderr, "OpenGL error on frame %d\n", frame);
      return 1;
    }
    if (frame >= 30)
      printf("FRAME\t%.6f\t%.6f\t%.6f\n", milliseconds(before, after),
             milliseconds(before, submitted), milliseconds(submitted, after));
  }
  SDL_GL_DeleteContext(context);
  SDL_DestroyWindow(window);
  SDL_QuitSubSystem(SDL_INIT_VIDEO);
  return 0;
}
