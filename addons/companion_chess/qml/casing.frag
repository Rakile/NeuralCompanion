VARYING vec3 casingPosition;

float grainHash(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}
float grainNoise(vec3 p) {
    vec3 cell = floor(p), f = fract(p);
    f = f*f*(3.0-2.0*f);
    return mix(mix(mix(grainHash(cell),grainHash(cell+vec3(1,0,0)),f.x),
                   mix(grainHash(cell+vec3(0,1,0)),grainHash(cell+vec3(1,1,0)),f.x),f.y),
               mix(mix(grainHash(cell+vec3(0,0,1)),grainHash(cell+vec3(1,0,1)),f.x),
                   mix(grainHash(cell+vec3(0,1,1)),grainHash(cell+vec3(1,1,1)),f.x),f.y),f.z);
}
void MAIN() {
    vec3 p = casingPosition * 1.3;
    // Fade sub-pixel grain to avoid sparkling while orbiting or zooming out.
    float footprint = max(length(dFdx(p)),length(dFdy(p)));
    float visibility = (1.0-smoothstep(0.7,2.4,footprint))*grainStrength;
    float grain = grainNoise(p);
    float height = (grain-0.5)*0.20*visibility;
    vec3 n = normalize(NORMAL);
    vec3 dx = dFdx(VAR_WORLD_POSITION), dy = dFdy(VAR_WORLD_POSITION);
    vec3 r1 = cross(dy,n), r2 = cross(n,dx);
    float determinant = dot(dx,r1);
    if (abs(determinant)>0.000001)
        NORMAL = normalize(abs(determinant)*n-sign(determinant)*(dFdx(height)*r1+dFdy(height)*r2));
    BASE_COLOR = vec4(casingColor.rgb*(1.0+(grain-0.5)*0.08*visibility),1.0);
    METALNESS = 0.0;
    ROUGHNESS = 0.48+(grain-0.5)*0.16*visibility;
    SPECULAR_AMOUNT = 0.5;
    CLEARCOAT_AMOUNT = 0.08;
    CLEARCOAT_ROUGHNESS = 0.4;
}
