import React from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { recordPhoneDebug } from '../utils/phoneDebug';
import { colors, spacing } from '../styles/theme';

type State = { error: Error | null };

export class PhoneErrorBoundary extends React.Component<React.PropsWithChildren, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    void recordPhoneDebug('error', 'ui_crash', {
      message: error.message,
      stack: error.stack,
      componentStack: info.componentStack,
    });
  }

  render() {
    const error = this.state.error;
    if (!error) return this.props.children;
    return (
      <View style={styles.screen}>
        <Text style={styles.title}>NC Remote could not open</Text>
        <Text style={styles.meta}>App 0.1.0 / {Platform.OS} {String(Platform.Version)}</Text>
        <ScrollView style={styles.errorBox}>
          <Text selectable style={styles.errorText}>{error.stack || error.message || 'Unknown application error.'}</Text>
        </ScrollView>
        <Text style={styles.note}>The crash was saved locally and will be sent to the desktop after the next successful connection.</Text>
        <Pressable style={styles.button} onPress={() => this.setState({ error: null })}>
          <Text style={styles.buttonText}>Try again</Text>
        </Pressable>
      </View>
    );
  }
}

const styles = StyleSheet.create({
  screen: { backgroundColor: colors.background, flex: 1, gap: spacing.md, padding: spacing.lg, paddingTop: 64 },
  title: { color: colors.text, fontSize: 22, fontWeight: '800' },
  meta: { color: colors.muted, fontSize: 13 },
  errorBox: { backgroundColor: '#080b0f', borderColor: colors.border, borderRadius: 6, borderWidth: 1, maxHeight: 360, padding: spacing.md },
  errorText: { color: '#f0b8b8', fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace', fontSize: 12, lineHeight: 17 },
  note: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  button: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: 6, padding: spacing.md },
  buttonText: { color: '#061018', fontSize: 14, fontWeight: '900' },
});
