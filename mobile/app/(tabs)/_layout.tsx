import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import type { ComponentProps } from 'react';
import { useTranslation } from 'react-i18next';
import type { ColorValue } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

type IoniconName = ComponentProps<typeof Ionicons>['name'];
type IconColor = ComponentProps<typeof Ionicons>['color'];

/** The tab bar forwards our string tint tokens; numeric (processed) colours never occur. */
function toIconColor(color: ColorValue): IconColor {
  return typeof color === 'number' ? undefined : (color ?? undefined);
}

function tabIcon(name: IoniconName) {
  function TabIcon({ color, size }: { color: ColorValue; size: number }) {
    return <Ionicons name={name} color={toIconColor(color)} size={size} accessible={false} />;
  }
  return TabIcon;
}

/** Primary navigation (docs/03 §2): five tabs, everything else is contextual. */
export default function TabsLayout() {
  const { t } = useTranslation();
  const theme = useAppTheme();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.colors.tabBarActive,
        tabBarInactiveTintColor: theme.colors.tabBarInactive,
        tabBarStyle: {
          backgroundColor: theme.colors.tabBarBackground,
          borderTopColor: theme.colors.divider,
          minHeight: theme.minTouchTarget + theme.spacing[4],
        },
        tabBarLabelStyle: { fontSize: theme.typography.caption.fontSize },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: t('tabs.home'), tabBarIcon: tabIcon('home-outline') }}
      />
      <Tabs.Screen
        name="explore"
        options={{ title: t('tabs.explore'), tabBarIcon: tabIcon('compass-outline') }}
      />
      <Tabs.Screen
        name="companions"
        options={{ title: t('tabs.companions'), tabBarIcon: tabIcon('people-outline') }}
      />
      <Tabs.Screen
        name="messages"
        options={{ title: t('tabs.messages'), tabBarIcon: tabIcon('chatbubbles-outline') }}
      />
      <Tabs.Screen
        name="profile"
        options={{ title: t('tabs.profile'), tabBarIcon: tabIcon('person-circle-outline') }}
      />
    </Tabs>
  );
}
