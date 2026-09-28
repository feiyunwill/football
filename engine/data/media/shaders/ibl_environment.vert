#version 150
in vec4 position;
out vec2 faceUV;
void main() {
    faceUV = position.xy;
    gl_Position = vec4(position.xy, 0.0, 1.0);
}
