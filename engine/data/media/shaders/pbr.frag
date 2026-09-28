#version 150
// Deferred Cook-Torrance direct lighting. Geometry textures contain world-space
// normals, linear albedo (decoded by sRGB texture sampling), and material M/R/AO.
uniform sampler2D map_albedo;
uniform sampler2D map_normal;
uniform sampler2D map_depth;
uniform sampler2D map_aux;
uniform sampler2DShadow map_shadow;
uniform mat4 inverseProjectionViewMatrix;
uniform mat4 lightViewProjectionMatrix;
uniform float contextWidth;
uniform float contextHeight;
uniform float contextX;
uniform float contextY;
uniform bool has_shadow;
uniform vec3 cameraPosition;
uniform vec3 lightPosition;
uniform vec3 lightColor;
uniform float lightRadius;
out vec4 stdout0;
out vec4 stdout1;
const float PI = 3.14159265359;

vec3 safeDirection(vec3 value, vec3 fallback) {
    float squaredLength = dot(value, value);
    return squaredLength > 1e-12 ? value * inversesqrt(squaredLength) : fallback;
}
float distributionGGX(float NdotH, float roughness) {
    float alpha = roughness * roughness;
    float alphaSquared = alpha * alpha;
    float d = NdotH * NdotH * (alphaSquared - 1.0) + 1.0;
    return alphaSquared / max(PI * d * d, 1e-8);
}
float geometrySchlickGGX(float NdotDirection, float roughness) {
    float r = roughness + 1.0;
    float k = r * r / 8.0;
    return NdotDirection / max(NdotDirection * (1.0 - k) + k, 1e-8);
}
float shadowVisibility(vec3 worldPosition) {
    if (!has_shadow) return 1.0;
    vec2 offsets[9] = vec2[9](
        vec2(0.5,0.5),vec2(-0.5,0.5),vec2(0.5,-0.5),vec2(-0.5,-0.5),
        vec2(1,0),vec2(0,1),vec2(-1,0),vec2(0,-1),vec2(0,0));
    vec4 projected = lightViewProjectionMatrix * vec4(worldPosition,1.0);
    float visibility = 0.0;
    for (int i=0;i<9;++i)
        visibility += textureProj(map_shadow,projected+
            vec4(offsets[i],0,0)/1500.0+vec4(0,0,-0.0002,0));
    return clamp(visibility/9.0,0.0,1.0);
}
void main() {
    vec2 uv = (gl_FragCoord.xy-vec2(contextX,contextY))/
              vec2(contextWidth,contextHeight);
    float depth = texture(map_depth,uv).r;
    if (depth >= 1.0) discard;
    vec4 world = inverseProjectionViewMatrix*vec4(uv*2.0-1.0,depth*2.0-1.0,1.0);
    vec3 worldPosition = world.xyz/world.w;
    vec3 albedo = max(texture(map_albedo,uv).rgb,vec3(0.0));
    vec3 parameters = clamp(texture(map_aux,uv).rgb,vec3(0.0),vec3(1.0));
    float metallic = parameters.r;
    float roughness = max(parameters.g,0.045);
    vec3 N = safeDirection(texture(map_normal,uv).xyz,vec3(0,0,1));
    vec3 V = safeDirection(cameraPosition-worldPosition,N);
    vec3 toLight = lightPosition-worldPosition;
    vec3 L = safeDirection(toLight,N);
    vec3 H = safeDirection(V+L,N);
    float NdotL=max(dot(N,L),0.0),NdotV=max(dot(N,V),0.0);
    vec3 F0=mix(vec3(0.04),albedo,metallic);
    vec3 F=F0+(1.0-F0)*pow(1.0-clamp(dot(H,V),0.0,1.0),5.0);
    float D=distributionGGX(max(dot(N,H),0.0),roughness);
    float G=geometrySchlickGGX(NdotV,roughness)*geometrySchlickGGX(NdotL,roughness);
    vec3 specular=D*G*F/max(4.0*NdotV*NdotL,1e-5);
    vec3 diffuse=(1.0-F)*(1.0-metallic)*albedo/PI;
    float attenuation=clamp(1.0-length(toLight)/max(lightRadius,1e-6),0.0,1.0);
    vec3 radiance=lightColor*attenuation*attenuation;
    // Keep lighting linear HDR; the later tone-map pass owns display encoding.
    stdout0=vec4((diffuse+specular)*radiance*NdotL*shadowVisibility(worldPosition),0.0);
    stdout1=vec4(0.0);
}
