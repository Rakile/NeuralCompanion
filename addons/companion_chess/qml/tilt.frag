VARYING vec2 blurAxis;
void MAIN() {
    vec2 uv = INPUT_UV;
    // Position is measured from the top; aspect correction keeps the angle
    // consistent in narrow panels and fullscreen. Zero degrees is horizontal.
    vec2 screen = vec2(uv.x, FRAMEBUFFER_Y_UP > 0.0 ? 1.0-uv.y : uv.y);
    float a = radians(bandAngle);
    vec2 normal = vec2(-sin(a),cos(a));
    vec2 p = (screen-vec2(0.5))*vec2(INPUT_SIZE.x/INPUT_SIZE.y,1.0);
    float distanceFromBand = abs(dot(p,normal)-(focusPosition-0.5));
    float blend = smoothstep(focusWidth*.5,focusWidth*.5+.18,distanceFromBand);
    vec2 stepUV = blurAxis/INPUT_SIZE * blurAmount*blend*.25 * (INPUT_SIZE.y/900.0);
    vec2 edge = .5/INPUT_SIZE;
    vec4 sum = vec4(0.0);
    float total = 0.0;
    for (int i=-16;i<=16;++i) {
        float weight = exp(-float(i*i)/128.0);
        sum += texture(INPUT,clamp(uv+float(i)*stepUV,edge,vec2(1.0)-edge))*weight;
        total += weight;
    }
    FRAGCOLOR = sum/total;
}
