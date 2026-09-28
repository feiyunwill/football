#version 150

// Deferred split-sum IBL. Geometry stores linear albedo, world-space normal,
// depth, and metallic/perceptual-roughness/AO in the four G-buffer attachments.
uniform sampler2D map_albedo;
uniform sampler2D map_normal;
uniform sampler2D map_depth;
uniform sampler2D map_aux;
uniform samplerCube irradianceMap;
uniform samplerCube prefilterMap;
uniform sampler2D brdfLUT;
uniform mat4 inverseProjectionViewMatrix;
uniform vec3 cameraPosition;
uniform float contextWidth;
uniform float contextHeight;
uniform float contextX;
uniform float contextY;
out vec4 FragColor;

vec3 safeDirection(vec3 value, vec3 fallback) {
    float lengthSquared = dot(value, value);
    return lengthSquared > 1e-12 ? value * inversesqrt(lengthSquared) : fallback;
}

void main() {
    vec2 uv = (gl_FragCoord.xy - vec2(contextX, contextY)) /
              vec2(contextWidth, contextHeight);
    float depth = texture(map_depth, uv).r;
    if (depth >= 1.0) discard;

    vec4 world = inverseProjectionViewMatrix *
                 vec4(uv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
    if (abs(world.w) < 1e-6) discard;
    vec3 worldPosition = world.xyz / world.w;
    vec3 N = safeDirection(texture(map_normal, uv).xyz, vec3(0.0, 0.0, 1.0));
    vec3 V = safeDirection(cameraPosition - worldPosition, N);
    float NdotV = clamp(dot(N, V), 0.0, 1.0);

    vec3 albedo = max(texture(map_albedo, uv).rgb, vec3(0.0));
    vec3 material = clamp(texture(map_aux, uv).rgb, vec3(0.0), vec3(1.0));
    float metallic = material.r;
    float roughness = max(material.g, 0.045);
    float ao = material.b;

    vec3 F0 = mix(vec3(0.04), albedo, metallic);
    vec3 F = F0 + (max(vec3(1.0 - roughness), F0) - F0) *
                  pow(1.0 - NdotV, 5.0);
    vec3 kD = (vec3(1.0) - F) * (1.0 - metallic);
    vec3 irradiance = max(texture(irradianceMap, N).rgb, vec3(0.0));
    vec3 diffuse = irradiance * albedo;

    vec3 R = reflect(-V, N);
    vec3 prefiltered = max(textureLod(prefilterMap, R,
                                      roughness * 4.0).rgb, vec3(0.0));
    vec2 brdf = clamp(texture(brdfLUT, vec2(NdotV, roughness)).rg,
                      vec2(0.0), vec2(1.0));
    vec3 specular = prefiltered * (F * brdf.x + brdf.y);
    // Tone mapping and display transfer belong to the final full-screen pass.
    FragColor = vec4(max((kD * diffuse + specular) * ao, vec3(0.0)), 0.0);
}
