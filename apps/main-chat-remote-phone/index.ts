import { registerRootComponent } from 'expo';
import React from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import App from './App';
import { registerBackgroundPlayback } from './src/native/backgroundPlayback';
import { PhoneErrorBoundary } from './src/components/PhoneErrorBoundary';
import { registerAndroidPlaybackBackgroundTask } from './src/native/androidPlaybackBackground';

registerAndroidPlaybackBackgroundTask();

function Root() {
  return React.createElement(
    GestureHandlerRootView,
    { style: { flex: 1 } },
    React.createElement(PhoneErrorBoundary, null,
      React.createElement(SafeAreaProvider, null, React.createElement(App))),
  );
}

registerBackgroundPlayback();
registerRootComponent(Root);
