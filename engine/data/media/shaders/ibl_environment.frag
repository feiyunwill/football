#version 150
uniform vec3 sunDirection;
uniform vec3 sunColor;
in vec2 faceUV;
uniform int faceIndex;
out vec4 FragColor;
vec3 faceDirection(int face, vec2 uv) {
    vec2 st = uv;
    if (face == 0) return normalize(vec3( 1.0, -st.y, -st.x));
    if (face == 1) return normalize(vec3(-1.0, -st.y,  st.x));
    if (face == 2) return normalize(vec3( st.x,  1.0,  st.y));
    if (face == 3) return normalize(vec3( st.x, -1.0, -st.y));
    if (face == 4) return normalize(vec3( st.x, -st.y,  1.0));
    return normalize(vec3(-st.x, -st.y, -1.0));
}

void main() {
    vec3 ray = faceDirection(faceIndex, faceUV);
    float altitude = clamp(ray.z, 0.0, 1.0);
    vec3 horizon = vec3(0.48, 0.59, 0.71);
    vec3 zenith = vec3(0.13, 0.35, 0.77);
    vec3 sky = mix(horizon, zenith, pow(altitude, 0.55));
    float below = clamp(-ray.z, 0.0, 1.0);
    vec3 ground = mix(vec3(0.24, 0.28, 0.20),
                      vec3(0.10, 0.16, 0.09), below);
    float sunCosine = max(dot(ray, normalize(sunDirection)), 0.0);
    float disc = pow(sunCosine, 2048.0);
    float halo = pow(sunCosine, 64.0);
    vec3 radiance = ray.z >= 0.0 ? sky : ground;
    radiance += max(sunColor, vec3(0.0)) * (6.0*disc + 0.22*halo);
    FragColor = vec4(radiance, 1.0);
}
