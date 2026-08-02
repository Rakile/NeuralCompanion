import type { LiveFullscreenSettings } from './liveFullscreenSettings';

export type TouchPoint = {
  pageX: number;
  pageY: number;
};

export type TwoTouchMetrics = {
  midpointX: number;
  midpointY: number;
  distance: number;
};

export type FullscreenFrame = {
  left: number;
  top: number;
  width: number;
  height: number;
};

export type FullscreenLayout = {
  width: number;
  height: number;
};

export type FullscreenTransformTarget = 'circle' | 'background' | null;

type CircleTransformStart = Pick<
  LiveFullscreenSettings,
  'circleSizePct' | 'circleHorizontalPositionPct' | 'verticalPositionPct'
>;

type BackgroundTransformStart = Pick<
  LiveFullscreenSettings,
  'backgroundScalePct' | 'backgroundOffsetXPct' | 'backgroundOffsetYPct'
>;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function finite(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function rounded(value: number): number {
  return Number(value.toFixed(3));
}

export function sliderValueFromDrag(
  startValue: number,
  deltaX: number,
  trackWidth: number,
  minimum: number,
  maximum: number,
  step: number,
): number {
  const lower = Math.min(finite(minimum), finite(maximum));
  const upper = Math.max(finite(minimum), finite(maximum));
  const width = Math.max(1, finite(trackWidth, 1));
  const increment = Math.max(Number.EPSILON, Math.abs(finite(step, 1)));
  const raw = finite(startValue, lower) + finite(deltaX) / width * (upper - lower);
  const stepped = lower + Math.round((raw - lower) / increment) * increment;
  return rounded(clamp(stepped, lower, upper));
}

export function twoTouchMetrics(
  touches: readonly TouchPoint[] | null | undefined,
): TwoTouchMetrics | null {
  if (!touches || touches.length < 2) {
    return null;
  }
  const firstX = Number(touches[0]?.pageX);
  const firstY = Number(touches[0]?.pageY);
  const secondX = Number(touches[1]?.pageX);
  const secondY = Number(touches[1]?.pageY);
  if (![firstX, firstY, secondX, secondY].every(Number.isFinite)) {
    return null;
  }
  return {
    midpointX: rounded((firstX + secondX) / 2),
    midpointY: rounded((firstY + secondY) / 2),
    distance: rounded(Math.hypot(secondX - firstX, secondY - firstY)),
  };
}

type FullscreenTouchEvent = {
  nativeEvent: {
    touches: readonly TouchPoint[];
  };
};

type FullscreenMoveGesture = {
  dx: number;
  dy: number;
};

type FullscreenTransformResponderOptions = {
  isTransforming: () => boolean;
  onSingleTouchMove: (distancePx: number) => void;
  onTransformContact: (metrics: TwoTouchMetrics) => void;
  onTransformEnd: () => void;
};

export function createFullscreenTransformResponderCallbacks(
  options: FullscreenTransformResponderOptions,
) {
  const handleTransformContact = (event: FullscreenTouchEvent): boolean => {
    const metrics = twoTouchMetrics(event.nativeEvent.touches);
    if (!metrics) {
      return false;
    }
    options.onTransformContact(metrics);
    return true;
  };

  return {
    onPanResponderStart: (event: FullscreenTouchEvent) => {
      handleTransformContact(event);
    },
    onPanResponderMove: (
      event: FullscreenTouchEvent,
      gesture: FullscreenMoveGesture,
    ) => {
      if (handleTransformContact(event)) {
        return;
      }
      if (options.isTransforming()) {
        options.onTransformEnd();
        return;
      }
      options.onSingleTouchMove(Math.hypot(Number(gesture.dx) || 0, Number(gesture.dy) || 0));
    },
    onPanResponderEnd: (event: FullscreenTouchEvent) => {
      if (options.isTransforming() && event.nativeEvent.touches.length < 2) {
        options.onTransformEnd();
      }
    },
  };
}

export function chooseTransformTarget(
  midpoint: Pick<TwoTouchMetrics, 'midpointX' | 'midpointY'> | null,
  circleFrame: FullscreenFrame,
  backgroundActive: boolean,
): FullscreenTransformTarget {
  if (!midpoint) {
    return null;
  }
  const left = finite(circleFrame.left);
  const top = finite(circleFrame.top);
  const width = Math.max(0, finite(circleFrame.width));
  const height = Math.max(0, finite(circleFrame.height));
  const radiusX = width / 2;
  const radiusY = height / 2;
  const normalizedX = radiusX > 0
    ? (midpoint.midpointX - (left + radiusX)) / radiusX
    : Number.POSITIVE_INFINITY;
  const normalizedY = radiusY > 0
    ? (midpoint.midpointY - (top + radiusY)) / radiusY
    : Number.POSITIVE_INFINITY;
  const insideCircle = normalizedX ** 2 + normalizedY ** 2 <= 1;
  if (insideCircle) {
    return 'circle';
  }
  return backgroundActive ? 'background' : null;
}

function scaleRatio(initial: TwoTouchMetrics, current: TwoTouchMetrics): number {
  const initialDistance = finite(initial.distance);
  const currentDistance = finite(current.distance);
  if (initialDistance <= Number.EPSILON || currentDistance < 0) {
    return 1;
  }
  return currentDistance / initialDistance;
}

export function circleTransformFromGesture(
  start: CircleTransformStart,
  initial: TwoTouchMetrics,
  current: TwoTouchMetrics,
  layout: FullscreenLayout,
): Partial<LiveFullscreenSettings> {
  const width = Math.max(1, finite(layout.width, 1));
  const height = Math.max(1, finite(layout.height, 1));
  return {
    circleSizePct: rounded(clamp(finite(start.circleSizePct, 100) * scaleRatio(initial, current), 25, 200)),
    circleHorizontalPositionPct: rounded(clamp(
      finite(start.circleHorizontalPositionPct, 50)
        + (finite(current.midpointX) - finite(initial.midpointX)) / width * 100,
      10,
      90,
    )),
    verticalPositionPct: rounded(clamp(
      finite(start.verticalPositionPct, 34)
        + (finite(current.midpointY) - finite(initial.midpointY)) / height * 100,
      10,
      90,
    )),
  };
}

export function backgroundTransformFromGesture(
  start: BackgroundTransformStart,
  initial: TwoTouchMetrics,
  current: TwoTouchMetrics,
  layout: FullscreenLayout,
): Partial<LiveFullscreenSettings> {
  const width = Math.max(1, finite(layout.width, 1));
  const height = Math.max(1, finite(layout.height, 1));
  return {
    backgroundScalePct: rounded(clamp(
      finite(start.backgroundScalePct, 100) * scaleRatio(initial, current),
      25,
      200,
    )),
    backgroundOffsetXPct: rounded(clamp(
      finite(start.backgroundOffsetXPct)
        + (finite(current.midpointX) - finite(initial.midpointX)) / width * 100,
      -100,
      100,
    )),
    backgroundOffsetYPct: rounded(clamp(
      finite(start.backgroundOffsetYPct)
        + (finite(current.midpointY) - finite(initial.midpointY)) / height * 100,
      -100,
      100,
    )),
  };
}
