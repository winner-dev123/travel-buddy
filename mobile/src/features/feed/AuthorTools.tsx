import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import { deletePost, feedKeys, updatePost } from '@/features/feed/api';
import type { Post } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

const VISIBILITIES = ['public', 'followers', 'private'] as const;
type EditableVisibility = (typeof VISIBILITIES)[number];

/** The author's own controls on a story (POST-003): edit the text and audience, or delete it. */
export function AuthorTools({ post }: { post: Post }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(post.body ?? '');
  const [visibility, setVisibility] = useState<EditableVisibility>(
    (VISIBILITIES as readonly string[]).includes(post.visibility)
      ? (post.visibility as EditableVisibility)
      : 'public',
  );
  const save = useMutation({
    mutationFn: () =>
      updatePost(getApiClient(), post.id, {
        ...(body.trim() !== (post.body ?? '') ? { body: body.trim() } : {}),
        ...(visibility !== post.visibility ? { visibility } : {}),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(feedKeys.post(post.id), updated);
      void queryClient.invalidateQueries({ queryKey: feedKeys.all });
      setEditing(false);
    },
  });
  const remove = useMutation({
    mutationFn: () => deletePost(getApiClient(), post.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: feedKeys.all });
      router.back();
    },
  });
  const changed = body.trim() !== (post.body ?? '') || visibility !== post.visibility;
  const mayBeEmpty = post.media.length > 0; // text is optional only with photos
  const confirmDelete = () =>
    Alert.alert(t('authorTools.deleteTitle'), t('authorTools.deleteBody'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('authorTools.delete'), style: 'destructive', onPress: () => remove.mutate() },
    ]);

  if (!editing) {
    return (
      <View style={styles.row}>
        <View style={styles.fill}>
          <Button
            label={t('authorTools.edit')}
            variant="secondary"
            onPress={() => setEditing(true)}
            testID="post-edit"
          />
        </View>
        <View style={styles.fill}>
          <Button
            label={t('authorTools.delete')}
            variant="secondary"
            onPress={confirmDelete}
            busy={remove.isPending}
            testID="post-delete"
          />
        </View>
        {remove.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
      </View>
    );
  }
  return (
    <View style={{ gap: theme.spacing[2] }} testID="post-editor">
      <TextField
        label={t('compose.body')}
        value={body}
        onChangeText={setBody}
        multiline
        maxLength={5000}
        testID="post-edit-body"
      />
      <View style={styles.chips} accessibilityRole="radiogroup">
        {VISIBILITIES.map((value) => {
          const selected = visibility === value;
          return (
            <Pressable
              key={value}
              onPress={() => setVisibility(value)}
              accessibilityRole="radio"
              accessibilityState={{ selected }}
              style={[
                styles.chip,
                {
                  borderColor: selected ? theme.colors.primary : theme.colors.divider,
                  backgroundColor: selected ? theme.colors.primary : 'transparent',
                },
              ]}
              testID={`post-edit-visibility-${value}`}
            >
              <Text
                style={[
                  theme.typography.label,
                  { color: selected ? theme.colors.onPrimary : theme.colors.textPrimary },
                ]}
              >
                {t(`compose.visibility.${value}`)}
              </Text>
            </Pressable>
          );
        })}
      </View>
      {save.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
      <View style={styles.row}>
        <View style={styles.fill}>
          <Button
            label={t('authorTools.save')}
            onPress={() => save.mutate()}
            disabled={!changed || (!mayBeEmpty && body.trim().length === 0)}
            busy={save.isPending}
            testID="post-edit-save"
          />
        </View>
        <View style={styles.fill}>
          <Button
            label={t('common.cancel')}
            variant="secondary"
            onPress={() => setEditing(false)}
            testID="post-edit-cancel"
          />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', gap: 12, flexWrap: 'wrap' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
