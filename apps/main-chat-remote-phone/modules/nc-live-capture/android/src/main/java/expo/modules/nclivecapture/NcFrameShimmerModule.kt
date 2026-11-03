package expo.modules.nclivecapture

import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/** Decorative UI only. No capture engine, player, output ownership or events. */
class NcFrameShimmerModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("NCFrameShimmer")
    View(NcFrameShimmerView::class) {
      Prop("cornerRadius") { view: NcFrameShimmerView, value: Float -> view.cornerRadiusDp = value }
      Prop("durationMs") { view: NcFrameShimmerView, value: Int -> view.frameDurationMs = value }
    }
  }
}
