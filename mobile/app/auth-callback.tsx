import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

/**
 * Landing route for the social sign-in redirect (`travelbuddy://auth-callback`). The browser
 * session hands the URL to the sign-in screen, which finishes the flow and navigates on; on
 * Android the deep link can also open this route, which only waits for that.
 */
export default function AuthCallback() {
  const theme = useAppTheme();
  return (
    <View style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <ActivityIndicator color={theme.colors.primary} />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
