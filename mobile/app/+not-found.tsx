import { Link } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Text, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

export default function NotFoundScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();

  return (
    <View
      style={{
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        gap: theme.spacing[4],
        padding: theme.spacing[6],
        backgroundColor: theme.colors.background,
      }}
    >
      <Text
        accessibilityRole="header"
        style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
      >
        {t('notFound.title')}
      </Text>
      <Link
        href="/"
        accessibilityRole="link"
        style={[
          theme.typography.bodyStrong,
          {
            color: theme.colors.primary,
            minHeight: theme.minTouchTarget,
            paddingVertical: theme.spacing[3],
          },
        ]}
      >
        {t('notFound.goHome')}
      </Link>
    </View>
  );
}
