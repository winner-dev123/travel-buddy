import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import type { ComponentProps } from 'react';
import { useTranslation } from 'react-i18next';
import { StyleSheet, type ColorValue } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

type IoniconName = ComponentProps<typeof Ionicons>['name'];
type IconColor = ComponentProps<typeof Ionicons>['color'];

/** The tab bar forwards our string tint tokens; numeric (processed) colours never occur. */
function toIconColor(color: ColorValue): IconColor {
  return typeof color === 'number' ? undefined : (color ?? undefined);
}

/** The current tab shows the filled glyph, the others the outline: shape as well as colour. */
function tabIcon(active: IoniconName, idle: IoniconName) {
  function TabIcon({ color, focused }: { color: ColorValue; focused: boolean }) {
    return (
      <Ionicons
        name={focused ? active : idle}
        color={toIconColor(color)}
        size={23}
        accessible={false}
      />
    );
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
          borderTopWidth: StyleSheet.hairlineWidth,
          minHeight: theme.minTouchTarget + theme.spacing[5],
          paddingTop: theme.spacing[1],
        },
        // Five labels share a 360dp bar: no side padding, so "Companions" is not cut short.
        tabBarItemStyle: { paddingHorizontal: 0 },
        tabBarLabelStyle: {
          fontFamily: theme.fonts.semibold,
          fontSize: 10,
          letterSpacing: 0,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: t('tabs.home'), tabBarIcon: tabIcon('home', 'home-outline') }}
      />
      <Tabs.Screen
        name="explore"
        options={{ title: t('tabs.explore'), tabBarIcon: tabIcon('compass', 'compass-outline') }}
      />
      <Tabs.Screen
        name="companions"
        options={{ title: t('tabs.companions'), tabBarIcon: tabIcon('people', 'people-outline') }}
      />
      <Tabs.Screen
        name="messages"
        options={{
          title: t('tabs.messages'),
          tabBarIcon: tabIcon('chatbubbles', 'chatbubbles-outline'),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: t('tabs.profile'),
          tabBarIcon: tabIcon('person-circle', 'person-circle-outline'),
        }}
      />
    </Tabs>
  );
}
