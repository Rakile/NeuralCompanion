package expo.modules.nclivecapture

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.RadialGradient
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Shader
import android.view.animation.LinearInterpolator
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.views.ExpoView
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/** 15E halo crescent: cached radial shaders, one surface, no media dependencies. */
class NcFrameShimmerView(context: Context, appContext: AppContext) : ExpoView(context, appContext) {
  private val density = resources.displayMetrics.density
  private val padding = 6f * density
  private val bounds = RectF()
  private val shift = Matrix()
  private val light = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = 2.5f * density }
  private val halo = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = 0xff58ddff.toInt() }
  private var gradient: RadialGradient? = null
  private var haloGradient: RadialGradient? = null
  private val edgeLengths = FloatArray(8)
  private var perimeter = 0f
  private var animator: ValueAnimator? = null
  private var phase = 0f
  private var radius = 0f
  private var played = false
  var frameDurationMs = 1412
  var cornerRadiusDp = 10f
    set(value) { field = value.coerceAtLeast(0f); rebuild(); invalidate() }

  init {
    setWillNotDraw(false)
    importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    isClickable = false
    isFocusable = false
  }

  private fun rebuild() {
    val w = width - 2f * padding
    val h = height - 2f * padding
    if (w <= 0f || h <= 0f) return
    val inset = 1.25f * density
    bounds.set(padding + inset, padding + inset, width - padding - inset, height - padding - inset)
    radius = (min(cornerRadiusDp * density, min(w, h) / 2f) - inset).coerceAtLeast(0f)
    // Match the sample's 120px pool on a 64px-high frame, scaled with the button.
    val spread = h * 120f / 64f
    gradient = RadialGradient(0f, 0f, spread,
      intArrayOf(0xffefffff.toInt(), 0xff58ddff.toInt(), 0x0058ddff), floatArrayOf(0f, .14f, 1f), Shader.TileMode.CLAMP)
    haloGradient = RadialGradient(0f, 0f, spread,
      intArrayOf(0xffa6f2ff.toInt(), 0x00a6f2ff), floatArrayOf(0f, 1f), Shader.TileMode.CLAMP)
    light.shader = gradient
    halo.shader = haloGradient
    perimeter = 0f
    for (i in edgeLengths.indices) {
      edgeLengths[i] = when {
        i % 2 == 1 -> (PI * radius / 2f).toFloat()
        i % 4 == 0 -> (w - 2f * inset - 2f * radius).coerceAtLeast(0f)
        else -> (h - 2f * inset - 2f * radius).coerceAtLeast(0f)
      }
      perimeter += edgeLengths[i]
    }
  }

  override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
    super.onSizeChanged(w, h, oldw, oldh)
    rebuild()
    startIfReady()
  }

  override fun onAttachedToWindow() { super.onAttachedToWindow(); startIfReady() }
  override fun onDetachedFromWindow() { stop(); super.onDetachedFromWindow() }
  override fun onWindowVisibilityChanged(visibility: Int) {
    super.onWindowVisibilityChanged(visibility)
    if (visibility == VISIBLE) startIfReady() else stop()
  }

  private fun startIfReady() {
    if (played || gradient == null || !isAttachedToWindow || windowVisibility != VISIBLE) return
    played = true
    animator = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = frameDurationMs.coerceIn(100, 10000).toLong()
      interpolator = LinearInterpolator()
      addUpdateListener { phase = it.animatedValue as Float; invalidate() }
      start()
    }
  }

  private fun stop() {
    animator?.removeAllUpdateListeners()
    animator?.cancel()
    animator = null
    phase = 0f
    invalidate()
  }

  override fun onDraw(canvas: Canvas) {
    super.onDraw(canvas)
    if (gradient == null) return
    val fade = min(1f, min(phase * 8f, (1f - phase) * 8f)).coerceAtLeast(0f)
    // Constant-speed clockwise orbit, starting where the top-left arc meets the top.
    var distance = (phase % 1f) * perimeter
    var edge = 0
    while (edge < 7 && distance >= edgeLengths[edge]) { distance -= edgeLengths[edge]; edge++ }
    val angle = if (edgeLengths[edge] > 0f) distance / edgeLengths[edge] * (PI / 2f).toFloat() else 0f
    val l = bounds.left; val t = bounds.top; val r = bounds.right; val b = bounds.bottom
    var x = l; var y = t
    when (edge) {
      0 -> { x = l + radius + distance }
      1 -> { x = r - radius + radius * sin(angle); y = t + radius - radius * cos(angle) }
      2 -> { x = r; y = t + radius + distance }
      3 -> { x = r - radius + radius * cos(angle); y = b - radius + radius * sin(angle) }
      4 -> { x = r - radius - distance; y = b }
      5 -> { x = l + radius - radius * sin(angle); y = b - radius + radius * cos(angle) }
      6 -> { y = b - radius - distance }
      7 -> { x = l + radius - radius * cos(angle); y = t + radius - radius * sin(angle) }
    }
    shift.setTranslate(x, y)
    gradient?.setLocalMatrix(shift)
    haloGradient?.setLocalMatrix(shift)
    // Layered strokes approximate the sample's soft shadow without a software blur layer.
    halo.strokeWidth = 12f * density
    halo.alpha = (255f * .10f * fade).toInt()
    canvas.drawRoundRect(bounds, radius, radius, halo)
    halo.strokeWidth = 5f * density
    halo.alpha = (255f * .45f * fade).toInt()
    canvas.drawRoundRect(bounds, radius, radius, halo)
    light.alpha = (255f * fade).toInt()
    canvas.drawRoundRect(bounds, radius, radius, light)
  }
}
