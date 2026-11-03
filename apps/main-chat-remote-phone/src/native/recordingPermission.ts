import {Platform} from 'react-native';
import {AudioModule} from 'expo-audio';

/** Expo requests can briefly background Android even when already granted.
 * Recheck the OS on every capture start; never retain permission authority. */
export async function ensureRecordingPermission() {
  if (Platform.OS === 'android') {
    const current = await AudioModule.getRecordingPermissionsAsync();
    if (current.granted) return current;
  }
  return AudioModule.requestRecordingPermissionsAsync();
}
