#version 150

in vec4 position;
uniform mat4 orthoViewMatrix;
uniform mat4 orthoProjectionMatrix;

void main() {
    gl_Position = orthoProjectionMatrix * orthoViewMatrix * position;
}
