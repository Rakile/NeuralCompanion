import * as FileSystem from 'expo-file-system/legacy';
import * as ImagePicker from 'expo-image-picker';

import {
  isPrivateLiveFullscreenUri,
  normalizedImportedExtension,
  shouldDeleteReplacedBackground,
} from './liveFullscreenMediaPolicy';
import type { LiveFullscreenBackgroundKind } from './liveFullscreenSettings';

export type ImportedLiveFullscreenMedia = {
  backgroundKind: Extract<
    LiveFullscreenBackgroundKind,
    'custom_image' | 'custom_video'
  >;
  backgroundUri: string;
};

export const LIVE_FULLSCREEN_MEDIA_DIRECTORY = `${FileSystem.documentDirectory || ''}live-fullscreen/`;

function randomFileStem(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export async function importLiveFullscreenMedia(
  mediaType: 'image' | 'video',
  previousUri = '',
): Promise<ImportedLiveFullscreenMedia | null> {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!permission.granted) {
    throw new Error('Photo library permission is required to choose a background.');
  }
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: [mediaType === 'image' ? 'images' : 'videos'],
    allowsEditing: false,
    quality: 1,
  });
  if (result.canceled || !result.assets?.length) {
    return null;
  }
  const asset = result.assets[0]!;
  const extension = normalizedImportedExtension(
    String(asset.mimeType || ''),
    String(asset.fileName || asset.uri || ''),
  );
  if (!extension || (mediaType === 'video' && extension !== '.mp4') || (mediaType === 'image' && extension === '.mp4')) {
    throw new Error(mediaType === 'video' ? 'Choose an MP4 video.' : 'Choose a JPG, PNG, or WebP image.');
  }
  if (!FileSystem.documentDirectory) {
    throw new Error('Private app storage is unavailable.');
  }
  await FileSystem.makeDirectoryAsync(LIVE_FULLSCREEN_MEDIA_DIRECTORY, { intermediates: true });
  const nextUri = `${LIVE_FULLSCREEN_MEDIA_DIRECTORY}${randomFileStem()}${extension}`;
  await FileSystem.copyAsync({ from: asset.uri, to: nextUri });
  const copied = await FileSystem.getInfoAsync(nextUri);
  if (!copied.exists) {
    throw new Error('The selected background could not be copied.');
  }
  if (shouldDeleteReplacedBackground(previousUri, LIVE_FULLSCREEN_MEDIA_DIRECTORY, nextUri)) {
    await FileSystem.deleteAsync(previousUri, { idempotent: true }).catch(() => undefined);
  }
  return {
    backgroundKind: mediaType === 'video' ? 'custom_video' : 'custom_image',
    backgroundUri: nextUri,
  };
}

export async function removePrivateLiveFullscreenMedia(uri: string): Promise<void> {
  if (!isPrivateLiveFullscreenUri(uri, LIVE_FULLSCREEN_MEDIA_DIRECTORY)) {
    return;
  }
  await FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => undefined);
}
