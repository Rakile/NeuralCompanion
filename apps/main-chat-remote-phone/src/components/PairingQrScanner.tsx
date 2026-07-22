import { CameraView, type BarcodeScanningResult, useCameraPermissions } from 'expo-camera';
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Linking, Modal, Pressable, SafeAreaView, StatusBar, StyleSheet, Text, View } from 'react-native';

import { colors, spacing } from '../styles/theme';
import { parsePairingSetupUri, type PairingSetup } from '../utils/pairingSetup';

type Props = {
  visible: boolean;
  onCancel: () => void;
  onPairingScanned: (setup: PairingSetup) => void;
};

export function PairingQrScanner({ visible, onCancel, onPairingScanned }: Props) {
  const [permission, requestPermission] = useCameraPermissions();
  const [error, setError] = useState('');
  const [scanLocked, setScanLocked] = useState(false);
  const scanLockedRef = useRef(false);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (visible) {
      scanLockedRef.current = false;
      setScanLocked(false);
      setError('');
    }
    return () => {
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [visible]);

  const handleBarcode = (result: BarcodeScanningResult) => {
    if (scanLockedRef.current) {
      return;
    }
    scanLockedRef.current = true;
    setScanLocked(true);
    const setup = parsePairingSetupUri(result.data);
    if (setup) {
      onPairingScanned(setup);
      return;
    }
    setError('This is not a NeuralCompanion pairing QR code.');
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      scanLockedRef.current = false;
      setScanLocked(false);
    }, 1200);
  };

  const askForPermission = () => {
    setError('');
    requestPermission().catch(() => setError('Camera permission could not be requested.'));
  };

  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onCancel} statusBarTranslucent>
      <SafeAreaView style={styles.screen}>
        <StatusBar barStyle="light-content" backgroundColor={colors.background} />
        <View style={styles.header}>
          <Text style={styles.title}>Scan pairing QR code</Text>
          <Pressable style={styles.closeButton} onPress={onCancel} accessibilityRole="button">
            <Text style={styles.closeButtonText}>Close</Text>
          </Pressable>
        </View>

        {!permission ? (
          <View style={styles.centered}>
            <ActivityIndicator color={colors.accent} size="large" />
          </View>
        ) : permission.granted ? (
          <View style={styles.cameraArea}>
            <CameraView
              style={styles.camera}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
              onBarcodeScanned={scanLocked ? undefined : handleBarcode}
              onMountError={(event) => setError(event.message || 'Camera could not be started.')}
            />
            <View pointerEvents="none" style={styles.scanFrame} />
          </View>
        ) : (
          <View style={styles.centered}>
            <Text style={styles.permissionTitle}>Camera access required</Text>
            <Text style={styles.permissionText}>Allow camera access to scan the pairing code shown in NeuralCompanion.</Text>
            <Pressable
              style={styles.permissionButton}
              onPress={permission.canAskAgain ? askForPermission : () => Linking.openSettings().catch(() => undefined)}
            >
              <Text style={styles.permissionButtonText}>{permission.canAskAgain ? 'Allow camera' : 'Open settings'}</Text>
            </Pressable>
          </View>
        )}

        <View style={styles.footer}>
          <Text style={styles.hint}>Point the camera at the QR code in Main Chat Remote.</Text>
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: {
    backgroundColor: colors.background,
    flex: 1,
  },
  header: {
    alignItems: 'center',
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
    flexDirection: 'row',
    justifyContent: 'space-between',
    minHeight: 58,
    paddingHorizontal: spacing.lg,
  },
  title: {
    color: colors.text,
    fontSize: 17,
    fontWeight: '800',
  },
  closeButton: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    minHeight: 36,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  closeButtonText: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '800',
  },
  cameraArea: {
    flex: 1,
    justifyContent: 'center',
  },
  camera: {
    ...StyleSheet.absoluteFillObject,
  },
  scanFrame: {
    alignSelf: 'center',
    aspectRatio: 1,
    borderColor: colors.accent,
    borderRadius: 8,
    borderWidth: 3,
    width: '72%',
  },
  centered: {
    alignItems: 'center',
    flex: 1,
    gap: spacing.md,
    justifyContent: 'center',
    padding: spacing.lg,
  },
  permissionTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '800',
  },
  permissionText: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    maxWidth: 320,
    textAlign: 'center',
  },
  permissionButton: {
    alignItems: 'center',
    backgroundColor: colors.accent,
    borderRadius: 6,
    minHeight: 42,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  permissionButtonText: {
    color: '#061019',
    fontSize: 14,
    fontWeight: '800',
  },
  footer: {
    alignItems: 'center',
    backgroundColor: colors.panel,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    gap: spacing.xs,
    minHeight: 86,
    justifyContent: 'center',
    padding: spacing.md,
  },
  hint: {
    color: colors.text,
    fontSize: 13,
    textAlign: 'center',
  },
  error: {
    color: colors.danger,
    fontSize: 12,
    textAlign: 'center',
  },
});
